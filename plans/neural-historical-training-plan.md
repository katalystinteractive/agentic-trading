# Implementation Plan: Training Neural Network with Historical Data

**Date**: 2026-03-30
**Source analysis**: `plans/neural-historical-training-analysis.md` (verified, all issues fixed)
**Goal**: Train the neural network on 3,428 existing trades + extend dip lookback to 730 days. Move from 27 trades / 19 unchanged weights to 3,400+ trades / meaningful weight differentiation.

---

## Scope

3 phases, executable in order:

| Phase | What | Effort | Runtime |
| :--- | :--- | :--- | :--- |
| 1 | Re-run support discoverer with multi-period | 0 lines (existing tool) | UNMEASURED (~28 min est.) |
| 2 | Build historical trade trainer | ~100 lines NEW | ~5 min compute |
| 3 | Extend dip backtester to 1-hour / 730 days | ~50 lines MODIFY | UNMEASURED |

---

## Phase 1: Re-run Support Discoverer (0 code changes)

The support candidates were swept without multi-period or cross-validation. The code is already updated (multi-period sweep in `sweep_threshold()`). Just re-run.

```bash
python3 tools/neural_support_discoverer.py --exec-top 10 --workers 8
```

**Outcome**: `data/neural_support_candidates.json` updated with `composite` scores and `periods` data for all 30 candidates. Cross-validation flags overfitting tickers.

**Verification**:
```bash
python3 -c "
import json
with open('data/neural_support_candidates.json') as f:
    data = json.load(f)
c = data['candidates'][0]
print(f'Has composite: {c.get(\"composite\") is not None}')
print(f'Has periods: {c.get(\"periods\") is not None}')
"
```

---

## Phase 2: Historical Trade Trainer

### 2.1 New file: `tools/historical_trade_trainer.py`

**Purpose**: Extract trades from existing backtest results, reconstruct entry-time features, train synapse weights on ~3,428 trades.

```
Usage:
    python3 tools/historical_trade_trainer.py                # train from all candidate-gate trades
    python3 tools/historical_trade_trainer.py --epochs 5      # more training epochs
    python3 tools/historical_trade_trainer.py --dry-run        # show stats without updating weights
```

### 2.2 Trade extraction

**FACT** (verified): `data/backtest/candidate-gate/<TICKER>/trades.json` has ~3,428 trades across 68 tickers.

Buy trades have: `ticker, side, date, price, shares, zone, tier, avg_cost, regime`
Sell trades have: `ticker, side, date, price, shares, pnl_pct, pnl_dollars, exit_reason, days_held, avg_cost, regime`

```python
def extract_trades(gate_dir):
    """Load all trades from candidate-gate backtest results."""
    all_trades = []
    for ticker_dir in gate_dir.iterdir():
        if not ticker_dir.is_dir():
            continue
        trades_path = ticker_dir / "trades.json"
        if not trades_path.exists():
            continue
        with open(trades_path) as f:
            trades = json.load(f)
        # Only sell trades have P/L outcomes for weight learning
        sells = [t for t in trades if t.get("side", "").upper() == "SELL"
                 and t.get("exit_reason") != "SIM_END"]
        all_trades.extend(sells)
    return all_trades
```

### 2.3 Fired inputs reconstruction

**Challenge**: The existing trades don't have `fired_inputs` (the field weight_learner needs). We must reconstruct entry-time features from the trade data.

**Available on sell trades**: `pnl_pct`, `pnl_dollars`, `exit_reason`, `days_held`, `regime`, `avg_cost`, `price` (exit price), `ticker`.

**Reconstructable inputs** (no additional data needed):
- `pnl_pct` at exit — directly available
- `exit_type` — TARGET, STOP, SAME_DAY_EXIT, TIME_STOP, CATASTROPHIC — from `exit_reason`
- `regime` at exit — directly available
- `days_held` — directly available
- `entry_price` — reconstructable from `avg_cost` (for single-bullet positions) or approximate

**What we CAN train on**: Which combinations of regime + exit_type + days_held correlate with profitable outcomes. This is less granular than live entry-time features (RSI, support distance) but covers 3,428 trades vs 27.

```python
def build_fired_inputs(trade):
    """Reconstruct fired_inputs from trade outcome data."""
    tk = trade["ticker"]
    pnl_pct = trade.get("pnl_pct", 0)
    days_held = trade.get("days_held", 0)

    return {
        f"{tk}:profit_gate": {f"{tk}:pnl_pct": pnl_pct},
        f"{tk}:hold_gate": {f"{tk}:days_held": days_held},
    }
```

### 2.4 Training

```python
from weight_learner import update_weights, save_weights

def train_from_historical(trades, epochs=3, learning_rate=0.01):
    """Train synapse weights from historical backtest trades."""
    # Load existing weights or start fresh
    weights = {}
    if WEIGHTS_PATH.exists():
        with open(WEIGHTS_PATH) as f:
            data = json.load(f)
        weights = data.get("weights", {})

    # Add fired_inputs to each trade
    for t in trades:
        t["fired_inputs"] = build_fired_inputs(t)
        t["pnl"] = t.get("pnl_dollars", 0)

    # Train
    for epoch in range(epochs):
        np.random.seed(42 + epoch)
        shuffled = list(trades)
        np.random.shuffle(shuffled)
        weights = update_weights(shuffled, weights, learning_rate,
                                 norm_divisor=50.0)  # pnl_pct range -47.6% to +14%

    return weights
```

**Note**: `norm_divisor=50.0` because `pnl_pct` ranges -47.6% to +14.0% (verified from 1,215 sell trades). Using 50.0 gives good granularity across the full range without clamping moderate values. The dip strategy uses 10.0 (for 0-10% dip percentages). The weight_learner already supports configurable `norm_divisor` from the backward-compatible change in Phase 3 of the neural architecture.

### 2.5 Output

Writes updated `data/synapse_weights.json` with training stats:

```python
stats = {
    "total_trades": len(trades),
    "wins": sum(1 for t in trades if t["pnl"] > 0),
    "losses": sum(1 for t in trades if t["pnl"] <= 0),
    "source": "historical_trade_trainer",
    "epochs": epochs,
}
save_weights(weights, stats)
```

### 2.6 Verification

```bash
python3 tools/historical_trade_trainer.py --dry-run
# Verify: shows ~3,400 trades extracted
# Verify: weights change meaningfully (not all at 1.0)

python3 -c "
import json
with open('data/synapse_weights.json') as f:
    data = json.load(f)
weights = data.get('weights', {})
all_w = [w for gate in weights.values() for w in gate.values()]
at_one = sum(1 for w in all_w if w == 1.0)
print(f'Weights at 1.0: {at_one}/{len(all_w)}')
print(f'Range: [{min(all_w):.4f}, {max(all_w):.4f}]')
"
```

---

## Phase 3: Extend Dip Training to 1-Hour / 730 Days

### 3.1 Add `--interval` flag to `neural_dip_backtester.py`

```python
parser.add_argument("--interval", choices=["5m", "1h"], default="5m",
    help="Bar interval: 5m (60-day max) or 1h (730-day max)")
```

### 3.2 Adjust download and cache

```python
if args.interval == "1h":
    days = min(args.days, 730)
    cache_path = CACHE_DIR / "intraday_1h_cache.pkl"
else:
    days = min(args.days, 60)
    cache_path = CACHE_DIR / "intraday_5min_cache.pkl"

data = yf.download(tickers, period=f"{days}d", interval=args.interval, ...)
```

### 3.3 No changes to evaluator functions

**FACT** (verified): `_extract_open()`, `_extract_price_at()`, and `_extract_first_hour_low()` all use UTC timestamps, not bar indices. They work with any interval. No changes needed in `neural_dip_evaluator.py`.

### 3.4 Adjust parameter sweeper

`parameter_sweeper.py::precompute_signals()` also needs the interval parameter for its `build_first_hour_graph()` calls. Add `--interval` flag:

```python
parser.add_argument("--interval", choices=["5m", "1h"], default="5m")
```

And pass through to the download:

```python
intraday = download_intraday(tickers, days, interval=args.interval)
```

### 3.5 Benchmark signal rate at 1-hour

Before full sweep, measure how often the breadth gate fires with 1-hour bars:

```bash
python3 tools/neural_dip_backtester.py --interval 1h --days 730 --cached
# Check output: how many signal days out of ~730 trading days?
```

**UNKNOWN**: The 20% signal rate from 5-min bars may not transfer to 1-hour. Must measure before relying on it.

### 3.6 Verification

```bash
# Compare 5-min and 1-hour results on overlapping 60-day window
python3 tools/neural_dip_backtester.py --interval 5m --days 60 --cached
python3 tools/neural_dip_backtester.py --interval 1h --days 60 --cached
# Compare: do the same tickers get signals? Similar P/L?
```

---

## Files Summary

| File | Action | Lines |
| :--- | :--- | :--- |
| `tools/historical_trade_trainer.py` | NEW — extract + train from backtest trades | ~100 |
| `tools/neural_dip_backtester.py` | MODIFY — add `--interval` flag, interval-aware cache | ~30 |
| `tools/parameter_sweeper.py` | MODIFY — add `--interval` flag, pass to download | ~20 |
| **Total** | | **~150** |

**Not modified**: `neural_dip_evaluator.py` (timestamp-based, already interval-agnostic), `weight_learner.py` (already has `norm_divisor` param), `support_parameter_sweeper.py` (uses daily bars, not intraday)

---

## Weight Merge Behavior

Phase 2 trains on support strategy trades (profit_gate, hold_gate keys). The existing synapse_weights.json has dip strategy weights (dip_gate, bounce_gate keys). These are DIFFERENT gate namespaces — they coexist in the same file without collision.

`historical_trade_trainer.py` loads existing weights first, then trains on top. The dip strategy weights remain untouched (different keys). The support strategy weights are NEW keys added to the same dict.

After Phase 2, `synapse_weights.json` will contain:
- Dip gates: `CIFR:dip_gate`, `CIFR:bounce_gate`, etc. (from prior 27-trade training)
- Support gates: `CIFR:profit_gate`, `CIFR:hold_gate`, etc. (from 3,428-trade historical training)

---

## Limitations (from analysis Section 7)

1. **Per-ticker weight learning**: 3,428 trades ÷ 68 tickers = ~50 trades/ticker avg. Still below the 100+ ideal for per-ticker weights. Cluster-level weights (shared across similar tickers) would be more statistically reliable, but are not implemented yet.

2. **Intraday regime**: All regime data is daily-level. The neural network cannot learn intraday VIX/momentum patterns with current data granularity.

3. **New ticker cold start**: A ticker with zero historical trades gets cluster defaults. This is the intended behavior — live trades refine the prior over time.

---

## Execution Order

```
Phase 1: Re-run support discoverer (0 code, ~28 min)
  → Populates composite + periods for support candidates

Phase 2: Build + run historical trade trainer (~100 lines, ~5 min)
  → Trains weights on 3,428 trades instead of 27

Phase 3: Extend dip to 1-hour 730 days (~50 lines, benchmark first)
  → Step 1: Download 1h data, measure signal rate
  → Step 2: If signal rate reasonable, run full sweep
  → Step 3: Re-train dip weights on expanded data
```
