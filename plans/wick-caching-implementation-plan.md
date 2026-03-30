# Implementation Plan: Wick Analysis Caching for Support Sweeper

**Date**: 2026-03-29
**Finding**: 73% of simulation time is wick analysis, recomputed identically across all 30 threshold combos per ticker. Caching eliminates 29 of 30 redundant calls.
**Expected speedup**: Stage 1 from 85 min → ~6.5 min sequential, ~1 min with 8 workers.

---

## Verified Facts

- **FACT**: `run_simulation()` calls `analyze_stock_data()` ~50 times per invocation (weekly recompute over 249 days). Confirmed by cProfile: 2.90s of 3.95s total (73%).
- **FACT**: `analyze_stock_data()` takes `(ticker, hist, config, capital_config)` as inputs. It does NOT take sell_target, stop_pct, or any trade-state parameter.
- **FACT**: During Stage 1 threshold sweep, `capital_config` is FIXED (default pool=$300, bullets=5). Only sell_target and cat_hard_stop vary. Wick analysis results are identical across all 30 combos.
- **FACT**: During Stage 2 execution sweep, `capital_config` varies (pool/bullets change). Wick LEVELS are the same but bullet plan differs per combo. Partial caching possible (cache levels, recompute plan).
- **FACT**: Recompute frequency matters for accuracy: daily=249 calls/$573 P/L, weekly=50 calls/$248, monthly=12 calls/$86. Cannot skip recomputation without changing results.

---

## Approach

Cache wick analysis results PER (ticker, recompute_day, capital_config_hash) inside a single sweep run. When the next combo requests wick analysis for the same ticker on the same day with the same capital config, return the cached result instead of recomputing.

### Why this is safe

The wick analyzer is a **pure function** of its inputs: same `(ticker, hist_slice, config, capital_config)` → same output. During a sweep:
- `ticker` is fixed (one ticker per sweep call)
- `hist_slice` at any given recompute day is fixed (same price history)
- `config` (WickConfig) is fixed (not swept)
- `capital_config` is fixed during Stage 1, varies during Stage 2

So during Stage 1, ALL 30 combos produce identical wick calls. Cache hit rate: 29/30 = 97%.

---

## Implementation

### Step 1: Add wick cache to `backtest_engine.py` (~20 lines)

**FACT** (verified): `analyze_stock_data` is called at line 509 of `backtest_engine.py` inside the daily simulation loop. It's called when `sim_day_count % recompute_interval == 0` (line 506).

**Change**: Add a `wick_cache` dict parameter to `run_simulation()`. Before calling `analyze_stock_data`, check the cache. After calling, store the result.

```python
def run_simulation(price_data, regime_data, cfg, wick_cache=None):
    """..."""
    if wick_cache is None:
        wick_cache = {}  # no sharing across calls — backward compat

    ...
    # Line ~509, where wick analysis is called:
    # Condition: days_since_recompute[tk] >= recompute_interval (lines 477-479, counter-based)
    # Cache key uses day_idx (the simulation day index, line 213) — NOT sim_day_count (doesn't exist)
    cache_key = (tk, day_idx)
    if cache_key in wick_cache:
        wick_result = wick_cache[cache_key]
        err = None
    else:
        wick_result, err = analyze_stock_data(tk, hist=hist_slice, ...)
        if not err:
            wick_cache[cache_key] = wick_result
```

**Backward compat**: `wick_cache=None` → creates empty dict per call → no caching → identical to current behavior. Existing callers pass no `wick_cache` → unchanged.

**Compounding safety**: `SurgicalSimConfig.compound` defaults to `False` (line 166 of `backtest_config.py`). When compound=False, `live_capital` is derived from the fixed `capital_config` dict, NOT from trade-history-dependent remaining capital. This means `live_capital` is identical across combos during Stage 1 → cache is safe.

**IMPORTANT**: If `cfg.compound=True`, the cache is UNSAFE — `live_capital` varies by trade history across combos, producing different wick bullet plans. The sweeper MUST NOT pass `compound=True` with a shared cache. Add a guard:

```python
if wick_cache and cfg.compound:
    raise ValueError("Cannot use wick_cache with compound=True — capital varies by trade history")
```

**For Stage 1 sweep**: The sweeper creates ONE `wick_cache` dict and passes it to all 30 `run_simulation()` calls for the same ticker:

```python
wick_cache = {}  # shared across combos
for sell_target, cat_stop in combos:
    cfg = SurgicalSimConfig(sell_default=sell_target, ...)
    trades, cycles, eq, dip = run_simulation(price_data, regime_data, cfg, wick_cache)
    # First combo: cache miss → computes 50 wick calls → stores in cache
    # Combos 2-30: cache hit → 0 wick calls → uses cached results
```

### Step 2: Wire cache into `support_parameter_sweeper.py` (~15 lines)

**Change `_simulate_with_config()`**: Accept and pass `wick_cache`:

```python
def _simulate_with_config(ticker, months, config_overrides, data_dir=None, wick_cache=None):
    ...
    trades, cycles, equity, dip = run_simulation(price_data, regime_data, cfg, wick_cache)
```

**Change `sweep_threshold()`**: Create one cache, pass to all combos:

```python
def sweep_threshold(ticker, months=10):
    data_dir = _collect_once(ticker, months)
    price_data, regime_data, _ = load_collected_data(data_dir)
    wick_cache = {}  # shared across all 30 combos

    for sell_target, cat_stop in combos:
        ...
        result = _simulate_with_config(ticker, months, overrides, data_dir, wick_cache)
```

**Change `sweep_execution()`**: Group combos by unique capital_config, share cache within each group:

```python
def sweep_execution(ticker, threshold_params, months=10):
    data_dir = _collect_once(ticker, months)
    price_data, regime_data, _ = load_collected_data(data_dir)

    # Group combos by (pool, bullets) — combos with same pool+bullets
    # but different tier thresholds produce identical wick analysis
    # (tier thresholds only affect which levels are used, not the wick computation)
    # Reduced grid: 3 pools × 3 bullets = 9 groups
    # Within each group: 2 reserve_pools × 2 tier_full × 2 tier_std = 8 combos share the same cache
    for pool in EXECUTION_GRID["active_pool"]:
        for bullets in EXECUTION_GRID["active_bullets_max"]:
            wick_cache = {}  # new cache per (pool, bullets) group
            for res_pool, res_bullets, t_full, t_std in itertools.product(...):
                cfg = SurgicalSimConfig(active_pool=pool, active_bullets_max=bullets, ...)
                trades, ... = run_simulation(price_data, regime_data, cfg, wick_cache)
    # 9 groups × 1 wick computation each = 9 wick calls (vs 144 without cache)
```

With the reduced grid (3 pools × 3 bullets = 9 unique capital configs), cache hit rate for Stage 2: 135/144 = 94%.

### Step 3: Load price data ONCE per ticker (~10 lines)

**Current**: `_simulate_with_config()` calls `load_collected_data()` every invocation. With 30 combos, that's 30 pickle loads of the same file.

**Fix**: Load once in `sweep_threshold()`, pass `price_data` and `regime_data` directly:

```python
def sweep_threshold(ticker, months=10):
    data_dir = _collect_once(ticker, months)
    price_data, regime_data, _ = load_collected_data(data_dir)  # load ONCE
    wick_cache = {}

    for sell_target, cat_stop in combos:
        cfg = SurgicalSimConfig(...)
        cfg.tickers = [ticker]
        trades, cycles, eq, dip = run_simulation(price_data, regime_data, cfg, wick_cache)
```

This eliminates 29 redundant pickle loads per ticker.

---

## Verification

1. Run CIFR sweep WITHOUT cache → record all 30 P/L values
2. Run CIFR sweep WITH cache → record all 30 P/L values
3. Compare: all 30 must match exactly (cache doesn't change results)
4. Compare time: expect ~29x speedup for Stage 1

---

## Files Modified

| File | Change | Backward compat | Lines |
| :--- | :--- | :--- | :--- |
| `tools/backtest_engine.py` | Add `wick_cache` param to `run_simulation()` | `wick_cache=None` → no caching | ~20 |
| `tools/support_parameter_sweeper.py` | Load data once, share `wick_cache` across combos | Existing callers unchanged | ~25 |

**No changes to**: `graph_engine.py`, `neural_dip_evaluator.py`, `parameter_sweeper.py`, `backtest_config.py`, dip strategy files (all frozen)

---

## Expected Performance

| Scenario | Current | With caching | Speedup |
| :--- | :--- | :--- | :--- |
| 1 ticker Stage 1 (30 combos) | 62s | ~4s (1 wick + 29 cached) | ~15x |
| 68 tickers Stage 1 sequential | 85 min | ~4.5 min | ~19x |
| 68 tickers Stage 1 + 8 workers | ~17 min | ~35s | ~29x |
| Stage 2 (144 combos, 5 tickers) | ~24 min | ~3 min (9 unique configs) | ~8x |

NOTE: All performance numbers are ESTIMATES extrapolated from the benchmark. Must verify with actual runs.
