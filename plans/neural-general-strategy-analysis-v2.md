# Analysis: Applying the Neural Network to the General Support-Based Strategy (v2)

**Date**: 2026-03-29 (Sunday, 5:29 PM local / 10:29 AM ET)
**Purpose**: Determine whether the neural architecture can be applied to the existing multi-day support-based strategy.
**Previous version**: `neural-general-strategy-analysis.md` — had 7 wrong/mislabeled claims. This version corrects all of them.

**Honesty note**: Every claim labeled FACT (verified against code), ESTIMATE, PROPOSED, or HYPOTHETICAL.

---

## 1. What Transfers vs What Doesn't

### 1.1 Truly strategy-agnostic (FACT — verified)

Only ONE component is genuinely strategy-agnostic:

**`graph_engine.py`** — The DAG engine has zero trading code. No imports from trading tools, no references to dip/support/ticker/price in functional code. It provides:
- `Node` with `compute: Callable[[dict], Any]`
- `Signal` with `old_value: Any, new_value: Any`
- `edge_weights: dict[str, float]`
- Topological sort + resolve

This transfers to ANY strategy without modification.

### 1.2 The PATTERN transfers, but the tools are coupled (FACT — verified)

The architecture pattern — observers fire values → subscription gates compare to thresholds → weights learn from outcomes → clustering groups similar behavior — is generic. But the tools that implement it are coupled to the dip strategy:

| Tool | Coupling | What needs changing for support strategy |
| :--- | :--- | :--- |
| `parameter_sweeper.py` | **Tightly coupled** — imports `build_first_hour_graph`, `build_decision_graph`, `DIP_CONFIG`, `_extract_col`, `_extract_latest` directly from `neural_dip_evaluator.py`. Sweeps `SWEEP_DIP_THRESHOLDS`, `SWEEP_BREADTH`. | Needs a NEW sweeper that imports from `backtest_engine.py` instead, with different parameter grids |
| `ticker_clusterer.py` | **Coupled** — `FEATURE_COLS` has 8 columns: `dip_frequency`, `median_dip_depth_pct`, `median_bounce_pct`, `target_hit_rate`, `stop_hit_rate`, `eod_cut_rate`, `eod_recovery_rate`, `mean_pnl_pct`. Three are strategy-generic (`target_hit_rate`, `stop_hit_rate`, `mean_pnl_pct`), five are dip-specific. `compute_cluster_profiles()` extracts `dip_threshold`, `bounce_threshold`. | Needs configurable feature columns + different cluster profile fields |
| `weight_learner.py` | **Partially coupled** — normalization hardcodes `min(abs(input_val) / 10.0, 1.0)` with comment "dip/bounce are typically 0-10%". Functionally works on any inputs but normalization range is wrong for RSI (0-100) or support distance. | Needs configurable normalization range |
| `neural_dip_evaluator.py` | **Fully coupled** — the dip strategy evaluator. Not relevant to support strategy. | Not used — a new evaluator needed |
| `neural_candidate_discoverer.py` | **Fully coupled** — calls dip sweeper functions directly. | Needs a new discoverer or a strategy parameter |

### 1.3 Reusable unchanged (FACT)

| Component | Why no changes needed |
| :--- | :--- |
| `graph_engine.py` | Zero strategy knowledge — pure DAG infrastructure |
**That's it.** Only 1 of 7 tools is truly reusable without any modification. `weekly_reoptimize.py` uses `subprocess.run()` but has hardcoded tool paths (`parameter_sweeper.py`, `ticker_clusterer.py`, `weight_learner.py`) — it would need parameterization to call strategy-specific tools.

---

## 2. The General Strategy in Neural Terms

### 2.1 Current general strategy (FACT — verified against code)

**FACT:** `backtest_engine.py::run_simulation()` implements:
- Buy at wick-adjusted support levels (calls `wick_offset_analyzer.py::analyze_stock_data()` at line 509 for level recomputation)
- Hold for days/weeks until profit target or stop hit
- Sell targets in simulation: **6.0% / 8.0% / 10.0%** (from `backtest_config.py` lines 117-119: `sell_default=6.0`, `sell_fast_cycler=8.0`, `sell_exceptional=10.0`)
- NOTE: The live `sell_target_calculator.py` uses 4.5%/6.0%/7.5% — different from the simulation values
- Bullet sizing: multiple entries at different support levels
- Data loading: `load_collected_data()` reads pre-saved `price_data.pkl` — does NOT download data itself. Downloads happen in a separate `backtest_data_collector.py` step.

### 2.2 Observer neurons for the general strategy (PROPOSED)

| Observer | What it measures | Source (FACT — verified exists) |
| :--- | :--- | :--- |
| `{tk}:rsi_level` | Current RSI value (continuous 0-100) | `technical_scanner.py::calc_rsi()` (line 13) |
| `{tk}:macd_level` | MACD histogram value | `technical_scanner.py::calc_macd()` (line 23) |
| `{tk}:momentum_level` | Composite momentum classification | `shared_utils.py::classify_momentum()` (line 321) |
| `{tk}:pl_pct` | Current position P/L % | `graph_builder.py` (line ~253, already a graph node) |
| `{tk}:days_held` | Days since entry | `graph_builder.py` (line ~268, already a graph node) |
| `{tk}:cycle_speed` | Median days between fills | `tickers/<TICKER>/cycle_timing.json` (100+ files exist) |
| `regime_level` | VIX value (continuous) | yfinance ^VIX |

**NOTE:** `{tk}:support_distance` and `{tk}:tier_quality` are PROPOSED observers that would need NEW computation code — these values are not currently available as simple function calls. Support distance requires loading wick analysis data and finding the nearest level to current price. Tier quality requires loading the wick analysis hold rates.

**Execution-layer observers (PROPOSED):**

| Observer | What it measures | Current source (FACT) |
| :--- | :--- | :--- |
| `{tk}:pool_utilization` | % of active pool currently deployed | Computable from portfolio.json positions vs `active_pool` |
| `{tk}:bullets_used` | Number of active bullets filled | `portfolio.json` positions `bullets_used` field |
| `{tk}:avg_cost` | Current average entry price | `portfolio.json` positions `avg_cost` field |
| `{tk}:level_count` | Number of support levels in active zone | `tickers/<TICKER>/wick_analysis.md` (must parse) |

These observers feed the execution gates — when the network decides to buy, how much to allocate depends on pool utilization, bullets remaining, and level count.

### 2.3 Subscription gates (PROPOSED)

| Gate | What it decides | Current state in codebase |
| :--- | :--- | :--- |
| `{tk}:rsi_gate` | RSI <= threshold → entry signal | **No RSI entry gate exists** in the support strategy. RSI < 30 is a label in `technical_scanner.py` (line 203) used for display, NOT as a buy trigger. The support strategy buys at support levels regardless of RSI. |
| `{tk}:profit_target_gate` | P/L >= X% → sell signal | Simulation uses 6.0%/8.0%/10.0% from `backtest_config.py`. Live uses 4.5%/6.0%/7.5% from `sell_target_calculator.py`. |
| `{tk}:stop_gate` | P/L <= -X% → exit signal | Catastrophic thresholds in `shared_utils.py` — multiple levels (WARNING at -8%, HARD_STOP at deeper levels). |
| `{tk}:momentum_gate` | Momentum favorable → hold/add | `classify_momentum()` returns categorical labels, thresholds are in the function. |
| `regime_gate` | VIX <= threshold → favorable regime | VIX > 25 = Risk-Off, VIX < 20 = Risk-On, 20-25 = Neutral (from `backtest_config.py` line 44, `market_context_pre_analyst.py` line 35 — uses strict `>` 25, so VIX exactly 25.0 is Neutral). Three regimes, not a binary gate. |

### 2.4 Parameters the sweep would optimize per ticker (PROPOSED)

#### Threshold parameters (selection layer)

| Parameter | Current value (FACT — from `backtest_config.py`) | Proposed sweep range |
| :--- | :--- | :--- |
| Profit target % | `sell_default=6.0` (line 117) | [4.0, 5.0, 6.0, 7.0, 8.0, 10.0] |
| Stop loss % | Varies by catastrophic level in `shared_utils.py` | [-8, -10, -15, -20, -25] |
| RSI entry threshold | Does not exist — would be NEW | [20, 25, 30, 35, 40] |
| VIX regime threshold | VIX > 25 = Risk-Off (`backtest_config.py` line 44, strict >) | [18, 20, 25, 30, 35] |

#### Execution parameters (position building layer)

| Parameter | Current value (FACT — from `backtest_config.py`) | Proposed sweep range |
| :--- | :--- | :--- |
| Active pool $ | `active_pool=300.0` (line 105) | [200, 300, 400, 500, 750] |
| Reserve pool $ | `reserve_pool=300.0` (line 106) | [200, 300, 400, 500] |
| Active bullets max | `active_bullets_max=5` (line 107) | [3, 4, 5, 6, 7] |
| Reserve bullets max | `reserve_bullets_max=3` (line 108) | [2, 3, 4, 5] |
| Tier full threshold (hold rate %) | `tier_full=50` (line 111) | [40, 50, 60, 70] |
| Tier std threshold (hold rate %) | `tier_std=30` (line 112) | [20, 30, 40] |

#### What this means for the sweep grid

**Threshold-only sweep** (selection layer): 6 × 5 × 5 × 5 = **750 combos**
**Full sweep** (threshold + execution): 750 × 5 × 4 × 5 × 4 × 4 × 3 = **180 million combos** — clearly infeasible as brute force.

**PROPOSED solution**: Two-stage sweep:
1. **Stage 1**: Sweep threshold parameters (750 combos) with fixed execution params (current defaults). Find optimal thresholds per ticker.
2. **Stage 2**: With optimal thresholds locked, sweep execution parameters (5 × 4 × 5 × 4 × 4 × 3 = 4,800 combos) to find optimal pool/bullet/tier sizing per ticker.
3. Total: 750 + 4,800 = **5,550 combos** — manageable.

This two-stage approach works because threshold parameters (when to buy/sell) and execution parameters (how much to buy) are approximately independent — changing the pool size doesn't change WHEN you buy, only HOW MUCH.

#### What the network would discover per ticker (PROPOSED)

After the sweep, each ticker gets a complete learned profile:

```json
{
  "CRDO": {
    "profit_target_pct": 7.0,
    "stop_pct": -10,
    "rsi_entry": 35,
    "vix_threshold": 25,
    "active_pool": 500,
    "reserve_pool": 300,
    "active_bullets_max": 4,
    "reserve_bullets_max": 3,
    "tier_full": 60,
    "tier_std": 30
  }
}
```

**HYPOTHETICAL example**: CRDO might deserve $500 pool (higher conviction), 7% target (bigger swings), only 4 active bullets (fewer but larger entries), and a tighter tier_full threshold of 60% (only trust levels with strong hold rates). All discovered from simulation P/L, not guessed.

---

## 3. The Simulation Runtime Problem

### 3.1 Why the dip strategy sweeps fast (FACT)

**FACT:** The dip strategy sweeper pre-computes signals once (graph-based), then sweeps parameter combos as pure arithmetic on pre-computed entry/high/low/close values. 600 combos per ticker in ~0.01s each.

This works because the dip strategy is **stateless within a day**: each trade is independent (buy in morning, sell by close). Changing the target % doesn't affect which days you trade or what entry price you get.

### 3.2 Why the support strategy can't sweep the same way (FACT)

**FACT:** The support strategy is **path-dependent across days**:
- Bullet 1 fills at support level A → average cost changes
- Bullet 2 fills at support level B → average cost changes again
- Sell target depends on current average cost
- Changing the profit target changes WHEN you sell, which changes how many bullets are still active, which changes the average cost for the NEXT trade

You cannot sweep profit targets arithmetically on pre-computed data because each target value creates a different trade sequence.

### 3.3 Runtime estimates (ESTIMATE — not measured)

**ESTIMATE:** `backtest_engine.py::run_simulation()` runtime per invocation is unmeasured. It processes daily bars over 10+ months, recomputes wick levels weekly via `analyze_stock_data()` (line 509), and simulates trade-by-trade. Plausible range: 30 seconds to 5 minutes per ticker per parameter set, depending on trade frequency and level recomputation cost. Must benchmark before planning.

**Brute-force sweep**: 5,550 combos (two-stage) × 30s = 46 hours per ticker. At 1,500 tickers = ~69,000 hours. Still infeasible for full universe.

**Practical approach**: Sweep threshold params only (750 combos) on top 100 universe passers. At 30s/combo: 750 × 30s × 100 tickers = 625 hours. With multiprocessing (8 cores): ~78 hours = 3.25 days. Feasible as a weekend batch job. Then sweep execution params (4,800 combos) only on the top 30 that passed threshold sweep.

### 3.4 Options to make it feasible (PROPOSED)

**Option A: Simplified P/L model for sweep, full simulation for validation**
Build a simplified daily replay that approximates the support strategy without full wick recomputation:
1. Pre-compute support levels once per ticker (not weekly)
2. For each day, check if price hit a support level → entry
3. For each open position, check if P/L hit target → exit
4. Sweep target/stop thresholds on this simplified model
5. Run full `backtest_engine.py` only on top 50 candidates to validate

This is conceptually similar to how the dip sweeper pre-computes signals.

**Option B: Parameterize backtest_engine.py**
Modify `backtest_engine.py` to accept profit target / stop / RSI thresholds as config parameters instead of reading from `backtest_config.py`. Run the full simulation per combo. Use `multiprocessing` to parallelize across tickers.

**Option C: Reduce the grid**
Instead of 750 combos, sweep fewer parameters. If we only sweep profit target (6 values) and stop (5 values) = 30 combos per ticker. At 30s each = 15 minutes per ticker. At 100 tickers (top universe passers) = 25 hours. Feasible as a weekend batch job.

---

## 4. Baseline Preservation — The Dip Strategy Is the Reference Point

### 4.1 Why we don't touch the dip implementation (FACT)

The dip strategy (Phases 1-5 + candidate discoverer) is a proven, running system:
- **$46.57 profit across 142 trades** in 60-day backtest on 30 discovered candidates
- **All 30 candidates profitable** in out-of-sample validation
- **12-minute universe scan** across 1,477 tickers
- **Learned per-ticker parameters**: dip threshold, target, stop, breadth — all data-driven
- **Synapse weights trained** from trade outcomes
- **Weekly re-optimization pipeline** running

This is our control group. If the support strategy neural network produces worse results than the dip network, we know because we kept the dip results intact for comparison.

### 4.2 What "keep intact" means concretely

**ZERO modifications to these files:**

| File | Reason |
| :--- | :--- |
| `neural_dip_evaluator.py` | Live dip trading logic — must not regress |
| `parameter_sweeper.py` | Produces dip profiles + sweep results — baseline data |
| `neural_candidate_discoverer.py` | Produced the 30-candidate reference results |
| `neural_dip_backtester.py` | Validates dip strategy — must reproduce same P/L |
| `data/neural_candidates.json` | The 30-candidate baseline — keep for comparison |
| `data/sweep_results.json` | Dip sweep training data — keep for reference |

**Modifications allowed ONLY if backward compatible:**

| File | Allowed change | Constraint |
| :--- | :--- | :--- |
| `weight_learner.py` | Add configurable normalization | Must default to `/10.0` when no config passed — dip learning unchanged |
| `ticker_clusterer.py` | Accept feature columns as parameter | Must default to current `FEATURE_COLS` — dip clustering unchanged |
| `backtest_engine.py` | Accept target/stop/pool/bullets/tier as config overrides | Must default to `SurgicalSimConfig` defaults (6.0%/300/5/50 etc.) — existing simulation unchanged |
| `weekly_reoptimize.py` | Parameterize tool paths | Must default to current dip tools — existing pipeline unchanged |
| `graph_engine.py` | No changes needed | Already strategy-agnostic |

### 4.3 How we compare results

After the support strategy neural network runs on the same universe:

```
COMPARISON TABLE (PROPOSED):
| Metric                  | Dip Strategy (baseline) | Support Strategy (new) |
| :---                    | :---                    | :---                   |
| Universe tickers swept  | 1,477                   | same 1,477             |
| Passed all gates        | 56                      | ?                      |
| Top 30 total val P/L    | $22.16                  | ?                      |
| Top 30 total train P/L  | $24.41                  | ?                      |
| Total trades (60 days)  | 142                     | ?                      |
| Avg P/L per trade       | $0.33                   | ?                      |
| Learned breadth range   | 10-30%                  | N/A (different signal)  |
| Sweep time              | 12 min                  | ? (depends on Option)  |
```

Both strategies run on the SAME universe and the SAME time period. The comparison is apples-to-apples — which neural network finds more profitable candidates?

A ticker can appear in BOTH top-30 lists — "CRDO is profitable for same-day dip buys AND for support-based swing trades." That's a strong signal.

---

## 5. What Must Be Built

### 5.1 New files needed (PROPOSED)

| File | Purpose | Estimated lines |
| :--- | :--- | :--- |
| `tools/support_parameter_sweeper.py` | Two-stage sweep: (1) threshold params via backtest_engine, (2) execution params (pool/bullets/tier) | ~300 |
| `tools/support_feature_extractor.py` | Extract behavioral features for clustering (hold duration, target hit rate, cycle speed, support reliability, pool efficiency) | ~120 |
| `tools/neural_support_discoverer.py` | Universe-scale discovery for support strategy — rank by validation P/L, output top 30 with complete profiles (thresholds + execution params) | ~250 |

### 5.2 Files needing backward-compatible modification (PROPOSED)

All modifications MUST preserve existing behavior when called without new parameters:

| File | Change | Backward-compat constraint | Estimated lines |
| :--- | :--- | :--- | :--- |
| `tools/weight_learner.py` | Add `norm_divisor` parameter | Default `norm_divisor=10.0` preserves dip behavior | ~10 |
| `tools/ticker_clusterer.py` | Add `feature_cols` parameter | Default to current `FEATURE_COLS` constant | ~15 |
| `tools/backtest_engine.py` | Add `sell_target_pct` / `stop_pct` parameters to `run_simulation()` | Default to `backtest_config.py` values (6.0/8.0/10.0) | ~20 |
| `tools/weekly_reoptimize.py` | Add `--strategy` flag to select tool set | Default `--strategy dip` runs current pipeline unchanged | ~15 |

### 5.3 Files NOT changed (baseline preservation)

| File | Why |
| :--- | :--- |
| `graph_engine.py` | Truly strategy-agnostic — no changes needed |
| `neural_dip_evaluator.py` | Baseline dip trading logic — frozen |
| `parameter_sweeper.py` | Baseline dip sweep — frozen |
| `neural_candidate_discoverer.py` | Produced baseline 30-candidate results — frozen |
| `neural_dip_backtester.py` | Baseline validation — frozen |
| `data/neural_candidates.json` | Baseline 30-candidate results — preserved for comparison |
| `data/sweep_results.json` | Baseline dip sweep training data — preserved for reference |

---

## 6. What the Unified System Would Look Like (PROPOSED)

```
TRULY SHARED (no changes):
  graph_engine.py              — DAG computation

SHARED WITH BACKWARD-COMPATIBLE MODIFICATIONS:
  weight_learner.py            — add norm_divisor param (default=10.0)
  ticker_clusterer.py          — add feature_cols param (default=current FEATURE_COLS)
  backtest_engine.py           — accept all SurgicalSimConfig fields as overrides
  weekly_reoptimize.py         — add --strategy flag (default=dip)

STRATEGY MODULE 1 — Same-Day Dip (FROZEN BASELINE):
  neural_dip_evaluator.py      — dip observers + gates (DO NOT MODIFY)
  parameter_sweeper.py         — dip parameter sweep (DO NOT MODIFY)
  neural_candidate_discoverer.py — dip universe discovery (DO NOT MODIFY)
  neural_dip_backtester.py     — dip validation (DO NOT MODIFY)
  data/neural_candidates.json  — baseline 30 candidates (PRESERVE)
  data/sweep_results.json      — baseline dip sweep data (PRESERVE)

STRATEGY MODULE 2 — Support-Based (NEW):
  support_parameter_sweeper.py — support strategy sweep
  support_feature_extractor.py — support behavioral features
  neural_support_discoverer.py — support universe discovery
  data/neural_support_candidates.json — support candidates (separate file)

EACH MODULE produces per-ticker learned profiles:
  DIP profile:     {dip_threshold, bounce_threshold, target_pct, stop_pct, breadth_threshold}
  SUPPORT profile: {profit_target_pct, stop_pct, rsi_entry, vix_threshold,
                    active_pool, reserve_pool, active_bullets_max,
                    reserve_bullets_max, tier_full, tier_std}

COMPARISON:
  Both modules run on the same universe (1,477 tickers).
  Both produce ranked candidates with learned profiles.
  Compare: which strategy finds more profitable candidates?
  Tickers appearing in BOTH top-30 lists = highest confidence picks.
```

---

## 7. Open Questions

1. **Simulation runtime** — UNMEASURED. Must benchmark `backtest_engine.py::run_simulation()` per invocation before choosing between Option A (simplified model), B (parameterized full sim), or C (smaller grid). Run: time a single simulation call.

2. **Which parameters actually matter?** — The dip strategy has 4 swept parameters. The support strategy may benefit from fewer. If only profit target and stop matter (not RSI entry), the grid is 30 combos instead of 750 — much more feasible.

3. **Path dependency** — Can a simplified model approximate the full simulation well enough for sweep ranking? If the simplified model picks the same top 30 as the full simulation, it's good enough. Must validate.

4. **Feature columns for support clustering** — What behavioral features distinguish support-strategy tickers? Candidates: median hold duration, target-hit-to-stop-hit ratio, cycle speed, level count, average recovery depth. Must be discovered from simulation data.

5. **Weight normalization** — RSI ranges 0-100, support distance might range 0-20%, P/L ranges -25% to +10%. The weight learner needs per-feature normalization, not a global `/10.0`. Options: min-max scaling, z-score, or per-feature divisor from training data.

6. **Two-stage sweep independence assumption** — The plan assumes threshold params and execution params are approximately independent (pool size doesn't change WHEN you buy). This is mostly true but not perfectly — a larger pool means more bullets available, which means more entries, which changes average cost, which changes when target is hit. Must validate by checking whether Stage 2 results change significantly when Stage 1 thresholds vary.

7. **Pool size vs share price scaling** — FACT: current strategy sizes bullets at ~$100 for $16+ stocks, ~$30 for $1.50 stocks (from MEMORY.md strategy rules). Pool sweep must respect this — a $750 pool on a $3 stock means very different share counts than on a $50 stock. The sweep should compute shares-per-bullet from pool÷bullets÷price, matching `bullet_recommender.py` logic.

8. **Support level selection** — Currently wick-adjusted levels come from `wick_offset_analyzer.py`. The neural network does NOT learn which support levels to use — it learns how to SIZE and THRESHOLD around them. Level selection stays with wick analysis. Is this the right split, or should level quality also be a swept parameter?
