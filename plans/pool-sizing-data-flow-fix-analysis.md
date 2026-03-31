# Analysis: Pool Sizing Data Flow Fix

**Date**: 2026-03-31 (Tuesday)
**Purpose**: The neural watchlist sweeper only runs Stage 1 (threshold), so NO watchlist ticker gets optimized pool sizing. Every ticker defaults to $300/$300 despite having sweep data showing optimal pools of $200-$500. Three issues exposed.

---

## Issue 1: `neural_watchlist_sweeper.py` skips Stage 2 (FACT — verified)

**FACT**: `neural_watchlist_sweeper.py` line 92 calls `sweep_threshold(tk)` which returns `(params, result, composite, periods)`. The `params` dict only contains `sell_default` and `cat_hard_stop` — no pool/bullet params.

**FACT**: `sweep_execution(tk, threshold_params, months)` (Stage 2) optimizes `active_pool`, `reserve_pool`, `active_bullets_max`, `reserve_bullets_max`, `tier_full`, `tier_std` across 144 combos. This is never called by the watchlist sweeper.

**FACT**: When run via `support_parameter_sweeper.py --stage both`, Stage 2 runs on the top 10 profitable tickers and merges execution params into `results[tk]["params"]` (line 706). The watchlist sweeper duplicates Stage 1 but not Stage 2.

**Result**: All 27 watchlist tickers in `neural_watchlist_profiles.json` have params like `{"sell_default": 7.0, "cat_hard_stop": 15}` — no `active_pool`, no `active_bullets_max`. When `get_ticker_pool()` reads this file, `params.get("active_pool", 300)` returns the default 300.

**PROPOSED fix**: After Stage 1 completes in the watchlist sweeper, run Stage 2 on each profitable ticker. The sequential loop (line 88-114) already has `params` and `result` — add a `sweep_execution()` call and merge the returned execution params.

---

## Issue 2: `support_sweep_results.json` is never read by the pool chain (FACT — verified)

**FACT**: `support_parameter_sweeper.py --stage both` writes complete results (threshold + execution params) to `data/support_sweep_results.json`. This file has the correct `active_pool`, `active_bullets_max`, etc. for every swept ticker.

**FACT**: `get_ticker_pool()` in `shared_utils.py` does NOT read `support_sweep_results.json`. Its priority chain is:
1. `multi-period-results.json` (line 71)
2. `neural_watchlist_profiles.json` (line 84)
3. `neural_support_candidates.json` (line 106)
4. `portfolio.json` (line 126)
5. Hardcoded $300 (line 138)

**Result**: Even when `support_sweep_results.json` has `active_pool: 500` for a ticker, the pool chain never sees it. The data exists but is stranded.

**PROPOSED fix**: Two options:
- **Option A**: Make the watchlist sweeper write the correct params (Issue 1 fix) so `neural_watchlist_profiles.json` has pool data. This is the cleaner fix — one source of truth.
- **Option B**: Add `support_sweep_results.json` to the `get_ticker_pool()` priority chain. This adds complexity and another file to maintain.

**Recommendation**: Option A. Fix the source (watchlist sweeper), not the consumer.

---

## Issue 3: `active_bullets_max` not sourced from neural profiles (FACT — verified)

**FACT**: `load_capital_config()` in `wick_offset_analyzer.py` (line 64-68) gets `active_pool`/`reserve_pool` from `get_ticker_pool()`, but gets `active_bullets_max`/`reserve_bullets_max` from `portfolio.json` capital section (static defaults: 5 active, 3 reserve).

**FACT**: Lines 70-82 attempt a fallback to `neural_support_candidates.json` for bullet overrides, but this only works for tickers in the support candidate file — not watchlist tickers.

**FACT**: The neural sweep determines optimal bullet counts (3, 5, or 7) per ticker. STIM's sweep found 7 active bullets optimal. But `load_capital_config("STIM")` returns `active_bullets_max: 5` (portfolio.json default).

**PROPOSED fix**: `get_ticker_pool()` should also return `active_bullets_max` and `reserve_bullets_max` when available from the neural profile. `load_capital_config()` should use these instead of the static portfolio.json defaults.

---

## Root Cause Summary

The neural sweep pipeline has two separate paths that don't converge:

```
Path A (weekly cron):
  neural_watchlist_sweeper.py → Stage 1 only → neural_watchlist_profiles.json (incomplete)

Path B (manual/ad-hoc):
  support_parameter_sweeper.py --stage both → Stage 1+2 → support_sweep_results.json (complete but unused)
```

The fix is to make Path A include Stage 2, so the weekly cron produces complete profiles.

---

## Proposed Changes

### Change 1: `neural_watchlist_sweeper.py` — add Stage 2

After `sweep_threshold()` returns profitable params, call `sweep_execution()` to optimize pool/bullets. Merge execution params into the result.

**Sequential path** (line 88-114):
```python
params, result, composite, periods = sweep_threshold(tk)
if params and result:
    # NEW: Stage 2 — optimize pool/bullets with thresholds locked
    exec_params, exec_result = sweep_execution(tk, params, train_months)
    if exec_params:
        params = exec_params  # merged threshold + execution
        result = exec_result  # use execution result for stats
    ...
```

**Parallel path** (line 73-86): The `_sweep_threshold_worker` lives in `support_parameter_sweeper.py` (line 505), imported by the watchlist sweeper at line 71. Two options:
- Create a new `_sweep_both_worker` in `neural_watchlist_sweeper.py` that calls both `sweep_threshold` + `sweep_execution`
- Or: run Stage 1 in parallel, then Stage 2 sequentially on profitable results (matching main sweeper pattern — simpler, no new worker needed)

**Impact on runtime**: Stage 2 runs 144 combos per ticker (~30-60s each). At 27 tickers, adds ~15-25 min to the weekly sweeper run (currently ~25 min for Stage 1). Total ~50 min — acceptable for weekly cron.

### Change 2: `get_ticker_pool()` — return bullet counts

When reading from any neural profile source, also extract and return `active_bullets_max` and `reserve_bullets_max` if present.

```python
return {
    "active_pool": ap,
    "reserve_pool": rp,
    "total_pool": ap + rp,
    "active_bullets_max": params.get("active_bullets_max"),  # NEW
    "reserve_bullets_max": params.get("reserve_bullets_max"),  # NEW
    "source": "neural_watchlist",
    "composite": ...,
}
```

### Change 3: `load_capital_config()` — use neural bullet counts

In `wick_offset_analyzer.py`, after calling `get_ticker_pool()`, use the returned bullet counts if available:

```python
pool = get_ticker_pool(ticker)
result = {
    "active_pool": pool["active_pool"],
    "reserve_pool": pool["reserve_pool"],
    "active_bullets_max": pool.get("active_bullets_max") or cap.get("active_bullets_max", 5),
    "reserve_bullets_max": pool.get("reserve_bullets_max") or cap.get("reserve_bullets_max", 3),
}
```

---

## Files

| File | Change | Est. Lines |
| :--- | :--- | :--- |
| `tools/neural_watchlist_sweeper.py` | Add Stage 2 call after Stage 1, merge params | ~15 |
| `tools/shared_utils.py` | Return bullet counts from `get_ticker_pool()` | ~6 |
| `tools/wick_offset_analyzer.py` | Use neural bullet counts in `load_capital_config()` | ~4 |
| **Total** | | **~25** |

---

## Additional Consumers

**FACT** (verified): `graph_builder.py` line 334 calls `get_ticker_pool(t)` directly. Line 184 reads `neural_watchlist_profiles.json` for neural profiles. The daily analyzer displays pool data via graph nodes (lines 1565-1574). Both are indirect consumers of the pool chain and will automatically benefit from the fix — no changes needed in these files since they read through `get_ticker_pool()`.

**FACT**: `bullet_recommender.py` line 223 calls `load_capital_config(ticker)` — the primary consumer. Covered by the proposed Change 3.

---

## Downstream Impact

Once fixed, ALL 27 watchlist tickers will have:
- Neural-optimized pool sizes ($200-$500 instead of flat $300)
- Neural-optimized bullet counts (3/5/7 instead of flat 5)
- Neural-optimized sell targets (already working)
- Neural-optimized level filters (already working)

The weekly cron run will produce complete profiles automatically. No manual intervention needed.
