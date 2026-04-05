# Simulation Gap Analysis: What's Missing That Would Improve Profits

**Date**: 2026-04-03
**Scope**: All 5 sweep types + backtest engine + live tool consumption

---

## What We Have (Complete Picture)

### 5 Sweep Types — What Each Optimizes

| Sweep | Question It Answers | Params | Combos |
| :--- | :--- | :--- | :--- |
| **Support Threshold** | What sell % and stop loss % are optimal? | sell_default (4-10%), cat_hard_stop (15-40%) | 30 |
| **Support Execution** | How much capital and how many bullets per zone? | pool sizes, bullet counts, tier thresholds | 144 |
| **Level Filters** | Which support levels are worth trading? | min_hold_rate, touch_freq, dormancy, zone_filter | 100 |
| **Resistance Sell** | Should we sell at resistance instead of flat %? | strategy (first/best), reject_rate, approaches, fallback | 54 |
| **Bounce Sell** | Should we sell at bounce-derived targets? | window_days, confidence, cap_prior_high, fallback | 54 |
| **Entry Gates** | Should we use recency-weighted offsets and cooldowns? | offset_decay (0/60/90d), post_break_cooldown (0/2/5d) | 9 |

### Backtest Engine — What It Simulates Each Day
- Regime classification (Risk-On/Neutral/Risk-Off from VIX + indices)
- Exit checks: profit target, time stop (60d + Risk-Off extension), catastrophic stop
- Fill checks: day_low ≤ limit_price → fill
- Level recomputation: rolling 13-month wick analysis (no look-ahead)
- Zone assignment: Active/Buffer/Reserve by distance from current price
- Pool-distributed sizing with tier weights
- Cycle tracking (completed buy→sell cycles, duration, win rate)

### What's Fully Wired
- Support sweep → pool sizes, bullet counts, tier thresholds → bullet_recommender
- Level filters → wick_offset_analyzer → which levels to trade
- Entry gates → offset decay, cooldown → wick_offset_analyzer buy prices
- Resistance/bounce → broker_reconciliation → sell targets in daily analyzer
- All 4 composites → watchlist_tournament → weekly ranking

---

## Meaningful Gaps (Ranked by Profit Impact)

### GAP 1: Execution Slippage Not Modeled
**Impact: HIGH (3-5% of gross P/L)**

The backtester assumes perfect fills: buy at exactly limit price, sell at exactly target price. Reality:
- Bid-ask spread costs 0.3-1.5% per trade on our $3-60 stocks
- Limit buys may fill at limit but the "fair" price was higher (you got filled because price was crashing through your level)
- Limit sells may not fill at exact target — price touches target then reverses before your order executes

**What we could simulate**: Add a configurable slippage parameter (e.g., 0.5% adverse on each side). This would give more realistic composite scores and might change which tickers/strategies win.

**Sweep dimension**: `slippage_pct: [0, 0.3, 0.5, 1.0]` — sweep to find which tickers are robust to slippage vs which ones only work with perfect execution.

**Actionability**: MEDIUM — simple to add to backtest_engine (adjust fill price by slippage_pct), but increases combo count by 4×.

---

### GAP 2: Capital Constraints Not Modeled
**Impact: HIGH (2-5% of gross P/L)**

The backtester gives every ticker its own independent $300/$300 pool. In reality, with 24 tickers at $600 each, that's $14.4K — but you don't have $14.4K. When 8 tickers have active positions simultaneously, remaining capital per ticker drops.

**What we could simulate**: Multi-ticker portfolio simulation — simulate ALL tickers together with a shared capital pool. Track deployed capital per day. When pool exhausted, queue entries by priority (highest composite first).

**What this reveals**:
- Optimal number of concurrent positions
- Which tickers to prioritize when capital is scarce
- Whether $600/stock is too much (should be $400 with more tickers) or too little

**Actionability**: HIGH — this is a new simulation type, not a parameter sweep. Build a portfolio-level backtester that runs all tickers simultaneously with shared capital.

---

### GAP 3: Position Sizing Not Optimized Per-Ticker
**Impact: MEDIUM (1-3% of gross P/L)**

Current: every ticker gets $300 active + $300 reserve (or sweep-optimized pools from Stage 2). But the sweep optimizes pool size in isolation — it doesn't know that BBAI ($3.57 avg cost, $114/mo composite) deserves more capital than CLF ($8.82 avg, $19/mo composite).

**What we could simulate**: Allocate capital proportionally to composite score. Higher-composite tickers get larger pools. Simulate the portfolio-level P/L of proportional vs equal allocation.

**What this reveals**:
- Optimal capital allocation across tickers
- Diminishing returns of adding more capital to already-profitable tickers
- Threshold below which a ticker isn't worth the capital

**Actionability**: MEDIUM — requires portfolio-level simulation (same as Gap 2). Could also be a simpler heuristic: `pool = base_pool × (composite / median_composite)`.

---

### GAP 4: Sell Timing Not Optimized (Hold Duration)
**Impact: MEDIUM (1-2% of gross P/L)**

Current: sell when price ≥ avg_cost × (1 + sell_pct). The sell_pct is optimized (6%, 8%, 10% tiers), but we don't optimize **when to take partial profits**.

**What we could simulate**: Trailing stop or time-based profit-taking.
- After N days in profit, lower target from 6% to 4% (take what you can)
- After price reaches 80% of target, place trailing stop at 50% of gains
- Partial exits: sell half at 4%, hold rest for 8%

**What this reveals**:
- Whether holding for full target or taking partial profits produces more $/mo
- Optimal trailing stop distance
- Whether "sell half" beats "sell all"

**Sweep dimension**: `partial_exit_pct: [0 (disabled), 50, 75]`, `partial_exit_trigger: [3, 4, 5]%`, `trailing_stop_pct: [0 (disabled), 2, 3]%`

**Actionability**: HIGH — adds ~27 combos to threshold sweep. Moderate backtest_engine changes (add partial exit logic).

---

### GAP 5: Cross-Ticker Correlation Not Modeled
**Impact: MEDIUM (1-3% during crashes)**

Current: each ticker is simulated independently. But in reality, when crypto crashes, CIFR + CLSK + MARA + HUT + IREN all drop together. All your crypto bullets fill simultaneously, all positions go underwater together.

**What we could simulate**: Sector-correlated drawdown events. When VIX > 30 and sector ETF drops > 5%, penalize all tickers in that sector.

**What this reveals**:
- Maximum portfolio drawdown from sector concentration
- Optimal sector diversification (how many tickers per sector)
- Whether sector exposure limits improve risk-adjusted returns

**Actionability**: LOW-MEDIUM — requires sector tagging (already have `sector_registry.py`) and portfolio-level simulation. Complex but valuable for risk management.

---

### GAP 6: Level Break Cascades Not Modeled
**Impact: MEDIUM (1-2% in volatile periods)**

Current: post_break_cooldown pauses orders for 2-5 days after a level breaks. But it doesn't model the **cascade effect**: when A1 breaks, A2 often breaks within 1-2 days (momentum). The backtester treats each level independently.

**What we could simulate**: Cascade detection — when a level breaks, compute the probability that adjacent levels also break within N days. Skip entries at adjacent levels during cascade.

**Sweep dimension**: `cascade_skip_adjacent: [0 (disabled), 1, 2]` adjacent levels, `cascade_window_days: [1, 2, 3]`

**Actionability**: MEDIUM — ~6 combos, moderate backtest_engine changes (track break events across levels).

---

### GAP 7: No Optimization of WHEN to Enter the Strategy
**Impact: MEDIUM (1-2%)**

Current: the backtester starts simulating from day 1. But real entries happen when the stock pulls back to support — not on any given day. We don't simulate "waiting for the right entry point."

**What we could simulate**: Entry timing optimization — given a ticker, what's the optimal pullback % from recent high before placing the first bullet?

**What this reveals**:
- Should you enter immediately or wait for a 5-10% pullback?
- Does waiting improve cycle efficiency?
- What's the cost of waiting too long (missing the move)?

**Sweep dimension**: `initial_entry_pullback_pct: [0 (immediate), 3, 5, 8, 10]`

**Actionability**: HIGH — simple to add to backtest_engine (skip first N% of pullback before placing orders).

---

### GAP 8: Same-Day Exit P/L Not Accurately Modeled
**Impact: LOW-MEDIUM (0.5-1%)**

Current: backtest uses daily OHLC bars. Same-day exits check if `day_high >= target`, but can't model intraday price path. A stock might hit your buy level at 10:30 AM, bounce 4% by 11:00 AM, then close flat — backtester would miss the intraday opportunity.

**What we could simulate**: Use hourly bars (already available in `intraday_1h_730d.pkl` from data collector) for same-day exit logic. When a fill happens, check hourly bars for intraday exit opportunities.

**Actionability**: MEDIUM — data exists, but switching to hourly bars for exit checks adds complexity and runtime (~4× slower per simulation day).

---

### GAP 9: Earnings Gate Not Wired in Backtester
**Impact: MEDIUM (1-2%)**

Current: `backtest_config.py` has `earnings_gate: bool = False` (line 181), and the strategy document mandates blocking orders 7 days before earnings. But `backtest_engine.py` never checks this flag — all backtested performance includes earnings-week trades that would be blocked in live operation.

**What this means**: Sweep results may overstate P/L by including trades that the live system would skip. Some of these trades are winners (pre-earnings momentum), some are losers (gap-down after earnings). The net effect is unknown but could inflate or deflate composites by 1-2%.

**What we could simulate**: Wire `earnings_gate=True` in backtest_config, add earnings date checking in the fill loop (skip fills within 7 days of earnings). Earnings dates are already collected by `backtest_data_collector.py`.

**Actionability**: HIGH — config field exists, earnings dates exist. Need ~20 lines in backtest_engine to check fill dates against earnings calendar.

---

### GAP 10: Sweeps Use compound=False (Non-Compounding)
**Impact: LOW (context, not a leak)**

All sweep results are computed with `compound: bool = False` (backtest_config.py line 188). This means pools stay at base size ($300/$300) regardless of wins or losses. In live trading, profits can be reinvested (growing pools) or losses can be absorbed.

**What this means**: Sweep composites are **conservative** — they don't capture compounding gains from winning streaks. A ticker with consistent 6% cycles would compound in reality but shows flat $/mo in sweeps. This is acceptable (conservative bias is better than optimistic) but worth noting when comparing sweep predictions to live P/L.

**Actionability**: LOW — could add `compound=True` as a sweep variant, but the current conservative approach is safer against overfitting.

---

## Priority Ranking

| Priority | Gap | Impact | Effort | ROI |
| :--- | :--- | :--- | :--- | :--- |
| **1** | Portfolio-level capital simulation (Gap 2+3) | HIGH | HIGH | Game-changing — answers "how many tickers and how much per ticker" |
| **2** | Sell timing / partial exits (Gap 4) | MEDIUM | MEDIUM | New sweep dimension, moderate engine changes |
| **3** | Execution slippage (Gap 1) | HIGH | LOW | Simple param, reveals which tickers are fragile |
| **4** | Level break cascades (Gap 6) | MEDIUM | MEDIUM | ~6 combos, protects against momentum crashes |
| **5** | Entry timing optimization (Gap 7) | MEDIUM | LOW | ~5 combos, simple pullback gate |
| **6** | Cross-ticker correlation (Gap 5) | MEDIUM | HIGH | Sector risk management, complex sim |
| **7** | Same-day exit accuracy (Gap 8) | LOW | MEDIUM | Better bounce modeling, uses existing hourly data |
| **8** | Earnings gate in backtest (Gap 9) | MEDIUM | LOW | Wire existing config + data, ~20 lines |

---

## Recommendation

**Phase 1 (Next build)**: Gaps 1 + 7 + 9 — Add slippage parameter, entry timing sweep, and earnings gate wiring. All LOW effort (add config params, ~20 lines engine changes each). Slippage reveals which tickers are fragile. Entry timing answers "wait for pullback or enter now?" Earnings gate removes trades that violate live rules from composites.

**Phase 2 (Following build)**: Gap 4 — Sell timing / partial exit sweep. MEDIUM effort (new exit logic in backtest_engine). Changes the fundamental question from "what % to sell at" to "when and how much to sell."

**Phase 3 (Later)**: Gaps 2+5 — Portfolio-level simulation with capital constraints and sector correlation. HIGH effort but game-changing — answers the meta-question "what's the optimal portfolio composition?"
