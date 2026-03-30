# Implementation Plan: Neural Order Adjuster with Multi-Period + Reason Chains

**Date**: 2026-03-29
**Source analysis**: `plans/neural-order-adjuster-analysis.md` (verified, 16/16 correct)
**Goal**: Tool that computes concrete sell/buy adjustments from neural profiles, backed by multi-period simulation evidence, with reason chains showing the neural firing path.

---

## Scope

3 steps, sequential (each depends on the prior):

| Step | What | File | Type | Lines |
| :--- | :--- | :--- | :--- | :--- |
| 1 | Multi-period sweep in support sweeper | `support_parameter_sweeper.py` | MODIFY | ~40 |
| 2 | Order adjuster with reason chains | `neural_order_adjuster.py` | NEW | ~200 |
| 3 | Wire into daily analyzer | `daily_analyzer.py` | MODIFY | ~10 |

**NOT modified**: `multi_period_scorer.py` (import `compute_composite`, don't modify), `shared_utils.py`, `broker_reconciliation.py`, `wick_offset_analyzer.py`, `graph_builder.py` (all already have neural integration)

---

## Step 1: Multi-Period Sweep in Support Sweeper

### 1.1 Import compute_composite

**Where**: Top of `support_parameter_sweeper.py`, after existing imports.

```python
from multi_period_scorer import compute_composite
```

### 1.2 Change `sweep_threshold()` to run 4 periods

**Current** (line 151): `def sweep_threshold(ticker, months=10)` — runs single simulation.

**Change**: For each combo, run 4 simulations (12/6/3/1 months), compute composite, rank by composite instead of single P/L.

```python
SWEEP_PERIODS = [12, 6, 3, 1]  # months

def sweep_threshold(ticker, months=10):
    """Stage 1: Sweep sell target + catastrophic stop across multi-period."""
    data_dir = _collect_once(ticker, max(SWEEP_PERIODS))  # collect for longest period
    from backtest_engine import load_collected_data
    price_data, regime_data, _ = load_collected_data(data_dir)
    # NOTE: _simulate_with_config passes period_months to the simulation,
    # which controls the sim start date (end - period_months*30 days).
    # Price data covers 12 months; shorter periods just simulate a later
    # start date within the same data. Data collection happens ONCE.

    best_composite = float("-inf")
    best_params = None
    best_result = None
    best_periods = None

    for sell_target, cat_stop in combos:
        overrides = {
            "sell_default": sell_target,
            "sell_fast_cycler": sell_target + 2.0,
            "sell_exceptional": sell_target + 4.0,
            "cat_hard_stop": cat_stop,
            "cat_warning": max(cat_stop - 10, 5),
        }

        # Run each period — separate wick_cache per period
        # WHY: wick analysis at day_idx=50 in a 12-month sim covers different
        # history than day_idx=50 in a 3-month sim (different start date).
        # Cache keys use day_idx, so sharing across periods would return
        # wrong levels. Each period gets its own cache.
        results_by_period = {}
        for period_months in SWEEP_PERIODS:
            period_wick_cache = {}  # isolated per period
            try:
                result = _simulate_with_config(
                    ticker, period_months, overrides, data_dir,
                    price_data, regime_data, period_wick_cache)
                results_by_period[period_months] = {
                    "pnl": result.get("pnl", 0),
                    "cycles": result.get("cycles", 0),
                    "trades": result.get("sells", 0),
                    "win_rate": result.get("win_rate", 0),
                }
            except Exception:
                results_by_period[period_months] = {"pnl": 0, "cycles": 0}

        # Compute composite $/month
        composite, details = compute_composite(results_by_period)

        if composite > best_composite:
            best_composite = composite
            best_params = {"sell_default": sell_target, "cat_hard_stop": cat_stop}
            best_result = result  # last period's full result (for features)
            best_periods = results_by_period

    return best_params, best_result, best_composite, best_periods
```

### 1.3 Update return value handling

`sweep_threshold()` currently returns `(best_params, best_result)`. Adding `best_composite` and `best_periods` changes the return signature.

**All callers must be updated**:
- `neural_support_discoverer.py` calls `sweep_threshold()` — update to unpack 4 values
- `_sweep_threshold_worker()` in sweeper — update return
- `main()` in sweeper — update display

### 1.4 Update neural_support_candidates.json output

Add `composite` and `periods` to each candidate:

```python
ranked.append({
    "ticker": tk,
    "pnl": stats["pnl"],       # single-period P/L (backward compat)
    "composite": composite,     # NEW: $/month composite
    "periods": periods_data,    # NEW: per-period breakdown
    ...
})
```

### 1.5 Verification

```bash
python3 tools/support_parameter_sweeper.py --ticker CIFR --stage threshold
# Verify output shows composite $/month and per-period breakdown
```

---

## Step 2: Neural Order Adjuster

### 2.1 New file: `tools/neural_order_adjuster.py`

**Purpose**: Compare every pending order against neural-computed recommendations. Output adjustment tables with reason chains.

```
Usage:
    python3 tools/neural_order_adjuster.py              # full report
    python3 tools/neural_order_adjuster.py --sells-only
    python3 tools/neural_order_adjuster.py --buys-only
```

### 2.2 Sell adjustment computation

For EVERY pending SELL order (not just neural tickers):

```python
from broker_reconciliation import compute_recommended_sell, _load_profiles
from shared_utils import get_ticker_pool

profiles = _load_profiles()  # already merges neural

for tk, orders in pending_orders.items():
    pos = positions.get(tk, {})
    avg = pos.get("avg_cost", 0)
    if avg <= 0:
        continue

    sell_orders = [o for o in orders if o.get("type", "").upper() == "SELL"]
    rec_sell, source = compute_recommended_sell(tk, avg, pos, profiles)

    for o in sell_orders:
        current = o["price"]
        diff = rec_sell - current
        # Build reason chain from source + neural evidence
        reason = _build_sell_reason(tk, source, profiles, ns_candidates)
        adjustments.append({...})
```

### 2.3 Buy adjustment computation

For EVERY pending BUY order:

```python
from wick_offset_analyzer import load_capital_config

for tk, orders in pending_orders.items():
    buy_orders = [o for o in orders if o.get("type", "").upper() == "BUY"]
    cap = load_capital_config(tk)  # already has neural pool + bullets
    pool = cap["active_pool"]
    bullets = cap["active_bullets_max"]
    pool_source = get_ticker_pool(tk)["source"]

    for o in buy_orders:
        buy_price = o["price"]
        current_shares = o["shares"]
        rec_shares = max(1, int(pool / bullets / buy_price))
        diff = rec_shares - current_shares
        reason = _build_buy_reason(tk, pool, bullets, pool_source, ns_candidates)
        adjustments.append({...})
```

### 2.4 Reason chain builder

```python
def _build_sell_reason(ticker, source, profiles, ns_candidates):
    """Build reason chain showing neural firing path for sell recommendation."""
    parts = [f"Source: {source}"]

    # Add neural evidence if neural was the source
    candidate = ns_candidates.get(ticker)
    if candidate and "neural" in source:
        periods = candidate.get("periods", {})
        if periods:
            for months in [12, 6, 3, 1]:
                p = periods.get(str(months)) or periods.get(months, {})
                if p:
                    parts.append(f"{months}mo: ${p.get('pnl', 0):.0f} P/L, "
                                 f"{p.get('cycles', 0)} cycles, "
                                 f"{p.get('win_rate', 0)}% WR")
        composite = candidate.get("composite")
        if composite:
            parts.append(f"Composite: ${composite:.1f}/mo")

    return " | ".join(parts)


def _build_buy_reason(ticker, pool, bullets, pool_source, ns_candidates):
    """Build reason chain showing neural firing path for buy recommendation."""
    parts = [f"Pool: ${pool}/{bullets}b ({pool_source})"]

    candidate = ns_candidates.get(ticker)
    if candidate:
        pnl = candidate.get("pnl", 0)
        parts.append(f"Neural P/L: ${pnl:.0f}")
        # Show improvement vs default if available
        default_pool = 300
        default_bullets = 5
        if pool != default_pool or bullets != default_bullets:
            parts.append(f"vs default ${default_pool}/{default_bullets}b")

    return " | ".join(parts)
```

### 2.5 Output tables

**Sell table** — shows ALL pending sells, not just ones that need changes:

```
## Sell Order Adjustments (N changes, M OK)

| Ticker | Shares | Current Sell | Rec Sell | Action | Reason |
| :--- | :--- | :--- | :--- | :--- | :--- |
| NU | 15 | $16.75 (5.7%) | $17.44 (10.0%) | **RAISE +$0.69** | Source: neural_support 10.0% | 12mo: $347 P/L, 15 cyc | Composite: $23.1/mo |
| ACHR | 92 | $6.92 (6.0%) | $6.92 (6.0%) | OK | Source: standard 6.0% (no neural profile) |
```

**Buy table** — shows ALL pending buys:

```
## Buy Order Adjustments (N changes, M OK)

| Ticker | Price | Current | Rec | Action | Reason |
| :--- | :--- | :--- | :--- | :--- | :--- |
| RDW | $7.89 | 6 sh | 9 sh | **+3 sh** | Pool: $500/7b (neural_support) | Neural P/L: $833 |
| NVDA | $174.60 | 1 sh | 1 sh | OK | Pool: $300/5b (portfolio.json) |
```

### 2.6 Summary line

```
Sells: 2 RAISE, 0 LOWER, 12 OK (14 total)
Buys: 15 resize, 15 OK (30 total)
```

---

## Step 3: Wire into Daily Analyzer

### 3.1 Call adjuster after neural sections

**Where**: In `_print_neural_sections()` or immediately after it in `main()`.

```python
# After _print_neural_sections(portfolio):
try:
    from neural_order_adjuster import compute_and_print_adjustments
    compute_and_print_adjustments(portfolio)
except ImportError:
    pass  # tool not yet built — graceful skip
```

### 3.2 The adjuster provides a callable function

```python
# In neural_order_adjuster.py:
def compute_and_print_adjustments(portfolio):
    """Called by daily_analyzer for inline report section."""
    ns_candidates = _load_neural_candidates()
    sell_adj = compute_sell_adjustments(portfolio, ns_candidates)
    buy_adj = compute_buy_adjustments(portfolio, ns_candidates)
    print_sell_adjustments(sell_adj)
    print_buy_adjustments(buy_adj)
```

---

## Verification

### After Step 1:
```bash
python3 tools/support_parameter_sweeper.py --ticker CIFR --stage threshold
# Verify: composite $/month shown, per-period breakdown in output
```

### After Step 2:
```bash
python3 tools/neural_order_adjuster.py
# Verify: ALL pending sells shown (not just neural tickers)
# Verify: ALL pending buys shown
# Verify: reason chains include source + neural evidence
# Verify: multi-period data in reason when available
```

### After Step 3:
```bash
python3 tools/daily_analyzer.py --no-deploy --no-fitness --no-screen --no-recon
# Verify: adjustment tables appear after neural profile sections
```

---

## Files Summary

| File | Action | Lines |
| :--- | :--- | :--- |
| `tools/support_parameter_sweeper.py` | MODIFY — multi-period sweep, import compute_composite | ~40 |
| `tools/neural_support_discoverer.py` | MODIFY — unpack new return values from sweep_threshold | ~10 |
| `tools/neural_order_adjuster.py` | NEW — adjustment tables with reason chains | ~200 |
| `tools/daily_analyzer.py` | MODIFY — call adjuster inline | ~10 |
| **Total** | | **~260** |
