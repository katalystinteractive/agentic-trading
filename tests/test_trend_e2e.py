"""M7 — deterministic end-to-end: snapshot -> ledger -> gates -> actions -> report."""
import datetime
import json
from pathlib import Path

import pytest

from daily_trend_snapshot import build_snapshot
from trend_ledger import build_trend_ledger
from trend_validator import apply_strategy_gates
from trend_action_planner import build_monitoring_actions
from trend_reporter import render_report
from trend_contracts import aggregate_run_status, validate_artifact

FIX = Path(__file__).resolve().parent / "fixtures" / "trend_monitoring" / "snapshot_sources_v2.json"
NOW = datetime.datetime(2026, 5, 31, 21, 0, 0)


def _fake_ohlcv():
    pd = pytest.importorskip("pandas")
    idx = pd.date_range("2026-04-01", periods=40, freq="D")

    def frame(base):
        return pd.DataFrame({"Open": [base] * 40, "High": [base * 1.03] * 40,
                             "Low": [base * 0.97] * 40,
                             "Close": [base * 0.99] + [base] * 39, "Volume": [1_000_000] * 40},
                            index=idx)
    raw = pd.concat({"ALFA": frame(24.5), "BETA": frame(11.25)}, axis=1)
    return lambda tickers, **kw: raw


@pytest.fixture
def offline(monkeypatch):
    import trend_sources as ts
    monkeypatch.setattr(ts, "get_sector", lambda t: {"sector": "Tech", "broad_sector": "Technology"})
    monkeypatch.setattr(ts, "get_earnings_status",
                        lambda t, d=None: {"earnings_status": "CLEAR", "earnings_blocked": False, "days_to_earnings": 40})
    monkeypatch.setattr(ts, "compute_overlaps",
                        lambda t: {"portfolio_overlap": False, "candidate_overlap": False, "watchlist_overlap": False})


def _run():
    sources = json.loads(FIX.read_text())
    snap = build_snapshot("2026-05-31", sources, downloader=_fake_ohlcv(), now=NOW, live=True)
    ledger = build_trend_ledger(snap, prior_ledger=None, run_id="2026-05-31-210000-deadbeef", now=NOW)
    apply_strategy_gates(ledger)
    actions = build_monitoring_actions(ledger)
    report = render_report(ledger, actions)
    return snap, ledger, actions, report


def test_full_chain_validates_and_is_shaped(offline):
    snap, ledger, actions, report = _run()
    assert validate_artifact(snap, "daily-market-snapshot") == []
    assert validate_artifact(ledger, "trend-ledger") == []
    assert validate_artifact(actions, "monitoring-actions") == []
    assert "All recommendations are read-only." in report
    assert "Quotas: monitored" in report
    assert "ALFA" in report and "BETA" in report
    # terminal run status with all phases completed
    phases = [{"phase": p, "status": "completed"} for p in ("snapshot", "ledger", "actions", "report")]
    assert aggregate_run_status(phases, provider_failures=bool(snap["provider_failures"])) in (
        "completed", "completed_with_gaps")


def test_full_chain_is_deterministic(offline):
    _, ledger1, actions1, report1 = _run()
    _, ledger2, actions2, report2 = _run()
    assert report1 == report2
    # ledger records identical except volatile generated_at (not in records)
    assert [r["stable_key"] for r in ledger1["records"]] == [r["stable_key"] for r in ledger2["records"]]
    assert ledger1["run_id"] == ledger2["run_id"] == "2026-05-31-210000-deadbeef"
    assert actions1["quotas"] == actions2["quotas"]
