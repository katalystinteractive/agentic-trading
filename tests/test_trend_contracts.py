import json
from pathlib import Path

import pytest

from trend_contracts import (
    CRITIC_OPERATIONS,
    FINDING_CATEGORIES,
    FINDING_SEVERITIES,
    RUN_STATUSES,
    SCHEMA_VERSION,
    SOURCE_FRESHNESS,
    TrendValidationError,
    VALIDATORS,
    build_run_id,
    load_validated_trend_json,
    normalize_freshness,
    source_ref,
    validate_critic_patches,
    validate_source_ref,
    validate_source_refs,
)

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schemas" / "trend_monitoring"


def test_canonical_freshness_enum_and_aliases():
    assert SOURCE_FRESHNESS == ("same_day", "fresh_cache", "weekly_context", "stale", "unknown")
    assert normalize_freshness("fresh") == "same_day"      # legacy alias
    assert normalize_freshness("cached") == "fresh_cache"
    assert normalize_freshness("bogus") == "unknown"
    ref = source_ref(artifact="x", json_pointer="/a", value=1, as_of_date=None,
                     freshness="fresh", claim_field="/records/0/x")
    assert ref["freshness"] == "same_day"


def test_run_id_format_is_deterministic_when_pinned():
    import datetime as _dt
    rid = build_run_id("2026-05-31", {"x": 1}, now=_dt.datetime(2026, 5, 31, 14, 30, 5), seed=None)
    assert rid.startswith("2026-05-31-143005-")
    assert len(rid.split("-")[-1]) == 8
    assert build_run_id("2026-05-31", {"x": 1}, now=_dt.datetime(2026, 5, 31, 14, 30, 5)) == rid


def test_all_artifacts_have_a_validator_and_schema_file():
    for artifact in ("daily-market-snapshot", "trend-ledger", "validation-findings",
                     "critic-patches", "monitoring-actions", "run-status"):
        assert artifact in VALIDATORS, f"missing validator for {artifact}"
        assert (SCHEMA_DIR / f"{artifact}.schema.json").exists(), f"missing schema for {artifact}"


def _full_required_payload(artifact, required):
    # Plausible-typed value for each top-level required field.
    defaults = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": artifact,
        "as_of_date": "2026-05-31",
        "generated_at": "2026-05-31T00:00:00Z",
        "run_id": "2026-05-31-000000-deadbeef",
        "run_status": "running",
        "phase_statuses": [],
        "records": [],
        "findings": [],
        "actions": [],
        "patches": [],
    }
    return {f: defaults.get(f) for f in required}


def test_schema_required_fields_are_enforced_by_validator():
    # schema.required must be a subset of what the validator enforces: a full
    # required payload yields no missing-field issue, and dropping any one does.
    for artifact in ("daily-market-snapshot", "trend-ledger", "validation-findings",
                     "critic-patches", "monitoring-actions", "run-status"):
        schema = json.loads((SCHEMA_DIR / f"{artifact}.schema.json").read_text())
        validator = VALIDATORS[artifact]
        required = schema["required"]
        full = _full_required_payload(artifact, required)
        for field in required:
            payload = dict(full)
            payload.pop(field, None)
            missing = [i for i in validator(payload)
                       if i.path.endswith(f"/{field}") or i.path == f"/{field}"]
            assert missing, f"{artifact}: validator did not flag missing required '{field}'"


def test_schema_enums_match_contract_enums():
    finding_schema = json.loads((SCHEMA_DIR / "validation-findings.schema.json").read_text())
    assert tuple(finding_schema["enums"]["finding_category"]) == FINDING_CATEGORIES
    assert tuple(finding_schema["enums"]["severity"]) == FINDING_SEVERITIES
    critic_schema = json.loads((SCHEMA_DIR / "critic-patches.schema.json").read_text())
    assert tuple(critic_schema["enums"]["operation"]) == CRITIC_OPERATIONS
    run_schema = json.loads((SCHEMA_DIR / "run-status.schema.json").read_text())
    assert tuple(run_schema["enums"]["run_status"]) == RUN_STATUSES


def test_critic_patches_validator_rejects_bad_operation_and_write_effect():
    bad = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "critic-patches",
        "as_of_date": "2026-05-31",
        "patches": [{"id": "p1", "operation": "bogus_op", "write_effect": "write"}],
    }
    issues = validate_critic_patches(bad)
    paths = {i.path for i in issues}
    assert "/patches/0/operation" in paths
    assert "/patches/0/write_effect" in paths


def test_source_ref_contract_accepts_nullable_as_of_date():
    ref = source_ref(
        artifact="fixture",
        json_pointer="/records/0",
        value={"ticker": "ALFA"},
        as_of_date=None,
        freshness="fresh",
        claim_field="ticker",
    )

    assert validate_source_ref(ref, "daily-market-snapshot", "/source_refs/0") == []


def test_source_refs_require_json_pointer_and_known_freshness():
    issues = validate_source_refs(
        [{"artifact": "x", "json_pointer": "records/0", "value": 1,
          "as_of_date": "2026-05-31", "freshness": "new", "claim_field": "x"}],
        "daily-market-snapshot",
        "/source_refs",
    )

    assert {issue.path for issue in issues} == {
        "/source_refs/0/json_pointer",
        "/source_refs/0/freshness",
    }


def test_load_validated_trend_json_raises_for_bad_schema_version(tmp_path):
    path = tmp_path / "daily-market-snapshot.json"
    path.write_text(json.dumps({
        "schema_version": SCHEMA_VERSION + 1,
        "artifact_type": "daily-market-snapshot",
        "as_of_date": "2026-05-31",
        "generated_at": "2026-05-31T00:00:00Z",
        "records": [],
    }))

    with pytest.raises(TrendValidationError):
        load_validated_trend_json(path, "daily-market-snapshot")

