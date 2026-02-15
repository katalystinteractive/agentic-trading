import yfinance as yf
import sys
import time
import requests
from pathlib import Path
from datetime import datetime

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

# Try VADER, fallback to keyword-based sentiment
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    VADER_AVAILABLE = True
except ImportError:
    VADER_AVAILABLE = False

_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = _ROOT / "agents"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36"
}

# Catalyst keyword categories
CATALYST_KEYWORDS = {
    'Earnings': ['earnings', 'revenue', 'profit', 'eps', 'guidance', 'beat', 'miss', 'quarterly'],
    'Regulatory': ['fda', 'sec', 'regulation', 'approval', 'lawsuit', 'fine', 'compliance', 'antitrust'],
    'Corporate': ['merger', 'acquisition', 'buyout', 'ipo', 'spinoff', 'restructuring', 'ceo', 'management'],
    'Equity': ['offering', 'dilution', 'secondary', 'shelf', 'atm'],
    'Shareholder': ['dividend', 'buyback', 'repurchase', 'split'],
    'Analyst': ['upgrade', 'downgrade', 'price target', 'initiate', 'overweight', 'underweight', 'outperform'],
    'Short': ['short', 'short-seller', 'short seller', 'short report', 'shorting'],
}

# Keyword-based fallback sentiment words
POSITIVE_WORDS = ['surge', 'soar', 'jump', 'rally', 'gain', 'beat', 'strong', 'upgrade',
                  'outperform', 'bullish', 'growth', 'record', 'breakout', 'profit', 'dividend',
                  'buyback', 'approval', 'innovation', 'expansion']
NEGATIVE_WORDS = ['drop', 'fall', 'plunge', 'crash', 'miss', 'weak', 'downgrade', 'bearish',
                  'loss', 'decline', 'cut', 'layoff', 'lawsuit', 'investigation', 'recall',
                  'warning', 'debt', 'dilution', 'offering', 'default', 'short', 'short-seller']


def _write_cache(ticker, filename, report):
    agent_dir = AGENTS_DIR / ticker
    agent_dir.mkdir(parents=True, exist_ok=True)
    with open(agent_dir / filename, "w") as f:
        f.write(report + "\n")


def keyword_sentiment(text):
    """Fallback sentiment when VADER is not available."""
    text_lower = text.lower()
    pos_count = sum(1 for w in POSITIVE_WORDS if w in text_lower)
    neg_count = sum(1 for w in NEGATIVE_WORDS if w in text_lower)
    total = pos_count + neg_count
    if total == 0:
        return 0.0, "Neutral"
    score = (pos_count - neg_count) / total
    if score > 0.1:
        return score, "Positive"
    elif score < -0.1:
        return score, "Negative"
    return score, "Neutral"


def detect_catalysts(text):
    """Detect catalyst categories in text."""
    text_lower = text.lower()
    found = []
    for category, keywords in CATALYST_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                found.append(category)
                break
    return found


def _get_sentiment(analyzer, text):
    """Run sentiment analysis on text. Returns (score, label)."""
    if VADER_AVAILABLE and analyzer:
        scores = analyzer.polarity_scores(text)
        compound = scores['compound']
        if compound >= 0.05:
            return compound, "Positive"
        elif compound <= -0.05:
            return compound, "Negative"
        return compound, "Neutral"
    return keyword_sentiment(text)


# ---------------------------------------------------------------------------
# Fetcher 1: yfinance
# ---------------------------------------------------------------------------
def _fetch_yfinance_news(ticker_symbol):
    """Returns list of {"title", "date", "source", "url"}."""
    articles = []
    try:
        ticker = yf.Ticker(ticker_symbol)
        news = ticker.news
        if not news:
            return articles
        for item in news[:20]:
            content = item.get('content', item)
            if isinstance(content, dict):
                title = content.get('title', item.get('title', 'N/A'))
                pub_date = content.get('pubDate', item.get('providerPublishTime', None))
                provider = content.get('provider', {})
                if isinstance(provider, dict):
                    source = provider.get('displayName', 'Unknown')
                else:
                    source = str(provider) if provider else 'Unknown'
                link = content.get('url', item.get('link', ''))
            else:
                title = item.get('title', 'N/A')
                pub_date = item.get('providerPublishTime', None)
                source = item.get('publisher', 'Unknown')
                link = item.get('link', '')

            title = title.replace('\u200b', '').strip()

            # Parse date
            if isinstance(pub_date, str):
                try:
                    dt = datetime.fromisoformat(pub_date.replace('Z', '+00:00'))
                    date_str = dt.strftime('%Y-%m-%d')
                except Exception:
                    date_str = pub_date[:10] if len(str(pub_date)) >= 10 else str(pub_date)
            elif isinstance(pub_date, (int, float)):
                try:
                    dt = datetime.fromtimestamp(pub_date)
                    date_str = dt.strftime('%Y-%m-%d')
                except Exception:
                    date_str = "N/A"
            else:
                date_str = "N/A"

            articles.append({
                "title": title,
                "date": date_str,
                "source": source,
                "url": link,
                "origin": "yfinance",
                "is_internal": False,
            })
    except Exception:
        pass
    return articles


# ---------------------------------------------------------------------------
# Fetcher 2: Finviz
# ---------------------------------------------------------------------------
def _fetch_finviz_news(ticker_symbol):
    """Scrape Finviz news table. Returns list of dicts."""
    if not BS4_AVAILABLE:
        return []
    articles = []
    try:
        url = f"https://finviz.com/quote.ashx?t={ticker_symbol}&ty=c&p=d&b=1"
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        if resp.status_code != 200:
            return articles
        soup = BeautifulSoup(resp.text, "html.parser")
        news_table = soup.find("table", id="news-table")
        if not news_table:
            return articles

        current_date = "N/A"
        for row in news_table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            # First cell: date/time. Format: "Feb-14-26 11:52PM" or just "03:56PM"
            date_cell = cells[0].get_text(strip=True)
            if len(date_cell) > 8:
                # Full date+time: "Feb-14-26 11:52PM"
                parts = date_cell.split()
                if parts:
                    current_date = parts[0]
            # else: time-only, keep current_date

            # Second cell: headline link
            link_tag = cells[1].find("a")
            if not link_tag:
                continue
            title = link_tag.get_text(strip=True)
            href = link_tag.get("href", "")

            # Source: text after the link (often in a span)
            source_span = cells[1].find("span")
            if source_span:
                source = source_span.get_text(strip=True).strip("()")
            else:
                source = "Finviz"

            # Parse finviz date to standard format
            date_str = current_date
            try:
                dt = datetime.strptime(current_date, "%b-%d-%y")
                date_str = dt.strftime("%Y-%m-%d")
            except Exception:
                pass

            is_internal = href.startswith("/news/") or href.startswith("news/")

            articles.append({
                "title": title,
                "date": date_str,
                "source": source,
                "url": href if not is_internal else f"https://finviz.com{href}",
                "origin": "finviz",
                "is_internal": is_internal,
            })
    except Exception:
        pass
    return articles


# ---------------------------------------------------------------------------
# Fetcher 3: Google News RSS
# ---------------------------------------------------------------------------
def _fetch_google_news(ticker_symbol, company_name=""):
    """Parse Google News RSS. Returns list of dicts."""
    if not BS4_AVAILABLE:
        return []
    articles = []
    try:
        query = f"{ticker_symbol}+stock"
        if company_name:
            query = f"{ticker_symbol}+{company_name.split()[0]}+stock"
        url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        if resp.status_code != 200:
            return articles
        soup = BeautifulSoup(resp.text, "xml")
        items = soup.find_all("item")
        for item in items[:100]:
            title_tag = item.find("title")
            title = title_tag.get_text(strip=True) if title_tag else "N/A"
            link_tag = item.find("link")
            link = link_tag.get_text(strip=True) if link_tag else ""
            # link can also be the next sibling text node
            if not link and link_tag and link_tag.next_sibling:
                link = str(link_tag.next_sibling).strip()
            pub_tag = item.find("pubDate")
            source_tag = item.find("source")
            source = source_tag.get_text(strip=True) if source_tag else "Google News"

            date_str = "N/A"
            if pub_tag:
                try:
                    # RFC 2822 format: "Sat, 15 Feb 2026 14:30:00 GMT"
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(pub_tag.get_text(strip=True))
                    date_str = dt.strftime("%Y-%m-%d")
                except Exception:
                    raw = pub_tag.get_text(strip=True)
                    date_str = raw[:10] if len(raw) >= 10 else raw

            articles.append({
                "title": title,
                "date": date_str,
                "source": source,
                "url": link,
                "origin": "google",
                "is_internal": False,
            })
    except Exception:
        pass
    return articles


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------
def _normalize_title(title):
    """Normalize title for dedup: lowercase, first 50 chars, strip punctuation."""
    t = title.lower().strip()
    # Remove common noise
    for ch in ['...', '"', "'", '\u2018', '\u2019', '\u201c', '\u201d']:
        t = t.replace(ch, '')
    return t[:50]


def _deduplicate(all_articles):
    """Deduplicate by normalized title prefix. Prefer Finviz (has fetchable content)."""
    seen = {}
    # Priority: finviz > google > yfinance (finviz has internal article content)
    priority = {"finviz": 0, "google": 1, "yfinance": 2}
    sorted_articles = sorted(all_articles, key=lambda a: priority.get(a.get("origin", ""), 9))
    for art in sorted_articles:
        key = _normalize_title(art["title"])
        if key not in seen:
            seen[key] = art
    # Return sorted by date descending
    result = list(seen.values())
    result.sort(key=lambda a: a.get("date", ""), reverse=True)
    return result


# ---------------------------------------------------------------------------
# Deep dive: fetch article content from Finviz internal links
# ---------------------------------------------------------------------------
def _fetch_article_content(url):
    """Fetch full article from Finviz internal URL. Returns list of paragraph strings."""
    if not BS4_AVAILABLE:
        return []
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        content_div = soup.find("div", class_="content")
        if not content_div:
            # Try article tag or main content area
            content_div = soup.find("article") or soup.find("div", id="content")
        if not content_div:
            return []
        paragraphs = []
        for p in content_div.find_all("p"):
            text = p.get_text(strip=True)
            if len(text) >= 40:  # Filter out nav text, bylines
                paragraphs.append(text)
        return paragraphs[:5]  # First 5 substantive paragraphs
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------
def analyze_news(ticker_symbol):
    lines = []

    # Get company name from yfinance
    company_name = ticker_symbol
    try:
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info
        if info:
            company_name = info.get('shortName', ticker_symbol)
    except Exception:
        pass

    # Set up sentiment analyzer
    if VADER_AVAILABLE:
        analyzer = SentimentIntensityAnalyzer()
        method = "VADER"
    else:
        analyzer = None
        method = "Keyword"

    # Fetch from all three sources
    yf_articles = _fetch_yfinance_news(ticker_symbol)
    fv_articles = _fetch_finviz_news(ticker_symbol)
    gn_articles = _fetch_google_news(ticker_symbol, company_name)

    all_articles = yf_articles + fv_articles + gn_articles

    if not all_articles:
        lines.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
        lines.append("")
        lines.append(f"## News & Sentiment: {company_name} ({ticker_symbol})")
        lines.append("")
        lines.append("*No recent news available from any source.*")
        return "\n".join(lines)

    # Deduplicate
    deduped = _deduplicate(all_articles)

    # Source counts (before dedup, for reporting)
    yf_count = len(yf_articles)
    fv_count = len(fv_articles)
    gn_count = len(gn_articles)

    # Identify internal Finviz articles for deep dive
    internal_articles = [a for a in deduped if a.get("is_internal")]

    # Header
    lines.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    lines.append("")
    lines.append(f"## News & Sentiment: {company_name} ({ticker_symbol})")

    # Placeholder for source line — deep dive count patched after fetch loop
    source_line_idx = len(lines)
    lines.append("")  # placeholder, replaced below

    # --- Headlines Table (Top 30) ---
    lines.append("")
    lines.append("### Headlines (Top 30, Deduplicated)")
    lines.append("| Date | Source | Headline | Sentiment | Score | Catalysts |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")

    analyzed = []
    catalyst_counts = {}

    for art in deduped[:30]:
        title = art["title"]
        analysis_text = title
        score, sentiment = _get_sentiment(analyzer, analysis_text)
        catalysts = detect_catalysts(analysis_text)
        catalyst_str = ", ".join(catalysts) if catalysts else "—"

        for cat in catalysts:
            catalyst_counts[cat] = catalyst_counts.get(cat, 0) + 1

        analyzed.append({
            "title": title,
            "sentiment": sentiment,
            "score": score,
            "catalysts": catalysts,
        })

        # Truncate and escape for table
        headline = title[:60] + "..." if len(title) > 60 else title
        headline = headline.replace('|', '-')
        source_display = art["source"][:15] if len(art["source"]) > 15 else art["source"]
        source_display = source_display.replace('|', '-')

        lines.append(f"| {art['date']} | {source_display} | {headline} | {sentiment} | {score:+.2f} | {catalyst_str} |")

    # --- Sentiment Summary ---
    lines.append("")
    lines.append("### Sentiment Summary")
    lines.append("| Metric | Value |")
    lines.append("| :--- | :--- |")

    total = len(analyzed)
    positive = sum(1 for a in analyzed if a['sentiment'] == 'Positive')
    neutral = sum(1 for a in analyzed if a['sentiment'] == 'Neutral')
    negative = sum(1 for a in analyzed if a['sentiment'] == 'Negative')
    avg_score = sum(a['score'] for a in analyzed) / total if total > 0 else 0

    if avg_score > 0.1:
        overall = "Bullish"
    elif avg_score < -0.1:
        overall = "Bearish"
    else:
        overall = "Neutral"

    lines.append(f"| Articles Analyzed | {total} |")
    lines.append(f"| Positive | {positive} ({positive/total*100:.0f}%) |")
    lines.append(f"| Neutral | {neutral} ({neutral/total*100:.0f}%) |")
    lines.append(f"| Negative | {negative} ({negative/total*100:.0f}%) |")
    lines.append(f"| Average Score | {avg_score:+.3f} |")
    lines.append(f"| Overall Sentiment | **{overall}** |")
    lines.append(f"| Total Unique Headlines | {len(deduped)} |")

    # --- Detected Catalysts ---
    if catalyst_counts:
        lines.append("")
        lines.append("### Detected Catalysts")
        lines.append("| Category | Count | Headlines |")
        lines.append("| :--- | :--- | :--- |")

        for category, count in sorted(catalyst_counts.items(), key=lambda x: x[1], reverse=True):
            matching = []
            for art in analyzed:
                if category in art.get('catalysts', []):
                    short_title = art['title'][:40] + ".." if len(art['title']) > 40 else art['title']
                    short_title = short_title.replace('|', '-')
                    matching.append(short_title)
            headlines = "; ".join(matching[:2])
            lines.append(f"| {category} | {count} | {headlines} |")

    # --- Deep Dive Articles ---
    if internal_articles:
        lines.append("")
        lines.append("### Deep Dive Articles")

        fetched_count = 0
        for art in internal_articles[:5]:
            paragraphs = _fetch_article_content(art["url"])
            if not paragraphs:
                continue
            fetched_count += 1

            # Analyze full text for better sentiment
            full_text = " ".join(paragraphs)
            dd_score, dd_sentiment = _get_sentiment(analyzer, full_text)
            dd_catalysts = detect_catalysts(full_text)
            dd_catalyst_str = ", ".join(dd_catalysts) if dd_catalysts else "None"

            lines.append("")
            headline_clean = art["title"].replace('|', '-')
            lines.append(f"#### {headline_clean}")
            lines.append(f"*Source: {art['source']} | Date: {art['date']} | Sentiment: {dd_sentiment} ({dd_score:+.2f})*")
            lines.append("")
            for para in paragraphs:
                # Escape pipe chars in blockquotes
                para_clean = para.replace('|', '-')
                lines.append(f"> {para_clean}")
                lines.append("")
            lines.append(f"**Catalysts:** {dd_catalyst_str}")

            time.sleep(0.5)  # Rate limiting between fetches

        if fetched_count == 0:
            lines.append("")
            lines.append("*No fetchable article content available.*")
        deep_dive_actual = fetched_count
    else:
        deep_dive_actual = 0

    # Patch the source line placeholder with actual deep dive count
    lines[source_line_idx] = (
        f"*Sources: Finviz ({fv_count}), Google News ({gn_count}), yfinance ({yf_count}) | "
        f"Method: {method} | Deep Dives: {deep_dive_actual}*"
    )

    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 news_sentiment.py <TICKER>")
    else:
        ticker = sys.argv[1].upper()
        report = analyze_news(ticker)
        if report:
            print(report)
            _write_cache(ticker, "news.md", report)
