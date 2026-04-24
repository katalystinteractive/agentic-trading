import json

import expected_edge
import watchlist_tournament as tournament


def test_expected_edge_rewards_target_odds_and_stop_risk():
    weak = expected_edge.score_graph_candidate(
        "dip",
        params={"target_pct": 4.0, "stop_pct": -5.0},
        stats={"trades": 10, "win_rate": 50, "composite": 100},
        features={
            "target_hit_rate": 0.40,
            "stop_hit_rate": 0.35,
            "mean_pnl_pct": 0.2,
            "trade_count": 10,
        },
    )
    strong = expected_edge.score_graph_candidate(
        "dip",
        params={"target_pct": 4.0, "stop_pct": -3.0},
        stats={"trades": 10, "win_rate": 70, "composite": 100},
        features={
            "target_hit_rate": 0.70,
            "stop_hit_rate": 0.10,
            "mean_pnl_pct": 0.6,
            "trade_count": 10,
        },
    )

    assert strong["expected_edge_pct"] > weak["expected_edge_pct"]
    assert strong["edge_adjusted_composite"] > weak["edge_adjusted_composite"]
    assert strong["graph_score"] > weak["graph_score"]


def test_expected_edge_does_not_turn_zero_trade_candidate_into_edge():
    scored = expected_edge.score_graph_candidate(
        "support",
        params={"sell_default": 6.0, "cat_hard_stop": 20},
        stats={"trades": 0, "win_rate": 100, "composite": 100},
        features={"target_hit_rate": 1.0, "stop_hit_rate": 0.0},
    )

    assert scored["edge_components"]["confidence"] == 0
    assert scored["edge_adjusted_composite"] == 0


def test_expected_edge_uses_calibrated_probability_buckets(monkeypatch):
    calibration = {
        "strategies": {
            "dip": {
                "target": [{
                    "lower": 0.0,
                    "upper": 1.0,
                    "samples": 20,
                    "raw_mean": 0.5,
                    "observed": 0.8,
                    "calibrated": 0.8,
                }],
                "stop": [{
                    "lower": 0.0,
                    "upper": 1.0,
                    "samples": 20,
                    "raw_mean": 0.2,
                    "observed": 0.1,
                    "calibrated": 0.1,
                }],
            },
        },
    }
    monkeypatch.setattr(expected_edge, "_load_probability_calibration",
                        lambda: calibration)

    scored = expected_edge.score_graph_candidate(
        "dip",
        params={"target_pct": 4.0, "stop_pct": -3.0},
        stats={"trades": 20, "win_rate": 50, "composite": 100},
        features={
            "target_hit_rate": 0.50,
            "stop_hit_rate": 0.20,
            "mean_pnl_pct": 0.0,
            "trade_count": 20,
        },
    )

    assert scored["edge_components"]["raw_p_target"] == 0.5
    assert scored["edge_components"]["p_target"] == 0.8
    assert scored["edge_components"]["raw_p_stop"] == 0.2
    assert scored["edge_components"]["p_stop"] == 0.1


def test_tournament_uses_edge_adjusted_composite_from_existing_sweep(monkeypatch, tmp_path):
    sweep_path = tmp_path / "support_sweep_results.json"
    sweep_path.write_text(json.dumps({
        "_meta": {"source": "support_parameter_sweeper.py"},
        "RAW": {"stats": {"composite": 100, "edge_adjusted_composite": 50}},
        "EDGE": {"stats": {"composite": 90, "edge_adjusted_composite": 80}},
    }))

    monkeypatch.setattr(tournament, "SWEEP_FILES", {"support": sweep_path})
    tournament._sweep_cache.clear()

    all_sweeps = tournament.load_all_sweeps()

    assert all_sweeps["RAW"] == {"support": 50.0}
    assert all_sweeps["EDGE"] == {"support": 80.0}


def test_tournament_falls_back_to_composite_for_legacy_artifacts(monkeypatch, tmp_path):
    sweep_path = tmp_path / "support_sweep_results.json"
    sweep_path.write_text(json.dumps({
        "_meta": {"source": "support_parameter_sweeper.py"},
        "LEGACY": {"stats": {"composite": 42}},
    }))

    monkeypatch.setattr(tournament, "SWEEP_FILES", {"support": sweep_path})
    tournament._sweep_cache.clear()

    assert tournament.load_all_sweeps()["LEGACY"] == {"support": 42.0}
