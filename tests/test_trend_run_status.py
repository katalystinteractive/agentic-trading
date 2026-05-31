"""§5.6 — per-phase run-status lifecycle: ownership, precedence, skipped synthesis."""
from trend_contracts import update_phase_status, load_validated_trend_json


def _read(tmp):
    return load_validated_trend_json(tmp / "run-status.json", "run-status")


def test_phase_ownership_and_running_until_complete(tmp_path):
    update_phase_status(tmp_path, as_of_date="2026-05-31", run_id="R1",
                        phase="snapshot", status="completed", started_at="t0", finished_at="t1")
    doc = _read(tmp_path)
    assert doc["run_status"] == "running"      # downstream phases not done yet
    assert [p["phase"] for p in doc["phase_statuses"]] == ["snapshot"]

    update_phase_status(tmp_path, as_of_date="2026-05-31", run_id="R1",
                        phase="ledger", status="completed", started_at="t1", finished_at="t2")
    doc = _read(tmp_path)
    assert doc["run_status"] == "running"
    # snapshot entry preserved, ledger appended in canonical order
    assert [p["phase"] for p in doc["phase_statuses"]] == ["snapshot", "ledger"]


def test_full_chain_terminal_completed(tmp_path):
    for ph in ("snapshot", "ledger", "actions"):
        update_phase_status(tmp_path, as_of_date="2026-05-31", run_id="R1",
                            phase=ph, status="completed", started_at="t", finished_at="t")
    doc = update_phase_status(tmp_path, as_of_date="2026-05-31", run_id="R1",
                              phase="report", status="completed", started_at="t", finished_at="t")
    assert doc["run_status"] == "completed"
    assert doc["finished_at"] is not None


def test_nonconverged_ledger_synthesizes_skipped_downstream(tmp_path):
    update_phase_status(tmp_path, as_of_date="2026-05-31", run_id="R1",
                        phase="snapshot", status="completed", started_at="t", finished_at="t")
    doc = update_phase_status(tmp_path, as_of_date="2026-05-31", run_id="R1",
                              phase="ledger", status="nonconverged", started_at="t", finished_at="t")
    by_phase = {p["phase"]: p for p in doc["phase_statuses"]}
    assert doc["run_status"] == "nonconverged"
    assert by_phase["actions"]["status"] == "skipped"
    assert by_phase["report"]["status"] == "skipped"
    assert by_phase["actions"]["started_at"] is None


def test_provider_failures_force_completed_with_gaps(tmp_path):
    for ph in ("snapshot", "ledger", "actions"):
        update_phase_status(tmp_path, as_of_date="2026-05-31", run_id="R1",
                            phase=ph, status="completed", started_at="t", finished_at="t")
    doc = update_phase_status(tmp_path, as_of_date="2026-05-31", run_id="R1",
                              phase="report", status="completed", started_at="t", finished_at="t",
                              provider_failures=True)
    assert doc["run_status"] == "completed_with_gaps"
