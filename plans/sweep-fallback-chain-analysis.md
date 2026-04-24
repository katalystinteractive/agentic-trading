# Analysis: Sweep Winner Fallback Chain

**Date**: 2026-04-02 (Thursday)
**Purpose**: When the 3-way sweep winner (bounce/resistance) can't find qualifying levels from live data, the system falls through to neural % — potentially producing a WORSE target than the second-best sweep strategy. BBAI exposed this: bounce winner, but bounce found no qualifying levels live, so it recommended $3.91 (neural 5%) while the existing resistance target was $4.64 (resistance 24.7%).

---

## 1. Current Behavior (FACT — verified)

**FACT**: `compute_recommended_sell()` in `broker_reconciliation.py` checks the 3-way winner and runs ONLY that path:
- If `_sweep_winner == "resistance"`: run resistance path only
- If `_sweep_winner == "bounce"`: run bounce path only
- If neither: fall through to neural %

**FACT**: When the winning path fails, the fallthrough depends on WHERE it fails:
- Empty `qualifying` list → returns `bounce_fallback_pct` target (NOT neural %) — this is a bounce-specific fallback
- `wick_data` is None or empty → falls through to neural %
- `levels` is empty (no levels with hold_rate >= 15) → falls through to neural %
- Exception raised → falls through to neural %

**FACT**: BBAI's 3-way result: bounce composite $49.3/mo (winner), resistance composite $47.4/mo (second). Bounce won by $1.9/mo. But live bounce path failed (likely `wick_data` returned no qualifying support levels for BBAI at current price) → fell through to neural_watchlist 5.0% = $3.91. The resistance path WOULD have found $4.64 (67% reject) but was never tried.

**Result**: BBAI's sell recommendation dropped from $4.64 to $3.91 — a $0.73 downgrade — because the system skipped the second-best strategy.

---

## 2. Root Cause

The 3-way winner determines which strategy SHOULD be used based on simulation data. But live conditions can differ:
- Support levels shift with new wick data
- Approach counts change as new events occur
- Confidence thresholds may not be met with current data

When the winner can't produce a target, the fallback should be the SECOND-best sweep strategy, not a complete bypass to flat %.

---

## 3. Proposed Fix (PROPOSED)

Change the fallback chain in `compute_recommended_sell()` from:

```
winner strategy → neural % → default 6%
```

To:

```
winner strategy → second-best strategy → neural % → default 6%
```

### 3.1 Implementation

After the winner path's try/except block fails or returns no qualifying levels, try the other sweep strategy before falling through:

```python
# Determine winner and runner-up
bounce_entry = bounce_data.get(ticker, {})
res_entry = res_data.get(ticker, {})

# Get composites for ordering
bounce_comp = bounce_entry.get("stats", {}).get("composite", 0)
res_comp = res_entry.get("stats", {}).get("composite", 0)

# Order: try highest composite first, then second
strategies = []
if bounce_comp > 0:
    strategies.append(("bounce", bounce_comp, bounce_entry))
if res_comp > 0:
    strategies.append(("resistance", res_comp, res_entry))
strategies.sort(key=lambda x: x[1], reverse=True)

# Try each strategy in composite order
for strategy_name, comp, entry in strategies:
    if hist is None or hist.empty:
        break
    if strategy_name == "resistance":
        target = _try_resistance(hist, avg_cost, entry)
    elif strategy_name == "bounce":
        target = _try_bounce(hist, avg_cost, entry, ticker)
    if target and target > avg_cost:
        return target result
# Fall through to neural %
```

### 3.2 Refactoring consideration

The resistance and bounce code blocks in `compute_recommended_sell()` are ~30 lines each. To support the fallback chain, extract them into helper functions:
- `_try_resistance_target(hist, avg_cost, res_entry)` → `(price, source)` or `None`
- `_try_bounce_target(hist, avg_cost, bounce_entry, ticker)` → `(price, source)` or `None`

**Important**: Resistance and bounce entries have different param keys (resistance: `min_reject_rate`, `resistance_strategy`; bounce: `bounce_window_days`, `bounce_confidence_min`). Each helper function receives its own entry object from the correct sweep file — never mix them.

Then the main function becomes:
```python
for strategy_name, comp, entry in strategies:
    result = None
    if strategy_name == "resistance":
        result = _try_resistance_target(hist, avg_cost, entry)
    elif strategy_name == "bounce":
        result = _try_bounce_target(hist, avg_cost, entry, ticker)
    if result:
        return result
# Fall through to neural %
```

---

## 4. Files

| File | Change | Est. Lines |
| :--- | :--- | :--- |
| `tools/broker_reconciliation.py` | Extract `_try_resistance_target()` + `_try_bounce_target()`, composite-ordered fallback loop | ~15 net (refactor, not new logic) |
| **Total** | | **~15** |

---

## 5. Edge Cases

1. **Both strategies fail**: Falls through to neural % (unchanged from current behavior, but now both were tried)
2. **Only one sweep file exists**: The missing strategy has composite=0, sorts last, only the existing one runs
3. **No sweep files at all**: `strategies` list is empty, falls through to neural % immediately
4. **Winner produces target but it's below avg_cost**: That strategy's try-block returns None, second strategy is tried
