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

## ~~DESIGN: Extreme overlap between weekly_reoptimize steps and standalone sweepers~~ — RESOLVED
**Status**: CLOSED (2026-04-11)
**Root cause**: `neural_watchlist_sweeper.py` ran the same Stage 1+2 as `support_parameter_sweeper.py` but wrote to a separate file (`neural_watchlist_profiles.json`). Both produce identical params (sell_default, pools, bullets, tiers). The watchlist sweeper also used the OLD grid [3,5,7] instead of the expanded [1,2,3,4,5,7].
**Fix applied**: Replaced Step 2 with direct call to `support_parameter_sweeper.py --stage both --workers 8`. This uses the expanded grid, writes to the canonical `support_sweep_results.json`, and eliminates the redundant `neural_watchlist_profiles.json` path. Clustering (Step 3) and weight training (Step 4) remain separate — they read dip sweep output, not support sweep output.

---

## ~~IMPROVEMENT: Pipeline should log step start/end with timestamps~~ — RESOLVED
**Status**: CLOSED (2026-04-11)
**Fix applied**: New `_run_sweep_step()` helper logs step number, name, start time, end time, duration, and stderr on failure. All 4 surgical sweep steps use this helper.
