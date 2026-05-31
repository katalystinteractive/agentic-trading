"""Extract deterministic trend records and recent edge scores."""
from __future__ import annotations

from typing import Any

from shared_utils import compute_support_level_score
from trend_contracts import RECENT_EDGE_WEIGHTS


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _score_return_pct(value: Any) -> float | None:
    pct = _as_float(value)
    if pct is None:
        return None
    return _clamp((pct + 20.0) / 40.0 * 100.0)


def _score_delta_pct(value: Any) -> float | None:
    # Locked formula (spec §178): 50 + clamp(delta, -25, 25) * 2  -> -25=0, 0=50, +25=100.
    pct = _as_float(value)
    if pct is None:
        return None
    return _clamp(50.0 + max(-25.0, min(25.0, pct)) * 2.0)


def _score_liquidity_freshness(metrics: dict[str, Any]) -> tuple[float | None, Any]:
    # Locked penalty model (spec §180): start 100, subtract 30 partial-provider,
    # 30 stale-cache, 20 below-target avg vol, 20 missing ATR; clamp 0..100.
    avg_volume = _as_float(metrics.get("avg_volume"))
    atr = _as_float(metrics.get("atr"))
    freshness = metrics.get("freshness")
    if avg_volume is None and atr is None and freshness is None:
        return None, None
    freshness = str(freshness or "unknown")
    score = 100.0
    if metrics.get("provider_partial"):
        score -= 30.0
    if freshness in ("stale", "weekly_context", "unknown"):
        score -= 30.0
    if avg_volume is None or avg_volume < 500_000.0:
        score -= 20.0
    if atr is None:
        score -= 20.0
    return _clamp(score), {
        "avg_volume": avg_volume,
        "atr": atr,
        "freshness": freshness,
        "provider_partial": bool(metrics.get("provider_partial")),
    }


def _input(
    component: str,
    source_field: str,
    raw_value: Any,
    normalized_value: float | None,
    weight: float,
) -> dict[str, Any]:
    return {
        "component": component,
        "source_field": source_field,
        "raw_value": raw_value,
        "normalized_value": None if normalized_value is None else round(normalized_value, 2),
        "weight": weight,
        "missing": normalized_value is None,
    }


def compute_recent_edge_score(record: dict[str, Any]) -> tuple[float | None, list[dict[str, Any]]]:
    """Compute the researched 0..100 recent-edge score for one snapshot record."""
    metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
    support_level = metrics.get("support_level")
    support_score = None
    support_raw: Any = support_level
    if isinstance(support_level, dict) and support_level:
        support = compute_support_level_score(
            support_level,
            current_price=metrics.get("price"),
        )
        support_score = _as_float(support.get("support_score"))
        support_raw = support

    return_field = "simulation_validation_return_pct"
    return_raw = metrics.get(return_field)
    if return_raw is None:
        return_field = "post_signal_return_pct"
        return_raw = metrics.get(return_field)
    return_score = _score_return_pct(return_raw)

    delta_field = "watchlist_fitness_delta_pct"
    delta_raw = metrics.get(delta_field)
    if delta_raw is None:
        delta_field = "candidate_fitness_delta_pct"
        delta_raw = metrics.get(delta_field)
    delta_score = _score_delta_pct(delta_raw)

    liquidity_score, liquidity_raw = _score_liquidity_freshness(metrics)

    inputs = [
        _input("support", "support_level", support_raw, support_score, RECENT_EDGE_WEIGHTS["support"]),
        _input(
            "post_signal_or_simulation",
            return_field,
            return_raw,
            return_score,
            RECENT_EDGE_WEIGHTS["post_signal_or_simulation"],
        ),
        _input(
            "watchlist_or_candidate_delta",
            delta_field,
            delta_raw,
            delta_score,
            RECENT_EDGE_WEIGHTS["watchlist_or_candidate_delta"],
        ),
        _input(
            "liquidity_freshness",
            "avg_volume,freshness",
            liquidity_raw,
            liquidity_score,
            RECENT_EDGE_WEIGHTS["liquidity_freshness"],
        ),
    ]
    present = [item for item in inputs if not item["missing"]]
    if not present:
        return None, inputs
    # §11.10: missing components are excluded from the denominator (spec §212), so
    # re-normalize by the sum of present weights — a record missing one component is
    # not under-scored.
    weight_sum = sum(item["weight"] for item in present)
    score = sum(item["normalized_value"] * item["weight"] for item in present) / weight_sum
    return round(score, 2), inputs


from trend_contracts import (  # noqa: E402
    MONITORING_ONLY_CATEGORIES,
    PRIORITY_P1_MIN,
    PRIORITY_P2_MIN,
    PRIORITY_P3_MIN,
    READINESS_ACCEPTED_MIN,
    READINESS_MONITOR_ONLY_MIN,
    SUPPORT_RETEST_MAX_DISTANCE_PCT,
    PULLBACK_MAX_DAILY_CHANGE_PCT,
    PULLBACK_MIN_SWING_PCT,
    BREAKOUT_MIN_DAILY_CHANGE_PCT,
    VOLATILITY_ATR_EXPANSION_RATIO,
    RS_ROTATION_MIN_EXCESS_5D_PCT,
    EVENT_EARNINGS_WINDOW_DAYS,
)

_FRESHNESS_TO_QUALITY = {
    "same_day": "fresh",
    "fresh_cache": "fresh",
    "weekly_context": "partial",
    "stale": "stale",
    "unknown": "partial",
}
_QUALITY_RANK = {"fresh": 0, "partial": 1, "stale": 2, "failed": 3}


def _support_distance(metrics: dict[str, Any]) -> float | None:
    d = _as_float(metrics.get("support_distance_pct"))
    if d is None and isinstance(metrics.get("support_level"), dict):
        d = _as_float(metrics["support_level"].get("distance_pct"))
    return d


def compute_trend_category(metrics: dict[str, Any]) -> str:
    """First-match-wins classifier (brief §6.1/§11.1). Falls back to DORMANT_OR_NO_ACTION."""
    days_to_earn = _as_float(metrics.get("days_to_earnings"))
    if metrics.get("earnings_blocked") or (days_to_earn is not None and days_to_earn <= EVENT_EARNINGS_WINDOW_DAYS):
        return "EVENT_DRIVEN_SETUP"
    dist = _support_distance(metrics)
    if isinstance(metrics.get("support_level"), dict) and dist is not None and abs(dist) <= SUPPORT_RETEST_MAX_DISTANCE_PCT:
        return "SUPPORT_RETEST"
    daily = _as_float(metrics.get("daily_change_pct"))
    swing = _as_float(metrics.get("median_swing"))
    if daily is not None and daily <= PULLBACK_MAX_DAILY_CHANGE_PCT and swing is not None and swing >= PULLBACK_MIN_SWING_PCT:
        return "MEAN_REVERSION_PULLBACK"
    high_20d = _as_float(metrics.get("high_20d"))
    price = _as_float(metrics.get("price"))
    if daily is not None and daily >= BREAKOUT_MIN_DAILY_CHANGE_PCT and price is not None and high_20d is not None and price >= high_20d:
        return "BREAKOUT_ACCELERATION"
    atr_pct = _as_float(metrics.get("atr_pct"))
    atr_avg = _as_float(metrics.get("atr_pct_avg_60d"))
    if atr_pct is not None and atr_avg not in (None, 0) and atr_pct >= VOLATILITY_ATR_EXPANSION_RATIO * atr_avg:
        return "VOLATILITY_EXPANSION"
    rs = _as_float(metrics.get("rs_excess_5d"))
    if rs is not None and rs >= RS_ROTATION_MIN_EXCESS_5D_PCT:
        return "RELATIVE_STRENGTH_ROTATION"
    return "DORMANT_OR_NO_ACTION"


def _source_quality(record: dict[str, Any], missing_components: list[str]) -> str:
    worst = "fresh"
    for ref in record.get("source_refs") or []:
        q = _FRESHNESS_TO_QUALITY.get(str(ref.get("freshness")), "partial")
        if _QUALITY_RANK[q] > _QUALITY_RANK[worst]:
            worst = q
    if missing_components and _QUALITY_RANK[worst] < _QUALITY_RANK["partial"]:
        worst = "partial"
    return worst


def _priority_tier(score: float | None, source_quality: str) -> str:
    if score is None:
        return "P4"
    if score >= PRIORITY_P1_MIN and source_quality == "fresh":
        return "P1"
    if score >= PRIORITY_P2_MIN:
        return "P2"
    if score >= PRIORITY_P3_MIN:
        return "P3"
    return "P4"


def _readiness(score: float | None, present_count: int) -> str:
    if score is None or present_count == 0:
        return "needs_data"
    if score >= READINESS_ACCEPTED_MIN:
        return "accepted"
    return "monitor_only"


def _cadence(priority_tier: str, readiness: str, near_trigger: bool) -> str:
    if priority_tier == "P1" or near_trigger:
        return "intraday"
    if readiness == "needs_data":
        return "weekly"
    if priority_tier in ("P2", "P3"):
        return "daily"
    return "weekly"


def enrich_snapshot_record(record: dict[str, Any]) -> dict[str, Any]:
    """Copy a snapshot record and add deterministic trend + derived fields (M2/M3)."""
    enriched = {
        "ticker": record.get("ticker"),
        "metrics": dict(record.get("metrics") or {}),
        "source_refs": list(record.get("source_refs") or []),
    }
    metrics = enriched["metrics"]
    score, inputs = compute_recent_edge_score(record)
    metrics["recent_edge_score"] = score
    metrics["recent_edge_score_inputs"] = inputs
    missing_components = [i["component"] for i in inputs if i["missing"]]
    present_count = len(inputs) - len(missing_components)
    metrics["missing_edge_components"] = missing_components

    category = compute_trend_category(metrics)
    enriched["trend_category"] = category
    source_quality = _source_quality(enriched, missing_components)
    readiness = _readiness(score, present_count)
    priority_tier = _priority_tier(score, source_quality)
    dist = _support_distance(metrics)
    near_trigger = dist is not None and abs(dist) <= SUPPORT_RETEST_MAX_DISTANCE_PCT
    enriched["readiness"] = readiness
    enriched["priority_tier"] = priority_tier
    enriched["source_quality"] = source_quality
    enriched["monitoring_cadence"] = _cadence(priority_tier, readiness, near_trigger)
    enriched["monitoring_only_category"] = category in MONITORING_ONLY_CATEGORIES
    enriched["human_action_required"] = False  # set by the action planner (M6, §11.4)

    # Legacy state retained for back-compat with existing ledger rendering/tests.
    if score is None:
        state = "insufficient_evidence"
    elif score >= 75:
        state = "high_priority"
    elif score >= 60:
        state = "candidate"
    else:
        state = "monitor"
    enriched["trend_state"] = state
    return enriched
