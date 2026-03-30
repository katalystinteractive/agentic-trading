# Analysis: Neural Network Candidate Discovery at Universe Scale

**Date**: 2026-03-29 (Sunday, 4:10 PM local / 9:10 AM ET)
**Purpose**: Apply the neural network (Phases 1-5) to the full universe of tickers (~1,500 passers) to discover the top 30 same-day dip-buy candidates, ranked by neural simulation P/L.

**Honesty note**: Every claim labeled FACT (verified), ESTIMATE, or PROPOSED.

---

## 1. What Exists Today

### 1.1 Universe pipeline (FACT)
- `data/us_universe.json` — 6,851 US tickers (NASDAQ FTP)
- `tools/universe_screener.py` — filters to ~1,502 passers (price $3-60, vol ≥500K, swing ≥10%, consistency ≥80%), cached in `data/universe_screen_cache.json` with 7-day validity
- `tools/sim_ranked_screener.py` — takes top N passers by tradability (swing × volume), runs 10-month multi-period backtest on each, ranks by P/L

### 1.2 Current simulation (FACT)
- `tools/candidate_sim_gate.py` → `backtest_engine.py::run_simulation()` — multi-period support-based strategy simulation (buy at wick-adjusted support, sell at profit target)
- Returns: trades, cycles, equity_curve, dip_metrics
- Gate thresholds: P/L > $0, Win > 90%, Sharpe > 2, zero catastrophic stops (Conversion gate was removed 2026-03-27)
- Runtime: ESTIMATE ~3-5 minutes per ticker (downloads 13-month history, computes wick analysis, runs simulation — not formally benchmarked)

### 1.3 Neural network (FACT — just built)
- Level-firing observers → subscription gates with per-ticker thresholds
- Learned synapse weights (reward-modulated Hebbian)
- Soft AND aggregator (safety gates hard AND)
- Per-ticker profiles with cluster assignments + confidence scores
- Parameter sweeper: pre-computes signals once per dip_threshold, sweeps target/stop as arithmetic
- Weekly re-optimization pipeline

### 1.4 Key finding from memory (FACT)
> "100-point scoring has zero correlation with simulation P/L. Simulation is the only reliable predictor."

This means the neural network's value is NOT in replacing the scoring — it's in replacing the dip-strategy parameters with data-driven, per-ticker optimized thresholds. The simulation remains the ranking method.

---

## 2. The Problem: Two Different Strategies

**FACT:** The current system has TWO distinct trading strategies:

| Aspect | Support-Based (existing sim) | Same-Day Dip (neural network) |
| :--- | :--- | :--- |
| Hold period | Days to weeks | Same day (buy AM, sell PM) |
| Entry signal | Price hits wick-adjusted support level | Morning dip + bounce pattern |
| Exit signal | Sell target (4.5-7.5% above avg cost) | Intraday target, stop, or EOD cut |
| Data needed | 13-month daily + wick analysis | 60-day 5-minute bars |
| Simulation | `backtest_engine.py` (multi-period) | `neural_dip_backtester.py` (intraday replay) |
| Parameters | Support levels, tier sizing, bullets | Dip threshold, bounce threshold, target, stop |

**The neural network we built is for the same-day dip strategy.** Applying it to candidate discovery means: find the top 30 tickers where the neural dip-buy strategy produces the best P/L when replayed over historical intraday data.

---

## 3. What "Neural Candidate Discovery" Means

### 3.1 The pipeline

```
Step 1: Universe filter (existing)
  ~6,800 tickers → ~1,500 passers (price/vol/swing gates)

Step 2: Neural parameter sweep (existing tools, new scale)
  For each of ~1,500 passers:
    - Download 60-day 5-min data
    - Pre-compute signals per dip_threshold
    - Sweep 120 target/stop/dip combos
    - Find best params + compute features
    - Cross-validate (train 2/3, validate 1/3)

Step 3: Rank by neural simulation P/L
  Sort by best P/L from sweep
  Apply gates: minimum trades, positive P/L, no overfitting

Step 4: Cluster and assign profiles
  Run ticker_clusterer.py on the top candidates
  Assign cluster defaults to each

Step 5: Output top 30
  Per-ticker: optimal params, P/L, win rate, cluster, confidence, CV result
```

### 3.2 What this replaces

Currently `sim_ranked_screener.py` runs the support-based simulation (~3-5 min/ticker, 30 tickers = ~2 hours). The neural candidate discoverer runs the intraday dip sweep (~0.7s/ticker after signal pre-computation, 1,500 tickers = ~20 minutes total).

**Observed:** The parameter sweeper ran 21 tickers in 14 seconds. This includes BOTH the shared signal pre-computation (graph-based, ~12s) AND the per-ticker sweep (arithmetic, ~2s for all 21). The per-ticker sweep time is negligible; the pre-computation dominates.

**ESTIMATE at 1,500 tickers:** Signal pre-computation scales with ticker count (graph node count grows). At 1,500 tickers, the graph builds ~5 dip thresholds × ~12 signal days = ~60 graph builds, each with 1,500 ticker nodes (~12,000 nodes). The per-ticker arithmetic sweep stays fast. The TWO bottlenecks are: (1) yfinance download for 1,500 tickers' 60-day 5-min data, (2) graph builds with 12,000 nodes. Both are UNMEASURED.

---

## 4. Data Constraints

### 4.1 yfinance 5-min data limits (FACT)
- Max 60 days of 5-min bars per ticker
- yfinance bulk download: `yf.download(tickers, period="60d", interval="5m")` supports multi-ticker download in one call
- At 1,500 tickers, this is a large download but yfinance handles it (chunks internally)

### 4.2 Download time (ESTIMATE)
- **FACT:** Current download for 21 tickers: ~10 seconds
- **ESTIMATE at 1,500:** yfinance chunks downloads internally. Expected ~5-10 minutes for 1,500 tickers. Must measure.

### 4.3 Memory (ESTIMATE)
- 21 tickers × 60 days × 78 bars/day × 6 columns (OHLCV + Adj Close) = ~589K values. Fits in ~5MB.
- 1,500 tickers × same = ~42M values. At 8 bytes/float64 = ~321MB. Should fit on a 16GB machine but worth verifying.

### 4.4 Signal pre-computation scaling (ESTIMATE)
- Current: 5 dip thresholds × 21 tickers × 60 days = builds the graph 300 times (each with 21 ticker nodes)
- At 1,500: 5 × 1500 × 60 = builds the graph 300 times (each with 1,500 ticker nodes)
- **The graph build count stays at 300** — it's the node count per graph that scales. 1,500 nodes × ~8 nodes/ticker = 12,000 nodes per graph.
- **UNMEASURED:** Resolve time for 12,000 nodes. Expected sub-second (topological sort + trivial lambdas).

**Critical insight:** The pre-computation approach from `parameter_sweeper.py` is essential at this scale. Building the graph once per dip_threshold per day, then doing pure arithmetic for the 120 target/stop combos per ticker, is what makes this feasible. Without it, we'd need 1,500 × 120 × 60 = 10.8 million graph builds.

---

## 5. Architecture: Neural Candidate Discoverer

### 5.1 New file: `tools/neural_candidate_discoverer.py`

**Purpose:** Scan the full universe through the neural dip strategy. Rank by P/L. Output top 30.

```
Input:  data/universe_screen_cache.json (1,500 passers)
Output: data/neural_candidates.json (top 30 with profiles)
        data/neural_candidates.md (human-readable report)
```

### 5.2 Pipeline stages

**Stage 1: Load universe passers**
- Read `data/universe_screen_cache.json`
- Exclude already-onboarded tickers (portfolio positions + watchlist)
- Apply tighter gates if needed (min swing, min volume)

**Stage 2: Download intraday data**
- `yf.download(all_tickers, period="60d", interval="5m")`
- One bulk download for all ~1,500 tickers
- Cache to `data/backtest/universe_intraday_cache.pkl`

**Stage 3: Pre-compute signals**
- Reuse `precompute_signals()` from `parameter_sweeper.py`
- This is the bottleneck — builds the graph for all tickers on each signal day
- **Optimization needed:** At 1,500 tickers, the breadth threshold (50% must dip) means fewer signal days. But the graph must still be built to CHECK breadth.

**Stage 4: Sweep per ticker**
- Reuse `sweep_ticker()` from `parameter_sweeper.py`
- Pure arithmetic after pre-computation — fast

**Stage 5: Cross-validate**
- `--split` mode: train on first 40 days, validate on last 20
- Flag tickers where train P/L > 0 but validation P/L < 0

**Stage 6: Rank and gate**
- Sort by validation P/L (not train P/L — to avoid overfitting)
- Gates:
  - Minimum 3 trades in validation window
  - Positive validation P/L
  - No overfitting flag (train positive, validation negative → reject)
  - Confidence score ≥ 40

**Stage 7: Cluster top candidates**
- Run clustering on the top 50 candidates (not all 1,500 — most will fail gates)
- Assign cluster profiles

**Stage 8: Output top 30**
- Write `data/neural_candidates.json` with per-ticker profiles + metrics
- Write `data/neural_candidates.md` with ranked table

### 5.3 Chunking strategy for 1,500 tickers

**Problem:** `precompute_signals()` builds the graph with ALL tickers. At 1,500 tickers, breadth = percentage of tickers dipping. The breadth calculation is global — it needs all tickers at once.

**Options:**

A. **Single graph with 1,500 tickers** — Build one massive graph. 1,500 × 8 = 12,000 nodes. Must measure resolve time. If <2s, this is the simplest approach.

B. **Two-pass approach:**
   1. First pass: Compute dip_pct for all 1,500 tickers (no graph — just math). Determine which days have 50%+ breadth.
   2. Second pass: On breadth-passing days only, build the graph for candidate evaluation.

   This avoids building 12,000-node graphs on days where breadth won't fire anyway (most days).

C. **Shard by sector, aggregate breadth:**
   Split tickers into sector shards. Compute breadth across all shards. Only build decision graphs for shards with candidates.

**Recommendation:** Option B (two-pass). Pass 1 is trivial arithmetic (compute dip_pct for each ticker from open vs 10:30 price). Pass 2 only runs on the ~20% of days where breadth fires. This reduces graph builds by 80%.

### 5.4 What existing tools are reused vs new

| Component | Status | Notes |
| :--- | :--- | :--- |
| `universe_screener.py` | REUSE as-is | Provides passer list |
| `parameter_sweeper.py::precompute_signals()` | REUSE with modification | Needs to handle 1,500 tickers |
| `parameter_sweeper.py::sweep_ticker()` | REUSE as-is | Pure arithmetic, scales linearly |
| `parameter_sweeper.py::evaluate_params()` | REUSE as-is | For cross-validation |
| `parameter_sweeper.py::_extract_features()` | REUSE as-is | For clustering |
| `ticker_clusterer.py` | REUSE as-is | Clusters top candidates |
| `weight_learner.py` | REUSE as-is | Trains weights on discovered candidates |
| Data download | NEW | Bulk 1,500-ticker 5-min download + cache |
| Two-pass breadth | NEW | Breadth pre-filter before graph builds |
| Ranking + gating | NEW | Validation-P/L ranking, overfitting rejection |
| Output formatting | NEW | Top 30 table + JSON profiles |

---

## 6. Output Schema

### 6.1 `data/neural_candidates.json`

```json
{
  "_meta": {
    "source": "neural_candidate_discoverer.py",
    "updated": "2026-03-29",
    "universe_passers": 1502,
    "tickers_with_signal": 847,
    "tickers_with_trades": 312,
    "passed_gates": 67,
    "top_n": 30
  },
  "candidates": [
    {
      "rank": 1,
      "ticker": "EXAMPLE",
      "params": {"dip_threshold": 1.0, "bounce_threshold": 0.3, "target_pct": 4.0, "stop_pct": -3.0, "breadth_threshold": 0.20},
      "train_pnl": 5.20,
      "val_pnl": 2.10,
      "train_trades": 8,
      "val_trades": 4,
      "win_rate": 75.0,
      "cluster": 2,
      "confidence": 68.5,
      "features": {...},
      "overfit": false
    },
    ...
  ]
}
```

### 6.2 Ranking criteria

Ranked by **validation P/L** (out-of-sample), not training P/L. This is the neural network's defense against overfitting — a ticker that looks great in training but loses money in validation gets flagged and rejected.

---

## 7. Differences from sim_ranked_screener.py

| Aspect | sim_ranked_screener.py | Neural candidate discoverer |
| :--- | :--- | :--- |
| Strategy simulated | Support-based (buy at wick support) | Same-day dip (buy AM dip, sell PM) |
| Data needed | 13-month daily bars | 60-day 5-min bars |
| Runtime per ticker | ESTIMATE ~3-5 min (wick analysis + sim) | Shared pre-computation + negligible per-ticker arithmetic |
| Total runtime | ESTIMATE ~2 hours for 30 tickers | UNMEASURED for 1,500 tickers (must benchmark) |
| Parameters optimized | None (fixed strategy) | 4 per ticker (dip threshold, target, stop, breadth threshold) |
| Cross-validation | None | Train 2/3, validate 1/3 |
| Overfitting detection | None | Automatic (train vs validation P/L) |
| Weight learning | None | Hebbian update from trade outcomes |
| Clustering | None | K-means behavioral clustering |

**Key advantage:** The neural discoverer tests ALL 1,500 passers and finds the ones where the dip strategy works, rather than testing 30 pre-selected tickers.

---

## 8. Breadth Threshold — Learned, Not Guessed

### 8.1 The problem with hard-coded breadth

**FACT:** Breadth is the last binary **signal-threshold** neuron among the swept parameters. The dip and bounce gates were converted to level-firing in Phase 1. Static safety gates (`dip_viable`, `not_catastrophic`, `not_exit`, `earnings_clear`, `historical_range`) are intentionally binary — they are yes/no safety checks, not continuous signals. But both `breadth_dip` AND `breadth_bounce` remain hard-coded binary neurons:

```python
breadth_dip:    breadth_ratio >= 0.50  # hard-coded at 50%, zero evidence at scale
breadth_bounce: bounce_ratio >= 0.50   # same hard-coded threshold in decision graph
```

At 21 tickers, 50% = 11 must dip. At 1,500 tickers, 50% = 750 must dip. At 5,000 tickers, 50% = 2,500 must dip. The threshold that works at 21 tickers is meaningless at scale.

### 8.2 The solution: breadth becomes a swept parameter

Breadth threshold joins the sweep grid as a 4th parameter dimension. The network discovers the optimal breadth level from data, just like it discovers optimal dip_threshold, target, and stop.

**Current sweep grid (120 combos):**
```
dip_threshold: [0.5, 1.0, 1.5, 2.0, 2.5]     — 5 values
target_pct:    [2.0, 3.0, 3.5, 4.0, 5.0, 6.0] — 6 values
stop_pct:      [-2.0, -3.0, -4.0, -5.0]        — 4 values
```

**Extended sweep grid with breadth (600 combos):**
```
dip_threshold:    [0.5, 1.0, 1.5, 2.0, 2.5]     — 5 values
target_pct:       [2.0, 3.0, 3.5, 4.0, 5.0, 6.0] — 6 values
stop_pct:         [-2.0, -3.0, -4.0, -5.0]        — 4 values
breadth_threshold: [0.10, 0.20, 0.30, 0.40, 0.50] — 5 values (NEW)
```

Total: 5 × 6 × 4 × 5 = 600 combos per ticker. The per-ticker sweep is pure arithmetic after pre-computation, so 5× more combos has negligible runtime impact.

### 8.3 What changes architecturally

**Observer neuron (already exists):**
```
breadth_level: fires with 0.23 (23% of tickers dipped today)
```

**FACT:** The raw breadth ratio IS already computed in `build_first_hour_graph()` as `breadth_ratio = dip_count / n`. It's just immediately compared to the hard-coded 0.50 threshold. Converting it to level-firing follows the exact same pattern as dip_level → dip_gate.

**Subscription gate (new):**
```
breadth_gate: breadth_level >= optimal_threshold (discovered by sweep)
```

The optimal threshold becomes part of the ticker profile. Different tickers might trade best at different breadth levels — a volatile crypto miner might profit when only 15% of the market dips (it dips harder), while a steady-state stock needs 40% breadth (true market-wide weakness).

### 8.4 Per-regime breadth thresholds

With breadth in the sweep grid AND synapse weight learning (Phase 3), the system can learn regime-specific breadth preferences:

- **Risk-On:** Lower breadth threshold works (individual dips are buyable opportunities)
- **Risk-Off:** Higher breadth threshold needed (need conviction that it's a buyable dip, not a crash)

This emerges from the weight learning — if Risk-Off dips at 15% breadth consistently lose money, the breadth_gate weight for Risk-Off gets weakened.

### 8.5 Impact on pre-computation

**Current precompute_signals():** Builds the graph once per dip_threshold (5 builds per day). Breadth is computed inside the graph and determines whether to continue.

**With breadth as a parameter:** Pre-computation needs to compute signals for ALL breadth levels, not just filter at 50%. The two-pass approach becomes:

1. **Pass 1:** Compute raw dip_pct for all tickers on all days (pure arithmetic, no graph). Also compute raw breadth_ratio per day.
2. **Pass 2:** For each dip_threshold, identify which tickers dipped. For each day, record the breadth ratio. Store the per-ticker signal data regardless of breadth — the sweep decides which breadth threshold works.

This means MORE signal data is retained (days that would have been filtered at 50% breadth are now kept for the 10%/20%/30% breadth sweeps), which gives the sweep more training data.

### 8.6 Implementation in parameter_sweeper.py

The `precompute_signals()` function currently filters by breadth:
```python
if not fh_state.get("breadth_dip"):
    continue  # skips this day entirely
```

Change to: record ALL days with their breadth ratio, let the sweep decide:
```python
# Don't filter by breadth — record the ratio, sweep decides
breadth_ratio = dip_count / n
day_signals[str(day)] = {"_breadth": breadth_ratio, ...per-ticker data...}
```

The `sweep_ticker()` function adds breadth_threshold to its loop:
```python
for dip_thresh, target_pct, stop_pct, breadth_thresh in itertools.product(
        SWEEP_DIP_THRESHOLDS, SWEEP_TARGETS, SWEEP_STOPS, SWEEP_BREADTH):
    day_signals = signals.get(dip_thresh, {})
    for day_str, tk_data in day_signals.items():
        if tk_data.get("_breadth", 0) < breadth_thresh:
            continue  # breadth didn't fire at this threshold
        ...
```

### 8.7 What the sweep might discover (HYPOTHETICAL)

**NOTE:** The examples below are HYPOTHETICAL — illustrating what per-ticker breadth optimization could reveal. Actual values will come from the sweep.

At 5,000 tickers, the sweep might find patterns like:

| Ticker | Optimal Breadth | Hypothesis |
| :--- | :--- | :--- |
| MARA | ~10% | Crypto dips independently, may not need market-wide weakness |
| LUNR | ~35% | Space sector may move with broader sentiment |
| CLF | ~45% | Steel may follow macro cycles closely |
| NVDA | ~20% | Large-cap, may dip on sector rotation, not market-wide events |

If true, these would have been invisible at a fixed 50% threshold — tickers that are profitable at lower breadth never trade because the gate is too restrictive.

---

## 9. Integration with Existing Workflows

The neural candidate discoverer does NOT replace `sim_ranked_screener.py` — it complements it. A ticker can be a good candidate for both strategies:

1. **Neural discoverer** finds: "MARA is great for same-day dip buys (dip≥1.5%, target=4%, win rate 70%)"
2. **sim_ranked_screener** finds: "MARA has reliable support levels for multi-day swing trades"
3. **Both are valid** — the system can use MARA for dip buys AND support-based buys

The output `data/neural_candidates.json` would be consumed by:
- `batch_onboard.py` — to onboard discovered tickers
- `watchlist_manager.py` — to add to CANDIDATE tier
- The daily neural dip evaluator — to use the discovered ticker's profile for live trading

---

## 10. Implementation Steps

1. **Modify `tools/parameter_sweeper.py`** (~60 lines)
   - Add `SWEEP_BREADTH = [0.10, 0.20, 0.30, 0.40, 0.50]` to sweep grid
   - Change `precompute_signals()` to NOT filter by breadth — record `_breadth` ratio per day, let sweep decide
   - Change `sweep_ticker()` to add breadth_threshold to the iteration loop + filter days by breadth inside sweep
   - Add `breadth_threshold` to output params
   - Total combos: 120 → 600 (still pure arithmetic, negligible runtime impact)

2. **Modify `tools/neural_dip_evaluator.py`** (~25 lines)
   - Convert `breadth_dip` from binary node to level-firing observer (`breadth_dip_level`) + subscription gate (`breadth_dip_gate`) in `build_first_hour_graph()`
   - Convert `breadth_bounce` from binary node to level-firing observer (`breadth_bounce_level`) + subscription gate (`breadth_bounce_gate`) in `build_decision_graph()`
   - Load `breadth_threshold` from profile (with DIP_CONFIG 0.50 fallback)
   - Same pattern as dip_level → dip_gate conversion from Phase 1

3. **New file: `tools/neural_candidate_discoverer.py`** (~250 lines)
   - Bulk data download for universe passers + cache
   - Two-pass: compute raw dip_pct + breadth_ratio (arithmetic), then graph build only on relevant days
   - Import and call `precompute_signals()`, `sweep_ticker()`, `evaluate_params()`, `_extract_features()` from parameter_sweeper
   - Cross-validation ranking by validation P/L
   - Gating: min trades, positive val P/L, no overfitting, confidence ≥ 40
   - Cluster top candidates via `ticker_clusterer.py`
   - Output top 30 to `data/neural_candidates.json` + `.md`

4. **No changes to:**
   - `graph_engine.py`
   - `ticker_clusterer.py`
   - `weight_learner.py`

---

## 11. Open Questions

1. ~~**Breadth threshold at 1,500 tickers**~~ **RESOLVED:** Breadth threshold becomes a swept parameter (Section 8). The network discovers the optimal breadth level per ticker from simulation data. No guessing needed.

2. **yfinance rate limits** — Downloading 60-day 5-min data for 1,500+ tickers. yfinance may throttle or fail. May need chunking (batches of 200-300 tickers with delays between).

3. **Memory** — 1,500 tickers × 60 days × 78 bars × 6 columns ≈ 321MB. Should fit on 16GB but must verify. At 5,000 tickers: ~1GB.

4. **Signal pre-computation time** — With breadth no longer filtering days, MORE signal data is retained per dip_threshold. The two-pass approach (arithmetic dip_pct first, graph build only where needed) mitigates this. UNMEASURED at scale.

5. **Should this run weekly alongside the re-optimization?** The discoverer finds NEW candidates; the re-optimizer maintains EXISTING profiles. They could share the data download but run separately.
