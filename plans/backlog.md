# Backlog — Known Issues & Improvements

---

## ~~BUG: Steps 7-10 silently skipped~~ — RESOLVED
**Status**: CLOSED (2026-04-11)
**Root cause**: The April 4 log was from the OLD code (pre-orchestrator commit of April 5). Steps 7-10 didn't exist yet. The April 11 run was the first with new code but was killed before reaching Steps 7-10.
**Fix applied**: Added `_run_sweep_step()` helper with start/end timestamps, stderr logging, flush. Step numbering fixed (tournament → STEP 11). Individual sweepers confirmed working (resistance exit code 0 in manual test).

---

## ~~BUG: Weekly reoptimize appears to run TWICE~~ — RESOLVED
**Status**: CLOSED (2026-04-11)
**Root cause**: The "second pass" in the log was from a manual sweep run on April 8-9 that wrote to the same log file (append mode). Not a cron double-fire.
**Fix applied**: Added run-once guard via `data/.reoptimize_guard` file (writes today's date, skips if already ran today). Same pattern as tournament idempotency.

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

## ~~IMPROVEMENT: Pipeline should log step start/end with timestamps~~ — RESOLVED
**Status**: CLOSED (2026-04-11)
**Fix applied**: New `_run_sweep_step()` helper logs step number, name, start time, end time, duration, and stderr on failure. All 4 surgical sweep steps use this helper.
