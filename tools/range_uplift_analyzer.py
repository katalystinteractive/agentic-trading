"""Range Uplift Analyzer — redeploy dormant orders at higher support levels.

When a stock moves UP and establishes a higher trading range, existing pending
BUY orders become dormant — they sit well below current price and will never
fill.  This tool detects dormant orders, finds support levels within the new
range, and recommends cancelling dormant orders and redeploying at higher levels.

Applies to:
  1. Watchlist tickers with no position but dormant pending BUY orders (e.g. AR)
  2. Tickers with positions whose pending orders are now far below current price

Mirror of Range Reset: Reset deploys reserve capital at LOWER levels for
underwater positions.  Uplift redeploys EXISTING order capital at HIGHER levels
for tickers where price has moved up.

Usage:
    python3 tools/range_uplift_analyzer.py              # all qualifying tickers
    python3 tools/range_uplift_analyzer.py AR APLD       # specific tickers
"""
import sys
import json
import copy
import datetime
import re
import numpy as np
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"
OUTPUT_MD = _ROOT / "range-uplift-analysis.md"
OUTPUT_JSON = _ROOT / "range-uplift-analysis.json"

# --- Imports from sibling tools ---
sys.path.insert(0, str(Path(__file__).resolve().parent))
from wick_offset_analyzer import fetch_history, analyze_stock_data, compute_pool_sizing
from shared_utils import load_cycle_timing, score_cycle_efficiency
from sell_target_calculator import (
    find_pa_resistances, find_hvn_ceilings, count_resistance_approaches,
    recommend_sell, merge_resistance_levels,
)
from range_reset_analyzer import (
    _compute_range_metrics, _classify_stability, _is_match, _classify_level_range,
)

# --- Constants ---
SWING_MIN = 20.0                 # % — minimum 20d range swing (gate G5)
EXIT_CONSERVATIVE = 1.045        # 4.5% conservative exit
EXIT_STANDARD = 1.06             # 6% standard exit
EXIT_AGGRESSIVE = 1.075          # 7.5% aggressive exit
MIN_HOLD_RATE = 15.0             # % — below this = dead zone, no order

# Uplift-specific
DORMANCY_DIST_PCT = 0.15         # 15% below current price = dormant
MIN_DORMANT_ORDERS = 1           # need at least 1 dormant order to qualify
MIN_FREED_CAPITAL = 20.0         # $ — skip if freed capital too small

# Scoring weights (sum to 100)
STABILITY_PTS = 25
STABILITY_PTS_SETTLING = 15
SWING_PTS = 20
SWING_PTS_PARTIAL = 15
EXIT_REACH_PTS = 20
CYCLE_EFF_PTS = 15
RISK_PTS = 20
RISK_PTS_MODERATE = 10

assert STABILITY_PTS + SWING_PTS + EXIT_REACH_PTS + CYCLE_EFF_PTS + RISK_PTS == 100, \
    "Scoring weights must sum to 100"

# Reserve order pattern — exclude from dormancy scan
_RESERVE_RE = re.compile(r"reserve|R\d", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Portfolio loading & candidate identification
# ---------------------------------------------------------------------------

def _load_portfolio():
    with open(PORTFOLIO_PATH, "r") as f:
        return json.load(f)


def _identify_uplift_candidates(portfolio, requested_tickers=None):
    """Find tickers with unfilled BUY pending orders.

    Pre-fetch gates (G1, G3 only).  G2/G4/G5/G6 require price data — checked
    in _process_ticker after fetch_history.

    Returns (candidates_list, skipped_dict).
    """
    candidates = []
    skipped = {}
    pending_orders = portfolio.get("pending_orders", {})
    positions = portfolio.get("positions", {})

    for ticker, orders in pending_orders.items():
        if requested_tickers and ticker not in requested_tickers:
            continue

        # G1: has unfilled BUY orders (exclude filled, exclude non-BUY)
        unfilled_buys = [
            o for o in orders
            if o.get("type") == "BUY" and not o.get("filled")
        ]
        if not unfilled_buys:
            if requested_tickers:
                skipped[ticker] = "no unfilled BUY orders"
            continue

        # G3: not RECOVERY
        pos = positions.get(ticker, {})
        note = pos.get("note", "")
        if "recovery" in note.lower():
            if requested_tickers:
                skipped[ticker] = "recovery mode — defer to exit-review"
            continue

        candidates.append({
            "ticker": ticker,
            "shares": pos.get("shares", 0),
            "avg_cost": pos.get("avg_cost", 0),
            "unfilled_buys": unfilled_buys,
            "all_orders": orders,
        })

    # Check for requested tickers not found in pending_orders at all
    if requested_tickers:
        for t in requested_tickers:
            if t not in pending_orders and t not in skipped:
                skipped[t] = "no pending orders"

    return candidates, skipped


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def _fetch_ticker_data(ticker):
    """Fetch 13-month history once. Returns (ticker, hist) or (ticker, None)."""
    try:
        hist = fetch_history(ticker, months=13)
        return ticker, hist
    except Exception as e:
        print(f"  *Error fetching {ticker}: {e}*")
        return ticker, None


# ---------------------------------------------------------------------------
# Dormancy detection
# ---------------------------------------------------------------------------

def _detect_dormant_orders(unfilled_buys, current_price, low_20d):
    """Classify unfilled BUY orders as dormant or active.

    Pre-filter: only unfilled BUY orders passed in (filled excluded upstream).
    Exclude reserve orders (intentional deep-support capital).

    Dormant if BOTH:
      1. order_price < current_price * (1 - DORMANCY_DIST_PCT)  [>15% below]
      2. low_20d > order_price * 1.10  [20d low hasn't been within 10% of order]

    Returns (dormant_list, active_list, freed_capital).
    """
    dormant = []
    active = []
    freed = 0.0
    dormancy_threshold = current_price * (1 - DORMANCY_DIST_PCT)

    for o in unfilled_buys:
        # Exclude reserve orders from dormancy scan
        note = o.get("note", "")
        if _RESERVE_RE.search(note):
            active.append(o)
            continue

        price = o.get("price", 0)
        shares = o.get("shares", 0)

        is_distant = price < dormancy_threshold
        is_stale = low_20d > price * 1.10

        if is_distant and is_stale:
            cost = round(price * shares, 2)
            dist_pct = round((price - current_price) / current_price * 100, 1)
            dormant.append({
                "price": price,
                "shares": shares,
                "cost": cost,
                "distance_pct": dist_pct,
                "note": note,
            })
            freed += cost
        else:
            active.append(o)

    return dormant, active, round(freed, 2)


# ---------------------------------------------------------------------------
# Redeployment scenarios
# ---------------------------------------------------------------------------

def _compute_redeployment_scenarios(candidate, hist, metrics, active_orders,
                                    freed_capital):
    """Compute new bullet scenarios from wick levels within the 20d range.

    Uses freed_capital (from dormant orders) as the budget.
    Returns (scenarios_list, context_dict) or (None, context_dict).
    """
    ticker = candidate["ticker"]

    data, err = analyze_stock_data(ticker, hist)
    if err is not None:
        return None, {"error": err, "total_levels": 0}

    all_levels = data.get("levels", [])
    low_20d = metrics["low_20d"]
    high_20d = metrics["high_20d"]

    # Prices of active (non-dormant) orders — exclude from new scenarios
    active_buy_prices = [
        o["price"] for o in active_orders
        if o.get("type") == "BUY"
    ]

    # Classify and filter levels
    in_range = []
    below_range_count = 0
    above_range_count = 0

    for raw_lvl in all_levels:
        buy_at = raw_lvl.get("recommended_buy")
        if buy_at is None:
            continue

        # Skip if an active order already covers this level
        is_covered = any(_is_match(buy_at, pp) for pp in active_buy_prices)
        if is_covered:
            continue

        range_class = _classify_level_range(buy_at, low_20d, high_20d)
        if range_class == "below-range":
            below_range_count += 1
            continue
        if range_class == "above-range":
            above_range_count += 1
            continue
        # near-range: include for uplift (they're close to the current range)
        # in-range: include

        # Skip dead-zone levels
        if raw_lvl.get("hold_rate", 0) < MIN_HOLD_RATE:
            continue

        lvl = copy.deepcopy(raw_lvl)
        lvl["range_class"] = range_class
        in_range.append(lvl)

    total_levels = len(all_levels)
    context = {
        "total_levels": total_levels,
        "in_range_count": len(in_range),
        "below_range_count": below_range_count,
        "above_range_count": above_range_count,
    }

    if not in_range:
        context["message"] = ("No usable support levels in current range — "
                              "wait for range expansion or new level formation")
        return None, context

    # Preserve original level metadata before compute_pool_sizing strips it
    orig_meta = [
        {
            "tier": lvl.get("effective_tier", lvl.get("tier", "?")),
            "source": lvl.get("source", ""),
            "support_price": lvl.get("support_price", lvl.get("recommended_buy")),
            "range_class": lvl.get("range_class", "?"),
        }
        for lvl in in_range
    ]

    # Size bullets via compute_pool_sizing using freed capital as budget
    sized = compute_pool_sizing(in_range, freed_capital, pool_name="uplift")

    # Build scenario rows with blended avg math
    scenarios = []
    old_shares = candidate["shares"]
    old_avg = candidate["avg_cost"]

    for i, lvl in enumerate(sized):
        meta = orig_meta[i] if i < len(orig_meta) else {}
        lvl.update(meta)
        buy_at = lvl["recommended_buy"]
        new_shares = lvl.get("shares", 0)
        cost = lvl.get("cost", 0)
        if new_shares == 0:
            continue

        total_shares = old_shares + new_shares
        if old_shares > 0:
            blended_avg = round(
                (old_shares * old_avg + new_shares * buy_at) / total_shares, 2
            )
        else:
            # Watchlist ticker (no position) — first scenario sets the avg
            blended_avg = round(buy_at, 2)

        exit_6pct = round(blended_avg * EXIT_STANDARD, 2)
        reachable = exit_6pct <= metrics["high_20d_p75"]

        scenarios.append({
            "support_price": lvl.get("support_price", buy_at),
            "buy_at": buy_at,
            "hold_rate": lvl.get("hold_rate", 0),
            "tier": lvl.get("effective_tier", lvl.get("tier", "?")),
            "shares": new_shares,
            "cost": cost,
            "new_avg": blended_avg,
            "exit_6pct": exit_6pct,
            "reachable": reachable,
            "range_class": lvl.get("range_class", "?"),
            "source": lvl.get("source", ""),
        })

        # Accumulate for next row
        old_shares = total_shares
        old_avg = blended_avg

    context["blended_avg_final"] = old_avg if scenarios else candidate["avg_cost"]
    context["total_shares_final"] = old_shares if scenarios else candidate["shares"]

    if not scenarios:
        context["message"] = "Budget too small for any allocation at current levels"
        return None, context

    return scenarios, context


# ---------------------------------------------------------------------------
# Exit reachability via recommend_sell()
# ---------------------------------------------------------------------------

def _compute_exit_reachability(hist, blended_avg, total_shares, metrics):
    """Use recommend_sell() to compute scored sell targets.

    Returns (sell_recs, reachable_bool, details_dict).
    """
    math_prices = {
        "conservative": round(blended_avg * EXIT_CONSERVATIVE, 2),
        "standard": round(blended_avg * EXIT_STANDARD, 2),
        "aggressive": round(blended_avg * EXIT_AGGRESSIVE, 2),
    }
    exit_zone_lo = math_prices["conservative"]
    exit_zone_hi = math_prices["aggressive"]

    pa = find_pa_resistances(hist, exit_zone_lo, exit_zone_hi)
    hvn = find_hvn_ceilings(hist, exit_zone_lo, exit_zone_hi)
    merged = merge_resistance_levels(pa, hvn)

    for lvl in merged:
        approach_data = count_resistance_approaches(hist, lvl["price"])
        lvl.update(approach_data)

    sell_recs = recommend_sell(math_prices, merged, total_shares)

    best_price = sell_recs[0]["price"] if sell_recs else math_prices["standard"]
    reachable = best_price <= metrics["high_20d_p75"]

    return sell_recs, reachable, {
        "math_prices": math_prices,
        "resistance_levels": merged,
        "best_sell": best_price,
    }


# ---------------------------------------------------------------------------
# Risk assessment (5 uplift-specific components)
# ---------------------------------------------------------------------------

def _assess_risk(metrics, stability, hist):
    """5-component uplift risk assessment. Returns (components_dict, overall_str).

    Key differences from Range Reset:
    - Overextension (ATR) replaces capital concentration / max drawdown
    - Volume confirmation — sustained volume, not low-volume float-up
    - 200-SMA: Uplift PREFERS being ABOVE 200-SMA (uptrend confirmation)
    - Consolidation: prefers gentle upslope (0% to +3%)
    """
    components = {}

    # 1. Stability (gating)
    if stability == "STABLE":
        components["stability"] = ("LOW", f"{metrics['convergence']}% convergence")
    elif stability == "SETTLING":
        components["stability"] = ("MODERATE", f"{metrics['convergence']}% convergence")
    else:
        components["stability"] = ("HIGH", f"{metrics['convergence']}% convergence")

    # 2. Overextension (gating) — how far above 20d median relative to ATR
    current_price = metrics["current_price"]
    median_20d = metrics["median_20d"]
    h20 = hist.tail(20)
    atr_20d = float((h20["High"] - h20["Low"]).mean())
    overext = current_price - median_20d

    if atr_20d > 0:
        if overext < 1.0 * atr_20d:
            components["overextension"] = ("LOW", f"price < median + 1 ATR")
        elif overext < 1.5 * atr_20d:
            components["overextension"] = ("MODERATE", f"price < median + 1.5 ATR")
        else:
            components["overextension"] = ("HIGH", f"price >= median + 1.5 ATR")
    else:
        components["overextension"] = ("MODERATE", "ATR=0 (insufficient data)")

    # 3. Volume (info — does not gate)
    vol_recent = float(h20["Volume"].mean())
    if len(hist) >= 40:
        vol_prior = float(hist.tail(40).head(20)["Volume"].mean())
        vol_ratio = vol_recent / vol_prior if vol_prior > 0 else 1.0
    else:
        vol_ratio = 1.0

    if vol_ratio >= 1.0:
        components["volume"] = ("LOW", f"{vol_ratio:.0%} of prior 20d")
    elif vol_ratio >= 0.8:
        components["volume"] = ("MODERATE", f"{vol_ratio:.0%} of prior 20d")
    else:
        components["volume"] = ("HIGH", f"{vol_ratio:.0%} of prior 20d")

    # 4. 200-SMA (info — does not gate)
    sma_dist = metrics.get("sma200_dist")
    if sma_dist is None:
        components["sma200"] = ("MODERATE", "200-SMA unavailable")
    elif sma_dist > 10:
        components["sma200"] = ("LOW", f"{sma_dist:+.1f}%")
    elif sma_dist >= 0:
        components["sma200"] = ("MODERATE", f"{sma_dist:+.1f}%")
    else:
        components["sma200"] = ("HIGH", f"{sma_dist:+.1f}%")

    # 5. Consolidation quality — 20-SMA slope (gating)
    slope = metrics.get("sma20_slope")
    if slope is None:
        components["consolidation"] = ("MODERATE", "slope unavailable")
    elif 0 <= slope <= 3:
        components["consolidation"] = ("LOW", f"slope {slope:+.1f}%/10d")
    elif (3 < slope <= 5) or (-1 <= slope < 0):
        components["consolidation"] = ("MODERATE", f"slope {slope:+.1f}%/10d")
    else:
        components["consolidation"] = ("HIGH", f"slope {slope:+.1f}%/10d")

    # Overall = worst of gating components (stability, overextension, consolidation)
    # Volume and 200-SMA are informational only
    gating = [
        components["stability"][0],
        components["overextension"][0],
        components["consolidation"][0],
    ]
    if "HIGH" in gating:
        overall = "HIGH"
    elif "MODERATE" in gating:
        overall = "MODERATE"
    else:
        overall = "LOW"

    return components, overall


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_candidate(stability, swing_20d, exit_reachable, ticker, risk_overall,
                     cycle_timing=None):
    """Score 0-100."""
    score = 0

    # Stability
    if stability == "STABLE":
        score += STABILITY_PTS
    elif stability == "SETTLING":
        score += STABILITY_PTS_SETTLING

    # Swing
    if swing_20d >= 30:
        score += SWING_PTS
    elif swing_20d >= SWING_MIN:
        score += SWING_PTS_PARTIAL

    # Exit reachability
    if exit_reachable:
        score += EXIT_REACH_PTS

    # Cycle efficiency
    if cycle_timing is None:
        cycle_timing = load_cycle_timing(ticker)
    ce = score_cycle_efficiency(cycle_timing)
    score += round(ce * CYCLE_EFF_PTS / 20)

    # Risk (inverse)
    if risk_overall == "LOW":
        score += RISK_PTS
    elif risk_overall == "MODERATE":
        score += RISK_PTS_MODERATE

    return score


def _verdict_from_score(score, stability=None):
    """Map score to verdict. UNSTABLE caps at MONITOR."""
    if stability == "UNSTABLE":
        return "MONITOR" if score >= 25 else "NO-UPLIFT"
    if score >= 75:
        return "UPLIFT-READY"
    elif score >= 50:
        return "UPLIFT-POSSIBLE"
    elif score >= 25:
        return "MONITOR"
    else:
        return "NO-UPLIFT"


# ---------------------------------------------------------------------------
# Process one ticker
# ---------------------------------------------------------------------------

def _process_ticker(candidate, hist, portfolio):
    """Full pipeline for one ticker. Returns result dict."""
    ticker = candidate["ticker"]
    result = {"ticker": ticker}

    # G4: sufficient data
    if hist is None or len(hist) < 60:
        result["skip"] = "insufficient data (need 60+ trading days)"
        return result

    metrics = _compute_range_metrics(hist)
    current_price = metrics["current_price"]

    # Data freshness
    last_date = hist.index[-1].strftime("%Y-%m-%d")
    result["data_as_of"] = last_date

    # G5: swing >= SWING_MIN
    if metrics["swing_20d"] < SWING_MIN:
        result["skip"] = f"swing {metrics['swing_20d']}% < {SWING_MIN}% minimum"
        return result

    # G6: not underwater (if position exists with shares > 0)
    shares = candidate["shares"]
    avg_cost = candidate["avg_cost"]
    if shares > 0 and avg_cost > 0 and current_price < avg_cost:
        pnl_pct = round((current_price - avg_cost) / avg_cost * 100, 1)
        result["skip"] = f"underwater ({pnl_pct}%) — use Range Reset instead"
        return result

    # Detect dormant orders
    dormant, active_orders, freed_capital = _detect_dormant_orders(
        candidate["unfilled_buys"], current_price, metrics["low_20d"]
    )

    # G2: minimum dormant orders
    if len(dormant) < MIN_DORMANT_ORDERS:
        result["skip"] = f"no dormant orders (all within {DORMANCY_DIST_PCT:.0%} of price)"
        return result

    # Min freed capital gate
    if freed_capital < MIN_FREED_CAPITAL:
        result["skip"] = f"freed capital ${freed_capital:.2f} < ${MIN_FREED_CAPITAL:.2f} minimum"
        return result

    # Build result
    total_pending = len(candidate["unfilled_buys"])
    result["position"] = {
        "shares": shares,
        "avg_cost": avg_cost,
        "current_price": current_price,
    }
    result["metrics"] = metrics
    result["dormant_orders"] = dormant
    result["active_orders"] = [
        {
            "price": o.get("price", 0),
            "shares": o.get("shares", 0),
            "cost": round(o.get("price", 0) * o.get("shares", 0), 2),
            "distance_pct": round((o.get("price", 0) - current_price) / current_price * 100, 1),
            "note": o.get("note", ""),
        }
        for o in active_orders
        if o.get("type") == "BUY"
    ]
    result["freed_capital"] = freed_capital
    result["total_pending_buys"] = total_pending

    stability = _classify_stability(metrics["convergence"])
    result["stability"] = stability

    # Redeployment scenarios
    scenarios, context = _compute_redeployment_scenarios(
        candidate, hist, metrics, active_orders, freed_capital
    )
    result["level_context"] = context

    if scenarios is None:
        # No scenarios — score with exit_reachable=False
        risk_components, risk_overall = _assess_risk(metrics, stability, hist)
        result["risk"] = {"components": risk_components, "overall": risk_overall}
        score = _score_candidate(stability, metrics["swing_20d"], False, ticker, risk_overall)
        result["score"] = score
        result["verdict"] = _verdict_from_score(score, stability)
        result["scenarios"] = None
        result["sell_recs"] = None
        return result

    result["scenarios"] = scenarios

    # Exit reachability
    blended_avg = context["blended_avg_final"]
    total_shares = context["total_shares_final"]
    sell_recs, exit_reachable, exit_details = _compute_exit_reachability(
        hist, blended_avg, total_shares, metrics
    )
    result["sell_recs"] = sell_recs
    result["exit_details"] = exit_details
    result["exit_reachable"] = exit_reachable

    # Risk
    risk_components, risk_overall = _assess_risk(metrics, stability, hist)
    result["risk"] = {"components": risk_components, "overall": risk_overall}

    # Score
    score = _score_candidate(
        stability, metrics["swing_20d"], exit_reachable, ticker, risk_overall
    )
    result["score"] = score
    result["verdict"] = _verdict_from_score(score, stability)

    return result


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _format_ticker_md(r):
    """Format one ticker result as markdown."""
    if "skip" in r:
        return f"### {r['ticker']} — SKIPPED\n\n*{r['skip']}*\n"

    lines = []
    m = r["metrics"]
    verdict = r["verdict"]
    score = r["score"]
    data_date = r.get("data_as_of", "?")

    lines.append(f"### {r['ticker']} — {verdict} (Score: {score}/100)\n")
    lines.append(f"*Data as of {data_date} close.*\n")

    # Current Position
    pos = r["position"]
    shares = pos["shares"]
    dormant = r["dormant_orders"]
    active = r["active_orders"]
    total_buys = r["total_pending_buys"]

    lines.append("**Current Position**")
    lines.append("| Field | Value |")
    lines.append("| :--- | :--- |")
    if shares > 0:
        lines.append(f"| Shares | {shares} @ ${pos['avg_cost']:.2f} avg |")
    else:
        lines.append("| Shares | 0 (watchlist) |")

    # All pending order price range (dormant + active)
    all_prices = [d["price"] for d in dormant] + [a["price"] for a in active]
    if len(all_prices) > 1:
        all_range = f"${min(all_prices):.2f} — ${max(all_prices):.2f}"
    else:
        all_range = f"${all_prices[0]:.2f}"
    lines.append(f"| Pending BUY Orders | {total_buys} ({all_range}) |")
    lines.append(f"| Dormant Orders | {len(dormant)} of {total_buys} (all >{DORMANCY_DIST_PCT:.0%} below price) |")
    lines.append(f"| Freed Capital | ${r['freed_capital']:.2f} |")
    lines.append("")

    # Dormant Orders table
    lines.append("**Dormant Orders (to cancel)**")
    lines.append("| # | Price | Shares | Cost | Distance | Note |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
    for i, d in enumerate(dormant, 1):
        lines.append(
            f"| {i} | ${d['price']:.2f} | {d['shares']} | ${d['cost']:.2f} "
            f"| {d['distance_pct']:+.1f}% | {d['note']} |"
        )
    lines.append("")

    # Active orders table (if any)
    if active:
        lines.append("**Active Orders (kept)**")
        lines.append("| # | Price | Shares | Cost | Distance | Note |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for i, a in enumerate(active, 1):
            lines.append(
                f"| {i} | ${a['price']:.2f} | {a['shares']} | ${a['cost']:.2f} "
                f"| {a['distance_pct']:+.1f}% | {a['note']} |"
            )
        lines.append("")

    # New Range Analysis
    lines.append("**New Range Analysis**")
    lines.append("| Metric | Value |")
    lines.append("| :--- | :--- |")
    lines.append(f"| 20d Range | ${m['low_20d']:.2f} — ${m['high_20d']:.2f} |")
    lines.append(f"| 20d High (p75) | ${m['high_20d_p75']:.2f} |")
    lines.append(f"| 20d Swing | {m['swing_20d']}% |")
    lines.append(f"| 20d Median | ${m['median_20d']:.2f} |")
    lines.append(f"| 40d Median | ${m['median_40d']:.2f} |")
    lines.append(f"| Median Convergence | {m['convergence']}% → {r['stability']} |")
    sma_str = f"{m['sma200_dist']:+.1f}%" if m['sma200_dist'] is not None else "N/A"
    lines.append(f"| 200-SMA Distance | {sma_str} |")
    slope_str = f"{m['sma20_slope']:+.1f}%/10d" if m['sma20_slope'] is not None else "N/A"
    lines.append(f"| 20-SMA Slope (10d) | {slope_str} |")

    ctx = r["level_context"]
    total = ctx.get("total_levels", 0)
    in_r = ctx.get("in_range_count", 0)
    below = ctx.get("below_range_count", 0)
    above = ctx.get("above_range_count", 0)
    lines.append(f"| Levels (13-month) | {total} total: {in_r} usable, {below} below-range, {above} above-range |")
    lines.append("")

    scenarios = r.get("scenarios")
    if scenarios is None:
        msg = ctx.get("message", "No scenarios available")
        lines.append(f"*{msg}*\n")
    else:
        # Below-threshold warning
        if verdict in ("MONITOR", "NO-UPLIFT"):
            lines.append("*Below deployment threshold (need 50+). Scenarios shown for reference only.*\n")

        # Redeployment Scenarios table
        lines.append("**Redeployment Scenarios**")
        lines.append("| Level | Buy At | Hold% | Tier | Shares | Cost | Avg | 6% Exit | Reachable? |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for s in scenarios:
            source_label = s.get("source", "")
            reach_str = "YES" if s["reachable"] else "NO"
            lines.append(
                f"| {source_label} | ${s['buy_at']:.2f} | {s['hold_rate']:.0f}% | {s['tier']} "
                f"| {s['shares']} | ${s['cost']:.2f} | ${s['new_avg']:.2f} "
                f"| ${s['exit_6pct']:.2f} | {reach_str} |"
            )
        lines.append("")

        p75 = m["high_20d_p75"]
        max_20d = m["high_20d"]
        lines.append(f"*Budget: ${r['freed_capital']:.2f} freed from {len(dormant)} cancelled orders.*")
        lines.append(f"*Reachability: 6% exit vs 20d high p75 (${p75:.2f}). Absolute 20d max: ${max_20d:.2f} (reference only).*")
        lines.append("*Averages are cumulative — each row assumes all rows above it also fill.*\n")

    # Sell recommendation
    sell_recs = r.get("sell_recs")
    if sell_recs:
        if len(sell_recs) == 1:
            sr = sell_recs[0]
            lines.append(f"**Recommended Sell Target:** ${sr['price']:.2f} ({sr['basis']})\n")
        else:
            lines.append("**Recommended Sell Targets:**")
            for sr in sell_recs:
                lines.append(f"- ${sr['price']:.2f} × {sr['shares']} shares ({sr['basis']})")
            lines.append("")

    # Risk Assessment
    risk = r.get("risk", {})
    components = risk.get("components", {})
    if components:
        lines.append("**Risk Assessment**")
        lines.append("| Component | Rating |")
        lines.append("| :--- | :--- |")
        # Info-only components get (info) suffix
        info_components = {"volume", "sma200"}
        for name, (rating, detail) in components.items():
            label = name.replace("_", " ").title()
            suffix = " (info)" if name in info_components else ""
            lines.append(f"| {label}{suffix} | {rating} ({detail}) |")
        lines.append(f"| **Overall** | **{risk.get('overall', '?')}** |")
        lines.append("")

    return "\n".join(lines)


def _format_summary_table(results):
    """Format stdout summary table."""
    lines = []
    lines.append("| Ticker | Score | Verdict | Stability | Swing | Dormant | Freed$ | Risk |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for r in results:
        if "skip" in r:
            lines.append(f"| {r['ticker']} | — | SKIPPED | — | — | — | — | {r['skip']} |")
            continue
        m = r.get("metrics", {})
        n_dormant = len(r.get("dormant_orders", []))
        freed = r.get("freed_capital", 0)
        risk_overall = r.get("risk", {}).get("overall", "?")
        lines.append(
            f"| {r['ticker']} | {r['score']} | {r['verdict']} "
            f"| {r.get('stability', '?')} | {m.get('swing_20d', '?')}% "
            f"| {n_dormant} | ${freed:.0f} | {risk_overall} |"
        )
    return "\n".join(lines)


def _build_json_output(results, report_date=None):
    """Build JSON-serializable output."""
    out = {
        "date": report_date or datetime.date.today().isoformat(),
        "candidates": [],
    }
    for r in results:
        entry = {"ticker": r["ticker"]}
        if "skip" in r:
            entry["skip"] = r["skip"]
        else:
            entry["score"] = r["score"]
            entry["verdict"] = r["verdict"]
            entry["data_as_of"] = r.get("data_as_of")
            entry["stability"] = r.get("stability")
            entry["swing_20d"] = r.get("metrics", {}).get("swing_20d")
            entry["exit_reachable"] = r.get("exit_reachable", False)
            entry["risk_overall"] = r.get("risk", {}).get("overall")
            entry["metrics"] = r.get("metrics")
            entry["position"] = r.get("position")
            entry["dormant_orders"] = r.get("dormant_orders")
            entry["active_orders"] = r.get("active_orders")
            entry["freed_capital"] = r.get("freed_capital")
            entry["scenarios"] = r.get("scenarios")
            entry["sell_recs"] = r.get("sell_recs")
            # Risk component breakdown
            risk_comps = r.get("risk", {}).get("components", {})
            entry["risk_components"] = {
                k: {"rating": v[0], "detail": v[1]}
                for k, v in risk_comps.items()
            }
        out["candidates"].append(entry)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    requested = [t.upper() for t in sys.argv[1:]] if len(sys.argv) > 1 else None
    portfolio = _load_portfolio()

    candidates, skipped = _identify_uplift_candidates(portfolio, requested)
    if skipped:
        for t, reason in skipped.items():
            print(f"  {t}: skipped ({reason})")
    if not candidates:
        print("No qualifying tickers found (need unfilled BUY orders, not recovery).")
        return

    tickers = [c["ticker"] for c in candidates]

    # Data freshness warning (weekends/holidays)
    now = datetime.datetime.now()
    if now.weekday() >= 5:
        day_name = "Saturday" if now.weekday() == 5 else "Sunday"
        print(f"Note: Today is {day_name} — all price data is from last trading day's close.")

    print(f"Analyzing {len(tickers)} tickers: {', '.join(tickers)}")

    # Fetch history in parallel
    hist_map = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_fetch_ticker_data, t) for t in tickers]
        for f in futures:
            t, h = f.result()
            hist_map[t] = h

    # Process each ticker
    results = []
    for c in candidates:
        ticker = c["ticker"]
        hist = hist_map.get(ticker)
        r = _process_ticker(c, hist, portfolio)
        results.append(r)

    # Sort by score descending (skipped at end)
    results.sort(key=lambda r: r.get("score", -1), reverse=True)

    # Summary table to stdout
    summary = _format_summary_table(results)
    print("\n" + summary)

    # Effective data date
    data_dates = [r.get("data_as_of") for r in results if r.get("data_as_of")]
    report_date = max(data_dates) if data_dates else datetime.date.today().isoformat()

    # Full markdown report
    md_parts = [f"# Range Uplift Analysis — {report_date}\n"]
    md_parts.append(summary + "\n")
    md_parts.append("---\n")
    for r in results:
        md_parts.append(_format_ticker_md(r))
        md_parts.append("---\n")

    md_out = "\n".join(md_parts)
    with open(OUTPUT_MD, "w") as f:
        f.write(md_out)
    print(f"\nWrote {OUTPUT_MD}")

    # JSON output
    json_out = _build_json_output(results, report_date=report_date)
    with open(OUTPUT_JSON, "w") as f:
        json.dump(json_out, f, indent=2)
    print(f"Wrote {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
