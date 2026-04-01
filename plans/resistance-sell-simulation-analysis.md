# Analysis: Resistance-Aware Sell Simulation

**Date**: 2026-04-01 (Wednesday)
**Purpose**: Design a simulation mode where the backtest exits positions at resistance levels (where price historically gets rejected) instead of flat percentage targets. Determine whether resistance-based exits produce better P/L than the current flat approach.

**Honesty note**: Every claim labeled FACT (verified) or PROPOSED.

---

## 1. Current State (FACT — verified)

### 1.1 Flat sell mode (what the backtest does today)

**FACT**: `backtest_engine.py` line 306 computes sell targets as flat percentages:
```python
target_price = pos.avg_cost * (1 + sell_target / 100)
```
Where `sell_target` comes from `_compute_sell_target()` (lines 111-131): default 6%, fast cycler 8%, exceptional 10%.

**FACT**: `backtest_config.py` line 125 defines `sell_mode: str = "flat"` with a comment `# "flat" or "resistance"` — the field exists but is NEVER read by `backtest_engine.py` (verified: zero matches for `sell_mode` in `backtest_engine.py`).

**FACT**: The current parameter sweep in `support_parameter_sweeper.py` sweeps `sell_default` across `[4.0, 5.0, 6.0, 7.0, 8.0, 10.0]` — all flat percentages. The sweep finds the best flat percentage per ticker but never tests resistance-based exits.

### 1.2 Resistance detection infrastructure (what already exists)

**FACT**: `sell_target_calculator.py` has production-ready resistance detection:
- `find_pa_resistances()` (lines 132-165) — clusters daily Highs into resistance levels
- `find_hvn_ceilings()` (lines 168-213) — volume profile HVN nodes above price
- `merge_resistance_levels()` (lines 237-257) — dedup within 2%, merge PA+HVN sources
- `count_resistance_approaches()` (lines 260-322) — counts approach events with reject/broke classification
- `_score_level()` (lines 329-354) — scores by rejection quality × sample size
- `recommend_sell()` (lines 377-436) — tranche splitting for multi-level sells

**FACT**: `cycle_timing_analyzer.py` reuses the same functions (imports at lines 27-30) for resistance event detection and cycle timing.

**FACT**: The backtest's wick cache (line 134 of `backtest_engine.py`) stores computed wick analysis per (ticker, day_idx). This cache mechanism can be extended to also store resistance levels.

### 1.3 Mirror architecture between support and resistance

**FACT**: Support detection in `wick_offset_analyzer.py` uses:
- `find_hvn_floors()` — volume profile floors (Lows)
- `find_price_action_supports()` — clusters of daily Lows
- `find_approach_events()` — approach counting with hold/break classification

Resistance detection in `sell_target_calculator.py` uses the exact mirror:
- `find_hvn_ceilings()` — volume profile ceilings (Highs)
- `find_pa_resistances()` — clusters of daily Highs
- `count_resistance_approaches()` — approach counting with reject/broke classification

The two systems are architecturally parallel but currently don't share code.

---

## 2. What Must Be Built (PROPOSED)

### 2.1 Resistance-aware exit logic in backtest_engine.py

At buy time, compute resistance levels above entry price using the existing `sell_target_calculator` functions. At sell time, exit at the nearest resistance level instead of a flat percentage.

**Integration point**: Lines 302-331 of `backtest_engine.py` (profit target check). When `cfg.sell_mode == "resistance"`:

1. Look up resistance levels for this ticker (from a resistance cache, computed once per wick refresh)
2. Find resistance levels above `pos.avg_cost`
3. Select the target based on the sweep-optimized strategy:
   - `"first"`: sell at the NEAREST resistance (quick exit)
   - `"best"`: sell at the HIGHEST-SCORING resistance (best rejection rate)
   - `"tranche"`: sell in tranches across multiple resistances
4. Exit when `day_high >= resistance_price`

### 2.2 Resistance cache alongside wick cache

**FACT**: The wick cache stores support-side analysis per (ticker, day_idx). Resistance analysis is equally expensive (HVN computation + PA clustering). A parallel resistance cache avoids recomputation across sweep combos.

**PROPOSED**: Add a `resistance_cache` parameter to `run_simulation()`, keyed by `(ticker, day_idx)`. Each entry stores:
```python
{
    "levels": [{"price": 1.55, "source": "HVN+PA", "reject_rate": 70, "approaches": 5}, ...],
    "computed_at": day_idx,
}
```

Resistance is recomputed on the same schedule as wick analysis (`cfg.recompute_levels`): daily, weekly, or monthly.

### 2.3 New sweep parameters

Add to `SurgicalSimConfig`:
```python
# Resistance sell mode
sell_mode: str = "flat"              # "flat" or "resistance" (already exists)
resistance_strategy: str = "first"   # "first" (nearest) or "best" (highest reject rate)
min_reject_rate: int = 40            # minimum rejection rate to trust a resistance
min_resistance_approaches: int = 2   # minimum approach count
resistance_fallback_pct: float = 6.0 # flat % fallback when no qualifying resistance found
```

### 2.4 Resistance sweep grid

```python
RESISTANCE_GRID = {
    "resistance_strategy": ["first", "best"],
    "min_reject_rate": [30, 50, 70],
    "min_resistance_approaches": [2, 3, 5],
    "resistance_fallback_pct": [4, 6, 8],
}
```

Total combos: 2 × 3 × 3 × 3 = **54 combos** per ticker × 4 periods = 216 simulations.

**Note**: `"tranche"` (split sells across multiple resistance levels) is excluded from the initial grid because the backtest engine's `Position` class tracks shares as a single int and all exits do `del positions[tk]` (full sell). Supporting partial sells requires engine-level position tracking changes — a future enhancement, not part of this initial build.

### 2.5 New sweep tool: `resistance_parameter_sweeper.py`

**PROPOSED**: New tool following the established sweeper pattern:

```python
# Stage 1: Sweep resistance params with threshold+execution locked from prior sweeps
def sweep_resistance(ticker, threshold_params, execution_params=None, months=10):
    """Sweep resistance exit strategy parameters.

    Uses sell_mode="resistance" in backtest config.
    Multi-period composite scoring across 12mo/6mo/3mo/1mo.
    """
```

**Data isolation**: Writes to `data/resistance_sweep_results.json` (separate from `support_sweep_results.json`). Never overwrites support sweep data.

**Multi-period**: Uses `SWEEP_PERIODS = [12, 6, 3, 1]` and `compute_composite()` — identical pattern to `sweep_threshold()`.

**Parallel workers**: `_sweep_resistance_worker()` + `Pool.map()` in `main()`, gated by `--workers N`.

### 2.6 Integration with live tools

Once the sweep finds optimal resistance params per ticker, the results flow through:

```
resistance_sweep_results.json
     ↓ read by
broker_reconciliation.py → compute_recommended_sell() uses resistance levels
sell_target_calculator.py → already does this (just needs to prefer sweep-learned params)
daily_analyzer.py → shows resistance-based sell targets
```

**Key**: The existing `sell_target_calculator.py` already recommends resistance-based sells for the live path. The sweep would validate and optimize its parameters, then feed the optimized params back.

---

## 3. Data Flow (PROPOSED)

```
Step 1: Run support sweep (existing — produces threshold + execution params)
Step 2: Run resistance sweep (NEW — uses locked threshold+execution, sweeps resistance params)
Step 3: Compare flat vs resistance P/L per ticker
Step 4: For each ticker, use the approach with higher composite $/mo
```

### 3.1 Comparison methodology

For each ticker, compute:
- **Flat composite**: Best flat sell % from `support_sweep_results.json`
- **Resistance composite**: Best resistance strategy from `resistance_sweep_results.json`
- **Winner**: Higher composite determines which `sell_mode` the ticker uses

This produces a per-ticker `sell_mode` decision: some tickers may be better with flat (clean breakouts), others with resistance (mean-reversion patterns with reliable ceilings).

### 3.2 Output file

`data/resistance_sweep_results.json`:
```json
{
    "_meta": {
        "source": "resistance_parameter_sweeper.py",
        "updated": "2026-04-01",
        "combos": 54,
        "tickers_swept": 27
    },
    "STIM": {
        "params": {
            "resistance_strategy": "first",
            "min_reject_rate": 50,
            "min_resistance_approaches": 3,
            "resistance_fallback_pct": 6
        },
        "stats": {
            "composite": 52.1,
            "pnl": 15.30,
            "trades": 4,
            "win_rate": 100.0
        },
        "periods": {
            "12": {"pnl": 520, "cycles": 15, "trades": 15, "win_rate": 95.0},
            "6": {"pnl": 280, "cycles": 9, "trades": 9, "win_rate": 100.0},
            "3": {"pnl": 100, "cycles": 5, "trades": 5, "win_rate": 100.0},
            "1": {"pnl": 15.3, "cycles": 2, "trades": 2, "win_rate": 100.0}
        },
        "vs_flat": {
            "flat_composite": 48.4,
            "resistance_composite": 52.1,
            "improvement_pct": 7.6,
            "winner": "resistance"
        }
    }
}
```

---

## 4. Backtest Engine Changes (PROPOSED)

### 4.1 Resistance computation during simulation

Inside `run_simulation()`, when wick analysis is computed (or loaded from cache), also compute resistance levels:

```python
# After wick analysis at line ~530:
if cfg.sell_mode == "resistance":
    res_key = (tk, day_idx)
    if res_key in resistance_cache:
        resistance_levels = resistance_cache[res_key]
    else:
        from sell_target_calculator import find_pa_resistances, find_hvn_ceilings, merge_resistance_levels, count_resistance_approaches
        # Use hist_slice up to current sim day (no look-ahead)
        # Functions accept (hist, zone_low, zone_high) — NOT (hist, price, zone)
        zone_low = pos.avg_cost * 1.02   # start slightly above entry
        zone_high = pos.avg_cost * 1.20  # search up to 20% above entry
        pa_res = find_pa_resistances(hist_slice, zone_low, zone_high)
        hvn_res = find_hvn_ceilings(hist_slice, zone_low, zone_high)
        merged = merge_resistance_levels(pa_res + hvn_res)
        # Count approaches for each level
        for level in merged:
            stats = count_resistance_approaches(hist_slice, level["price"])
            level.update(stats)
        resistance_levels = merged
        resistance_cache[res_key] = resistance_levels
```

**Note**: `find_pa_resistances(hist, zone_low, zone_high)` and `find_hvn_ceilings(hist, zone_low, zone_high)` already accept arbitrary bounds — no refactor needed. `cycle_timing_analyzer.py` already calls them with arbitrary bounds (lines 157-158).

### 4.2 Resistance-based exit check

Replace the flat target check when `sell_mode == "resistance"`:

```python
if cfg.sell_mode == "resistance" and resistance_levels:
    # Filter by sweep-learned parameters
    qualifying = [r for r in resistance_levels
                  if r["price"] > pos.avg_cost
                  and r.get("reject_rate", 0) >= cfg.min_reject_rate
                  and r.get("approaches", 0) >= cfg.min_resistance_approaches]

    if qualifying:
        if cfg.resistance_strategy == "first":
            target_price = min(r["price"] for r in qualifying)  # nearest
        elif cfg.resistance_strategy == "best":
            target_price = max(qualifying, key=lambda r: r.get("reject_rate", 0))["price"]
    else:
        # No qualifying resistance — use fallback flat %
        target_price = pos.avg_cost * (1 + cfg.resistance_fallback_pct / 100)
else:
    # Original flat logic
    target_price = pos.avg_cost * (1 + sell_target / 100)
```

### 4.3 Look-ahead bias prevention

**CRITICAL**: Resistance levels must be computed from historical data UP TO the current simulation day, NOT future data. The `hist_slice` at line 498-504 already handles this for wick analysis. The same slice must be used for resistance computation.

**FACT**: `find_pa_resistances()` and `find_hvn_ceilings()` accept a history DataFrame as input. Passing `hist_slice` (which ends at the current simulation day) prevents look-ahead.

---

## 5. Files

| File | Action | Est. Lines |
| :--- | :--- | :--- |
| `tools/backtest_engine.py` | Add resistance exit logic, resistance cache, `sell_mode` dispatch | ~50 |
| `tools/backtest_config.py` | Add resistance config fields to `SurgicalSimConfig` | ~6 |
| `tools/resistance_parameter_sweeper.py` | **NEW** — resistance sweep tool with multi-period + parallel workers | ~200 |
| **Total** | | **~256** |

**NOT modified**: `sell_target_calculator.py` (functions already accept arbitrary bounds — no refactor needed), `wick_offset_analyzer.py` (support-side, untouched), `support_parameter_sweeper.py` (separate sweep, separate output), `neural_watchlist_profiles.json` (separate data).

---

## 6. Runtime Estimate

- 54 combos × 4 periods × ~2s per sim = ~430s (~7 min) per ticker
- 27 tickers sequential = ~3 hours
- 27 tickers with `--workers 8` = ~25 min

---

## 7. Requirements Compliance

| Requirement | How Met |
| :--- | :--- |
| **Data isolation** | Writes to `data/resistance_sweep_results.json` — never touches support sweep data |
| **Multi-period scoring** | Uses `SWEEP_PERIODS = [12, 6, 3, 1]` + `compute_composite()` |
| **Parallel workers** | `_sweep_resistance_worker()` + `Pool.map()` with `--workers N` |

---

## 8. Open Questions

1. **Should resistance sweep lock threshold+execution params from the support sweep?** Proposed yes — resistance is a sell-side optimization that should use the already-optimized buy-side parameters. This makes it a "Stage 4" after Stages 1-3.

2. **Tranche selling in backtest**: The live `recommend_sell()` splits across multiple tranches. Tranche is excluded from the initial grid (see Section 2.4) because implementing partial sells requires position tracking changes (all sells currently do `del positions[tk]`). This remains a future enhancement once the initial first/best strategies prove the concept.

3. **Resistance level stability**: Resistance levels shift as new price data arrives (same as support). Should the resistance sweep use the same `recompute_levels` cadence (weekly default) as support? Proposed yes — consistency.

4. **Cron integration**: Should the weekly reoptimize pipeline include a resistance sweep step? Proposed yes — add as Step 5 after weight training. This adds ~25 min to the weekly run.
