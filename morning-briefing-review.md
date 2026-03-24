# Morning Briefing Verification — 2026-03-16

## Verdict: ISSUES

## Verification Summary

| Check | Result | Details |
| :--- | :--- | :--- |
| 1. P/L Math | PASS | Clean |
| 2. Day Count Math | PASS | Clean |
| 3. Verdict Assignment | FAIL | 4 critical, 1 minor |
| 4. Earnings Gate Logic | PASS | Clean |
| 5. Regime Classification | PASS | Clean |
| 6. Entry Gate Logic | FAIL | 1 critical, 36 minor |
| 7. Data Consistency | FAIL | 10 critical |
| 8. Coverage & Completeness | PASS | Clean |
| 9. Cross-Domain Consistency | PASS | Clean |

## Check 1: P/L Math Errors

No p/l math errors found.

## Check 2: Day Count Errors

No day count errors found.

## Check 3: Verdict Errors

| Ticker | Detail | Severity |
| :--- | :--- | :--- |
| LUNR | Verdict: expected HOLD (rule 2 (non-recovery + GATED + P/L <= 0%)), briefing shows REDUCE | Critical |
| CLF | Verdict: expected MONITOR (rule 16 (WITHIN time stop)), briefing shows HOLD | Critical |
| TEM | Verdict: expected MONITOR (rule 16 (WITHIN time stop)), briefing shows HOLD | Critical |
| TMC | Verdict: expected MONITOR (rule 16 (WITHIN time stop)), briefing shows HOLD | Critical |
| SOUN | Momentum label: expected Bearish, briefing shows BEARISH | Minor |

## Check 4: Earnings Gate Errors

No earnings gate errors found.

## Check 5: Regime Classification Errors

No regime classification errors found.

## Check 6: Entry Gate Errors

| Ticker | Detail | Severity |
| :--- | :--- | :--- |
| LUNR | BUY $16.00 % Below Current: expected -6.5%, briefing shows 9.0% | Minor |
| LUNR | BUY $15.33 % Below Current: expected -10.5%, briefing shows 12.8% | Minor |
| LUNR | BUY $15.20 % Below Current: expected -11.2%, briefing shows 13.6% | Minor |
| LUNR | BUY $10.06 % Below Current: expected -41.2%, briefing shows 42.8% | Minor |
| LUNR | BUY $7.78 % Below Current: expected -54.6%, briefing shows 55.8% | Minor |
| LUNR | BUY $6.64 % Below Current: expected -61.2%, briefing shows 62.3% | Minor |
| OKLO | BUY $57.21 % Below Current: expected -2.9%, briefing shows 1.4% | Minor |
| OKLO | BUY $51.10 % Below Current: expected -13.2%, briefing shows 12.0% | Minor |
| CLF | BUY $9.41 % Below Current: expected 10.4%, briefing shows ⚠️ Above current ($8.52) | Minor |
| TEM | BUY $48.75 % Below Current: expected -3.4%, briefing shows 10.6% | Minor |
| TMC | BUY $5.63: expected combined gate ACTIVE (market=ACTIVE, earnings=ACTIVE), briefing shows REVIEW | Critical |
| TMC | BUY $5.63 % Below Current: expected -5.9%, briefing shows 11.9% | Minor |
| APLD | BUY $21.93 % Below Current: expected -20.7%, briefing shows 42.3% | Minor |
| ARM | BUY $112.53 % Below Current: expected -7.6%, briefing shows 11.5% | Minor |
| NU | BUY $13.03 % Below Current: expected -8.4%, briefing shows 29.6% | Minor |
| BBAI | BUY $3.82 % Below Current: expected -2.8%, briefing shows 0.0% | Minor |
| BBAI | BUY $3.71 % Below Current: expected -5.6%, briefing shows 2.9% | Minor |
| BBAI | BUY $3.66 % Below Current: expected -6.9%, briefing shows 4.2% | Minor |
| CIFR | BUY $14.07 % Below Current: expected -6.0%, briefing shows 0.0% | Minor |
| CIFR | BUY $12.86 % Below Current: expected -14.1%, briefing shows 8.6% | Minor |
| CIFR | BUY $5.38 % Below Current: expected -64.1%, briefing shows 61.8% | Minor |
| CLSK | BUY $9.66 % Below Current: expected -3.6%, briefing shows 5.7% | Minor |
| CLSK | BUY $9.09 % Below Current: expected -9.3%, briefing shows 11.2% | Minor |
| CLSK | BUY $8.91 % Below Current: expected -11.1%, briefing shows 13.0% | Minor |
| CLSK | BUY $8.40 % Below Current: expected -16.2%, briefing shows 18.0% | Minor |
| NVDA | BUY $174.60 % Below Current: expected -5.5%, briefing shows ~4.8% | Minor |
| NVDA | BUY $169.54 % Below Current: expected -8.2%, briefing shows ~7.7% | Minor |
| NVDA | BUY $146.74 % Below Current: expected -20.6%, briefing shows ~19.7% | Minor |
| RUN | BUY $11.05 % Below Current: expected -13.3%, briefing shows 0.0% | Minor |
| RUN | BUY $10.69 % Below Current: expected -16.1%, briefing shows 3.3% | Minor |
| RUN | BUY $10.10 % Below Current: expected -20.7%, briefing shows 8.6% | Minor |
| RUN | BUY $10.05 % Below Current: expected -21.1%, briefing shows 9.0% | Minor |
| RUN | BUY $7.87 % Below Current: expected -38.2%, briefing shows 28.8% | Minor |
| RUN | BUY $6.11 % Below Current: expected -52.0%, briefing shows 44.7% | Minor |
| RUN | BUY $5.45 % Below Current: expected -57.2%, briefing shows 50.7% | Minor |
| SMCI | BUY $29.95 % Below Current: expected -5.0%, briefing shows 0.0% | Minor |
| SMCI | BUY $28.78 % Below Current: expected -8.7%, briefing shows 3.9% | Minor |

## Check 7: Data Mismatches

| Ticker | Detail | Severity |
| :--- | :--- | :--- |
| LUNR | Missing BUY $17.59 (2 shares) from briefing card | Critical |
| OKLO | Missing BUY $58.04 (1 shares) from briefing card | Critical |
| CLF | Missing BUY $9.97 (10 shares) from briefing card | Critical |
| CLF | Missing BUY $9.88 (6 shares) from briefing card | Critical |
| CLF | Missing BUY $8.48 (21 shares) from briefing card | Critical |
| TMC | Missing BUY $6.01 (9 shares) from briefing card | Critical |
| ACHR | Missing BUY $5.98 (16 shares) from briefing card | Critical |
| NNE | Missing BUY $24.03 (2 shares) from briefing card | Critical |
| SOUN | Missing BUY $7.26 (8 shares) from briefing card | Critical |
| OUST | BUY $20.32: portfolio shares=1, briefing shares=4 | Critical |

## Check 8: Coverage Gaps

No coverage gaps found.

## Check 9: Cross-Domain Consistency Issues

No cross-domain consistency issues found.

## Quality Notes

Verification run: 2026-03-16
Total findings: 15 critical, 37 minor
**15 critical issue(s) require attention.**
