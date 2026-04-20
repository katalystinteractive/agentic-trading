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
