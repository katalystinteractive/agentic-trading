# Analysis: Neural Graph Architecture — Event-Driven Decision Network

**Date**: 2026-03-29 (Sunday)
**Purpose**: Define a neural firing network where nodes (neurons) are dormant until their specific condition is met, then fire signals through synapses to other neurons, cascading toward a terminal BUY or NO_ACTION decision.

---

## 1. What This Is vs What We Built

### Current graph (snapshot model):
- Runs once at daily analyzer start
- Computes ALL nodes simultaneously
- Compares to previous run's state
- Produces action dashboard from diffs
- **No temporal awareness** — doesn't know what time it is
- **No event-driven firing** — all nodes resolve in one pass

### Neural graph (event-driven model):
- Neurons are **dormant** until their condition is met
- **Time-aware** — some neurons only fire during specific windows
- **Event-driven** — a price change fires PRICE_FEED, which cascades to TICKER_DIPPED, which cascades to BREADTH_DIP, which cascades to SIGNAL_CONFIRMED
- **Terminal decision** — the cascade either reaches BUY_DIP (fire = take action) or NO_ACTION (not enough neurons fired)
- **Reason chain is the firing path** — you trace back through which neurons fired and which didn't

---

## 2. The Daily Dip Neural Network

### Layer 1: Environment Neurons

These detect external conditions. They fire independently of any ticker.

| Neuron | Fires When | Signal Carries | Dependencies |
| :--- | :--- | :--- | :--- |
| `TIME_WINDOW_1` | 9:30 AM ≤ now ≤ 10:30 AM ET | "first_hour" | System clock |
| `TIME_WINDOW_2` | 10:30 AM ≤ now ≤ 11:00 AM ET | "second_hour" | System clock |
| `MARKET_OPEN` | Market is open today (not weekend/holiday) | True/False | trading_calendar |
| `REGIME` | Always fires (reads current regime) | "Risk-On" / "Neutral" / "Risk-Off" | VIX + indices |

**Behavior**:
- `TIME_WINDOW_1` lights up at 9:30 AM. Stays lit until 10:30 AM. Goes dark after.
- `TIME_WINDOW_2` lights up at 10:30 AM. Stays lit until 11:00 AM. Goes dark after.
- `MARKET_OPEN` lights up at market open. If dark (weekend/holiday), entire network stays dormant.

### Layer 2: Market-Wide Neurons

These aggregate signals across all watched tickers. They fire based on collective behavior.

| Neuron | Fires When | Signal Carries | Synapses From |
| :--- | :--- | :--- | :--- |
| `BREADTH_DIP` | ≥50% of tickers dipped >1% from open | dip_count, total, ratio | `TIME_WINDOW_1` + all `{tk}:TICKER_DIPPED` |
| `BREADTH_BOUNCE` | ≥50% of tickers bounced >0.3% | bounce_count, total, ratio | `TIME_WINDOW_2` + all `{tk}:TICKER_BOUNCED` |
| `SIGNAL_CONFIRMED` | Both BREADTH_DIP and BREADTH_BOUNCE fired | "CONFIRMED" / "STAY_OUT" / "MIXED" | `BREADTH_DIP` + `BREADTH_BOUNCE` |

**Behavior**:
- `BREADTH_DIP` can ONLY evaluate when `TIME_WINDOW_1` is lit. If TIME_WINDOW_1 never fired (before 9:30 or after 10:30), BREADTH_DIP stays dark.
- `BREADTH_BOUNCE` can ONLY evaluate when `TIME_WINDOW_2` is lit.
- `SIGNAL_CONFIRMED` fires only if BOTH breadth neurons fired. If only one fired, it signals "MIXED" or "STAY_OUT" — the cascade continues but with a weaker signal.

### Layer 3: Per-Ticker Neurons

One set per watched ticker. These evaluate individual ticker conditions.

| Neuron | Fires When | Signal Carries | Synapses From |
| :--- | :--- | :--- | :--- |
| `{tk}:PRICE_FEED` | Always (reads current price) | current, open, high, low | yfinance / broker feed |
| `{tk}:TICKER_DIPPED` | (open - current) / open > 1% | dip_pct | `{tk}:PRICE_FEED` |
| `{tk}:TICKER_BOUNCED` | Price recovering >0.3% from first-hour low | bounce_pct | `{tk}:PRICE_FEED` + `TIME_WINDOW_2` |
| `{tk}:DIP_VIABLE` | Simulation says dip play works for this ticker | YES / CAUTION / NO / BLOCKED | Pre-computed (multi-period scorer) |
| `{tk}:NOT_CATASTROPHIC` | Ticker NOT in HARD_STOP or EXIT_REVIEW | clear / blocked | `{tk}:catastrophic` + `{tk}:verdict` |
| `{tk}:EARNINGS_CLEAR` | Ticker NOT in earnings blackout (<7 days) | clear / blocked | earnings_gate |
| `{tk}:HISTORICAL_RANGE` | Median daily range ≥ 3% AND recovery ≥ 60% | range_pct, recovery_pct | Pre-computed (1-month stats) |

**Behavior**:
- `PRICE_FEED` fires continuously (or on each price update). Every price tick cascades to TICKER_DIPPED and TICKER_BOUNCED.
- `TICKER_DIPPED` lights up as soon as the ticker dips >1% from open. Stays lit as long as it's below the threshold.
- `TICKER_BOUNCED` only evaluates during TIME_WINDOW_2. It checks if the ticker is recovering from the first-hour low.
- `DIP_VIABLE`, `NOT_CATASTROPHIC`, `EARNINGS_CLEAR`, `HISTORICAL_RANGE` are evaluated once at start of day. They're "pre-lit" or "pre-blocked" — they don't change during the session.

### Layer 4: Per-Ticker Gate Neurons

All must fire for a ticker to become a dip candidate.

| Neuron | Fires When | Synapses From |
| :--- | :--- | :--- |
| `{tk}:CANDIDATE` | ALL of the following fired: | |
| | `{tk}:TICKER_DIPPED` (dipped today) | Layer 3 |
| | `{tk}:TICKER_BOUNCED` (recovering) | Layer 3 |
| | `{tk}:DIP_VIABLE` = YES or CAUTION | Layer 3 |
| | `{tk}:NOT_CATASTROPHIC` = clear | Layer 3 |
| | `{tk}:EARNINGS_CLEAR` = clear | Layer 3 |
| | `{tk}:HISTORICAL_RANGE` passed | Layer 3 |

**Behavior**:
- This is an AND gate — ALL inputs must fire. If any single neuron is dark, CANDIDATE stays dark.
- Signal carries: ticker, dip_pct, current_price, entry_price (current × 0.99), target (+4%), stop (-3%)

### Layer 5: Portfolio Neurons

Cross-ticker decisions that constrain which candidates actually get capital.

| Neuron | Fires When | Signal Carries | Synapses From |
| :--- | :--- | :--- | :--- |
| `PDT_AVAILABLE` | day_trade_count < 3 in last 5 days | remaining_trades | trade_history |
| `CAPITAL_AVAILABLE` | dip_pool ≥ $100 remaining | available_budget | portfolio capital |
| `RANKER` | ≥1 CANDIDATE neuron fired | ranked list: top 5 by dip_pct | All `{tk}:CANDIDATE` + `PDT_AVAILABLE` + `CAPITAL_AVAILABLE` |

**Behavior**:
- `PDT_AVAILABLE` evaluates once at start. If dark (3 day trades used), entire buy path is blocked.
- `CAPITAL_AVAILABLE` evaluates based on remaining dip budget after existing positions.
- `RANKER` collects all CANDIDATE signals, sorts by dip_pct descending, takes top 5. It only fires if at least 1 candidate exists AND PDT AND capital are available.

### Layer 6: Decision Neurons (Terminal)

These produce the final action output.

| Neuron | Fires When | Output |
| :--- | :--- | :--- |
| `{tk}:BUY_DIP` | RANKER includes this ticker AND SIGNAL_CONFIRMED = "CONFIRMED" | "BUY {tk} at ${entry}, sell at ${target}, stop at ${stop}, size ${budget}" |
| `NO_ACTION` | SIGNAL_CONFIRMED did NOT fire, OR no candidates, OR PDT blocked, OR capital exhausted | "No dip play today — {reason from unfired neuron}" |

**Behavior**:
- `BUY_DIP` is the terminal neuron. When it fires, a trade recommendation is produced.
- `NO_ACTION` fires when the cascade failed at any point. Its reason traces which neuron blocked the cascade.
- REGIME modifies BUY_DIP sizing: Risk-Off → half position ($50 instead of $100).

---

## 3. The Firing Sequence (Timeline)

```
7:00 AM  — MARKET_OPEN evaluates: is today a trading day?
           If NO → entire network stays dormant all day.

9:00 AM  — Pre-session evaluation:
           {tk}:DIP_VIABLE, NOT_CATASTROPHIC, EARNINGS_CLEAR, HISTORICAL_RANGE
           evaluated once. Pre-lit or pre-blocked for the day.
           PDT_AVAILABLE, CAPITAL_AVAILABLE evaluated once.
           REGIME evaluated once.

9:30 AM  — TIME_WINDOW_1 fires.
           {tk}:PRICE_FEED starts updating (5-min bars or live).
           {tk}:TICKER_DIPPED evaluates on each price update.
           BREADTH_DIP evaluates: are ≥50% of tickers dipping?

10:30 AM — TIME_WINDOW_1 goes dark. TIME_WINDOW_2 fires.
           BREADTH_DIP finalizes: either fired or didn't.
           {tk}:TICKER_BOUNCED starts evaluating.
           BREADTH_BOUNCE evaluates: are ≥50% bouncing?

11:00 AM — TIME_WINDOW_2 goes dark.
           BREADTH_BOUNCE finalizes.
           SIGNAL_CONFIRMED evaluates: both breadth neurons fired?

           If CONFIRMED:
             All {tk}:CANDIDATE neurons evaluate (AND gate).
             RANKER collects candidates, ranks by dip_pct.
             {tk}:BUY_DIP fires for top 5 ranked candidates.
             → TRADE RECOMMENDATIONS OUTPUT

           If NOT confirmed:
             NO_ACTION fires with reason.
             → "No dip play today — [breadth too weak / no bounce / etc.]"

11:00 AM+ — Network goes dormant until next trading day.
```

---

## 4. The Reason Chain (Why Did BUY_DIP Fire?)

When `CLSK:BUY_DIP` fires, the full reason chain traces every synapse:

```
MARKET_OPEN: True (Monday 2026-03-30)
  → TIME_WINDOW_1: 9:30-10:30 (fired)
    → CLSK:PRICE_FEED: open=$8.90, current=$8.72 at 10:15
      → CLSK:TICKER_DIPPED: dip 2.0% from open (fired, threshold 1%)
    → 14/27 tickers dipped >1%
      → BREADTH_DIP: 51.9% breadth (fired, threshold 50%)
  → TIME_WINDOW_2: 10:30-11:00 (fired)
    → CLSK:PRICE_FEED: current=$8.81 at 10:45 (recovering from $8.72 low)
      → CLSK:TICKER_BOUNCED: +1.0% from first-hour low (fired, threshold 0.3%)
    → 15/27 tickers bouncing >0.3%
      → BREADTH_BOUNCE: 55.6% (fired, threshold 50%)
  → SIGNAL_CONFIRMED: CONFIRMED (both breadth neurons fired)
  → CLSK:DIP_VIABLE: YES (68.4% win rate, Risk-Off regime win 42%)
  → CLSK:NOT_CATASTROPHIC: clear (P/L -3.7%, not HARD_STOP)
  → CLSK:EARNINGS_CLEAR: clear (next earnings 45 days away)
  → CLSK:HISTORICAL_RANGE: 7.6% range, 100% recovery (fired)
  → CLSK:CANDIDATE: ALL gates passed (fired)
  → PDT_AVAILABLE: 1/3 used (2 remaining)
  → CAPITAL_AVAILABLE: $400 remaining
  → RANKER: CLSK ranked #1 (2.0% dip, biggest dipper)
  → REGIME: Risk-Off → half-size ($50 instead of $100)
  → CLSK:BUY_DIP: BUY CLSK at $8.81, sell at $9.16 (+4%), stop at $8.55 (-3%), size $50
```

Every node in the chain is a neuron that either fired or blocked. The reason is the firing path itself.

---

## 5. How This Differs from the Current Graph Engine

| Aspect | Current Graph | Neural Graph |
| :--- | :--- | :--- |
| **Evaluation** | All nodes resolve once | Neurons fire when conditions met |
| **Timing** | Snapshot at run time | Time-window-aware (9:30-10:30, 10:30-11:00) |
| **Data flow** | Bottom-up resolution | Event-driven cascade |
| **Activation** | All nodes always compute | Dormant until condition triggers |
| **Aggregation** | No cross-ticker aggregation | BREADTH neurons aggregate 27 tickers |
| **Decision** | Dashboard lists actions | Terminal BUY_DIP neuron fires or doesn't |
| **Sequencing** | No order dependency | Layer 1 must fire before Layer 2 |
| **Continuous** | Runs once per session | Could run on every price tick |
| **Output** | Markdown report | Single decision: BUY / NO_ACTION per ticker |

---

## 6. What the Graph Engine Needs to Support This

The current `graph_engine.py` can resolve dependencies and propagate signals, but it lacks:

### 6.1 Temporal Gating
Neurons need to know what time it is. TIME_WINDOW_1 fires at 9:30, goes dark at 10:30. The engine needs a clock and the ability to gate node evaluation by time.

### 6.2 Event-Driven Evaluation
Currently all nodes resolve in one `resolve()` call. The neural model needs nodes to re-evaluate when their inputs change (price update → TICKER_DIPPED re-evaluates → cascades).

### 6.3 AND-Gate Neurons
CANDIDATE fires only when ALL inputs fired. Current engine has `depends_on` but it means "needs this data," not "needs this to have fired." The neural model needs a distinction between "data dependency" and "activation dependency."

### 6.4 Aggregation Neurons
BREADTH_DIP counts how many per-ticker neurons fired. Current engine doesn't have a "count my fired children" operation.

### 6.5 Dormancy
Current engine computes every node every time. Neural model needs nodes that stay dormant (don't compute) until their pre-conditions activate.

### 6.6 Continuous Re-evaluation
Current engine resolves once. Neural model could re-resolve on each price tick (every 5 minutes during market hours).

---

## 7. Implementation Approaches

### Approach A: Extend Current Engine
Add temporal gating, AND-gate logic, and aggregation to the existing DependencyGraph. Keep the single-resolve pattern but add a "phase" concept (pre-session, first-hour, second-hour, decision).

**Pros**: Builds on tested infrastructure. Incremental.
**Cons**: Stretches the snapshot model into something it wasn't designed for.

### Approach B: Build Neural Engine
New `NeuralGraph` class alongside DependencyGraph. Neurons have states (dormant, evaluating, fired, blocked). Synapses carry signals. Clock drives temporal gating. Event loop drives re-evaluation.

**Pros**: Clean design for the problem. No compromises.
**Cons**: New infrastructure to build and test.

### Approach C: Phased Resolution
Keep current engine but call `resolve()` multiple times with different contexts:
1. Pre-session resolve (static neurons: DIP_VIABLE, EARNINGS_CLEAR, etc.)
2. First-hour resolve (TIME_WINDOW_1 active, feed price data, compute BREADTH_DIP)
3. Second-hour resolve (TIME_WINDOW_2 active, compute BREADTH_BOUNCE)
4. Decision resolve (SIGNAL_CONFIRMED → CANDIDATE → RANKER → BUY_DIP)

**Pros**: Uses existing engine. Clear phase boundaries.
**Cons**: Requires external orchestration of phases. Not truly event-driven.

---

## 8. The Vision Beyond Dip Strategy

This neural model is not limited to daily dips. The same architecture applies to:

- **Support-level entry decisions**: Neurons for "price approaching level," "hold rate above threshold," "zone is active," "regime allows entry" → cascades to PLACE_LIMIT_ORDER.
- **Exit decisions**: Neurons for "P/L above target," "time stop approaching," "momentum flipped bearish" → cascades to SELL or HOLD.
- **Portfolio rebalancing**: Neurons for "sector over-concentrated," "capital depleted in sector," "new candidate scored higher than weakest position" → cascades to REBALANCE.
- **Risk management**: Neurons for "VIX spike >10% in one day," "3+ positions in HARD_STOP," "portfolio drawdown >15%" → cascades to PAUSE_ALL or REDUCE_EXPOSURE.

Each use case is a different neural network that shares the same engine and some of the same environment neurons (REGIME, MARKET_OPEN, TIME_WINDOW).

---

## 9. What Needs Analysis Next

Before building, we need to determine:

1. **Which approach (A/B/C)?** — extends existing engine, build new, or phased resolution?
2. **How does it interact with the current daily analyzer?** — replaces it? Runs alongside? Called from it?
3. **What data feeds are needed?** — yfinance 5-min bars during market hours? Or simulated from daily OHLCV?
4. **How is it tested?** — can we test with historical intraday data, or only live?
5. **What is the MVP?** — which neurons are essential for the first working version vs nice-to-have?
