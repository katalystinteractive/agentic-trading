# Implementation Plan: Scalable Neural Architecture

**Date**: 2026-03-29
**Source analysis**: `plans/scalable-neural-architecture-analysis.md` (verified, 0 hallucinations)
**Supporting analysis**: `plans/neural-level-firing-analysis.md` (verified)
**Approach**: 5 phases, each independently deployable and testable. Phase 1 starts immediately.

---

## Scope

This plan covers all 5 phases from the analysis. Each phase is a separate implementation cycle (analysis is done — this is the plan for all of them). Phases are ordered by dependency: each phase builds on the prior one.

| Phase | What | Prerequisite | New files | Modified files |
| :--- | :--- | :--- | :--- | :--- |
| 1 | Level-firing + subscription gates + profiles | None | `data/ticker_profiles.json` | `neural_dip_evaluator.py` |
| 2 | Parameter sweep + clustering | Phase 1 | `tools/parameter_sweeper.py`, `tools/ticker_clusterer.py` | `neural_dip_backtester.py` |
| 3 | Synapse weights | Phase 2 | `tools/weight_learner.py`, `data/synapse_weights.json` | `graph_engine.py`, `neural_dip_evaluator.py` |
| 4 | Portfolio optimization layer | Phase 1 | None | `neural_dip_evaluator.py` |
| 5 | Continuous learning pipeline | Phases 2+3 | `tools/weekly_reoptimize.py` | cron entries |

---

## Phase 1: Level-Firing + Subscription Gates + Profiles

**Goal**: Replace binary neurons with value-firing observers + per-ticker subscription gates. Load per-ticker thresholds from JSON profiles.

### 1.1 Create `data/ticker_profiles.json`

Seed file with the 5 tickers from Test 3. All other tickers use DIP_CONFIG defaults.

```json
{
  "_meta": {
    "version": 1,
    "source": "plans/dip-parameter-tuning-analysis.md Test 3",
    "updated": "2026-03-29",
    "note": "bounce_threshold is global default (not optimized). behavior labels coined in scalable-neural-architecture-analysis.md"
  },
  "OKLO": {"dip_threshold": 1.0, "bounce_threshold": 0.3, "target_pct": 5.0, "stop_pct": -3.0},
  "AR":   {"dip_threshold": 2.0, "bounce_threshold": 0.3, "target_pct": 2.0, "stop_pct": -4.0},
  "IONQ": {"dip_threshold": 2.0, "bounce_threshold": 0.3, "target_pct": 4.0, "stop_pct": -3.0},
  "CLSK": {"dip_threshold": 2.0, "bounce_threshold": 0.3, "target_pct": 3.5, "stop_pct": -3.0},
  "NNE":  {"dip_threshold": 1.5, "bounce_threshold": 0.3, "target_pct": 3.5, "stop_pct": -4.0}
}
```

**Schema**: Each ticker key maps to a dict with `dip_threshold`, `bounce_threshold`, `target_pct`, `stop_pct`. All values are percentages. Missing tickers fall back to DIP_CONFIG globals.

### 1.2 Add profile loading to `neural_dip_evaluator.py`

**Where**: After the existing `DIP_CONFIG` dict (line 48), add:

```python
PROFILES_PATH = _ROOT / "data" / "ticker_profiles.json"

def _load_profiles():
    """Load per-ticker profiles. Returns dict. Missing file = empty dict."""
    if PROFILES_PATH.exists():
        with open(PROFILES_PATH) as f:
            data = json.load(f)
        # Strip _meta key
        return {k: v for k, v in data.items() if not k.startswith("_")}
    return {}

def _get_profile(tk, profiles):
    """Get profile for ticker, falling back to DIP_CONFIG globals."""
    if tk in profiles:
        return profiles[tk]
    return {
        "dip_threshold": DIP_CONFIG["dip_threshold_pct"],
        "bounce_threshold": DIP_CONFIG["bounce_threshold_pct"],
        "target_pct": 4.0,  # current hardcoded default (line 393)
        "stop_pct": -3.0,   # current hardcoded default (line 394)
    }
```

**Lines added**: ~20

### 1.3 Change `build_first_hour_graph()` — observer neurons fire values

**Current** (lines 276-278, 290-292):
```python
dip_pct = round((o - c) / o * 100, 1) if o and c and o > 0 else 0
dipped = dip_pct >= cfg["dip_threshold_pct"]
...
graph.add_node(f"{tk}:dipped", compute=lambda _, d=dipped: d, ...)
```

**Changed to**:
```python
dip_pct = round((o - c) / o * 100, 1) if o and c and o > 0 else 0
profile = _get_profile(tk, profiles)
dipped = dip_pct >= profile["dip_threshold"]
...
# Observer: fires with raw value
graph.add_node(f"{tk}:dip_level", compute=lambda _, pct=dip_pct: pct,
    reason_fn=lambda old, new, _: f"DIP_LEVEL={new:.1f}%")

# Subscription gate: compares value to per-ticker threshold
graph.add_node(f"{tk}:dip_gate",
    compute=lambda inputs, thresh=profile["dip_threshold"], t=tk:
        inputs[f"{t}:dip_level"] >= thresh,
    depends_on=[f"{tk}:dip_level"],
    reason_fn=lambda old, new, _, thresh=profile["dip_threshold"]:
        f"DIP_GATE(≥{thresh}%) {'ACTIVATED' if new else 'SILENT'}")
```

**What changes**:
- `{tk}:dipped` (boolean) replaced by `{tk}:dip_level` (float) + `{tk}:dip_gate` (boolean)
- The threshold comes from `profile["dip_threshold"]` instead of `cfg["dip_threshold_pct"]`
- `dip_count` logic: count tickers where `dip_gate` is True (use per-ticker threshold, not global)

**Breadth calculation change**: Currently `dip_count` uses the global 1.0% threshold. With per-ticker thresholds, dip_count should count tickers that pass their own threshold:

```python
dip_count = 0
for tk in tickers:
    ...
    profile = _get_profile(tk, profiles)
    dipped = dip_pct >= profile["dip_threshold"]
    if dipped:
        dip_count += 1
```

This is the same loop structure — the only change is `profile["dip_threshold"]` instead of `cfg["dip_threshold_pct"]`.

**Lines changed**: ~15 (replacing existing code, net addition ~8)

### 1.4 Change `build_decision_graph()` — bounce observer + per-ticker targets

**Same pattern** for bounce:

```python
# Observer: fires with raw value
graph.add_node(f"{tk}:bounce_level", compute=lambda _, pct=bounce_pct: pct,
    reason_fn=lambda old, new, _: f"BOUNCE_LEVEL={new:.1f}%")

# Subscription gate
graph.add_node(f"{tk}:bounce_gate",
    compute=lambda inputs, thresh=profile["bounce_threshold"], t=tk:
        inputs[f"{t}:bounce_level"] >= thresh,
    depends_on=[f"{tk}:bounce_level"],
    reason_fn=lambda old, new, _, thresh=profile["bounce_threshold"]:
        f"BOUNCE_GATE(≥{thresh}%) {'ACTIVATED' if new else 'SILENT'}")
```

**Candidate AND-gate change** — depends_on references the new gate names:

```python
# Current depends_on (line 382-384):
depends_on=[f"{tk}:dipped", f"{tk}:bounced", ...]

# Changed to:
depends_on=[f"{tk}:dip_gate", f"{tk}:bounce_gate", ...]
```

**Per-ticker target/stop** — currently hardcoded (lines 393-394):

```python
# Current:
"target": round(current * 1.04, 2),
"stop": round(current * 0.97, 2),

# Changed to:
"target": round(current * (1 + profile["target_pct"] / 100), 2),
"stop": round(current * (1 + profile["stop_pct"] / 100), 2),
```

**Lines changed**: ~25

### 1.5 Update `build_first_hour_graph()` signature

Add `profiles` parameter:

```python
# Current:
def build_first_hour_graph(tickers, prices, static, hist_ranges, regime):

# Changed to:
def build_first_hour_graph(tickers, prices, static, hist_ranges, regime, profiles=None):
    profiles = profiles or {}
```

Same for `build_decision_graph()`:

```python
def build_decision_graph(tickers, prices_11, fh_state, static, hist_ranges, regime, profiles=None):
    profiles = profiles or {}
```

**Backward compatibility**: `profiles=None` defaults to empty dict, which causes `_get_profile()` to return DIP_CONFIG defaults. Existing callers (backtester, live evaluator) work unchanged until updated.

### 1.6 Update callers to pass profiles

**`neural_dip_evaluator.py` main flow** (around line 500+):
```python
profiles = _load_profiles()
_, fh_state = build_first_hour_graph(tickers, fh_bars, static, hist_ranges, regime, profiles)
graph, top, budget = build_decision_graph(tickers, decision_bars, fh_state, static, hist_ranges, regime, profiles)
```

**`neural_dip_backtester.py` replay_day()** (line 147):
```python
def replay_day(day, day_bars, tickers, static, hist_ranges, regime, n_tickers, profiles=None):
    profiles = profiles or {}
    ...
    _, fh_state = build_first_hour_graph(tickers, fh_bars, static, hist_ranges, regime, profiles)
    ...
    decision_graph, top, budget = build_decision_graph(
        tickers, decision_bars, fh_state, static, hist_ranges, regime, profiles)
```

### 1.7 Update reason chains

The reason chain now shows values AND thresholds:

```
Before: "CLSK:dipped: Dipped 2.3%"
After:  "CLSK:dip_level: DIP_LEVEL=2.3%" → "CLSK:dip_gate: DIP_GATE(≥2.0%) ACTIVATED"
```

The `flat_reason()` composition from graph_engine.py handles this automatically — each signal carries its reason text, and child signals compose.

### 1.8 Node count change

Per ticker, replacing 1 binary node with 2 nodes (observer + gate) for dip and bounce:
- Old: `{tk}:dipped` (1 node) + `{tk}:bounced` (1 node) = 2 nodes
- New: `{tk}:dip_level` + `{tk}:dip_gate` + `{tk}:bounce_level` + `{tk}:bounce_gate` = 4 nodes
- Net: +2 nodes per ticker × 21 = +42 nodes in the decision graph

### 1.9 Verification

1. `python3 tools/neural_dip_evaluator.py --phase first_hour --dry-run` — verify reason chains show DIP_LEVEL and DIP_GATE
2. `python3 tools/neural_dip_backtester.py --days 30 --cached` — verify same results as before when profiles fall back to DIP_CONFIG defaults
3. Add Test 3 profiles, re-run backtester — verify OKLO uses 1.0% threshold while AR uses 2.0%
4. Verify a ticker NOT in profiles (e.g., LUNR) uses DIP_CONFIG default 1.0%

### 1.10 Files modified

| File | Action | Estimated lines |
| :--- | :--- | :--- |
| `data/ticker_profiles.json` | NEW | ~15 |
| `tools/neural_dip_evaluator.py` | MODIFY | ~70 changed/added |
| `tools/neural_dip_backtester.py` | MODIFY | ~10 (add profiles param to replay_day + callers) |

---

## Phase 2: Automated Parameter Sweep + Clustering

**Goal**: Automate what Test 3 did manually — sweep parameters per ticker, extract feature vectors, cluster tickers, produce profiles automatically.

### 2.1 Add `--sweep` mode to `neural_dip_backtester.py`

**New CLI flag**: `--sweep` enables parameter grid iteration.

```python
parser.add_argument("--sweep", action="store_true",
    help="Sweep target/stop/dip_threshold per ticker and find optimal params")
parser.add_argument("--sweep-output", type=str, default=None,
    help="Path for sweep results JSON (default: data/sweep_results.json)")
```

**Sweep grid** (configurable via constants):

```python
SWEEP_TARGETS = [2.0, 3.0, 3.5, 4.0, 5.0]       # 5 values
SWEEP_STOPS = [-2.0, -3.0, -4.0, -5.0]            # 4 values
SWEEP_DIP_THRESHOLDS = [0.5, 1.0, 1.5, 2.0, 2.5]  # 5 values
# Total: 5 × 4 × 5 = 100 combos per ticker
```

**How it works**: For each ticker, for each combo, override DIP_CONFIG with those values and replay. The existing `replay_day()` already uses `build_first_hour_graph()` / `build_decision_graph()` which (after Phase 1) accept profiles. The sweep creates a one-ticker profile for each combo.

**Output**: `data/sweep_results.json` with per-ticker best params:

```json
{
  "OKLO": {
    "best": {"dip_threshold": 1.0, "target_pct": 5.0, "stop_pct": -3.0},
    "best_pnl": 38.50,
    "total_trades": 27,
    "win_rate": 0.56,
    "all_combos": [...]
  },
  ...
}
```

### 2.2 Add parallelization to backtester

**Approach**: `multiprocessing.Pool` (not threading — the replay is CPU-bound math + pandas, GIL blocks threading).

```python
from multiprocessing import Pool

def _sweep_one_ticker(args):
    """Sweep all param combos for one ticker. Runs in child process."""
    tk, intraday, daily, trading_days, static = args
    results = []
    for target, stop, dip_thresh in itertools.product(SWEEP_TARGETS, SWEEP_STOPS, SWEEP_DIP_THRESHOLDS):
        profile = {tk: {"dip_threshold": dip_thresh, "bounce_threshold": 0.3,
                        "target_pct": target, "stop_pct": stop}}
        # replay all days with this profile
        ...
    return tk, results

def sweep_all(tickers, intraday, daily, trading_days):
    args_list = [(tk, intraday, daily, trading_days, static) for tk in tickers]
    with Pool(processes=min(8, len(tickers))) as pool:
        results = pool.map(_sweep_one_ticker, args_list)
    return dict(results)
```

**Constraint**: Each child process needs the full intraday DataFrame (large). This means memory scales with process count × data size. For 400 tickers, may need to chunk into batches of 50 tickers.

**NOTE**: `multiprocessing` requires the function to be picklable — lambda compute functions inside graph nodes may not serialize. The sweep function must import and call `build_first_hour_graph` / `build_decision_graph` directly, not pass graph objects across processes. This is the existing pattern — each process builds its own graph from scratch.

### 2.3 Feature vector extraction

**New function** in backtester or new file `tools/parameter_sweeper.py`:

```python
def extract_features(tk, results):
    """Compute feature vector for clustering from backtest results."""
    all_buys = results.get("all_combos", {}).get("best", {}).get("buys", [])
    # Use the best-param results for feature extraction
    return {
        "median_daily_range_pct": ...,    # from hist_ranges (already computed)
        "dip_frequency": ...,              # count(dip days) / total days
        "median_dip_depth_pct": ...,       # median of dip_pct on dip days
        "bounce_rate": ...,                # count(bounced) / count(dipped)
        "eod_recovery_rate": ...,          # count(EOD_CUT positive) / count(EOD_CUT)
        "target_hit_rate": ...,            # count(TARGET) / total trades
        "mean_eod_return_on_dip": ...,     # mean pnl_pct for EOD_CUT trades
    }
```

**Data source**: The backtester's `replay_day()` return value already contains exit_reason (TARGET, STOP, EOD_CUT) and pnl per trade. The feature vector is computed from aggregating these.

### 2.4 Clustering — new file `tools/ticker_clusterer.py`

**New dependency**: Add `scikit-learn` to requirements.

```python
"""Cluster tickers by dip behavior using sweep results."""
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score
import json, argparse
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

def cluster_tickers(sweep_results_path, output_path=None, max_k=10):
    """Load sweep results, extract features, cluster, write profiles."""
    with open(sweep_results_path) as f:
        sweep = json.load(f)

    tickers = [tk for tk in sweep if not tk.startswith("_")]
    features = [extract_features(tk, sweep[tk]) for tk in tickers]

    # Standardize
    scaler = StandardScaler()
    X = scaler.fit_transform(features)

    # Find optimal K
    best_k, best_score = 2, -1
    for k in range(2, min(max_k + 1, len(tickers))):
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = km.fit_predict(X)
        score = silhouette_score(X, labels)
        if score > best_score:
            best_k, best_score = k, score

    # Final clustering
    km = KMeans(n_clusters=best_k, random_state=42, n_init=10)
    labels = km.fit_predict(X)

    # Build cluster profiles from centroid tickers' best params
    cluster_profiles = {}
    for cluster_id in range(best_k):
        cluster_tickers_list = [tickers[i] for i, l in enumerate(labels) if l == cluster_id]
        # Average the best params within the cluster
        avg_params = _average_params(cluster_tickers_list, sweep)
        cluster_profiles[cluster_id] = avg_params

    # Build per-ticker profiles
    profiles = {"_meta": {"version": 2, "clusters": best_k, "silhouette": best_score}}
    for i, tk in enumerate(tickers):
        cluster_id = int(labels[i])
        best = sweep[tk]["best"]
        profiles[tk] = {
            "dip_threshold": best["dip_threshold"],
            "bounce_threshold": 0.3,  # not yet optimized
            "target_pct": best["target_pct"],
            "stop_pct": best["stop_pct"],
            "cluster": cluster_id,
        }

    # Write
    out = output_path or _ROOT / "data" / "ticker_profiles.json"
    with open(out, "w") as f:
        json.dump(profiles, f, indent=2)

    return profiles
```

### 2.5 Confidence scoring

**Added to `ticker_clusterer.py`** or as a separate function:

```python
def compute_confidence(tk, sweep_result, cluster_profiles, cluster_id):
    """Score how much we trust this ticker's profile."""
    trade_count = sweep_result.get("total_trades", 0)
    best_pnl = sweep_result.get("best_pnl", 0)

    # Parameter stability: run sweep on 2 half-windows, compare best params
    # (requires sweep to support --start/--end date ranges — Phase 2 extension)
    stability = 0.5  # placeholder until date-range sweep is built

    score = (
        min(trade_count / 50, 1.0) * 30 +
        (1.0 if best_pnl > 0 else 0) * 30 +
        stability * 20 +
        20  # cluster distance — requires feature distance calc
    )
    return round(score, 1)
```

**NOTE**: Full parameter stability requires running the sweep on split time windows (e.g., first 30 days vs last 30 days). This needs the backtester to support `--start` and `--end` date filtering, which it currently does not. Mark this as a Phase 2 extension.

### 2.6 Verification

1. `python3 tools/neural_dip_backtester.py --sweep --days 60` — produces `data/sweep_results.json`
2. `python3 tools/ticker_clusterer.py` — reads sweep results, produces updated `data/ticker_profiles.json`
3. Verify profiles contain per-ticker optimal params
4. Verify fallback: remove a ticker from profiles, confirm it uses DIP_CONFIG defaults
5. Benchmark: time the sweep at 21 tickers to establish baseline

### 2.7 Files

| File | Action | Estimated lines |
| :--- | :--- | :--- |
| `tools/parameter_sweeper.py` | NEW — sweep logic + feature extraction | ~200 |
| `tools/ticker_clusterer.py` | NEW — clustering + profile generation | ~150 |
| `tools/neural_dip_backtester.py` | MODIFY — add --sweep flag, parallelization | ~80 |
| `requirements.txt` | MODIFY — add scikit-learn | 1 |

---

## Phase 3: Synapse Weights

**Goal**: Add learnable weights to graph edges so the system can learn which inputs matter most per ticker.

### 3.1 Modify `graph_engine.py` — add edge weights

**This is the ONLY graph_engine.py change across all 5 phases.**

**Change `add_node()`** to accept optional edge weights:

```python
def add_node(
    self,
    name: str,
    compute: Callable[[dict[str, Any]], Any] | None = None,
    depends_on: list[str] | None = None,
    is_report: bool = False,
    reason_fn: Callable[[Any, Any, list[Signal]], str] | None = None,
    edge_weights: dict[str, float] | None = None,  # NEW
) -> Node:
```

**Change `Node.__init__()`**:

```python
self.edge_weights: dict[str, float] = edge_weights or {}
```

**Change `DependencyGraph.resolve()`** (line 225):

```python
# Current:
inputs = {dep: self.nodes[dep].value for dep in node.depends_on}

# Changed to:
inputs = {}
for dep in node.depends_on:
    val = self.nodes[dep].value
    weight = node.edge_weights.get(dep, 1.0)
    if isinstance(val, (int, float)) and weight != 1.0:
        inputs[dep] = val * weight
    else:
        inputs[dep] = val  # non-numeric values pass through unweighted
```

**Backward compatibility**: `edge_weights` defaults to empty dict. When empty, all weights are 1.0 (current behavior). Existing graphs work identically.

**ESTIMATE: ~25 lines changed in graph_engine.py** (add_node signature, Node.__init__, resolve loop, Node.__repr__ weight display).

### 3.2 Weight persistence — `data/synapse_weights.json`

```json
{
  "_meta": {"version": 1, "updated": "2026-04-15"},
  "weights": {
    "OKLO:dip_gate": {"OKLO:dip_level": 0.92, "OKLO:bounce_level": 0.78},
    "OKLO:candidate": {"OKLO:dip_gate": 0.85, "OKLO:bounce_gate": 0.95, ...},
    ...
  },
  "regime_weights": {
    "Risk-Off": { ... },
    "Neutral": { ... },
    "Risk-On": { ... }
  }
}
```

### 3.3 Weight loading in `neural_dip_evaluator.py`

```python
WEIGHTS_PATH = _ROOT / "data" / "synapse_weights.json"

def _load_weights(regime="Neutral"):
    """Load synapse weights for current regime."""
    if not WEIGHTS_PATH.exists():
        return {}
    with open(WEIGHTS_PATH) as f:
        data = json.load(f)
    regime_w = data.get("regime_weights", {}).get(regime, {})
    base_w = data.get("weights", {})
    # Regime-specific weights override base weights
    merged = {**base_w, **regime_w}
    return merged
```

**Integration**: Pass weights when building gate nodes:

```python
weights = _load_weights(regime)
graph.add_node(f"{tk}:dip_gate",
    compute=...,
    depends_on=[f"{tk}:dip_level"],
    edge_weights=weights.get(f"{tk}:dip_gate", {}),
    ...)
```

### 3.4 New file: `tools/weight_learner.py`

**Purpose**: After trades close, update synapse weights based on outcomes.

```python
"""Update synapse weights from trade outcomes.

Usage:
    python3 tools/weight_learner.py --trade-log data/backtest/results.json
    python3 tools/weight_learner.py --live  # reads from trade_history.json
"""

def update_weights(trade_results, current_weights, learning_rate=0.01):
    """Reward-modulated Hebbian update.

    For each closed trade:
      outcome = +1 if pnl > 0 else -1
      For each synapse that fired for this trade:
        weight += learning_rate * outcome * normalized_input
        weight = clamp(weight, 0.0, 1.0)

    NOTE: This cannot learn negative correlations. If experimentation
    shows some inputs inversely predict success, expand range to [-1, 1].
    """
    updated = dict(current_weights)
    for trade in trade_results:
        tk = trade["ticker"]
        outcome = 1.0 if trade["pnl"] > 0 else -1.0
        # Get the input values that were active for this trade
        for gate_name, input_values in trade.get("fired_inputs", {}).items():
            node_weights = updated.get(gate_name, {})
            for input_name, input_val in input_values.items():
                # Normalize input to [0, 1] range
                norm_val = min(abs(input_val) / 10.0, 1.0)
                w = node_weights.get(input_name, 1.0)
                w += learning_rate * outcome * norm_val
                w = max(0.0, min(1.0, w))
                node_weights[input_name] = round(w, 4)
            updated[gate_name] = node_weights
    return updated
```

**Training data source**: The backtester's sweep results (Phase 2) contain per-trade outcomes with entry, exit_reason, and pnl. The `fired_inputs` field needs to be added to the backtester output — record what dip_level, bounce_level values were active when each trade was taken.

### 3.5 Backtester extension — record fired inputs

**In `replay_day()`**, when a trade is taken, record the observer values:

```python
buys.append({
    "ticker": tk,
    "entry": round(entry, 2),
    "pnl": round(pnl, 2),
    "pnl_pct": round(pnl / entry * 100, 2),
    "exit_reason": exit_reason,
    # NEW: record what inputs fired for weight learning
    "fired_inputs": {
        f"{tk}:dip_gate": {f"{tk}:dip_level": dip_pct},
        f"{tk}:bounce_gate": {f"{tk}:bounce_level": bounce_pct},
    }
})
```

### 3.6 CANDIDATE aggregator change — soft AND

With weights, the CANDIDATE node changes from hard AND to weighted score:

```python
# Current: all([dipped, bounced, viable, ...])
# New: weighted score
graph.add_node(f"{tk}:candidate",
    compute=lambda inputs, t=tk: _compute_candidate_score(inputs, t),
    depends_on=[f"{tk}:dip_gate", f"{tk}:bounce_gate", ...],
    edge_weights=weights.get(f"{tk}:candidate", {}),
    ...)

def _compute_candidate_score(inputs, tk):
    """Soft AND: sum weighted gate outputs, compare to threshold."""
    gates = [f"{tk}:dip_gate", f"{tk}:bounce_gate", f"{tk}:dip_viable",
             f"{tk}:not_catastrophic", f"{tk}:not_exit",
             f"{tk}:earnings_clear", f"{tk}:historical_range"]
    # Safety gates (catastrophic, exit, earnings) always use hard AND
    safety_gates = [f"{tk}:not_catastrophic", f"{tk}:not_exit", f"{tk}:earnings_clear"]
    for sg in safety_gates:
        if not inputs.get(sg, False):
            return False

    # Soft gates use weighted sum
    soft_gates = [g for g in gates if g not in safety_gates]
    score = sum(1.0 if inputs.get(g, False) else 0.0 for g in soft_gates)
    # With 4 soft gates, threshold 3.0 = at least 3 of 4 must pass
    return score >= 3.0
```

**Note**: Safety constraints (catastrophic, exit, earnings) remain hard AND — these are not learnable. Only the signal gates (dip, bounce, viable, range) participate in the soft AND.

### 3.7 Verification

1. Run backtester with all weights = 1.0 — verify identical results to Phase 1
2. Set one weight to 0.0 — verify that input is ignored
3. Run `weight_learner.py` on sweep results — verify weights change
4. Re-run backtester with learned weights — compare P/L to uniform weights
5. Test regime-aware weights: set different weights for Risk-Off, verify correct weights load

### 3.8 Files

| File | Action | Estimated lines |
| :--- | :--- | :--- |
| `tools/graph_engine.py` | MODIFY — edge_weights parameter | ~25 (ESTIMATE) |
| `tools/weight_learner.py` | NEW — weight update logic | ~120 |
| `tools/neural_dip_evaluator.py` | MODIFY — load weights, pass to nodes | ~30 |
| `tools/neural_dip_backtester.py` | MODIFY — record fired_inputs | ~15 |
| `data/synapse_weights.json` | NEW — persisted weights | auto-generated |

---

## Phase 4: Portfolio Optimization Layer

**Goal**: At scale, prevent concentrated bets — don't buy 10 crypto miners on the same dip day.

### 4.1 Sector balance gate

**Uses existing infrastructure**: `tools/sector_registry.py` already has `FINE_SECTOR_MAP` (174 tickers) and `get_sector()` with yfinance fallback.

**New node in `build_decision_graph()`**:

```python
from sector_registry import get_sector

# After ranking candidates, before creating buy_dip nodes:
sector_counts = {}
sector_filtered_top = []
MAX_PER_SECTOR = 2  # configurable

for c in top:
    sector = get_sector(c["ticker"])
    count = sector_counts.get(sector, 0)
    if count < MAX_PER_SECTOR:
        sector_filtered_top.append(c)
        sector_counts[sector] = count + 1
    # else: skip this candidate

# Use sector_filtered_top instead of top for buy_dip nodes
```

### 4.2 Correlation gate

**Approach**: Before creating buy_dip nodes, check pairwise correlation of candidate price series. Skip candidates that correlate >0.8 with an already-selected candidate.

```python
def _filter_correlated(candidates, prices, threshold=0.8):
    """Remove candidates that correlate highly with already-selected ones."""
    selected = []
    for c in candidates:
        if not selected:
            selected.append(c)
            continue
        correlated = False
        for s in selected:
            corr = _compute_correlation(prices, c["ticker"], s["ticker"])
            if corr > threshold:
                correlated = True
                break
        if not correlated:
            selected.append(c)
    return selected
```

**Data source**: The intraday price data is already available (passed to `build_decision_graph()`).

### 4.3 Capital allocation

**Current**: Fixed budget per trade (`budget_normal=100` or `budget_risk_off=50`).

**Proposed**: Distribute budget by confidence score × expected P/L:

```python
def _allocate_capital(candidates, total_budget, profiles):
    """Distribute budget proportionally by expected return."""
    for c in candidates:
        profile = _get_profile(c["ticker"], profiles)
        # Expected return = target_pct × win_rate (from profile confidence)
        c["budget"] = total_budget / len(candidates)  # start with equal
    return candidates
```

**Simplest first**: Equal allocation is the starting point. Confidence-weighted allocation is a Phase 5 refinement once confidence scores have been validated.

### 4.4 max_tickers cap

**Current**: Hard-coded at 5 in DIP_CONFIG. At 400 tickers, this may need to increase.

**Change**: Make it configurable but keep the current default:

```python
DIP_CONFIG = {
    ...
    "max_tickers": 5,  # increase when capital and risk tolerance allow
}
```

This is a strategy decision — the code just needs to read the config value.

### 4.5 Files

| File | Action | Estimated lines |
| :--- | :--- | :--- |
| `tools/neural_dip_evaluator.py` | MODIFY — sector filter, correlation filter | ~60 |
| `tools/sector_registry.py` | NO CHANGES (already has what we need) | 0 |

---

## Phase 5: Continuous Learning Pipeline

**Goal**: Automate the weekly re-optimization so the system maintains itself.

### 5.1 New file: `tools/weekly_reoptimize.py`

```python
"""Weekly re-optimization pipeline. Run via cron every Saturday.

Steps:
  1. Download latest 60-day 5-min data
  2. Run parameter sweep for all tickers
  3. Re-cluster
  4. Update ticker_profiles.json
  5. Compute confidence scores
  6. Run weight learning on sweep results
  7. Email summary
"""
```

**Integration**: Calls `parameter_sweeper.py` and `ticker_clusterer.py` from Phase 2, and `weight_learner.py` from Phase 3.

### 5.2 Cross-validation

**Add to parameter_sweeper.py**: `--split` flag that runs the sweep on first 40 days, then validates on last 20 days.

```python
parser.add_argument("--split", action="store_true",
    help="Train on first 2/3, validate on last 1/3")
```

Compare best params' in-sample P/L vs out-of-sample P/L. Flag tickers where out-of-sample P/L is negative despite positive in-sample (overfitting signal).

### 5.3 Divergence monitoring

Track live trades vs backtested predictions:

```python
def check_divergence(live_trades, backtested_predictions):
    """Flag if live P/L diverges >2 std from backtested P/L."""
    live_pnl = [t["pnl"] for t in live_trades]
    bt_pnl = [t["pnl"] for t in backtested_predictions]
    if len(live_pnl) < 10:
        return None  # not enough data
    live_mean = np.mean(live_pnl)
    bt_std = np.std(bt_pnl, ddof=1)
    bt_mean = np.mean(bt_pnl)
    z_score = (live_mean - bt_mean) / bt_std if bt_std > 0 else 0
    return {"z_score": z_score, "divergent": abs(z_score) > 2.0}
```

### 5.4 Cron entry

```cron
# Weekly re-optimization — Saturday 6 AM local
0 6 * * 6 cd /Users/kamenkamenov/agentic-trading && python3 tools/weekly_reoptimize.py >> data/reoptimize.log 2>&1
```

### 5.5 Email summary via existing notify.py

Add a generic `send_summary_email()` function to `tools/notify.py` (which already has `send_dip_alert()` for BUY_DIP notifications). The new function reuses the existing SendGrid setup:

```python
# NEW function added to tools/notify.py
def send_summary_email(subject, body):
    """Send a plain-text summary email via SendGrid."""
    # Uses same _send_email() internal as send_dip_alert()
    ...
```

Then call from the pipeline:

```python
from notify import send_summary_email
send_summary_email(
    subject="Weekly Re-optimization Complete",
    body=f"Clusters: {n_clusters}\nProfiles updated: {n_updated}\nConfidence drops: {n_drops}"
)
```

### 5.6 Files

| File | Action | Estimated lines |
| :--- | :--- | :--- |
| `tools/weekly_reoptimize.py` | NEW — pipeline orchestrator | ~150 |
| `tools/parameter_sweeper.py` | MODIFY — add --split for cross-validation | ~40 |
| `tools/notify.py` | MODIFY — add send_summary_email() | ~15 |
| cron | NEW entry | 1 |

---

## Implementation Order and Dependencies

```
Phase 1 (Level-firing)
  ↓
  ├── Phase 2 (Sweep + Clustering) ──→ Phase 5 (Continuous pipeline)
  │                                       ↑
  └── Phase 4 (Portfolio optimization)    │
                                          │
      Phase 3 (Synapse weights) ──────────┘
```

- Phase 1 is prerequisite for all others
- Phases 2 and 4 can run in parallel after Phase 1
- Phase 3 requires Phase 2 (needs sweep results as training data)
- Phase 5 requires Phases 2 and 3

---

## Total Estimated Changes

| Category | Lines |
| :--- | :--- |
| New files | ~620 (sweeper 200, clusterer 150, weight_learner 120, weekly 150) |
| Modified files | ~290 (evaluator ~160, backtester ~105, graph_engine ~25) |
| Data files | ~3 (profiles JSON, weights JSON, cron) |
| New dependency | scikit-learn |
| **Total** | **~910 lines of code** |

**NOTE**: All line estimates are ESTIMATES. Actual counts will vary during implementation.

---

## Risk Mitigation

### Backward compatibility at every phase
- Phase 1: `profiles=None` defaults to DIP_CONFIG. Existing callers work unchanged.
- Phase 3: `edge_weights={}` defaults to 1.0. Existing graphs work unchanged.
- Each phase can be deployed independently. If Phase 3 has issues, Phase 1+2 still work.

### No hallucinated capabilities
- Every proposed change references existing code by file and line number
- No timing estimates are given (unmeasured — benchmark after building)
- No convergence claims for weight learning (needs experimentation)
- Clustering algorithm choice deferred to experimentation on real data

### Safety constraints never become learnable
- PDT limits, capital minimums, catastrophic stops, earnings gates — always hard AND
- Synapse weights only apply to signal gates (dip, bounce, range, viable)
- Learning cannot override safety constraints
