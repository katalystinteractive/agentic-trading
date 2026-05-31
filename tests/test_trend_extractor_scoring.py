"""M2 — scoring correctness: ±25 delta, liquidity penalty model, §11.10 denominator."""
from trend_extractor import (
    _score_delta_pct,
    _score_liquidity_freshness,
    compute_recent_edge_score,
)


def test_delta_score_uses_pm25_saturation():
    assert _score_delta_pct(25) == 100.0
    assert _score_delta_pct(0) == 50.0
    assert _score_delta_pct(-25) == 0.0
    assert _score_delta_pct(40) == 100.0   # clamps
    assert _score_delta_pct(-40) == 0.0


def test_liquidity_penalty_model():
    full, _ = _score_liquidity_freshness({"avg_volume": 1_000_000, "atr": 1.0, "freshness": "same_day"})
    assert full == 100.0
    partial_stale, _ = _score_liquidity_freshness(
        {"avg_volume": 1_000_000, "atr": 1.0, "freshness": "stale", "provider_partial": True}
    )
    assert partial_stale == 40.0  # -30 partial -30 stale
    missing_atr_low_vol, _ = _score_liquidity_freshness({"avg_volume": 100_000, "freshness": "same_day"})
    assert missing_atr_low_vol == 60.0  # -20 low vol -20 missing atr


def test_renormalization_when_only_support_present():
    # Only the support component present -> score equals its normalized value, NOT 0.40x it.
    record = {
        "ticker": "ONLYSUP",
        "metrics": {
            "price": 24.5,
            "support_level": {
                "buy_at": 23.4, "current_price": 24.5, "hold_rate": 0.78,
                "effective_tier": "Full", "zone": "Active", "trend": "Improving",
                "approaches": 6, "monthly_touch_freq": 1.6,
            },
        },
        "source_refs": [],
    }
    score, inputs = compute_recent_edge_score(record)
    comp = {i["component"]: i for i in inputs}
    assert comp["support"]["missing"] is False
    assert comp["post_signal_or_simulation"]["missing"] is True
    assert comp["watchlist_or_candidate_delta"]["missing"] is True
    assert comp["liquidity_freshness"]["missing"] is True
    assert score == comp["support"]["normalized_value"]


def test_full_record_denominator_is_one():
    record = {
        "ticker": "FULL",
        "metrics": {
            "price": 24.5, "avg_volume": 1_800_000, "atr": 1.2, "freshness": "same_day",
            "simulation_validation_return_pct": 13.0, "watchlist_fitness_delta_pct": 9.0,
            "support_level": {"buy_at": 23.4, "current_price": 24.5, "hold_rate": 0.78,
                              "effective_tier": "Full", "zone": "Active", "trend": "Improving",
                              "approaches": 6, "monthly_touch_freq": 1.6},
        },
        "source_refs": [],
    }
    score, inputs = compute_recent_edge_score(record)
    present = [i for i in inputs if not i["missing"]]
    expected = round(sum(i["normalized_value"] * i["weight"] for i in present)
                     / sum(i["weight"] for i in present), 2)
    assert score == expected
    assert abs(sum(i["weight"] for i in present) - 1.0) < 1e-9  # all four present
