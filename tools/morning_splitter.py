#!/usr/bin/env python3
"""
Morning Splitter — Splits morning-briefing-condensed.md into per-ticker input files.

Reads the condensed briefing and portfolio.json, then writes:
  - morning-work/TICKER.md for each ticker (global context + per-ticker data)
  - morning-work/manifest.json with metadata for the orchestrator

Usage: python3 tools/morning_splitter.py
"""

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONDENSED = PROJECT_ROOT / "morning-briefing-condensed.md"
PORTFOLIO = PROJECT_ROOT / "portfolio.json"
OUTPUT_DIR = PROJECT_ROOT / "morning-work"


# ---------------------------------------------------------------------------
# Ticker classification (matches morning_compiler.py logic exactly)
# ---------------------------------------------------------------------------

def load_portfolio():
    """Load portfolio.json and classify tickers.

    Returns (active, watchlist_with_orders, scouting) lists.
    Classification:
      1. Active = shares > 0
      2. Watchlist = shares == 0 AND has pending BUY orders (from watchlist array)
      3. Scouting = on watchlist array but no shares and no pending BUY orders
      4. If a ticker appears in both active and watchlist array, classify as active only
    """
    with open(PORTFOLIO) as f:
        data = json.load(f)

    active = []
    watchlist_with_orders = []
    scouting = []

    for ticker, pos in data.get("positions", {}).items():
        shares = pos.get("shares", 0)
        if isinstance(shares, str):
            shares = int(shares) if shares.isdigit() else 0
        if shares > 0:
            active.append(ticker)

    for ticker in data.get("watchlist", []):
        if ticker in active:
            continue  # already an active position
        has_buy = False
        for order in data.get("pending_orders", {}).get(ticker, []):
            if order.get("type", "").upper() == "BUY":
                has_buy = True
                break
        if has_buy:
            watchlist_with_orders.append(ticker)
        else:
            scouting.append(ticker)

    return active, watchlist_with_orders, scouting, data


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def find_ticker_sections(lines, start_idx, end_idx):
    """Find all ### TICKER sections between start_idx and end_idx.

    Returns list of (ticker, section_start, section_end) tuples.
    Matches morning_compiler.py logic: ### header where text after ### matches
    ^[A-Z]{1,6}$ (skipping known non-ticker headers).
    """
    sections = []
    current_ticker = None
    current_start = None

    for i in range(start_idx, end_idx):
        line = lines[i].strip()
        if (line.startswith("### ")
                and not line.startswith("### Next")
                and not line.startswith("### Earnings")
                and not line.startswith("### Short")
                and not line.startswith("### Squeeze")
                and not line.startswith("### Trend")
                and not line.startswith("### Momentum")
                and not line.startswith("### Volatility")
                and not line.startswith("### Key ")
                and not line.startswith("### Signal")
                and not line.startswith("### Revenue")
                and not line.startswith("### Headlines")
                and not line.startswith("### Sentiment")
                and not line.startswith("### Detected")
                and not line.startswith("### Context")
                and not line.startswith("### Major")
                and not line.startswith("### Market")
                and not line.startswith("### Sector")
                and not line.startswith("### Suggested")):
            potential_ticker = line[4:].strip()
            if potential_ticker and re.match(r'^[A-Z]{1,6}$', potential_ticker):
                if current_ticker is not None:
                    sections.append((current_ticker, current_start, i))
                current_ticker = potential_ticker
                current_start = i

    if current_ticker is not None:
        sections.append((current_ticker, current_start, end_idx))

    return sections


def find_section_start(lines, header):
    """Find the line index of a ## section header."""
    for i, line in enumerate(lines):
        if line.strip() == header:
            return i
    return None


def find_next_h2(lines, start_idx):
    """Find the next ## header after start_idx."""
    for i in range(start_idx + 1, len(lines)):
        if lines[i].strip().startswith("## ") and not lines[i].strip().startswith("## #"):
            return i
    return len(lines)


# ---------------------------------------------------------------------------
# Table parsing
# ---------------------------------------------------------------------------

def parse_table_row(line):
    """Split a markdown table row into cells, stripping whitespace."""
    if not line.strip().startswith("|"):
        return []
    cells = line.split("|")
    # First and last elements are empty strings from leading/trailing |
    return [c.strip() for c in cells[1:-1]]


def parse_market_regime(lines):
    """Parse Market Regime table from the condensed file.

    Returns dict with regime, reasoning, vix, indices_above_sma, sector_breadth.
    """
    result = {
        "regime": "Unknown",
        "reasoning": "",
        "vix": "N/A",
        "indices_above_sma": 0,
        "sector_breadth": 0,
    }

    # Find ### Market Regime section
    regime_start = None
    for i, line in enumerate(lines):
        if line.strip() == "### Market Regime":
            regime_start = i
            break

    if regime_start is not None:
        for i in range(regime_start, min(regime_start + 15, len(lines))):
            cells = parse_table_row(lines[i])
            if len(cells) >= 2:
                key = cells[0].strip()
                val = cells[1].strip()
                if key == "Regime":
                    # Strip bold markers
                    result["regime"] = val.replace("**", "")
                elif key == "Reasoning":
                    result["reasoning"] = val

    # Parse VIX from Volatility & Rates table
    for i, line in enumerate(lines):
        if line.strip() == "### Volatility & Rates":
            for j in range(i, min(i + 10, len(lines))):
                cells = parse_table_row(lines[j])
                if len(cells) >= 2 and cells[0] == "VIX":
                    # VIX value looks like: 19.09 (-8.31% 5D)
                    vix_match = re.match(r'([\d.]+)', cells[1])
                    if vix_match:
                        result["vix"] = float(vix_match.group(1))
            break

    # Count indices above 50-SMA from Major Indices table
    for i, line in enumerate(lines):
        if line.strip() == "### Major Indices":
            above_count = 0
            for j in range(i, min(i + 10, len(lines))):
                cells = parse_table_row(lines[j])
                if len(cells) >= 6:
                    trend = cells[5].strip()
                    if "Above 50-SMA" in trend:
                        above_count += 1
            result["indices_above_sma"] = above_count
            break

    # Count sectors with positive daily performance
    for i, line in enumerate(lines):
        if line.strip() == "### Sector Performance (Ranked by Daily)":
            positive_count = 0
            for j in range(i + 1, min(i + 20, len(lines))):
                cells = parse_table_row(lines[j])
                if len(cells) >= 3:
                    day_pct = cells[2].strip()
                    if day_pct.startswith("+"):
                        positive_count += 1
            result["sector_breadth"] = positive_count
            break

    return result


def parse_position_summary(lines):
    """Parse the ## Position Summary table into a dict keyed by ticker.

    Each value is a dict with: shares, avg_cost, current_price, pl_pct,
    entry_date, days_held, time_stop_status, bullets_used, target_exit, note.
    """
    positions = {}

    start = find_section_start(lines, "## Position Summary")
    if start is None:
        return positions

    # Column headers
    headers = [
        "shares", "avg_cost", "current_price", "pl_pct", "entry_date",
        "days_held", "time_stop_status", "bullets_used", "target_exit", "note"
    ]

    for i in range(start + 1, len(lines)):
        line = lines[i].strip()
        if line.startswith("## ") or line == "---":
            break
        cells = parse_table_row(line)
        if len(cells) < 2:
            continue
        # Skip header and separator rows
        if cells[0] in ("Ticker", ":---", ""):
            continue
        ticker = cells[0].strip()
        if not re.match(r'^[A-Z]{1,6}$', ticker):
            continue
        pos = {}
        for idx, key in enumerate(headers):
            pos[key] = cells[idx + 1].strip() if idx + 1 < len(cells) else ""
        positions[ticker] = pos

    return positions


def parse_pending_orders(lines):
    """Parse ## Pending Orders Detail table into a dict keyed by ticker.

    Each value is a list of order dicts with: type, order_price, shares,
    current_price, pct_below, active_position, days_to_earnings, notes.
    """
    orders = {}

    start = find_section_start(lines, "## Pending Orders Detail")
    if start is None:
        return orders

    headers = [
        "type", "order_price", "shares", "current_price",
        "pct_below", "active_position", "days_to_earnings", "notes"
    ]

    for i in range(start + 1, len(lines)):
        line = lines[i].strip()
        if line.startswith("## ") or line == "---":
            break
        cells = parse_table_row(line)
        if len(cells) < 2:
            continue
        if cells[0] in ("Ticker", ":---", ""):
            continue
        ticker = cells[0].strip()
        if not re.match(r'^[A-Z]{1,6}$', ticker):
            continue
        order = {}
        for idx, key in enumerate(headers):
            order[key] = cells[idx + 1].strip() if idx + 1 < len(cells) else ""
        orders.setdefault(ticker, []).append(order)

    return orders


def parse_portfolio_summary(lines):
    """Parse ## Active Positions table (under Portfolio Status Output) for the
    portfolio summary that goes into every ticker file.

    Returns list of dicts with: ticker, shares, avg_cost, pl_pct.
    """
    summary = []

    start = find_section_start(lines, "## Active Positions")
    if start is None:
        return summary

    for i in range(start + 1, len(lines)):
        line = lines[i].strip()
        if line.startswith("## ") or line == "---":
            break
        cells = parse_table_row(line)
        if len(cells) < 8:
            continue
        ticker = cells[0].strip()
        if not re.match(r'^[A-Z]{1,6}$', ticker):
            continue
        summary.append({
            "ticker": ticker,
            "shares": cells[1].strip(),
            "avg_cost": cells[2].strip(),
            "pl_pct": cells[7].strip(),
        })

    return summary


def parse_capital_summary(lines):
    """Parse the last ## Capital Summary table for deployed, velocity, bounce values."""
    capital = {
        "deployed": "N/A",
        "velocity_pool": "$1,000",
        "bounce_pool": "$1,000",
    }

    # Find the LAST Capital Summary (the detailed one near end of file)
    last_start = None
    for i, line in enumerate(lines):
        if line.strip() == "## Capital Summary":
            last_start = i

    if last_start is None:
        return capital

    for i in range(last_start + 1, min(last_start + 20, len(lines))):
        cells = parse_table_row(lines[i])
        if len(cells) >= 2:
            key = cells[0].strip().lower()
            val = cells[1].strip()
            if "deployed" in key:
                capital["deployed"] = val
            elif "velocity pool" in key:
                capital["velocity_pool"] = val
            elif "bounce pool" in key:
                capital["bounce_pool"] = val

    return capital


def parse_date(lines):
    """Extract date from the first header line."""
    for line in lines[:5]:
        m = re.search(r'(\d{4}-\d{2}-\d{2})', line)
        if m:
            return m.group(1)
    return "unknown"


# ---------------------------------------------------------------------------
# Per-ticker file builder
# ---------------------------------------------------------------------------

def build_ticker_file(ticker, ticker_type, date, regime_info, portfolio_summary,
                      capital, position_data, pending_orders_list,
                      tool_output_text):
    """Build the content for a single TICKER.md file."""
    parts = []

    # Header
    parts.append(f"# {ticker} Analysis Input\n")

    # Global Context
    parts.append("## Global Context")
    parts.append("| Metric | Value |")
    parts.append("| :--- | :--- |")
    parts.append(f"| Date | {date} |")
    parts.append(f"| Regime | {regime_info['regime']} |")
    parts.append(f"| Regime Detail | {regime_info['reasoning']} |")
    vix_val = regime_info['vix']
    parts.append(f"| VIX | {vix_val} |")
    parts.append(f"| Indices Above 50-SMA | {regime_info['indices_above_sma']}/3 |")
    parts.append(f"| Sector Breadth | {regime_info['sector_breadth']}/11 positive |")
    parts.append("")

    # Portfolio Summary (all active tickers)
    parts.append("## Portfolio Summary")
    parts.append("| Ticker | Shares | Avg Cost | P/L % |")
    parts.append("| :--- | :--- | :--- | :--- |")
    for row in portfolio_summary:
        parts.append(f"| {row['ticker']} | {row['shares']} | {row['avg_cost']} | {row['pl_pct']} |")
    parts.append("")

    # Capital
    parts.append("## Capital")
    parts.append("| Metric | Value |")
    parts.append("| :--- | :--- |")
    parts.append(f"| Deployed | {capital['deployed']} |")
    parts.append(f"| Velocity Pool | {capital['velocity_pool']} |")
    parts.append(f"| Bounce Pool | {capital['bounce_pool']} |")
    parts.append("")

    # Position Data
    parts.append("## Position Data")
    if position_data:
        parts.append("| Field | Value |")
        parts.append("| :--- | :--- |")
        field_labels = {
            "shares": "Shares",
            "avg_cost": "Avg Cost",
            "current_price": "Current Price",
            "pl_pct": "P/L %",
            "entry_date": "Entry Date",
            "days_held": "Days Held",
            "time_stop_status": "Time Stop Status",
            "bullets_used": "Bullets Used",
            "target_exit": "Target Exit",
            "note": "Note",
        }
        for key, label in field_labels.items():
            val = position_data.get(key, "N/A")
            parts.append(f"| {label} | {val} |")
    else:
        if ticker_type == "watchlist":
            parts.append("No active position (watchlist)")
        elif ticker_type == "scouting":
            parts.append("No active position (scouting)")
        else:
            parts.append("No position data available")
    parts.append("")

    # Pending Orders
    parts.append("## Pending Orders")
    if pending_orders_list:
        parts.append("| Type | Order Price | Shares | % Below Current | Days to Earnings | Notes |")
        parts.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for order in pending_orders_list:
            parts.append(
                f"| {order.get('type', '')} "
                f"| {order.get('order_price', '')} "
                f"| {order.get('shares', '')} "
                f"| {order.get('pct_below', '')} "
                f"| {order.get('days_to_earnings', '')} "
                f"| {order.get('notes', '')} |"
            )
    else:
        parts.append("No pending orders")
    parts.append("")

    # Tool Outputs (full per-ticker section from condensed file)
    parts.append("## Tool Outputs")
    if tool_output_text:
        parts.append(tool_output_text.rstrip())
    else:
        parts.append("No tool output data available")
    parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Validate inputs
    if not CONDENSED.exists():
        print(f"*Error: {CONDENSED} not found. Run the compiler phase first.*")
        sys.exit(1)
    if not PORTFOLIO.exists():
        print(f"*Error: {PORTFOLIO} not found.*")
        sys.exit(1)

    # Load data
    active_tickers, watchlist_tickers, scouting_tickers, portfolio_data = load_portfolio()
    print(f"Active: {len(active_tickers)} ({', '.join(active_tickers)})")
    print(f"Watchlist: {len(watchlist_tickers)} ({', '.join(watchlist_tickers)})")
    print(f"Scouting: {len(scouting_tickers)} ({', '.join(scouting_tickers)})")

    # Read condensed file
    content = CONDENSED.read_text(encoding="utf-8")
    lines = content.split("\n")

    # Parse global data
    date = parse_date(lines)
    regime_info = parse_market_regime(lines)
    portfolio_summary = parse_portfolio_summary(lines)
    position_summary = parse_position_summary(lines)
    pending_orders = parse_pending_orders(lines)
    capital = parse_capital_summary(lines)

    print(f"\nDate: {date}")
    print(f"Regime: {regime_info['regime']} ({regime_info['reasoning']})")
    print(f"Position summary rows: {len(position_summary)}")
    print(f"Pending orders tickers: {len(pending_orders)}")

    # Find per-ticker section boundaries
    active_section_start = find_section_start(lines, "## Per-Ticker Active Position Data")
    watchlist_section_start = find_section_start(lines, "## Watchlist Ticker Data")
    scouting_section_start = find_section_start(lines, "## Scouting Tickers (No Orders)")

    # Determine end boundaries for ticker section parsing
    if active_section_start is not None:
        active_end = watchlist_section_start or scouting_section_start or len(lines)
    else:
        active_end = 0

    if watchlist_section_start is not None:
        watchlist_end = scouting_section_start or len(lines)
    else:
        watchlist_end = 0

    # Parse ticker sections
    active_sections = {}
    if active_section_start is not None:
        for ticker, s, e in find_ticker_sections(lines, active_section_start, active_end):
            # Include everything from the ### TICKER header (skip the header itself)
            # to the next ticker or section boundary
            section_lines = lines[s:e]
            # Remove leading ### TICKER line — the tool outputs start after it
            if section_lines and section_lines[0].strip().startswith("### "):
                section_lines = section_lines[1:]
            active_sections[ticker] = "\n".join(section_lines).strip()

    watchlist_sections = {}
    if watchlist_section_start is not None:
        for ticker, s, e in find_ticker_sections(lines, watchlist_section_start, watchlist_end):
            section_lines = lines[s:e]
            if section_lines and section_lines[0].strip().startswith("### "):
                section_lines = section_lines[1:]
            watchlist_sections[ticker] = "\n".join(section_lines).strip()

    print(f"Active tool sections: {len(active_sections)} ({', '.join(active_sections.keys())})")
    print(f"Watchlist tool sections: {len(watchlist_sections)} ({', '.join(watchlist_sections.keys())})")

    # Create output directory
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Build manifest
    manifest = {
        "date": date,
        "regime": regime_info["regime"],
        "regime_detail": {
            "vix": regime_info["vix"],
            "reasoning": regime_info["reasoning"],
            "indices_above_sma": regime_info["indices_above_sma"],
            "sector_breadth": regime_info["sector_breadth"],
        },
        "tickers": [],
        "capital": {
            "deployed": _parse_dollar(capital["deployed"]),
            "velocity_pool": _parse_dollar(capital["velocity_pool"]),
            "bounce_pool": _parse_dollar(capital["bounce_pool"]),
        },
    }

    total_files = 0
    total_bytes = 0

    # Process active tickers
    for ticker in active_tickers:
        tool_text = active_sections.get(ticker, "")
        pos_data = position_summary.get(ticker, None)
        orders = pending_orders.get(ticker, [])

        file_content = build_ticker_file(
            ticker, "active", date, regime_info, portfolio_summary,
            capital, pos_data, orders, tool_text
        )

        out_path = OUTPUT_DIR / f"{ticker}.md"
        out_path.write_text(file_content, encoding="utf-8")
        file_size = out_path.stat().st_size
        total_files += 1
        total_bytes += file_size

        manifest["tickers"].append({
            "ticker": ticker,
            "type": "active",
            "agent": "active-ticker-analyst",
            "input_file": f"morning-work/{ticker}.md",
        })

        print(f"  {ticker:6s} (active)    -> {out_path.name} ({file_size / 1024:.1f} KB)")

    # Process watchlist tickers
    for ticker in watchlist_tickers:
        tool_text = watchlist_sections.get(ticker, "")
        pos_data = None  # No active position
        orders = pending_orders.get(ticker, [])

        file_content = build_ticker_file(
            ticker, "watchlist", date, regime_info, portfolio_summary,
            capital, pos_data, orders, tool_text
        )

        out_path = OUTPUT_DIR / f"{ticker}.md"
        out_path.write_text(file_content, encoding="utf-8")
        file_size = out_path.stat().st_size
        total_files += 1
        total_bytes += file_size

        manifest["tickers"].append({
            "ticker": ticker,
            "type": "watchlist",
            "agent": "watchlist-ticker-analyst",
            "input_file": f"morning-work/{ticker}.md",
        })

        print(f"  {ticker:6s} (watchlist) -> {out_path.name} ({file_size / 1024:.1f} KB)")

    # Process scouting tickers
    for ticker in scouting_tickers:
        # Scouting tickers have no per-ticker tool sections — they are just listed
        tool_text = ""
        pos_data = None
        orders = pending_orders.get(ticker, [])

        file_content = build_ticker_file(
            ticker, "scouting", date, regime_info, portfolio_summary,
            capital, pos_data, orders, tool_text
        )

        out_path = OUTPUT_DIR / f"{ticker}.md"
        out_path.write_text(file_content, encoding="utf-8")
        file_size = out_path.stat().st_size
        total_files += 1
        total_bytes += file_size

        manifest["tickers"].append({
            "ticker": ticker,
            "type": "scouting",
            "agent": "watchlist-ticker-analyst",
            "input_file": f"morning-work/{ticker}.md",
        })

        print(f"  {ticker:6s} (scouting)  -> {out_path.name} ({file_size / 1024:.1f} KB)")

    # Write manifest
    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8"
    )

    # Summary
    print(f"\n--- Split Complete ---")
    print(f"Output directory: {OUTPUT_DIR}")
    print(f"Ticker files: {total_files} ({total_bytes / 1024:.1f} KB total)")
    print(f"  Active: {len(active_tickers)}")
    print(f"  Watchlist: {len(watchlist_tickers)}")
    print(f"  Scouting: {len(scouting_tickers)}")
    print(f"Manifest: {manifest_path} ({manifest_path.stat().st_size} bytes)")
    if total_files > 0:
        print(f"Avg file size: {total_bytes / total_files / 1024:.1f} KB")


def _parse_dollar(val):
    """Parse a dollar string like '$2,126.60' into a float."""
    if isinstance(val, (int, float)):
        return val
    try:
        cleaned = val.replace("$", "").replace(",", "").strip()
        return float(cleaned)
    except (ValueError, AttributeError):
        return 0.0


if __name__ == "__main__":
    main()
