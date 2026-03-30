# Analysis: Applying the Neural Network to the General Support-Based Strategy

**Date**: 2026-03-29 (Sunday, 5:29 PM local / 10:29 AM ET)
**Purpose**: Determine whether the neural architecture (Phases 1-5) can be applied to the existing multi-day support-based strategy, not just same-day dip buying.

**Honesty note**: Every claim labeled FACT (verified against code), ESTIMATE, PROPOSED, or HYPOTHETICAL.

---

## 1. The Architecture Is Strategy-Agnostic

**FACT:** The graph engine (`tools/graph_engine.py`) has zero knowledge of trading strategies. It provides:
- `Node` with `compute: Callable[[dict], Any]` — accepts any function
- `Signal` with `old_value: Any, new_value: Any` — carries any type
- `edge_weights: dict[str, float]` — learned weights on any connection
- Topological sort + resolve — works on any DAG

**FACT:** The learning infrastructure has zero strategy coupling:
- `weight_learner.py` reads `fired_inputs` and `pnl` — doesn't know what the inputs represent
- `ticker_clusterer.py` clusters on feature vectors — doesn't know what the features mean
- `parameter_sweeper.py` sweeps parameter combos and evaluates P/L — the strategy is in the simulation, not the sweeper

**Conclusion:** The architecture transfers directly. The strategy-specific parts are:
1. Which observer neurons exist (what values to measure)
2. Which subscription gates exist (what thresholds to learn)
3. Which simulation evaluates P/L (what strategy to replay)

---

## 2. What the General Strategy Looks Like in Neural Terms

### 2.1 Current general strategy (FACT — from backtest_engine.py)

**FACT:** `backtest_engine.py::run_simulation()` implements:
- Buy at wick-adjusted support levels (computed by `wick_offset_analyzer.py`)
- Hold for days/weeks until profit target or stop hit
- Sell targets: 4.5% / 6.0% / 7.5% above average cost
- Bullet sizing: multiple entries at different support levels
- Cycle timing: how fast support levels get touched and recovered
- Tier system: Skip / Half / Standard / Full sizing based on level reliability

### 2.2 Observer neurons for the general strategy (PROPOSED)

| Observer | What it measures | Source |
| :--- | :--- | :--- |
| `{tk}:support_distance` | % distance from price to nearest support level | wick_analysis.md / bullet_recommender.py |
| `{tk}:rsi_level` | Current RSI value (continuous 0-100) | technical_scanner.py::calc_rsi() |
| `{tk}:macd_level` | MACD histogram value | technical_scanner.py::calc_macd() |
| `{tk}:momentum_level` | Composite momentum (RSI + MACD) | shared_utils.py::classify_momentum() |
| `{tk}:pl_pct` | Current position P/L % | graph_builder.py (already exists) |
| `{tk}:days_held` | Days since entry | graph_builder.py (already exists) |
| `{tk}:tier_quality` | Hold rate at nearest support level | wick_analysis.md |
| `{tk}:cycle_speed` | Median days between fills | cycle_timing.json |
| `regime_level` | VIX value (continuous, not bucketed) | yfinance ^VIX |
| `{tk}:volume_ratio` | Today's volume vs 20-day average | yfinance |

### 2.3 Subscription gates (PROPOSED)

| Gate | What it decides | Currently hard-coded as |
| :--- | :--- | :--- |
| `{tk}:rsi_gate` | RSI <= threshold → entry signal | Fixed at RSI < 30 (oversold) |
| `{tk}:support_gate` | Price within X% of support → entry signal | Fixed support levels from wick analysis |
| `{tk}:profit_target_gate` | P/L >= X% → sell signal | Fixed at 4.5% / 6.0% / 7.5% |
| `{tk}:stop_gate` | P/L <= -X% → exit signal | Fixed catastrophic thresholds |
| `{tk}:momentum_gate` | Momentum score >= threshold | Fixed classify_momentum() thresholds |
| `regime_gate` | VIX <= threshold → favorable regime | Fixed at VIX < 25 for Risk-On |

### 2.4 What the sweep would optimize per ticker (PROPOSED)

| Parameter | Current | Swept range (PROPOSED) |
| :--- | :--- | :--- |
| Profit target % | Fixed 4.5% | [3.0, 4.0, 4.5, 5.0, 6.0, 7.5] |
| Stop loss % | Fixed per catastrophic threshold | [-5, -8, -10, -15, -20] |
| RSI entry threshold | Fixed 30 | [20, 25, 30, 35, 40] |
| Support proximity % | Not parameterized | [1, 2, 3, 5, 8] |
| VIX regime threshold | Fixed 25 | [18, 20, 25, 30, 35] |

---

## 3. What Exists vs What Must Be Built

### 3.1 Already exists (FACT)

| Component | File | Status |
| :--- | :--- | :--- |
| Graph engine with edge weights | `graph_engine.py` | Built (Phase 3) |
| Level-firing observer pattern | `neural_dip_evaluator.py` | Built (Phase 1) |
| Subscription gate pattern | `neural_dip_evaluator.py` | Built (Phase 1) |
| Synapse weight learning | `weight_learner.py` | Built (Phase 3) |
| Behavioral clustering | `ticker_clusterer.py` | Built (Phase 2) |
| Parameter sweep infrastructure | `parameter_sweeper.py` | Built (Phase 2) |
| Cross-validation | `parameter_sweeper.py` | Built (Phase 5) |
| Portfolio optimization (sector/correlation) | `neural_dip_evaluator.py` | Built (Phase 4) |
| Weekly re-optimization pipeline | `weekly_reoptimize.py` | Built (Phase 5) |
| Support-based simulation | `backtest_engine.py` | Built (existing) |
| RSI/MACD computation | `technical_scanner.py` | Built (existing) |
| Wick analysis | `wick_offset_analyzer.py` | Built (existing) |
| Daily analyzer graph builder | `graph_builder.py` | Built (existing) |

### 3.2 Must be built (PROPOSED)

| Component | What | Estimated effort |
| :--- | :--- | :--- |
| General strategy parameter sweeper | Sweep profit target / stop / RSI / support proximity using `backtest_engine.py` as the simulator | New file, ~200 lines |
| General strategy observer neurons | Plug RSI, MACD, support distance, etc. as level-firing observers into a graph builder | ~100 lines in new or existing file |
| General strategy feature extraction | Extract behavioral features from simulation results (hold duration, target hit rate, cycle speed) for clustering | ~50 lines |
| Unified candidate discoverer | Run both strategies (dip + support) on universe, combine rankings | Modify `neural_candidate_discoverer.py`, ~50 lines |

### 3.3 Reused unchanged

| Component | Why no changes |
| :--- | :--- |
| `graph_engine.py` | Strategy-agnostic infrastructure |
| `weight_learner.py` | Reads `fired_inputs` + `pnl`, doesn't know strategy |
| `ticker_clusterer.py` | Clusters on feature vectors, doesn't know strategy |
| `weekly_reoptimize.py` | Pipeline orchestrator, calls tools |

---

## 4. Key Difference: Simulation Runtime

**FACT:** The same-day dip strategy sweeps 600 combos per ticker in ~0.01s each (pure arithmetic on pre-computed signals). Total: 1,477 tickers in 12 minutes.

**FACT:** The general strategy simulation (`backtest_engine.py`) takes ~3-5 minutes per ticker per parameter set (downloads 13-month history, computes wick analysis, runs multi-period simulation).

**This is the bottleneck.** Sweeping 6 targets × 5 stops × 5 RSI × 5 proximity = 750 combos per ticker at 3 min each = 2,250 minutes = 37.5 hours per ticker. At 1,500 tickers this is impossible.

### 4.1 How to make it feasible (PROPOSED)

**Option A: Pre-compute once, sweep arithmetically**
Same approach as the dip strategy. Run the simulation ONCE per ticker to get daily trade data (entries, exits, P/L at each support level). Then sweep different thresholds as arithmetic on the pre-computed data. This is how `parameter_sweeper.py` works — build the graph once, then sweep combos as math.

**Challenge:** The general strategy has path-dependent state (bullets fill sequentially, average cost changes with each fill, sell targets depend on average cost). This makes pure arithmetic sweeping harder — you can't just change the profit target independently of the entry sequence.

**Option B: Parameterize the existing simulation**
Modify `backtest_engine.py` to accept target/stop/RSI thresholds as parameters instead of hard-coding them. Run the simulation once per parameter combo. At 750 combos × 3 min = 37 hours per ticker — still too slow for 1,500 tickers.

**Option C: Simplified simulation for sweep, full simulation for validation**
1. Use a simplified P/L model for the sweep (similar to how the dip sweeper uses entry vs remaining high/low/close)
2. Run full `backtest_engine.py` simulation only on the top 50 candidates to validate

This is the most pragmatic approach and mirrors how `sim_ranked_screener.py` already works — screen broadly, validate narrowly.

**Option D: Pre-compute daily price features, sweep entry/exit rules arithmetically**
For each ticker, pre-compute: daily RSI, daily support distance, daily P/L if entered at support. Then sweep "enter when RSI < X AND support_distance < Y, exit when P/L > Z" as pure arithmetic on the pre-computed daily features. This bypasses the full simulation for the sweep phase.

---

## 5. What the Unified System Would Look Like

### 5.1 Two strategy modules, one neural network (PROPOSED)

```
SHARED INFRASTRUCTURE (exists):
  graph_engine.py          — DAG computation
  weight_learner.py        — Hebbian weight updates
  ticker_clusterer.py      — behavioral clustering
  parameter_sweeper.py     — sweep + cross-validate
  weekly_reoptimize.py     — automated pipeline

STRATEGY MODULE 1: Same-Day Dip (exists):
  neural_dip_evaluator.py  — dip observers + gates
  parameter_sweeper.py     — dip parameter sweep
  neural_candidate_discoverer.py — universe discovery

STRATEGY MODULE 2: Support-Based (PROPOSED):
  neural_support_evaluator.py  — support/RSI/momentum observers + gates
  support_parameter_sweeper.py — support strategy parameter sweep
  neural_support_discoverer.py — universe discovery for support strategy

UNIFIED OUTPUT:
  Both modules produce ranked candidates with learned profiles.
  A ticker can appear in both — "good for dip buys AND support buys."
```

---

## 6. Open Questions

1. **Path-dependent simulation** — The support strategy has stateful bullet sequences. Can this be swept arithmetically (Option D), or does each combo need a full simulation (Option B)?

2. **What parameters actually matter?** — The dip strategy has 4 parameters (dip, target, stop, breadth). The support strategy may have more (target, stop, RSI, support proximity, tier, bullet count). More parameters = exponentially larger sweep grid.

3. **Should this be a separate sweep or unified?** — Two separate sweepers (dip + support) or one that handles both strategies? Separate is simpler and doesn't require changing the existing dip sweeper.

4. **Runtime feasibility at 1,500 tickers** — Even with Option D (arithmetic sweep on pre-computed features), computing daily RSI/MACD/support distance for 1,500 tickers over 13 months requires downloading 13 months of daily data for all tickers. The download alone may take 30+ minutes.
