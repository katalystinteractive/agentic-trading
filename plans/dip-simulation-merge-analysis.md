# Analysis: Extending Surgical Simulation to Cover Daily Dip KPIs

**Date**: 2026-03-29 (Sunday)
**Question**: Can we run one simulation that produces both surgical (support-level) AND daily dip KPIs?

---

## 1. Current State

**Surgical strategy**: Has multi-period simulation (12mo/6mo/3mo/1mo), composite scoring, simulation-backed pool allocation. Results drive the daily analyzer via graph nodes.

**Dip strategy**: Has a single-period simulator that's completely disconnected from the daily analyzer. The dip watchlist uses hardcoded thresholds (range ≥ 3%, recovery ≥ 60%) computed on-the-fly from 1-month yfinance data. No simulation-backed evidence.

**The gap**: The surgical strategy proved that simulation > hardcoded thresholds (100-point scoring had zero correlation with P/L). The dip strategy still uses hardcoded thresholds.

---

## 2. Can We Merge?

**YES, partially.** Both simulators loop over daily OHLCV bars. The surgical sim already has Open, High, Low, Close per day per ticker. Computing dip metrics is simple arithmetic on the same data:

```
dip_pct = (open - low) / open × 100        → "did a 1%+ dip happen?"
recovery_pct = (close - low) / low × 100    → "did it recover 3%+?"
dip_buy_pl = buy at open-1%, sell at +4% or stop at -3% or cut at close
```

These are ~30 lines added to the surgical sim's daily loop. Zero impact on existing surgical logic.

**What we CAN compute from daily OHLCV (same data the surgical sim already fetches):**

| KPI | Computation | Uses |
| :--- | :--- | :--- |
| Dip frequency | count(open-to-low ≥ 1%) / total_days | "How often does this ticker dip?" |
| Recovery rate | count(dipped AND low-to-close ≥ 3%) / dip_days | "When it dips, how often does it bounce?" |
| Dip win rate | count(dip-buy hits +4% target) / dip_trades | "If I buy the dip, how often do I win?" |
| Dip P/L | sum of per-day dip-buy results (+4%/-3%/EOD cut) | "Total profit from dip strategy on this ticker" |
| Dip Sharpe | dip P/L mean / stddev | "Risk-adjusted dip returns" |
| Per-regime breakdown | All above split by Risk-On/Neutral/Risk-Off | "Does the dip play work in Risk-Off?" |

**What we CANNOT compute from daily OHLCV:**

| KPI | Why Not | What It Needs |
| :--- | :--- | :--- |
| Breadth confirmation | Requires cross-ticker 5-min bars at 10:30 AM | Intraday data for all tickers simultaneously |
| Intraday signal timing | First-hour vs second-hour distinction | 5-minute bars with market-hour timestamps |
| PDT tracking | Same-day round-trip counting within 5-day window | Multi-ticker intraday state machine |
| Precise entry price | Real entry is at ~10:30 AM after confirmation | 5-min bar at 10:30, not daily open |

---

## 3. Is the Daily OHLCV Approximation Good Enough?

**The honest answer: mostly yes, for the metrics that matter.**

The dip watchlist currently uses these hardcoded filters:
- `median_daily_range ≥ 3%` — computable from daily OHLCV ✓
- `recovery_rate ≥ 60%` — computable from daily OHLCV ✓

These are the SAME metrics we can compute in the surgical sim's side-channel. The daily OHLCV tells us: "on days when this stock dipped ≥1% from open, did it recover ≥3% by close?" This is exactly what the dip strategy needs to know.

**What's lost without intraday data:**
- Breadth confirmation (50% of tickers dipped) — this is a MARKET-WIDE signal, not per-ticker. It filters days, not tickers. The per-ticker decision of "is this ticker a good dip candidate?" doesn't need breadth data.
- Precise entry timing (10:30 AM) — using daily open-1% as entry proxy is slightly different from the real ~10:30 entry. But over 252 trading days, the averages converge.

**Bottom line**: Daily OHLCV gives us per-ticker dip viability. Intraday data gives us per-day signal confirmation. These are orthogonal — one selects WHICH tickers to watch, the other selects WHICH days to trade. The simulation side-channel answers the first question.

---

## 4. What the Merged Output Adds

Currently the multi-period scorer outputs per-ticker:
```json
{
  "CLSK": {
    "composite": 18.7,       // $/month from surgical strategy
    "active_pool": 321,
    "reserve_pool": 322
  }
}
```

With the merge, it would also output:
```json
{
  "CLSK": {
    "composite": 18.7,
    "active_pool": 321,
    "reserve_pool": 322,
    "dip_kpis": {
      "dip_frequency_pct": 37.7,    // 37.7% of days had a 1%+ dip
      "recovery_rate_pct": 85.3,    // 85.3% of dip days recovered 3%+
      "dip_win_rate_pct": 68.4,     // 68.4% of dip-buys hit +4% target
      "dip_pnl": 127.45,           // total simulated dip P/L over period
      "dip_sharpe": 2.1,           // risk-adjusted
      "by_regime": {
        "Risk-On": {"win_rate": 78.0, "pnl": 95.00},
        "Neutral": {"win_rate": 65.0, "pnl": 28.50},
        "Risk-Off": {"win_rate": 42.0, "pnl": 3.95}
      }
    }
  }
}
```

**What this enables for the daily dip decision:**

Instead of hardcoded `recovery_rate ≥ 60%`, the daily analyzer reads simulation-backed evidence:
- "CLSK: 85.3% recovery rate, 68.4% dip win rate, $127 P/L over 12 months" → STRONG dip candidate
- "USAR: 45.2% recovery rate, 31.0% dip win rate, -$42 P/L" → WEAK dip candidate, skip

And critically, the **regime breakdown** answers: "Does this ticker's dip play work in Risk-Off?"
- CLSK Risk-Off win rate 42% → "dips don't recover well in Risk-Off, half-size or skip"
- LUNR Risk-Off win rate 71% → "dips still work even in Risk-Off, proceed"

This is the per-ticker live context that's currently missing.

---

## 5. How It Connects to the Graph

The dip KPIs from simulation become new graph nodes:

```
multi_period_results (leaf) → {tk}:dip_kpis (computed)
                             → {tk}:dip_viable (decision: YES/NO/CAUTION)
                                → used by print_daily_fluctuation_watchlist()
```

The `{tk}:dip_viable` node combines:
- Simulation-backed dip win rate (> 50%?)
- Regime-specific performance (current regime's win rate > 40%?)
- Graph's existing `{tk}:catastrophic` (not HARD_STOP?)
- Graph's existing `{tk}:verdict` (not EXIT?)

This replaces the hardcoded `recovery_rate ≥ 60%` with simulation-backed evidence that accounts for regime and current ticker state.

---

## 6. Implementation Scope

### What changes in `backtest_engine.py` (~30 lines):

Add a side-channel tracker in the daily loop that computes dip metrics from the OHLCV data already being read. No changes to surgical logic.

### What changes in `multi_period_scorer.py` (~20 lines):

Extract dip_kpis from the simulation results and include in the multi-period output JSON alongside the existing composite score.

### What changes in `graph_builder.py` (~15 lines):

Add `{tk}:dip_kpis` leaf node (reads from multi-period results) and `{tk}:dip_viable` computed node.

### What changes in `daily_analyzer.py` (~10 lines):

`print_daily_fluctuation_watchlist()` reads `{tk}:dip_viable` from graph instead of computing `recovery_rate ≥ 60%` on-the-fly.

**Total: ~75 lines across 4 files. One simulation run produces both strategies' KPIs.**

---

## 7. What This Does NOT Replace

- **`dip_signal_checker.py`** stays unchanged — it handles real-time intraday breadth confirmation at 10:30 AM. This is a per-DAY gate, not a per-TICKER gate.
- **`dip_strategy_simulator.py`** stays available for full intraday backtesting when needed. The merged side-channel is a screening tool, not a replacement for detailed dip simulation.
- **The $100/trade budget** and **PDT tracking** remain separate concerns.

---

## 8. Honest Assessment (Post-Verification)

Verification found the core idea is sound but the analysis understated several issues:

| Claim | Initial | Verified | Issue |
| :--- | :--- | :--- | :--- |
| Daily OHLCV has Open available | YES | YES, but not currently accessed | backtest_engine reads High/Low/Close but not Open. 1 line to add. |
| Side-channel adds ~30 lines | ~30 | **~40-45** | Dip P/L tracking needs state management, not just arithmetic |
| Total across all files ~75 lines | ~75 | **~100-120** | Return tuple refactoring in candidate_sim_gate + multi_period_scorer plumbing |
| Zero impact on surgical logic | YES | YES | True side-channel, confirmed |
| Results comparable to standalone dip sim | MOSTLY | MOSTLY | Per-ticker viability matches. Breadth/signal timing cannot be replicated. |
| Recovery formula matches daily_analyzer | YES | **SUBTLE DIFF** | daily_analyzer uses High (low-to-high), analysis proposed Close (low-to-close). Must use High to match. |
| Regime breakdown feasible | YES | YES, needs trade-level tagging | Regime exists per day in backtest loop. Dip metrics must be tagged per-regime. |

### Issues Found During Verification

**1. Recovery formula mismatch**: daily_analyzer.py uses `(high - low) / low` (low-to-high recovery). The proposed formula uses `(close - low) / low` (low-to-close). These are different — high shows the BEST intraday recovery, close shows what actually held. Must decide which to use and be consistent. Recommendation: use High (matches existing daily_analyzer threshold gate).

**2. Order-of-operations ambiguity**: With daily OHLCV only, we don't know if the low happened before or after the high. The dip P/L computation must assume an order: check stop first (conservative), then check target, then close at EOD. This is the same assumption the surgical sim uses and is acknowledged as a simplification.

**3. Return tuple breaking change**: `run_simulation()` currently returns a 3-tuple `(trades, cycles, equity_curve)`. Adding `dip_kpis` makes it a 4-tuple. All callers must update: `candidate_sim_gate.py`, `backtest_reporter.py`, and the workflow agents. Not just 2 files.

**4. daily_range_analyzer.py already does similar work**: This module computes recovery rates, fill rates, and per-target win rates from daily OHLCV. Could the surgical sim call `daily_range_analyzer.analyze_daily_range()` per ticker instead of reimplementing the dip logic? This would avoid formula duplication. Need to check if analyze_daily_range accepts a hist DataFrame or only fetches from yfinance.

**5. Dip viable node spec missing**: The analysis mentions `{tk}:dip_viable` graph node but doesn't specify the computation. Proposal: `dip_viable = "YES" if dip_win_rate > 50% AND current_regime_win_rate > 40% else "CAUTION" if dip_win_rate > 40% else "NO"`.

### Risks

**Low risk**: Side-channel arithmetic is simple, regime data is available, no surgical logic affected.

**Medium risk**: Return tuple refactoring touches 3-4 files. If done incorrectly, breaks the surgical simulation workflow.

**Low risk**: Formula choice (High vs Close) affects threshold comparison but not the architecture.

---

## 9. Conclusion (Revised)

YES, the merge is feasible and valuable. The core idea is correct: one simulation run can produce both surgical and dip KPIs from the same daily OHLCV data.

**Corrections from verification:**
- Line count: ~100-120 lines, not 75
- Files touched: 5 (backtest_engine, candidate_sim_gate, multi_period_scorer, graph_builder, daily_analyzer), not 4
- Recovery formula must use High (match existing daily_analyzer), not Close
- Return tuple change is a breaking change requiring careful plumbing

**What's real**: Simulation-backed dip win rate per ticker, per regime, replacing hardcoded 60% threshold. This is the same upgrade path that proved valuable for the surgical strategy.

**What's approximate**: The daily OHLCV dip-buy entry is a proxy for the real 10:30 AM confirmed entry. Over many trades the averages converge, but this is inherently an approximation.
