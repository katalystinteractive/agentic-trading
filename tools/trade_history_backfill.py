#!/usr/bin/env python3
"""
Trade History Backfill — Parse historical trades from tickers/*/memory.md
into structured trade_history.json entries.

One-time tool. Ongoing recording is handled by portfolio_manager.py _record_trade().

Usage: python3 tools/trade_history_backfill.py [--dry-run]
"""

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRADE_HISTORY = PROJECT_ROOT / "trade_history.json"
TICKERS_DIR = PROJECT_ROOT / "tickers"
PORTFOLIO = PROJECT_ROOT / "portfolio.json"

# --- Regex patterns (order: B, C, E first (specific), then A/D (general)) ---

# Pattern B: "Bullet N filled at $X (N shares)"
PAT_B = re.compile(
    r'\*\*(\d{4}-\d{2}-\d{2}):?\*\*\s+Bullet\s+\d+\s+filled\s+at\s+\$?([\d.]+)\s+\((\d+)\s+shares?'
)

# Pattern C: "Sold N shares @ $X"
PAT_C = re.compile(
    r'\*\*(\d{4}-\d{2}-\d{2}):?\*\*\s+Sold\s+(\d+)\s+shares?\s+@\s+\$?([\d.]+)'
)

# Pattern E: Table format "| DATE | BUY/SELL | N | $X |"
PAT_E = re.compile(
    r'\|\s*(\S+)\s*\|\s*(BUY|SELL)\s*\|\s*(\d+)\s*\|\s*\$?([\d.]+)'
)

# Pattern A: Standard "DATE: BUY/SELL N shares @ $X"
PAT_A = re.compile(
    r'(?:\*\*)?(\d{4}-\d{2}-\d{2}):?(?:\*\*)?\s+(BUY|SELL)\s+(\d+)\s+(?:shares?\s+)?@\s+\$?([\d.]+)'
)

# Pattern D detector: date-free trade regex for multi-trade lines
PAT_D_TRADE = re.compile(
    r'(BUY|SELL)\s+(\d+)\s+(?:shares?\s+)?@\s+\$?([\d.]+)'
)

# Date extractor for Pattern D lines
PAT_DATE = re.compile(r'(?:\*\*)?(\d{4}-\d{2}-\d{2}):?(?:\*\*)?')


def load_existing_trades():
    """Load existing trade_history.json trades."""
    if TRADE_HISTORY.exists():
        with open(TRADE_HISTORY) as f:
            data = json.load(f)
        return data.get("trades", [])
    return []


def load_portfolio():
    """Load portfolio.json."""
    with open(PORTFOLIO) as f:
        return json.load(f)


def is_pre_strategy(ticker, portfolio):
    """Check if ticker is pre-strategy based on portfolio.json."""
    pos = portfolio.get("positions", {}).get(ticker, {})
    note = pos.get("note", "").lower()
    entry = pos.get("entry_date", "")
    if "pre-strategy" in note or entry.startswith("pre-"):
        return True
    return False


def parse_memory_file(ticker, filepath):
    """Parse a single memory.md file and return list of trade dicts."""
    trades = []
    text = filepath.read_text(encoding="utf-8")

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        parsed = []

        # Pattern B: Bullet filled
        m = PAT_B.search(line)
        if m:
            parsed.append({
                "date": m.group(1), "side": "BUY",
                "shares": int(m.group(3)), "price": float(m.group(2)),
                "pattern": "B"
            })
            trades.extend(parsed)
            continue

        # Pattern C: Sold
        m = PAT_C.search(line)
        if m:
            parsed.append({
                "date": m.group(1), "side": "SELL",
                "shares": int(m.group(2)), "price": float(m.group(3)),
                "pattern": "C"
            })
            trades.extend(parsed)
            continue

        # Pattern E: Table format
        m = PAT_E.search(line)
        if m:
            date_str = m.group(1)
            if date_str.startswith("Pre-"):
                # Parse "Pre-2026" or "Pre-2026-02-12" as 2026-01-01
                year_match = re.search(r'(\d{4})', date_str)
                date_str = f"{year_match.group(1)}-01-01" if year_match else "2026-01-01"
                is_pre = True
            else:
                is_pre = False
            parsed.append({
                "date": date_str, "side": m.group(2),
                "shares": int(m.group(3)), "price": float(m.group(4)),
                "pattern": "E", "pre_strategy_from_date": is_pre
            })
            trades.extend(parsed)
            continue

        # Pattern A/D: Check for multi-trade (D) first
        date_m = PAT_DATE.search(line)
        if not date_m:
            continue

        date_str = date_m.group(1)
        d_matches = PAT_D_TRADE.findall(line)

        if len(d_matches) > 1:
            # Pattern D: Multiple trades on one line
            for side, shares, price in d_matches:
                parsed.append({
                    "date": date_str, "side": side.upper(),
                    "shares": int(shares), "price": float(price),
                    "pattern": "D"
                })
        else:
            # Pattern A: Single trade
            m = PAT_A.search(line)
            if m:
                parsed.append({
                    "date": m.group(1), "side": m.group(2).upper(),
                    "shares": int(m.group(3)), "price": float(m.group(4)),
                    "pattern": "A"
                })

        trades.extend(parsed)

    # Tag with ticker
    for t in trades:
        t["ticker"] = ticker

    return trades


def is_duplicate(new_trade, existing_trades):
    """Check if trade already exists (dedup by ticker, side, date, shares with price tolerance)."""
    for ex in existing_trades:
        if (ex.get("ticker") == new_trade["ticker"]
                and ex.get("side") == new_trade["side"]
                and ex.get("date") == new_trade["date"]
                and ex.get("shares") == new_trade["shares"]
                and abs(ex.get("price", 0) - new_trade["price"]) < 0.01):
            return True
    return False


def validate_sells(trades_by_ticker):
    """Validate SELL profit % against computed values. Returns list of warnings."""
    warnings = []
    # We can't easily validate profit % from memory.md text here since we
    # only extracted structured fields. This would require re-reading raw lines.
    # Skip for now — the plan says this is optional validation.
    return warnings


def main():
    dry_run = "--dry-run" in sys.argv

    portfolio = load_portfolio()
    existing_trades = load_existing_trades()
    max_id = max((t.get("id", 0) for t in existing_trades), default=0)

    # Find all memory.md files
    memory_files = sorted(TICKERS_DIR.glob("*/memory.md"))

    all_parsed = []
    parse_warnings = []

    for mf in memory_files:
        ticker = mf.parent.name
        try:
            parsed = parse_memory_file(ticker, mf)
            all_parsed.extend(parsed)
        except Exception as e:
            parse_warnings.append(f"Error parsing {ticker}/memory.md: {e}")

    # Deduplicate against existing trades
    new_trades = []
    skipped = 0
    for pt in all_parsed:
        if is_duplicate(pt, existing_trades):
            skipped += 1
            continue
        # Also check against trades we're about to add (self-dedup)
        if is_duplicate(pt, new_trades):
            skipped += 1
            continue

        max_id += 1
        pre_strat = pt.pop("pre_strategy_from_date", False) or is_pre_strategy(pt["ticker"], portfolio)
        pattern = pt.pop("pattern")

        record = {
            "id": max_id,
            "ticker": pt["ticker"],
            "side": pt["side"],
            "date": pt["date"],
            "shares": pt["shares"],
            "price": pt["price"],
            "avg_cost_before": None,
            "avg_cost_after": None,
            "total_shares_after": None,
            "note": f"backfilled from memory.md (Pattern {pattern})",
            "backfilled": True,
        }
        if pre_strat:
            record["pre_strategy"] = True

        new_trades.append(record)

    # Output
    print(f"# Trade History Backfill {'(DRY RUN)' if dry_run else ''}")
    print(f"\nParsed {len(all_parsed)} trades from {len(memory_files)} memory.md files")
    print(f"Skipped {skipped} duplicates (already in trade_history.json)")
    print(f"New trades to add: {len(new_trades)}")
    print()

    if new_trades:
        print("| # | Ticker | Side | Date | Shares | Price | Pattern | Pre-Strategy |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for t in new_trades:
            pat = t["note"].split("Pattern ")[-1].rstrip(")")
            pre = "Yes" if t.get("pre_strategy") else ""
            print(f"| {t['id']} | {t['ticker']} | {t['side']} | {t['date']} | {t['shares']} | ${t['price']:.2f} | {pat} | {pre} |")
        print()

    if parse_warnings:
        print("## Warnings")
        for w in parse_warnings:
            print(f"- {w}")
        print()

    if not dry_run and new_trades:
        # Write to trade_history.json
        all_trades = existing_trades + new_trades
        with open(TRADE_HISTORY, "w", encoding="utf-8") as f:
            json.dump({"trades": all_trades}, f, indent=2, default=str)
        print(f"Wrote {len(all_trades)} total trades to {TRADE_HISTORY}")
    elif dry_run:
        print("(Dry run — no files modified)")


if __name__ == "__main__":
    main()
