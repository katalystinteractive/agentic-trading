"""M4 — stable_key identity, cross-run merge, transitions (§5.2/§6.6/§6.7/§5.14)."""
import copy

from trend_ledger import build_trend_ledger, build_stable_key


def _rec(ticker, support=23.4):
    return {
        "ticker": ticker,
        "metrics": {
            "price": support + 1.1, "avg_volume": 1_800_000, "atr": 1.2, "freshness": "same_day",
            "simulation_validation_return_pct": 13.0, "watchlist_fitness_delta_pct": 9.0,
            "support_distance_pct": 0.5,
            "support_level": {"support": support, "buy_at": support, "current_price": support + 1.1,
                              "hold_rate": 0.78, "effective_tier": "Full", "zone": "Active",
                              "trend": "Improving", "approaches": 6, "monthly_touch_freq": 1.6,
                              "distance_pct": 0.5},
        },
        "source_refs": [{"artifact": "support_eval", "json_pointer": "/0", "freshness": "same_day"}],
    }


def _snap(as_of, records):
    return {"as_of_date": as_of, "records": records}


def test_first_run_bootstrap_all_new():
    ledger = build_trend_ledger(_snap("2026-05-31", [_rec("ALFA")]), prior_ledger=None)
    assert ledger["prior_ledger_run_id"] is None
    assert "run_id" in ledger and ledger["run_id"].startswith("2026-05-31-")
    rec = ledger["records"][0]
    assert rec["trend_status"] == "new"
    assert rec["first_seen"] == "2026-05-31"
    assert rec["stable_key"] == "ALFA:SUPPORT_RETEST:support_23.40"
    assert ledger["summary"]["by_transition"]["new"] == 1


def test_persisting_preserves_identity():
    l1 = build_trend_ledger(_snap("2026-05-31", [_rec("ALFA")]))
    l2 = build_trend_ledger(_snap("2026-06-01", [_rec("ALFA")]), prior_ledger=l1)
    r2 = l2["records"][0]
    assert r2["trend_status"] == "persisting"
    assert r2["first_seen"] == "2026-05-31"           # carried
    assert r2["last_seen"] == "2026-06-01"
    assert r2["id"] == l1["records"][0]["id"]          # stable id
    assert l2["prior_ledger_run_id"] == l1["run_id"]


def test_new_ticker_and_absent_goes_stale():
    l1 = build_trend_ledger(_snap("2026-05-31", [_rec("ALFA")]))
    l2 = build_trend_ledger(_snap("2026-06-01", [_rec("BETA", support=10.9)]), prior_ledger=l1)
    by_ticker = {r["ticker"]: r for r in l2["records"]}
    assert by_ticker["BETA"]["trend_status"] == "new"
    assert by_ticker["ALFA"]["trend_status"] == "stale"   # absent from snapshot
    assert by_ticker["ALFA"]["absent_streak"] == 1


def test_duplicate_stable_key_merges():
    dup = copy.deepcopy(_rec("ALFA"))
    dup["source_refs"] = [{"artifact": "other", "json_pointer": "/9", "freshness": "same_day"}]
    ledger = build_trend_ledger(_snap("2026-05-31", [_rec("ALFA"), dup]))
    keys = [r["stable_key"] for r in ledger["records"]]
    assert keys.count("ALFA:SUPPORT_RETEST:support_23.40") == 1   # merged to one
    assert ledger["summary"]["duplicate_merged_keys"]
    merged = ledger["records"][0]
    assert len(merged["source_refs"]) == 2   # unioned


def test_stable_key_anchor_shapes():
    assert build_stable_key({"ticker": "x", "trend_category": "EVENT_DRIVEN_SETUP", "metrics": {}}, "2026-05-31") \
        == "X:EVENT_DRIVEN_SETUP:event_2026-05-31"
    assert build_stable_key({"ticker": "y", "trend_category": "DORMANT_OR_NO_ACTION", "metrics": {}}, "2026-05-31") \
        == "Y:DORMANT_OR_NO_ACTION:dormant"
