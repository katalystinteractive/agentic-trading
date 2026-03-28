# Analysis: Can the Dependency Graph Enhance Candidate Evaluation?

**Date**: 2026-03-29 (Sunday)
**Purpose**: Honest assessment of whether the reactive dependency graph can improve the sim-ranked candidate workflow's evaluation, and if so, where exactly.

---

## 1. How the Candidate Workflow Works Today

**Phase 1 — Simulation Screening** (`sim_ranked_screener.py`):
- Loads pre-screened universe (swing ≥25%, vol ≥1M)
- Runs 10-month backtest on top 30 by tradability proxy
- Gates: P/L > $0, Win > 90%, Sharpe > 2.0, zero catastrophic stops
- Output: candidates ranked by P/L

**Phase 2 — Portfolio Validation** (`post_sim_validator.py`):
- 4 mechanical checks: sector concentration, earnings blackout, price correlation, liquidity
- Output: flags (informational, non-blocking)

**What it does well**: Proves a candidate was profitable in simulation with high win rate and risk-adjusted returns. This is the hard part — most stocks fail the gates.

**What it doesn't do**: Contextualize the simulation results against current reality.

---

## 2. The 10 Evaluation Gaps (Verified Against Code)

I found 10 gaps. For each, I checked: does the data exist, does the strategy need it, and can the graph help.

### Gap 1: Market Regime During Simulation — REAL GAP, GRAPH CAN HELP

**The problem**: A candidate showing $1,200 P/L over 10 months tells you nothing about WHEN those profits were made. If 90% came during Risk-On months and we're currently in Risk-Off, the candidate's track record is irrelevant to current conditions.

**Data exists?** YES. `backtest_engine.py` already precomputes regime per day using VIX + index data. The simulation loop has regime data — it just doesn't report P/L broken out by regime.

**Strategy needs it?** YES. The daily analyzer already gates entry decisions on regime (Risk-Off → PAUSE/REVIEW). Candidates evaluated without regime awareness bypass this gate.

**Graph can help?** YES. A graph node `{candidate}:regime_resilience` could consume the simulation's per-regime P/L breakdown and produce a resilience score. If a candidate only profits during Risk-On, the node signals "LOW resilience" which the dashboard surfaces as a warning.

**Effort**: MEDIUM. The simulation engine needs to output P/L per regime (code change in `backtest_engine.py`), then the graph consumes it.

### Gap 2: Capital Availability — REAL GAP, GRAPH CAN HELP

**The problem**: 10 candidates pass simulation, but we only have $3,000 of remaining capital. The workflow says "onboard all 10" without checking if we can afford it.

**Data exists?** YES. `portfolio.json` has capital section. `get_ticker_pool()` computes per-ticker pools. Remaining capital = total capital - sum of deployed positions.

**Strategy needs it?** YES. Every stock gets $300-$600 from a fixed capital pool. If the pool is exhausted, we can't onboard.

**Graph can help?** YES. A graph node `available_capital` computes remaining capital from portfolio positions. When candidates are evaluated, the graph can rank them by "P/L per dollar deployed" and cut the list at the capital boundary.

**Effort**: LOW. The data and computation already exist. Just wire into evaluation output.

### Gap 3: Wick Data Quality — REAL GAP, GRAPH CAN HELP

**The problem**: Simulation proves a candidate is profitable, but in practice we need usable support levels to place bullet orders. If the candidate has no wick data, or support levels are eroding, the simulation results can't be replicated.

**Data exists?** PARTIALLY. `screening_data.json` from Phase 1 has some wick analysis (for shortlisted candidates). But not all simulation passers have deep wick analysis.

**Strategy needs it?** YES. The entire mean-reversion strategy depends on placing limit buys at wick-adjusted support levels. No levels = no strategy.

**Graph can help?** YES. A graph node `{candidate}:wick_viability` checks: number of active-zone levels, average hold rate, zone coverage. If a candidate passes simulation but has zero usable support levels, the node flags "NOT DEPLOYABLE."

**Effort**: MEDIUM. Need to run wick analysis on passers (may already happen in screening) and pipe results through graph.

### Gap 4: Cycle Count in Simulation — REAL GAP, GRAPH CAN HELP

**The problem**: A candidate with $1,200 P/L from 2 lucky trades is ranked the same as one with $1,200 from 25 consistent cycles. The first is noise; the second is a pattern.

**Data exists?** YES. The simulation output already includes cycle count. `sim_ranked_screener.py` outputs `total_cycles` in results.

**Strategy needs it?** YES. The surgical filter already has KPI_MIN_CYCLES=5. But this gate isn't applied to sim-ranked results — only to the old scoring-based workflow.

**Graph can help?** YES. A graph node `{candidate}:statistical_confidence` flags candidates with <5 cycles as "LOW CONFIDENCE" even if P/L is high. This is a 5-line computation on existing data.

**Effort**: LOW. The data exists in simulation output. Just add a threshold check.

### Gap 5: Earnings Proximity (Beyond Blackout) — REAL GAP, GRAPH CAN HELP

**The problem**: Phase 2 checks "is the candidate IN a blackout window right now?" But it doesn't check "earnings is in 8 days — if we onboard today, we'll be in blackout before we can even trade one cycle."

**Data exists?** YES. `earnings_gate.py` returns next earnings date and approaching window (14 days).

**Strategy needs it?** YES. The strategy has a 7-day pre-earnings blackout. If a candidate's next earnings is in 10 days, we have only 3 days to operate before we're blocked.

**Graph can help?** YES. A graph node `{candidate}:earnings_clearance` computes: days until next earnings - expected cycle duration (median ~14 days from cycle timing). If clearance < 1 cycle, flag "EARNINGS TOO CLOSE."

**Effort**: LOW. `check_earnings_gate()` already returns the data. Add a comparison to median cycle length.

### Gap 6: Price-to-Pool Sizing — REAL GAP, GRAPH CAN HELP

**The problem**: A $150 stock with a $300 pool = 2 shares per level. That's not enough for meaningful averaging. The simulation ran with hypothetical sizing, but real deployment needs real share counts.

**Data exists?** YES. Current price is known. Pool size is known ($300 default or simulation-backed). Shares per bullet = pool / levels / price.

**Strategy needs it?** YES. Bullet sizing scales with share price (~$100 for $16+ stocks, ~$30 for $1.50 stocks). A $150 stock breaks this model.

**Graph can help?** YES. A graph node `{candidate}:sizing_viability` checks: at current price and pool, how many shares per bullet? If <3 shares per level, flag "SIZING IMPRACTICAL."

**Effort**: LOW. Pure arithmetic on existing data.

### Gap 7: Active vs Dormant Sector Overlap — MARGINAL GAP

**The problem**: Sector concentration check counts ALL tickers in a sector, not just active ones. Having 5 crypto tickers in watchlist (4 dormant) is different from 5 active crypto positions.

**Data exists?** YES. portfolio.json has position status (shares > 0 = active).

**Strategy needs it?** PARTIALLY. Strategy says diversify, but sector diversity scoring already exists in `surgical_filter.py` and `watchlist_fitness.py`.

**Graph can help?** MARGINALLY. Could weight sector count by capital deployed instead of ticker count. But this is a refinement, not a new capability.

**Effort**: LOW, but benefit is marginal.

### Gap 8: Correlation with Active Positions — ALREADY EXISTS

**The problem**: Candidates correlated with existing positions create capital conflict.

**Data exists?** YES. `post_sim_validator.py` already computes correlation at >75% threshold.

**Strategy needs it?** YES, and it's already checked.

**Graph can help?** NO additional benefit. This is already in Phase 2. The graph would duplicate existing logic.

**Effort**: N/A — already implemented.

### Gap 9: Seasonal P/L Decomposition — SPECULATIVE

**The problem**: Candidate P/L might be seasonal — all from January, nothing in other months.

**Data exists?** PARTIALLY. Multi-period scorer runs 12mo/6mo/3mo/1mo windows. But per-month P/L decomposition within a window doesn't exist.

**Strategy needs it?** UNCLEAR. The strategy doesn't reference seasonality. It's a valid concern but no decision rule exists.

**Graph can help?** SPECULATIVE. Would need new simulation output (monthly P/L) that doesn't exist today.

**Effort**: HIGH. Requires backtest engine changes + new graph nodes + decision rules that don't exist.

### Gap 10: Execution Microstructure — SPECULATIVE

**The problem**: Simulation assumes orders fill at wick-adjusted prices. Real execution has slippage.

**Data exists?** NO. No fill-rate tracking at specific price levels.

**Strategy needs it?** Eventually, but not urgent. The strategy already accounts for wick offsets.

**Graph can help?** NO. This is a data collection problem, not a graph problem. You'd need to track actual fills vs expected fills over time.

**Effort**: HIGH. New data pipeline required.

---

## 3. What the Graph Can Actually Do for Candidates

Of the 10 gaps, **6 are real and graph-addressable** (gaps 1-6), **1 is marginal** (gap 7), **1 is already implemented** (gap 8), and **2 are speculative** (gaps 9-10).

The graph can add a **candidate evaluation layer** that runs AFTER simulation but BEFORE the human sees results. It would:

```
Simulation Results (Phase 1)
  │
  └→ Graph Evaluation Layer (NEW)
      ├─ {candidate}:regime_resilience    — P/L breakdown by regime
      ├─ {candidate}:capital_clearance    — can we afford to onboard?
      ├─ {candidate}:wick_viability       — support levels usable?
      ├─ {candidate}:statistical_confidence — enough cycles?
      ├─ {candidate}:earnings_clearance   — enough time before next event?
      ├─ {candidate}:sizing_viability     — shares per bullet practical?
      │
      └→ {candidate}:evaluation_grade     — composite: READY / CAUTION / NOT_READY
          │
          └→ REPORT: candidates ranked by P/L but annotated with grade
```

**What changes for the user**: Instead of seeing:
```
| Rank | Ticker | P/L | Win% | Sharpe |
| 1    | ASTS   | $1,200 | 95% | 3.2 |
| 2    | HIMS   | $1,100 | 92% | 2.8 |
```

You'd see:
```
| Rank | Ticker | P/L | Win% | Grade | Flags |
| 1    | ASTS   | $1,200 | 95% | READY | 25 cycles, wick OK, earnings clear |
| 2    | HIMS   | $1,100 | 92% | CAUTION | 3 cycles (low confidence), earnings in 9 days |
```

The simulation ranking stays authoritative. The graph doesn't re-rank — it annotates.

---

## 4. What the Graph CANNOT Do

- **Replace simulation** — the graph doesn't run backtests. Simulation is the source of truth for performance.
- **Predict future performance** — the graph evaluates current deployability, not future P/L.
- **Remove human judgment** — the CAUTION grade informs the decision, doesn't make it.
- **Fix missing data** — if wick analysis hasn't been run on a candidate, the graph can't invent support levels.

---

## 5. Honest Assessment (Post-Verification)

The initial analysis claimed 6 gaps were "real and graph-addressable." Verification against the actual code found:

| Gap | Real? | Already Covered? | Would Change Outcomes? | Verified Verdict |
| :--- | :--- | :--- | :--- | :--- |
| 1. Regime resilience | YES — data exists in backtest but not aggregated | NO | **LOW** — descriptive context, user would still onboard proven P/L | REAL but low practical impact |
| 2. Capital availability | YES — not checked in workflow | NO | **VERY LOW** — user already knows capital constraints manually | REAL but moot — UX improvement only |
| 3. Wick viability | YES for sim-ranked | PARTIAL — `surgical_filter.py` gates 2-4 check this, but NOT applied to sim-ranked workflow | **HIGH** — prevents wasted onboarding of undeployable candidates | **REAL + HIGH VALUE** |
| 4. Cycle confidence | YES — cycle count in output | YES — `surgical_filter.py` Gate 6 has KPI_MIN_CYCLES=5, but NOT applied to sim-ranked | **LOW** — Win>90% + Sharpe>2 already filters noise harder than cycle count | REAL but redundant with existing gates |
| 5. Earnings clearance | YES — no cycle-vs-earnings comparison | NO | **LOW** — limit orders don't fill immediately, so blackout timing is irrelevant for patience-based strategy | REAL but edge case |
| 6. Sizing viability | YES — sim-ranked doesn't check | NO | **MEDIUM** — caught downstream by bullet_recommender, but real constraint for high-price stocks | REAL but caught at next step |
| 7. Active sector overlap | MARGINAL | PARTIAL | MARGINAL | Not worth building |
| 8. Correlation | N/A | YES — in post_sim_validator | N/A | Already done |
| 9. Seasonal P/L | SPECULATIVE | NO | NO data exists | Not worth building |
| 10. Microstructure | SPECULATIVE | NO | NO data exists | Not worth building |

### Key Finding

**Only 1 gap would genuinely change evaluation outcomes: Gap 3 (Wick Viability).**

A candidate can pass simulation with $1,200 P/L but have zero usable support levels because:
- Support levels eroded (decayed hold rate below threshold)
- No levels in the active zone at current price
- Too few levels for the bullet strategy (need 3+ active)

The sim-ranked workflow runs backtests on historical data where levels existed. It doesn't check if those levels still exist TODAY. The surgical-candidate-workflow DOES check this (via `surgical_filter.py` gates 2-4), but the sim-ranked workflow bypasses those gates entirely.

**This is a real deployability blocker** — you'd onboard a candidate, run bullet_recommender, and get "No eligible support levels" or "1 level with 18% hold rate." Wasted time and effort.

### What About the Other 5?

- **Regime resilience**: Nice context ("earned P/L mostly in Risk-On") but wouldn't change onboarding decision when simulation proves profitability
- **Capital availability**: User knows their capital. Adding a number to the report doesn't change behavior
- **Cycle confidence**: A candidate with 2 cycles but Win>90% and Sharpe>2 is more statistically filtered than one with 25 cycles at 60% win rate. The existing gates are harder
- **Earnings clearance**: With limit orders at wick-adjusted prices, fills happen when price dips to the level, not on a schedule. Earnings proximity doesn't matter if the order hasn't filled yet
- **Sizing viability**: A $150 stock failing bullet_recommender is caught at the next step, not at screening. And the simulation already proved P/L at that price — the question is whether YOUR pool can replicate it, which is a manual capital decision

---

## 6. Revised Conclusion

The candidate workflow has **one genuine gap that the graph can fill**: wick viability for sim-ranked candidates.

The fix is simpler than a full graph integration:
- Run `surgical_filter.py` gates 2-4 (active levels ≥ 3, anchor level ≥ 50% hold, dead zone < 30%) on sim-ranked passers
- This is ~20 lines of code in `post_sim_validator.py` or a new Phase 2.5 step
- No graph node needed — just apply the existing surgical_filter gates to sim-ranked results

**The graph is NOT the right tool for this.** The surgical_filter gates already exist as Python functions. Wrapping them in graph nodes adds complexity without adding capability. The right fix is: call the existing functions on the sim-ranked passers.

The other 5 gaps are either already handled by harder gates, caught at the next step, or provide context that doesn't change decisions. Building graph nodes for them would be the same mistake as the 8 upgrade proposals — architecturally elegant, practically useless.
