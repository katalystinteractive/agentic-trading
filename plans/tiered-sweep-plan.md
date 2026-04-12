# Implementation Plan: Tiered Sweep Pipeline — Scaling to 500+

**Date**: 2026-04-12
**Source**: `plans/tiered-sweep-scaling-analysis.md` (verified, v2)

---

## Context

The Saturday pipeline sweeps 61 of 1,594 universe passers (3.8% coverage). 1,537 tickers have never been evaluated. To scale to 500+ watchlist, we need a tiered approach: fast pre-screen of ALL passers, detailed sweep of top candidates, advanced optimization of the best.

**Critical constraint:** Existing sweep results (`data/support_sweep_results.json`, `data/sweep_results.json`, etc.) drive daily decisions via daily_analyzer, bullet_recommender, and sell_target_calculator. The pre-screen must write to its OWN output file and NEVER modify existing sweep result files.

---

## Step 1: Create `tools/universe_prescreener.py` (NEW, ~200 lines)

### Purpose
Run Stage 1 threshold sweep (30 combos × 4 periods) across ALL universe passers. Produces composite $/month ranking of the full universe.

### Architecture
```python
"""Universe pre-screener — Stage 1 sweep across all universe passers.

Runs the threshold grid (30 combos × 4 periods = 120 sims per ticker)
for every ticker in data/universe_screen_cache.json. Produces composite
$/month scores using the same multi_period_scorer as the full sweeper.

Output: data/universe_prescreen_results.json (OWN FILE — never touches
existing sweep data that drives daily decisions).

Usage:
    python3 tools/universe_prescreener.py                    # full run
    python3 tools/universe_prescreener.py --workers 8        # parallel
    python3 tools/universe_prescreener.py --top 200          # show top N
    python3 tools/universe_prescreener.py --cached           # use cached results
"""
```

### Core function
```python
def prescreen_ticker(ticker):
    """Run Stage 1 (30 combos × 4 periods) for a single ticker.

    Uses the same _collect_once / _simulate_with_config pattern as
    support_parameter_sweeper.py. Downloads price data once per ticker,
    then runs each period with a SHARED wick cache across combos
    (fixes the per-combo cache reset in the current sweeper).

    Returns dict with ticker, composite, best_params, period_details.
    """
    from support_parameter_sweeper import (
        _collect_once, _simulate_with_config, THRESHOLD_GRID, SWEEP_PERIODS
    )
    from multi_period_scorer import compute_composite

    data_dir = _collect_once(ticker, max(SWEEP_PERIODS))
    if data_dir is None:
        return None

    results_by_period = {}
    for months in SWEEP_PERIODS:
        wick_cache = {}  # SHARED across all 30 combos for this period
        best = {"pnl": float("-inf"), "params": None, "trades": 0, "cycles": 0, "win_rate": 0}
        for sell_default in THRESHOLD_GRID["sell_default"]:
            for cat_hard in THRESHOLD_GRID["cat_hard_stop"]:
                overrides = {"sell_default": sell_default, "cat_hard_stop": cat_hard}
                result = _simulate_with_config(
                    ticker, months, overrides, data_dir=data_dir, wick_cache=wick_cache
                )
                if result and result.get("pnl", float("-inf")) > best["pnl"]:
                    best = {
                        "pnl": result["pnl"],
                        "params": overrides,
                        "sells": result.get("sells", 0),
                        "cycles": result.get("cycles", 0),
                        "win_rate": result.get("win_rate", 0),
                    }
        results_by_period[months] = best

    composite, details = compute_composite(results_by_period)
    return {
        "ticker": ticker,
        "composite": round(composite, 2),
        "best_params": best["params"],
        "details": details,
        "sells_12mo": results_by_period.get(12, {}).get("trades", 0),
    }
```

### Parallel execution
```python
def run_prescreen(tickers, workers=8):
    """Pre-screen all tickers in parallel. Returns ranked list."""
    results = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(prescreen_ticker, tk): tk for tk in tickers}
        for future in as_completed(futures):
            try:
                r = future.result()
                if r and r["composite"] > 0:
                    results.append(r)
            except Exception:
                pass
    return sorted(results, key=lambda x: -x["composite"])
```

### Output file: `data/universe_prescreen_results.json`
```json
{
    "_meta": {
        "source": "universe_prescreener.py",
        "updated": "2026-04-12",
        "tickers_screened": 1594,
        "tickers_with_signal": 420,
        "top_composite": 163.4
    },
    "rankings": [
        {"ticker": "APP", "composite": 163.4, "best_params": {"sell_default": 6.0, "cat_hard_stop": 25}, "sells_12mo": 8},
        {"ticker": "EOSE", "composite": 38.2, ...},
        ...
    ]
}
```

### What this file does NOT do
- Does NOT write to `data/support_sweep_results.json`
- Does NOT write to any existing sweep result file
- Does NOT modify `portfolio.json`
- Does NOT affect daily_analyzer, bullet_recommender, or sell_target_calculator
- Is purely informational until Tier 2 promotes tickers

**~200 lines.**

---

## Step 2: Verify `_collect_once` and `_simulate_with_config` are importable

**File**: `tools/support_parameter_sweeper.py`

### Check
These functions need to be importable by the prescreener. Verify they don't depend on module-level state that fails at import time (e.g., argparse, global downloads).

Current signatures:
- `_collect_once(ticker, months)` — downloads price data, returns data_dir path
- `_simulate_with_config(ticker, data_dir, months, overrides, wick_cache=None, ...)` — runs one simulation, returns stats dict

Both are internal functions (prefixed `_`). They should work when imported since they don't trigger side effects at module load.

**~0 lines changed** (verification only). If import fails, extract the functions into a shared module.

---

## Step 3: Wire Tier 1 into `tools/weekly_reoptimize.py`

**File**: `tools/weekly_reoptimize.py`
**Location**: After Step 0 (wick refresh), before current Step 1 (dip sweep)

### New step: Tier 1 Pre-Screen
```python
# Step 0.5: Tier 1 — Pre-screen entire universe
print("=" * 60)
print("STEP 0.5: Universe Pre-Screen (Tier 1)")
print(f"  Started: {time.strftime('%H:%M:%S')}")
print("=" * 60, flush=True)
t0_prescreen = time.time()
try:
    result = subprocess.run(
        [sys.executable, "tools/universe_prescreener.py", "--workers", "8"],
        cwd=str(_ROOT), capture_output=True, text=True, timeout=3600,
    )
    if result.returncode != 0:
        print(f"  *Pre-screen failed: {result.stderr[:200]}*", file=sys.stderr)
    else:
        # Count results
        import json as _json
        _prescreen_path = _ROOT / "data" / "universe_prescreen_results.json"
        if _prescreen_path.exists():
            with open(_prescreen_path) as _f:
                _ps = _json.load(_f)
            _n = len(_ps.get("rankings", []))
            print(f"  Pre-screened: {_n} tickers with positive composite")
except subprocess.TimeoutExpired:
    print("  *Pre-screen timed out (1 hour)*", file=sys.stderr)
except Exception as e:
    print(f"  *Pre-screen error: {e}*", file=sys.stderr)
_prescreen_elapsed = time.time() - t0_prescreen
print(f"  Completed in {_prescreen_elapsed:.0f}s ({_prescreen_elapsed/60:.1f} min)")
print(f"  Finished: {time.strftime('%H:%M:%S')}\n", flush=True)
timings["prescreen"] = _prescreen_elapsed
```

### Modify Tier 2 pool: Top 200 from pre-screen feed into support sweep

Current Step 2 sweeps `_tracked + challengers` (~45 tickers). Change to:
1. Keep all tracked tickers (must always be swept)
2. Add top N from pre-screen that aren't already tracked
3. Total Tier 2 pool: tracked + top pre-screen candidates (capped at 200)

```python
# Build Tier 2 pool: tracked tickers + top pre-screen candidates
# Write tickers to a file that support_parameter_sweeper.py reads via --tickers-file
_tier2_pool = list(_tracked)
_prescreen_path = _ROOT / "data" / "universe_prescreen_results.json"
if _prescreen_path.exists():
    with open(_prescreen_path) as f:
        _ps = json.load(f)
    _tracked_set = set(_tracked)
    for r in _ps.get("rankings", []):
        if len(_tier2_pool) >= 200:
            break
        if r["ticker"] not in _tracked_set:
            _tier2_pool.append(r["ticker"])

# Write pool to temp file for sweeper
_tier2_file = _ROOT / "data" / ".tier2_pool.json"
with open(_tier2_file, "w") as f:
    json.dump(_tier2_pool, f)
```

**Also requires:** Add `--tickers-file` argument to `support_parameter_sweeper.py` that reads ticker list from a JSON file instead of computing its own pool. The subprocess call in `step_watchlist_sweep()` passes `--tickers-file data/.tier2_pool.json`.

```python
# In step_watchlist_sweep(), add --tickers-file to the subprocess call:
return _run_sweep_step("2", "Support Sweep (Stage 1+2)",
    [sys.executable, "tools/support_parameter_sweeper.py",
     "--stage", "both", "--workers", "8",
     "--tickers-file", str(_ROOT / "data" / ".tier2_pool.json")])
```

**In `support_parameter_sweeper.py`**, add to argparse:
```python
parser.add_argument("--tickers-file", type=str, default=None,
                    help="JSON file with ticker list (overrides default pool)")
```
And in the ticker loading logic, if `--tickers-file` is provided, load from that file instead of computing the tracked+challengers pool.

**~35 lines.**

---

## Step 4: Read pre-screen results in daily_analyzer Part 6

**File**: `tools/daily_analyzer.py`
**Location**: Part 6 (New Candidate Screening)

### Current behavior
Part 6 runs `surgical_filter.py` or `universe_screener.py --cached` to find candidates. Shows a short list of screened tickers.

### Enhancement
After existing screening output, add a "Pre-Screen Rankings" section showing top untracked tickers from pre-screen results:

```python
# After existing Part 6 screening output
_prescreen_path = _ROOT / "data" / "universe_prescreen_results.json"
if _prescreen_path.exists():
    try:
        with open(_prescreen_path) as f:
            ps = json.load(f)
        rankings = ps.get("rankings", [])
        # Filter to untracked tickers
        # Note: in run_candidate_screening(), portfolio is loaded via data = _load()
        data = _load()
        tracked = set(data.get("watchlist", [])) | set(data.get("positions", {}).keys())
        untracked = [r for r in rankings if r["ticker"] not in tracked][:15]
        if untracked:
            print("\n### Universe Pre-Screen — Top Untracked")
            print("| Rank | Ticker | Composite $/mo | Trades (12mo) | Best Sell% | Best Stop% |")
            print("| :--- | :--- | :--- | :--- | :--- | :--- |")
            for i, r in enumerate(untracked, 1):
                bp = r.get("best_params", {})
                print(f"| {i} | {r['ticker']} | ${r['composite']:.1f} | "
                      f"{r.get('trades_12mo', '?')} | "
                      f"{bp.get('sell_default', '?')}% | {bp.get('cat_hard_stop', '?')}% |")
    except (json.JSONDecodeError, KeyError):
        pass
```

**~20 lines.**

---

## Step 5: Expand tournament pool

**File**: `tools/watchlist_tournament.py`
**Location**: In `load_all_sweeps()` or `compute_rankings()`

### Current behavior
Tournament ranks tickers that appear in sweep result files (tracked + challengers from sweeps).

### Enhancement
After loading sweep results, also load pre-screen results for tickers not already in the sweep pool. These get a composite score but no optimized params — they compete on pre-screen composite only.

```python
# After loading all sweep files, supplement with pre-screen rankings
_prescreen_path = _ROOT / "data" / "universe_prescreen_results.json"
if _prescreen_path.exists():
    try:
        with open(_prescreen_path) as f:
            ps = json.load(f)
        for r in ps.get("rankings", []):
            tk = r["ticker"]
            if tk not in all_sweeps:
                # Must match existing format: {strategy_name: composite_float}
                # compute_rankings uses max(composites, key=composites.get)
                all_sweeps[tk] = {"prescreen": r["composite"]}
    except (json.JSONDecodeError, KeyError):
        pass
```

**~15 lines.**

---

## Safety: What stays untouched

These files drive daily decisions and are NOT modified by the pre-screener:

| File | Owner | Used By | Protected |
| :--- | :--- | :--- | :--- |
| `data/support_sweep_results.json` | support_parameter_sweeper | bullet_recommender, daily_analyzer, sell_target_calculator | ✅ Never touched by prescreener |
| `data/sweep_results.json` | parameter_sweeper (dip) | neural_dip_evaluator, daily_analyzer | ✅ Never touched |
| `data/resistance_sweep_results.json` | resistance_sweeper | backtest_engine, bullet_recommender | ✅ Never touched |
| `data/bounce_sweep_results.json` | bounce_sweeper | backtest_engine | ✅ Never touched |
| `data/entry_sweep_results.json` | entry_sweeper | wick_offset_analyzer, proximity_monitor | ✅ Never touched |
| `data/regime_exit_sweep_results.json` | regime_exit sweeper | daily_analyzer | ✅ Never touched |
| `portfolio.json` | portfolio_manager | everything | ✅ Never touched by prescreener |

The pre-screener writes ONLY to `data/universe_prescreen_results.json`.

Tier 2 (existing support_parameter_sweeper.py) DOES write to `data/support_sweep_results.json` — but only merges new ticker results into the existing dict. Existing tracked ticker params are preserved/updated (same behavior as today, just with a larger pool).

---

## Files Modified/Created

| File | Action | Lines |
| :--- | :--- | :--- |
| `tools/universe_prescreener.py` | NEW | ~200 |
| `tools/weekly_reoptimize.py` | MODIFY | ~40 (add Tier 1 step, expand Tier 2 pool, pass tickers file) |
| `tools/support_parameter_sweeper.py` | MODIFY | ~15 (add --tickers-file arg, load from file) |
| `tools/daily_analyzer.py` | MODIFY | ~20 (pre-screen rankings in Part 6) |
| `tools/watchlist_tournament.py` | MODIFY | ~10 (expand tournament pool) |
| `data/universe_prescreen_results.json` | NEW (output) | — |
| **Total** | | **~285** |

---

## Implementation Order

1. Step 2: Verify imports (quick check, no code)
2. Step 1: Create universe_prescreener.py
3. Test: `python3 tools/universe_prescreener.py --workers 8 --top 20` — verify output
4. Step 3: Wire into weekly_reoptimize.py
5. Step 4: Daily analyzer pre-screen section
6. Step 5: Tournament pool expansion
7. Run tests: `python3 -m pytest tests/ -v`
8. System graph update

---

## Verification

1. **Pre-screener runs**: `python3 tools/universe_prescreener.py --workers 8 --top 20` — shows top 20 by composite
2. **Output file exists**: `cat data/universe_prescreen_results.json | python3 -m json.tool | head -20`
3. **Existing data untouched**: `git diff data/support_sweep_results.json` — no changes
4. **Daily analyzer shows rankings**: `python3 tools/daily_analyzer.py --no-recon --no-perf` — Part 6 includes pre-screen table
5. **Tournament expanded**: Pre-screen tickers appear in tournament rankings
6. **Pipeline integration**: Weekly reoptimize includes Step 0.5
7. **Tests pass**: `python3 -m pytest tests/ -v`
