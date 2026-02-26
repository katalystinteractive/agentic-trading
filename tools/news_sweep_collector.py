#!/usr/bin/env python3
"""
News Sweep Collector — Runs news_sentiment.py for all portfolio tickers in parallel.

Replaces the LLM-based news-sweeper agent that ran tools sequentially with zero
qualitative work. This script runs all tools as subprocesses in parallel (~1 min
vs ~4 min sequential), parses outputs, and writes news-sweep-raw.md.

Usage: python3 tools/news_sweep_collector.py
"""

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO = PROJECT_ROOT / "portfolio.json"
TOOLS_DIR = PROJECT_ROOT / "tools"
OUTPUT = PROJECT_ROOT / "news-sweep-raw.md"


def _split_table_row(line):
    """Split a markdown table row into columns, stripping padding and empty edge cells."""
    cols = [p.strip() for p in line.split("|")]
    if cols and cols[0] == "":
        cols = cols[1:]
    if cols and cols[-1] == "":
        cols = cols[:-1]
    return cols


def run_tool(tool_name, args=None, timeout=90):
    """Run a Python tool and capture stdout. Returns (stdout, error_or_None)."""
    cmd = ["python3", str(TOOLS_DIR / tool_name)]
    if args:
        cmd.extend(args)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=str(PROJECT_ROOT)
        )
        if result.returncode != 0:
            err = result.stderr.strip() or f"Exit code {result.returncode}"
            return result.stdout.strip(), f"*Error running {tool_name}: {err}*"
        return result.stdout.strip(), None
    except subprocess.TimeoutExpired:
        return "", f"*Error: {tool_name} timed out after {timeout}s*"
    except Exception as e:
        return "", f"*Error running {tool_name}: {e}*"


def load_portfolio():
    """Read portfolio.json. Exit with error if missing/malformed."""
    try:
        with open(PORTFOLIO, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"*Error: {PORTFOLIO} not found*")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"*Error: {PORTFOLIO} malformed JSON: {e}*")
        sys.exit(1)


def classify_tickers(portfolio):
    """Returns {"tier1": [...], "tier2": [...], "tier3": [...]} sorted alphabetically."""
    positions = portfolio.get("positions", {})
    pending_orders = portfolio.get("pending_orders", {})
    watchlist = portfolio.get("watchlist", [])

    universe = set(positions.keys()) | set(pending_orders.keys()) | set(watchlist)

    tier1 = set()
    tier2 = set()
    tier3 = set()

    for ticker in universe:
        # Tier 1: active position with shares > 0
        pos = positions.get(ticker, {})
        shares = pos.get("shares", 0)
        if isinstance(shares, (int, float)) and shares > 0:
            tier1.add(ticker)
            continue

        # Tier 2: non-empty pending orders AND not Tier 1
        orders = pending_orders.get(ticker, [])
        if isinstance(orders, list) and len(orders) > 0:
            tier2.add(ticker)
            continue

        # Tier 3: everything remaining
        tier3.add(ticker)

    return {
        "tier1": sorted(tier1),
        "tier2": sorted(tier2),
        "tier3": sorted(tier3),
    }


def parse_portfolio_status(stdout):
    """Parse portfolio_status.py output for current prices + day change %.

    Parses 3 tables:
    - Active Positions (10 cols): ticker from col 0, price from col 3
    - Watchlist (5 cols): ticker from col 0, price from col 1, day_pct from col 4
    - Pending Orders (10 cols): ticker from col 0, current market price from col 4 (deduplicated)

    Merge: price priority Active > Watchlist > Pending. day_pct from Watchlist only.
    Returns {ticker: {"price": float|None, "day_pct": str|None}}.
    """
    active_prices = {}
    watchlist_data = {}    # ticker -> (price, day_pct)
    pending_market_prices = {}    # ticker -> current market price from col 4 (first occurrence only)

    section = None
    for line in stdout.split("\n"):
        stripped = line.strip()

        # Detect section headers
        if stripped.startswith("## Active Positions"):
            section = "active"
            continue
        elif stripped.startswith("## Pending Orders"):
            section = "pending"
            continue
        elif stripped.startswith("## Watchlist"):
            section = "watchlist"
            continue
        elif stripped.startswith("## "):
            section = None
            continue

        # Skip non-data rows and lines outside a known section
        if section is None:
            continue
        if not stripped.startswith("|") or stripped.startswith("| Ticker") or stripped.startswith("| :"):
            continue

        cols = _split_table_row(stripped)
        if not cols:
            continue

        ticker = cols[0]

        if section == "active" and len(cols) >= 4:
            price_str = cols[3].replace("$", "").replace(",", "")
            try:
                active_prices[ticker] = float(price_str)
            except ValueError:
                pass

        elif section == "watchlist" and len(cols) >= 5:
            price_str = cols[1].replace("$", "").replace(",", "")
            day_pct = cols[4]
            try:
                watchlist_data[ticker] = (float(price_str), day_pct)
            except ValueError:
                pass

        elif section == "pending" and len(cols) >= 5:
            price_str = cols[4].replace("$", "").replace(",", "")
            try:
                if ticker not in pending_market_prices:
                    pending_market_prices[ticker] = float(price_str)
            except ValueError:
                pass

    # Merge: price priority Active > Watchlist > Pending; day_pct from Watchlist only
    all_tickers = set(active_prices.keys()) | set(watchlist_data.keys()) | set(pending_market_prices.keys())
    result = {}
    for ticker in all_tickers:
        price = None
        if ticker in active_prices:
            price = active_prices[ticker]
        elif ticker in watchlist_data:
            price = watchlist_data[ticker][0]
        elif ticker in pending_market_prices:
            price = pending_market_prices[ticker]

        day_pct = watchlist_data[ticker][1] if ticker in watchlist_data else None
        result[ticker] = {"price": price, "day_pct": day_pct}

    return result


def parse_sentiment_summary(stdout):
    """Find ### Sentiment Summary, extract rows between header and next ### or end.
    Returns list of (metric, value) tuples or None.

    TODO: If news_sentiment.py changes its section headers, these parsers break
    silently (return None). Consider adding a warning when a non-error, non-no-news
    ticker yields no parsed sections.
    """
    lines = stdout.split("\n")
    in_section = False
    rows = []

    for line in lines:
        stripped = line.strip()
        if stripped == "### Sentiment Summary":
            in_section = True
            continue
        if in_section and stripped.startswith("###"):
            break
        if not in_section:
            continue
        if not stripped.startswith("|") or stripped.startswith("| Metric") or stripped.startswith("| :"):
            continue

        cols = _split_table_row(stripped)
        if len(cols) >= 2:
            rows.append((cols[0], cols[1]))

    return rows if rows else None


def parse_detected_catalysts(stdout):
    """Find ### Detected Catalysts, extract rows between header and next ### or end.
    Returns list of (category, count, headlines) or None."""
    lines = stdout.split("\n")
    in_section = False
    rows = []

    for line in lines:
        stripped = line.strip()
        if stripped == "### Detected Catalysts":
            in_section = True
            continue
        if in_section and stripped.startswith("###"):
            break
        if not in_section:
            continue
        if not stripped.startswith("|") or stripped.startswith("| Category") or stripped.startswith("| :"):
            continue

        cols = _split_table_row(stripped)
        if len(cols) >= 3:
            rows.append((cols[0], cols[1], cols[2]))

    return rows if rows else None


def parse_top_headlines(stdout, n=3):
    """Find ### Headlines (Top 30, extract first n data rows.
    Returns list of (date, source, headline, sentiment, score) — drops Catalysts column.
    Returns None if not found."""
    lines = stdout.split("\n")
    in_section = False
    rows = []

    for line in lines:
        stripped = line.strip()
        if "### Headlines (Top 30" in stripped:
            in_section = True
            continue
        if in_section and stripped.startswith("###"):
            break
        if not in_section:
            continue
        if not stripped.startswith("|") or stripped.startswith("| Date") or stripped.startswith("| :"):
            continue

        cols = _split_table_row(stripped)
        if len(cols) >= 5:
            # Take first 5 columns only (drop 6th Catalysts column)
            rows.append((cols[0], cols[1], cols[2], cols[3], cols[4]))
            if len(rows) >= n:
                break

    return rows if rows else None


def is_no_news(stdout):
    """Check for no-news marker in output."""
    return "No recent news available from any source" in stdout


def count_pending_orders(ticker_orders):
    """Count BUY vs SELL orders in a per-ticker order list.
    Returns (buy_count, sell_count)."""
    buy_count = 0
    sell_count = 0
    for order in ticker_orders:
        order_type = order.get("type", "").upper()
        if order_type == "BUY":
            buy_count += 1
        elif order_type == "SELL":
            sell_count += 1
    return buy_count, sell_count


def build_portfolio_context(tickers_by_tier, portfolio, prices):
    """Build the 9-column Portfolio Context table.

    Tier 1: all columns populated (with null guards).
    Tier 2: shares/avg/target = "—", pending sells = "—", pending buys from count_pending_orders().
    Tier 3: all "—" except Ticker/Tier/Price/DayChg%.
    """
    positions = portfolio.get("positions", {})
    pending_orders = portfolio.get("pending_orders", {})

    lines = []
    lines.append("## Portfolio Context")
    lines.append("| Ticker | Tier | Current Price | Day Chg% | Shares | Avg Cost | Target | Pending Buys | Pending Sells |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for tier_num, tier_key in [(1, "tier1"), (2, "tier2"), (3, "tier3")]:
        for ticker in tickers_by_tier[tier_key]:
            price_data = prices.get(ticker, {"price": None, "day_pct": None})
            price = price_data["price"]
            day_pct = price_data["day_pct"]

            price_str = f"${price:.2f}" if price is not None else "N/A"
            day_pct_str = day_pct if day_pct is not None else "N/A"

            if tier_num == 1:
                pos = positions.get(ticker, {})
                shares = pos.get("shares", 0)
                shares_str = str(int(shares)) if isinstance(shares, (int, float)) and shares > 0 else "\u2014"

                avg_cost = pos.get("avg_cost")
                avg_str = f"${avg_cost:.2f}" if avg_cost is not None else "\u2014"

                target = pos.get("target_exit")
                target_str = f"${target:.2f}" if isinstance(target, (int, float)) else "\u2014"

                orders = pending_orders.get(ticker, [])
                buys, sells = count_pending_orders(orders)
                buys_str = str(buys)
                sells_str = str(sells)

            elif tier_num == 2:
                shares_str = "\u2014"
                avg_str = "\u2014"
                target_str = "\u2014"

                orders = pending_orders.get(ticker, [])
                buys, _ = count_pending_orders(orders)
                buys_str = str(buys)
                sells_str = "\u2014"

            else:  # Tier 3
                shares_str = "\u2014"
                avg_str = "\u2014"
                target_str = "\u2014"
                buys_str = "\u2014"
                sells_str = "\u2014"

            lines.append(
                f"| {ticker} | {tier_num} | {price_str} | {day_pct_str} | "
                f"{shares_str} | {avg_str} | {target_str} | {buys_str} | {sells_str} |"
            )

    return "\n".join(lines)


def build_ticker_section(ticker, stdout, error):
    """Build per-ticker markdown block with Sentiment Summary, Catalysts, Top Headlines.
    Handles no-news and error cases."""
    lines = []
    lines.append(f"### {ticker}")

    if error and not stdout:
        lines.append("*Tool error \u2014 see Failures section.*")
        return "\n".join(lines)

    if is_no_news(stdout):
        lines.append("*No news data available.*")
        return "\n".join(lines)

    # Sentiment Summary
    lines.append("#### Sentiment Summary")
    summary = parse_sentiment_summary(stdout)
    if summary:
        lines.append("| Metric | Value |")
        lines.append("| :--- | :--- |")
        for metric, value in summary:
            lines.append(f"| {metric} | {value} |")
    else:
        lines.append("*No sentiment data available.*")
    lines.append("")

    # Detected Catalysts
    lines.append("#### Detected Catalysts")
    catalysts = parse_detected_catalysts(stdout)
    if catalysts:
        lines.append("| Category | Count | Headlines |")
        lines.append("| :--- | :--- | :--- |")
        for category, count, headlines in catalysts:
            lines.append(f"| {category} | {count} | {headlines} |")
    else:
        lines.append("No catalysts detected.")
    lines.append("")

    # Top Headlines
    lines.append("#### Top Headlines")
    headlines = parse_top_headlines(stdout, n=3)
    if headlines:
        lines.append("| Date | Source | Headline | Sentiment | Score |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for date_str, source, headline, sentiment, score in headlines:
            lines.append(f"| {date_str} | {source} | {headline} | {sentiment} | {score} |")
    else:
        lines.append("*No headlines available.*")

    return "\n".join(lines)


def build_output(tickers_by_tier, portfolio, prices, tool_results, failures):
    """Assemble complete news-sweep-raw.md matching exact existing format."""
    today_str = date.today().isoformat()

    total_tickers = sum(len(v) for v in tickers_by_tier.values())
    no_news_count = sum(
        1 for t in tool_results
        if is_no_news(tool_results[t][0])
    )

    parts = []

    # Title
    parts.append(f"# News Sweep Raw Data \u2014 {today_str}")
    parts.append("")

    # Sweep Summary
    parts.append("## Sweep Summary")
    parts.append("| Metric | Value |")
    parts.append("| :--- | :--- |")
    parts.append(f"| Date | {today_str} |")
    parts.append(f"| Tickers Swept | {total_tickers} |")
    parts.append(f"| Tier 1 (Active) | {len(tickers_by_tier['tier1'])} |")
    parts.append(f"| Tier 2 (Pending) | {len(tickers_by_tier['tier2'])} |")
    parts.append(f"| Tier 3 (Watch) | {len(tickers_by_tier['tier3'])} |")
    parts.append(f"| No News Data | {no_news_count} |")
    parts.append(f"| Failures | {len(failures)} |")
    parts.append("")

    # Portfolio Context
    parts.append(build_portfolio_context(tickers_by_tier, portfolio, prices))
    parts.append("")
    parts.append("---")
    parts.append("")

    # Tier sections
    tier_labels = {
        "tier1": "Tier 1 \u2014 Active Positions",
        "tier2": "Tier 2 \u2014 Pending Entry",
        "tier3": "Tier 3 \u2014 Watch Only",
    }

    for tier_key in ["tier1", "tier2", "tier3"]:
        parts.append(f"## {tier_labels[tier_key]}")
        parts.append("")

        tickers = tickers_by_tier[tier_key]
        if not tickers:
            parts.append("No tickers in this tier.")
            parts.append("")
            continue

        for ticker in tickers:
            stdout, err = tool_results.get(ticker, ("", None))
            section = build_ticker_section(ticker, stdout, err)
            parts.append(section)
            parts.append("")
            parts.append("---")
            parts.append("")

    # Failures
    parts.append("## Failures")
    if failures:
        for ticker, error_msg in failures:
            parts.append(f"- {ticker}: {error_msg}")
    else:
        parts.append("No failures.")

    return "\n".join(parts) + "\n"


def main():
    t0 = time.monotonic()

    # Load portfolio
    portfolio = load_portfolio()

    # Classify tickers
    tickers_by_tier = classify_tickers(portfolio)
    all_tickers = tickers_by_tier["tier1"] + tickers_by_tier["tier2"] + tickers_by_tier["tier3"]

    print(f"News Sweep Collector \u2014 {date.today().isoformat()}")
    print(f"Tickers: {len(all_tickers)} (T1:{len(tickers_by_tier['tier1'])} T2:{len(tickers_by_tier['tier2'])} T3:{len(tickers_by_tier['tier3'])})")

    # Run portfolio_status.py for current prices
    print("Running portfolio_status.py...")
    ps_stdout, ps_error = run_tool("portfolio_status.py")
    if ps_error:
        print(f"  Warning: {ps_error}")
    prices = parse_portfolio_status(ps_stdout) if ps_stdout else {}

    # Run news_sentiment.py per ticker (parallel, Tier 1 first in submission order)
    print(f"Running news_sentiment.py for {len(all_tickers)} tickers (4 workers)...")
    tool_results = {}
    failures = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {}
        for ticker in all_tickers:
            future = executor.submit(run_tool, "news_sentiment.py", [ticker])
            futures[future] = ticker

        for future in as_completed(futures):
            ticker = futures[future]
            try:
                stdout, error = future.result()
                tool_results[ticker] = (stdout, error)
                if error and not stdout:
                    failures.append((ticker, error))
                    print(f"  {ticker}: FAILED")
                elif is_no_news(stdout):
                    print(f"  {ticker}: no news")
                else:
                    print(f"  {ticker}: OK")
            except Exception as e:
                error_msg = f"*Error: {e}*"
                tool_results[ticker] = ("", error_msg)
                failures.append((ticker, error_msg))
                print(f"  {ticker}: EXCEPTION")

    # Build and write output
    content = build_output(tickers_by_tier, portfolio, prices, tool_results, failures)
    OUTPUT.write_text(content, encoding="utf-8")

    # Summary
    elapsed = time.monotonic() - t0
    size_kb = OUTPUT.stat().st_size / 1024
    no_news = sum(1 for t in all_tickers if is_no_news(tool_results.get(t, ("", None))[0]))

    print(f"\nOutput: news-sweep-raw.md ({size_kb:.1f} KB)")
    print(f"Tickers swept: {len(all_tickers)}")
    print(f"No news data: {no_news}")
    print(f"Failures: {len(failures)}")
    print(f"Elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
