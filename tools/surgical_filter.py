"""Surgical Filter — mechanical scoring, verification, and shortlist generation.

Reads screening_data.json (from surgical_screener.py), scores 20 candidates
on a deterministic 100-point scale, verifies arithmetic, and writes
candidate_shortlist.md for the LLM evaluator.

Usage:
    python3 tools/surgical_filter.py                  # default shortlist of 7
    python3 tools/surgical_filter.py --shortlist 25   # larger shortlist
"""
import argparse
import json
import sys
import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wick_offset_analyzer import classify_level, compute_pool_sizing

ROOT = Path(__file__).resolve().parent.parent
INPUT_PATH = ROOT / "screening_data.json"
OUTPUT_PATH = ROOT / "candidate_shortlist.md"
JSON_OUTPUT_PATH = ROOT / "candidate_shortlist.json"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Criterion 1: Tier point values
TIER_POINTS = {"Full": 6, "Std": 5, "Half": 2, "Skip": 0}

# Criterion 2: B1 Proximity thresholds
B1_IDEAL_PCT = 3.0
B1_POOR_PCT = 20.0

# Criterion 3: Zone Coverage
COVERAGE_GOOD_MIN = 8.0
COVERAGE_GOOD_MAX = 25.0

# Max points per criterion (must sum to 100)
MAX_BULLETS_TIER = 15
MAX_B1_PROXIMITY = 5
MAX_ZONE_COVERAGE = 15
MAX_RESERVE_DEPTH = 5
MAX_SWING = 10
MAX_SECTOR_DIVERSITY = 10
MAX_CYCLE_EFFICIENCY = 20
MAX_HOLD_QUALITY = 20

assert (MAX_BULLETS_TIER + MAX_B1_PROXIMITY + MAX_ZONE_COVERAGE +
        MAX_RESERVE_DEPTH + MAX_SWING + MAX_SECTOR_DIVERSITY +
        MAX_CYCLE_EFFICIENCY + MAX_HOLD_QUALITY) == 100, "Scoring constants must sum to 100"

# Criterion 4: Reserve thresholds
RESERVE_MIN_HOLD = 30.0
RESERVE_GAP_PENALTY = 30.0

# Criterion 5: Swing thresholds
SWING_FULL_POINTS = 20.0
SWING_FLOOR = 10.0
COMPRESSION_THRESHOLD = 0.65
COMPRESSION_PENALTY = 3

# Criterion 6: Sector thresholds
SECTOR_CONCENTRATION_LIMIT = 999  # Effectively disabled; scoring handles concentration

# Verification thresholds
SAMPLE_SIZE_MIN = 3
RECENCY_WINDOW_DAYS = 90
RECENCY_DROP_THRESHOLD = 20  # overall_hold - recent_hold > this → flag (imported by surgical_pre_verify.py)
GAP_FLAG_PCT = 20.0  # informational flag threshold (more sensitive than scoring penalty)

# Output
SHORTLIST_SIZE = 7

# Formal KPI Card v1.0 (Phase 5, Gap 1.3)
KPI_MONTHLY_SWING_MIN = 35.0
KPI_ACTIVE_LEVELS_MIN = 3
KPI_ANCHOR_LEVEL_MIN_HOLD = 50.0
KPI_DEAD_ZONE_MAX = 30.0
KPI_PRICE_MIN = 5.0
KPI_PRICE_MAX = 30.0

# KPI Gates 6-8: Cycle efficiency
KPI_MIN_CYCLES = 5
KPI_MIN_FILL_PCT = 85.0
KPI_STRONG_HOLD_MIN = 50.0
KPI_STRONG_LEVELS_MIN = 2


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _compute_gap_pct(active_bullets, reserve_bullets):
    """Compute gap percentage between lowest active and highest reserve buy.

    Returns float or None if either list is empty.
    """
    if not active_bullets or not reserve_bullets:
        return None
    lowest_active = min(b["buy_at"] for b in active_bullets)
    highest_reserve = max(b["buy_at"] for b in reserve_bullets)
    if lowest_active == 0:
        return None
    return ((lowest_active - highest_reserve) / lowest_active) * 100


def evaluate_kpi_gates(passer, wick_data):
    """Evaluate formal KPI gates. Returns (pass_all, gates_list).

    Each gate: {"name": str, "threshold": str, "actual": str, "passed": bool}
    Candidates that fail gates are flagged, not removed (backtest hard gate deferred).
    """
    gates = []
    bp = wick_data["bullet_plan"]
    active = bp.get("active", [])
    reserve = bp.get("reserve", [])

    # Gate 1: Monthly Swing >= 35%
    swing = passer["median_swing"]
    gates.append({
        "name": "Monthly Swing",
        "threshold": f">= {KPI_MONTHLY_SWING_MIN}%",
        "actual": f"{swing:.1f}%",
        "passed": swing >= KPI_MONTHLY_SWING_MIN,
    })

    # Gate 2: Active levels with hold >= 30%: count >= 3
    active_with_hold = [b for b in active if b.get("hold_rate", 0) >= 30]
    gates.append({
        "name": "Active Levels (hold >= 30%)",
        "threshold": f">= {KPI_ACTIVE_LEVELS_MIN}",
        "actual": str(len(active_with_hold)),
        "passed": len(active_with_hold) >= KPI_ACTIVE_LEVELS_MIN,
    })

    # Gate 3: Anchor level with hold >= 50%
    anchor_count = sum(1 for b in active if b.get("hold_rate", 0) >= KPI_ANCHOR_LEVEL_MIN_HOLD)
    gates.append({
        "name": "Anchor Level (hold >= 50%)",
        "threshold": ">= 1",
        "actual": str(anchor_count),
        "passed": anchor_count >= 1,
    })

    # Gate 4: Dead zone < 30%
    gap_pct = _compute_gap_pct(active, reserve)
    if gap_pct is not None:
        gates.append({
            "name": "Dead Zone",
            "threshold": f"< {KPI_DEAD_ZONE_MAX}%",
            "actual": f"{gap_pct:.1f}%",
            "passed": gap_pct < KPI_DEAD_ZONE_MAX,
        })
    else:
        gates.append({
            "name": "Dead Zone",
            "threshold": f"< {KPI_DEAD_ZONE_MAX}%",
            "actual": "N/A",
            "passed": True,  # no gap = no dead zone
        })

    # Gate 5: Price in $5-$30
    price = passer["price"]
    gates.append({
        "name": "Price Range",
        "threshold": f"${KPI_PRICE_MIN}-${KPI_PRICE_MAX}",
        "actual": f"${price:.2f}",
        "passed": KPI_PRICE_MIN <= price <= KPI_PRICE_MAX,
    })

    # Gate 6: Cycle data exists (>= 5 validated cycles)
    cycle_timing = passer.get("cycle_timing")
    cycle_count = cycle_timing["total_cycles"] if cycle_timing else 0
    gates.append({
        "name": "Cycle Data (>= 5 cycles)",
        "threshold": f">= {KPI_MIN_CYCLES}",
        "actual": str(cycle_count),
        "passed": cycle_count >= KPI_MIN_CYCLES,
    })

    # Gate 7: Consistency (>= 85% immediate fill)
    fill_pct = cycle_timing["immediate_fill_pct"] if cycle_timing else 0
    gates.append({
        "name": "Fill Consistency (>= 85%)",
        "threshold": f">= {KPI_MIN_FILL_PCT}%",
        "actual": f"{fill_pct:.0f}%",
        "passed": fill_pct >= KPI_MIN_FILL_PCT,
    })

    # Gate 8: Active levels with 50%+ hold rate (decayed) >= 2
    strong_levels = sum(1 for b in active
                        if b.get("decayed_hold_rate", b.get("hold_rate", 0)) >= KPI_STRONG_HOLD_MIN)
    gates.append({
        "name": f"Strong Levels (hold >= {KPI_STRONG_HOLD_MIN:.0f}%)",
        "threshold": f">= {KPI_STRONG_LEVELS_MIN}",
        "actual": str(strong_levels),
        "passed": strong_levels >= KPI_STRONG_LEVELS_MIN,
    })

    # Gate 9: Swing Compression (recent/median >= 0.65)
    compression_ratio = passer.get("compression_ratio", 1.0)
    gates.append({
        "name": "Swing Compression",
        "threshold": f">= {COMPRESSION_THRESHOLD}",
        "actual": f"{compression_ratio:.2f}",
        "passed": compression_ratio >= COMPRESSION_THRESHOLD,
    })

    pass_all = all(g["passed"] for g in gates)
    return pass_all, gates


# ---------------------------------------------------------------------------
# Scoring functions (7 criteria, 100 pts total)
# All read from wick_data["bullet_plan"] and wick_data["current_price"]
# ---------------------------------------------------------------------------

def score_bullets_tier(wick_data):
    """Criterion 1: Active Bullet Count & Tier Quality (0-20)."""
    active = wick_data["bullet_plan"]["active"]
    raw = sum(TIER_POINTS.get(b.get("raw_tier", b["tier"]), 0) for b in active)
    return min(MAX_BULLETS_TIER, raw)


def score_b1_proximity(wick_data):
    """Criterion 2: B1 Proximity (0-10).
    Returns 0 if no active bullets.
    """
    active = wick_data["bullet_plan"]["active"]
    if not active:
        return 0
    b1_buy = active[0]["buy_at"]
    current = wick_data["current_price"]
    if current == 0:
        return 0
    distance_pct = (current - b1_buy) / current * 100
    if distance_pct <= B1_IDEAL_PCT:
        return MAX_B1_PROXIMITY
    if distance_pct >= B1_POOR_PCT:
        return 0
    # Linear interpolation
    return round(MAX_B1_PROXIMITY * (B1_POOR_PCT - distance_pct) / (B1_POOR_PCT - B1_IDEAL_PCT))


def score_zone_coverage(wick_data):
    """Criterion 3: Active Zone Coverage (0-15).
    Returns 0 if no active bullets.
    """
    active = wick_data["bullet_plan"]["active"]
    if not active:
        return 0
    current = wick_data["current_price"]
    buy_prices = [b["buy_at"] for b in active]
    if current == 0:
        return 0
    spread_pct = (max(buy_prices) - min(buy_prices)) / current * 100

    if spread_pct < 3:
        spread_score = 3  # clustering
    elif spread_pct < COVERAGE_GOOD_MIN:
        spread_score = 8
    elif spread_pct <= COVERAGE_GOOD_MAX:
        spread_score = 15  # good spread
    else:
        spread_score = 10  # overspread

    count_bonus = min(5, len(active))
    return min(MAX_ZONE_COVERAGE, spread_score + count_bonus)


def score_reserve_depth(wick_data):
    """Criterion 4: Reserve Depth (0-10)."""
    reserves = wick_data["bullet_plan"]["reserve"]
    viable = [r for r in reserves if r["hold_rate"] >= RESERVE_MIN_HOLD]

    if not viable:
        return 0

    # Base score: 1st viable = 7, 2nd = 5, 3rd = 3 (max 15)
    pts_per = [7, 5, 3]
    base = sum(pts_per[i] for i in range(min(len(viable), 3)))

    # Dead zone penalty — only if active bullets exist
    penalty = 0
    active_bullets = wick_data["bullet_plan"]["active"]
    if active_bullets and viable:
        gap_pct = _compute_gap_pct(active_bullets, viable)
        if gap_pct is not None and gap_pct > RESERVE_GAP_PENALTY:
            penalty = -3

    return max(0, min(MAX_RESERVE_DEPTH, base + penalty))


def score_swing(passer):
    """Criterion 5: Monthly Swing (0-10).
    Reads from passer dict (screening passers list), NOT wick_data.
    Applies compression penalty if recent swing is significantly below median.
    """
    swing = passer["median_swing"]
    if swing >= SWING_FULL_POINTS:
        pts = MAX_SWING
    elif swing <= SWING_FLOOR:
        pts = 0
    else:
        pts = round(MAX_SWING * (swing - SWING_FLOOR) / (SWING_FULL_POINTS - SWING_FLOOR))
    # Compression penalty: recent swing collapsing vs historical median
    ratio = passer.get("compression_ratio", 1.0)
    if ratio < COMPRESSION_THRESHOLD:
        pts = max(0, pts - COMPRESSION_PENALTY)
    return pts


def score_hold_quality(wick_data):
    """Criterion 8: Hold Rate Quality (0-20).
    Rewards tickers with multiple reliable support levels (decayed hold rate).
    Uses decayed_hold_rate for recency weighting.
    """
    active = wick_data["bullet_plan"]["active"]

    # Count reliable levels (decayed HR >= 50%)
    reliable = sum(1 for b in active
                   if b.get("decayed_hold_rate", b.get("hold_rate", 0)) >= 50)

    # Floor level bonus (decayed HR >= 60%)
    has_floor = any(b.get("decayed_hold_rate", b.get("hold_rate", 0)) >= 60
                    for b in active)

    # Scoring: 0-4 reliable levels -> 0-12 pts, floor bonus +8
    if reliable >= 4:
        pts = 12
    elif reliable >= 3:
        pts = 9
    elif reliable >= 2:
        pts = 6
    elif reliable >= 1:
        pts = 3
    else:
        pts = 0

    if has_floor:
        pts += 8

    return min(pts, MAX_HOLD_QUALITY)


def score_cycle_efficiency(cycle_timing):
    """Criterion 7: Cycle Efficiency (0-20). Delegates to shared_utils."""
    from shared_utils import score_cycle_efficiency as _shared_score
    return _shared_score(cycle_timing, max_points=MAX_CYCLE_EFFICIENCY)


def score_sector_diversity(ticker, sector, portfolio_ctx):
    """Criterion 6: Sector Diversity (0-10).
    Diminishing-returns curve: mild penalty for early concentration,
    fades as portfolio scales. Never blocks a strong candidate.
    """
    if not sector or sector == "Unknown":
        return MAX_SECTOR_DIVERSITY
    existing = portfolio_ctx.get("sectors", {}).get(sector, [])
    count = len(existing)
    if count == 0:
        return MAX_SECTOR_DIVERSITY        # 10 — new sector, full points
    elif count <= 2:
        return MAX_SECTOR_DIVERSITY - 2    # 8 — 2nd-3rd ticker, mild
    elif count <= 5:
        return MAX_SECTOR_DIVERSITY - 4    # 6 — 4th-6th, moderate
    elif count <= 15:
        return MAX_SECTOR_DIVERSITY - 6    # 4 — 7th-16th, notable
    else:
        return MAX_SECTOR_DIVERSITY - 8    # 2 — 17th+, heavy but not zero


def score_daily_range(passer):
    """Daily Range Viability Score (0-90, sector added by caller to reach 0-100).
    Parallel to support-level scoring for tickers with intraday oscillation.
    """
    dr = passer.get("median_daily_range", 0)
    days_3 = passer.get("days_above_3pct", 0)
    recovery = passer.get("dip_recovery_ratio", 0)
    ltc = passer.get("median_low_to_close", 0)
    swing = passer.get("median_swing", 0)

    # Criterion 1: Range Magnitude (0-25)
    if dr >= 6:
        mag = 25
    elif dr >= 4:
        mag = 20
    elif dr >= 3:
        mag = 15
    elif dr >= 2:
        mag = 10
    else:
        mag = 0

    # Criterion 2: Range Consistency (0-25)
    if days_3 >= 90:
        con = 25
    elif days_3 >= 80:
        con = 20
    elif days_3 >= 70:
        con = 15
    elif days_3 >= 60:
        con = 10
    else:
        con = 0

    # Criterion 3: Dip-Recovery Pattern (0-25)
    if recovery >= 70:
        rec = 25
    elif recovery >= 55:
        rec = 18
    elif recovery >= 40:
        rec = 12
    elif recovery >= 25:
        rec = 6
    else:
        rec = 0
    if ltc >= 3:
        rec = min(25, rec + 5)

    # Criterion 4: Swing (0-15)
    if swing >= 20:
        swg = 15
    elif swing >= 15:
        swg = 10
    elif swing >= 10:
        swg = 5
    else:
        swg = 0

    return mag + con + rec + swg  # 0-90, sector added by caller


# ---------------------------------------------------------------------------
# Mechanical Verification
# ---------------------------------------------------------------------------

def verify_candidate(ticker, wick_data, capital_config):
    """Returns verification dict with tier, bullet math, pool, sample, recency checks."""
    issues = []
    sample_size_flags = []
    recency_flags = []
    recency_detail = []

    bp = wick_data["bullet_plan"]
    all_bullets = bp["active"] + bp["reserve"]

    # Build a lookup from support_price to level data for event-level checks.
    # Use 2-decimal rounding to match bullet_plan precision (2 dec) vs levels (4 dec).
    level_lookup = {}
    for lvl in wick_data["levels"]:
        level_lookup[round(lvl["support_price"], 2)] = lvl

    # 1. Tier classification check — uses canonical classify_level() from wick_offset_analyzer
    tier_check = True
    for b in all_bullets:
        lvl = level_lookup.get(round(b["support_price"], 2))
        if not lvl:
            continue
        _, expected_tier = classify_level(
            lvl["hold_rate"], lvl["gap_pct"],
            wick_data.get("active_radius", 15.0),
            lvl["total_approaches"])
        # Compare against raw_tier (original classify_level result), not "tier"
        # which is now effective_tier and may differ due to recency demotion
        compare_tier = b.get("raw_tier", b["tier"])
        if compare_tier != expected_tier:
            tier_check = False
            issues.append(f"{ticker} ${b['support_price']}: tier {compare_tier} vs expected {expected_tier}")

    # 2. Bullet math check — re-derive expected sizing via compute_pool_sizing, 30% tolerance
    bullet_math_check = True
    active_levels_for_sizing = [{"recommended_buy": b["buy_at"],
                                  "effective_tier": b["tier"],
                                  "hold_rate": b["hold_rate"]}
                                 for b in bp["active"]]
    reserve_levels_for_sizing = [{"recommended_buy": b["buy_at"],
                                   "effective_tier": b["tier"],
                                   "hold_rate": b["hold_rate"]}
                                  for b in bp["reserve"]]
    expected_active = compute_pool_sizing(active_levels_for_sizing,
                                          capital_config.get("active_pool", 300), "active")
    expected_reserve = compute_pool_sizing(reserve_levels_for_sizing,
                                           capital_config.get("reserve_pool", 300), "reserve")
    for b, exp in list(zip(bp["active"], expected_active)) + list(zip(bp["reserve"], expected_reserve)):
        actual_cost = b["shares"] * b["buy_at"]
        expected_cost = exp["cost"]
        if expected_cost > 0 and abs(actual_cost - expected_cost) / expected_cost > 0.30:
            bullet_math_check = False
            issues.append(f"{ticker} ${b['buy_at']}: cost ${actual_cost:.2f} vs expected ${expected_cost:.2f}")

    # 3. Pool deployment check (5% tolerance)
    active_pool = capital_config["active_pool"]
    reserve_pool = capital_config["reserve_pool"]
    pool_check = (
        bp["active_total_cost"] <= active_pool * 1.05 and
        bp["reserve_total_cost"] <= reserve_pool * 1.05
    )
    if not pool_check:
        if bp["active_total_cost"] > active_pool * 1.05:
            issues.append(f"{ticker}: active deployment ${bp['active_total_cost']:.0f} > ${active_pool} pool")
        if bp["reserve_total_cost"] > reserve_pool * 1.05:
            issues.append(f"{ticker}: reserve deployment ${bp['reserve_total_cost']:.0f} > ${reserve_pool} pool")

    # 4. Sample size check
    for b in bp["active"]:
        if b["approaches"] < SAMPLE_SIZE_MIN:
            sample_size_flags.append(f"${b['support_price']}: only {b['approaches']} approaches")

    # 5. Recency analysis — compare last-90-day hold rate vs overall
    last_date_str = wick_data.get("last_date", "")
    try:
        last_date = datetime.datetime.strptime(last_date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        last_date = datetime.datetime.now()
    cutoff = last_date - datetime.timedelta(days=RECENCY_WINDOW_DAYS)

    for b in all_bullets:
        lvl = level_lookup.get(round(b["support_price"], 2))
        if not lvl or not lvl.get("events"):
            continue

        overall_hold = lvl["hold_rate"]
        recent_events = []
        for e in lvl["events"]:
            try:
                edate = datetime.datetime.strptime(e["date"], "%Y-%m-%d")
                if edate >= cutoff:
                    recent_events.append(e)
            except (ValueError, TypeError):
                continue

        if recent_events:
            recent_held = sum(1 for e in recent_events if e["held"])
            recent_hold_pct = round(recent_held / len(recent_events) * 100, 1)
        else:
            recent_hold_pct = None

        # Classify trend
        if recent_hold_pct is None:
            trend = "No recent data"
        elif recent_hold_pct > overall_hold + 5:
            trend = "Improving"
        elif recent_hold_pct < overall_hold - 5:
            trend = "Deteriorating"
        else:
            trend = "Stable"

        recency_detail.append({
            "support_price": b["support_price"],
            "overall_hold_pct": overall_hold,
            "recent_hold_pct": recent_hold_pct,
            "recent_events": len(recent_events),
            "trend": trend,
        })

        if recent_hold_pct is not None and overall_hold - recent_hold_pct > RECENCY_DROP_THRESHOLD:
            recency_flags.append(
                f"${b['support_price']}: recent hold {recent_hold_pct:.0f}% vs overall {overall_hold:.0f}%"
            )

    return {
        "tier_check": tier_check,
        "bullet_math_check": bullet_math_check,
        "pool_check": pool_check,
        "sample_size_flags": sample_size_flags,
        "recency_flags": recency_flags,
        "recency_detail": recency_detail,
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# Stress Metrics
# ---------------------------------------------------------------------------

def compute_stress_metrics(ticker, wick_data, passer, portfolio_ctx, capital_config):
    """Returns dict with pre-computed critic metrics."""
    bp = wick_data["bullet_plan"]
    active = bp["active"]
    reserve = bp["reserve"]

    # Sample size
    if active:
        min_active_approaches = min(b["approaches"] for b in active)
        all_active_above_3 = all(b["approaches"] >= 3 for b in active)
    else:
        min_active_approaches = 0
        all_active_above_3 = False

    # B1 distance
    if active:
        b1_buy = active[0]["buy_at"]
        current = wick_data["current_price"]
        b1_distance_pct = round((current - b1_buy) / current * 100, 1) if current else 0
    else:
        b1_distance_pct = None

    # Sector concentration
    sector = passer.get("sector", "Unknown")
    existing_in_sector = portfolio_ctx.get("sectors", {}).get(sector, [])
    sector_count_after = len(existing_in_sector) + 1
    sector_exceeds_limit = sector_count_after > SECTOR_CONCENTRATION_LIMIT

    # Budget — use actual pool sizes from capital_config
    active_total = bp["active_total_cost"]
    reserve_total = bp["reserve_total_cost"]
    all_in_cost = active_total + reserve_total
    cap_total = capital_config.get("active_pool", 300) + capital_config.get("reserve_pool", 300)
    budget_feasible = all_in_cost <= cap_total * 1.05

    # Reserve quality
    reserve_count_40pct = sum(1 for r in reserve if r["hold_rate"] >= 40)

    # Active-reserve gap
    active_reserve_gap_pct = _compute_gap_pct(active, reserve)
    if active_reserve_gap_pct is not None:
        active_reserve_gap_pct = round(active_reserve_gap_pct, 1)

    return {
        "min_active_approaches": min_active_approaches,
        "all_active_above_3": all_active_above_3,
        "b1_distance_pct": b1_distance_pct,
        "sector_count_after": sector_count_after,
        "sector_exceeds_limit": sector_exceeds_limit,
        "active_total_cost": active_total,
        "reserve_total_cost": reserve_total,
        "all_in_cost": all_in_cost,
        "cap_total": cap_total,
        "budget_feasible": budget_feasible,
        "reserve_count_40pct": reserve_count_40pct,
        "active_reserve_gap_pct": active_reserve_gap_pct,
    }


# ---------------------------------------------------------------------------
# Qualitative Question Generator
# ---------------------------------------------------------------------------

def generate_qualitative_questions(ticker, passer, flags, stress_metrics, portfolio_ctx):
    """Generate 2-4 qualitative questions per candidate based on detected flags."""
    questions = []

    if stress_metrics.get("sector_exceeds_limit"):
        sector = passer.get("sector", "Unknown")
        existing = portfolio_ctx.get("sectors", {}).get(sector, [])
        questions.append(
            f"Does {ticker}'s business niche genuinely differentiate it from "
            f"existing {sector} holdings ({', '.join(existing)})?"
        )

    if any("deteriorat" in f.lower() for f in flags):
        questions.append(
            "Is the recent hold-rate decline a temporary dip or structural "
            "support breakdown? Check if the sector/market regime changed."
        )

    if any("sample size" in f.lower() for f in flags):
        questions.append(
            "Are the low-sample-size levels (<3 approaches) in critical "
            "positions (B1-B2)? If so, is the risk of false signal acceptable?"
        )

    gap = stress_metrics.get("active_reserve_gap_pct")
    if gap and gap > GAP_FLAG_PCT:
        questions.append(
            f"The {gap:.0f}% gap between active bottom and reserve top creates "
            f"a dead zone. Can reserves realistically rescue the position?"
        )

    b1_dist = stress_metrics.get("b1_distance_pct")
    if b1_dist and b1_dist > 10:
        questions.append(
            f"B1 requires a {b1_dist:.1f}% pullback. Is the stock near resistance "
            f"or mid-cycle? Entry timing affects capital efficiency."
        )

    if not questions:
        questions.append(
            "Are the support levels clean bounce patterns or choppy/degrading? "
            "Evaluate pattern quality from the approach history."
        )

    return questions[:4]


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

def filter_and_score(data):
    """Score top-20 candidates, verify, compute stress metrics.

    Returns: (shortlist, all_scored) where:
      shortlist = top SHORTLIST_SIZE results
      all_scored = all results
    """
    results = []
    portfolio_ctx = data.get("portfolio_context", {})
    capital_config = data.get("capital_config", {})
    cycle_timings = data.get("cycle_timings", {})

    for passer in data["passers"][:20]:
        ticker = passer["ticker"]
        cycle_timing = cycle_timings.get(ticker)
        # Attach cycle_timing to passer for KPI gates
        passer["cycle_timing"] = cycle_timing

        if ticker not in data.get("wick_analyses", {}):
            sector_score = score_sector_diversity(
                ticker, passer.get("sector", "Unknown"), portfolio_ctx)
            swing_score = score_swing(passer)
            cycle_score = score_cycle_efficiency(cycle_timing)
            # Support-dependent criteria (bullets, b1, coverage, reserve, hold) = 0
            support_total = sector_score + swing_score + cycle_score  # max 40
            # Daily range score can rescue wick-failed tickers
            dr_base = score_daily_range(passer)
            daily_range_score = dr_base + sector_score
            strategy_type = "daily_range" if daily_range_score > support_total else "support"
            effective_score = max(support_total, daily_range_score)
            results.append({
                "ticker": ticker,
                "passer": passer,
                "total_score": support_total,
                "daily_range_score": daily_range_score,
                "strategy_type": strategy_type,
                "effective_score": effective_score,
                "scores": {"sector_diversity": sector_score, "swing": swing_score, "cycle_efficiency": cycle_score},
                "wick_failed": True,
                "verification": None,
                "stress_metrics": None,
                "flags": ["Wick analysis failed"] if strategy_type == "daily_range" else ["Wick analysis failed — capped at 40"],
                "kpi_pass_all": False,
                "kpi_gates": [],
            })
            continue

        wick = data["wick_analyses"][ticker]
        scores = {
            "bullets_tier": score_bullets_tier(wick),
            "b1_proximity": score_b1_proximity(wick),
            "zone_coverage": score_zone_coverage(wick),
            "reserve_depth": score_reserve_depth(wick),
            "swing": score_swing(passer),
            "sector_diversity": score_sector_diversity(
                ticker, passer.get("sector", "Unknown"), portfolio_ctx),
            "cycle_efficiency": score_cycle_efficiency(cycle_timing),
            "hold_quality": score_hold_quality(wick),
        }
        total = sum(scores.values())

        # Parallel daily range score (reuse sector score from support scoring)
        dr_base = score_daily_range(passer)
        daily_range_score = dr_base + scores["sector_diversity"]
        strategy_type = "daily_range" if daily_range_score > total else "support"
        effective_score = max(total, daily_range_score)

        verification = verify_candidate(ticker, wick, capital_config)
        stress = compute_stress_metrics(ticker, wick, passer, portfolio_ctx, capital_config)

        # Build flags
        # NOTE: Flag string formats are parsed by surgical_pre_verify.py _is_mechanical_flag().
        # If you change the wording/format below, update the regex patterns there too.
        flags = list(verification["issues"])
        if verification["sample_size_flags"]:
            flags.append(f"Sample size weak: {len(verification['sample_size_flags'])} "
                         f"levels <3 approaches")
        if verification["recency_flags"]:
            flags.append(f"Recency deterioration: {len(verification['recency_flags'])} levels")
        if stress["sector_exceeds_limit"]:
            flags.append(f"Sector concentration: {stress['sector_count_after']}x "
                         f"{passer.get('sector', 'Unknown')}")
        if not stress["budget_feasible"]:
            flags.append(f"Budget exceeds ${stress['cap_total']}: ${stress['all_in_cost']:.0f}")
        if stress.get("active_reserve_gap_pct") and stress["active_reserve_gap_pct"] > GAP_FLAG_PCT:
            flags.append(f"Active-reserve gap: {stress['active_reserve_gap_pct']:.0f}%")

        # KPI Card evaluation
        kpi_pass_all, kpi_gates = evaluate_kpi_gates(passer, wick)
        if not kpi_pass_all:
            failed_names = [g["name"] for g in kpi_gates if not g["passed"]]
            flags.append(f"KPI gates failed: {', '.join(failed_names)}")

        results.append({
            "ticker": ticker,
            "passer": passer,
            "total_score": total,
            "daily_range_score": daily_range_score,
            "strategy_type": strategy_type,
            "effective_score": effective_score,
            "scores": scores,
            "wick_failed": False,
            "verification": verification,
            "stress_metrics": stress,
            "flags": flags,
            "kpi_pass_all": kpi_pass_all,
            "kpi_gates": kpi_gates,
        })

    results.sort(key=lambda r: r["effective_score"], reverse=True)
    return results[:SHORTLIST_SIZE], results


# ---------------------------------------------------------------------------
# Output Rendering
# ---------------------------------------------------------------------------

def _fmt_dollar(val):
    if val is None:
        return "N/A"
    return f"${val:.2f}"


def build_shortlist_md(shortlist, all_scored, portfolio_ctx, wick_analyses):
    """Render candidate_shortlist.md with full bullet plan tables from wick data."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = []

    lines.append("# Surgical Candidate Shortlist")
    lines.append(f"*Generated: {now} | Scored by surgical_filter.py*")
    lines.append("")

    # Scoring Summary — Top 7
    lines.append(f"## Scoring Summary — Top {len(shortlist)}")
    lines.append("| # | Ticker | Strategy | Sector | Price | Swing% | Bullets (0-15) | B1 (0-5) "
                 "| Coverage (0-15) | Reserve (0-5) | Swing (0-10) | Sector (0-10) "
                 "| Cycle (0-20) | HoldQ (0-20) | DR Score | Effective | Flags |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- "
                 "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for i, r in enumerate(shortlist, 1):
        p = r["passer"]
        s = r["scores"]
        flag_str = "; ".join(r["flags"]) if r["flags"] else "None"
        st = r.get("strategy_type", "support").upper()[:3]  # SUP or DAI
        dr = r.get("daily_range_score", "—")
        eff = r.get("effective_score", r["total_score"])
        if r["wick_failed"]:
            lines.append(
                f"| {i} | {r['ticker']} | {st} | {p.get('sector', '?')} | ${p['price']:.2f} "
                f"| {p['median_swing']}% | — | — | — | — | — "
                f"| {s.get('sector_diversity', '—')} | — | — | {dr} | {eff} | {flag_str} |"
            )
        else:
            lines.append(
                f"| {i} | {r['ticker']} | {st} | {p.get('sector', '?')} | ${p['price']:.2f} "
                f"| {p['median_swing']}% | {s['bullets_tier']} | {s['b1_proximity']} "
                f"| {s['zone_coverage']} | {s['reserve_depth']} | {s['swing']} "
                f"| {s['sector_diversity']} | {s['cycle_efficiency']} "
                f"| {s['hold_quality']} | {dr} | {eff} | {flag_str} |"
            )
    lines.append("")

    # All 20 Scores
    lines.append("## All 20 Scores")
    lines.append("| # | Ticker | Total | Wick OK |")
    lines.append("| :--- | :--- | :--- | :--- |")
    for i, r in enumerate(all_scored, 1):
        wick_ok = "No" if r["wick_failed"] else "Yes"
        lines.append(f"| {i} | {r['ticker']} | {r['total_score']} | {wick_ok} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Per-candidate detail for shortlist
    for r in shortlist:
        if r["wick_failed"]:
            lines.append(f"## Candidate Detail: {r['ticker']}")
            lines.append("*Wick analysis failed — limited data available.*")
            lines.append("")
            continue

        ticker = r["ticker"]
        p = r["passer"]
        s = r["scores"]
        v = r["verification"]
        sm = r["stress_metrics"]
        wick = wick_analyses.get(ticker, {})
        bp = wick.get("bullet_plan", {})

        lines.append(f"## Candidate Detail: {ticker}")
        lines.append("")

        # Quick Facts
        lines.append("### Quick Facts")
        lines.append("| Field | Value |")
        lines.append("| :--- | :--- |")
        lines.append(f"| Sector | {p.get('sector', 'Unknown')} |")
        lines.append(f"| Price | ${p['price']:.2f} |")
        lines.append(f"| Median Swing | {p['median_swing']}% |")
        lines.append(f"| Consistency | {p['consistency']}% |")
        if wick.get("active_radius"):
            lines.append(f"| Active Radius | {wick['active_radius']:.1f}% |")
        lines.append("")

        # Score Breakdown
        lines.append("### Score Breakdown")
        lines.append("| Criterion | Score | Max | Detail |")
        lines.append("| :--- | :--- | :--- | :--- |")
        lines.append(f"| Bullets & Tier Quality | {s['bullets_tier']} | {MAX_BULLETS_TIER} | Sum of tier points for active bullets |")
        lines.append(f"| B1 Proximity | {s['b1_proximity']} | {MAX_B1_PROXIMITY} | Distance from current price to first fill |")
        lines.append(f"| Zone Coverage | {s['zone_coverage']} | {MAX_ZONE_COVERAGE} | Spread of active bullets across price range |")
        lines.append(f"| Reserve Depth | {s['reserve_depth']} | {MAX_RESERVE_DEPTH} | Viable reserve levels with 30%+ hold |")
        lines.append(f"| Swing Magnitude | {s['swing']} | {MAX_SWING} | Monthly swing opportunity |")
        lines.append(f"| Sector Diversity | {s['sector_diversity']} | {MAX_SECTOR_DIVERSITY} | Diminishing returns by sector count |")
        lines.append(f"| Cycle Efficiency | {s['cycle_efficiency']} | {MAX_CYCLE_EFFICIENCY} | Cycle speed, fill rate, consistency |")
        lines.append(f"| Hold Rate Quality | {s['hold_quality']} | {MAX_HOLD_QUALITY} | Reliable levels + floor bonus |")
        lines.append(f"| **Total** | **{r['total_score']}** | **100** | |")
        lines.append("")

        # Bullet Plan — full table from wick data
        lines.append("### Bullet Plan")
        active_bullets = bp.get("active", [])
        reserve_bullets = bp.get("reserve", [])
        if active_bullets or reserve_bullets:
            lines.append("| # | Zone | Support | Buy At | Hold% | Tier | Approaches | Shares | Cost |")
            lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            bullet_num = 1
            for b in active_bullets:
                lines.append(
                    f"| {bullet_num} | Active | {_fmt_dollar(b['support_price'])} "
                    f"| {_fmt_dollar(b['buy_at'])} | {b['hold_rate']:.0f}% | {b['tier']} "
                    f"| {b['approaches']} | {b['shares']} | ${b['cost']:.2f} |"
                )
                bullet_num += 1
            for b in reserve_bullets:
                lines.append(
                    f"| {bullet_num} | Reserve | {_fmt_dollar(b['support_price'])} "
                    f"| {_fmt_dollar(b['buy_at'])} | {b['hold_rate']:.0f}% | {b['tier']} "
                    f"| {b['approaches']} | {b['shares']} | ${b['cost']:.2f} |"
                )
                bullet_num += 1
            lines.append("")
            lines.append(f"- **Active total:** ${bp.get('active_total_cost', 0):.2f}")
            lines.append(f"- **Reserve total:** ${bp.get('reserve_total_cost', 0):.2f}")
            lines.append(f"- **All-in cost:** ${bp.get('active_total_cost', 0) + bp.get('reserve_total_cost', 0):.2f}")
        else:
            lines.append("*No qualifying bullet levels.*")
        lines.append("")

        # Recency Analysis
        if v and v["recency_detail"]:
            lines.append("### Recency Analysis")
            lines.append("| Level | Overall Hold% | Last 90d Hold% | Recent Events | Trend |")
            lines.append("| :--- | :--- | :--- | :--- | :--- |")
            for rd in v["recency_detail"]:
                recent_str = f"{rd['recent_hold_pct']:.0f}%" if rd["recent_hold_pct"] is not None else "—"
                lines.append(
                    f"| {_fmt_dollar(rd['support_price'])} | {rd['overall_hold_pct']:.0f}% "
                    f"| {recent_str} | {rd['recent_events']} | {rd['trend']} |"
                )
            lines.append("")

        # Verification
        if v:
            lines.append("### Verification")
            lines.append(f"- Tier check: {'PASS' if v['tier_check'] else 'FAIL'}")
            lines.append(f"- Bullet math: {'PASS' if v['bullet_math_check'] else 'FAIL'}")
            lines.append(f"- Pool deployment: {'PASS' if v['pool_check'] else 'FAIL'}")
            if v["sample_size_flags"]:
                for f in v["sample_size_flags"]:
                    lines.append(f"  - Sample size: {f}")
            lines.append("")

        # Stress Metrics
        if sm:
            lines.append("### Stress Metrics")
            lines.append("| Metric | Value | Assessment |")
            lines.append("| :--- | :--- | :--- |")
            lines.append(f"| Min active approaches | {sm['min_active_approaches']} "
                         f"| {'Strong' if sm['all_active_above_3'] else 'Weak — some <3'} |")
            if sm["b1_distance_pct"] is not None:
                b1_assess = "Ideal" if sm["b1_distance_pct"] <= 5 else (
                    "OK" if sm["b1_distance_pct"] <= 10 else "Far")
                lines.append(f"| B1 distance | {sm['b1_distance_pct']:.1f}% | {b1_assess} |")
            lines.append(f"| Sector after onboard | {sm['sector_count_after']}x "
                         f"| {'Over limit' if sm['sector_exceeds_limit'] else 'OK'} |")
            lines.append(f"| Budget feasible | ${sm['all_in_cost']:.0f} / ${sm.get('cap_total', 600)} "
                         f"| {'Yes' if sm['budget_feasible'] else 'No — exceeds'} |")
            lines.append(f"| Reserve 40%+ hold | {sm['reserve_count_40pct']} levels "
                         f"| {'Good' if sm['reserve_count_40pct'] >= 1 else 'Weak'} |")
            if sm["active_reserve_gap_pct"] is not None:
                gap_assess = "OK" if sm["active_reserve_gap_pct"] <= GAP_FLAG_PCT else (
                    "Caution" if sm["active_reserve_gap_pct"] <= RESERVE_GAP_PENALTY else "Dead zone")
                lines.append(f"| Active-reserve gap | {sm['active_reserve_gap_pct']:.0f}% | {gap_assess} |")
            lines.append("")

        # KPI Card
        kpi_gates = r.get("kpi_gates", [])
        if kpi_gates:
            kpi_pass = r.get("kpi_pass_all", False)
            lines.append(f"### KPI Card {'— PASS' if kpi_pass else '— FAIL'}")
            lines.append("| KPI | Threshold | Actual | Status |")
            lines.append("| :--- | :--- | :--- | :--- |")
            for g in kpi_gates:
                status = "PASS" if g["passed"] else "FAIL"
                lines.append(f"| {g['name']} | {g['threshold']} | {g['actual']} | {status} |")
            lines.append("")

        # Flags
        if r["flags"]:
            lines.append("### Flags")
            for f in r["flags"]:
                lines.append(f"- {f}")
            lines.append("")

        # Qualitative Questions
        questions = generate_qualitative_questions(
            ticker, p, r["flags"], sm, portfolio_ctx)
        if questions:
            lines.append("### For Evaluator: Qualitative Questions")
            for qi, q in enumerate(questions, 1):
                lines.append(f"{qi}. {q}")
            lines.append("")

        lines.append("---")
        lines.append("")

    # Portfolio Context
    lines.append("## Portfolio Context")
    lines.append("")
    lines.append("### Current Sectors")
    sectors = portfolio_ctx.get("sectors", {})
    if sectors:
        lines.append("| Sector | Tickers | Count |")
        lines.append("| :--- | :--- | :--- |")
        for sector, tickers in sorted(sectors.items()):
            lines.append(f"| {sector} | {', '.join(sorted(tickers))} | {len(tickers)} |")
    else:
        lines.append("*No sector data.*")
    lines.append("")

    lines.append("### Concentration Thresholds")
    at_limit = [s for s, t in sectors.items() if len(t) >= SECTOR_CONCENTRATION_LIMIT]
    if at_limit:
        lines.append(f"- At/over limit ({SECTOR_CONCENTRATION_LIMIT}+): {', '.join(at_limit)}")
    else:
        lines.append("- No sectors at concentration limit")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main(shortlist_size=None):
    if not INPUT_PATH.exists():
        print(f"*Error: {INPUT_PATH.name} not found — run surgical_screener.py first*")
        sys.exit(1)

    try:
        data = json.loads(INPUT_PATH.read_text())
    except json.JSONDecodeError as e:
        print(f"*Error parsing {INPUT_PATH.name}: {e}*")
        sys.exit(1)

    # Allow runtime override of shortlist size
    global SHORTLIST_SIZE
    if shortlist_size is not None:
        SHORTLIST_SIZE = shortlist_size

    print(f"Loaded {INPUT_PATH.name}: {data.get('total_passers', '?')} passers, "
          f"{len(data.get('wick_analyses', {}))} wick analyses "
          f"(shortlist: {SHORTLIST_SIZE})")

    shortlist, all_scored = filter_and_score(data)

    # Use the version with full bullet tables
    wick_analyses = data.get("wick_analyses", {})
    portfolio_ctx = data.get("portfolio_context", {})
    report = build_shortlist_md(shortlist, all_scored, portfolio_ctx, wick_analyses)
    OUTPUT_PATH.write_text(report + "\n")

    # Write structured JSON for programmatic access (pre-verifier)
    json_output = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "shortlist": [
            {
                "ticker": r["ticker"],
                "total_score": r["total_score"],
                "scores": r["scores"],
                "wick_failed": r["wick_failed"],
                "flags": r["flags"],
                "verification": r["verification"],
                "stress_metrics": r["stress_metrics"],
                "passer": r["passer"],
                "kpi_pass_all": r.get("kpi_pass_all", False),
                "kpi_gates": r.get("kpi_gates", []),
            }
            for r in shortlist
        ],
        "all_scored": [
            {"ticker": r["ticker"], "total_score": r["total_score"], "wick_failed": r["wick_failed"]}
            for r in all_scored
        ],
    }
    try:
        JSON_OUTPUT_PATH.write_text(json.dumps(json_output, indent=2, default=float) + "\n")
        print(f"Wrote {JSON_OUTPUT_PATH.name}")
    except (OSError, IOError) as e:
        print(f"*Warning: failed to write {JSON_OUTPUT_PATH.name}: {e} — markdown output still valid*")

    print(f"\nWrote {OUTPUT_PATH.name}")
    print(f"  Top {len(shortlist)}: {', '.join(r['ticker'] + '(' + str(r['total_score']) + ')' for r in shortlist)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Surgical Filter — score and shortlist candidates")
    parser.add_argument("--shortlist", type=int, default=None,
                        help=f"Shortlist size (default: {SHORTLIST_SIZE})")
    args = parser.parse_args()
    main(shortlist_size=args.shortlist)
