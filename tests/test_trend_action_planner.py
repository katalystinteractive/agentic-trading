from trend_action_planner import build_monitoring_actions


def _rec(ticker, score, readiness, tier, **extra):
    base = {
        "ticker": ticker, "id": f"TRD-{ticker}", "trend_category": "SUPPORT_RETEST",
        "readiness": readiness, "priority_tier": tier, "trend_status": "new",
        "source_quality": "fresh",
        "metrics": {"recent_edge_score": score},
        "source_refs": [{"artifact": "support_eval", "json_pointer": "/0", "value": 1,
                         "as_of_date": "2026-05-31", "freshness": "same_day", "claim_field": "/metrics"}],
    }
    base.update(extra)
    return base


def test_build_monitoring_actions_marks_recommendation_only():
    ledger = {
        "as_of_date": "2026-05-31",
        "records": [
            _rec("ALFA", 82.0, "accepted", "P1"),
            _rec("BETA", 55.0, "monitor_only", "P3", monitoring_cadence="daily"),
        ],
    }
    actions = build_monitoring_actions(ledger)
    by_ticker = {a["ticker"]: a for a in actions["actions"]}
    assert by_ticker["ALFA"]["action"] == "PROMOTE_TO_SIMULATION"
    assert by_ticker["BETA"]["action"] == "WATCH_DAILY"
    assert all(a["write_effect"] == "none" for a in actions["actions"])
    assert actions["as_of_date"] == "2026-05-31"
    assert "quotas" in actions and actions["quotas"]["used_monitored_tickers"] == 2
