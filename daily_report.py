# daily_report.py
# Enhanced Daily Market + Portfolio report (with English->Thai translation)
# Requirements: yfinance, requests
# Env vars: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

import os
import re
from html import unescape
import datetime
import requests
import yfinance as yf
import urllib.parse
import time

# ---------- CONFIG ----------
TICKERS = {
    "IONQ": 56.2,
    "FLY": 24.635,
    "LUNR": 9.23
}
MARKETAUX_TOKEN = "demo"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
# --------------------------------

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def log(s):
    print(f"[DEBUG] {s}")

# --- Translation helper: English -> Thai (uses public translate endpoint) ---
def translate_to_th(text):
    """
    Translate given English text to Thai using unofficial Google translate endpoint.
    Returns Thai text on success, otherwise returns original text.
    """
    if not text or text.strip() == "":
        return text
    try:
        # batch small pieces to avoid very long URLs; handle up to ~2000 chars
        q = str(text)
        # encode
        q_enc = urllib.parse.quote(q)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=th&dt=t&q={q_enc}"
        r = requests.get(url, timeout=10, headers=HEADERS)
        if r.status_code != 200:
            log(f"translate status {r.status_code}")
            return text
        resp = r.json()
        # resp is list of sentences -> join
        translated = []
        for part in resp[0]:
            if len(part) > 0:
                translated.append(part[0])
        result = "".join(translated)
        # minor cleanup
        result = result.replace("  ", " ").strip()
        # limit length
        if len(result) > 4000:
            result = result[:4000] + "..."
        # small delay to be polite
        time.sleep(0.1)
        return result
    except Exception as e:
        log(f"translate err: {e}")
        return text

# --- Prices ---
def get_price(ticker):
    try:
        t = yf.Ticker(ticker)
        d = t.history(period="5d")
        if d.empty:
            log(f"price: no data for {ticker}")
            return None
        last = float(d['Close'][-1])
        prev = float(d['Close'][-2]) if len(d['Close']) > 1 else last
        pct = (last - prev) / prev * 100 if prev != 0 else 0.0
        return {"price": round(last, 4), "pct": round(pct, 2)}
    except Exception as e:
        log(f"price err {ticker}: {e}")
        return None

# --- Market news (Marketaux -> Yahoo fallback) ---
def get_market_news():
    headlines = []
    used_source = None
    try:
        url = f"https://api.marketaux.com/v1/news/all?countries=us&limit=20&api_token={MARKETAUX_TOKEN}"
        r = requests.get(url, timeout=8, headers=HEADERS)
        if r.status_code == 200:
            j = r.json()
            items = j.get("data",[]) or []
            for n in items:
                title = n.get("title","") or ""
                lower = title.lower()
                if any(k in lower for k in ["fed","cpi","inflation","interest","recession","jobs","gdp","earnings","ai","semiconductor","defense","nasa"]):
                    headlines.append(f"- {title} ({n.get('source',{}).get('name','')})")
                    if len(headlines) >= 6:
                        break
            if headlines:
                used_source = "Marketaux"
    except Exception as e:
        log(f"marketaux err: {e}")

    if not headlines:
        try:
            url2 = "https://finance.yahoo.com/news"
            r2 = requests.get(url2, timeout=10, headers=HEADERS)
            if r2.status_code == 200:
                text = r2.text
                found = re.findall(r'<h3.*?>(.*?)</h3>', text, flags=re.S|re.I)
                for f in found:
                    title = re.sub(r'<.*?>','', f).strip()
                    title = unescape(title)
                    if not title: continue
                    low = title.lower()
                    if any(k in low for k in ["fed","cpi","inflation","interest","recession","jobs","gdp","earnings","ai","semiconductor","defense","nasa"]):
                        entry = f"- {title} (Yahoo News)"
                        if entry not in headlines:
                            headlines.append(entry)
                    if len(headlines) >= 6:
                        break
                if headlines:
                    used_source = "YahooNewsPage"
        except Exception as e:
            log(f"yahoo news page err: {e}")

    if not headlines:
        return {"headlines": ["- ไม่มีข่าวสำคัญที่มีผลต่อตลาด"], "source": used_source or "none"}
    return {"headlines": headlines, "source": used_source or "unknown"}

# --- Stock news (improved) ---
def get_stock_news(ticker, extra_keywords=None):
    headlines = []
    used_sources = []
    extra_keywords = extra_keywords or []
    keywords = ["earnings","q3","q4","quarter","result","guidance","press release","contract","launch","mission","nasa","defense","acquir","acquisition","scitec","sci tec"] + [k.lower() for k in extra_keywords]

    # Yahoo search endpoint
    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={ticker}"
        r = requests.get(url, timeout=8, headers=HEADERS)
        if r.status_code == 200:
            j = r.json()
            news = j.get("news",[]) or []
            for n in news:
                title = (n.get("title") or "").strip()
                if not title: continue
                low = title.lower()
                if any(k in low for k in keywords):
                    entry = f"- {title} ({n.get('publisher') or n.get('source','')})"
                    if entry not in headlines:
                        headlines.append(entry)
                if len(headlines) >= 6:
                    break
            if headlines:
                used_sources.append("YahooSearch")
    except Exception as e:
        log(f"yahoo search err for {ticker}: {e}")

    # scrape quote news page
    if len(headlines) < 6:
        try:
            url_news = f"https://finance.yahoo.com/quote/{ticker}/news?p={ticker}"
            r2 = requests.get(url_news, timeout=8, headers=HEADERS)
            if r2.status_code == 200:
                text = r2.text
                found = re.findall(r'<h3.*?>(.*?)</h3>', text, flags=re.S|re.I)
                for f in found:
                    title = re.sub(r'<.*?>','', f).strip()
                    title = unescape(title)
                    low = title.lower()
                    if any(k in low for k in keywords) or any(w.lower() in title.lower() for w in [ticker] + extra_keywords):
                        entry = f"- {title} (Yahoo)"
                        if entry not in headlines:
                            headlines.append(entry)
                    if len(headlines) >= 6:
                        break
                if headlines:
                    used_sources.append("YahooQuoteNews")
        except Exception as e:
            log(f"yahoo quote news err for {ticker}: {e}")

    # press releases page
    if len(headlines) < 6:
        try:
            url_pr = f"https://finance.yahoo.com/quote/{ticker}/press-releases?p={ticker}"
            r3 = requests.get(url_pr, timeout=8, headers=HEADERS)
            if r3.status_code == 200:
                text = r3.text
                found = re.findall(r'<h3.*?>(.*?)</h3>', text, flags=re.S|re.I)
                for f in found:
                    title = re.sub(r'<.*?>','', f).strip()
                    title = unescape(title)
                    low = title.lower()
                    if any(k in low for k in keywords) or any(w.lower() in title.lower() for w in [ticker] + extra_keywords):
                        entry = f"- {title} (Yahoo PR)"
                        if entry not in headlines:
                            headlines.append(entry)
                    if len(headlines) >= 6:
                        break
                if headlines:
                    used_sources.append("YahooPR")
        except Exception as e:
            log(f"yahoo pr err for {ticker}: {e}")

    # alias search
    if len(headlines) < 6:
        comp_aliases = [ticker]
        if ticker == "FLY":
            comp_aliases += ["Firefly Aerospace", "Firefly"]
        if ticker == "LUNR":
            comp_aliases += ["Intuitive Machines", "LUNR"]
        if ticker == "IONQ":
            comp_aliases += ["IonQ", "IonQ Inc"]
        for alias in comp_aliases:
            if len(headlines) >= 6:
                break
            try:
                url_a = f"https://query1.finance.yahoo.com/v1/finance/search?q={requests.utils.requote_uri(alias)}"
                r4 = requests.get(url_a, timeout=6, headers=HEADERS)
                if r4.status_code == 200:
                    j4 = r4.json()
                    news4 = j4.get("news",[]) or []
                    for n in news4:
                        title = (n.get("title") or "").strip()
                        if not title: continue
                        low = title.lower()
                        if any(k in low for k in keywords):
                            entry = f"- {title} ({n.get('publisher') or n.get('source','')})"
                            if entry not in headlines:
                                headlines.append(entry)
                        if len(headlines) >= 6:
                            break
                    if news4:
                        used_sources.append(f"YahooAlias:{alias}")
            except Exception as e:
                log(f"alias search err {alias}: {e}")

    if not headlines:
        return {"headlines": ["- ไม่มีข้อมูลข่าว"], "source": ",".join(used_sources) if used_sources else "none"}
    return {"headlines": headlines[:6], "source": ",".join(used_sources)}

# --- Decision rules ---
def decision_rule(ticker, price, avg_cost):
    if price is None:
        return "No data"
    if ticker == "LUNR":
        if price <= 9.5:
            return "Buy (DCA zone 8.5-9.5)"
        elif price > 12:
            return "Hold / consider trimming"
    if ticker == "FLY":
        if price <= 20:
            return "Buy (zone 18.5-20)"
        elif price > 30:
            return "Hold / consider trim"
    if ticker == "IONQ":
        if price <= 50:
            return "Buy (accumulate < 50)"
        elif price > 56:
            return "Hold / avoid adding"
    if avg_cost and price < avg_cost * 0.9:
        return "Consider adding (below your avg cost)"
    return "Hold"

# --- Build message (translate headlines to Thai) ---
def build_message():
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
    header = f"📅 รายงานประจำวันที่ {now:%Y-%m-%d} (08:00 TH)\n\n"

    # Market snapshot
    try:
        sp = yf.Ticker("^GSPC").history(period="1d")["Close"][-1]
        nd = yf.Ticker("^IXIC").history(period="1d")["Close"][-1]
        dj = yf.Ticker("^DJI").history(period="1d")["Close"][-1]
        market_part = f"🌎 ตลาดเมื่อคืน\nS&P500 {round(sp,2)} | Nasdaq {round(nd,2)} | Dow {round(dj,2)}\n\n"
    except Exception as e:
        log(f"market snapshot err: {e}")
        market_part = "🌎 ตลาดเมื่อคืน: (no data)\n\n"

    # Market news (and translate)
    mnews = get_market_news()
    market_news = "📰 ข่าวสำคัญที่มีผลต่อตลาด:\n"
    # join original headlines (english), then translate block to thai
    original_market_text = "\n".join(mnews.get("headlines", ["- ไม่มีข่าวสำคัญที่มีผลต่อตลาด"]))
    thai_market = translate_to_th(original_market_text)
    # include translated headlines, and small note about source
    market_news += thai_market + "\n"
    market_news += f"\n(แหล่งข่าว: {mnews.get('source')})\n\n"
    log(f"Market news source: {mnews.get('source')}; headlines_count={len(mnews.get('headlines',[]))}")

    # Portfolio
    portfolio = "━━━━━━━━━━━━━━\n📌 สถานะหุ้นในพอร์ต\n"
    for t, avg in TICKERS.items():
        info = get_price(t)
        portfolio += f"\n🔹 {t}"
        if info:
            portfolio += f" — ${info['price']:.2f} ({info['pct']:+.2f}%)\n"
            portfolio += f"avg: ${avg}\n"
            portfolio += f"คำแนะนำ: {decision_rule(t, info['price'], avg)}\n"
        else:
            portfolio += " — (no price data)\n"

        # stock news: get english headlines then translate
        sn = get_stock_news(t)
        eng_text = "\n".join(sn.get("headlines", ["- ไม่มีข้อมูลข่าว"]))
        thai_text = translate_to_th(eng_text)
        portfolio += "ข่าวของหุ้นนี้ (สรุปภาษาไทย):\n"
        portfolio += thai_text + "\n"
        portfolio += f"(แหล่ง: {sn.get('source')})\n"
        log(f"{t} news source: {sn.get('source')}; headlines_count={len(sn.get('headlines',[]))}")

    summary = ("\n📌 สรุปคำแนะนำรวม:\n"
               "- LUNR: เน้นสะสมในโซน 8.5–9.5\n"
               "- FLY: สะสมเมื่อ < 20\n"
               "- IONQ: สะสมเมื่อ < 50\n")

    return header + market_part + market_news + portfolio + summary

# --- Send to Telegram ---
def send_telegram(message):
    if not TOKEN or not CHAT_ID:
        log("Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID")
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        r = requests.post(url, data=payload, timeout=15)
        log(f"Telegram status: {r.status_code}")
        try:
            log(f"Telegram response: {r.json()}")
        except:
            log(f"Telegram text response: {r.text}")
        return r.status_code == 200
    except Exception as e:
        log(f"tg send error: {e}")
        return False

# --- Main ---
def main():
    log("Starting daily_report.py")
    msg = build_message()
    print(msg)  # visible in Actions log
    ok = send_telegram(msg)
    if ok:
        log("Message sent")
    else:
        log("Failed to send message")

if __name__ == "__main__":
    main()