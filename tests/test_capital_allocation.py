from shared_utils import compute_position_allocation


def test_higher_expected_edge_receives_larger_allocation_within_cap():
    weak = compute_position_allocation(
        100,
        10,
        features={"fill_likelihood": 0.8},
        score={"expected_edge_pct": 0.5, "edge_components": {"confidence": 0.8, "p_stop": 0.10}},
        max_dollars=150,
    )
    strong = compute_position_allocation(
        100,
        10,
        features={"fill_likelihood": 0.8},
        score={"expected_edge_pct": 5.0, "edge_components": {"confidence": 0.8, "p_stop": 0.10}},
        max_dollars=150,
    )

    assert strong["allocated_dollars"] > weak["allocated_dollars"]
    assert strong["shares"] > weak["shares"]
    assert strong["cost"] <= 150


def test_high_edge_low_confidence_and_stop_risk_is_capped_down():
    allocation = compute_position_allocation(
        100,
        10,
        features={"fill_likelihood": 0.9},
        score={"expected_edge_pct": 8.0, "edge_components": {"confidence": 0.1, "p_stop": 0.8}},
        max_dollars=150,
    )

    assert allocation["allocation_action"] == "reduced"
    assert allocation["allocated_dollars"] < 100
    assert "stop risk" in allocation["allocation_reason"]


def test_dormant_dead_capital_penalty_reduces_allocation():
    fresh = compute_position_allocation(
        100,
        10,
        features={"hold_rate": 70, "fill_likelihood": 0.8},
    )
    dormant = compute_position_allocation(
        100,
        10,
        features={"hold_rate": 70, "fill_likelihood": 0.8, "dormant": True},
    )

    assert dormant["allocated_dollars"] < fresh["allocated_dollars"]
    assert "dormant penalty" in dormant["allocation_reason"]
