# daily_report.py
# Improved Daily Report with extractive summarization + Thai translation
# Requirements: yfinance, requests, beautifulsoup4
# Env vars: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID

import os, re, time, datetime, requests, math
from html import unescape
from collections import Counter
from bs4 import BeautifulSoup
import yfinance as yf
import urllib.parse

# -------- CONFIG ----------
TICKERS = {"IONQ":56.2, "FLY":24.635, "LUNR":9.23}
HEADERS = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
MARKETAUX_TOKEN = "demo"
# --------------------------------

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def log(s): print(f"[DEBUG] {s}")

# ---------- UTILITIES ----------
def translate_to_th(text):
    """Translate English text to Thai using public Google translate endpoint (best-effort)."""
    if not text: return text
    try:
        q_enc = urllib.parse.quote(text)
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=th&dt=t&q={q_enc}"
        r = requests.get(url, timeout=12, headers=HEADERS)
        if r.status_code != 200:
            return text
        resp = r.json()
        translated = "".join([part[0] for part in resp[0] if part and part[0]])
        time.sleep(0.08)
        return translated.strip()
    except Exception as e:
        log("translate err "+str(e))
        return text

def fetch_url_text(url):
    """Fetch article URL and extract visible paragraph text (returns combined text)."""
    try:
        r = requests.get(url, timeout=10, headers=HEADERS)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        # Remove script/style, nav, footer
        for tag in soup(["script","style","nav","footer","header","aside","form","noscript"]):
            tag.decompose()
        # Try common article containers
        article_text = []
        # Priority: <article> tags, then main, then <div> with many <p>, then all <p>
        article = soup.find("article")
        if article:
            ps = article.find_all("p")
            for p in ps:
                txt = p.get_text().strip()
                if txt:
                    article_text.append(txt)
        if not article_text:
            main = soup.find("main")
            if main:
                for p in main.find_all("p"):
                    txt = p.get_text().strip()
                    if txt:
                        article_text.append(txt)
        if not article_text:
            # fallback: choose largest div by text length
            divs = soup.find_all("div")
            best = ""
            for d in divs:
                txt = " ".join([p.get_text().strip() for p in d.find_all("p")])
                if len(txt) > len(best):
                    best = txt
            if best:
                # split into paragraphs
                article_text += [t.strip() for t in best.split("\n") if t.strip()]
        if not article_text:
            # final fallback: take all <p>
            for p in soup.find_all("p"):
                txt = p.get_text().strip()
                if txt:
                    article_text.append(txt)
        # join and normalize whitespace
        joined = "\n".join(article_text)
        # minor cleanup
        joined = re.sub(r'\s+', ' ', joined).strip()
        return joined
    except Exception as e:
        log("fetch_url_text err "+str(e))
        return ""

def split_sentences(text):
    """Naive sentence splitter (period/question/exclaim)."""
    if not text: return []
    # Replace abbreviations common in news to avoid split? keep simple
    text = text.replace("\r"," ").replace("\n",". ")
    # split by punctuation marks followed by space and capital letter or digit
    sents = re.split(r'(?<=[\.\?\!])\s+(?=[A-Z0-9"])', text)
    sents = [s.strip() for s in sents if s.strip()]
    return sents

def score_sentences(sentences, important_terms=None):
    """
    Score sentences by term frequency of important words + length heuristic.
    important_terms: list of keywords to weight (e.g., earnings, revenue, acquisition)
    """
    if not sentences: return []
    # normalize words
    words = []
    for s in sentences:
        for w in re.findall(r"\w+", s.lower()):
            words.append(w)
    freq = Counter(words)
    important_terms = [t.lower() for t in (important_terms or [])]
    sent_scores = []
    for s in sentences:
        s_words = re.findall(r"\w+", s.lower())
        if not s_words:
            sent_scores.append((s,0.0))
            continue
        # base score = sum freq of words in sentence
        base = sum(freq[w] for w in s_words)
        # boost if contains important terms
        boost = sum(3 for t in important_terms if t in s.lower())
        # penalize very short sentences
        length_penalty = 0.8 if len(s_words) < 6 else 1.0
        score = base * (1 + boost) * length_penalty
        sent_scores.append((s, score))
    # sort by score desc
    sent_scores.sort(key=lambda x: x[1], reverse=True)
    return sent_scores

def make_extract_summary(text, important_terms=None, max_sentences=3):
    """
    Create extractive summary: select top scored sentences and keep original order.
    """
    if not text:
        return ""
    sents = split_sentences(text)
    if not sents:
        return ""
    scored = score_sentences(sents, important_terms)
    # pick top N candidate sentences
    top = [s for s,sc in scored[:max_sentences*3]]  # take more candidates to preserve order
    # keep only sentences that are in top, but in original order
    summary = []
    for s in sents:
        if s in top and s not in summary:
            summary.append(s)
        if len(summary) >= max_sentences:
            break
    # fallback: if no summary selected, take first N sentences
    if not summary:
        summary = sents[:max_sentences]
    # join
    return " ".join(summary)

# ---------- News pipeline ----------
def get_candidate_articles_from_yahoo(ticker):
    """
    Return list of dicts: {'title', 'url', 'publisher'} from Yahoo search endpoint.
    """
    out = []
    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={urllib.parse.quote(ticker)}"
        r = requests.get(url, timeout=8, headers=HEADERS)
        if r.status_code == 200:
            j = r.json()
            news = j.get("news",[]) or []
            for n in news:
                title = n.get("title") or ""
                urln = n.get("url") or n.get("link") or ""
                publisher = n.get("publisher") or n.get("source") or ""
                if urln:
                    out.append({"title": title, "url": urln, "publisher": publisher})
    except Exception as e:
        log("yahoo search err "+str(e))
    # ensure unique by url
    uniq = []
    res = []
    for a in out:
        if a["url"] not in uniq:
            uniq.append(a["url"])
            res.append(a)
    return res

def summarize_article_from_candidate(candidate, important_terms=None):
    """
    Given candidate {'title','url','publisher'} try to fetch article text and produce summary (EN).
    Returns dict: {'title','url','publisher','summary_en'}
    """
    url = candidate.get("url","")
    title = candidate.get("title","")
    publisher = candidate.get("publisher","")
    # try to fetch article page and extract text
    text = fetch_url_text(url)
    if not text:
        # try to fetch meta description via HEAD or open graph
        try:
            r = requests.get(url, timeout=8, headers=HEADERS)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text,"html.parser")
                desc = ""
                meta = soup.find("meta", attrs={"name":"description"}) or soup.find("meta", property="og:description")
                if meta and meta.get("content"):
                    desc = meta.get("content","")
                text = desc
        except Exception as e:
            log("meta fetch err "+str(e))
    summary_en = ""
    if text:
        # create extractive summary (2-4 sentences depending length)
        max_sents = 3 if len(text.split()) > 200 else 2
        summary_en = make_extract_summary(text, important_terms=important_terms, max_sentences=max_sents)
    # fallback to headline if summary empty
    if not summary_en:
        if title:
            summary_en = title
        else:
            summary_en = "(เนื้อหาไม่สามารถดึงได้)"
    return {"title": title, "url": url, "publisher": publisher, "summary_en": summary_en}

def get_stock_summaries(ticker, extra_keywords=None):
    """Return list of article summaries (EN) for ticker, prioritized to earnings/press/guidance."""
    candidates = get_candidate_articles_from_yahoo(ticker)
    # if not many candidates try alias search
    if len(candidates) < 3:
        aliases = [ticker]
        if ticker == "FLY": aliases += ["Firefly Aerospace","Firefly SciTec","SciTec","Sci Tec"]
        if ticker == "LUNR": aliases += ["Intuitive Machines"]
        if ticker == "IONQ": aliases += ["IonQ", "IonQ Inc"]
        for a in aliases:
            if len(candidates) >= 6: break
            try:
                url = f"https://query1.finance.yahoo.com/v1/finance/search?q={urllib.parse.quote(a)}"
                r = requests.get(url, timeout=6, headers=HEADERS)
                if r.status_code == 200:
                    j = r.json(); news = j.get("news",[]) or []
                    for n in news:
                        urln = n.get("url") or ""
                        title = n.get("title") or ""
                        publisher = n.get("publisher") or n.get("source") or ""
                        if urln and all(urln != c["url"] for c in candidates):
                            candidates.append({"title":title,"url":urln,"publisher":publisher})
            except: pass
    # prioritize candidates whose title contains target keywords
    priority = []
    for c in candidates:
        t = (c.get("title") or "").lower()
        if any(k in t for k in ["earnings","q3","q4","quarter","results","guidance","press","acquir","acquisition","contract","scitec","sci tec","firefly","sci-tec"]):
            priority.insert(0,c)
        else:
            priority.append(c)
    # summarize top 4
    summaries = []
    for c in priority[:6]:
        s = summarize_article_from_candidate(c, important_terms=["earnings","revenue","guidance","contract","acquisition","launch","mission","backlog","profit","loss"])
        summaries.append(s)
    return summaries

# ---------- Build and send report ----------
def decision_rule(ticker, price, avg_cost):
    if price is None: return "No data"
    if ticker=="LUNR":
        if price <= 9.5: return "Buy (DCA zone 8.5-9.5)"
        elif price>12: return "Hold / consider trimming"
    if ticker=="FLY":
        if price <= 20: return "Buy (zone 18.5-20)"
        elif price>30: return "Hold / consider trim"
    if ticker=="IONQ":
        if price <= 50: return "Buy (accumulate < 50)"
        elif price>56: return "Hold / avoid adding"
    return "Hold"

def build_message():
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
    header = f"📅 รายงานประจำวันที่ {now:%Y-%m-%d} (08:00 TH)\n\n"
    # market snapshot
    try:
        sp = yf.Ticker("^GSPC").history(period="1d")["Close"][-1]
        nd = yf.Ticker("^IXIC").history(period="1d")["Close"][-1]
        dj = yf.Ticker("^DJI").history(period="1d")["Close"][-1]
        market_part = f"🌎 ตลาดเมื่อคืน\nS&P500 {round(sp,2)} | Nasdaq {round(nd,2)} | Dow {round(dj,2)}\n\n"
    except: market_part = "🌎 ตลาดเมื่อคืน: (no data)\n\n"

    # market news (try Marketaux then Yahoo)
    mnews = []
    try:
        url = f"https://api.marketaux.com/v1/news/all?countries=us&limit=15&api_token={MARKETAUX_TOKEN}"
        r = requests.get(url, timeout=8, headers=HEADERS)
        if r.status_code==200:
            j = r.json(); items = j.get("data",[]) or []
            for n in items:
                t = n.get("title",""); ifilter = t.lower()
                if any(k in ifilter for k in ["fed","cpi","inflation","interest","recession","gdp","earnings","ai","defense"]):
                    mnews.append({"title":t,"source":n.get("source",{}).get("name","")})
    except Exception as e:
        log("marketaux err "+str(e))
    # fallback Yahoo news page if none
    if not mnews:
        try:
            url2 = "https://finance.yahoo.com/news"
            r2 = requests.get(url2, timeout=8, headers=HEADERS)
            if r2.status_code==200:
                soup = BeautifulSoup(r2.text,"html.parser")
                for h3 in soup.find_all("h3")[:10]:
                    t = h3.get_text().strip()
                    if any(k in t.lower() for k in ["fed","cpi","inflation","interest","recession","gdp","earnings","ai","defense"]):
                        mnews.append({"title":t,"source":"Yahoo News"})
        except Exception as e:
            log("yahoo news page err "+str(e))
    # prepare market text (translate summary)
    if mnews:
        # join headlines and translate as a short block
        eng_block = " | ".join([f"{i['title']}" for i in mnews[:5]])
        th_block = translate_to_th(eng_block)
        market_news_text = th_block
    else:
        market_news_text = "- ไม่มีข่าวสำคัญที่มีผลต่อตลาด"

    # portfolio build
    port = "━━━━━━━━━━━━━━\n📌 สถานะหุ้นในพอร์ต\n"
    for t, avg in TICKERS.items():
        info = None
        try:
            info = yf.Ticker(t).history(period="5d")
            if not info.empty:
                last = float(info['Close'][-1]); prev = float(info['Close'][-2]) if len(info['Close'])>1 else last
                pct = (last-prev)/prev*100 if prev!=0 else 0.0
                price_info = {"price":round(last,4),"pct":round(pct,2)}
            else:
                price_info = None
        except Exception as e:
            price_info = None
        port += f"\n🔹 {t}"
        if price_info:
            port += f" — ${price_info['price']:.2f} ({price_info['pct']:+.2f}%)\n"
            port += f"avg: ${avg}\n"
            port += f"คำแนะนำ: {decision_rule(t, price_info['price'], avg)}\n"
        else:
            port += " — (no price data)\n"

        # get summaries for this ticker
        summaries = get_stock_summaries(t)
        if summaries:
            # build english block of summaries (title + summary)
            eng_sum_blocks = []
            for s in summaries[:3]:
                title = s.get("title") or ""
                summary_en = s.get("summary_en") or ""
                url = s.get("url") or ""
                publisher = s.get("publisher") or ""
                text_block = (title + ". " + summary_en).strip()
                # limit length
                if len(text_block) > 2000:
                    text_block = text_block[:2000]
                eng_sum_blocks.append(text_block + (f" ({publisher})" if publisher else ""))
            eng_combined = "\n\n".join(eng_sum_blocks)
            # translate to Thai
            thai_summary = translate_to_th(eng_combined)
            port += "ข่าวสำคัญ (สรุป):\n"
            port += thai_summary + "\n"
            # include first article link for reference
            first_url = summaries[0].get("url") if summaries and summaries[0].get("url") else ""
            if first_url:
                port += f"🔗 อ่านต้นฉบับ: {first_url}\n"
        else:
            port += "ข่าวของหุ้นนี้: - ไม่มีข้อมูลข่าว\n"

    # final summary
    final = ("\n📌 สรุปคำแนะนำรวม:\n- LUNR: เน้นสะสมในโซน 8.5–9.5\n- FLY: สะสมเมื่อ < 20\n- IONQ: สะสมเมื่อ < 50\n")

    # compose message
    msg = header + market_part + "📰 ข่าวสำคัญที่มีผลต่อตลาด:\n" + market_news_text + "\n\n" + port + final
    return msg

def send_telegram(message):
    if not TOKEN or not CHAT_ID:
        log("Missing TELEGRAM_TOKEN/CHAT_ID")
        return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id":CHAT_ID,"text":message}
    try:
        r = requests.post(url, data=payload, timeout=15)
        log("tg status "+str(r.status_code))
        return r.status_code==200
    except Exception as e:
        log("tg send err "+str(e))
        return False

def main():
    log("Starting improved daily report")
    msg = build_message()
    print(msg[:4000])  # print first part to Actions log
    ok = send_telegram(msg)
    if ok:
        log("Message sent")
    else:
        log("Failed to send")

if __name__ == "__main__":
    main()