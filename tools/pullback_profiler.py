#!/usr/bin/env python3
"""
Pullback Profiler — Pullback depth distribution per ticker.

Gap addressed: 3.1 (pullback depth profiling)

CLI: python3 tools/pullback_profiler.py [TICKER ...]
     No args = all tickers with pending BUY orders (active + watchlist).
"""

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared_wick import find_local_highs, find_local_lows
from shared_utils import parse_bullet_label

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO = PROJECT_ROOT / "portfolio.json"
DEPTH_STEPS = [-2, -3, -5, -7, -9, -12, -15, -20]


def load_json(path):
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def get_tickers_with_buys(portfolio):
    """Get all tickers that have unfilled BUY orders."""
    tickers = set()
    for ticker, orders in portfolio.get("pending_orders", {}).items():
        for o in orders:
            if o.get("type", "").upper() == "BUY" and not o.get("filled"):
                tickers.add(ticker)
                break
    return sorted(tickers)


def get_unfilled_buys(ticker, portfolio):
    """Get unfilled BUY orders for a ticker."""
    orders = []
    for o in portfolio.get("pending_orders", {}).get(ticker, []):
        if o.get("type", "").upper() == "BUY" and not o.get("filled"):
            orders.append({
                "price": o.get("price", 0),
                "label": parse_bullet_label(o.get("note", "")),
            })
    return sorted(orders, key=lambda x: -x["price"])


def compute_pullbacks(highs, lows):
    """Compute pullback depths from local high-low pairs.

    For each pair of consecutive local highs, find the deepest local low
    between them. For the last high, use lows after it.
    Returns list of (high_val, low_val, depth_pct).
    """
    local_highs = find_local_highs(highs, window=10)
    local_lows = find_local_lows(lows, window=10)

    if not local_highs or not local_lows:
        return []

    pullbacks = []
    for hi_idx in range(len(local_highs)):
        h_i, h_val = local_highs[hi_idx]
        # Define search range for lows
        if hi_idx + 1 < len(local_highs):
            end_idx = local_highs[hi_idx + 1][0]
        else:
            end_idx = len(highs)  # to end of data

        # Find deepest low between h_i and end_idx
        candidate_lows = [(li, lv) for li, lv in local_lows if h_i < li < end_idx]
        if not candidate_lows:
            continue

        deepest = min(candidate_lows, key=lambda x: x[1])
        depth_pct = (deepest[1] - h_val) / h_val * 100

        # Filter: minimum 2% depth
        if depth_pct <= -2.0:
            pullbacks.append((h_val, deepest[1], depth_pct))

    return pullbacks


def build_distribution(pullbacks):
    """Build cumulative distribution at standard depth steps.
    Returns list of (depth_step, reach_pct)."""
    if not pullbacks:
        return [(d, 0.0) for d in DEPTH_STEPS]
    n = len(pullbacks)
    dist = []
    for step in DEPTH_STEPS:
        count = sum(1 for _, _, d in pullbacks if d <= step)
        dist.append((step, count / n * 100))
    return dist


def map_bullets_to_distribution(buy_orders, current_price, distribution):
    """Map bullet levels to distribution fill rates.
    Returns list of dicts with label, price, depth_pct, fill_rate_pct."""
    if not distribution:
        return []
    mapped = []
    for order in buy_orders:
        depth = (order["price"] - current_price) / current_price * 100
        # Interpolate fill rate from distribution
        fill_rate = interpolate_fill_rate(depth, distribution)
        mapped.append({
            "label": order["label"],
            "price": order["price"],
            "depth_pct": round(depth, 1),
            "fill_rate_pct": round(fill_rate, 0),
        })
    return mapped


def interpolate_fill_rate(depth, distribution):
    """Interpolate fill rate from cumulative distribution.
    depth is negative (e.g., -5.2%). distribution is list of (step, reach_pct).
    Returns percentage of pullbacks that reach at least this depth."""
    if depth >= 0:
        return 99.0  # already at or above current price

    steps = [d for d, _ in distribution]
    rates = [r for _, r in distribution]

    # If shallower than shallowest step
    if depth > steps[0]:
        return 99.0
    # If deeper than deepest step
    if depth <= steps[-1]:
        return rates[-1]

    # Linear interpolation between steps
    for i in range(len(steps) - 1):
        if steps[i] >= depth >= steps[i + 1]:
            frac = (depth - steps[i]) / (steps[i + 1] - steps[i])
            return rates[i] + frac * (rates[i + 1] - rates[i])

    return rates[-1]


def detect_phase(close_vals, local_highs_list, local_lows_list, current):
    """Detect current phase from price action."""
    if not local_highs_list or not local_lows_list:
        return "RECOVERY"

    last_high = local_highs_list[-1][1]
    last_low = local_lows_list[-1][1]

    price_range = last_high - last_low if last_high > last_low else 1.0
    position = (current - last_low) / price_range if price_range > 0 else 0.5

    if position < 0.15:
        return "SUPPORT"
    elif position > 0.85:
        return "RESISTANCE"
    elif len(close_vals) >= 4:
        roc = (close_vals[-1] - close_vals[-4]) / close_vals[-4] if close_vals[-4] != 0 else 0
        if roc < -0.005:
            return "PULLBACK"
    return "RECOVERY"


def profile_ticker(ticker, portfolio):
    """Profile a single ticker. Returns (output_lines, cache_dict) or (error_lines, None)."""
    try:
        df = yf.download(ticker, period="13mo", auto_adjust=True, progress=False)
        if df.empty:
            return [f"*Error: {ticker} — empty data*"], None
    except Exception as e:
        return [f"*Error fetching {ticker}: {e}*"], None

    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    if isinstance(high, pd.DataFrame):
        high = high.iloc[:, 0]
    if isinstance(low, pd.DataFrame):
        low = low.iloc[:, 0]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    highs = high.values.tolist()
    lows = low.values.tolist()
    closes = close.values.tolist()
    current = closes[-1]

    # Compute pullbacks
    pullbacks = compute_pullbacks(highs, lows)
    distribution = build_distribution(pullbacks)

    # Stats
    if pullbacks:
        depths = [d for _, _, d in pullbacks]
        avg_depth = sum(depths) / len(depths)
        sorted_depths = sorted(depths)
        mid = len(sorted_depths) // 2
        median_depth = sorted_depths[mid] if len(sorted_depths) % 2 else (sorted_depths[mid - 1] + sorted_depths[mid]) / 2
    else:
        avg_depth = 0.0
        median_depth = 0.0

    # Map bullets
    buy_orders = get_unfilled_buys(ticker, portfolio)
    bullet_fill_rates = map_bullets_to_distribution(buy_orders, current, distribution)

    # Detect phase
    local_highs_list = find_local_highs(highs, window=10)
    local_lows_list = find_local_lows(lows, window=10)
    phase = detect_phase(closes, local_highs_list, local_lows_list, current)

    # Build output
    lines = []
    lines.append(f"### Pullback Depth Profile — {ticker}")
    lines.append("| Depth | % Reaching | Mapped Bullet |")
    lines.append("| :--- | :--- | :--- |")
    for step, reach_pct in distribution:
        # Find matching bullet at this depth
        bullet_match = ""
        for bf in bullet_fill_rates:
            if abs(bf["depth_pct"] - step) < 2.0 and not bullet_match:
                bullet_match = f"{bf['label']} (${bf['price']:.2f}) {bf['fill_rate_pct']:.0f}% fill rate"
        lines.append(f"| {step}% | {reach_pct:.0f}% | {bullet_match or '—'} |")
    lines.append(f"Pullback count: {len(pullbacks)} | Avg depth: {avg_depth:.1f}% | Median depth: {median_depth:.1f}%")
    lines.append("")

    # Cache
    cache = {
        "ticker": ticker,
        "pullback_count": len(pullbacks),
        "avg_depth_pct": round(avg_depth, 1),
        "median_depth_pct": round(median_depth, 1),
        "distribution": [{"depth_pct": s, "reach_pct": round(r, 1)} for s, r in distribution],
        "bullet_fill_rates": bullet_fill_rates,
        "current_phase": phase,
        "last_updated": date.today().isoformat(),
    }

    return lines, cache


def main():
    portfolio = load_json(PORTFOLIO)

    # Determine tickers
    if len(sys.argv) > 1:
        tickers = [t.upper() for t in sys.argv[1:]]
    else:
        tickers = get_tickers_with_buys(portfolio)

    if not tickers:
        print("### Pullback Depth Profile")
        print("*No tickers with pending BUY orders.*")
        return

    all_lines = []
    summary_rows = []

    for ticker in tickers:
        lines, cache = profile_ticker(ticker, portfolio)
        all_lines.extend(lines)

        if cache:
            # Write cache
            cache_dir = PROJECT_ROOT / "tickers" / ticker
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path = cache_dir / "pullback_profile.json"
            with open(cache_path, "w") as f:
                json.dump(cache, f, indent=2)

            # Summary row
            b1_rate = cache["bullet_fill_rates"][0]["fill_rate_pct"] if cache["bullet_fill_rates"] else "—"
            b4_rates = [bf["fill_rate_pct"] for bf in cache["bullet_fill_rates"] if bf["label"] >= "B4"]
            b4_rate = f"{b4_rates[0]:.0f}%" if b4_rates else "—"
            b1_str = f"{b1_rate:.0f}%" if isinstance(b1_rate, float) else b1_rate
            summary_rows.append({
                "ticker": ticker,
                "count": cache["pullback_count"],
                "avg": cache["avg_depth_pct"],
                "median": cache["median_depth_pct"],
                "b1": b1_str,
                "b4": b4_rate,
            })

    # Print per-ticker profiles
    for line in all_lines:
        print(line)

    # Summary table
    if summary_rows:
        print("### Pullback Summary")
        print("| Ticker | Pullbacks | Avg Depth | Median Depth | B1 Fill Rate | B4+ Fill Rate |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for r in summary_rows:
            print(f"| {r['ticker']} | {r['count']} | {r['avg']}% | {r['median']}% | {r['b1']} | {r['b4']} |")


if __name__ == "__main__":
    main()
