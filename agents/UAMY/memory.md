# UAMY — Trade Log & Observations

## Trade Log

| Date | Action | Shares | Price | Running Total | Avg Cost | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Pre-2026-02-12 | BUY | 40 | $7.96 | 40 | $7.96 | Initial position (pre-strategy) |

## Observations
- Feb 12: Pulled back ~8-12% on "sell the news" after Idaho JV details (49% stake disappointed), federal price floor reversal, and profit-taking from 500%+ run.
- Feb 12: Broke below $7.85 long-term MA. Intraday low $7.22.
- Feb 13: Stabilized. Closed ~$7.79 (+5.5% from prior close). Intraday low $7.11. Alliance Global raised PT to $13.50.
- Feb 13: Original $7.03 limit order placed (Gemini advice). Did not fill.
- Feb 16: Wick offset analysis run. $7.01 support has only 25% hold rate — $7.03 order was at a weak level. Cancelled.
- Feb 16: Active pool exhausted ($318 deployed on 40 shares). Reserve plan activated with wick-adjusted levels.
- Technical scan: Neutral-Bearish (score -2). Below SMA 20/EMA 9/EMA 21. Stochastic oversold. ATR 15.6% — extremely volatile.
- Volume profile: POC at $8.19, VWAP at $8.76. Bought near POC, now below value area. Buy zone at $6.63-$7.25 shows 56% buy volume — institutional accumulation.

## Plan (Reserve Deployment)
- **Reserve 1:** 15 shares @ **$6.62** ($6.52 HVN support, wick-adjusted. Converges with Bollinger Lower $6.63.)
- **Reserve 2:** 16 shares @ **$6.22** ($6.04 HVN pre-rally base, wick-adjusted.)
- **Reserve 3:** Hold ~$100 dry powder for $5.95 washout (200-day MA zone) — only if structural support breaks.
- **Stop rule:** If $6.00 breaks on high volume, thesis is broken. Consider full exit.
- **Recovery target:** $8.76 (VWAP) for break-even+ on current 40 shares. If Reserve 1 fills, target drops to $8.35.

## Lessons
- Position entered before strategy system. Similar to IONQ — recovery mode.
- Original $7.03 limit violated strategy rule: always use wick_offset_analyzer, never place at raw support. The $7.01 level fails 75% of the time — deploying reserve capital there was poor risk management.
- Gemini's staggered entry concept was directionally correct but lacked data-driven precision. Our wick analyzer provides the edge.
