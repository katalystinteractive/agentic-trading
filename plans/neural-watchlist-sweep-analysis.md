# Analysis: Guaranteed Neural Profiles for Watchlist + Better Reason Chains

**Date**: 2026-03-29 (Sunday, 11:45 PM local / 4:45 PM ET)
**Purpose**: (1) Ensure every watchlist ticker always has a neural profile. (2) Fix the meaningless "Neural P/L: $324" reason in the order adjuster.

**Honesty note**: Every claim labeled FACT (verified) or PROPOSED.

---

## 1. Problem 1: Watchlist Tickers Missing Neural Profiles

### 1.1 Current state (FACT — verified)

**FACT**: The neural support discoverer (`neural_support_discoverer.py`) sweeps tickers from `data/backtest/candidate-gate/` — whatever happens to have collected simulation data. This is NOT the watchlist. It's a mix of candidate-gate tickers from past screening runs.

**FACT**: The watchlist is in `portfolio.json` under `"watchlist"` (array of ticker strings) plus all tickers with active positions in `"positions"`.

**FACT**: 4 sell orders currently show "standard 6.0%" because their tickers (CLF, NNE, TEM, TMC) have no neural support profile despite being active positions.

### 1.2 What's needed (PROPOSED)

Two separate neural profile sets:

| Set | Source | Purpose | Updated |
| :--- | :--- | :--- | :--- |
| **Watchlist profiles** | `data/neural_watchlist_profiles.json` | Every position + watchlist ticker gets a sweep — no exceptions | Weekly (Saturday re-optimization) |
| **Candidate profiles** | `data/neural_support_candidates.json` | Universe discovery — top 30 from 1,500 passers | Weekly or on-demand |

The watchlist sweep is MANDATORY — it runs on every ticker the user has a position in or is watching. The candidate sweep is EXPLORATORY — it finds new tickers to add to the watchlist.

### 1.3 What must change (PROPOSED)

**New step in weekly_reoptimize.py**: After the dip sweep, run the support sweeper on ALL watchlist + position tickers. Write results to `data/neural_watchlist_profiles.json`.

**Priority chain update** — `_load_profiles()` in `broker_reconciliation.py` and `graph_builder.py` should check:
1. `ticker_profiles.json` (dip strategy, existing)
2. `neural_watchlist_profiles.json` (NEW — watchlist-specific sweep)
3. `neural_support_candidates.json` (candidate discovery, existing)

This ensures every position/watchlist ticker has a neural sell target, pool, and bullet count — not just the ones that happened to be in the candidate gate.

---

## 2. Problem 2: "Neural P/L: $324" Is a Meaningless Reason

### 2.1 Current state (FACT — verified)

**FACT**: `_build_buy_reason()` in `neural_order_adjuster.py` outputs:
```
Pool: $363/5b (multi-period-scorer) | Neural P/L: $324
```

"Neural P/L: $324" tells the user nothing actionable:
- $324 over what time period?
- Is that good or bad?
- What params produced it?
- Why does it justify this share count?

### 2.2 What the reason should say (PROPOSED)

The reason chain should trace the FULL path from input data to the recommendation:

**For sell adjustments:**
```
RAISE from $16.75 (5.7%) to $17.44 (10.0%)
  Priority: target_exit=None → ticker_profiles=None → neural_watchlist(10.0%)
  Evidence: 12mo $347/15t/100%WR | 6mo $180/8t/100%WR | 3mo $85/4t | Composite $23.1/mo
  vs default 6.0%: would sell at $16.80 (leaving $0.64/share on table)
```

**For buy adjustments:**
```
-5 shares (9 → 4) at $13.03
  Priority: multi-period-scorer pool=$320 / 5 bullets = $64/bullet = 4 shares
  Neural sweep: 10.0% sell target, 100% WR across 4 periods, $23.1/mo composite
  Current sizing: $300 pool / 5 bullets = $60/bullet = 9 shares (over-allocated)
```

The reason must answer:
- **WHAT** changed (the delta)
- **WHY** (which priority level determined the value)
- **EVIDENCE** (per-period P/L, win rate, composite — when from neural)
- **VS DEFAULT** (what it would be without the neural override)

### 2.3 Data available for reason chains (FACT)

**FACT**: `get_ticker_pool()` returns `source` field: `"multi-period-scorer"`, `"neural_support"`, `"portfolio.json (default)"`.

**FACT**: `compute_recommended_sell()` returns `source` string: `"target_exit"`, `"neural_support 10.0%"`, `"optimized 12.0%"`, `"standard 6.0%"`.

**FACT**: `neural_support_candidates.json` candidates have `pnl` and `params` (sell_default, active_pool, etc.).

**FACT**: `composite` and `periods` fields are in the code (`rank_and_gate()` in `neural_support_discoverer.py` populates them) but are NOT in the current on-disk JSON. The current file was written before multi-period sweep support was added. These fields will only be populated after the sweeper is re-run with the multi-period code from Step 1 of the order adjuster plan.

**FACT**: `neural_watchlist_profiles.json` DOESN'T EXIST YET. Once created by the watchlist sweep (with multi-period), it WILL contain `composite` and `periods`.

**DEPENDENCY**: The richer reason chains (per-period evidence) require the sweeper to be re-run. Until then, reason chains will show only `pnl` (single-period). The watchlist sweep step in `weekly_reoptimize.py` will produce the full data automatically on first Saturday run.

**MISSING**: The current `_build_buy_reason()` only reads `pnl` and `composite` from neural candidates. It doesn't show:
- What the pool WOULD be without the override (the "vs default" comparison)
- Per-period breakdown (12/6/3/1mo)
- The full priority chain path

---

## 3. Implementation

### 3.1 New: Watchlist sweep step

Add to `weekly_reoptimize.py` (or as a standalone tool):

```python
def step_watchlist_sweep():
    """Sweep support params for ALL watchlist + position tickers."""
    from neural_dip_evaluator import _load_portfolio, _get_dip_candidates
    portfolio = _load_portfolio()

    # ALL tickers the user has or watches
    tickers = set(portfolio.get("positions", {}).keys())
    tickers.update(portfolio.get("watchlist", []))

    # Run support sweeper on each
    for tk in sorted(tickers):
        sweep_threshold(tk, months=10)

    # Write to data/neural_watchlist_profiles.json
```

### 3.2 Update priority chain

In `broker_reconciliation.py::_load_profiles()`, `graph_builder.py`, and `shared_utils.py::get_ticker_pool()`:
- After checking `ticker_profiles.json`
- Add check for `neural_watchlist_profiles.json` BEFORE `neural_support_candidates.json`

This ensures watchlist-specific profiles (trained on exactly the user's tickers) take priority over generic candidate discovery profiles.

### 3.3 Fix reason chain in neural_order_adjuster.py

Replace `_build_buy_reason()` and `_build_sell_reason()` with richer output that includes:
- Priority path trace
- Per-period evidence when available
- "vs default" comparison

---

## 4. Files

| File | Change | Lines |
| :--- | :--- | :--- |
| `tools/weekly_reoptimize.py` | Add watchlist sweep step | ~30 |
| `tools/neural_order_adjuster.py` | Richer reason chains with full evidence | ~40 |
| `tools/broker_reconciliation.py` | Add watchlist profiles to priority chain | ~10 |
| `tools/graph_builder.py` | Add watchlist profiles to priority chain | ~10 |
| `tools/shared_utils.py` | Add watchlist profiles to pool priority chain | ~10 |
| **Total** | | **~100** |
