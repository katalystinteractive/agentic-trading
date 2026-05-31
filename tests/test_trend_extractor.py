from trend_extractor import compute_recent_edge_score, enrich_snapshot_record


def test_recent_edge_score_uses_researched_components_and_weights():
    record = {
        "ticker": "ALFA",
        "metrics": {
            "price": 24.5,
            "avg_volume": 1800000,
            "freshness": "fresh",
            "simulation_validation_return_pct": 13.0,
            "watchlist_fitness_delta_pct": 9.0,
            "support_level": {
                "buy_at": 23.4,
                "current_price": 24.5,
                "hold_rate": 0.78,
                "monthly_touch_freq": 1.6,
                "approaches": 6,
                "effective_tier": "Full",
                "zone": "Active",
                "trend": "Improving",
            },
        },
        "source_refs": [{"artifact": "fixture"}],
    }

    score, inputs = compute_recent_edge_score(record)

    assert score is not None
    assert 0 <= score <= 100
    assert {item["component"] for item in inputs} == {
        "support",
        "post_signal_or_simulation",
        "watchlist_or_candidate_delta",
        "liquidity_freshness",
    }
    assert round(sum(item["weight"] for item in inputs), 2) == 1.0


def test_enrich_snapshot_record_preserves_source_refs_and_sets_state():
    enriched = enrich_snapshot_record({
        "ticker": "MISS",
        "metrics": {},
        "source_refs": [{"artifact": "fixture"}],
    })

    assert enriched["ticker"] == "MISS"
    assert enriched["metrics"]["recent_edge_score"] is None
    assert enriched["trend_state"] == "insufficient_evidence"
    assert enriched["source_refs"] == [{"artifact": "fixture"}]

