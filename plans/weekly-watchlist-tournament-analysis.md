# Analysis: Weekly Watchlist Tournament

**Date**: 2026-04-03 (Friday)
**Purpose**: Design a simulation-driven weekly watchlist tournament that ensures the top 30 tickers by profit/risk ratio are always tracked.

---

## 1. The Problem

We have 42 tickers with full sweep data (support, resistance, bounce, entry, level filters). Only 27 are tracked (positions + watchlist). The data shows clear mismatches:

| Ticker | Status | Composite $/mo | Action Needed |
| :--- | :--- | :--- | :--- |
| APP | **Not tracked** | $114.2 | Should be tracked — beats everything |
| HIMS | **Not tracked** | $26.0 | Outperforms CLF ($16.4), OUST ($17.3) |
| IBRX | **Not tracked** | $25.3 | Outperforms ONDS ($19.8), RUN ($20.0) |
| MARA | **Not tracked** | $22.1 | Outperforms OUST, ONDS |
| IREN | **Not tracked** | $21.7 | Outperforms OUST, ONDS |
| TMC | **Tracked (90 shares)** | N/A | Absent from all sweep files — sim errors (IndexError). Active position with no simulation backing — cannot be ranked. Defer to winding_down. |
| SMCI | **Tracked** | N/A | Absent from all sweep files — position closed 2026-03-20, no sweep run. Dead slot. |
| CLF | **Tracked** | $16.4 | Bottom quartile of tracked tickers |
| OUST | **Tracked** | $17.3 | Below several untracked candidates |

**Root cause**: No automated process compares incumbents vs challengers using simulation data. The 100-point fitness scoring (watchlist_fitness.py) measures strategy fit, but the impact assessment proved it has **zero correlation with simulation P/L**. Composite $/mo from the multi-period sweeps is the real signal, but it doesn't drive watchlist decisions today.

---

## 2. What Exists Today

### 2.1 Scoring Systems (Two Separate, Unlinked)

**Watchlist Fitness (100 pts)** — measures strategy compatibility:
- Swing (15), Consistency (15), Level Quality (10), Hold Rate (10), Order Hygiene (20), Cycle Efficiency (20), Touch Frequency (10)
- Produces 9 verdicts: ENGAGE, ADD, HOLD-WAIT, RESTRUCTURE, REVIEW, REMOVE, EXIT-REVIEW, RECOVERY, WAIT
- ADD = active position + ENGAGE-eligible, EXIT-REVIEW = active position failing criteria, RECOVERY = pre-strategy position, WAIT = overbought RSI/SMA override
- **Problem**: ENGAGE doesn't mean profitable. A ticker can score 85/100 and lose money in simulation.

**Simulation Composite ($/mo)** — measures actual backtest profitability:
- 4-period weighted average (12mo/6mo/3mo/1mo)
- Significance-gated: periods with <5 cycles get reduced weight
- **This is the real signal** — directly measures what matters (P/L)

### 2.2 Candidate Pipeline (Discovery → Onboarding)
1. `universe_screener.py` — scans ~4000 tickers, finds ~50-200 passers
2. `surgical_screener.py` — deep wick analysis on top 20-50
3. `surgical_filter.py` — scores and shortlists top 7
4. `candidate_tracker.py` — manages candidate pool (add/promote/age-out)
5. `batch_onboard.py` — creates ticker infrastructure + adds to watchlist

**Problem**: This pipeline discovers candidates but never pits them against incumbents using simulation data. A candidate scores 80/100 on the filter and gets onboarded, but we never ask "does this ticker simulate better than what we already have?"

### 2.3 Weekly Reoptimize Pipeline
- Runs Saturday: support sweep → clustering → weight training
- Now also: resistance sweep → bounce sweep → entry sweep (just added to cron)
- **Problem**: Re-optimizes parameters for tracked tickers only. Doesn't sweep candidates, doesn't compare, doesn't recommend swaps.

---

## 3. Requirements for Weekly Tournament

### 3.1 Core Ranking Metric

**Best-of composite $/mo** across all sweep types (support, resistance, bounce, entry) is the primary ranking signal. Per ticker, pick the highest composite from whichever strategy performed best.

**Important: `compute_composite()` already handles confidence.** The multi-period scorer weights each period by `min(cycles, 5) / 5`, so low-cycle periods are automatically discounted. Adding a separate confidence multiplier on top would double-penalize.

The tournament score should apply **only adjustments NOT already in the composite**:

```
tournament_score = best_composite
```
Where:
- `best_composite` = max(support_composite, resistance_composite, bounce_composite, entry_composite) per ticker
- Each composite is read from `stats.composite` in the respective sweep result file

Trade count and win rate are already captured by the composite's significance weighting (`compute_composite()` weights by `min(cycles, 5)/5`). Period consistency is inherent in the 4-period averaging. No additional multiplier needed.

**Future enhancement**: When `--split` cross-validation data becomes available in sweep results (currently `None` for all tickers — sweeps haven't been run with `--split`), add an overfit penalty: `× 0.7` if train P/L > 0 but validation P/L < 0. This requires running Saturday sweeps with `--split` flag.

**Note on sweep availability**: Not all tickers have all 4 sweep types. Use whatever sweep data exists. Tickers absent from ALL sweep files (e.g., TMC) get tournament_score = 0.

### 3.2 Tournament Structure

**Weekly cycle (runs after Saturday sweeps complete)**:

1. **Rank all swept tickers** by tournament score — incumbents and candidates together in one table
2. **Mark the top 30** as the target watchlist
3. **Flag incumbents outside top 30** → candidates for REMOVAL
4. **Flag non-incumbents inside top 30** → candidates for ADDITION
5. **Apply safety gates** before recommending swaps:
   - Never force-sell a ticker with an active position — set `winding_down` flag (no new bullets, monitor until close)
   - Never remove a ticker added <4 weeks ago (give it time)
   - Require new ticker to beat incumbent by ≥20% tournament score (stability margin)
   - Cap swaps at 3 per week (avoid thrashing)

### 3.3 Integration with Existing Tools

The tournament should NOT replace existing tools — it sits on top:

| Existing Tool | Tournament Interaction |
| :--- | :--- |
| Sweep results (4 files: support, resistance, bounce, entry) | **Input** — reads `stats.composite` $/mo from each, picks best per ticker |
| `watchlist_fitness.py` | **No gate for tournament ranking.** Fitness verdicts inform post-tournament actions (onboarding readiness, order hygiene) but do NOT filter tournament entry. New candidates without cycle data would get HOLD-WAIT from fitness, which would block them if used as a gate. Tournament ranks purely by simulation composite. |
| `surgical_filter.py` | **Discovery feed** — new candidates that pass screening enter the sweep pipeline |
| `watchlist_manager.py` | **Executor** — tournament recommendations flow to promote/demote/drop commands |
| `batch_onboard.py` | **Onboarding** — new top-30 tickers that aren't yet set up get onboarded |
| `weekly_reoptimize.py` | **Trigger** — tournament runs as a new step AFTER all sweeps complete |

### 3.4 The Candidate Sweep Gap

Sweep tools technically accept ANY ticker via `--ticker` flag — no onboarding required. The gap is **operational**: nobody triggers sweeps for non-tracked tickers automatically. The candidate pipeline (universe_screener → surgical_filter) discovers candidates but doesn't invoke sweeps on them.

**Approach: Sweep Top 15 Candidates (Stage 1 only)**

After universe screening shortlists top 15 candidates, run support sweep **Stage 1 only** (30 threshold combos × 4 periods). This produces a composite $/mo for ranking.

- **Runtime**: ~6-7 min per ticker sequential, ~15-20 min with 8 workers for 15 tickers
- **Why Stage 1 only**: Full Stage 1+2 takes ~120-150 min for 15 tickers — too slow for weekly pipeline. Stage 1 composite is sufficient for ranking. Full Stage 1+2 runs only for tickers that win a tournament slot.
- **No onboarding needed**: `_collect_once()` fetches yfinance data directly, runs simulation without identity.md or wick_analysis.md

Tickers that earn a top-30 slot then get promoted (can run Sunday or next Saturday):
1. Full Stage 1+2 support sweep (re-run with execution optimization, ~8-12 min per ticker)
2. Resistance, bounce, entry sweeps (~15 min per ticker total)
3. Onboarding via `batch_onboard.py` (identity, memory, wick analysis, cycle timing)
4. Added to watchlist with `added_date` timestamp

Stage 1 data from candidate sweep is NOT reused — full Stage 1+2 re-run ensures execution params are optimized, not just thresholds.

### 3.5 Output Format

Weekly tournament report:

```
## Watchlist Tournament — 2026-04-05

### Power Rankings (Top 30 by Tournament Score)
| Rank | Ticker | Score | Comp $/mo | WR | Trades | Status |
| 1    | APP    | 108.3 | $114.2    | 92%| 34     | NEW → Onboard |
| 2    | NVDA   | 34.2  | $35.6     | 88%| 15     | Tracked ✓ |
| ...  | ...    | ...   | ...       | ...| ...    | ... |
| 29   | CLF    | 15.1  | $16.4     | 75%| 12     | Tracked ✓ |
| 30   | CDE    | 13.5  | $14.2     | 70%| 8      | NEW → Challenge |
| ---  | ---    | ---   | ---       | ---| ---    | Below cutoff |
| 31   | OUST   | 12.8  | $17.3     | 65%| 6      | DROP candidate |
| 32   | TMC    | 0.0   | $0.0      | 0% | 0      | WIND DOWN (90 shares) |

### Recommended Actions
- ONBOARD: APP (score 108.3, beats #30 by 700%)
- CHALLENGE: CDE to replace OUST (13.5 vs 12.8, +5.5%)
- WIND DOWN: TMC (zero simulation value, 90 active shares → no new bullets, monitor until close)
- DROP: SMCI (zero simulation value, no active position → remove from watchlist)

### Stability Check
- No churning: 2 swaps this week (under 3-swap cap)
- APP was #1 in both 12mo and 3mo periods (consistent)
- CDE has only 8 trades (composite already discounted by significance weighting)
```

---

## 4. What Needs to Be Built

### 4.1 New Tool: `tools/watchlist_tournament.py`
- Reads 4 sweep result files (support, resistance, bounce, entry)
- Computes tournament score per ticker
- Ranks all swept tickers
- Applies safety gates
- Produces tournament report (markdown + JSON)
- CLI: `python3 tools/watchlist_tournament.py [--dry-run] [--top N]`

### 4.2 Extension: Candidate Sweep Pipeline
- After screening shortlists top 15 candidates, auto-run support sweep (Stage 1 only) on them for ranking
- Could be a new step in `weekly_reoptimize.py` or a standalone script
- Only candidates that beat bottom-5 incumbents get full 5-sweep treatment

### 4.3 Cron Addition
- New Saturday cron job after entry sweep completes (~13:20)
- `13:30 Saturday` → run tournament, email results

### 4.4 Integration Points
- Tournament output feeds `watchlist_manager.py rebalance`
- New tickers flagged for onboarding feed `batch_onboard.py`
- Drop candidates with active positions feed `exit-review-workflow`

---

## 5. Scope Estimate

| Component | Lines | Complexity |
| :--- | :--- | :--- |
| `watchlist_tournament.py` (core ranker + report) | ~200 | Medium — reads 4 sweep result files, computes scores, applies gates |
| Candidate sweep integration | ~50 | Low — extend weekly_reoptimize with one more step |
| Cron addition | ~3 | Trivial |
| **Total** | **~250** | |

---

## 6. Decisions (Resolved)

1. **Ranking metric**: Use ALL sweep composites (support, resistance, bounce, entry) — pick the **best composite** across all sweep types per ticker. This captures tickers that excel at any strategy, not just support.

2. **Swap aggressiveness**: 3/week cap for competitive swaps (where challenger beats incumbent by ≥20%). Tickers absent from sweep data entirely are flagged for removal with no cap — they have no simulation backing. However, the winding_down rule still applies: tickers with active positions (e.g., TMC — 90 shares, sim errors) get `winding_down` flag instead of immediate drop. Tickers with no position (e.g., SMCI — closed) are dropped immediately. Most weeks should be 0-1 actual changes.

3. **Dropped tickers with active positions**: Keep monitoring until position closes, but **no more capital deployment** (no new bullets). Existing pending buys stay, existing sell targets stay. Once position fully closes, remove from watchlist. This avoids forced selling while naturally winding down.

4. **Universe screening**: Run weekly on cron. Full automated pipeline: universe screen → shortlist → sweep top 15 candidates → tournament ranking → onboard winners / wind down losers.

---

## 7. Revised Scope

| Component | Lines | Complexity |
| :--- | :--- | :--- |
| `watchlist_tournament.py` (core ranker + report) | ~250 | Medium — reads 4 sweep result files, computes best-of composite per ticker, applies gates, produces report + JSON |
| Candidate sweep step in `weekly_reoptimize.py` | ~60 | Low — after screening, run support sweep on top 15 candidates |
| Universe screening cron job | ~3 | Trivial — add Saturday cron entry before sweeps |
| "Wind down" flag in portfolio.json | ~30 | Low — add `winding_down: true` to position, `added_date` to watchlist entries. Daily analyzer skips new bullets for winding_down positions. 4-week protection uses added_date. |
| Cron addition for tournament | ~3 | Trivial |
| **Total** | **~346** | |

### Full Saturday Pipeline (Automated)
```
09:00  Universe screening (~10-20 min, cached 3-day validity)
09:30  Candidate sweep — top 15, Stage 1 only, 8 workers (~20 min)
10:00  Weekly reoptimize — support sweep all tracked (~70 min)
11:30  Resistance sweep (~35 min)
12:15  Bounce sweep (~50 min)
13:15  Entry sweep (~4 min)
13:30  Watchlist tournament — rank all, flag swaps, email report (~2 min)
```
All done by ~13:32 Saturday. Results ready for review before Monday.

**Post-tournament (if swaps recommended)**:
- Promoted tickers: full Stage 1+2 sweep + onboarding (can run Sunday or deferred to next Saturday)
- Dropped tickers with positions: `winding_down` flag set, no new bullets
