# Deep Dive Review — CIFR — 2026-03-16

## Verdict: PASS

## Verification Summary

| Check | Result | Details |
| :--- | :--- | :--- |
| Bullet Math | PASS | All 7 bullets transcribed exactly; cost sanity within tolerance |
| Tier Classifications | PASS | All bullet-selected levels correctly classified; $5.42 Half anomaly noted (not a bullet) |
| Zone Assignments | PASS | Active floor $9.96; all 4 active ≥ $9.96, all 8 reserve < $9.96 |
| Price Accuracy & Transcription | PASS | All buy-at prices match pre-analyst exactly; no exact-support bullets |
| Budget Compliance | PASS | Active ~$288.70 / $300; Reserve ~$298.45 / $300 |
| Projected Averages | PASS | All rows match pre-analyst; spot-checks pass within $1 tolerance |
| Format Compliance | PASS | Headings, persona pattern, wick table alignment, status label all correct |
| Portfolio.json | N/A | Existing ticker |

## Bullet Math Detail

| Bullet | Buy Price | Pre-analyst Shares | Identity Shares | Pre-analyst Cost | Identity Cost | Result |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| B1 | $14.82 | 5 | 5 | ~$74.10 | ~$74.10 | PASS |
| B2 | $14.18 | 5 | 5 | ~$70.91 | ~$70.91 | PASS |
| B3 | $13.09 | 6 | 6 | ~$78.54 | ~$78.54 | PASS |
| B4 | $13.03 | 5 | 5 | ~$65.15 | ~$65.15 | PASS |
| R1 | $5.38 | 22 | 22 | ~$118.47 | ~$118.47 | PASS |
| R2 | $3.30 | 28 | 28 | ~$92.40 | ~$92.40 | PASS |
| R3 | $3.02 | 29 | 29 | ~$87.58 | ~$87.58 | PASS |

**Active total:** ~$288.70 / $300 — PASS
**Reserve total:** ~$298.45 / $300 — PASS

## Issues Found

No issues found.

## Notes

- **$5.42 tier anomaly (observation only):** Wick table shows $5.42 (40% hold rate) as Half tier; raw threshold for 40% is Std. Likely reflects effective tier after confidence gate application (<3 approaches → Half cap). $5.42 is NOT selected as a bullet — no plan impact.
- **Zero-offset levels (observation only):** $4.82 (+0.00%) and $2.18 (+0.00%) have buy-at = raw support. Neither is selected as a bullet, so the limit-order-at-exact-support rule is not violated.
- **Convergence warning correctly carried:** Identity.md preserves the pre-analyst convergence note for $13.09 / $13.03 (within 0.5%). Both bullets retained per protocol.
- **59% dead zone gap noted:** Identity.md correctly flags the gap from last active bullet ($13.03) to first reserve ($5.38), consistent with pre-analyst output.
- **Projected averages R2 row:** Spot-check yields avg $7.04 vs reported $7.03 ($0.01 difference, well within $1 tolerance). PASS.
- **R2/R3 reserve bullets not in portfolio.json pending_orders:** Only B1-B4 + R1 are placed (5 orders). R2 and R3 are in the identity plan but not yet staged. This is an existing ticker (Step 8 N/A) and consistent with selective reserve deployment. No reviewer action required.
