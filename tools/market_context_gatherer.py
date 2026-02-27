#!/usr/bin/env python3
"""Market Context Gatherer — Phase 1 orchestrator for market-context workflow.

Replaces the LLM gatherer's manual extraction with Python orchestration.
Runs market_pulse.py and portfolio_status.py in parallel, extracts all
pending BUY orders, maps sectors, and writes market-context-raw.md.

Usage: python3 tools/market_context_gatherer.py
"""

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

# Same-directory imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
from news_sweep_collector import split_table_row

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = PROJECT_ROOT / "portfolio.json"
TOOLS_DIR = PROJECT_ROOT / "tools"
OUTPUT_PATH = PROJECT_ROOT / "market-context-raw.md"

# ---------------------------------------------------------------------------
# Sector mapping — must match market_pulse.py's 11 sector names.
# UPDATE THIS DICT when new tickers are added to portfolio.json.
# ---------------------------------------------------------------------------
SECTOR_MAP = {
    "NU": "Financial",
    "STIM": "Healthcare",
    "IONQ": "Technology",
    "LUNR": "Industrial",
    "USAR": "Materials",
    "INTC": "Technology",
    "APLD": "Technology",
    "SMCI": "Technology",
    "AR": "Energy",
    "VALE": "Materials",
    "CLF": "Materials",
    "SEDG": "Technology",
    "ACHR": "Industrial",
    "RKT": "Financial",
    "NNE": "Utilities",
    "UAMY": "Materials",
    "TMC": "Materials",
    "BBAI": "Technology",
    "CIFR": "Technology",
    "CLSK": "Technology",
    "SOUN": "Technology",
}

# Sector ETF mapping (must match market_pulse.py SECTORS dict)
SECTOR_ETF = {
    "Technology": "XLK",
    "Financial": "XLF",
    "Energy": "XLE",
    "Healthcare": "XLV",
    "Industrial": "XLI",
    "Comm Services": "XLC",
    "Cons Cyclical": "XLY",
    "Cons Defensive": "XLP",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
    "Materials": "XLB",
}


# ---------------------------------------------------------------------------
# Helpers (same patterns as exit_review_gatherer.py)
# ---------------------------------------------------------------------------

def run_tool(tool_name, args=None, timeout=120):
    """Run a Python tool and capture stdout. Returns (stdout, error_msg)."""
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
    """Load portfolio.json. Exit with error if missing/malformed."""
    try:
        with open(PORTFOLIO_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"*Error: {PORTFOLIO_PATH} not found*", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"*Error: {PORTFOLIO_PATH} malformed JSON: {e}*", file=sys.stderr)
        sys.exit(1)


def format_price(price):
    """Format price with $ and 2 decimals."""
    if price is None:
        return "N/A"
    return f"${price:.2f}"


def get_sector(ticker):
    """Look up sector from SECTOR_MAP. Log warning if Unknown."""
    sector = SECTOR_MAP.get(ticker, "Unknown")
    if sector == "Unknown":
        print(f"  Warning: {ticker} not in SECTOR_MAP — assigned 'Unknown'",
              file=sys.stderr)
    return sector


# ---------------------------------------------------------------------------
# Tool runners
# ---------------------------------------------------------------------------

def run_market_pulse():
    """Run market_pulse.py."""
    return run_tool("market_pulse.py", timeout=120)


def run_portfolio_status():
    """Run portfolio_status.py."""
    return run_tool("portfolio_status.py", timeout=120)


# ---------------------------------------------------------------------------
# Price parsing from portfolio_status.py output
# ---------------------------------------------------------------------------

def parse_all_prices(ps_output):
    """Parse current prices from ALL three portfolio_status.py tables.

    Identifies sections by scanning for ## Active Positions, ## Pending Orders,
    ## Watchlist headers. Extracts prices per table format:
    - Active Positions (10 columns): col 3 = Current Price
    - Pending Orders (10 columns): col 4 = Current Price
    - Watchlist (5 columns): col 1 = Price

    Returns dict[str, float] keyed by ticker. Active Positions prices take
    priority (never overwritten by later tables).
    """
    prices = {}
    current_section = None

    for line in ps_output.split("\n"):
        stripped = line.strip()

        # Detect section headers
        if stripped.startswith("## Active Positions"):
            current_section = "active"
            continue
        elif stripped.startswith("## Pending Orders"):
            current_section = "pending"
            continue
        elif stripped.startswith("## Watchlist"):
            current_section = "watchlist"
            continue
        elif stripped.startswith("## "):
            current_section = None
            continue

        # Skip non-table lines and headers/separators
        if not stripped.startswith("|") or current_section is None:
            continue
        cols = split_table_row(stripped)
        if not cols or cols[0] in ("Ticker", "Index"):
            continue
        if any(c.startswith(":---") or c.startswith("---") for c in cols):
            continue

        ticker = cols[0].strip()
        price_str = None

        if current_section == "active" and len(cols) >= 10:
            # Col 3 = Current (header: Current)
            price_str = cols[3]
        elif current_section == "pending" and len(cols) >= 10:
            # Col 4 = Current (header: Current)
            price_str = cols[4]
        elif current_section == "watchlist" and len(cols) >= 5:
            # Col 1 = Price (header: Price)
            price_str = cols[1]

        if price_str:
            cleaned = price_str.replace("$", "").replace(",", "").strip()
            try:
                price = float(cleaned)
                # Use setdefault so Active Positions prices are never overwritten
                prices.setdefault(ticker, price)
            except ValueError:
                pass

    return prices


# ---------------------------------------------------------------------------
# Pending BUY order extraction
# ---------------------------------------------------------------------------

def extract_pending_buy_orders(portfolio, prices):
    """Extract all pending BUY orders from portfolio.json.

    Skips empty arrays. Includes ALL BUY orders regardless of PAUSED/earnings
    notes — the market-context gate is independent of the earnings gate.
    Computes % Below Current using portfolio_status.py prices.

    Returns list of dicts sorted by ticker then % Below Current descending.
    """
    orders = []
    positions = portfolio.get("positions", {})
    pending = portfolio.get("pending_orders", {})

    for ticker, ticker_orders in sorted(pending.items()):
        # Skip empty arrays
        if not ticker_orders:
            continue

        for order in ticker_orders:
            if order.get("type") != "BUY":
                continue

            order_price = order["price"]
            shares = order["shares"]
            current = prices.get(ticker)
            note = order.get("note", "")
            sector = get_sector(ticker)

            # Compute % Below Current
            if current and current > 0:
                pct_below = (current - order_price) / current * 100
            else:
                pct_below = None

            # Determine active position status
            pos = positions.get(ticker, {})
            pos_shares = pos.get("shares", 0)
            if isinstance(pos_shares, (int, float)) and pos_shares > 0:
                active_str = f"Yes ({int(pos_shares)} shares)"
            else:
                active_str = "No (watchlist)"

            orders.append({
                "ticker": ticker,
                "sector": sector,
                "order_price": order_price,
                "shares": shares,
                "current_price": current,
                "pct_below": pct_below,
                "active_position": active_str,
                "note": note,
            })

    # Sort by ticker alphabetically, then by % Below Current descending
    orders.sort(key=lambda o: (o["ticker"], -(o["pct_below"] or 0)))
    return orders


# ---------------------------------------------------------------------------
# Table builders
# ---------------------------------------------------------------------------

def build_pending_buy_table(orders):
    """Build the 8-column Pending BUY Orders Detail table."""
    lines = []
    lines.append("| Ticker | Sector | Order Price | Shares | Current Price "
                  "| % Below Current | Active Position | Notes |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for o in orders:
        pct_str = f"{o['pct_below']:.1f}%" if o["pct_below"] is not None else "N/A"
        lines.append(
            f"| {o['ticker']} | {o['sector']} | {format_price(o['order_price'])} "
            f"| {o['shares']} | {format_price(o['current_price'])} "
            f"| {pct_str} | {o['active_position']} | {o['note']} |"
        )

    return "\n".join(lines)


def build_active_positions_table(portfolio, prices):
    """Build the Active Positions Summary table.

    Counts BOTH BUY and SELL pending orders per ticker.
    """
    lines = []
    lines.append("| Ticker | Sector | Shares | Avg Cost | Current Price "
                  "| Deployed | Pending BUYs | Pending SELLs |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    positions = portfolio.get("positions", {})
    pending = portfolio.get("pending_orders", {})

    for ticker in sorted(positions.keys()):
        pos = positions[ticker]
        shares = pos.get("shares", 0)
        if not isinstance(shares, (int, float)) or shares <= 0:
            continue

        avg_cost = pos.get("avg_cost", 0)
        current = prices.get(ticker)
        deployed = shares * avg_cost
        sector = get_sector(ticker)

        # Count pending orders
        ticker_orders = pending.get(ticker, [])
        buy_count = sum(1 for o in ticker_orders if o.get("type") == "BUY")
        sell_count = sum(1 for o in ticker_orders if o.get("type") == "SELL")

        lines.append(
            f"| {ticker} | {sector} | {int(shares)} | {format_price(avg_cost)} "
            f"| {format_price(current)} | {format_price(deployed)} "
            f"| {buy_count} | {sell_count} |"
        )

    return "\n".join(lines)


def build_sector_mapping(market_pulse_output, portfolio):
    """Build the Sector Mapping table.

    Maps portfolio tickers (with pending BUY orders or active positions)
    to the 11 sector ETFs. Uses SECTOR_MAP for ticker→sector.
    Extracts sector Day% from market_pulse.py output.
    """
    # Parse sector performance from market_pulse output
    sector_day_pct = {}
    in_sector_table = False
    for line in market_pulse_output.split("\n"):
        stripped = line.strip()
        if "Sector Performance" in stripped:
            in_sector_table = True
            continue
        if in_sector_table and stripped.startswith("###"):
            break
        if not in_sector_table or not stripped.startswith("|"):
            continue
        cols = split_table_row(stripped)
        if not cols or cols[0] == "Sector":
            continue
        if any(c.startswith(":---") or c.startswith("---") for c in cols):
            continue
        if len(cols) >= 3:
            sector_name = cols[0]
            day_pct = cols[2]  # Day% column
            sector_day_pct[sector_name] = day_pct

    # Group tickers by sector
    sector_tickers = {}
    positions = portfolio.get("positions", {})
    pending = portfolio.get("pending_orders", {})
    watchlist = portfolio.get("watchlist", [])

    all_tickers = set()
    all_tickers.update(positions.keys())
    for ticker, orders in pending.items():
        if orders:  # non-empty
            all_tickers.add(ticker)
    all_tickers.update(watchlist)

    for ticker in sorted(all_tickers):
        sector = get_sector(ticker)
        if sector not in sector_tickers:
            sector_tickers[sector] = []
        sector_tickers[sector].append(ticker)

    # Build table
    lines = []
    lines.append("| Portfolio Sector | Tickers | Market Sector ETF | Day% |")
    lines.append("| :--- | :--- | :--- | :--- |")

    for sector in sorted(sector_tickers.keys()):
        tickers = sorted(sector_tickers[sector])
        etf = SECTOR_ETF.get(sector, "N/A")
        day_pct = sector_day_pct.get(sector, "N/A")
        lines.append(f"| {sector} | {', '.join(tickers)} | {etf} | {day_pct} |")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cross-check
# ---------------------------------------------------------------------------

def cross_check_counts(orders, portfolio):
    """Verify total BUY orders extracted matches portfolio.json.

    Returns (match: bool, expected: int, got: int, details: str).
    """
    expected = 0
    per_ticker = {}
    pending = portfolio.get("pending_orders", {})

    for ticker, ticker_orders in pending.items():
        if not ticker_orders:
            continue
        buy_count = sum(1 for o in ticker_orders if o.get("type") == "BUY")
        if buy_count > 0:
            per_ticker[ticker] = buy_count
            expected += buy_count

    got = len(orders)
    match = expected == got

    if not match:
        # Find which tickers are missing
        extracted_counts = {}
        for o in orders:
            extracted_counts[o["ticker"]] = extracted_counts.get(o["ticker"], 0) + 1
        missing = []
        for ticker, count in per_ticker.items():
            ext = extracted_counts.get(ticker, 0)
            if ext != count:
                missing.append(f"{ticker}: expected {count}, got {ext}")
        details = "; ".join(missing) if missing else "Count mismatch, no specific ticker identified"
    else:
        details = "OK"

    return match, expected, got, details


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def assemble_raw(today_str, market_pulse_output, buy_orders, buy_table,
                 positions_table, sector_mapping, cross_check_str, errors):
    """Assemble the complete market-context-raw.md."""
    parts = []

    # Title
    parts.append(f"# Market Context Raw Data — {today_str}")
    parts.append("")

    # Market Pulse Output
    parts.append("## Market Pulse Output")
    parts.append("")
    if market_pulse_output:
        # Strip the "## Market Pulse" header and timestamp from tool output
        # since we wrap it in our own section
        mp_lines = market_pulse_output.split("\n")
        filtered = []
        skip_header = True
        for line in mp_lines:
            if skip_header:
                stripped = line.strip()
                if stripped.startswith("## Market Pulse"):
                    continue
                if stripped.startswith("*") and stripped.endswith("*") and len(stripped) < 30:
                    continue
                skip_header = False
            filtered.append(line)
        parts.append("\n".join(filtered))
    else:
        parts.append("*Error: market_pulse.py failed to produce output.*")
    parts.append("")
    parts.append("---")
    parts.append("")

    # Pending BUY Orders Detail
    parts.append("## Pending BUY Orders Detail")
    parts.append("")
    ticker_count = len(set(o["ticker"] for o in buy_orders))
    parts.append(f"*{len(buy_orders)} orders across {ticker_count} tickers. "
                 f"Sorted alphabetically by ticker, then by % Below Current "
                 f"descending (deepest first).*")
    parts.append("")
    parts.append(buy_table)
    parts.append("")
    parts.append(cross_check_str)
    parts.append("")
    parts.append("---")
    parts.append("")

    # Active Positions Summary
    parts.append("## Active Positions Summary")
    parts.append("")
    parts.append(positions_table)
    parts.append("")
    parts.append("---")
    parts.append("")

    # Sector Mapping
    parts.append("## Sector Mapping")
    parts.append("")
    parts.append(sector_mapping)
    parts.append("")

    # Errors section (if any)
    if errors:
        parts.append("---")
        parts.append("")
        parts.append("## Tool Errors")
        parts.append("")
        for err in errors:
            parts.append(f"- {err}")
        parts.append("")

    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    t0 = time.monotonic()
    today_str = date.today().isoformat()

    print(f"Market Context Gatherer — {today_str}")
    print("=" * 50)

    # Load portfolio
    portfolio = load_portfolio()
    errors = []

    # Step 1: Run market_pulse.py and portfolio_status.py in parallel
    print("\n[1/4] Running market_pulse.py and portfolio_status.py in parallel...")
    with ThreadPoolExecutor(max_workers=2) as executor:
        mp_future = executor.submit(run_market_pulse)
        ps_future = executor.submit(run_portfolio_status)
    mp_output, mp_err = mp_future.result()
    ps_output, ps_err = ps_future.result()

    if mp_err:
        errors.append(mp_err)
        print(f"  market_pulse.py: {mp_err}")
    else:
        print("  market_pulse.py: OK")

    if ps_err:
        errors.append(ps_err)
        print(f"  portfolio_status.py: {ps_err}")
    else:
        print("  portfolio_status.py: OK")

    # Step 2: Parse prices from portfolio_status.py
    print("\n[2/4] Parsing prices and extracting pending BUY orders...")
    prices = parse_all_prices(ps_output)
    print(f"  Prices parsed: {len(prices)} tickers")

    # Step 3: Extract pending BUY orders
    buy_orders = extract_pending_buy_orders(portfolio, prices)
    ticker_count = len(set(o["ticker"] for o in buy_orders))
    print(f"  Pending BUY orders: {len(buy_orders)} across {ticker_count} tickers")

    # Step 4: Cross-check and build tables
    print("\n[3/4] Cross-checking counts...")
    match, expected, got, details = cross_check_counts(buy_orders, portfolio)
    if match:
        cross_check_str = (
            f"**Cross-check:** {got} BUY orders enumerated across "
            f"{ticker_count} tickers. Count matches portfolio.json."
        )
        print(f"  Cross-check: PASS ({got} orders)")
    else:
        cross_check_str = (
            f"**Cross-check WARNING:** Expected {expected} BUY orders "
            f"from portfolio.json, extracted {got}. Details: {details}"
        )
        print(f"  Cross-check: MISMATCH — expected {expected}, got {got}")
        errors.append(f"Cross-check mismatch: expected {expected}, got {got}. {details}")

    # Build tables
    print("\n[4/4] Assembling market-context-raw.md...")
    buy_table = build_pending_buy_table(buy_orders)
    positions_table = build_active_positions_table(portfolio, prices)
    sector_mapping = build_sector_mapping(mp_output, portfolio)

    # Assemble and write
    content = assemble_raw(
        today_str, mp_output, buy_orders, buy_table,
        positions_table, sector_mapping, cross_check_str, errors
    )
    OUTPUT_PATH.write_text(content, encoding="utf-8")

    # Summary
    elapsed = time.monotonic() - t0
    size_kb = OUTPUT_PATH.stat().st_size / 1024

    print(f"\n{'=' * 50}")
    print(f"Output: market-context-raw.md ({size_kb:.1f} KB)")
    print(f"Pending BUY orders: {len(buy_orders)} across {ticker_count} tickers")
    print(f"Prices parsed: {len(prices)} tickers")
    print(f"Tool errors: {len(errors)}")
    print(f"Elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
