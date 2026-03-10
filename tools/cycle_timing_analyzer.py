#!/usr/bin/env python3
"""Cycle timing analyzer: measures resistance-to-support cycle duration.

After selling at resistance, how long until the stock returns to support
(where buy orders fill)? Uses 13-month daily data to compute per-ticker
cooldown recommendations.

Usage:
    python3 tools/cycle_timing_analyzer.py OUST RUN    # specific tickers
    python3 tools/cycle_timing_analyzer.py              # all watchlist + position tickers
"""
import sys
import json
import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wick_offset_analyzer import (
    fetch_history, find_hvn_floors, find_price_action_supports,
    load_tickers_from_portfolio,
)
from sell_target_calculator import (
    find_pa_resistances, find_hvn_ceilings, merge_resistance_levels,
    count_resistance_approaches,
)
from trading_calendar import as_of_date_label

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PROXIMITY_PCT = 8.0          # matches upstream functions
DEEP_THRESHOLD_PCT = 10.0    # support >10% below resistance = "order-zone" level
DECAY_OFFSETS = [1, 3, 5, 10]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _dedupe_levels(levels, tolerance_pct=0.02):
    """Merge support levels within tolerance_pct of each other.

    Sorts by price ascending.  When two levels are within tolerance,
    merges into a single level with averaged price, combined source,
    and max of touches / volume.
    """
    if not levels:
        return levels
    levels = sorted(levels, key=lambda x: x["price"])
    merged = [dict(levels[0])]  # copy to avoid mutating originals
    for lvl in levels[1:]:
        prev = merged[-1]
        if prev["price"] > 0 and (lvl["price"] - prev["price"]) / prev["price"] < tolerance_pct:
            # Merge: average price, combine sources, keep max touches/volume
            prev["price"] = round((prev["price"] + lvl["price"]) / 2, 4)
            src_prev = prev.get("source", "")
            src_new = lvl.get("source", "")
            if src_new and src_new not in src_prev:
                prev["source"] = src_prev + "+" + src_new if src_prev else src_new
            prev["touches"] = max(prev.get("touches", 0), lvl.get("touches", 0))
            prev["volume"] = max(prev.get("volume", 0), lvl.get("volume", 0))
        else:
            merged.append(dict(lvl))
    return merged


def _trading_days_between(hist, start_str, end_str):
    """Count trading days strictly between start (exclusive) and end (inclusive)."""
    start_ts = pd.Timestamp(start_str)
    end_ts = pd.Timestamp(end_str)
    if hist.index.tz is not None:
        start_ts = start_ts.tz_localize(hist.index.tz)
        end_ts = end_ts.tz_localize(hist.index.tz)
    return len(hist[(hist.index > start_ts) & (hist.index <= end_ts)])


def _compute_decay(hist, res_date_str, offsets=DECAY_OFFSETS):
    """Compute Close price change at each offset after resistance date.

    Returns dict {offset_str: pct_change} — missing offsets omitted.
    """
    res_ts = pd.Timestamp(res_date_str)
    if hist.index.tz is not None:
        res_ts = res_ts.tz_localize(hist.index.tz)
    res_idx = hist.index.get_indexer([res_ts], method="nearest")[0]
    # Guard: nearest match too far away
    if abs((hist.index[res_idx] - res_ts).days) > 2:
        return {}
    res_close = hist["Close"].iloc[res_idx]
    decay = {}
    for offset in offsets:
        target_idx = res_idx + offset
        if target_idx < len(hist):
            target_close = hist["Close"].iloc[target_idx]
            decay[str(offset)] = round((target_close - res_close) / res_close * 100, 1)
    return decay


# ---------------------------------------------------------------------------
# Step A: Detect resistance levels
# ---------------------------------------------------------------------------
def _detect_resistance(hist, current_price):
    """Find resistance levels with approach counts and breakout filtering.

    Returns list of dicts with keys: price, source, approaches,
    historical_approaches, rejected, broke, reject_rate, touches/volume.
    """
    zone_low = current_price
    zone_high = float(hist["High"].max())

    pa_levels = find_pa_resistances(hist, zone_low, zone_high)
    hvn_levels = find_hvn_ceilings(hist, zone_low, zone_high)
    resistance_levels = merge_resistance_levels(pa_levels, hvn_levels)

    # Enrich with approach counts
    for lvl in resistance_levels:
        stats = count_resistance_approaches(hist, lvl["price"],
                                             proximity_pct=PROXIMITY_PCT)
        lvl.update(stats)
        # Deflate if current price is near this level (live approach included)
        if current_price >= lvl["price"] * (1 - PROXIMITY_PCT / 100.0):
            lvl["historical_approaches"] = max(0, lvl.get("approaches", 0) - 1)
        else:
            lvl["historical_approaches"] = lvl.get("approaches", 0)

    # Filter: 2+ historical approaches
    resistance_levels = [l for l in resistance_levels
                         if l.get("historical_approaches", 0) >= 2]

    # Post-filter: strip levels below current_price (from 50% buffer in _search_bounds)
    resistance_levels = [l for l in resistance_levels
                         if l["price"] >= current_price]

    # Fallback: if nothing found, widen zone below current_price
    if not resistance_levels:
        zone_low = current_price * 0.90
        pa_levels = find_pa_resistances(hist, zone_low, zone_high)
        hvn_levels = find_hvn_ceilings(hist, zone_low, zone_high)
        resistance_levels = merge_resistance_levels(pa_levels, hvn_levels)
        for lvl in resistance_levels:
            stats = count_resistance_approaches(hist, lvl["price"],
                                                 proximity_pct=PROXIMITY_PCT)
            lvl.update(stats)
            if current_price >= lvl["price"] * (1 - PROXIMITY_PCT / 100.0):
                lvl["historical_approaches"] = max(0, lvl.get("approaches", 0) - 1)
            else:
                lvl["historical_approaches"] = lvl.get("approaches", 0)
        resistance_levels = [l for l in resistance_levels
                             if l.get("historical_approaches", 0) >= 2]

    return resistance_levels


# ---------------------------------------------------------------------------
# Step B: Find dated resistance touch events
# ---------------------------------------------------------------------------
def find_resistance_events(hist, resistance_levels, proximity_pct=PROXIMITY_PCT):
    """Find dated resistance touch events.

    Returns [(date_str, resistance_price), ...] sorted by date then price.
    NO same-day dedup — record ALL resistance levels touched per day.
    """
    assert isinstance(hist.index, pd.DatetimeIndex), "hist must have DatetimeIndex"
    events = []
    pct = proximity_pct / 100.0

    for lvl in resistance_levels:
        price = lvl["price"]
        lower = price * (1 - pct)
        for i in range(len(hist)):
            high = hist["High"].iloc[i]
            close = hist["Close"].iloc[i]
            if high >= lower and close < price:
                date_str = hist.index[i].strftime("%Y-%m-%d")
                events.append((date_str, price))

    # Deduplicate exact (date, price) pairs, sort by date then price
    events = sorted(set(events))
    return events


# ---------------------------------------------------------------------------
# Step C: Detect support levels
# ---------------------------------------------------------------------------
def _detect_supports(hist, resistance_levels, current_price):
    """Find support levels for cycle matching — full historical range."""
    price_cap = float(hist["High"].max())
    hvn_supports = find_hvn_floors(hist)
    pa_supports = find_price_action_supports(hist, price_cap)

    # Combine + deduplicate within 2% (no current_price filter)
    all_supports = _dedupe_levels(hvn_supports + pa_supports, tolerance_pct=0.02)

    # Exclude supports within proximity of ANY resistance level
    pct = PROXIMITY_PCT / 100.0
    all_supports = [
        s for s in all_supports
        if not any(abs(s["price"] - r["price"]) / r["price"] < pct
                   for r in resistance_levels)
    ]

    # Exclude above-current supports unless HVN-confirmed AND meaningfully
    # below lowest resistance (>10% below)
    min_res_price = (min(l["price"] for l in resistance_levels)
                     if resistance_levels else float("inf"))
    all_supports = [
        s for s in all_supports
        if s["price"] <= current_price
        or ("HVN" in s.get("source", "")
            and s["price"] < min_res_price * (1 - DEEP_THRESHOLD_PCT / 100.0))
    ]

    return all_supports


# ---------------------------------------------------------------------------
# Step D: Match cycles — resistance to first support touch
# ---------------------------------------------------------------------------
def find_first_support_after(hist, support_levels, after_date_str,
                              proximity_pct=PROXIMITY_PCT, end_date_str=None):
    """Scan forward from after_date, find first day Low enters proximity of any support.

    Returns (date_str, support_price) or (None, None).
    Iterates supports in DESCENDING price order — highest support = first touched.
    """
    pct = proximity_pct / 100.0
    after_dt = pd.Timestamp(after_date_str)
    if hist.index.tz is not None:
        after_dt = after_dt.tz_localize(hist.index.tz)
    subset = hist[hist.index > after_dt]
    if end_date_str is not None:
        end_dt = pd.Timestamp(end_date_str)
        if hist.index.tz is not None:
            end_dt = end_dt.tz_localize(hist.index.tz)
        subset = subset[subset.index < end_dt]

    sorted_supports = sorted(support_levels, key=lambda l: l["price"], reverse=True)
    for date, row in subset.iterrows():
        low = row["Low"]
        for lvl in sorted_supports:
            price = lvl["price"]
            if low <= price * (1 + pct) and low >= price * (1 - pct):
                return date.strftime("%Y-%m-%d"), price
    return None, None


def find_first_deep_support_after(hist, support_levels, after_date_str,
                                   resistance_price,
                                   deep_threshold_pct=DEEP_THRESHOLD_PCT,
                                   proximity_pct=PROXIMITY_PCT,
                                   end_date_str=None):
    """Like find_first_support_after but only considers support levels
    >deep_threshold_pct below resistance_price (order-zone levels)."""
    deep_levels = [l for l in support_levels
                   if l["price"] < resistance_price * (1 - deep_threshold_pct / 100.0)]
    return find_first_support_after(hist, deep_levels, after_date_str,
                                     proximity_pct, end_date_str=end_date_str)


# ---------------------------------------------------------------------------
# Per-ticker analysis pipeline
# ---------------------------------------------------------------------------
def analyze_ticker(ticker):
    """Run full cycle timing analysis for a single ticker.

    Returns (ticker, result_dict, error_str).
    result_dict is None on error; error_str is None on success.
    """
    try:
        hist = fetch_history(ticker, months=13)
    except Exception as e:
        return ticker, None, f"*Error fetching {ticker}: {e}*"
    if hist is None or hist.empty or len(hist) < 60:
        return ticker, None, f"*Skipping {ticker} — insufficient data*"

    current_price = round(float(hist["Close"].iloc[-1]), 2)
    last_date = hist.index[-1].strftime("%Y-%m-%d")

    # Step A: Resistance levels
    resistance_levels = _detect_resistance(hist, current_price)
    if not resistance_levels:
        return ticker, {
            "ticker": ticker,
            "current_price": current_price,
            "last_date": last_date,
            "resistance_levels": [],
            "support_levels_used": [],
            "current_cycle": None,
            "cycles": [],
            "statistics": {"total_cycles": 0},
            "post_resistance_decay": {},
            "recommendation": {
                "cooldown_days": None,
                "confidence": "NO_DATA",
                "immediate_reentry_viable": False,
            },
        }, None

    # Step B: Resistance events
    resistance_events = find_resistance_events(hist, resistance_levels)

    # Post-event gate: remove levels with 0 actual rejection events
    levels_with_events = {price for _, price in resistance_events}
    resistance_levels = [l for l in resistance_levels
                         if l["price"] in levels_with_events]
    # Re-filter events to only include levels still in resistance_levels
    remaining_prices = {l["price"] for l in resistance_levels}
    resistance_events = [(d, p) for d, p in resistance_events
                         if p in remaining_prices]

    if not resistance_events:
        return ticker, {
            "ticker": ticker,
            "current_price": current_price,
            "last_date": last_date,
            "resistance_levels": resistance_levels,
            "support_levels_used": [],
            "current_cycle": None,
            "cycles": [],
            "statistics": {"total_cycles": 0},
            "post_resistance_decay": {},
            "recommendation": {
                "cooldown_days": None,
                "confidence": "NO_DATA",
                "immediate_reentry_viable": False,
            },
        }, None

    # Step C: Support levels
    all_supports = _detect_supports(hist, resistance_levels, current_price)

    # Step D: Match cycles
    cycles = []
    for i, (res_date, res_price) in enumerate(resistance_events):
        # Bound search: next resistance event on a DIFFERENT date
        end_bound = None
        for j in range(i + 1, len(resistance_events)):
            if resistance_events[j][0] != res_date:
                end_bound = resistance_events[j][0]
                break

        touch_date, touch_price = find_first_support_after(
            hist, all_supports, res_date, end_date_str=end_bound)
        deep_date, deep_price = find_first_deep_support_after(
            hist, all_supports, res_date, res_price, end_date_str=end_bound)

        days_first = (_trading_days_between(hist, res_date, touch_date)
                      if touch_date else None)
        days_deep = (_trading_days_between(hist, res_date, deep_date)
                     if deep_date else None)

        cycles.append({
            "resistance_date": res_date,
            "resistance_price": round(res_price, 2),
            "first_touch_date": touch_date,
            "first_touch_price": round(touch_price, 2) if touch_price else None,
            "days_first": days_first,
            "deep_touch_date": deep_date,
            "deep_touch_price": round(deep_price, 2) if deep_price else None,
            "days_deep": days_deep,
        })

    # Step E: Separate completed vs incomplete cycles
    completed = [c for c in cycles if c["first_touch_date"] is not None]
    incomplete = [c for c in cycles if c["first_touch_date"] is None]

    current_cycle = None
    if incomplete:
        best = max(incomplete, key=lambda c: c["resistance_date"])
        current_cycle = {
            "resistance_date": best["resistance_date"],
            "resistance_price": best["resistance_price"],
            "days_elapsed": _trading_days_between(hist, best["resistance_date"],
                                                   last_date),
            "status": "IN PROGRESS",
        }

    cycles = completed  # only completed cycles feed into statistics

    # Step F: Post-resistance decay
    # Dedup by resistance date to avoid double-weighting same-day multi-level events
    seen_decay_dates = set()
    per_cycle_decay = []
    for c in cycles:
        rd = c["resistance_date"]
        if rd in seen_decay_dates:
            # Reuse the decay from the first cycle on this date
            for prev in per_cycle_decay:
                if prev["date"] == rd:
                    c["post_resistance_decay"] = prev["decay"]
                    break
        else:
            decay = _compute_decay(hist, rd)
            c["post_resistance_decay"] = decay
            per_cycle_decay.append({"date": rd, "decay": decay})
            seen_decay_dates.add(rd)

    # Aggregate decay medians per offset
    agg_decay = {}
    for offset in DECAY_OFFSETS:
        key = str(offset)
        vals = [d["decay"].get(key) for d in per_cycle_decay
                if d["decay"].get(key) is not None]
        if vals:
            agg_decay[key] = round(float(np.median(vals)), 1)

    # Step G: Statistics + recommendation
    first_days = [c["days_first"] for c in cycles if c["days_first"] is not None]
    deep_days = [c["days_deep"] for c in cycles if c["days_deep"] is not None]

    median_first = int(np.median(first_days)) if first_days else None
    median_deep = int(np.median(deep_days)) if deep_days else None
    min_first = int(min(first_days)) if first_days else None
    max_first = int(max(first_days)) if first_days else None
    min_deep = int(min(deep_days)) if deep_days else None
    max_deep = int(max(deep_days)) if deep_days else None

    base_median = median_deep if median_deep is not None else median_first
    cooldown_days = max(3, int(base_median * 0.6)) if base_median is not None else None

    n_cycles = len(cycles)
    confidence = ("NO_DATA" if n_cycles == 0
                  else "LOW" if n_cycles <= 2
                  else "NORMAL")

    immediate_fill_pct = (
        round(sum(1 for d in first_days if d <= 2) / len(first_days) * 100, 1)
        if first_days else 0
    )
    immediate_reentry_viable = immediate_fill_pct >= 40

    result = {
        "ticker": ticker,
        "current_price": current_price,
        "last_date": last_date,
        "resistance_levels": [
            {
                "price": round(l["price"], 2),
                "approaches": l.get("approaches", 0),
                "historical_approaches": l.get("historical_approaches", 0),
                "rejected": l.get("rejected", 0),
                "broke": l.get("broke", 0),
                "reject_rate": round(l.get("reject_rate", 0), 1),
                "source": l.get("source", ""),
            }
            for l in resistance_levels
        ],
        "support_levels_used": [
            {"price": round(s["price"], 2), "source": s.get("source", "")}
            for s in all_supports
        ],
        "current_cycle": current_cycle,
        "cycles": cycles,
        "statistics": {
            "total_cycles": n_cycles,
            "median_first": median_first,
            "min_first": min_first,
            "max_first": max_first,
            "median_deep": median_deep,
            "min_deep": min_deep,
            "max_deep": max_deep,
            "immediate_fill_pct": immediate_fill_pct,
        },
        "post_resistance_decay": agg_decay,
        "recommendation": {
            "cooldown_days": cooldown_days,
            "confidence": confidence,
            "immediate_reentry_viable": immediate_reentry_viable,
        },
    }

    return ticker, result, None


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------
def _fmt_dollar(val):
    if val is None:
        return "N/A"
    return f"${val:.2f}"


def _fmt_days(val):
    if val is None:
        return "—"
    return f"{val}d"


def _format_ticker_report(r):
    """Format a single ticker's result dict as markdown."""
    lines = []
    ticker = r["ticker"]
    lines.append(f"## Cycle Timing Analysis: {ticker}")
    lines.append(f"*Data as of: {r['last_date']}*")
    lines.append(f"**Current Price: {_fmt_dollar(r['current_price'])}**")
    lines.append("")

    # Current Cycle
    cc = r.get("current_cycle")
    if cc:
        lines.append("### Current Cycle")
        lines.append("| Field | Value |")
        lines.append("| :--- | :--- |")
        lines.append(f"| Resistance touch | {cc['resistance_date']} @ "
                      f"{_fmt_dollar(cc['resistance_price'])} |")
        lines.append(f"| Days elapsed | {cc['days_elapsed']} trading days |")
        lines.append(f"| Status | {cc['status']} |")
        stats = r["statistics"]
        lines.append(f"| Historical median (first touch) | "
                      f"{_fmt_days(stats.get('median_first'))} |")
        lines.append(f"| Historical median (deep/order-zone) | "
                      f"{_fmt_days(stats.get('median_deep'))} |")
        lines.append("")

    # Cycle Statistics
    stats = r["statistics"]
    n_first = sum(1 for c in r["cycles"] if c["days_first"] is not None)
    n_deep = sum(1 for c in r["cycles"] if c["days_deep"] is not None)
    lines.append("### Cycle Statistics")
    lines.append("| Metric | First Touch | Deep/Order-Zone Touch |")
    lines.append("| :--- | :--- | :--- |")
    lines.append(f"| Observed Cycles | {n_first} | {n_deep} |")
    lines.append(f"| Median Duration | {_fmt_days(stats.get('median_first'))} | "
                  f"{_fmt_days(stats.get('median_deep'))} |")
    range_first = (f"{stats['min_first']} — {stats['max_first']}d"
                   if stats.get("min_first") is not None else "—")
    range_deep = (f"{stats['min_deep']} — {stats['max_deep']}d"
                  if stats.get("min_deep") is not None else "—")
    lines.append(f"| Range | {range_first} | {range_deep} |")
    lines.append("")

    rec = r["recommendation"]
    lines.append("| Metric | Value |")
    lines.append("| :--- | :--- |")
    lines.append(f"| Same/Next Day Fill Rate | "
                  f"{stats.get('immediate_fill_pct', 0)}% |")
    lines.append(f"| Confidence | {rec['confidence']} |")
    cd = rec.get("cooldown_days")
    cd_str = f"**{cd} trading days**" if cd is not None else "**N/A (insufficient data)**"
    lines.append(f"| **Cooldown Recommendation** | {cd_str} |")
    lines.append("")

    # Post-Resistance Price Decay
    decay = r.get("post_resistance_decay", {})
    lines.append("### Post-Resistance Price Decay (Median)")
    lines.append("| +1d | +3d | +5d | +10d |")
    lines.append("| :--- | :--- | :--- | :--- |")
    vals = []
    for k in ["1", "3", "5", "10"]:
        v = decay.get(k)
        vals.append(f"{v:+.1f}%" if v is not None else "—")
    lines.append(f"| {' | '.join(vals)} |")
    lines.append("")

    # Cycle Event Log
    lines.append("### Cycle Event Log")
    lines.append("| # | R Date | R Level | 1st Touch | Days | "
                  "Deep Touch | Days |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for i, c in enumerate(r["cycles"], 1):
        ft = c.get("first_touch_date", "—") or "—"
        ft_p = _fmt_dollar(c.get("first_touch_price"))
        ft_str = f"{ft} @ {ft_p}" if ft != "—" else "—"
        dt = c.get("deep_touch_date", "—") or "—"
        dt_p = _fmt_dollar(c.get("deep_touch_price"))
        dt_str = f"{dt} @ {dt_p}" if dt != "—" else "—"
        lines.append(
            f"| {i} | {c['resistance_date']} | "
            f"{_fmt_dollar(c['resistance_price'])} | "
            f"{ft_str} | {_fmt_days(c.get('days_first'))} | "
            f"{dt_str} | {_fmt_days(c.get('days_deep'))} |"
        )
    lines.append("")

    # Resistance Levels Detected
    lines.append("### Resistance Levels Detected")
    lines.append("| Level | Source | Approaches | Broke | Reject Rate |")
    lines.append("| :--- | :--- | :--- | :--- | :--- |")
    for l in r.get("resistance_levels", []):
        lines.append(
            f"| {_fmt_dollar(l['price'])} | {l['source']} | "
            f"{l.get('historical_approaches', l.get('approaches', 0))} | "
            f"{l.get('broke', 0)} | {l.get('reject_rate', 0):.0f}% |"
        )
    lines.append("")

    # Re-Entry Recommendation
    lines.append("### Re-Entry Recommendation")
    if rec["immediate_reentry_viable"]:
        lines.append(f"Immediate re-entry viable — "
                      f"{stats.get('immediate_fill_pct', 0)}% of cycles "
                      f"completed in ≤2 trading days.")
    elif cd is not None:
        lines.append(f"Wait **{cd} trading days** before placing re-entry orders "
                      f"(confidence: {rec['confidence']}).")
    else:
        lines.append("Insufficient data to recommend a cooldown period.")
    lines.append("")

    return "\n".join(lines)


def _format_summary_table(results):
    """Format cross-ticker summary table sorted alphabetically."""
    lines = []
    lines.append("## Cross-Ticker Summary")
    lines.append("")
    lines.append("| Ticker | Cycles | Med 1st | Med Deep | Cooldown | "
                  "Imm Fill% | Confidence | Status |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for ticker in sorted(results.keys()):
        r = results[ticker]
        stats = r["statistics"]
        rec = r["recommendation"]
        cc = r.get("current_cycle")
        status = "—"
        if cc:
            status = f"IN PROGRESS ({cc['days_elapsed']}d)"
        lines.append(
            f"| {ticker} | {stats['total_cycles']} | "
            f"{_fmt_days(stats.get('median_first'))} | "
            f"{_fmt_days(stats.get('median_deep'))} | "
            f"{_fmt_days(rec.get('cooldown_days'))} | "
            f"{stats.get('immediate_fill_pct', 0)}% | "
            f"{rec['confidence']} | {status} |"
        )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    tickers = [t.upper() for t in sys.argv[1:] if t.upper().isalpha() and len(t) <= 5]
    if not tickers:
        tickers = load_tickers_from_portfolio()

    if not tickers:
        print("*No tickers to analyze.*")
        return

    date_label = as_of_date_label()
    results = {}
    errors = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(analyze_ticker, t): t for t in tickers}
        for future in as_completed(futures):
            ticker, result, err = future.result()
            if err:
                errors.append(err)
            if result:
                results[ticker] = result

    # Output ordering: alphabetical
    output_lines = []
    output_lines.append(f"# Cycle Timing Analysis — {date_label}")
    output_lines.append("")

    for err in errors:
        output_lines.append(err)
        output_lines.append("")

    for ticker in sorted(results.keys()):
        r = results[ticker]
        output_lines.append(_format_ticker_report(r))

        # Write per-ticker files
        ticker_dir = _ROOT / "tickers" / ticker
        ticker_dir.mkdir(parents=True, exist_ok=True)
        md_path = ticker_dir / "cycle_timing.md"
        json_path = ticker_dir / "cycle_timing.json"
        md_path.write_text(_format_ticker_report(r), encoding="utf-8")
        json_path.write_text(json.dumps(r, indent=2, default=str),
                             encoding="utf-8")

    output_lines.append(_format_summary_table(results))

    print("\n".join(output_lines))


if __name__ == "__main__":
    main()
