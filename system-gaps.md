# System Gap Analysis — Agentic Trading Harness
*Created: 2026-03-15 | Status: Living document*

---

## Area 1: Ticker Selection (Surgical Screening)

### What Exists
- `surgical_filter.py` — scores tickers on swing, support density, hold rates, recency, dead zones
- `surgical-candidate-workflow` — 3-phase screen→verify→critic pipeline
- Implicit thresholds (30%+ swing, 3+ active levels, etc.)

### Gaps

| # | Gap | Impact | Effort | Priority |
| :--- | :--- | :--- | :--- | :--- |
| 1.1 | **No backtested success metric.** We score tickers on support quality but never simulate: "Would this ticker have been profitable with our exact strategy over 13 months?" A ticker could score 95 on screening metrics and still lose money due to timing, gap-downs, or regime shifts. | High | High | P2 |
| 1.2 | **No post-onboard performance tracking vs screening score.** CLSK scored 98 and delivered 4/4 cycles. Was that because of the score? We have no correlation model between screening factors and actual cycling profitability. After 30+ completed cycles we could identify which screening factors actually predict success. | High | Medium | P2 |
| 1.3 | **No formal KPI card.** Screening thresholds evolved organically. No single document defines the exact pass/fail criteria with rationale for each threshold. Makes it hard to tune or explain why a ticker was rejected. | Medium | Low | P3 |
| 1.4 | **Narrow ticker universe (~149).** We only screen tickers from a predefined list. Could pre-filter a larger universe (3000+ US equities) using Finviz/TradingView screeners by volatility, avg volume, price range, then run wick analysis only on survivors. | Medium | Medium | P3 |
| 1.5 | **No sector-rotation awareness.** Screening doesn't consider which sectors are currently cycling well vs stuck. Adding a "sector momentum" factor could steer new onboards toward sectors with active mean-reversion patterns. | Low | Medium | P4 |

---

## Area 2: First Entry Timing

### What Exists
- `wick_offset_analyzer.py` — data-driven buy-at prices from historical wick penetration
- `cycle-timing-workflow` — analyzes resistance-to-support cycle duration
- `market-context-workflow` — regime awareness (risk-on/off)
- Manual cooldown evaluation post-sell

### Gaps

| # | Gap | Impact | Effort | Priority |
| :--- | :--- | :--- | :--- | :--- |
| 2.1 | **No cycle phase detection.** Each ticker has a rhythm (resistance→pullback→support→bounce→resistance). We don't detect where a ticker is in its cycle. Placing B1 while price is falling toward it is high-probability. Placing B1 after price just bounced off support means it sits for days. | High | Medium | P1 |
| 2.2 | **No "probability of fill in next N days" per order.** B1 at 3% below price has ~60% weekly fill probability. B4 at 15% below has ~5%. We treat all orders equally. This metric would feed into capital allocation (gap 5.2). | High | Medium | P1 |
| 2.3 | **No velocity/momentum filter.** A stock dropping 3%/day toward B1 is likely to overshoot and cascade to B2-B3. A stock drifting 0.3%/day is more likely to hold at B1. Entry timing should account for approach speed. | Medium | Medium | P2 |
| 2.4 | **Cooldown evaluation is manual.** We hand-analyzed CLSK/RUN/OUST/TMC cooldown status. The system should auto-track post-sell decay daily and alert at threshold (e.g., -5% from sell = re-entry ready, 0% or positive = extend cooldown). | Medium | Low | P2 |
| 2.5 | **No "distance to first fill" dashboard.** A single view showing all tickers sorted by how close current price is to B1, with estimated days to fill. This tells the user which tickers are about to cycle and which are dormant. | Medium | Low | P2 |

---

## Area 3: Active Buy Level & Sizing Optimization

### What Exists
- `wick_offset_analyzer.py` — identifies support levels with hold rates from 13-month data
- `compute_pool_sizing()` — equal-impact distribution of $300 across levels
- Tier system (Full/Std/Half/Skip) weights allocation by confidence
- Level merging for nearby supports

### Gaps

| # | Gap | Impact | Effort | Priority |
| :--- | :--- | :--- | :--- | :--- |
| 3.1 | **No pullback depth profiling.** We know monthly swing (e.g., 43.8%) but don't profile typical pullback depth distribution. "80% of CLSK pullbacks reach B1, 45% reach B2, 15% reach B3, 5% reach B4." This determines how many bullets are useful vs dead capital. | High | Medium | P1 |
| 3.2 | **No optimal bullet count per ticker.** System uses ALL qualifying levels (up to 5 active). But maybe 3 concentrated bullets outperform 5 spread-thin bullets for a given ticker's pullback pattern. Optimal count depends on pullback depth distribution (3.1). | High | Medium | P1 |
| 3.3 | **No averaging efficiency metric.** After each cycle, we should measure: "What was the actual cost basis improvement from multi-level fills? Did B2-B5 actually improve the avg enough to matter, or did B1 fill and price bounced?" If B1 alone drives most cycles, deeper bullets are waste. | Medium | Low | P2 |
| 3.4 | **Level spacing isn't optimized.** Levels come from wherever PA/HVN happen to be. The optimal spacing might be different — e.g., "B1 at -3%, B2 at -7%, B3 at -12%." Wick data could inform optimal spacing per ticker based on actual price behavior. | Medium | Medium | P3 |
| 3.5 | **No simulation of alternative sizing strategies.** Current equal-impact model is untested against alternatives: pyramid-down (more shares at deeper levels), inverse-pyramid (more shares at shallow levels), or Kelly-criterion-based sizing. | Medium | High | P3 |

---

## Area 4: Reserve Level & Sizing Optimization

### What Exists
- $300 reserve pool, up to 3 bullets
- Reserve levels from wick analysis beyond active zone
- Exit review workflow flags positions for HOLD/REDUCE/EXIT

### Gaps

| # | Gap | Impact | Effort | Priority |
| :--- | :--- | :--- | :--- | :--- |
| 4.1 | **Reserve utilization rate unknown.** Many reserve levels haven't been tested since mid-2025. What % of reserve capital actually fills per quarter? If it's <5%, that's $300/ticker × 20 tickers = $6,000 sitting idle. | Medium | Low | P2 |
| 4.2 | **No conditional reserve deployment.** Reserves are set-and-forget. In a confirmed sector decline, reserves should be held back (expecting further drop). In a flash crash, they should fire. Market context doesn't feed into reserve activation. | Medium | Medium | P3 |
| 4.3 | **Reserve sizing ignores active position size.** 3 reserve shares at $7 improve a 5-share $10 avg position by 11.3%. The same 3 reserve shares improve a 20-share $10 avg position by only 3.9%. Reserve sizing should scale with how many active shares are deployed. | Medium | Medium | P3 |
| 4.4 | **No "deep dive vs cut losses" threshold.** At what pullback % does adding reserves stop being rational? If reserves deploy at -25% and the stock needs to recover +33% to break even, the expected time to recover may exceed the opportunity cost of redeploying that capital. Ties to area 6. | High | Medium | P2 |
| 4.5 | **No reserve-to-active promotion.** When a ticker's price drops significantly, what were active levels become above current price (useless) and reserve levels become the real active zone. The system doesn't automatically re-classify and re-optimize for the new price reality. | Low | Medium | P4 |

---

## Area 5: Bullet Loading Timing (Capital Efficiency)

### What Exists
- Limit orders placed at onboarding and left open
- Morning briefing flags approaching fills
- Market context workflow provides regime gate per order

### Gaps

| # | Gap | Impact | Effort | Priority |
| :--- | :--- | :--- | :--- | :--- |
| 5.1 | **No opportunity cost calculation.** 20 tickers × 5 bullets = ~$6,000 active capital in open orders. Most won't fill for weeks. That capital could be earning returns in active cycling tickers instead. We don't measure the cost of idle capital. | High | Medium | P1 |
| 5.2 | **No cross-portfolio capital optimization.** "CLSK B1 has 70% fill probability this week. OUST B4 has 2%. Reallocate OUST B4 capital to a second CLSK cycling slot." We optimize per-ticker but not across the portfolio. | High | High | P2 |
| 5.3 | **No staged deployment.** We place all 5 bullets at once. Alternative: place B1-B2 now, keep B3-B5 as planned-but-unplaced. When B2 fills, place B3. This keeps capital available for other opportunities. | High | Low | P1 |
| 5.4 | **No capital velocity metric.** How fast does each dollar cycle through trades? "Average dollar deployed earns 6% every X days." Faster velocity = higher annualized return. Currently unmeasured. | High | Medium | P1 |
| 5.5 | **No fill probability model.** We don't estimate how likely each pending order is to fill in the next 1/3/5/10 days. This requires analyzing: distance to current price, approach velocity, historical fill frequency at that level, regime context. | High | Medium | P1 |
| 5.6 | **No "stale order" alerting.** Orders that have sat unfilled for 14+ days without price approaching should be flagged for review. The capital may be better deployed elsewhere. | Medium | Low | P2 |

---

## Area 6: Loss Recognition & Capital Redeployment

### What Exists
- `exit-review-workflow` — 18-point verdict ruleset (HOLD/REDUCE/EXIT)
- Manual review of underwater positions
- No formal redeployment framework

### Gaps

| # | Gap | Impact | Effort | Priority |
| :--- | :--- | :--- | :--- | :--- |
| 6.1 | **No break-even time estimate.** "At -9.9% with current bounce rate from this level, estimated time to break even: 12 days." vs "Sell at loss, redeploy to CLSK, expected to recover loss in 5 days." The comparison is missing. | High | Medium | P1 |
| 6.2 | **No formal abandon-position criteria.** What makes a position unrecoverable? Needs explicit rules: (a) all active support levels broke in last 30 days, (b) capital trapped >30 days without cycling, (c) fundamental thesis invalidated, (d) opportunity cost exceeds recovery potential. | High | Medium | P1 |
| 6.3 | **No redeployment ROI calculator.** "Selling CLF at -9.9% loss = -$43.71. Redeploying $397 to LUNR (5-day avg cycle, 6% avg profit) = +$23.82 in 5 days. Net recovery: 8 days." This makes cut-loss decisions quantitative, not emotional. | High | Medium | P1 |
| 6.4 | **No "capital trap" alerting.** Positions that have been underwater for >14 days with no fill activity and no approaching support should be auto-flagged. Currently requires manual exit review workflow trigger. | Medium | Low | P2 |
| 6.5 | **No partial exit optimization.** When cutting losses, it might be optimal to sell half (freeing capital for redeployment) while keeping half (in case of recovery). The system doesn't model partial exits. | Low | Medium | P4 |

---

## Area 7: P/L Tracking & Performance Analytics

### What Exists
- `portfolio_status.py` — current unrealized P/L per position
- Per-ticker `memory.md` with trade log entries
- `trade_history.json` (exists but not systematically maintained)
- No aggregation, no dashboard

### Gaps

| # | Gap | Impact | Effort | Priority |
| :--- | :--- | :--- | :--- | :--- |
| 7.1 | **No aggregated P/L dashboard.** Cannot answer: "Total realized profit since inception? This month? This week?" without manually reading 20 memory.md files. | High | Low | P1 |
| 7.2 | **No cycle-level analytics.** Need: total cycles completed, win rate, avg profit/cycle, avg cycle duration, best/worst ticker, capital utilization rate. This is the scorecard for the entire system. | High | Medium | P1 |
| 7.3 | **No benchmark comparison.** SPY/QQQ YTD return vs our strategy YTD return. Alpha = our return - benchmark. Without this we don't know if the strategy is beating buy-and-hold. | Medium | Low | P2 |
| 7.4 | **No capital utilization metric.** "Average capital deployed: $4,200 of $12,000 available (35%). Idle capital: $7,800." Tells us if we're under-deployed and how much room we have to scale. | Medium | Low | P2 |
| 7.5 | **No per-ticker profitability ranking.** "CLSK: 4 cycles, $8.19 profit, 2.1-day avg cycle, $300 pool = 65% annualized. USAR: 0 cycles, -$97 unrealized, 45 days stuck = -32% annualized." This determines which tickers to keep and which to drop. | High | Medium | P1 |
| 7.6 | **No trade history normalization.** Trade data lives in narrative memory.md files (unstructured text). Needs to be in structured format (JSON/CSV) with: ticker, entry_date, entry_price, shares, exit_date, exit_price, profit_pct, cycle_days. | Medium | Medium | P2 |
| 7.7 | **No drawdown tracking.** Maximum drawdown from peak portfolio value. Worst single-position drawdown. Risk-adjusted return (Sharpe-like ratio for our strategy). | Medium | Medium | P3 |

---

## Area 8: Dynamic Sell Targets & Post-Sell Tracking

### What Exists
- `sell_target_calculator.py` — finds resistance levels in 4.5%-7.5% profit zone
- PA + HVN rejection data for sell price selection
- Tranche splitting logic for multi-level sells
- No post-sell tracking

### Gaps

| # | Gap | Impact | Effort | Priority |
| :--- | :--- | :--- | :--- | :--- |
| 8.1 | **No post-sell continuation tracking.** When we sell at $10.24, we don't track that CLSK went to $10.80 afterwards. Over 50 cycles, this data shows: "Our sells average X% below subsequent peak. Raising targets by Y% would capture $Z more." | High | Low | P1 |
| 8.2 | **No adaptive sell targets.** If a ticker consistently blows through our sell level and runs 3-4% higher, next cycle should use a higher target. If it consistently reverses before our sell, lower it. Currently static. | High | Medium | P1 |
| 8.3 | **No split-sell optimization model.** When to sell all-at-once vs split? Needs: "Historical post-sell continuation says this ticker runs X% past T1 resistance Y% of the time. Optimal: sell 60% at T1, trail 40% to T2. EV gain: $Z." | Medium | Medium | P2 |
| 8.4 | **No trailing stop logic.** For positions that run well past the sell target, a trailing stop would capture more upside. Example: "CLSK at +8% and still rising. Set trailing stop at +6% (lock in gains, let it run)." Currently we use fixed limit sells. | Medium | Medium | P3 |
| 8.5 | **No resistance-level freshness check on sell.** Sell targets are set at position entry and not re-evaluated. If new resistance forms closer to current price (from recent price action), the sell target should update. The `sell_target_calculator.py` uses live data but isn't re-run automatically as conditions change. | Low | Low | P3 |

---

## Area 9: Optimal Profit Target % (The Core Unsolved Question)

### What Exists
- Fixed 4.5%/6.0%/7.5% target tiers
- Typically aim for 6% (Standard)
- No frequency analysis, no per-ticker optimization, no simulation

### Gaps

| # | Gap | Impact | Effort | Priority |
| :--- | :--- | :--- | :--- | :--- |
| 9.1 | **No cycle frequency analysis by target %.** The fundamental question: at 3% target, how many cycles/month? At 6%? At 8%? Total profit = frequency × profit_per_cycle. The optimal % maximizes this product. Currently guessing at 6%. | **Critical** | Medium | **P0** |
| 9.2 | **No per-ticker optimal target.** CLSK cycles in 2-3 days — maybe optimal at 4%. OUST has 56% monthly swing — maybe optimal at 8%. LUNR has -8.7% next-day decay — maybe optimal at 3%. One-size-fits-all 6% is almost certainly suboptimal. | **Critical** | Medium | **P0** |
| 9.3 | **No historical backtesting of target %s.** We have 13 months of OHLC data per ticker. Could simulate our exact strategy at each target (2% through 10% in 0.5% steps) and find the profit-maximizing target per ticker. | **Critical** | Medium | **P0** |
| 9.4 | **No frequency-magnitude tradeoff visualization.** A chart per ticker showing: X-axis = target %, Y-axis = total profit over 13 months. The peak of this curve is the optimal target. Would also show: cycle count, avg cycle duration, win rate at each target %. | High | Low | P1 |
| 9.5 | **No regime-adaptive targets.** High-VIX months have wider swings — higher targets are achievable and fill faster. Low-VIX months favor lower targets. The optimal target should shift with market conditions. | Medium | Medium | P2 |
| 9.6 | **No compound effect modeling.** At 3% target cycling every 3 days vs 6% every 6 days, the 3% compounds faster (reinvesting profits sooner). Over 12 months, compounding differences can be 15-20% of total return. The simulation (9.3) must account for this. | High | Medium | P1 |

---

## Summary: All Gaps by Priority

### P0 — Critical (Build First)
| # | Gap | Area | Effort |
| :--- | :--- | :--- | :--- |
| 9.1 | Cycle frequency analysis by target % | Profit Target | Medium |
| 9.2 | Per-ticker optimal target % | Profit Target | Medium |
| 9.3 | Historical backtesting of target %s | Profit Target | Medium |

### P1 — High Impact (Build Next)
| # | Gap | Area | Effort |
| :--- | :--- | :--- | :--- |
| 7.1 | Aggregated P/L dashboard | P/L Tracking | Low |
| 7.2 | Cycle-level analytics | P/L Tracking | Medium |
| 7.5 | Per-ticker profitability ranking | P/L Tracking | Medium |
| 8.1 | Post-sell continuation tracking | Sell Targets | Low |
| 8.2 | Adaptive sell targets | Sell Targets | Medium |
| 5.1 | Opportunity cost calculation | Capital Efficiency | Medium |
| 5.3 | Staged bullet deployment | Capital Efficiency | Low |
| 5.4 | Capital velocity metric | Capital Efficiency | Medium |
| 5.5 | Fill probability model | Capital Efficiency | Medium |
| 2.1 | Cycle phase detection | Entry Timing | Medium |
| 2.2 | Fill probability per order | Entry Timing | Medium |
| 3.1 | Pullback depth profiling | Active Levels | Medium |
| 3.2 | Optimal bullet count per ticker | Active Levels | Medium |
| 6.1 | Break-even time estimate | Loss Recognition | Medium |
| 6.2 | Formal abandon-position criteria | Loss Recognition | Medium |
| 6.3 | Redeployment ROI calculator | Loss Recognition | Medium |
| 9.4 | Frequency-magnitude tradeoff visualization | Profit Target | Low |
| 9.6 | Compound effect modeling | Profit Target | Medium |

### P2 — Medium Impact
| # | Gap | Area | Effort |
| :--- | :--- | :--- | :--- |
| 1.1 | Backtested success metric for screening | Ticker Selection | High |
| 1.2 | Post-onboard performance vs score tracking | Ticker Selection | Medium |
| 2.3 | Velocity/momentum filter | Entry Timing | Medium |
| 2.4 | Automated cooldown evaluation | Entry Timing | Low |
| 2.5 | Distance-to-first-fill dashboard | Entry Timing | Low |
| 3.3 | Averaging efficiency metric | Active Levels | Low |
| 4.1 | Reserve utilization rate | Reserve Levels | Low |
| 4.4 | Deep dive vs cut losses threshold | Reserve Levels | Medium |
| 5.2 | Cross-portfolio capital optimization | Capital Efficiency | High |
| 5.6 | Stale order alerting | Capital Efficiency | Low |
| 6.4 | Capital trap alerting | Loss Recognition | Low |
| 7.3 | Benchmark comparison (SPY/QQQ) | P/L Tracking | Low |
| 7.4 | Capital utilization metric | P/L Tracking | Low |
| 7.6 | Trade history normalization (structured JSON) | P/L Tracking | Medium |
| 8.3 | Split-sell optimization model | Sell Targets | Medium |
| 9.5 | Regime-adaptive targets | Profit Target | Medium |

### P3 — Lower Impact
| # | Gap | Area | Effort |
| :--- | :--- | :--- | :--- |
| 1.3 | Formal KPI card for screening | Ticker Selection | Low |
| 1.4 | Wider ticker universe | Ticker Selection | Medium |
| 3.4 | Level spacing optimization | Active Levels | Medium |
| 3.5 | Alternative sizing strategy simulation | Active Levels | High |
| 4.2 | Conditional reserve deployment | Reserve Levels | Medium |
| 4.3 | Reserve sizing scaled to active position | Reserve Levels | Medium |
| 7.7 | Drawdown tracking | P/L Tracking | Medium |
| 8.4 | Trailing stop logic | Sell Targets | Medium |
| 8.5 | Resistance freshness check on sell | Sell Targets | Low |

### P4 — Future
| # | Gap | Area | Effort |
| :--- | :--- | :--- | :--- |
| 1.5 | Sector rotation awareness | Ticker Selection | Medium |
| 4.5 | Reserve-to-active promotion | Reserve Levels | Medium |
| 6.5 | Partial exit optimization | Loss Recognition | Medium |

---

## Proposed Build Order

### Phase 1: Foundation (Measure what we have)
**Goal:** Know how the system is actually performing before optimizing it.
1. **7.6** — Normalize trade history into structured JSON (all memory.md → trade_history.json)
2. **7.1 + 7.2 + 7.5** — P/L dashboard with cycle analytics and per-ticker ranking
3. **8.1** — Post-sell continuation tracking (add to sell flow, start collecting data)
4. **7.3 + 7.4** — Benchmark comparison and capital utilization metrics

**Deliverable:** `python3 tools/pnl_dashboard.py` — single command gives full performance picture.

### Phase 2: Core Optimizer (Answer the biggest question)
**Goal:** Find the optimal profit target % per ticker.
1. **9.3** — Backtesting engine: simulate strategy at 2%-10% targets per ticker using 13-month OHLC
2. **9.1 + 9.2** — Cycle frequency analysis output per ticker
3. **9.4** — Frequency-magnitude tradeoff curve visualization
4. **9.6** — Compound effect modeling in the simulation

**Deliverable:** `python3 tools/target_optimizer.py CLSK` — outputs optimal target % and expected annual return.

### Phase 3: Capital Intelligence (Deploy smarter)
**Goal:** Get capital cycling faster with less idle time.
1. **5.5 + 2.2** — Fill probability model per order
2. **5.4** — Capital velocity metric
3. **5.3** — Staged deployment rules
4. **2.1** — Cycle phase detection per ticker
5. **2.5** — Distance-to-first-fill dashboard
6. **5.1** — Opportunity cost calculation

**Deliverable:** Morning briefing enriched with fill probabilities and capital deployment recommendations.

### Phase 4: Active Optimization (Fine-tune the strategy)
**Goal:** Optimize bullet placement and loss management.
1. **3.1** — Pullback depth profiling per ticker
2. **3.2** — Optimal bullet count per ticker (using 3.1 data)
3. **8.2** — Adaptive sell targets (using 8.1 data collected in Phase 1)
4. **6.1 + 6.2 + 6.3** — Loss recognition framework with break-even calculator
5. **2.4** — Automated cooldown evaluation

**Deliverable:** Per-ticker strategy profile: optimal bullet count, level spacing, sell target, abandon threshold.

### Phase 5: Full System (Backtested screening + portfolio optimization)
**Goal:** Close the loop — screening predicts profitability, portfolio is globally optimized.
1. **1.1** — Backtested screening using Phase 2 engine
2. **1.2** — Screening score vs actual performance correlation
3. **5.2** — Cross-portfolio capital optimization
4. **4.4 + 4.2** — Reserve deployment thresholds and conditional activation
5. **9.5** — Regime-adaptive targets

**Deliverable:** Fully autonomous system that screens, deploys, times, and exits with minimal manual intervention.

---

## Success Metrics (How We Know It's Working)

| Metric | Current (Estimated) | Phase 1 Target | Phase 5 Target |
| :--- | :--- | :--- | :--- |
| Cycles completed/month | ~8-12 | Measured accurately | 20+ |
| Win rate | ~90% (estimated) | Measured accurately | 95%+ |
| Avg profit/cycle | ~6% (fixed target) | Measured accurately | Optimized per-ticker |
| Avg cycle duration | ~4 days (estimated) | Measured accurately | <3 days |
| Capital utilization | ~35% (estimated) | Measured accurately | 70%+ |
| Capital velocity | Unknown | Measured | 2x current |
| Monthly realized profit | Unknown | Measured | 2-3x current |
| Annualized return | Unknown | Measured | 40%+ |
| Post-sell money left on table | Unknown | Measured | <1.5% avg |
| Abandoned position losses/quarter | Unknown | Measured | <2% of capital |
