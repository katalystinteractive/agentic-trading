import json
from pathlib import Path

from daily_trend_snapshot import build_snapshot
from trend_action_planner import build_monitoring_actions, main
from trend_ledger import build_trend_ledger, write_ledger_artifacts


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "trend_monitoring"


def test_action_planner_outputs_recommendation_only_actions(tmp_path):
    sources = json.loads((FIXTURE_DIR / "snapshot_sources.json").read_text())
    ledger = build_trend_ledger(build_snapshot("2026-05-31", sources))

    actions = build_monitoring_actions(ledger)

    assert actions["actions"]
    assert {action["write_effect"] for action in actions["actions"]} == {"none"}
    assert all(action["source_refs"] for action in actions["actions"])


def test_action_planner_cli_writes_actions_and_status(tmp_path):
    sources = json.loads((FIXTURE_DIR / "snapshot_sources.json").read_text())
    ledger = build_trend_ledger(build_snapshot("2026-05-31", sources))
    ledger_path = write_ledger_artifacts(ledger, tmp_path, "run-1")[0]

    code = main([
        "--as-of", "2026-05-31",
        "--ledger", str(ledger_path),
        "--output-dir", str(tmp_path),
    ])

    assert code == 0
    assert (tmp_path / "monitoring-actions.json").exists()
    assert (tmp_path / "monitoring-actions.md").exists()
    assert (tmp_path / "run-status.json").exists()

