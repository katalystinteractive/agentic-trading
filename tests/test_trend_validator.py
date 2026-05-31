import json
from pathlib import Path

from daily_trend_snapshot import build_snapshot
from trend_ledger import build_trend_ledger
from trend_validator import findings_artifact, validate_trend_ledger_records, write_findings


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "trend_monitoring"


def test_validator_accepts_complete_ledger(tmp_path):
    sources = json.loads((FIXTURE_DIR / "snapshot_sources.json").read_text())
    ledger = build_trend_ledger(build_snapshot("2026-05-31", sources))

    issues = validate_trend_ledger_records(ledger)

    assert issues == []
    path = write_findings(ledger=ledger, issues=issues, output_dir=tmp_path)
    assert json.loads(path.read_text())["findings"] == []


def test_validator_reports_missing_source_refs_with_evidence():
    ledger = {
        "schema_version": 1,
        "artifact_type": "trend-ledger",
        "as_of_date": "2026-05-31",
        "generated_at": "2026-05-31T00:00:00Z",
        "records": [{
            "ticker": "BAD",
            "metrics": {"recent_edge_score": 70, "recent_edge_score_inputs": []},
            "trend_state": "candidate",
            "source_refs": [],
        }],
    }

    issues = validate_trend_ledger_records(ledger)
    findings = findings_artifact(as_of_date="2026-05-31", issues=issues, source_artifact="trend-ledger")

    assert issues
    assert all(finding["source_refs"] for finding in findings["findings"])

