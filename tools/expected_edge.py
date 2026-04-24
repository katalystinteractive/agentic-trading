"""Expected-edge scoring for graph-policy sweep artifacts.

The scorer is deliberately transparent: it only ranks candidates that already
survived their existing hard gates and sweeps. It does not create new candidates.
"""

from __future__ import annotations

import math
from pathlib import Path

from neural_artifact_validator import ArtifactValidationError, load_validated_json


ROOT = Path(__file__).resolve().parent.parent
CALIBRATION_PATH = ROOT / "data" / "probability_calibration.json"
_CALIBRATION_CACHE = {"mtime": None, "data": None}


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value, low, high):
    return max(low, min(high, value))


def _probability(value):
    value = _as_float(value)
    if value > 1:
        value = value / 100.0
    return _clamp(value, 0.0, 1.0)


def _trade_confidence(trades, min_trades):
    trades = max(0.0, _as_float(trades))
    if trades <= 0:
        return 0.0
    return _clamp(math.sqrt(trades / max(1.0, min_trades)), 0.0, 1.0)


def _validation_multiplier(cross_validation):
    if not cross_validation:
        return 1.0
    cv_trades = _as_float(cross_validation.get("trades"))
    if cv_trades <= 0:
        return 0.85
    cv_pnl = _as_float(cross_validation.get("pnl"))
    if cv_pnl < 0:
        return 0.55
    return 1.1


def _load_probability_calibration():
    try:
        mtime = CALIBRATION_PATH.stat().st_mtime
    except OSError:
        return None
    if _CALIBRATION_CACHE["mtime"] == mtime:
        return _CALIBRATION_CACHE["data"]
    try:
        data = load_validated_json(CALIBRATION_PATH)
    except (ArtifactValidationError, FileNotFoundError, ValueError):
        data = None
    _CALIBRATION_CACHE["mtime"] = mtime
    _CALIBRATION_CACHE["data"] = data
    return data


def calibrate_probability(strategy, outcome, raw_probability,
                          calibration=None):
    raw = _probability(raw_probability)
    if calibration is None:
        calibration = _load_probability_calibration()
    if not isinstance(calibration, dict):
        return raw
    buckets = (
        calibration.get("strategies", {})
        .get(strategy, {})
        .get(outcome, [])
    )
    if not isinstance(buckets, list):
        return raw
    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        lower = _as_float(bucket.get("lower"))
        upper = _as_float(bucket.get("upper"), 1.0)
        if lower <= raw <= upper:
            return _probability(bucket.get("calibrated", raw))
    return raw


def score_graph_candidate(strategy, params, stats, features=None,
                          cross_validation=None):
    """Return expected-edge fields for an already-gated candidate.

    The output is JSON-serializable and intended to be merged into an artifact's
    existing `stats` dict.
    """
    params = params or {}
    stats = stats or {}
    features = features or {}

    trades = (
        _as_float(stats.get("trades"))
        or _as_float(features.get("trade_count"))
        or _as_float(stats.get("cycles"))
    )
    win_rate = _probability(stats.get("win_rate"))
    raw_p_target = _probability(features.get("target_hit_rate", win_rate))
    raw_p_stop = _probability(features.get("stop_hit_rate"))
    calibration = _load_probability_calibration()
    p_target = calibrate_probability(strategy, "target", raw_p_target, calibration)
    p_stop = calibrate_probability(strategy, "stop", raw_p_stop, calibration)
    p_other = _clamp(1.0 - p_target - p_stop, 0.0, 1.0)

    if strategy == "dip":
        target_reward_pct = _as_float(params.get("target_pct"))
        stop_loss_pct = abs(_as_float(params.get("stop_pct")))
        execution_cost_pct = 0.20
        min_trades = 5
    else:
        target_reward_pct = _as_float(params.get("sell_default"))
        stop_loss_pct = _as_float(params.get("cat_hard_stop"), 25.0)
        execution_cost_pct = 0.35
        min_trades = 8

    mean_pnl_pct = _as_float(features.get("mean_pnl_pct"))
    gross_ev_pct = (
        p_target * target_reward_pct
        - p_stop * stop_loss_pct
        + p_other * mean_pnl_pct
    )

    hold_days = _as_float(features.get("median_hold_days"))
    hold_penalty_pct = min(1.5, hold_days * 0.015)
    confidence = _trade_confidence(trades, min_trades)
    confidence = _clamp(confidence * _validation_multiplier(cross_validation),
                        0.0, 1.0)

    expected_edge_pct = gross_ev_pct - execution_cost_pct - hold_penalty_pct
    risk_multiplier = _clamp(1.0 - p_stop * 0.5, 0.5, 1.0)
    edge_multiplier = _clamp(1.0 + expected_edge_pct / 20.0, 0.25, 1.75)

    composite = _as_float(stats.get("composite"))
    edge_adjusted_composite = composite * confidence * risk_multiplier * edge_multiplier

    graph_score = _clamp(
        50.0 + expected_edge_pct * 8.0 + confidence * 20.0 - p_stop * 20.0,
        0.0,
        100.0,
    )

    return {
        "expected_edge": round(expected_edge_pct, 3),
        "expected_edge_pct": round(expected_edge_pct, 3),
        "graph_score": round(graph_score, 1),
        "edge_adjusted_composite": round(edge_adjusted_composite, 2),
        "edge_components": {
            "p_target": round(p_target, 3),
            "p_stop": round(p_stop, 3),
            "raw_p_target": round(raw_p_target, 3),
            "raw_p_stop": round(raw_p_stop, 3),
            "p_other": round(p_other, 3),
            "target_reward_pct": round(target_reward_pct, 3),
            "stop_loss_pct": round(stop_loss_pct, 3),
            "gross_ev_pct": round(gross_ev_pct, 3),
            "execution_cost_pct": round(execution_cost_pct, 3),
            "hold_penalty_pct": round(hold_penalty_pct, 3),
            "confidence": round(confidence, 3),
            "risk_multiplier": round(risk_multiplier, 3),
            "edge_multiplier": round(edge_multiplier, 3),
        },
    }


def attach_expected_edge(strategy, entry):
    """Merge expected-edge fields into a sweep result entry's stats."""
    if not isinstance(entry, dict):
        return entry
    stats = entry.setdefault("stats", {})
    stats.update(score_graph_candidate(
        strategy=strategy,
        params=entry.get("params"),
        stats=stats,
        features=entry.get("features"),
        cross_validation=entry.get("cross_validation"),
    ))
    return entry
