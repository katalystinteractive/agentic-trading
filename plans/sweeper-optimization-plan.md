# Sweeper Optimization Plan

**Goal:** Reduce `weekly_reoptimize.py` total pipeline runtime by an estimated **1–2 hours** (currently trending toward 10+ hours on the upgraded 200-ticker Tier 2 pool) by eliminating the redundancies identified in the verified sweeper audit.

**Source analysis:** verified against code in 3 verify-analysis iterations; 7 corrections applied before convergence.

**Scope:** 5 standalone sweeper files (`parameter_sweeper.py`, `support_parameter_sweeper.py`, `resistance_parameter_sweeper.py`, `bounce_parameter_sweeper.py`, `entry_parameter_sweeper.py`) plus orchestrator `tools/weekly_reoptimize.py`. Out of scope: the `universe_prescreener.py` batch-download path (already efficient) and the already-correct cache plumbing inside `_simulate_with_config`.

---

## Fixes, ordered by implementation sequence

### Fix A — `step_sweep` auto-uses cache when fresh (trivial, instant)

**File:** `tools/weekly_reoptimize.py`

**Change:** `step_sweep(use_cached=args.skip_download, ...)` on line 633 becomes:
```python
_cache_pkl = _ROOT / "data" / "backtest" / "intraday_5min_60d.pkl"
_cache_fresh = _cache_pkl.exists() and (
    (time.time() - _cache_pkl.stat().st_mtime) / 3600 < 168  # 7 days
)
sweep_ok, t = step_sweep(
    use_cached=(args.skip_download or _cache_fresh),
    strategy=args.strategy,
)
```

**Rationale:** The 5-min intraday cache is refreshed only when `parameter_sweeper.py` itself runs (Saturday pipeline). Between runs, it's simply stale until the next pipeline touches it. Reusing a <7-day-old cache on the next Saturday saves the ~1–2 min re-download without changing data freshness semantics — we're just skipping a redundant refetch of data that the cache already has. User can still force a full refresh by passing `--skip-download` in reverse (i.e., by deleting the pkl before run, since `--skip-download` is already the code path we're defaulting to).

**Risk:** Low. The existing `--cached` code path in `parameter_sweeper.py` is already exercised by manual runs. One edge case: the freshness check is `_cache_pkl.exists() and (age < 7d)` — it does NOT validate pkl integrity. If the file is empty/truncated/corrupted but fresh, Fix A would silently reuse it. Mitigation: if this ever bites, delete the pkl manually; the next run re-downloads. Add a size-sanity check (`_cache_pkl.stat().st_size > 1024`) if we see problems in practice. Not adding the try/except pickle.load guard by default — it's overkill for a pipeline whose other components will surface the error immediately on first read attempt.

**Verification:** confirm log prints "Using cached 5-min data" or equivalent on subsequent runs.

**Estimated saving:** 1–2 min per run.

---

### Fix B — Hoist `wick_cache` above the combo loop in 4 sweepers (low complexity, biggest ROI per LOC)

**Files:**
1. `tools/resistance_parameter_sweeper.py` — hoist `period_wick_cache = {}` (currently line 112, **inside the period loop** which is nested inside the combo loop) to outside the combo loop, turning it into a ticker-scoped cache (can rename to `wick_cache` at the same time for clarity).
2. `tools/bounce_parameter_sweeper.py` — hoist `period_wick_cache = {}` (currently line 104, inside the period loop) to outside the combo loop.
3. `tools/entry_parameter_sweeper.py` — hoist `wick_cache = {}` (currently line 90, inside combo loop but already shared across periods within that combo — so entry is less broken than resistance/bounce, but still reruns wick work for every new combo) to outside the combo loop.
4. `tools/support_parameter_sweeper.py` `sweep_execution()` — replace the per-`(pool, bullets)` group `wick_cache` (currently line 304) with one ticker-scoped cache shared across all combos in that sweep call.

**Current cache scopes (for context):**
- Resistance/bounce: reset **per period** (worst — ~4× wasted recompute per combo).
- Entry: reset **per combo** but reused across periods within that combo (better — only combos-worth of recompute wasted).
- Support sweep_execution: per-`(pool, bullets)` group (middle ground).
- Post-fix: all four share a single ticker-scoped cache across every combo × period, matching the entry sweeper's current best-case behavior and extending it further.

**Invariant to preserve:** wick analysis key = `(ticker, support_level, period)`. Strategy params do NOT enter the key. Verified via reading `_simulate_with_config` — `wick_cache` is passed through to `run_simulation` and keyed on price/level, not strategy params.

**Risk:** Low. If the cache key is accidentally strategy-dependent, we'd see different results. Mitigation: run a single-ticker smoke test comparing pre-fix and post-fix simulation output before running the full sweep.

**Verification:** One smoke-test run of `support_parameter_sweeper.py --ticker CIFR --stage both` before/after Fix B; `sweep_results.json` CIFR entry should be byte-identical.

**Estimated saving:** 20–30 min (resistance dominates with 54 combos × ~200 tickers of redundant wick work).

---

### Fix C — Cross-sweeper early exit: filter downstream pools to profitable-at-support tickers (low complexity, compound win)

**Files:**
1. `tools/weekly_reoptimize.py` — after STEP 2 (support sweep) completes, read `data/support_sweep_results.json`, extract profitable tickers (`pnl > 0`), write `data/.profitable_tier2_pool.json`.
2. `tools/weekly_reoptimize.py` — change STEP 7/8/9/10 invocations to use `--tickers-file data/.profitable_tier2_pool.json` instead of `.tier2_pool.json` (or pass the new file via the existing `_tier2_args()` helper).
3. New helper in `weekly_reoptimize.py`: `_build_profitable_pool() -> Path` — runs between STEP 2 and STEP 7.

**Fallback:** if `support_sweep_results.json` is missing or empty, fall back to the full Tier 2 pool so the pipeline doesn't wedge.

**Risk:** A ticker that's unprofitable on support might be profitable on resistance/bounce alone. This is a real risk — we would miss optimization opportunities for such tickers.

**Mitigation:** Start conservative — filter only tickers with `stats.trades == 0` (truly no activity), not just `pnl <= 0`. A ticker with trades but losses on support might still profit with a different entry condition on resistance/bounce (or a different holding-period rule on entry sweep), so we keep it in the downstream pools. This keeps the cross-sweep pool tighter without dropping potentially-optimizable tickers. After the first post-fix run, we can revisit whether to tighten the filter further.

**Schema note:** In `support_sweep_results.json`, the trade count is stored under the JSON key `"trades"` (not `"sells"`) — it maps from `result.get("sells", 0)` inside `_simulate_with_config` but is persisted as `trades` in the per-ticker `stats` block. Filter code must read `entry["stats"]["trades"]`.

**Verification:** Compare the Tier 2 pool size before and after filter. Log the count. Ensure at least N tickers remain (e.g., ≥100) before proceeding; else fall back to full pool.

**Estimated saving:** ~10 min per downstream sweeper × 4 sweepers = 30–40 min if 30-40% of pool has zero support trades.

---

### Fix D — Consolidate support sweeper stages into one CLI invocation (medium complexity, biggest single win but highest risk)

**File:** `tools/support_parameter_sweeper.py`

**Change:**
1. Add `--stage all` option to argparse choices (line ~833).
2. When `--stage all`, invoke `sweep_threshold → sweep_execution → sweep_slippage` sequentially in one process per ticker. **regime_exit is NOT included** — see scope note below.
3. Load `price_data` and `regime_data` ONCE per ticker (via `load_collected_data(data_dir)`) and pass them through all three consolidated stage calls via the existing `price_data=` and `regime_data=` kwargs on `_simulate_with_config` (supported at lines 124–126). `sweep_threshold`/`sweep_execution`/`sweep_slippage` all use `_simulate_with_config` internally and can inherit the pre-loaded data once `--stage all` wires the kwargs through their outer function signatures.
4. Build and share `wick_cache` once per ticker across all three consolidated stages.

**File:** `tools/weekly_reoptimize.py`
- STEP 2 call: change `--stage both` to `--stage all`.
- Delete STEP 10 (`step_slippage_sweep`, line 461 and its invocation at line 670) from the pipeline sequence — folded into STEP 2.
- **Keep STEP 10b** (`step_regime_exit_sweep`, line 468) as a separate step — see scope note.

**Scope note (why regime_exit stays separate):** `sweep_regime_exit()` writes to a **different** results file (`REGIME_EXIT_RESULTS_PATH` = `data/regime_exit_sweep_results.json` at line 709) — explicitly isolated from `RESULTS_PATH` = `data/support_sweep_results.json` that threshold/execution/slippage share. The separate file has **active downstream consumers**: `tools/watchlist_tournament.py:31` and `tools/daily_analyzer.py:103` both read `regime_exit_sweep_results.json`. Consolidating regime_exit into `--stage all` would require either (a) refactoring `sweep_regime_exit` to merge into `RESULTS_PATH` with namespaced keys AND updating both consumers to read from `support_sweep_results.json` instead, or (b) having `--stage all` write to two output files (leaky abstraction). Simpler and safer: leave regime_exit as its own STEP 10b. It shares the data-collection gate with earlier stages through `_collect_once`'s 24h cache, so the marginal cost of one extra process is just one `load_collected_data` (~3–4 MB pickle read) per ticker. Future work: if we want to collapse STEP 10b later, do it as a separate refactor and include consumer-update work in that plan.

**Risk:** Medium. Behavior must be identical to running the stages sequentially today. Possible pitfalls:
- `_collect_once`'s 24h cache gate makes subsequent calls no-ops — but if we bypass it by passing `price_data` in-memory, we never touch disk; that's actually safer.
- **Data flow is already in-memory:** `sweep_execution` receives `threshold_params` as a function argument (not a disk read); `sweep_slippage` receives `base_params` the same way. Each stage writes its results into `RESULTS_PATH` (= `data/support_sweep_results.json`) via merge. So consolidating into `--stage all` just means calling them back-to-back in one process — no new disk contention, no new read-after-write ordering constraint. Simpler than feared.

**Verification:** run `support_parameter_sweeper.py --stage all --ticker CIFR` and compare `sweep_results.json` entries against a sequential `--stage both` + `--stage slippage` run for CIFR. They should match. (`--stage regime_exit` is still invoked separately and writes to its own file, so its output is unchanged regardless.)

**Estimated saving:** 15–30 min. Eliminates 1× redundant `load_collected_data` call per ticker (threshold+execution already share within `--stage both`, but slippage currently runs as a separate process with its own load). Also eliminates 1× `_collect_once` dir probe (slippage no longer needs one since it reuses the data loaded for threshold+execution) and avoids a full re-hydration of `wick_cache` for the slippage stage.

**Backward compatibility:** keep `--stage both`, `--stage slippage`, `--stage regime_exit` operational for ad-hoc diagnostic use.

---

### Fix E — Cap `candidate-gate/` retention (trivial, out-of-band housekeeping)

**File:** `tools/universe_prescreener.py`

**Change:** after the post-run export loop (around line 418), add cleanup:
```python
# Cleanup: keep only dirs in current Tier 2 pool + last 90 days of historical data
#          (historical_trade_trainer.py consumes older dirs for training)
_KEEP_AGE_DAYS = 90
_cutoff = time.time() - _KEEP_AGE_DAYS * 86400
for _d in _gate_dir.iterdir():
    if _d.is_dir() and _d.stat().st_mtime < _cutoff:
        import shutil
        shutil.rmtree(_d)
```

**Risk:** Low if the retention window is generous (90 days covers ≥12 weekly sweeps). Must NOT break `historical_trade_trainer.py` — which reads `GATE_DIR.iterdir()`. Keeping 90 days of history preserves training data.

**Verification:** run `python3 tools/historical_trade_trainer.py` after cleanup to confirm it still finds training examples.

**Estimated saving:** negligible runtime; caps disk at ~2.5 GB instead of unbounded growth.

---

## Implementation order

1. **Fix A** — 5 minutes of work, immediate 1–2 min runtime win. Do first to validate the wrapper logs are capturing everything cleanly.
2. **Fix B** — one-line hoists in 4 files, smoke-tested per file. Do second for the biggest low-risk win.
3. **Fix C** — requires reading `support_sweep_results.json`; stabilizes once we see one full upgraded run complete. Needs the `sells == 0` filter so we're conservative.
4. **Fix D** — the invasive one. Save for last so fixes A/B/C aren't blocked on it. Requires a smoke test per ticker.
5. **Fix E** — independent housekeeping; can run anytime.

## Cumulative estimated saving

~1.1 to 1.8 hours off total pipeline runtime, assuming the upgraded pipeline is currently ~10 hours. Breakdown: Fix A ~2 min + Fix B ~20–30 min + Fix C ~30–40 min + Fix D ~15–30 min + Fix E negligible runtime.

## Rollout

- After each fix, run manually via `bash tools/run_weekly_reoptimize.sh` on a small ticker subset first (e.g., `--strategy dip` on a small pool, or target a single ticker via `--ticker` where the sweeper supports it). **Known limitation:** `weekly_reoptimize.py`'s `--dry-run` flag only suppresses orchestrator-level writes (guard files, email, history JSON). It does NOT forward to child sweepers — they run for real. For a truly cheap rehearsal, use a small ticker subset rather than relying on `--dry-run`.
- If rehearsal output matters, pipe to a throwaway log path by editing `run_weekly_reoptimize.sh` temporarily, or add a `--log-file` flag to the wrapper if we expect many rehearsals.
- Once all five fixes land, trigger a real ad-hoc run to measure new baseline (the timestamped logs from `run_weekly_reoptimize.sh` give us per-phase durations for calibration).
- Compare vs. current baseline (Apr 11 old-version: 2h 54m for 19-ticker pool; upgraded pipeline will have its own baseline after first clean completion).

## What this plan does NOT touch

- `universe_prescreener.py` batch-download logic — already efficient, don't regress.
- `_simulate_with_config` cache plumbing — already correctly wired; Fix D only *uses* it more.
- Grid sizes (54 resistance, 54 bounce, 9 entry, etc.) — reducing grids is a separate optimization question about parameter space, not runtime redundancy.
- Per-period `[12, 6, 3, 1]` SWEEP_PERIODS — same, separate question about multi-period validation design.
- The candidate sweep (STEP 6) — parallel ThreadPoolExecutor pattern is intentional; streaming it would garble logs.

## Open questions

1. **Does `sweep_slippage` write to the same `sweep_results.json` keys as `sweep_threshold`/`sweep_execution`, or its own file?** — RESOLVED: all four stages (threshold, execution, slippage, regime_exit) merge into `RESULTS_PATH` (= `data/support_sweep_results.json`), confirmed at `sweep_slippage` line 1192. Data flow between stages is via in-memory function arguments (`threshold_params`, `base_params`), not disk reads — so Fix D's `--stage all` just invokes them back-to-back in one Python process, no read-after-write ordering concerns.
2. **Is `regime_exit` meant to be part of the default pipeline or diagnostic-only?** — RESOLVED: `step_regime_exit_sweep()` at `weekly_reoptimize.py:468` IS unconditionally invoked as STEP 10b in the surgical sweep sequence (line 670) — it's part of the default pipeline. However, Fix D **does NOT consolidate regime_exit** into `--stage all`: regime_exit writes to a separate file (`regime_exit_sweep_results.json`) with active downstream consumers (`watchlist_tournament.py:31`, `daily_analyzer.py:103`) that would break under consolidation. Fix D consolidates only threshold → execution → slippage; STEP 10b stays as-is. A future refactor could absorb regime_exit after updating those consumers, but that's out of scope here.
3. **Does downstream neural training (`neural_support_evaluator.py`) depend on any specific output format from `support_sweep_results.json`?** — RESOLVED by verification: `neural_support_evaluator.py` reads `data/neural_support_candidates.json`, NOT `support_sweep_results.json`. Fix D is safe from the neural-training direction.
