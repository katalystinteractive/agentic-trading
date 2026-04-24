"""Validate generated neural/graph-policy artifacts.

This is a promotion gate for generated JSON under data/. It validates schema
shape, metadata freshness, schema version, execution-mode tags, and count
consistency before artifacts are trusted by operators or live/reporting tools.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from model_complexity_gate import is_live_decision_artifact, live_decision_reason


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

SCHEMA_VERSION = 1
DEFAULT_MAX_AGE_DAYS = 14
MIN_DIP_VALIDATION_TRADES = 5
MIN_SUPPORT_TRADES = 3

EXECUTION_INTRADAY_NEURAL = "intraday_5min_neural_replay"
EXECUTION_SUPPORT_DAILY = "support_surgical_daily_ohlc"
EXECUTION_GRAPH_POLICY = "graph_policy"


@dataclass(frozen=True)
class ArtifactSpec:
    filename: str
    kind: str
    source: str
    execution_mode: str | None


SPECS = [
    ArtifactSpec("neural_candidates.json", "dip_candidates",
                 "neural_candidate_discoverer.py", EXECUTION_INTRADAY_NEURAL),
    ArtifactSpec("neural_support_candidates.json", "support_candidates",
                 "neural_support_discoverer.py", EXECUTION_SUPPORT_DAILY),
    ArtifactSpec("neural_watchlist_profiles.json", "watchlist_profiles",
                 "neural_watchlist_sweeper.py", EXECUTION_SUPPORT_DAILY),
    ArtifactSpec("synapse_weights.json", "weights",
                 "weight_learner.py", EXECUTION_GRAPH_POLICY),
    ArtifactSpec("ticker_profiles.json", "ticker_profiles",
                 "ticker_clusterer.py", EXECUTION_INTRADAY_NEURAL),
    ArtifactSpec("sweep_results.json", "dip_sweep",
                 "parameter_sweeper.py", EXECUTION_INTRADAY_NEURAL),
    ArtifactSpec("support_sweep_results.json", "support_sweep",
                 "support_parameter_sweeper.py", EXECUTION_SUPPORT_DAILY),
    ArtifactSpec("probability_calibration.json", "probability_calibration",
                 "probability_calibrator.py", EXECUTION_GRAPH_POLICY),
]


@dataclass
class Issue:
    artifact: str
    message: str
    severity: str = "ERROR"


class ArtifactValidationError(RuntimeError):
    """Raised when a generated neural artifact fails validation."""

    def __init__(self, path: Path, issues: list[Issue]):
        self.path = path
        self.issues = issues
        detail = "; ".join(issue.message for issue in issues[:5])
        if len(issues) > 5:
            detail += f"; ... {len(issues) - 5} more"
        super().__init__(f"{path.name} failed validation: {detail}")


def _spec_for_filename(filename: str) -> ArtifactSpec | None:
    for spec in SPECS:
        if spec.filename == filename:
            return spec
    return None


def _load_json(path: Path, issues: list[Issue]) -> dict[str, Any] | None:
    if not path.exists():
        issues.append(Issue(path.name, "missing artifact"))
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        issues.append(Issue(path.name, f"invalid JSON: {exc}"))
        return None
    if not isinstance(data, dict):
        issues.append(Issue(path.name, "artifact root must be an object"))
        return None
    return data


def _parse_updated(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(text).date()
        except ValueError:
            return None


def _entry_count(data: dict[str, Any], key: str | None = None) -> int:
    if key:
        values = data.get(key)
        return len(values) if isinstance(values, list) else 0
    return sum(1 for name in data if not name.startswith("_"))


def _meta(data: dict[str, Any], spec: ArtifactSpec, issues: list[Issue],
          max_age_days: int, allow_stale: bool) -> dict[str, Any]:
    meta = data.get("_meta")
    if not isinstance(meta, dict):
        issues.append(Issue(spec.filename, "missing _meta object"))
        return {}

    version = meta.get("schema_version")
    if not isinstance(version, int) or version < SCHEMA_VERSION:
        issues.append(Issue(
            spec.filename,
            f"_meta.schema_version must be >= {SCHEMA_VERSION}",
        ))

    source = meta.get("source")
    if source != spec.source:
        issues.append(Issue(
            spec.filename,
            f"_meta.source must be {spec.source!r}, got {source!r}",
        ))

    if spec.execution_mode:
        mode = meta.get("execution_mode")
        if mode != spec.execution_mode:
            issues.append(Issue(
                spec.filename,
                f"_meta.execution_mode must be {spec.execution_mode!r}, got {mode!r}",
            ))

    updated = _parse_updated(meta.get("updated"))
    if updated is None:
        issues.append(Issue(spec.filename, "_meta.updated must be an ISO date"))
    elif not allow_stale:
        age = (date.today() - updated).days
        if age < 0:
            issues.append(Issue(spec.filename, "_meta.updated is in the future"))
        elif age > max_age_days:
            issues.append(Issue(
                spec.filename,
                f"artifact is stale: {age} days old, max {max_age_days}",
            ))

    return meta


def _validate_model_complexity_gate(data: dict[str, Any], spec: ArtifactSpec,
                                    issues: list[Issue]) -> None:
    if not is_live_decision_artifact(data):
        issues.append(Issue(spec.filename, live_decision_reason(data)))


def _require_number(obj: dict[str, Any], field: str, artifact: str,
                    issues: list[Issue]) -> None:
    value = obj.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        issues.append(Issue(artifact, f"field {field!r} must be numeric"))


def _require_fields(obj: dict[str, Any], fields: list[str], artifact: str,
                    label: str, issues: list[Issue]) -> None:
    for field in fields:
        if field not in obj:
            issues.append(Issue(artifact, f"{label} missing field {field!r}"))


def _validate_dip_candidates(data: dict[str, Any], spec: ArtifactSpec,
                             meta: dict[str, Any], issues: list[Issue]) -> None:
    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        issues.append(Issue(spec.filename, "candidates must be a list"))
        return
    if meta.get("passed_gates") is not None and meta["passed_gates"] < len(candidates):
        issues.append(Issue(spec.filename, "passed_gates is smaller than candidates length"))
    if meta.get("top_n") is not None and meta["top_n"] < len(candidates):
        issues.append(Issue(spec.filename, "top_n is smaller than candidates length"))

    for idx, item in enumerate(candidates):
        label = f"candidates[{idx}]"
        if not isinstance(item, dict):
            issues.append(Issue(spec.filename, f"{label} must be an object"))
            continue
        _require_fields(item, ["ticker", "val_trades", "params", "features"],
                        spec.filename, label, issues)
        if item.get("val_trades", 0) < MIN_DIP_VALIDATION_TRADES:
            issues.append(Issue(
                spec.filename,
                f"{label} has val_trades < {MIN_DIP_VALIDATION_TRADES}",
            ))
        params = item.get("params")
        if isinstance(params, dict):
            _require_fields(
                params,
                ["dip_threshold", "bounce_threshold", "target_pct",
                 "stop_pct", "breadth_threshold"],
                spec.filename,
                f"{label}.params",
                issues,
            )


def _validate_support_candidates(data: dict[str, Any], spec: ArtifactSpec,
                                 meta: dict[str, Any], issues: list[Issue]) -> None:
    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        issues.append(Issue(spec.filename, "candidates must be a list"))
        return
    if meta.get("passed_gates") is not None and meta["passed_gates"] < len(candidates):
        issues.append(Issue(spec.filename, "passed_gates is smaller than candidates length"))

    for idx, item in enumerate(candidates):
        label = f"candidates[{idx}]"
        if not isinstance(item, dict):
            issues.append(Issue(spec.filename, f"{label} must be an object"))
            continue
        _require_fields(item, ["ticker", "trades", "params", "features"],
                        spec.filename, label, issues)
        if item.get("trades", 0) < MIN_SUPPORT_TRADES:
            issues.append(Issue(
                spec.filename,
                f"{label} has trades < {MIN_SUPPORT_TRADES}",
            ))
        if item.get("overfit") is True:
            issues.append(Issue(spec.filename, f"{label} is flagged overfit"))


def _validate_watchlist_profiles(data: dict[str, Any], spec: ArtifactSpec,
                                 meta: dict[str, Any], issues: list[Issue]) -> None:
    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        issues.append(Issue(spec.filename, "candidates must be a list"))
        return
    if meta.get("profiles_created") != len(candidates):
        issues.append(Issue(spec.filename, "profiles_created must match candidates length"))
    if meta.get("tracked_tickers", 0) < len(candidates):
        issues.append(Issue(spec.filename, "tracked_tickers is smaller than candidates length"))
    for idx, item in enumerate(candidates):
        if not isinstance(item, dict):
            issues.append(Issue(spec.filename, f"candidates[{idx}] must be an object"))
            continue
        _require_fields(item, ["ticker", "params", "stats"],
                        spec.filename, f"candidates[{idx}]", issues)


def _validate_weights(data: dict[str, Any], spec: ArtifactSpec,
                      meta: dict[str, Any], issues: list[Issue]) -> None:
    weights = data.get("weights")
    if not isinstance(weights, dict):
        issues.append(Issue(spec.filename, "weights must be an object"))
        return
    diagnostic = data.get("diagnostic_weights", {})
    if diagnostic is None:
        diagnostic = {}
    if not isinstance(diagnostic, dict):
        issues.append(Issue(spec.filename, "diagnostic_weights must be an object"))
        diagnostic = {}

    def _edge_count(weight_map: dict[str, Any]) -> int:
        return sum(len(edges) for edges in weight_map.values()
                   if isinstance(edges, dict))

    def _check_map(weight_map: dict[str, Any], label: str) -> None:
        for node, edges in weight_map.items():
            if not isinstance(edges, dict):
                issues.append(Issue(spec.filename, f"{label}[{node!r}] must be an object"))
                continue
            for edge, value in edges.items():
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    issues.append(Issue(spec.filename, f"{label} {node}.{edge} must be numeric"))
                elif not 0 <= value <= 1:
                    issues.append(Issue(spec.filename, f"{label} {node}.{edge} outside [0, 1]"))

    _check_map(weights, "weight")
    _check_map(diagnostic, "diagnostic_weight")

    for node in weights:
        if any(node.endswith(suffix) for suffix in (":profit_gate", ":hold_gate", ":stop_gate")):
            issues.append(Issue(
                spec.filename,
                f"diagnostic support gate {node!r} must not be in policy weights",
            ))
    for node in diagnostic:
        if any(node.endswith(suffix) for suffix in (":dip_gate", ":bounce_gate", ":candidate")):
            issues.append(Issue(
                spec.filename,
                f"policy gate {node!r} must not be in diagnostic_weights",
            ))

    policy_count = _edge_count(weights)
    diagnostic_count = _edge_count(diagnostic)

    stats = meta.get("stats")
    if isinstance(stats, dict):
        if stats.get("policy_synapses") is not None and stats["policy_synapses"] != policy_count:
            issues.append(Issue(spec.filename, "stats.policy_synapses must match policy weight count"))
        if stats.get("diagnostic_synapses") is not None and stats["diagnostic_synapses"] != diagnostic_count:
            issues.append(Issue(spec.filename, "stats.diagnostic_synapses must match diagnostic weight count"))
        if stats.get("total_synapses") is not None:
            expected_total = policy_count + diagnostic_count
            if stats["total_synapses"] != expected_total:
                issues.append(Issue(spec.filename, "stats.total_synapses must match policy + diagnostic weight count"))

    if not isinstance(data.get("regime_weights"), dict):
        issues.append(Issue(spec.filename, "regime_weights must be an object"))


def _validate_ticker_profiles(data: dict[str, Any], spec: ArtifactSpec,
                              meta: dict[str, Any], issues: list[Issue]) -> None:
    profiles = {k: v for k, v in data.items() if not k.startswith("_")}
    if not profiles:
        issues.append(Issue(spec.filename, "must contain at least one ticker profile"))
        return
    cluster_profiles = meta.get("cluster_profiles")
    if not isinstance(cluster_profiles, dict):
        issues.append(Issue(spec.filename, "_meta.cluster_profiles must be an object"))
    else:
        expected = sum(cp.get("size", 0) for cp in cluster_profiles.values()
                       if isinstance(cp, dict))
        if expected and expected != len(profiles):
            issues.append(Issue(spec.filename, "cluster profile sizes must match profile count"))

    for ticker, profile in profiles.items():
        if not isinstance(profile, dict):
            issues.append(Issue(spec.filename, f"{ticker} profile must be an object"))
            continue
        for field in ["dip_threshold", "bounce_threshold", "target_pct",
                      "stop_pct", "confidence"]:
            _require_number(profile, field, spec.filename, issues)


def _validate_sweep(data: dict[str, Any], spec: ArtifactSpec,
                    meta: dict[str, Any], issues: list[Issue],
                    support: bool) -> None:
    entries = {k: v for k, v in data.items() if not k.startswith("_")}
    if not entries:
        issues.append(Issue(spec.filename, "must contain at least one ticker entry"))
    if meta.get("tickers_swept") is not None and meta["tickers_swept"] != len(entries):
        issues.append(Issue(spec.filename, "tickers_swept must match ticker entry count"))
    if meta.get("total_tickers") is not None and meta["total_tickers"] != len(entries):
        issues.append(Issue(spec.filename, "total_tickers must match ticker entry count"))
    if meta.get("profitable") is not None and meta["profitable"] != len(entries):
        issues.append(Issue(spec.filename, "profitable must match ticker entry count"))

    for ticker, entry in entries.items():
        if not isinstance(entry, dict):
            issues.append(Issue(spec.filename, f"{ticker} entry must be an object"))
            continue
        _require_fields(entry, ["params", "stats"], spec.filename, ticker, issues)
        if not support:
            _require_fields(entry, ["features", "trades"], spec.filename, ticker, issues)


def _validate_probability_calibration(data: dict[str, Any], spec: ArtifactSpec,
                                      meta: dict[str, Any],
                                      issues: list[Issue]) -> None:
    strategies = data.get("strategies")
    if not isinstance(strategies, dict):
        issues.append(Issue(spec.filename, "strategies must be an object"))
        return
    if meta.get("samples") is not None and meta["samples"] < 0:
        issues.append(Issue(spec.filename, "_meta.samples must be non-negative"))
    for strategy in ("dip", "support"):
        outcomes = strategies.get(strategy)
        if not isinstance(outcomes, dict):
            issues.append(Issue(spec.filename, f"strategies.{strategy} must be an object"))
            continue
        for outcome in ("target", "stop"):
            buckets = outcomes.get(outcome)
            if not isinstance(buckets, list):
                issues.append(Issue(spec.filename, f"{strategy}.{outcome} buckets must be a list"))
                continue
            for idx, bucket in enumerate(buckets):
                label = f"{strategy}.{outcome}[{idx}]"
                if not isinstance(bucket, dict):
                    issues.append(Issue(spec.filename, f"{label} must be an object"))
                    continue
                _require_fields(
                    bucket,
                    ["lower", "upper", "samples", "raw_mean", "observed", "calibrated"],
                    spec.filename,
                    label,
                    issues,
                )
                for field in ("lower", "upper", "raw_mean", "observed", "calibrated"):
                    value = bucket.get(field)
                    if not isinstance(value, (int, float)) or isinstance(value, bool):
                        issues.append(Issue(spec.filename, f"{label}.{field} must be numeric"))
                    elif not 0 <= value <= 1:
                        issues.append(Issue(spec.filename, f"{label}.{field} outside [0, 1]"))
                samples = bucket.get("samples")
                if not isinstance(samples, int) or samples < 0:
                    issues.append(Issue(spec.filename, f"{label}.samples must be a non-negative integer"))
                if isinstance(bucket.get("lower"), (int, float)) and isinstance(bucket.get("upper"), (int, float)):
                    if bucket["lower"] >= bucket["upper"]:
                        issues.append(Issue(spec.filename, f"{label}.lower must be below upper"))


def validate_artifact(path: Path, spec: ArtifactSpec, max_age_days: int,
                      allow_stale: bool = False) -> list[Issue]:
    issues: list[Issue] = []
    data = _load_json(path, issues)
    if data is None:
        return issues
    meta = _meta(data, spec, issues, max_age_days, allow_stale)
    _validate_model_complexity_gate(data, spec, issues)

    if spec.kind == "dip_candidates":
        _validate_dip_candidates(data, spec, meta, issues)
    elif spec.kind == "support_candidates":
        _validate_support_candidates(data, spec, meta, issues)
    elif spec.kind == "watchlist_profiles":
        _validate_watchlist_profiles(data, spec, meta, issues)
    elif spec.kind == "weights":
        _validate_weights(data, spec, meta, issues)
    elif spec.kind == "ticker_profiles":
        _validate_ticker_profiles(data, spec, meta, issues)
    elif spec.kind == "dip_sweep":
        _validate_sweep(data, spec, meta, issues, support=False)
    elif spec.kind == "support_sweep":
        _validate_sweep(data, spec, meta, issues, support=True)
    elif spec.kind == "probability_calibration":
        _validate_probability_calibration(data, spec, meta, issues)
    else:
        issues.append(Issue(spec.filename, f"unknown artifact kind {spec.kind!r}"))

    return issues


def load_validated_json(path: Path, max_age_days: int = DEFAULT_MAX_AGE_DAYS,
                        allow_stale: bool = False) -> dict[str, Any]:
    """Load one known artifact after validating its promotion contract."""
    spec = _spec_for_filename(path.name)
    if spec is None:
        raise ValueError(f"No neural artifact spec registered for {path.name}")
    issues = validate_artifact(path, spec, max_age_days=max_age_days,
                               allow_stale=allow_stale)
    if any(issue.severity == "ERROR" for issue in issues):
        raise ArtifactValidationError(path, issues)
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ArtifactValidationError(
            path, [Issue(path.name, "artifact root must be an object")])
    return data


def validate_directory(data_dir: Path, max_age_days: int = DEFAULT_MAX_AGE_DAYS,
                       allow_stale: bool = False,
                       filenames: set[str] | None = None) -> list[Issue]:
    issues: list[Issue] = []
    for spec in SPECS:
        if filenames and spec.filename not in filenames:
            continue
        issues.extend(validate_artifact(
            data_dir / spec.filename,
            spec,
            max_age_days=max_age_days,
            allow_stale=allow_stale,
        ))
    return issues


def _print_issues(issues: list[Issue]) -> None:
    if not issues:
        print("Neural artifact validation passed.")
        return
    for issue in issues:
        print(f"{issue.severity}: {issue.artifact}: {issue.message}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate neural generated artifacts")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR,
                        help="Directory containing generated JSON artifacts")
    parser.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS,
                        help=f"Maximum artifact age in days (default: {DEFAULT_MAX_AGE_DAYS})")
    parser.add_argument("--allow-stale", action="store_true",
                        help="Skip freshness failures while still validating shape")
    parser.add_argument("--file", action="append", default=None,
                        help="Validate only this artifact filename; can be repeated")
    args = parser.parse_args()

    issues = validate_directory(
        args.data_dir,
        max_age_days=args.max_age_days,
        allow_stale=args.allow_stale,
        filenames=set(args.file or []) or None,
    )
    _print_issues(issues)
    return 1 if any(issue.severity == "ERROR" for issue in issues) else 0


if __name__ == "__main__":
    raise SystemExit(main())
