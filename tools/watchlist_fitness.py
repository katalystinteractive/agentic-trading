#!/usr/bin/env python3
"""Watchlist fitness review — evaluates whether watchlist tickers still fit the
mean-reversion strategy and whether they're at the right cycle point to engage.

Combines gatherer + pre-analyst: Python does all mechanical work (scoring,
verdicts, cycle data). LLM agents add qualitative judgment in the workflow.

Usage:
    python3 tools/watchlist_fitness.py                        # all watchlist + position tickers
    python3 tools/watchlist_fitness.py AR SOUN                # specific tickers
    python3 tools/watchlist_fitness.py --tier ENGAGED         # filter by tier
    python3 tools/watchlist_fitness.py --summary-only         # compact output for 200+ tickers
"""
import argparse
import sys
import json
import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wick_offset_analyzer import (
    analyze_stock_data, fetch_history, load_tickers_from_portfolio,
)
from technical_scanner import calc_rsi, sma
from bullet_recommender import match_order_to_level, classify_drift, is_paused, parse_bullets_used
from trading_calendar import as_of_date_label
from shared_utils import load_cycle_timing

# ---------------------------------------------------------------------------
# Constants — scoring (must sum to 100)
# ---------------------------------------------------------------------------
SWING_POINTS = 15
CONSISTENCY_POINTS = 15
LEVEL_COUNT_POINTS = 15
HOLD_RATE_POINTS = 10
ORDER_HYGIENE_POINTS = 25
CYCLE_EFFICIENCY_POINTS = 20

assert (SWING_POINTS + CONSISTENCY_POINTS + LEVEL_COUNT_POINTS +
        HOLD_RATE_POINTS + ORDER_HYGIENE_POINTS +
        CYCLE_EFFICIENCY_POINTS) == 100, "Scoring constants must sum to 100"

COMPRESSION_THRESHOLD = 0.65
COMPRESSION_PENALTY = 3


# ---------------------------------------------------------------------------
# Portfolio helpers
# ---------------------------------------------------------------------------
def _load_portfolio():
    with open(PORTFOLIO_PATH, "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Per-ticker fetch + analysis (runs in thread pool)
# ---------------------------------------------------------------------------
def _fetch_and_analyze(ticker):
    """Single fetch per ticker: fetch_history once, pass to analyze_stock_data."""
    try:
        hist = fetch_history(ticker, months=13)
    except Exception as e:
        return ticker, None, None, f"*Error fetching {ticker}: {e}*"
    if hist.empty or len(hist) < 60:
        return ticker, None, None, f"*Skipping {ticker} — insufficient data*"

    data, err = analyze_stock_data(ticker, hist=hist)
    if data is None:
        return ticker, None, None, err
    return ticker, data, hist, None


# ---------------------------------------------------------------------------
# Cycle data computation
# ---------------------------------------------------------------------------
def _compute_cycle_data(hist, current_price):
    """Compute cycle position indicators from hist. Informational only."""
    close = hist["Close"]

    # RSI
    rsi_series = calc_rsi(close)
    rsi = float(rsi_series.iloc[-1]) if len(rsi_series.dropna()) > 0 else None

    # SMA distances
    sma50_series = sma(close, 50)
    sma50 = float(sma50_series.iloc[-1]) if len(sma50_series.dropna()) > 0 else None
    sma50_dist_pct = ((current_price - sma50) / sma50 * 100) if sma50 else None

    sma200_series = sma(close, 200)
    if len(sma200_series.dropna()) >= 1:
        sma200 = float(sma200_series.iloc[-1])
        sma200_dist_pct = ((current_price - sma200) / sma200 * 100)
    else:
        sma200 = None
        sma200_dist_pct = None

    # 3-month range percentile
    recent_63 = hist.tail(63)
    if len(recent_63) >= 20:
        low_3m = float(recent_63["Low"].min())
        high_3m = float(recent_63["High"].max())
        range_3m = high_3m - low_3m
        range_pctile = max(0.0, min(100.0, ((current_price - low_3m) / range_3m * 100))) if range_3m > 0 else 50.0
    else:
        range_pctile = None

    # Up-day ratio (last 20 days)
    recent_20 = hist.tail(20)
    up_days = int((recent_20["Close"] > recent_20["Open"]).sum())
    up_day_total = len(recent_20)

    # Technical state classification (first-match-wins)
    cycle_state = "NEUTRAL"
    if rsi is not None and sma50_dist_pct is not None:
        if rsi > 70 and sma50_dist_pct > 10:
            cycle_state = "OVERBOUGHT"
        elif rsi < 30 and sma50_dist_pct < -10:
            cycle_state = "OVERSOLD"
        elif rsi > 65 and sma50_dist_pct > 5:
            cycle_state = "EXTENDED"
        elif rsi < 40 and sma50_dist_pct < -5:
            cycle_state = "PULLBACK"

    return {
        "rsi": round(rsi, 1) if rsi is not None else None,
        "sma50": round(sma50, 2) if sma50 is not None else None,
        "sma50_dist_pct": round(sma50_dist_pct, 1) if sma50_dist_pct is not None else None,
        "sma200": round(sma200, 2) if sma200 is not None else None,
        "sma200_dist_pct": round(sma200_dist_pct, 1) if sma200_dist_pct is not None else None,
        "range_pctile": round(range_pctile, 0) if range_pctile is not None else None,
        "up_days": up_days,
        "up_day_total": up_day_total,
        "cycle_state": cycle_state,
    }


# ---------------------------------------------------------------------------
# Fitness scoring
# ---------------------------------------------------------------------------
def _score_swing(swing, compression_ratio=1.0):
    if swing is None or swing < 10:
        return 0
    if swing < 15:
        pts = 10
    else:
        pts = SWING_POINTS
    if compression_ratio < COMPRESSION_THRESHOLD:
        pts = max(0, pts - COMPRESSION_PENALTY)
    return pts


def _score_consistency(consistency):
    if consistency is None or consistency < 80:
        return 0
    if consistency < 90:
        return 10
    return CONSISTENCY_POINTS


def _count_active_half_plus(levels):
    """Count Active-zone levels with effective_tier in (Half, Std, Full)."""
    count = 0
    for lvl in levels:
        if lvl.get("zone") == "Active" and lvl.get("effective_tier", lvl.get("tier")) in ("Half", "Std", "Full"):
            count += 1
    return count


def _score_level_count(active_half_plus_count):
    return min(active_half_plus_count * 4, LEVEL_COUNT_POINTS)


def _score_hold_rate(levels):
    """Score based on count of reliable Active levels (decayed HR >= 50%) + floor bonus."""
    reliable = 0
    has_floor = False
    for lvl in levels:
        if lvl.get("zone") != "Active":
            continue
        tier = lvl.get("effective_tier", lvl.get("tier"))
        if tier == "Skip":
            continue
        hr = lvl.get("decayed_hold_rate", lvl.get("hold_rate", 0))
        if hr >= 50:
            reliable += 1
        if hr >= 60:
            has_floor = True

    if reliable >= 3:
        pts = 6
    elif reliable >= 2:
        pts = 4
    elif reliable >= 1:
        pts = 2
    else:
        pts = 0

    if has_floor:
        pts += 4

    return min(pts, HOLD_RATE_POINTS)


def _score_order_hygiene(orphaned_count, all_active_above_price, has_non_paused_orders):
    pts = ORDER_HYGIENE_POINTS
    pts -= orphaned_count * 10
    if has_non_paused_orders and all_active_above_price:
        pts -= 5
    return max(pts, 0)


def _score_cycle_efficiency(ticker):
    """Score cycle efficiency for watchlist fitness (0-20).
    Returns (points, reason_str). Delegates scoring to shared_utils."""
    from shared_utils import score_cycle_efficiency as _shared_score
    ct = load_cycle_timing(ticker)
    if ct is None:
        return 0, "No cycle data"

    pts = _shared_score(ct, max_points=CYCLE_EFFICIENCY_POINTS)

    total = ct.get("total_cycles", 0)
    fill_pct = ct.get("immediate_fill_pct", 0)
    median_deep = ct.get("median_deep")
    reason = f"{total} cycles, {fill_pct:.0f}% fill, median {median_deep}d" if median_deep else f"{total} cycles"
    return pts, reason


# ---------------------------------------------------------------------------
# Order analysis
# ---------------------------------------------------------------------------
def _analyze_orders(ticker, data, portfolio):
    """Analyze pending orders for a ticker. Returns dict with order stats."""
    pending_all = portfolio.get("pending_orders", {})
    orders = pending_all.get(ticker, [])
    buy_orders = [o for o in orders if o.get("type") == "BUY"]

    active_orders = [o for o in buy_orders if not is_paused(o)]
    paused_orders = [o for o in buy_orders if is_paused(o)]

    current_price = data["current_price"]
    levels = data.get("levels", [])

    matched = 0
    drifted = 0
    orphaned = 0
    orphaned_orders = []
    all_above_price = False

    for order in active_orders:
        level, dist = match_order_to_level(order["price"], levels)
        if level is not None:
            status = classify_drift(dist)
            if status == "MATCH":
                matched += 1
            elif status == "DRIFT":
                drifted += 1
        else:
            orphaned += 1
            orphaned_orders.append(order)

    # Check if all non-paused orders are above current price
    if active_orders:
        all_above_price = all(o["price"] > current_price for o in active_orders)
    else:
        all_above_price = False

    all_paused = len(buy_orders) > 0 and len(active_orders) == 0

    return {
        "total_buy_orders": len(buy_orders),
        "active_count": len(active_orders),
        "paused_count": len(paused_orders),
        "matched": matched,
        "drifted": drifted,
        "orphaned": orphaned,
        "orphaned_orders": orphaned_orders,
        "all_above_price": all_above_price,
        "all_paused": all_paused,
        "has_non_paused_orders": len(active_orders) > 0,
    }


# ---------------------------------------------------------------------------
# Engagement verdict
# ---------------------------------------------------------------------------
def _compute_verdict(ticker, data, portfolio, order_info, swing, consistency, cycle_pts=None, recent_swing=None):
    """Compute base verdict + position-aware modifier. Returns (verdict, verdict_note)."""
    positions = portfolio.get("positions", {})
    has_position = ticker in positions and positions[ticker].get("shares", 0) > 0
    pending_all = portfolio.get("pending_orders", {})

    # Step A: Pre-strategy / Recovery detection (active positions only)
    if ticker in positions:
        pos = positions[ticker]
        parsed = parse_bullets_used(pos.get("bullets_used", 0), pos.get("note", ""))
        if parsed["pre_strategy"] and pos.get("shares", 0) > 0:
            return "RECOVERY", "Pre-strategy position — use exit-review-workflow for assessment."

    # Step B/E: Strategy fitness verdicts (first-match-wins)
    all_active_skip = order_info.get("all_active_skip", False)

    # REMOVE — fails strategy selection criteria
    if (swing is not None and swing < 10) or (consistency is not None and consistency < 80):
        note = "Fails strategy selection criteria"
        if swing is not None and swing < 10:
            note += f" (swing {swing:.1f}% < 10%)"
        if consistency is not None and consistency < 80:
            note += f" (consistency {consistency:.1f}% < 80%)"
        # Check for pending orders
        buy_count = sum(
            1 for o in pending_all.get(ticker, []) if o.get("type") == "BUY"
        )
        if buy_count > 0:
            note += f". {buy_count} pending BUY order(s) should be cancelled"
        base = "REMOVE"
        if has_position:
            return "EXIT-REVIEW", note + ". Active position — defer to exit-review-workflow."
        return base, note

    # REVIEW — approaching boundary
    if (swing is not None and swing < 12) or (consistency is not None and consistency < 85):
        note = "Approaching strategy boundary"
        if swing is not None and swing < 12:
            note += f" (swing {swing:.1f}% near 10% floor)"
        if consistency is not None and consistency < 85:
            note += f" (consistency {consistency:.1f}% near 80% floor)"
        base = "REVIEW"
        if has_position:
            return "HOLD-WAIT", note + ". Keep position, don't add bullets until resolved."
        return base, note

    # COMPRESSION — recent swing decaying significantly
    if swing and recent_swing and swing > 0:
        comp_ratio = recent_swing / swing
        if comp_ratio < COMPRESSION_THRESHOLD:
            note = (f"Swing compressing: recent {recent_swing:.1f}% vs "
                    f"median {swing:.1f}% (ratio {comp_ratio:.2f})")
            if has_position:
                return "HOLD-WAIT", note + ". Keep position, monitor for swing recovery."
            return "HOLD-WAIT", note

    # RESTRUCTURE — strategy fits BUT orders misaligned
    restructure_reasons = []
    if order_info["orphaned"] > 0:
        restructure_reasons.append(f"{order_info['orphaned']} orphaned order(s)")
    if all_active_skip:
        restructure_reasons.append("all Active-zone levels are Skip tier")
    if order_info["has_non_paused_orders"] and order_info["all_above_price"]:
        restructure_reasons.append("all non-paused orders above current price")

    if restructure_reasons:
        note = "Strategy fits, orders need adjustment: " + "; ".join(restructure_reasons)
        base = "RESTRUCTURE"
        if has_position:
            return "HOLD-WAIT", note + ". Keep position, don't add bullets until orders fixed."
        return base, note

    # CYCLE-GATE — require minimum cycle validation for ENGAGE
    if cycle_pts is None:
        cycle_pts = _score_cycle_efficiency(ticker)[0]
    has_cycle_data = cycle_pts >= 8
    on_existing_watchlist = ticker in portfolio.get("watchlist", [])

    if not has_cycle_data:
        if on_existing_watchlist or has_position:
            # Grace period: existing watchlist tickers keep ENGAGE with warning
            note = "Strategy fits, ready for engagement. WARNING: No cycle timing data — run cycle_timing_analyzer.py to validate."
            base = "ENGAGE"
        else:
            # New tickers without cycle data cannot reach ENGAGE
            note = "Strategy fits, but no cycle timing validation (cycle_pts < 8). Run cycle_timing_analyzer.py first."
            base = "HOLD-WAIT"
        if has_position:
            return ("ADD" if base == "ENGAGE" else "HOLD-WAIT"), note
        return base, note

    # ENGAGE — catch-all for tickers that fit and aren't RESTRUCTURE
    note = "Strategy fits, ready for engagement"
    base = "ENGAGE"
    if has_position:
        return "ADD", note + ". Active position — ready to add bullets."
    return base, note


# ---------------------------------------------------------------------------
# Re-entry signals (RESTRUCTURE / HOLD-WAIT only)
# ---------------------------------------------------------------------------
def _compute_reentry_signals(data, hist):
    """Compute re-entry signals for RESTRUCTURE / HOLD-WAIT tickers."""
    levels = data.get("levels", [])
    current_price = data["current_price"]

    # First reliable Active Half+ level
    first_level = None
    for lvl in levels:
        if (lvl.get("zone") == "Active"
                and lvl.get("effective_tier", lvl.get("tier")) in ("Half", "Std", "Full")
                and lvl.get("recommended_buy") is not None
                and lvl["recommended_buy"] < current_price):
            first_level = lvl
            break

    # Pullback estimate: 20-day high * (1 - monthly_swing/100)
    swing = data.get("monthly_swing")
    high_20d = float(hist["High"].iloc[-20:].max()) if len(hist) >= 20 else None
    pullback_est = None
    if high_20d is not None and swing is not None and swing > 0:
        pullback_est = round(high_20d * (1 - swing / 100), 2)

    return {
        "first_reliable_level": round(first_level["recommended_buy"], 2) if first_level else None,
        "first_reliable_support": round(first_level["support_price"], 2) if first_level else None,
        "pullback_estimate": pullback_est,
        "high_20d": round(high_20d, 2) if high_20d is not None else None,
    }


# ---------------------------------------------------------------------------
# Main per-ticker pipeline
# ---------------------------------------------------------------------------
def _process_ticker(ticker, data, hist, portfolio):
    """Run full analysis pipeline for one ticker. Returns result dict."""
    current_price = data["current_price"]
    swing = data.get("monthly_swing")
    recent_swing = data.get("recent_swing")
    compression_ratio = (recent_swing / swing) if (swing and recent_swing and swing > 0) else 1.0
    consistency = data.get("swing_consistency")
    levels = data.get("levels", [])

    # Order analysis
    order_info = _analyze_orders(ticker, data, portfolio)

    # Compute all_active_skip for verdict + JSON export
    active_levels = [lvl for lvl in levels if lvl.get("zone") == "Active"]
    all_active_skip = len(active_levels) > 0 and all(
        lvl.get("effective_tier", lvl.get("tier")) == "Skip" for lvl in active_levels
    )
    order_info["all_active_skip"] = all_active_skip

    # Pre-compute cycle efficiency (used by both verdict and scoring)
    cycle_pts, cycle_reason = _score_cycle_efficiency(ticker)

    # Verdict
    verdict, verdict_note = _compute_verdict(ticker, data, portfolio, order_info, swing, consistency, cycle_pts=cycle_pts, recent_swing=recent_swing)

    # Shared order_info dict for JSON output
    def _order_info_json():
        return {
            "total_buy_orders": order_info["total_buy_orders"],
            "matched": order_info["matched"],
            "drifted": order_info["drifted"],
            "orphaned": order_info["orphaned"],
            "paused": order_info["paused_count"],
            "all_paused": order_info["all_paused"],
            "all_active_skip": order_info["all_active_skip"],
            "all_above_price": order_info["all_above_price"],
            "has_non_paused_orders": order_info["has_non_paused_orders"],
        }

    # For RECOVERY — skip scoring
    if verdict == "RECOVERY":
        return {
            "ticker": ticker,
            "current_price": current_price,
            "last_date": data.get("last_date"),
            "verdict": verdict,
            "verdict_note": verdict_note,
            "recovery": True,
            "fitness_score": None,
            "score_components": None,
            "cycle_data": None,
            "order_info": _order_info_json(),
            "reentry_signals": None,
        }

    # Fitness scoring
    active_half_plus = _count_active_half_plus(levels)

    swing_pts = _score_swing(swing, compression_ratio)
    consistency_pts = _score_consistency(consistency)
    level_pts = _score_level_count(active_half_plus)
    hr_pts = _score_hold_rate(levels)
    hygiene_pts = _score_order_hygiene(
        order_info["orphaned"],
        order_info["all_above_price"],
        order_info["has_non_paused_orders"],
    )
    total = swing_pts + consistency_pts + level_pts + hr_pts + hygiene_pts + cycle_pts

    score_components = {
        "swing": {"value": swing, "recent": recent_swing, "ratio": round(compression_ratio, 2), "points": swing_pts, "max": SWING_POINTS},
        "consistency": {"value": consistency, "points": consistency_pts, "max": CONSISTENCY_POINTS},
        "level_quality": {"count": active_half_plus, "points": level_pts, "max": LEVEL_COUNT_POINTS},
        "hold_rate": {"points": hr_pts, "max": HOLD_RATE_POINTS},
        "order_hygiene": {"orphaned": order_info["orphaned"], "points": hygiene_pts, "max": ORDER_HYGIENE_POINTS},
        "cycle_efficiency": {"reason": cycle_reason, "points": cycle_pts, "max": CYCLE_EFFICIENCY_POINTS},
    }

    # Cycle data
    cycle_data = _compute_cycle_data(hist, current_price)

    # Re-entry signals for RESTRUCTURE / HOLD-WAIT
    reentry = None
    if verdict in ("RESTRUCTURE", "HOLD-WAIT"):
        reentry = _compute_reentry_signals(data, hist)

    return {
        "ticker": ticker,
        "current_price": current_price,
        "last_date": data.get("last_date"),
        "monthly_swing": swing,
        "swing_consistency": consistency,
        "verdict": verdict,
        "verdict_note": verdict_note,
        "recovery": False,
        "fitness_score": total,
        "score_components": score_components,
        "cycle_data": cycle_data,
        "order_info": _order_info_json(),
        "reentry_signals": reentry,
    }


# ---------------------------------------------------------------------------
# Markdown output
# ---------------------------------------------------------------------------
def _fmt(val, fmt_str=".1f", prefix="", suffix=""):
    if val is None:
        return "N/A"
    return f"{prefix}{val:{fmt_str}}{suffix}"


def _format_ticker_md(result):
    """Format one ticker result as markdown section."""
    t = result["ticker"]
    v = result["verdict"]
    lines = [f"### {t} — {v}", ""]

    if result["recovery"]:
        lines.append(f"**Verdict**: {v} — {result['verdict_note']}")
        lines.append("")
        return "\n".join(lines)

    # Fitness score table
    sc = result["score_components"]
    lines.append(f"**Fitness Score: {result['fitness_score']}/100**")
    lines.append("")
    lines.append("| Component | Points | Max |")
    lines.append("| :--- | :--- | :--- |")
    lines.append(f"| Swing ({_fmt(sc['swing']['value'])}%) | {sc['swing']['points']} | {sc['swing']['max']} |")
    lines.append(f"| Consistency ({_fmt(sc['consistency']['value'])}%) | {sc['consistency']['points']} | {sc['consistency']['max']} |")
    lines.append(f"| Level Quality ({sc['level_quality']['count']} Active Half+) | {sc['level_quality']['points']} | {sc['level_quality']['max']} |")
    lines.append(f"| Hold Rate Quality | {sc['hold_rate']['points']} | {sc['hold_rate']['max']} |")
    lines.append(f"| Order Hygiene ({sc['order_hygiene']['orphaned']} orphaned) | {sc['order_hygiene']['points']} | {sc['order_hygiene']['max']} |")
    lines.append(f"| Cycle Efficiency ({sc['cycle_efficiency']['reason']}) | {sc['cycle_efficiency']['points']} | {sc['cycle_efficiency']['max']} |")
    lines.append(f"| **Total** | **{result['fitness_score']}** | **100** |")
    lines.append("")

    # Cycle data table
    cd = result["cycle_data"]
    if cd:
        lines.append("**Cycle Data** *(informational — not a verdict driver)*:")
        lines.append("| Indicator | Value |")
        lines.append("| :--- | :--- |")
        lines.append(f"| RSI(14) | {_fmt(cd['rsi'])} |")
        sma50_str = f"{cd['sma50_dist_pct']:+.1f}%" if cd['sma50_dist_pct'] is not None else "N/A"
        lines.append(f"| 50-SMA distance | {sma50_str} |")
        sma200_str = f"{cd['sma200_dist_pct']:+.1f}%" if cd['sma200_dist_pct'] is not None else "N/A"
        lines.append(f"| 200-SMA distance | {sma200_str} |")
        range_str = f"{cd['range_pctile']:.0f}th" if cd['range_pctile'] is not None else "N/A"
        lines.append(f"| 3-month range pctile | {range_str} |")
        lines.append(f"| Up days (last 20) | {cd['up_days']}/{cd['up_day_total']} |")
        lines.append(f"| Cycle State | {cd['cycle_state']} |")
        lines.append("")

    # Order sanity
    oi = result["order_info"]
    paused_note = ""
    if oi["all_paused"] and oi["total_buy_orders"] > 0:
        paused_note = " — All orders paused (earnings/market gate active)"
    lines.append(f"**Order Sanity**: {oi['matched']} matched, {oi['drifted']} drifted, {oi['orphaned']} orphaned, {oi['paused']} paused{paused_note}")
    lines.append("")

    # Verdict
    lines.append(f"**Verdict**: {v} — {result['verdict_note']}")
    lines.append("")

    # Re-entry signals
    re = result.get("reentry_signals")
    if re:
        parts = []
        if re["first_reliable_level"]:
            parts.append(f"First reliable Active Half+ level: ${re['first_reliable_level']:.2f} (support ${re['first_reliable_support']:.2f})")
        if re["pullback_estimate"]:
            parts.append(f"Pullback estimate: ${re['pullback_estimate']:.2f} (from 20d high ${re['high_20d']:.2f})")
        if parts:
            lines.append("**Re-entry signals**: " + " | ".join(parts))
            lines.append("")

    return "\n".join(lines)


def _format_summary_table(results):
    """Format verdict summary table (used in stdout and watchlist-fitness.md)."""
    lines = []
    lines.append("| Ticker | Score | Verdict | Cycle | Note |")
    lines.append("| :--- | :--- | :--- | :--- | :--- |")
    for r in results:
        score = str(r["fitness_score"]) if r["fitness_score"] is not None else "—"
        cycle = r["cycle_data"]["cycle_state"] if r.get("cycle_data") else "—"
        note = r["verdict_note"][:60] + "..." if len(r.get("verdict_note", "")) > 60 else r.get("verdict_note", "")
        lines.append(f"| {r['ticker']} | {score} | {r['verdict']} | {cycle} | {note} |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def _filter_by_tier(tickers, tier, portfolio):
    """Filter tickers by watchlist manager tier."""
    from watchlist_manager import classify_tier
    return [t for t in tickers if classify_tier(t, portfolio) == tier]


def _format_summary_compact(results):
    """Compact summary for --summary-only mode (200+ ticker friendly)."""
    # Group by verdict
    by_verdict = {}
    for r in results:
        v = r["verdict"]
        by_verdict.setdefault(v, []).append(r)

    lines = []
    lines.append("## Verdict Distribution")
    lines.append("")
    lines.append("| Verdict | Count | Tickers |")
    lines.append("| :--- | :--- | :--- |")
    for verdict in ["ENGAGE", "ADD", "HOLD-WAIT", "RESTRUCTURE", "REVIEW",
                    "REMOVE", "EXIT-REVIEW", "RECOVERY"]:
        group = by_verdict.get(verdict, [])
        if group:
            tickers_str = ", ".join(r["ticker"] for r in group[:15])
            if len(group) > 15:
                tickers_str += f" (+{len(group) - 15} more)"
            lines.append(f"| {verdict} | {len(group)} | {tickers_str} |")
    lines.append("")

    # Score distribution
    scored = [r for r in results if r["fitness_score"] is not None]
    if scored:
        scores = [r["fitness_score"] for r in scored]
        lines.append("## Score Distribution")
        lines.append(f"- Range: {min(scores)}-{max(scores)}")
        lines.append(f"- Median: {sorted(scores)[len(scores)//2]}")
        above_70 = [r for r in scored if r["fitness_score"] >= 70]
        lines.append(f"- Score >= 70: {len(above_70)} tickers")
        below_40 = [r for r in scored if r["fitness_score"] < 40]
        lines.append(f"- Score < 40: {len(below_40)} tickers")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Watchlist Fitness Review")
    parser.add_argument("tickers", nargs="*", help="Specific tickers to analyze")
    parser.add_argument("--tier", choices=["ACTIVE", "ENGAGED", "SCOUTING"],
                        help="Filter by watchlist manager tier")
    parser.add_argument("--summary-only", action="store_true",
                        help="Compact output (verdict distribution + scores only)")
    args = parser.parse_args()

    portfolio = _load_portfolio()

    if args.tickers:
        tickers = [t.upper() for t in args.tickers]
    else:
        tickers = load_tickers_from_portfolio()

    # Tier filter
    if args.tier:
        tickers = _filter_by_tier(tickers, args.tier, portfolio)
        print(f"Filtered to {len(tickers)} {args.tier} tickers")

    as_of = as_of_date_label()

    # Parallel fetch + analyze
    results = []
    errors = []
    workers = min(8, max(4, len(tickers) // 10))  # scale workers with ticker count
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_and_analyze, t): t for t in tickers}
        for future in as_completed(futures):
            ticker, data, hist, err = future.result()
            if err:
                errors.append((ticker, err))
                continue
            result = _process_ticker(ticker, data, hist, portfolio)
            results.append(result)

    # Sort by ticker for deterministic output
    results.sort(key=lambda r: r["ticker"])

    # Build markdown report
    if args.summary_only:
        md_lines = [
            f"# Watchlist Fitness Review (Summary)",
            f"",
            f"*Data as of: {as_of} | {len(results)} tickers*",
            f"",
        ]
        md_lines.append(_format_summary_compact(results))
        md_lines.append(_format_summary_table(results))
    else:
        md_lines = [
            f"# Watchlist Fitness Review",
            f"",
            f"*Data as of: {as_of}*",
            f"",
        ]
        for r in results:
            md_lines.append(_format_ticker_md(r))

        # Verdict summary table
        md_lines.append("## Verdict Summary")
        md_lines.append("")
        md_lines.append(_format_summary_table(results))
        md_lines.append("")

    if errors:
        md_lines.append("## Errors")
        md_lines.append("")
        for ticker, err in sorted(errors):
            md_lines.append(f"- **{ticker}**: {err}")
        md_lines.append("")

    md_content = "\n".join(md_lines)

    # Build JSON output (strip non-serializable hist)
    json_data = {
        "as_of": as_of,
        "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ticker_count": len(results),
        "error_count": len(errors),
        "tickers": results,
        "errors": [{"ticker": t, "error": e} for t, e in sorted(errors)],
    }

    # Write files
    md_path = _ROOT / "watchlist-fitness.md"
    json_path = _ROOT / "watchlist-fitness.json"
    with open(md_path, "w") as f:
        f.write(md_content)
    with open(json_path, "w") as f:
        json.dump(json_data, f, indent=2, default=str)

    # Print summary to stdout
    print(f"Watchlist Fitness Review — {as_of}")
    print(f"Tickers analyzed: {len(results)}, errors: {len(errors)}")
    print()
    if args.summary_only:
        print(_format_summary_compact(results))
    print(_format_summary_table(results))
    print()
    print(f"Files written: {md_path.name}, {json_path.name}")


if __name__ == "__main__":
    main()
