# Cycle Timing Review — 2026-03-17

## Verification Summary

| # | Check | Result |
| :--- | :--- | :--- |
| 1 | Math verification | PASS |
| 2 | Cooldown formula | PASS |
| 3 | Immediate fill consistency | PASS |
| 4 | LLM coverage | PASS |
| 5 | Recency + completeness | PASS |

**Result: 5/5 checks passed**

## Mechanical Check Details

### Check 1: Math verification
PASS — no issues found.

### Check 2: Cooldown formula
PASS — no issues found.

### Check 3: Immediate fill consistency
PASS — no issues found.

### Check 4: LLM coverage
PASS — no issues found.

### Check 5: Recency + completeness
- OKLO: [Minor] Most recent cycle is 252 days old (stale)

**Tickers verified:** ARM, LUNR, OKLO, SOUN

---

## Qualitative Assessment

### Per-Ticker Notes

**ARM**

The analyst correctly identifies the consistent $112.76 institutional floor and cites semiconductor tariff headwinds as support for the full cooldown. One gap: the 9 cycles cluster into two distinct windows — March 2025 (cycles 1-3) and Dec 2025-Jan 2026 (cycles 4-9) — with a 9-month gap between them. The analyst does not acknowledge this gap. The recent cluster of 6 cycles in a 5-week window (Dec 2025-Jan 2026) is the operationally relevant dataset; the March 2025 cycles add sample size but occurred under a different market regime. This does not change the cooldown, but the confidence framing should weight the recent cluster more heavily. Sell price of $125.88 is just below the $126.76 resistance — close enough that the cycle framework applies cleanly.

**LUNR**

The analyst's -8.7% +1d decay note is the most actionable qualitative observation in the report and is well-supported by the data. However, the "17 cycles" citation overstates effective sample size. Reviewing the log: cycles 1-4 share the same Feb 2025 dates, cycles 7-10 share 2026-02-04, cycles 11-14 share 2026-02-11, and cycles 15-17 share 2026-02-24 — each of these date clusters is a single market event with multiple resistance levels triggering simultaneously. Effective unique pullback events: approximately 7-8, not 17. The NORMAL confidence rating is still appropriate, but citing "largest dataset of this group" as a strength slightly overstates edge. The practical recommendation is unchanged. Sell prices ($18.54/$18.72) straddle the $18.62 resistance level — this is a proper resistance-exit scenario.

**OKLO**

The pre-critic Minor flag (252 days stale) deserves amplification here. OKLO's last cycle closed 2025-07-09; between then and now, the stock experienced the current sell event at $63.09 without any recorded intervening cycle. This 8-month gap encompasses significant NRC and DOE policy developments under the current administration — the context that makes OKLO trade is different today than in mid-2025. The +11.8% +10d recovery median is statistically valid but reflects market conditions from over 8 months ago. The analyst appropriately notes the $46.01 deep-touch backstop from cycles 4/5, which is important given the wide range ($46-$55) in the deep-touch levels. The 3d cooldown minimum is mechanically correct and the conservatism is appropriate given staleness. Sell at $63.09 is squarely in the $61.28-$63.45 resistance zone — clean cycle exit.

**SOUN**

One observation the analyst missed: SOUN was sold at $7.76 with a re-entry target of $7.74 — a $0.02 spread. This is not a resistance-exit scenario. The sell price sits well below the resistance cluster ($8.65-$9.04); the position was exited between cost basis and resistance as a mid-cycle profit take. The cycle framework, which presumes a sale at resistance followed by a decay toward support, does not fully apply here. Consequence: the re-entry target essentially equals the exit price, and the 3d cooldown may expire with the stock trading at or near $7.74 — meaning there is minimal additional decay to wait for. The analyst's compressed-inter-cycle observation (6 days between the last two resistance events) is correct and well-reasoned, but the non-resistance exit context should have been surfaced explicitly. Cooldown of 3d is still appropriate as a minimum "don't chase" buffer, but the re-entry window may be narrower than the framework implies.

### Override Assessment

No overrides were applied. This is credible: all 4 tickers show formula-minimum (3d) cooldowns with 100% fill rates, and no sector or regime condition rises to override threshold. The analyst appropriately treated LUNR's +1d decay as an execution note rather than a cooldown extension — that judgment is sound (the decay data supports waiting within the 3-day window, not extending beyond it).

### Cross-Ticker Observations

All 4 tickers land on the 3d minimum, which is an artifact of the `max(3, int(median_deep * 0.6))` formula: with median_deep=1d across the board, the formula yields max(3, 0)=3d for every ticker. This is mechanically correct but means the cooldown output is purely floor-driven — there is zero differentiation. The real differentiation lives in the decay profiles: LUNR's -8.7% at +1d vs. ARM's -1.2% is material execution guidance that the analyst captured well.

The batch also shows a sector clustering phenomenon — all 4 are high-beta names in AI-adjacent themes (semiconductor IP, space, nuclear power, AI voice). A broad AI/tech risk-off move would suppress all 4 simultaneously, which is relevant if the user is considering re-entering all 4 at once after the 3-day window. The analyst does not address cross-ticker correlation risk.

---

## Overall Verdict

**Verdict: PASS**

All 5 mechanical checks pass. Qualitative flags are informational rather than recommendation-changing: ARM's cycle gap is noted, LUNR's effective sample size is somewhat overstated, OKLO's staleness is Minor as classified, and SOUN's non-resistance exit context was missed by the analyst but does not invalidate the 3d cooldown. The uniform 3d result is mechanically correct. No overrides were warranted and none were applied incorrectly.
