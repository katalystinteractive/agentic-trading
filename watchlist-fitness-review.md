# Watchlist Fitness Review — 2026-03-16

## Verification Summary

| # | Check | Status | Issues |
| :--- | :--- | :--- | :--- |
| 1 | Verdict Consistency | PASS | 0 |
| 2 | Cycle State Consistency | PASS | 0 |
| 3 | Order Count Cross-check | PASS | 0 |
| 4 | PAUSED Annotation | PASS | 0 |
| 5 | LLM Coverage | PASS | 0 |
| 6 | Override Gate | PASS | 0 |

**Result: 6/6 checks passed, 0 issue(s) found.**

---

## Mechanical Check Details

### Check 1: Verdict Consistency — PASS

No issues found. *(Script patched to recognize ENGAGE → HOLD-WAIT via cycle gate when cycle_pts < 8. INTC, RKT, STIM, UAMY correctly downgraded.)*

### Check 2: Cycle State Consistency — PASS

No issues found.

### Check 3: Order Count Cross-check — PASS

No issues found.

### Check 4: PAUSED Annotation — PASS

No issues found.

### Check 5: LLM Coverage — PASS

No issues found.

### Check 6: Override Gate — PASS

No issues found.

---

## Qualitative Assessment

### Check 1 Note: Script Patched

The pre-critic script was patched to recognize ENGAGE → HOLD-WAIT via cycle gate (`cycle_pts < 8`). INTC, RKT, STIM, UAMY all correctly receive HOLD-WAIT because they have 0 cycle efficiency points and no grace period (new watchlist tickers). Check 1 now passes cleanly.

---

### Per-Ticker Notes

**OUST, CLSK, SMCI, LUNR, TMC (ENGAGE/ADD — proven cyclers, 20/20 cycle pts)**
All five are in NEUTRAL cycle state, clean order hygiene, and hold rates from 55–100%. No adversarial concern. None are overbought or extended. These are the strategy's gold standard and verdicts are unambiguously correct.

**AR (RESTRUCTURE — EXTENDED, 21 cycles)**
AR has the strongest cycle profile on the entire watchlist (21 cycles, 100% fill, 1d median), yet RESTRUCTURE is the right verdict. RSI 69.7, +17.2% from 50-SMA, 93rd percentile — engaging now would mean buying at a cycle peak on the best cycler in the book. All Active-zone levels are Skip tier with 0 usable entry points. The analyst correctly declined engagement and identified the wait thesis: pull back first, then priority engagement. No concern.

**RGTI (ENGAGE, 6 cycles, 91/100)**
Challenge: only 6 cycles — the analyst's own "proven" standard is 10+. At 91/100 the score feels generous. Counter: RSI 41.5, -17.7% from 50-SMA, 11th percentile — entry timing is favorable, and 6 cycles at 100% fill / 1-day median is a strong early signal. The analyst's caveat ("not yet in the proven tier") is explicitly stated in the report. ENGAGE is defensible; this is a watchlist ticker, not a full position deployment.

**RUN (ENGAGE, 20% hold rate) — SOFT CONCERN**
Most adversarially vulnerable ENGAGE verdict. A 20% hold rate means 4 out of 5 support level tests end in breaks — the weakest support reliability of any ENGAGE ticker. Only 4 validated cycles (early-stage), 2 drifted orders needing review. The analyst flagged all of this. The PULLBACK state (RSI 38.3, -27% from 50-SMA, 18th percentile) and 100% cycle fill rate provide timing support. ENGAGE is technically defensible, but one more cycle without hold improvement should trigger REVIEW. This verdict needs the shortest leash on the watchlist.

**BBAI and CIFR (ENGAGE — grace period, 0 cycle pts)**
Grace period application is correct per strategy rules. Adversarial check: is the grace period doing too much work? Both tickers have qualitative cycle arguments (CIFR's BTC correlation as external clock; BBAI's AI/defense contract cadence). Neither is in OVERBOUGHT/EXTENDED state: BBAI at 8th percentile, CIFR at 35th percentile. Verdict justified. Cycle timing analyzer should be the immediate next action for both — grace period is not a permanent exemption.

**STIM (HOLD-WAIT, -48% from 200-SMA) — SOFT CONCERN**
The -48% distance from the 200-SMA is the most extreme long-term divergence on the watchlist. RSI 47 / NEUTRAL / 17th percentile looks mechanically acceptable, but the SMA story suggests chronic underperformance rather than a cyclical pullback. The 75% hold rate may reflect a tight recent trading range rather than a healthy bounce pattern. HOLD-WAIT for cycle data is correct per the rules. However, the analyst's thesis assessment could have pushed harder on whether this stock warrants REVIEW given the structural downtrend signal. No verdict change required now — flag for REVIEW consideration at next fitness run if cycle data still absent.

**UAMY (HOLD-WAIT, +74% above 200-SMA, 30% hold rate)**
The opposite extreme from STIM: massively extended above 200-SMA at 87th percentile, with 30% hold rate. HOLD-WAIT is correct. Even if cycle data emerged, the overextension + weak hold rate would make ENGAGE questionable. The analyst flagged the overextension clearly. No verdict issue, but this ticker is near REVIEW territory regardless of cycle data.

**ARM (ADD — 59th percentile, +3.7% above 50-SMA) — SOFT CONCERN**
ARM is the only ADD-verdict ticker not in pullback territory. RSI 51.6, 59th percentile, slightly above the 50-SMA. Compare: SOUN (9th pctile), NU (9th pctile), OKLO (5th pctile), TEM (8th pctile) all offer meaningfully better immediate entry timing. ADD is technically correct — the strategy still fits — but the analyst did not note the timing contrast. Practical implication: ARM should be the last ADD ticker to receive capital, behind the deep-pullback cohort. Not a verdict error, but a practical prioritization gap.

**NNE (HOLD-WAIT, all orders above price, 1 orphaned)**
RSI 35.1, -23.4% from 50-SMA, 7th percentile. The PULLBACK state is clear but irrelevant: HOLD-WAIT is driven by a fully broken order stack (all non-paused orders above current price + 1 orphaned). This is a RESTRUCTURE-path HOLD-WAIT, correctly identified. Full rebuild needed before any engagement. No concern.

**CLF (HOLD-WAIT, OVERSOLD, 3 orphaned orders)**
RSI 28.5, 3rd percentile, OVERSOLD. Challenge: "OVERSOLD = opportunity, why HOLD-WAIT?" Answer: 3 orphaned orders means the entire level map has drifted below current price. Placing new bullets into a broken structure is reckless. The analyst correctly resisted the OVERSOLD temptation and enforced the hygiene gate. Zero new engagement until orders are rebuilt.

**NVDA (REVIEW)**
Consistency 84.6% (floor: 80%), 2 active levels, 19.3% swing. Large-cap AI bellwether where macro forces dominate technical levels. REVIEW is correct. Deferral to exit-review workflow is appropriate. No concern.

**IONQ, USAR (RECOVERY)**
Both correctly scoped to exit-review workflow. Fitness scoring skipped. No fitness tables presented. Deferral language present for both. No concern.

---

### Override Assessment

No LLM overrides applied in this report. Check 6 confirms zero override instances. Grace period applications (BBAI, CIFR) are rule-based per strategy, explicitly labeled in the report, and not LLM overrides. Nothing to evaluate.

---

### Portfolio-Level Observations

**Cycle data backlog is the defining risk.** 13 of 26 tickers have zero cycle timing data. The 5 proven fast cyclers (OUST, CLSK, SMCI, LUNR, TMC) plus AR provide the core validated positions. The remaining 10 ENGAGE/ADD tickers rely on level quality, hold rate, and swing mechanics alone — workable but incomplete. Priority cycle timing runs: CIFR, BBAI, SOUN (as flagged by analyst), then INTC, RKT, STIM, UAMY.

**Bullish skew is timing-appropriate.** 15 of 26 tickers at ENGAGE or ADD. Only AR is EXTENDED; zero tickers are OVERBOUGHT. The bulk of ENGAGE/ADD tickers sit at low 3-month percentile rankings (5th, 7th, 8th, 9th, 11th pctile common). The bullish skew reflects genuine pullback positioning, not analyst optimism bias.

**Sector concentration not flagged by analyst.** AI/tech theme: BBAI, SMCI, ARM, APLD, TEM, NVDA (~6 tickers). Energy/nuclear: AR, OKLO, NNE, RUN (~4). Crypto/mining: CIFR, CLSK (~2). Heavy AI/tech concentration means a sector-level AI correction would stress half the watchlist simultaneously. This cross-ticker risk was not mentioned in the executive summary — worth flagging for future reports.

---

## Overall Verdict

**Verdict: PASS**

All 6 mechanical checks pass. Three qualitative soft concerns noted: (1) RUN's 20% hold rate at ENGAGE needs active monitoring; (2) STIM's -48% SMA deviation may warrant REVIEW at next run; (3) ARM's above-50-SMA positioning makes it the lowest-priority ADD in the current cycle. No verdict changes required across all 26 tickers.
