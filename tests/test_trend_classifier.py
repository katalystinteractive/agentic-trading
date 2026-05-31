"""M3 — deterministic classifier (§11.1) + derived outputs (§5.3, §11.3-11.5)."""
from trend_extractor import compute_trend_category, enrich_snapshot_record

SUP = {"buy_at": 23.4, "current_price": 24.5, "hold_rate": 0.78, "effective_tier": "Full",
       "zone": "Active", "trend": "Improving", "approaches": 6, "monthly_touch_freq": 1.6}


def test_classifier_per_category():
    assert compute_trend_category({"earnings_blocked": True}) == "EVENT_DRIVEN_SETUP"
    assert compute_trend_category({"days_to_earnings": 10}) == "EVENT_DRIVEN_SETUP"
    assert compute_trend_category({"support_level": SUP, "support_distance_pct": 2.0}) == "SUPPORT_RETEST"
    assert compute_trend_category({"daily_change_pct": -3.0, "median_swing": 12.0}) == "MEAN_REVERSION_PULLBACK"
    assert compute_trend_category({"daily_change_pct": 4.0, "price": 11.0, "high_20d": 10.0}) == "BREAKOUT_ACCELERATION"
    assert compute_trend_category({"atr_pct": 6.0, "atr_pct_avg_60d": 4.0}) == "VOLATILITY_EXPANSION"
    assert compute_trend_category({"rs_excess_5d": 4.0}) == "RELATIVE_STRENGTH_ROTATION"
    assert compute_trend_category({}) == "DORMANT_OR_NO_ACTION"


def test_classifier_precedence_event_beats_support():
    m = {"earnings_blocked": True, "support_level": SUP, "support_distance_pct": 1.0}
    assert compute_trend_category(m) == "EVENT_DRIVEN_SETUP"


def test_support_retest_requires_proximity():
    far = {"support_level": SUP, "support_distance_pct": 8.0}
    assert compute_trend_category(far) != "SUPPORT_RETEST"  # too far -> not a retest


def test_all_missing_record_is_needs_data():
    enriched = enrich_snapshot_record({"ticker": "EMPTY", "metrics": {}, "source_refs": []})
    assert enriched["metrics"]["recent_edge_score"] is None
    assert enriched["readiness"] == "needs_data"
    assert enriched["priority_tier"] == "P4"
    assert enriched["trend_category"] == "DORMANT_OR_NO_ACTION"
    assert set(enriched["metrics"]["missing_edge_components"]) == {
        "support", "post_signal_or_simulation", "watchlist_or_candidate_delta", "liquidity_freshness",
    }


def test_derived_outputs_present_and_typed():
    rec = {"ticker": "ALFA", "metrics": {
        "price": 24.5, "avg_volume": 1_800_000, "atr": 1.2, "freshness": "same_day",
        "simulation_validation_return_pct": 13.0, "watchlist_fitness_delta_pct": 9.0,
        "support_level": SUP, "support_distance_pct": 0.5,
    }, "source_refs": [{"freshness": "same_day"}]}
    e = enrich_snapshot_record(rec)
    assert e["trend_category"] == "SUPPORT_RETEST"
    assert e["readiness"] in ("accepted", "monitor_only")
    assert e["priority_tier"] in ("P1", "P2", "P3", "P4")
    assert e["source_quality"] == "fresh"
    assert e["monitoring_cadence"] in ("intraday", "daily", "weekly", "cooldown")
