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

---

## ~~PERF: Extend Fix B — hoist `resistance_cache` and `bounce_cache` to ticker scope~~ — RESOLVED
**Status**: CLOSED (2026-04-20, commit `6154f5b`)
**Fix applied**: Hoisted both caches above the combo loop in `tools/resistance_parameter_sweeper.py` and `tools/bounce_parameter_sweeper.py`, mirroring the earlier `wick_cache` hoist (Fix B from commit `2311524`). Comment links each cache to its `(ticker, day_string)` key in `backtest_engine.py` for future maintainers. All 302 tests pass; expected weekly runtime saving confirmed per analysis (~1h 15m–1h 30m off STEP 7 + STEP 8 combined).

**Original report (kept for context):**
**Status**: OPEN (discovered 2026-04-19 mid-run)
**Expected saving**: ~1h 15m–1h 30m combined off STEP 7 + STEP 8 (bounce roughly 2h → ~45–60m; resistance roughly 1h 3m → ~30–40m)
**Root cause**: The recent Fix B hoisted only `wick_cache` above the combo loop in resistance/bounce sweepers. But `resistance_cache` and `bounce_cache` have the identical invariant — both are keyed on `(ticker, day_string)` in `backtest_engine.py` (lines 704 and 728 respectively), with comments stating "resistance levels don't depend on capital state" and "bounce profiles don't depend on capital state". They do NOT depend on any sweep-grid parameter.

Current state: each ticker recomputes per-day bounce/resistance profiles **54 times** (once per combo) instead of once per ticker. This is the dominant remaining cost in STEP 7 (54 combos × redundant resistance detection) and STEP 8 (54 combos × redundant bounce detection).

**Proposed fix** (one-line hoist per file, mirrors the wick_cache pattern already applied):
- `tools/resistance_parameter_sweeper.py` — hoist `resistance_cache = {}` (line ~110) to above the combo loop, keeping the shared-across-all-combos semantics like `wick_cache` now has.
- `tools/bounce_parameter_sweeper.py` — hoist `bounce_cache = {}` (line ~106) the same way.

**Verification**: Same pattern as Fix B verification — single-ticker smoke test, confirm `*_sweep_results.json` output for that ticker is byte-identical vs pre-hoist.

**Discovered during**: the 2026-04-19 ad-hoc run, where STEP 8 was running nearly 2× slower per ticker than STEP 7 despite both having the same 54-combo grid. Investigation of `backtest_engine.py` confirmed the cache key shape was `(ticker, day)` only — not strategy-dependent.

**Why it wasn't caught in the original plan verification**: the original audit identified wick_cache as the dominant redundant recompute; resistance_cache and bounce_cache were cited in v2 as "shared across periods within a combo" which was accurate but understated — they can be shared across ALL combos safely.

---

## ~~PIPELINE: Add support-level-density gate to Tier 2 pool construction~~ — RESOLVED
**Status**: CLOSED (2026-04-20, commit `0f51b26`)
**Fix applied**: New `apply_density_gate()` + `_worker_density_check()` in `tools/universe_prescreener.py`, wired into `main()` as Phase 2.5 (after stage-1 ranking, before `save_results`). Uses the existing `multiprocessing.Pool` infrastructure — workers reuse their process-local price cache, no new yfinance round-trips.

Counting criterion matches `bullet_recommender.py:336-339` exactly:
- `recommended_buy` not None and `< current_price`
- `zone == "Active"` (strict — not zone_promoted Buffer)
- `effective_tier` not in `{"Skip", ""}`

Gate threshold: `MIN_SUPPORT_LEVELS_FOR_TIER2 = 3`. Smoke-tested on 5 tickers (HMY/OSCR/JBLU/BDRX/VWAV) — VWAV with 2 levels correctly gated out; others with 3+ kept. Smoke-test runtime: ~4s for 5 tickers at 4 workers → full 1,585-ticker gate projected ~3–7 min at 8 workers.

Passing rankings get a new `level_count` field attached for downstream visibility.

**Original report (kept for context):**
**Status**: OPEN (filed 2026-04-20)
**Impact**: Eliminates the "thin-ladder ticker" problem that wastes pool slots, onboarding time, and manual drop decisions every week.

**Symptom observed**: Out of ~15 candidates onboarded from tournament ranks #5–#26 on 2026-04-19/20, 6 had to be dropped during bullet-recommendation because they had ≤2 active-zone support levels — `bullet_recommender.py` rejected them with "insufficient for surgical bullet stacking":
- BDRX (#5) — 1 level after re-onboard (price shifted)
- VWAV (#7) — 2 levels + yfinance delisting warning
- FRMM (#15) — 0 raw levels
- PLCE (#16) — 1 level
- SRAD (#18) — 1 level
- FIGR (#19) — 1 active + 1 buffer
- OCUL (#22) — 2 levels (borderline, placed manually as thin ladder)

That's a ~40% drop rate on tournament-ranked "top 25" candidates. The tournament ranks them because their composite P/L score is genuinely high — a single strong support level with good hold rate can drive high simulation returns. But the bullet-stacking strategy structurally needs **3+ discrete support levels** for proper layered entries.

**Root cause**: the screening funnel gates on volatility, liquidity, and "any profitable support config exists," but never on ladder depth:

```
US universe (~6,851)
    ↓ universe_screener.py        (price $3+, vol 500K+, swing 10%+, consistency 80%+)
~1,585 passers
    ↓ universe_prescreener.py     (stage-1 support sweep, ranks by signal)
Top 200 → Tier 2 pool
    ↓ watchlist_tournament.py     (composite scoring, ranks 1–204)
Tournament top-30
```

At no step does the pipeline check: "does this ticker have enough discrete support levels to support a ≥3-bullet ladder?" `wick_offset_analyzer.py` produces the level count, but it runs downstream of the tournament during onboarding.

**Proposed fix** (preferred): gate at **Tier 2 pool construction** in `universe_prescreener.py` (or immediately after, in `weekly_reoptimize.py:_build_profitable_tier2_pool` / equivalent).

After the stage-1 pre-screen identifies a ranked candidate, run `wick_offset_analyzer.analyze_stock_data()` for it, count raw Active+Buffer support levels, and apply a gate:
- **Hard floor**: <3 raw support levels → exclude from Tier 2 pool entirely
- **Tag for segregation**: 3–4 levels → include but flag `strategy_fit: "thin"` so tournament can rank them in a separate tier (not competing with full-ladder tickers for top-30 slots)
- **Keep as-is**: ≥5 levels → full eligibility

Cache the wick analysis during pre-screen so tournament + onboarding re-use it (avoids duplicate yfinance calls).

**Alternative**: gate at `watchlist_tournament.py` — cheaper to implement (post-hoc filter) but wastes pre-screen compute on unusable tickers.

**Expected impact**:
- Tournament top-30 becomes directly actionable (zero drops during onboarding)
- `batch_onboard` time saved: ~22 min × ~3 thin tickers per weekly wave = **~65 min/wk saved**
- No more manual "drop + clean sweep-result JSONs" cleanup cycle
- Lower-ranked tickers in the tail correspond to real bullet-strategy-viable candidates, so "going deeper into the rankings" stops diluting quality

**Discovered during**: 2026-04-20 onboarding session. User questioned why thin-level tickers pass the 200-pool screen in the first place. Root cause analysis confirmed no gate exists at any screening stage for ladder depth — only for P/L signal on any single level.

**Related**: same principle might benefit downstream `bullet_recommender.py` — its current "insufficient for surgical bullet stacking" rejection is a last-mile filter that could be promoted upstream.

---

## ~~SCORING: Composite simulation score ignores period recency~~ — RESOLVED
**Status**: CLOSED (2026-04-20, commit `4ca8678`)
**Fix applied**: Added `RECENCY_WEIGHTS = {12: 1, 6: 2, 3: 3, 1: 4}` module constant in `tools/multi_period_scorer.py`. Applied as a multiplier in `compute_composite()` **after** significance + regime adjustments (Step 3.5), so existing signals persist.

Shape chosen: linear 1:2:3:4 (option 1 from the original fix proposals) — simplest to reason about and tune. Half-life and regime-consistency variants can be added later if needed.

Verified behavior:
- Ticker with rates [5, 5, 10, 15] for 12/6/3/1mo (strengthening): composite went 8.75 → 10.5
- Ticker with rates [15, 10, 5, 5] (decaying): composite went 8.75 → 7.0
- Without recency both scored identically; now strengthening wins by ~50%.

Test coverage: new `tests/test_multi_period_scorer.py` with 5 tests locking the behavior (recency tilt, weight monotonicity, regime interaction, degenerate zero-cycle case, uniform-rate sanity). All 308 tests pass.

**Original report (kept for context):**
**Status**: OPEN (filed 2026-04-20)
**Impact**: Tournament ranks tickers that "worked on average over 12mo" higher than tickers that "work right now," leading to bullet placements at levels that may never hit under current market regime.

**Root cause**: `tools/multi_period_scorer.py` aggregates 12mo / 6mo / 3mo / 1mo simulation P/L using cycle-count weighting only:

```python
PERIODS = [12, 6, 3, 1]
SIGNIFICANCE_THRESHOLD = 5
weight_i = min(cycles_i, SIGNIFICANCE_THRESHOLD) / SIGNIFICANCE_THRESHOLD
composite = sum(weight_i * rate_i) / sum(weight_i)
```

A ticker with 10 cycles in each period all hit full weight 1.0 regardless of whether the cycles were clustered 12 months ago or last week. The 12mo and 1mo periods have **equal influence** on the composite.

**Symptom observed (2026-04-19 run)**:
- Multiple top-30 tournament tickers had levels that are arguably stale — composite score reflects 12-month average behavior, but current price action has drifted far from those levels or the market regime has changed.
- E.g., a ticker ranked #10 because support held reliably in months 8–12 may now be in a different regime where those levels don't matter anymore. Bullets placed there are dead money until the regime reverts.

**Contrast with how wick_offset_analyzer handles recency**:
- `decay_half_life = 90` days on hold rate
- `decay_half_life = 180` days on HVN volume
- Tier promotion follows decayed (recent) behavior
- `DORMANCY_THRESHOLD_DAYS = 90` for level dormancy

These give the **level selection** appropriate recency sensitivity. But the **ticker selection** (composite score → tournament rank) doesn't have parallel recency weighting. The mismatch is: levels are recency-aware, tournament rankings aren't.

**Proposed fix**: add recency weighting to composite aggregation. Several shapes to pick from:

1. **Linear recency weights**: `1mo:4, 3mo:3, 6mo:2, 12mo:1` (sum 10) — short-term heavily favored.
2. **Half-life decay matching wick analyzer**: weight each period by `exp(-period_midpoint_days * ln(2) / 90)` — matches level-decay half-life.
3. **Regime-consistency bonus**: weight recent period UP when market regime matches current regime (e.g., if current is Risk-On, 1mo Risk-On cycles weighted extra).

**Expected impact**:
- Tournament ranks favor tickers whose patterns are still active now (not relics).
- Bullet placements more likely to fill within typical cycle window (1–4 weeks).
- Tickers whose edge has decayed slip down the rankings and get dropped naturally.
- User concern "levels we are deploying are a waste of money and will never hit" directly addressed.

**Verification**: run the tournament with recency weights on the same dataset, compare top-30 delta against current rankings. Spot-check: do the demoted tickers correspond to "trailing-edge" strategy decay?

**Discovered during**: 2026-04-20 conversation about recency mechanics in the pipeline. User identified the gap between level-side recency sensitivity (well-handled in wick_offset_analyzer) and ticker-selection-side recency blindness (missing in multi_period_scorer / tournament composite).

**Related**: pairs with the "support-level-density gate" backlog item — together they ensure (a) tickers that enter the tournament are bullet-ladder-viable, and (b) tickers that rank well actually have currently-active patterns.

---

## ~~BUG: Bullet drift missing-order inference misclassifies same-day fills~~ — RESOLVED
**Status**: CLOSED (2026-04-24)
**Priority**: P0 — clears failing test suite and protects order-state accuracy.

**Fix applied**: Added `_trade_date_overlaps_window()` in `tools/bullet_drift_report.py`
and changed `_classify_missing()` to treat date-only trade records as a full-day
interval when checking the snapshot/report window. This preserves rejection of
wrong ticker, wrong side, stale dates, malformed dates, and price mismatches while
allowing same-day date-only BUY fills to classify as `FILLED`.

**Verification**:
- `python3 -m pytest tests/test_bullet_drift_report.py -q` → 35 passed
- `python3 -m pytest -q` → 343 passed

**Original report (kept for context):**
**Status**: OPEN (filed 2026-04-24)

**Symptom observed**: `python3 -m pytest -q` currently reports `340 passed, 1 failed`.
The failing test is `tests/test_bullet_drift_report.py::TestMissingOrder::test_filled_within_window`.
Expected action is `FILLED`, but `tools/bullet_drift_report.py` returns `CANCELLED`.

**Root cause**: `tools/bullet_drift_report.py:_trade_date_to_epoch()` converts date-only
trade history entries (`YYYY-MM-DD`) to `23:59:59` local time. If a report is generated
earlier on the same date, a legitimate same-day fill is treated as occurring after
`report_ts`, so `_classify_missing()` fails the `snapshot_ts <= t_epoch < report_ts`
window check.

**Proposed fix**:
- Treat date-only trade history as a full-day interval rather than a single end-of-day timestamp.
- Update `_classify_missing()` to match date-only trades when any part of the trade date overlaps the snapshot/report window.
- Preserve existing behavior for future dates, wrong side, wrong ticker, and price mismatch.
- Add/keep tests for: same-day within window, yesterday outside window, wrong side, price outside tolerance, malformed date.

**Verification**:
- `python3 -m pytest tests/test_bullet_drift_report.py -q`
- `python3 -m pytest -q`

**Expected impact**: Weekly drift reports stop incorrectly labeling filled broker orders
as cancelled, and the repo returns to a green test baseline.

---

## ~~INFRA: Define real project packaging and dependency lock~~ — RESOLVED
**Status**: CLOSED (2026-04-24)
**Priority**: P0 — required for reproducible execution on a fresh machine.

**Fix applied**: Added `pyproject.toml` as the canonical project/dependency
definition with runtime dependencies, dev extras, and pytest configuration. Replaced
`requirements.txt` with a compatibility entry point that installs `.[dev]`. Added
`requirements.lock` with direct dependency pins captured from the current working
environment. Replaced the placeholder README with setup, test, command, and layout
documentation.

**Verification**:
- `python3 tools/portfolio_manager.py --help` → OK
- `python3 tools/bullet_recommender.py --help` → OK
- `python3 tools/backtest_engine.py --help` → OK
- `python3 -m pytest` → 343 passed
- Clean venv install in `/tmp/agentic-trading-venv` with
  `python -m pip install -e '.[dev]' -c requirements.lock` → OK
- Clean venv `python -m pytest` → 343 passed

**Note**: The lock file pins direct project dependencies, not every transitive
package in the workstation environment. It is used as a constraints file with
`python3 -m pip install -e '.[dev]' -c requirements.lock`. The initial lock pin
for `chromadb==1.5.3` was yanked on PyPI during validation, so it was moved to
the current non-yanked `chromadb==1.5.8` and retested.

**Original report (kept for context):**
**Status**: OPEN (filed 2026-04-24)

**Symptom observed**: `requirements.txt` lists only `chromadb`, `sentence-transformers`,
and `scikit-learn`, while the tool layer imports `yfinance`, `pandas`, `numpy`,
`requests`, `bs4`, `pytest`, and other runtime/test dependencies. There is no
`pyproject.toml`, lockfile, pytest config, or canonical install command.

**Root cause**: Dependencies have grown organically around individual tools without
a single source of truth for runtime vs dev/test packages.

**Proposed fix**:
- Add `pyproject.toml` with project metadata, Python version, runtime dependencies, and dev/test optional dependencies.
- Either replace `requirements.txt` with an exported lock/requirements file or make it explicitly generated from `pyproject.toml`.
- Add pytest config so imports do not rely on each test mutating `sys.path`.
- Document install commands in `README.md`.

**Verification**:
- Create a clean virtualenv.
- Install from the documented command.
- Run `python3 -m pytest -q`.
- Smoke-run representative tools: `tools/portfolio_manager.py --help`, `tools/bullet_recommender.py --help`, `tools/backtest_engine.py --help`.

**Expected impact**: The system becomes reproducible instead of depending on whatever
happens to be installed in the current workstation environment.

---

## ~~INFRA: Separate generated runtime data from source-controlled code~~ — RESOLVED
**Status**: CLOSED (2026-04-24)
**Priority**: P0 — required before code review, commits, or reliable rollback are sane.

**Fix applied**: Expanded `.gitignore` to cover workflow runtime state, packaging
artifacts, generated root-level reports, data logs/caches/sweep outputs, backtest
artifacts, generated ticker analyses, and portfolio/trade backup files. Added
`templates/state/portfolio.template.json` and `templates/state/trade_history.template.json`
so state can be bootstrapped without copying live files. Added
`docs/source-control-policy.md` and linked it from `README.md` to classify tracked,
ignored, live-state, and legacy generated artifacts.

**Verification**:
- `git status --short --ignored` shows generated runtime outputs now ignored
  (`data/backtest/`, `.workflow-state/`, sweep logs/results, generated ticker analysis,
  packaging artifacts, backup files).
- Durable ticker `identity.md` and `memory.md` remain trackable.
- `python3 -m pytest` → 343 passed

**Note**: This does not remove already-tracked generated artifacts from git. `.gitignore`
cannot affect tracked files. A separate follow-up is required for an index cleanup
using `git rm --cached` after reviewing exactly which legacy artifacts should stop
being tracked.

**Original report (kept for context):**
**Status**: OPEN (filed 2026-04-24)

**Symptom observed**: The worktree currently has 193 changed/untracked entries.
`git diff --stat` shows roughly 77k insertions and 31k deletions, mostly generated
reports, caches, sweep outputs, ticker artifacts, and portfolio state. The repo is
about 514 MB, with `data/` about 467 MB. `.gitignore` only excludes a small set of
paths.

**Root cause**: Source code, operational state, generated reports, cache files,
logs, backtest artifacts, and live portfolio/trade ledgers are all stored together
without clear tracking rules.

**Proposed fix**:
- Classify files into: source code, strategy docs, canonical fixtures, live operational state, generated reports, caches/logs, and large backtest artifacts.
- Expand `.gitignore` for generated caches/logs/runtime outputs such as sweep logs, prescreen caches, `.workflow-state`, large backtest result folders, and transient guard files.
- Decide whether live `portfolio.json` and `trade_history.json` remain tracked, move to a `state/` area, or use template files plus local ignored state.
- Add sample/template files for required state schemas if live state becomes ignored.
- Keep small deterministic test fixtures tracked under `tests/fixtures/`.

**Verification**:
- `git status --short` should show only intentional source/doc changes after a normal run.
- Run one normal analysis/reoptimize path and confirm generated files do not pollute source diffs.
- Confirm required state can be bootstrapped from templates plus documented commands.

**Expected impact**: Future changes become reviewable. Operational runs stop drowning
real code changes in generated artifact churn.

---

## ~~VCS: Untrack legacy generated artifacts already in the git index~~ — RESOLVED
**Status**: CLOSED (2026-04-24)
**Priority**: P0 — completes the source/runtime separation after the ignore policy.

**Fix applied**: Used `git ls-files -ci --exclude-standard` as the reviewed
tracked-ignored set, corrected `.gitignore` root-level report patterns so they do
not match `.workflow/agents/*`, broadened `data/` and `morning-work/` runtime
rules, then removed 342 generated/runtime artifacts from the git index with
`git rm --cached`. Files remain on disk and are now ignored.

**Verification**:
- `git ls-files -ci --exclude-standard | wc -l` → 0
- `git diff --cached --name-status | wc -l` → 342 staged index removals
- Confirmed sample local generated files still exist on disk:
  `candidate-evaluation.md`, `data/support_sweep_results.json`,
  `tickers/ACHR/wick_analysis.md`, `.workflow-state/...json`
- Confirmed broader generated outputs still exist on disk:
  `data/candidates.json`, `morning-work/ACHR.md`
- Confirmed workflow source remains tracked:
  `.workflow/agents/status-analyst.md`,
  `.workflow/agents/cycle-timing-analyst.md`
- `python3 -m pytest` → 343 passed

**Original report (kept for context):**
**Status**: OPEN (filed 2026-04-24)

**Symptom observed**: Many generated artifacts are already tracked, so they still
appear as modified even after `.gitignore` was expanded. Examples include root-level
candidate reports, `data/*_results.json`, `data/*_cache.json`, and
`tickers/*/wick_analysis.md`.

**Root cause**: `.gitignore` only applies to untracked files. Files already in the
git index must be explicitly removed from tracking while preserved on disk.

**Proposed fix**:
- Review `docs/source-control-policy.md` against the currently tracked generated files.
- Build a dry-run list of files to untrack with `git ls-files`.
- Use `git rm --cached` only for approved generated artifacts, preserving local files.
- Keep source, workflow definitions, strategy docs, templates, and durable ticker
  `identity.md`/`memory.md` files tracked.
- Commit the index cleanup separately from code changes for reviewability.

**Verification**:
- `git status --short` after cleanup shows no generated artifact churn from normal runs.
- Tracked source/test/workflow/docs files remain present.
- Existing local generated files still exist on disk after `git rm --cached`.

**Expected impact**: Code reviews stop being polluted by legacy generated artifacts
that were committed before the ignore policy existed.

---

## ~~SAFETY: Add schema validation, atomic writes, and write locking for portfolio state~~ — RESOLVED
**Status**: CLOSED (2026-04-24)
**Priority**: P1 — protects live portfolio/trade ledger integrity.

**Fix applied**: Hardened `tools/portfolio_manager.py` with stdlib validation for
portfolio, pending order, position, and trade-history shapes. Added `.portfolio.lock`
advisory locking around state I/O, timestamped backups for both `portfolio.json`
and `trade_history.json`, atomic temp-file writes with fsync + replace, and corrupt
JSON recovery that renames invalid files before starting fresh. The CLI path now
holds the state lock across load/migrate/command dispatch, while shared `_save()`
and `_record_trade()` remain individually locked for imported callers.

**Follow-up fix applied**: Added transactional imported-caller APIs
`record_fill()` and `record_sell()` that acquire the lock, load fresh state,
migrate, dispatch, save, and record trade history as one transaction. Refactored
`daily_analyzer.py` and `order_proximity_monitor.py` to call these wrappers instead
of loading portfolio state externally and passing stale in-memory data to
`cmd_fill()` / `cmd_sell()`.

**Test coverage added**: `tests/test_portfolio_manager_safety.py`
- timestamped backup + atomic JSON save
- invalid portfolio rejection without overwrite
- corrupt trade-history recovery
- load-time portfolio shape validation
- stale imported-caller fill regression
- stale imported-caller sell regression

**Verification**:
- `python3 -m pytest tests/test_portfolio_manager_safety.py -q` → 6 passed
- `python3 -m py_compile tools/portfolio_manager.py tools/daily_analyzer.py tools/order_proximity_monitor.py` → OK
- `python3 tools/portfolio_manager.py --help` → OK
- `python3 -m pytest` → 349 passed

**Original report (kept for context):**
**Status**: OPEN (filed 2026-04-24)

**Symptom observed**: `tools/portfolio_manager.py` centralizes writes, which is good,
but `portfolio.json` and `trade_history.json` are plain JSON files with no formal
schema validation, no atomic temp-file replace, and no lock around concurrent
cron/manual invocations.

**Root cause**: The state layer is still file-based without database-style guarantees.
That is acceptable for this project size, but it needs basic file safety.

**Proposed fix**:
- Define explicit schemas for portfolio, pending orders, positions, and trade history records.
- Validate loaded state before mutation and validate output state before saving.
- Write via temp file + fsync + atomic replace.
- Add a process lock around portfolio/trade history mutations.
- Make backup naming timestamped, not a single overwrite-only `portfolio.json.bak`.
- Add recovery behavior for corrupt state that does not silently discard useful records.

**Verification**:
- Unit tests for valid state, malformed state, corrupt JSON, concurrent fill attempts, and failed write rollback.
- CLI smoke tests for `fill`, `sell`, `order`, `cancel`, `place`, `pause`, and `unpause`.
- Confirm `trade_history.json` IDs stay monotonic and no duplicate IDs are created under concurrent calls.

**Expected impact**: Manual use plus scheduled monitors can coexist without risking
silent state corruption or lost trade records.

---

## ~~VALIDATION: Harden backtest assumptions before trusting reported edge~~ — RESOLVED
**Status**: CLOSED (2026-04-25)
**Priority**: P1 — protects strategy conclusions from simulation artifacts.

**Fix applied**: Added an explicit `same_day_exit_mode` execution assumption to
`SurgicalSimConfig` with `optimistic`, `conservative`, and `disabled` modes. The
historical optimistic behavior remains available, but conservative mode refuses
same-day exits on daily OHLC bars where the fill low and target high are both
touched without intraday sequence evidence. Candidate simulation gates now force
`same_day_exit_mode="conservative"` before pass/fail approval.

Added execution cost modeling to the surgical backtest config and engine:
`entry_spread_pct`, `exit_spread_pct`, `fee_per_trade`, and `fee_per_share`.
Sell trades now include gross P/L, net P/L, and fees; reporter summaries expose
gross P/L, transaction costs, and net P/L. Entry/exit slippage remains supported
and is combined with spread assumptions.

Added `build_execution_stress_report()` plus `--execution-stress` on
`tools/backtest_engine.py`, writing `execution_stress.json` to compare optimistic,
conservative, and no-same-day-exit modes on the same dataset.

**Test coverage added**: `tests/test_backtest_execution_assumptions.py`
- optimistic mode preserves old same-day-exit behavior
- conservative mode disallows same-day exit on same daily OHLC bar
- transaction costs produce distinct gross/net P&L and fee fields
- stress report compares same-day modes

**Verification**:
- `python3 -m pytest tests/test_backtest_execution_assumptions.py -q` → 4 passed
- `python3 -m pytest tests/test_backtest_execution_assumptions.py tests/test_strategy_improvements.py -q` → 114 passed
- `python3 -m py_compile tools/backtest_engine.py tools/backtest_config.py tools/backtest_reporter.py tools/candidate_sim_gate.py` → OK
- `python3 -m pytest -q` → 353 passed

**Symptom observed**: The sample surgical backtest report shows `100.0%` win rate,
`0.1` average hold days, and 85 same-day exits out of 87 completed sells. That may
reflect a real toy-period behavior, but it is also the exact shape produced by
overoptimistic high/low sequencing, missing slippage/spread/fees, or same-day
exit assumptions that cannot be executed in real market order.

**Root cause**: The backtest engine uses daily OHLC bars. Without explicit intraday
sequence constraints, a strategy can accidentally assume the day reached the buy
low before the sell high. Same-day exit logic also needs a strict execution model.

**Proposed fix**:
- Audit `tools/backtest_engine.py` fill/exit ordering for same-day buy and sell behavior.
- Add a conservative mode: if a buy and sell target are both touched in the same daily bar, either disallow same-day exit or require an explicit intraday assumption.
- Add slippage, spread, and fee parameters to `SurgicalSimConfig`.
- Report metrics both gross and net of transaction assumptions.
- Add a stress report comparing optimistic, conservative, and no-same-day-exit modes.
- Mark candidate simulation gates as invalid unless they pass under the conservative mode.

**Verification**:
- Unit tests for OHLC bars where both low and high are touched on the same day.
- Regression test proving no-same-day-exit mode changes the sample result when appropriate.
- Re-run candidate gate/backtest report and compare win rate, average hold days, max drawdown, and profit factor across modes.

**Expected impact**: Backtest metrics become decision-grade rather than merely
directional, and the system stops over-ranking candidates that only work under
optimistic bar sequencing.

---

## ~~DOCS: Replace placeholder README with operator runbook~~ — RESOLVED
**Status**: CLOSED (2026-04-25)
**Priority**: P1 — makes the system maintainable and recoverable.

**Fix applied**: Replaced the short setup README with an operator runbook covering
project purpose, setup, quick checks, layout, strategy map, live state files,
command safety classes, daily workflow, weekly workflow, backtesting, emergency
procedures, generated artifacts, and source-control checks. The runbook separates
read-only/reporting commands, generated-artifact writers, and portfolio-mutating
commands, and links the relevant workflow YAML files plus
`docs/source-control-policy.md`.

**Verification**:
- README includes setup/install/test commands.
- README lists mutating commands separately from read-only/reporting commands.
- README documents state bootstrap templates and warns not to overwrite live state.
- README documents yfinance/provider failures, corrupt JSON recovery, stuck cron
  checks, stale lock handling, and test-failure handling.
- `python3 tools/backtest_engine.py --help` → OK
- `python3 tools/bullet_recommender.py --help` → OK
- `python3 tools/daily_analyzer.py --help` → OK
- `python3 tools/portfolio_manager.py --help` → OK
- `python3 -m pytest -q` → 353 passed

**Symptom observed**: `README.md` only contains the repo title. The actual operating
knowledge is spread across `strategy.md`, workflow YAML files, tool docstrings,
plans, generated reports, and conversation context.

**Root cause**: The project evolved as an operational workspace, but onboarding and
recovery docs were never consolidated.

**Proposed fix**:
- Document the system purpose, strategy summary, and major components.
- Add setup/install commands after dependency packaging is complete.
- Add daily, weekly, and emergency workflows with exact commands.
- Document state files, generated artifacts, and what is safe to delete/regenerate.
- Add troubleshooting for yfinance failures, corrupt JSON, failed cron run, stale locks, and test failures.
- Link to `strategy.md`, workflows, and key tools.

**Verification**:
- A clean clone plus README instructions can run tests and at least one non-mutating analysis command.
- README lists every mutating command separately from read-only/reporting commands.

**Expected impact**: The system becomes operable without relying on memory or prior
conversation history.

---

## ~~CI: Add a minimum quality gate for tests and import health~~ — RESOLVED
**Status**: CLOSED (2026-04-25)
**Priority**: P2 — prevents recurrence after the P0 cleanup is complete.

**Fix applied**: Added a local `Makefile` quality gate with `test`,
`import-health`, and `quality` targets. Added `tests/test_tool_imports.py`, which
imports every public `tools/*.py` module and excludes only private helper modules
from the public tool-surface smoke test. Added `.github/workflows/ci.yml` to run
the quality gate on push and pull request using Python 3.10 and the documented
editable install with `requirements.lock` as constraints. Added a CI badge and
`make quality` command to the README quick checks.

**Verification**:
- `python3 -m pytest tests/test_tool_imports.py -q` → 123 passed
- `make quality` → full test suite passed, then import-health passed
- Existing network-sensitive tests remain mocked; the import-health gate only
  imports modules and does not call live market-data paths.

**Symptom observed**: The repo had a failing test despite substantial local test
coverage. There is no visible automated gate that blocks regressions in the core
tool layer.

**Root cause**: Tests exist, but they are not enforced as a standard pre-merge or
pre-commit quality gate.

**Proposed fix**:
- Add a lightweight CI workflow or local `make test` equivalent after packaging is defined.
- Gate on `python3 -m pytest -q`.
- Add a fast import smoke test for all `tools/*.py` modules where import should be side-effect-safe.
- Exclude known CLI-only/network-heavy modules from import smoke with an explicit allowlist/denylist.
- Add a status badge or README section showing the quality gate command.

**Verification**:
- CI/local gate passes on a clean checkout.
- Introducing a known failing test fails the gate.
- Network-dependent tests remain mocked or clearly separated.

**Expected impact**: The project keeps a green baseline after this cleanup instead
of rediscovering broken operational paths during live use.

---

## ~~BUG: Live dip evaluator can suppress valid BUY signals~~ — RESOLVED
**Status**: CLOSED (2026-04-25)
**Priority**: P0 - live/backtest correctness gap.

**Fix applied**: Added `decision_graph.propagate_signals()` in
`tools/neural_dip_evaluator.py:evaluate_decision()` before reading activated
report nodes. Added focused regression coverage in
`tests/test_neural_dip_evaluator.py` proving a graph-approved dip candidate emits
a live BUY signal and a non-confirmed bounce still reports no buy.

**Verification**:
- `python3 -m pytest tests/test_neural_dip_evaluator.py -q` -> 2 passed
- `python3 -m py_compile tools/neural_dip_evaluator.py tests/test_neural_dip_evaluator.py` -> OK

**Original report (kept for context):**
**Status**: OPEN (filed 2026-04-25)

**Symptom observed**: `tools/neural_dip_evaluator.py:evaluate_decision()` builds the
decision graph and immediately calls `decision_graph.get_activated_reports()`.
`tools/graph_engine.py:get_activated_reports()` only returns report nodes that
already have propagated signals, but `evaluate_decision()` does not call
`decision_graph.propagate_signals()` first.

A synthetic graph check showed a valid `AAA:buy_dip` report is invisible before
propagation and visible after propagation.

**Root cause**: The live dip evaluator and graph engine disagree on the activation
contract. Report-node values can be true after graph resolution, while report
signals remain empty until propagation runs.

**Proposed fix**:
- Update `evaluate_decision()` to call `decision_graph.propagate_signals()` before
  reading activated reports, or switch the live decision path to the same
  node-value contract used by the backtester.
- Preserve human-readable reason/path output for selected BUY decisions.
- Add a regression test with a synthetic ticker/day where `build_decision_graph()`
  produces a true `buy_dip` node and `evaluate_decision()` emits a BUY decision.

**Verification**:
- Unit test proving a valid synthetic `buy_dip` graph produces a live BUY signal.
- Unit test proving a no-signal graph still emits the current "No dip play today"
  behavior.
- `python3 -m pytest tests/test_graph.py tests/test_strategy_improvements.py -q`
- `python3 -m pytest -q`

**Expected impact**: Live dip evaluation stops silently discarding graph-approved
BUY signals, and live/backtest parity becomes testable.

---

## ~~BUG: Neural dip backtester checks the wrong first-hour breadth key~~ — RESOLVED
**Status**: CLOSED (2026-04-25)
**Priority**: P0 - backtest validity gap.

**Fix applied**: Changed `tools/neural_dip_backtester.py:replay_day()` to read
`breadth_dip_gate`, matching the first-hour graph state emitted by
`tools/neural_dip_evaluator.py`. Kept the contract strict instead of accepting the
legacy `breadth_dip` key because no current persisted producer uses that shape.

**Test coverage added**: `tests/test_neural_dip_backtester.py`
- replay advances to decisioning and confirms a buy when `breadth_dip_gate=True`
- replay returns `NO_DIP` and does not call the decision graph when only the
  legacy `breadth_dip` key is present

**Verification**:
- `python3 -m pytest tests/test_neural_dip_backtester.py -q` -> 2 passed
- `python3 -m py_compile tools/neural_dip_backtester.py tests/test_neural_dip_backtester.py` -> OK

**Original report (kept for context):**
**Status**: OPEN (filed 2026-04-25)

**Symptom observed**: `tools/neural_dip_backtester.py:replay_day()` checks
`fh_state.get("breadth_dip")`, but `tools/neural_dip_evaluator.py` stores the
first-hour market gate as `breadth_dip_gate`.

**Root cause**: A key-name mismatch between the first-hour graph state and replay
logic likely causes replay to return `NO_DIP` even when the intended breadth gate
is true.

**Proposed fix**:
- Change replay to read `breadth_dip_gate`.
- Add a compatibility fallback only if there is a real persisted artifact that
  still uses `breadth_dip`; otherwise keep the contract strict.
- Add a focused replay test that builds a first-hour state with
  `breadth_dip_gate=True` and proves the replay can advance to ticker-level
  decisioning.

**Verification**:
- Unit test for the first-hour gate key.
- Existing neural/backtest tests.
- `python3 -m pytest -q`

**Expected impact**: Neural dip replay uses the same first-hour gate as the live
graph builder, making backtest results more meaningful.

---

## ~~VALIDATION: Add neural artifact schema, freshness, and promotion checks~~ — RESOLVED
**Status**: CLOSED (2026-04-25)
**Priority**: P1 - prevents stale learned artifacts from driving decisions.

**Fix applied**: Added `tools/neural_artifact_validator.py` as the promotion gate
for generated neural/graph-policy JSON artifacts. It validates `_meta` shape,
`schema_version`, expected source tool, execution mode, ISO update date,
freshness, candidate trade-count gates, overfit flags, weight ranges, and metadata
count consistency.

Added `make neural-artifacts` to run the validator explicitly. It is intentionally
not part of `make quality`, because a clean checkout may not have generated
runtime artifacts and existing local artifacts should fail until regenerated.

**Fail-closed wiring applied**: Future artifact writers now emit schema/execution
metadata, and live/report consumers use `load_validated_json()` before consuming
learned artifacts. Invalid neural artifacts are skipped instead of silently
influencing live dip/support decisions, pool sizing, sell target fallbacks, order
adjustments, broker reconciliation, daily analyzer neural sections, or wick
capital overrides.

Updated writers:
- `neural_candidate_discoverer.py`
- `neural_support_discoverer.py`
- `neural_watchlist_sweeper.py`
- `parameter_sweeper.py`
- `support_parameter_sweeper.py`
- `weight_learner.py`
- `ticker_clusterer.py`

**Test coverage added**: `tests/test_neural_artifact_validator.py`
- valid fixture artifacts pass
- stale artifacts fail freshness checks
- dip candidates require minimum validation trades
- support sweep metadata counts must match entries
- missing schema version fails the contract
- `load_validated_json()` raises `ArtifactValidationError` on invalid artifacts

**Verification**:
- `python3 -m pytest tests/test_neural_artifact_validator.py -q` -> 6 passed
- `python3 -m py_compile tools/neural_artifact_validator.py ...` -> OK
- `python3 -m pytest tests/test_tool_imports.py -q` -> 124 passed
- `python3 -m pytest -q` -> 487 passed
- `python3 tools/neural_artifact_validator.py --allow-stale` -> expected failure
  on current local generated artifacts due missing schema/execution metadata,
  low `val_trades`, and support sweep count mismatch

**Original report (kept for context):**
**Status**: OPEN (filed 2026-04-25)

**Symptom observed**: Generated neural artifacts appear stale or inconsistent after
the first-pass sanitization and conservative backtest hardening:
- `data/neural_candidates.json` was generated before the current validation gate.
- `data/neural_support_candidates.json` predates the recent execution-assumption
  hardening.
- `data/support_sweep_results.json` metadata says one ticker was swept while the
  file contains hundreds of entries.

**Root cause**: Neural artifacts are treated as plain generated JSON without a
shared schema/version contract, freshness policy, or promotion gate tied to the
current execution assumptions.

**Proposed fix**:
- Add a validator for neural artifacts used by live/reporting code:
  `neural_candidates.json`, `neural_support_candidates.json`,
  `neural_watchlist_profiles.json`, `synapse_weights.json`,
  `ticker_profiles.json`, and sweep result files.
- Validate `_meta.updated`, schema version, source tool/version, execution mode,
  minimum validation trades, metadata counts, and required fields.
- Fail closed for live decisioning when required neural artifacts are stale,
  malformed, or generated under incompatible assumptions.
- Add a command or Make target for neural artifact validation.

**Verification**:
- Tests for valid artifacts, stale artifacts, malformed artifacts, mismatched
  counts, and incompatible execution-mode metadata.
- Validator exits non-zero on intentionally broken fixture artifacts.
- `make quality`

**Expected impact**: The system stops trusting stale or internally inconsistent
learned outputs after strategy/backtest semantics change.

---

## ~~DESIGN: Replace support evaluator markdown parsing with structured data~~ — RESOLVED
**Status**: CLOSED (2026-04-25)
**Priority**: P1 - support decisions should not depend on stale generated prose.

**Fix applied**: Replaced `tools/neural_support_evaluator.py` markdown parsing with
structured `wick_offset_analyzer.analyze_stock_data()` output. The evaluator now
extracts buy levels from `data["bullet_plan"]["active"]` and
`data["bullet_plan"]["reserve"]`, rejects stale structured analyzer output, and
records support source metadata in each opportunity plus the evaluator cache.
`wick_analysis.md` remains operator-facing output only.

**Test coverage added**: `tests/test_neural_support_evaluator.py`
- support levels are loaded from structured analyzer output, not markdown
- stale structured analyzer output fails closed
- opportunities preserve support source, zone, tier, and source-data date

**Verification**:
- `python3 -m pytest tests/test_neural_support_evaluator.py -q` -> 3 passed
- `python3 -m py_compile tools/neural_support_evaluator.py tests/test_neural_support_evaluator.py` -> OK
- `python3 -m pytest tests/test_neural_support_evaluator.py tests/test_neural_artifact_validator.py tests/test_tool_imports.py -q` -> 136 passed

**Original report (kept for context):**
**Status**: OPEN (filed 2026-04-25)

**Symptom observed**: `tools/neural_support_evaluator.py` loads support levels by
parsing cached `tickers/<ticker>/wick_analysis.md`. If that markdown is missing,
stale, ignored by source control, or generated with old assumptions, the evaluator
can silently produce no opportunity or a stale opportunity.

**Root cause**: A live decision path depends on generated markdown instead of a
structured support-level artifact with schema, timestamp, and source metadata.

**Proposed fix**:
- Replace markdown parsing with structured output from
  `wick_offset_analyzer.analyze_stock_data()` or a cached JSON artifact.
- Include schema version, generation timestamp, ticker, source data window, and
  analyzer parameters.
- Add a freshness check before live support evaluation.
- Keep markdown reports as operator-facing output only.

**Verification**:
- Unit test for support evaluation using structured support-level fixtures.
- Unit test proving stale/missing structured data fails closed or recomputes,
  depending on the chosen contract.
- `python3 -m pytest -q`

**Expected impact**: Support recommendations become reproducible and auditable
instead of depending on parsed prose files.

---

## ~~DESIGN: Decide and enforce whether learned support weights affect live policy~~ — RESOLVED
**Status**: CLOSED (2026-04-25)
**Priority**: P1 - closes the gap between training outputs and live behavior.

**Decision**: Support outcome gates are diagnostic only. They are reconstructed
from outcomes such as P/L, days held, or stop behavior, so they are not live input
signals and must not affect support recommendations, pool sizing, order
adjustment, or dip decisions.

**Fix applied**:
- `weight_learner.save_weights()` now splits policy weights from
  diagnostic-only support gates.
- Live policy gates stay in `data/synapse_weights.json:weights`:
  `*:dip_gate`, `*:bounce_gate`, and `*:candidate`.
- Support diagnostics move to `data/synapse_weights.json:diagnostic_weights`:
  `*:profit_gate`, `*:hold_gate`, and `*:stop_gate`.
- Existing support gates found in legacy `weights` are migrated out of the live
  policy map on the next save.
- `neural_artifact_validator.py` rejects diagnostic support gates if they appear
  in policy `weights`, and rejects policy gates if they appear in
  `diagnostic_weights`.
- Added `docs/neural-graph-policy.md` and linked it from the README.

**Test coverage added**: `tests/test_weight_learner.py`
- support gates are saved as diagnostics only
- legacy support gates are migrated out of policy weights
- unknown non-policy gates are diagnostic by default

**Additional validation coverage**:
- `tests/test_neural_artifact_validator.py` now rejects support diagnostic gates
  in the live policy weight map.

**Verification**:
- `python3 -m pytest tests/test_weight_learner.py tests/test_neural_artifact_validator.py -q` -> 10 passed
- `python3 -m py_compile tools/weight_learner.py tools/historical_trade_trainer.py tools/support_parameter_sweeper.py tools/neural_artifact_validator.py tests/test_weight_learner.py tests/test_neural_artifact_validator.py` -> OK
- `python3 -m pytest tests/test_weight_learner.py tests/test_neural_artifact_validator.py tests/test_tool_imports.py -q` -> 134 passed
- `python3 -m pytest -q` -> 494 passed

**Original report (kept for context):**
**Status**: OPEN (filed 2026-04-25)

**Symptom observed**: Training/sweep paths emit support-style learned inputs such
as `profit_gate`, `hold_gate`, and `stop_gate`, but live support decisioning mostly
uses candidate/profile JSON and cached support levels. The learned support gates
do not appear to be first-class live policy inputs.

**Root cause**: The project has a partial learned-support story: artifacts are
created and retained, but the live consumers do not consistently consume the same
signals.

**Proposed fix**:
- Choose one contract:
  - Wire learned support gates/weights into live support scoring and order
    adjustment, with tests; or
  - Remove/de-emphasize unused support gates from training artifacts and docs.
- Document which fields are learned policy inputs versus diagnostic metadata.
- Add tests proving the chosen learned fields affect, or intentionally do not
  affect, support recommendations.

**Verification**:
- Focused tests around `neural_support_evaluator`, `shared_utils.get_ticker_pool`,
  and `neural_order_adjuster` as applicable.
- Artifact fixture test proving unused fields do not create misleading behavior.
- `python3 -m pytest -q`

**Expected impact**: Operators can tell which support behavior is genuinely learned
and which behavior is deterministic configuration.

---

## ~~TESTING: Add behavioral coverage for neural graph policy and weight learning~~ — RESOLVED
**Status**: CLOSED (2026-04-25)
**Priority**: P1 - protects the neural layer from silent regressions.

**Fix applied**: Added focused behavioral tests for the neural graph policy surface
across live dip evaluation, neural dip replay, support evaluation, artifact
contracts, and weight learning.

**Coverage now in place**:
- `tests/test_neural_dip_evaluator.py`: live decision propagation and no-buy path.
- `tests/test_neural_dip_backtester.py`: first-hour key contract, strict legacy-key
  rejection, and live/replay parity using the real graph builders on the same
  synthetic state.
- `tests/test_neural_support_evaluator.py`: structured support analyzer output,
  stale-data fail-closed behavior, and opportunity source metadata.
- `tests/test_neural_artifact_validator.py`: artifact schema/freshness/count
  contract plus fail-closed validated loading.
- `tests/test_weight_learner.py`: direct `update_weights()` behavior for
  profitable strengthening, losing attenuation, clamping to `[0, 1]`, and the
  current no-inhibitory-weight limitation; also covers diagnostic support weight
  separation.

**Verification**:
- `python3 -m pytest tests/test_weight_learner.py tests/test_neural_dip_backtester.py -q` -> 9 passed
- `python3 -m py_compile tests/test_weight_learner.py tests/test_neural_dip_backtester.py` -> OK
- `python3 -m pytest tests/test_graph.py tests/test_neural_dip_evaluator.py tests/test_neural_dip_backtester.py tests/test_neural_support_evaluator.py tests/test_neural_artifact_validator.py tests/test_weight_learner.py -q` -> 114 passed
- `python3 -m pytest -q` -> 498 passed

**Original report (kept for context):**
**Status**: OPEN (filed 2026-04-25)

**Symptom observed**: Existing graph tests cover generic graph mechanics, and import
health covers module loadability, but there is limited behavioral coverage for:
live dip evaluation, neural dip replay, support evaluation, neural artifact
contracts, and `weight_learner.update_weights()`.

**Root cause**: The neural layer evolved through operational scripts and generated
artifacts faster than focused regression tests were added.

**Proposed fix**:
- Add synthetic fixtures for dip live evaluation, dip replay, support candidate
  evaluation, and weight updates.
- Test the current weight model explicitly: weights clamp to `[0, 1]`, profitable
  trades increase/retain signal strength, losing trades attenuate signal strength,
  and negative/inhibitory correlations are not represented unless the model is
  expanded.
- Add parity tests where the same synthetic graph state produces compatible live
  and replay decisions.

**Verification**:
- New focused neural test module(s).
- `python3 -m pytest tests/test_graph.py <new neural tests> -q`
- `python3 -m pytest -q`

**Expected impact**: The neural implementation has executable contracts instead of
only generated-output inspection.

---

## ~~DOCS: Clarify "neural" as learned graph policy unless true ML semantics are added~~ — RESOLVED
**Status**: CLOSED (2026-04-25)
**Priority**: P2 - reduces operator and maintainer confusion.

**Fix applied**: Added and expanded `docs/neural-graph-policy.md` to state that
the `neural_*` layer is an explainable learned graph policy, not a trained neural
network. The doc lists learned policy weights, diagnostic-only weights, swept dip
parameters, swept support parameters, deterministic static gates, and generated
artifacts. Linked the contract from `README.md`.

Updated `tools/neural_candidate_discoverer.py` wording from "neural network" to
"learned graph policy" so operator-facing tool docs do not overstate the
implementation.

**Verification**:
- `rg -n "neural network|trained neural|learned graph policy|graph policy" README.md docs strategy.md tools/neural_* tools/weight_learner.py tools/historical_trade_trainer.py` -> remaining matches either say "not a trained neural network" or "learned graph policy"
- `python3 -m py_compile tools/neural_candidate_discoverer.py` -> OK
- `python3 -m pytest tests/test_tool_imports.py -q` -> 124 passed

**Original report (kept for context):**
**Status**: OPEN (filed 2026-04-25)

**Symptom observed**: The code and artifacts use "neural" terminology, but the
current implementation is an explainable rule/dependency graph with swept
parameters and a simple Hebbian-style weight table. It is not a neural network in
the ML sense.

**Root cause**: Naming grew around the analogy before the implementation had a
clear model contract.

**Proposed fix**:
- Document the implementation as a learned graph policy: deterministic gates,
  learned/swept parameters, graph propagation, and generated artifacts.
- List exactly which fields are learned, which are swept, and which are static
  operator configuration.
- Either rename operator-facing docs from "neural" to "graph policy" where
  practical, or add a prominent terminology note.

**Verification**:
- README or strategy docs describe the neural/graph-policy architecture accurately.
- No docs imply the project is using a trained neural network unless a true model
  is introduced.

**Expected impact**: Future maintenance focuses on the actual system properties:
parity, artifact validity, explainability, and regression coverage.

---

## Roadmap Integration Contract
Every roadmap task below must include an explicit weekly-pipeline integration check
before it can be marked resolved:

- No roadmap item may ship as a standalone tool or artifact only. Each item must
  upgrade at least one existing operational tool that is already used by the
  workflow.
- If it changes candidate ranking or sizing, it must write fields into the sweep or
  profile artifacts consumed by `tools/weekly_reoptimize.py` and
  `tools/watchlist_tournament.py`.
- If it changes live recommendations, it must be consumed by the live/reporting path
  that already runs from cron, such as `neural_support_evaluator.py`,
  `neural_dip_evaluator.py`, `daily_analyzer.py`, `neural_order_adjuster.py`, or
  shared allocation helpers.
- If it produces learned/calibrated artifacts, those artifacts must be generated or
  promoted inside the Saturday pipeline before downstream steps read them.
- Verification must include either a direct unit/integration test for the consumer
  path or a weekly pipeline dry-run/tournament fixture proving the new fields affect
  output ranking, sizing, gating, or reports.
- The resolution note must include a `Wired existing tools:` line naming the exact
  existing scripts/functions upgraded, such as `tools/weekly_reoptimize.py`,
  `tools/wick_offset_analyzer.py`, `tools/bullet_recommender.py`,
  `tools/daily_analyzer.py`, `tools/batch_onboard.py`, or
  `tools/portfolio_manager.py:record_fill/record_sell`.

---

## ~~PROFIT: Add expected-value scoring for graph-policy candidates~~ — RESOLVED
**Status**: CLOSED (2026-04-25)
**Priority**: P1 - turns pass/fail gates into rankable expected-edge decisions.

**Fix applied**: Added `tools/expected_edge.py` with a transparent expected-edge
scorer for already-gated graph-policy candidates. Dip and support sweep artifacts
now include `expected_edge`, `expected_edge_pct`, `graph_score`,
`edge_adjusted_composite`, and `edge_components` in each ticker's `stats`. The
tournament now prefers `edge_adjusted_composite` when present and falls back to
legacy `composite` for older artifacts.

**Wired existing tools**:
- `tools/parameter_sweeper.py` emits edge fields into `data/sweep_results.json`.
- `tools/support_parameter_sweeper.py` emits edge fields into
  `data/support_sweep_results.json`.
- `tools/weekly_reoptimize.py` already regenerates those artifacts before running
  the tournament, so the upgraded fields enter the Saturday pipeline.
- `tools/watchlist_tournament.py` consumes the upgraded score path for rankings.

**Verification**:
- `python3 -m py_compile tools/expected_edge.py tools/parameter_sweeper.py tools/support_parameter_sweeper.py tools/watchlist_tournament.py tests/test_expected_edge.py`
- `python3 -m pytest tests/test_expected_edge.py -q`
- `python3 -m pytest tests/test_expected_edge.py tests/test_neural_artifact_validator.py tests/test_tool_imports.py -q`
- `python3 -m pytest -q`
- `python3 tools/watchlist_tournament.py --dry-run --no-email`

**Original report (kept for context):**
**Status**: OPEN (filed 2026-04-25)

**Symptom observed**: The graph policy mostly emits binary pass/fail decisions.
Candidates that survive hard gates are ranked by simple strategy-specific fields
such as dip magnitude or support proximity, not by calibrated expected value.

**Root cause**: The current graph architecture protects safety and explainability,
but it does not compute a single comparable edge score that combines target odds,
stop odds, expected return, transaction costs, fill probability, confidence, and
capital lockup.

**Proposed fix**:
- Add a `graph_score` / `expected_edge` field for every surviving dip and support
  candidate.
- Compute a transparent score from existing graph features:
  target/stop distance, historical hit rates, recovery behavior, recentness,
  execution costs, spread/slippage assumptions, and confidence.
- Keep hard safety gates deterministic; scoring only ranks candidates that survive.
- Include score components in reports so operators can see why one candidate ranks
  above another.
- Wire `expected_edge` into the weekly-generated artifacts that rank opportunities:
  dip sweep/candidate outputs, support sweep/profile outputs, and tournament
  composites where applicable.

**Existing-tool wiring required**:
- `tools/parameter_sweeper.py` and `tools/support_parameter_sweeper.py` must emit
  score fields into existing sweep artifacts.
- `tools/weekly_reoptimize.py` must regenerate those artifacts before tournament.
- `tools/watchlist_tournament.py` must consume the upgraded score/composite path.
- `tools/neural_dip_evaluator.py`, `tools/neural_support_evaluator.py`, or
  `tools/daily_analyzer.py` must display/use the score where live recommendations
  are affected.

**Verification**:
- Synthetic tests where higher target probability and lower stop risk rank first.
- Tests proving hard safety gates still block candidates regardless of score.
- Backtest/report fixture showing old binary decisions plus new score fields.
- Tournament or weekly-pipeline fixture proving `expected_edge` changes the ranked
  order when all hard gates are equal.
- `python3 -m pytest -q`

**Expected impact**: Candidate selection becomes profit/risk ranked rather than
only gate-passing, improving budget focus when multiple opportunities appear.

---

## ~~PROFIT: Add calibrated probability layer over graph features~~ — RESOLVED
**Status**: CLOSED (2026-04-25)
**Priority**: P1 - improves score quality before considering a true neural model.

**Fix applied**: Added `tools/probability_calibrator.py`, which builds promoted
probability calibration buckets from existing dip/support sweep outcomes and writes
`data/probability_calibration.json` with schema/source/execution metadata. Extended
`tools/neural_artifact_validator.py` so the calibration artifact is part of the
validated graph-policy artifact surface. Updated `tools/expected_edge.py` so
target/stop probabilities are calibrated through the validated artifact when it is
fresh and valid, while invalid/missing calibration fails closed to raw feature
probabilities.

The weekly pipeline now runs a probability-calibration step before sweeps generate
new expected-edge scores. The generated calibration artifact was created locally
from existing sweep data and validated successfully.

**Wired existing tools**:
- `tools/weekly_reoptimize.py` runs `tools/probability_calibrator.py` before sweep
  scoring/tournament artifacts are regenerated.
- `tools/probability_calibrator.py` builds `data/probability_calibration.json` from
  existing `data/sweep_results.json` and `data/support_sweep_results.json`.
- `tools/neural_artifact_validator.py` validates the calibration artifact schema,
  freshness, source, execution mode, buckets, and probability ranges.
- `tools/expected_edge.py` consumes validated calibration data for dip/support
  target and stop probabilities.
- `tools/parameter_sweeper.py` and `tools/support_parameter_sweeper.py` inherit the
  calibrated scoring path because both call `attach_expected_edge()`.
- `tools/watchlist_tournament.py` consumes the resulting calibrated
  `edge_adjusted_composite` through the existing ranking path.

**Verification**:
- `python3 -m py_compile tools/probability_calibrator.py tools/neural_artifact_validator.py tools/expected_edge.py tools/weekly_reoptimize.py tests/test_expected_edge.py tests/test_neural_artifact_validator.py`
- `python3 -m pytest tests/test_expected_edge.py tests/test_neural_artifact_validator.py -q`
- `python3 tools/probability_calibrator.py --dry-run`
- `python3 tools/probability_calibrator.py`
- `python3 tools/neural_artifact_validator.py --file probability_calibration.json`
- `python3 -m pytest tests/test_expected_edge.py tests/test_neural_artifact_validator.py tests/test_tool_imports.py -q`
- `python3 -m pytest -q`

**Original report (kept for context):**
**Status**: OPEN (filed 2026-04-25)

**Symptom observed**: Current learned weights attenuate graph inputs but do not
produce calibrated probabilities such as probability of target, probability of
stop, probability of fill, or expected hold time.

**Root cause**: The existing reward-modulated weight learner is useful but limited:
weights clamp to `[0, 1]`, there are no bias terms, no inhibitory relationships,
and no probability calibration.

**Proposed fix**:
- Train a simple calibrated model over graph-policy features first: logistic
  regression, isotonic calibration, or another small interpretable model.
- Produce probabilities for target hit, stop hit, fill likelihood, and expected
  hold-time bucket where data supports it.
- Store calibration artifacts with schema/source/execution metadata and validate
  them through the artifact validator.
- Feed calibrated probabilities into `expected_edge` scoring, not directly into
  hard safety gates.
- Add the calibration build/promotion step to the Saturday re-optimization flow
  before `expected_edge` scoring reads calibrated probabilities.

**Existing-tool wiring required**:
- `tools/weekly_reoptimize.py` must build or promote calibration artifacts before
  sweep scoring/tournament steps run.
- `tools/neural_artifact_validator.py` must validate calibration artifacts.
- Existing scoring consumers, especially `tools/parameter_sweeper.py`,
  `tools/support_parameter_sweeper.py`, `tools/neural_dip_evaluator.py`, and
  `tools/neural_support_evaluator.py`, must load promoted calibration data through
  the validator and fail closed.
- `tools/daily_analyzer.py` must surface probability/score evidence when it changes
  operator-facing recommendations.

**Verification**:
- Fixture tests for calibration artifact schema and fail-closed loading.
- Walk-forward validation showing calibrated probabilities are better than raw
  hit-rate baselines.
- Reliability/bucket report comparing predicted probability vs realized outcome.
- Pipeline fixture proving fresh promoted calibration artifacts are loaded by the
  weekly sweep/scoring path and stale or rejected artifacts fail closed.
- `python3 -m pytest -q`

**Expected impact**: Scores become more decision-grade and less dependent on raw
thresholds or uncalibrated historical averages.

---

## ~~VALIDATION: Add walk-forward promotion gate for learned and swept artifacts~~ — RESOLVED
**Status**: CLOSED (2026-04-25)
**Priority**: P1 - prevents worse artifacts from replacing better live behavior.

**Fix applied**: Added `tools/artifact_promoter.py`, a reusable promotion gate for
generated graph-policy artifacts. The gate snapshots the incumbent live artifact,
validates the candidate through `tools/neural_artifact_validator.py`, computes a
transparent promotion score, and either leaves the candidate promoted or restores
the incumbent. Rejected candidates are archived under `data/artifact_promotion/`
with a JSON promotion report explaining the decision.

`tools/weekly_reoptimize.py` now snapshots and promotes the artifacts that feed
downstream weekly/live behavior before downstream consumers run: probability
calibration, dip sweep results, support sweep results, ticker profiles, and
synapse weights. Existing consumers continue to read only the normal live artifact
paths, so an unpromoted candidate cannot silently feed the tournament, daily
analyzer, bullet recommender, or live evaluators.

**Wired existing tools**:
- `tools/weekly_reoptimize.py` snapshots incumbents and calls the promotion gate
  around probability calibration, dip sweeps, support sweeps, clustering profiles,
  and weight training.
- `tools/artifact_promoter.py` validates, scores, promotes, rejects, restores, and
  reports artifact decisions.
- `tools/neural_artifact_validator.py` remains the schema/freshness gate used before
  any candidate artifact can be promoted.
- `tools/watchlist_tournament.py`, `tools/daily_analyzer.py`,
  `tools/bullet_recommender.py`, `tools/neural_dip_evaluator.py`, and
  `tools/neural_support_evaluator.py` keep reading the promoted live artifact paths.

**Verification**:
- `python3 -m py_compile tools/artifact_promoter.py tools/weekly_reoptimize.py tests/test_artifact_promoter.py`
- `python3 -m pytest tests/test_artifact_promoter.py tests/test_neural_artifact_validator.py tests/test_expected_edge.py -q`
- `python3 -m py_compile tools/artifact_promoter.py tools/weekly_reoptimize.py tools/neural_artifact_validator.py tools/expected_edge.py tests/test_artifact_promoter.py tests/test_neural_artifact_validator.py tests/test_expected_edge.py`
- `python3 -m pytest -q`

**Original report (kept for context):**
**Status**: OPEN (filed 2026-04-25)

**Symptom observed**: Sweep, profile, and weight artifacts can be regenerated, but
the system does not yet require a candidate artifact to beat the currently live
artifact out-of-sample after costs before promotion.

**Root cause**: Artifact validation now checks shape, freshness, and metadata, but
not comparative performance against the incumbent artifact.

**Proposed fix**:
- Add an incumbent-vs-candidate artifact promotion command.
- Evaluate candidate artifacts on walk-forward windows with conservative execution
  assumptions and transaction costs.
- Compare expected edge, realized P/L, drawdown, hit rate, fill rate, capital
  utilization, and dead-capital time.
- Only promote when candidate artifacts beat incumbent artifacts by a configured
  margin and do not violate risk limits.
- Write a promotion report explaining pass/fail and archive rejected artifacts.
- Make the Saturday pipeline write candidates to staging paths first, then promote
  accepted artifacts to the live paths consumed by tournament and daily tools.

**Existing-tool wiring required**:
- `tools/weekly_reoptimize.py` must write regenerated artifacts to staging and call
  the promotion gate before downstream consumers run.
- `tools/watchlist_tournament.py`, `tools/daily_analyzer.py`,
  `tools/bullet_recommender.py`, and live evaluators must read only promoted/live
  artifact paths.
- `tools/neural_artifact_validator.py` must reject unpromoted or stale staged
  artifacts from live/reporting consumers.

**Verification**:
- Fixture where a better candidate artifact is promoted.
- Fixture where a worse candidate artifact is rejected.
- Fixture where higher P/L but worse drawdown/risk fails promotion.
- Weekly-pipeline fixture proving downstream tournament/live consumers read the
  promoted incumbent/live artifact, not an unpromoted staging artifact.
- `python3 -m pytest -q`

**Expected impact**: The system stops trusting regenerated artifacts merely because
they are new, and only deploys changes that improve out-of-sample behavior.

---

## ~~OBSERVABILITY: Track live prediction quality and realized outcomes~~ — RESOLVED
**Status**: RESOLVED (implemented 2026-04-25)
**Fix applied**:
- Added `tools/prediction_ledger.py` as the live decision-to-outcome ledger for
  graph-policy recommendations.
- Live dip and support recommendations now write prediction rows with
  recommendation details, expected-edge score components, candidate features,
  artifact version markers, and reason chains.
- Portfolio fills/sells now link executions back to open prediction rows,
  including fill accuracy, hold days, exit reason, and realized P/L.
- Daily analysis now prints the prediction-ledger summary, and weekly calibration
  receives live prediction aggregates through `probability_calibrator.py`.
- Ledger reporting includes realized performance by strategy, ticker, regime,
  score bucket, and artifact version.

**Wired existing tools**:
- `tools/neural_dip_evaluator.py`: writes live `dip` prediction records when a
  non-dry-run BUY_DIP recommendation is emitted.
- `tools/neural_support_evaluator.py`: writes live `support` prediction records
  when actionable support alerts are sent.
- `tools/portfolio_manager.py`: `record_fill`/`record_sell` link actual fills and
  exits through the ledger via the existing portfolio transaction path used by
  manual trade recording and `daily_analyzer.py`.
- `tools/daily_analyzer.py`: prints the ledger summary during the normal daily
  report.
- `tools/weekly_reoptimize.py`: already runs `tools/probability_calibrator.py`;
  the calibrator now reads `data/prediction_ledger.json` and embeds live
  prediction aggregates into calibration metadata.

**Verification**:
- `python3 -m py_compile tools/prediction_ledger.py tools/neural_dip_evaluator.py tools/neural_support_evaluator.py tools/portfolio_manager.py tools/daily_analyzer.py tools/probability_calibrator.py`
- `python3 -m pytest tests/test_prediction_ledger.py tests/test_portfolio_manager_safety.py tests/test_neural_support_evaluator.py tests/test_neural_dip_backtester.py tests/test_expected_edge.py -q`
- `python3 tools/probability_calibrator.py --dry-run`
- `python3 tools/probability_calibrator.py`
- `python3 tools/neural_artifact_validator.py --file probability_calibration.json`
- `python3 -m pytest -q`

**Original report (kept for context)**:
**Priority**: P1 - closes the learning loop from decision to realized performance.

**Symptom observed**: The system can report decisions and outcomes, but it does not
yet persist a complete prediction ledger linking decision-time expected edge to
actual fill, exit, hold time, and P/L.

**Root cause**: Trade history captures executions, while graph-policy scoring and
candidate rationale are not stored as first-class prediction records.

**Proposed fix**:
- Add a prediction ledger for every live graph-policy recommendation.
- Store decision timestamp, ticker, candidate features, score components,
  expected edge, probabilities, recommended size, artifact versions, and reason
  chain.
- On fill/exit, link realized fill price, hold time, exit reason, gross/net P/L,
  and whether the original prediction was directionally correct.
- Add a report comparing expected vs realized performance by ticker, regime,
  strategy type, and artifact version.
- Ensure weekly training/calibration can read the ledger as an input, while live
  evaluators write prediction records during normal cron execution.

**Existing-tool wiring required**:
- `tools/neural_dip_evaluator.py` and `tools/neural_support_evaluator.py` must write
  prediction records when they create recommendations.
- `tools/daily_analyzer.py` must include the ledger summary/report.
- `tools/portfolio_manager.py:record_fill` and `tools/portfolio_manager.py:record_sell`
  must link fills/sells back to open prediction records.
- `tools/weekly_reoptimize.py` must make the ledger available to calibration,
  scoring, or training steps.

**Verification**:
- Tests for writing prediction records without mutating portfolio state.
- Tests linking fills/exits back to the originating prediction.
- Report fixture showing calibration error and realized P/L by score bucket.
- Integration test proving a live recommendation creates a ledger row and the
  weekly calibration/training path can aggregate it.
- `python3 -m pytest -q`

**Expected impact**: Future learning can optimize against actual live prediction
quality instead of only regenerated backtests and ad-hoc inspection.

---

## ~~PROFIT: Allocate capital by expected value, confidence, and opportunity cost~~ — RESOLVED
**Status**: RESOLVED (implemented 2026-04-25)
**Fix applied**:
- Added a shared edge-adjusted allocation contract in `tools/shared_utils.py`.
  It sizes from expected edge, confidence, fill likelihood, stop risk,
  hold-time risk, and dead-capital/dormancy penalties.
- Upgraded wick bullet-plan sizing so `compute_pool_sizing()` tilts pool dollars
  toward stronger risk-adjusted levels while preserving pool caps and broker
  share-rounding rules.
- Upgraded live support alerts and neural order adjustments to use the shared
  allocation contract instead of fixed `pool / bullets / price` sizing.
- Upgraded dip recommendations from equal-split budget to edge/confidence/risk
  adjusted budgets within the total dip cap.
- Added allocation action/multiplier/reason fields to bullet plans, support
  opportunities, order-adjuster output, dip alerts, onboarding wick summaries,
  and prediction-ledger recommendation payloads.

**Wired existing tools**:
- `tools/shared_utils.py`: exposes `compute_allocation_signal()` and
  `compute_position_allocation()` as the shared sizing contract.
- `tools/wick_offset_analyzer.py`: uses the shared contract when building
  structured bullet plans and reports allocation multipliers in wick output.
- `tools/bullet_recommender.py`: uses the upgraded wick sizing path and reports
  allocation multipliers in the Level Map.
- `tools/neural_support_evaluator.py`: sizes actionable support alerts through
  the shared contract and records allocation context in prediction rows.
- `tools/neural_dip_evaluator.py`: sizes live dip budgets through the shared
  contract and records allocation context in prediction rows.
- `tools/neural_order_adjuster.py`: compares pending BUY orders against the
  upgraded allocation contract and reports why shares changed.
- `tools/daily_analyzer.py`: already calls `neural_order_adjuster`, so its daily
  report now includes upgraded buy sizing.
- `tools/batch_onboard.py`: preserves allocation action/multiplier/share fields
  in generated onboarding wick summaries.

**Verification**:
- `python3 -m py_compile tools/shared_utils.py tools/wick_offset_analyzer.py tools/bullet_recommender.py tools/neural_support_evaluator.py tools/neural_dip_evaluator.py tools/neural_order_adjuster.py tools/batch_onboard.py`
- `python3 -m pytest tests/test_capital_allocation.py tests/test_wick_offset_analyzer.py tests/test_neural_support_evaluator.py tests/test_neural_dip_backtester.py tests/test_expected_edge.py -q`
- `python3 -m pytest -q`

**Original report (kept for context)**:
**Priority**: P1 - makes sizing follow edge rather than mostly fixed buckets.

**Symptom observed**: Dip budgets and support pools are still mostly fixed,
equal-split, or profile-driven. Candidate confidence and expected edge do not yet
drive capital allocation in a unified way.

**Root cause**: The system has strong gate logic and pool controls, but sizing is
not yet tied to expected value, uncertainty, fill probability, or dead-capital
risk.

**Proposed fix**:
- Use `expected_edge`, confidence, fill likelihood, stop risk, and hold-time risk
  to size candidate allocations.
- Keep hard caps for PDT, pool limits, per-ticker concentration, sector
  concentration, and reserve requirements.
- Add an opportunity-cost penalty for orders unlikely to fill soon or likely to
  tie up capital at dormant levels.
- Report why capital was increased, reduced, or skipped.
- Wire allocation outputs into the shared pool/sizing helpers and order-adjuster
  paths used after weekly artifacts are regenerated.

**Existing-tool wiring required**:
- Shared allocation helpers in `tools/shared_utils.py` must expose the upgraded
  pool/bullet sizing contract.
- `tools/wick_offset_analyzer.py` must use the upgraded sizing when building the
  structured bullet plan.
- `tools/bullet_recommender.py`, `tools/neural_order_adjuster.py`, and
  `tools/daily_analyzer.py` must use/report the upgraded allocation.
- `tools/batch_onboard.py` must produce onboarding artifacts/sweeps that preserve
  the upgraded allocation fields for new tickers.

**Verification**:
- Tests where higher expected edge receives larger allocation within caps.
- Tests where high edge but low confidence or high drawdown risk is capped.
- Tests where dormant/dead-capital penalty reduces or skips allocation.
- Weekly/live consumer fixture proving changed edge/confidence changes recommended
  pool, bullet count, or shares in the generated reports/orders.
- `python3 -m pytest -q`

**Expected impact**: More capital goes to the best risk-adjusted opportunities,
while weaker or slower opportunities consume less budget.

---

## ~~PROFIT: Improve support-level ranking beyond proximity~~ — RESOLVED
**Status**: RESOLVED (implemented 2026-04-25)
**Fix applied**:
- Added `compute_support_level_score()` in `tools/shared_utils.py` to score
  support levels by expected recovery edge, fill likelihood, tier, zone,
  recent behavior, dormancy, frequency, confidence, distance, and capital lockup.
- `tools/wick_offset_analyzer.py` now computes and persists
  `support_score`, `support_expected_edge_pct`, and
  `support_score_components` on both structured `levels` and `bullet_plan`
  entries.
- `tools/neural_support_evaluator.py` now sorts opportunities by support score
  before distance and includes score/edge/components in the report, cache, and
  prediction-ledger payload.
- `tools/bullet_recommender.py` now ranks level display and next-bullet selection
  by support score, falling back to proximity only as a tie-breaker.
- `tools/batch_onboard.py` now preserves support score and expected edge in
  generated onboarding wick summaries.

**Wired existing tools**:
- `tools/shared_utils.py`: exposes the shared support-level scoring contract.
- `tools/wick_offset_analyzer.py`: computes/persists score fields in weekly/live
  structured bullet plans.
- `tools/bullet_recommender.py`: recommends the next eligible bullet by score.
- `tools/neural_support_evaluator.py`: ranks actionable support opportunities by
  score and writes score fields to `data/support_eval_latest.json`.
- `tools/daily_analyzer.py`: consumes the upgraded support evaluator cache and
  existing support/bullet flows now carrying score fields.
- `tools/batch_onboard.py`: includes score fields when creating initial wick
  summaries for new tickers.

**Verification**:
- `python3 -m py_compile tools/shared_utils.py tools/wick_offset_analyzer.py tools/bullet_recommender.py tools/neural_support_evaluator.py tools/batch_onboard.py`
- `python3 -m pytest tests/test_neural_support_evaluator.py tests/test_wick_offset_analyzer.py tests/test_capital_allocation.py -q`
- `python3 -m pytest -q`

**Original report (kept for context)**:
**Priority**: P1 - improves support entries before adding model complexity.

**Symptom observed**: Support scanning identifies levels near price, but ranking is
still heavily proximity-driven after structural gates. It does not fully rank by
expected bounce quality, fill likelihood, capital lockup, and recent behavior.

**Root cause**: Wick analysis provides rich level features, but the support
evaluator does not yet combine them into a profit/risk ranking score.

**Proposed fix**:
- Add support-level `expected_edge` using decayed hold rate, recent approaches,
  monthly touch frequency, tier, zone, dormancy, expected bounce/target, and
  fill likelihood.
- Penalize dormant levels, low touch-frequency levels, weak recent behavior, and
  levels that would tie up too much capital.
- Rank actionable support opportunities by support-level score, not only distance
  to buy price.
- Include score components in the support report and evaluator cache.
- Persist support-level scores into the daily support evaluator cache and any
  weekly support profile artifacts that tournament/reporting should inspect.

**Existing-tool wiring required**:
- `tools/wick_offset_analyzer.py` must compute/persist support-level score
  components in `bullet_plan`.
- `tools/bullet_recommender.py` must rank/recommend bullets using the upgraded level
  score when choosing among eligible levels.
- `tools/neural_support_evaluator.py` must sort actionable support opportunities
  by the upgraded score, not only proximity.
- `tools/daily_analyzer.py` and `tools/batch_onboard.py` must surface/use the score
  through their existing support/onboarding flows.

**Verification**:
- Tests where a slightly farther high-quality level outranks a closer weak level.
- Tests where dormant levels are penalized despite attractive distance.
- Tests where score components are present in cached opportunities.
- Support evaluator fixture proving sorted actionable opportunities use
  support-level `expected_edge`, not only proximity.
- `python3 -m pytest -q`

**Expected impact**: Support orders are placed at levels with better expected
recovery behavior, not just the nearest eligible support.

---

## ~~DECISION: Add model-complexity gate before introducing a true neural network~~ — RESOLVED
**Status**: RESOLVED (implemented 2026-04-25)
**Runtime behavior changed**:
- Promoted graph-policy/sweep artifacts continue to affect weekly rankings, live
  support/dip recommendations, bullet sizing, and order adjustments.
- Future true neural/black-box model artifacts are treated as advisory unless
  `_meta` proves they were promoted against the graph-policy baseline with
  positive out-of-sample and risk-adjusted lift.
- Unpromoted black-box artifacts now fail validation and are ignored by the
  tournament instead of being consumed merely because a file exists.

**Fix applied**:
- Added `tools/model_complexity_gate.py` with the shared live-eligibility contract.
- Added `docs/model-complexity-gate.md` documenting the decision checklist and
  graph-baseline comparison protocol.
- Updated `tools/neural_artifact_validator.py` so known generated artifacts fail
  closed if they declare an unpromoted black-box model family.
- Updated `tools/watchlist_tournament.py` so unpromoted black-box sweep artifacts
  do not affect rankings.
- Added `tools/weekly_reoptimize.py` model-complexity gate before downstream live
  artifact consumption.

**Wired existing tools**:
- `tools/weekly_reoptimize.py`: enforces the gate before downstream consumers run.
- `tools/watchlist_tournament.py`: ignores advisory/unpromoted model sweep output.
- `tools/neural_artifact_validator.py`: blocks unpromoted black-box artifacts at
  the shared artifact loading boundary used by `daily_analyzer.py`,
  `neural_dip_evaluator.py`, `neural_support_evaluator.py`,
  `bullet_recommender.py`, and `neural_order_adjuster.py` through their existing
  validated artifact reads and shared support/bullet flows.

**Verification**:
- `python3 -m py_compile tools/model_complexity_gate.py tools/neural_artifact_validator.py tools/watchlist_tournament.py tools/weekly_reoptimize.py`
- `python3 -m pytest tests/test_model_complexity_gate.py tests/test_neural_artifact_validator.py tests/test_expected_edge.py tests/test_tool_imports.py -q`
- `python3 -m pytest -q`

**Original report (kept for context)**:
**Priority**: P2 - prevents premature black-box complexity.

**Symptom observed**: The project uses `neural_*` terminology, which can create a
temptation to add a true neural network even though the current strategy is
rule-heavy, safety-gated, and data-sparse per ticker.

**Root cause**: There is no explicit decision gate defining when a true neural
model is justified versus when calibrated graph-policy improvements are sufficient.

**Proposed fix**:
- Document criteria for considering a true neural model:
  calibrated graph scoring has plateaued, enough labeled examples exist,
  walk-forward evaluation shows incremental lift, explainability/reporting remains
  acceptable, and operational risk is controlled.
- Add a model-comparison protocol: graph baseline vs calibrated graph vs candidate
  neural model.
- Require the neural candidate to beat the calibrated graph baseline
  out-of-sample after costs and risk controls before live use.
- Keep neural model output advisory until it passes promotion criteria.
- Add a pipeline guard that prevents unpromoted black-box model outputs from
  affecting weekly tournament rankings, live recommendations, or order sizing.

**Existing-tool wiring required**:
- `tools/weekly_reoptimize.py` must enforce the comparison/promotion guard before
  any model output can affect live artifacts.
- `tools/watchlist_tournament.py`, `tools/daily_analyzer.py`,
  `tools/neural_dip_evaluator.py`, `tools/neural_support_evaluator.py`,
  `tools/bullet_recommender.py`, and `tools/neural_order_adjuster.py` must ignore
  advisory/unpromoted model output.
- The final resolution must state whether the task changed runtime behavior or only
  added a guard/reporting contract, and name the existing tools wired.

**Verification**:
- Documented decision checklist.
- Test or fixture for comparing model report artifacts.
- No live path consumes black-box neural output without passing promotion.
- Weekly pipeline/tournament fixture proving advisory model output is ignored until
  it passes the promotion gate.

**Expected impact**: Model complexity is introduced only when it demonstrates
measurable, risk-adjusted improvement over the explainable graph policy.
