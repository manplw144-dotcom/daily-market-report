# daily_report.py
# Enhanced Daily Market + Portfolio report
# - price from yfinance
# - market news (Marketaux demo)
# - improved Yahoo news scraper/keyword search for earnings/Qn/press
# - sends message to Telegram (env: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)
# Requirements: pip install yfinance requests

import os
import re
from html import unescape
import datetime
import requests
import yfinance as yf

# ---------------- CONFIG ----------------
TICKERS = {
    "IONQ": 56.2,
    "FLY": 24.635,
    "LUNR": 9.23
}
MARKETAUX_TOKEN = "demo"   # demo token; replace if you have a key
# ----------------------------------------

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


# --- Helpers: prices ---
def get_price(ticker):
    try:
        t = yf.Ticker(ticker)
        d = t.history(period="5d")
        if d.empty:
            return None
        last = float(d['Close'][-1])
        prev = float(d['Close'][-2]) if len(d['Close']) > 1 else last
        ch = last - prev
        pct = (ch / prev * 100) if prev != 0 else 0.0
        return {"price": round(last, 4), "change": round(ch, 4), "pct": round(pct, 2)}
    except Exception as e:
        print(f"price err {ticker}:", e)
        return None


# --- Market-level news (general) using Marketaux demo (best-effort) ---
def get_market_news():
    try:
        url = f"https://api.marketaux.com/v1/news/all?countries=us&limit=15&api_token={MARKETAUX_TOKEN}"
        r = requests.get(url, timeout=10).json()
        items = r.get("data", [])
        headlines = []
        for n in items:
            title = n.get("title", "") or ""
            lower = title.lower()
            if any(k in lower for k in ["fed", "cpi", "inflation", "interest", "recession", "jobs", "unemployment", "gdp", "debt ceiling", "shutdown", "earnings", "bank", "rate cut", "rate hike", "ai", "semiconductor", "defense", "nasa"]):
                headlines.append(f"- {title} ({n.get('source', {}).get('name','')})")
            if len(headlines) >= 5:
                break
        if not headlines:
            return "- ไม่มีข่าวสำคัญที่มีผลต่อตลาด"
        return "\n".join(headlines)
    except Exception as e:
        print("market news err:", e)
        return "- ไม่พบข้อมูลข่าวตลาด"


# --- Improved Yahoo news scraper + keyword search (earnings/press/guidance) ---
def get_yahoo_news_improved(ticker):
    """
    Improved: search by ticker and by company keywords, scrape Yahoo quote news page,
    and filter for earnings/Qn/press/guidance/contract/launch keywords.
    Returns up to 6 relevant headlines.
    """
    headlines = []
    try:
        # 1) Yahoo search endpoint
        url_search = f"https://query1.finance.yahoo.com/v1/finance/search?q={ticker}"
        r = requests.get(url_search, timeout=8)
        js = r.json() if r.status_code == 200 else {}
        news = js.get("news", []) or []
        for n in news:
            title = (n.get("title") or "").strip()
            if not title:
                continue
            low = title.lower()
            if any(k in low for k in ["earnings", "q3", "q4", "quarter", "result", "guidance", "press release", "acquir", "acquisition", "contract", "launch", "mission", "nasa", "defense", "scitec", "sci tec", "firefly"]):
                headlines.append(f"- {title} ({n.get('publisher') or n.get('source','')})")
            if len(headlines) >= 6:
                break

        # 2) Scrape Yahoo news page for the ticker
        if len(headlines) < 6:
            try:
                url_news_page = f"https://finance.yahoo.com/quote/{ticker}/news?p={ticker}"
                r2 = requests.get(url_news_page, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
                if r2.status_code == 200:
                    text = r2.text
                    found = re.findall(r'<h3.*?>(.*?)</h3>', text, flags=re.S | re.I)
                    for f in found:
                        title = re.sub(r'<.*?>', '', f).strip()
                        title = unescape(title)
                        low = title.lower()
                        if title and any(k in low for k in ["earnings", "q3", "q4", "quarter", "result", "guidance", "press release", "contract", "launch", "mission", "scitec", "firefly", "sci tec"]):
                            entry = f"- {title} (Yahoo)"
                            if entry not in headlines:
                                headlines.append(entry)
                        if len(headlines) >= 6:
                            break
            except Exception:
                pass

        # 3) Search by company keywords for broader coverage
        if len(headlines) < 6:
            keywords = [ticker, "Firefly Aerospace", "SciTec", "Firefly", "Firefly SciTec", "Sci Tec"]
            for kw in keywords:
                try:
                    url_kw = f"https://query1.finance.yahoo.com/v1/finance/search?q={requests.utils.requote_uri(kw)}"
                    r3 = requests.get(url_kw, timeout=6)
                    j3 = r3.json() if r3.status_code == 200 else {}
                    news3 = j3.get("news", []) or []
                    for n in news3:
                        title = (n.get("title") or "").strip()
                        if not title:
                            continue
                        low = title.lower()
                        if any(k in low for k in ["earnings", "q3", "q4", "quarter", "result", "guidance", "press release", "acquir", "contract", "launch", "mission", "scitec"]):
                            entry = f"- {title} ({n.get('publisher') or n.get('source','')})"
                            if entry not in headlines:
                                headlines.append(entry)
                        if len(headlines) >= 6:
                            break
                except Exception:
                    continue
                if len(headlines) >= 6:
                    break

    except Exception as e:
        print("get_yahoo_news_improved err:", e)

    # fallback: if still empty, return up to 3 recent headlines from initial search
    if not headlines:
        try:
            if news:
                for n in news[:3]:
                    title = n.get("title", "")
                    if title:
                        headlines.append(f"- {title} ({n.get('publisher') or n.get('source','')})")
        except Exception:
            pass

    if not headlines:
        return "- ไม่มีข้อมูลข่าว"
    # dedupe & limit
    uniq = []
    for h in headlines:
        if h not in uniq:
            uniq.append(h)
        if len(uniq) >= 6:
            break
    return "\n".join(uniq)


# --- Simple decision rules (customize as needed) ---
def decision_rule(ticker, price, avg_cost):
    if price is None:
        return "No data"
    if ticker == "LUNR":
        if price <= 9.5:
            return "Buy (DCA zone 8.5-9.5)"
        elif price > 12:
            return "Hold / consider trimming on strong run"
    if ticker == "FLY":
        if price <= 20:
            return "Buy (zone 18.5-20)"
        elif price > 30:
            return "Hold / consider trim"
    if ticker == "IONQ":
        if price <= 50:
            return "Buy (accumulate < 50)"
        elif price > 56:
            return "Hold / avoid adding (high valuation)"
    if avg_cost and price < avg_cost * 0.9:
        return "Consider adding (below your avg cost)"
    return "Hold"


# --- Build message ---
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
        print("market snapshot err", e)
        market_part = "🌎 ตลาดเมื่อคืน: (no data)\n\n"

    # Market news
    market_news = "📰 ข่าวสำคัญที่มีผลต่อตลาด:\n" + get_market_news() + "\n\n"

    # Portfolio section
    portfolio = "━━━━━━━━━━━━━━\n📌 สถานะหุ้นในพอร์ต\n"
    for t, avg in TICKERS.items():
        info = get_price(t)
        portfolio += f"\n🔹 {t}"
        if info:
            portfolio += f" — ${info['price']:.2f} ({info['pct']:+.2f}%)\n"
            portfolio += f"avg: ${avg}\n"
            rec = decision_rule(t, info['price'], avg)
            portfolio += f"คำแนะนำ: {rec}\n"
        else:
            portfolio += " — (no price data)\n"

        # stock-specific news via improved Yahoo function
        portfolio += "ข่าวของหุ้นนี้:\n"
        portfolio += get_yahoo_news_improved(t) + "\n"

    summary = ("\n📌 สรุปคำแนะนำรวม:\n"
               "- LUNR: เน้นสะสมในโซน 8.5–9.5\n"
               "- FLY: สะสมเมื่อ < 20\n"
               "- IONQ: สะสมเมื่อ < 50\n")

    return header + market_part + market_news + portfolio + summary


# --- Send to Telegram ---
def send_telegram(message):
    if not TOKEN or not CHAT_ID:
        print("Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID")
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        r = requests.post(url, data=payload, timeout=15)
        print("Telegram status:", r.status_code)
        try:
            print("Telegram response:", r.json())
        except:
            print("Telegram text response:", r.text)
        return r.status_code == 200
    except Exception as e:
        print("tg send error:", e)
        return False


# --- Main ---
def main():
    msg = build_message()
    print(msg)  # for Actions log
    ok = send_telegram(msg)
    if ok:
        print("Message sent")
    else:
        print("Failed to send message")


if __name__ == "__main__":
    main()