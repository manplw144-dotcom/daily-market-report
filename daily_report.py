# daily_report_nocost.py
# No-cost daily report:
# - fetch recent news (last 24h) for tickers
# - extract article text, perform extractive summarization (keyword-weighted + position)
# - translate summary to Thai via translate.googleapis.com
# - produce 8-12 line Thai summary + detailed impact bullets
# - send to Telegram
#
# Requirements: pip install yfinance requests beautifulsoup4
# Env: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
# Author: ChatGPT (assistant) - tailored for user's preference (C / C / C)

import os
import re
import time
import math
import requests
import datetime
import urllib.parse
from collections import Counter
from bs4 import BeautifulSoup
import yfinance as yf
from html import unescape

# ---------- CONFIG ----------
TICKERS = {
    "IONQ": 56.2,
    "FLY": 24.635,
    "LUNR": 9.23
}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
MARKETAUX_TOKEN = "demo"  # optional; used if helpful
TRANSLATE_ENDPOINT = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=th&dt=t&q="

# Summarization tuning
IMPORTANT_KEYWORDS = [
    "earnings", "revenue", "guidance", "contract", "acquisition", "acquire",
    "merger", "launch", "failure", "delay", "success", "loss", "profit",
    "backlog", "order", "funding", "cash", "grant", "award", "agreement",
    "settlement", "investigation", "contractor", "nasa", "defense", "sec"
]
MAX_SUMMARY_SENTENCES = 6  # aim 3-5 sentences; we'll produce 4-6 english then translate and expand to 8-12 thai lines

# Telegram / env
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ---------- Helpers ----------
def log(msg):
    print(f"[DEBUG] {msg}")

def safe_get(url, timeout=10):
    try:
        return requests.get(url, headers=HEADERS, timeout=timeout)
    except Exception as e:
        log(f"HTTP GET err for {url}: {e}")
        return None

def translate_to_th(text):
    """Translate English text to Thai using public Google translate endpoint (best-effort)."""
    if not text or text.strip() == "":
        return text
    try:
        q_enc = urllib.parse.quote(text)
        url = TRANSLATE_ENDPOINT + q_enc
        r = safe_get(url, timeout=12)
        if r and r.status_code == 200:
            data = r.json()
            # data[0] is list of sentences with translated pieces
            translated = "".join([part[0] for part in data[0] if part and part[0]])
            # cleanup
            translated = re.sub(r'\s+', ' ', translated).strip()
            # short pause
            time.sleep(0.06)
            return translated
        else:
            log(f"translate failed status: {r.status_code if r else 'no resp'}")
            return text
    except Exception as e:
        log(f"translate err: {e}")
        return text

# ---------- Article fetching & date handling ----------
def fetch_yahoo_candidates(ticker, limit=10):
    """
    Use Yahoo search endpoint to get candidate news articles for ticker.
    Returns list of dicts: {title,url,publisher}
    """
    out = []
    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={urllib.parse.quote(ticker)}"
        r = safe_get(url, timeout=8)
        if r and r.status_code == 200:
            j = r.json()
            news = j.get("news", []) or []
            for n in news[:limit]:
                title = n.get("title") or ""
                urln = n.get("url") or n.get("link") or ""
                publisher = n.get("publisher") or n.get("source") or ""
                out.append({"title": title, "url": urln, "publisher": publisher})
    except Exception as e:
        log(f"fetch_yahoo_candidates err {e}")
    # dedupe by url
    seen = set()
    res = []
    for a in out:
        u = a.get("url")
        if u and u not in seen:
            seen.add(u)
            res.append(a)
    return res

def fetch_article_text_and_published(url):
    """
    Fetch article and attempt to extract:
    - main text (concatenate <p>)
    - published datetime (ISO-ish) if found via meta/time tags
    Returns: (text, published_iso_or_none)
    """
    try:
        r = safe_get(url, timeout=10)
        if not r or r.status_code != 200:
            return "", None
        text = r.text
        soup = BeautifulSoup(text, "html.parser")
        # try meta published time tags
        pub = None
        # common tags
        meta_queries = [
            ("meta", {"property":"article:published_time"}),
            ("meta", {"name":"article:published_time"}),
            ("meta", {"name":"pubdate"}),
            ("meta", {"name":"publishdate"}),
            ("meta", {"name":"published_time"}),
            ("meta", {"property":"og:published_time"}),
            ("meta", {"property":"og:pubdate"}),
            ("meta", {"itemprop":"datePublished"}),
        ]
        for tag, attrs in meta_queries:
            try:
                node = soup.find(tag, attrs=attrs)
                if node:
                    if node.has_attr("content"):
                        pub = node["content"]
                        break
                    elif node.has_attr("datetime"):
                        pub = node["datetime"]
                        break
            except Exception:
                continue
        # try <time> tag
        if not pub:
            ttag = soup.find("time")
            if ttag:
                if ttag.has_attr("datetime"):
                    pub = ttag["datetime"]
                else:
                    pub = ttag.get_text(strip=True)
        # extract text: prefer <article>, then <main>, then largest <div> with many <p>, else all <p>
        body_text = []
        article_tag = soup.find("article")
        if article_tag:
            for p in article_tag.find_all("p"):
                t = p.get_text().strip()
                if t:
                    body_text.append(t)
        if not body_text:
            main = soup.find("main")
            if main:
                for p in main.find_all("p"):
                    t = p.get_text().strip()
                    if t:
                        body_text.append(t)
        if not body_text:
            # choose largest div
            divs = soup.find_all("div")
            best = ""
            for d in divs:
                ps = d.find_all("p")
                s = " ".join([p.get_text().strip() for p in ps])
                if len(s) > len(best):
                    best = s
            if best:
                # split into reasonable paragraphs
                paras = re.split(r'\n+', best)
                for p in paras:
                    p = p.strip()
                    if p:
                        body_text.append(p)
        if not body_text:
            # fallback to any <p>
            for p in soup.find_all("p"):
                t = p.get_text().strip()
                if t:
                    body_text.append(t)
        joined = " ".join(body_text)
        joined = re.sub(r'\s+', ' ', joined).strip()
        # normalize pub to ISO if possible; best-effort
        pub_iso = None
        if pub:
            # try common patterns like '2025-11-13T12:34:56Z' or 'Tue, 13 Nov 2025 12:34:56 GMT'
            try:
                # try fromisoformat (allow Z -> +00:00)
                s = str(pub).strip()
                if s.endswith("Z"):
                    s2 = s.replace("Z", "+00:00")
                else:
                    s2 = s
                try:
                    dt = datetime.datetime.fromisoformat(s2)
                    pub_iso = dt.isoformat()
                except Exception:
                    # try parsing common RFC format
                    try:
                        dt = datetime.datetime.strptime(s, "%a, %d %b %Y %H:%M:%S %Z")
                        pub_iso = dt.isoformat()
                    except Exception:
                        pub_iso = s  # leave raw
            except Exception:
                pub_iso = str(pub)
        return joined, pub_iso
    except Exception as e:
        log(f"fetch_article_text err {e} for {url}")
        return "", None

def is_within_last_24h(pub_iso):
    """Return True if pub_iso (iso or string) is within last 24 hours. If pub_iso unknown -> False."""
    if not pub_iso:
        return False
    try:
        # try parse ISO-like
        s = str(pub_iso)
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        try:
            dt = datetime.datetime.fromisoformat(s)
            # convert to naive UTC
            if dt.tzinfo:
                dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        except Exception:
            # fallback: try to extract YYYY-MM-DD
            m = re.search(r'(\d{4}-\d{2}-\d{2})', s)
            if m:
                dt = datetime.datetime.fromisoformat(m.group(1))
            else:
                return False
        now = datetime.datetime.utcnow()
        delta = now - dt
        return 0 <= delta.total_seconds() <= 86400
    except Exception as e:
        log(f"is_within_last_24h err {e} for {pub_iso}")
        return False

# ---------- Summarization (extractive) ----------
def split_sentences(text):
    if not text: return []
    # naive sentence splitter
    text = text.replace("\r", " ").replace("\n", " ")
    # split on . ! ? with follow-up whitespace + capital or number; keep simple
    sents = re.split(r'(?<=[\.\?\!])\s+(?=[A-Z0-9"“\'\(\[])', text)
    # fallback: if too few, split by period
    if len(sents) < 2:
        sents = text.split('. ')
    sents = [s.strip() for s in sents if s and len(s.strip()) > 10]
    return sents

def compute_tf(sentences):
    words = []
    for s in sentences:
        for w in re.findall(r"\w+", s.lower()):
            words.append(w)
    freq = Counter(words)
    return freq

def score_sentence(s, tf, important_terms):
    words = re.findall(r"\w+", s.lower())
    if not words:
        return 0.0
    # base = sum of tf for words in sentence
    base = sum(tf.get(w, 0) for w in words)
    # position score: earlier sentences are often more important
    pos_bonus = 1.0
    # boost for containing important keywords
    kw_bonus = sum(2 for kw in important_terms if kw in s.lower())
    # length penalty for too short or too long
    length = len(words)
    length_factor = 1.0
    if length < 6:
        length_factor = 0.7
    elif length > 80:
        length_factor = 0.9
    score = base * (1 + kw_bonus) * length_factor + pos_bonus
    return score

def extractive_summary(text, important_terms=None, max_sentences=4):
    if not text:
        return ""
    sents = split_sentences(text)
    if not sents:
        return ""
    tf = compute_tf(sents)
    important_terms = important_terms or []
    scored = [(s, score_sentence(s, tf, important_terms)) for s in sents]
    # pick top candidates but preserve original order
    topk = sorted(scored, key=lambda x: x[1], reverse=True)[:max_sentences*3]
    top_sentences = [s for s,sc in topk]
    summary = []
    for s in sents:
        if s in top_sentences and s not in summary:
            summary.append(s)
        if len(summary) >= max_sentences:
            break
    # fallback: first max_sentences
    if not summary:
        summary = sents[:max_sentences]
    # join as paragraph
    return " ".join(summary)

# ---------- Impact assessment rule-based ----------
def assess_impact(summary_en):
    """
    Determine impact: 'ขึ้น', 'ลง', 'เป็นกลาง' + detailed reasoning bullets.
    Rules:
      - positive keywords -> likely up
      - negative keywords -> likely down
      - mixed -> neutral
    """
    text = summary_en.lower()
    pos_keys = ["beat", "beats", "outperform", "raised guidance", "increase", "win", "awarded", "contract", "award", "acquired", "acquisition", "profit", "growth", "record", "order"]
    neg_keys = ["miss", "missed", "cut guidance", "lower guidance", "delay", "failure", "investigation", "loss widened", "loss", "recall", "bankruptcy", "lawsuit", "suspend"]
    pos_count = sum(1 for k in pos_keys if k in text)
    neg_count = sum(1 for k in neg_keys if k in text)
    # also weighting for explicit numbers like revenue up/down
    # simple heuristics:
    impact = "เป็นกลาง"
    reason_list = []
    if pos_count > neg_count and pos_count >= 1:
        impact = "ขึ้น"
    elif neg_count > pos_count and neg_count >= 1:
        impact = "ลง"
    else:
        impact = "เป็นกลาง"
    # produce reasons: extract sentences that contain keywords
    sents = split_sentences(summary_en)
    for s in sents:
        ls = s.lower()
        if any(k in ls for k in pos_keys + neg_keys):
            reason_list.append(s.strip())
    # if no explicit sentences, pick first sentence as reason
    if not reason_list and sents:
        reason_list.append(sents[0].strip())
    # create bullets with short Thai translation of reasons
    # we'll translate later; here return english reasons
    return impact, reason_list

# ---------- Main pipeline per ticker ----------
def process_ticker(ticker):
    """
    1) fetch candidates
    2) fetch article text + pub time
    3) filter last 24h
    4) summarize each article (extractive)
    5) translate summaries to Thai and create formatted output
    """
    out_entries = []
    candidates = fetch_yahoo_candidates(ticker, limit=12)
    log(f"{ticker} candidates {len(candidates)}")
    # try also searching aliases if few candidates
    if len(candidates) < 6:
        aliases = [ticker]
        if ticker == "FLY":
            aliases += ["Firefly Aerospace", "Firefly SciTec", "SciTec", "Sci Tec"]
        if ticker == "LUNR":
            aliases += ["Intuitive Machines"]
        if ticker == "IONQ":
            aliases += ["IonQ", "IonQ Inc"]
        for a in aliases:
            if a == ticker: continue
            try:
                more = fetch_yahoo_candidates(a, limit=6)
                for m in more:
                    if all(m.get("url") != c.get("url") for c in candidates):
                        candidates.append(m)
            except:
                pass
    # fetch article text and published time
    articles = []
    for c in candidates:
        url = c.get("url")
        if not url:
            continue
        art_text, pub_iso = fetch_article_text_and_published(url)
        if not art_text:
            continue
        # filter by last 24h if pub_iso present
        include = False
        if pub_iso:
            if is_within_last_24h(pub_iso):
                include = True
        else:
            # heuristic: if title contains month names or 'today' or url contains '/2025/' or 'nov' etc - include but mark
            title = c.get("title","")
            if re.search(r'\b(today|yesterday|hours ago|minutes ago|ago)\b', title, flags=re.I):
                include = True
            if re.search(r'\b(202[0-9]|nov|oct|sep|aug|jul|jun|may|apr|mar|feb|jan)\b', c.get("url","") + title, flags=re.I):
                include = True
        if include:
            articles.append({"title": c.get("title"), "url": url, "publisher": c.get("publisher"), "text": art_text, "pub": pub_iso})
    log(f"{ticker} articles within 24h: {len(articles)}")
    # limit to most relevant (up to 3)
    articles = articles[:3]
    if not articles:
        return []
    # produce summaries
    for a in articles:
        text = a.get("text","")
        # extractive summary english (3-4 sentences)
        summary_en = extractive_summary(text, important_terms=IMPORTANT_KEYWORDS, max_sentences=MAX_SUMMARY_SENTENCES)
        # if summary too short, consider taking first 2-4 original sentences
        if not summary_en:
            sents = split_sentences(text)
            summary_en = " ".join(sents[:3]) if sents else (a.get("title") or "")
        # assess impact
        impact_label, reasons_en = assess_impact(summary_en)
        # form structured result
        out_entries.append({
            "title": a.get("title"),
            "url": a.get("url"),
            "publisher": a.get("publisher"),
            "pub": a.get("pub"),
            "summary_en": summary_en,
            "impact": impact_label,
            "impact_reasons_en": reasons_en
        })
    return out_entries

# ---------- Compose Thai human-friendly summary for ticker ----------
def format_ticker_section(ticker, avg_cost):
    # price
    try:
        p = yf.Ticker(ticker).history(period="1d")['Close'][-1]
        price_now = round(float(p),4)
    except Exception:
        price_now = None
    header = f"{ticker} — สรุปข่าวสำคัญประจำวันที่ { (datetime.datetime.utcnow() + datetime.timedelta(hours=7)).strftime('%Y-%m-%d') }\n"
    header += f"ราคาล่าสุด: ${price_now if price_now is not None else 'n/a'} | ต้นทุนเฉลี่ยของคุณ: ${avg_cost}\n"
    # process
    entries = process_ticker(ticker)
    if not entries:
        body = "  - ไม่มีข่าวสำคัญภายใน 24 ชั่วโมง\n\n"
        return header + body
    # For each article, create Thai summary (8-12 lines total per ticker ideally)
    # We'll translate each article's extractive summary and impact reasons, then expand slightly to reach 8-12 lines overall.
    sections_th = []
    for idx, e in enumerate(entries):
        # create english block: title + summary_en + reasons
        title_en = e.get("title") or ""
        summary_en = e.get("summary_en") or ""
        reasons_en = e.get("impact_reasons_en") or []
        eng_block = title_en + ". " + summary_en
        if reasons_en:
            eng_block += " Reasons: " + " | ".join(reasons_en[:3])
        # translate
        thai_block = translate_to_th(eng_block)
        # Post-process: split into sentences (thai may not have explicit punctuation) — we will chunk by periods from english or split on sentences from thai heuristics
        # Format into readable bullets: headline (1 line), summary (3-6 lines), impact bullets (2-3 lines)
        # We'll create a polished Thai paragraph using simple templates
        # Try to extract a short headline via translate of title_en
        title_th = translate_to_th(title_en) if title_en else ""
        # create summary_th as translation of summary_en (may be similar to thai_block)
        summary_th = translate_to_th(summary_en)
        # translate reasons
        reasons_th = [translate_to_th(r) for r in reasons_en] if reasons_en else []
        # impact label translation
        impact_th = {"ขึ้น":"ขึ้น", "ลง":"ลง", "เป็นกลาง":"เป็นกลาง"}.get(e.get("impact","เป็นกลาง"), "เป็นกลาง")
        # build section text
        sec = ""
        if title_th:
            sec += f"• {title_th}\n"
        # break summary into sentences heuristically
        # try to split by '. ' or '。' or newline
        chunks = re.split(r'(?<=[\.\?!])\s+|\n+', summary_th)
        # keep up to 5 short lines
        count_lines = 0
        for c in chunks:
            c = c.strip()
            if not c:
                continue
            # ensure line not too long
            if len(c) > 220:
                # break long line into smaller chunks at comma
                parts = re.split(r',\s+|;|\.', c)
                for p in parts:
                    p = p.strip()
                    if p:
                        sec += f"    - {p}\n"
                        count_lines += 1
                        if count_lines >= 6:
                            break
                if count_lines >= 6:
                    break
            else:
                sec += f"    - {c}\n"
                count_lines += 1
            if count_lines >= 6:
                break
        # impact block
        sec += f"    ผลกระทบโดยสรุป: ราคาน่าจะ '{impact_th}' ใน 1–3 วันข้างหน้า เนื่องจาก:\n"
        for rth in reasons_th[:3]:
            sec += f"      • {rth}\n"
        # add original URL
        if e.get("url"):
            sec += f"    อ่านต้นฉบับ: {e.get('url')}\n"
        sec += "\n"
        sections_th.append(sec)
    # Combine and ensure overall lines ~8-12: if too short, expand by adding publisher/pub date info
    combined = header + "\n"
    for s in sections_th:
        combined += s
    # Add short recommendation for the ticker based on combined impacts
    # Aggregate impact votes
    impacts = [e.get("impact","เป็นกลาง") for e in entries]
    up_votes = sum(1 for v in impacts if v == "ขึ้น")
    down_votes = sum(1 for v in impacts if v == "ลง")
    if up_votes > down_votes:
        rec = "คำแนะนำรวม: มีแนวโน้มเป็นบวก — พิจารณาสะสม/เพิ่มน้ำหนักตามความเสี่ยง"
    elif down_votes > up_votes:
        rec = "คำแนะนำรวม: มีสัญญาณลบ — พิจารณาลดน้ำหนักหรือตั้งจุดตัดขาดทุน"
    else:
        rec = "คำแนะนำรวม: สัญญาณผสม — รักษาสัดส่วนและติดตามข่าว/ผลประกอบการเพิ่มเติม"
    combined += rec + "\n\n"
    return combined

# ---------- Compose full report ----------
def build_full_report():
    now_th = (datetime.datetime.datetime.utcnow() + datetime.timedelta(hours=7)).strftime("%Y-%m-%d %H:%M")
    header = f"📅 รายงานประจำวันที่ {now_th} (TH)\n\n"
    # market snapshot
    try:
        sp = yf.Ticker("^GSPC").history(period="1d")["Close"][-1]
        nd = yf.Ticker("^IXIC").history(period="1d")["Close"][-1]
        dj = yf.Ticker("^DJI").history(period="1d")["Close"][-1]
        market_line = f"🌎 ตลาดเมื่อคืน: S&P500 {round(sp,2)} | Nasdaq {round(nd,2)} | Dow {round(dj,2)}\n\n"
    except Exception:
        market_line = "🌎 ตลาดเมื่อคืน: (no data)\n\n"
    body = ""
    # Market-level news (short): try Marketaux -> Yahoo news page (but we will summarise only top 1-2 items if within 24h)
    market_news_block = ""
    try:
        # try Marketaux
        url = f"https://api.marketaux.com/v1/news/all?countries=us&limit=12&api_token={MARKETAUX_TOKEN}"
        r = safe_get(url, timeout=6)
        items = []
        if r and r.status_code == 200:
            js = r.json()
            items = js.get("data", []) or []
        # filter for market-moving keywords
        filtered = []
        for it in items:
            title = it.get("title","")
            lower = title.lower()
            if any(k in lower for k in ["fed","cpi","inflation","interest","recession","gdp","earnings","rate cut","rate hike","bank","unemployment","jobs","ai","semiconductor","defense","nasa"]):
                filtered.append({"title":title, "url": it.get("url",""), "source": it.get("source",{}).get("name","")})
        if not filtered:
            # fallback Yahoo news page
            r2 = safe_get("https://finance.yahoo.com/news", timeout=8)
            if r2 and r2.status_code == 200:
                soup = BeautifulSoup(r2.text, "html.parser")
                for h3 in soup.find_all("h3")[:8]:
                    t = h3.get_text().strip()
                    if any(k in t.lower() for k in ["fed","cpi","inflation","interest","recession","gdp","earnings","ai","defense"]):
                        filtered.append({"title": t, "url": "", "source": "Yahoo News"})
        # keep only those that appear within last 24h by heuristics (we skip thorough published time here; assume Marketaux is recent)
        if filtered:
            top = filtered[:2]
            eng_block = " | ".join([it["title"] for it in top])
            thai_block = translate_to_th(eng_block)
            market_news_block = thai_block + "\n\n"
        else:
            market_news_block = "- ไม่มีข่าวระดับแมครสำคัญภายใน 24 ชั่วโมง\n\n"
    except Exception as e:
        log(f"market news pipeline err: {e}")
        market_news_block = "- ไม่มีข่าวระดับแมครสำคัญ (error)\n\n"

    # per-ticker sections
    for t, avg in TICKERS.items():
        body += format_ticker_section(t, avg)

    # final portfolio-level suggestion (short)
    final_note = "\n📌 สรุปพอร์ตโดยรวม: รักษาสัดส่วนความเสี่ยงตามเป้าหมายของคุณ — หากต้องการผมสามารถให้คำแนะนำปรับสัดส่วนเชิงกลยุทธ์ต่อได้\n"
    report = header + market_line + "📰 ข่าวสำคัญระดับตลาด (สรุป):\n" + market_news_block + body + final_note
    return report

# ---------- Telegram sender ----------
def send_to_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log("Missing TELEGRAM_TOKEN or TELEGRAM_CHAT_ID")
        return False
    # Telegram message size limit ~4096 characters, so chunk if longer
    chunks = []
    max_len = 3800
    if len(text) <= max_len:
        chunks = [text]
    else:
        # naive chunk by paragraphs
        parts = text.split("\n\n")
        cur = ""
        for p in parts:
            if len(cur) + len(p) + 2 < max_len:
                cur += p + "\n\n"
            else:
                chunks.append(cur)
                cur = p + "\n\n"
        if cur:
            chunks.append(cur)
    ok = True
    for c in chunks:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": c})
            log(f"TG send status {r.status_code}")
            if r.status_code != 200:
                ok = False
        except Exception as e:
            log(f"TG send err: {e}")
            ok = False
    return ok

# ---------- Main ----------
def main():
    log("Starting daily_report_nocost")
    report = build_full_report()
    # print head of report for logs
    print(report[:4000])
    sent = send_to_telegram(report)
    if sent:
        log("Report sent to Telegram")
    else:
        log("Failed to send report to Telegram")

if __name__ == "__main__":
    main()