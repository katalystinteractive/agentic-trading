# Analysis: Stage 3 Level Filter Sweep Parallel Worker Support

**Date**: 2026-03-31 (Tuesday)
**Purpose**: Stage 3 (`--stage level`) runs sequentially — one ticker at a time, ~10 min each. At 26 tickers, this is ~4 hours. Stage 1 already supports `--workers N` via multiprocessing.Pool. Stage 3 should use the same pattern for ~8x speedup.

**Honesty note**: Every claim labeled FACT (verified) or PROPOSED.

---

## 1. Current State (FACT — verified)

**FACT**: Stage 1 parallel support exists at lines 599-612 of `support_parameter_sweeper.py`. Pattern:
- `_sweep_threshold_worker(args)` at line 505 — takes `(ticker, months)`, calls `sweep_threshold()`, returns `(ticker, result_dict_or_None)`
- `main()` checks `if args.workers > 1 and len(tickers) > 1:` (line 599)
- Uses `Pool(processes=min(args.workers, len(tickers)))` with `pool.map()` (lines 601-602)
- Falls back to sequential loop in the `else` branch (line 614)

**FACT**: Stage 3 at lines 717-761 runs sequentially only. No parallel path exists. Each ticker calls `sweep_levels(tk, threshold_params, execution_params, args.months)` which runs 100 combos × 4 periods = 400 simulations.

**FACT**: `sweep_levels()` is self-contained — it calls `_collect_once(ticker, ...)` internally (line 356), loads its own price data (line 358), and has no shared mutable state between tickers. Safe for multiprocessing.

**FACT**: The `_log_progress()` calls inside `sweep_levels()` (combo progress, quality metrics) write to stderr. In multiprocessing, each worker's stderr output will interleave. This is the same behavior as Stage 1 — acceptable for progress monitoring, just not perfectly ordered.

---

## 2. What Must Change (PROPOSED)

### 2.1 Add `_sweep_levels_worker()` function

Parallel with `_sweep_threshold_worker()` (line 505). Takes all needed args as a single tuple (multiprocessing.Pool.map requires a single arg per item).

```python
def _sweep_levels_worker(args):
    """Worker for parallel level filter sweep."""
    ticker, threshold_params, execution_params, months = args
    try:
        best_params, best_result, composite, periods = sweep_levels(
            ticker, threshold_params, execution_params, months)
        if best_params:
            return ticker, {
                "level_params": best_params,
                "stats": {
                    "composite": round(composite, 2) if composite else 0,
                    "pnl": best_result.get("pnl", 0) if best_result else 0,
                    "trades": best_result.get("sells", 0) if best_result else 0,
                },
                "periods": periods,
            }
        return ticker, None
    except Exception:
        return ticker, None
```

**~15 lines**

### 2.2 Add parallel fork in Stage 3 block of `main()`

Same pattern as Stage 1 (lines 599-612). Insert before the existing sequential loop:

```python
if args.workers > 1:
    worker_args = [(tk, prior[tk]["params"],
                    {k: prior[tk]["params"][k] for k in
                     ("active_pool", "reserve_pool", "active_bullets_max", "reserve_bullets_max")
                     if k in prior[tk]["params"]},
                    args.months)
                   for tk in tickers
                   if tk in prior and not tk.startswith("_")]
    with Pool(processes=min(args.workers, len(worker_args))) as pool:
        for tk, result in pool.map(_sweep_levels_worker, worker_args):
            if result:
                level_output[tk] = result
                lp = result["level_params"]
                print(f"  {tk}: hr={lp['min_hold_rate']} tf={lp['min_touch_freq']} "
                      f"zone={lp['zone_filter']} composite=${result['stats']['composite']:.1f}/mo",
                      flush=True)
            else:
                print(f"  {tk}: no improvement", flush=True)
else:
    # existing sequential loop stays here
    for tk in tickers:
        ...
```

**~20 lines**

### 2.3 Ticker filtering moves before the fork

Currently the sequential loop does per-ticker checks (lines 728-732: skip `_` prefixed, skip tickers not in `prior`). In the parallel path, this filtering happens when building `worker_args` (the list comprehension filters both). The warning for skipped tickers needs to be printed before the Pool starts:

```python
for tk in tickers:
    if not tk.startswith("_") and tk not in prior:
        print(f"  {tk}... *skipped (not in prior sweep results)*", flush=True)
```

**~3 lines**

---

## 3. Considerations

### 3.1 Progress logging interleaving

**FACT**: `_log_progress()` inside `sweep_levels()` writes to stderr with `flush=True`. With 8 workers, combo progress from different tickers will interleave. This is the same behavior Stage 1 has — all progress messages include the combo index but NOT the ticker name.

**PROPOSED**: Add the ticker name to `_log_progress` calls inside `sweep_levels()` to disambiguate interleaved output. This means modifying `sweep_levels()` to accept an optional `label` param or prefixing ticker inside the function (it already has `ticker` as first param).

### 3.2 Memory usage

**FACT**: Each worker loads price data independently via `_collect_once()` + `load_collected_data()`. At 8 workers, that's 8 tickers' worth of price data in memory simultaneously. Each ticker's data is ~2-5 MB (245 trading days of OHLCV). 8 × 5 MB = ~40 MB — negligible.

### 3.3 No shared state

**FACT**: `sweep_levels()` has no module-level mutable state that crosses ticker boundaries. The `_level_filter_cache` in `wick_offset_analyzer.py` is not accessed during sweeps (it's for the live bullet plan path). Each worker is fully independent.

### 3.4 Error handling

**FACT**: `_sweep_threshold_worker()` catches all exceptions and returns `(ticker, None)` (line 536-537). The same pattern should be used for `_sweep_levels_worker()`. Errors in one worker don't crash the pool.

### 3.5 `--dry-run` compatibility

**FACT**: The `--dry-run` flag gates the file write at line 758: `if level_output and not args.dry_run:`. This check runs in `main()` AFTER the parallel block completes. Since workers only return data via `pool.map()` return values (populating `level_output` in the main process), `--dry-run` works correctly in parallel mode without any change — the guard applies to the post-fork write, not inside workers.

### 3.6 Ticker uniqueness assumption

**FACT**: `_collect_once()` writes to `GATE_RESULTS_DIR / ticker / price_data.pkl` — a per-ticker filesystem cache. Parallel workers writing to the same ticker's directory would race. This cannot happen because `worker_args` is built from `tickers` (unique list) filtered by `prior` membership — each ticker appears exactly once. The list comprehension `for tk in tickers if tk in prior and not tk.startswith("_")` guarantees uniqueness since `tickers` itself is unique (derived from directory listing at line 580 or `--ticker` arg at line 575).

---

## 4. Files

| File | Change | Lines |
| :--- | :--- | :--- |
| `tools/support_parameter_sweeper.py` | Add `_sweep_levels_worker()`, parallel fork in Stage 3 block, pre-filter skip warnings | ~38 |
| **Total** | | **~38** |

---

## 5. Impact

| Metric | Sequential | Parallel (8 workers) |
| :--- | :--- | :--- |
| Stage 3 runtime (26 tickers) | ~4 hours | ~30-40 min |
| Weekly reoptimize total | ~5 hours | ~1.5 hours |
| Memory overhead | Baseline | +~40 MB |

---

## 6. Open Question

**Should `sweep_levels()` combo progress include the ticker name?** Currently `_log_progress(f"level combo {idx+1}/{total_combos} — best: ${best_composite:.1f}/mo")` has no ticker context. In sequential mode this is fine (only one ticker runs at a time). In parallel mode, 8 tickers' combo progress interleaves and you can't tell which is which. Adding `ticker` as a prefix (e.g., `f"{ticker}: level combo..."`) is a 1-line change inside `sweep_levels()` but changes the log format for sequential mode too.
