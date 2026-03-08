# Deep Dive Review — TMC — 2026-02-26

## Verdict: PASS

## Verification Summary

| Check | Result | Details |
| :--- | :--- | :--- |
| Bullet Math | PASS | All 8 bullets (B1–B5, R1–R3) — shares and costs correct within tolerance |
| Tier Classifications | PASS | All tiers match strategy.md thresholds; $3.93 tool error correctly overridden by analyst |
| Zone Assignments | PASS | $4.74 PA correctly labelled "Active" in updated identity.md; overflow to R1 documented |
| Price Accuracy | PASS | All buy-ats match raw wick data; no bullet at exact raw support; dead zone excluded |
| Budget Compliance | PASS | Active $288.57 / $300; Reserve $297.95 / $300; counts 5/5 + 3/3 |
| Format Compliance | PASS | Headings, persona pattern, table alignment, bullet format, status label all correct |
| Portfolio.json | N/A | EXISTING ticker — 8 orders and watchlist entry consistent with identity.md |

## Bullet Math Detail

**Capital configuration:** Active Full/Std ~$60; Active Half ~$30; Reserve ~$100

### Active Bullets

| Bullet | Buy Price | Tier | Expected Shares | Actual Shares | Expected Cost | Actual Cost | Result |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| B1 | $6.26 | Full ($60) | floor(60/6.26) = 9 | 9 | $56.34 | ~$56 | PASS |
| B2 | $5.90 | Full ($60) | floor(60/5.90) = 10 | 10 | $59.00 | ~$59 | PASS |
| B3 | $5.63 | Std ($60) | floor(60/5.63) = 10 | 10 | $56.30 | ~$56 | PASS |
| B4 | $5.43 | Std ($60) | floor(60/5.43) = 11 | 11 | $59.73 | ~$60 | PASS |
| B5 | $5.20 | Std ($60) | floor(60/5.20) = 11 | 11 | $57.20 | ~$57 | PASS |

### Reserve Bullets

| Bullet | Buy Price | Expected Shares | Actual Shares | Expected Cost | Actual Cost | Result |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| R1 | $4.93 | floor(100/4.93) = 20 | 20 | $98.60 | ~$99 | PASS |
| R2 | $4.75 | floor(100/4.75) = 21 | 21 | $99.75 | ~$100 | PASS |
| R3 | $1.66 | floor(100/1.66) = 60 | 60 | $99.60 | ~$100 | PASS |

**Active total:** $288.57 / $300 — PASS
**Reserve total:** $297.95 / $300 — PASS

## Zone Assignment Detail

| Metric | Value |
| :--- | :--- |
| Monthly swing | 53.0% |
| Active radius | 53.0% / 2 = 26.5% |
| Current price | $6.39 |
| Active floor | $6.39 × (1 − 0.265) = **$4.697** |

Zone classification uses raw support price:

| Raw Level | Raw Level vs. Floor | Zone (raw data) | Zone (identity.md) | Result |
| :--- | :--- | :--- | :--- | :--- |
| $6.06 HVN+PA | $6.06 ≥ $4.697 | Active | Active | PASS |
| $5.79 HVN+PA | $5.79 ≥ $4.697 | Active | Active | PASS |
| $5.53 HVN+PA | $5.53 ≥ $4.697 | Active | Active | PASS |
| $5.26 HVN+PA | $5.26 ≥ $4.697 | Active | Active | PASS |
| $4.99 HVN+PA | $4.99 ≥ $4.697 | Active | Active | PASS |
| $4.74 PA | $4.74 ≥ $4.697 | Active | Active | PASS |
| $4.57 PA | $4.57 < $4.697 | Reserve | Reserve | PASS |
| $1.60 PA | $1.60 < $4.697 | Reserve | Reserve | PASS |

**Active count:** 5 bullets / 5 max — PASS. $4.74 active-zone level overflows capacity; routed to R1. ✓
**Reserve count:** 3 bullets / 3 max — PASS

## Issues Found

No issues found.

## Notes

1. **Previous review ISSUES resolved:** An earlier run of this review flagged $4.74 PA zone label as "Reserve" in the identity.md table. The analyst corrected this during the 2026-02-26 compile pass — identity.md now correctly shows "Active" for $4.74 PA with an Active Overflow note explaining the R1 assignment. Zone check now passes.

2. **$3.93 PA tier anomaly (not an identity error):** Raw data labels $3.93 PA as "Half" tier despite 50% hold rate (2 approaches, 1 held). Identity correctly labels it "Full" per strategy.md (50%+ = Full). The raw data tier appears to reflect a tool-internal sample-size adjustment not defined in strategy.md. Identity label is correct per rules. $3.93 is an unfunded gap-coverage level — not in the bullet plan.

3. **$3.93 low confidence:** Only 2 approaches at this level (below the 3-approach minimum for confidence). Not reclassified; noted only. Level is unfunded so practical impact is nil.

4. **$4.74 as R1 rationale:** With 5 Active-zone levels filling the B1–B5 cap, the $4.74 PA level (buy-at $4.93) had no active slot. Analyst deployed it as R1 — a tighter reserve anchor than the tool's suggested $4.75 (raw $4.57, Reserve zone). This deviation from the tool's suggested plan is a documented, defensible analyst decision.

5. **$6.32 HVN+PA dead zone correctly handled:** Buy-at $6.61 is above current price ($6.39). Excluded from bullet plan with "↑above" notation. ✓

6. **Skip-tier levels correctly excluded from table:** $2.86 HVN+PA, $1.81–$1.65 PA range (0% hold) do not appear in identity.md wick table. ✓
