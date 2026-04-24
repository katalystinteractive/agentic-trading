import json
from datetime import date

import pytest

import watchlist_tournament as tournament
from model_complexity_gate import (
    filter_live_decision_entries,
    is_live_decision_artifact,
)
from neural_artifact_validator import ArtifactValidationError, load_validated_json
from weekly_reoptimize import step_model_complexity_gate


def _write(path, payload):
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _support_sweep_meta(**extra):
    meta = {
        "schema_version": 1,
        "source": "support_parameter_sweeper.py",
        "execution_mode": "support_surgical_daily_ohlc",
        "updated": date.today().isoformat(),
        "total_tickers": 1,
    }
    meta.update(extra)
    return meta


def test_graph_policy_artifact_is_live_eligible_by_default():
    data = {
        "_meta": {"source": "parameter_sweeper.py"},
        "AAA": {"stats": {"composite": 10}},
    }

    assert is_live_decision_artifact(data) is True
    assert filter_live_decision_entries(data) == {
        "AAA": {"stats": {"composite": 10}},
    }


def test_black_box_artifact_is_advisory_until_promoted():
    data = {
        "_meta": {
            "model_family": "black_box_model",
            "promotion_status": "advisory",
        },
        "AAA": {"stats": {"composite": 1000}},
    }

    assert is_live_decision_artifact(data) is False
    with pytest.raises(ValueError):
        filter_live_decision_entries(data)


def test_promoted_black_box_artifact_can_be_live_eligible():
    data = {
        "_meta": {
            "model_family": "black_box_model",
            "promotion_status": "promoted",
            "promotion": {
                "approved": True,
                "baseline_family": "graph_policy",
                "out_of_sample_lift_pct": 3.0,
                "risk_adjusted_lift_pct": 1.5,
            },
        },
        "AAA": {"stats": {"composite": 1000}},
    }

    assert is_live_decision_artifact(data) is True


def test_validator_rejects_unpromoted_black_box_artifact(tmp_path):
    path = tmp_path / "support_sweep_results.json"
    _write(path, {
        "_meta": _support_sweep_meta(
            model_family="black_box_model",
            promotion_status="advisory",
        ),
        "AAA": {
            "params": {"sell_default": 6.0},
            "stats": {"trades": 3},
        },
    })

    with pytest.raises(ArtifactValidationError):
        load_validated_json(path)


def test_tournament_ignores_unpromoted_black_box_sweep(monkeypatch, tmp_path):
    sweep_path = tmp_path / "support_sweep_results.json"
    _write(sweep_path, {
        "_meta": {
            "model_family": "black_box_model",
            "promotion_status": "advisory",
        },
        "AAA": {"stats": {"edge_adjusted_composite": 999}},
    })
    monkeypatch.setattr(tournament, "SWEEP_FILES", {"support": sweep_path})
    tournament._sweep_cache.clear()

    all_sweeps = tournament.load_all_sweeps()
    assert all("support" not in comps for comps in all_sweeps.values())


def test_weekly_gate_blocks_advisory_black_box_artifact(tmp_path):
    path = tmp_path / "candidate_model.json"
    _write(path, {
        "_meta": {
            "model_family": "neural_model",
            "promotion_status": "advisory",
        },
        "AAA": {"score": 99},
    })

    ok, report = step_model_complexity_gate(paths=[path])

    assert ok is False
    assert report["blocked"]
