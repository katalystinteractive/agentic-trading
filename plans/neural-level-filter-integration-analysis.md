# Analysis: Integrating Level Filter Findings into Live Tools

**Date**: 2026-03-31 (Tuesday, 12:35 AM local / 5:35 PM ET Monday)
**Purpose**: The level filter sweep produces per-ticker optimal filters in `data/sweep_support_levels.json`, but neither `wick_offset_analyzer.py` nor `bullet_recommender.py` reads that file. Level filter findings need to flow into the live tools that produce actual order recommendations.

**Honesty note**: Every claim labeled FACT (verified) or PROPOSED.

---

## 1. Current Gap (FACT — verified)

**FACT**: The level filter sweep runs inside `backtest_engine.py` during simulation. The filters are applied asymmetrically: active bullets (lines 558-569) get all four filters (`min_hold_rate`, `min_touch_freq`, `skip_dormant`, `zone_filter`), while reserve bullets (lines 587-593) get only `min_touch_freq` and `skip_dormant`. This asymmetry is by design — `zone_filter="active"` already excludes reserve entirely, and `min_hold_rate` is only needed for active where tiers are more permissive.

**FACT**: The LIVE bullet plan is produced by `wick_offset_analyzer.py::_compute_bullet_plan()` at line 559. This function selects:
- Active candidates: `zone == "Active"` AND `effective_tier != "Skip"` (lines 571-573)
- Reserve candidates: `zone == "Reserve"` AND `effective_tier in ("Full", "Std")` (lines 578-580)

**FACT**: `_compute_bullet_plan()` does NOT check `min_touch_freq`, `skip_dormant`, or `zone_filter`. These filters only exist in the backtest path.

**FACT**: `bullet_recommender.py` calls `analyze_stock_data()` (line 1112) which calls `_compute_bullet_plan()` (line 870). The recommender gets the unfiltered bullet plan and produces order recommendations from ALL qualifying levels.

**Result**: The neural network discovers "CIFR should only trade Active zone" but the bullet recommender still recommends Reserve levels for CIFR.

---

## 2. Integration Point (FACT — verified)

The single integration point is `_compute_bullet_plan()` in `wick_offset_analyzer.py` (line 559).

**FACT**: This function receives 3 parameters: `level_results`, `current_price`, `cap` (capital config). It does NOT receive any level filter config.

**FACT**: This function is called from ONE place: `analyze_stock_data()` at line 870.

**FACT**: `analyze_stock_data()` receives `ticker` as its first parameter (line 652 of the function signature). The ticker is available to look up level filter profiles.

**Call chain**:
```
bullet_recommender.py → analyze_stock_data(ticker, ...) → _compute_bullet_plan(level_results, price, cap)
                                                           ↑ ticker available here
                                                           ↑ can load level filter profile for this ticker
```

---

## 3. What Must Change (PROPOSED)

### 3.1 Load level filter profile in `_compute_bullet_plan()`

Add an optional `level_filters` parameter:

```python
def _compute_bullet_plan(level_results, current_price, cap=None, level_filters=None):
```

If `level_filters` is provided, apply the filters when selecting candidates:

```python
# Current active selection (line 571-572):
active_candidates = [r for r in level_results
                     if r["zone"] == "Active" and r["effective_tier"] != "Skip"
                     and r["recommended_buy"] and r["recommended_buy"] < current_price]

# With level filters:
active_candidates = [r for r in level_results
                     if r["zone"] == "Active" and r["effective_tier"] != "Skip"
                     and r["recommended_buy"] and r["recommended_buy"] < current_price
                     and _passes_level_filters(r, level_filters)]
```

Where `_passes_level_filters()` checks (zone-aware to match backtest asymmetry):
```python
def _passes_level_filters(r, filters):
    if not filters:
        return True
    zone = r.get("zone", "")
    # min_hold_rate: Active only (backtest applies this at lines 557-559 in active loop only)
    if zone == "Active" and filters.get("min_hold_rate", 0) > 0:
        hr = r.get("decayed_hold_rate", r.get("hold_rate", 0))
        if hr < filters["min_hold_rate"]:
            return False
    # min_touch_freq: both Active and Reserve (backtest applies to both loops)
    if filters.get("min_touch_freq", 0) > 0:
        if r.get("monthly_touch_freq", 0) < filters["min_touch_freq"]:
            return False
    # skip_dormant: both Active and Reserve (backtest applies to both loops)
    if filters.get("skip_dormant") and r.get("dormant", False):
        return False
    return True
```

### 3.2 Pass level filters from `analyze_stock_data()`

Load the per-ticker level filter profile at the `analyze_stock_data()` level and pass to `_compute_bullet_plan()`:

```python
# In analyze_stock_data(), before calling _compute_bullet_plan():
level_filters = _load_level_filters(ticker)

"bullet_plan": _compute_bullet_plan(level_results, current_price,
                                     capital_config or load_capital_config(),
                                     level_filters=level_filters),
```

Where `_load_level_filters()` reads from `data/sweep_support_levels.json`:

```python
def _load_level_filters(ticker):
    """Load per-ticker level filter profile from neural sweep results."""
    try:
        lf_path = Path(__file__).resolve().parent.parent / "data" / "sweep_support_levels.json"
        if lf_path.exists():
            with open(lf_path) as f:
                data = json.load(f)
            entry = data.get(ticker, {})
            return entry.get("level_params")  # PROPOSED key — must match Stage 3 write schema
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return None
```

**Schema coordination**: The key `"level_params"` is a PROPOSED schema choice. When Stage 3's `sweep_levels()` is wired to write `LEVEL_RESULTS_PATH`, it must use this key to wrap the per-ticker filter dict (`min_hold_rate`, `min_touch_freq`, `skip_dormant`, `zone_filter`). If Stage 3 uses a different key (e.g., `"params"`), `_load_level_filters()` will silently return `None` and no filtering occurs. This must be coordinated during implementation.

### 3.3 Zone filter and reserve level filtering

**FACT** (verified): `_compute_bullet_plan()` already separates Active and Reserve candidates at lines 571-573 and 578-580. The `zone_filter` from the neural sweep determines whether Reserve candidates are included.

When `zone_filter == "active"`: skip the Reserve candidate selection entirely.
When `zone_filter == "all"`: apply `_passes_level_filters()` to reserve candidates too (matching backtest behavior where `min_touch_freq` and `skip_dormant` are applied to reserve bullets at lines 587-593).

```python
if level_filters and level_filters.get("zone_filter") == "active":
    reserve_candidates = []  # skip Reserve entirely
else:
    reserve_candidates = [r for r in level_results
                          if r["zone"] == "Reserve" ...
                          and _passes_level_filters(r, level_filters)]
```

---

## 4. Backward Compatibility

**`level_filters=None` default**: When no level filter file exists or the ticker has no profile, `_passes_level_filters()` returns `True` for all levels. Behavior is identical to current code.

**Prerequisite**: `data/sweep_support_levels.json` must be generated by running `support_parameter_sweeper.py` Stage 3 level filter sweep before these filters take effect. **Note**: Stage 3 requires TWO implementation steps: (1) wire `--stage level` into the CLI choices in `main()`, and (2) add write logic that calls `sweep_levels()` and writes results to `LEVEL_RESULTS_PATH` — currently `LEVEL_RESULTS_PATH` is defined but no code writes to it. The write block must use the `"level_params"` key to match `_load_level_filters()`. Until the file exists, `_load_level_filters()` returns `None` and all levels pass through unfiltered (identical to current behavior).

**`bullet_recommender.py`**: No changes needed. It calls `analyze_stock_data()` which handles the filter loading internally. The recommender gets a filtered bullet plan transparently.

**`backtest_engine.py`**: No changes needed. It has its OWN filter logic (from the sweep config fields). The wick analyzer's filter and the backtest engine's filter are independent — the wick analyzer filters the live bullet plan, the backtest engine filters during simulation. They should converge to the same result since both use the same neural profile.

---

## 5. Data Flow After Integration

```
sweep_support_levels.json (per-ticker level filter profiles)
     ↓ read by
wick_offset_analyzer.py::_load_level_filters(ticker)
     ↓ passed to
_compute_bullet_plan(level_results, price, cap, level_filters)
     ↓ filtered bullet plan
analyze_stock_data() returns filtered results
     ↓ consumed by
bullet_recommender.py → order recommendations (only worthwhile levels)
daily_analyzer.py → display (only worthwhile levels shown)
broker_reconciliation.py → sell/buy actions (only worthwhile levels)
```

---

## 6. Files

| File | Change | Lines |
| :--- | :--- | :--- |
| `tools/wick_offset_analyzer.py` | Add `_load_level_filters()`, `_passes_level_filters()`, pass to `_compute_bullet_plan()` | ~33 |
| `tests/test_wick_offset_analyzer.py` | Add test cases for level filter behavior (filtered active, filtered reserve, zone_filter="active", no-filter default) | ~20 |
| **Total** | | **~53** |

**NOT modified**: `bullet_recommender.py` (inherits filtered plan), `daily_analyzer.py` (inherits), `broker_reconciliation.py` (inherits), `backtest_engine.py` (has its own filter path)

**Design note**: `_compute_bullet_plan()` already sorts active candidates with `dormant` levels pushed to end (line 575). The proposed `skip_dormant` filter removes dormant levels before sorting, making the sort position moot for those levels. These interact correctly — filter-then-sort is the natural order.

---

## 7. Open Questions

1. **Should `_load_level_filters()` cache the file read?** It's called once per `analyze_stock_data()` invocation, which is once per ticker. At 27 watchlist tickers, that's 27 file reads of the same JSON. A module-level cache with mtime check (like `_load_mp_data()` in `shared_utils.py`) would be more efficient.

2. **What if level filters remove ALL levels?** If `min_hold_rate=70` and no level has 70%+ hold rate, `active_candidates` would be empty. The bullet plan returns empty lists, and `bullet_recommender.py` shows "No levels available." This is correct behavior — the neural network determined no level is worth trading for this ticker at these thresholds.
