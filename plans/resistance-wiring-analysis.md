# Analysis: Wiring Resistance Sweep Results into Live Sell Chain

**Date**: 2026-04-01 (Wednesday)
**Purpose**: The resistance sweep produces per-ticker optimal params in `data/resistance_sweep_results.json`, but no live tool reads this file. Sell targets in the daily analyzer, broker reconciliation, and order adjuster still use flat percentages. This analysis determines what needs to change to make resistance findings flow into actual order recommendations.

**Honesty note**: Every claim labeled FACT (verified) or PROPOSED.

---

## 1. Current Live Sell Chain (FACT — verified)

**FACT**: `broker_reconciliation.py::compute_recommended_sell()` (line 173) has this priority chain:
1. Manual `target_exit` from portfolio.json (line 183-185) → absolute price
2. `optimal_target_pct` from neural profiles (line 186-191) → flat % from avg_cost
3. Hardcoded `SELL_DEFAULT_PCT = 6.0` (line 193) → flat 6%

**FACT**: `_load_profiles()` (lines 42-83) merges THREE JSON files: `ticker_profiles.json` (base, lines 45-49), `neural_watchlist_profiles.json` (lines 53-65), and `neural_support_candidates.json` (lines 68-81). Each contributes `sell_default` → stored as `optimal_target_pct`. No resistance data is loaded.

**FACT**: `neural_order_adjuster.py` calls `compute_recommended_sell()` at line 19 and builds reason chains with flat % targets only.

**FACT**: `sell_target_calculator.py::analyze_ticker()` (lines 495-630) DOES compute live resistance levels and recommends resistance-based sell prices — but is only called via CLI (`python3 tools/sell_target_calculator.py TICKER`), never programmatically by broker_reconciliation or daily_analyzer for automated recommendations.

**Result**: The sweep discovers "STIM does best with resistance strategy=first, reject>=50%" but live orders still use flat 6%.

---

## 2. What `resistance_sweep_results.json` Contains (FACT — verified)

Per-ticker entry:
```json
{
    "params": {
        "resistance_strategy": "first",
        "min_reject_rate": 50,
        "min_resistance_approaches": 3,
        "resistance_fallback_pct": 6
    },
    "stats": {"composite": 52.1, "pnl": 15.3, "trades": 4},
    "vs_flat": {
        "flat_composite": 48.4,
        "resistance_composite": 52.1,
        "winner": "resistance"
    }
}
```

**Key point**: The file contains STRATEGY PARAMS (how to select resistance levels), NOT the actual resistance price levels. Actual levels must be computed live from historical data using `sell_target_calculator.py` functions — exactly as the backtest does during simulation.

---

## 3. Integration Design (PROPOSED)

### 3.1 New priority tier in `compute_recommended_sell()`

Insert resistance-based sell target between neural % and hardcoded fallback:

```
Priority: target_exit > resistance (if winner) > neural % > default 6%
```

When `resistance_sweep_results.json` shows `vs_flat.winner == "resistance"` for a ticker:
1. Load the ticker's resistance params (strategy, min_reject_rate, etc.)
2. Compute live resistance levels using `sell_target_calculator` functions
3. Filter by sweep-learned thresholds
4. Select target via strategy ("first" or "best")
5. Return the resistance price as the sell target

When `winner == "flat"` or ticker is not in resistance results: fall through to existing neural % path.

### 3.2 Resistance level computation at recommendation time

The sell_target_calculator functions already exist and accept arbitrary bounds:
- `find_pa_resistances(hist, zone_low, zone_high)` — clusters daily Highs
- `find_hvn_ceilings(hist, zone_low, zone_high)` — volume profile HVN nodes
- `merge_resistance_levels(levels)` — dedup within 2%
- `count_resistance_approaches(hist, level, proximity_pct=8.0)` — approach/reject counting

**FACT**: These functions require a historical DataFrame. `compute_recommended_sell()` currently does NOT have access to historical data — it only receives `ticker`, `avg_cost`, `pos`, `profiles`.

**PROPOSED**: Add an optional `hist` parameter to `compute_recommended_sell()`. When resistance mode is active, the caller passes the historical DataFrame. If `hist` is None, resistance path is skipped (falls through to flat %).

### 3.3 Where to load resistance sweep results

Two options:

**Option A — Load in `_load_profiles()`**: Merge resistance params into the profiles dict alongside `sell_default`. This keeps the loading centralized but mixes two different data types (flat % and resistance params) in one dict.

**Option B — Separate loader function**: Create `_load_resistance_profiles()` in broker_reconciliation.py that reads `resistance_sweep_results.json` and returns `{ticker: params_dict}`. Called once at startup, cached. This keeps resistance data separate from the flat % profile chain.

**Recommendation**: Option B — cleaner separation, matches the `_load_level_filters()` pattern in wick_offset_analyzer.py.

### 3.4 Callers that need to pass `hist`

**FACT**: `compute_recommended_sell()` is called from:
1. `broker_reconciliation.py::reconcile_ticker()` — has access to wick analysis data (passed in)
2. `neural_order_adjuster.py::compute_and_print_adjustments()` — calls reconcile_ticker
3. `graph_builder.py` — builds sell target nodes

For callers that don't have `hist`, the resistance path simply doesn't activate (hist=None → skip). This is backward compatible.

For `reconcile_ticker()`, the historical data can be fetched via yfinance (same pattern as `sell_target_calculator.py` line 505: `yf.download(ticker, period="13mo")`). This is a one-time fetch per ticker during reconciliation. **Only fetch for tickers where `vs_flat.winner == "resistance"`** — tickers using flat % don't need the fetch.

For `graph_builder.py` (line 359), the sell_target node lambda currently passes only `(ticker, avg_cost, pos, profiles)` — it has no mechanism to pass `hist`. Two options:
- Add a hist dependency node to the graph (increases complexity)
- Leave graph_builder using flat % and only apply resistance in broker_reconciliation (simpler, graph just needs the price for display)

**Recommendation**: Leave `graph_builder.py` unchanged — it shows sell targets for display only. The authoritative sell recommendation comes from `broker_reconciliation.py` which IS wired with resistance.

### 3.5 Runtime cost

Computing live resistance levels requires `yf.download(ticker, period="13mo")` per ticker (~1-3s each). With ~20 active tickers, this adds 20-60 seconds to reconciliation. Mitigations:
- **Conditional fetch**: Only fetch for tickers where `vs_flat.winner == "resistance"` (typically a subset)
- **Cache**: If wick analysis was recently run (e.g., within same daily_analyzer execution), reuse the cached historical data instead of re-fetching
- **Acceptable**: Even at 60s, this is within the daily_analyzer's total runtime (~90s currently)

---

## 4. Reason Chain Updates (PROPOSED)

`neural_order_adjuster.py` builds reason chains showing WHY a sell target was chosen. When resistance is the winner, the reason should include:

```
Avg $1.26 × resistance@$1.55 (70% reject, 5 approaches, strategy=first)
```

Instead of:
```
Avg $1.26 × neural_watchlist 6.0% = $1.34
```

This requires the resistance price and its stats (reject_rate, approaches) to flow from `compute_recommended_sell()` into the order adjuster's output formatting.

**PROPOSED**: `compute_recommended_sell()` returns a 3-tuple instead of 2-tuple:
```python
# Before: return price, source
# After: return price, source, details
# Where details = {"reject_rate": 70, "approaches": 5, "strategy": "first"} for resistance
# or details = {} for flat %
```

Backward compatible — existing callers destructure `price, source = compute_recommended_sell(...)` and will get a ValueError if not updated. All callers must be updated to accept the 3rd element.

**Alternative**: Return details in the source string: `"resistance@$1.55 (70% reject, 5 approaches)"`. Simpler, no signature change, but less structured.

**Recommendation**: Use the source string approach — simpler, no caller changes needed.

---

## 5. Files

| File | Change | Est. Lines |
| :--- | :--- | :--- |
| `tools/broker_reconciliation.py` | Add `_load_resistance_profiles()`, resistance tier in `compute_recommended_sell()`, hist parameter | ~40 |
| `tools/neural_order_adjuster.py` | Update reason chain to show resistance details in source string | ~5 |
| **Total** | | **~45** |

**NOT modified**: `sell_target_calculator.py` (functions already exist), `daily_analyzer.py` (inherits through broker recon), `resistance_parameter_sweeper.py` (output format unchanged).

---

## 6. Data Flow After Integration

```
resistance_sweep_results.json (per-ticker strategy params + vs_flat winner)
     ↓ read by
broker_reconciliation.py::_load_resistance_profiles()
     ↓ used in
compute_recommended_sell(ticker, avg_cost, pos, profiles, hist=None)
     ↓ when winner == "resistance":
sell_target_calculator functions compute live resistance levels
     ↓ filtered by sweep-learned thresholds
target_price = nearest/best qualifying resistance
     ↓ consumed by
neural_order_adjuster.py → sell adjustment table with resistance reason
daily_analyzer.py → action dashboard PLACE/ADJUST sell orders
```

---

## 7. Edge Cases

1. **`resistance_sweep_results.json` doesn't exist**: `_load_resistance_profiles()` returns empty dict (FileNotFoundError guard). All tickers fall through to neural %. This is the state before the first sweep runs — zero impact on existing behavior.
2. **No resistance results for ticker**: Falls through to neural % (existing behavior)
2. **Winner is "flat"**: Falls through to neural % (resistance sweep determined flat is better)
3. **No qualifying resistance levels**: Uses `resistance_fallback_pct` (same as backtest)
4. **hist unavailable** (yfinance down): Falls through to neural % (resistance needs history)
5. **Resistance levels shift between sweep and live**: Expected — live computation uses current 13-month data. The sweep optimized the STRATEGY (first vs best, thresholds), not the specific price levels.
