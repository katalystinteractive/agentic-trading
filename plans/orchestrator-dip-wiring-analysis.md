# Analysis: Single Orchestrator + Dip Sweep Wiring to Tournament

**Date**: 2026-04-05 (Sunday)

---

## Part A: Single Orchestrator

### Current State
7 separate Saturday cron entries fire at fixed times, hoping prior jobs finished:

```
09:00  universe_screener.py (standalone)
10:00  weekly_reoptimize.py (dip sweep + watchlist sweep + cluster + weights + candidate sweep)
11:30  resistance_parameter_sweeper.py --workers 8
12:15  bounce_parameter_sweeper.py --workers 8
13:15  entry_parameter_sweeper.py --workers 8
13:30  support_parameter_sweeper.py --stage slippage --workers 8
15:30  watchlist_tournament.py (standalone)
```

### Problem
- If weekly_reoptimize runs long (90 min instead of 70), resistance starts while support sweep is still writing to `support_sweep_results.json` — race condition
- If bounce runs long, entry starts before bounce finishes — not a data dependency issue but wastes CPU
- Tournament has a 2-hour safety buffer (15:30) which wastes time when sweeps finish by 13:40

### Solution
Move resistance/bounce/entry/slippage into `weekly_reoptimize.py` as new steps. Keep universe_screener and tournament as separate crons (different purposes).

**New Saturday pipeline:**
```
09:00  universe_screener.py (standalone — data source, runs independently)
10:00  weekly_reoptimize.py (ALL sweeps sequentially):
         Step 1: Dip parameter sweep (~15 min)
         Step 2: Watchlist support sweep (~45 min)
         Step 3: Clustering (~2 min)
         Step 4: Weight training (~2 min)
         Step 5: Overfitting + confidence checks (~1 min)
         Step 6: Candidate sweep Stage 1 (~2 min)
         Step 7: Resistance sweep --workers 8 (~35 min)
         Step 8: Bounce sweep --workers 8 (~50 min)
         Step 9: Entry sweep --workers 8 (~4 min)
         Step 10: Slippage sweep --workers 8 (~10 min)
         Step 11: Tournament (LAST — all data complete)
         Total: ~166 min (~2h 46m), finishes ~12:46
15:30  watchlist_tournament.py (safety re-run — idempotent, only acts if no prior run today)
```

### What Changes

**`weekly_reoptimize.py`**: Add 5 new step functions (resistance, bounce, entry, slippage, tournament). Each follows the existing `step_X()` pattern — subprocess.run, capture output, return (success, elapsed).

**`cron_neural_trading.txt`**: Remove 4 standalone sweep entries (resistance, bounce, entry, slippage). Keep universe_screener (09:00) and tournament (15:30 as safety net).

**Tournament idempotency**: Add check in `watchlist_tournament.py` — if `tournament_results.json` was already written today AND all 4 sweep files were modified today, skip execution (safety cron becomes no-op if orchestrator ran successfully). If sweep files are stale (orchestrator failed mid-pipeline), the safety cron should also skip to avoid running on partial data — better to have no tournament than a wrong one.

### Implementation

```python
# New steps in weekly_reoptimize.py (after step_candidate_sweep):

def step_resistance_sweep():
    """Run resistance parameter sweep for tracked + challengers."""
    cmd = [sys.executable, "tools/resistance_parameter_sweeper.py", "--workers", "8"]
    ...

def step_bounce_sweep():
    """Run bounce parameter sweep for tracked + challengers."""
    cmd = [sys.executable, "tools/bounce_parameter_sweeper.py", "--workers", "8"]
    ...

def step_entry_sweep():
    """Run entry parameter sweep for tracked + challengers."""
    cmd = [sys.executable, "tools/entry_parameter_sweeper.py", "--workers", "8"]
    ...

def step_slippage_sweep():
    """Run slippage + pullback sweep."""
    cmd = [sys.executable, "tools/support_parameter_sweeper.py", "--stage", "slippage", "--workers", "8"]
    ...
```

Each step: ~10 lines (subprocess call + timing + print). Total: ~50 lines.

Wire into main() after candidate sweep, before build_summary.

**Estimated lines**: ~60 (5 step functions + main() wiring + cron cleanup).

---

## Part B: Dip Sweep Wiring to Tournament

### Current State
- `parameter_sweeper.py` (dip strategy) runs inside weekly_reoptimize as Step 1
- Outputs to `data/sweep_results.json` with `stats.total_pnl`, `trades`, `wins`, `win_rate`
- **No `composite` field** — dip sweeper doesn't use `multi_period_scorer.compute_composite()`
- Tournament reads `stats.composite` from 4 files — dip file has no composite, so dip tickers score 0

### What Needs to Change

**Option 1: Full multi-period composite in parameter_sweeper.py** (CORRECT — aligns dip with surgical)
- Import `compute_composite` from `multi_period_scorer`
- Refactor sweep loop to run 4 periods (12/6/3/1 month) like surgical sweepers
- **Problem**: parameter_sweeper currently downloads ONE 60-day 5-min dataset and sweeps across it. Multi-period scoring requires 4 separate simulation windows. This is a **significant refactor** of the sweep loop — NOT just adding 20 lines. The sweep function structure would need to match support_parameter_sweeper's multi-period pattern.
- **Effort**: ~80-100 lines (refactor sweep loop + 4-period runs + composite computation)

**Option 2: Compute composite in tournament from raw stats** (HACKY — different metric)
- Tournament converts `total_pnl` to $/month estimate
- Different methodology than surgical composite — not apples-to-apples
- Not recommended

**Recommendation: Option 1.** The dip sweeper should produce the same composite metric as surgical sweepers so the tournament can compare fairly.

### Implementation for Option 1

In `parameter_sweeper.py`, after the sweep completes and best params are found per ticker:

```python
from multi_period_scorer import compute_composite

# Run 4-period scoring with best dip params
results_by_period = {}
for period_months in [12, 6, 3, 1]:
    result = sweep_with_params(ticker, best_params, period_months)
    results_by_period[period_months] = {
        "pnl": result["total_pnl"],
        "cycles": result["trades"],
        "win_rate": result["win_rate"],
    }
composite, _ = compute_composite(results_by_period)
entry["stats"]["composite"] = round(composite, 2)
```

**Problem**: `parameter_sweeper.py` sweeps across a single period (60 days), not 4 periods. It would need to run the best params across 12/6/3/1 month windows to produce a multi-period composite — same as surgical sweepers do.

**Option 2 (Recommended for Phase 1): Crude composite from existing data**
```python
entry["stats"]["composite"] = round(entry["stats"]["total_pnl"] / 2, 2)  # 60 days ≈ 2 months
```

This gives dip tickers a non-zero score for tournament ranking. **Important caveat**: This is NOT methodologically equivalent to surgical composites. Surgical composites use 4-period weighted scoring (12/6/3/1 month) with significance gating. Dip composite is a simple 2-month average from a single 60-day window. Comparisons are directional, not precise — a dip ticker scoring $30/mo may not be directly comparable to a surgical ticker scoring $30/mo.

**Acceptable for Phase 1** — gets DAI tickers into the tournament instead of scoring zero. Full multi-period refactor (Option 1, ~100 lines) is Phase 2 work.

### Tournament Changes

Add dip to `SWEEP_FILES`:
```python
SWEEP_FILES = {
    "dip": _ROOT / "data" / "sweep_results.json",
    "support": _ROOT / "data" / "support_sweep_results.json",
    ...
}
```

`load_all_sweeps()` already handles multiple files — no other changes needed. The `max(composites)` ranking in `compute_rankings()` automatically picks dip if it's the best strategy for a ticker.

### Universe Gap

Dip sweeper uses `_get_dip_candidates(portfolio)` — positions + watchlist with pending BUY only. No challengers. Surgical sweepers include tracked + top challengers.

For tournament comparison to be fair, dip sweeper should also include challengers. But this is a Phase 2 optimization — the immediate wire (adding composite + SWEEP_FILES entry) gives DAI tickers a score instead of zero.

---

## Combined Implementation

### Files Modified

| File | Change | Lines |
| :--- | :--- | :--- |
| `tools/weekly_reoptimize.py` | Add step_resistance/bounce/entry/slippage/tournament + main wiring | ~70 |
| `tools/parameter_sweeper.py` | Add crude composite field (`total_pnl / 2`) to output stats | ~5 |
| `tools/watchlist_tournament.py` | Add "dip" to SWEEP_FILES + idempotency check (sweep freshness) | ~15 |
| `cron_neural_trading.txt` | Remove 4 standalone sweep entries | -4 lines |
| **Total** | | **~90** |

### Implementation Order

1. Add 5 step functions to `weekly_reoptimize.py`
2. Wire into main() after candidate sweep
3. Add composite to `parameter_sweeper.py` output
4. Add "dip" to tournament SWEEP_FILES
5. Add idempotency check to tournament
6. Update cron: remove 4 standalone entries
7. Test: `python3 tools/weekly_reoptimize.py --dry-run`

---

## Risks

1. **Sequential pipeline longer than parallel** — All sweeps in one process takes ~166 min vs ~130 min parallel. Acceptable (finishes by 12:46 vs 13:40).

2. **One failure blocks all subsequent steps** — If resistance sweep crashes, bounce/entry/slippage/tournament don't run. Mitigation: wrap each step in try/except, log failure, continue to next step.

3. **Dip composite is crude** — `total_pnl / 2` is not multi-period weighted. Full fix requires refactoring parameter_sweeper to run 4-period scoring. Acceptable as Phase 1 wire — crude composite is better than zero composite.
