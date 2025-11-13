import os
import datetime
import requests
import yfinance as yf

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

TICKERS = {
    "IONQ": 56.2,
    "FLY": 24.635,
    "LUNR": 9.23
}

# -------- Market News (General) -------- #
def get_market_news():
    try:
        url = "https://api.marketaux.com/v1/news/all?countries=us&limit=10&api_token=demo"
        r = requests.get(url, timeout=10).json()
        news_items = r.get("data", [])
        headlines = []

        for n in news_items[:5]:
            title = n.get("title", "")
            if any(x in title.lower() for x in ["fed", "inflation", "cpi", "interest", "ai", "tech", "spacex", "economy"]):
                headlines.append(f"- {title}")

        if not headlines:
            return "- ไม่มีข่าวสำคัญที่มีผลต่อตลาด"
        return "\n".join(headlines)
    except:
        return "- ไม่พบข้อมูลข่าวตลาด"


# -------- Price + Change -------- #
def get_price(ticker):
    try:
        d = yf.Ticker(ticker).history(period="5d")
        if d.empty:
            return None
        price = float(d["Close"][-1])
        prev = float(d["Close"][-2]) if len(d["Close"]) > 1 else price
        pct = (price - prev) / prev * 100 if prev else 0
        return price, round(pct, 2)
    except:
        return None


# -------- Stock-specific news -------- #
def get_stock_news(keyword):
    try:
        url = f"https://api.marketaux.com/v1/news/all?search={keyword}&limit=5&api_token=demo"
        r = requests.get(url, timeout=10).json()
        news_items = r.get("data", [])
        headlines = []

        for n in news_items[:3]:
            title = n.get("title", "")
            headlines.append(f"- {title}")

        if not headlines:
            return "- ไม่มีข่าวสำคัญ"
        return "\n".join(headlines)
    except:
        return "- ไม่พบข้อมูลข่าว"


# -------- Build message -------- #
def build_message():

    now = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
    msg = f"📅 รายงานประจำวันที่ {now:%Y-%m-%d} (08:00 TH)\n\n"

    # Market snapshot
    try:
        sp = yf.Ticker("^GSPC").history(period="1d")["Close"][-1]
        nd = yf.Ticker("^IXIC").history(period="1d")["Close"][-1]
        dj = yf.Ticker("^DJI").history(period="1d")["Close"][-1]
        msg += f"🌎 ตลาดเมื่อคืน\nS&P500 {round(sp,2)} | Nasdaq {round(nd,2)} | Dow {round(dj,2)}\n\n"
    except:
        msg += "🌎 ตลาดเมื่อคืน: ไม่พบข้อมูล\n\n"

    # Market news
    msg += "📰 ข่าวสำคัญที่มีผลต่อตลาด:\n"
    msg += get_market_news() + "\n\n"

    # Portfolio
    msg += "━━━━━━━━━━━━━━\n"
    msg += "📌 สถานะหุ้นในพอร์ต\n"

    for t, avg in TICKERS.items():
        info = get_price(t)
        if not info:
            msg += f"{t}: ไม่มีข้อมูลราคา\n"
            continue

        price, pct = info
        msg += f"\n🔹 {t} — ${price:.2f} ({pct:+.2f}%)\n"
        msg += f"avg: ${avg}\n"

        # Reasons & signals
        if t == "IONQ":
            if price < 50:
                msg += "คำแนะนำ: สะสมเพิ่มเมื่อ < 50\n"
        if t == "FLY":
            if price < 20:
                msg += "คำแนะนำ: สะสมเพิ่มเมื่อ < 20\n"
        if t == "LUNR":
            if price <= 9.5:
                msg += "คำแนะนำ: ซื้อเพิ่มเมื่อ ≤ 9.5\n"

        # Stock news
        msg += "ข่าวของหุ้นนี้:\n"
        msg += get_stock_news(t) + "\n"

    return msg


# -------- Send -------- #
def send(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": text})
    return r.status_code == 200


# -------- Main -------- #
def main():
    msg = build_message()
    print(msg)  # For GitHub logs
    send(msg)


if __name__ == "__main__":
    main()