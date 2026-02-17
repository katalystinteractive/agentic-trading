# Global Trading Strategy: The "Surgical" Mean Reversion

## Core Philosophy
We employ a **Mean Reversion** strategy, targeting stocks that consistently fluctuate within a **7-12% monthly range**. We aim to "buy low" at established historical support levels and "sell high" at the top of the channel, typically within a 3-week window.

## Capital Allocation (Per Stock)
*   **Total Allocation:** ~$600 per stock.
*   **Active Pool ($300):** Deployed in 3 "Bullets" (Tranches) of ~$100 each to average down surgically. Bullet dollar size scales with share price to buy whole shares (e.g., ~$100 for $16+ stocks, ~$30 for $1.50 stocks).
*   **Reserve Pool ($300):** The "Safety Net." **Every stock has a reserve pool.** Only deployed if the stock breaks structural support (e.g., 52-week lows, last HVN floor) to aggressively lower basis for a break-even exit. Reserve bullets are placed at smart levels below the active pool range.

## Selection Criteria
1.  **Price:** < $40 preferred (allows for whole-share averaging with $100 bullets).
2.  **Volatility:** Must demonstrate consistent 7-12% monthly swings (High Beta is good, but must respect technicals).
3.  **Liquidity:** High volume to ensure limit orders fill during "wicks".
4.  **Sector Balance:** Diversify across uncorrelated sectors (e.g., Fintech, Energy, Infrastructure) to mitigate systemic risk.

## Execution Rules
### Entry Protocol ("The Bullets")
*   **Bullet 1:** Placed at "Support 1" (e.g., 50-day SMA, Channel Floor, HVN Floor).
*   **Bullet 2:** Placed at "Support 2" (e.g., Previous Pivot Low, Gap Fill).
*   **Bullet 3:** Placed at "Capitulation/Panic" levels (e.g., RSI < 30, Bollinger Band lower pierce).

### Limit Order Placement Rule
**Never place a limit buy at the exact support level.** Use `python3 tools/wick_offset_analyzer.py <TICKER>` to calculate the data-driven buy price for each support level. The tool analyzes 13 months of wick behavior at each specific level and outputs the exact recommended buy price based on where wicks historically stopped. Place limit orders at the tool's "Buy At" price, not the raw support level. Re-run periodically as new data accumulates.

### Exit Protocol
*   **Profit Target:** 10-12% gain from the average cost basis.
*   **Time Stop:** If target is not hit within **3 weeks**, review for exit (rotate capital).
*   **Earnings Rule:** Generally exit or reduce position before earnings reports to avoid binary risk, unless specifically playing a post-earnings drift.

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
*   **Earnings Gate:** If a binary event (earnings call) is approaching, gate the largest capital deployment on the event outcome. Keep a starter position to benefit from pre-event bounce, but reserve the majority of dry powder for post-event clarity.
*   **Washout Discipline:** When a major psychological support breaks (e.g., $30), do not buy $1 below. Wait for the capitulation flush (typically 10-15% further down). Fewer shares at a deeper price achieve the same average reduction for less capital.
*   **Relief Rally Validation:** After a sharp drop, the first bounce may be a "dead cat bounce." Validate by checking: (1) volume increasing on up days, (2) price holds above prior resistance for 2+ days, (3) RSI crosses back above 30.
*   **LLM Cross-Verification:** When an LLM cites specific institutional buying (e.g., "JPMorgan +648%"), verify through `institutional_flow.py` before acting. Directional signals are usually correct, but specific names/numbers may be hallucinated.

### Cached Structural Data
Structural tools auto-save per-ticker cache files to `agents/<TICKER>/` on every run. These files refresh each time the tool is re-run:
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
*   **Price:** $5-$80 (wider range than Surgical — velocity doesn't need $100 bullet math).
*   **ATR%:** > 2.5% daily (needs enough daily movement to hit 4.5% in 1-3 days).
*   **Volume:** > 2M daily average (ensures tight spreads for quick entries/exits).
*   Must NOT be in the Surgical stock pool (no overlap).

### Velocity Watchlist
(Candidates to be identified — APLD likely first transition from Surgical)

---

## Current Watchlist & Status
See `portfolio.json` for live positions/orders and run `python3 tools/portfolio_status.py` for a full report.

*   **NU (Fintech):** Mid-Month Bottomer. Growth Anchor.
*   **SOFI (Fintech/AI):** Binary Bottomer. AI Wildcard.
*   **AR (Energy):** Early-Month Bottomer. The Slow Cooker.
*   **KMI (Energy/Infrastructure):** Early-Month Bottomer. Dividend Fortress.
*   **STIM (MedTech):** Early-Month Bottomer. The Micro-Cap Swinger.
*   **IONQ (Quantum Computing):** Cycle Unknown. The Quantum Gambit. Recovery mode (pre-strategy, underwater).
*   **UAMY (Critical Minerals):** Cycle Unknown. The Critical Mineral. Policy-driven speculative play (pre-strategy, underwater).
*   **USAR (Rare Earth):** Cycle Unknown. The Rare Earth Pioneer. Pre-revenue, policy-driven speculative play (pre-strategy, underwater).
*   **INTC (Semiconductor):** Cycle Unknown. The Chip Comeback. Turnaround play on 18A node (pre-strategy, near breakeven).
*   **APLD (AI/HPC Infrastructure):** Cycle TBD. The AI Data Center. High-volatility mean reversion candidate (ATR 12.1%).
*   **VALE (Mining/Iron Ore):** Early-Month Bottomer. The Iron Ore Metronome. Best AR-like swing consistency (7-13% in 9/13 months). Watching for consolidation support data.
*   **CLF (Steel):** Early-Month Bottomer. The Steel Forge. Dense support near price (45-71% hold rates, 7-15 tests each). Active limits pending.
*   **SEDG (Solar):** Early-Month Bottomer. The Solar Swinger. Dead zone at $32-$35, waiting for pullback to $29-$31 support.