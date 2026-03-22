# Global Trading Strategy: The "Surgical" Mean Reversion

## Core Philosophy
We employ a **Mean Reversion** strategy, targeting stocks that consistently fluctuate with a **10%+ monthly swing**. We aim to "buy low" at established historical support levels and "sell high" at the top of the channel, typically within a 4-8 week window.

## Capital Allocation (Per Stock)
*   **Total Allocation:** ~$600 per stock.
*   **Active Pool ($300):** Up to 5 bullets, pool-distributed sizing with equal averaging impact.
    Each pool is distributed across all levels using price-weighted allocation — each bullet
    buys roughly the same number of shares, so each fill moves the average by the same amount.
    Half-tier levels (15-29% hold rate) get ~half the shares. Per-bullet cap: 40% of pool.
    Residual shares go to highest hold_rate levels. Below 15% hold: no order (true dead zone).
*   **Reserve Pool ($300):** Up to 3 bullets, same pool-distributed sizing. Deployed at deep support
    (beyond normal monthly swing range) when the stock breaks structural levels.
    **Every stock has a reserve pool.**

## Selection Criteria
1.  **Price:** < $40 preferred (allows for whole-share averaging with $60-100 bullets).
2.  **Volatility:** Must demonstrate 10%+ monthly swing (median), with 80%+ of months hitting 10%+.
3.  **Liquidity:** High volume to ensure limit orders fill during "wicks".
4.  **Sector Balance:** Diversify across uncorrelated sectors (e.g., Fintech, Energy, Infrastructure) to mitigate systemic risk.
5.  **Cycle Efficiency:** Prefer stocks with fast, validated resistance→support→recovery cycles.

### Cycle Efficiency Scoring (20 points)

Cycle efficiency measures how quickly and reliably a stock completes resistance→support→recovery cycles:

| Sub-Component | Points | Thresholds |
| :--- | :--- | :--- |
| Cycle Count | 0-6 | 0=0, 1-4=2, 5-9=4, 10+=6 |
| Immediate Fill Rate | 0-6 | <50%=0, 50-79%=2, 80-99%=4, 100%=6 |
| Median Deep Speed | 0-5 | >15d=0, 8-15d=2, 3-7d=3, 1-2d=5 |
| Consistency Bonus | 0-3 | All three maxed = 3 |

**Source:** `tickers/<TICKER>/cycle_timing.json` → `statistics` object.

**KPI Gates (informational):**
- Gate 6: >= 5 validated cycles
- Gate 7: >= 85% immediate fill rate
- Gate 8: >= 3 active levels with 50%+ hold rate

Candidates failing these gates are flagged, not rejected — new tickers won't have cycle data yet.

## Execution Rules
### Entry Protocol ("Zone-Based Bullets")
*   **Active Zone** = support levels within half the stock's median monthly swing
    from current price, capped at 20%. These catch normal monthly pullbacks.
*   **Buffer Zone** = support levels between 1× and 2× the active radius from
    current price. These catch deeper pullbacks beyond the normal monthly range.
*   **Reserve Zone** = support levels beyond the buffer zone. These deploy only
    when the stock breaks through normal fluctuation range.
*   Place up to 5 bullets at wick-adjusted prices across the Active Zone.
*   Place up to 5 bullets at wick-adjusted prices across the Buffer Zone.
*   Place up to 3 reserve bullets at the deepest reliable levels in the Reserve Zone.
*   Hold rate determines bullet SIZE, not eligibility (minimum 15% hold to place any order).
*   Run `python3 tools/wick_offset_analyzer.py <TICKER>` — the tool classifies each
    level as Active/Buffer/Reserve and suggests a bullet plan.
*   **Fallback:** If monthly swing cannot be computed (< 3 months data), a 15% active
    radius is used. Results should be validated manually in this case.
*   **Earnings Entry Gate:** Before placing limit buy orders, check the earnings calendar
    via `python3 tools/earnings_analyzer.py <TICKER>`. Do not place NEW buy orders if
    earnings is <7 days away. Between 7-14 days, enter only with an explicit
    exit-before-earnings plan documented in the ticker's identity.md. When earnings
    enters the 7-day window for a ticker with existing pending buy orders, **PAUSE**
    (do not cancel) those orders — they remain staged to catch a post-earnings drop.

### Market Context Entry Gate
Before placing or reviewing pending buy orders, assess the market regime via
`python3 tools/market_pulse.py`. The regime classification drives a portfolio-level
overlay on all entry decisions:

*   **Risk-On** (majority of indices above 50-SMA + VIX < 20): Proceed with
    normal bullet placement at wick-adjusted support levels. No entry constraint.
*   **Neutral** (mixed signals — neither Risk-On nor Risk-Off): Proceed with
    normal entries. Note tighter bullet spacing may be warranted if VIX is
    trending upward or sector rotation is unfavorable.
*   **Risk-Off** (minority of indices above 50-SMA + VIX > 25): **PAUSE all
    pending buy orders for watchlist tickers** (no active position). For tickers
    with active positions, pending buy orders at deep support (>15% below
    current price) remain valid as capitulation catchers, but orders within
    15% of current price should be reviewed for pausing. No new orders
    should be placed. Review active position stops for tightening.

**Interaction with Earnings Entry Gate:** Both gates apply independently. A
pending order must pass BOTH the earnings gate (ticker-level) AND the market
context gate (portfolio-level) to remain active. If either gate says PAUSE,
the order is paused.

**Sector context:** When leading/lagging sectors diverge from portfolio
exposure, note the mismatch. Pending orders in lagging sectors during
Risk-Off carry elevated risk.

### Limit Order Placement Rule
**Never place a limit buy at the exact support level.** Use `python3 tools/wick_offset_analyzer.py <TICKER>` to calculate the data-driven buy price for each support level. The tool analyzes 13 months of wick behavior at each specific level and outputs the exact recommended buy price based on where wicks historically stopped. Place limit orders at the tool's "Buy At" price, not the raw support level. Re-run periodically as new data accumulates.

### Exit Protocol
*   **Profit Target:** 10-12% gain from the average cost basis.
*   **Time Stop:** If target is not hit within **8 weeks (~60 days)**, review for exit (rotate capital).
*   **Earnings Rule:** Binary events (earnings calls) require position-specific
    assessment, not a blanket exit. Use the Earnings Decision Framework below.

### Earnings Decision Framework

**Timing thresholds (days to earnings):**
*   **GATED (<7 days):** Active decision required — evaluate per position type below.
*   **APPROACHING (7-14 days):** Flag for review. No new entries without explicit
    exit-before-earnings plan. Pause pending buy orders for non-recovery positions.
*   **CLEAR (>14 days or unknown):** No earnings constraint.

**Position-type decisions when GATED (<7 days):**

1.  **Profitable swing trades (P/L > 0%, non-recovery):**
    **EXIT or REDUCE** — lock in gains. The asymmetry is negative: a post-earnings
    drop can erase the gain entirely (NU Q1 2025: -18.9% in one day), while the
    incremental upside from holding through is marginal. Close the position or
    reduce to a starter stake. Cancel or pause remaining buy orders.

2.  **Underwater swing trades (P/L < 0%, non-recovery, still building bullets):**
    **HOLD existing position, PAUSE pending buy orders.** The position is early-stage
    — exiting abandons a setup you believe in and locks in a loss for no strategic
    reason. Pending bullets at deeper support levels are designed to catch drops; a
    post-earnings pullback is exactly the scenario they serve. If earnings spikes the
    stock, you have exposure. Resume pending orders after the event. Exception: if
    conviction in the stock has deteriorated (broken thesis, not just price), EXIT.

3.  **Recovery positions (pre-strategy, underwater):**
    Earnings may BE the recovery catalyst. Do not automatically reduce.
    *   **With specific earnings thesis** (management responding to short report,
        expected guidance beat, institutional accumulation into event, unchanged
        price targets): **HOLD** — the binary event is the recovery path. Selling
        deep underwater before the catalyst locks in losses and removes upside
        exposure to the very event that could close the gap.
    *   **Moderately or deeply underwater (P/L <= -10%) with no specific thesis:**
        **HOLD with awareness** — marginal downside is limited when already this
        far underwater, while recovery upside from a positive surprise is meaningful.
        (This covers both the -10% to -20% range and the deeper-than-20% range.)
    *   **Near breakeven recovery (P/L > -10%) with no thesis:** **REDUCE** —
        protect the near-recovery by taking partial profits or cutting to starter.

4.  **Fully-loaded positions (all active bullets used, non-recovery):**
    Maximum exposure to the binary event. If profitable: **REDUCE** (take partial
    gains off the table). If underwater with thesis: **HOLD**. If underwater with
    no thesis: **HOLD** — bullets are exhausted and exiting now locks in the
    maximum loss with no averaging path remaining.

**Pending order management when GATED:**
*   **PAUSE** (do not cancel) pending buy orders. Post-earnings drops are caught
    by deeper support bullets — that's their purpose. Post-earnings spikes cause
    no harm from unfilled orders. Resume orders after the event.
*   Exception: Recovery positions with a specific earnings thesis — buy orders may
    remain active if the thesis supports continued accumulation at those levels.
*   **Never place NEW buy orders** when earnings is <7 days away.

**Post-earnings protocol:**
*   Resume paused pending orders.
*   Re-run `earnings_analyzer.py` to update cached data with the new quarter.
*   Evaluate the earnings outcome against the pre-event thesis.
*   If the stock gapped down to a pending bullet level: let the bullet do its job.
*   If the stock spiked: evaluate whether target exit is now within reach.

**Periodic audit:** Weekly cross-check all pending limit orders against the earnings
calendar. Flag any ticker where earnings is <14 days away and pending buy orders
are still active. This prevents accidental fills into binary events.

### Position Reporting Order
When reporting on active positions, always present information in this sequence:
1.  **Trades Executed:** List each individual fill (date, price, shares) from the agent's `memory.md` trade log.
2.  **Current Average:** The computed average cost basis and total shares from all fills.
3.  **Pending Limit Orders:** Any open BUY or SELL orders not yet filled (from `portfolio.json`).
4.  **Wick-Adjusted Buy Levels:** Data-driven buy prices from `wick_analysis.md` (or run `wick_offset_analyzer.py` if no cache exists). Show the "Buy At" price, hold rate, and shares to buy at each level. Never report raw support levels without wick adjustment.
5.  **Projected Sell Levels:** Target exit price and expected P/L % based on current average.
6.  **Scenario Table (if applicable):** When projecting outcomes (bull/bear/etc.), each row must pass these checks:
    *   **Direction-Price Consistency:** Buy levels must match the scenario. Bull scenarios use higher buy prices (pullbacks within an uptrend); bear scenarios use lower buy prices (washout/capitulation). Never suggest buying at $30 in a bull scenario when the stock is already at $34+.
    *   **Show the Math:** New Avg = (current shares × current avg + new shares × buy price) / total shares. Always compute explicitly, never estimate.
    *   **Monotonic Sanity Check:** Lower buy prices must produce lower new averages. If they don't, the math is wrong. Review before presenting.

### The "Cycle" Awareness
*   **Monthly Rhythm:** Identify if the stock typically bottoms Early (Days 1-8), Mid (12-18), or Late (23-30) in the month.
*   **Do Not Chase:** If the "Low Window" has passed and price is mid-range, **WAIT** for the next cycle.

### Underwater Position Recovery ("Dig Out" Protocol)
When a position was entered before the strategy was refined and is significantly underwater:
*   **Earnings Gate:** If a binary event (earnings call) is approaching, **gate new
    capital deployment** — pause pending buy orders and reserve dry powder for
    post-event clarity. **Hold the existing position** through the event: recovery
    positions are underwater precisely because they need a catalyst, and earnings
    may be that catalyst (especially when management must address specific concerns
    like short reports, guidance questions, or revenue dependency). Sell only if the
    recovery thesis has broken (not merely because earnings is near). See Earnings
    Decision Framework above for the full position-type matrix.
*   **Washout Discipline:** When a major psychological support breaks (e.g., $30), do not buy $1 below. Wait for the capitulation flush (typically 10-15% further down). Fewer shares at a deeper price achieve the same average reduction for less capital.
*   **Relief Rally Validation:** After a sharp drop, the first bounce may be a "dead cat bounce." Validate by checking: (1) volume increasing on up days, (2) price holds above prior resistance for 2+ days, (3) RSI crosses back above 30.
*   **LLM Cross-Verification:** When an LLM cites specific institutional buying (e.g., "JPMorgan +648%"), verify through `institutional_flow.py` before acting. Directional signals are usually correct, but specific names/numbers may be hallucinated.

### Range Reset Protocol
When a position is underwater with ≥3 active bullets exhausted but the stock has settled into a
stable new trading range, deploy fresh bullets from the reserve pool to play that range.

*   **Trigger:** Underwater position with ≥3 bullets exhausted, stock settled into new range.
*   **Three signals required:** Median convergence <5% (STABLE), 20d swing ≥20%, 6% exit
    reachable within the range (p75 of 20d highs).
*   **Capital source:** Reserve pool ($300 per stock) — no new allocation beyond existing reserves.
*   **Minimum score:** 50/100 (RESET-POSSIBLE or better) to deploy.
*   **UNSTABLE = no deploy** regardless of score — wait for the range to stabilize.
*   **Tool:** `python3 tools/range_reset_analyzer.py [TICKER ...]` — analyzes all qualifying
    underwater positions or specific tickers. Outputs scored scenarios with sized bullets.
*   **After deployment:** Update `portfolio.json` via `portfolio_manager.py`, re-run
    `sell_target_calculator.py` for revised sell targets.
*   **Does not override** exit-review verdicts for RECOVERY positions (those are excluded
    from range reset analysis).

**Scoring (100 points):** Stability (25), Swing (20), Exit Reachability (20),
Cycle Efficiency (15), Risk inverse (20). Verdicts: RESET-READY (75+),
RESET-POSSIBLE (50-74), MONITOR (25-49), NO-RESET (0-24).

### Range Uplift Protocol
When pending BUY orders become dormant because the stock established a higher trading range,
cancel dormant orders and redeploy at support levels within the new range.

*   **Trigger:** Pending BUY orders >15% below current price AND 20d range low >10% above order price.
*   **Three signals required:** Median convergence <5% (STABLE), 20d swing >=20%, 6% exit
    reachable within the range (p75 of 20d highs).
*   **Capital source:** Freed capital from cancelled dormant orders — no new allocation.
*   **Minimum score:** 50/100 (UPLIFT-POSSIBLE or better) to redeploy.
*   **UNSTABLE = no deploy** regardless of score — wait for the range to stabilize.
*   **Tool:** `python3 tools/range_uplift_analyzer.py [TICKER ...]`
*   **After redeployment:** Cancel old orders, place new orders, update `portfolio.json`
    via `portfolio_manager.py`.
*   **Does not override** exit-review verdicts for RECOVERY positions.

**Scoring (100 points):** Stability (25), Swing (20), Exit Reachability (20),
Cycle Efficiency (15), Risk inverse (20). Verdicts: UPLIFT-READY (75+),
UPLIFT-POSSIBLE (50-74), MONITOR (25-49), NO-UPLIFT (0-24).

### Cached Structural Data
Structural tools auto-save per-ticker cache files to `tickers/<TICKER>/` on every run. These files refresh each time the tool is re-run:
*   `wick_analysis.md` — Support levels & data-driven buy recommendations (from `wick_offset_analyzer.py`).
*   `earnings.md` — Earnings history, revenue trend, price reactions (from `earnings_analyzer.py`).
*   `institutional.md` — Top holders, insider transactions, cluster buy signals (from `institutional_flow.py`).
*   `short_interest.md` — Short %, squeeze risk, days to cover (from `short_interest.py`).
*   `news.md` — Headlines, sentiment, deep-dive articles (from `news_sentiment.py`).

---

## Velocity Strategy: The "Quick Strike"

### Core Philosophy
High-frequency mean reversion targeting **4.5% gains** in **1-3 trading days**. Uses technical confluence scoring (RSI + MACD + Bollinger + Stochastic) to identify optimal entry windows. Runs in parallel with the Surgical strategy on a separate stock pool.

### Capital Allocation
*   **Total Pool:** $1,000 (shared across all velocity tickers)
*   **Per-Trade Size:** ~$150-200 (max 5-6 concurrent positions)
*   **No Bullet Averaging:** Single entry, single exit. If stop hits, move on.

### Signal Scoring (100-point scale)
| Signal | Points | Condition |
| :--- | :--- | :--- |
| RSI(14) Oversold | 30 | RSI < 35 |
| MACD Bullish Cross | 25 | MACD line crosses above signal line, histogram turning positive |
| Bollinger Lower Pierce | 25 | Price touches or breaks below lower Bollinger Band (20,2) |
| Stochastic Oversold | 10 | %K < 20 |
| RSI 3-Day Trend | 10 | RSI rising for 3 consecutive days from oversold territory |
| **Entry Threshold** | **70+** | |

### Exit Rules (First to Trigger)
1.  **+4.5% Target Hit** — Take profit immediately.
2.  **RSI > 70** — Overbought exit (may trigger before 4.5% if momentum is strong).
3.  **-3% Hard Stop** — Cut loss, no averaging, no hoping.
4.  **3 Trading Day Time Stop** — If neither target nor stop hit in 3 days, exit at market.

### Selection Criteria (Hard Gates — scanner blocks verdict if any fail)
*   **Price:** $5-$80 (wider range than Surgical — velocity doesn't need tiered bullet math).
*   **ATR%:** > 2.5% daily (needs enough daily movement to hit 4.5% in 1-3 days).
*   **Volume:** > 2M daily average (ensures tight spreads for quick entries/exits).
*   Must NOT be in the Surgical or Bounce stock pool (no overlap).

### Velocity Watchlist
(Candidates to be identified — APLD likely first transition from Surgical)

---

## Bounce Strategy: The "Quick Flip"

### Core Philosophy
Capture **historically validated support bounces** with immediate limit sell orders at data-driven targets. When price approaches a support level that has a proven bounce history, buy at the wick-adjusted price and sell into the bounce. Targets are per-level medians from hourly data — not fixed percentages.

### Capital Allocation
*   **Total Pool:** $1,000 (shared across all bounce tickers)
*   **Per-Trade Size:** ~$100 (matches one Surgical bullet)
*   **Max Concurrent:** 10 trades
*   **No Averaging:** Single entry, single exit. If stop hits, move on.

### Data-Driven Bounce Targets
*   Uses **hourly data** (`interval="1h"`, ~2 years) for intraday timestamp accuracy.
*   Measures actual bounce magnitude (same-day remainder, 2-day, 3-day) from each held support approach.
*   Sell target = buy price × (1 + median 3-day bounce %) — unique per stock per level.

### Signal Verdicts
| Verdict | Criteria |
| :--- | :--- |
| STRONG BOUNCE | hold_rate >= 50% AND >= 60% of holds produce >= 4.5% bounce within 3 days |
| BOUNCE | hold_rate >= 40% AND >= 40% of holds produce >= 4.5% bounce within 3 days |
| WEAK | Below thresholds |
| NO DATA | < 3 historical approaches |

### Exit Rules (First to Trigger)
1.  **Bounce Target Hit** — Sell at the data-driven median bounce price.
2.  **RSI > 70** — Overbought exit (may trigger before target).
3.  **-3% Hard Stop** — Cut loss, no averaging, no hoping.
4.  **3 Trading Day Time Stop** — If neither target nor stop hit in 3 days, exit at market.

### Selection Criteria
*   Must NOT be in the Surgical stock pool (no overlap with positions, pending orders, or watchlist).
*   Must NOT be in the Velocity stock pool (no overlap with velocity positions, pending, or watchlist).
*   Must have >= 3 historical approaches at the support level (minimum data threshold).
*   Verdict must be STRONG BOUNCE or BOUNCE (WEAK and NO DATA levels are informational only).

### Tools
*   `python3 tools/bounce_analyzer.py <TICKER>` — Analyze support levels with hourly bounce history. Only levels within 30% of current price are included (distant historical support is excluded). Outputs markdown + JSON cache.
*   `python3 tools/bounce_dashboard.py` — Track active bounce trades, cached signals (actionable only by default; `--all` to include WEAK/NO DATA), exit alerts, capital summary.

---

## Current Watchlist & Status
See `portfolio.json` for live positions/orders and run `python3 tools/portfolio_status.py` for a full report.

*   **NU (Fintech):** Mid-Month Bottomer. Growth Anchor.
*   **AR (Energy):** Early-Month Bottomer. The Slow Cooker.
*   **STIM (MedTech):** Early-Month Bottomer. The Micro-Cap Swinger.
*   **IONQ (Quantum Computing):** Cycle Unknown. The Quantum Gambit. Recovery mode (pre-strategy, underwater).
*   **UAMY (Critical Minerals):** Cycle Unknown. The Critical Mineral. Policy-driven speculative play (pre-strategy, underwater).
*   **USAR (Rare Earth):** Cycle Unknown. The Rare Earth Pioneer. Pre-revenue, policy-driven speculative play (pre-strategy, underwater).
*   **INTC (Semiconductor):** Cycle Unknown. The Chip Comeback. Turnaround play on 18A node (pre-strategy, near breakeven).
*   **APLD (AI/HPC Infrastructure):** Cycle TBD. The AI Data Center. High-volatility mean reversion candidate (ATR 12.1%).
*   **VALE (Mining/Iron Ore):** Early-Month Bottomer. The Iron Ore Metronome. Best AR-like swing consistency (9/13 months hit 10%+). Watching for consolidation support data.
*   **CLF (Steel):** Early-Month Bottomer. The Steel Forge. Dense support near price (45-71% hold rates, 7-15 tests each). Active limits pending.
*   **SEDG (Solar):** Early-Month Bottomer. The Solar Swinger. Dead zone at $32-$35, waiting for pullback to $29-$31 support.
*   **CIFR (Crypto/BTC Mining):** Cycle TBD. The Bitcoin Miner. Massive monthly swings (67.8% median). B1 filled at $14.82, sell target $16.30.
*   **ACHR (Aerospace/eVTOL):** Cycle TBD. The eVTOL Pioneer. 40.7% monthly swing, 75% hold at $6.55 PA. Limits pending.
*   **SOUN (Technology/AI):** Cycle TBD. The Voice AI Play. 47.8% monthly swing, 75% hold at $6.95 PA. Limits pending.
*   **CLSK (Crypto/BTC Mining):** Cycle TBD. The Bitcoin Miner. 41.9% monthly swing, 5 active levels ($8.40-$9.66), 58% hold at $8.25 PA. Limits pending.
*   **SMCI (AI/Server Infrastructure):** Cycle TBD. The AI Server Builder. 34.9% monthly swing, 91% hold at $27.22 PA — strongest single level in portfolio. Limits pending.
*   **RKT (Fintech/Mortgage):** Cycle TBD. The Mortgage Fintech. 30.5% monthly swing, 3 active levels converge to $17.05 buy. Limits pending.