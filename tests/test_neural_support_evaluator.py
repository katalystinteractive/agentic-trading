from datetime import date, timedelta

import neural_support_evaluator as nse


def _analysis(last_date=None):
    return {
        "last_date": last_date or date.today().isoformat(),
        "current_price": 10.5,
        "bullet_plan": {
            "active": [{
                "support_price": 10.0,
                "buy_at": 9.9,
                "hold_rate": 70.0,
                "decayed_hold_rate": 65.0,
                "zone": "Active",
                "tier": "Full",
                "support_score": 75.0,
                "support_expected_edge_pct": 3.0,
                "support_score_components": {"p_target": 0.7},
            }],
            "reserve": [{
                "support_price": 8.0,
                "buy_at": 7.9,
                "hold_rate": 55.0,
                "decayed_hold_rate": 50.0,
                "zone": "Reserve",
                "tier": "Std",
                "support_score": 55.0,
                "support_expected_edge_pct": 1.5,
                "support_score_components": {"p_target": 0.5},
            }],
        },
    }


def test_load_support_levels_uses_structured_analyzer_not_markdown(monkeypatch, tmp_path):
    monkeypatch.setattr(nse, "_ROOT", tmp_path)
    monkeypatch.setattr(nse, "analyze_stock_data", lambda ticker: (_analysis(), None))

    levels = nse.load_support_levels("AAA")

    assert levels == [
        {
            "ticker": "AAA",
            "raw_support": 10.0,
            "hold_rate": 65.0,
            "buy_at": 9.9,
            "zone": "Active",
            "tier": "Full",
            "source": "wick_offset_analyzer.analyze_stock_data",
            "last_date": date.today().isoformat(),
            "current_price": 10.5,
            "monthly_touch_freq": 0,
            "dormant": False,
            "support_score": 75.0,
            "support_expected_edge_pct": 3.0,
            "support_score_components": {"p_target": 0.7},
        },
        {
            "ticker": "AAA",
            "raw_support": 8.0,
            "hold_rate": 50.0,
            "buy_at": 7.9,
            "zone": "Reserve",
            "tier": "Std",
            "source": "wick_offset_analyzer.analyze_stock_data",
            "last_date": date.today().isoformat(),
            "current_price": 10.5,
            "monthly_touch_freq": 0,
            "dormant": False,
            "support_score": 55.0,
            "support_expected_edge_pct": 1.5,
            "support_score_components": {"p_target": 0.5},
        },
    ]


def test_load_support_levels_fails_closed_on_stale_structured_analysis(monkeypatch):
    stale_date = (date.today() - timedelta(days=30)).isoformat()
    monkeypatch.setattr(nse, "analyze_stock_data", lambda ticker: (_analysis(stale_date), None))

    assert nse.load_support_levels("AAA", max_age_days=7) == []


def test_scan_opportunities_includes_structured_support_metadata(monkeypatch):
    monkeypatch.setattr(nse, "load_support_levels", lambda ticker: [{
        "raw_support": 10.0,
        "hold_rate": 65.0,
        "buy_at": 9.9,
        "zone": "Active",
        "tier": "Full",
        "source": "wick_offset_analyzer.analyze_stock_data",
        "last_date": date.today().isoformat(),
    }])
    candidates = [{
        "ticker": "AAA",
        "params": {
            "active_pool": 500,
            "active_bullets_max": 5,
            "sell_default": 6.0,
        },
    }]

    opportunities = nse.scan_opportunities(
        candidates,
        prices={"AAA": 10.0},
        portfolio={"pending_orders": {}},
        proximity_pct=5.0,
    )

    assert opportunities == [{
        "ticker": "AAA",
        "price": 10.0,
        "support": 9.9,
        "distance_pct": 1.0,
        "shares": 6,
        "allocated_dollars": 61.9,
        "allocation_multiplier": 0.619,
        "allocation_action": "reduced",
        "allocation_reason": "edge +2.9%; confidence 35%; fill 28%",
        "support_score": 64.8,
        "support_expected_edge_pct": 2.85,
        "support_score_components": {
            "p_target": 0.65,
            "p_break": 0.35,
            "fill_likelihood": 0.519,
            "distance_pct": 1.01,
            "tier_bonus": 6.0,
            "zone_bonus": 3.0,
            "trend_bonus": 0.0,
            "dormant_penalty": 0.0,
            "low_frequency_penalty": 5.0,
            "confidence_penalty": 6.0,
            "capital_lock_penalty": 0.99,
        },
        "pool": 500,
        "sell_target_pct": 6.0,
        "hold_rate": 65.0,
        "zone": "Active",
        "tier": "Full",
        "support_source": "wick_offset_analyzer.analyze_stock_data",
        "support_last_date": date.today().isoformat(),
        "already_ordered": False,
    }]


def test_scan_opportunities_ranks_farther_high_quality_level_over_closer_weak(monkeypatch):
    monkeypatch.setattr(nse, "load_support_levels", lambda ticker: [
        {
            "raw_support": 9.9,
            "hold_rate": 20.0,
            "buy_at": 9.9,
            "zone": "Active",
            "tier": "Half",
            "source": "wick_offset_analyzer.analyze_stock_data",
            "last_date": date.today().isoformat(),
            "monthly_touch_freq": 0.1,
            "recent_approaches": 0,
            "dormant": True,
        },
        {
            "raw_support": 9.65,
            "hold_rate": 85.0,
            "buy_at": 9.65,
            "zone": "Active",
            "tier": "Full",
            "source": "wick_offset_analyzer.analyze_stock_data",
            "last_date": date.today().isoformat(),
            "monthly_touch_freq": 2.0,
            "recent_approaches": 5,
            "trend": "Improving",
        },
    ])
    candidates = [{
        "ticker": "AAA",
        "params": {"active_pool": 500, "active_bullets_max": 5, "sell_default": 6.0},
    }]

    opportunities = nse.scan_opportunities(
        candidates,
        prices={"AAA": 10.0},
        portfolio={"pending_orders": {}},
        proximity_pct=5.0,
    )

    assert [o["support"] for o in opportunities] == [9.65, 9.9]
    assert opportunities[0]["support_score"] > opportunities[1]["support_score"]
    assert opportunities[0]["distance_pct"] > opportunities[1]["distance_pct"]
    assert opportunities[1]["support_score_components"]["dormant_penalty"] > 0
