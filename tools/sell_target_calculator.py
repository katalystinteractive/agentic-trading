"""Sell target calculator: data-driven sell targets from math + resistance levels.

Computes profit targets (4.5%/6.0%/7.5%) and finds historical resistance levels
in the target zone using 13-month daily price data. Recommends sell price based
on resistance closest to 6% target, with rejection rate as tiebreaker.

Usage:
    python3 tools/sell_target_calculator.py CIFR
    python3 tools/sell_target_calculator.py CIFR APLD NU   # multi-ticker
"""
import sys
import json
import math
import datetime
import argparse
import numpy as np
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wick_offset_analyzer import fetch_history


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MATH_TARGETS = [
    ("Conservative (4.5%)", 1.045),
    ("Standard (6.0%)", 1.060),
    ("Aggressive (7.5%)", 1.075),
]

MIN_TOUCHES = 2       # Narrow zone (~3% of price), 3+ is too strict
MERGE_PCT = 0.02      # 2% dedup threshold for merging nearby resistance levels


# ---------------------------------------------------------------------------
# Portfolio helpers
# ---------------------------------------------------------------------------

def _load_portfolio():
    with open(PORTFOLIO_PATH, "r") as f:
        return json.load(f)


def _fmt_dollar(val):
    if val is None:
        return "N/A"
    if not isinstance(val, (int, float)):
        return str(val)
    return f"${val:.2f}"


# ---------------------------------------------------------------------------
# Resistance detection
# ---------------------------------------------------------------------------

def find_pa_resistances(hist, zone_low, zone_high):
    """Cluster daily Highs in buffered zone. Uses max(cluster) for resistance price."""
    zone_width = zone_high - zone_low
    buffer = zone_width * 0.5
    search_low = zone_low - buffer
    search_high = zone_high + buffer

    all_highs = hist["High"].values
    # Filter to highs within the search window
    in_zone = np.sort(all_highs[(all_highs >= search_low) & (all_highs <= search_high)])
    if len(in_zone) == 0:
        return []

    clusters = []
    current_cluster = [in_zone[0]]

    for i in range(1, len(in_zone)):
        cluster_med = np.median(current_cluster)
        if cluster_med > 0 and (in_zone[i] - cluster_med) / cluster_med < 0.02:
            current_cluster.append(in_zone[i])
        else:
            if len(current_cluster) >= MIN_TOUCHES:
                clusters.append({
                    "price": round(float(max(current_cluster)), 4),
                    "touches": len(current_cluster),
                    "source": "PA",
                })
            current_cluster = [in_zone[i]]

    if len(current_cluster) >= MIN_TOUCHES:
        clusters.append({
            "price": round(float(max(current_cluster)), 4),
            "touches": len(current_cluster),
            "source": "PA",
        })

    return clusters


def find_hvn_ceilings(hist, zone_low, zone_high, n_bins=40):
    """Volume profile HVN nodes in target zone (180-day decay, 40 bins, 70th pctl)."""
    zone_width = zone_high - zone_low
    buffer = zone_width * 0.5
    search_low = zone_low - buffer
    search_high = zone_high + buffer

    lows = hist["Low"].values
    highs = hist["High"].values
    volumes = hist["Volume"].values
    dates = hist.index

    price_min, price_max = lows.min(), highs.max()
    bin_edges = np.linspace(price_min * 0.95, price_max * 1.05, n_bins + 1)

    reference = dates[-1].to_pydatetime().replace(tzinfo=None)

    vol_by_bin = np.zeros(n_bins)
    for i in range(len(hist)):
        days_old = (reference - dates[i].to_pydatetime().replace(tzinfo=None)).days
        decay = math.exp(-days_old * math.log(2) / 180)
        weighted_vol = volumes[i] * decay

        day_low, day_high = lows[i], highs[i]
        day_range = day_high - day_low if day_high > day_low else 0.01
        for b in range(n_bins):
            bin_lo, bin_hi = bin_edges[b], bin_edges[b + 1]
            if day_low <= bin_hi and day_high >= bin_lo:
                overlap = min(day_high, bin_hi) - max(day_low, bin_lo)
                vol_by_bin[b] += weighted_vol * (overlap / day_range)

    threshold = np.percentile(vol_by_bin, 70)
    ceilings = []
    for b in range(n_bins):
        if vol_by_bin[b] >= threshold:
            bin_top = bin_edges[b + 1]
            if search_low <= bin_top <= search_high:
                ceilings.append({
                    "price": round(float(bin_top), 4),
                    "volume": vol_by_bin[b],
                    "source": "HVN",
                })

    return ceilings


def merge_resistance_levels(pa, hvn):
    """Dedup within 2%, merge sources (HVN+PA). Returns sorted list."""
    all_levels = list(hvn)  # Start with HVN

    for p in pa:
        duplicate = False
        for existing in all_levels:
            if existing["price"] > 0 and abs(p["price"] - existing["price"]) / existing["price"] < MERGE_PCT:
                if "PA" not in existing["source"]:
                    existing["source"] += "+PA"
                existing["touches"] = p.get("touches", 0)
                duplicate = True
                break
        if not duplicate:
            all_levels.append(p)

    # Sort by price ascending (lowest resistance first)
    all_levels.sort(key=lambda x: x["price"])
    return all_levels


def count_resistance_approaches(hist, level, proximity_pct=8.0):
    """Count approach events to a resistance level (inverted logic from support).

    Approach start: high enters within proximity_pct% below resistance level.
    Broke: any bar during approach has close >= level.
    Rejected: approach ends via 3-day gap-out without any bar having close >= level.
    Returns {"approaches": int, "rejected": int, "broke": int, "reject_rate": float}.
    """
    approaches = 0
    rejected = 0
    broke = 0

    in_approach = False
    approach_broke = False
    gap_days = 0
    max_gap = 3

    closes = hist["Close"].values
    highs = hist["High"].values

    for i in range(len(hist)):
        close = closes[i]
        high = highs[i]

        # Distance: how far below the resistance level the high is (as %)
        dist_pct = ((level - high) / level) * 100 if level > 0 else 100

        if 0 <= dist_pct < proximity_pct:
            # High is within proximity zone below resistance
            if not in_approach:
                in_approach = True
                approach_broke = False
            gap_days = 0

            # Check if close broke through resistance
            if close >= level:
                approach_broke = True
        elif dist_pct < 0:
            # High is above resistance — definitely in approach territory
            if not in_approach:
                in_approach = True
                approach_broke = False
            gap_days = 0
            if close >= level:
                approach_broke = True
        else:
            # High is far below resistance
            if in_approach:
                gap_days += 1
                if gap_days >= max_gap:
                    approaches += 1
                    if approach_broke:
                        broke += 1
                    else:
                        rejected += 1
                    in_approach = False
                    gap_days = 0

    # Close any open approach
    if in_approach:
        approaches += 1
        if approach_broke:
            broke += 1
        else:
            rejected += 1

    reject_rate = (rejected / approaches * 100) if approaches > 0 else 0
    return {
        "approaches": approaches,
        "rejected": rejected,
        "broke": broke,
        "reject_rate": round(reject_rate, 1),
    }


# ---------------------------------------------------------------------------
# Recommendation logic
# ---------------------------------------------------------------------------

def recommend_sell(math_targets, resistance_levels):
    """Pick resistance closest to 6% target; tiebreaker: higher rejection rate.

    math_targets: dict with keys "conservative", "standard", "aggressive" -> price.
    resistance_levels: list of dicts with "price", "reject_rate", etc.
    Returns (price, basis_str) or falls back to math 6%.
    """
    standard = math_targets["standard"]

    if not resistance_levels:
        return standard, "Math Standard (6.0%) — no resistance levels found in zone"

    # Find closest to standard target
    best = None
    best_dist = float('inf')
    for lvl in resistance_levels:
        dist = abs(lvl["price"] - standard)
        if dist < best_dist or (dist == best_dist and best is not None
                                and lvl.get("reject_rate", 0) > best.get("reject_rate", 0)):
            best_dist = dist
            best = lvl

    if best is None:
        return standard, "Math Standard (6.0%) — no resistance levels found in zone"

    # Determine which math target it's closest to
    target_names = {
        "conservative": "Conservative (4.5%)",
        "standard": "Standard (6.0%)",
        "aggressive": "Aggressive (7.5%)",
    }
    nearest_target = "Standard (6.0%)"
    nearest_dist = float('inf')
    for key, name in target_names.items():
        d = abs(best["price"] - math_targets[key])
        if d < nearest_dist:
            nearest_dist = d
            nearest_target = name

    basis = f"{best['source']} resistance, {best['reject_rate']:.0f}% rejection rate, closest to {nearest_target}"
    return best["price"], basis


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyze_ticker(ticker, portfolio):
    """Full sell target analysis for a single ticker. Prints markdown report."""
    positions = portfolio.get("positions", {})
    pending_all = portfolio.get("pending_orders", {})

    # Validate position
    if ticker not in positions:
        print(f"*Error: {ticker} not found in active positions*")
        return
    pos = positions[ticker]
    shares = pos.get("shares", 0)
    if shares <= 0:
        print(f"*Error: {ticker} has no active shares*")
        return
    avg_cost = pos.get("avg_cost", 0)
    if avg_cost <= 0:
        print(f"*Error: {ticker} has avg_cost=0 (closed position)*")
        return

    target_exit = pos.get("target_exit")

    # Fetch current price
    try:
        hist = fetch_history(ticker, months=13)
    except Exception:
        print(f"*Error: Could not fetch price data for {ticker}*")
        return
    if hist.empty or len(hist) < 10:
        print(f"*Error: Could not fetch price data for {ticker}*")
        return

    current_price = float(hist["Close"].iloc[-1])
    last_date = hist.index[-1].strftime("%Y-%m-%d")
    now = datetime.datetime.now().strftime("%Y-%m-%d")

    # Compute math targets
    math_prices = {}
    for label, mult in MATH_TARGETS:
        math_prices[label] = round(avg_cost * mult, 2)
    math_prices["conservative"] = math_prices["Conservative (4.5%)"]
    math_prices["standard"] = math_prices["Standard (6.0%)"]
    math_prices["aggressive"] = math_prices["Aggressive (7.5%)"]

    zone_low = math_prices["conservative"]
    zone_high = math_prices["aggressive"]

    # Unrealized P/L
    unrealized_pct = (current_price - avg_cost) / avg_cost * 100
    unrealized_dollar = (current_price - avg_cost) * shares
    sign = "+" if unrealized_pct >= 0 else ""

    # Header
    print(f"## Sell Target Analysis: {ticker}")
    print(f"*Generated: {now} | Data as of: {last_date}*")
    print()

    # Position table
    print("### Position")
    print("| Field | Value |")
    print("| :--- | :--- |")
    print(f"| Shares | {shares} |")
    print(f"| Avg Cost | {_fmt_dollar(avg_cost)} |")
    print(f"| Current Price | {_fmt_dollar(current_price)} |")
    print(f"| Unrealized P/L | {sign}{unrealized_pct:.1f}% ({_fmt_dollar(unrealized_dollar)}) |")
    print(f"| Existing Target | {_fmt_dollar(target_exit) if target_exit else '—'} |")
    print()

    # Math targets table
    print("### Mathematical Targets")
    print("| Target | Price | P/L % | Proceeds |")
    print("| :--- | :--- | :--- | :--- |")
    for label, mult in MATH_TARGETS:
        price = round(avg_cost * mult, 2)
        pct = (mult - 1) * 100
        proceeds = round(price * shares, 2)
        print(f"| {label} | {_fmt_dollar(price)} | +{pct:.1f}% | {_fmt_dollar(proceeds)} |")
    print()

    # Check if current price is already above 7.5% target
    if current_price > zone_high:
        print(f"> Current price ({_fmt_dollar(current_price)}) is already above the 7.5% target ({_fmt_dollar(zone_high)}) — consider taking profit.")
        print()
        # Skip resistance scan — show SELL orders and recommend math target
        _print_sell_orders(ticker, pending_all)
        print("### Recommendation")
        print("| Field | Value |")
        print("| :--- | :--- |")
        print(f"| Recommended Sell | {_fmt_dollar(math_prices['standard'])} |")
        print(f"| Basis | Price above all targets — consider immediate profit-taking |")
        print(f"| Total Shares | {shares} |")
        print(f"| Expected Proceeds | {_fmt_dollar(round(math_prices['standard'] * shares, 2))} |")
        print(f"| Expected P/L | +6.0% |")
        return

    # Find resistance levels in buffered zone
    pa_resistances = find_pa_resistances(hist, zone_low, zone_high)
    hvn_ceilings = find_hvn_ceilings(hist, zone_low, zone_high)
    resistance_levels = merge_resistance_levels(pa_resistances, hvn_ceilings)

    # Count approach/rejection events per level
    for lvl in resistance_levels:
        result = count_resistance_approaches(hist, lvl["price"])
        lvl.update(result)

    # Determine nearest math target for each resistance level
    target_map = {
        "conservative": ("Conservative (4.5%)", math_prices["conservative"]),
        "standard": ("Standard (6.0%)", math_prices["standard"]),
        "aggressive": ("Aggressive (7.5%)", math_prices["aggressive"]),
    }

    # Print resistance levels table
    zone_width = zone_high - zone_low
    buffer = zone_width * 0.5
    search_low = zone_low - buffer
    search_high = zone_high + buffer

    if resistance_levels:
        print(f"### Resistance Levels in Target Zone ({_fmt_dollar(search_low)} — {_fmt_dollar(search_high)})")
        print("| Level | Source | Approaches | Rejected | Reject Rate | Nearest Target |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for lvl in resistance_levels:
            # Find nearest math target
            nearest = "Standard (6.0%)"
            nearest_dist = float('inf')
            for key, (name, price) in target_map.items():
                d = abs(lvl["price"] - price)
                if d < nearest_dist:
                    nearest_dist = d
                    nearest = name
            print(f"| {_fmt_dollar(lvl['price'])} | {lvl['source']} "
                  f"| {lvl['approaches']} | {lvl['rejected']} "
                  f"| {lvl['reject_rate']:.0f}% | {nearest} |")
        print()
    else:
        print(f"### Resistance Levels in Target Zone ({_fmt_dollar(search_low)} — {_fmt_dollar(search_high)})")
        print("*No resistance levels found in target zone.*")
        print()

    # SELL orders
    _print_sell_orders(ticker, pending_all)

    # Recommendation
    rec_price, basis = recommend_sell(math_prices, resistance_levels)
    expected_proceeds = round(rec_price * shares, 2)
    expected_pl = (rec_price - avg_cost) / avg_cost * 100

    print("### Recommendation")
    print("| Field | Value |")
    print("| :--- | :--- |")
    print(f"| Recommended Sell | {_fmt_dollar(rec_price)} |")
    print(f"| Basis | {basis} |")
    print(f"| Total Shares | {shares} |")
    print(f"| Expected Proceeds | {_fmt_dollar(expected_proceeds)} |")
    print(f"| Expected P/L | +{expected_pl:.1f}% |")


def _print_sell_orders(ticker, pending_all):
    """Print existing SELL orders for context."""
    orders = pending_all.get(ticker, [])
    sell_orders = [o for o in orders if o["type"] == "SELL"]

    print("### Existing SELL Orders")
    if not sell_orders:
        print("No pending SELL orders.")
        print()
        return

    print("| Price | Shares | Placed | Note |")
    print("| :--- | :--- | :--- | :--- |")
    for order in sell_orders:
        placed = "Yes" if order.get("placed", False) else "—"
        note = order.get("note", "")
        print(f"| {_fmt_dollar(order['price'])} | {order.get('shares', '—')} | {placed} | {note} |")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Sell target calculator — data-driven sell targets from math + resistance")
    parser.add_argument("tickers", nargs="+", type=str.upper,
                        help="One or more stock ticker symbols")
    args = parser.parse_args()

    portfolio = _load_portfolio()

    for i, ticker in enumerate(args.tickers):
        if i > 0:
            print()
            print("---")
            print()
        analyze_ticker(ticker, portfolio)


if __name__ == "__main__":
    main()
