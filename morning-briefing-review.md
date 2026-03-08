# Morning Briefing Verification — 2026-03-08

## Verdict: ISSUES

## Verification Summary

| Check | Result | Details |
| :--- | :--- | :--- |
| 1. P/L Math | PASS | Clean |
| 2. Day Count Math | PASS | Clean |
| 3. Verdict Assignment | FAIL | 4 critical |
| 4. Earnings Gate Logic | PASS | Clean |
| 5. Regime Classification | PASS | Clean |
| 6. Entry Gate Logic | FAIL | 2 critical, 27 minor |
| 7. Data Consistency | PASS | Clean |
| 8. Coverage & Completeness | PASS | Clean |
| 9. Cross-Domain Consistency | PASS | Clean |

## Check 1: P/L Math Errors

No p/l math errors found.

## Check 2: Day Count Errors

No day count errors found.

## Check 3: Verdict Errors

| Ticker | Detail | Severity |
| :--- | :--- | :--- |
| CLSK | Verdict: expected MONITOR (rule 16 (WITHIN time stop)), briefing shows HOLD | Critical |
| NNE | Verdict: expected MONITOR (rule 16 (WITHIN time stop)), briefing shows HOLD | Critical |
| OUST | Verdict: expected MONITOR (rule 16 (WITHIN time stop)), briefing shows HOLD | Critical |
| TMC | Verdict: expected MONITOR (rule 16 (WITHIN time stop)), briefing shows HOLD | Critical |

## Check 4: Earnings Gate Errors

No earnings gate errors found.

## Check 5: Regime Classification Errors

No regime classification errors found.

## Check 6: Entry Gate Errors

| Ticker | Detail | Severity |
| :--- | :--- | :--- |
| CLSK | BUY $9.11 % Below Current: expected -1.1%, briefing shows 0.0% | Minor |
| CLSK | BUY $8.88 % Below Current: expected -3.6%, briefing shows 2.5% | Minor |
| NNE | BUY $24.03 % Below Current: expected 2.1%, briefing shows 0.0% | Minor |
| NNE | BUY $23.50 % Below Current: expected -0.2%, briefing shows 2.2% | Minor |
| APLD | BUY $21.93: expected combined gate REVIEW (market=REVIEW, earnings=ACTIVE), briefing shows ACTIVE | Critical |
| APLD | BUY $21.93 % Below Current: expected -12.8%, briefing shows 42.3% | Minor |
| CIFR | BUY $14.07 % Below Current: expected 3.3%, briefing shows 0.0% | Minor |
| CIFR | BUY $12.86 % Below Current: expected -5.6%, briefing shows 8.6% | Minor |
| CIFR | BUY $5.38 % Below Current: expected -60.5%, briefing shows 61.8% | Minor |
| CLF | BUY $9.97 % Below Current: expected 1.4%, briefing shows 0.0% | Minor |
| CLF | BUY $9.41 % Below Current: expected -4.3%, briefing shows 5.6% | Minor |
| CLF | BUY $8.48 % Below Current: expected -13.7%, briefing shows 14.9% | Minor |
| NU | BUY $13.03: expected combined gate REVIEW (market=REVIEW, earnings=ACTIVE), briefing shows ACTIVE | Critical |
| NU | BUY $13.03 % Below Current: expected -10.6%, briefing shows 29.6% | Minor |
| AR | BUY $35.00 % Below Current: expected -9.9%, briefing shows 0.0% | Minor |
| AR | BUY $32.68 % Below Current: expected -15.8%, briefing shows 6.6% | Minor |
| AR | BUY $31.16 % Below Current: expected -19.8%, briefing shows 11.0% | Minor |
| BBAI | BUY $3.82 % Below Current: expected -10.1%, briefing shows 0.0% | Minor |
| BBAI | BUY $3.71 % Below Current: expected -12.7%, briefing shows 2.9% | Minor |
| BBAI | BUY $3.66 % Below Current: expected -13.9%, briefing shows 4.2% | Minor |
| NVDA | BUY $174.60 % Below Current: expected -1.8%, briefing shows 0.0% | Minor |
| NVDA | BUY $169.54 % Below Current: expected -4.7%, briefing shows 2.9% | Minor |
| NVDA | BUY $168.40 % Below Current: expected -5.3%, briefing shows 3.6% | Minor |
| NVDA | BUY $146.74 % Below Current: expected -17.5%, briefing shows 16.0% | Minor |
| SMCI | BUY $28.78 % Below Current: expected -8.1%, briefing shows ~11.2% | Minor |
| SOUN | BUY $7.48 % Below Current: expected -7.3%, briefing shows 0.0% | Minor |
| SOUN | BUY $7.26 % Below Current: expected -10.0%, briefing shows 2.9% | Minor |
| TEM | BUY $50.98 % Below Current: expected -2.4%, briefing shows 0.0% | Minor |
| TEM | BUY $48.75 % Below Current: expected -6.7%, briefing shows 4.4% | Minor |

## Check 7: Data Mismatches

No data mismatches found.

## Check 8: Coverage Gaps

No coverage gaps found.

## Check 9: Cross-Domain Consistency Issues

No cross-domain consistency issues found.

## Quality Notes

Verification run: 2026-03-08
Total findings: 6 critical, 27 minor
**6 critical issue(s) require attention.**
