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

## 8. Honest Assessment

| Claim | Real? | Evidence |
| :--- | :--- | :--- |
| Daily OHLCV can compute dip metrics | YES | open-to-low, low-to-close are standard bar computations |
| Side-channel adds ~30 lines | YES | DailyDipTracking dataclass + arithmetic in existing loop |
| Results comparable to standalone dip sim | MOSTLY | Daily metrics match. Breadth/intraday timing differ. |
| Regime breakdown is new and valuable | YES | Surgical sim already has regime per day. Just split dip stats by it. |
| Replaces hardcoded 60% threshold | YES | Simulation-backed win rate replaces arbitrary threshold |
| Multi-period (12/6/3/1mo) works for dip | YES | Same data, same loop, same window — dip metrics computed at each window |
| Graph integration is natural | YES | dip_kpis from multi-period-results.json → graph leaf → dip_viable node |

**The main risk**: The daily OHLCV dip-buy entry (at open - 1%) is an approximation of the real entry (at ~10:30 AM after breadth confirmation). Over many trades the averages converge, but individual-day results will differ. The simulation tells you "this ticker's dips are generally profitable" — the intraday signal checker tells you "today's specific dip is confirmed."

**Conclusion**: YES, extending the surgical simulation to track dip KPIs as a side-channel is feasible, low-risk (~75 lines total), and provides simulation-backed evidence for the daily dip per-ticker decision that currently relies on hardcoded thresholds. One simulation run, two strategy outputs.
