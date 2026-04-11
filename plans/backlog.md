# Backlog — Known Issues & Improvements

---

## BUG: Steps 7-10 (resistance/bounce/entry/slippage) silently skipped in weekly pipeline
**Priority**: HIGH
**Date identified**: 2026-04-11
**Evidence**: First Saturday run of consolidated orchestrator showed Steps 1-6 → Tournament, completely skipping resistance/bounce/entry/slippage sweeps. No error, no warning, no log output. Steps ARE wired in main() (lines 560-565) but produced zero output in the log.
**Impact**: Tournament ran on stale resistance/bounce/entry data from prior weeks. Sweep findings not refreshed.
**Root cause**: TBD — need to investigate whether the step functions ran but had empty stdout, or were somehow skipped by the control flow.
**Fix needed**: Add explicit logging at the START of each step function (before subprocess.run), verify the loop at lines 560-565 actually executes, ensure stdout is flushed.

---

## BUG: Weekly reoptimize appears to run TWICE (pipeline restarts after completion)
**Priority**: HIGH
**Date identified**: 2026-04-11
**Evidence**: Log shows "Total pipeline time: 4643s" then immediately "STEP 1: Parameter Sweep" starts again. The neural_watchlist_sweeper is running a SECOND pass. Either the cron triggered twice (unlikely — single entry at 10:00) or the script loops internally.
**Root cause**: TBD — check if weekly_reoptimize.py has any loop/retry logic, or if the cron entry fired twice due to the old Stage 1+2 sweep background task still running.
**Fix needed**: Add run-once guard (check if already ran today, similar to tournament idempotency).

---

## DESIGN: Extreme overlap between weekly_reoptimize steps and standalone sweepers
**Priority**: MEDIUM
**Date identified**: 2026-04-11
**Description**: The weekly pipeline runs:
- Step 1: `parameter_sweeper.py` (dip sweep)
- Step 2: `neural_watchlist_sweeper.py` — which INTERNALLY runs `support_parameter_sweeper.py` Stage 1+2
- Steps 7-10: `resistance/bounce/entry/slippage_parameter_sweeper.py`

But `neural_watchlist_sweeper.py` (Step 2) already runs support Stage 1+2 for ALL tracked tickers. Then if Steps 7-10 ran, they would ALSO call support sweep functions (they read support_sweep_results.json for base params). The support sweep data gets generated in Step 2 and consumed in Steps 7-10 — this is correct ordering but the execution is wasteful:
- Step 2 sweeps ALL tickers with 288 combos (Stage 1+2)
- Steps 7-10 each sweep 37 tickers with their own combos
- Total: ~500+ minutes of sweep computation per Saturday

**Question**: Should Step 2 (neural_watchlist_sweeper) be replaced by a direct call to `support_parameter_sweeper.py --stage both --workers 8`? The neural_watchlist_sweeper adds clustering and profiling on top, but that's handled separately in Steps 3-4 (ticker_clusterer, weight_learner). Need to audit what neural_watchlist_sweeper does that support_parameter_sweeper + Steps 3-4 don't already cover.

---

## IMPROVEMENT: Pipeline should log step start/end with timestamps
**Priority**: LOW
**Date identified**: 2026-04-11
**Description**: Current step functions only log completion. Should log "Starting Step N: {name}" at the beginning and "Completed Step N in Xs" at the end. Currently impossible to tell from logs which step is running or when transitions happen.
