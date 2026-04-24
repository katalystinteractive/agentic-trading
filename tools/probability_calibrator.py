"""Build calibrated probability buckets for graph-policy expected-edge scoring."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CALIBRATION_PATH = DATA_DIR / "probability_calibration.json"

BIN_EDGES = [0.0, 0.2, 0.4, 0.6, 0.8, 1.000001]
MIN_BUCKET_SAMPLES = 1
SMOOTHING_WEIGHT = 4.0


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _probability(value):
    value = _as_float(value)
    if value > 1:
        value /= 100.0
    return max(0.0, min(1.0, value))


def _load_json(path):
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _iter_entries(data):
    for ticker, entry in data.items():
        if ticker.startswith("_") or not isinstance(entry, dict):
            continue
        yield ticker, entry


def _dip_observed_rates(stats, features):
    trades = _as_float(stats.get("trades")) or _as_float(features.get("trade_count"))
    exits = stats.get("exits") if isinstance(stats.get("exits"), dict) else {}
    if trades <= 0:
        return 0.0, 0.0, 0.0
    target = _as_float(exits.get("TARGET"))
    stop = _as_float(exits.get("STOP"))
    if target == 0 and stop == 0:
        return (
            trades,
            _probability(features.get("target_hit_rate", stats.get("win_rate", 0))),
            _probability(features.get("stop_hit_rate")),
        )
    return trades, _probability(target / trades), _probability(stop / trades)


def _support_observed_rates(stats, features, trades_detail):
    sells = [
        trade for trade in trades_detail
        if isinstance(trade, dict)
        and str(trade.get("side", "")).upper() == "SELL"
        and trade.get("exit_reason") != "SIM_END"
    ]
    trades = _as_float(stats.get("trades")) or _as_float(features.get("trade_count"))
    if sells:
        trades = len(sells)
        target = sum(1 for trade in sells if "TARGET" in str(trade.get("exit_reason", "")))
        stop = sum(
            1 for trade in sells
            if "STOP" in str(trade.get("exit_reason", ""))
            or "CATASTROPHIC" in str(trade.get("exit_reason", ""))
        )
        return trades, _probability(target / trades), _probability(stop / trades)
    if trades <= 0:
        return 0.0, 0.0, 0.0
    return (
        trades,
        _probability(features.get("target_hit_rate", stats.get("win_rate", 0))),
        _probability(features.get("stop_hit_rate")),
    )


def collect_examples(data_dir=DATA_DIR):
    """Collect raw-vs-observed probability examples from existing sweep artifacts."""
    examples = {
        "dip": {"target": [], "stop": []},
        "support": {"target": [], "stop": []},
    }

    dip_data = _load_json(Path(data_dir) / "sweep_results.json")
    for _ticker, entry in _iter_entries(dip_data):
        stats = entry.get("stats") or {}
        features = entry.get("features") or {}
        trades, observed_target, observed_stop = _dip_observed_rates(stats, features)
        if trades <= 0:
            continue
        examples["dip"]["target"].append({
            "raw": _probability(features.get("target_hit_rate", stats.get("win_rate", 0))),
            "observed": observed_target,
            "samples": trades,
        })
        examples["dip"]["stop"].append({
            "raw": _probability(features.get("stop_hit_rate")),
            "observed": observed_stop,
            "samples": trades,
        })

    support_data = _load_json(Path(data_dir) / "support_sweep_results.json")
    for _ticker, entry in _iter_entries(support_data):
        stats = entry.get("stats") or {}
        features = entry.get("features") or {}
        trades = entry.get("trades") or []
        n, observed_target, observed_stop = _support_observed_rates(stats, features, trades)
        if n <= 0:
            continue
        examples["support"]["target"].append({
            "raw": _probability(features.get("target_hit_rate", stats.get("win_rate", 0))),
            "observed": observed_target,
            "samples": n,
        })
        examples["support"]["stop"].append({
            "raw": _probability(features.get("stop_hit_rate")),
            "observed": observed_stop,
            "samples": n,
        })

    return examples


def _bucket_examples(examples):
    buckets = []
    for lower, upper in zip(BIN_EDGES, BIN_EDGES[1:]):
        bucket = [
            ex for ex in examples
            if lower <= ex["raw"] < upper
        ]
        samples = sum(ex["samples"] for ex in bucket)
        if samples < MIN_BUCKET_SAMPLES:
            continue
        raw_weighted = sum(ex["raw"] * ex["samples"] for ex in bucket)
        observed_weighted = sum(ex["observed"] * ex["samples"] for ex in bucket)
        raw_mean = raw_weighted / samples
        observed = observed_weighted / samples
        calibrated = (
            observed_weighted + raw_mean * SMOOTHING_WEIGHT
        ) / (samples + SMOOTHING_WEIGHT)
        buckets.append({
            "lower": round(lower, 3),
            "upper": round(min(1.0, upper), 3),
            "samples": int(samples),
            "raw_mean": round(raw_mean, 4),
            "observed": round(observed, 4),
            "calibrated": round(max(0.0, min(1.0, calibrated)), 4),
        })
    return buckets


def build_calibration(data_dir=DATA_DIR):
    examples = collect_examples(data_dir)
    try:
        from prediction_ledger import summarize_predictions
        live_prediction_summary = summarize_predictions(
            Path(data_dir) / "prediction_ledger.json")
    except Exception:
        live_prediction_summary = {}
    strategies = {}
    total_samples = 0
    for strategy, outcomes in examples.items():
        strategies[strategy] = {}
        for outcome, rows in outcomes.items():
            buckets = _bucket_examples(rows)
            strategies[strategy][outcome] = buckets
            total_samples += sum(bucket["samples"] for bucket in buckets)

    return {
        "_meta": {
            "schema_version": 1,
            "source": "probability_calibrator.py",
            "execution_mode": "graph_policy",
            "updated": date.today().isoformat(),
            "samples": int(total_samples),
            "live_prediction_summary": live_prediction_summary,
        },
        "strategies": strategies,
    }


def write_calibration(data, path=CALIBRATION_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str) + "\n")
    tmp.replace(path)


def main():
    parser = argparse.ArgumentParser(description="Build probability calibration artifact")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--output", type=Path, default=CALIBRATION_PATH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    data = build_calibration(args.data_dir)
    samples = data["_meta"]["samples"]
    print(f"Probability calibration samples: {samples}")
    if args.dry_run:
        print(json.dumps(data, indent=2, default=str))
        return
    write_calibration(data, args.output)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
