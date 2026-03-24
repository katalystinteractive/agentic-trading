#!/usr/bin/env python3
"""
Cycle Grouper — Groups flat trades from trade_history.json into buy-to-sell
round-trip cycles. Outputs cycle_history.json.

Usage: python3 tools/cycle_grouper.py [--ticker CLSK]
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

from trading_calendar import is_trading_day

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRADE_HISTORY = PROJECT_ROOT / "trade_history.json"
CYCLE_HISTORY = PROJECT_ROOT / "cycle_history.json"
PORTFOLIO = PROJECT_ROOT / "portfolio.json"


def load_trades():
    with open(TRADE_HISTORY) as f:
        return json.load(f).get("trades", [])


def load_portfolio():
    with open(PORTFOLIO) as f:
        return json.load(f)


def load_existing_cycles():
    if CYCLE_HISTORY.exists():
        with open(CYCLE_HISTORY) as f:
            return json.load(f)
    return {"cycles": [], "parse_warnings": [], "last_updated": None}


def count_trading_days(start_date_str, end_date_str):
    """Count trading days between two dates (inclusive)."""
    start = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    count = 0
    d = start
    from datetime import timedelta
    while d <= end:
        if is_trading_day(d):
            count += 1
        d += timedelta(days=1)
    return count


def group_cycles(trades, portfolio):
    """Group trades into cycles per ticker. Returns (cycles, warnings)."""
    # Sort all trades by (ticker, date, id) for deterministic ordering
    sorted_trades = sorted(trades, key=lambda t: (t["ticker"], t["date"], t.get("id", 0)))

    # Group by ticker
    by_ticker = {}
    for t in sorted_trades:
        by_ticker.setdefault(t["ticker"], []).append(t)

    all_cycles = []
    warnings = []

    for ticker, ticker_trades in sorted(by_ticker.items()):
        running_shares = 0
        cycle_num = 0
        current_entries = []
        current_exits = []

        for trade in ticker_trades:
            side = trade.get("side", "").upper()
            shares = trade.get("shares", 0)

            if side == "BUY":
                if running_shares == 0 and not current_entries:
                    # Start new cycle
                    cycle_num += 1
                    current_entries = []
                    current_exits = []
                current_entries.append(trade)
                running_shares += shares

            elif side == "SELL":
                if running_shares <= 0 and not current_entries:
                    # Orphaned SELL
                    warnings.append(
                        f"WARNING: {ticker} has orphaned SELL (id={trade.get('id')}, "
                        f"date={trade.get('date')}) with no preceding BUY — "
                        f"skipping from cycle formation. Resolve via backfill."
                    )
                    continue

                current_exits.append(trade)
                running_shares -= shares

                if running_shares <= 0:
                    # Cycle closed
                    running_shares = 0
                    cycle = _build_cycle(ticker, cycle_num, current_entries, current_exits, "closed")
                    all_cycles.append(cycle)
                    current_entries = []
                    current_exits = []

        # Open cycle remaining
        if current_entries and running_shares > 0:
            cycle_num += 1 if not current_exits and running_shares > 0 and cycle_num == 0 else 0
            if not any(c["cycle_id"] == f"{ticker}-{cycle_num}" for c in all_cycles):
                pass  # cycle_num already incremented when entries started
            cycle = _build_cycle(ticker, cycle_num, current_entries, current_exits, "open")
            all_cycles.append(cycle)

            # Phantom open cycle validation
            pos_shares = portfolio.get("positions", {}).get(ticker, {}).get("shares", 0)
            if isinstance(pos_shares, int) and pos_shares == 0:
                warnings.append(
                    f"WARNING: {ticker} cycle {ticker}-{cycle_num} is open but "
                    f"portfolio.json shows 0 shares — likely missing SELL record."
                )

    return all_cycles, warnings


def _build_cycle(ticker, num, entries, exits, status):
    """Build a cycle dict from entry and exit trade lists."""
    cycle_id = f"{ticker}-{num}"

    entry_shares = sum(e["shares"] for e in entries)
    entry_cost = sum(e["shares"] * e["price"] for e in entries)
    entry_avg = entry_cost / entry_shares if entry_shares > 0 else 0

    first_entry_date = min(e["date"] for e in entries)
    pre_strategy = any(e.get("pre_strategy", False) or e.get("backfilled", False) and e.get("pre_strategy", False) for e in entries)

    entry_trade_ids = [e.get("id") for e in entries if e.get("id") is not None]
    exit_trade_ids = [x.get("id") for x in exits if x.get("id") is not None]

    zones_used = list(set(e.get("zone") for e in entries if e.get("zone")))

    cycle = {
        "cycle_id": cycle_id,
        "ticker": ticker,
        "status": status,
        "pre_strategy": pre_strategy,
        "first_entry_date": first_entry_date,
        "entry_trade_ids": entry_trade_ids,
        "exit_trade_ids": exit_trade_ids,
        "entry_shares": entry_shares,
        "entry_avg": round(entry_avg, 4),
        "bullets_used": len(entries),
        "zones_used": zones_used,
    }

    if status == "closed" and exits:
        exit_shares = sum(x["shares"] for x in exits)
        exit_cost = sum(x["shares"] * x["price"] for x in exits)
        exit_avg = exit_cost / exit_shares if exit_shares > 0 else 0
        last_exit_date = max(x["date"] for x in exits)

        profit_pct = (exit_avg - entry_avg) / entry_avg * 100 if entry_avg > 0 else 0
        profit_dollar = (exit_avg - entry_avg) * exit_shares

        first_dt = datetime.strptime(first_entry_date, "%Y-%m-%d").date()
        last_dt = datetime.strptime(last_exit_date, "%Y-%m-%d").date()
        cycle_days = (last_dt - first_dt).days

        trading_days = count_trading_days(first_entry_date, last_exit_date)

        cycle.update({
            "last_exit_date": last_exit_date,
            "exit_shares": exit_shares,
            "exit_avg": round(exit_avg, 4),
            "profit_pct": round(profit_pct, 2),
            "profit_dollar": round(profit_dollar, 2),
            "cycle_days": cycle_days,
            "trading_days": trading_days,
        })
    else:
        cycle.update({
            "last_exit_date": None,
            "exit_shares": None,
            "exit_avg": None,
            "profit_pct": None,
            "profit_dollar": None,
            "cycle_days": None,
            "trading_days": None,
        })

    return cycle


def main():
    parser = argparse.ArgumentParser(description="Group trades into cycles")
    parser.add_argument("--ticker", help="Filter to specific ticker")
    args = parser.parse_args()

    trades = load_trades()
    portfolio = load_portfolio()
    existing = load_existing_cycles()

    all_cycles, warnings = group_cycles(trades, portfolio)

    # Merge: preserve post_sell_tracking from existing cycles
    existing_by_id = {c["cycle_id"]: c for c in existing.get("cycles", [])}

    for cycle in all_cycles:
        old = existing_by_id.get(cycle["cycle_id"])
        if old and "post_sell_tracking" in old:
            cycle["post_sell_tracking"] = old["post_sell_tracking"]

    # If --ticker filter, only replace that ticker's cycles
    if args.ticker:
        ticker_upper = args.ticker.upper()
        # Keep all existing non-filtered ticker cycles
        other_cycles = [c for c in existing.get("cycles", []) if c["ticker"] != ticker_upper]
        filtered_new = [c for c in all_cycles if c["ticker"] == ticker_upper]
        final_cycles = other_cycles + filtered_new
        # Also filter warnings
        warnings = [w for w in warnings if ticker_upper in w]
    else:
        final_cycles = all_cycles

    # Sort by ticker, then cycle_id
    final_cycles.sort(key=lambda c: (c["ticker"], c["cycle_id"]))

    output = {
        "cycles": final_cycles,
        "parse_warnings": warnings,
        "last_updated": date.today().isoformat(),
    }

    with open(CYCLE_HISTORY, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)

    # Print summary
    closed = [c for c in final_cycles if c["status"] == "closed"]
    open_c = [c for c in final_cycles if c["status"] == "open"]
    tickers = sorted(set(c["ticker"] for c in final_cycles))

    print(f"# Cycle Grouper Results")
    print(f"\nTotal cycles: {len(final_cycles)} ({len(closed)} closed, {len(open_c)} open)")
    print(f"Tickers: {len(tickers)} ({', '.join(tickers)})")

    if warnings:
        print(f"\n## Warnings ({len(warnings)})")
        for w in warnings:
            print(f"- {w}")

    print(f"\n## Closed Cycles")
    print("| Cycle | Ticker | Entry | Exit | Bullets | Entry Avg | Exit Avg | P/L % | P/L $ | Days |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for c in closed:
        pl_str = f"+{c['profit_pct']:.1f}%" if c['profit_pct'] >= 0 else f"{c['profit_pct']:.1f}%"
        dl_str = f"+${c['profit_dollar']:.2f}" if c['profit_dollar'] >= 0 else f"-${abs(c['profit_dollar']):.2f}"
        print(f"| {c['cycle_id']} | {c['ticker']} | {c['first_entry_date']} | {c['last_exit_date']} | {c['bullets_used']} | ${c['entry_avg']:.2f} | ${c['exit_avg']:.2f} | {pl_str} | {dl_str} | {c['cycle_days']}d |")

    if open_c:
        print(f"\n## Open Cycles")
        print("| Cycle | Ticker | Entry | Bullets | Entry Avg | Shares |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for c in open_c:
            print(f"| {c['cycle_id']} | {c['ticker']} | {c['first_entry_date']} | {c['bullets_used']} | ${c['entry_avg']:.2f} | {c['entry_shares']} |")

    print(f"\nWrote {CYCLE_HISTORY}")


if __name__ == "__main__":
    main()
