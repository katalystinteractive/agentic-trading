# Analysis: Sweep Results Consumer Wiring Gaps

**Date**: 2026-04-01 (Wednesday)
**Purpose**: Audit which tools consume the three sweep result files and identify gaps where findings don't surface.

---

## 1. Three Sweep Result Files

| File | Produced By | Contents |
| :--- | :--- | :--- |
| `data/support_sweep_results.json` | `support_parameter_sweeper.py` | sell_default %, pool, bullets, composite |
| `data/resistance_sweep_results.json` | `resistance_parameter_sweeper.py` | resistance strategy, thresholds, vs_flat winner |
| `data/bounce_sweep_results.json` | `bounce_parameter_sweeper.py` | bounce window, confidence, vs_others winner |

---

## 2. Consumer Audit (FACT — verified)

### broker_reconciliation.py — WIRED

**FACT**: `_load_profiles()` (lines 42-83) reads `neural_watchlist_profiles.json` for `sell_default` → `optimal_target_pct`.

**FACT**: `_load_resistance_profiles()` (lines 86-103) reads `resistance_sweep_results.json`.

**FACT**: `_load_bounce_profiles()` (lines 106-125) reads `bounce_sweep_results.json`.

**FACT**: `compute_recommended_sell()` (line 210) has the full priority chain: `target_exit > resistance > bounce > neural % > default 6%`.

**Status**: Fully wired. All three sweep types feed sell recommendations. Note: `reconcile_ticker()` (line 590) conditionally fetches hist via yfinance for resistance-winner tickers and passes it to `compute_recommended_sell()` — this is the primary live wiring path.

### daily_analyzer.py — WIRED (through broker recon)

**FACT**: `daily_analyzer.py` calls `reconcile_ticker()` from `broker_reconciliation.py` (line 1352) as part of its reconciliation phase.

**FACT**: The reconciliation output feeds the ACTION DASHBOARD (PLACE/ADJUST/CANCEL sell orders) with reason chains showing the sweep source (e.g., "resistance 22.1% ($7.97, 50% reject)").

**Status**: Wired indirectly through broker reconciliation. Sweep results surface in sell order recommendations.

### neural_order_adjuster.py — PARTIALLY WIRED

**FACT**: Calls `compute_recommended_sell()` (line 137) but does NOT pass `hist`. Without `hist`, the resistance and bounce code paths are skipped — it only gets the neural % target.

**FACT**: The sweep-optimized sell targets (resistance/bounce) do NOT surface in the order adjuster's sell adjustment table. It shows the same flat % as graph_builder.

**Gap**: Order adjuster needs to fetch hist for resistance/bounce-winner tickers and pass to `compute_recommended_sell()` — same pattern as `reconcile_ticker()` which already does this.

### bullet_recommender.py — NOT WIRED

**FACT**: `bullet_recommender.py` does NOT call `compute_recommended_sell()`. It does NOT read any of the three sweep result files.

**FACT**: For sell target display, it reads the EXISTING pending sell order from `portfolio.json` (line 503: `sell_price = pending_sells[0]["price"]`) and compares it against the position's avg_cost to show a percentage.

**FACT**: It also calls `sell_target_calculator.py` as a subprocess after fills (auto-triggered by `portfolio_manager.py cmd_fill()`), but this is independent of sweep results.

**Gap**: When a user runs `python3 tools/bullet_recommender.py STIM`, they see the pending sell order price from portfolio.json but NOT the sweep-optimized target. If the sweep says "bounce $1.54" but the pending sell is at "$1.34 (6%)", the bullet recommender shows $1.34 with no indication that a better target exists.

### sell_target_calculator.py — NOT WIRED

**FACT**: `sell_target_calculator.py` is a standalone CLI tool that computes its own resistance-based sell recommendations from live wick data. It does NOT read `resistance_sweep_results.json` or `bounce_sweep_results.json`.

**FACT**: Its recommendations are independent of the sweep findings. It may recommend different resistance levels than what the sweep optimized.

**Gap**: The sweep determines optimal resistance/bounce STRATEGY (first vs best, min reject rate, etc.), but `sell_target_calculator.py` uses its own hardcoded scoring parameters. The sweep-learned parameters are not applied to the live resistance analysis.

### wick_offset_analyzer.py — NOT APPLICABLE

**FACT**: The wick analyzer produces support levels and bullet plans (buy-side). It reads `sweep_support_levels.json` for level filters (which IS wired). It has no role in sell target computation.

**Status**: Not applicable — buy-side tool. Level filter integration is complete.

### graph_builder.py — PARTIALLY WIRED

**FACT**: `graph_builder.py` line 359 calls `compute_recommended_sell()` but passes `hist=None`, so the resistance and bounce paths are skipped. It only gets the neural % target for graph display purposes.

**Status**: Shows flat % in graph nodes. Resistance/bounce targets don't surface in the graph.

---

## 3. Gap Summary

| Tool | Sweep Results Used? | Gap |
| :--- | :--- | :--- |
| broker_reconciliation.py | YES (all 3) | None |
| daily_analyzer.py | YES (through recon) | None |
| neural_order_adjuster.py | YES (through recon) | None |
| **neural_order_adjuster.py** | **Partial** | Calls compute_recommended_sell but no hist — skips resistance/bounce |
| **bullet_recommender.py** | **NO** | Does not show sweep-optimized sell target |
| **sell_target_calculator.py** | **NO** | Uses own parameters, not sweep-learned thresholds |
| wick_offset_analyzer.py | N/A (buy-side) | None |
| graph_builder.py | Partial (flat % only) | hist=None skips resistance/bounce |

**Note**: `compute_recommended_sell()` docstring (line 213) is stale — says "target_exit > resistance > neural % > default 6%" but omits the bounce tier. Should be updated to match the actual priority chain.

---

## 4. Proposed Fixes

### 4.1 bullet_recommender.py — Show sweep-optimized sell target

Add a "Neural Sell Target" section to the bullet recommender output that calls `compute_recommended_sell()` with historical data. Shows the sweep-optimized price alongside the existing pending sell order for comparison.

**~15 lines.**

### 4.2 sell_target_calculator.py — Use sweep-learned parameters

When computing resistance recommendations, load the sweep's optimal params (min_reject_rate, min_resistance_approaches, resistance_strategy) and apply them instead of hardcoded defaults. This aligns the CLI tool's output with what the sweep determined is optimal.

**~10 lines.**

### 4.3 graph_builder.py — Pass hist for resistance/bounce targets

Fetch historical data for tickers where resistance/bounce wins and pass to `compute_recommended_sell()`. This would show the correct sell target in the graph/daily analyzer display nodes.

**Note**: This adds yfinance fetches during graph build, increasing runtime. May not be worth it since the authoritative sell recommendation already comes through broker reconciliation. Recommend leaving as-is unless graph display accuracy matters.

---

### 4.4 neural_order_adjuster.py — Pass hist for resistance/bounce

Same pattern as `reconcile_ticker()`: fetch hist for tickers where resistance/bounce wins, pass to `compute_recommended_sell()`. This makes the sell adjustment table show the correct sweep-derived target.

**~10 lines.**

### 4.5 broker_reconciliation.py — Fix stale docstring

Update `compute_recommended_sell()` docstring to include bounce tier in the priority chain.

**~1 line.**

---

## 5. Files

| File | Change | Est. Lines |
| :--- | :--- | :--- |
| `tools/bullet_recommender.py` | Add sweep-optimized sell target display | ~15 |
| `tools/sell_target_calculator.py` | Load sweep params for resistance scoring | ~10 |
| `tools/neural_order_adjuster.py` | Pass hist for resistance/bounce tickers | ~10 |
| `tools/broker_reconciliation.py` | Fix stale docstring | ~1 |
| **Total** | | **~36** |

**NOT modified**: `graph_builder.py` (leave as-is — recon is authoritative).
