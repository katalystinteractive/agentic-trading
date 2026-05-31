"""Shared contracts for deterministic V2 trend-monitoring artifacts."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
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
# Canonical per-source-ref freshness enum (Source Evidence Model, spec §1235).
SOURCE_FRESHNESS = ("same_day", "fresh_cache", "weekly_context", "stale", "unknown")
# Back-compat aliases so legacy source labels normalize to the canonical enum.
FRESHNESS_ALIASES = {
    "fresh": "same_day",
    "cached": "fresh_cache",
    "fresh_cache": "fresh_cache",
    "weekly": "weekly_context",
    "weekly_context": "weekly_context",
    "same_day": "same_day",
    "stale": "stale",
    "unknown": "unknown",
}

# ---- Locked taxonomies (spec §1082/§1126/§1158/§1250/§1238) -----------------
TREND_CATEGORIES = (
    "SUPPORT_RETEST",
    "MEAN_REVERSION_PULLBACK",
    "RELATIVE_STRENGTH_ROTATION",
    "VOLATILITY_EXPANSION",
    "BREAKOUT_ACCELERATION",
    "EVENT_DRIVEN_SETUP",
    "DORMANT_OR_NO_ACTION",
)
# Categories that may never auto-promote regardless of score (brief §6.1/§6.6).
MONITORING_ONLY_CATEGORIES = ("RELATIVE_STRENGTH_ROTATION", "BREAKOUT_ACCELERATION")
FINDING_CATEGORIES = (
    "UNSUPPORTED_SOURCE_CLAIM",
    "STALE_SOURCE_ARTIFACT",
    "DATA_PROVIDER_GAP",
    "STRATEGY_GATE_CONFLICT",
    "INSUFFICIENT_RECENT_EDGE",
    "DUPLICATE_OR_FRAGMENTED_TREND",
    "MISSING_REQUIRED_TREND",
)
ACTION_CATEGORIES = (
    "WATCH_DAILY",
    "WATCH_INTRADAY",
    "PROMOTE_TO_SIMULATION",
    "PROMOTE_TO_DEEP_DIVE",
    "ADD_TO_CANDIDATE_POOL",
    "RECOMMEND_WATCHLIST_REVIEW",
    "COOLDOWN_OR_DROP",
    "NO_CHANGE",
)
TRANSITION_STATES = (
    "new",
    "persisting",
    "upgraded",
    "downgraded",
    "blocked",
    "stale",
    "retired",
)
READINESS = ("accepted", "monitor_only", "blocked", "needs_data", "failed")
PRIORITY_TIERS = ("P1", "P2", "P3", "P4")
MONITORING_CADENCE = ("intraday", "daily", "weekly", "cooldown")
SOURCE_QUALITY = ("fresh", "partial", "stale", "failed")
FINDING_SEVERITIES = ("error", "warning", "info")
# Locked critic patch operations (spec §1315).
CRITIC_OPERATIONS = (
    "replace",
    "append_blocked_reason",
    "downgrade_readiness",
    "merge_duplicate",
    "retire_record",
    "mark_needs_data",
)

# Legacy action constants (mapped to canonical categories by the action planner).
ACTION_ADD_TO_CANDIDATE_POOL = "ADD_TO_CANDIDATE_POOL"
ACTION_PROMOTE_TO_SIMULATION = "PROMOTE_TO_SIMULATION"
ACTION_MONITOR = "MONITOR"

# recommended_next_workflow mapping (brief §6.4; names verified against workflows/).
NEXT_WORKFLOW = {
    "WATCH_DAILY": "none",
    "WATCH_INTRADAY": "none",
    "PROMOTE_TO_SIMULATION": "sim-ranked-candidate-workflow",
    "PROMOTE_TO_DEEP_DIVE": "deep-dive-workflow",
    "ADD_TO_CANDIDATE_POOL": "none",
    "RECOMMEND_WATCHLIST_REVIEW": "watchlist-fitness-workflow",
    "COOLDOWN_OR_DROP": "none",
    "NO_CHANGE": "none",
}

RECENT_EDGE_WEIGHTS = {
    "support": 0.40,
    "post_signal_or_simulation": 0.25,
    "watchlist_or_candidate_delta": 0.20,
    "liquidity_freshness": 0.15,
}

# ---- Tunable thresholds (brief §14 PROPOSED — adjustable on sign-off) --------
# Priority tiers (applied to the re-normalized recent_edge_score, brief §11.10).
PRIORITY_P1_MIN = 80.0
PRIORITY_P2_MIN = 65.0
PRIORITY_P3_MIN = 50.0
# Readiness thresholds.
READINESS_ACCEPTED_MIN = 65.0
READINESS_MONITOR_ONLY_MIN = 50.0
# Quota caps (brief §6.2, spec §115).
MAX_MONITORED_TICKERS = 500
MAX_HIGH_PRIORITY_REFRESHES = 75
MAX_REVIEW_ACTIONS = 30
# Aging / cooldown (brief §6.6).
STALE_AFTER_DAYS = 1            # no same-day evidence -> stale
COOLDOWN_DAYS = 5              # consecutive stale runs -> retired
ABSENT_AGE_OUT_DAYS = 10       # absent from snapshot N runs -> retired
# Classifier triggers (brief §11.1).
SUPPORT_RETEST_MAX_DISTANCE_PCT = 3.0
PULLBACK_MAX_DAILY_CHANGE_PCT = -2.0
PULLBACK_MIN_SWING_PCT = 10.0
BREAKOUT_MIN_DAILY_CHANGE_PCT = 3.0
VOLATILITY_ATR_EXPANSION_RATIO = 1.3
RS_ROTATION_MIN_EXCESS_5D_PCT = 3.0
EVENT_EARNINGS_WINDOW_DAYS = 14
# Strategy gates (brief §12).
GATE_MIN_AVG_VOLUME = 500_000
GATE_PRICE_MIN = 3.0
GATE_PRICE_MAX = 60.0
GATE_MIN_LADDER_LEVELS = 2
GATE_SECTOR_CONCENTRATION_MAX = 5
# Watchlist-review trigger (brief §11.2).
WATCHLIST_REVIEW_DELTA_PCT = -10.0
# Runtime guard (spec §150/§1523).
RUNTIME_TARGET_MINUTES = 45
RUNTIME_HARD_CAP_MINUTES = 90


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


def utc_now(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment.replace(microsecond=0).isoformat() + "Z"


def new_run_id() -> str:
    return uuid.uuid4().hex


def short_hash(payload: Any) -> str:
    """Deterministic 8-hex digest of a JSON-serializable payload."""
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]


def build_run_id(
    as_of_date: str,
    payload: Any = None,
    *,
    now: datetime | None = None,
    seed: str | None = None,
) -> str:
    """Spec run_id = <as_of_date>-<HHMMSS>-<short_hash> (spec §1569).

    Deterministic when `now` and `seed`/`payload` are pinned (used by golden tests).
    """
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    hhmmss = moment.strftime("%H%M%S")
    digest = seed[:8] if seed else short_hash(payload if payload is not None else as_of_date)
    return f"{as_of_date}-{hhmmss}-{digest}"


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


def validate_daily_market_snapshot(data: Any) -> list[TrendValidationIssue]:
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
    # Keyed-by-ticker object (spec §1277) — validated when present (M1+ shape).
    tickers = obj.get("tickers")
    if tickers is not None:
        if not isinstance(tickers, dict):
            issues.append(_issue(artifact, "/tickers", "must be an object keyed by ticker"))
        else:
            for sym, entry in tickers.items():
                ent = _require_object(entry, artifact, f"/tickers/{sym}", issues)
                if ent is None:
                    continue
                _require_fields(ent, ["ticker", "metrics", "source_refs"], artifact, f"/tickers/{sym}", issues)
                if "source_refs" in ent:
                    issues.extend(validate_source_refs(
                        ent["source_refs"], artifact, f"/tickers/{sym}/source_refs",
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
    indices = [PHASES.index(p) for p in seen if p in PHASES]
    if any(p not in PHASES for p in seen) or indices != sorted(indices) or len(set(seen)) != len(seen):
        issues.append(_issue(
            artifact, "/phase_statuses",
            "phases must be a strictly ordered subset of the required phases",
        ))
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


def validate_critic_patches(data: Any) -> list[TrendValidationIssue]:
    artifact = "critic-patches"
    issues: list[TrendValidationIssue] = []
    obj = _require_object(data, artifact, "", issues)
    if obj is None:
        return issues
    _require_fields(obj, ["schema_version", "artifact_type", "as_of_date", "patches"], artifact, "", issues)
    _validate_schema_version(obj, artifact, issues)
    if obj.get("artifact_type") != artifact:
        issues.append(_issue(artifact, "/artifact_type", f"must be {artifact!r}"))
    patches = obj.get("patches")
    if not isinstance(patches, list):
        issues.append(_issue(artifact, "/patches", "must be a list"))
        return issues
    for idx, patch in enumerate(patches):
        item = _require_object(patch, artifact, f"/patches/{idx}", issues)
        if item is None:
            continue
        _require_fields(item, ["id", "operation", "write_effect"], artifact, f"/patches/{idx}", issues)
        if "operation" in item and item["operation"] not in CRITIC_OPERATIONS:
            issues.append(_issue(artifact, f"/patches/{idx}/operation", "invalid critic operation"))
        if item.get("write_effect") != "none":
            issues.append(_issue(artifact, f"/patches/{idx}/write_effect", "must be 'none'"))
    unrepaired = obj.get("unrepaired_findings")
    if unrepaired is not None and not isinstance(unrepaired, list):
        issues.append(_issue(artifact, "/unrepaired_findings", "must be a list when present"))
    return issues


# Back-compat alias for the pre-rename name.
validate_daily_snapshot = validate_daily_market_snapshot

VALIDATORS = {
    "daily-market-snapshot": validate_daily_market_snapshot,
    "trend-ledger": validate_trend_ledger,
    "run-status": validate_run_status,
    "validation-findings": validate_validation_findings,
    "monitoring-actions": validate_monitoring_actions,
    "critic-patches": validate_critic_patches,
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


def normalize_freshness(freshness: Any) -> str:
    """Map a raw/legacy freshness label to the canonical enum (brief §6.3)."""
    if freshness in SOURCE_FRESHNESS:
        return str(freshness)
    return FRESHNESS_ALIASES.get(str(freshness), "unknown")


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
        "freshness": normalize_freshness(freshness),
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


def aggregate_run_status(phase_statuses: list[dict[str, Any]], *, provider_failures: bool = False) -> str:
    """Deterministic aggregate precedence (spec §1618): failed > nonconverged >
    completed_with_gaps > running > completed."""
    statuses = [p.get("status") for p in phase_statuses if isinstance(p, dict)]
    if "failed" in statuses:
        return "failed"
    if any(p.get("phase") == "ledger" and p.get("status") == "nonconverged"
           for p in phase_statuses if isinstance(p, dict)):
        return "nonconverged"
    if "completed_with_gaps" in statuses or provider_failures:
        return "completed_with_gaps"
    if "running" in statuses:
        return "running"
    return "completed"


def runtime_exceeded(started_at: str, now: datetime | None = None,
                     cap_minutes: int = RUNTIME_HARD_CAP_MINUTES) -> bool:
    """True when elapsed since started_at exceeds the hard runtime cap (spec §1523)."""
    try:
        start = datetime.fromisoformat(str(started_at).replace("Z", ""))
    except ValueError:
        return False
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return (moment - start).total_seconds() > cap_minutes * 60


def update_phase_status(
    output_dir: Path,
    *,
    as_of_date: str,
    run_id: str,
    phase: str,
    status: str,
    started_at: str | None = None,
    finished_at: str | None = None,
    input_artifacts: list[str] | None = None,
    output_artifacts: list[str] | None = None,
    errors: list[dict[str, Any]] | None = None,
    provider_failures: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Per-phase run-status update (spec §1592-1637).

    Loads the existing run-status, replaces ONLY this phase's entry (preserving the
    others), recomputes the deterministic aggregate (§1618), synthesizes terminal
    ``skipped`` entries for downstream required phases when this phase failed or did not
    converge, and atomically rewrites the file.
    """
    path = output_dir / "run-status.json"
    by_phase: dict[str, dict[str, Any]] = {}
    if path.exists():
        try:
            existing = load_validated_trend_json(path, "run-status")
            for p in existing.get("phase_statuses") or []:
                if isinstance(p, dict) and p.get("phase"):
                    by_phase[p["phase"]] = p
        except TrendValidationError:
            by_phase = {}
    by_phase[phase] = phase_entry(
        phase, status, started_at=started_at, finished_at=finished_at,
        input_artifacts=input_artifacts, output_artifacts=output_artifacts, errors=errors,
    )
    if status in ("failed", "nonconverged"):
        terminal_ts = finished_at or utc_now(now)
        idx = PHASES.index(phase) if phase in PHASES else len(PHASES)
        for downstream in PHASES[idx + 1:]:
            by_phase[downstream] = phase_entry(
                downstream, "skipped", started_at=None, finished_at=terminal_ts,
                errors=[{"phase": phase, "status": status, "reason": "upstream phase terminal"}],
            )
    ordered = [by_phase[p] for p in PHASES if p in by_phase]
    present = {p["phase"] for p in ordered}
    aggregate = aggregate_run_status(ordered, provider_failures=provider_failures)
    # The run stays `running` until the terminal `report` phase has an entry (§1625),
    # unless a phase already failed or did not converge (terminal immediately).
    if aggregate in ("completed", "completed_with_gaps") and "report" not in present:
        aggregate = "running"
    doc = build_run_status(
        as_of_date=as_of_date, run_id=run_id, run_status=aggregate,
        phase_statuses=ordered, generated_at=utc_now(now),
    )
    atomic_write_json(path, doc)
    return doc


def status_from_output_dir(output_dir: Path, as_of_date: str) -> tuple[str, list[dict[str, Any]]]:
    path = output_dir / "run-status.json"
    if not path.exists():
        return new_run_id(), []
    try:
        data = load_validated_trend_json(path, "run-status")
    except TrendValidationError:
        return new_run_id(), []
    return str(data.get("run_id") or new_run_id()), list(data.get("phase_statuses") or [])

