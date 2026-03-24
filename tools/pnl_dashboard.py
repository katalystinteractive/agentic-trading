#!/usr/bin/env python3
"""
P/L Dashboard — Single command for full performance picture.

6 tables: Summary, Period Breakdown, Per-Ticker Ranking, Open Position Health,
Benchmark Comparison, Capital Utilization.

Usage: python3 tools/pnl_dashboard.py [--period week|month|ytd|all] [--ticker CLSK]
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yfinance as yf

from portfolio_status import fetch_prices
from trading_calendar import as_of_date_label

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CYCLE_HISTORY = PROJECT_ROOT / "cycle_history.json"
PORTFOLIO = PROJECT_ROOT / "portfolio.json"
COOLDOWN = PROJECT_ROOT / "cooldown.json"
OUTPUT = PROJECT_ROOT / "pnl_dashboard.md"


def load_json(path):
    with open(path) as f:
        return json.load(f)


def parse_date(s):
    """Parse ISO date string to date object."""
    return datetime.strptime(s, "%Y-%m-%d").date()


def filter_period(cycles, period, today):
    """Filter closed cycles by period."""
    if period == "all":
        return cycles

    for c in cycles:
        if c["last_exit_date"] is None:
            continue

    filtered = []
    for c in cycles:
        if c["last_exit_date"] is None:
            continue
        exit_d = parse_date(c["last_exit_date"])

        if period == "week":
            monday = today - timedelta(days=today.weekday())
            if exit_d >= monday:
                filtered.append(c)
        elif period == "month":
            if exit_d.year == today.year and exit_d.month == today.month:
                filtered.append(c)
        elif period == "last30":
            if exit_d >= today - timedelta(days=30):
                filtered.append(c)
        elif period == "ytd":
            if exit_d.year == today.year:
                filtered.append(c)

    return filtered


def compute_summary(closed, open_cycles, portfolio, live_prices):
    """Compute Table 1: Summary metrics."""
    positions = portfolio.get("positions", {})
    capital = portfolio.get("capital", {})
    watchlist = portfolio.get("watchlist", [])

    total_profit = sum(c["profit_dollar"] for c in closed)
    n_cycles = len(closed)

    if n_cycles > 0:
        wins = len([c for c in closed if c["profit_pct"] > 0.0])
        win_rate = wins / n_cycles * 100
        avg_profit_pct = sum(c["profit_pct"] for c in closed) / n_cycles
        avg_profit_dollar = total_profit / n_cycles
        avg_duration = sum(c["cycle_days"] for c in closed) / n_cycles
        turnover = sum(c["entry_avg"] * c["entry_shares"] for c in closed)
        margin = total_profit / turnover * 100 if turnover > 0 else 0
    else:
        win_rate = avg_profit_pct = avg_profit_dollar = avg_duration = turnover = margin = None

    per_stock_total = capital.get("per_stock_total", 600)
    total_pool = len(watchlist) * per_stock_total
    return_on_pool = total_profit / total_pool * 100 if total_pool > 0 else 0

    # Unrealized P/L
    unrealized = 0.0
    for ticker, pos in positions.items():
        shares = pos.get("shares", 0)
        if not isinstance(shares, int) or shares <= 0:
            continue
        avg_cost = pos.get("avg_cost", 0)
        price_data = live_prices.get(ticker, {})
        current = price_data.get("price")
        if current is not None:
            unrealized += (current - avg_cost) * shares

    net_pl = total_profit + unrealized

    rows = [
        ("Total Realized Profit ($)", f"${total_profit:+,.2f}"),
        ("Total Realized Cycles", str(n_cycles)),
        ("Win Rate", f"{win_rate:.1f}%" if win_rate is not None else "--"),
        ("Avg Profit/Cycle (%)", f"{avg_profit_pct:+.1f}%" if avg_profit_pct is not None else "--"),
        ("Avg Profit/Cycle ($)", f"${avg_profit_dollar:+,.2f}" if avg_profit_dollar is not None else "--"),
        ("Avg Cycle Duration", f"{avg_duration:.1f} days" if avg_duration is not None else "--"),
        ("Total Capital Turnover", f"${turnover:,.2f}" if turnover is not None else "--"),
        ("Profit Margin on Turnover", f"{margin:.2f}%" if margin is not None else "--"),
        ("Return on Pool Capital", f"{return_on_pool:.2f}%"),
        ("Unrealized P/L ($)", f"${unrealized:+,.2f}"),
        ("Net P/L ($)", f"${net_pl:+,.2f}"),
    ]
    return rows


def compute_period_breakdown(closed, today):
    """Compute Table 2: Period Breakdown."""
    periods = [
        ("This Week", "week"),
        ("This Month", "month"),
        ("Last 30 Days", "last30"),
        ("YTD", "ytd"),
        ("All Time", "all"),
    ]

    rows = []
    for label, period in periods:
        filtered = filter_period(closed, period, today)
        n = len(filtered)
        if n > 0:
            wins = len([c for c in filtered if c["profit_pct"] > 0.0])
            wr = wins / n * 100
            profit = sum(c["profit_dollar"] for c in filtered)
            avg_pct = sum(c["profit_pct"] for c in filtered) / n
            rows.append((label, str(n), f"{wr:.0f}%", f"${profit:+,.2f}", f"{avg_pct:+.1f}%"))
        else:
            rows.append((label, "0", "--", "--", "--"))

    return rows


def compute_ticker_ranking(cycles, portfolio, live_prices, today):
    """Compute Table 3: Per-Ticker Ranking."""
    positions = portfolio.get("positions", {})
    cooldowns = []
    cooldown_path = PROJECT_ROOT / "cooldown.json"
    if cooldown_path.exists():
        cooldowns = load_json(cooldown_path).get("cooldowns", [])
    cooldown_tickers = {c["ticker"]: c for c in cooldowns if parse_date(c["reeval_date"]) > today}

    # Group cycles by ticker
    by_ticker = {}
    for c in cycles:
        by_ticker.setdefault(c["ticker"], []).append(c)

    rows = []
    for ticker in sorted(by_ticker.keys()):
        ticker_cycles = by_ticker[ticker]
        closed = [c for c in ticker_cycles if c["status"] == "closed"]
        open_c = [c for c in ticker_cycles if c["status"] == "open"]
        n_closed = len(closed)

        if n_closed > 0:
            wins = len([c for c in closed if c["profit_pct"] > 0.0])
            win_pct = wins / n_closed * 100
            avg_pct = sum(c["profit_pct"] for c in closed) / n_closed
            total_dollar = sum(c["profit_dollar"] for c in closed)
            turnover = sum(c["entry_avg"] * c["entry_shares"] for c in closed)
            total_profit_pct = total_dollar / turnover * 100 if turnover > 0 else 0

            first_entry = min(c["first_entry_date"] for c in ticker_cycles)
            obs_days = (today - parse_date(first_entry)).days
            if obs_days >= 30:
                ann = total_profit_pct * (365 / obs_days)
                ann_str = f"{ann:.1f}%"
            else:
                ann_str = "N/A (< 30d data)"
        else:
            win_pct = avg_pct = total_dollar = 0
            ann_str = "N/A"

        # Status label
        has_open_pos = False
        unrealized_pct = None
        days_held = None
        pos = positions.get(ticker, {})
        pos_shares = pos.get("shares", 0) if isinstance(pos.get("shares", 0), int) else 0
        if pos_shares > 0:
            has_open_pos = True
            avg_cost = pos.get("avg_cost", 0)
            price_data = live_prices.get(ticker, {})
            current = price_data.get("price")
            if current and avg_cost > 0:
                unrealized_pct = (current - avg_cost) / avg_cost * 100

            entry_date = pos.get("entry_date", "")
            if entry_date.startswith("pre-"):
                days_held = 999
            elif entry_date:
                try:
                    days_held = (today - parse_date(entry_date)).days
                except ValueError:
                    days_held = None

        if has_open_pos and n_closed == 0:
            status = "No Cycles"
        elif has_open_pos and (
            (unrealized_pct is not None and unrealized_pct <= -15.0) or
            (days_held is not None and days_held >= 60)
        ):
            status = "Trapped"
        elif has_open_pos and unrealized_pct is not None and unrealized_pct < 0.0:
            status = "Underwater"
        elif has_open_pos:
            status = "Active"
        elif not has_open_pos and ticker in cooldown_tickers:
            status = "Cooldown"
        elif not has_open_pos and n_closed >= 1:
            status = "Re-entry"
        else:
            status = "Watching"

        rows.append({
            "ticker": ticker,
            "cycles": n_closed,
            "win_pct": win_pct,
            "avg_pct": avg_pct,
            "total_dollar": total_dollar,
            "ann_str": ann_str,
            "status": status,
        })

    # Sort by total_dollar descending, then alphabetically for ties/zero cycles
    rows.sort(key=lambda r: (-r["total_dollar"], r["ticker"]))

    return rows


def compute_open_health(portfolio, live_prices, today):
    """Compute Table 4: Open Position Health."""
    positions = portfolio.get("positions", {})
    rows = []

    for ticker in sorted(positions.keys()):
        pos = positions[ticker]
        shares = pos.get("shares", 0)
        if not isinstance(shares, int) or shares <= 0:
            continue

        avg_cost = pos.get("avg_cost", 0)
        price_data = live_prices.get(ticker, {})
        current = price_data.get("price")
        if current and avg_cost > 0:
            pl_pct = (current - avg_cost) / avg_cost * 100
            pl_str = f"{pl_pct:+.1f}%"
        else:
            pl_str = "N/A"

        entry_date = pos.get("entry_date", "")
        if entry_date.startswith("pre-"):
            days_str = ">60 (est)"
            time_stop = "REVIEW"
        elif entry_date:
            try:
                dh = (today - parse_date(entry_date)).days
                days_str = str(dh)
                time_stop = "REVIEW" if dh >= 60 else "OK"
            except ValueError:
                days_str = "?"
                time_stop = "?"
        else:
            days_str = "?"
            time_stop = "?"

        bullets = pos.get("bullets_used", "?")

        rows.append((ticker, str(shares), f"${avg_cost:.2f}",
                      f"${current:.2f}" if current else "N/A",
                      pl_str, days_str, str(bullets), time_stop))

    return rows


def compute_benchmark(closed, today):
    """Compute Table 5: Benchmark Comparison."""
    periods = [
        ("This Week", "week"),
        ("This Month", "month"),
        ("Last 30 Days", "last30"),
        ("YTD", "ytd"),
        ("All Time", "all"),
    ]

    # Determine earliest entry for "All Time"
    if closed:
        all_time_start = min(parse_date(c["first_entry_date"]) for c in closed)
    else:
        all_time_start = today - timedelta(days=30)

    # Fetch benchmark data
    benchmarks = {}
    for sym in ["SPY", "QQQ"]:
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="1y")
            if not hist.empty:
                benchmarks[sym] = hist
        except Exception:
            pass

    rows = []
    for label, period in periods:
        # Strategy return for this period
        filtered = filter_period(closed, period, today)
        if filtered:
            turnover = sum(c["entry_avg"] * c["entry_shares"] for c in filtered)
            profit = sum(c["profit_dollar"] for c in filtered)
            strat_ret = profit / turnover * 100 if turnover > 0 else 0
            strat_str = f"{strat_ret:+.1f}%"
        else:
            strat_ret = None
            strat_str = "N/A"

        # Period start date
        if period == "week":
            start = today - timedelta(days=today.weekday())
        elif period == "month":
            start = today.replace(day=1)
        elif period == "last30":
            start = today - timedelta(days=30)
        elif period == "ytd":
            start = today.replace(month=1, day=1)
        else:
            start = all_time_start

        for sym in ["SPY", "QQQ"]:
            hist = benchmarks.get(sym)
            if hist is not None and not hist.empty:
                # Find closest date >= start
                mask = hist.index.date >= start
                if mask.any():
                    period_data = hist[mask]
                    if len(period_data) >= 1:
                        close_start = period_data["Close"].iloc[0]
                        close_end = period_data["Close"].iloc[-1]
                        bench_ret = (close_end - close_start) / close_start * 100
                        bench_str = f"{bench_ret:+.1f}%"

                        if strat_ret is not None:
                            excess = strat_ret - bench_ret
                            excess_str = f"{excess:+.1f}%"
                        else:
                            excess_str = "N/A"
                    else:
                        bench_str = "N/A"
                        excess_str = "N/A"
                else:
                    bench_str = "N/A"
                    excess_str = "N/A"
            else:
                bench_str = "N/A"
                excess_str = "N/A"

            rows.append((sym, label, bench_str, strat_str, excess_str))

    return rows


def compute_utilization(portfolio):
    """Compute Table 6: Capital Utilization."""
    positions = portfolio.get("positions", {})
    capital = portfolio.get("capital", {})
    pending_orders = portfolio.get("pending_orders", {})
    watchlist = portfolio.get("watchlist", [])

    ticker_count = len(watchlist)
    per_stock_total = capital.get("per_stock_total", 600)
    total_pool = ticker_count * per_stock_total

    # Active positions at cost
    active_at_cost = sum(
        pos["shares"] * pos["avg_cost"]
        for pos in positions.values()
        if isinstance(pos.get("shares", 0), int) and pos["shares"] > 0
    )

    # Pending buy orders (exclude filled)
    pending_buy = 0.0
    for ticker, orders in pending_orders.items():
        for o in orders:
            if o.get("type", "").upper() == "BUY" and "filled" not in o:
                pending_buy += o.get("price", 0) * o.get("shares", 0)

    available = total_pool - active_at_cost - pending_buy
    utilization = (active_at_cost + pending_buy) / total_pool * 100 if total_pool > 0 else 0

    rows = [
        ("Ticker Count", str(ticker_count)),
        ("Total Pool", f"${total_pool:,.2f}"),
        ("Active Positions (at cost)", f"${active_at_cost:,.2f}"),
        ("Pending Buy Orders", f"${pending_buy:,.2f}"),
        ("Available (idle)", f"${available:,.2f}"),
        ("Utilization Rate", f"{utilization:.1f}%"),
    ]
    return rows


def main():
    parser = argparse.ArgumentParser(description="P/L Dashboard")
    parser.add_argument("--period", choices=["week", "month", "ytd", "all"])
    parser.add_argument("--ticker", help="Filter to specific ticker")
    args = parser.parse_args()

    today = date.today()
    cycle_data = load_json(CYCLE_HISTORY)
    portfolio = load_json(PORTFOLIO)
    all_cycles = cycle_data.get("cycles", [])

    # Filter by ticker if specified
    if args.ticker:
        ticker_upper = args.ticker.upper()
        all_cycles = [c for c in all_cycles if c["ticker"] == ticker_upper]

    closed = [c for c in all_cycles if c["status"] == "closed"]
    open_c = [c for c in all_cycles if c["status"] == "open"]

    # Filter by period if specified
    if args.period:
        closed = filter_period(closed, args.period, today)

    # Fetch live prices for open positions
    positions = portfolio.get("positions", {})
    active_tickers = [t for t, p in positions.items()
                      if isinstance(p.get("shares", 0), int) and p["shares"] > 0]
    live_prices = fetch_prices(active_tickers) if active_tickers else {}

    parts = []
    header = f"# P/L Dashboard — {as_of_date_label(today)}"
    parts.append(header)
    parts.append("")

    # Table 1: Summary
    parts.append("## Summary")
    parts.append("| Metric | Value |")
    parts.append("| :--- | :--- |")
    for label, value in compute_summary(closed, open_c, portfolio, live_prices):
        parts.append(f"| {label} | {value} |")
    parts.append("")

    # Table 2: Period Breakdown
    parts.append("## Period Breakdown")
    parts.append("| Period | Cycles | Win Rate | Profit ($) | Avg/Cycle (%) |")
    parts.append("| :--- | :--- | :--- | :--- | :--- |")
    for row in compute_period_breakdown(closed, today):
        parts.append(f"| {' | '.join(row)} |")
    parts.append("")

    # Table 3: Per-Ticker Ranking
    parts.append("## Per-Ticker Ranking")
    parts.append("| Rank | Ticker | Cycles | Win% | Avg Profit (%) | Total $ | Simple Ann. | Status |")
    parts.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    ranking = compute_ticker_ranking(cycle_data.get("cycles", []), portfolio, live_prices, today)
    if args.ticker:
        ranking = [r for r in ranking if r["ticker"] == args.ticker.upper()]
    for i, r in enumerate(ranking, 1):
        win_str = f"{r['win_pct']:.0f}%" if r['cycles'] > 0 else "--"
        avg_str = f"{r['avg_pct']:+.1f}%" if r['cycles'] > 0 else "--"
        total_str = f"${r['total_dollar']:+,.2f}" if r['cycles'] > 0 else "--"
        parts.append(f"| {i} | {r['ticker']} | {r['cycles']} | {win_str} | {avg_str} | {total_str} | {r['ann_str']} | {r['status']} |")
    parts.append("")

    # Table 4: Open Position Health
    parts.append("## Open Position Health")
    parts.append("| Ticker | Shares | Avg Cost | Current | P/L | Days Held | Bullets | Time Stop |")
    parts.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    health = compute_open_health(portfolio, live_prices, today)
    if args.ticker:
        health = [r for r in health if r[0] == args.ticker.upper()]
    for row in health:
        parts.append(f"| {' | '.join(row)} |")
    parts.append("")

    # Table 5: Benchmark Comparison
    parts.append("## Benchmark Comparison")
    parts.append("| Benchmark | Period | Benchmark Return | Strategy Return | Excess Return |")
    parts.append("| :--- | :--- | :--- | :--- | :--- |")
    for row in compute_benchmark(closed, today):
        parts.append(f"| {' | '.join(row)} |")
    parts.append("")

    # Table 6: Capital Utilization
    parts.append("## Capital Utilization")
    parts.append("| Metric | Value |")
    parts.append("| :--- | :--- |")
    for label, value in compute_utilization(portfolio):
        parts.append(f"| {label} | {value} |")
    parts.append("")

    output_text = "\n".join(parts)
    OUTPUT.write_text(output_text, encoding="utf-8")

    # Also print to stdout
    print(output_text)


if __name__ == "__main__":
    main()
