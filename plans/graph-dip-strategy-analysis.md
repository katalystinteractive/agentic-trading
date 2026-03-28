# Analysis: Can the Graph Enhance Daily Dip Per-Ticker Decisions?

**Date**: 2026-03-29 (Sunday)
**Purpose**: Determine if graph-based context would improve the per-ticker go/no-go decision for daily dip trades.

---

## 1. How the Dip Decision Currently Works

The daily dip strategy runs in two stages:

**Stage 1 — Watchlist (in daily_analyzer.py, pre-market):**
- Fetches 1-month daily OHLC per ticker
- Computes: median daily range, dip frequency, recovery rate at 2%/3%
- Filters: range ≥ 3%, recovery ≥ 60%
- Applies earnings gate (blocks tickers within 7-day pre-earnings)
- Outputs: per-ticker buy/sell/stop prices for the day

**Stage 2 — Signal confirmation (dip_signal_checker.py, ~10:30 AM ET):**
- Fetches 5-minute intraday bars
- Step 1: first-hour breadth — did ≥50% of tickers dip >1% from open?
- Step 2: second-hour bounce — did ≥50% bounce >0.3%?
- If both pass: rank dippers by size, pick top 5, recommend BUY
- Per-ticker entry: buy at current price, sell at +4%, stop at -3%, cut at EOD

**Parameters (backtested and optimized):**
- Budget: $100 per ticker, $500 daily cap
- Sell target: +4% (optimized from 3% via backtest sweep)
- Stop loss: -3%
- Max hold: 1 day (same-day exit)
- Top N: 5 per signal
- PDT limit: 3 day trades per 5-day window at <$25K

---

## 2. What Context the Decision Currently Uses

| Context | Used? | How |
| :--- | :--- | :--- |
| Historical range/dip/recovery | YES | 1-month OHLC metrics per ticker |
| Earnings proximity | YES | earnings_gate blocks tickers <7 days from earnings |
| Market breadth (cross-ticker) | YES | 50% breadth + 50% bounce confirmation |
| Market regime (VIX) | PARTIAL | Risk-Off WARNING printed, but no automatic sizing adjustment |
| PDT count | YES | Checked against 3/5-day limit |
| Current price | YES | Buy at current after signal confirmation |

## 3. What Context the Decision Does NOT Use

| Missing Context | Available in Graph? | Currently Available Elsewhere? |
| :--- | :--- | :--- |
| Catastrophic drawdown flag for ticker | YES — `{tk}:catastrophic` node | YES — dashboard URGENT section, but dip code doesn't read it |
| Regime from graph (vs hardcoded VIX check) | YES — `regime` node | YES — print_market_regime() returns it, but dip function has its own VIX check |
| Active bullet orders pending for same ticker | NO graph node | YES — portfolio.json pending_orders |
| Sector overlap with other dip picks today | NO graph node | YES — sector_registry.py |
| Available capital (dry powder) | NO graph node | YES — computable from portfolio.json |
| Ticker's verdict (MONITOR/EXIT/REVIEW) | YES — `{tk}:verdict` node | Only in graph, not in dip code |

---

## 4. The 6 Potential Improvements — Honest Assessment

### 4.1 Catastrophic Drawdown Block — REAL VALUE

**Current behavior**: The dip strategy will recommend buying a dip on IONQ even though IONQ is at -38.1% HARD_STOP in the main strategy. The daily analyzer prints the dip watchlist with IONQ eligible (range 6.2%, recovery 100%).

**What the graph provides**: `{tk}:catastrophic` node = "HARD_STOP"

**Would it change the decision?** YES. You should not buy a same-day dip on a stock that your main strategy says "pause all buying." If the stock is in free-fall (-38%), a 1% dip-buy hoping for a 4% bounce is fighting the trend.

**Is the graph needed?** NO. This check is simpler than a graph node:
```python
paused = {tk for tk, p in positions.items()
          if p.get("shares", 0) > 0
          and (live_prices.get(tk, 0) - p["avg_cost"]) / p["avg_cost"] < -0.25}
```
Pure arithmetic. No graph required. But the graph ALREADY computes this — reading `{tk}:catastrophic` is one dict lookup vs recomputing from scratch.

**Verdict**: REAL VALUE. Graph provides it at zero cost (already computed). Simple integration.

### 4.2 Regime-Based Position Sizing — MARGINAL VALUE

**Current behavior**: Prints "WARNING: Risk-Off regime — dips are likely to keep dipping. Daily plays are HIGH RISK today." But doesn't actually change the $100 budget or skip entries.

**What the graph provides**: `regime` node = "Risk-Off"

**Would it change the decision?** PARTIALLY. The WARNING is already printed. The user can manually skip. Automating half-sizing during Risk-Off would enforce discipline, but it's a parameter change ($100 → $50), not a structural decision change.

**Is the graph needed?** NO. The dip watchlist function already receives `regime` as a parameter. It just doesn't act on it beyond printing a warning.

**Verdict**: MARGINAL. The regime is already available. The gap is a missing if-statement, not missing data.

### 4.3 Verdict-Aware Filtering — REAL VALUE

**Current behavior**: Dip strategy recommends buys on ALL eligible tickers regardless of what the main strategy's verdict says. A ticker with verdict "EXIT" (R11: exceeded time + bearish momentum) could show up as a dip pick.

**What the graph provides**: `{tk}:verdict` node = ("EXIT", "R11", "...")

**Would it change the decision?** YES. If the main strategy says EXIT this position, buying a same-day dip on it contradicts the portfolio thesis. You're adding exposure to a ticker you're trying to exit.

**Is the graph needed?** YES — this is where the graph adds real value. The verdict computation requires avg_cost, price, days_held, earnings_gate, momentum, and regime — all already wired in the graph. Recomputing this inside the dip function would duplicate the entire verdict engine. Reading `{tk}:verdict` from the graph is the right approach.

**Verdict**: REAL VALUE. Graph is the correct source — avoids duplicating verdict computation.

### 4.4 Pending Bullet Conflict Detection — MARGINAL VALUE

**Current behavior**: Dip strategy doesn't know if the same ticker has active support-level buy orders pending. If CLSK has a limit buy at $8.40 (A1 bullet) and the dip strategy recommends buying CLSK at $8.66 (1% below open), both could fill on the same day.

**What the graph provides**: `{tk}:recon` node contains pending buy orders.

**Would it change the decision?** MARGINALLY. The dip trade and the bullet fill are independent strategies. The dip exits same-day at +4%. The bullet is a multi-week hold. They use different capital pools. Having both fill is inconvenient for capital management but not contradictory.

**Is the graph needed?** NO. Portfolio.json pending_orders is sufficient. And the strategies are designed to be independent.

**Verdict**: MARGINAL. Not a conflict — different strategies, different capital, different time horizons.

### 4.5 Sector Overlap Among Dip Picks — MARGINAL VALUE

**Current behavior**: If dip signal fires, top 5 dippers are recommended regardless of sector. Could recommend 3 crypto tickers on the same day.

**What the graph provides**: No sector node exists for dip picks (they're from the watchlist, not the graph's active tickers).

**Would it change the decision?** MARGINALLY. Same-day trades exit by EOD. Sector concentration risk is a multi-day portfolio concern, not a same-day concern. If all 3 crypto stocks dip and bounce, buying all 3 is fine — you exit all 3 by close.

**Is the graph needed?** NO. And the risk is minimal for same-day trades.

**Verdict**: NOT VALUABLE for same-day trades. Sector concentration matters for multi-day positions, not intraday.

### 4.6 Capital Availability Gate — MARGINAL VALUE

**Current behavior**: Assumes $100/ticker, $500/day is always available. No check against actual dry powder.

**Would it change the decision?** RARELY. The dip budget ($500/day) is small relative to the total portfolio ($10K+). It's unlikely the user lacks $500 in cash.

**Is the graph needed?** NO. Simple check against portfolio.json capital section.

**Verdict**: MARGINAL. Edge case that almost never triggers.

---

## 5. Summary: What the Graph Actually Improves

| Improvement | Real Value? | Graph Needed? | Effort |
| :--- | :--- | :--- | :--- |
| 4.1 Catastrophic block | **YES** — don't dip-buy HARD_STOP tickers | NO (arithmetic) but graph has it for free | 5 lines |
| 4.2 Regime sizing | MARGINAL — warning already shown | NO — regime already passed as param | 3 lines |
| 4.3 Verdict filtering | **YES** — don't dip-buy EXIT tickers | **YES** — avoids duplicating verdict engine | 10 lines |
| 4.4 Bullet conflict | MARGINAL — independent strategies | NO — portfolio.json sufficient | N/A |
| 4.5 Sector overlap | NOT VALUABLE — same-day trades | NO | N/A |
| 4.6 Capital gate | MARGINAL — edge case | NO | N/A |

**Two improvements are genuinely valuable:**

1. **Don't dip-buy HARD_STOP tickers** (4.1) — uses `{tk}:catastrophic` from graph
2. **Don't dip-buy EXIT/REVIEW tickers** (4.3) — uses `{tk}:verdict` from graph

Both prevent the dip strategy from buying tickers that the main strategy has flagged for exit or review. This is not a new gate — it's using the graph's existing per-ticker decisions to prevent contradictory trades.

---

## 6. What the Implementation Would Look Like

In `print_daily_fluctuation_watchlist()` (daily_analyzer.py), after the earnings gate check, add:

```python
# Read graph nodes if available
if graph is not None:
    cat = graph.nodes.get(f"{tk}:catastrophic")
    if cat and cat.value in ("HARD_STOP", "EXIT_REVIEW"):
        # Skip — main strategy says pause all buying
        continue

    verdict = graph.nodes.get(f"{tk}:verdict")
    if verdict and isinstance(verdict.value, tuple) and verdict.value[0] in ("EXIT", "REDUCE"):
        # Skip — main strategy says exit this position
        continue
```

This is ~10 lines in the existing function. It reads 2 graph nodes per ticker. No new graph infrastructure needed.

**The dip watchlist output changes**: Tickers blocked by verdict/catastrophic show with a note explaining why:

```
| ~~IONQ~~ | — | — | — | — | — | — | HARD_STOP (-38.1%) |
| ~~USAR~~ | — | — | — | — | — | — | VERDICT: EXIT (R11) |
```

---

## 7. Conclusion

The graph CAN improve the daily dip per-ticker decision, but only in 2 specific ways:
1. Block dip-buys on catastrophic drawdown tickers (already computed by graph)
2. Block dip-buys on EXIT/REDUCE verdict tickers (already computed by graph)

Both are simple reads from existing graph nodes — no new nodes, no new edges, no new architecture. The value is preventing contradictory trades where one strategy says "buy the dip" and the other says "stop buying."

The other 4 potential improvements (regime sizing, bullet conflict, sector overlap, capital gate) are either already handled, not applicable to same-day trades, or marginal edge cases.
