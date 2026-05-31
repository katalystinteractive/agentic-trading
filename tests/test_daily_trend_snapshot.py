import json
from pathlib import Path

import daily_trend_snapshot as snapshot
from trend_contracts import load_validated_trend_json


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "trend_monitoring"


def test_build_snapshot_from_fixture_merges_sources():
    sources = json.loads((FIXTURE_DIR / "snapshot_sources.json").read_text())

    data = snapshot.build_snapshot("2026-05-31", sources)

    assert data["artifact_type"] == "daily-market-snapshot"
    tickers = {record["ticker"] for record in data["records"]}
    assert tickers == {"ALFA", "BETA"}
    alfa = next(record for record in data["records"] if record["ticker"] == "ALFA")
    assert alfa["metrics"]["simulation_validation_return_pct"] == 13.0
    assert len(alfa["source_refs"]) >= 4


def test_snapshot_cli_fixture_writes_only_output_dir(tmp_path):
    code = snapshot.main([
        "--as-of", "2026-05-31",
        "--fixture", str(FIXTURE_DIR),
        "--output-dir", str(tmp_path),
    ])

    assert code == 0
    artifact = load_validated_trend_json(tmp_path / "daily-market-snapshot.json", "daily-market-snapshot")
    assert len(artifact["records"]) == 2
    assert (tmp_path / "daily-market-snapshot.md").exists()
    assert (tmp_path / "run-status.json").exists()
    assert list((tmp_path / "run-history" / "2026-05-31").glob("*/*"))

