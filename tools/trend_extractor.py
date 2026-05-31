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
    pct = _as_float(value)
    if pct is None:
        return None
    return _clamp((pct + 15.0) / 30.0 * 100.0)


def _score_liquidity_freshness(metrics: dict[str, Any]) -> tuple[float | None, Any]:
    avg_volume = _as_float(metrics.get("avg_volume"))
    freshness = metrics.get("freshness")
    if avg_volume is None and freshness is None:
        return None, None
    freshness = freshness or "unknown"
    volume_score = None if avg_volume is None else _clamp(avg_volume / 500_000.0 * 100.0)
    freshness_score = {"fresh": 100.0, "unknown": 50.0, "stale": 35.0}.get(str(freshness), 50.0)
    if volume_score is None:
        return freshness_score, {"freshness": freshness}
    return round((volume_score * 0.65) + (freshness_score * 0.35), 2), {
        "avg_volume": avg_volume,
        "freshness": freshness,
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
    score = sum(item["normalized_value"] * item["weight"] for item in present)
    return round(score, 2), inputs


def enrich_snapshot_record(record: dict[str, Any]) -> dict[str, Any]:
    """Copy a snapshot record and add deterministic trend fields."""
    enriched = {
        "ticker": record.get("ticker"),
        "metrics": dict(record.get("metrics") or {}),
        "source_refs": list(record.get("source_refs") or []),
    }
    score, inputs = compute_recent_edge_score(record)
    enriched["metrics"]["recent_edge_score"] = score
    enriched["metrics"]["recent_edge_score_inputs"] = inputs
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
