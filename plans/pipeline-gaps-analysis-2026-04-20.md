# Pipeline Gaps Analysis — 2026-04-20

Complete inventory of gaps in the tournament + bullet-strategy pipeline, plus a deep evaluation of how deployment amounts are determined. Target: close everything blocking before next Saturday's `weekly_reoptimize` cron run.

---

## A. Executive summary

**Six gaps identified**, grouped by severity:

| # | Gap | Impact | Status |
|---:|:---|:---|:---|
| A1 | Phantom auto-fills in `order_proximity_monitor` | Corrupted portfolio state 3× in 24h | ✅ FIXED today |
| A2 | Fractional shares under $150 rejected by broker | Orders invalid for sub-$150 tickers | ✅ FIXED today |
| A3 | Recency blindness in composite tournament scoring | Stale ladders get top-30 ranks | 📋 BACKLOG (filed today) |
| A4 | No support-level-density gate before Tier 2 pool | ~40% of top-25 onboards need drops | 📋 BACKLOG (filed today) |
| A5 | `resistance_cache` / `bounce_cache` not hoisted | ~1h 15m–1h 30m weekly runtime waste | 📋 BACKLOG (filed earlier) |
| A6 | Buffer-zone levels flattened to 1-share fallback regardless of quality | High-quality Buffer levels undersized (e.g., FIGR B1 = 1 sh despite 80% hold) | ⚠ NEW — see section D |
| A7 | Full vs Std tier treated identically in sizing | No distinction between 50%+ and 30–49% hold rates | ⚠ NEW — see section D |
| A8 | No broker-state reconciliation | Portfolio.json can silently drift from broker | ⚠ NEW — potential for silent errors |
| A9 | Earnings blackout is advisory-only | Orders can be placed/fill during blackout window | ⚠ NEW — today we did this manually |
| A10 | Regime-aware offset computation disabled by default | VIX / risk-on/off don't shift bullet levels | ⚠ NEW — `regime_aware_offset=False` |
| A11 | Dormant levels placed with 1-share fallback | Orphaned broker orders on levels 90d+ untested | ⚠ NEW (design question) — see D7 |
| A12 | Weight formula ignores `total_approaches` (sample size) | Low-approach levels same weight as high-approach | ⚠ NEW — see D8 |
| A13 | `compute_pool_sizing` docstring misleading | Minor — causes confusion when reading the code | ⚠ NEW — see D9 |
| A14 | No test coverage for `POOL_MAX_FRACTION` cap | Regressions in sizing math could slip in unnoticed | ⚠ NEW — see D10 |

**2 fixed this session, 3 in backlog, 9 newly identified.**

---

## B. Already-closed gaps (this session, for completeness)

### B1. Phantom auto-fills (commit `8816447`)
- `order_proximity_monitor.py` ran every 5 min via cron, auto-filling at the order's **limit price** the moment current price touched/crossed the limit.
- Two failure modes: (1) order not actually live at broker → phantom position; (2) broker fills at better price than limit → user's real-fill command double-counts.
- **Fix:** `--enable-auto-fill` flag, default OFF. Cron uses notification-only mode.

### B2. Fractional shares under $150 (commit `2311524`)
- `wick_offset_analyzer.compute_pool_sizing` rounded to 0.1 uniformly regardless of price.
- Broker rejects fractional for stocks <$150.
- **Fix:** `FRACTIONAL_SHARE_MIN_PRICE = 150`, helper `_round_to_broker_step(shares, price)`, integer shares for sub-$150.

---

## C. Open backlog items (summarized; full detail in `plans/backlog.md`)

### C1. Recency blindness in composite scoring
- `multi_period_scorer.py` aggregates 12/6/3/1mo P/L weighted only by cycle count, not by recency.
- A ticker that worked great 12mo ago but is now regime-stalled ranks the same as one actively working now.
- Evidence: APP A1 at $388 vs current $491 (-21%); CRWV A1 at $78 vs current $117 (-34%); INV A1 at $4.38 vs current $6.19 (-29%). All three would be lower-ranked under recency-weighted composite.

### C2. Support-level-density gate
- No stage in the universe → prescreen → tournament funnel checks ladder depth.
- ~40% of tournament top-25 candidates require manual drop during onboarding.
- Fix: gate Tier 2 pool construction on `raw_support_levels >= 3`.

### C3. Cache hoist (resistance + bounce)
- Per-combo cache resets waste ~1h 15m–1h 30m in weekly run.
- Fix: hoist `resistance_cache` and `bounce_cache` above combo loop, matching the wick_cache Fix B pattern.

---

## D. Newly identified gaps (this analysis)

### D1. Buffer-zone levels get 1-share fallback regardless of quality

**Location:** `tools/bullet_recommender.py` — `_concentrated_pool_sizing` helper + comment at line 423: `"Buffer levels (dormant, non-promoted) are intentionally excluded from both pools. They get 1-share fallback via sizing_lookup.get() default in the Level Map."`

**Symptom:** FIGR case tonight — A1 (Std tier, 38% hold) got 9 shares / $295. B1 (Full tier, 80% hold — MUCH stronger signal) got 1 share / $30. Pool design means the zone classification dominates over hold-rate quality.

**Root cause:** the bullet pool is scoped to `zone == "Active"` (+ promoted Buffers). Non-promoted Buffer levels — regardless of hold rate or tier — fall through to the `sizing_lookup.get((lvl), (1, price))` default.

**Consequence:** thin ladders (only 1–2 Active levels) concentrate pool entirely on the Active levels, even when the next-deepest Buffer level is the actual quality signal. Averaging-down math doesn't work because Buffer fill contributes ~1% to avg cost.

**Proposed fix:**
- If the Active pool has <3 levels AND a promoted-adjacent Buffer level exists with Full tier, give it a partial active-pool weight (e.g., 20–30% of pool).
- OR: compute a "quality score" per level (tier × hold × approaches) and allocate the pool by quality, not just zone membership.

### D2. Full vs Std tier identical sizing weight

**Location:** `tools/wick_offset_analyzer.py:177`:
```python
POOL_TIER_MULT = {"Full": 1.0, "Std": 1.0, "Half": 0.5}
```

**Symptom:** Full tier (≥50% hold) gets the same weight as Std tier (30–49% hold). A ticker with 3 Active levels — one Full (80% hold, 15 approaches) and two Std (35% hold, 6 approaches each) — distributes capital equally across all three regardless of signal strength.

**Root cause:** the multiplier table was originally designed to cap Half at 0.5 but didn't further differentiate Full (strong) from Std (moderate).

**Proposed fix:** tier multipliers scaled by hold tier:
```python
POOL_TIER_MULT = {"Full": 1.5, "Std": 1.0, "Half": 0.5}
```
Or continuous scaling: `mult = hold_rate / 50` with floor 0.3, cap 2.0.

**Backward-compat:** re-run all existing sweeps afterward (most results are recomputed weekly anyway).

### D3. No autonomous broker reconciliation

**Clarified after verification:** `tools/broker_reconciliation.py` DOES exist AND is imported/used by `daily_analyzer.py`, `bullet_recommender.py`, `neural_order_adjuster.py`, and `graph_builder.py`. The functions (e.g., `compute_recommended_sell`, `_load_profiles`) are called on-demand during analysis workflows.

**Actual gap:** the module is **not scheduled autonomously** to diff portfolio.json against broker state. Today's silent-drift incidents (MU/CRWD wipes, URI phantom fills, QUBT/VNDA duplicates) all happened because nothing was watching for portfolio.json ≠ broker.

**Three failure modes observed:**
- `watchlist_tournament.py` drops a ticker → wipes pending_orders in portfolio.json → broker still has live orders (MU/CRWD cleanup earlier today)
- User cancels at broker but doesn't tell us → portfolio.json shows `placed=True` phantom
- `order_proximity_monitor` auto-fills at limit price → doesn't match real broker fills (now FIXED in commit `8816447`, but the monitor still won't catch manual broker-side cancels)

**Proposed fix:** add a scheduled reconciliation pass that (a) fetches live broker open orders once per day (or every N hours during market hours), (b) diffs against `portfolio.json` `pending_orders` with `placed=True`, (c) emails a report of discrepancies. Zero automatic mutations — the report prompts the user to decide how to reconcile.

**Does NOT require writing a new tool** — just a scheduled invocation of `broker_reconciliation.py`'s diff mode. Likely already has a `--report` or similar flag; if not, thin wrapper needed.

### D4. Earnings blackout is advisory-only

**Location:** `tools/bullet_recommender.py:234` — `earnings_gate` imported and displayed as a warning, but the tool doesn't block recommendation output.

**Symptom:** today we had TPG and JBLU blackout warnings; we placed orders anyway, then manually canceled after my advice. This is correct behavior if we trust humans-in-loop, but risky if an automation places without review.

**Proposed fix:** make earnings-gate hard-block configurable:
- Add `EARNINGS_BLACKOUT_DAYS = 7` (or similar) as a pipeline constant
- `bullet_recommender.py` suppresses the Level Map entirely if earnings within blackout window, prints explicit notice
- `watchlist_tournament.py` could also skip placement recommendations for tickers in blackout (though ranking still fine)

### D5. Regime-aware offset disabled by default

**Location:** `tools/wick_offset_analyzer.py:213`: `self.regime_aware_offset = kwargs.get("regime_aware_offset", False)`

**Symptom:** Risk-On vs Risk-Off regime conditions shift how deep wicks go below support. Per the tool, it CAN compute `risk_on_hold_rate` / `risk_off_hold_rate` / `risk_on_offset` / `risk_off_offset` per level, but these aren't actively used in the default bullet sizing or buy-price calculation.

**Proposed fix:** enable `regime_aware_offset=True` in the default config. Adjust `recommended_buy` based on current regime — deeper offset during Risk-Off.

### D7. Dormant levels (90d+ untested) still get 1-share placement instead of being skipped

**Location:** `tools/bullet_recommender.py:429-436` — `_concentrated_pool_sizing` explicitly separates dormant from fresh, gives dormant a 1-share fallback:
```python
dormant_sized = [{"shares": 1, "cost": lvl["recommended_buy"],
                  "dollar_alloc": lvl["recommended_buy"]} for lvl in dormant]
```

**Symptom:** a level not tested in 90+ days still gets an order placed (1 share). Safety rationale: "if level suddenly activates, we have exposure." Cost rationale concern: may reserve broker slots and capital on levels that simply no longer matter.

**Open design question:** should dormant levels be:
- (a) Skipped entirely (cleaner Level Map, less broker clutter)
- (b) 1-share fallback (current — catches re-emergence, costs minimal capital)
- (c) 1-share fallback **only** for high-prior-hold-rate dormant levels (e.g., the level held 80%+ during its last 3 tests before going dormant)

Not a bug, a design choice worth revisiting with explicit intent. Recommend: leave as (b) for now since the capital commitment is trivial (~$10–30 per dormant level); revisit if we see dormant 1-share orders actually filling and creating orphaned positions.

### D8. Weight formula ignores `total_approaches` count (sample size)

**Location:** `tools/wick_offset_analyzer.py:290` — weight formula:
```python
weight = price × POOL_TIER_MULT[tier] × max(1.0, monthly_touch_freq)
```

**Symptom:** a level with **3 approaches** over 13 months (thin sample) gets the same weight as one with **15 approaches** (deep sample), as long as monthly frequency matches. The confidence floor (`<3 approaches → Half cap`) exists but only triggers the binary Half downgrade.

**Impact example:** FIGR A1 has 3/8 approaches (8 tests). If another ticker had 3/20 approaches with the same monthly frequency, both would get identical pool weight — but the 20-approach ticker's 15% hold rate is a stronger signal than the 8-approach one's 38% hold rate.

**Proposed fix:** multiply weight by `sqrt(approaches / 3)` or linear `min(approaches, 15) / 15`:
```python
approaches_boost = min(r.get("total_approaches", 3), 15) / 15
weight = price × mult × freq_boost × max(0.3, approaches_boost)
```

**Backward-compat:** re-run affected sweeps. Defer until after P0/P1 gates close.

### D9. `compute_pool_sizing` docstring misleading

**Location:** `tools/wick_offset_analyzer.py:264`:
> "Distribute pool_budget across levels for **equal averaging impact**."

**Reality:** the code implements `weight = price × tier × freq` dollar distribution. Higher-priced levels absorb more dollars, NOT equal avg-cost impact per fill. Section E5 of this analysis already documents this behavior.

**Proposed fix:** correct the docstring to match the actual algorithm. Trivial doc-only change.

### D10. Missing test coverage for `POOL_MAX_FRACTION` cap + residual redistribution

**Location:** `tests/test_wick_offset_analyzer.py`

**Symptom:** existing tests (`test_cap_limits_expensive_level`, `test_cap_redistributes_to_uncapped`, `test_all_capped_distributes_via_residual`) verify simple cases but don't cover:
1. Multi-level cap-triggering — 3+ levels where 2 hit the 60% cap and redistribution must flow through multiple uncapped targets correctly.
2. Broker-step-compliant residual — when residual dollars < 1 share (<$price) for sub-$150 tickers, verify no crash and final total ≤ pool budget.
3. Residual redistribution order — frequency-sorted priority should determine which uncapped level absorbs leftover first.

**Proposed fix:** add 3 tests:
- `test_pool_cap_60pct_multi_level` (verifies 2+ levels capped + residual redistribution)
- `test_residual_distribution_order` (verifies frequency-sort priority)
- `test_cap_no_leftover_below_min_step` (verifies graceful handling when residual < 1 share unit)

### D6. No active-zone radius update on intraday price moves

**Location:** `tools/wick_offset_analyzer.py:899-903` — active_radius computed once from recent swing, capped at 20%.

**Symptom:** INV rallied 35% in a day. The wick_analysis cached from yesterday still classifies levels based on yesterday's $4.60 reference. If I re-ran today, levels would reclassify against $6.19 — some Active become Buffer, some Buffer become Reserve.

**Consequence:** between wick refreshes (weekly), stale active-zone classifications can produce bullet recommendations against outdated zones.

**Proposed fix:**
- Daily `wick_offset_analyzer` refresh for tickers in watchlist (not weekly)
- OR: runtime zone re-classification in `bullet_recommender.py` using current price, not cached zones

---

## E. Sizing logic deep-dive — how amounts are determined

### E1. The pipeline

```
user sees bullet map
   ↓
bullet_recommender.py
   ├─ reads wick_analysis.md (cached)
   ├─ classifies levels into Active / Buffer / Reserve / Dormant
   ├─ filters: valid_levels = not above current price
   ├─ splits: active_pool_levels vs reserve_pool_levels vs buffer-fallback
   └─ calls wick_offset_analyzer.compute_pool_sizing per pool
   ↓
compute_pool_sizing (line 263)
   ├─ per level: weight = price × POOL_TIER_MULT[tier] × max(1, monthly_freq)
   ├─ cap each allocation at POOL_MAX_FRACTION (60%) of pool
   ├─ redistribute leftover capacity to uncapped levels
   ├─ convert dollars → shares (0.1 if price≥$150, else integer ≥1)
   └─ residual redistribution to highest-frequency levels
   ↓
output: shares + cost per level
```

### E2. The weight formula

```python
weight = price × POOL_TIER_MULT[tier] × max(1.0, monthly_touch_freq)
```

| Variable | Values | Notes |
|:---|:---|:---|
| `price` | level's wick-adjusted buy price | **Linear in price** — higher-priced levels dominate the pool because `$price × allocation = $cost` scales |
| `POOL_TIER_MULT[tier]` | Full=1.0, Std=1.0, Half=0.5 | **Flat across Full & Std** (gap D2) |
| `monthly_touch_freq` | 0.3 to ~4.0 typical, floored at 1.0 | More-frequent levels get proportionally more allocation |
| `POOL_MAX_FRACTION` | 0.60 | Cap: no single bullet can absorb more than 60% of pool |

### E3. Worked example — why FIGR A1 got $295 and B1 got $30

**FIGR pool inputs (Active pool = $300, Buffer levels get 1-share fallback):**

| Level | Zone | Price | Tier | mult | Freq | freq_boost | Weight | In Active pool? |
|:---|:---|---:|:---:|---:|---:|---:|---:|:---:|
| A1 | Active | $32.80 | Std | 1.0 | 1.7 | 1.7 | 55.76 | ✓ |
| B1 | Buffer | $29.95 | Full | 1.0 | 1.3 | 1.3 | N/A | ✗ — excluded, gets 1-share fallback |

Since A1 is the ONLY level in the Active pool, it absorbs all $300 (capped at $180 per POOL_MAX_FRACTION? Actually the cap applies per-bullet within a multi-bullet pool; with 1 level, the leftover redistribution fills back up to the pool budget). Result: 9 shares × $32.80 ≈ $295.

B1 defaults to 1-share × $29.95.

### E4. Worked example — why OSCR's 7 placed orders cleanly fit $300

**OSCR Active pool levels:**
- A1 ($15.44), A2 ($14.47), A3 ($14.17) — 3 Active
- B1–B4 promoted-to-Active ($13.84, $13.05, $12.86, $11.85) — 4 promoted (graduate to Active pool)

All 7 levels enter the active pool. Weights scale by `price × tier × freq`. Equal tier (Std across most) means the split is primarily driven by price and frequency, capped at 60% per bullet. Result: well-distributed 2/1/6/5/3/2/3 shares totaling $299.99.

### E5. Key behaviors to flag for the user

| Behavior | Intent | Actual effect |
|:---|:---|:---|
| "Equal averaging impact" (docstring) | Pool distributed so each fill has comparable avg-cost impact | **Not what happens.** Dollars distributed by weight (price × tier × freq), not by inverse-price. Higher-priced levels get more dollars; lower-priced levels get fewer. |
| Promoted Buffer → Active pool | High-quality buffer levels graduate into the main pool | **Works** — any level with `zone_promoted=True` (pullback-tested) enters active_pool_levels. |
| Tier caps sizing | Weak levels get less capital | **Partially true** — only Half (15–29% hold) is penalized. Full (50%+) and Std (30–49%) are equivalent. |
| Single-bullet cap at 60% | Prevents concentration | **Works** — but for thin ladders (1 active level), the leftover redistribution pushes back up toward 100%. |
| Frequency weighting | More-frequently-tested levels get more capital | **Works** — explicitly in the formula. |

### E6. What the user is NOT seeing

1. Sizing does not reward recency — a level that last held 2 weeks ago gets the same weight as one that last held 6 months ago, as long as both pass the decayed hold rate threshold.
2. Sizing does not reward approach count — a level with 3 approaches and 33% hold is treated identically to one with 15 approaches and 33% hold (same tier).
3. Sizing does not adjust for position management — if you already have existing shares at a level, the tool doesn't re-weight to average down more aggressively.
4. Sizing does not adjust for current regime — risk-on vs risk-off doesn't change the shares per level.

---

## F. Priority matrix — close before next cron run (Sat Apr 25)

| Priority | Gap | Effort | Impact | Pre-next-run? |
|:---:|:---|:---|:---|:---:|
| 🔴 P0 | A4/C2: support-level-density gate | Medium (new helper + prescreen integration) | Eliminates 40% drop rate on onboards | **YES** — affects Tier 2 pool used by next run |
| 🔴 P0 | A3/C1: recency weighting in composite | Low (modify multi_period_scorer weights) | Better tournament rankings that match current regime | **YES** — affects tournament output |
| 🟡 P1 | A5/C3: resistance/bounce cache hoist | Trivial (one-line hoists) | 1h 15m–1h 30m runtime savings | **YES** — saves cron time |
| 🟡 P1 | D2: tier multiplier differentiation | Trivial (1 line constant) | Better capital allocation | **YES** if we want level quality to matter |
| 🟡 P1 | D1: Buffer quality-sizing | Medium (redesign pool-scope logic) | Fixes thin-ladder sizing lopsidedness | **NICE TO HAVE** — not blocking |
| 🟢 P2 | D4: earnings hard-block | Low (bullet_recommender config change) | Prevents blackout placements | Before next tournament → yes |
| 🟢 P2 | D3: autonomous broker reconciliation cron | Low (scheduled wrapper around existing tool) | Catches silent drift | Can wait |
| 🟢 P2 | D5: regime-aware offsets | Medium (enable + verify backward-compat) | Marginally better entries in volatile regimes | Can wait |
| 🟢 P2 | D6: daily wick refresh | Low (cron change) | Keeps zone classifications current | Can wait |
| 🟢 P2 | D9: `compute_pool_sizing` docstring | Trivial (one-line doc change) | Docs match behavior | With Phase 1 |
| 🟢 P2 | D10: POOL_MAX_FRACTION test coverage | Low (3 new unit tests) | Prevents sizing-math regressions | With Phase 1 (prevents future bugs) |
| 🟡 P1 | D8: include `total_approaches` in weight | Trivial (formula addition) + sweep re-run | Better signal-weighted sizing | Defer — needs careful backtest |
| 🟢 P2 | D7: dormant level sizing (design question) | Medium (stakeholder choice) | Cleaner broker state if skipped | Defer until dormant fills observed |

---

## G. Recommended closure plan before next run

**Phase 1 (mechanical fixes — all trivial, ~45 min total):**
1. D2 — change `POOL_TIER_MULT` to `{"Full": 1.5, "Std": 1.0, "Half": 0.5}` in `wick_offset_analyzer.py:177` ✅ **confirmed by user**
2. C3 — hoist `resistance_cache`/`bounce_cache` per the prior backlog spec
3. D4 — promote earnings-gate to hard-block in `bullet_recommender.py`
4. D9 — fix `compute_pool_sizing` docstring to describe actual price-weighted behavior
5. D10 — add 3 unit tests for `POOL_MAX_FRACTION` cap + residual redistribution

**Phase 2 (structural fixes — 2–3 hours total):**
6. C2 — support-level-density gate in `universe_prescreener.py` (post-processing filter)
7. C1 — recency weights in `multi_period_scorer.compute_composite` (linear `1:2:3:4` weighting of 12/6/3/1mo periods)

**Phase 3 (defer to post-run):**
8. D1 — Buffer quality-sizing redesign
9. D3 — autonomous broker reconciliation cron (schedule existing tool)
10. D5 — regime-aware offsets (enable + backtest)
11. D6 — daily wick refresh cron
12. D7 — dormant-level placement strategy (design decision)
13. D8 — add `total_approaches` to weight formula (after Phase 1 tier change settles)

---

## H. Open question for user — RESOLVED

**Question:** Should Full tier carry more weight than Std tier in sizing?
**User answer (2026-04-20):** **Yes.** D2 is confirmed as a real fix.

Phase 1 will implement `POOL_TIER_MULT = {"Full": 1.5, "Std": 1.0, "Half": 0.5}` or similar — subject to backtest verification before merging.
