"""Velocity Dashboard — scan all candidates, rank by signal, track active trades."""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

import yfinance as yf
import pandas as pd
import numpy as np

from velocity_scanner import score_velocity_signal

ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO = ROOT / "portfolio.json"


def load_portfolio():
    return json.loads(PORTFOLIO.read_text())


def get_current_price(ticker):
    """Fetch current price for a single ticker."""
    try:
        df = yf.download(ticker, period="5d", interval="1d", progress=False)
        if df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return float(df["Close"].iloc[-1])
    except Exception:
        return None


def count_trading_days(entry_date_str):
    """Count trading days since entry (approximate — weekdays only)."""
    try:
        entry = datetime.strptime(entry_date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return "?"
    today = datetime.now()
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
    per_trade = vel_cap.get("per_trade_size", 175)
    max_concurrent = vel_cap.get("max_concurrent", 6)
    target_pct = vel_cap.get("target_pct", 4.5)
    stop_pct = vel_cap.get("stop_loss_pct", 3.0)
    time_stop_days = vel_cap.get("time_stop_days", 3)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n## Velocity Dashboard — {now}")

    # --- Active Trades ---
    print("\n### Active Trades")
    if vel_positions:
        print("| Ticker | Entry | Current | P/L% | Day | Stop | Target | Status |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

        deployed = 0
        for ticker, pos in vel_positions.items():
            entry_price = pos.get("entry_price", 0)
            shares = pos.get("shares", 0)
            stop_price = pos.get("stop_price", 0)
            target_price = pos.get("target_price", 0)
            entry_date = pos.get("entry_date", "")
            time_stop_date = pos.get("time_stop_date", "")

            current = get_current_price(ticker)
            if current is None:
                current = entry_price

            pnl_pct = ((current - entry_price) / entry_price) * 100 if entry_price > 0 else 0
            days_in = count_trading_days(entry_date)
            deployed += shares * entry_price

            # Determine status
            if pnl_pct >= target_pct:
                status = "TARGET HIT"
            elif pnl_pct <= -stop_pct:
                status = "STOP HIT"
            elif isinstance(days_in, int) and days_in >= time_stop_days:
                status = "TIME STOP"
            elif pnl_pct > 0:
                status = "In Profit"
            else:
                status = "Underwater"

            print(
                f"| {ticker} | ${entry_price:.2f} | ${current:.2f} | "
                f"{pnl_pct:+.1f}% | {days_in}/{time_stop_days} | "
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
        print("| Ticker | Price | Score | RSI | MACD | Boll | Stoch | ATR% | Signal |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

        results = []
        for ticker in vel_watchlist:
            if ticker in vel_positions:
                continue  # already in an active trade
            result = score_velocity_signal(ticker)
            if result:
                results.append(result)

        # Sort by score descending
        results.sort(key=lambda r: r["score"], reverse=True)

        for r in results:
            # Extract individual component points for compact display
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
        print("*No tickers on velocity watchlist. Add tickers to `velocity_watchlist` in portfolio.json.*")

    # --- Exit Alerts ---
    alerts = []
    for ticker, pos in vel_positions.items():
        entry_price = pos.get("entry_price", 0)
        stop_price = pos.get("stop_price", 0)
        target_price = pos.get("target_price", 0)
        entry_date = pos.get("entry_date", "")

        current = get_current_price(ticker)
        if current is None:
            continue

        pnl_pct = ((current - entry_price) / entry_price) * 100 if entry_price > 0 else 0
        days_in = count_trading_days(entry_date)

        if pnl_pct >= target_pct:
            alerts.append(f"**{ticker}**: TARGET HIT at ${current:.2f} (+{pnl_pct:.1f}%) — SELL NOW")
        elif pnl_pct <= -stop_pct:
            alerts.append(f"**{ticker}**: STOP HIT at ${current:.2f} ({pnl_pct:.1f}%) — SELL NOW")
        elif isinstance(days_in, int) and days_in >= time_stop_days:
            alerts.append(f"**{ticker}**: TIME STOP (day {days_in}) at ${current:.2f} ({pnl_pct:+.1f}%) — SELL NOW")

    if alerts:
        print("\n### Exit Alerts")
        for a in alerts:
            print(f"- {a}")


if __name__ == "__main__":
    run_dashboard()
