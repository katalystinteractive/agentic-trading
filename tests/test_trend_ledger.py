import json
from pathlib import Path

from daily_trend_snapshot import build_snapshot
from trend_contracts import load_validated_trend_json
from trend_ledger import build_trend_ledger, write_ledger_artifacts


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "trend_monitoring"


def test_build_trend_ledger_adds_scores_and_states(tmp_path):
    sources = json.loads((FIXTURE_DIR / "snapshot_sources.json").read_text())
    ledger = build_trend_ledger(build_snapshot("2026-05-31", sources))

    assert ledger["artifact_type"] == "trend-ledger"
    assert {record["ticker"] for record in ledger["records"]} == {"ALFA", "BETA"}
    assert all("recent_edge_score_inputs" in record["metrics"] for record in ledger["records"])

    paths = write_ledger_artifacts(ledger, tmp_path, "run-1")
    assert paths[0].name == "trend-ledger.json"
    assert load_validated_trend_json(paths[0], "trend-ledger")["records"]

