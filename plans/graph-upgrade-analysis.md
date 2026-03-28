# Graph Upgrade Analysis — What's Real vs What I Made Up

**Date**: 2026-03-28 (Saturday)
**Purpose**: Honest assessment of 8 proposed graph upgrades. For each: what data exists, what's the real benefit, what did I make up.

---

## Summary

| # | Upgrade | Data Exists | Real Benefit | Verdict |
| :--- | :--- | :--- | :--- | :--- |
| 1 | Scenario Simulator | Yes | Marginal — already testable via `_build_fixture_graph()` | **OVERSOLD** |
| 2 | Cross-Run Trends | Yes (trade_history.json) | Marginal — convenience over parsing trade_history | **OVERSOLD** |
| 3 | Portfolio Aggregates | Yes (computable) | No — no strategy rules use sector totals or portfolio-level thresholds | **MADE UP** |
| 4 | Correlation Nodes | Yes (yfinance) | No — strategy buys each stock independently, doesn't hedge correlation | **MADE UP** |
| 5 | Capital Efficiency | Yes (trade_history.json) | Partial — per-ticker ROI is useful for lagger identification, portfolio ROI is vanity | **HALF REAL** |
| 6 | Cooldown Integration | Yes (cooldown.json) | Marginal — already checked in find_deployment_tickers() | **OVERSOLD** |
| 7 | News Sentiment | Yes (news.md per ticker) | No — data is markdown not JSON, sentiment is lagging, strategy doesn't use it | **MADE UP** |
| 8 | Intraday Signals | No infrastructure | No — strategy uses limit orders at pre-calculated prices, not intraday dips | **MADE UP** |

---

## Detailed Assessment

### 1. Scenario Simulator — OVERSOLD

**What I claimed**: "You could ask 'what if CLSK drops 20%' and get the full cascade."

**Reality**: You can already do this:
```python
graph = _build_fixture_graph(live_prices={"CLSK": 7.00})
```
This builds and resolves the entire graph with the hypothetical price. The graph engine already supports this — it's just a function call with different inputs. There's nothing to "build."

**What a graph `simulate()` method would add**: Syntactic sugar. Instead of rebuilding the whole graph, you'd call `graph.simulate({"CLSK:price": 7.00})` and it re-resolves only the affected branch. Saves ~0.3s of computation on a 1.2s resolve cycle.

**Honest benefit**: Near zero. The rebuild is fast enough. The feature sounds impressive but solves a non-problem.

### 2. Cross-Run Trends — OVERSOLD

**What I claimed**: "Detect 'CLSK verdict has been MONITOR for 5 consecutive runs but P/L is trending -2% to -12%.'"

**Reality**: trade_history.json already has every fill and sell with dates, prices, and P/L. To find "CLSK P/L trend over 5 days," you query trade_history — you don't need 5 graph snapshots.

**What trend storage would add**: Slightly easier access to "was regime Risk-Off yesterday?" without parsing trade_history. But graph_state.json is overwritten each run — you'd need to modify the persistence to keep a rolling array.

**Honest benefit**: Convenience for regime/verdict history lookups. Not a new capability — the data already exists in trade_history.json, just in a different format.

### 3. Portfolio Aggregates — MADE UP

**What I claimed**: "Nodes that aggregate across tickers — total_deployed, sector_exposure, catastrophic_count. Would fire signals like 'portfolio-level risk escalation.'"

**Reality**: The strategy (strategy.md) does not have portfolio-level risk rules. Each stock has its own $300-$600 pool, its own support levels, its own entry/exit logic. There is no rule that says "if 3 stocks are in HARD_STOP, pause all buying." I invented that.

**What exists**: You can compute total deployed from portfolio.json (`sum(shares × avg_cost)`). Sector mapping exists in sector_registry.py. But no strategy rule acts on these aggregations.

**Honest benefit**: Zero for trading decisions. Nice for a portfolio dashboard, but the daily analyzer already shows every position with P/L. You can count HARD_STOP tickers by reading the URGENT section.

### 4. Correlation Nodes — MADE UP

**What I claimed**: "If CLSK and CIFR both drop, a correlation node detects 'Crypto sector correlated drawdown.'"

**Reality**: The strategy buys each stock independently at its own wick-adjusted support levels. There is no rule that says "if crypto is correlated, reduce exposure." Correlation is a risk measure for hedged portfolios — this is a momentum/mean-reversion strategy that doesn't hedge.

**What exists**: 3 crypto tickers (CLSK, CIFR, APLD) that likely correlate. But the system already has sector_registry.py for sector awareness, and watchlist fitness already scores sector diversity (10 points). Adding correlation nodes would produce numbers nobody acts on.

**Honest benefit**: Zero for current strategy. Potentially useful if the strategy evolves to include sector-level position limits, but that rule doesn't exist today.

### 5. Capital Efficiency — HALF REAL

**What I claimed**: "Track how much capital is deployed vs how much P/L it has generated."

**Reality check**: Per-ticker capital efficiency IS useful. You already proved this during lagger analysis — AR had zero support cycles, STIM had catastrophic tail risk. The question "is this ticker worth the capital allocated to it?" is a real question with real answers.

**What exists**: trade_history.json has every fill and sell with P/L. pnl_dashboard.py (exists but untested in this session) computes period breakdowns. Multi-period scorer already ranks tickers by simulated P/L per month.

**What's made up**: "Portfolio-wide ROI" is a vanity metric. You care about per-ticker ROI to identify laggers, not aggregate ROI vs a benchmark.

**Honest benefit**: Per-ticker ROI tracking is real and useful — but you already have it via multi-period scorer ($X/mo composite scores). A graph node would duplicate that computation. The real gap is connecting the multi-period results to actionable decisions like "drop this ticker" — which watchlist fitness already does.

### 6. Cooldown Integration — OVERSOLD

**What I claimed**: "When a ticker exits cooldown, a signal fires: 'CIFR cooldown expired — eligible for re-entry.'"

**Reality**: cooldown.json exists with 3 entries. `find_deployment_tickers()` in daily_analyzer.py already checks cooldowns when deciding which tickers to show deployment recommendations for. The graph would add: a node that says "cooldown expired" in the CHANGED section.

**Honest benefit**: Marginal. You'd see "ARM cooldown expired" in the dashboard instead of discovering it when the deployment section runs. Saves you 2 seconds of reading. The logic already exists — the graph just moves the notification earlier in the report.

### 7. News Sentiment — MADE UP

**What I claimed**: "Feed news headlines into a graph node. When sentiment flips, it propagates to verdict/gate decisions."

**Reality**: news.md files exist for each ticker (30 headlines with sentiment scores). But:
- Data is **markdown**, not JSON — requires regex parsing
- Sentiment is a **lagging indicator** — by the time 30 articles are compiled, the move happened
- The strategy has **zero sentiment rules** — entries are purely technical (support levels + wick analysis)
- Adding "sentiment affects verdict" would be inventing a new strategy rule, not implementing an existing one

**Honest benefit**: Zero for current strategy. If you want sentiment-driven decisions, that's a strategy change, not a graph upgrade.

### 8. Intraday Signals — MADE UP

**What I claimed**: "Nodes could fire mid-day: 'CLSK just hit your A1 buy level.'"

**Reality**:
- daily_analyzer.py fetches `period="5d"` — daily candles, not intraday
- No intraday infrastructure exists in the codebase
- The strategy uses **limit orders** placed at pre-calculated prices — the broker handles execution, not the system
- If a limit order at $8.40 fills, you find out from the broker notification, not from polling yfinance

**Honest benefit**: Zero. Limit orders fill automatically. Polling for "did it fill?" adds complexity without value. The fill recording happens when you report it via `--fills`.

---

## What Would Actually Help

Based on this analysis, the upgrades that have REAL data AND match the CURRENT strategy are:

1. **Per-ticker ROI comparison** (Upgrade 5, narrowed) — but multi-period scorer already does this. The gap is displaying it in the dashboard alongside verdicts: "CLSK: MONITOR, $18.7/mo composite, 5 cycles." This is a display change, not a graph change.

2. **Regime persistence** (Upgrade 2, narrowed) — "Risk-Off for 3 consecutive days" is more useful than just "Risk-Off today." This requires keeping the last 3-5 regime values. Small change to graph_state.json.

3. **Catastrophic count as dashboard metric** — not a graph node, just a line in the dashboard: "2 of 16 positions in HARD_STOP (12.5% of portfolio)." This is 2 lines of code in `print_action_dashboard_from_signals()`, not a graph upgrade.

None of these require new graph nodes. They're display improvements using data the graph already computes.

---

## Conclusion

Of the 8 upgrades I proposed:
- **0 are clear wins** that justify the analysis→plan→implement→verify cycle
- **2 are half-real** (capital efficiency, regime persistence) but already partially covered by existing tools
- **6 are made up** — they sound good but either the data doesn't exist, the strategy doesn't use them, or the benefit is marginal

The honest next step is not "build more graph features" but "use the graph you built to make better daily decisions." The graph is complete for the strategy as it exists today. New graph features should come when the strategy evolves to need them — not because the architecture can support them.
