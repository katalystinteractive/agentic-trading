# Implementation Plan: Neural Network for Support-Based Strategy

**Date**: 2026-03-29
**Source analysis**: `plans/neural-general-strategy-analysis-v2.md` (verified, 18/18 correct)
**Constraint**: Dip strategy implementation is FROZEN — zero modifications to dip files. Shared tools get backward-compatible changes only.

---

## Scope

4 steps, executed sequentially:

| Step | What | New Files | Modified Files | Frozen Files |
| :--- | :--- | :--- | :--- | :--- |
| 0 | Benchmark simulation runtime | — | — | — |
| 1 | Backward-compatible shared tool changes | — | `weight_learner.py`, `ticker_clusterer.py`, `backtest_engine.py`, `weekly_reoptimize.py` | Dip module (6 files) |
| 2 | Support parameter sweeper (two-stage) | `support_parameter_sweeper.py` | — | — |
| 3 | Support candidate discoverer + feature extractor | `support_feature_extractor.py`, `neural_support_discoverer.py` | — | — |

---

## Step 0: Benchmark Simulation Runtime

**Why first**: The runtime per simulation invocation determines which sweep approach is feasible (Option A, B, or C from analysis Section 3.4). Every other decision depends on this number.

```bash
python3 -c "
import time
from tools.backtest_engine import run_simulation, load_collected_data
from tools.backtest_config import SurgicalSimConfig
# Use a ticker that has collected data
data_dir = 'data/backtest/candidate-gate/CIFR'
price_data, regime_data = load_collected_data(data_dir)
cfg = SurgicalSimConfig()
t0 = time.time()
trades, cycles, equity, dip = run_simulation(price_data, regime_data, cfg)
elapsed = time.time() - t0
print(f'Simulation time: {elapsed:.1f}s, trades: {len(trades)}, cycles: {len(cycles)}')
"
```

**Expected outcome**: A single number (e.g., "42 seconds" or "3.2 minutes") that determines which option we use:
- < 10s → Option B (parameterize + sweep all combos) is feasible
- 10-60s → Option C (reduced grid, 30 combos) is feasible
- > 60s → Option A (simplified model for sweep, full sim for validation only)

**No code changes in this step.** Just measurement.

---

## Step 1: Backward-Compatible Shared Tool Changes

All changes MUST preserve existing behavior when called without new parameters. Each tool gets a self-test to verify backward compatibility.

### 1.1 `weight_learner.py` — configurable normalization

**Current** (line 64):
```python
norm_val = min(abs(float(input_val)) / 10.0, 1.0)
```

**Change to**:
```python
def update_weights(trades, current_weights, learning_rate=0.01, norm_divisor=10.0):
    ...
    norm_val = min(abs(float(input_val)) / norm_divisor, 1.0)
```

**Backward compat**: `norm_divisor=10.0` default. All existing calls pass no `norm_divisor` → unchanged behavior.

**Support strategy usage**: `norm_divisor=100.0` for RSI (0-100 range), `norm_divisor=25.0` for stop loss percentages.

### 1.2 `ticker_clusterer.py` — configurable feature columns

**Current** (lines 29-38):
```python
FEATURE_COLS = [
    "dip_frequency", "median_dip_depth_pct", "median_bounce_pct",
    "target_hit_rate", "stop_hit_rate", "eod_cut_rate",
    "eod_recovery_rate", "mean_pnl_pct",
]
```

**Change**: Add `feature_cols` parameter to `build_feature_matrix()` and `cluster_tickers()`:

```python
def build_feature_matrix(sweep_data, feature_cols=None):
    cols = feature_cols or FEATURE_COLS
    ...
```

Same for `cluster_tickers()` main function and CLI: add `--feature-cols` flag (optional, defaults to FEATURE_COLS).

**Backward compat**: All existing calls pass no `feature_cols` → uses FEATURE_COLS constant → unchanged behavior.

### 1.3 `backtest_engine.py` — accept config overrides

**FACT** (verified): `run_simulation()` already accepts a `cfg: SurgicalSimConfig` parameter. `SurgicalSimConfig` is a dataclass with all the fields we want to sweep (line 100-119 of `backtest_config.py`):
- `sell_default`, `sell_fast_cycler`, `sell_exceptional` (profit targets)
- `active_pool`, `reserve_pool` (pool sizing)
- `active_bullets_max`, `reserve_bullets_max` (bullet count)
- `tier_full`, `tier_std`, `tier_half` (tier thresholds)

**This means**: `backtest_engine.py` ALREADY accepts parameterized config. No modification needed to the engine itself. The support sweeper creates `SurgicalSimConfig` instances with swept values and passes them to `run_simulation()`.

**Change needed**: NONE in `backtest_engine.py`. The parameterization already exists via the config dataclass.

**Update to plan**: Remove `backtest_engine.py` from the "modified files" list. Move to "no changes needed."

### 1.4 `weekly_reoptimize.py` — strategy flag

**Current**: Hardcodes tool paths in `step_sweep()`, `step_cluster()`, `step_train_weights()`.

**Change**: Add `--strategy` flag:
```python
parser.add_argument("--strategy", choices=["dip", "support"], default="dip")
```

In each step function, select the tool based on strategy:
```python
STRATEGY_TOOLS = {
    "dip": {
        "sweeper": "tools/parameter_sweeper.py",
        "clusterer": "tools/ticker_clusterer.py",
    },
    "support": {
        "sweeper": "tools/support_parameter_sweeper.py",
        "clusterer": "tools/ticker_clusterer.py",  # same tool, different --feature-cols
    },
}
```

**Backward compat**: `--strategy dip` (default) runs current pipeline unchanged.

### 1.5 Verification

1. Run existing dip pipeline: `python3 tools/parameter_sweeper.py --cached` → same output as before
2. Run existing weight training: `python3 tools/weight_learner.py` → same weights
3. Run existing clustering: `python3 tools/ticker_clusterer.py` → same clusters
4. Run existing weekly pipeline: `python3 tools/weekly_reoptimize.py --skip-download --no-email` → same results

### 1.6 Files changed

| File | Change | Lines |
| :--- | :--- | :--- |
| `tools/weight_learner.py` | Add `norm_divisor` param to `update_weights()` | ~5 |
| `tools/ticker_clusterer.py` | Add `feature_cols` param to `build_feature_matrix()` + CLI | ~15 |
| `tools/weekly_reoptimize.py` | Add `--strategy` flag + tool selection dict | ~20 |
| `tools/backtest_engine.py` | **NO CHANGES** — already accepts `SurgicalSimConfig` | 0 |

---

## Step 2: Support Parameter Sweeper

### 2.1 New file: `tools/support_parameter_sweeper.py`

**Purpose**: Two-stage parameter sweep for the support strategy using `backtest_engine.py` as the simulator.

```
Usage:
    python3 tools/support_parameter_sweeper.py --ticker CIFR          # sweep one ticker
    python3 tools/support_parameter_sweeper.py --top 100              # top 100 universe passers
    python3 tools/support_parameter_sweeper.py --stage threshold      # stage 1 only
    python3 tools/support_parameter_sweeper.py --stage execution      # stage 2 only (needs stage 1 results)
    python3 tools/support_parameter_sweeper.py --split                # cross-validation
    python3 tools/support_parameter_sweeper.py --workers 8            # parallel via multiprocessing
```

**Cross-validation (`--split`)**: Same approach as dip sweeper. `simulate_candidate()` runs on `months` months of data (default 10). With `--split`:
- **Train**: first 7 months → find best params
- **Validate**: last 3 months → evaluate best params on unseen data
- Implemented by passing `months=7` for train sweep, then re-running best params with a date-range restricted simulation for the last 3 months
- Flag tickers where train P/L > 0 but validation P/L < 0 (overfitting signal)

### 2.2 Stage 1: Threshold sweep

```python
from backtest_config import SurgicalSimConfig
from backtest_engine import run_simulation, load_collected_data
from candidate_sim_gate import simulate_candidate

THRESHOLD_GRID = {
    "sell_default": [4.0, 5.0, 6.0, 7.0, 8.0, 10.0],      # 6 values
    "cat_hard_stop": [15, 20, 25, 30, 40],                   # 5 values (FACT: field exists on SurgicalSimConfig line 133)
}
# RSI and VIX sweeps deferred until benchmark shows runtime is feasible
# Start with 6 × 5 = 30 combos (not 750) — Option C from analysis
# Follow-up: after benchmark, if runtime < 10s per combo, expand to full grid:
#   THRESHOLD_GRID_FULL = {
#       "sell_default": [4.0, 5.0, 6.0, 7.0, 8.0, 10.0],  # 6
#       "cat_hard_stop": [15, 20, 25, 30, 40],              # 5
#       "rsi_entry": [20, 25, 30, 35, 40],                  # 5 (NEW gate — requires backtest_engine mod)
#       "vix_threshold": [18, 20, 25, 30, 35],              # 5
#   }  # = 750 combos

def sweep_threshold(ticker, months=10):
    """Sweep profit target + catastrophic stop for one ticker."""
    best_pnl = float("-inf")
    best_params = None

    for sell_target in THRESHOLD_GRID["sell_default"]:
        for cat_stop in THRESHOLD_GRID["cat_hard_stop"]:
            cfg = SurgicalSimConfig(
                sell_default=sell_target,
                sell_fast_cycler=sell_target + 2.0,
                sell_exceptional=sell_target + 4.0,
                cat_hard_stop=cat_stop,
                cat_warning=max(cat_stop - 10, 5),  # scale warning relative to hard stop
            )
            result = simulate_candidate(ticker, months=months, config=cfg)
            pnl = result.get("pnl", 0)
            if pnl > best_pnl:
                best_pnl = pnl
                best_params = {"sell_default": sell_target, "cat_hard_stop": cat_stop}

    return best_params, best_pnl

# NOTE on RSI entry: backtest_engine.py currently has NO RSI entry gate.
# Adding RSI as a swept parameter requires modifying backtest_engine.py
# to check RSI before placing buy orders. This is a backtest_engine.py
# modification — deferred until the threshold sweep proves valuable
# with just sell_default + cat_hard_stop.
```

**Key dependency**: `simulate_candidate()` in `candidate_sim_gate.py` handles data collection + simulation. Need to verify it accepts a custom `SurgicalSimConfig`.

**FACT** (verified): `candidate_sim_gate.py` line 82 calls `run_simulation(price_data, regime_data, cfg)` where `cfg` is a `SurgicalSimConfig`. Currently it constructs a default config. The sweeper would pass a custom config with swept values.

**Required change to `candidate_sim_gate.py`**: Add optional `config` parameter to `simulate_candidate()`:
```python
def simulate_candidate(ticker, months=10, config=None):
    cfg = config or SurgicalSimConfig()
    ...
```

This is a backward-compatible change (default `None` → current behavior).

### 2.3 Stage 2: Execution sweep

With optimal thresholds locked from Stage 1, sweep pool/bullet/tier:

```python
EXECUTION_GRID = {
    "active_pool": [200, 300, 400, 500, 750],      # 5 values
    "reserve_pool": [200, 300, 400, 500],            # 4 values
    "active_bullets_max": [3, 4, 5, 6, 7],           # 5 values
    "reserve_bullets_max": [2, 3, 4, 5],             # 4 values
    "tier_full": [40, 50, 60, 70],                   # 4 values
    "tier_std": [20, 30, 40],                        # 3 values
}
# 5 × 4 × 5 × 4 × 4 × 3 = 4,800 combos

def sweep_execution(ticker, threshold_params, months=10):
    """Sweep execution params with thresholds locked."""
    best_pnl = float("-inf")
    best_params = None

    for pool, res_pool, bullets, res_bullets, t_full, t_std in itertools.product(...):
        cfg = SurgicalSimConfig(
            sell_default=threshold_params["sell_default"],
            active_pool=pool,
            reserve_pool=res_pool,
            active_bullets_max=bullets,
            reserve_bullets_max=res_bullets,
            tier_full=t_full,
            tier_std=t_std,
        )
        result = simulate_candidate(ticker, months=months, config=cfg)
        ...
```

**Runtime concern**: 4,800 combos per ticker at ~30s each = 40 hours per ticker. This runs ONLY on the top 30 from Stage 1. At 30 tickers with 8-core parallel: 40 × 30 / 8 = 150 hours = 6.25 days.

**Mitigation**: Start with a reduced execution grid (3 × 2 × 3 × 2 × 2 × 2 = 144 combos). At 30s: 144 × 30s × 30 tickers / 8 cores = 4.5 hours. Expand grid if results are promising.

### 2.4 Parallelization

```python
from multiprocessing import Pool

def _sweep_one_ticker(args):
    """Run in child process. Imports inside to avoid pickle issues."""
    ticker, months, config_overrides = args
    from candidate_sim_gate import simulate_candidate
    from backtest_config import SurgicalSimConfig
    cfg = SurgicalSimConfig(**config_overrides)
    return simulate_candidate(ticker, months=months, config=cfg)
```

**FACT** (verified): `multiprocessing` requires picklable functions. `simulate_candidate` is a module-level function — picklable. `SurgicalSimConfig` is a dataclass — picklable. Lambda compute functions inside graph nodes are NOT picklable, but the sweeper doesn't pass graph objects across processes — each process builds its own.

### 2.5 Output

`data/support_sweep_results.json` — separate from dip sweep results:
```json
{
  "_meta": {"source": "support_parameter_sweeper.py", ...},
  "CIFR": {
    "threshold_params": {"sell_default": 7.0, "cat_hard_stop": 20},
    "execution_params": {"active_pool": 500, "active_bullets_max": 4, ...},
    "combined_params": {...all params...},
    "stats": {"pnl": 45.20, "trades": 12, "win_rate": 91.7, ...},
    "trades": [...per-trade detail with fired_inputs...],
    "features": {...behavioral features for clustering...}
  }
}
```

**`fired_inputs` for weight learning**: `backtest_engine.py` trade records currently do NOT contain `fired_inputs`. The weight learner requires this field (line 50 of `weight_learner.py`: `trade.get("fired_inputs")`). The support sweeper must post-process trade records to ADD `fired_inputs` after the simulation:

```python
# After simulation produces trades, enrich with fired_inputs for weight learning
for trade in trades:
    if trade.get("side") == "buy":
        trade["fired_inputs"] = {
            f"{tk}:profit_gate": {f"{tk}:pl_pct": trade.get("pnl_pct", 0)},
            f"{tk}:stop_gate": {f"{tk}:pl_pct": trade.get("pnl_pct", 0)},
        }
```

This is the same pattern as the dip sweeper (lines 214-217 of `parameter_sweeper.py`), adapted for support strategy inputs.

**Pool vs share price scaling**: `backtest_engine.py` handles share count computation internally — it computes shares from `pool ÷ bullets ÷ price` during the simulation (via `_compute_bullet_plan()` called from the wick analysis integration). The sweeper does NOT need price-aware pool filtering — the simulation already produces correct share counts for any pool/price combination. A $750 pool on a $3 stock correctly computes ~250 shares/bullet × fewer bullets, matching `bullet_recommender.py` logic.
```

### 2.6 Files

| File | Action | Lines |
| :--- | :--- | :--- |
| `tools/support_parameter_sweeper.py` | NEW | ~300 |
| `tools/candidate_sim_gate.py` | MODIFY — add optional `config` param to `simulate_candidate()` | ~5 |

---

## Step 3: Support Feature Extractor + Candidate Discoverer

### 3.1 New file: `tools/support_feature_extractor.py`

Extract behavioral features from support simulation results for clustering:

```python
SUPPORT_FEATURE_COLS = [
    "median_hold_days",       # how long positions are held
    "target_hit_rate",        # % of trades hitting profit target
    "stop_hit_rate",          # % of trades hitting stop
    "cycle_speed_days",       # median days between cycle completions
    "avg_bullets_per_cycle",  # how many bullets fill per position
    "pool_efficiency",        # P/L per dollar deployed
    "level_reliability",      # weighted hold rate across support levels
    "mean_pnl_pct",           # average trade P/L %
]

def extract_support_features(ticker, simulation_result):
    """Compute behavioral features from support strategy simulation."""
    trades = simulation_result.get("trades", [])
    ...
```

### 3.2 New file: `tools/neural_support_discoverer.py`

Same pattern as `neural_candidate_discoverer.py` but for support strategy:

```
Pipeline:
  1. Load universe passers
  2. Collect data for each ticker (backtest_data_collector)
  3. Run support_parameter_sweeper (Stage 1 threshold sweep)
  4. Cross-validate: train/validate split
  5. Rank by validation P/L, apply gates
  6. Run Stage 2 execution sweep on top 30
  7. Cluster using support_feature_extractor features
  8. Output to data/neural_support_candidates.json
```

**Key difference from dip discoverer**: The data collection step is slower (downloads 13-month daily data per ticker vs 60-day 5-min). And the simulation is slower (path-dependent vs arithmetic). The discoverer may need to run on fewer tickers (top 100-200 universe passers by tradability, not all 1,477).

### 3.3 Output comparison

After both discoverers run, produce a comparison:

```python
def compare_strategies():
    """Load both candidate lists, find overlaps, produce summary."""
    with open("data/neural_candidates.json") as f:
        dip = json.load(f)
    with open("data/neural_support_candidates.json") as f:
        support = json.load(f)

    dip_tickers = {c["ticker"] for c in dip["candidates"]}
    support_tickers = {c["ticker"] for c in support["candidates"]}
    overlap = dip_tickers & support_tickers

    print(f"Dip-only: {len(dip_tickers - support_tickers)}")
    print(f"Support-only: {len(support_tickers - dip_tickers)}")
    print(f"Both strategies: {len(overlap)} — {overlap}")
```

### 3.4 Files

| File | Action | Lines |
| :--- | :--- | :--- |
| `tools/support_feature_extractor.py` | NEW | ~120 |
| `tools/neural_support_discoverer.py` | NEW | ~250 |

---

## Implementation Order

```
Step 0: Benchmark (no code changes — just measurement)
  ↓ (determines Option A/B/C for Step 2)
Step 1: Backward-compatible shared tool changes
  ↓ (verify dip pipeline still works)
Step 2: Support parameter sweeper
  ↓ (test on single ticker first, then top 30)
Step 3: Feature extractor + discoverer
  ↓ (run on universe, compare with dip results)
```

---

## Total Estimated Changes

| Category | Lines |
| :--- | :--- |
| New files | ~670 (sweeper 300, extractor 120, discoverer 250) |
| Modified files | ~45 (weight_learner 5, clusterer 15, weekly 20, sim_gate 5) |
| Unchanged (engine already parameterized) | `backtest_engine.py` |
| **Total** | **~715 lines** |

**Frozen files (ZERO modifications):**
- `neural_dip_evaluator.py`
- `parameter_sweeper.py`
- `neural_candidate_discoverer.py`
- `neural_dip_backtester.py`
- `graph_engine.py`
- `data/neural_candidates.json`
- `data/sweep_results.json`

---

## Risk Mitigation

### Runtime is the biggest unknown
Step 0 (benchmark) must come first. If `run_simulation()` takes > 60 seconds, the full 5,550-combo sweep per ticker is infeasible even with parallelization. Option A (simplified model) would need to be designed and validated before Step 2.

### Two-stage independence assumption
Analysis Q6 flags that pool size affects trade sequence. After Step 2 Stage 1 runs, verify by re-running Stage 1 with the top ticker's Stage 2 execution params. If P/L changes significantly, the stages aren't independent and need joint optimization (smaller grid, Option C).

### Backward compatibility
Every Step 1 change gets verified by re-running the existing dip pipeline and comparing output byte-for-byte. If any output differs, the change broke backward compat.
