# realtime_check.py
import os, json, time, requests, datetime, subprocess
import yfinance as yf

# ---------- CONFIG ----------
THRESHOLDS = {
    "IONQ": 50.0,   # golden timing threshold
    "FLY": 20.0,
    "LUNR": 9.5
}
TICKERS = list(THRESHOLDS.keys())
STATUS_FILE = "alerts_status.json"
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
MARKETAUX_TOKEN = "demo"   # demo token (free) - change if you have key
# ----------------------------

def load_status():
    if not os.path.exists(STATUS_FILE):
        return {"price_alerts": {}, "news_ids": []}
    with open(STATUS_FILE, "r") as f:
        return json.load(f)

def save_status(status):
    with open(STATUS_FILE, "w") as f:
        json.dump(status, f, indent=2)

def get_price(ticker):
    try:
        d = yf.Ticker(ticker).history(period="2d")
        if d.empty:
            return None
        p = float(d['Close'][-1])
        prev = float(d['Close'][-2]) if len(d['Close'])>1 else p
        pct = (p-prev)/prev*100 if prev!=0 else 0.0
        return {"price": round(p,4), "pct": round(pct,2)}
    except Exception as e:
        print("price err", ticker, e)
        return None

def get_news_for(ticker):
    try:
        url = f"https://api.marketaux.com/v1/news/all?search={ticker}&countries=us&limit=5&api_token={MARKETAUX_TOKEN}"
        r = requests.get(url, timeout=10).json()
        return r.get("data", [])
    except Exception as e:
        print("news err", e)
        return []

def send_telegram(text):
    if not TOKEN or not CHAT_ID:
        print("Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID")
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    try:
        r = requests.post(url, data=payload, timeout=15)
        print("tg status", r.status_code)
        try:
            print("tg resp", r.json())
        except:
            print("tg text", r.text)
        return r.status_code == 200
    except Exception as e:
        print("tg send err", e)
        return False

def git_commit_push(filename, commit_msg="Update alerts status"):
    # Use GITHUB_TOKEN-based auth via actions runner; ensure git config set in workflow
    try:
        subprocess.run(["git", "config", "--global", "user.email", "actions@github.com"], check=True)
        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "add", filename], check=True)
        subprocess.run(["git", "commit", "-m", commit_msg], check=True)
        # push using token already available in env (GITHUB_TOKEN) via remote origin
        subprocess.run(["git", "push"], check=True)
        return True
    except subprocess.CalledProcessError as e:
        print("git push error", e)
        return False

def main():
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
    status = load_status()
    updated = False

    # PRICE ALERTS
    for t in TICKERS:
        info = get_price(t)
        if not info:
            continue
        p = info["price"]
        pct = info["pct"]
        sent = status.get("price_alerts", {}).get(t, False)
        threshold = THRESHOLDS[t]
        # trigger when price <= threshold AND not yet sent
        if p <= threshold and not sent:
            text = f"⚡️ PRICE ALERT: {t} reached golden timing ${p:.2f} (threshold {threshold}) at {now:%Y-%m-%d %H:%M} TH\nChange {pct:+.2f}%\n"
            send_telegram(text)
            status.setdefault("price_alerts", {})[t] = True
            updated = True
        # if price back above threshold, reset sent flag (so future crossing triggers again)
        if p > threshold and sent:
            status.setdefault("price_alerts", {})[t] = False
            updated = True

    # NEWS ALERTS (new articles)
    for t in TICKERS:
        articles = get_news_for(t)
        seen = set(status.get("news_ids", []))
        for a in articles:
            aid = a.get("id") or (a.get("url") or a.get("title"))
            if not aid:
                continue
            if aid in seen:
                continue
            # basic filter: relevant keywords present in title
            title = a.get("title","")
            url = a.get("url","")
            # only alert if title seems significant (length > 30 or contains key words)
            if len(title) > 30 or any(k in title.lower() for k in ["contract","launch","earnings","acquir","nasa","defense","investor","partnership","agreement","merger","acquisition","delay","failure","success"]):
                text = f"🗞 NEWS ALERT ({t}): {title}\n{url}"
                send_telegram(text)
            # mark as seen regardless to avoid repeated noisy alerts
            seen.add(aid)
            updated = True
        status["news_ids"] = list(seen)

    # DAILY PORTFOLIO SNAPSHOT at each run (optional short)
    # We will send a short snapshot every hour to avoid spam (check minute==00)
    if datetime.datetime.utcnow().minute == 0:  # send hourly snapshot at top of hour (UTC)
        snap = f"📊 Snapshot {now:%Y-%m-%d %H:%M} TH\n"
        for t in TICKERS:
            info = get_price(t)
            if not info:
                snap += f"{t}: no data\n"
            else:
                snap += f"{t}: ${info['price']:.2f} ({info['pct']:+.2f}%)\n"
        send_telegram(snap)

    if updated:
        save_status(status)
        git_commit_push(STATUS_FILE, commit_msg=f"Auto-update alerts_status at {now:%Y-%m-%d %H:%M}")

if __name__ == "__main__":
    main()