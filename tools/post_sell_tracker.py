#!/usr/bin/env python3
"""
Post-Sell Tracker — Track 5 trading days of price action after each sell.
Extends cycle_history.json with post_sell_tracking fields.

Usage: python3 tools/post_sell_tracker.py [--backfill]
"""

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yfinance as yf

from trading_calendar import is_trading_day

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CYCLE_HISTORY = PROJECT_ROOT / "cycle_history.json"


def get_trading_days_after(sell_date, n=5):
    """Return list of the next n trading days after sell_date."""
    days = []
    d = sell_date + timedelta(days=1)
    while len(days) < n:
        if is_trading_day(d):
            days.append(d)
        d += timedelta(days=1)
        if d > date.today() + timedelta(days=30):  # safety limit
            break
    return days


def count_elapsed_trading_days(sell_date, today):
    """Count trading days elapsed since sell_date (exclusive of sell date)."""
    count = 0
    d = sell_date + timedelta(days=1)
    while d <= today:
        if is_trading_day(d):
            count += 1
        d += timedelta(days=1)
    return count


def fetch_post_sell_data(ticker, sell_date_str, sell_price):
    """Fetch price data for the tracking window after a sell."""
    sell_date = datetime.strptime(sell_date_str, "%Y-%m-%d").date()
    today = date.today()

    elapsed = count_elapsed_trading_days(sell_date, today)
    tracking_complete = elapsed >= 5

    # Fetch enough data to cover the window
    try:
        t = yf.Ticker(ticker)
        # Fetch 15 calendar days to cover 5 trading days + weekends
        start = sell_date + timedelta(days=1)
        end = sell_date + timedelta(days=15)
        if end > today:
            end = today + timedelta(days=1)
        hist = t.history(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))

        if hist.empty:
            return None
    except Exception:
        return None

    # Only use first 5 trading days
    trading_days_in_window = []
    for idx in range(len(hist)):
        d = hist.index[idx].date()
        if is_trading_day(d) and d > sell_date:
            trading_days_in_window.append(idx)
            if len(trading_days_in_window) >= 5:
                break

    if not trading_days_in_window:
        return None

    window = hist.iloc[trading_days_in_window]
    closes = window["Close"]

    peak = closes.max()
    peak_idx = closes.idxmax()
    peak_date = peak_idx.date().isoformat() if hasattr(peak_idx, 'date') else str(peak_idx)

    trough = closes.min()
    trough_idx = closes.idxmin()
    trough_date = trough_idx.date().isoformat() if hasattr(trough_idx, 'date') else str(trough_idx)

    money_left = max(0, (peak - sell_price) / sell_price * 100)

    result = {
        "sell_price": round(sell_price, 2),
        "sell_date": sell_date_str,
        "peak_after_sell": round(float(peak), 2),
        "peak_date": peak_date,
        "trough_after_sell": round(float(trough), 2),
        "trough_date": trough_date,
        "money_left_on_table_pct": round(money_left, 1),
        "tracking_complete": tracking_complete,
    }

    # 5th trading day close
    if len(trading_days_in_window) >= 5:
        close_5d = float(closes.iloc[4])
        result["close_5d_after"] = round(close_5d, 2)
        result["close_5d_pct"] = round((close_5d - sell_price) / sell_price * 100, 1)
    else:
        result["close_5d_after"] = None
        result["close_5d_pct"] = None

    return result


def main():
    parser = argparse.ArgumentParser(description="Post-Sell Tracker")
    parser.add_argument("--backfill", action="store_true",
                        help="Also fill tracking for historical sells")
    args = parser.parse_args()

    with open(CYCLE_HISTORY) as f:
        data = json.load(f)

    cycles = data.get("cycles", [])
    updated = 0
    skipped = 0
    errors = 0

    for cycle in cycles:
        if cycle["status"] != "closed":
            continue
        if cycle.get("last_exit_date") is None or cycle.get("exit_avg") is None:
            continue

        existing = cycle.get("post_sell_tracking", {})

        # Skip if tracking is already complete (unless backfilling)
        if existing.get("tracking_complete", False) and not args.backfill:
            skipped += 1
            continue

        # Skip incomplete tracking that's not ready for update
        if not args.backfill and existing and not existing.get("tracking_complete", False):
            # Re-check if more days available
            pass

        ticker = cycle["ticker"]
        sell_date = cycle["last_exit_date"]
        sell_price = cycle["exit_avg"]

        result = fetch_post_sell_data(ticker, sell_date, sell_price)
        if result:
            cycle["post_sell_tracking"] = result
            updated += 1
        else:
            errors += 1

    data["last_updated"] = date.today().isoformat()

    with open(CYCLE_HISTORY, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

    # Print summary
    print(f"# Post-Sell Tracker")
    print(f"\nUpdated: {updated} | Skipped (complete): {skipped} | Errors: {errors}")

    tracked = [c for c in cycles if c.get("post_sell_tracking")]
    if tracked:
        print("\n| Cycle | Sell Date | Sell $ | Peak | Left on Table | 5D Close | 5D % | Complete |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for c in tracked:
            t = c["post_sell_tracking"]
            close_5d = f"${t['close_5d_after']:.2f}" if t.get("close_5d_after") else "N/A"
            close_pct = f"{t['close_5d_pct']:+.1f}%" if t.get("close_5d_pct") is not None else "N/A"
            complete = "Yes" if t["tracking_complete"] else "No"
            print(f"| {c['cycle_id']} | {t['sell_date']} | ${t['sell_price']:.2f} | ${t['peak_after_sell']:.2f} | {t['money_left_on_table_pct']:.1f}% | {close_5d} | {close_pct} | {complete} |")

    print(f"\nWrote {CYCLE_HISTORY}")


if __name__ == "__main__":
    main()
