"""Historical Trade Trainer — train synapse weights from existing backtest trades.

Extracts ~3,400 trades from candidate-gate backtest results, reconstructs
entry-time fired_inputs, and trains synapse weights via Hebbian learning.

Usage:
    python3 tools/historical_trade_trainer.py              # train from all trades
    python3 tools/historical_trade_trainer.py --epochs 5    # more training epochs
    python3 tools/historical_trade_trainer.py --dry-run      # show stats without updating
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
from weight_learner import update_weights, save_weights

_ROOT = Path(__file__).resolve().parent.parent
GATE_DIR = _ROOT / "data" / "backtest" / "candidate-gate"
WEIGHTS_PATH = _ROOT / "data" / "synapse_weights.json"


def extract_trades():
    """Load all sell trades from candidate-gate backtest results.

    Returns list of trade dicts with pnl field added.
    """
    all_trades = []
    tickers_found = 0
    tickers_empty = 0

    for ticker_dir in sorted(GATE_DIR.iterdir()):
        if not ticker_dir.is_dir():
            continue
        trades_path = ticker_dir / "trades.json"
        if not trades_path.exists():
            continue

        with open(trades_path) as f:
            trades = json.load(f)

        # Only sell trades have P/L outcomes
        sells = [t for t in trades if t.get("side", "").upper() == "SELL"
                 and t.get("exit_reason") != "SIM_END"]

        if sells:
            tickers_found += 1
            all_trades.extend(sells)
        else:
            tickers_empty += 1

    return all_trades, tickers_found, tickers_empty


def build_fired_inputs(trade):
    """Reconstruct fired_inputs from trade outcome data.

    Available on sell trades: pnl_pct, pnl_dollars, exit_reason,
    days_held, regime, avg_cost, price, ticker.

    We create gate entries for the weight learner to train on:
    - profit_gate: how much P/L the trade produced (diagnostic outcome signal)
    - hold_gate: how long the position was held (diagnostic timing signal)

    These gates are intentionally diagnostic-only. weight_learner.save_weights()
    keeps them out of the live policy weight map consumed by evaluators.
    """
    tk = trade["ticker"]
    pnl_pct = trade.get("pnl_pct", 0)
    days_held = trade.get("days_held", 0)

    return {
        f"{tk}:profit_gate": {f"{tk}:pnl_pct": pnl_pct},
        f"{tk}:hold_gate": {f"{tk}:days_held": float(days_held)},
    }


def train(trades, epochs=3, learning_rate=0.01, dry_run=False):
    """Train synapse weights from historical trades."""
    # Load existing weights (preserves dip strategy weights)
    weights = {}
    if WEIGHTS_PATH.exists():
        with open(WEIGHTS_PATH) as f:
            data = json.load(f)
        weights = data.get("weights", {})

    existing_keys = len(weights)

    # Add fired_inputs and pnl to each trade
    for t in trades:
        t["fired_inputs"] = build_fired_inputs(t)
        t["pnl"] = t.get("pnl_dollars", 0)

    # Count wins/losses
    wins = sum(1 for t in trades if t["pnl"] > 0)
    losses = len(trades) - wins

    print(f"Training on {len(trades)} trades ({wins} wins, {losses} losses)")
    print(f"Existing weights: {existing_keys} gate entries")
    print(f"Learning rate: {learning_rate}, Epochs: {epochs}")
    print(f"Norm divisor: 50.0 (pnl_pct range: -47.6% to +14.0%)\n")

    # Train
    for epoch in range(epochs):
        np.random.seed(42 + epoch)
        shuffled = list(trades)
        np.random.shuffle(shuffled)
        weights = update_weights(shuffled, weights, learning_rate,
                                 norm_divisor=50.0)

        # Stats
        all_w = [w for gate in weights.values() for w in gate.values()]
        # Separate dip vs support weights
        dip_w = [w for k, gate in weights.items()
                 for w in gate.values()
                 if "dip_gate" in k or "bounce_gate" in k]
        support_w = [w for k, gate in weights.items()
                     for w in gate.values()
                     if "profit_gate" in k or "hold_gate" in k]

        print(f"  Epoch {epoch + 1}: "
              f"total={len(all_w)} synapses "
              f"(dip: {len(dip_w)}, support: {len(support_w)}) | "
              f"support mean={np.mean(support_w):.4f} "
              f"range=[{min(support_w):.4f}, {max(support_w):.4f}]"
              if support_w else f"  Epoch {epoch + 1}: no support weights yet")

    # Stats
    stats = {
        "total_trades": len(trades),
        "wins": wins,
        "losses": losses,
        "source": "historical_trade_trainer",
        "epochs": epochs,
        "learning_rate": learning_rate,
        "total_synapses": sum(len(v) for v in weights.values()),
    }

    if dry_run:
        print(f"\n--- DRY RUN — weights not saved ---")
    else:
        save_weights(weights, stats)
        print(f"\nWeights saved to {WEIGHTS_PATH}")

    return weights, stats


def main():
    parser = argparse.ArgumentParser(description="Historical Trade Trainer")
    parser.add_argument("--epochs", type=int, default=5,
                        help="Training epochs (default: 5)")
    parser.add_argument("--learning-rate", type=float, default=0.01,
                        help="Learning rate (default: 0.01)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print(f"Historical Trade Trainer — {date.today().isoformat()}\n")

    # Extract trades
    trades, n_tickers, n_empty = extract_trades()
    print(f"Extracted {len(trades)} sell trades from {n_tickers} tickers "
          f"({n_empty} tickers with 0 trades)\n")

    if not trades:
        print("*No trades found. Run backtest simulations first.*")
        return

    # Show sample
    by_ticker = {}
    for t in trades:
        tk = t["ticker"]
        by_ticker[tk] = by_ticker.get(tk, 0) + 1
    top5 = sorted(by_ticker.items(), key=lambda x: x[1], reverse=True)[:5]
    print(f"Top 5 by trade count: {', '.join(f'{tk}:{n}' for tk, n in top5)}\n")

    # Train
    weights, stats = train(trades, args.epochs, args.learning_rate, args.dry_run)

    # Summary
    all_w = [w for gate in weights.values() for w in gate.values()]
    at_one = sum(1 for w in all_w if w == 1.0)
    support_w = [w for k, gate in weights.items()
                 for w in gate.values()
                 if "profit_gate" in k or "hold_gate" in k]
    dip_w = [w for k, gate in weights.items()
             for w in gate.values()
             if "dip_gate" in k or "bounce_gate" in k]

    print(f"\n## Weight Summary")
    print(f"| Category | Count | At 1.0 | Mean | Min | Max |")
    print(f"| :--- | :--- | :--- | :--- | :--- | :--- |")
    if dip_w:
        print(f"| Dip gates | {len(dip_w)} | "
              f"{sum(1 for w in dip_w if w == 1.0)} | "
              f"{np.mean(dip_w):.4f} | {min(dip_w):.4f} | {max(dip_w):.4f} |")
    if support_w:
        print(f"| Support gates | {len(support_w)} | "
              f"{sum(1 for w in support_w if w == 1.0)} | "
              f"{np.mean(support_w):.4f} | {min(support_w):.4f} | {max(support_w):.4f} |")
    print(f"| **Total** | **{len(all_w)}** | **{at_one}** | "
          f"**{np.mean(all_w):.4f}** | **{min(all_w):.4f}** | **{max(all_w):.4f}** |")


if __name__ == "__main__":
    main()
