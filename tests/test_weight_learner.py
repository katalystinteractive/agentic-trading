import json

import weight_learner as wl


def test_update_weights_strengthens_profitable_fired_inputs():
    updated = wl.update_weights(
        [{
            "pnl": 10,
            "fired_inputs": {
                "AAA:dip_gate": {"AAA:dip_level": 5.0},
            },
        }],
        {"AAA:dip_gate": {"AAA:dip_level": 0.5}},
        learning_rate=0.1,
        norm_divisor=10.0,
    )

    assert updated["AAA:dip_gate"]["AAA:dip_level"] == 0.55


def test_update_weights_attenuates_losing_fired_inputs():
    updated = wl.update_weights(
        [{
            "pnl": -10,
            "fired_inputs": {
                "AAA:bounce_gate": {"AAA:bounce_level": 5.0},
            },
        }],
        {"AAA:bounce_gate": {"AAA:bounce_level": 0.5}},
        learning_rate=0.1,
        norm_divisor=10.0,
    )

    assert updated["AAA:bounce_gate"]["AAA:bounce_level"] == 0.45


def test_update_weights_clamps_to_zero_and_one_without_inhibitory_weights():
    updated = wl.update_weights(
        [
            {
                "pnl": -10,
                "fired_inputs": {
                    "AAA:dip_gate": {"AAA:dip_level": 100.0},
                },
            },
            {
                "pnl": 10,
                "fired_inputs": {
                    "AAA:bounce_gate": {"AAA:bounce_level": 100.0},
                },
            },
        ],
        {
            "AAA:dip_gate": {"AAA:dip_level": 0.02},
            "AAA:bounce_gate": {"AAA:bounce_level": 0.99},
        },
        learning_rate=0.1,
        norm_divisor=10.0,
    )

    assert updated["AAA:dip_gate"]["AAA:dip_level"] == 0.0
    assert updated["AAA:bounce_gate"]["AAA:bounce_level"] == 1.0


def test_save_weights_keeps_support_gates_diagnostic_only(monkeypatch, tmp_path):
    weights_path = tmp_path / "synapse_weights.json"
    monkeypatch.setattr(wl, "WEIGHTS_PATH", weights_path)

    weights = {
        "AAA:dip_gate": {"AAA:dip_level": 0.8},
        "AAA:profit_gate": {"AAA:pnl_pct": 0.7},
        "AAA:hold_gate": {"AAA:days_held": 0.6},
        "AAA:stop_gate": {"AAA:pnl_pct": 0.5},
    }
    wl.save_weights(weights, {
        "source": "unit_test",
        "total_trades": 4,
        "wins": 3,
        "losses": 1,
    })

    data = json.loads(weights_path.read_text())

    assert data["weights"] == {
        "AAA:dip_gate": {"AAA:dip_level": 0.8},
    }
    assert data["diagnostic_weights"] == {
        "AAA:profit_gate": {"AAA:pnl_pct": 0.7},
        "AAA:hold_gate": {"AAA:days_held": 0.6},
        "AAA:stop_gate": {"AAA:pnl_pct": 0.5},
    }
    assert data["_meta"]["stats"]["policy_synapses"] == 1
    assert data["_meta"]["stats"]["diagnostic_synapses"] == 3
    assert data["_meta"]["stats"]["total_synapses"] == 4


def test_save_weights_migrates_existing_support_gates_out_of_policy(monkeypatch, tmp_path):
    weights_path = tmp_path / "synapse_weights.json"
    weights_path.write_text(json.dumps({
        "_meta": {
            "schema_version": 1,
            "source": "weight_learner.py",
            "execution_mode": "graph_policy",
            "updated": "2026-04-25",
        },
        "weights": {
            "OLD:profit_gate": {"OLD:pnl_pct": 0.4},
        },
        "regime_weights": {},
    }))
    monkeypatch.setattr(wl, "WEIGHTS_PATH", weights_path)

    wl.save_weights(
        {"AAA:bounce_gate": {"AAA:bounce_level": 0.9}},
        {"source": "unit_test"},
    )

    data = json.loads(weights_path.read_text())

    assert data["weights"] == {
        "AAA:bounce_gate": {"AAA:bounce_level": 0.9},
    }
    assert data["diagnostic_weights"] == {
        "OLD:profit_gate": {"OLD:pnl_pct": 0.4},
    }


def test_split_policy_and_diagnostic_weights_treats_unknown_as_diagnostic():
    policy, diagnostic = wl.split_policy_and_diagnostic_weights({
        "AAA:candidate": {"AAA:dip_gate": 1.0},
        "AAA:custom_support_gate": {"AAA:metric": 0.5},
    })

    assert policy == {"AAA:candidate": {"AAA:dip_gate": 1.0}}
    assert diagnostic == {"AAA:custom_support_gate": {"AAA:metric": 0.5}}
