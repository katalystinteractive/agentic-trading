# IONQ — Trade Log & Observations

## Trade Log

| Date | Action | Shares | Price | Running Total | Avg Cost | Notes |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Pre-2026 | BUY | 13 | $46.45 | 13 | $46.45 | Original position (pre-strategy) |
| 2026-02-12 | BUY | 2 | $31.025 | 15 | $44.39 | Tranche 1 partial — caught day low, bounced to $31.09 |

## Observations
- Feb 12: Price tested $31.02 (day low) and bounced immediately — institutional buy wall confirmed at $31.
- Feb 13: Intraday swing from $30.85 to $34.18 (~10%). "Hammer" candle formed — classic bullish reversal signal.
- Gemini noted JPMorgan +648% and Deutsche Bank +56.4% but these could NOT be verified through yfinance data. Treat as directional only.
- Verified via yfinance: Norges Bank +66.7%, Vanguard +18.5%, BlackRock +33.8%, Morgan Stanley +29.9%. 9/10 top holders accumulating.

## Observations (continued)
- **2026-02-18 News:** Price $33.34 (-24.9% from avg $44.39). Earnings Feb 25. Multiple headwinds converging: (1) Fraud probe collides with $1.8B SkyWater deal — exec scrutiny intensifying, (2) Morgan Stanley cut stake per 13F — adds to institutional exit narrative, (3) Short-seller report pressure continuing, (4) Down 33% in past month. Zacks consensus: Q4 EPS -$0.48 (+48% YoY improvement), revenue $40.3M (+244% YoY). New competitor Infleqtion (INFQ) went public Feb 17. T1 remaining at $30.42 is 8.7% below current. Sentiment: Neutral (30% positive, 20% negative). Earnings next week is the key binary event.

## Lessons
- Only deployed half of Tranche 1 — disciplined restraint preserved dry powder for deeper dip or earnings play.
- LLM institutional claims need cross-verification. Overall direction was correct (institutions buying) but specific numbers were unverifiable.

## Plan (Gemini's 3-Tranche System)
Wick-adjusted buy prices from `wick_analysis.md` (run 2026-02-15):
- **T1 remaining:** Deploy at **$30.42** (Buy At for $29.55 support, 33% hold rate). ~3 shares.
- **T1 alt:** If $30 breaks on volume, redirect to **$26.27** (Buy At for $25.92 support, 20% hold rate). ~3 shares.
- **T2 (50%):** Post-Feb 25 earnings. Only if management rebuts short report convincingly. Level TBD post-earnings — re-run wick analyzer.
- **T3 (30%):** Trend confirmation — price holds above 20-day MA (~$35) for 2+ days.
- **Stop rule:** If $30 breaks on high volume, cancel all buys, wait for washout at $25.92-$26.27 zone.
