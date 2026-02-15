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

### The "Cycle" Awareness
*   **Monthly Rhythm:** Identify if the stock typically bottoms Early (Days 1-8), Mid (12-18), or Late (23-30) in the month.
*   **Do Not Chase:** If the "Low Window" has passed and price is mid-range, **WAIT** for the next cycle.

## Current Watchlist & Status
See `portfolio.json` for live positions/orders and run `python3 tools/portfolio_status.py` for a full report.

*   **NU (Fintech):** Mid-Month Bottomer. Growth Anchor.
*   **SOFI (Fintech/AI):** Binary Bottomer. AI Wildcard.
*   **AR (Energy):** Early-Month Bottomer. The Slow Cooker.
*   **KMI (Energy/Infrastructure):** Early-Month Bottomer. Dividend Fortress.
*   **STIM (MedTech):** Early-Month Bottomer. The Micro-Cap Swinger.