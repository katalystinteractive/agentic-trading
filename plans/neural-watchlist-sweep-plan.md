# Implementation Plan: Guaranteed Watchlist Profiles + Better Reason Chains

**Date**: 2026-03-29
**Source analysis**: `plans/neural-watchlist-sweep-analysis.md` (verified, 11/12 correct, 1 fixed)
**Goal**: Every watchlist ticker gets a neural profile. Reason chains show full evidence, not "Neural P/L: $324".

---

## Scope

| Step | What | File | Type | Lines |
| :--- | :--- | :--- | :--- | :--- |
| 1 | Watchlist sweep step in weekly pipeline | `weekly_reoptimize.py` | MODIFY | ~30 |
| 2 | Standalone watchlist sweep tool | `neural_watchlist_sweeper.py` | NEW | ~80 |
| 3 | Add watchlist profiles to priority chains | `broker_reconciliation.py`, `graph_builder.py`, `shared_utils.py` | MODIFY | ~30 |
| 4 | Fix reason chains in order adjuster | `neural_order_adjuster.py` | MODIFY | ~40 |

**Total: ~180 lines**

---

## Step 1: Watchlist Sweep Step in Weekly Pipeline

### 1.1 Add `step_watchlist_sweep()` to `weekly_reoptimize.py`

**Where**: After the existing dip sweep step, before clustering.

```python
def step_watchlist_sweep():
    """Sweep support params for ALL watchlist + position tickers."""
    print("=" * 60)
    print("STEP: Watchlist Support Sweep")
    print("=" * 60)

    cmd = [sys.executable, "tools/neural_watchlist_sweeper.py"]
    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_ROOT))
    elapsed = time.time() - t0

    print(result.stdout)
    success = result.returncode == 0
    print(f"  Watchlist sweep {'completed' if success else 'FAILED'} in {elapsed:.0f}s\n")
    return success, elapsed
```

### 1.2 Wire into main()

```python
# After existing dip sweep:
if args.strategy == "dip":
    sweep_ok, t = step_sweep(...)
elif args.strategy == "support":
    sweep_ok, t = step_sweep(...)

# Always run watchlist sweep (both strategies need it)
wl_ok, wl_t = step_watchlist_sweep()
timings["watchlist_sweep"] = wl_t
```

---

## Step 2: Standalone Watchlist Sweep Tool

### 2.1 New file: `tools/neural_watchlist_sweeper.py`

**Purpose**: Sweep support params for every position + watchlist ticker. Write `data/neural_watchlist_profiles.json`.

```python
"""Neural Watchlist Sweeper — guaranteed profiles for every tracked ticker.

Runs support parameter sweep on ALL tickers in portfolio.json positions +
watchlist. Ensures no ticker falls back to 'standard 6.0%' in the daily analyzer.

Usage:
    python3 tools/neural_watchlist_sweeper.py              # full sweep
    python3 tools/neural_watchlist_sweeper.py --workers 8   # parallel
"""

def main():
    # 1. Load ALL tracked tickers
    portfolio = _load_portfolio()
    tickers = set(portfolio.get("positions", {}).keys())
    tickers.update(portfolio.get("watchlist", []))
    tickers = sorted(tickers)

    # 2. Ensure data exists (collect if missing)
    for tk in tickers:
        _collect_once(tk, max(SWEEP_PERIODS))

    # 3. Sweep each ticker (reuse sweep_threshold from support_parameter_sweeper)
    results = {}
    for tk in tickers:
        params, result, composite, periods = sweep_threshold(tk)
        if params and result:
            results[tk] = {
                "params": params,
                "stats": {...},
                "composite": composite,
                "periods": periods,
            }

    # 4. Write to data/neural_watchlist_profiles.json
    output = {"_meta": {...}, "candidates": [...]}
    with open(WATCHLIST_PROFILES_PATH, "w") as f:
        json.dump(output, f, indent=2)
```

**Key**: Uses the SAME `sweep_threshold()` from `support_parameter_sweeper.py` (multi-period, wick cache). Same quality as the candidate discovery — just scoped to the watchlist.

**Output schema**: Uses a `candidates` array wrapper like `neural_support_candidates.json`, but each candidate has: `ticker`, `params`, `stats`, `composite`, `periods`. This is a subset of the candidate discovery schema (omits `features`, `cross_validation`, `cluster`). The downstream consumers (`_load_profiles`, `get_ticker_pool`) only read `params.sell_default` and `params.active_pool`, so the schema difference doesn't affect functionality.

**Error handling**: Tickers that fail data collection or sweep (insufficient history, delisted, yfinance error) are logged and reported in the summary — not silently dropped:

```python
skipped = []
for tk in tickers:
    try:
        params, result, composite, periods = sweep_threshold(tk)
        if params and result:
            results[tk] = {...}
        else:
            skipped.append((tk, "no profitable combo"))
    except Exception as e:
        skipped.append((tk, str(e)))

if skipped:
    print(f"\nSkipped {len(skipped)} tickers:")
    for tk, reason in skipped:
        print(f"  {tk}: {reason}")
```

---

## Step 3: Add Watchlist Profiles to Priority Chains

### 3.1 Three files, same pattern

In `broker_reconciliation.py::_load_profiles()`, `graph_builder.py` (lines 182-196), and `shared_utils.py::get_ticker_pool()`:

Insert check for `data/neural_watchlist_profiles.json` AFTER existing sources, BEFORE `neural_support_candidates.json`:

```python
# Priority:
# 1. ticker_profiles.json (dip strategy, existing)
# 2. neural_watchlist_profiles.json (NEW — guaranteed for every tracked ticker)
# 3. neural_support_candidates.json (candidate discovery)

# Add after existing ticker_profiles check:
try:
    wl_path = _ROOT / "data" / "neural_watchlist_profiles.json"
    if wl_path.exists():
        with open(wl_path) as f:
            wl_data = json.load(f)
        for c in wl_data.get("candidates", []):
            tk = c["ticker"]
            if tk not in profiles:
                profiles[tk] = {}
            if not profiles[tk].get("optimal_target_pct"):
                profiles[tk]["optimal_target_pct"] = c["params"].get("sell_default")
                profiles[tk]["_neural_source"] = "neural_watchlist"
except (FileNotFoundError, json.JSONDecodeError, KeyError):
    pass
```

Same pattern for `get_ticker_pool()` — check watchlist profiles for pool sizes before neural_support_candidates.

**Backward compat**: If `neural_watchlist_profiles.json` doesn't exist (hasn't run yet), falls through to existing chain. Zero impact until first sweep.

---

## Step 4: Fix Reason Chains in Order Adjuster

### 4.1 Replace `_build_sell_reason()`

```python
def _build_sell_reason(ticker, source, rec_price, avg_cost, ns_candidates):
    """Full reason chain: priority path + evidence + vs-default."""
    parts = []

    # Priority path
    parts.append(f"Source: {source}")

    # Evidence when neural
    candidate = ns_candidates.get(ticker)
    if candidate and "neural" in str(source):
        periods = candidate.get("periods")
        if periods:
            period_parts = []
            for months in [12, 6, 3, 1]:
                p = periods.get(str(months)) or periods.get(months, {})
                if p and p.get("pnl"):
                    period_parts.append(
                        f"{months}mo: ${p['pnl']:.0f}/{p.get('cycles', 0)}cyc/"
                        f"{p.get('win_rate', 0):.0f}%WR")
            if period_parts:
                parts.append(" | ".join(period_parts))
        composite = candidate.get("composite")
        if composite:
            parts.append(f"Composite: ${composite:.1f}/mo")

    # vs-default comparison
    default_sell = round(avg_cost * 1.06, 2)
    if abs(rec_price - default_sell) > 0.05:
        diff = rec_price - default_sell
        parts.append(f"vs default 6%: ${default_sell:.2f} ({'+' if diff > 0 else ''}${diff:.2f})")

    return " | ".join(parts)
```

### 4.2 Replace `_build_buy_reason()`

```python
def _build_buy_reason(ticker, pool, bullets, rec_shares, current_shares,
                      buy_price, pool_source, ns_candidates):
    """Full reason chain: pool source + sizing math + evidence."""
    parts = []

    # Pool source + sizing math
    per_bullet = round(pool / bullets, 0)
    parts.append(f"${pool}/{bullets}b=${per_bullet}/bullet ({pool_source})")

    # Sizing explanation
    parts.append(f"${per_bullet}/${buy_price:.2f}={rec_shares}sh")

    # Neural evidence
    candidate = ns_candidates.get(ticker)
    if candidate:
        composite = candidate.get("composite")
        if composite:
            parts.append(f"Composite: ${composite:.1f}/mo")
        elif candidate.get("pnl"):
            pnl = candidate["pnl"]
            wr = candidate.get("win_rate", 0)
            parts.append(f"P/L: ${pnl:.0f} ({wr}%WR)")

    # vs-default comparison
    default_shares = max(1, int(300 / 5 / buy_price))
    if rec_shares != default_shares:
        parts.append(f"vs default $300/5b={default_shares}sh")

    return " | ".join(parts)
```

### 4.3 Update callers to pass additional args

In `compute_sell_adjustments()`, update the call at line ~128:
```python
# Current:
reason = _build_sell_reason(tk, source, ns_candidates)
# Changed to:
reason = _build_sell_reason(tk, source, rec_sell, avg, ns_candidates)
```

In `compute_buy_adjustments()`, update the call at line ~168:
```python
# Current:
reason = _build_buy_reason(tk, pool, bullets, pool_source, ns_candidates)
# Changed to:
reason = _build_buy_reason(tk, pool, bullets, rec_shares, current_shares,
                           buy_price, pool_source, ns_candidates)
```

---

## Verification

### After Step 2:
```bash
python3 tools/neural_watchlist_sweeper.py --workers 4
# Verify: data/neural_watchlist_profiles.json created
# Verify: every position + watchlist ticker has a profile
# Verify: profiles have composite and periods data
```

### After Step 3:
```bash
python3 -c "
from tools.broker_reconciliation import _load_profiles, compute_recommended_sell
profiles = _load_profiles()
# CLF should now have a profile (was 'standard 6.0%' before)
sell, src = compute_recommended_sell('CLF', 8.82, {}, profiles)
print(f'CLF: {sell} ({src})')
# Should show neural_watchlist source, not 'standard 6.0%'
"
```

### After Step 4:
```bash
python3 tools/neural_order_adjuster.py --sells-only
# Verify: reasons show full priority path + evidence + vs-default
# Verify: no more bare "Neural P/L: $324"
```

---

## Files Summary

| File | Action | Lines |
| :--- | :--- | :--- |
| `tools/neural_watchlist_sweeper.py` | NEW — sweep every tracked ticker | ~80 |
| `tools/weekly_reoptimize.py` | MODIFY — add watchlist sweep step | ~30 |
| `tools/broker_reconciliation.py` | MODIFY — add watchlist profiles to priority | ~10 |
| `tools/graph_builder.py` | MODIFY — same priority insert | ~10 |
| `tools/shared_utils.py` | MODIFY — same priority insert for pools | ~10 |
| `tools/neural_order_adjuster.py` | MODIFY — richer reason chains | ~40 |
| **Total** | | **~180** |
