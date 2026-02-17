"""Velocity Dashboard — scan all candidates, rank by signal, track active trades."""

import json
from pathlib import Path
from datetime import datetime, timedelta

import yfinance as yf
import pandas as pd

from velocity_scanner import score_velocity_signal
from technical_scanner import calc_rsi

ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO = ROOT / "portfolio.json"


def load_portfolio():
    return json.loads(PORTFOLIO.read_text())


def get_price_and_rsi(ticker):
    """Fetch current price and RSI for a single ticker.

    Returns (price, rsi) tuple. Either may be None on error.
    """
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
    """Count trading days since entry (approximate — weekdays only)."""
    try:
        entry = datetime.strptime(entry_date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return "?"
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    days = 0
    current = entry
    while current < today:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Mon-Fri
            days += 1
    return days


def run_dashboard():
    portfolio = load_portfolio()
    vel_cap = portfolio.get("velocity_capital", {})
    vel_positions = portfolio.get("velocity_positions", {})
    vel_watchlist = portfolio.get("velocity_watchlist", [])

    total_pool = vel_cap.get("total_pool", 1000)
    max_concurrent = vel_cap.get("max_concurrent", 6)
    target_pct = vel_cap.get("target_pct", 4.5)
    stop_pct = vel_cap.get("stop_loss_pct", 3.0)
    time_stop_days = vel_cap.get("time_stop_days", 3)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n## Velocity Dashboard — {now}")

    # --- Active Trades ---
    # Fetch prices + RSI once, cache for reuse in exit alerts
    trade_data = {}  # ticker -> {current, rsi, pnl_pct, days_in}
    for ticker, pos in vel_positions.items():
        current, rsi = get_price_and_rsi(ticker)
        entry_price = pos.get("entry_price", 0)
        if current is None:
            current = entry_price
            rsi = None
        pnl_pct = ((current - entry_price) / entry_price) * 100 if entry_price > 0 else 0
        days_in = count_trading_days(pos.get("entry_date", ""))
        trade_data[ticker] = {"current": current, "rsi": rsi, "pnl_pct": pnl_pct, "days_in": days_in}

    print("\n### Active Trades")
    if vel_positions:
        print("| Ticker | Entry | Current | P/L% | RSI | Day | Stop | Target | Status |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

        deployed = 0
        for ticker, pos in vel_positions.items():
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

            # Determine status (exit rules in priority order)
            if pnl_pct >= target_pct:
                status = "TARGET HIT"
            elif pnl_pct <= -stop_pct:
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
        print("*No active velocity trades.*")
        deployed = 0

    # --- Capital ---
    available = total_pool - deployed
    open_trades = len(vel_positions)

    print("\n### Capital")
    print("| Metric | Value |")
    print("| :--- | :--- |")
    print(f"| Pool | ${total_pool:,.0f} |")
    print(f"| Deployed | ${deployed:,.0f} |")
    print(f"| Available | ${available:,.0f} |")
    print(f"| Open Trades | {open_trades}/{max_concurrent} |")

    # --- Candidate Signals ---
    print("\n### Candidate Signals (sorted by score)")
    if vel_watchlist:
        results = []
        skipped_overlap = []
        for ticker in vel_watchlist:
            if ticker in vel_positions:
                continue  # already in an active trade
            result = score_velocity_signal(ticker)
            if result is None:
                continue
            if result.get("overlap"):
                skipped_overlap.append(ticker)
                continue
            results.append(result)

        # Sort by score descending
        results.sort(key=lambda r: r["score"], reverse=True)

        if results:
            print("| Ticker | Price | Score | RSI | MACD | Boll | Stoch | ATR% | Signal |")
            print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            for r in results:
                comp_map = {c["name"]: c for c in r["components"]}
                rsi_pts = comp_map.get("RSI(14)", {}).get("points", 0)
                macd_pts = comp_map.get("MACD Cross", {}).get("points", 0)
                boll_pts = comp_map.get("Bollinger", {}).get("points", 0)
                stoch_pts = comp_map.get("Stochastic %K", {}).get("points", 0)

                print(
                    f"| {r['ticker']} | ${r['price']:.2f} | {r['score']} | "
                    f"{rsi_pts}/30 | {macd_pts}/25 | {boll_pts}/25 | "
                    f"{stoch_pts}/10 | {r['atr_pct']:.1f}% | {r['verdict']} |"
                )
        else:
            print("*No eligible candidates after filtering.*")
        if skipped_overlap:
            joined = ", ".join(skipped_overlap)
            print(f"\n*Skipped (surgical overlap): {joined}*")
    else:
        print("*No tickers on velocity watchlist. Add tickers to `velocity_watchlist` in portfolio.json.*")

    # --- Exit Alerts (uses cached trade_data — no duplicate API calls) ---
    alerts = []
    for ticker, pos in vel_positions.items():
        td = trade_data.get(ticker)
        if td is None:
            continue

        current = td["current"]
        pnl_pct = td["pnl_pct"]
        days_in = td["days_in"]
        rsi = td["rsi"]

        if pnl_pct >= target_pct:
            alerts.append(f"**{ticker}**: TARGET HIT at ${current:.2f} (+{pnl_pct:.1f}%) — SELL NOW")
        elif pnl_pct <= -stop_pct:
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
    run_dashboard()
