import json

import pytest

from trend_contracts import (
    SCHEMA_VERSION,
    TrendValidationError,
    load_validated_trend_json,
    source_ref,
    validate_source_ref,
    validate_source_refs,
)


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

