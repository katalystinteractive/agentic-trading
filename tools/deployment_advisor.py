#!/usr/bin/env python3
"""
Deployment Advisor — Staged bullet deployment recommendations.

Gap addressed: 5.3 (staged bullet deployment)

CLI: python3 tools/deployment_advisor.py
"""

import json
import re
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from technical_scanner import calc_atr

try:
    from market_context_pre_analyst import classify_regime
except ImportError as e:
    print(f"*Warning: classify_regime import failed ({e}), using Neutral regime*")
    def classify_regime(indices, vix):
        return {"regime": "Neutral", "indices_above": 0, "indices_total": 0,
                "vix_value": None, "reasoning": "Import fallback"}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO = PROJECT_ROOT / "portfolio.json"


def load_json(path):
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def parse_bullet_label(note):
    """Parse bullet label from order note."""
    if not note:
        return "B?"
    prefix = note.split("\u2014")[0].split("—")[0].strip()
    m = re.match(r"Bullets?\s+(\d+\+\d+)", prefix, re.IGNORECASE)
    if m:
        return f"B{m.group(1)}"
    m = re.match(r"B(\d+)\s+reserve", prefix, re.IGNORECASE)
    if m:
        return f"R{m.group(1)}"
    m = re.match(r"Reserve\s+(\d+)", prefix, re.IGNORECASE)
    if m:
        return f"R{m.group(1)}"
    m = re.match(r"Bullet\s+(\d+)", prefix, re.IGNORECASE)
    if m:
        return f"B{m.group(1)}"
    return "B?"


def bullet_number(label):
    """Extract numeric bullet number for sequential ordering. Returns int or 99."""
    m = re.match(r'[BR](\d+)', label)
    if m:
        return int(m.group(1))
    # Combined bullets like B2+3
    m = re.match(r'B(\d+)\+', label)
    if m:
        return int(m.group(1))
    return 99


def is_reserve(label):
    """Check if label is a reserve bullet."""
    return label.startswith("R")


def fetch_regime():
    """Fetch market regime. Returns regime string."""
    try:
        indices = []
        for sym in ["SPY", "QQQ", "IWM"]:
            try:
                df = yf.download(sym, period="6mo", auto_adjust=True, progress=False)
                close = df["Close"]
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                sma50 = close.rolling(50).mean().iloc[-1]
                current = close.iloc[-1]
                vs_50sma = "Above 50-SMA" if current >= sma50 else "Below 50-SMA"
                indices.append({"vs_50sma": vs_50sma})
            except Exception:
                pass
        vix_df = yf.download("^VIX", period="5d", auto_adjust=True, progress=False)
        vix_close = vix_df["Close"]
        if isinstance(vix_close, pd.DataFrame):
            vix_close = vix_close.iloc[:, 0]
        vix_val = float(vix_close.iloc[-1])
        result = classify_regime(indices, {"value": vix_val})
        return result["regime"]
    except Exception as e:
        print(f"*Warning: Regime fetch failed ({e}), using Neutral*")
        return "Neutral"


def get_bullet_status(order):
    """Determine bullet status from order fields."""
    if order.get("filled"):
        return "Filled"
    if order.get("placed", False):
        return "Placed"
    return "Unplaced"


def main():
    portfolio = load_json(PORTFOLIO)
    pending = portfolio.get("pending_orders", {})

    # Collect tickers with BUY orders (including filled for status display)
    tickers_with_buys = {}
    for ticker, orders in pending.items():
        buys = [o for o in orders if o.get("type", "").upper() == "BUY"]
        if buys:
            tickers_with_buys[ticker] = buys

    # Check if any unfilled exist
    has_unfilled = any(
        not o.get("filled") for orders in tickers_with_buys.values() for o in orders
    )

    if not has_unfilled:
        print("### Deployment Recommendations")
        print("| Ticker | B1 | B2 | B3 | B4 | B5 | R1-R3 | Action |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        print("| — | — | — | — | — | — | — | No pending orders |")
        return

    regime = fetch_regime()

    # Fetch ATR per ticker
    ticker_atr = {}
    ticker_current = {}
    for ticker in tickers_with_buys:
        try:
            df = yf.download(ticker, period="6mo", auto_adjust=True, progress=False)
            if df.empty:
                continue
            close = df["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            ticker_current[ticker] = float(close.iloc[-1])
            atr_s = calc_atr(df["High"], df["Low"], df["Close"])
            if isinstance(atr_s, pd.DataFrame):
                atr_s = atr_s.iloc[:, 0]
            val = float(atr_s.iloc[-1])
            if pd.isna(val) or val <= 0:
                print(f"*Warning: ATR unavailable for {ticker}, B3 rule skipped*")
                ticker_atr[ticker] = None
            else:
                ticker_atr[ticker] = val
        except Exception as e:
            print(f"*Error fetching {ticker}: {e}*")

    rows = []
    for ticker, buys in sorted(tickers_with_buys.items()):
        current = ticker_current.get(ticker)
        atr = ticker_atr.get(ticker)
        if current is None:
            continue

        # Parse and sort bullets by price descending (B1 = highest)
        bullets = []
        for o in buys:
            label = parse_bullet_label(o.get("note", ""))
            status = get_bullet_status(o)
            bullets.append({
                "label": label,
                "price": o["price"],
                "shares": o.get("shares", 0),
                "status": status,
                "is_reserve": is_reserve(label),
                "num": bullet_number(label),
            })
        bullets.sort(key=lambda b: -b["price"])

        # Assign sequential numbers for B? labels
        for i, b in enumerate(bullets):
            if b["label"] == "B?":
                b["num"] = i + 1

        # Build slot map: B1-B5, R1-R3
        slot_map = {}  # slot_name -> bullet info
        for b in bullets:
            if b["is_reserve"]:
                slot = f"R{b['num']}"
            else:
                slot = f"B{b['num']}"
            slot_map[slot] = b

        # Determine recommendations
        def get_status(slot):
            if slot not in slot_map:
                return "—"
            b = slot_map[slot]
            if b["status"] == "Filled":
                return "Filled"
            return b["status"]  # Will be overridden by deployment rules below

        def is_filled(slot):
            return slot in slot_map and slot_map[slot]["status"] == "Filled"

        recommendations = {}
        hold_capital = 0.0

        for slot, b in slot_map.items():
            if b["status"] == "Filled":
                recommendations[slot] = "Filled"
                continue

            label = slot
            num = b["num"]

            # B1, B2: always place
            if not b["is_reserve"] and num <= 2:
                recommendations[slot] = b["status"]  # Placed or Unplaced
                continue

            # B3: place if current within 2*ATR of B2, or B2 filled
            if not b["is_reserve"] and num == 3:
                b2_filled = is_filled("B2")
                b2_price = slot_map.get("B2", {}).get("price")
                if b2_filled:
                    recommendations[slot] = b["status"]
                elif atr is not None and b2_price is not None and abs(current - b2_price) <= 2 * atr:
                    recommendations[slot] = b["status"]
                else:
                    recommendations[slot] = "Hold"
                    hold_capital += b["shares"] * b["price"]
                continue

            # B4, B5: place if B3 filled or regime Risk-Off
            if not b["is_reserve"] and num in (4, 5):
                b3_filled = is_filled("B3")
                if b3_filled or regime == "Risk-Off":
                    recommendations[slot] = b["status"]
                else:
                    recommendations[slot] = "Hold"
                    hold_capital += b["shares"] * b["price"]
                continue

            # R1-R3: place if all active B3+ are filled
            if b["is_reserve"]:
                active_b3_plus = [s for s, sb in slot_map.items()
                                  if not sb["is_reserve"] and sb["num"] >= 3]
                all_filled = all(is_filled(s) for s in active_b3_plus) if active_b3_plus else False
                if all_filled:
                    recommendations[slot] = b["status"]
                else:
                    recommendations[slot] = "Hold"
                    hold_capital += b["shares"] * b["price"]
                continue

            # Default: Hold
            recommendations[slot] = "Hold"
            hold_capital += b["shares"] * b["price"]

        # Build row columns
        def col(slot):
            return recommendations.get(slot, "—")

        # R1-R3 combined
        r_statuses = []
        for rn in ["R1", "R2", "R3"]:
            s = recommendations.get(rn, "—")
            if s != "—":
                r_statuses.append(s)
        r_col = ", ".join(r_statuses) if r_statuses else "—"

        # Action column
        actions = []
        for slot, rec in recommendations.items():
            if rec in ("Placed", "Unplaced") and slot_map[slot]["status"] != rec:
                actions.append(f"Place {slot}")
        if hold_capital > 0:
            hold_slots = [s for s, r in recommendations.items() if r == "Hold"]
            actions.append(f"{'+'.join(hold_slots)} capital available: ${hold_capital:.0f}")
        if not actions:
            action_str = "Fully deployed"
        else:
            action_str = "; ".join(actions)

        # Detect "Place" recommendations (unfilled but rule says deploy)
        place_actions = []
        for slot, rec in recommendations.items():
            b = slot_map.get(slot)
            if b and b["status"] == "Unplaced" and rec != "Hold" and rec != "Filled":
                if atr is not None and not b["is_reserve"] and b["num"] == 3:
                    b2_price = slot_map.get("B2", {}).get("price")
                    if b2_price and abs(current - b2_price) <= 2 * atr:
                        place_actions.append(f"Place {slot}: within 2×ATR of B2")
                elif not b["is_reserve"] and b["num"] in (4, 5) and regime == "Risk-Off":
                    place_actions.append(f"Place {slot}: Risk-Off regime")

        if place_actions:
            action_str = "; ".join(place_actions + ([f"Hold capital: ${hold_capital:.0f}"] if hold_capital > 0 else []))

        rows.append(f"| {ticker} | {col('B1')} | {col('B2')} | {col('B3')} | {col('B4')} | {col('B5')} | {r_col} | {action_str} |")

    print("### Deployment Recommendations")
    print("| Ticker | B1 | B2 | B3 | B4 | B5 | R1-R3 | Action |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
