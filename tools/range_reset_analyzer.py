"""Range Reset Analyzer — detect playable new ranges on underwater positions.

When a stock drops and fills multiple bullets, the position becomes underwater.
If the stock then settles into a stable new range with strategy-grade swing,
this tool recommends fresh bullets from the reserve pool to play that range,
bringing the average down with each fill.

Usage:
    python3 tools/range_reset_analyzer.py              # all qualifying underwater positions
    python3 tools/range_reset_analyzer.py APLD CLF      # specific tickers
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
OUTPUT_MD = _ROOT / "range-reset-analysis.md"
OUTPUT_JSON = _ROOT / "range-reset-analysis.json"

# --- Imports from sibling tools ---
sys.path.insert(0, str(Path(__file__).resolve().parent))
from wick_offset_analyzer import fetch_history, analyze_stock_data, compute_pool_sizing, load_capital_config
from bullet_recommender import parse_bullets_used
from shared_constants import MATCH_TOLERANCE, EXIT_CONSERVATIVE, EXIT_STANDARD, EXIT_AGGRESSIVE, SWING_MIN, MIN_HOLD_RATE
from shared_utils import load_cycle_timing, score_cycle_efficiency
from sell_target_calculator import (
    find_pa_resistances, find_hvn_ceilings, count_resistance_approaches,
    recommend_sell, merge_resistance_levels,
)

# --- Constants ---
MEDIAN_CONVERGENCE_STABLE = 5.0      # % — 20d within 5% of 40d = STABLE
MEDIAN_CONVERGENCE_SETTLING = 10.0   # % — 5-10% = SETTLING, >10% = UNSTABLE
DOWNTREND_SMA200_THRESHOLD = -15.0   # % below 200-SMA = HIGH risk
SLOPE_FALLING_THRESHOLD = -3.0       # 10d slope of 20-SMA < -3% = falling knife
MIN_BULLETS_USED = 3                 # qualification: at least 3 bullets spent
RESERVE_CONFLICT_PCT = 0.02          # 2% tolerance for reserve order conflict detection
NEAR_RANGE_PCT = 0.10               # 10% below 20d low = near-range cutoff

# Scoring weights (sum to 100)
STABILITY_PTS = 25
STABILITY_PTS_SETTLING = 15   # partial credit for SETTLING
SWING_PTS = 20
SWING_PTS_PARTIAL = 15        # partial credit for 20-30% swing
EXIT_REACH_PTS = 20
CYCLE_EFF_PTS = 15
RISK_PTS = 20
RISK_PTS_MODERATE = 10        # partial credit for MODERATE risk

assert STABILITY_PTS + SWING_PTS + EXIT_REACH_PTS + CYCLE_EFF_PTS + RISK_PTS == 100, \
    "Scoring weights must sum to 100"


# ---------------------------------------------------------------------------
# Portfolio loading & qualification
# ---------------------------------------------------------------------------

def _load_portfolio():
    with open(PORTFOLIO_PATH, "r") as f:
        return json.load(f)


def _identify_underwater(portfolio, requested_tickers=None):
    """Return (candidates_list, skipped_dict) for positions passing G2-G3 structural gates.

    G1 (underwater) and G4 (sufficient data) require price data — checked in _process_ticker.
    skipped_dict: {ticker: reason} for explicitly requested tickers that didn't qualify.
    """
    candidates = []
    skipped = {}
    positions = portfolio.get("positions", {})
    for ticker, pos in positions.items():
        if requested_tickers and ticker not in requested_tickers:
            continue
        shares = pos.get("shares", 0)
        avg_cost = pos.get("avg_cost", 0)
        if shares <= 0 or avg_cost <= 0:
            if requested_tickers:
                skipped[ticker] = "closed position"
            continue

        # G3: not recovery mode
        note = pos.get("note", "")
        if "recovery mode" in note.lower():
            if requested_tickers:
                skipped[ticker] = "recovery mode"
            continue

        # G2: >= MIN_BULLETS_USED active bullets
        parsed = parse_bullets_used(pos.get("bullets_used", 0), note)
        if parsed["active"] < MIN_BULLETS_USED:
            if requested_tickers:
                skipped[ticker] = f"only {parsed['active']} active bullets (need {MIN_BULLETS_USED})"
            continue

        candidates.append({
            "ticker": ticker,
            "shares": shares,
            "avg_cost": avg_cost,
            "bullets_used": pos.get("bullets_used"),
            "parsed_bullets": parsed,
            "fill_prices": pos.get("fill_prices", []),
            "target_exit": pos.get("target_exit"),
            "note": note,
            "pre_strategy": parsed["pre_strategy"],
        })

    # Check for requested tickers not found in portfolio at all
    if requested_tickers:
        for t in requested_tickers:
            if t not in positions and t not in skipped:
                skipped[t] = "not in portfolio"

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
# Range metrics
# ---------------------------------------------------------------------------

def _compute_range_metrics(hist):
    """Compute 20d/40d medians, swing, p75, 200-SMA distance, 20-SMA slope."""
    current_price = float(hist["Close"].iloc[-1])

    # 20d range
    h20 = hist.tail(20)
    low_20d = float(h20["Low"].min())
    high_20d = float(h20["High"].max())
    median_20d = float(h20["Close"].median())
    swing_20d = ((high_20d - low_20d) / low_20d) * 100 if low_20d > 0 else 0
    high_20d_p75 = float(np.percentile(h20["High"].values, 75))

    # 40d median
    h40 = hist.tail(40)
    median_40d = float(h40["Close"].median())

    # Median convergence
    convergence = abs(median_20d - median_40d) / median_40d * 100 if median_40d > 0 else 999

    # 200-SMA distance
    sma200 = None
    sma200_dist = None
    if len(hist) >= 200:
        sma200 = float(hist["Close"].tail(200).mean())
        sma200_dist = (current_price - sma200) / sma200 * 100

    # 20-SMA slope (10d) — % change of 20-SMA over last 10 days
    # Need >=40 days for non-overlapping 20-day windows (now vs 10d ago)
    sma20_slope = None
    if len(hist) >= 40:
        sma20_now = float(hist["Close"].tail(20).mean())
        sma20_10d_ago = float(hist["Close"].iloc[-30:-10].mean())
        if sma20_10d_ago > 0:
            sma20_slope = (sma20_now - sma20_10d_ago) / sma20_10d_ago * 100

    return {
        "current_price": current_price,
        "low_20d": low_20d,
        "high_20d": high_20d,
        "median_20d": median_20d,
        "high_20d_p75": high_20d_p75,
        "swing_20d": round(swing_20d, 1),
        "median_40d": median_40d,
        "convergence": round(convergence, 1),
        "sma200": sma200,
        "sma200_dist": round(sma200_dist, 1) if sma200_dist is not None else None,
        "sma20_slope": round(sma20_slope, 1) if sma20_slope is not None else None,
    }


# ---------------------------------------------------------------------------
# Stability classification
# ---------------------------------------------------------------------------

def _classify_stability(convergence):
    if convergence < MEDIAN_CONVERGENCE_STABLE:
        return "STABLE"
    elif convergence <= MEDIAN_CONVERGENCE_SETTLING:
        return "SETTLING"
    else:
        return "UNSTABLE"


# ---------------------------------------------------------------------------
# Level filtering helpers
# ---------------------------------------------------------------------------

def _is_match(price_a, price_b, tolerance=MATCH_TOLERANCE):
    """True if prices are within tolerance %."""
    if price_b == 0:
        return False
    return abs(price_a - price_b) / price_b <= tolerance


def _classify_level_range(buy_at, low_20d, high_20d):
    """Classify a level as in-range, near-range, or below-range."""
    if low_20d <= buy_at <= high_20d:
        return "in-range"
    if buy_at < low_20d:
        dist_below = (low_20d - buy_at) / low_20d
        if dist_below <= NEAR_RANGE_PCT:
            return "near-range"
        return "below-range"
    return "above-range"


def _detect_reserve_orders(pending_orders, ticker):
    """Find unfilled reserve BUY orders and compute committed capital."""
    orders = pending_orders.get(ticker, [])
    reserve_committed = 0.0
    reserve_orders = []
    _reserve_re = re.compile(r"reserve|R\d", re.IGNORECASE)
    for o in orders:
        if o.get("type") != "BUY":
            continue
        if not _reserve_re.search(o.get("note", "")):
            continue
        if o.get("filled"):
            continue  # already deployed as fill_prices
        cost = o.get("shares", 0) * o.get("price", 0)
        reserve_committed += cost
        reserve_orders.append(o)
    return reserve_orders, round(reserve_committed, 2)


# ---------------------------------------------------------------------------
# Accumulation scenarios
# ---------------------------------------------------------------------------

def _compute_accumulation_scenarios(candidate, hist, metrics, portfolio,
                                    reserve_pool=300, precomputed_analysis=None):
    """Compute new bullet scenarios from wick levels within the 20d range.

    Returns (scenarios_list, context_dict) or (None, context_dict) if no levels.
    precomputed_analysis: optional (data_dict, None) tuple from a prior analyze_stock_data()
        call — avoids re-running the expensive level discovery when called from workflows.
    """
    ticker = candidate["ticker"]

    # Get all 13-month support levels (reuse precomputed if available)
    if precomputed_analysis is not None:
        data, err = precomputed_analysis
    else:
        data, err = analyze_stock_data(ticker, hist)
    if err is not None:
        return None, {"error": err, "total_levels": 0}

    all_levels = data.get("levels", [])
    fill_prices = candidate["fill_prices"]
    pending_orders = portfolio.get("pending_orders", {}).get(ticker, [])
    pending_buy_prices = [
        o["price"] for o in pending_orders
        if o.get("type") == "BUY" and not o.get("filled")
    ]

    low_20d = metrics["low_20d"]
    high_20d = metrics["high_20d"]

    # Classify and filter levels
    in_range = []
    filled_count = 0
    pending_count = 0
    below_range_count = 0
    above_range_count = 0

    for raw_lvl in all_levels:
        buy_at = raw_lvl.get("recommended_buy")
        if buy_at is None:
            continue

        # Check if filled
        is_filled = any(_is_match(buy_at, fp) for fp in fill_prices)
        if is_filled:
            filled_count += 1
            continue

        # Check if already has a pending order
        is_pending = any(_is_match(buy_at, pp) for pp in pending_buy_prices)
        if is_pending:
            pending_count += 1
            continue

        range_class = _classify_level_range(buy_at, low_20d, high_20d)
        if range_class == "below-range":
            below_range_count += 1
            continue
        if range_class == "above-range":
            above_range_count += 1
            continue

        # Skip dead-zone levels (hold_rate < 15% = no order per strategy)
        if raw_lvl.get("hold_rate", 0) < MIN_HOLD_RATE:
            continue

        # Deep-copy to avoid mutating caller's precomputed_analysis data
        lvl = copy.deepcopy(raw_lvl)
        lvl["range_class"] = range_class
        in_range.append(lvl)

    total_levels = len(all_levels)
    context = {
        "total_levels": total_levels,
        "in_range_count": len(in_range),
        "filled_count": filled_count,
        "pending_count": pending_count,
        "below_range_count": below_range_count,
        "above_range_count": above_range_count,
    }

    if not in_range:
        context["message"] = "No usable support levels in current range — wait for range expansion or deeper pullback"
        return None, context

    # Reserve budget
    reserve_orders, reserve_committed = _detect_reserve_orders(
        portfolio.get("pending_orders", {}), ticker
    )
    pool_budget = round(float(reserve_pool) - reserve_committed, 2)
    context["reserve_pool"] = reserve_pool
    context["reserve_committed"] = reserve_committed
    context["pool_budget"] = pool_budget
    context["reserve_orders"] = reserve_orders

    if pool_budget <= 0:
        context["message"] = "Reserve pool fully committed — no capital available for range reset"
        return None, context

    # Preserve original level metadata before compute_pool_sizing strips it
    # Keyed by index (not float price) to avoid collision when two levels share
    # the same recommended_buy price.
    orig_meta = [
        {
            "tier": lvl.get("effective_tier", lvl.get("tier", "?")),
            "source": lvl.get("source", ""),
            "support_price": lvl.get("support_price", lvl.get("recommended_buy")),
            "range_class": lvl.get("range_class", "?"),
        }
        for lvl in in_range
    ]

    # Size bullets via compute_pool_sizing (preserves input order)
    sized = compute_pool_sizing(in_range, pool_budget, pool_name="reserve")

    # Build scenario rows with blended avg math
    scenarios = []
    old_shares = candidate["shares"]
    old_avg = candidate["avg_cost"]

    for i, lvl in enumerate(sized):
        # Restore metadata stripped by compute_pool_sizing
        meta = orig_meta[i] if i < len(orig_meta) else {}
        lvl.update(meta)
        buy_at = lvl["recommended_buy"]
        new_shares = lvl.get("shares", 0)
        cost = lvl.get("cost", 0)
        if new_shares == 0:
            continue

        total_shares = old_shares + new_shares
        blended_avg = round((old_shares * old_avg + new_shares * buy_at) / total_shares, 2)
        exit_6pct = round(blended_avg * EXIT_STANDARD, 2)
        reachable = exit_6pct <= metrics["high_20d_p75"]

        # Check reserve conflict
        conflict = None
        for ro in reserve_orders:
            if abs(buy_at - ro["price"]) / ro["price"] <= RESERVE_CONFLICT_PCT:
                conflict = f"Pending R @ ${ro['price']:.2f} — cancel & redeploy?"
                break

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
            "conflict": conflict,
            "range_class": lvl.get("range_class", "?"),
            "source": lvl.get("source", ""),
        })

        # Accumulate for next row
        old_shares = total_shares
        old_avg = blended_avg

    context["blended_avg_final"] = old_avg if scenarios else candidate["avg_cost"]
    context["total_shares_final"] = old_shares if scenarios else candidate["shares"]

    # Empty scenarios (all levels rounded to 0 shares) → treat as None
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

    # Gather resistances in the exit zone
    pa = find_pa_resistances(hist, exit_zone_lo, exit_zone_hi)
    hvn = find_hvn_ceilings(hist, exit_zone_lo, exit_zone_hi)
    merged = merge_resistance_levels(pa, hvn)

    # Count approaches for each resistance level
    for lvl in merged:
        approach_data = count_resistance_approaches(hist, lvl["price"])
        lvl.update(approach_data)

    sell_recs = recommend_sell(math_prices, merged, total_shares)

    # Check if best sell target is reachable within p75
    best_price = sell_recs[0]["price"] if sell_recs else math_prices["standard"]
    reachable = best_price <= metrics["high_20d_p75"]

    return sell_recs, reachable, {
        "math_prices": math_prices,
        "resistance_levels": merged,
        "best_sell": best_price,
    }


# ---------------------------------------------------------------------------
# Risk assessment
# ---------------------------------------------------------------------------

def _assess_risk(metrics, stability, pool_budget, scenarios, reserve_pool=300):
    """5-component risk assessment. Returns (components_dict, overall_str)."""
    components = {}

    # 1. Stability
    if stability == "STABLE":
        components["stability"] = ("LOW", f"{metrics['convergence']}% convergence")
    elif stability == "SETTLING":
        components["stability"] = ("MODERATE", f"{metrics['convergence']}% convergence")
    else:
        components["stability"] = ("HIGH", f"{metrics['convergence']}% convergence")

    # 2. Capital concentration — measured against available budget (not total pool)
    # to reflect true exposure when reserves are partially committed elsewhere
    total_cost = sum(s["cost"] for s in scenarios) if scenarios else 0
    if pool_budget > 0:
        conc_pct = total_cost / pool_budget * 100
    else:
        conc_pct = 0
    if conc_pct < 20:
        components["capital"] = ("LOW", f"${total_cost:.0f} = {conc_pct:.0f}% of pool")
    elif conc_pct <= 40:
        components["capital"] = ("MODERATE", f"${total_cost:.0f} = {conc_pct:.0f}% of pool")
    else:
        components["capital"] = ("HIGH", f"${total_cost:.0f} = {conc_pct:.0f}% of pool")

    # 3. Max drawdown (-20%)
    exposure = total_cost * 0.20
    if exposure < 100:
        components["max_drawdown"] = ("LOW", f"${exposure:.0f} at risk")
    elif exposure <= 150:
        components["max_drawdown"] = ("MODERATE", f"${exposure:.0f} at risk")
    else:
        components["max_drawdown"] = ("HIGH", f"${exposure:.0f} at risk")

    # 4. 200-SMA position
    sma_dist = metrics.get("sma200_dist")
    if sma_dist is None:
        components["sma200"] = ("MODERATE", "200-SMA unavailable")
    elif sma_dist > -5:
        components["sma200"] = ("LOW", f"{sma_dist:+.1f}%")
    elif sma_dist >= DOWNTREND_SMA200_THRESHOLD:
        components["sma200"] = ("MODERATE", f"{sma_dist:+.1f}%")
    else:
        components["sma200"] = ("HIGH", f"{sma_dist:+.1f}%")

    # 5. Consolidation quality (20-SMA slope)
    slope = metrics.get("sma20_slope")
    if slope is None:
        components["consolidation"] = ("MODERATE", "slope unavailable")
    elif slope >= -1:
        components["consolidation"] = ("LOW", f"slope {slope:+.1f}%/10d")
    elif slope >= SLOPE_FALLING_THRESHOLD:
        components["consolidation"] = ("MODERATE", f"slope {slope:+.1f}%/10d")
    else:
        components["consolidation"] = ("HIGH", f"slope {slope:+.1f}%/10d")

    # Overall = worst of structural risk factors (stability, 200-SMA, consolidation).
    # Capital and max_drawdown are informational — they scale with position size,
    # not range quality, so they don't gate the deploy/no-deploy decision.
    key_ratings = [
        components["stability"][0],
        components["sma200"][0],
        components["consolidation"][0],
    ]
    if "HIGH" in key_ratings:
        overall = "HIGH"
    elif "MODERATE" in key_ratings:
        overall = "MODERATE"
    else:
        overall = "LOW"

    return components, overall


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_candidate(stability, swing_20d, exit_reachable, ticker, risk_overall,
                     cycle_timing=None):
    """Score 0-100. cycle_timing: optional pre-loaded dict (avoids disk read)."""
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
    """Map score to verdict. UNSTABLE caps at MONITOR per strategy rule."""
    if stability == "UNSTABLE":
        # "UNSTABLE = no deploy regardless of score" — strategy.md
        return "MONITOR" if score >= 25 else "NO-RESET"
    if score >= 75:
        return "RESET-READY"
    elif score >= 50:
        return "RESET-POSSIBLE"
    elif score >= 25:
        return "MONITOR"
    else:
        return "NO-RESET"


# ---------------------------------------------------------------------------
# Process one ticker
# ---------------------------------------------------------------------------

def _process_ticker(candidate, hist, portfolio, reserve_pool=300):
    """Full pipeline for one ticker. Returns result dict."""
    ticker = candidate["ticker"]
    result = {"ticker": ticker}

    # G4: sufficient data
    if hist is None or len(hist) < 60:
        result["skip"] = "insufficient data (need 60+ trading days)"
        return result

    metrics = _compute_range_metrics(hist)
    current_price = metrics["current_price"]

    # Data freshness: last trading date from history
    last_date = hist.index[-1].strftime("%Y-%m-%d")
    result["data_as_of"] = last_date

    # G1: underwater
    if current_price >= candidate["avg_cost"]:
        result["skip"] = "not underwater"
        return result

    pnl_pct = round((current_price - candidate["avg_cost"]) / candidate["avg_cost"] * 100, 1)
    pnl_dollar = round((current_price - candidate["avg_cost"]) * candidate["shares"], 2)

    result["position"] = {
        "shares": candidate["shares"],
        "avg_cost": candidate["avg_cost"],
        "current_price": current_price,
        "pnl_pct": pnl_pct,
        "pnl_dollar": pnl_dollar,
        "bullets_used": candidate["bullets_used"],
        "target_exit": candidate["target_exit"],
        "pre_strategy": candidate["pre_strategy"],
    }
    result["metrics"] = metrics

    stability = _classify_stability(metrics["convergence"])
    result["stability"] = stability

    # Accumulation scenarios
    scenarios, context = _compute_accumulation_scenarios(
        candidate, hist, metrics, portfolio, reserve_pool=reserve_pool
    )
    result["level_context"] = context

    if scenarios is None:
        # No scenarios — score with exit_reachable=False
        risk_components, risk_overall = _assess_risk(
            metrics, stability, context.get("pool_budget", 0), [],
            reserve_pool=reserve_pool,
        )
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
    risk_components, risk_overall = _assess_risk(
        metrics, stability, context.get("pool_budget", reserve_pool), scenarios,
        reserve_pool=reserve_pool,
    )
    result["risk"] = {"components": risk_components, "overall": risk_overall}

    # Score
    score = _score_candidate(stability, metrics["swing_20d"], exit_reachable, ticker, risk_overall)
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
    pos = r["position"]
    m = r["metrics"]
    verdict = r["verdict"]
    score = r["score"]

    data_date = r.get("data_as_of", "?")
    lines.append(f"### {r['ticker']} — {verdict} (Score: {score}/100)\n")
    lines.append(f"*Data as of {data_date} close.*\n")

    # Current Position
    lines.append("**Current Position**")
    lines.append("| Field | Value |")
    lines.append("| :--- | :--- |")
    lines.append(f"| Shares | {pos['shares']} @ ${pos['avg_cost']:.2f} avg |")
    lines.append(f"| P/L | {pos['pnl_pct']:+.1f}% (${pos['pnl_dollar']:+.2f}) |")
    lines.append(f"| Bullets Used | {pos['bullets_used']} |")
    target_str = f"${pos['target_exit']:.2f}" if pos['target_exit'] else "—"
    lines.append(f"| Current Sell Target | {target_str} |")
    lines.append(f"| Pre-Strategy | {'Yes' if pos['pre_strategy'] else 'No'} |")
    lines.append("")

    if pos["pre_strategy"]:
        lines.append("*Pre-strategy position — capital allocation may differ.*\n")

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
    filled = ctx.get("filled_count", 0)
    pend = ctx.get("pending_count", 0)
    below = ctx.get("below_range_count", 0)
    above = ctx.get("above_range_count", 0)
    parts = [f"{total} total: {in_r} usable, {filled} filled, {pend} pending, {below} below-range"]
    if above:
        parts[0] += f", {above} above-range"
    lines.append(f"| Levels (13-month) | {parts[0]} |")
    lines.append("")

    scenarios = r.get("scenarios")
    if scenarios is None:
        msg = ctx.get("message", "No scenarios available")
        lines.append(f"*{msg}*\n")
    else:
        # Below-threshold warning per strategy rule (minimum 50/100 to deploy)
        if verdict in ("MONITOR", "NO-RESET"):
            lines.append("*Below deployment threshold (need 50+). Scenarios shown for reference only.*\n")

        # Accumulation Scenarios table
        lines.append("**Accumulation Scenarios**")
        lines.append("| Level | Buy At | Hold% | Tier | Shares | Cost | New Avg | 6% Exit | Reachable? | Conflict |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for s in scenarios:
            source_label = s.get("source", "")
            reach_str = "YES" if s["reachable"] else "NO"
            conflict_str = s["conflict"] if s["conflict"] else "—"
            lines.append(
                f"| {source_label} | ${s['buy_at']:.2f} | {s['hold_rate']:.0f}% | {s['tier']} "
                f"| {s['shares']} | ${s['cost']:.2f} | ${s['new_avg']:.2f} "
                f"| ${s['exit_6pct']:.2f} | {reach_str} | {conflict_str} |"
            )
        lines.append("")

        p75 = m["high_20d_p75"]
        max_20d = m["high_20d"]
        lines.append(f"*Reachability: 6% exit vs 20d high p75 (${p75:.2f}). Absolute 20d max: ${max_20d:.2f} (reference only).*")
        lines.append(f"*Averages are cumulative — each row assumes all rows above it also fill.*")

        rc = ctx.get("reserve_committed", 0)
        pb = ctx.get("pool_budget", 300)
        rp = ctx.get("reserve_pool", 300)
        lines.append(f"*Reserve pool: ${rp} − ${rc:.2f} committed = ${pb:.2f} available.*\n")

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
        for name, (rating, detail) in components.items():
            label = name.replace("_", " ").title()
            lines.append(f"| {label} | {rating} ({detail}) |")
        lines.append(f"| **Overall** | **{risk.get('overall', '?')}** |")
        lines.append("")

    return "\n".join(lines)


def _format_summary_table(results):
    """Format stdout summary table."""
    lines = []
    lines.append("| Ticker | Score | Verdict | Stability | Swing | Exit? | Risk |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for r in results:
        if "skip" in r:
            lines.append(f"| {r['ticker']} | — | SKIPPED | — | — | — | {r['skip']} |")
            continue
        m = r.get("metrics", {})
        reach = "YES" if r.get("exit_reachable") else ("NO" if r.get("scenarios") is not None else "N/A")
        risk_overall = r.get("risk", {}).get("overall", "?")
        lines.append(
            f"| {r['ticker']} | {r['score']} | {r['verdict']} "
            f"| {r.get('stability', '?')} | {m.get('swing_20d', '?')}% "
            f"| {reach} | {risk_overall} |"
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
            entry["scenarios"] = r.get("scenarios")
            entry["sell_recs"] = r.get("sell_recs")
            # Context for downstream consumers
            ctx = r.get("level_context", {})
            entry["reserve_committed"] = ctx.get("reserve_committed", 0)
            entry["pool_budget"] = ctx.get("pool_budget", 0)
            entry["total_levels"] = ctx.get("total_levels", 0)
            entry["in_range_count"] = ctx.get("in_range_count", 0)
            entry["above_range_count"] = ctx.get("above_range_count", 0)
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
    cap = load_capital_config()
    reserve_pool = cap.get("reserve_pool", 300)

    candidates, skipped = _identify_underwater(portfolio, requested)
    if skipped:
        for t, reason in skipped.items():
            print(f"  {t}: skipped ({reason})")
    if not candidates:
        print("No qualifying underwater positions found (need ≥3 bullets used, not recovery).")
        return

    tickers = [c["ticker"] for c in candidates]

    # Data freshness warning (weekends/holidays)
    now = datetime.datetime.now()
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
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
        r = _process_ticker(c, hist, portfolio, reserve_pool=reserve_pool)
        results.append(r)

    # Sort by score descending (skipped at end)
    results.sort(key=lambda r: r.get("score", -1), reverse=True)

    # Summary table to stdout
    summary = _format_summary_table(results)
    print("\n" + summary)

    # Effective data date = most recent data_as_of across all results
    data_dates = [r.get("data_as_of") for r in results if r.get("data_as_of")]
    report_date = max(data_dates) if data_dates else datetime.date.today().isoformat()

    # Full markdown report
    md_parts = [f"# Range Reset Analysis — {report_date}\n"]
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
