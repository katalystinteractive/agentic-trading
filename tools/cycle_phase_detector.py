#!/usr/bin/env python3
"""
Cycle Phase Detector — Assigns cycle phase per ticker with pending BUY orders.

Gap addressed: 2.1 (cycle phase detection)

CLI: python3 tools/cycle_phase_detector.py
"""

import json
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from technical_scanner import calc_atr
from shared_utils import parse_bullet_label

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO = PROJECT_ROOT / "portfolio.json"


def load_json(path):
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def parse_wick_active_supports(ticker):
    """Parse active support levels from wick_analysis.md.
    Returns list of float support prices (raw Support column, not Buy At)."""
    wick_path = PROJECT_ROOT / "tickers" / ticker / "wick_analysis.md"
    if not wick_path.exists():
        return []
    text = wick_path.read_text(encoding="utf-8")
    # Find "Support Levels & Buy Recommendations" table
    supports = []
    in_table = False
    headers = []
    for line in text.split("\n"):
        if "Support Levels" in line and "Buy Recommendations" in line:
            in_table = True
            continue
        if in_table and line.strip().startswith("|"):
            parts = [p.strip() for p in line.split("|")]
            parts = [p for p in parts if p]
            if not headers:
                if "Zone" in parts or "Level" in parts:
                    headers = parts
                continue
            if parts[0].startswith(":") or parts[0].startswith("-"):
                continue
            if len(parts) < len(headers):
                continue
            # Map columns
            col_map = {h: i for i, h in enumerate(headers)}
            zone_idx = col_map.get("Zone")
            support_idx = col_map.get("Support") if "Support" in col_map else col_map.get("Level")
            if zone_idx is None or support_idx is None:
                continue
            zone = parts[zone_idx].strip()
            if zone != "Active":
                continue
            price_str = parts[support_idx].replace("$", "").replace(",", "").strip()
            try:
                supports.append(float(price_str))
            except ValueError:
                pass
        elif in_table and not line.strip().startswith("|") and line.strip():
            break
    return supports


def get_buy_prices_for_ticker(ticker, portfolio):
    """Get unfilled BUY prices from portfolio.json for a ticker."""
    prices = []
    for o in portfolio.get("pending_orders", {}).get(ticker, []):
        if o.get("type", "").upper() == "BUY" and not o.get("filled"):
            prices.append(o["price"])
    return prices


def clamp(val, lo, hi):
    return max(lo, min(hi, val))


def find_local_highs(values, window=10):
    """Find local highs from values array (use High series)."""
    result = []
    for i in range(window, len(values) - window):
        if values[i] == max(values[i - window:i + window + 1]):
            result.append((i, values[i]))
    return result


def find_local_lows(values, window=10):
    """Find local lows from values array (use Low series)."""
    result = []
    for i in range(window, len(values) - window):
        if values[i] == min(values[i - window:i + window + 1]):
            result.append((i, values[i]))
    return result


def apply_phase_rules(position, prev_position, roc, nearest_support, current, atr):
    """Apply first-match-wins phase rules. Returns phase string."""
    # Rule 1: SUPPORT
    at_support = position < 0.15
    if not pd.isna(atr) and atr > 0 and nearest_support is not None:
        at_support = at_support or (abs(current - nearest_support) / atr < 1.0)
    if at_support:
        return "SUPPORT"
    # Rule 2: RESISTANCE
    if position > 0.85 and abs(roc) < 0.005:
        return "RESISTANCE"
    # Rule 3: PULLBACK
    if prev_position is not None and position < prev_position and roc < -0.005:
        return "PULLBACK"
    # Rule 4: RECOVERY (default)
    return "RECOVERY"


def main():
    portfolio = load_json(PORTFOLIO)
    pending = portfolio.get("pending_orders", {})

    # Collect tickers with unfilled BUY orders
    tickers_with_buys = {}
    for ticker, orders in pending.items():
        unfilled = [o for o in orders if o.get("type", "").upper() == "BUY" and not o.get("filled")]
        if unfilled:
            tickers_with_buys[ticker] = unfilled

    if not tickers_with_buys:
        print("### Cycle Phase")
        print("| Ticker | Phase | Days in Phase | Position | B1 Distance | Median Cycle | Signal |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        print("| — | — | — | No pending orders | — | — | — |")
        return

    rows = []
    for ticker, unfilled_orders in sorted(tickers_with_buys.items()):
        try:
            df = yf.download(ticker, period="6mo", auto_adjust=True, progress=False)
            if df.empty:
                print(f"*Error: empty data for {ticker}*")
                continue
        except Exception as e:
            print(f"*Error fetching {ticker}: {e}*")
            continue

        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        high_series = df["High"]
        if isinstance(high_series, pd.DataFrame):
            high_series = high_series.iloc[:, 0]
        low_series = df["Low"]
        if isinstance(low_series, pd.DataFrame):
            low_series = low_series.iloc[:, 0]

        highs = high_series.values.astype(float)
        lows = low_series.values.astype(float)
        closes = close.values.astype(float)
        current = closes[-1]

        # ATR
        atr_series = calc_atr(df["High"], df["Low"], df["Close"])
        if isinstance(atr_series, pd.DataFrame):
            atr_series = atr_series.iloc[:, 0]
        atr_val = float(atr_series.iloc[-1])
        if pd.isna(atr_val) or atr_val <= 0:
            print(f"*Warning: ATR unavailable for {ticker}*")
            atr_val = float("nan")

        # Local extremes — highs from High series, lows from Low series
        local_highs_list = find_local_highs(highs)
        local_lows_list = find_local_lows(lows)
        local_high = local_highs_list[-1][1] if local_highs_list else max(highs)
        local_low = local_lows_list[-1][1] if local_lows_list else min(lows)

        # Position ratio
        if local_high == local_low or (local_high - local_low) / local_high < 0.015:
            position = 0.5
        else:
            position = clamp((current - local_low) / (local_high - local_low), 0.0, 1.0)

        # Previous position
        if len(closes) >= 2:
            prev_close = closes[-2]
            if local_high == local_low or (local_high - local_low) / local_high < 0.015:
                prev_position = 0.5
            else:
                prev_position = clamp((prev_close - local_low) / (local_high - local_low), 0.0, 1.0)
        else:
            prev_position = None

        # ROC 3-day
        if len(closes) >= 4:
            roc = (closes[-1] - closes[-4]) / closes[-4]
        else:
            roc = 0.0

        # Nearest active support
        active_supports = parse_wick_active_supports(ticker)
        if not active_supports:
            active_supports = get_buy_prices_for_ticker(ticker, portfolio)
        nearest_support = min(active_supports, key=lambda s: abs(current - s)) if active_supports else None

        # Phase
        phase = apply_phase_rules(position, prev_position, roc, nearest_support, current, atr_val)

        # Days in phase
        days_in_phase = 1
        if len(closes) >= 5:
            for lookback in range(2, min(31, len(closes) - 3)):
                prev_pos = clamp((closes[-lookback] - local_low) / (local_high - local_low), 0, 1) if (local_high - local_low) / max(local_high, 0.01) >= 0.015 else 0.5
                prev_prev_pos = clamp((closes[-lookback - 1] - local_low) / (local_high - local_low), 0, 1) if (local_high - local_low) / max(local_high, 0.01) >= 0.015 else 0.5
                if len(closes) > lookback + 3:
                    prev_roc = (closes[-lookback] - closes[-lookback - 3]) / closes[-lookback - 3]
                else:
                    prev_roc = 0.0
                prev_phase = apply_phase_rules(prev_pos, prev_prev_pos, prev_roc, nearest_support, closes[-lookback], atr_val)
                if prev_phase != phase:
                    break
                days_in_phase += 1

        # Nearest unfilled BUY (highest price)
        nearest_buy = max(unfilled_orders, key=lambda o: o["price"])
        nearest_label = parse_bullet_label(nearest_buy.get("note", ""))
        nearest_price = nearest_buy["price"]
        dist = (nearest_price - current) / current * 100

        # Signal
        if phase == "SUPPORT":
            signal = "At support floor"
        elif phase == "RESISTANCE":
            signal = "Near local high"
        elif phase == "PULLBACK":
            if not pd.isna(atr_val) and atr_val > 0 and abs(current - nearest_price) / atr_val < 1.0:
                signal = f"{nearest_label} within 1 ATR"
            else:
                signal = "Pulling back"
        elif phase == "RECOVERY":
            signal = "Rising from support"
        else:
            signal = "—"

        # B1 Distance display
        b1_dist_str = f"{dist:+.1f}%"

        # Median cycle from cycle_timing.json
        ct_path = PROJECT_ROOT / "tickers" / ticker / "cycle_timing.json"
        median_cycle = "N/A"
        if ct_path.exists():
            try:
                ct = json.loads(ct_path.read_text())
                stats = ct.get("statistics", {})
                md = stats.get("median_deep") or stats.get("median_first")
                if md:
                    median_cycle = f"{md}d"
            except Exception:
                pass

        rows.append({
            "ticker": ticker,
            "phase": phase,
            "days": days_in_phase,
            "position": position,
            "b1_dist": b1_dist_str,
            "median_cycle": median_cycle,
            "signal": signal,
        })

    # Sort: SUPPORT → PULLBACK → RESISTANCE → RECOVERY
    phase_order = {"SUPPORT": 0, "PULLBACK": 1, "RESISTANCE": 2, "RECOVERY": 3}
    rows.sort(key=lambda r: phase_order.get(r["phase"], 9))

    print("### Cycle Phase")
    print("| Ticker | Phase | Days in Phase | Position | B1 Distance | Median Cycle | Signal |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for r in rows:
        print(f"| {r['ticker']} | {r['phase']} | {r['days']} | {r['position']:.2f} | {r['b1_dist']} | {r['median_cycle']} | {r['signal']} |")


if __name__ == "__main__":
    main()
