import json
from datetime import date, timedelta

import pytest

from neural_artifact_validator import (
    ArtifactValidationError,
    load_validated_json,
    validate_directory,
)


def _write(path, payload):
    path.write_text(json.dumps(payload, indent=2))


def _meta(source, execution_mode, updated=None):
    return {
        "schema_version": 1,
        "source": source,
        "execution_mode": execution_mode,
        "updated": updated or date.today().isoformat(),
    }


def _write_valid_artifacts(data_dir):
    _write(data_dir / "neural_candidates.json", {
        "_meta": {
            **_meta("neural_candidate_discoverer.py",
                    "intraday_5min_neural_replay"),
            "passed_gates": 1,
            "top_n": 30,
        },
        "candidates": [{
            "ticker": "AAA",
            "val_trades": 5,
            "params": {
                "dip_threshold": 1.0,
                "bounce_threshold": 0.3,
                "target_pct": 4.0,
                "stop_pct": -3.0,
                "breadth_threshold": 0.5,
            },
            "features": {"trade_count": 5},
        }],
    })
    _write(data_dir / "neural_support_candidates.json", {
        "_meta": {
            **_meta("neural_support_discoverer.py",
                    "support_surgical_daily_ohlc"),
            "passed_gates": 1,
        },
        "candidates": [{
            "ticker": "AAA",
            "trades": 3,
            "params": {"sell_default": 6.0},
            "features": {"trade_count": 3},
            "overfit": False,
        }],
    })
    _write(data_dir / "neural_watchlist_profiles.json", {
        "_meta": {
            **_meta("neural_watchlist_sweeper.py",
                    "support_surgical_daily_ohlc"),
            "tracked_tickers": 1,
            "profiles_created": 1,
        },
        "candidates": [{
            "ticker": "AAA",
            "params": {"sell_default": 6.0},
            "stats": {"trades": 3},
        }],
    })
    _write(data_dir / "synapse_weights.json", {
        "_meta": {
            **_meta("weight_learner.py", "graph_policy"),
            "stats": {
                "policy_synapses": 1,
                "diagnostic_synapses": 0,
                "total_synapses": 1,
            },
        },
        "weights": {"AAA:dip_gate": {"AAA:dip_level": 0.8}},
        "diagnostic_weights": {},
        "regime_weights": {},
    })
    _write(data_dir / "ticker_profiles.json", {
        "_meta": {
            **_meta("ticker_clusterer.py", "intraday_5min_neural_replay"),
            "cluster_profiles": {"0": {"size": 1}},
        },
        "AAA": {
            "dip_threshold": 1.0,
            "bounce_threshold": 0.3,
            "target_pct": 4.0,
            "stop_pct": -3.0,
            "confidence": 80.0,
        },
    })
    _write(data_dir / "sweep_results.json", {
        "_meta": {
            **_meta("parameter_sweeper.py", "intraday_5min_neural_replay"),
            "tickers_swept": 1,
        },
        "AAA": {
            "params": {"dip_threshold": 1.0},
            "stats": {"trades": 5},
            "features": {"trade_count": 5},
            "trades": [],
        },
    })
    _write(data_dir / "support_sweep_results.json", {
        "_meta": {
            **_meta("support_parameter_sweeper.py",
                    "support_surgical_daily_ohlc"),
            "total_tickers": 1,
        },
        "AAA": {
            "params": {"sell_default": 6.0},
            "stats": {"trades": 3},
        },
    })
    _write(data_dir / "probability_calibration.json", {
        "_meta": {
            **_meta("probability_calibrator.py", "graph_policy"),
            "samples": 12,
        },
        "strategies": {
            "dip": {
                "target": [{
                    "lower": 0.0,
                    "upper": 1.0,
                    "samples": 5,
                    "raw_mean": 0.5,
                    "observed": 0.6,
                    "calibrated": 0.58,
                }],
                "stop": [],
            },
            "support": {
                "target": [],
                "stop": [{
                    "lower": 0.0,
                    "upper": 1.0,
                    "samples": 7,
                    "raw_mean": 0.3,
                    "observed": 0.2,
                    "calibrated": 0.22,
                }],
            },
        },
    })


def _messages(issues):
    return [issue.message for issue in issues]


def test_valid_neural_artifacts_pass(tmp_path):
    _write_valid_artifacts(tmp_path)

    assert validate_directory(tmp_path) == []


def test_stale_artifact_fails_freshness_check(tmp_path):
    _write_valid_artifacts(tmp_path)
    payload = json.loads((tmp_path / "neural_candidates.json").read_text())
    payload["_meta"]["updated"] = (date.today() - timedelta(days=30)).isoformat()
    _write(tmp_path / "neural_candidates.json", payload)

    messages = _messages(validate_directory(tmp_path, max_age_days=14))

    assert any("artifact is stale" in message for message in messages)


def test_dip_candidate_requires_minimum_validation_trades(tmp_path):
    _write_valid_artifacts(tmp_path)
    payload = json.loads((tmp_path / "neural_candidates.json").read_text())
    payload["candidates"][0]["val_trades"] = 2
    _write(tmp_path / "neural_candidates.json", payload)

    messages = _messages(validate_directory(tmp_path))

    assert any("val_trades < 5" in message for message in messages)


def test_support_sweep_metadata_count_must_match_entries(tmp_path):
    _write_valid_artifacts(tmp_path)
    payload = json.loads((tmp_path / "support_sweep_results.json").read_text())
    payload["_meta"]["total_tickers"] = 99
    _write(tmp_path / "support_sweep_results.json", payload)

    messages = _messages(validate_directory(tmp_path))

    assert "total_tickers must match ticker entry count" in messages


def test_missing_schema_version_fails_contract(tmp_path):
    _write_valid_artifacts(tmp_path)
    payload = json.loads((tmp_path / "synapse_weights.json").read_text())
    del payload["_meta"]["schema_version"]
    _write(tmp_path / "synapse_weights.json", payload)

    messages = _messages(validate_directory(tmp_path))

    assert any("schema_version" in message for message in messages)


def test_load_validated_json_fails_closed_on_invalid_artifact(tmp_path):
    _write_valid_artifacts(tmp_path)
    payload = json.loads((tmp_path / "neural_support_candidates.json").read_text())
    payload["candidates"][0]["overfit"] = True
    _write(tmp_path / "neural_support_candidates.json", payload)

    with pytest.raises(ArtifactValidationError):
        load_validated_json(tmp_path / "neural_support_candidates.json")


def test_support_diagnostic_gates_are_rejected_from_policy_weights(tmp_path):
    _write_valid_artifacts(tmp_path)
    payload = json.loads((tmp_path / "synapse_weights.json").read_text())
    payload["weights"]["AAA:profit_gate"] = {"AAA:pnl_pct": 0.5}
    payload["_meta"]["stats"] = {
        "policy_synapses": 2,
        "diagnostic_synapses": 0,
        "total_synapses": 2,
    }
    _write(tmp_path / "synapse_weights.json", payload)

    messages = _messages(validate_directory(tmp_path))

    assert any("must not be in policy weights" in message for message in messages)


def test_probability_calibration_bucket_shape_is_validated(tmp_path):
    _write_valid_artifacts(tmp_path)
    payload = json.loads((tmp_path / "probability_calibration.json").read_text())
    del payload["strategies"]["dip"]["target"][0]["calibrated"]
    _write(tmp_path / "probability_calibration.json", payload)

    messages = _messages(validate_directory(tmp_path))

    assert any("missing field 'calibrated'" in message for message in messages)
