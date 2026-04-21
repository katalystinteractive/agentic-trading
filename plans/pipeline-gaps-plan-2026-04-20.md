# Pipeline Gaps Closure Plan — 2026-04-20

Implementation plan to close the verified gaps from `plans/pipeline-gaps-analysis-2026-04-20.md` before next Saturday's `weekly_reoptimize` cron run (2026-04-25).

**Source analysis:** `plans/pipeline-gaps-analysis-2026-04-20.md` (verified across 2 iterations; 14 gaps, 2 already fixed, 12 open).

**Scope:** 7 changes covering Phase 1 (mechanical) + Phase 2 (structural). Phase 3 (6 items) deferred post-run with backlog entries.

---

## 0. Pre-implementation checklist

Before touching any code:

1. **Baseline smoke tests** — capture the current state so we can diff post-change:
   ```bash
   python3 -m pytest tests/ -x --tb=short > /tmp/pretest_baseline.txt 2>&1
   python3 tools/bullet_recommender.py APP > /tmp/baseline_APP.md 2>&1
   python3 tools/bullet_recommender.py QUBT > /tmp/baseline_QUBT.md 2>&1
   python3 tools/bullet_recommender.py HMY > /tmp/baseline_HMY.md 2>&1
   ```
   These three tickers span price ranges (APP ~$491, HMY ~$18, QUBT ~$10) and different tier distributions. Post-change reruns compared against these.

2. **Git branch**: work on `main` (project standard — no feature branches). Commit after each fix lands.

3. **Confirm no stale work in progress**:
   ```bash
   git status
   # Expect: portfolio.json + today's session state only
   ```

4. **Read-only audit first**:
   - `tools/wick_offset_analyzer.py:177` POOL_TIER_MULT constant location
   - `tools/bullet_recommender.py:234-241` earnings gate
   - `tools/bullet_recommender.py:263-275` compute_pool_sizing docstring
   - `tools/resistance_parameter_sweeper.py:108-120` and `tools/bounce_parameter_sweeper.py:100-115` combo loops
   - `tools/multi_period_scorer.py:112-180` compute_composite

---

## 1. Phase 1: Mechanical fixes

Ordered by dependency: tests first (lock behavior), then behavior changes (tier weights, cache hoist, earnings), then docs.

### Fix 1.1 — D10: Add test coverage for `POOL_MAX_FRACTION` cap + residual redistribution

**File:** `tests/test_wick_offset_analyzer.py`

**Add three tests** targeting the sizing math:

```python
def test_pool_cap_60pct_multi_level():
    """Multiple levels hit cap; residual must redistribute to uncapped."""
    from wick_offset_analyzer import compute_pool_sizing
    levels = [
        {"recommended_buy": 200.0, "effective_tier": "Full",
         "monthly_touch_freq": 2.0, "hold_rate": 60.0},
        {"recommended_buy": 150.0, "effective_tier": "Full",
         "monthly_touch_freq": 2.0, "hold_rate": 60.0},
        {"recommended_buy": 40.0, "effective_tier": "Std",
         "monthly_touch_freq": 1.0, "hold_rate": 35.0},
    ]
    result = compute_pool_sizing(levels, 300, "active")
    total_cost = sum(r["cost"] for r in result)
    assert total_cost <= 300.1, f"total {total_cost} exceeds pool"
    # Two highest-priced levels likely cap; cheap level absorbs residual
    cheap_level = next(r for r in result if r["recommended_buy"] == 40.0)
    assert cheap_level["shares"] >= 1, "cheap level should absorb residual"


def test_residual_distribution_order():
    """Residual goes to highest-freq level first."""
    from wick_offset_analyzer import compute_pool_sizing
    levels = [
        {"recommended_buy": 10.0, "effective_tier": "Std",
         "monthly_touch_freq": 0.5, "hold_rate": 30.0},
        {"recommended_buy": 10.0, "effective_tier": "Std",
         "monthly_touch_freq": 2.5, "hold_rate": 35.0},
    ]
    result = compute_pool_sizing(levels, 100, "active")
    high_freq = next(r for r in result if r["monthly_touch_freq"] == 2.5)
    low_freq = next(r for r in result if r["monthly_touch_freq"] == 0.5)
    # High-freq gets >= low-freq allocation (priority in residual redistribution)
    assert high_freq["shares"] >= low_freq["shares"], \
        f"high_freq shares={high_freq['shares']} < low_freq shares={low_freq['shares']}"


def test_cap_no_leftover_below_min_step():
    """Sub-$150 ticker: residual below 1 share doesn't crash and stays under budget."""
    from wick_offset_analyzer import compute_pool_sizing
    # 3 tiny-priced levels that would over-allocate fractional but must round down
    levels = [
        {"recommended_buy": 7.13, "effective_tier": "Std",
         "monthly_touch_freq": 1.0, "hold_rate": 35.0},
        {"recommended_buy": 5.07, "effective_tier": "Std",
         "monthly_touch_freq": 1.0, "hold_rate": 35.0},
    ]
    result = compute_pool_sizing(levels, 50, "active")
    total_cost = sum(r["cost"] for r in result)
    # All shares must be integers (price < $150)
    for r in result:
        assert r["shares"] == int(r["shares"]), \
            f"price={r['recommended_buy']} got fractional shares={r['shares']}"
    # Total can exceed 50 due to min-1-share floor, but not by huge margin
    assert total_cost <= 50 + max(r["recommended_buy"] for r in result), \
        f"total={total_cost} exceeds tolerated overage"
```

**Verification:** `pytest tests/test_wick_offset_analyzer.py -k "test_pool_cap_60pct_multi_level or test_residual_distribution_order or test_cap_no_leftover_below_min_step" -v`

Tests must pass on the current code (they're documenting existing behavior). After Fix 1.2 lands, one or two may need adjustment — that's intentional.

**Commit message:** `test: add POOL_MAX_FRACTION cap + residual redistribution coverage`

---

### Fix 1.2 — D2: Differentiate Full from Std in `POOL_TIER_MULT`

**File:** `tools/wick_offset_analyzer.py:177`

**Change:**
```diff
-POOL_TIER_MULT = {"Full": 1.0, "Std": 1.0, "Half": 0.5}
+POOL_TIER_MULT = {"Full": 1.5, "Std": 1.0, "Half": 0.5}
```

**Rationale:** user confirmed Full should weight higher. 1.5 multiplier gives Full tier 50% more weight than Std, 3× more than Half — matches the intuition that 50%+ hold rate is a qualitatively stronger signal than 30–49%.

**Verification:**
1. Re-run baseline bullet_recommender for APP/QUBT/HMY.
2. Compare outputs — levels tagged Full should show higher share counts relative to Std-tier peers in the same pool.
3. Spot-check one ticker with mixed tiers (e.g., HMY has Std + Full mix) to confirm weight shift is in the expected direction.
4. Pytest: some existing tests may need updates if they assert exact share counts against Full/Std mixes.

**Rollback:** revert single line. No data migration needed.

**Commit message:** `feat: Full tier weighted 1.5× in pool sizing (vs Std 1.0×)`

---

### Fix 1.3 — C3: Hoist `resistance_cache` and `bounce_cache` above combo loop

**Files:** 
- `tools/resistance_parameter_sweeper.py:108-120`
- `tools/bounce_parameter_sweeper.py:100-115`

**Change pattern (resistance_parameter_sweeper.py):**
```diff
     # Ticker-scoped caches: wick analysis is price-dependent (not strategy-dependent),
     # so share across ALL combos × periods to avoid ~50× redundant recompute per ticker.
     wick_cache = {}
+    # Same invariant for resistance: _rc_key = (tk, day_str) (see backtest_engine.py:704).
+    # Cache is independent of strategy params; safe to share across all combos.
+    resistance_cache = {}

     for idx, (strategy, reject_rate, min_approaches, fallback_pct) in enumerate(combos):
         ...
         # Multi-period scoring
         results_by_period = {}
         last_result = None
-        resistance_cache = {}  # shared across periods within same combo
         for period_months in SWEEP_PERIODS:
```

**Same pattern for bounce** — hoist `bounce_cache = {}` above the combo loop (currently inside at line ~102).

**Verification:**
1. Single-ticker smoke test: `python3 tools/resistance_parameter_sweeper.py --ticker CIFR --workers 1`
2. Compare `data/resistance_sweep_results.json` CIFR entry pre/post — must be byte-identical (the cache is deterministic; hoisting doesn't change values).
3. Repeat for bounce with same ticker.
4. Measure runtime improvement on 5-ticker sample: should see ~30-50% faster per ticker.

**Rollback:** revert the hoist (one `resistance_cache = {}` line moves back inside the combo loop). No data migration.

**Expected runtime impact:** ~1h 15m–1h 30m saved from STEP 7 + STEP 8 in weekly_reoptimize (per backlog spec).

**Commit message:** `perf: hoist resistance_cache + bounce_cache to ticker scope (~1h 15m weekly saving)`

---

### Fix 1.4 — D4: Promote earnings-gate to hard-block in bullet_recommender

**File:** `tools/bullet_recommender.py:234-241`

**Current behavior:** earnings warning shown in bullet recommendation but does not block the Level Map output. User must manually decide to cancel orders placed during blackout.

**Proposed change:** add a configurable hard-block:

```diff
     try:
         from earnings_gate import check_earnings_gate, format_gate_warning
         gate = check_earnings_gate(ticker)
-        if gate and gate.get("block"):
-            # Warning only — show the banner, let user decide
-            ...
+        if gate and gate.get("block"):
+            # Hard-block: suppress the Level Map entirely; show clear notice.
+            print(f"## Bullet Recommendation: {ticker}")
+            print(f"*Generated: {now} | Data as of: {last_date}*\n")
+            print(f"> ⚠ **EARNINGS BLACKOUT — RECOMMENDATION SUPPRESSED**")
+            print(f"> {format_gate_warning(gate)}")
+            print(f"> Re-run `bullet_recommender.py {ticker}` after earnings clear.")
+            return
     except ImportError:
         pass  # earnings gate is advisory; don't crash on missing module
```

**Key details:**
- Only triggered when `gate["block"] == True` (respects the gate's own threshold logic, likely ≤7 days).
- Still shows the ticker header so the user knows the tool ran, just doesn't list levels.
- Does NOT modify `portfolio.json` — purely display-layer block.
- Preserves backward-compat: if `earnings_gate` module unavailable, behavior unchanged.

**Verification:**
1. Find a ticker with imminent earnings (e.g., TPG May 1 — 11 days away may be inside blackout).
2. Run `python3 tools/bullet_recommender.py TPG` — expect blackout banner, no Level Map.
3. Run for a ticker clear of earnings (e.g., HMY) — expect normal Level Map.
4. Pytest: no existing tests target this path; add one mocking the gate response.

**Rollback:** revert the block branch. No data side-effects.

**Commit message:** `feat: earnings-gate now hard-blocks bullet output during blackout window`

---

### Fix 1.5 — D9: Correct `compute_pool_sizing` docstring

**File:** `tools/wick_offset_analyzer.py:263-275`

**Change:**
```diff
 def compute_pool_sizing(levels, pool_budget, pool_name="active"):
-    """Distribute pool_budget across levels for equal averaging impact.
+    """Distribute pool_budget across levels by price-weighted allocation.
+
+    Each level's share of the pool is proportional to:
+        weight = recommended_buy × POOL_TIER_MULT[tier] × max(1.0, monthly_touch_freq)
+
+    Result: higher-priced and higher-frequency levels absorb more dollars.
+    This is NOT equal-averaging-impact — a fill at A1 affects avg cost more
+    than a fill at B1 (since A1 gets more shares).

     Args:
```

**Verification:** visual only (it's a docstring). Rebuild any Sphinx/docs output if they exist (they don't in this repo).

**Rollback:** revert the docstring.

**Commit message:** `docs: correct compute_pool_sizing docstring to describe actual price-weighted behavior`

---

## 2. Phase 2: Structural fixes

These are more involved and deserve individual review. Aim: both land before next Saturday run.

### Fix 2.1 — C1: Recency weights in `multi_period_scorer.compute_composite`

**File:** `tools/multi_period_scorer.py:112-180`

**Current behavior:**
```python
PERIODS = [12, 6, 3, 1]
SIGNIFICANCE_THRESHOLD = 5
weight_i = min(cycles_i, SIGNIFICANCE_THRESHOLD) / SIGNIFICANCE_THRESHOLD
composite = sum(weight_i * rate_i) / sum(weight_i)
```
No recency adjustment — 12mo and 1mo periods treated equally when both reach cycle-count threshold.

**Proposed change:** add a linear recency multiplier:
```python
RECENCY_WEIGHTS = {12: 1, 6: 2, 3: 3, 1: 4}  # shorter period = higher weight

# In compute_composite:
for months, pd in period_data.items():
    sig = min(pd["cycles"], SIGNIFICANCE_THRESHOLD) / SIGNIFICANCE_THRESHOLD
    recency = RECENCY_WEIGHTS.get(months, 1)
    weights[months] = sig * recency
```

**Rationale:** Shorter-period data reflects current regime. Per user observation, tickers with stale patterns from 12 months ago are ranking top-30 while currently not performing. Linear 1-2-3-4 weighting triples the influence of the 1-month period.

**Design decision needed:**
- (a) Linear `1:2:3:4` as above (simple, explainable)
- (b) Exponential `exp(-period_mo × ln(2) / 3)` (half-life = 3 months)
- (c) Match wick-analyzer's 90-day half-life: `exp(-period_midpoint_days × ln(2) / 90)`

**Recommendation:** start with (a) — easiest to reason about, easiest to tune.

**Verification:**
1. Pre/post tournament ranking diff on current `data/tournament_results.json` data.
2. Focus on ranks #5–#30 — expect some tickers to drop (stale patterns) and some to rise (newly active).
3. Sanity check: tickers that had all cycles in the 1mo window should rise. Tickers with cycles only in 12mo should drop.
4. Add test: `test_recency_weighted_composite` in `tests/` — hand-crafted 4-period input with known expected composite.

**Rollback:** revert the weight formula. Tournament rankings are recomputed on next cron run; no data migration needed.

**Risk:** changing tournament rankings mid-stream may surface unexpected tickers or demote currently-placed ones. Mitigation: run tournament once post-fix, review rankings with user before committing to the new watchlist.

**Commit message:** `feat: recency-weighted composite score (1mo weighted 4× vs 12mo 1×)`

---

### Fix 2.2 — C2: Support-level-density gate before Tier 2 pool construction

**Files:** 
- `tools/universe_prescreener.py` (or `tools/weekly_reoptimize.py` `_build_profitable_tier2_pool` — need to decide)
- Potentially a new helper in `tools/sector_registry.py` or a standalone density-check module

**Current funnel:**
```
1,585 universe passers
  ↓ universe_prescreener.py (stage-1 support sweep)
Top 200 by signal → Tier 2 pool
  ↓ tournament
```

**Proposed gate:** after stage-1 pre-screen, before selecting top-200, require each candidate to have ≥3 raw support levels per `wick_offset_analyzer.analyze_stock_data()`.

**Implementation approach — Option A (committed):**

Verifier confirmed that `universe_prescreener.py`'s stage-1 output schema is exactly `{"ticker", "composite", "best_params", "sells_12mo", "win_rate_12mo"}` with **no level-count or level-structure field**. The earlier "Option B" idea (reuse stage-1 output) is not viable without changing the prescreener's output schema first — and changing the schema to add level count requires running wick analysis anyway, so it's equivalent to Option A. Committing to Option A:

**Algorithm:**
1. After stage-1 signal scoring completes in `universe_prescreener.py`, iterate over the 1,585 passers.
2. For each ticker, call `wick_offset_analyzer.analyze_stock_data(ticker, ...)` to produce level count.
3. Count raw support levels (any zone — Active + Buffer + Reserve).
4. **Gate:** exclude tickers with `raw_levels < 3` from the Tier 2 candidate pool.
5. **Cache:** write wick analysis output to `tickers/<TICKER>/wick_analysis.md` so downstream steps (`batch_onboard`, `bullet_recommender`) reuse it instead of recomputing.

**Runtime cost:**
- Solo `wick_offset_analyzer.py TICKER` runtime: ~0.5-2s per ticker (mostly yfinance fetch + HVN computation)
- 1,585 tickers sequential: ~20-50 min. Unacceptable.
- **Parallelized at 8 workers:** ~3-7 min. Acceptable.
- Use `concurrent.futures.ThreadPoolExecutor(max_workers=8)` (I/O-bound) or `multiprocessing.Pool(8)` (CPU-bound for HVN).

**Integration point:** add to `universe_prescreener.py` as Phase 2.5 (after stage-1 signal ranking, before selecting top-200). New code block ~30 LOC.

**Alternative integration (simpler but less clean):** skip the gate in prescreener, apply it in `weekly_reoptimize.py:_build_profitable_tier2_pool` instead. Pro: doesn't touch prescreener's existing flow; just filters the 200-ticker input before it's used downstream. Con: tournament still ranks the thin tickers (wasted compute). Recommend in-prescreener for cleanliness unless time constraint forces the alternative.

**Parallel-workers caveat:** wick_offset_analyzer uses yfinance which has global rate limiting. Too many parallel workers → Yahoo 429 errors (we saw this earlier in the session running 4 bullet_recommenders in parallel). Keep workers at 8, add simple exponential-backoff retry on rate-limit errors.

**Output contract:** append `level_count` field to the prescreener's per-ticker output dict so tournament / downstream can inspect it. Also emit a summary line: "X of N tickers gated out for <3 levels."

**Verification:**
1. Before gate: run prescreener, note top-200 tickers.
2. After gate: expect ~1,200–1,300 passers remaining (assuming 20-30% of tickers have thin structure). Top-200 selection from the filtered pool.
3. Cross-check: previously-dropped tickers (BDRX, OCUL, FRMM, PLCE, SRAD, VWAV) should NOT appear in the new top-200.
4. Measure: count of manual drops during next onboarding wave — target 0.

**Rollback:** remove the gate. Data files unchanged.

**Commit message:** `feat: support-level-density gate (>=3 levels) before Tier 2 pool selection`

---

## 3. Phase 3: Deferred (backlog after next run)

Not blocking for next Saturday. Tracked in `plans/backlog.md`:

| # | Gap | Rationale for defer |
|:---|:---|:---|
| D1 | Buffer quality-sizing redesign | Needs careful backtest; thin-ladder edge case |
| D3 | Autonomous broker reconciliation cron | Tool exists; scheduling is simple but orthogonal |
| D5 | Regime-aware offsets (enable + backtest) | Requires full run with regime data; risky pre-run |
| D6 | Daily wick refresh cron | Nice-to-have; weekly is adequate for most cases |
| D7 | Dormant-level placement strategy | Design decision needed; keep 1-share fallback for now |
| D8 | Add `total_approaches` to weight formula | Small optimization; after Phase 1 tier change settles |

Each has a backlog entry; plan updates required only if priority shifts.

---

## 4. Verification strategy — end-to-end

After all Phase 1 + Phase 2 changes land, run this end-to-end validation:

1. **Full test suite passes:**
   ```bash
   pytest tests/ -x --tb=short
   ```

2. **Single-ticker bullet_recommender diff** on 3 known tickers (APP, QUBT, HMY):
   - Compare Phase 1 output vs baseline from section 0.
   - Expected deltas: Full-tier levels get more shares (D2); APP earnings blackout may suppress if in window (D4); otherwise similar.

3. **Full weekly_reoptimize dry-run** on a subset:
   ```bash
   python3 tools/weekly_reoptimize.py --skip-download --dry-run
   ```
   Expected changes:
   - STEP 7/8 complete faster (C3 hoist)
   - Tournament rankings shift to favor recent performers (C1)
   - Tier 2 pool composition excludes thin tickers (C2)

4. **Spot-check on specific cases:**
   - TPG, JBLU, LAZ, NVCR, SVV (earnings-parked) — rankings should drop if recency weighting demotes stale patterns.
   - APP, CRWV (A1 far from current price) — remain ranked if their patterns are still active.

5. **Commit each fix separately** for clean revert history.

---

## 5. Rollback strategy per fix

| Fix | Revert command | Data implications |
|:---|:---|:---|
| 1.1 tests | `git revert <sha>` | None |
| 1.2 tier mult | `git revert <sha>` | Next weekly run recomputes with old weights |
| 1.3 cache hoist | `git revert <sha>` | None — cache is runtime-only |
| 1.4 earnings block | `git revert <sha>` | None — display-layer only |
| 1.5 docstring | `git revert <sha>` | None |
| 2.1 recency weights | `git revert <sha>` | Tournament recomputes old composites next run |
| 2.2 density gate | `git revert <sha>` + `rm -f tickers/*/wick_analysis.md` for stale cache cleanup if rolling back within the same week | Tier 2 pool gains back thin tickers next run. **Cache caveat:** this fix writes `tickers/<TICKER>/wick_analysis.md` for all 1,585 passers. Reverting code doesn't delete those cache files — downstream tools (bullet_recommender, batch_onboard) will keep reading them. Usually harmless (cache is valid data), but if a bug forces rollback, clear the cache to force fresh analyses on next run. |

**No destructive data migrations.** All behavior changes take effect on next cron cycle; rolling back restores old behavior the same way.

---

## 6. Timeline

Phase 1 estimated **~45–90 min** total (trivial changes with test runs).
Phase 2 estimated **~2–3 hours** (structural + verification).
**Plus end-to-end verification run** (section 4): **~45–90 min** for the dry-run weekly_reoptimize + tournament ranking diff + spot-checks.

**Total estimated work: ~4–5.5 hours.**

Target completion: **before 2026-04-25 Saturday 10:00 local** (cron fires `0 10 * * 6`). ~6 days of lead time from 2026-04-19 — feasible with buffer for iteration if any fix misbehaves under real data.

Implementation order:
1. Fix 1.1 (tests) — lock existing behavior
2. Fix 1.5 (docstring) — trivial, do while tests run
3. Fix 1.3 (cache hoist) — independent perf win
4. Fix 1.2 (tier weights) — may require test updates
5. Fix 1.4 (earnings block) — independent
6. Fix 2.1 (recency weights) — may surface ranking shifts
7. Fix 2.2 (density gate) — final Tier 2 filter

---

## 7. Open decisions

- **Fix 2.1 recency weight shape:** linear vs exponential. Recommend linear `1:2:3:4`.
- **Fix 2.2 density gate location:** in prescreener vs in orchestrator. Needs a 15-min code read to confirm stage-1 output includes level count (Option B viability).
- **Fix 1.2 Full tier multiplier value:** 1.5 proposed. Could be 2.0 if we want more aggressive tier differentiation. User call.

None of these block implementation; defaults above are sane starting points.
