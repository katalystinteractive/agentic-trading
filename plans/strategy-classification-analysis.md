# Analysis: Strategy Classification Gap — Surgical vs Daily Range

**Date**: 2026-04-05 (Sunday)
**Trigger**: UGRO onboarded as tournament challenger ($39/mo composite) but has only 1 active-zone support level — can't be traded with the surgical bullet strategy.

---

## The Problem

The tournament ranks all tickers by composite $/mo from the backtest engine. But the backtest engine only simulates the **surgical strategy** (support-level bullets). Tickers that don't fit surgical (few/no support levels, high daily range) get either:
- **Inflated scores** — simulation luck with 1-2 levels produces a misleading composite
- **Zero scores** — no levels found, no trades simulated, composite = $0

Neither outcome is correct. These tickers need a different strategy (daily range) with its own simulation.

---

## What Already Exists

### Strategy Classification (surgical_filter.py)
- `score_daily_range()` computes a 100-point daily range score
- `strategy_type = "daily_range" if daily_range_score > support_total else "support"`
- **Already classifies every screened ticker** — but the classification is NOT persisted to sweep files or used by the tournament

### Daily Range Tools
- `daily_range_analyzer.py` — computes optimal dip entry + recovery target from 3-month data
- `bullet_recommender.py` — already has fallback: if zero valid levels, calls `daily_range_analyzer` and shows dip entry instead of bullets
- Screening data includes: `median_daily_range`, `days_above_3pct`, `dip_recovery_ratio`

### What's Missing
- **No daily range simulation** — the backtest engine can't simulate dip entries
- **No daily range sweep** — can't optimize dip parameters
- **No strategy tag in sweep results** — tournament can't distinguish surgical vs daily_range tickers
- **No minimum level gate** — a ticker with 1 active level passes all gates

---

## Real-World Impact

| Ticker | Active Levels | Tournament Score | Strategy Fit | Problem |
| :--- | :--- | :--- | :--- | :--- |
| UGRO | 1 | $39.0/mo | Daily Range | Simulation inflated — can't deploy surgical bullets |
| APP | ? | $141.7/mo | Unknown | Needs classification |
| NUAI | 4 | $36.9/mo | Surgical | OK — 4 active levels, good structure |
| CRWV | 4 | $35.8/mo | Surgical | OK — 4 active levels, good structure |

---

## What Needs to Be Built

### Phase 1: Strategy Gate in Tournament (LOW effort, immediate value)

Add a **minimum active level check** to the tournament before recommending onboarding. If a ticker has <3 active levels, tag it as "daily_range" in the tournament output. This doesn't require a new simulator — just prevents bad surgical recommendations.

**Implementation**:
1. Add `count_active_levels(ticker)` utility to `shared_utils.py` — reads wick data, counts levels in active zone
2. In `watchlist_tournament.py`, after ranking: run wick analysis for candidates, tag `strategy_type`
3. In the report: show strategy type column, flag daily_range tickers differently
4. In `execute_actions()`: onboard daily_range tickers with a `strategy_type` field so bullet_recommender knows to use daily range entry instead

**~40 lines across 2 files.**

### Phase 2: Daily Range Simulation (LOW-MEDIUM effort — reuse existing infrastructure)

Daily range simulation infrastructure **already exists** across 3 tools (~2,800 lines total):
- `parameter_sweeper.py` — sweeps dip thresholds, targets, stops per ticker. Outputs `data/sweep_results.json`.
- `dip_strategy_simulator.py` — backtests daily fluctuation strategy with breadth + bounce gates.
- `neural_dip_backtester.py` — replays historical 5-min data through neural evaluation.

**What's needed**: Wire the existing `parameter_sweeper.py` output (`sweep_results.json`) into the tournament ranking, alongside the surgical composite. The dip sweeper already produces per-ticker composite scores.

**Output**: `data/sweep_results.json` already exists with per-ticker stats (pnl, win_rate, trades). Need to add `composite` $/mo field (via `compute_composite()`) for tournament comparison.

**~50 lines to wire existing dip sweep output to tournament** (not 230 lines from scratch).

### Phase 3: Unified Tournament Ranking (LOW effort after Phase 2)

Tournament loads BOTH sweep types:
- Surgical composite from support/resistance/bounce/entry sweeps
- Daily range composite from daily_range_sweep_results.json

For each ticker: `best_composite = max(surgical_best, daily_range_composite)`

Tickers compete on the same $/mo metric regardless of strategy — the tournament just picks the best approach per ticker automatically.

**~15 lines changed in `watchlist_tournament.py`.**

---

## Recommended Approach

**Phase 1 now** — add the strategy gate to tournament + onboarding. Prevents future UGROs. ~40 lines, immediate value.

**Phase 2 next session** — build the daily range simulator. Enables proper scoring of high-range tickers. ~230 lines, significant but well-scoped.

**Phase 3 follows Phase 2** — unified ranking. Trivial after Phase 2 exists. ~15 lines.

---

## What to Do About UGRO Now

UGRO has 1 active level and 19% daily range. It fits the daily range strategy:
- Dip buy at $18.91 (-0.5% from $19.00)
- Target: $19.47 (+3%)
- Win rate: 100% (from daily_range_analyzer)

For Monday: place UGRO as a **daily range entry** (dip buy), not a surgical bullet. The bullet_recommender already shows this in the "Daily Fluctuation Entry" section. Once Phase 2 is built, UGRO gets a proper daily range composite score.
