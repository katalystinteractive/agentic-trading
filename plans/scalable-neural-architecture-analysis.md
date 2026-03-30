# Analysis: Scalable Neural Architecture for 300-400 Tickers

**Date**: 2026-03-29 (Sunday, 2:22 PM local / 7:22 AM ET)
**Purpose**: Design a neural architecture that works at 21 tickers today and scales to 300-400 without architectural changes. Identify what must be learned vs hand-coded.

**Honesty note**: This document separates FACT (verified against code), ESTIMATE (plausible but unmeasured), and PROPOSED (does not exist yet). Every claim is labeled.

---

## 1. Why the Current Approach Breaks at Scale

### 1.1 Manual classification is impossible
**FACT:** Test 3 in `plans/dip-parameter-tuning-analysis.md` identified distinct behavioral patterns for 5 tickers (e.g., OKLO = "big swinger", AR = "profits from EOD cuts"). We derived 3 category labels from those findings: `big_swinger`, `eod_drifter`, `moderate_recoverer`. These labels were coined in this document — they do not appear in the tuning analysis itself. The other 16 tickers have no profile — they use global `DIP_CONFIG` defaults.

At 400 tickers, nobody is reading 400 backtester outputs and manually assigning categories. The system must discover behavioral clusters automatically.

### 1.2 Parameter optimization does not scale manually
**FACT:** The current backtester (`tools/neural_dip_backtester.py`) runs ONE fixed parameter config per invocation using `DIP_CONFIG`. It has no parameter grid sweep, no `--target` flag, no loop over parameter combinations. Test 3's per-ticker results were produced by manually editing `DIP_CONFIG` and re-running — not by automated sweeps.

**What's missing for scale:** A parameter sweep mode that iterates target/stop/dip_threshold combinations per ticker. This does not exist today and must be built.

### 1.3 Manual profile review doesn't scale
**FACT:** At 21 tickers, a human can sanity-check each profile. At 400, you need automated confidence scoring — profiles with <20 trades, poor out-of-sample performance, or unstable parameters across time windows should be flagged or rejected automatically.

### 1.4 Static profiles go stale
**FACT:** A profile optimized on Q4 2025 data may be wrong by Q2 2026. At 21 tickers, a monthly manual re-run is manageable. At 400, re-optimization must be automated.

---

## 2. What Exists Today (verified against code)

### 2.1 Graph engine (`tools/graph_engine.py`)
**FACT:** The engine is type-agnostic. `Signal.old_value` and `Signal.new_value` are typed `Any`. `Node.compute` returns `Any`. The engine already supports continuous values — it does not force boolean. No engine changes needed for level-firing.

### 2.2 Neural dip evaluator (`tools/neural_dip_evaluator.py`)
**FACT:** Current per-ticker neurons are binary:
- `{tk}:dipped` — True/False (dip_pct >= 1.0%, pre-computed outside graph)
- `{tk}:bounced` — True/False (bounce_pct >= 0.3%, pre-computed outside graph)
- `{tk}:not_catastrophic` — True/False
- `{tk}:not_exit` — True/False
- `{tk}:earnings_clear` — True/False
- `{tk}:historical_range` — True/False (range >= 3.0% AND recovery >= 60%)
- `{tk}:dip_viable` — True/False
- `{tk}:candidate` — True/False (AND-gate of above)
- `{tk}:buy_dip` — True/False (candidate AND signal AND PDT AND capital)

**FACT:** The raw dip percentage IS calculated (line 276: `dip_pct = round((o - c) / o * 100, 1)`) but only the boolean enters the graph. The value bypasses the graph via `fh_state` dict.

**FACT:** `DIP_CONFIG` has 10 global parameters. All tickers share the same thresholds:
```
dip_threshold_pct: 1.0, bounce_threshold_pct: 0.3, breadth_threshold: 0.50,
range_threshold_pct: 3.0, recovery_threshold_pct: 60.0, budget_normal: 100,
budget_risk_off: 50, max_tickers: 5, pdt_limit: 3, capital_min: 100
```

### 2.3 Per-ticker data from Test 3
**FACT:** `plans/dip-parameter-tuning-analysis.md` Test 3 has optimized parameters for exactly 5 tickers:

| Ticker | Dip Threshold | Target | Stop | Behavior (label coined here) |
| :--- | :--- | :--- | :--- | :--- |
| OKLO | 1.0% | 5.0% | -3.0% | big_swinger |
| AR | 2.0% | 2.0% | -4.0% | eod_drifter |
| IONQ | 2.0% | 4.0% | -3.0% | moderate_recoverer |
| CLSK | 2.0% | 3.5% | -3.0% | moderate_recoverer |
| NNE | 1.5% | 3.5% | -4.0% | moderate_recoverer |

The `bounce_threshold` (0.3%) is the global `DIP_CONFIG` default — it was never varied or optimized per-ticker. The `behavior` labels were derived from Test 3's prose descriptions and coined in this document — they are NOT outputs of the simulation.

### 2.4 Node counts (verified)
**FACT:** In `build_first_hour_graph()`: 6 per-ticker nodes × 21 tickers + 2 shared (regime, breadth_dip) = **128 nodes**.
**FACT:** In `build_decision_graph()`: 8 per-ticker nodes × 21 tickers + 5 shared + up to 5 buy_dip = **~178 nodes**.

### 2.5 Backtester capabilities
**FACT:** `neural_dip_backtester.py` supports:
- `--days N` (max 60, yfinance 5-min constraint)
- `--cached` (reuse cached data)
- `--json` (output results file)

**FACT:** It does NOT support:
- Parameter grid sweep (no `--target`, `--stop`, `--dip-threshold` flags)
- Parallel execution (no threading, no multiprocessing)
- Per-ticker parameter variation (runs one global DIP_CONFIG)

### 2.6 ML infrastructure
**FACT:** The project has no clustering or ML training libraries. No scikit-learn, no scipy. `numpy` is present (used by the backtester for array math and Sharpe ratio), but not for ML. `chromadb` and `sentence-transformers` exist for the knowledge store. Any clustering or weight learning requires adding new dependencies (e.g., scikit-learn).

### 2.7 Trade frequency
**FACT:** The `max_tickers` cap in DIP_CONFIG is 5 — at most 5 buys per day regardless of universe size. Current observed frequency: 1-3 trades/day at 21 tickers on signal days (not every day has a signal).

---

## 3. What a True Learning System Needs

### 3.1 Three things the system must learn on its own

1. **Behavioral clustering** — Group tickers by how they dip and recover. Not 3 categories manually assigned, but N clusters discovered from data (dip depth distribution, recovery speed, volume profile). A ticker's cluster determines its default subscription thresholds.

2. **Per-ticker threshold optimization** — Within each cluster, fine-tune thresholds to each ticker's actual behavior. Today this requires manually editing DIP_CONFIG and re-running the backtester. At scale, this must be automated.

3. **Synapse weight learning** — Not all inputs matter equally. For OKLO, the dip magnitude matters most. For AR, the EOD drift pattern matters most. Synapse weights encode this: `weighted_input = weight × raw_value`. Currently all weights are implicitly 1.0 (raw passthrough). Learning adjusts them based on P/L outcomes.

### 3.2 Three things that should remain hand-coded

1. **Graph topology** — Which neurons connect to which. The structure (observer → gate → candidate → buy) represents domain knowledge about how dip-buying works. This shouldn't be learned — it should be designed.

2. **Safety constraints** — PDT limits, capital minimums, catastrophic stop thresholds. These are risk management rules, not patterns to discover.

3. **Market regime classification** — VIX-based regime (Risk-On/Neutral/Risk-Off) is a macro judgment. The thresholds can be tuned but the concept is domain knowledge.

---

## 4. Proposed Architecture: Graph Structure + Learned Parameters

**STATUS: PROPOSED — none of this exists in code today.**

The key insight: keep the graph engine for structure and explainability, but make the parameters learnable.

### 4.1 Layer Design

```
LAYER 1: OBSERVER NEURONS (fire with raw values instead of booleans)
  Shared: VIX_LEVEL, BREADTH_DIP_LEVEL, BREADTH_BOUNCE_LEVEL
  Per-ticker: {tk}:DIP_LEVEL, {tk}:BOUNCE_LEVEL
  Per-ticker: {tk}:RANGE_LEVEL
  NOTE: Each per-ticker observer is inherently separate (each stock has
        its own price). "One observer, many subscribers" only applies
        to shared signals like VIX and breadth.

LAYER 2: WEIGHTED SYNAPSES (PROPOSED — learned weights per connection)
  Each observer→gate connection has a weight W in [0.0, 1.0]
  Gate input = W × observer_value
  Initial weights = 1.0 (equivalent to current raw passthrough)
  Learning adjusts weights based on trade P/L outcomes

LAYER 3: SUBSCRIPTION GATES (per-ticker thresholds, auto-tuned)
  {tk}:DIP_GATE — threshold from cluster default OR per-ticker optimization
  {tk}:BOUNCE_GATE — same
  Static gates unchanged: NOT_CATASTROPHIC, EARNINGS_CLEAR, NOT_EXIT

LAYER 4: AGGREGATOR (AND-gate, per-ticker)
  {tk}:CANDIDATE — weighted combination of gate outputs
  At 21 tickers: simple AND (all gates must pass) — same as today
  At 400 tickers: soft AND with learned aggregator threshold

LAYER 5: PORTFOLIO OPTIMIZATION (PROPOSED — needed at scale)
  SECTOR_BALANCE — don't buy 10 crypto miners on the same dip day
  CORRELATION_GATE — don't buy tickers that move together
  CAPITAL_ALLOCATOR — distribute budget across candidates by confidence
  (At 21 tickers this layer is trivial. At 400 it's essential.)

LAYER 6: TERMINAL
  {tk}:BUY_DIP — entry, target, stop, confidence score, cluster label
```

### 4.2 What's new vs current

| Component | Current (FACT) | Scaled (PROPOSED) |
| :--- | :--- | :--- |
| Behavioral classification | Manual: 3 types for 5 tickers, 16 unclassified | Auto-clustering: N types discovered from data |
| Subscription thresholds | Global DIP_CONFIG for all tickers | Per-ticker from cluster default + optimization |
| Synapse weights | Implicit 1.0 (all inputs equal) | Learned from P/L outcomes |
| Aggregator logic | Hard AND (all gates must pass) | Soft AND with learned threshold |
| Portfolio layer | Basic PDT + capital check (max_tickers=5) | Sector balance + correlation + allocation |
| Profile confidence | None | Auto-scored: trade count, stability, out-of-sample |
| Re-optimization | Manual (edit DIP_CONFIG, re-run) | Automated background job |

---

## 5. Behavioral Auto-Clustering

**STATUS: PROPOSED — requires adding scikit-learn or similar dependency.**

### 5.1 What we cluster on

For each ticker, compute a feature vector from historical data (the backtester already produces some of these metrics):

```python
features = {
    "median_daily_range_pct": 7.7,      # PROPOSED format; compute_ranges_for_day() computes range data but not in this schema
    "dip_frequency": 0.45,               # PROPOSED: fraction of days with dip > threshold
    "median_dip_depth_pct": 2.3,         # PROPOSED: typical dip magnitude
    "bounce_rate": 0.68,                 # PROPOSED: fraction of dips that bounce
    "eod_recovery_rate": 0.55,           # PROPOSED: fraction that recover by EOD
    "target_hit_rate_3pct": 0.30,        # PROPOSED: from backtester P/L breakdown
    "target_hit_rate_5pct": 0.15,        # PROPOSED: from backtester P/L breakdown
    "mean_eod_return_on_dip": 0.8,       # PROPOSED: avg EOD return when dipped
}
```

### 5.2 Clustering method

Standard approach: K-means or DBSCAN on standardized feature vectors. Start with K=5 clusters, evaluate silhouette score to find optimal K. At 400 tickers, expect 5-10 natural clusters.

The current 3 manual categories might emerge as clusters, or the data might reveal different groupings:
- **Flash recoverers** — deep dip, fast bounce, high target hit rate
- **Slow grinders** — shallow dip, slow recovery, EOD profit
- **Momentum followers** — dip correlates with sector/market, recovery tracks index
- **Noise traders** — random dip patterns, no predictable behavior (skip these)
- **Event-driven** — dips only on news/earnings, not tradeable with this strategy

**NOTE:** These labels are hypothetical. The actual clusters will be determined by data.

### 5.3 Cluster to default profile

Each cluster gets a centroid profile:

```python
# PROPOSED — values would come from clustering, not hard-coded
CLUSTER_PROFILES = {
    0: {"dip_threshold": 1.2, "bounce_threshold": 0.4, "target": 4.5,
        "stop": -3.0, "label": "flash_recoverer"},
    1: {"dip_threshold": 2.1, "bounce_threshold": 0.2, "target": 2.0,
        "stop": -4.0, "label": "slow_grinder"},
    # ... discovered from data, not hand-coded
}
```

New tickers with no trade history get the closest cluster's profile. As trades accumulate, per-ticker optimization refines the thresholds away from the cluster default.

---

## 6. Synapse Weight Learning

**STATUS: PROPOSED — no learning infrastructure exists in the codebase today.**

### 6.1 What weights do

In the current system, all inputs to the CANDIDATE AND-gate are equally weighted — either pass or fail. A binary `{tk}:dipped` has no way to express "dip matters more than bounce for this ticker."

With synapse weights:

```
CANDIDATE score = W_dip × dip_gate_output
               + W_bounce × bounce_gate_output
               + W_range × range_gate_output
```

If `score >= aggregator_threshold` then CANDIDATE fires.

This lets the system learn that for flash recoverers, bounce matters more (W_bounce = 0.9) while for slow grinders, dip depth matters more (W_dip = 0.9).

### 6.2 How weights are learned

After each trade closes (target hit, stop hit, or EOD cut):

```python
# Reward-modulated Hebbian update (NOT the delta rule — the delta rule
# requires an error term (target - output), which we don't have.
# This is simpler: reinforce inputs that co-occurred with profit.)
outcome = +1 if pnl > 0 else -1
for synapse in fired_synapses:
    synapse.weight += learning_rate * outcome * synapse.input_value
    synapse.weight = clamp(synapse.weight, 0.0, 1.0)
```

**Limitation:** Clamping to [0.0, 1.0] means the system cannot learn negative correlations (a feature that inversely predicts success). If this is needed, the range must be expanded to [-1.0, 1.0].

**Open question:** The right learning rule for this problem may be something other than Hebbian. Options include:
- Reward-modulated Hebbian (shown above) — simplest
- Online logistic regression — more principled, handles correlations
- Bayesian updating — maintains uncertainty estimates

The choice depends on how noisy trade outcomes are and how much correlation exists between inputs. This needs experimentation, not a premature commitment to one algorithm.

### 6.3 Learning rate and stability

- **Learning rate**: Needs calibration through experimentation. Starting point: 0.01.
- **Weight decay**: Slowly pull weights toward 1.0 (uniform) to prevent overfitting. Inactive synapses revert to default.
- **Minimum trades**: Don't update weights until 20+ trades recorded for that ticker. Before that, use cluster default weights.
- **Regime-aware learning**: Separate weight sets for Risk-On / Neutral / Risk-Off regimes. A synapse weight learned in Risk-On may not apply in Risk-Off.

**Convergence timeline**: Unknown. Depends on trade frequency, noise level, and feature quality. At 21 tickers with 1-3 trades/day, individual ticker weights may never converge (too few samples). At 400 tickers, convergence is faster because cluster-level learning aggregates across many tickers. But no simulation has been run to estimate a timeline — any specific number would be a guess.

### 6.4 What this is NOT

This is NOT a deep learning model. No hidden layers, no backpropagation, no GPU required. It's closer to a single-layer adaptive filter with domain-structured inputs. The graph provides the structure (domain knowledge), the weights provide the adaptation (learning).

Deep learning on 400 tickers × 60 days of data would likely overfit. The constrained structure (fixed topology, clamped weights, weight decay) is intentional.

---

## 7. Confidence Scoring and Profile Management

**STATUS: PROPOSED**

### 7.1 Per-ticker confidence score

```python
confidence = {
    "trade_count": 47,           # more trades = higher confidence
    "out_of_sample_pnl": 12.0,   # tested on held-out data
    "parameter_stability": 0.85,  # how much params change across time windows
    "cluster_distance": 0.3,      # how close to cluster centroid
}

# Composite score (proposed weighting — needs validation)
score = (
    min(trade_count / 50, 1.0) * 30 +      # 30 pts for sample size
    (1 if oos_pnl > 0 else 0) * 30 +        # 30 pts for out-of-sample profit
    parameter_stability * 20 +               # 20 pts for stable params
    (1 - cluster_distance) * 20              # 20 pts for fitting a cluster well
)
```

Tickers with confidence < 40 use cluster defaults only (no per-ticker overrides).
Tickers with confidence < 20 are excluded from dip-buying entirely.

### 7.2 Automated re-optimization pipeline

**PROPOSED — nothing below exists today. Every step must be built.**

```
Weekly (Saturday):
  1. Download latest 60-day 5-min data for all tickers
  2. Run backtester with parameter sweep per ticker
     (REQUIRES: parameter sweep mode — not yet built)
     (REQUIRES: parallelization — not yet built)
  3. Re-cluster on updated feature vectors
     (REQUIRES: clustering code — not yet built)
  4. Update ticker_profiles.json with new optimal params
  5. Compute confidence scores
  6. Flag tickers with confidence drops or cluster changes
  7. Email summary

Monthly:
  1. Run cross-validation (train on weeks 1-3, test on week 4)
  2. Compare live P/L vs backtested P/L
  3. Flag divergence
```

**Runtime estimate:** Unknown. The backtester has no timing instrumentation and no parallelization. Before estimating runtime at 400 tickers, we need to: (1) add a parameter sweep mode, (2) add parallelization, (3) benchmark on 21 tickers, (4) extrapolate.

---

## 8. Implementation Phases

### Phase 1: Level-firing foundation (works at 21 tickers)
**STATUS: Designed in `plans/neural-level-firing-analysis.md`, NOT yet implemented.**
- Change observer neurons from boolean to value-returning (return dip_pct instead of True/False)
- Add subscription gate neurons with per-ticker thresholds
- Load profiles from `data/ticker_profiles.json` (file does not exist yet)
- Fall back to DIP_CONFIG for tickers without profiles
- **Estimated change: ~70 lines in neural_dip_evaluator.py (verified in level-firing analysis)**
- **graph_engine.py: NO CHANGES**

### Phase 2: Automated parameter sweep + clustering (needed at 50+ tickers)
**STATUS: Nothing built. Requires new code + new dependency (scikit-learn).**
- Add `--sweep` mode to backtester (iterate parameter combos per ticker)
- Add parallelization to backtester (ThreadPoolExecutor/multiprocessing)
- Feature vector computation from backtester output
- Clustering code (new file, e.g., `tools/ticker_clusterer.py`)
- Cluster centroid to default profile mapping
- Confidence scoring per ticker
- **graph_engine.py: NO CHANGES**

### Phase 3: Synapse weights (needed at 100+ tickers)
**STATUS: Nothing built. Requires graph_engine.py change.**
- Add optional `weight` parameter to graph edges (ESTIMATE: ~30 lines in graph_engine.py)
- When a node receives inputs, multiply each by its edge weight
- Initial weights = 1.0 (backward compatible with Phases 1-2)
- Post-trade weight update (learning rule TBD — needs experimentation)
- Weight persistence in `data/synapse_weights.json`
- Regime-aware weight sets (3 regimes × N synapses)
- **This is the ONLY graph_engine.py change across all phases**

### Phase 4: Portfolio optimization layer (needed at 200+ tickers)
**STATUS: Nothing built.**
- Sector balance gate (max N tickers per sector per day)
- Correlation gate (don't buy correlated tickers simultaneously)
- Capital allocator (distribute budget by confidence × expected P/L)
- `max_tickers` cap raised or removed (currently hard-coded at 5)
- **graph_engine.py: NO CHANGES**

### Phase 5: Continuous learning pipeline (needed at 300+ tickers)
**STATUS: Nothing built.**
- Automated weekly re-optimization (cron job)
- Cross-validation with train/test split
- Live vs backtest P/L divergence monitoring
- Dynamic cluster count (re-evaluate K periodically)
- Weight decay and synapse pruning
- Alerting on confidence drops and cluster shifts
- **graph_engine.py: NO CHANGES**

---

## 9. What Changes in graph_engine.py

| Phase | Change | Lines |
| :--- | :--- | :--- |
| Phase 1 | NOTHING | 0 |
| Phase 2 | NOTHING | 0 |
| Phase 3 | Add optional edge weight parameter | ~30 (ESTIMATE) |
| Phase 4 | NOTHING | 0 |
| Phase 5 | NOTHING | 0 |

**Total across all phases:** ~30 lines in graph_engine.py (ESTIMATE). Everything else is application-level code.

---

## 10. Scale Estimates

**IMPORTANT: All numbers below are ESTIMATES unless marked FACT. None have been benchmarked.**

### 10.1 Node counts

**FACT:** Current evaluator creates 6 per-ticker nodes in first_hour_graph and 8 in decision_graph.

| Scale | Per-ticker nodes | Shared nodes | buy_dip nodes (capped) | Total (decision graph) |
| :--- | :--- | :--- | :--- | :--- |
| 21 tickers (FACT) | 8 × 21 = 168 | 5 | up to 5 | ~178 |
| 100 tickers (ESTIMATE) | 8 × 100 = 800 | 5 | up to 5 | ~810 |
| 400 tickers (ESTIMATE) | 8 × 400 = 3,200 | 5 | up to 5 | ~3,210 |

NOTE: buy_dip nodes are capped at `max_tickers` (currently 5) regardless of universe size.

### 10.2 Graph resolve time

**UNMEASURED.** The graph engine has no timing instrumentation. Each node's compute function is a trivial lambda (lookup or comparison). Topological sort is O(V+E). For ~3,200 nodes with simple compute functions, sub-second resolve is plausible but unverified. **Must benchmark before relying on this.**

### 10.3 Trade frequency at scale

**FACT:** Current `max_tickers` cap is 5 buys/day. This limits trade frequency regardless of universe size. At 400 tickers, this cap must be addressed:
- Keep cap at 5 → ~100 trades/month (same as today)
- Raise cap to 20 → potentially ~400 trades/month (ESTIMATE)
- Remove cap → depends on signal frequency and capital

The right cap depends on available capital and risk tolerance. This is a strategy decision, not an architecture decision.

### 10.4 Backtester runtime

**UNMEASURED.** No timing data exists. Before estimating runtime at 400 tickers:
1. Add timing instrumentation to current backtester
2. Benchmark at 21 tickers with one config
3. Add parameter sweep mode
4. Benchmark sweep at 21 tickers
5. Extrapolate to 400

---

## 11. What This Is and What This Isn't

### What it is
A **structured learning system** — domain knowledge provides the graph topology (which signals matter, how they combine), while automated optimization and adaptive weight updates learn the parameters (thresholds, weights). This is similar to a feature-engineered linear model where the features are hand-designed but the coefficients are learned.

### What it isn't
- Not a deep neural network (no hidden layers, no backprop through layers)
- Not a black box (every decision traces through named neurons with visible weights)
- Not a reinforcement learning agent (no exploration/exploitation, no policy gradient)
- Not a transformer/attention model (no sequence modeling)

### Why this is the right choice for this problem
1. **Explainability** — Every trade decision has a traceable path: "DIP_LEVEL=2.3% × weight=0.85 → DIP_GATE(≥1.8%) ACTIVATED → CANDIDATE score 0.73 ≥ threshold 0.6 → BUY". You can't get this from a black-box model, and for real money trading, you need it.

2. **Data efficiency** — Deep learning needs massive datasets. Even at 400 tickers, we're looking at hundreds of trades per month (not millions). A constrained model with few parameters per ticker learns from this volume; a deep model would overfit.

3. **Stability** — Financial models that learn too aggressively blow up. The constrained structure (fixed graph topology + clamped weights + weight decay) limits how far the system can drift from the designed behavior.

4. **Incrementality** — Each phase adds capability without rewriting. Phase 1 works at 21 tickers with ~70 lines of changes. Phase 5 handles 400 tickers. Same engine, same concepts.

---

## 12. Remaining Open Questions

1. **Clustering algorithm choice** — K-means assumes spherical clusters. DBSCAN finds arbitrary shapes but needs epsilon tuning. At 400 tickers, which produces more actionable groupings? Needs experimentation on real data.

2. **Learning rule selection** — Reward-modulated Hebbian is simplest but may not be optimal. Online logistic regression handles correlated inputs better. The right choice depends on the actual noise characteristics of trade outcomes. Needs experimentation.

3. **Regime-aware vs universal weights** — Should each regime (Risk-On/Neutral/Risk-Off) have completely separate weight sets? Or one set with regime as an additional input? Separate sets need 3x the data to converge.

4. **Cross-ticker learning** — If MARA and RIOT (both crypto miners) show similar patterns, should learning on MARA's trades also update RIOT's weights? Transfer learning within clusters could speed convergence for new tickers.

5. ~~**When to start Phase 3**~~ **ANSWERED:** The backtester generates training volume — we don't need to wait for live trades. A same-day buy/sell candidates workflow running through historical data produces hundreds/thousands of simulated trades on day one. The backtester IS the training set for weight learning. Phase 3 can start as soon as the backtester has parameter sweep mode (Phase 2). Live trades then serve as ongoing validation and fine-tuning, not as the primary training source.

6. **max_tickers cap** — Currently 5. At 400 tickers, this artificially limits trade volume and learning data. What's the right cap? Depends on capital, risk tolerance, and how many simultaneous positions can be managed.

7. **Backtester parallelization approach** — Python's GIL limits threading for CPU-bound work. Options: multiprocessing (process pool), subprocess per ticker, or external job scheduler. The right choice depends on the actual bottleneck (CPU vs I/O from yfinance downloads).
