# Implementation Plan: Neural Candidate Discovery at Universe Scale

**Date**: 2026-03-29
**Source analysis**: `plans/neural-candidate-discovery-analysis.md` (verified, 0 hallucinations)
**Goal**: Apply the neural network to ~1,500 universe passers to discover top 30 same-day dip-buy candidates, with breadth as a learned parameter.

---

## Scope

3 implementation steps, executed sequentially (each depends on the prior):

| Step | What | Files Modified | Files Created |
| :--- | :--- | :--- | :--- |
| 1 | Add breadth to sweep grid + convert breadth neurons to level-firing | `parameter_sweeper.py`, `neural_dip_evaluator.py` | — |
| 2 | Build neural candidate discoverer | — | `neural_candidate_discoverer.py` |
| 3 | Test at scale | — | `data/neural_candidates.json` |

---

## Step 1: Breadth as a Learned Parameter

### 1.1 Add breadth to sweep grid in `parameter_sweeper.py`

**Add constant** (after existing sweep grids, line ~46):
```python
SWEEP_BREADTH = [0.10, 0.20, 0.30, 0.40, 0.50]
```

### 1.2 Change `precompute_signals()` to NOT filter by breadth

**Current** (line 89 of parameter_sweeper.py):
```python
if not fh_state.get("breadth_dip"):
    continue
```

**Change to**: Record breadth ratio per day, don't filter. All signal days are kept regardless of breadth — the sweep decides which breadth threshold works.

```python
# Don't filter by breadth — record the ratio, let sweep decide
breadth_ratio = dip_count_for_day / n if n > 0 else 0
```

**Problem**: `dip_count` is computed inside `build_first_hour_graph()` and returned as a boolean `breadth_dip` in `fh_state`. We need the RAW ratio, not the boolean.

**Solution**: `build_first_hour_graph()` already stores per-ticker dip_pct in `fh_state` (lines 461-467 of evaluator, after `graph.resolve()`). Compute breadth_ratio OUTSIDE the graph from the per-ticker dip data in fh_state:

```python
# After build_first_hour_graph(), compute raw breadth from fh_state
dip_count_for_day = sum(1 for tk in tickers
                        if fh_state.get(f"{tk}:dip_pct", 0) >= dip_thresh)
breadth_ratio = dip_count_for_day / n if n > 0 else 0
```

This avoids modifying `build_first_hour_graph()` — the raw dip_pct values are already in fh_state.

Store breadth_ratio at the day level in the signals dict:

```python
# Store all ticker data for this day + breadth ratio
day_entry = {"_breadth_ratio": round(breadth_ratio, 3)}
for tk in tickers:
    ...  # existing per-ticker data
    day_entry[tk] = tk_data_dict
day_signals[str(day)] = day_entry
```

### 1.3 Change `sweep_ticker()` to include breadth in the sweep

**Current loop** (line 170):
```python
for target_pct, stop_pct in itertools.product(SWEEP_TARGETS, SWEEP_STOPS):
```

**Change to**:
```python
for target_pct, stop_pct, breadth_thresh in itertools.product(
        SWEEP_TARGETS, SWEEP_STOPS, SWEEP_BREADTH):
```

**Add breadth filter inside the day loop**:
```python
for day_str, day_data in day_signals.items():
    if day_filter and day_str not in day_filter:
        continue
    # Breadth gate — skip days where breadth doesn't meet this threshold
    if day_data.get("_breadth_ratio", 0) < breadth_thresh:
        continue
    if tk not in day_data:
        continue
    d = day_data[tk]
    ...
```

**Add breadth_threshold to output params**:
```python
best_params = {
    "dip_threshold": dip_thresh,
    "bounce_threshold": DIP_CONFIG["bounce_threshold_pct"],
    "target_pct": target_pct,
    "stop_pct": stop_pct,
    "breadth_threshold": breadth_thresh,  # NEW
}
```

### 1.4 Update `evaluate_params()` to include breadth filter

Same change — add `breadth_thresh` from params, filter days by `_breadth_ratio`.

### 1.5 Convert breadth neurons to level-firing in `neural_dip_evaluator.py`

**In `build_first_hour_graph()`** — convert `breadth_dip` binary node:

Current (line ~454):
```python
graph.add_node("breadth_dip",
    compute=lambda _: breadth_ratio >= cfg["breadth_threshold"], ...)
```

Change to:
```python
graph.add_node("breadth_dip_level", compute=lambda _: breadth_ratio,
    reason_fn=lambda old, new, _: f"BREADTH_DIP={new:.0%}")
graph.add_node("breadth_dip_gate",
    compute=lambda inputs: inputs["breadth_dip_level"] >= cfg["breadth_threshold"],
    depends_on=["breadth_dip_level"],
    reason_fn=lambda old, new, _:
        f"BREADTH_GATE(>={cfg['breadth_threshold']:.0%}) {'FIRED' if new else 'NOT FIRED'}")
```

**Note**: For the evaluator (live trading), breadth_threshold still comes from DIP_CONFIG (global). For the sweep, breadth is varied per combo. This is consistent — the sweep discovers the optimal value, which then gets written to profiles and eventually to DIP_CONFIG or per-ticker override.

**In `build_decision_graph()`** — same conversion for `breadth_bounce`:

Current (line ~581):
```python
graph.add_node("breadth_bounce", compute=lambda _: breadth_bounce_fired, ...)
```

Change to:
```python
graph.add_node("breadth_bounce_level", compute=lambda _: breadth_bounce_ratio,
    reason_fn=lambda old, new, _: f"BREADTH_BOUNCE={new:.0%}")
graph.add_node("breadth_bounce_gate",
    compute=lambda inputs: inputs["breadth_bounce_level"] >= cfg["breadth_threshold"],
    depends_on=["breadth_bounce_level"],
    reason_fn=lambda old, new, _:
        f"BOUNCE_BREADTH_GATE(>={cfg['breadth_threshold']:.0%}) {'FIRED' if new else 'NOT FIRED'}")
```

**Update `signal_confirmed`** to depend on the new gate names:
```python
graph.add_node("signal_confirmed",
    compute=lambda inputs: inputs["breadth_dip_gate"] and inputs["breadth_bounce_gate"],
    depends_on=["breadth_dip_gate", "breadth_bounce_gate"], ...)
```

Wait — `signal_confirmed` currently depends on `breadth_bounce` which depends on `breadth_dip` being fired (from fh_state). With level-firing, `signal_confirmed` should depend on BOTH breadth gates. But `breadth_dip_gate` is in the first-hour graph, not the decision graph. It's passed via `fh_state`.

**Resolution**: Keep `breadth_dip_fired` as a value read from `fh_state` (same as current). The level-firing conversion for `breadth_dip` is in the first-hour graph (for reason chains). In the decision graph, `signal_confirmed` uses the cached boolean from fh_state + the new `breadth_bounce_gate`:

```python
signal_confirmed = breadth_dip_fired and breadth_bounce_fired
# breadth_dip_fired comes from fh_state (already computed in first-hour graph)
# breadth_bounce_fired comes from the new breadth_bounce_gate
```

Actually, this is the SAME as current — `breadth_dip_fired = fh_state.get("breadth_dip", False)`. We just need to change the fh_state key from `"breadth_dip"` to `"breadth_dip_gate"` since the node name changed.

### 1.6 Update fh_state key references

In `evaluate_first_hour()` (line ~616):
```python
# Current
dip_count = sum(1 for tk in tickers if fh_state.get(f"{tk}:dip_gate"))

# Already correct — uses dip_gate
```

In `evaluate_decision()` and in the decision graph builder:
```python
# Current
breadth_dip_fired = fh_state.get("breadth_dip", False)

# Change to
breadth_dip_fired = fh_state.get("breadth_dip_gate", False)
```

### 1.7 Add `breadth_threshold` to `_get_profile()` fallback

```python
def _get_profile(tk, profiles):
    if profiles and tk in profiles:
        return profiles[tk]
    return {
        "dip_threshold": DIP_CONFIG["dip_threshold_pct"],
        "bounce_threshold": DIP_CONFIG["bounce_threshold_pct"],
        "target_pct": 4.0,
        "stop_pct": -3.0,
        "breadth_threshold": DIP_CONFIG["breadth_threshold"],  # NEW
    }
```

### 1.8 Verification

1. Run `python3 tools/parameter_sweeper.py --cached` — verify 600 combos (not 120), breadth_threshold in output
2. Run `python3 tools/neural_dip_backtester.py --cached --days 30` — verify it still works (breadth gates fire correctly)
3. Verify reason chains show `BREADTH_DIP=23%` and `BREADTH_GATE(>=50%) FIRED`

### 1.9 Files modified

| File | Changes | Estimated lines |
| :--- | :--- | :--- |
| `tools/parameter_sweeper.py` | Add SWEEP_BREADTH, remove breadth filter in precompute, add breadth to sweep loop, store _breadth_ratio | ~50 |
| `tools/neural_dip_evaluator.py` | Convert breadth_dip + breadth_bounce to level-firing, update fh_state key, add breadth_threshold to _get_profile | ~25 |

---

## Step 2: Neural Candidate Discoverer

### 2.1 New file: `tools/neural_candidate_discoverer.py`

**Purpose**: Scan full universe through neural dip strategy, rank by validation P/L, output top 30.

```
Usage:
    python3 tools/neural_candidate_discoverer.py                    # full run
    python3 tools/neural_candidate_discoverer.py --cached           # use cached intraday
    python3 tools/neural_candidate_discoverer.py --top 50           # top 50 instead of 30
    python3 tools/neural_candidate_discoverer.py --chunk-size 300   # download in chunks
```

### 2.2 Pipeline stages

```python
def main():
    # Stage 0: Validate universe cache
    cache_path = _ROOT / "data" / "universe_screen_cache.json"
    if not cache_path.exists():
        print("*No universe cache. Run: python3 tools/universe_screener.py*")
        return
    cache_age = (datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)).days
    if cache_age > 7:
        print(f"*Universe cache is {cache_age} days old (>7). Consider refreshing.*")

    # Stage 1: Load universe passers
    passers = load_universe_passers()  # from universe_screen_cache.json
    exclude = load_existing_tickers()  # portfolio positions + watchlist
    candidates = [p for p in passers if p["ticker"] not in exclude]

    # Stage 2: Download intraday data (chunked for large universe)
    intraday, daily = download_universe_data(
        [c["ticker"] for c in candidates], chunk_size=300)

    # Stage 3: Two-pass signal computation
    # Pass 1: Compute raw dip_pct per ticker per day (arithmetic only — no graph)
    # Determine breadth_ratio per day to skip days where no breadth threshold fires
    raw_dips = compute_raw_dips(tickers, trading_days, intraday)
    # Pass 2: Build graph ONLY on days where breadth >= min(SWEEP_BREADTH)
    # (i.e., at least 10% of tickers dipped — the lowest breadth we sweep)
    signal_days = [d for d in trading_days
                   if raw_dips[d]["breadth_ratio"] >= min(SWEEP_BREADTH)]
    signals = precompute_signals_on_days(tickers, signal_days, intraday, daily)

    # Stage 4: Sweep each ticker (with cross-validation)
    train_days, val_days = split_days(all_signal_days)
    results = {}
    for tk in tickers:
        params, stats, trades, features = sweep_ticker(tk, signals, train_days)
        if params:
            cv = evaluate_params(tk, params, signals, val_days)
            results[tk] = {params, stats, trades, features, cv}

    # Stage 5: Rank by validation P/L, apply gates
    ranked = rank_and_gate(results)

    # Stage 6: Cluster top candidates
    cluster_top(ranked[:50])

    # Stage 7: Output top 30
    write_results(ranked[:30])
```

**Two-pass optimization (from analysis Section 5.3, Option B):**

Pass 1 (`compute_raw_dips`) is pure arithmetic — for each day, compute `(open - 10:30_price) / open` for every ticker. This gives `dip_pct` per ticker and `breadth_ratio` per day without building any graph nodes. At 1,500 tickers this is a ~0.1s operation per day.

Pass 2 only builds the full graph on days where `breadth_ratio >= 10%` (the lowest SWEEP_BREADTH value). At 1,500 tickers, if only 30% of days pass this filter, we avoid building 12,000-node graphs on 70% of days.

```python
def compute_raw_dips(tickers, trading_days, intraday, dip_thresh):
    """Pass 1: Arithmetic-only dip computation. No graph, no nodes."""
    results = {}
    n = len(tickers)
    for day in trading_days:
        day_bars = intraday[intraday.index.date == day]
        if len(day_bars) < 12:
            continue
        fh_bars = day_bars.iloc[:12]
        dip_count = 0
        for tk in tickers:
            o = _extract_open(fh_bars, tk, n)
            c = _extract_price_at(fh_bars, tk, 10, 30, n)
            dip_pct = round((o - c) / o * 100, 1) if o and c and o > 0 else 0
            if dip_pct >= dip_thresh:
                dip_count += 1
        results[day] = {"breadth_ratio": dip_count / n if n > 0 else 0}
    return results
```

### 2.3 Chunked data download

yfinance may throttle at 1,500 tickers. Download in chunks with delays:

```python
def download_universe_data(tickers, chunk_size=300, delay=5):
    """Download 5-min data in chunks to avoid yfinance throttling."""
    all_data = []
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        print(f"Downloading chunk {i//chunk_size + 1} ({len(chunk)} tickers)...")
        data = yf.download(chunk, period="60d", interval="5m", progress=False)
        all_data.append(data)
        if i + chunk_size < len(tickers):
            time.sleep(delay)
    # Concatenate chunks
    return pd.concat(all_data, axis=1)
```

### 2.4 Ranking and gating

```python
def rank_and_gate(results):
    """Rank by validation P/L, apply gates."""
    ranked = []
    for tk, r in results.items():
        cv = r.get("cross_validation")
        if not cv or cv["trades"] < 2:
            continue  # too few validation trades
        if cv["pnl"] <= 0:
            continue  # negative out-of-sample
        if r["stats"]["total_pnl"] > 0 and cv["pnl"] < 0:
            continue  # overfitting: train positive, validation negative
        ranked.append({"ticker": tk, "val_pnl": cv["pnl"], **r})

    ranked.sort(key=lambda x: x["val_pnl"], reverse=True)
    return ranked
```

### 2.5 Output files

- `data/neural_candidates.json` — structured results (schema from analysis Section 6.1)
- `data/neural_candidates.md` — human-readable ranked table

### 2.6 Files created

| File | Purpose | Estimated lines |
| :--- | :--- | :--- |
| `tools/neural_candidate_discoverer.py` | Universe-scale neural sweep + ranking | ~250 |

---

## Step 3: Test at Scale

### 3.1 Initial test at current scale (21 tickers)

Before running on 1,500 tickers, verify the full pipeline works on current watchlist:

```bash
python3 tools/neural_candidate_discoverer.py --cached
```

This uses cached 5-min data for 21 tickers. Should complete in <30 seconds.

### 3.2 Scale test at ~200 tickers

Run on a subset of universe passers to benchmark:

```bash
python3 tools/neural_candidate_discoverer.py --top 200 --chunk-size 100
```

Measure: download time, pre-computation time, total time, memory usage.

### 3.3 Full run at 1,500 tickers

```bash
python3 tools/neural_candidate_discoverer.py --top 1500
```

Expected runtime: UNMEASURED. Must benchmark at 200 first and extrapolate.

### 3.4 Verification checklist

1. Breadth threshold varies per ticker in output (not all 50%)
2. Cross-validation P/L shown for each candidate
3. Overfitting tickers rejected (positive train, negative validation)
4. Top 30 sorted by validation P/L
5. Cluster assignments in output
6. Profile schema includes `breadth_threshold`

---

## Implementation Order

```
Step 1: Breadth as learned parameter
  ├── parameter_sweeper.py (breadth in sweep grid)
  └── neural_dip_evaluator.py (breadth level-firing)
  ↓
Step 2: neural_candidate_discoverer.py
  ↓
Step 3: Test (21 → 200 → 1500)
```

---

## Total Estimated Changes

| Category | Lines |
| :--- | :--- |
| New files | ~250 (neural_candidate_discoverer.py) |
| Modified files | ~75 (parameter_sweeper ~50, evaluator ~25) |
| **Total** | **~325 lines** |

**No changes to**: `graph_engine.py`, `ticker_clusterer.py`, `weight_learner.py`, `weekly_reoptimize.py`
