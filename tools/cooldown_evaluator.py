#!/usr/bin/env python3
"""
Cooldown Evaluator — Automated cooldown assessment for tickers in cooldown.json.

Gap addressed: 2.4 (automated cooldown evaluation)

CLI: python3 tools/cooldown_evaluator.py
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COOLDOWN = PROJECT_ROOT / "cooldown.json"
TRADE_HISTORY = PROJECT_ROOT / "trade_history.json"


def load_json(path):
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def parse_wick_active_levels(ticker):
    """Parse active support levels and their tiers from wick_analysis.md.
    Returns list of dicts: {price, tier, hold_rate}."""
    wick_path = PROJECT_ROOT / "tickers" / ticker / "wick_analysis.md"
    if not wick_path.exists():
        return []
    text = wick_path.read_text(encoding="utf-8")
    levels = []
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
            col_map = {h: i for i, h in enumerate(headers)}
            zone_idx = col_map.get("Zone")
            support_idx = col_map.get("Support") if "Support" in col_map else col_map.get("Level")
            tier_idx = col_map.get("Tier")
            decayed_idx = col_map.get("Decayed")
            if zone_idx is None or support_idx is None:
                continue
            if parts[zone_idx].strip() != "Active":
                continue
            price_str = parts[support_idx].replace("$", "").replace(",", "").strip()
            try:
                price = float(price_str)
            except ValueError:
                continue
            tier = parts[tier_idx].strip() if tier_idx is not None and tier_idx < len(parts) else "Unknown"
            # Extract hold rate from Decayed column
            hold_rate = "N/A"
            if decayed_idx is not None and decayed_idx < len(parts):
                m = re.search(r'(\d+)%', parts[decayed_idx])
                if m:
                    hold_rate = f"{m.group(1)}%"
            levels.append({"price": price, "tier": tier, "hold_rate": hold_rate})
        elif in_table and not line.strip().startswith("|") and line.strip():
            break
    return levels


def get_sell_price(ticker, sold_date_str, trade_history):
    """Get weighted average sell price from trade_history.json.
    Matches SELL records for ticker on or after sold_date."""
    trades = trade_history.get("trades", [])
    sold_date = datetime.strptime(sold_date_str, "%Y-%m-%d").date()
    sells = []
    for t in trades:
        if t.get("ticker") != ticker or t.get("side") != "SELL":
            continue
        try:
            trade_date = datetime.strptime(t["date"], "%Y-%m-%d").date()
        except (ValueError, KeyError):
            continue
        if trade_date >= sold_date:
            sells.append(t)
    if not sells:
        return None
    total_value = sum(t["price"] * t["shares"] for t in sells)
    total_shares = sum(t["shares"] for t in sells)
    if total_shares == 0:
        return None
    return total_value / total_shares


def check_support_breaks(ticker, sold_date_str, level_prices, df):
    """Check if ALL active support levels broke since sell date.
    A level broke = 2+ consecutive closes below level_price."""
    if not level_prices:
        return False
    try:
        sell_dt = datetime.strptime(sold_date_str, "%Y-%m-%d")
        post_sell = df[df.index >= pd.Timestamp(sell_dt)]
    except Exception:
        return False
    close = post_sell["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    closes = close.values.astype(float)
    if len(closes) < 2:
        return False

    for level_price in level_prices:
        broke = False
        consecutive = 0
        for c in closes:
            if c < level_price:
                consecutive += 1
                if consecutive >= 2:
                    broke = True
                    break
            else:
                consecutive = 0
        if not broke:
            return False  # At least one level held
    return True  # ALL levels broke


def main():
    cooldown_data = load_json(COOLDOWN)
    trade_history = load_json(TRADE_HISTORY)
    cooldowns = cooldown_data.get("cooldowns", [])

    print("### Cooldown Status")
    print("| Ticker | Sold | Sell Price | Current | Decay | Reeval | Best Active Tier | Hold Rate | Verdict |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    if not cooldowns:
        print("| — | — | — | — | No cooldowns | — | — | — | — |")
        return

    for entry in cooldowns:
        ticker = entry.get("ticker", "?")
        sold_date = entry.get("sold_date", "")
        reeval_date = entry.get("reeval_date", "")

        # Format dates
        try:
            sold_display = datetime.strptime(sold_date, "%Y-%m-%d").strftime("%b %d")
        except ValueError:
            sold_display = sold_date
        try:
            reeval_display = datetime.strptime(reeval_date, "%Y-%m-%d").strftime("%b %d")
        except ValueError:
            reeval_display = reeval_date or "—"

        # Sell price from trade_history
        sell_price = get_sell_price(ticker, sold_date, trade_history)
        sell_price_str = f"${sell_price:.2f}" if sell_price else "—"

        # Current price
        try:
            df = yf.download(ticker, period="6mo", auto_adjust=True, progress=False)
            if df.empty:
                print(f"| {ticker} | {sold_display} | {sell_price_str} | *Error* | — | {reeval_display} | — | — | HOLD |")
                continue
            close = df["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            current = float(close.iloc[-1])
        except Exception as e:
            print(f"*Error fetching {ticker}: {e}*")
            print(f"| {ticker} | {sold_display} | {sell_price_str} | *Error* | — | {reeval_display} | — | — | HOLD |")
            continue

        # Decay
        if sell_price is not None:
            decay_pct = (current - sell_price) / sell_price * 100
            decay_str = f"{decay_pct:+.1f}%"
        else:
            decay_pct = None
            decay_str = "—"

        # Active levels from wick_analysis
        active_levels = parse_wick_active_levels(ticker)
        if active_levels:
            # Best tier: Full=4 > Std=3 > Half=2 > Skip=1
            tier_rank = {"Full": 4, "Std": 3, "Half": 2, "Skip": 1}
            # Normalize tier names (strip ^ v suffixes)
            for lv in active_levels:
                clean_tier = re.sub(r'[\^v]', '', lv["tier"]).strip()
                lv["tier_clean"] = clean_tier
                lv["rank"] = tier_rank.get(clean_tier, 0)
            best_rank = max(lv["rank"] for lv in active_levels)
            best_levels = [lv for lv in active_levels if lv["rank"] == best_rank]
            # Among same-rank, pick highest hold rate
            def extract_hr(lv):
                m = re.search(r'(\d+)', lv["hold_rate"])
                return int(m.group(1)) if m else 0
            best_level = max(best_levels, key=extract_hr)
            best_tier = best_level["tier"]
            hold_rate = best_level["hold_rate"]
            level_prices = [lv["price"] for lv in active_levels]
        else:
            # Fallback: try analyze_stock_data
            try:
                from wick_offset_analyzer import analyze_stock_data
                data, err = analyze_stock_data(ticker)
                if data and "bullet_plan" in data:
                    active = data["bullet_plan"].get("active", [])
                    if active:
                        best_tier = max(active, key=lambda x: {"Full": 4, "Std": 3, "Half": 2, "Skip": 1}.get(x.get("tier", ""), 0)).get("tier", "Unknown")
                        hold_rate = "N/A"
                    else:
                        best_tier = "Unknown"
                        hold_rate = "N/A"
                else:
                    best_tier = "Unknown"
                    hold_rate = "N/A"
            except Exception:
                best_tier = "Unknown"
                hold_rate = "N/A"
            level_prices = []

        # Verdict rules (first-match-wins)
        # 1. EXTEND: ALL active support levels broke
        all_broke = check_support_breaks(ticker, sold_date, level_prices, df) if level_prices else False
        if all_broke:
            verdict = "EXTEND"
        # 2. RE-ENTER: decay < 0 AND best tier in (Std, Full)
        # Named RE-ENTER (not EXIT) to avoid confusion with exit-review EXIT = sell
        elif decay_pct is not None and decay_pct < 0:
            clean_best = re.sub(r'[\^v]', '', best_tier).strip()
            if clean_best in ("Std", "Full"):
                verdict = "RE-ENTER"
            else:
                verdict = "HOLD"
        # 3. HOLD: default
        else:
            verdict = "HOLD"

        print(f"| {ticker} | {sold_display} | {sell_price_str} | ${current:.2f} | {decay_str} | {reeval_display} | {best_tier} | {hold_rate} | {verdict} |")


if __name__ == "__main__":
    main()
