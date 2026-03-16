#!/usr/bin/env python3
"""
Deployment Advisor — Staged bullet deployment recommendations.

Gap addressed: 5.3 (staged bullet deployment)

CLI: python3 tools/deployment_advisor.py
"""

import re
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from technical_scanner import calc_atr
from shared_regime import fetch_regime_detail
from shared_utils import load_json, parse_bullet_label, parse_entry_date
from market_context_gatherer import SECTOR_MAP

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO = PROJECT_ROOT / "portfolio.json"

# Reserve deployment constants
POSITION_AGE_MIN_DAYS = 7
DORMANCY_THRESHOLD_DAYS = 90

# Deployment status enum
DEPLOY_R1_ONLY = "DEPLOY_R1_ONLY"
DEPLOY_R1_R2 = "DEPLOY_R1_R2"
HOLD_MECHANICAL = "HOLD_MECHANICAL"
HOLD_VIX_RISK_ON = "HOLD_VIX_RISK_ON"
HOLD_VIX_CRISIS = "HOLD_VIX_CRISIS"
DEPLOY_PENDING_SECTOR_REVIEW = "DEPLOY_PENDING_SECTOR_REVIEW"


def vix_base_status(vix):
    """Step 1: VIX-based reserve deployment status."""
    if vix is None:
        return DEPLOY_R1_ONLY  # safe default
    if vix < 18:
        return HOLD_VIX_RISK_ON
    if vix <= 25:
        return DEPLOY_R1_ONLY
    if vix <= 35:
        return DEPLOY_R1_R2
    return HOLD_VIX_CRISIS


def check_position_age(ticker, positions):
    """Gate 2a: Position too young? Pre-strategy positions skip."""
    pos = positions.get(ticker, {})
    entry_str = pos.get("entry_date", "")
    if not entry_str:
        return False  # no data = don't gate
    entry, is_pre = parse_entry_date(entry_str)
    if is_pre:
        return False  # pre-strategy positions skip age gate
    if entry is None:
        return False
    return (date.today() - entry).days < POSITION_AGE_MIN_DAYS


def check_dormancy(ticker):
    """Gate 2b: Stock dormant (no cycle activity in 90+ days)?
    Checks both cycles array and current_cycle object."""
    ct_path = PROJECT_ROOT / "tickers" / ticker / "cycle_timing.json"
    ct = load_json(ct_path)
    if not ct:
        return False  # no data = don't gate

    last_activity = None

    # Check current_cycle first — active cycle means NOT dormant
    current_cycle = ct.get("current_cycle", {})
    for date_field in ("resistance_date",):
        d_str = current_cycle.get(date_field)
        if d_str:
            try:
                d = datetime.strptime(d_str, "%Y-%m-%d").date()
                if last_activity is None or d > last_activity:
                    last_activity = d
            except ValueError:
                pass

    # Check cycles array
    cycles = ct.get("cycles", [])
    if cycles:
        last_cycle = cycles[-1]
        for date_field in ("resistance_date", "first_touch_date", "deep_touch_date"):
            d_str = last_cycle.get(date_field)
            if d_str:
                try:
                    d = datetime.strptime(d_str, "%Y-%m-%d").date()
                    if last_activity is None or d > last_activity:
                        last_activity = d
                except ValueError:
                    pass

    if last_activity is None:
        return False  # no parseable dates = don't gate
    return (date.today() - last_activity).days > DORMANCY_THRESHOLD_DAYS


def check_sector_concentration(ticker, positions):
    """Gate 2c: Sector over-concentrated?
    Fires when sector has >3 active positions AND >40% of total active."""
    ticker_sector = SECTOR_MAP.get(ticker)
    if not ticker_sector:
        return False

    sector_counts = {}
    total_active = 0
    for t, pos in positions.items():
        if pos.get("shares", 0) > 0:
            total_active += 1
            s = SECTOR_MAP.get(t, "Unknown")
            sector_counts[s] = sector_counts.get(s, 0) + 1

    if total_active == 0:
        return False

    this_sector_count = sector_counts.get(ticker_sector, 0)
    this_sector_pct = this_sector_count / total_active

    return this_sector_count > 3 and this_sector_pct > 0.40


def compute_reserve_status(ticker, vix, positions):
    """3-step reserve deployment decision tree."""
    base = vix_base_status(vix)
    if base not in (DEPLOY_R1_ONLY, DEPLOY_R1_R2):
        return base
    if check_position_age(ticker, positions):
        return HOLD_MECHANICAL
    if check_dormancy(ticker):
        return HOLD_MECHANICAL
    if check_sector_concentration(ticker, positions):
        return DEPLOY_PENDING_SECTOR_REVIEW
    return base


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
        print("| Ticker | B1 | B2 | B3 | B4 | B5 | R1-R3 | Reserve Status | Action |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        print("| — | — | — | — | — | — | — | — | No pending orders |")
        return

    regime_detail = fetch_regime_detail()
    regime = regime_detail["regime"]
    vix = regime_detail["vix"]
    positions = portfolio.get("positions", {})

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
        def is_filled(slot):
            return slot in slot_map and slot_map[slot]["status"] == "Filled"

        # Pre-compute active B3+ slots (used by reserve rules and action column)
        active_b3_plus = [s for s, sb in slot_map.items()
                          if not sb["is_reserve"] and sb["num"] >= 3]

        recommendations = {}
        hold_capital = 0.0

        for slot, b in slot_map.items():
            if b["status"] == "Filled":
                recommendations[slot] = "Filled"
                continue

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

            # R1-R3: VIX-graduated reserve deployment
            if b["is_reserve"]:
                reserve_status = compute_reserve_status(ticker, vix, positions)
                all_b3_filled = all(is_filled(s) for s in active_b3_plus) if active_b3_plus else False
                if not all_b3_filled:
                    # B3+ not all filled — reserves always hold
                    recommendations[slot] = "Hold"
                    hold_capital += b["shares"] * b["price"]
                elif reserve_status in (HOLD_VIX_RISK_ON, HOLD_VIX_CRISIS, HOLD_MECHANICAL):
                    recommendations[slot] = "Hold"
                    hold_capital += b["shares"] * b["price"]
                elif reserve_status == DEPLOY_PENDING_SECTOR_REVIEW:
                    recommendations[slot] = "Review"
                    hold_capital += b["shares"] * b["price"]
                elif reserve_status == DEPLOY_R1_ONLY:
                    if num == 1:
                        recommendations[slot] = b["status"]
                    else:
                        recommendations[slot] = "Hold"
                        hold_capital += b["shares"] * b["price"]
                elif reserve_status == DEPLOY_R1_R2:
                    if num <= 2:
                        recommendations[slot] = b["status"]
                    else:
                        recommendations[slot] = "Hold"
                        hold_capital += b["shares"] * b["price"]
                else:
                    recommendations[slot] = b["status"]
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

        # Action column — detect Unplaced bullets that rules say to deploy
        place_actions = []
        for slot, rec in recommendations.items():
            b = slot_map.get(slot)
            if not b or b["status"] != "Unplaced" or rec in ("Hold", "Filled"):
                continue
            # B1/B2: always place (standard deploy)
            if not b["is_reserve"] and b["num"] <= 2:
                place_actions.append(f"Place {slot}: standard deploy")
            # B3: within 2×ATR of B2
            elif atr is not None and not b["is_reserve"] and b["num"] == 3:
                b2_price = slot_map.get("B2", {}).get("price")
                if b2_price and abs(current - b2_price) <= 2 * atr:
                    place_actions.append(f"Place {slot}: within 2×ATR of B2")
                elif is_filled("B2"):
                    place_actions.append(f"Place {slot}: B2 filled")
            # B4/B5: Risk-Off or B3 filled
            elif not b["is_reserve"] and b["num"] in (4, 5):
                if regime == "Risk-Off":
                    place_actions.append(f"Place {slot}: Risk-Off regime")
                elif is_filled("B3"):
                    place_actions.append(f"Place {slot}: B3 filled")
            # Reserves: graduated deployment
            elif b["is_reserve"]:
                if rec not in ("Hold", "Filled", "Review"):
                    reserve_status = compute_reserve_status(ticker, vix, positions)
                    place_actions.append(f"Place {slot}: {reserve_status}")

        actions = list(place_actions)
        if hold_capital > 0:
            hold_slots = [s for s, r in recommendations.items() if r == "Hold"]
            actions.append(f"{'+'.join(hold_slots)} capital available: ${hold_capital:.0f}")
        if not actions:
            action_str = "Fully deployed"
        else:
            action_str = "; ".join(actions)

        # Reserve status for display
        res_status = compute_reserve_status(ticker, vix, positions)
        rows.append(f"| {ticker} | {col('B1')} | {col('B2')} | {col('B3')} | {col('B4')} | {col('B5')} | {r_col} | {res_status} | {action_str} |")

    print("### Deployment Recommendations")
    print("| Ticker | B1 | B2 | B3 | B4 | B5 | R1-R3 | Reserve Status | Action |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for row in rows:
        print(row)


if __name__ == "__main__":
    main()
