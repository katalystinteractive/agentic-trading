# Mechanical Pre-Verification Report
*Generated: 2026-03-23 22:29 | Tool: surgical_pre_verify.py*

## Summary
| Check | Result | Details |
| :--- | :--- | :--- |
| Score match | PASS | 0 mismatches |
| Flag coverage | FAIL | 6 flags unaddressed |
| Sector audit | PASS | All sectors mapped |
| Duplicate buy prices | PASS | No duplicates |
| Recency counts | PASS | All counts verified |
| Score arithmetic | PASS | All sums verified |
| Recommendation consistency | PASS | All consistent |
| Cycle data completeness | PASS | All consistent |
| Active zone proximity | WARN | 5 tickers >15% gap |

## Per-Ticker Findings
### NUAI
- Score match: PASS
- Flag coverage: 1 addressed / **1 missed** (3 mechanical skipped)
  - Missed: Active-reserve gap: 65%
- Active zone gap: **16.9%** — nearest buy $4.12 vs price $4.96

### ASTX
- Score match: PASS
- Flag coverage: 1 addressed / **1 missed** (3 mechanical skipped)
  - Missed: Active-reserve gap: 25%
- Active zone gap: **17.1%** — nearest buy $36.18 vs price $43.66

### BMNZ
- Score match: PASS
- Flag coverage: 0 addressed / **1 missed**
  - Missed: KPI gates failed: Strong Levels (hold >= 50%)
- Active zone gap: **16.8%** — nearest buy $15.25 vs price $18.33

### VELO
- Score match: PASS
- Flag coverage: 1 addressed / **1 missed** (3 mechanical skipped)
  - Missed: Active-reserve gap: 39%
- Active zone gap: **15.5%** — nearest buy $11.16 vs price $13.21

### CRWU
- Score match: PASS
- Flag coverage: 0 addressed / **1 missed**
  - Missed: Recency deterioration: 1 levels
- Active zone gap: **18.3%** — nearest buy $4.20 vs price $5.14

### RGTZ
- Score match: PASS
- Flag coverage: 1 addressed / **1 missed**
  - Missed: Active-reserve gap: 31%

### IREX
- Score match: PASS
- Flag coverage: 1 addressed / 0 missed

## For Verifier: Qualitative Focus Areas
1. **NUAI**: evaluate unaddressed flags: Active-reserve gap: 65%
2. **ASTX**: evaluate unaddressed flags: Active-reserve gap: 25%
3. **BMNZ**: evaluate unaddressed flags: KPI gates failed: Strong Levels (hold >= 50%)
4. **VELO**: evaluate unaddressed flags: Active-reserve gap: 39%
5. **CRWU**: evaluate unaddressed flags: Recency deterioration: 1 levels
6. **RGTZ**: evaluate unaddressed flags: Active-reserve gap: 31%

