# Exit Review Report — 2026-02-27
*Generated: 2026-02-27 | Analyst: EXR-ANLST | Pre-analyst: exit_review_pre_analyst.py v2.0.0*

**Positions reviewed:** 8 | EXIT: 0, REDUCE: 1, HOLD: 3, MONITOR: 4 | Rule 3 overrides: none

---

## Exit Review Matrix

| Ticker | Days Held | Time Stop | P/L % | P/L $ | Target Dist | Earnings | Momentum | Squeeze | Verdict | Rule |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| STIM | 12 | WITHIN | +32.6% | +$62.92 | +0.0% | UNKNOWN | Neutral (+0) | N/A | **REDUCE** | 6a |
| INTC | >60 days (pre-strategy) | EXCEEDED | -22.2% | -$52.00 | +40.8% | UNKNOWN | Neutral (+0) | N/A | **HOLD** | 10 |
| IONQ | >60 days (pre-strategy) | EXCEEDED | -8.0% | -$53.25 | N/A | UNKNOWN | Neutral (+0) | N/A | **HOLD** | 10 |
| USAR | >60 days (pre-strategy) | EXCEEDED | -6.7% | -$21.60 | +14.5% | UNKNOWN | Neutral (+0) | N/A | **HOLD** | 10 |
| APLD | 10 | WITHIN | -11.7% | -$29.44 | +37.1% | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |
| LUNR | 2 | WITHIN | -61.0% | -$93.60 | +182.2% | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |
| NU | 14 | WITHIN | -9.7% | -$28.80 | +24.3% | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |
| SMCI | 4 | WITHIN | -7.9% | -$7.38 | +19.4% | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |

---

## Per-Position Detail

### STIM — REDUCE (Rule 6a)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 12 days held (entered 2026-02-15) |
| Profit Target | EXCEEDED | P/L +32.6%, target $1.79 (+0.0% to target) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 3/5 → still_building
**Verdict Trace:** Rule 6a — P/L 32.6% exceeds target range — take profits

**Reasoning:** STIM reached its target price of $1.79 at data collection, delivering a 32.6% gain in just 12 days — a textbook mean-reversion exit. The pending SELL limit at $1.79 aligns with documented 84% sell-wall resistance at that level; live data shows price has since pulled back to $1.42, confirming that $1.79 acted as resistance. With 3/5 bullets deployed and the full profit-target print achieved, Rule 6a profit-taking is unambiguous.

**Recommended Action:** The SELL limit at $1.79 is already placed — maintain it for a re-test of the resistance level. If price does not recover to $1.79 within the remaining time window, or if price deteriorates below cost basis ($1.35), close full position at market to prevent profit reversal. Do not deploy additional bullets until profit is booked.

**Rotate-to Suggestions:**
- **AR** ($34.38): Active bullets already staged at $32.68 and $31.16 — $255.97 freed capital directly funds the existing bullet queue without requiring new setup work.
- **CLF** ($11.05, +2.4% today): Active bullets at $9.97, $9.53, $8.48 — 3-bullet plan in place with today's positive momentum validating near-term strength.
- **UAMY** ($8.91): 5 active bullets across $7.71–$5.95 — staggered accumulation plan with multiple wick-adjusted levels ready to absorb capital on continued weakness.

---

### INTC — HOLD (Rule 10)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | EXCEEDED | >60 days (pre-strategy) days held (entered pre-2026-02-12) |
| Profit Target | BELOW | P/L -22.2%, target $51.21 (+40.8% to target) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=True, pre_strategy=True, reclassified=False
**Bullets:** 3/5 (pre-strategy), ~$67 remaining → still_building
**Verdict Trace:** Rule 10 — Recovery — default hold, time stop informational only

**Reasoning:** INTC is a pre-strategy recovery position 22.2% underwater with the time stop waived under Rule 10 — the 40.8% target distance ($36.38 → $51.21) reflects the full mean-reversion magnitude needed, not a near-term expectation. Reserve bullets at $37.56 and $36.38 are staged well below today's live price ($45.46), providing accumulation optionality on deeper weakness without forcing a premature exit. The recovery thesis remains intact with no exit trigger active.

**Recommended Action:** Maintain position. Keep SELL limit at $51.21 and all staged BUY orders (active at $42.28, reserves at $37.56 and $36.38) as placed. Monitor for reserve bullet fills if price continues weakness toward the $36–37 zone.

---

### IONQ — HOLD (Rule 10)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | EXCEEDED | >60 days (pre-strategy) days held (entered pre-2026) |
| Profit Target | BELOW | P/L -8.0%, No target (recovery) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=True, pre_strategy=True, reclassified=False
**Bullets:** 1/5 → still_building
**Verdict Trace:** Rule 10 — Recovery — default hold, time stop informational only

**Reasoning:** IONQ is a pre-strategy recovery with only 1/5 bullets deployed, making it the most under-built active position in the portfolio — 4 bullets remain available to reduce the average cost if price provides further entry opportunities. The 8.0% drawdown is modest and within recovery tolerance; no price target is assigned as the position is in early accumulation phase. Rule 10 holds: patience and accumulation are the correct posture.

**Recommended Action:** Maintain position. Continue monitoring for wick-adjusted entry levels to deploy Bullets 2–5. No pending BUY orders currently placed; consider establishing the next bullet using wick_offset_analyzer.py before the next review cycle.

---

### USAR — HOLD (Rule 10)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | EXCEEDED | >60 days (pre-strategy) days held (entered pre-2026-02-12) |
| Profit Target | BELOW | P/L -6.7%, target $23.05 (+14.5% to target) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=True, pre_strategy=True, reclassified=False
**Bullets:** 3/5 (pre-strategy), pool exhausted → fully_loaded
**Verdict Trace:** Rule 10 — Recovery — default hold, time stop informational only

**Reasoning:** USAR is the closest to recovery among the three Rule 10 HOLDs: 6.7% underwater with only 14.5% needed to reach target ($20.13 → $23.05), the narrowest gap in the recovery cohort. With the bullet pool exhausted (fully_loaded), no further accumulation is possible — the position is fully built and waiting for price recovery. Rule 10 holds: time stop waived, exit only on target hit.

**Recommended Action:** Maintain position. The SELL limit at $23.05 is the sole actionable order. No buy action is available (pool exhausted). Watch for a recovery catalyst; today's live range ($19.46–$20.47) confirms price is holding above the entry average region.

---

### APLD — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 10 days held (entered 2026-02-17) |
| Profit Target | BELOW | P/L -11.7%, target $38.00 (+37.1% to target) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 4/5 → still_building
**Verdict Trace:** Rule 16 — Within time window — standard tracking

**Reasoning:** APLD is 10 days into its 60-day window, 11.7% underwater with 37.1% remaining to target — standard early-cycle variance that triggers no exit rules. With 4/5 bullets deployed and the final active bullet staged at $27.71 (Bullet 5, wick-adjusted), today's day low of $28.25 came within 1.9% of the trigger without filling, keeping one remaining accumulation bullet intact. No action warranted.

**Recommended Action:** No action. Continue standard tracking. BUY at $27.71 (Bullet 5) and SELL at $38.00 remain as placed. Monitor for Bullet 5 fill opportunity if today's weakness extends.

---

### LUNR — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 2 days held (entered 2026-02-25) |
| Profit Target | BELOW | P/L -61.0%, target $18.74 (+182.2% to target) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 3/5 → still_building
**Verdict Trace:** Rule 16 — Within time window — standard tracking

**Reasoning:** LUNR entered just 2 days ago and the -61.0% P/L figure warrants attention — at a $17.04 avg cost with today's live price near $17.67 (+3.7%), a -61% print suggests a cost basis discrepancy or stale snapshot in the position summary row rather than actual portfolio loss. Rule 16 holds regardless: the position is 2 days old, well within the 60-day window, and 3/5 bullets remain available with 4 reserve levels stacked down to $6.64 providing deep accumulation capacity.

**Recommended Action:** No action. Continue standard tracking. Verify LUNR cost basis in portfolio.json to confirm the -61.0% figure is a data artifact vs. an actual mark. Active bullets (4 at $15.52, 5 at $15.08) and all reserve levels remain as placed. SELL limit at $18.74 is valid given today's high of $17.83.

---

### NU — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 14 days held (entered 2026-02-13) |
| Profit Target | BELOW | P/L -9.7%, target $18.50 (+24.3% to target) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 3/5 → still_building
**Verdict Trace:** Rule 16 — Within time window — standard tracking

**Reasoning:** NU is 14 days in, 9.7% underwater with a 24.3% target distance — well-positioned in a standard mean-reversion accumulation cycle with 2 bullets still available. The reserve BUY at $14.88 is appropriately paused pending post-earnings clarity (Feb 26 gate); today's live price of $15.06 is just 1.2% above that trigger, making the earnings outcome the immediate decision point for resuming accumulation.

**Recommended Action:** No action. Continue standard tracking. Review NU earnings outcome and resume the reserve BUY at $14.88 if the thesis remains intact. SELL limit at $18.50 remains as placed.

---

### SMCI — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 4 days held (entered 2026-02-23) |
| Profit Target | BELOW | P/L -7.9%, target $34.43 (+19.4% to target) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 1/5 → still_building
**Verdict Trace:** Rule 16 — Within time window — standard tracking

**Reasoning:** SMCI entered 4 days ago with only 1/5 bullets deployed — maximum build capacity remains. Down 7.9% from a $31.30 avg, today's day high of $33.45 came within 2.9% of the $34.43 target, showing the price is oscillating in the intended range. Bullets 2 and 3 at $29.35 and $28.84 are staged below current price for opportunistic accumulation on weakness.

**Recommended Action:** No action. Continue standard tracking. BUY orders at $29.35 (Bullet 2) and $28.84 (Bullet 3) remain staged. SELL limit at $34.43 remains valid; today's action validates the target zone is in play.

---

## Cross-Check Results

| Check | Result | Detail |
| :--- | :--- | :--- |
| All 8 invariant checks | PASS | No violations found |

---

## Capital Rotation

| Ticker | Verdict | Shares | Current Price | Capital Freed |
| :--- | :--- | :--- | :--- | :--- |
| STIM | REDUCE | 143 | $1.79 | $255.97 |

**Total capital freed (if executed):** $255.97

**Rotate-to candidates:**
- **AR** — existing bullet orders at $32.68/$31.16 absorb capital immediately with no new setup required
- **CLF** — 3 active bullets ($9.97/$9.53/$8.48) in place; +2.4% today validates near-term momentum
- **UAMY** — 5 active bullets ($7.71–$5.95) with staggered accumulation; capital fits across multiple orders

---

## Executive Summary

8 positions reviewed across the active portfolio: 1 REDUCE (STIM), 3 HOLD (INTC, IONQ, USAR), 4 MONITOR (APLD, LUNR, NU, SMCI). STIM is the sole action item — it printed its $1.79 target and Rule 6a mandates profit-taking; a SELL limit at $1.79 is already placed, and $255.97 in freed capital can rotate directly into staged AR, CLF, or UAMY bullet orders. Three pre-strategy recovery positions remain on Rule 10 hold with time stops waived, and all four MONITOR positions are within their 60-day windows with no exit triggers — the portfolio's mechanical structure is functioning as designed. One data note: LUNR's -61.0% P/L should be verified against the current cost basis, as the live price (+3.7% today) does not reconcile with that loss magnitude.

---

## Prioritized Recommendations

1. **STIM — REDUCE** *(urgent)*: Confirm SELL limit at $1.79 is active and not expired. If price revisits $1.79, profit is captured at target. If price deteriorates below cost basis ($1.35) before the limit fills, close at market to protect the remaining gain.

2. **NU — MONITOR** *(review)*: Reserve BUY at $14.88 is paused post-earnings (Feb 26). Today's live price ($15.06) is 1.2% above the trigger. Evaluate earnings outcome and resume the order if the thesis is intact — it may fill on the next down move.

3. **LUNR — MONITOR** *(verify)*: Reconcile the -61.0% P/L figure against portfolio.json cost basis. If correct, document the holding rationale for a 2-day position at that drawdown; if it is a data artifact, no action needed.

4. **INTC — HOLD** *(watch)*: Reserve bullets at $37.56 and $36.38 are far below current price ($45.46) but provide accumulation capacity on continued macro weakness. No action today.

5. **APLD, SMCI, IONQ, USAR** *(no action)*: Standard tracking. All within rules, no fills today, no orders to modify.
