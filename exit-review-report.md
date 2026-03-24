# Exit Review Report — 2026-03-18
*Generated: 2026-03-18 | Analyst: EXR-ANLST | Pre-analyst: exit_review_pre_analyst.py*

**Positions reviewed:** 10 | EXIT: 0, REDUCE: 0, HOLD: 2, MONITOR: 8 | Rule 3 overrides: none

---

## Exit Review Matrix

| Ticker | Days Held | Time Stop | P/L % | P/L $ | Target Dist | Earnings | Momentum | Squeeze | Verdict | Rule |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| IONQ | >60 days (pre-strategy) | EXCEEDED | -25.0% | -$166.80 | N/A | UNKNOWN | Neutral (+0) | N/A | **HOLD** | 10 |
| USAR | >60 days (pre-strategy) | EXCEEDED | -8.8% | -$28.35 | +17.1% | UNKNOWN | Neutral (+0) | N/A | **HOLD** | 10 |
| ACHR | 16 | WITHIN | -3.7% | -$22.08 | N/A | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |
| APLD | 29 | WITHIN | -5.3% | -$23.25 | +38.1% | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |
| CIFR | 1 | WITHIN | +1.8% | +$1.89 | N/A | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |
| CLF | 15 | WITHIN | -9.6% | -$50.73 | N/A | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |
| NNE | 13 | WITHIN | -6.5% | -$21.00 | N/A | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |
| NU | 33 | WITHIN | -10.1% | -$48.00 | +17.5% | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |
| TEM | 9 | WITHIN | -0.3% | -$0.14 | N/A | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |
| TMC | 5 | WITHIN | +1.0% | +$0.54 | N/A | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |

---

## Per-Position Detail

### IONQ — HOLD (Rule 10)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | EXCEEDED | >60 days (pre-strategy) days held (entered pre-2026) |
| Profit Target | BELOW | P/L -25.0%, No target (recovery) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=True, pre_strategy=True, reclassified=False
**Bullets:** 1/5 → still_building
**Verdict Trace:** Rule 10 — Recovery — default hold, time stop informational only

**Reasoning:** IONQ is a pre-strategy recovery position at -25.0% ($-166.80) with the time stop formally exceeded, but Rule 10 applies: for recovery-classified positions the time stop is informational only and the default is HOLD. The position carries significant drawdown against a $44.43 avg with current price around $33.34, yet only 1/5 bullets have been deployed — the recovery pool remains largely intact for cost-basis improvement on further weakness. The thesis stress-test (Wolfpack short report rebuttal, Feb 25 earnings) is the critical qualitative question, but the mechanical ruleset correctly defers exit on a recovery position until either a confirmed thesis break or an active sell signal materialises.

**Recommended Action:** Maintain position. Review earnings transcript and management commentary from Feb 25 to assess whether the Wolfpack rebuttal was substantive (specific technical counter-evidence, unchanged/raised guidance) or defensive (non-answers, deflection). If thesis is intact: hold and consider deploying B2 on next material support test. If thesis is broken: escalate to manual REDUCE outside this workflow.

**Rule 3 Note:** IONQ verdict is HOLD via Rule 10 (not a REDUCE). No Rule 3 override applicable.

---

### USAR — HOLD (Rule 10)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | EXCEEDED | >60 days (pre-strategy) days held (entered pre-2026-02-12) |
| Profit Target | BELOW | P/L -8.8%, target $23.05 (+17.1% to target) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=True, pre_strategy=True, reclassified=False
**Bullets:** 3/5 (pre-strategy), pool exhausted → fully_loaded
**Verdict Trace:** Rule 10 — Recovery — default hold, time stop informational only

**Reasoning:** USAR is a recovery position at -8.8% ($-28.35) with time stop exceeded, but Rule 10 governs: time stop is informational for recovery positions. At -8.8% the drawdown is moderate and the target distance of +17.1% to $23.05 is achievable within a normal swing cycle — this is not a distressed situation. The bullets_used flag shows the pre-strategy reserve is fully deployed (pool exhausted), meaning no further cost-basis improvement is possible; patience is the only remaining tool.

**Recommended Action:** Maintain position. No further orders to place — pool is exhausted. Continue standard tracking; exit naturally when price reaches $23.05 or above. No broker action required today.

---

### ACHR — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 16 days held (entered 2026-03-02) |
| Profit Target | BELOW | P/L -3.7%, No target (recovery) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 5/5 → fully_loaded
**Verdict Trace:** Rule 16 — Within time window — standard tracking

**Reasoning:** ACHR is 16 days in with a mild -3.7% drawdown and a fully-loaded bullet stack (5/5). Time stop is within window and no exit trigger fires. The pre-analyst flags an opportunity cost note — at ~4d/cycle, 4 cycles could theoretically have completed in this window — but the position is fully loaded and not at a loss threshold that warrants forced action.

**Recommended Action:** No action. Continue standard tracking. Monitor price for profit target approach; if ACHR stalls at current level through the 60-day mark, escalate to formal exit review.

---

### APLD — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 29 days held (entered 2026-02-17) |
| Profit Target | BELOW | P/L -5.3%, target $38.00 (+38.1% to target) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 5/5 → fully_loaded
**Verdict Trace:** Rule 16 — Within time window — standard tracking

**Reasoning:** APLD is 29 days in at -5.3% with a $38.00 target requiring +38.1% recovery — a wide gap that warrants attention even though the time stop hasn't been reached. The knowledge store flags the NVIDIA stake sale (filed Feb 17) as a known headwind against the thesis. The position is fully loaded with 5/5 bullets; opportunity cost is mounting (~7 cycles foregone), and the path to target is long in a stock facing institutional overhang.

**Recommended Action:** No mechanical action today (Rule 16). Flag for early escalation if price does not show upward momentum by day 45. Begin reviewing whether the NVIDIA divestment permanently resets APLD's valuation narrative before the formal time stop triggers.

---

### CIFR — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 1 days held (entered 2026-03-17) |
| Profit Target | BELOW | P/L +1.8%, No target (recovery) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 1/5 → still_building
**Verdict Trace:** Rule 16 — Within time window — standard tracking

**Reasoning:** CIFR is a brand-new position entered yesterday (1 day held) showing a small +1.8% gain out of the gate. With only 1/5 bullets deployed and ample room to build, this position is in the earliest possible stage — no exit criteria are remotely relevant. Standard monitoring is the correct posture.

**Recommended Action:** No action. Continue standard tracking. Queue remaining bullets per bullet_recommender.py on next support test.

---

### CLF — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 15 days held (entered 2026-03-03) |
| Profit Target | BELOW | P/L -9.6%, No target (recovery) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 6/5 → fully_loaded
**Verdict Trace:** Rule 16 — Within time window — standard tracking

**Reasoning:** CLF is 15 days in at -9.6% ($-50.73) with bullets over-deployed (6/5) and no defined profit target, meaning recovery depends entirely on price action. At -9.6% without a structured exit plan the position is relying on mean reversion; no additional bullets are available to improve cost basis further.

**Recommended Action:** No action today (time stop within window, Rule 16). Flag CLF as approaching the threshold for escalation — if drawdown deepens past -12% or the 60-day window approaches without recovery, initiate a formal exit decision ahead of the time stop. No additional bullets available; no broker action required.

---

### NNE — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 13 days held (entered 2026-03-05) |
| Profit Target | BELOW | P/L -6.5%, No target (recovery) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 6/5 → fully_loaded
**Verdict Trace:** Rule 16 — Within time window — standard tracking

**Reasoning:** NNE is 13 days in at -6.5% with bullets fully maxed (6/5). The drawdown is moderate and within normal mean-reversion range for a nuclear energy name in the current macro environment. Time stop is well within window and no exit trigger fires.

**Recommended Action:** No action. Continue standard tracking. No additional bullets available. Monitor for price recovery toward entry levels.

---

### NU — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 33 days held (entered 2026-02-13) |
| Profit Target | BELOW | P/L -10.1%, target $16.75 (+17.5% to target) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 6/5 → fully_loaded
**Verdict Trace:** Rule 16 — Within time window — standard tracking

**Reasoning:** NU is 33 days in at -10.1% ($-48.00) with a +17.5% gap to the $16.75 target and bullets maxed out — the most time-pressured MONITOR in the portfolio. At 33 days the time stop window is more than half consumed; with 6/5 bullets deployed there's no remaining cost-basis lever. The pre-analyst notes ~8 missed cycles of opportunity cost.

**Recommended Action:** No action today. However, NU is approaching an inflection point — if price does not show recovery by day 45–50, escalate to exit review ahead of the formal 60-day stop. Begin watching for NU catalyst (Brazil macro, Nubank earnings) to reassess whether +17.5% to target is realistic in the remaining window.

---

### TEM — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 9 days held (entered 2026-03-09) |
| Profit Target | BELOW | P/L -0.3%, No target (recovery) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 1/5 → still_building
**Verdict Trace:** Rule 16 — Within time window — standard tracking

**Reasoning:** TEM is 9 days in at essentially flat (-0.3%, -$0.14) with only 1/5 bullets deployed. The position is in the early building phase with minimal drawdown and substantial room to add on weakness. No exit pressure of any kind applies here.

**Recommended Action:** No action. Continue standard tracking. Queue remaining bullets per bullet_recommender.py on next support test.

---

### TMC — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 5 days held (entered 2026-03-13) |
| Profit Target | BELOW | P/L +1.0%, No target (recovery) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 1/5 → still_building
**Verdict Trace:** Rule 16 — Within time window — standard tracking

**Reasoning:** TMC is 5 days in with a small +1.0% gain, 1/5 bullets deployed, and a prior successful cycle on record (+6.9% from $5.86 avg per knowledge store). The position is tracking positively in its early stage and no exit criteria are relevant. Standard monitoring applies.

**Recommended Action:** No action. Continue standard tracking. Queue remaining bullets per bullet_recommender.py. If price extends above the prior $6.26 exit level, consider whether to trail a stop.

---

## Cross-Check Results

| Check | Result | Detail |
| :--- | :--- | :--- |
| All 8 invariant checks | PASS | No violations found |

---

## Capital Rotation

No capital rotation needed at this time. Zero EXIT or REDUCE verdicts — no capital freed today.

---

## Executive Summary

Ten positions reviewed across the full portfolio; the ruleset produced 2 HOLD verdicts (IONQ and USAR — both pre-strategy recovery positions with exceeded time stops treated as informational under Rule 10) and 8 MONITOR verdicts (all within their 60-day windows). No exits or reduces are mechanically triggered today, and all 8 invariant cross-checks passed clean. The critical manual action is a qualitative thesis check on IONQ: the -25.0% drawdown with 1/5 bullets remaining makes the Feb 25 earnings quality the deciding factor for whether to hold and continue building or escalate to a manual reduce.

---

## Prioritized Recommendations

1. **IONQ — Thesis check (urgent, manual):** Confirm whether Feb 25 earnings management commentary constituted a substantive rebuttal of the Wolfpack short report. If yes: maintain HOLD, plan B2 deployment on next support test. If no: escalate to manual REDUCE outside this workflow.

2. **NU — Watch window closing:** 33 days in, -10.1%, +17.5% to target, pool exhausted. Set escalation trigger at day 45 if no price recovery begins. Monitor Brazil macro and Nubank earnings catalyst timing.

3. **CLF — Drawdown watch:** -9.6% with 6/5 bullets, no defined target. Set personal alert at -12% for early escalation. No broker action today.

4. **APLD — Long path to target:** +38.1% gap to $38.00 with NVIDIA institutional overhang. Flag for escalation if no upward momentum by day 45.

5. **USAR — No action required:** Passive recovery, pool exhausted, wait for $23.05 naturally.

6. **ACHR, NNE, CIFR, TEM, TMC — Standard tracking:** All within early window, no immediate concerns. For CIFR, TEM, TMC (1/5 bullets each): deploy remaining bullets via bullet_recommender.py on next support test.
