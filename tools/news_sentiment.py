import yfinance as yf
import sys
from datetime import datetime

# Try VADER, fallback to keyword-based sentiment
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    VADER_AVAILABLE = True
except ImportError:
    VADER_AVAILABLE = False

# Catalyst keyword categories
CATALYST_KEYWORDS = {
    'Earnings': ['earnings', 'revenue', 'profit', 'eps', 'guidance', 'beat', 'miss', 'quarterly'],
    'Regulatory': ['fda', 'sec', 'regulation', 'approval', 'lawsuit', 'fine', 'compliance', 'antitrust'],
    'Corporate': ['merger', 'acquisition', 'buyout', 'ipo', 'spinoff', 'restructuring', 'ceo', 'management'],
    'Equity': ['offering', 'dilution', 'secondary', 'shelf', 'atm'],
    'Shareholder': ['dividend', 'buyback', 'repurchase', 'split'],
    'Analyst': ['upgrade', 'downgrade', 'price target', 'initiate', 'overweight', 'underweight', 'outperform'],
}

# Keyword-based fallback sentiment words
POSITIVE_WORDS = ['surge', 'soar', 'jump', 'rally', 'gain', 'beat', 'strong', 'upgrade',
                  'outperform', 'bullish', 'growth', 'record', 'breakout', 'profit', 'dividend',
                  'buyback', 'approval', 'innovation', 'expansion']
NEGATIVE_WORDS = ['drop', 'fall', 'plunge', 'crash', 'miss', 'weak', 'downgrade', 'bearish',
                  'loss', 'decline', 'cut', 'layoff', 'lawsuit', 'investigation', 'recall',
                  'warning', 'debt', 'dilution', 'offering', 'default']

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

def analyze_news(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info
        if not info or info.get('regularMarketPrice') is None:
            print(f"Error: Could not fetch data for {ticker_symbol}")
            return
    except Exception as e:
        print(f"Error: {e}")
        return

    company_name = info.get('shortName', ticker_symbol)

    if VADER_AVAILABLE:
        analyzer = SentimentIntensityAnalyzer()
        method = "VADER"
    else:
        analyzer = None
        method = "Keyword"

    print(f"\n## News Sentiment: {company_name} ({ticker_symbol})")
    print(f"*Method: {method}*")

    # Fetch news
    try:
        news = ticker.news
    except Exception as e:
        print(f"Error fetching news: {e}")
        return

    if not news:
        print("\n*No recent news available.*")
        return

    # --- Table 1: Recent News ---
    print(f"\n### Recent News")
    print("| Date | Source | Headline | Sentiment | Score | Catalysts |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- |")

    articles = []
    catalyst_counts = {}

    for item in news[:20]:
        # Handle nested content structure
        content = item.get('content', item)
        if isinstance(content, dict):
            title = content.get('title', item.get('title', 'N/A'))
            summary = content.get('summary', item.get('summary', ''))
            pub_date = content.get('pubDate', item.get('providerPublishTime', None))
            provider = content.get('provider', {})
            if isinstance(provider, dict):
                source = provider.get('displayName', 'Unknown')
            else:
                source = str(provider) if provider else 'Unknown'
        else:
            title = item.get('title', 'N/A')
            summary = item.get('summary', '')
            pub_date = item.get('providerPublishTime', None)
            source = item.get('publisher', 'Unknown')

        # Clean title
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

        # Sentiment analysis
        analysis_text = f"{title}. {summary}" if summary else title
        if VADER_AVAILABLE and analyzer:
            scores = analyzer.polarity_scores(analysis_text)
            compound = scores['compound']
            if compound >= 0.05:
                sentiment = "Positive"
            elif compound <= -0.05:
                sentiment = "Negative"
            else:
                sentiment = "Neutral"
        else:
            compound, sentiment = keyword_sentiment(analysis_text)

        # Detect catalysts
        catalysts = detect_catalysts(analysis_text)
        catalyst_str = ", ".join(catalysts) if catalysts else "—"
        for cat in catalysts:
            catalyst_counts[cat] = catalyst_counts.get(cat, 0) + 1

        articles.append({
            'sentiment': sentiment,
            'score': compound,
            'title': title
        })

        # Truncate headline for table
        headline = title[:60] + "..." if len(title) > 60 else title
        # Escape pipe characters in headline
        headline = headline.replace('|', '-')
        source = source[:15] if len(source) > 15 else source

        print(f"| {date_str} | {source} | {headline} | {sentiment} | {compound:+.2f} | {catalyst_str} |")

    # --- Table 2: Sentiment Summary ---
    print(f"\n### Sentiment Summary")
    print("| Metric | Value |")
    print("| :--- | :--- |")

    total = len(articles)
    positive = sum(1 for a in articles if a['sentiment'] == 'Positive')
    neutral = sum(1 for a in articles if a['sentiment'] == 'Neutral')
    negative = sum(1 for a in articles if a['sentiment'] == 'Negative')
    avg_score = sum(a['score'] for a in articles) / total if total > 0 else 0

    if avg_score > 0.1:
        overall = "Bullish"
    elif avg_score < -0.1:
        overall = "Bearish"
    else:
        overall = "Neutral"

    print(f"| Articles Analyzed | {total} |")
    print(f"| Positive | {positive} ({positive/total*100:.0f}%) |")
    print(f"| Neutral | {neutral} ({neutral/total*100:.0f}%) |")
    print(f"| Negative | {negative} ({negative/total*100:.0f}%) |")
    print(f"| Average Score | {avg_score:+.3f} |")
    print(f"| Overall Sentiment | **{overall}** |")

    # --- Table 3: Detected Catalysts ---
    if catalyst_counts:
        print(f"\n### Detected Catalysts")
        print("| Category | Count | Headlines |")
        print("| :--- | :--- | :--- |")

        for category, count in sorted(catalyst_counts.items(), key=lambda x: x[1], reverse=True):
            # Find matching headlines
            matching = []
            for item in news[:20]:
                content = item.get('content', item)
                if isinstance(content, dict):
                    t = content.get('title', item.get('title', ''))
                else:
                    t = item.get('title', '')
                t_lower = t.lower()
                if any(kw in t_lower for kw in CATALYST_KEYWORDS.get(category, [])):
                    short_title = t[:40] + ".." if len(t) > 40 else t
                    short_title = short_title.replace('|', '-')
                    matching.append(short_title)
            headlines = "; ".join(matching[:2])
            print(f"| {category} | {count} | {headlines} |")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 news_sentiment.py <TICKER>")
    else:
        analyze_news(sys.argv[1].upper())
