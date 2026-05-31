import json
from pathlib import Path

from daily_trend_snapshot import build_snapshot
from trend_action_planner import build_monitoring_actions
from trend_contracts import atomic_write_json
from trend_ledger import build_trend_ledger, write_ledger_artifacts
from trend_reporter import main, render_report


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "trend_monitoring"


def test_reporter_mentions_read_only_boundary():
    sources = json.loads((FIXTURE_DIR / "snapshot_sources.json").read_text())
    ledger = build_trend_ledger(build_snapshot("2026-05-31", sources))
    actions = build_monitoring_actions(ledger)

    report = render_report(ledger, actions)

    assert "read-only" in report
    assert "ALFA" in report


def test_reporter_cli_writes_final_status(tmp_path):
    sources = json.loads((FIXTURE_DIR / "snapshot_sources.json").read_text())
    ledger = build_trend_ledger(build_snapshot("2026-05-31", sources))
    ledger_path = write_ledger_artifacts(ledger, tmp_path, "run-1")[0]
    atomic_write_json(tmp_path / "monitoring-actions.json", build_monitoring_actions(ledger))

    code = main([
        "--as-of", "2026-05-31",
        "--ledger", str(ledger_path),
        "--output-dir", str(tmp_path),
    ])

    assert code == 0
    assert (tmp_path / "daily-trend-report.md").exists()
    status = json.loads((tmp_path / "run-status.json").read_text())
    assert status["run_status"] == "completed"

