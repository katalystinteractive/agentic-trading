# Mechanical Pre-Verification Report
*Generated: 2026-03-05 07:50 | Tool: surgical_pre_verify.py*

## Summary
| Check | Result | Details |
| :--- | :--- | :--- |
| Score match | PASS | 0 mismatches |
| Flag coverage | PASS | All flags addressed |
| Sector audit | FAIL | 1 misclassifications |
| Duplicate buy prices | WARN | 1 anomalies |
| Recency counts | PASS | All counts verified |
| Score arithmetic | PASS | All sums verified |
| Recommendation consistency | PASS | All consistent |

## Score Adjustments Recommended
| Ticker | Issue | Impact |
| :--- | :--- | :--- |
| NVDA | Labeled "Unknown" | Sector diversity score may be incorrect for candidates in this ticker's true sector |

## Per-Ticker Findings
### OUST
- Score match: PASS
- Flag coverage: No quality flags to check (2 mechanical skipped)

### IREN
- Score match: PASS
- Flag coverage: 3 addressed / 0 missed (4 mechanical skipped)

### QBTS
- Score match: PASS
- Flag coverage: No quality flags to check (1 mechanical skipped)

### HUT
- Score match: PASS
- Flag coverage: 2 addressed / 0 missed (2 mechanical skipped)

### RGTI
- Score match: PASS
- Flag coverage: No quality flags to check (1 mechanical skipped)
- Duplicate buy price: $14.78 at supports $14.12, $14.70

### NTLA
- Score match: PASS
- Flag coverage: 1 addressed / 0 missed

### RDW
- Score match: PASS
- Flag coverage: 1 addressed / 0 missed

## Data Quality Issues
### Sector Misclassifications
- NVDA: labeled "Unknown" — Sector diversity score may be incorrect for candidates in this ticker's true sector

### Duplicate Buy Prices
- RGTI: $14.78 shared by supports $14.12, $14.70

## For Verifier: Qualitative Focus Areas
1. **RGTI**: assess duplicate buy price convergence — coincidence or data issue?

