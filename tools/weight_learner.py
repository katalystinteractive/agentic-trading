"""Weight learner — train synapse weights from trade outcomes.

Reads sweep_results.json (per-trade data with fired_inputs),
applies reward-modulated Hebbian updates, writes synapse_weights.json.

Usage:
    python3 tools/weight_learner.py                          # train from sweep results
    python3 tools/weight_learner.py --learning-rate 0.02     # custom learning rate
    python3 tools/weight_learner.py --epochs 5               # multiple passes
    python3 tools/weight_learner.py --dry-run                # show weights without writing
"""
import sys
import json
import argparse
from pathlib import Path
from collections import defaultdict
from datetime import date
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
SWEEP_RESULTS_PATH = _ROOT / "data" / "sweep_results.json"
WEIGHTS_PATH = _ROOT / "data" / "synapse_weights.json"


# ---------------------------------------------------------------------------
# Weight update
# ---------------------------------------------------------------------------

def update_weights(trades, current_weights, learning_rate=0.01, norm_divisor=10.0):
    """Reward-modulated Hebbian update.

    For each closed trade:
      outcome = +1 if pnl > 0 else -1
      For each synapse that fired:
        weight += learning_rate * outcome * normalized_input
        weight = clamp(weight, 0.0, 1.0)

    NOTE: Clamping to [0, 1] means negative correlations cannot be learned.
    This is a known limitation — expand to [-1, 1] if experimentation shows need.

    Returns updated weights dict.
    """
    updated = deepcopy(current_weights)

    for trade in trades:
        fired = trade.get("fired_inputs")
        if not fired:
            continue

        pnl = trade.get("pnl", 0)
        outcome = 1.0 if pnl > 0 else -1.0

        for gate_name, input_values in fired.items():
            if gate_name not in updated:
                updated[gate_name] = {}
            node_weights = updated[gate_name]

            for input_name, input_val in input_values.items():
                # Normalize input to [0, 1] range
                norm_val = min(abs(float(input_val)) / norm_divisor, 1.0)
                w = node_weights.get(input_name, 1.0)
                w += learning_rate * outcome * norm_val
                w = max(0.0, min(1.0, w))
                node_weights[input_name] = round(w, 4)

    return updated


def train_from_sweep(sweep_path=None, learning_rate=0.01, epochs=1):
    """Load sweep results, extract all trades, train weights.

    Returns (weights_dict, stats_dict).
    """
    path = sweep_path or SWEEP_RESULTS_PATH
    if not path.exists():
        print(f"*Sweep results not found at {path}. Run parameter_sweeper.py first.*")
        return None, None

    with open(path) as f:
        sweep_data = json.load(f)

    # Collect all trades from all tickers
    all_trades = []
    for tk, result in sweep_data.items():
        if tk.startswith("_"):
            continue
        trades = result.get("trades", [])
        all_trades.extend(trades)

    if not all_trades:
        print("*No trades found in sweep results.*")
        return None, None

    # Load existing weights or start fresh
    weights = {}
    if WEIGHTS_PATH.exists():
        with open(WEIGHTS_PATH) as f:
            data = json.load(f)
        weights = data.get("weights", {})

    # Train
    n_positive = sum(1 for t in all_trades if t.get("pnl", 0) > 0)
    n_negative = len(all_trades) - n_positive
    print(f"Training on {len(all_trades)} trades "
          f"({n_positive} wins, {n_negative} losses)")
    print(f"Learning rate: {learning_rate}, Epochs: {epochs}\n")

    for epoch in range(epochs):
        # Shuffle trades for each epoch (reduces order bias)
        np.random.seed(42 + epoch)
        shuffled = list(all_trades)
        np.random.shuffle(shuffled)

        weights = update_weights(shuffled, weights, learning_rate)

        # Stats per epoch
        w_values = []
        for gate_weights in weights.values():
            w_values.extend(gate_weights.values())
        if w_values:
            print(f"  Epoch {epoch + 1}: "
                  f"mean_w={np.mean(w_values):.4f} "
                  f"min_w={min(w_values):.4f} "
                  f"max_w={max(w_values):.4f} "
                  f"synapses={len(w_values)}")

    stats = {
        "total_trades": len(all_trades),
        "wins": n_positive,
        "losses": n_negative,
        "epochs": epochs,
        "learning_rate": learning_rate,
        "total_synapses": sum(len(v) for v in weights.values()),
    }

    return weights, stats


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_weights(weights, stats, regime="Neutral"):
    """Write synapse_weights.json with regime support."""
    data = {"_meta": {"version": 1, "updated": date.today().isoformat()}}

    # Load existing to preserve other regimes
    if WEIGHTS_PATH.exists():
        with open(WEIGHTS_PATH) as f:
            data = json.load(f)

    data["_meta"]["updated"] = date.today().isoformat()
    data["_meta"]["stats"] = stats

    # Store base weights (used when no regime-specific override exists)
    data["weights"] = weights

    # Initialize regime_weights structure if needed
    if "regime_weights" not in data:
        data["regime_weights"] = {}

    with open(WEIGHTS_PATH, "w") as f:
        json.dump(data, f, indent=2)

    return WEIGHTS_PATH


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Weight Learner")
    parser.add_argument("--learning-rate", type=float, default=0.01,
                        help="Learning rate (default: 0.01)")
    parser.add_argument("--epochs", type=int, default=3,
                        help="Training epochs (default: 3)")
    parser.add_argument("--sweep-file", type=str, default=None,
                        help="Path to sweep_results.json")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show weights without writing")
    args = parser.parse_args()

    sweep_path = Path(args.sweep_file) if args.sweep_file else None
    weights, stats = train_from_sweep(sweep_path, args.learning_rate, args.epochs)

    if weights is None:
        return

    # Print learned weights
    print(f"\n### Learned Synapse Weights\n")
    print(f"| Gate | Input | Weight |")
    print(f"| :--- | :--- | :--- |")
    for gate_name in sorted(weights.keys()):
        for input_name, w in sorted(weights[gate_name].items()):
            marker = ""
            if w < 0.5:
                marker = " ↓"
            elif w > 1.0:
                marker = " ↑"  # shouldn't happen with clamping
            elif w != 1.0:
                marker = f" (Δ{w - 1.0:+.3f})"
            print(f"| {gate_name} | {input_name} | {w:.4f}{marker} |")

    if args.dry_run:
        print(f"\n--- DRY RUN — weights not saved ---")
    else:
        out_path = save_weights(weights, stats)
        print(f"\nWeights saved to {out_path}")
        print(f"Synapses: {stats['total_synapses']}")


if __name__ == "__main__":
    main()
