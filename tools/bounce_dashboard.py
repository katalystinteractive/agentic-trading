"""Bounce Dashboard — track active bounce trades, cached signals, exit alerts.

Reads cached bounce_analysis.json files (does NOT re-run hourly analysis).
Fetches live price + RSI only for active trades.

Usage:
    python3 tools/bounce_dashboard.py          # actionable levels only
    python3 tools/bounce_dashboard.py --all    # include WEAK/NO DATA levels
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

import yfinance as yf
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO = ROOT / "portfolio.json"
AGENTS_DIR = ROOT / "agents"


def load_portfolio():
    return json.loads(PORTFOLIO.read_text())


def calc_rsi(series, period=14):
    """Simple RSI calculation (standalone — no cross-imports)."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def get_price_and_rsi(ticker):
    """Fetch current price and RSI for a single ticker."""
    try:
        df = yf.download(ticker, period="3mo", interval="1d", progress=False)
        if df.empty:
            return None, None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        price = float(df["Close"].iloc[-1])
        rsi_val = float(calc_rsi(df["Close"]).iloc[-1])
        return price, rsi_val
    except Exception:
        return None, None


def count_trading_days(entry_date_str):
    """Count trading days since entry (weekdays only)."""
    try:
        entry = datetime.strptime(entry_date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return "?"
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    days = 0
    current = entry
    while current < today:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days += 1
    return days


def load_cached_signals():
    """Load all bounce_analysis.json cache files from agent directories."""
    signals = []
    if not AGENTS_DIR.exists():
        return signals
    for json_file in sorted(AGENTS_DIR.glob("*/bounce_analysis.json")):
        try:
            data = json.loads(json_file.read_text())
            signals.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return signals


def check_overlap(ticker, portfolio):
    """Check if ticker overlaps with Surgical or Velocity pools."""
    surgical = set(portfolio.get("positions", {}).keys()) | \
               set(portfolio.get("pending_orders", {}).keys()) | \
               set(portfolio.get("watchlist", []))
    velocity = set(portfolio.get("velocity_positions", {}).keys()) | \
               set(portfolio.get("velocity_pending", {}).keys()) | \
               set(portfolio.get("velocity_watchlist", []))
    if ticker in surgical:
        return "Surgical"
    if ticker in velocity:
        return "Velocity"
    return None


def run_dashboard(show_all=False):
    portfolio = load_portfolio()
    bounce_cap = portfolio.get("bounce_capital", {})
    bounce_positions = portfolio.get("bounce_positions", {})

    total_pool = bounce_cap.get("total_pool", 1000)
    max_concurrent = bounce_cap.get("max_concurrent", 10)
    stop_loss_pct = bounce_cap.get("stop_loss_pct", 3.0)
    time_stop_days = bounce_cap.get("time_stop_days", 3)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n## Bounce Dashboard — {now}")

    # --- Active Trades ---
    trade_data = {}
    for ticker, pos in bounce_positions.items():
        current, rsi = get_price_and_rsi(ticker)
        entry_price = pos.get("entry_price", 0)
        if current is None:
            current = entry_price
            rsi = None
        pnl_pct = ((current - entry_price) / entry_price) * 100 if entry_price > 0 else 0
        days_in = count_trading_days(pos.get("entry_date", ""))
        trade_data[ticker] = {"current": current, "rsi": rsi, "pnl_pct": pnl_pct, "days_in": days_in}

    print("\n### Active Trades")
    if bounce_positions:
        print("| Ticker | Entry | Current | P/L% | RSI | Day | Stop | Target | Status |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

        deployed = 0
        for ticker, pos in bounce_positions.items():
            entry_price = pos.get("entry_price", 0)
            shares = pos.get("shares", 0)
            stop_price = pos.get("stop_price", 0)
            target_price = pos.get("target_price", 0)

            td = trade_data[ticker]
            current = td["current"]
            rsi = td["rsi"]
            pnl_pct = td["pnl_pct"]
            days_in = td["days_in"]
            deployed += shares * entry_price

            # Status (exit rules in priority order)
            if current >= target_price:
                status = "TARGET HIT"
            elif pnl_pct <= -stop_loss_pct:
                status = "STOP HIT"
            elif rsi is not None and rsi > 70:
                status = "OVERBOUGHT"
            elif isinstance(days_in, int) and days_in >= time_stop_days:
                status = "TIME STOP"
            elif pnl_pct > 0:
                status = "In Profit"
            else:
                status = "Underwater"

            rsi_str = f"{rsi:.0f}" if rsi is not None else "N/A"
            print(
                f"| {ticker} | ${entry_price:.2f} | ${current:.2f} | "
                f"{pnl_pct:+.1f}% | {rsi_str} | {days_in}/{time_stop_days} | "
                f"${stop_price:.2f} | ${target_price:.2f} | {status} |"
            )
    else:
        print("*No active bounce trades.*")
        deployed = 0

    # --- Capital ---
    available = total_pool - deployed
    open_trades = len(bounce_positions)

    print("\n### Capital")
    print("| Metric | Value |")
    print("| :--- | :--- |")
    print(f"| Pool | ${total_pool:,.0f} |")
    print(f"| Deployed | ${deployed:,.0f} |")
    print(f"| Available | ${available:,.0f} |")
    print(f"| Open Trades | {open_trades}/{max_concurrent} |")

    # --- Cached Bounce Signals ---
    actionable_verdicts = {"STRONG BOUNCE", "BOUNCE"}
    label = "Cached Bounce Signals" if show_all else "Cached Bounce Signals (actionable only)"
    print(f"\n### {label}")
    cached = load_cached_signals()
    if cached:
        # Flatten levels across all cached tickers, sorted by verdict then bounce magnitude
        verdict_order = {"STRONG BOUNCE": 0, "BOUNCE": 1, "WEAK": 2, "NO DATA": 3}
        all_levels = []
        for data in cached:
            ticker = data.get("ticker", "?")
            generated = data.get("generated", "?")
            for lvl in data.get("levels", []):
                entry = {**lvl, "_ticker": ticker, "_generated": generated}
                all_levels.append(entry)

        if not show_all:
            all_levels = [l for l in all_levels if l.get("verdict") in actionable_verdicts]

        all_levels.sort(key=lambda x: (
            verdict_order.get(x.get("verdict", "NO DATA"), 9),
            -(x.get("bounce_3d_median") or 0),
        ))

        if all_levels:
            print("| Ticker | Level | Source | Hold% | Bounce 3D | >= 4.5% | Buy At | Verdict | Cached | Overlap |")
            print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            for lvl in all_levels:
                ticker = lvl["_ticker"]
                overlap = check_overlap(ticker, portfolio)
                if ticker in bounce_positions:
                    overlap_str = "Active"
                elif overlap:
                    overlap_str = overlap
                else:
                    overlap_str = "-"
                hr = f"{lvl.get('hold_rate', 0):.0%}"
                b3 = f"+{lvl['bounce_3d_median']:.1f}%" if lvl.get("bounce_3d_median") is not None else "N/A"
                p45 = f"{lvl.get('pct_above_4_5', 0):.0%}"
                if lvl.get("buy_at"):
                    buy = f"${lvl['buy_at']:.2f}"
                    if lvl.get("verdict") not in actionable_verdicts:
                        buy += "*"
                else:
                    buy = "N/A"
                print(
                    f"| {ticker} | ${lvl.get('price', 0):.2f} | {lvl.get('source', '?')} "
                    f"| {hr} | {b3} | {p45} | {buy} "
                    f"| {lvl.get('verdict', '?')} | {lvl['_generated']} | {overlap_str} |"
                )
            if show_all and any(l.get("verdict") not in actionable_verdicts for l in all_levels):
                print("\n*\\* Buy At is raw support level (not wick-adjusted) — informational only, do not use for orders.*")
        else:
            msg = "*Cached files found but no level data.*" if show_all else \
                  "*No actionable levels (STRONG BOUNCE / BOUNCE). Run with `--all` to see all levels.*"
            print(msg)
    else:
        print("*No cached bounce signals. Run `python3 tools/bounce_analyzer.py <TICKER>` to generate.*")

    # --- Exit Alerts ---
    alerts = []
    for ticker, pos in bounce_positions.items():
        td = trade_data.get(ticker)
        if td is None:
            continue

        current = td["current"]
        pnl_pct = td["pnl_pct"]
        days_in = td["days_in"]
        rsi = td["rsi"]
        entry_price = pos.get("entry_price", 0)
        target_price = pos.get("target_price", 0)

        if current >= target_price:
            alerts.append(f"**{ticker}**: TARGET HIT at ${current:.2f} (+{pnl_pct:.1f}%) — SELL NOW")
        elif pnl_pct <= -stop_loss_pct:
            alerts.append(f"**{ticker}**: STOP HIT at ${current:.2f} ({pnl_pct:.1f}%) — SELL NOW")
        elif rsi is not None and rsi > 70:
            alerts.append(f"**{ticker}**: OVERBOUGHT (RSI {rsi:.0f}) at ${current:.2f} ({pnl_pct:+.1f}%) — SELL NOW")
        elif isinstance(days_in, int) and days_in >= time_stop_days:
            alerts.append(f"**{ticker}**: TIME STOP (day {days_in}) at ${current:.2f} ({pnl_pct:+.1f}%) — SELL NOW")

    if alerts:
        print("\n### Exit Alerts")
        for a in alerts:
            print(f"- {a}")


if __name__ == "__main__":
    run_dashboard(show_all="--all" in sys.argv)
