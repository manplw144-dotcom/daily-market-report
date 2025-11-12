# daily_report.py
import os
import datetime
import requests
import yfinance as yf

# --- config ---
TICKERS = {"IONQ":56.2,"FLY":24.635,"LUNR":9.23}
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
# ----------------

def get_price(ticker):
    try:
        t = yf.Ticker(ticker)
        d = t.history(period="5d")
        if d.empty:
            return None
        p = float(d['Close'][-1])
        prev = float(d['Close'][-2]) if len(d['Close'])>1 else p
        ch = p - prev
        pct = (ch / prev * 100) if prev != 0 else 0.0
        return p, round(pct,2)
    except Exception:
        return None

def build_message():
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
    header = f"📅 รายงานตลาดประจำวันที่ {now:%Y-%m-%d %H:%M} (TH)\n\n"
    body = ""
    # market snapshot
    try:
        sp = yf.Ticker("^GSPC").history(period="1d")['Close'][-1]
        nd = yf.Ticker("^IXIC").history(period="1d")['Close'][-1]
        dj = yf.Ticker("^DJI").history(period="1d")['Close'][-1]
        body += f"📈 Market Snapshot: S&P500 {round(sp,2)} | Nasdaq {round(nd,2)} | Dow {round(dj,2)}\n\n"
    except:
        body += "📈 Market Snapshot: (no data)\n\n"

    body += "🔎 พอร์ตของคุณ:\n"
    for t,avg in TICKERS.items():
        info = get_price(t)
        if not info:
            body += f"{t}: (no data)\n"
            continue
        price, pct = info
        action = "ถือ"
        if t=="LUNR" and price <= 9.5:
            action = "ซื้อเพิ่ม (zone 8.5-9.5)"
        if t=="FLY" and price <= 20:
            action = "ซื้อเพิ่ม (zone 18.5-20)"
        if t=="IONQ" and price <= 50:
            action = "ซื้อเพิ่ม (<50)"
        body += f"{t}: ${price:.2f} ({pct:+.2f}%) | avg ${avg} → {action}\n"
    summary = ("\n📌 สรุปคำแนะนำรวม:\n"
               "- LUNR: เน้นสะสมในโซน 8.5–9.5\n"
               "- FLY: สะสมเมื่อ < 20\n"
               "- IONQ: สะสมเมื่อ < 50\n")
    return header + body + summary

def send_telegram(text):
    if not TOKEN or not CHAT_ID:
        print("Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID")
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    try:
        r = requests.post(url, data=payload, timeout=15)
        return r.status_code == 200
    except Exception as e:
        print("send error", e)
        return False

def main():
    msg = build_message()
    ok = send_telegram(msg)
    if ok:
        print("Message sent")
    else:
        print("Failed to send")

if __name__ == "__main__":
    main()
