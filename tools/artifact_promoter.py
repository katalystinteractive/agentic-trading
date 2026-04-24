"""Promotion gate for generated graph-policy artifacts.

Weekly tools still write their normal live artifact path. This gate snapshots the
incumbent before a step runs, captures the newly generated candidate afterward,
and only leaves the candidate live when it validates and is not materially worse.
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Any

from neural_artifact_validator import (
    ArtifactValidationError,
    load_validated_json,
)


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PROMOTION_DIR = DATA_DIR / "artifact_promotion"
REPORTS_DIR = PROMOTION_DIR / "reports"
STAGING_DIR = PROMOTION_DIR / "staging"
REJECTED_DIR = PROMOTION_DIR / "rejected"
INCUMBENT_DIR = PROMOTION_DIR / "incumbents"

DEFAULT_MARGIN = 0.02
SUPPORTED_ARTIFACTS = {
    "sweep_results.json",
    "support_sweep_results.json",
    "synapse_weights.json",
    "ticker_profiles.json",
    "probability_calibration.json",
}


@dataclass
class PromotionDecision:
    artifact: str
    decision: str
    reason: str
    incumbent_score: float | None
    candidate_score: float | None
    report_path: str | None = None

    @property
    def approved(self) -> bool:
        return self.decision in {"promoted", "kept"}


def _timestamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_raw(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _entries(data: dict[str, Any]):
    return [
        entry for key, entry in data.items()
        if not key.startswith("_") and isinstance(entry, dict)
    ]


def _sweep_score(data: dict[str, Any]) -> float:
    score = 0.0
    for entry in _entries(data):
        stats = entry.get("stats") or {}
        cv = entry.get("cross_validation") or {}
        component = stats.get("edge_adjusted_composite")
        if component is None:
            component = stats.get("composite")
        if component is None:
            component = stats.get("pnl", stats.get("total_pnl", 0))
        component = _safe_float(component)
        trades = _safe_float(stats.get("trades", cv.get("trades", 0)))
        if cv:
            cv_pnl = _safe_float(cv.get("pnl"))
            cv_trades = _safe_float(cv.get("trades"))
            if cv_trades > 0:
                component = (component + cv_pnl) / 2.0
            if component > 0 and cv_pnl < 0:
                component *= 0.5
        score += component * min(1.0, trades / 5.0 if trades else 0.5)
    return round(score, 4)


def _weights_score(data: dict[str, Any]) -> float:
    meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
    stats = meta.get("stats") if isinstance(meta.get("stats"), dict) else {}
    policy = _safe_float(stats.get("policy_synapses"))
    total = _safe_float(stats.get("total_synapses"))
    return round(policy + total * 0.1, 4)


def _profiles_score(data: dict[str, Any]) -> float:
    profiles = _entries(data)
    if not profiles:
        return 0.0
    confidences = [_safe_float(profile.get("confidence")) for profile in profiles]
    return round(sum(confidences) / len(confidences), 4)


def _calibration_score(data: dict[str, Any]) -> float:
    meta = data.get("_meta") if isinstance(data.get("_meta"), dict) else {}
    return _safe_float(meta.get("samples"))


def artifact_score(path: Path) -> float:
    data = _load_raw(path)
    if path.name in {"sweep_results.json", "support_sweep_results.json"}:
        return _sweep_score(data)
    if path.name == "synapse_weights.json":
        return _weights_score(data)
    if path.name == "ticker_profiles.json":
        return _profiles_score(data)
    if path.name == "probability_calibration.json":
        return _calibration_score(data)
    return 0.0


def snapshot_incumbent(live_path: Path, run_id: str | None = None) -> Path | None:
    live_path = Path(live_path)
    if not live_path.exists():
        return None
    run_id = run_id or _timestamp()
    dest_dir = INCUMBENT_DIR / run_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / live_path.name
    shutil.copy2(live_path, dest)
    return dest


def _write_report(decision: PromotionDecision, candidate_path: Path,
                  incumbent_path: Path | None) -> str:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"{date.today().isoformat()}-{candidate_path.name}.json"
    payload = {
        "date": date.today().isoformat(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "artifact": decision.artifact,
        "decision": decision.decision,
        "reason": decision.reason,
        "candidate_path": str(candidate_path),
        "incumbent_path": str(incumbent_path) if incumbent_path else None,
        "candidate_score": decision.candidate_score,
        "incumbent_score": decision.incumbent_score,
    }
    report_path.write_text(json.dumps(payload, indent=2) + "\n")
    return str(report_path)


def _reject_candidate(candidate_path: Path, artifact_name: str) -> None:
    if not candidate_path.exists():
        return
    REJECTED_DIR.mkdir(parents=True, exist_ok=True)
    dest = REJECTED_DIR / f"{_timestamp()}-{artifact_name}"
    shutil.copy2(candidate_path, dest)


def promote_candidate(candidate_path: Path, live_path: Path,
                      incumbent_path: Path | None = None,
                      min_margin: float = DEFAULT_MARGIN,
                      allow_stale: bool = False) -> PromotionDecision:
    """Promote candidate to live path or restore incumbent.

    If candidate_path is already the live path, a rejected decision restores the
    incumbent over it. If candidate_path is a staging file, an approved decision
    copies it to live_path.
    """
    candidate_path = Path(candidate_path)
    live_path = Path(live_path)
    incumbent_path = Path(incumbent_path) if incumbent_path else None
    artifact = live_path.name

    try:
        load_validated_json(candidate_path, allow_stale=allow_stale)
    except (ArtifactValidationError, FileNotFoundError, ValueError) as exc:
        reason = f"candidate validation failed: {exc}"
        if incumbent_path and incumbent_path.exists():
            shutil.copy2(incumbent_path, live_path)
        _reject_candidate(candidate_path, artifact)
        decision = PromotionDecision(artifact, "rejected", reason, None, None)
        decision.report_path = _write_report(decision, candidate_path, incumbent_path)
        return decision

    candidate_score = artifact_score(candidate_path)
    incumbent_score = artifact_score(incumbent_path) if incumbent_path and incumbent_path.exists() else None

    if incumbent_score is None:
        decision = PromotionDecision(
            artifact, "promoted", "no incumbent artifact", None, candidate_score)
    elif incumbent_score <= 0:
        decision = PromotionDecision(
            artifact, "promoted", "incumbent score is non-positive",
            incumbent_score, candidate_score)
    elif candidate_score + abs(incumbent_score) * min_margin < incumbent_score:
        if incumbent_path and incumbent_path.exists():
            shutil.copy2(incumbent_path, live_path)
        _reject_candidate(candidate_path, artifact)
        decision = PromotionDecision(
            artifact,
            "rejected",
            f"candidate score {candidate_score:.4f} below incumbent {incumbent_score:.4f}",
            incumbent_score,
            candidate_score,
        )
    else:
        if candidate_path.resolve() != live_path.resolve():
            live_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate_path, live_path)
        decision = PromotionDecision(
            artifact,
            "promoted",
            "candidate met incumbent comparison gate",
            incumbent_score,
            candidate_score,
        )

    decision.report_path = _write_report(decision, candidate_path, incumbent_path)
    return decision


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote generated graph-policy artifacts")
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--live", type=Path, required=True)
    parser.add_argument("--incumbent", type=Path)
    parser.add_argument("--min-margin", type=float, default=DEFAULT_MARGIN)
    parser.add_argument("--allow-stale", action="store_true")
    args = parser.parse_args()

    decision = promote_candidate(
        args.candidate,
        args.live,
        incumbent_path=args.incumbent,
        min_margin=args.min_margin,
        allow_stale=args.allow_stale,
    )
    print(json.dumps(decision.__dict__, indent=2))
    return 0 if decision.approved else 1


if __name__ == "__main__":
    raise SystemExit(main())
