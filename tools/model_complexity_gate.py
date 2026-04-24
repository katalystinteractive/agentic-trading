"""Promotion boundary for true neural/black-box model artifacts.

Graph-policy and sweep artifacts are allowed to affect live decisions after the
existing schema/freshness/promotion checks. Future black-box model outputs must
prove promotion against the graph baseline before any live consumer may use them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


GRAPH_POLICY_FAMILIES = {
    "",
    "graph_policy",
    "calibrated_graph_policy",
    "learned_graph_policy",
    "sweep_policy",
    "rule_graph",
}
BLACK_BOX_FAMILIES = {
    "neural_model",
    "black_box_model",
    "ml_model",
    "deep_learning_model",
}
PROMOTED_STATUSES = {"promoted", "approved", "live"}


def artifact_meta(data: dict[str, Any] | None) -> dict[str, Any]:
    meta = (data or {}).get("_meta", {})
    return meta if isinstance(meta, dict) else {}


def model_family(data: dict[str, Any] | None) -> str:
    meta = artifact_meta(data)
    return str(meta.get("model_family", "graph_policy")).strip().lower()


def _as_number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_black_box_model(data: dict[str, Any] | None) -> bool:
    return model_family(data) in BLACK_BOX_FAMILIES


def is_live_decision_artifact(data: dict[str, Any] | None) -> bool:
    """Return whether an artifact is eligible to affect live decisions."""
    family = model_family(data)
    if family in GRAPH_POLICY_FAMILIES:
        return True
    if family not in BLACK_BOX_FAMILIES:
        return False

    meta = artifact_meta(data)
    promotion = meta.get("promotion", {})
    if not isinstance(promotion, dict):
        promotion = {}

    status = str(
        meta.get("promotion_status")
        or meta.get("live_decision_status")
        or promotion.get("status", "")
    ).strip().lower()
    if status not in PROMOTED_STATUSES:
        return False
    if promotion.get("approved") is False:
        return False

    baseline = str(
        promotion.get("baseline_family")
        or promotion.get("baseline")
        or meta.get("baseline_family", "")
    ).strip().lower()
    if baseline and baseline not in GRAPH_POLICY_FAMILIES:
        return False

    lift = _as_number(
        promotion.get("out_of_sample_lift_pct",
                      promotion.get("risk_adjusted_lift_pct",
                                    meta.get("out_of_sample_lift_pct"))),
        default=0.0,
    )
    risk_lift = _as_number(
        promotion.get("risk_adjusted_lift_pct", lift),
        default=lift,
    )
    return lift > 0 and risk_lift > 0


def live_decision_reason(data: dict[str, Any] | None) -> str:
    """Human-readable decision for logs/tests."""
    family = model_family(data)
    if family in GRAPH_POLICY_FAMILIES:
        return f"{family or 'graph_policy'} artifact is live-eligible"
    if family not in BLACK_BOX_FAMILIES:
        return f"unknown model_family {family!r} is not live-eligible"
    if is_live_decision_artifact(data):
        return "black-box model artifact is promoted for live use"
    return "black-box model artifact is advisory until promoted against graph baseline"


def require_live_decision_artifact(data: dict[str, Any] | None,
                                   path: Path | str | None = None,
                                   consumer: str = "live consumer") -> dict[str, Any]:
    if is_live_decision_artifact(data):
        return data or {}
    label = Path(path).name if path else "artifact"
    raise ValueError(f"{consumer} ignored {label}: {live_decision_reason(data)}")


def filter_live_decision_entries(data: dict[str, Any] | None,
                                 path: Path | str | None = None,
                                 consumer: str = "live consumer") -> dict[str, Any]:
    """Return ticker entries only if the artifact is live-eligible."""
    require_live_decision_artifact(data, path=path, consumer=consumer)
    return {k: v for k, v in (data or {}).items() if not k.startswith("_")}
