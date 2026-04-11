# Portfolio-Level Simulation & Cross-Ticker Correlation — Analysis

**Date**: 2026-04-11 (v2 — verified)
**Tasks**: (3) Portfolio-level simulation, (4) Cross-ticker correlation risk

---

## Current State

### Per-Ticker Simulation (what exists)
- `backtest_engine.py` runs all tickers in a shared simulation loop (shared regime, shared dates) but each ticker has independent capital pools ($300 active + $300 reserve by default)
- No cross-ticker capital constraints — each ticker's $600 pool is independent, total exposure unbounded
- Multi-period composite scoring (12/6/3/1 month) ranks tickers by $/month
- 6 sweep types optimize per-ticker parameters independently
- Regime awareness exists (Risk-On/Neutral/Risk-Off) but applies same regime to all tickers

### Sector Tracking (what exists)
- `sector_registry.py`: 175 tickers mapped to 13 fine sectors, 11 broad sectors, 12 monitoring groups
- `market_pulse.py`: tracks 11 sector ETFs (XLK, XLF, XLE, etc.) with day/5d/20d performance
- `surgical_filter.py`: 10/100 pts for sector diversity (diminishing returns curve). SECTOR_CONCENTRATION_LIMIT=999 (disabled)
- `watchlist_fitness.py`: ZERO sector diversity scoring
- `multi_period_scorer.py`: has `allocate_capital()` for proportional pool sizing by composite — existing portfolio-level function that could feed capital adequacy checks

### What's Missing
1. **No total capital budget** — system can't model "I have $12K total, not $600 per ticker × 30 tickers"
2. **No simultaneous fill modeling** — if 5 crypto tickers all drop 10%, all fill bullets simultaneously, exhausting capital
3. **No correlation between tickers** — BBAI and TEM are both AI stocks but simulated independently
4. **No sector concentration warnings** — portfolio is 46% broad-sector Technology (AI + Quantum + Tech + Crypto mapped to XLK) with no alert. Fine-sector concentration is lower (~15% per sector) but still unmonitored
5. **No portfolio drawdown metric** — individual ticker drawdowns tracked but not portfolio-level

---

## What Would Actually Bring Value

### The Real Problem
The user has ~20 active positions across ~29 watchlist tickers, each with $600 surgical pools. Total theoretical surgical exposure: $17,400. Plus $1,000 velocity capital (6 concurrent × $175) and $1,000 bounce capital (10 concurrent × $100) = $19,400 total theoretical exposure. But tickers cluster by sector — a crypto crash hits CIFR, CLSK, APLD simultaneously. A "quantum winter" hits IONQ, RGTI, QBTS at once. The per-ticker simulation says each is profitable independently, but doesn't model the scenario where 6 tickers need capital at the same time.

### What Does NOT Bring Value
- **Full portfolio Monte Carlo simulation** — too complex, too many parameters, results not actionable
- **Correlation matrix computation** — requires 252-day rolling windows, computationally expensive, and the sector grouping already captures the most meaningful correlations
- **Beta-weighted position sizing** — overengineered for our $300-per-ticker pools
- **Sector rotation signals** — we're mean-reversion traders, not momentum rotators

### What DOES Bring Value (grounded in recent data)

**A. Sector Stress Test** — simulate what happens when an entire sector drops X% simultaneously
- Input: sector group, drop %, current positions
- Output: how many bullets fire, total capital needed, whether pool is exhausted
- Actionable: "If crypto drops 15%, you need $1,800 across 3 tickers. Your pools cover $900. Risk: 50% underfunded."

**B. Concentration Gate** — prevent onboarding/promoting tickers that make the portfolio too concentrated
- Add sector diversity scoring to `watchlist_fitness.py` (currently 0%)
- Lower `SECTOR_CONCENTRATION_LIMIT` from 999 to an actual limit (e.g., 5 per fine sector)
- Actionable: fitness verdicts say "REMOVE: sector overweight (4th AI ticker, limit 3)"

**C. Capital Adequacy Check** — daily check of total deployed vs total available
- Run at portfolio level in daily analyzer
- Show: total deployed, total pending, total if all pending fill, surplus/deficit
- Actionable: "WARNING: If all pending BUYs fill, you need $2,400 more than available"

**D. Correlated Drawdown Simulation** — NEW simulation that runs all tickers together with sector-correlated price moves
- Uses 4-period composite scoring (12/6/3/1 month)
- 8 parallel workers
- Own output files (no contamination)
- Integrates into daily analyzer as "Portfolio Risk" section

---

## Design Decisions

### Simulation Architecture

**Option A: Modify backtest_engine.py** to support multi-ticker mode
- Pro: single engine, consistent
- Con: breaks existing per-ticker sweeps, risky refactor of 880-line engine

**Option B: NEW portfolio_simulator.py** that wraps backtest_engine per-ticker results
- Pro: zero risk to existing sims, clean separation, parallel workers
- Con: doesn't model cross-ticker capital constraints during simulation

**Option C: NEW portfolio_stress_test.py** that simulates sector shocks on current positions
- Pro: directly actionable, fast, uses real portfolio data
- Con: not a full backtest, more of a scenario analyzer

**Choice: B + C combined.** Build `portfolio_stress_test.py` for immediate actionable output (sector shocks on real positions), and `portfolio_correlation_sim.py` for backtested composite scoring of portfolio-level risk.

### Correlation Method

**Option A: Statistical correlation** (rolling 60-day price correlation matrix)
- Pro: data-driven, catches non-obvious correlations
- Con: expensive to compute, unstable with small windows, changes over time

**Option B: Sector-based grouping** (tickers in same fine sector assumed correlated)
- Pro: simple, stable, already have FINE_SECTOR_MAP with 175 tickers
- Con: misses cross-sector correlations (NVDA correlates with crypto miners)

**Option C: Hybrid** — sector grouping as primary, with optional statistical correlation for validation
- Pro: captures known relationships, can discover unknown ones
- Con: more complex

**Choice: B (sector-based grouping).** Our 13 fine sectors already capture the meaningful clusters (Crypto, Quantum, Nuclear, AI, etc.) that drive correlated moves in our portfolio. Statistical correlation would require 252-day rolling windows and adds complexity without proportional value at our portfolio size (~20 positions). The sector map is manually curated and covers 175 tickers. If sector grouping proves insufficient (e.g., missing NVDA↔crypto miner correlation), we can add explicit `correlation_group` overrides later.

### Integration Points

| Output | Where it surfaces | How |
| :--- | :--- | :--- |
| Sector concentration warnings | Daily analyzer Part 7 | New "Portfolio Risk" section |
| Capital adequacy check | Daily analyzer | "If all pending fill..." warning |
| Stress test results | Daily analyzer + standalone CLI | Sector shock scenarios |
| Concentration gate | watchlist_fitness.py | New scoring component |
| Concentration gate | surgical_filter.py | Lower SECTOR_CONCENTRATION_LIMIT |

---

## Scope

### In Scope (4 deliverables)

1. **`tools/portfolio_stress_test.py`** — NEW tool
   - CLI: `python3 tools/portfolio_stress_test.py [--shock-pct 15] [--json] [--workers 8]`
   - Runs sector shock scenarios on current portfolio
   - 4-period composite scoring (12/6/3/1 month) for historical validation
   - 8 parallel workers for sector-parallel stress testing
   - Writes `data/portfolio_stress_results.json` (own file, no contamination)

2. **Concentration gate in watchlist_fitness.py**
   - Add sector diversity as 11th scoring component (reallocate from existing 100 pts)
   - Lower SECTOR_CONCENTRATION_LIMIT to actionable value (e.g., 4 per fine sector)
   - REMOVE/RESTRUCTURE verdicts include "sector overweight" reason

3. **Capital adequacy in daily_analyzer.py**
   - New section showing total deployed, total pending, worst-case if all fill
   - Warning when worst-case exceeds available capital

4. **Correlated drawdown in daily_analyzer.py**
   - Reads stress test results, shows "Sector Risk" summary
   - Flags sectors where >3 tickers are active with concentration warning

### Out of Scope
- Modifying backtest_engine.py (too risky, per-ticker sims work correctly)
- Portfolio-level sweep optimization (would take hours to run)
- Statistical correlation matrix (sector grouping is sufficient)
- Rebalancing recommendations (manual decision)

---

## Files to Create/Modify

| File | Action | Why |
| :--- | :--- | :--- |
| `tools/portfolio_stress_test.py` | NEW | Sector shock simulation |
| `tools/watchlist_fitness.py` | MODIFY | Add sector diversity scoring + concentration limit |
| `tools/daily_analyzer.py` | MODIFY | Add portfolio risk section |
| `tools/surgical_filter.py` | MODIFY | Lower SECTOR_CONCENTRATION_LIMIT |
| `data/portfolio_stress_results.json` | NEW (output) | Stress test results |

**Lines changed estimate:** ~250-350 across 4 files + 1 new file.

---

## Risks and Mitigations

| Risk | Mitigation |
| :--- | :--- |
| Sector grouping misses cross-sector correlation | FINE_SECTOR_MAP is manually curated, covers 175 tickers. Can add "correlation_group" later |
| Stress test runtime too slow | 8 parallel workers, sector-sharded. Each sector independent |
| Concentration limit too aggressive | Start at 4 per fine sector, tune based on real fitness results |
| Score rebalance breaks existing rankings | Use assert guards (existing pattern in both files) |
| New simulation contaminates existing data | Writes to `data/portfolio_stress_results.json` only |
