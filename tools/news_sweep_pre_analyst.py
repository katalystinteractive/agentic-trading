#!/usr/bin/env python3
"""News Sweep Pre-Analyst — mechanical pre-processor for Phase 2.

Reads news-sweep-raw.md and portfolio.json. Produces news-sweep-pre-analyst.md
with deterministic heatmap, risk flags, themes, and recommendation skeleton.
The LLM analyst reads this output and adds qualitative analysis only.

Usage: python3 tools/news_sweep_pre_analyst.py
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

# Same-directory imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
from news_sweep_collector import split_table_row

ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = ROOT / "news-sweep-raw.md"
PORTFOLIO_PATH = ROOT / "portfolio.json"
OUTPUT_PATH = ROOT / "news-sweep-pre-analyst.md"

EXCLUDED_CATALYST_CATEGORIES = {"Earnings"}

KEYWORD_THEMES = {
    "Bitcoin/Crypto": ["bitcoin", "btc", "crypto", "mining", "halving"],
    "AI Infrastructure": ["ai ", "data center", "gpu", "artificial intelligence"],
    "Interest Rate/Fed": ["fed ", "rate", "interest rate", "fomc"],
    "Commodity": ["iron ore", "nickel", "copper", "rare earth", "antimony"],
}


# ---------------------------------------------------------------------------
# Input Validation
# ---------------------------------------------------------------------------

def validate_inputs():
    """Check inputs exist and load them. Returns (raw_text, portfolio_dict) or exits."""
    if not RAW_PATH.exists():
        print(f"*Error: {RAW_PATH.name} not found — run news_sweep_collector.py first*")
        sys.exit(1)
    raw_text = RAW_PATH.read_text(encoding="utf-8")

    if not PORTFOLIO_PATH.exists():
        print(f"*Error: {PORTFOLIO_PATH.name} not found*")
        sys.exit(1)
    try:
        portfolio = json.loads(PORTFOLIO_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"*Error: {PORTFOLIO_PATH.name} malformed JSON: {e}*")
        sys.exit(1)

    return raw_text, portfolio


# ---------------------------------------------------------------------------
# Raw Data Parsing
# ---------------------------------------------------------------------------

def _parse_sweep_summary(lines):
    """Extract 7 metrics from the Sweep Summary table."""
    result = {}
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped == "## Sweep Summary":
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if not in_section:
            continue
        if not stripped.startswith("|") or stripped.startswith("| Metric") or stripped.startswith("| :"):
            continue
        cols = split_table_row(stripped)
        if len(cols) >= 2:
            key = cols[0].strip()
            val = cols[1].strip()
            result[key] = val
    return {
        "date": result.get("Date", ""),
        "tickers_swept": int(result.get("Tickers Swept", "0")),
        "tier1": int(result.get("Tier 1 (Active)", "0")),
        "tier2": int(result.get("Tier 2 (Pending)", "0")),
        "tier3": int(result.get("Tier 3 (Watch)", "0")),
        "no_news": int(result.get("No News Data", "0")),
        "failures": int(result.get("Failures", "0")),
    }


def _parse_portfolio_context(lines):
    """Parse the 9-column Portfolio Context table.

    Tier is read from col 1 as the single authoritative source.
    """
    def parse_price(s):
        s = s.strip().replace("$", "").replace(",", "")
        if s in ("—", "\u2014", "N/A", ""):
            return None
        try:
            return float(s)
        except ValueError:
            return None

    def parse_int_or_none(s):
        s = s.strip()
        if s in ("—", "\u2014", "N/A", ""):
            return None
        try:
            return int(s)
        except ValueError:
            return None

    def parse_float_or_none(s):
        s = s.strip()
        if s in ("—", "\u2014", "N/A", ""):
            return None
        try:
            return float(s)
        except ValueError:
            return None

    result = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped == "## Portfolio Context":
            in_section = True
            continue
        if in_section and (stripped.startswith("## ") or stripped == "---"):
            break
        if not in_section:
            continue
        if not stripped.startswith("|") or stripped.startswith("| Ticker") or stripped.startswith("| :"):
            continue
        cols = split_table_row(stripped)
        if len(cols) < 9:
            continue

        ticker = cols[0].strip()
        tier = int(cols[1].strip())
        current_price = parse_price(cols[2])
        day_chg = cols[3].strip()
        if day_chg in ("N/A", "—", "\u2014"):
            day_chg = None
        shares = parse_float_or_none(cols[4])
        avg_cost = parse_price(cols[5])
        target = parse_price(cols[6])
        pending_buys = parse_int_or_none(cols[7])
        pending_sells = parse_int_or_none(cols[8])

        result.append({
            "ticker": ticker,
            "tier": tier,
            "current_price": current_price,
            "day_chg": day_chg,
            "shares": shares,
            "avg_cost": avg_cost,
            "target": target,
            "pending_buys": pending_buys,
            "pending_sells": pending_sells,
        })
    return result


def _parse_sentiment_summary(section_lines):
    """Parse #### Sentiment Summary table from a ticker section.

    Returns dict or None if section not found.
    """
    in_section = False
    rows = {}
    for line in section_lines:
        stripped = line.strip()
        if stripped == "#### Sentiment Summary":
            in_section = True
            continue
        if in_section and stripped.startswith("####"):
            break
        if not in_section:
            continue
        if not stripped.startswith("|") or stripped.startswith("| Metric") or stripped.startswith("| :"):
            continue
        cols = split_table_row(stripped)
        if len(cols) >= 2:
            rows[cols[0].strip()] = cols[1].strip()

    if not rows:
        return None

    # Parse Overall Sentiment — strip bold markers
    overall = rows.get("Overall Sentiment", "")
    overall = overall.replace("**", "").strip()

    # Parse Average Score
    avg_str = rows.get("Average Score", "0")
    try:
        avg_score = float(avg_str)
    except ValueError:
        avg_score = 0.0

    # Parse Positive count and percentage
    pos_match = re.match(r'(\d+)\s*\((\d+)%\)', rows.get("Positive", ""))
    pos_count = int(pos_match.group(1)) if pos_match else 0
    pos_pct = int(pos_match.group(2)) if pos_match else 0

    # Parse Negative count and percentage
    neg_match = re.match(r'(\d+)\s*\((\d+)%\)', rows.get("Negative", ""))
    neg_count = int(neg_match.group(1)) if neg_match else 0
    neg_pct = int(neg_match.group(2)) if neg_match else 0

    # Parse Neutral
    neut_match = re.match(r'(\d+)\s*\((\d+)%\)', rows.get("Neutral", ""))
    neut_count = int(neut_match.group(1)) if neut_match else 0

    # Articles analyzed
    articles_str = rows.get("Articles Analyzed", "0")
    try:
        articles = int(articles_str)
    except ValueError:
        articles = 0

    return {
        "overall_sentiment": overall,
        "avg_score": avg_score,
        "positive_count": pos_count,
        "positive_pct": pos_pct,
        "negative_count": neg_count,
        "negative_pct": neg_pct,
        "neutral_count": neut_count,
        "articles_analyzed": articles,
    }


def _parse_catalysts(section_lines):
    """Parse #### Detected Catalysts table from a ticker section.

    Returns list of dicts or empty list if section not found.
    """
    in_section = False
    rows = []
    for line in section_lines:
        stripped = line.strip()
        if stripped == "#### Detected Catalysts":
            in_section = True
            continue
        if in_section and stripped.startswith("####"):
            break
        if not in_section:
            continue
        # Handle "No catalysts detected." text
        if in_section and "no catalysts detected" in stripped.lower():
            return []
        if not stripped.startswith("|") or stripped.startswith("| Category") or stripped.startswith("| :"):
            continue
        cols = split_table_row(stripped)
        if len(cols) >= 3:
            try:
                count = int(cols[1].strip())
            except (ValueError, IndexError):
                count = 0
            rows.append({
                "category": cols[0].strip(),
                "count": count,
                "headlines": cols[2].strip(),
            })
    return rows


def _parse_headlines(section_lines):
    """Parse #### Top Headlines table from a ticker section.

    Returns list of dicts or empty list.
    """
    in_section = False
    rows = []
    for line in section_lines:
        stripped = line.strip()
        if stripped == "#### Top Headlines":
            in_section = True
            continue
        if in_section and stripped.startswith("####"):
            break
        if not in_section:
            continue
        if not stripped.startswith("|") or stripped.startswith("| Date") or stripped.startswith("| :"):
            continue
        cols = split_table_row(stripped)
        if len(cols) >= 5:
            rows.append({
                "date": cols[0].strip(),
                "source": cols[1].strip(),
                "headline": cols[2].strip(),
                "sentiment": cols[3].strip(),
                "score": cols[4].strip(),
            })
    return rows


def _parse_ticker_sections(lines):
    """Split raw data into per-ticker sections by ### headers.

    Returns dict keyed by ticker with parsed data.
    """
    tickers = {}
    current_ticker = None
    current_lines = []

    for line in lines:
        stripped = line.strip()
        # Match ### TICKER (but not #### subsections)
        match = re.match(r'^### ([A-Z]+)$', stripped)
        if match:
            if current_ticker:
                tickers[current_ticker] = current_lines
            current_ticker = match.group(1)
            current_lines = []
            continue
        if current_ticker is not None:
            current_lines.append(line)

    if current_ticker:
        tickers[current_ticker] = current_lines

    result = {}
    for ticker, section_lines in tickers.items():
        section_text = "\n".join(section_lines)

        no_news = "*No news data available.*" in section_text
        failure = "*Tool error" in section_text

        sentiment = None
        catalysts = []
        top_headlines = []

        if not no_news and not failure:
            sentiment = _parse_sentiment_summary(section_lines)
            catalysts = _parse_catalysts(section_lines)
            top_headlines = _parse_headlines(section_lines)

        result[ticker] = {
            "sentiment": sentiment,
            "catalysts": catalysts,
            "top_headlines": top_headlines,
            "no_news": no_news,
            "failure": failure,
        }

    return result


def _parse_failures(lines):
    """Extract failure list from ## Failures section."""
    in_section = False
    failures = []
    for line in lines:
        stripped = line.strip()
        if stripped == "## Failures":
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if not in_section:
            continue
        if stripped.startswith("- "):
            failures.append(stripped[2:])
    return failures


def parse_raw_data(raw_text):
    """Master parser — returns structured dict from news-sweep-raw.md."""
    lines = raw_text.split("\n")

    sweep_summary = _parse_sweep_summary(lines)
    portfolio_context = _parse_portfolio_context(lines)
    ticker_data = _parse_ticker_sections(lines)
    failures = _parse_failures(lines)

    # Assign tier from portfolio context to each ticker
    tier_map = {pc["ticker"]: pc["tier"] for pc in portfolio_context}
    for ticker, data in ticker_data.items():
        data["tier"] = tier_map.get(ticker, 3)

    return {
        "date": sweep_summary["date"],
        "sweep_summary": sweep_summary,
        "portfolio_context": portfolio_context,
        "tickers": ticker_data,
        "failures": failures,
    }


# ---------------------------------------------------------------------------
# Pending Orders
# ---------------------------------------------------------------------------

def get_pending_orders(portfolio):
    """Extract pending orders by ticker, separated into buys and sells.

    Skips orders with PAUSED in the note — these are intentionally
    suspended and should not trigger risk flags.
    """
    result = {}
    pending = portfolio.get("pending_orders", {})
    for ticker, orders in pending.items():
        if not isinstance(orders, list):
            continue
        buys = []
        sells = []
        for order in orders:
            # Skip PAUSED orders
            note = order.get("note", "")
            if "PAUSED" in note.upper():
                continue
            order_type = order.get("type", "").upper()
            if order_type == "BUY":
                buys.append(order)
            elif order_type == "SELL":
                sells.append(order)
        result[ticker] = {"buys": buys, "sells": sells}
    return result


# ---------------------------------------------------------------------------
# Heatmap
# ---------------------------------------------------------------------------

def build_heatmap(raw_data):
    """Build sorted heatmap rows + distribution counts.

    Returns (rows, distribution) where rows is list of dicts and
    distribution is {"bullish": N, "neutral": N, "bearish": N, "no_data": N}.
    """
    pc_lookup = {pc["ticker"]: pc for pc in raw_data["portfolio_context"]}
    rows = []
    dist = {"bullish": 0, "neutral": 0, "bearish": 0, "no_data": 0}

    for ticker, data in raw_data["tickers"].items():
        pc = pc_lookup.get(ticker, {})
        tier = data.get("tier", 3)
        current_price = pc.get("current_price")

        if data["no_news"] or data["failure"] or data["sentiment"] is None:
            rows.append({
                "ticker": ticker,
                "tier": tier,
                "current_price": current_price,
                "overall_sentiment": "N/A",
                "avg_score": None,
                "pos_pct": "N/A",
                "neg_pct": "N/A",
                "top_catalyst": "N/A",
                "is_na": True,
            })
            dist["no_data"] += 1
            continue

        sent = data["sentiment"]

        # Top catalyst: highest count category
        top_catalyst = "\u2014"
        if data["catalysts"]:
            sorted_cats = sorted(data["catalysts"], key=lambda c: (-c["count"], c["category"]))
            top_catalyst = sorted_cats[0]["category"]

        overall = sent["overall_sentiment"]
        if overall == "Bullish":
            dist["bullish"] += 1
        elif overall == "Bearish":
            dist["bearish"] += 1
        elif overall == "Neutral":
            dist["neutral"] += 1

        rows.append({
            "ticker": ticker,
            "tier": tier,
            "current_price": current_price,
            "overall_sentiment": overall,
            "avg_score": sent["avg_score"],
            "pos_pct": f"{sent['positive_pct']}%",
            "neg_pct": f"{sent['negative_pct']}%",
            "top_catalyst": top_catalyst,
            "is_na": False,
        })

    # Sort: tier ascending, then avg_score ascending within tier, N/A at bottom
    def sort_key(r):
        score = r["avg_score"] if r["avg_score"] is not None else float('inf')
        return (r["tier"], score, r["ticker"])

    rows.sort(key=sort_key)

    return rows, dist


# ---------------------------------------------------------------------------
# Risk Flags
# ---------------------------------------------------------------------------

def detect_risk_flags(raw_data, pending_orders):
    """Detect all 5 risk flag types. Returns list of flag dicts."""
    flags = []
    pc_lookup = {pc["ticker"]: pc for pc in raw_data["portfolio_context"]}

    for ticker, data in raw_data["tickers"].items():
        if data["no_news"] or data["failure"] or data["sentiment"] is None:
            continue

        tier = data["tier"]
        overall = data["sentiment"]["overall_sentiment"]
        avg_score = data["sentiment"]["avg_score"]
        pc = pc_lookup.get(ticker, {})
        current_price = pc.get("current_price")
        orders = pending_orders.get(ticker, {"buys": [], "sells": []})
        catalyst_categories = {c["category"] for c in data["catalysts"]}

        # Type A: Tier 1 AND Bearish
        if tier == 1 and overall == "Bearish":
            flags.append({
                "type": "A",
                "ticker": ticker,
                "finding": f"Bearish ({avg_score:+.3f}); Tier 1 active position",
            })

        # Type B: Bearish AND has pending BUY orders
        if overall == "Bearish" and len(orders["buys"]) > 0:
            flags.append({
                "type": "B",
                "ticker": ticker,
                "finding": f"Bearish ({avg_score:+.3f}); {len(orders['buys'])} pending BUY orders",
            })

        # Type C: Tier 1 AND Bullish AND pending SELL AND current >= 85% of sell_price
        if tier == 1 and overall == "Bullish" and current_price is not None:
            for sell_order in orders["sells"]:
                sell_price = sell_order.get("price")
                if sell_price is None:
                    continue
                if current_price >= sell_price:
                    continue  # Already at/above target
                pct_of_target = current_price / sell_price * 100
                if pct_of_target >= 85.0:
                    flags.append({
                        "type": "C",
                        "ticker": ticker,
                        "finding": (f"Bullish ({avg_score:+.3f}); pending SELL ${sell_price:.2f}; "
                                    f"current ${current_price:.2f} = {pct_of_target:.1f}% of target"),
                        "pct_of_target": pct_of_target,
                    })

        # Type D: "Equity" in catalyst categories
        if "Equity" in catalyst_categories:
            equity_cat = next((c for c in data["catalysts"] if c["category"] == "Equity"), None)
            headlines_text = equity_cat["headlines"] if equity_cat else ""
            flags.append({
                "type": "D",
                "ticker": ticker,
                "finding": f"Equity catalyst detected: {headlines_text}",
            })

        # Type E: Tier 1 or 2 AND "Earnings" in catalyst categories
        if tier in (1, 2) and "Earnings" in catalyst_categories:
            earnings_cat = next((c for c in data["catalysts"] if c["category"] == "Earnings"), None)
            earnings_headlines = earnings_cat["headlines"] if earnings_cat else ""
            # Include top headlines full text for date extraction
            top_headlines_text = []
            for hl in data["top_headlines"]:
                top_headlines_text.append(f"{hl['date']} | {hl['headline']}")
            flags.append({
                "type": "E",
                "ticker": ticker,
                "tier": tier,
                "finding": (f"Tier {tier}; Earnings catalyst detected"),
                "earnings_headlines": earnings_headlines,
                "top_headlines": top_headlines_text,
            })

    # Sort by type priority (A→E) then ticker alphabetically
    type_priority = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
    flags.sort(key=lambda f: (type_priority.get(f["type"], 9), f["ticker"]))

    # Assign sequential flag numbers
    for i, flag in enumerate(flags):
        flag["flag_num"] = i + 1

    return flags


# ---------------------------------------------------------------------------
# Theme Detection
# ---------------------------------------------------------------------------

def _keyword_matches_text(keyword, text):
    """Check keyword match using word-boundary prefix for single words, substring for phrases.

    Single words use \\b prefix to avoid false positives (e.g. "rate" in "corporate").
    Multi-word phrases use substring matching (already specific enough).
    Trailing spaces in keywords (e.g. "ai ") are stripped — word boundary handles it.
    """
    kw = keyword.strip().lower()
    if " " in kw:
        return kw in text.lower()
    return bool(re.search(r"\b" + re.escape(kw), text, re.IGNORECASE))


# Catalyst categories appearing in >50% of non-NA tickers are too generic for themes
CATALYST_PREVALENCE_THRESHOLD = 0.50


def detect_themes(raw_data):
    """Detect cross-ticker themes via catalyst aggregation and keyword matching.

    Returns list of theme dicts.
    """
    themes = []
    non_na_count = sum(1 for d in raw_data["tickers"].values()
                       if not d["no_news"] and not d["failure"])

    # --- Catalyst aggregation ---
    cat_map = {}  # category -> [ticker]
    for ticker, data in raw_data["tickers"].items():
        if data["no_news"] or data["failure"]:
            continue
        for cat in data["catalysts"]:
            category = cat["category"]
            if category in EXCLUDED_CATALYST_CATEGORIES:
                continue
            cat_map.setdefault(category, []).append(ticker)

    for category, tickers_list in cat_map.items():
        unique_tickers = sorted(set(tickers_list))
        if len(unique_tickers) < 2:
            continue
        # Skip categories that are too generic (appear in >50% of tickers)
        if non_na_count > 0 and len(unique_tickers) / non_na_count > CATALYST_PREVALENCE_THRESHOLD:
            continue

        direction = _compute_direction(raw_data, unique_tickers)
        urgency = _compute_urgency(raw_data, unique_tickers)

        matched_headlines = {}
        for t in unique_tickers:
            t_data = raw_data["tickers"].get(t, {})
            for cat in t_data.get("catalysts", []):
                if cat["category"] == category:
                    matched_headlines.setdefault(t, []).append(cat["headlines"])

        themes.append({
            "name": f"{category} Catalyst",
            "basis": "catalyst_aggregation",
            "category": category,
            "tickers": unique_tickers,
            "direction": direction,
            "urgency": urgency,
            "matched_headlines": matched_headlines,
        })

    # --- Keyword matching ---
    for theme_name, keywords in KEYWORD_THEMES.items():
        matched_tickers = []
        matched_headlines = {}
        for ticker, data in raw_data["tickers"].items():
            if data["no_news"] or data["failure"]:
                continue
            all_text_parts = []
            for hl in data.get("top_headlines", []):
                all_text_parts.append(hl.get("headline", ""))
            for cat in data.get("catalysts", []):
                all_text_parts.append(cat.get("headlines", ""))
            all_text = " ".join(all_text_parts)

            if any(_keyword_matches_text(kw, all_text) for kw in keywords):
                matched_tickers.append(ticker)
                ticker_matches = []
                for hl in data.get("top_headlines", []):
                    if any(_keyword_matches_text(kw, hl.get("headline", "")) for kw in keywords):
                        ticker_matches.append(hl["headline"])
                for cat in data.get("catalysts", []):
                    if any(_keyword_matches_text(kw, cat.get("headlines", "")) for kw in keywords):
                        ticker_matches.append(cat["headlines"])
                if ticker_matches:
                    matched_headlines[ticker] = ticker_matches

        if len(matched_tickers) < 2:
            continue

        direction = _compute_direction(raw_data, matched_tickers)
        urgency = _compute_urgency(raw_data, matched_tickers)

        themes.append({
            "name": theme_name,
            "basis": "keyword_matching",
            "tickers": sorted(set(matched_tickers)),
            "direction": direction,
            "urgency": urgency,
            "matched_headlines": matched_headlines,
        })

    # --- Dedup: merge overlapping themes (bidirectional >50%) ---
    themes = _dedup_themes(themes)

    return themes


def _compute_direction(raw_data, tickers):
    """Compute majority sentiment direction for a list of tickers."""
    counts = {"Bullish": 0, "Neutral": 0, "Bearish": 0}
    for t in tickers:
        data = raw_data["tickers"].get(t, {})
        if data.get("sentiment"):
            overall = data["sentiment"]["overall_sentiment"]
            if overall in counts:
                counts[overall] += 1
    if counts["Bullish"] > counts["Bearish"]:
        return "Bullish"
    if counts["Bearish"] > counts["Bullish"]:
        return "Bearish"
    if counts["Bullish"] == counts["Bearish"] and counts["Bullish"] > 0:
        return "Mixed"
    return "Neutral"


def _compute_urgency(raw_data, tickers):
    """Compute urgency from Tier 1 count: 0=Low, 1-2=Medium, 3+=High."""
    t1_count = sum(1 for t in tickers
                   if raw_data["tickers"].get(t, {}).get("tier") == 1)
    if t1_count >= 3:
        return "High"
    if t1_count >= 1:
        return "Medium"
    return "Low"


def _dedup_themes(themes):
    """Merge themes that share >50% overlap on BOTH sides (bidirectional).

    Bidirectional check prevents small specific themes (e.g. 2-ticker Bitcoin/Crypto)
    from being absorbed into large generic themes (e.g. 8-ticker Analyst Catalyst).
    """
    merged = []
    used = set()

    for i, t1 in enumerate(themes):
        if i in used:
            continue
        current = t1.copy()
        current_tickers = set(t1["tickers"])

        for j, t2 in enumerate(themes):
            if j <= i or j in used:
                continue
            t2_tickers = set(t2["tickers"])
            overlap = current_tickers & t2_tickers
            if not overlap:
                continue
            # Bidirectional: overlap must be >50% of BOTH sets
            pct_of_current = len(overlap) / len(current_tickers) if current_tickers else 0
            pct_of_t2 = len(overlap) / len(t2_tickers) if t2_tickers else 0
            if pct_of_current > 0.5 and pct_of_t2 > 0.5:
                current_tickers |= t2_tickers
                current["tickers"] = sorted(current_tickers)
                if t2["basis"] == "keyword_matching" and current["basis"] == "catalyst_aggregation":
                    current["name"] = t2["name"]
                    current["basis"] = t2["basis"]
                for tk, hls in t2.get("matched_headlines", {}).items():
                    current.setdefault("matched_headlines", {}).setdefault(tk, []).extend(hls)
                used.add(j)

        merged.append(current)
        used.add(i)

    return merged


# ---------------------------------------------------------------------------
# Recommendation Skeleton
# ---------------------------------------------------------------------------

def build_recommendation_skeleton(flags, themes):
    """Map flags to recommendation categories, themes with 3+ tickers to Theme Awareness.

    Group all Type E flags for the same ticker into one entry.
    """
    recs = []
    # Category mapping
    type_to_category = {
        "A": "Immediate Review",
        "E": "Earnings Gate",
        "D": "Dilution Risk",
        "B": "Pending Order Review",
        "C": "Positive Momentum",
    }
    category_priority = {
        "Immediate Review": 0,
        "Earnings Gate": 1,
        "Dilution Risk": 2,
        "Pending Order Review": 3,
        "Positive Momentum": 4,
        "Theme Awareness": 5,
    }

    # Group Type E flags by ticker
    type_e_by_ticker = {}
    for flag in flags:
        if flag["type"] == "E":
            type_e_by_ticker.setdefault(flag["ticker"], []).append(flag)

    # Process non-E flags
    for flag in flags:
        if flag["type"] == "E":
            continue
        category = type_to_category.get(flag["type"], "Other")
        recs.append({
            "category": category,
            "ticker": flag["ticker"],
            "finding": flag["finding"],
            "next_step": "(LLM)",
        })

    # Process grouped Type E flags
    for ticker, e_flags in sorted(type_e_by_ticker.items()):
        # Combine findings
        findings = "; ".join(f["finding"] for f in e_flags)
        # Include earnings headlines for LLM imminence assessment
        all_earnings_headlines = []
        for ef in e_flags:
            if ef.get("earnings_headlines"):
                all_earnings_headlines.append(ef["earnings_headlines"])
        earnings_context = " | ".join(all_earnings_headlines) if all_earnings_headlines else ""

        recs.append({
            "category": "Earnings Gate",
            "ticker": ticker,
            "finding": findings,
            "earnings_context": earnings_context,
            "next_step": "(LLM)",
        })

    # Themes with 3+ tickers
    for theme in themes:
        if len(theme["tickers"]) >= 3:
            recs.append({
                "category": "Theme Awareness",
                "ticker": ", ".join(theme["tickers"]),
                "finding": f"{theme['name']} — {theme['direction']}, {theme['urgency']} urgency",
                "next_step": "(LLM)",
            })

    # Sort by priority
    recs.sort(key=lambda r: (category_priority.get(r["category"], 99), r["ticker"]))

    return recs


# ---------------------------------------------------------------------------
# Report Builder
# ---------------------------------------------------------------------------

def build_report(raw_data, heatmap_rows, distribution, flags, themes, recs):
    """Assemble news-sweep-pre-analyst.md — self-contained output for the LLM analyst."""
    today_str = raw_data["date"] or date.today().isoformat()
    lines = []

    lines.append(f"# News Sweep Pre-Analyst — {today_str}")
    lines.append(f"*Generated by news_sweep_pre_analyst.py | Mechanical pre-processing for Phase 2*")
    lines.append("")

    # --- Portfolio Context Summary ---
    lines.append("## Portfolio Context")
    lines.append("| Ticker | Tier | Current Price | Day Chg% | Shares | Avg Cost | Target | Pending Buys | Pending Sells |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for pc in raw_data["portfolio_context"]:
        price_str = f"${pc['current_price']:.2f}" if pc['current_price'] is not None else "N/A"
        day_str = pc['day_chg'] if pc['day_chg'] else "N/A"
        if pc['shares'] is not None:
            shares_str = str(int(pc['shares'])) if pc['shares'] == int(pc['shares']) else f"{pc['shares']:.2f}"
        else:
            shares_str = "\u2014"
        avg_str = f"${pc['avg_cost']:.2f}" if pc['avg_cost'] is not None else "\u2014"
        target_str = f"${pc['target']:.2f}" if pc['target'] is not None else "\u2014"
        buys_str = str(pc['pending_buys']) if pc['pending_buys'] is not None else "\u2014"
        sells_str = str(pc['pending_sells']) if pc['pending_sells'] is not None else "\u2014"
        lines.append(f"| {pc['ticker']} | {pc['tier']} | {price_str} | {day_str} | "
                      f"{shares_str} | {avg_str} | {target_str} | {buys_str} | {sells_str} |")
    lines.append("")

    # --- Sentiment Heatmap ---
    lines.append("## Sentiment Heatmap")
    lines.append("")
    current_tier = None
    tier_labels = {1: "Tier 1 \u2014 Active Positions", 2: "Tier 2 \u2014 Pending Entry", 3: "Tier 3 \u2014 Watch Only"}
    for row in heatmap_rows:
        if row["tier"] != current_tier:
            current_tier = row["tier"]
            lines.append(f"### {tier_labels.get(current_tier, f'Tier {current_tier}')}")
            lines.append("| Ticker | Tier | Current Price | Overall Sentiment | Avg Score | Pos% | Neg% | Top Catalyst |")
            lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

        price_str = f"${row['current_price']:.2f}" if row['current_price'] is not None else "N/A"
        if row["is_na"]:
            lines.append(f"| {row['ticker']} | {row['tier']} | {price_str} | N/A | N/A | N/A | N/A | N/A |")
        else:
            score_str = f"{row['avg_score']:+.3f}" if row['avg_score'] is not None else "N/A"
            lines.append(f"| {row['ticker']} | {row['tier']} | {price_str} | "
                          f"{row['overall_sentiment']} | {score_str} | {row['pos_pct']} | "
                          f"{row['neg_pct']} | {row['top_catalyst']} |")
    lines.append("")
    lines.append(f"**Distribution:** {distribution['bullish']} Bullish / {distribution['neutral']} Neutral / "
                  f"{distribution['bearish']} Bearish / {distribution['no_data']} No Data")
    lines.append("")

    # --- Risk Flags ---
    lines.append("## Risk Flags")
    if not flags:
        lines.append("No sentiment-position conflicts detected.")
    else:
        lines.append("| # | Type | Ticker | Finding |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for f in flags:
            lines.append(f"| {f['flag_num']} | {f['type']} | {f['ticker']} | {f['finding']} |")
        lines.append("")

        # Type E detail: include earnings headlines + top headlines for date extraction
        type_e_flags = [f for f in flags if f["type"] == "E"]
        if type_e_flags:
            lines.append("### Earnings Flag Detail (for LLM imminence assessment)")
            for ef in type_e_flags:
                lines.append(f"**Flag {ef['flag_num']} — {ef['ticker']} (Tier {ef.get('tier', '?')}):**")
                if ef.get("earnings_headlines"):
                    lines.append(f"- Earnings catalyst headlines: {ef['earnings_headlines']}")
                if ef.get("top_headlines"):
                    lines.append("- Top Headlines (full text):")
                    for hl in ef["top_headlines"]:
                        lines.append(f"  - {hl}")
                lines.append("")
    lines.append("")

    # --- Cross-Ticker Themes ---
    lines.append("## Cross-Ticker Themes")
    if not themes:
        lines.append("No cross-ticker themes detected.")
    else:
        for theme in themes:
            tickers_str = ", ".join(theme["tickers"])
            lines.append(f"### {theme['name']}")
            lines.append(f"**Tickers:** {tickers_str} | **Direction:** {theme['direction']} | **Urgency:** {theme['urgency']}")
            lines.append(f"**Basis:** {theme['basis']}")
            # Include matched headlines context
            if theme.get("matched_headlines"):
                lines.append("**Relevant Headlines:**")
                for ticker, hls in sorted(theme["matched_headlines"].items()):
                    for hl in hls:
                        lines.append(f"- {ticker}: {hl}")
            lines.append("*(LLM: write 1-2 sentence theme narrative)*")
            lines.append("")
    lines.append("")

    # --- Recommendation Skeleton ---
    lines.append("## Recommendation Skeleton")
    if not recs:
        lines.append("No actionable items at this time.")
    else:
        lines.append("| # | Category | Ticker | Finding | Next Step |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for i, rec in enumerate(recs, 1):
            lines.append(f"| {i} | {rec['category']} | {rec['ticker']} | {rec['finding']} | {rec['next_step']} |")
        lines.append("")

        # Type E earnings context for recommendations
        type_e_recs = [r for r in recs if r["category"] == "Earnings Gate" and r.get("earnings_context")]
        if type_e_recs:
            lines.append("### Earnings Context (for LLM imminence filtering)")
            for rec in type_e_recs:
                lines.append(f"- **{rec['ticker']}:** {rec['earnings_context']}")
            lines.append("")
    lines.append("")

    # --- Sweep Metadata ---
    lines.append("## Sweep Metadata")
    lines.append("| Metric | Value |")
    lines.append("| :--- | :--- |")
    lines.append(f"| Report Date | {today_str} |")
    lines.append(f"| Tickers Analyzed | {raw_data['sweep_summary']['tickers_swept']} |")
    lines.append("| Data Source | news_sentiment.py (Finviz, Google News, yfinance) |")
    lines.append("| Sentiment Method | VADER / Keyword fallback |")
    lines.append("| Pre-Processor | news_sweep_pre_analyst.py |")
    lines.append("| Disclaimer | Informational only. Not trading advice. Review raw data before acting. |")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("News Sweep Pre-Analyst")
    print("=" * 40)

    raw_text, portfolio = validate_inputs()
    raw_data = parse_raw_data(raw_text)
    pending_orders = get_pending_orders(portfolio)

    print(f"Date: {raw_data['date']}")
    print(f"Tickers: {raw_data['sweep_summary']['tickers_swept']} "
          f"(T1:{raw_data['sweep_summary']['tier1']} "
          f"T2:{raw_data['sweep_summary']['tier2']} "
          f"T3:{raw_data['sweep_summary']['tier3']})")

    heatmap_rows, distribution = build_heatmap(raw_data)
    print(f"Heatmap: {len(heatmap_rows)} rows — "
          f"{distribution['bullish']}B/{distribution['neutral']}N/"
          f"{distribution['bearish']}Be/{distribution['no_data']}ND")

    flags = detect_risk_flags(raw_data, pending_orders)
    type_counts = {}
    for f in flags:
        type_counts[f["type"]] = type_counts.get(f["type"], 0) + 1
    type_summary = ", ".join(f"{k}:{v}" for k, v in sorted(type_counts.items()))
    print(f"Risk flags: {len(flags)} ({type_summary})")

    themes = detect_themes(raw_data)
    print(f"Themes: {len(themes)}")
    for t in themes:
        print(f"  {t['name']}: {', '.join(t['tickers'])} [{t['direction']}, {t['urgency']}]")

    recs = build_recommendation_skeleton(flags, themes)
    print(f"Recommendations: {len(recs)}")

    report = build_report(raw_data, heatmap_rows, distribution, flags, themes, recs)
    OUTPUT_PATH.write_text(report, encoding="utf-8")

    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"\nWrote {OUTPUT_PATH.name} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
