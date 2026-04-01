"""Bounce-derived sell target analyzer.

Discovers per-level sell targets from actual historical bounce heights at
support levels. Uses recency-weighted medians (90-day half-life) so recent
bounces matter more than old ones. Combines multi-fill bounce profiles
into a single position sell target weighted by shares.

Usage:
    # Standalone test
    python3 tools/bounce_sell_analyzer.py STIM
"""
import sys
import math
import numpy as np
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))

from wick_offset_analyzer import find_approach_events


# ---------------------------------------------------------------------------
# Per-level bounce measurement (daily data)
# ---------------------------------------------------------------------------

def measure_bounce_daily(hist, approach_start_date, n_days=(2, 3, 5)):
    """Measure max high in N trading days after a support hold resolves.

    Uses daily OHLC data. find_approach_events() returns the approach START
    date. We scan forward to find the min_low date (approach trough), then
    measure bounce from there.

    Args:
        hist: DataFrame with OHLC, DatetimeIndex
        approach_start_date: str YYYY-MM-DD from event["start"]
        n_days: tuple of trading-day windows to measure

    Returns: {n: max_high_price} or {n: None}
    """
    try:
        start_idx = hist.index.get_indexer(
            [approach_start_date], method="nearest")[0]
    except (KeyError, IndexError):
        return {n: None for n in n_days}

    # Scan forward up to 10 days to find the local low (approach trough)
    scan = hist.iloc[start_idx:start_idx + 10]
    if scan.empty:
        return {n: None for n in n_days}
    min_low_idx = start_idx + int(scan["Low"].values.argmin())

    results = {}
    after = hist.iloc[min_low_idx + 1:]
    for n in n_days:
        window = after.iloc[:n]
        if not window.empty:
            results[n] = float(window["High"].max())
        else:
            results[n] = None
    return results


# ---------------------------------------------------------------------------
# Per-level bounce profiles with recency weighting
# ---------------------------------------------------------------------------

def compute_bounce_profiles(hist, levels, decay_half_life=90, bounce_window=3):
    """For each support level, compute recency-weighted bounce statistics.

    Args:
        hist: DataFrame with OHLC (daily, date-masked to current sim day)
        levels: list of support level prices
        decay_half_life: days for exponential decay (default 90)
        bounce_window: trading days to measure bounce (default 3)

    Returns: {level_price: {
        "median_bounce_pct": float,
        "median_bounce_target": float,
        "prior_high_median": float,
        "n_held": int,
        "confidence": float,
        "events": [{date, bounce_pct, max_high, weight}, ...]
    }}
    """
    profiles = {}
    today = hist.index[-1] if len(hist) > 0 else datetime.now()
    decay_lambda = math.log(2) / max(decay_half_life, 1)

    for level_price in levels:
        events = find_approach_events(hist, level_price)
        held_events = [e for e in events if e.get("held")]

        if not held_events:
            profiles[level_price] = {
                "median_bounce_pct": 0,
                "median_bounce_target": level_price,
                "prior_high_median": level_price,
                "n_held": 0,
                "confidence": 0,
                "events": [],
            }
            continue

        bounce_data = []
        for e in held_events:
            bounce_result = measure_bounce_daily(
                hist, e["start"], n_days=(bounce_window,))
            max_high = bounce_result.get(bounce_window)
            if max_high is None:
                continue

            bounce_pct = (max_high - level_price) / level_price * 100
            if bounce_pct <= 0:
                continue  # no meaningful bounce

            # Recency weight
            try:
                event_date = datetime.strptime(e["start"], "%Y-%m-%d")
                if hasattr(today, "date"):
                    days_ago = (today.date() - event_date.date()).days
                else:
                    days_ago = (today - event_date).days
            except (ValueError, TypeError):
                days_ago = 180  # old default

            weight = math.exp(-decay_lambda * max(days_ago, 0))

            bounce_data.append({
                "date": e["start"],
                "bounce_pct": round(bounce_pct, 2),
                "max_high": round(max_high, 2),
                "prior_high": e.get("prior_high", max_high),
                "weight": round(weight, 4),
            })

        if not bounce_data:
            profiles[level_price] = {
                "median_bounce_pct": 0,
                "median_bounce_target": level_price,
                "prior_high_median": level_price,
                "n_held": len(held_events),
                "confidence": 0,
                "events": [],
            }
            continue

        # Weighted median computation
        weights = np.array([d["weight"] for d in bounce_data])
        bounce_pcts = np.array([d["bounce_pct"] for d in bounce_data])
        prior_highs = np.array([d["prior_high"] for d in bounce_data])

        # Sort by value for weighted median
        sorted_idx = np.argsort(bounce_pcts)
        sorted_pcts = bounce_pcts[sorted_idx]
        sorted_weights = weights[sorted_idx]
        cum_weights = np.cumsum(sorted_weights)
        median_idx = np.searchsorted(cum_weights, cum_weights[-1] / 2)
        median_bounce_pct = float(sorted_pcts[min(median_idx, len(sorted_pcts) - 1)])

        # Weighted median of prior_high
        ph_sorted_idx = np.argsort(prior_highs)
        ph_sorted = prior_highs[ph_sorted_idx]
        ph_weights = weights[ph_sorted_idx]
        ph_cum = np.cumsum(ph_weights)
        ph_median_idx = np.searchsorted(ph_cum, ph_cum[-1] / 2)
        prior_high_median = float(ph_sorted[min(ph_median_idx, len(ph_sorted) - 1)])

        median_bounce_target = round(level_price * (1 + median_bounce_pct / 100), 2)

        # Confidence: based on weighted sample size
        confidence = min(1.0, float(np.sum(weights)) / 2.0)

        profiles[level_price] = {
            "median_bounce_pct": round(median_bounce_pct, 2),
            "median_bounce_target": median_bounce_target,
            "prior_high_median": round(prior_high_median, 2),
            "n_held": len(held_events),
            "confidence": round(confidence, 3),
            "events": bounce_data,
        }

    return profiles


# ---------------------------------------------------------------------------
# Multi-fill combination
# ---------------------------------------------------------------------------

def compute_combined_sell_target(fills, bounce_profiles,
                                 min_confidence=0.3, fallback_pct=6.0,
                                 cap_prior_high=True):
    """Combine multiple fills' bounce profiles into a single sell target.

    Args:
        fills: [{price, shares, level_price}, ...]
        bounce_profiles: {level_price: {median_bounce_target, confidence, ...}}
        min_confidence: minimum confidence to use bounce target
        fallback_pct: flat % when no qualifying bounce
        cap_prior_high: cap bounce target at prior_high median

    Returns: float (combined sell price)
    """
    if not fills:
        return 0

    total_shares = sum(f["shares"] for f in fills)
    if total_shares == 0:
        return 0

    weighted_target = 0
    for f in fills:
        level = f.get("level_price", f["price"])
        profile = bounce_profiles.get(level)

        if profile and profile["confidence"] >= min_confidence:
            target = profile["median_bounce_target"]
            if cap_prior_high and profile.get("prior_high_median", 0) > 0:
                target = min(target, profile["prior_high_median"])
            weighted_target += f["shares"] * target
        else:
            # No bounce data — use flat fallback from fill price
            weighted_target += f["shares"] * f["price"] * (1 + fallback_pct / 100)

    return round(weighted_target / total_shares, 2)


# ---------------------------------------------------------------------------
# CLI for standalone testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import yfinance as yf
    from wick_offset_analyzer import analyze_stock_data

    if len(sys.argv) < 2:
        print("Usage: python3 tools/bounce_sell_analyzer.py TICKER")
        sys.exit(1)

    ticker = sys.argv[1].upper()
    print(f"## Bounce Profile Analysis: {ticker}\n")

    # Fetch 13-month daily data
    hist = yf.download(ticker, period="13mo", progress=False)
    if hist.empty:
        print("*No data available.*")
        sys.exit(1)

    # Get support levels from wick analysis
    data, err = analyze_stock_data(ticker)
    if err:
        print(f"*Wick analysis error: {err}*")
        sys.exit(1)

    levels = [r["support_price"] for r in data.get("levels", [])
              if r.get("hold_rate", 0) >= 15]

    if not levels:
        print("*No qualifying support levels.*")
        sys.exit(1)

    profiles = compute_bounce_profiles(hist, levels, decay_half_life=90, bounce_window=3)

    print(f"| Level | Held | Bounce % | Target | Prior High | Confidence |")
    print(f"| :--- | :--- | :--- | :--- | :--- | :--- |")
    for level in sorted(profiles.keys(), reverse=True):
        p = profiles[level]
        if p["n_held"] > 0:
            print(f"| ${level:.2f} | {p['n_held']} | "
                  f"{p['median_bounce_pct']:.1f}% | "
                  f"${p['median_bounce_target']:.2f} | "
                  f"${p['prior_high_median']:.2f} | "
                  f"{p['confidence']:.2f} |")
