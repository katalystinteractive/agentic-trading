# Analysis: Level Filter Gaps + Neural Sweep Progress Logging

**Date**: 2026-03-31 (Tuesday)
**Purpose**: Address 6 verified gaps from the level filter integration review AND add progress/quality logging to all neural network sweep tools.

**Honesty note**: Every claim labeled FACT (verified) or PROPOSED.

---

## Part A: Level Filter Integration Gaps (6 findings, all verified)

### A1. Backtest baseline min_hold_rate=15 vs live no-filter (B1)

**FACT** (verified): `backtest_config.py:148` defaults `min_hold_rate=15`. `backtest_engine.py:558` unconditionally applies `if hr < cfg.min_hold_rate: continue` to active bullets. The live path `_passes_level_filters()` returns `True` immediately when `filters is None` (line 131). For non-swept tickers, live applies zero hold rate filtering while the backtest always applies 15%.

**FACT**: The 15% threshold is below the Half tier minimum (15%), so the only levels it would catch are those with hold_rate exactly 0-14% that somehow have effective_tier != Skip. In practice, the tier system at lines 571-573 already excludes `effective_tier == "Skip"`, which covers hold rates below the Half threshold. The divergence is real but rarely binding.

**PROPOSED fix**: No code change. The tier gate (Skip exclusion) makes this functionally equivalent. Document as known acceptable divergence.

### A2. All-exception combos produce a winner (C3)

**FACT** (verified): When every `_simulate_with_config` raises an exception inside `sweep_levels()`, all periods get `{"pnl": 0, "cycles": 0}`. `compute_composite()` returns 0. Since `best_composite` starts at `float("-inf")`, 0 > -inf is true and the all-exception combo becomes the "winner."

**FACT**: This same pattern exists in `sweep_threshold()` (line 222-226). It is the established convention.

**PROPOSED fix**: Initialize `best_composite = 0` instead of `float("-inf")` in all three sweep functions:
- `sweep_levels()` line 314: `best_composite = float("-inf")` → `best_composite = 0`
- `sweep_threshold()` line 182: `best_composite = float("-inf")` → `best_composite = 0`
- `sweep_execution()` line 247: `best_pnl = float("-inf")` → `best_pnl = 0`

This requires at least one combo to produce positive results to be accepted as a winner. Returns None when no combo improves over baseline.

### A3. No test for dormant sort with skip_dormant=False (D1)

**FACT** (verified): `test_skip_dormant_filters_both_zones` tests skip_dormant=True only. No test verifies that dormant levels sort last (line 626: `sort(key=lambda r: (r.get("dormant", False), ...))`) when filters allow them through.

**PROPOSED fix**: Add test `test_dormant_sorts_last_when_not_skipped` — create 2 Active levels (one dormant=True, one dormant=False), pass `level_filters={"skip_dormant": False}`, verify dormant level appears second in the active list.

### A4. No test for _load_level_filters (D2)

**FACT** (verified): Zero test coverage for the file-loading, caching, and key-lookup logic.

**PROPOSED fix**: Add `TestLoadLevelFilters` class with tests:
1. `test_returns_none_when_file_missing` — no file exists, returns None
2. `test_returns_params_for_known_ticker` — write temp JSON, verify correct params returned
3. `test_returns_none_for_unknown_ticker` — file exists but ticker not in it
4. `test_cache_reuses_data` — call twice, verify file read only once (mock or mtime check)

Use `tmp_path` pytest fixture to create temp JSON files.

### A5. No test for decayed_hold_rate fallback (D3)

**FACT** (verified): `_make_level()` always sets `decayed_hold_rate = hold_rate`. No test where they differ.

**PROPOSED fix**: Add test `test_min_hold_rate_uses_decayed_over_raw` — create Active level with `hold_rate=60, decayed_hold_rate=30`, apply `min_hold_rate=50`. Verify level is FILTERED (30 < 50) even though raw hold_rate=60 would pass. This confirms `_passes_level_filters` prefers `decayed_hold_rate`.

### A6. No test for zone_filter="all" (D4)

**FACT** (verified): Only `zone_filter="active"` is tested. The "all" value (default, no-op for reserve inclusion) has no explicit test.

**PROPOSED fix**: Add test `test_zone_filter_all_keeps_reserve` — create Active + Reserve levels, pass `level_filters={"zone_filter": "all"}`, verify both active and reserve lists are populated.

---

## Part B: Neural Sweep Progress Logging

### B1. Current State (FACT — verified across 6 tools)

| Tool | Per-Ticker | Per-Combo | Error Visibility | Timing |
| :--- | :--- | :--- | :--- | :--- |
| support_parameter_sweeper | Final result only | None | Silent swallow (3 places) | End-of-run only |
| parameter_sweeper | Final result only | None | Silent (2 places) | End-of-run only |
| neural_support_discoverer | Result + some errors | None | Catches execution | End-of-run only |
| neural_candidate_discoverer | Every 100 tickers | None | Catches download only | End-of-run only |
| neural_watchlist_sweeper | Result + errors | None | Catches sweep | End-of-run only |
| weekly_reoptimize | Per-step summary | None | Catches steps | Per-step timing |

### B2. What's Missing

1. **Combo-level progress within tickers**: When sweeping 100+ combos per ticker, no indication which combo we're on. A 5-minute ticker sweep looks identical to a hung process.

2. **Silent exception swallowing**: `support_parameter_sweeper.py` has 5 silent exception handlers:
   - Line 218: `sweep_threshold` multi-period sim failure → `{"pnl": 0, "cycles": 0}`
   - Lines 223-224: `sweep_threshold` composite computation failure → `composite = 0`
   - Line 279: `sweep_execution` sim failure → `continue` (skips combo silently)
   - Line 360: `sweep_levels` multi-period sim failure → `{"pnl": 0, "cycles": 0}`
   - Lines 363-365: `sweep_levels` composite computation failure → `composite = 0`
   Cannot distinguish legitimate 0-P/L from crashed simulations. `parameter_sweeper.py` has 2 equally silent handlers (lines 92, 139 — both `continue`).

3. **Per-ticker timing**: No way to detect which tickers are slow. Critical for identifying problematic tickers that inflate sweep time.

4. **Period failure tracking**: Multi-period sweeps (12mo/6mo/3mo/1mo) silently fallback to 0 when individual periods fail. No reporting of which periods succeeded vs failed for each combo.

5. **neural_candidate_discoverer visibility gap**: Main sweep loop processes 300+ tickers with output only every 100. A 60-minute run gives ~3 progress updates.

6. **Quality metrics during sweep**: No reporting of catastrophic stops, zero-trade combos, or negative P/L combos during the sweep. Quality only visible in final results.

### B3. Proposed Logging Architecture (PROPOSED)

**Design principle**: Progress logging goes to stderr (so stdout piping/capture is unaffected). Use a shared helper function for consistent format.

#### B3.1 Shared progress logger

```python
# In support_parameter_sweeper.py (or shared_utils.py if multiple tools need it)
import sys
import time

def _log_progress(msg, file=sys.stderr):
    """Print timestamped progress to stderr."""
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}", file=file, flush=True)
```

#### B3.2 Per-ticker timing wrapper

For each sweep function, wrap the per-ticker call with timing:

```python
t0 = time.time()
best_params, best_result, composite, periods = sweep_levels(...)
elapsed = time.time() - t0
_log_progress(f"{tk}: {elapsed:.0f}s — composite=${composite:.1f}/mo")
```

#### B3.3 Combo-level progress (configurable granularity)

Inside sweep functions, log progress at configurable intervals:

```python
total_combos = len(list(itertools.product(...)))
for i, (min_hr, min_tf, ...) in enumerate(itertools.product(...)):
    ...
    if (i + 1) % 25 == 0 or (i + 1) == total_combos:
        _log_progress(f"  combo {i+1}/{total_combos} — best so far: ${best_composite:.1f}/mo")
```

**Granularity**: Every 25 combos for 100-combo sweeps (4 updates). Every 50 for 600-combo sweeps (~12 updates). Keeps output manageable.

#### B3.4 Exception counting instead of silent swallow

Replace silent swallow with counted errors:

```python
# Before (silent):
except Exception:
    results_by_period[period_months] = {"pnl": 0, "cycles": 0}

# After (counted):
except Exception as e:
    results_by_period[period_months] = {"pnl": 0, "cycles": 0}
    sim_errors += 1
    if sim_errors <= 3:  # log first 3 errors per ticker
        _log_progress(f"  period {period_months}mo failed: {type(e).__name__}: {e}")
```

After sweep completes, report summary:
```python
if sim_errors > 0:
    _log_progress(f"  {sim_errors} simulation errors across {total_combos} combos")
```

#### B3.5 Quality metrics in sweep output

Add quality counters to sweep functions:

```python
quality = {"zero_trade": 0, "negative": 0, "catastrophic": 0, "positive": 0}
for combo in combos:
    ...
    if result["sells"] == 0:
        quality["zero_trade"] += 1
    elif result["pnl"] < 0:
        quality["negative"] += 1
    elif result.get("catastrophic", 0) > 0:
        quality["catastrophic"] += 1
    else:
        quality["positive"] += 1
```

Report at end of ticker sweep:
```python
_log_progress(f"  quality: {quality['positive']} profitable, {quality['negative']} negative, "
              f"{quality['zero_trade']} zero-trade, {quality['catastrophic']} catastrophic")
```

### B4. Files Affected

| Tool File | Changes |
| :--- | :--- |
| `tools/support_parameter_sweeper.py` | Add `_log_progress()`, combo progress in sweep_threshold/execution/levels, exception counting, per-ticker timing in main(), quality metrics |
| `tools/parameter_sweeper.py` | Combo progress in sweep_ticker(), exception counting, per-ticker timing |
| `tools/neural_support_discoverer.py` | Per-ticker timing, combo progress delegated to sweeper |
| `tools/neural_candidate_discoverer.py` | Change from every-100 to every-10 progress, per-ticker timing |
| `tools/neural_watchlist_sweeper.py` | Per-ticker timing, exception detail |
| `tools/weekly_reoptimize.py` | Per-step timing already exists — add step quality summary |

### B5. Backward Compatibility

All logging goes to stderr. Existing stdout output (tables, summaries) is unchanged. Tools that capture stdout via subprocess (weekly_reoptimize, daily_analyzer) see no difference. Progress logging is always-on (no --verbose flag needed — these are long-running batch tools where progress info is always valuable).

---

## Part C: Combined Scope

### Test additions (Part A)

| Test | Lines |
| :--- | :--- |
| `test_dormant_sorts_last_when_not_skipped` | ~8 |
| `TestLoadLevelFilters` (4 tests with tmp_path) | ~40 |
| `test_min_hold_rate_uses_decayed_over_raw` | ~6 |
| `test_zone_filter_all_keeps_reserve` | ~8 |
| **Test total** | **~62** |

### Code fixes (Part A)

| Fix | Lines |
| :--- | :--- |
| `best_composite = 0` in sweep_levels + sweep_threshold, `best_pnl = 0` in sweep_execution | ~3 |
| **Code fix total** | **~3** |

### Progress logging (Part B)

| File | Est. Lines |
| :--- | :--- |
| support_parameter_sweeper.py | ~40 |
| parameter_sweeper.py | ~20 |
| neural_candidate_discoverer.py | ~10 |
| neural_watchlist_sweeper.py | ~10 |
| neural_support_discoverer.py | ~10 |
| weekly_reoptimize.py | ~5 |
| **Logging total** | **~95** |

### Grand total: ~159 lines across 7 files + 1 test file
