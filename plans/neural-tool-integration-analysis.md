# Analysis: Plugging Neural Profiles into Computation Tools

**Date**: 2026-03-29 (Sunday, 10:36 PM local / 3:36 PM ET)
**Purpose**: The neural profiles are DISPLAYED in the daily analyzer but NOT APPLIED to the tools that compute actual order sizes, sell targets, and bullet plans. This analysis identifies every integration point and what must change.

**Honesty note**: Every claim labeled FACT (verified against code) or PROPOSED.

---

## 1. The Problem

**FACT**: The daily analyzer currently has two parallel systems:

1. **Computation path** (graph_builder → shared_utils → bullet_recommender → broker_reconciliation) — uses hardcoded $300 pool, 5 bullets, 6.0% sell target
2. **Display path** (`_print_neural_sections()`) — loads neural profiles, shows them in a table, but nothing uses them

The computation tools produce the actual numbers (shares per order, sell target prices, pool allocations). The neural profiles sit in a separate section saying "the network recommends different numbers" — but the tools ignore them.

---

## 2. The Hardcoded Value Chain (FACT — verified against code)

```
daily_analyzer.py main()
├─ _run_recon_for_graph()
│  ├─ load_capital_config(tk)         ← $300 pool, 5 bullets from wick_offset_analyzer.py:75-78
│  └─ compute_recommended_sell()      ← 6.0% from broker_reconciliation.py:28
│     └─ _load_profiles()             ← reads ticker_profiles.json ONLY (NOT neural support)
├─ build_daily_graph()
│  ├─ {tk}:pool node
│  │  └─ get_ticker_pool(tk)          ← $300/$300 from shared_utils.py:29-30
│  └─ {tk}:sell_target node
│     └─ compute_recommended_sell()   ← same 6.0% path
└─ _print_neural_sections()           ← DISPLAY ONLY, no computation impact
```

### 2.1 Pool sizing: $300 hardcoded in 3 places

| Location | Default | Override mechanism | Neural aware? |
| :--- | :--- | :--- | :--- |
| `shared_utils.py:29` (`_DEFAULT_ACTIVE = 300`) | $300 | multi-period-results.json or portfolio.json | **NO** |
| `shared_utils.py:30` (`_DEFAULT_RESERVE = 300`) | $300 | same | **NO** |
| `wick_offset_analyzer.py:75` (`cap.get("active_pool", 300)`) | $300 | capital_config dict passed by caller | **NO** |

**FACT**: `get_ticker_pool()` in `shared_utils.py` checks: (1) multi-period-results.json, (2) portfolio.json capital section, (3) hardcoded $300. Neural profiles are NOT in this chain.

### 2.2 Bullet count: 5/3 hardcoded in 2 places

| Location | Default | Override mechanism | Neural aware? |
| :--- | :--- | :--- | :--- |
| `wick_offset_analyzer.py:77` (`active_bullets_max=5`) | 5 | capital_config dict | **NO** |
| `wick_offset_analyzer.py:78` (`reserve_bullets_max=3`) | 3 | capital_config dict | **NO** |

**FACT**: `bullet_recommender.py:223` calls `load_capital_config()` which returns these defaults. No neural override path.

### 2.3 Sell target: 6.0% hardcoded in 2 places

| Location | Default | Override mechanism | Neural aware? |
| :--- | :--- | :--- | :--- |
| `broker_reconciliation.py:28` (`SELL_DEFAULT_PCT = 6.0`) | 6.0% | `profiles` dict with `optimal_target_pct` | **PARTIAL** — reads ticker_profiles.json only |
| `daily_analyzer.py:872` (`math 6.0%` fallback) | 6.0% | target_exit in portfolio.json | **NO** |

**FACT**: `broker_reconciliation.py::_load_profiles()` (lines 42-47) reads ONLY `ticker_profiles.json`. It does NOT check `neural_support_candidates.json`. The `sell_target_calculator.py::_load_profile()` DOES check neural support as fallback (we added this in Step 4), but `broker_reconciliation.py` has its own separate `_load_profiles()` that was NOT updated.

---

## 3. What Must Change (4 integration points)

### 3.1 `broker_reconciliation.py::_load_profiles()` — merge neural sell targets

**Current** (lines 42-47): Reads `ticker_profiles.json` only.

**Change**: Merge `neural_support_candidates.json` as secondary source for `optimal_target_pct`. Same pattern as `sell_target_calculator.py::_load_profile()`.

**Impact**: `compute_recommended_sell()` will use neural sell targets (e.g., 10% for APP) instead of falling back to 6.0%.

**Backward compat**: Existing `ticker_profiles.json` entries take priority. Neural is fallback.

**Lines**: ~15

### 3.2 `shared_utils.py::get_ticker_pool()` — add neural pool tier

**Current** (lines 55-100): Checks multi-period → portfolio.json → hardcoded $300.

**Change**: Insert neural check AFTER multi-period, BEFORE portfolio.json:
1. multi-period-results.json (simulation-backed, always wins)
2. **neural_support_candidates.json** (NEW — learned pool sizes)
3. portfolio.json (static defaults)
4. hardcoded $300

**Impact**: Pool nodes in graph_builder will use neural pool ($200-$750 per ticker) instead of flat $300. Bullet recommender and broker reconciliation inherit this through `load_capital_config()`.

**Backward compat**: multi-period still has priority. If no neural profile exists, falls back to portfolio.json then $300.

**Lines**: ~20

### 3.3 `wick_offset_analyzer.py::load_capital_config()` — pass neural bullets

**Current** (lines 46-79): Calls `get_ticker_pool()` for pool, uses hardcoded 5/3 for bullets.

**Change**: After `get_ticker_pool()`, check if neural profile has `active_bullets_max` / `reserve_bullets_max`. If yes, use neural values.

**Impact**: `bullet_recommender.py` will compute shares using neural bullet count (3-7) instead of fixed 5.

**Backward compat**: If no neural profile, uses existing 5/3 defaults.

**Lines**: ~15

### 3.4 `graph_builder.py` — needs its own profiles merge

**FACT** (verified): `graph_builder.py` loads its OWN `profiles` dict directly from `ticker_profiles.json` at lines 174-180. It does NOT call `broker_reconciliation._load_profiles()`. Updating `_load_profiles()` in broker_reconciliation will NOT affect graph_builder's sell targets.

**Change**: `graph_builder.py` must also merge `neural_support_candidates.json` into its `profiles` dict, using the same pattern as broker_reconciliation change 3.1.

**Lines**: ~15

### 3.5 `bullet_recommender.py` — must pass ticker to `load_capital_config()`

**FACT** (verified): `bullet_recommender.py:223` calls `load_capital_config()` with NO ticker argument. When `ticker=None`, `load_capital_config()` skips `get_ticker_pool()` entirely and uses static portfolio.json defaults. Neural pool changes in `get_ticker_pool()` will never reach bullet_recommender.

**Change**: The call at line 223 must pass the ticker:
```python
# Current:
cap = load_capital_config()
# Fixed:
cap = load_capital_config(ticker)
```

**Lines**: ~1 (but critical)

---

## 4. Priority Chain After Changes

```
FOR POOL SIZING:
  1. multi-period-results.json (simulation-backed allocation)  ← highest priority
  2. neural_support_candidates.json (per-ticker learned pool)  ← NEW
  3. portfolio.json capital section (static defaults)
  4. hardcoded $300/$300                                       ← lowest priority

FOR SELL TARGET:
  1. position target_exit (manual override in portfolio.json)     ← highest (user intent)
  2. ticker_profiles.json optimal_target_pct (existing profiles)
  3. neural_support_candidates.json sell_default (learned %)      ← NEW
  4. SELL_DEFAULT_PCT = 6.0% hardcoded                            ← lowest

NOTE: Manual target_exit MUST override neural. If the user sets a specific sell
target for a position, the neural recommendation should not silently replace it.
This requires reordering compute_recommended_sell() to check target_exit FIRST.

FOR BULLET COUNT:
  1. neural_support_candidates.json active/reserve_bullets_max   ← NEW (highest)
  2. portfolio.json capital section
  3. hardcoded 5 active / 3 reserve                              ← lowest
```

---

## 5. Files Modified

| File | Change | Lines | Backward compat |
| :--- | :--- | :--- | :--- |
| `shared_utils.py` | Add neural pool check in `get_ticker_pool()` | ~20 | Falls back to existing chain if no neural profile |
| `broker_reconciliation.py` | Merge neural sell targets in `_load_profiles()` + reorder priority (target_exit first) | ~20 | Manual target_exit overrides neural |
| `wick_offset_analyzer.py` | Check neural bullets in `load_capital_config()` | ~15 | Falls back to 5/3 if no neural profile |
| `graph_builder.py` | Merge neural profiles into its own `profiles` dict (lines 174-180) | ~15 | Falls back to ticker_profiles.json only |
| `bullet_recommender.py` | Pass ticker to `load_capital_config(ticker)` at line 223 | ~1 | Existing behavior when ticker=None unchanged |
| **Total** | | **~71** | |

**NOT modified**: `daily_analyzer.py` (neural display sections already exist)

---

## 6. What This Achieves

**Before**:
```
graph_builder: pool=$300 → bullet_recommender: 5 bullets → shares=12
broker_recon: sell at $16.75 (6.0%)
_print_neural_sections: "Neural says: pool=$500, 3 bullets, sell at 10%"  ← IGNORED
```

**After**:
```
shared_utils: pool=$500 (from neural) → bullet_recommender: 3 bullets → shares=33
broker_recon: sell at $17.44 (10.0% from neural)
_print_neural_sections: "Neural: $500/3/10%" ← MATCHES computation
```

The neural recommendations flow through the SAME computation tools that produce the actual orders. No more display-only data.
