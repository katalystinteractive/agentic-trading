"""Shared contracts for deterministic V2 trend-monitoring artifacts."""
from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1

PHASES = ("snapshot", "ledger", "actions", "report")
RUN_STATUSES = (
    "running",
    "completed",
    "completed_with_gaps",
    "failed",
    "nonconverged",
)
PHASE_STATUSES = (
    "running",
    "completed",
    "completed_with_gaps",
    "failed",
    "skipped",
    "nonconverged",
)
SOURCE_FRESHNESS = ("fresh", "stale", "unknown")

ACTION_ADD_TO_CANDIDATE_POOL = "ADD_TO_CANDIDATE_POOL"
ACTION_PROMOTE_TO_SIMULATION = "PROMOTE_TO_SIMULATION"
ACTION_MONITOR = "MONITOR"

RECENT_EDGE_WEIGHTS = {
    "support": 0.40,
    "post_signal_or_simulation": 0.25,
    "watchlist_or_candidate_delta": 0.20,
    "liquidity_freshness": 0.15,
}


@dataclass(frozen=True)
class TrendValidationIssue:
    artifact: str
    path: str
    message: str
    severity: str = "ERROR"


class TrendValidationError(RuntimeError):
    """Raised when a V2 trend artifact fails validation."""

    def __init__(self, path: Path, issues: list[TrendValidationIssue]):
        self.path = path
        self.issues = issues
        detail = "; ".join(issue.message for issue in issues[:5])
        if len(issues) > 5:
            detail += f"; ... {len(issues) - 5} more"
        super().__init__(f"{path.name} failed validation: {detail}")


def utc_now() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def new_run_id() -> str:
    return uuid.uuid4().hex


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def atomic_write_json(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)
    return path


def atomic_write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)
    return path


def copy_to_run_history(
    output_dir: Path,
    as_of_date: str,
    run_id: str,
    artifact_paths: list[Path],
) -> list[Path]:
    history_dir = output_dir / "run-history" / as_of_date / run_id
    history_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for path in artifact_paths:
        if path.exists():
            target = history_dir / path.name
            shutil.copy2(path, target)
            copied.append(target)
    return copied


def issue_dicts(issues: list[TrendValidationIssue]) -> list[dict[str, Any]]:
    return [asdict(issue) for issue in issues]


def _issue(artifact: str, path: str, message: str) -> TrendValidationIssue:
    return TrendValidationIssue(artifact=artifact, path=path, message=message)


def _require_object(
    value: Any,
    artifact: str,
    path: str,
    issues: list[TrendValidationIssue],
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        issues.append(_issue(artifact, path, "must be an object"))
        return None
    return value


def _require_fields(
    obj: dict[str, Any],
    fields: list[str],
    artifact: str,
    path: str,
    issues: list[TrendValidationIssue],
) -> None:
    for field in fields:
        if field not in obj:
            issues.append(_issue(artifact, f"{path}/{field}", "missing required field"))


def _validate_schema_version(
    obj: dict[str, Any],
    artifact: str,
    issues: list[TrendValidationIssue],
) -> None:
    if obj.get("schema_version") != SCHEMA_VERSION:
        issues.append(_issue(
            artifact,
            "/schema_version",
            f"must be {SCHEMA_VERSION}",
        ))


def validate_source_ref(
    ref: Any,
    artifact: str,
    path: str,
) -> list[TrendValidationIssue]:
    issues: list[TrendValidationIssue] = []
    obj = _require_object(ref, artifact, path, issues)
    if obj is None:
        return issues
    _require_fields(
        obj,
        ["artifact", "json_pointer", "value", "as_of_date", "freshness", "claim_field"],
        artifact,
        path,
        issues,
    )
    if "artifact" in obj and not isinstance(obj["artifact"], str):
        issues.append(_issue(artifact, f"{path}/artifact", "must be a string"))
    pointer = obj.get("json_pointer")
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        issues.append(_issue(artifact, f"{path}/json_pointer", "must be a JSON pointer"))
    as_of = obj.get("as_of_date")
    if as_of is not None:
        if not isinstance(as_of, str):
            issues.append(_issue(artifact, f"{path}/as_of_date", "must be null or ISO date"))
        else:
            try:
                datetime.fromisoformat(as_of[:10])
            except ValueError:
                issues.append(_issue(artifact, f"{path}/as_of_date", "must be null or ISO date"))
    freshness = obj.get("freshness")
    if freshness not in SOURCE_FRESHNESS:
        issues.append(_issue(
            artifact,
            f"{path}/freshness",
            f"must be one of {', '.join(SOURCE_FRESHNESS)}",
        ))
    if "claim_field" in obj and not isinstance(obj["claim_field"], str):
        issues.append(_issue(artifact, f"{path}/claim_field", "must be a string"))
    return issues


def validate_source_refs(
    refs: Any,
    artifact: str,
    path: str,
    *,
    required: bool = True,
) -> list[TrendValidationIssue]:
    issues: list[TrendValidationIssue] = []
    if not isinstance(refs, list):
        issues.append(_issue(artifact, path, "must be a list"))
        return issues
    if required and not refs:
        issues.append(_issue(artifact, path, "must include at least one source ref"))
    for idx, ref in enumerate(refs):
        issues.extend(validate_source_ref(ref, artifact, f"{path}/{idx}"))
    return issues


def validate_daily_snapshot(data: Any) -> list[TrendValidationIssue]:
    artifact = "daily-market-snapshot"
    issues: list[TrendValidationIssue] = []
    obj = _require_object(data, artifact, "", issues)
    if obj is None:
        return issues
    _require_fields(
        obj,
        ["schema_version", "artifact_type", "as_of_date", "generated_at", "records"],
        artifact,
        "",
        issues,
    )
    _validate_schema_version(obj, artifact, issues)
    if obj.get("artifact_type") != artifact:
        issues.append(_issue(artifact, "/artifact_type", f"must be {artifact!r}"))
    records = obj.get("records")
    if not isinstance(records, list):
        issues.append(_issue(artifact, "/records", "must be a list"))
        return issues
    for idx, record in enumerate(records):
        rec = _require_object(record, artifact, f"/records/{idx}", issues)
        if rec is None:
            continue
        _require_fields(
            rec,
            ["ticker", "metrics", "source_refs"],
            artifact,
            f"/records/{idx}",
            issues,
        )
        if "source_refs" in rec:
            issues.extend(validate_source_refs(
                rec["source_refs"],
                artifact,
                f"/records/{idx}/source_refs",
            ))
    return issues


def validate_trend_ledger(data: Any) -> list[TrendValidationIssue]:
    artifact = "trend-ledger"
    issues: list[TrendValidationIssue] = []
    obj = _require_object(data, artifact, "", issues)
    if obj is None:
        return issues
    _require_fields(
        obj,
        ["schema_version", "artifact_type", "as_of_date", "generated_at", "records"],
        artifact,
        "",
        issues,
    )
    _validate_schema_version(obj, artifact, issues)
    if obj.get("artifact_type") != artifact:
        issues.append(_issue(artifact, "/artifact_type", f"must be {artifact!r}"))
    records = obj.get("records")
    if not isinstance(records, list):
        issues.append(_issue(artifact, "/records", "must be a list"))
        return issues
    for idx, record in enumerate(records):
        rec = _require_object(record, artifact, f"/records/{idx}", issues)
        if rec is None:
            continue
        _require_fields(
            rec,
            ["ticker", "metrics", "source_refs", "trend_state"],
            artifact,
            f"/records/{idx}",
            issues,
        )
        score = rec.get("metrics", {}).get("recent_edge_score") if isinstance(rec.get("metrics"), dict) else None
        if score is not None and (
            not isinstance(score, (int, float))
            or isinstance(score, bool)
            or score < 0
            or score > 100
        ):
            issues.append(_issue(
                artifact,
                f"/records/{idx}/metrics/recent_edge_score",
                "must be null or a number from 0 to 100",
            ))
        metrics = rec.get("metrics")
        if isinstance(metrics, dict) and score is not None:
            inputs = metrics.get("recent_edge_score_inputs")
            if not isinstance(inputs, list) or not inputs:
                issues.append(_issue(
                    artifact,
                    f"/records/{idx}/metrics/recent_edge_score_inputs",
                    "required when recent_edge_score is not null",
                ))
            elif abs(sum(item.get("weight", 0) for item in inputs if isinstance(item, dict)) - 1.0) > 0.001:
                issues.append(_issue(
                    artifact,
                    f"/records/{idx}/metrics/recent_edge_score_inputs",
                    "component weights must sum to 1.0",
                ))
        if "source_refs" in rec:
            issues.extend(validate_source_refs(
                rec["source_refs"],
                artifact,
                f"/records/{idx}/source_refs",
            ))
    return issues


def validate_run_status(data: Any) -> list[TrendValidationIssue]:
    artifact = "run-status"
    issues: list[TrendValidationIssue] = []
    obj = _require_object(data, artifact, "", issues)
    if obj is None:
        return issues
    _require_fields(
        obj,
        ["schema_version", "artifact_type", "as_of_date", "run_id", "run_status", "phase_statuses"],
        artifact,
        "",
        issues,
    )
    _validate_schema_version(obj, artifact, issues)
    if obj.get("artifact_type") != artifact:
        issues.append(_issue(artifact, "/artifact_type", f"must be {artifact!r}"))
    if obj.get("run_status") not in RUN_STATUSES:
        issues.append(_issue(artifact, "/run_status", "invalid run status"))
    phases = obj.get("phase_statuses")
    if not isinstance(phases, list):
        issues.append(_issue(artifact, "/phase_statuses", "must be a list"))
        return issues
    seen = [phase.get("phase") for phase in phases if isinstance(phase, dict)]
    expected_prefix = list(PHASES[:len(seen)])
    if seen != expected_prefix:
        issues.append(_issue(artifact, "/phase_statuses", "phases must follow required order"))
    for idx, phase in enumerate(phases):
        item = _require_object(phase, artifact, f"/phase_statuses/{idx}", issues)
        if item is None:
            continue
        _require_fields(
            item,
            ["phase", "status", "started_at", "finished_at", "input_artifacts", "output_artifacts", "errors"],
            artifact,
            f"/phase_statuses/{idx}",
            issues,
        )
        if item.get("phase") not in PHASES:
            issues.append(_issue(artifact, f"/phase_statuses/{idx}/phase", "invalid phase"))
        if item.get("status") not in PHASE_STATUSES:
            issues.append(_issue(artifact, f"/phase_statuses/{idx}/status", "invalid phase status"))
        if item.get("status") == "skipped" and item.get("started_at") is not None:
            issues.append(_issue(artifact, f"/phase_statuses/{idx}/started_at", "skipped phase start must be null"))
        if item.get("status") != "running" and item.get("status") != "skipped" and item.get("finished_at") is None:
            issues.append(_issue(artifact, f"/phase_statuses/{idx}/finished_at", "terminal phase needs finish time"))
    return issues


def validate_validation_findings(data: Any) -> list[TrendValidationIssue]:
    artifact = "validation-findings"
    issues: list[TrendValidationIssue] = []
    obj = _require_object(data, artifact, "", issues)
    if obj is None:
        return issues
    _require_fields(obj, ["schema_version", "artifact_type", "as_of_date", "findings"], artifact, "", issues)
    _validate_schema_version(obj, artifact, issues)
    if obj.get("artifact_type") != artifact:
        issues.append(_issue(artifact, "/artifact_type", f"must be {artifact!r}"))
    findings = obj.get("findings")
    if not isinstance(findings, list):
        issues.append(_issue(artifact, "/findings", "must be a list"))
        return issues
    for idx, finding in enumerate(findings):
        item = _require_object(finding, artifact, f"/findings/{idx}", issues)
        if item is None:
            continue
        _require_fields(item, ["artifact", "path", "message", "severity", "source_refs"], artifact, f"/findings/{idx}", issues)
        if "source_refs" in item:
            issues.extend(validate_source_refs(
                item["source_refs"],
                artifact,
                f"/findings/{idx}/source_refs",
                required=False,
            ))
    return issues


def validate_monitoring_actions(data: Any) -> list[TrendValidationIssue]:
    artifact = "monitoring-actions"
    issues: list[TrendValidationIssue] = []
    obj = _require_object(data, artifact, "", issues)
    if obj is None:
        return issues
    _require_fields(obj, ["schema_version", "artifact_type", "as_of_date", "actions"], artifact, "", issues)
    _validate_schema_version(obj, artifact, issues)
    if obj.get("artifact_type") != artifact:
        issues.append(_issue(artifact, "/artifact_type", f"must be {artifact!r}"))
    actions = obj.get("actions")
    if not isinstance(actions, list):
        issues.append(_issue(artifact, "/actions", "must be a list"))
        return issues
    for idx, action in enumerate(actions):
        item = _require_object(action, artifact, f"/actions/{idx}", issues)
        if item is None:
            continue
        _require_fields(item, ["ticker", "action", "write_effect", "source_refs"], artifact, f"/actions/{idx}", issues)
        if item.get("write_effect") != "none":
            issues.append(_issue(artifact, f"/actions/{idx}/write_effect", "must be 'none'"))
        if "source_refs" in item:
            issues.extend(validate_source_refs(
                item["source_refs"],
                artifact,
                f"/actions/{idx}/source_refs",
            ))
    return issues


VALIDATORS = {
    "daily-market-snapshot": validate_daily_snapshot,
    "trend-ledger": validate_trend_ledger,
    "run-status": validate_run_status,
    "validation-findings": validate_validation_findings,
    "monitoring-actions": validate_monitoring_actions,
}


def validate_artifact(data: Any, artifact_type: str) -> list[TrendValidationIssue]:
    validator = VALIDATORS.get(artifact_type)
    if validator is None:
        return [_issue(artifact_type, "", "unknown trend artifact type")]
    return validator(data)


def load_validated_trend_json(path: Path, artifact_type: str) -> Any:
    try:
        data = load_json(path)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        issue = TrendValidationIssue(
            artifact=artifact_type,
            path="",
            message=f"invalid JSON artifact: {exc}",
        )
        raise TrendValidationError(path, [issue]) from exc
    issues = validate_artifact(data, artifact_type)
    if issues:
        raise TrendValidationError(path, issues)
    return data


def source_ref(
    *,
    artifact: str,
    json_pointer: str,
    value: Any,
    as_of_date: str | None,
    freshness: str,
    claim_field: str,
) -> dict[str, Any]:
    return {
        "artifact": artifact,
        "json_pointer": json_pointer,
        "value": value,
        "as_of_date": as_of_date,
        "freshness": freshness if freshness in SOURCE_FRESHNESS else "unknown",
        "claim_field": claim_field,
    }


def phase_entry(
    phase: str,
    status: str,
    *,
    started_at: str | None,
    finished_at: str | None,
    input_artifacts: list[str] | None = None,
    output_artifacts: list[str] | None = None,
    errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "phase": phase,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "input_artifacts": input_artifacts or [],
        "output_artifacts": output_artifacts or [],
        "errors": errors or [],
    }


def build_run_status(
    *,
    as_of_date: str,
    run_id: str,
    run_status: str,
    phase_statuses: list[dict[str, Any]],
    generated_at: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "run-status",
        "as_of_date": as_of_date,
        "generated_at": generated_at or utc_now(),
        "finished_at": None if run_status == "running" else (generated_at or utc_now()),
        "run_id": run_id,
        "run_status": run_status,
        "phase_statuses": phase_statuses,
    }


def status_from_output_dir(output_dir: Path, as_of_date: str) -> tuple[str, list[dict[str, Any]]]:
    path = output_dir / "run-status.json"
    if not path.exists():
        return new_run_id(), []
    try:
        data = load_validated_trend_json(path, "run-status")
    except TrendValidationError:
        return new_run_id(), []
    return str(data.get("run_id") or new_run_id()), list(data.get("phase_statuses") or [])

