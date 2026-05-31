"""M6 — quota ranking/overflow (§6.2), action selection (§11.2), run-status (§5.6/§5.12)."""
import datetime

from trend_action_planner import build_monitoring_actions, _intended_action
from trend_contracts import (
    MAX_HIGH_PRIORITY_REFRESHES,
    MAX_MONITORED_TICKERS,
    MAX_REVIEW_ACTIONS,
    aggregate_run_status,
    runtime_exceeded,
    validate_artifact,
)


def _ref():
    return {"artifact": "support_eval", "json_pointer": "/0", "value": 1,
            "as_of_date": "2026-05-31", "freshness": "same_day", "claim_field": "/metrics"}


def _accepted_p1_rec(i):
    return {
        "ticker": f"T{i:04d}", "id": f"TRD-{i}", "trend_category": "SUPPORT_RETEST",
        "readiness": "accepted", "priority_tier": "P1", "trend_status": "new",
        "source_quality": "fresh", "human_action_required": True, "monitoring_cadence": "intraday",
        "metrics": {"recent_edge_score": 600 - i}, "source_refs": [_ref()],
    }


def test_quota_caps_and_overflow():
    ledger = {"as_of_date": "2026-05-31", "records": [_accepted_p1_rec(i) for i in range(600)]}
    out = build_monitoring_actions(ledger)
    q = out["quotas"]
    assert q["used_monitored_tickers"] == MAX_MONITORED_TICKERS == 500
    assert q["used_high_priority_refreshes"] == MAX_HIGH_PRIORITY_REFRESHES == 75
    assert q["used_review_actions"] == MAX_REVIEW_ACTIONS == 30
    assert q["excluded_overflow"] == 100
    assert len(out["actions"]) == 500
    # top-30 keep PROMOTE; 31-75 deferred promote; 76-500 capped to WATCH_DAILY
    assert q["deferred_refresh"] == 500 - 75   # promote-like capped for non-top-75
    assert q["deferred_review"] == 75 - 30      # promote allowed but deferred
    assert validate_artifact(out, "monitoring-actions") == []


def test_top_record_promotes_and_overflow_is_watch_daily():
    ledger = {"as_of_date": "2026-05-31", "records": [_accepted_p1_rec(i) for i in range(600)]}
    out = build_monitoring_actions(ledger)
    by_ticker = {a["ticker"]: a for a in out["actions"]}
    assert by_ticker["T0000"]["action"] == "PROMOTE_TO_SIMULATION"   # rank 1, top-30
    assert by_ticker["T0000"]["deferred"] is False
    assert by_ticker["T0100"]["action"] == "WATCH_DAILY"             # rank 101, capped
    assert by_ticker["T0100"]["deferred"] is True


def test_intended_action_rules():
    assert _intended_action({"readiness": "accepted", "priority_tier": "P1",
                             "trend_category": "EVENT_DRIVEN_SETUP", "trend_status": "new"}) == "PROMOTE_TO_DEEP_DIVE"
    assert _intended_action({"readiness": "accepted", "priority_tier": "P2",
                             "trend_category": "SUPPORT_RETEST", "trend_status": "new"}) == "ADD_TO_CANDIDATE_POOL"
    assert _intended_action({"readiness": "monitor_only", "priority_tier": "P3",
                             "trend_category": "SUPPORT_RETEST", "trend_status": "persisting",
                             "monitoring_cadence": "daily"}) == "WATCH_DAILY"
    assert _intended_action({"readiness": "accepted", "priority_tier": "P1",
                             "trend_category": "RELATIVE_STRENGTH_ROTATION", "trend_status": "new",
                             "monitoring_only_category": True}) == "WATCH_INTRADAY"
    assert _intended_action({"trend_status": "retired", "readiness": "accepted",
                             "priority_tier": "P1", "trend_category": "SUPPORT_RETEST"}) == "COOLDOWN_OR_DROP"


def test_aggregate_run_status_precedence():
    base = [{"phase": "snapshot", "status": "completed"}, {"phase": "ledger", "status": "completed"}]
    assert aggregate_run_status(base) == "completed"
    assert aggregate_run_status(base, provider_failures=True) == "completed_with_gaps"
    assert aggregate_run_status(base + [{"phase": "actions", "status": "failed"}]) == "failed"
    assert aggregate_run_status([{"phase": "ledger", "status": "nonconverged"}]) == "nonconverged"
    assert aggregate_run_status(base + [{"phase": "actions", "status": "running"}]) == "running"


def test_runtime_guard():
    start = "2026-05-31T12:00:00"
    assert runtime_exceeded(start, now=datetime.datetime(2026, 5, 31, 13, 40, 0)) is True   # 100 min > 90
    assert runtime_exceeded(start, now=datetime.datetime(2026, 5, 31, 12, 10, 0)) is False  # 10 min
