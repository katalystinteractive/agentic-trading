# Implementation Plan: Neural Level Optimization

**Date**: 2026-03-31
**Source analysis**: `plans/neural-level-optimization-analysis.md` (verified, 5 iterations, 13 fixes, converged)
**Goal**: Neural network learns which support levels are worth deploying capital at — sweep min_hold_rate, touch frequency, dormancy, and zone filter per ticker.

---

## Scope

4 steps, ~71 lines across 4 files. Level filter results saved to a NEW separate file — no existing data overwritten.

| Step | What | File | Type | Lines |
| :--- | :--- | :--- | :--- | :--- |
| 1 | Add level filter fields to SurgicalSimConfig | `backtest_config.py` | MODIFY | ~6 |
| 2 | Add level filtering in backtest_engine.py | `backtest_engine.py` | MODIFY | ~15 |
| 3 | Add Stage 3 level filter sweep | `support_parameter_sweeper.py` | MODIFY | ~40 |
| 4 | Fix weight stats overwrite | `weight_learner.py` | MODIFY | ~10 |

**Output**: `data/sweep_support_levels.json` (NEW file — never overwrites threshold or execution results)

**NOT modified**: `wick_offset_analyzer.py` (fields already exist), `neural_dip_evaluator.py`, `daily_analyzer.py`, `graph_builder.py`

---

## Step 1: Add Level Filter Fields to SurgicalSimConfig

**Where**: `tools/backtest_config.py`, inside `SurgicalSimConfig` class after existing `min_hold_rate: int = 15` (line 148).

```python
# Level filter parameters (NEW — Stage 3 sweep)
min_touch_freq: float = 0.0     # skip levels touched less than X/month (0 = no filter)
skip_dormant: bool = False      # skip levels flagged as dormant (>90 days untested)
zone_filter: str = "all"        # "active" (Active only) or "all" (Active + Reserve)
```

**FACT** (verified): `min_hold_rate: int = 15` already exists at line 148. NOT adding it — only adding the 3 new fields.

**Backward compat**: Defaults match current behavior (no filtering beyond existing).

---

## Step 2: Add Level Filtering in backtest_engine.py

**Where**: After existing tier + hold_rate filters at lines 554-558, before `active_bullets_max` cap at line 560.

```python
# Existing filters (lines 554-558):
tier = bullet.get("effective_tier", bullet.get("tier", "Skip"))
if tier == "Skip":
    continue
hr = bullet.get("decayed_hold_rate", bullet.get("hold_rate", 0))
if hr < cfg.min_hold_rate:
    continue

# NEW filters (insert here, before active_bullets_max cap):
if cfg.min_touch_freq > 0:
    tf = bullet.get("monthly_touch_freq", 0)
    if tf < cfg.min_touch_freq:
        continue
if cfg.skip_dormant and bullet.get("dormant", False):
    continue
if cfg.zone_filter == "active":
    if bullet.get("zone", "") != "Active":
        continue
# NOTE: "all" = Active + Reserve (no Buffer in bullet plans)
# zone_filter only distinguishes "active" (Active only) vs "all" (Active + Reserve)

# Existing cap (line 560):
if cap.active_bullets >= cfg.active_bullets_max:
    break
```

**Also**: Add same 3 new filters for reserve bullets. NOTE: The reserve section (lines 574-582) has a SIMPLER filter than active — it checks tier (Skip excluded, only Full/Std allowed) but does NOT check `min_hold_rate`. Insert the new filters after the tier check at line 575.

**FACT** (verified): `monthly_touch_freq` and `dormant` already exist in the bullet plan dict. Zone values are always title-case: `"Active"` or `"Reserve"` (from `_bullet_entry()` line 623). Use title-case in comparisons.

**FACT** (verified): Buffer zone levels exist in wick analysis classification (98 levels across all tickers) but are NEVER included in bullet plans. `_compute_bullet_plan()` at line 572 only selects `zone == "Active"` and line 578 only selects `zone == "Reserve"`. Buffer levels are classified but excluded from trading. The `zone_filter` sweep option therefore only distinguishes between "Active only" vs "Active + Reserve" (not "Active + Buffer").

---

## Step 3: Add Stage 3 Level Filter Sweep

**Where**: `tools/support_parameter_sweeper.py`, after existing Stage 2 execution sweep.

### 3.1 Add level filter grid constant

```python
LEVEL_FILTER_GRID = {
    "min_hold_rate": [15, 30, 50, 60, 70],
    "min_touch_freq": [0, 0.5, 1.0, 2.0, 3.0],
    "skip_dormant": [False, True],
    "zone_filter": ["active", "all"],  # no Buffer in bullet plans
}
# 5 × 5 × 2 × 2 = 100 combos per ticker
```

### 3.2 Add `sweep_levels()` function

```python
def sweep_levels(ticker, threshold_params, execution_params=None, months=10):
    """Stage 3: Sweep level filters with thresholds + execution params locked."""
    data_dir = _collect_once(ticker, max(SWEEP_PERIODS))
    from backtest_engine import load_collected_data
    price_data, regime_data, _ = load_collected_data(data_dir)

    best_pnl = float("-inf")
    best_params = None
    best_result = None

    # Build base overrides from locked threshold + execution params
    base_overrides = {
        "sell_default": threshold_params["sell_default"],
        "sell_fast_cycler": threshold_params["sell_default"] + 2.0,
        "sell_exceptional": threshold_params["sell_default"] + 4.0,
        "cat_hard_stop": threshold_params["cat_hard_stop"],
        "cat_warning": max(threshold_params["cat_hard_stop"] - 10, 5),
    }
    if execution_params:
        base_overrides.update(execution_params)

    for min_hr, min_tf, skip_dorm, zone_f in itertools.product(
            LEVEL_FILTER_GRID["min_hold_rate"],
            LEVEL_FILTER_GRID["min_touch_freq"],
            LEVEL_FILTER_GRID["skip_dormant"],
            LEVEL_FILTER_GRID["zone_filter"]):

        overrides = {**base_overrides,
                     "min_hold_rate": min_hr,
                     "min_touch_freq": min_tf,
                     "skip_dormant": skip_dorm,
                     "zone_filter": zone_f}

        # Use period from threshold sweep (same start/end dates)
        period_wick_cache = {}
        try:
            result = _simulate_with_config(
                ticker, months, overrides, data_dir,
                price_data, regime_data, period_wick_cache)
        except Exception:
            continue

        pnl = result.get("pnl", 0)
        if pnl > best_pnl:
            best_pnl = pnl
            best_params = {
                "min_hold_rate": min_hr,
                "min_touch_freq": min_tf,
                "skip_dormant": skip_dorm,
                "zone_filter": zone_f,
            }
            best_result = result

    return best_params, best_result
```

### 3.3 Write to separate output file

```python
LEVEL_RESULTS_PATH = _ROOT / "data" / "sweep_support_levels.json"

# After sweep, write results:
output = {
    "_meta": {
        "source": "support_parameter_sweeper.py (Stage 3)",
        "updated": date.today().isoformat(),
        "grid_size": 100,
    }
}
for tk, r in results.items():
    output[tk] = {
        "level_params": r["params"],
        "stats": r["stats"],
    }

with open(LEVEL_RESULTS_PATH, "w") as f:
    json.dump(output, f, indent=2)
```

**Data preservation**: Writes to `data/sweep_support_levels.json` — does NOT overwrite `data/support_sweep_results.json` (Stage 1+2 results).

### 3.4 Wire into main() and discoverer

Add `--stage level` option to CLI:
```python
parser.add_argument("--stage", choices=["threshold", "execution", "level", "both"],
                    default="both")
```

When `--stage level`: read threshold params from existing results, run `sweep_levels()` on top tickers.

---

## Step 4: Fix Weight Stats Overwrite

**Where**: `tools/weight_learner.py`, `save_weights()` function.

**Current** (line 157): `data["_meta"]["stats"] = stats` — overwrites previous stats entirely.

**Fix**: Track stats per source:
```python
# Instead of overwriting:
if "stats_by_source" not in data["_meta"]:
    data["_meta"]["stats_by_source"] = {}
source = stats.get("source", "unknown")
data["_meta"]["stats_by_source"][source] = stats
data["_meta"]["stats"] = stats  # keep backward compat — last run also in top-level
```

This preserves stats from both `weight_learner` (dip trades) and `historical_trade_trainer` (support trades).

---

## Verification

### After Step 1-2:
```bash
python3 -c "
from tools.backtest_config import SurgicalSimConfig
cfg = SurgicalSimConfig(min_touch_freq=1.0, skip_dormant=True, zone_filter='active')
print(f'touch: {cfg.min_touch_freq}, dormant: {cfg.skip_dormant}, zone: {cfg.zone_filter}')
# Verify defaults
cfg2 = SurgicalSimConfig()
print(f'defaults: touch={cfg2.min_touch_freq}, dormant={cfg2.skip_dormant}, zone={cfg2.zone_filter}')
"
```

### After Step 3:
```bash
python3 tools/support_parameter_sweeper.py --ticker CIFR --stage level
# Verify: sweep_support_levels.json created
# Verify: support_sweep_results.json NOT overwritten
# Verify: output shows optimal min_hold_rate/touch_freq/zone per ticker
```

### After Step 4:
```bash
python3 tools/historical_trade_trainer.py --epochs 5
python3 tools/weight_learner.py --epochs 3
python3 -c "
import json
with open('data/synapse_weights.json') as f:
    data = json.load(f)
print(data['_meta'].get('stats_by_source', {}).keys())
# Should show both 'historical_trade_trainer' and 'weight_learner'
"
```

---

## Files Summary

| File | Action | Lines |
| :--- | :--- | :--- |
| `tools/backtest_config.py` | Add 3 new fields to SurgicalSimConfig | ~6 |
| `tools/backtest_engine.py` | Add 3 new filters after existing tier+hold_rate checks (active + reserve) | ~15 |
| `tools/support_parameter_sweeper.py` | Add LEVEL_FILTER_GRID, sweep_levels(), Stage 3 output to separate file | ~40 |
| `tools/weight_learner.py` | Track stats per source in _meta.stats_by_source | ~10 |
| **Total** | | **~71** |

**Output files** (NEW — never overwrite existing):
- `data/sweep_support_levels.json` — per-ticker level filter profiles

**Frozen files** (zero modifications):
- `wick_offset_analyzer.py` — fields already exist
- `neural_dip_evaluator.py` — dip strategy untouched
- `daily_analyzer.py` — level filters applied in backtest_engine, not display layer
- All existing data files preserved

---

## Future Stages (from analysis, not in this implementation)

**Stage 4 — Level Weighting** (analysis Optimization 2): Deploy MORE capital at high-probability levels instead of equal distribution. Requires changes to `compute_pool_sizing()` in wick_offset_analyzer.py. Separate implementation cycle.

**Stage 5 — Level Timing** (analysis Optimization 3): Dynamically activate/deactivate levels based on recency. Requires tracking days-since-last-touch (currently only boolean `dormant`). Separate implementation cycle.

**Stage 6 — Capital Efficiency Metric** (analysis Section 2.3): Optimize for P/L per dollar deployed per day instead of raw P/L. Requires per-level deployment tracking in backtest_engine.py. Separate implementation cycle — current Stage 3 uses raw P/L as a starting point.

## Notes

- **Stage 3 independence**: The plan assumes level filtering is independent of sell target. Should verify after implementation by checking whether optimal level filters change when sell target varies. If they do, a joint sweep may be needed.
- **Runtime**: 100 combos per ticker. Runtime is UNMEASURED — benchmark on CIFR before full sweep.
- **Grid reduced**: From 150 to 100 combos after discovering Buffer zone doesn't exist in bullet plans (zone_filter has 2 options instead of 3).
