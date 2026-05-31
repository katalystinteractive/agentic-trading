import json
from pathlib import Path

import daily_trend_snapshot
from trend_contracts import load_validated_trend_json
from trend_phase_ledger import run_ledger_phase


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "trend_monitoring"


def test_phase_ledger_writes_status_and_downstream_running(tmp_path):
    assert daily_trend_snapshot.main([
        "--as-of", "2026-05-31",
        "--fixture", str(FIXTURE_DIR),
        "--output-dir", str(tmp_path),
    ]) == 0

    code, paths = run_ledger_phase(
        "2026-05-31",
        tmp_path / "daily-market-snapshot.json",
        tmp_path,
    )

    assert code == 0
    assert {path.name for path in paths} >= {
        "trend-ledger.json",
        "validation-findings.json",
        "critic-patches.json",
        "run-status.json",
    }
    status = load_validated_trend_json(tmp_path / "run-status.json", "run-status")
    # §5.6 per-phase ownership: each phase writes only its own entry. After the ledger
    # phase, run-status carries snapshot + ledger; the run stays `running` until report.
    assert status["run_status"] == "running"
    by_phase = {p["phase"]: p for p in status["phase_statuses"]}
    assert set(by_phase) == {"snapshot", "ledger"}
    assert by_phase["snapshot"]["status"] in ("completed", "completed_with_gaps")
    assert by_phase["ledger"]["status"] == "completed"
