# Surgical Candidate Shortlist
*Generated: 2026-03-25 22:15 | Scored by surgical_filter.py*

## Scoring Summary — Top 7
| # | Ticker | Strategy | Sector | Price | Swing% | Bullets (0-15) | B1 (0-5) | Coverage (0-15) | Reserve (0-5) | Swing (0-10) | Sector (0-10) | Cycle (0-20) | HoldQ (0-20) | DR Score | Effective | Flags |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | WOLF | DAI | Tech | $18.50 | 57.6% | 13 | 5 | 15 | 0 | 10 | 8 | 13 | 3 | 98 | 98 | WOLF $17.66: cost $123.62 vs expected $70.64; WOLF $15.83: cost $63.32 vs expected $110.81; KPI gates failed: Active Levels (hold >= 30%), Cycle Data (>= 5 cycles), Strong Levels (hold >= 50%) |
| 2 | HIMS | DAI | Health | $20.84 | 56.4% | 0 | 0 | 0 | 0 | 10 | 10 | 15 | 0 | 98 | 98 | KPI gates failed: Active Levels (hold >= 30%), Anchor Level (hold >= 50%), Strong Levels (hold >= 50%) |
| 3 | QBTS | DAI | Quantum | $16.19 | 55.3% | 12 | 4 | 10 | 5 | 10 | 8 | 15 | 14 | 98 | 98 | QBTS $14.95: cost $284.05 vs expected $149.50; QBTS $14.4: cost $14.40 vs expected $144.00; QBTS $6.68: cost $6.68 vs expected $106.88; QBTS $6.05: cost $6.05 vs expected $96.80; QBTS $5.77: cost $5.77 vs expected $92.32; Active-reserve gap: 54%; KPI gates failed: Active Levels (hold >= 30%), Dead Zone |
| 4 | NTLA | DAI | Biotech | $13.26 | 44.2% | 9 | 5 | 15 | 5 | 10 | 8 | 20 | 0 | 98 | 98 | NTLA $13.02: cost $130.20 vs expected $78.12; NTLA $11.8: cost $47.20 vs expected $70.80; NTLA $11.63: cost $46.52 vs expected $69.78; NTLA $8.03: cost $8.03 vs expected $120.45; NTLA $6.95: cost $6.95 vs expected $90.35; NTLA $6.83: cost $6.83 vs expected $88.79; Active-reserve gap: 31%; KPI gates failed: Active Levels (hold >= 30%), Anchor Level (hold >= 50%), Dead Zone, Strong Levels (hold >= 50%) |
| 5 | IREN | DAI | Crypto | $41.43 | 60.9% | 15 | 5 | 15 | 5 | 10 | 6 | 13 | 17 | 96 | 96 | IREN $39.58: cost $39.58 vs expected $79.16; IREN $39.13: cost $156.52 vs expected $78.26; IREN $36.08: cost $36.08 vs expected $72.16; IREN $34.49: cost $34.49 vs expected $68.98; IREN $16.77: cost $16.77 vs expected $150.93; IREN $9.96: cost $9.96 vs expected $89.64; IREN $6.83: cost $6.83 vs expected $54.64; Recency deterioration: 1 levels; Active-reserve gap: 51%; KPI gates failed: Dead Zone, Price Range, Cycle Data (>= 5 cycles) |
| 6 | HUT | DAI | Crypto | $55.62 | 57.0% | 11 | 5 | 15 | 5 | 10 | 6 | 15 | 0 | 96 | 96 | HUT $32.84: cost $32.84 vs expected $164.20; HUT $18.94: cost $18.94 vs expected $75.76; HUT $10.97: cost $10.97 vs expected $54.85; Active-reserve gap: 33%; KPI gates failed: Active Levels (hold >= 30%), Anchor Level (hold >= 50%), Dead Zone, Price Range, Strong Levels (hold >= 50%) |
| 7 | DNA | DAI | Biotech | $7.36 | 55.4% | 6 | 2 | 4 | 0 | 10 | 8 | 15 | 11 | 96 | 96 | KPI gates failed: Active Levels (hold >= 30%), Strong Levels (hold >= 50%) |

## All 20 Scores
| # | Ticker | Total | Wick OK |
| :--- | :--- | :--- | :--- |
| 1 | WOLF | 67 | Yes |
| 2 | HIMS | 35 | Yes |
| 3 | QBTS | 78 | Yes |
| 4 | NTLA | 72 | Yes |
| 5 | IREN | 86 | Yes |
| 6 | HUT | 67 | Yes |
| 7 | DNA | 56 | Yes |
| 8 | RIOT | 85 | Yes |
| 9 | OPEN | 75 | Yes |
| 10 | MP | 62 | Yes |
| 11 | SMR | 70 | Yes |
| 12 | BEAM | 65 | Yes |
| 13 | MARA | 58 | Yes |
| 14 | JOBY | 88 | Yes |
| 15 | NVAX | 61 | Yes |
| 16 | AFRM | 61 | Yes |
| 17 | RXRX | 18 | No |
| 18 | UPST | 33 | Yes |
| 19 | QS | 65 | Yes |
| 20 | LCID | 62 | Yes |

---

## Candidate Detail: WOLF

### Quick Facts
| Field | Value |
| :--- | :--- |
| Sector | Tech |
| Price | $18.50 |
| Median Swing | 57.6% |
| Consistency | 100.0% |
| Active Radius | 20.0% |

### Score Breakdown
| Criterion | Score | Max | Detail |
| :--- | :--- | :--- | :--- |
| Bullets & Tier Quality | 13 | 15 | Sum of tier points for active bullets |
| B1 Proximity | 5 | 5 | Distance from current price to first fill |
| Zone Coverage | 15 | 15 | Spread of active bullets across price range |
| Reserve Depth | 0 | 5 | Viable reserve levels with 30%+ hold |
| Swing Magnitude | 10 | 10 | Monthly swing opportunity |
| Sector Diversity | 8 | 10 | Diminishing returns by sector count |
| Cycle Efficiency | 13 | 20 | Cycle speed, fill rate, consistency |
| Hold Rate Quality | 3 | 20 | Reliable levels + floor bonus |
| **Total** | **67** | **100** | |

### Bullet Plan
| # | Zone | Support | Buy At | Hold% | Tier | Approaches | Shares | Cost |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | Active | $16.88 | $17.66 | 29% | Half | 14 | 7 | $123.62 |
| 2 | Active | $16.11 | $16.84 | 44% | Std | 9 | 6 | $101.03 |
| 3 | Active | $15.34 | $15.83 | 50% | Full | 6 | 4 | $63.33 |

- **Active total:** $287.98
- **Reserve total:** $0.00
- **All-in cost:** $287.98

### Recency Analysis
| Level | Overall Hold% | Last 90d Hold% | Recent Events | Trend |
| :--- | :--- | :--- | :--- | :--- |
| $16.88 | 29% | 36% | 11 | Improving |
| $16.11 | 44% | 33% | 6 | Deteriorating |
| $15.34 | 50% | 50% | 4 | Stable |

### Verification
- Tier check: PASS
- Bullet math: FAIL
- Pool deployment: PASS

### Stress Metrics
| Metric | Value | Assessment |
| :--- | :--- | :--- |
| Min active approaches | 6 | Strong |
| B1 distance | 4.5% | Ideal |
| Sector after onboard | 2x | OK |
| Budget feasible | $288 / $600 | Yes |
| Reserve 40%+ hold | 0 levels | Weak |

### KPI Card — FAIL
| KPI | Threshold | Actual | Status |
| :--- | :--- | :--- | :--- |
| Monthly Swing | >= 35.0% | 57.6% | PASS |
| Active Levels (hold >= 30%) | >= 3 | 2 | FAIL |
| Anchor Level (hold >= 50%) | >= 1 | 1 | PASS |
| Dead Zone | < 30.0% | N/A | PASS |
| Price Range | $5.0-$30.0 | $18.50 | PASS |
| Cycle Data (>= 5 cycles) | >= 5 | 3 | FAIL |
| Fill Consistency (>= 85%) | >= 85.0% | 100% | PASS |
| Strong Levels (hold >= 50%) | >= 2 | 1 | FAIL |
| Swing Compression | >= 0.65 | 0.83 | PASS |

### Flags
- WOLF $17.66: cost $123.62 vs expected $70.64
- WOLF $15.83: cost $63.32 vs expected $110.81
- KPI gates failed: Active Levels (hold >= 30%), Cycle Data (>= 5 cycles), Strong Levels (hold >= 50%)

### For Evaluator: Qualitative Questions
1. Are the support levels clean bounce patterns or choppy/degrading? Evaluate pattern quality from the approach history.

---

## Candidate Detail: HIMS

### Quick Facts
| Field | Value |
| :--- | :--- |
| Sector | Health |
| Price | $20.84 |
| Median Swing | 56.4% |
| Consistency | 100.0% |
| Active Radius | 20.0% |

### Score Breakdown
| Criterion | Score | Max | Detail |
| :--- | :--- | :--- | :--- |
| Bullets & Tier Quality | 0 | 15 | Sum of tier points for active bullets |
| B1 Proximity | 0 | 5 | Distance from current price to first fill |
| Zone Coverage | 0 | 15 | Spread of active bullets across price range |
| Reserve Depth | 0 | 5 | Viable reserve levels with 30%+ hold |
| Swing Magnitude | 10 | 10 | Monthly swing opportunity |
| Sector Diversity | 10 | 10 | Diminishing returns by sector count |
| Cycle Efficiency | 15 | 20 | Cycle speed, fill rate, consistency |
| Hold Rate Quality | 0 | 20 | Reliable levels + floor bonus |
| **Total** | **35** | **100** | |

### Bullet Plan
*No qualifying bullet levels.*

### Verification
- Tier check: PASS
- Bullet math: PASS
- Pool deployment: PASS

### Stress Metrics
| Metric | Value | Assessment |
| :--- | :--- | :--- |
| Min active approaches | 0 | Weak — some <3 |
| Sector after onboard | 1x | OK |
| Budget feasible | $0 / $600 | Yes |
| Reserve 40%+ hold | 0 levels | Weak |

### KPI Card — FAIL
| KPI | Threshold | Actual | Status |
| :--- | :--- | :--- | :--- |
| Monthly Swing | >= 35.0% | 56.4% | PASS |
| Active Levels (hold >= 30%) | >= 3 | 0 | FAIL |
| Anchor Level (hold >= 50%) | >= 1 | 0 | FAIL |
| Dead Zone | < 30.0% | N/A | PASS |
| Price Range | $5.0-$30.0 | $20.84 | PASS |
| Cycle Data (>= 5 cycles) | >= 5 | 6 | PASS |
| Fill Consistency (>= 85%) | >= 85.0% | 100% | PASS |
| Strong Levels (hold >= 50%) | >= 2 | 0 | FAIL |
| Swing Compression | >= 0.65 | 0.73 | PASS |

### Flags
- KPI gates failed: Active Levels (hold >= 30%), Anchor Level (hold >= 50%), Strong Levels (hold >= 50%)

### For Evaluator: Qualitative Questions
1. Are the support levels clean bounce patterns or choppy/degrading? Evaluate pattern quality from the approach history.

---

## Candidate Detail: QBTS

### Quick Facts
| Field | Value |
| :--- | :--- |
| Sector | Quantum |
| Price | $16.19 |
| Median Swing | 55.3% |
| Consistency | 100.0% |
| Active Radius | 20.0% |

### Score Breakdown
| Criterion | Score | Max | Detail |
| :--- | :--- | :--- | :--- |
| Bullets & Tier Quality | 12 | 15 | Sum of tier points for active bullets |
| B1 Proximity | 4 | 5 | Distance from current price to first fill |
| Zone Coverage | 10 | 15 | Spread of active bullets across price range |
| Reserve Depth | 5 | 5 | Viable reserve levels with 30%+ hold |
| Swing Magnitude | 10 | 10 | Monthly swing opportunity |
| Sector Diversity | 8 | 10 | Diminishing returns by sector count |
| Cycle Efficiency | 15 | 20 | Cycle speed, fill rate, consistency |
| Hold Rate Quality | 14 | 20 | Reliable levels + floor bonus |
| **Total** | **78** | **100** | |

### Bullet Plan
| # | Zone | Support | Buy At | Hold% | Tier | Approaches | Shares | Cost |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | Active | $14.32 | $14.95 | 57% | Full | 7 | 19 | $284.14 |
| 2 | Active | $13.57 | $14.40 | 67% | Full | 3 | 1 | $14.40 |
| 3 | Reserve | $6.47 | $6.68 | 43% | Std | 7 | 1 | $6.68 |
| 4 | Reserve | $5.97 | $6.05 | 40% | Std | 5 | 1 | $6.05 |
| 5 | Reserve | $5.70 | $5.77 | 60% | Full | 5 | 1 | $5.77 |

- **Active total:** $298.54
- **Reserve total:** $18.50
- **All-in cost:** $317.04

### Recency Analysis
| Level | Overall Hold% | Last 90d Hold% | Recent Events | Trend |
| :--- | :--- | :--- | :--- | :--- |
| $14.32 | 57% | 100% | 1 | Improving |
| $13.57 | 67% | — | 0 | No recent data |
| $6.47 | 43% | — | 0 | No recent data |
| $5.97 | 40% | — | 0 | No recent data |
| $5.70 | 60% | — | 0 | No recent data |

### Verification
- Tier check: PASS
- Bullet math: FAIL
- Pool deployment: PASS

### Stress Metrics
| Metric | Value | Assessment |
| :--- | :--- | :--- |
| Min active approaches | 3 | Strong |
| B1 distance | 7.7% | OK |
| Sector after onboard | 3x | OK |
| Budget feasible | $317 / $600 | Yes |
| Reserve 40%+ hold | 3 levels | Good |
| Active-reserve gap | 54% | Dead zone |

### KPI Card — FAIL
| KPI | Threshold | Actual | Status |
| :--- | :--- | :--- | :--- |
| Monthly Swing | >= 35.0% | 55.3% | PASS |
| Active Levels (hold >= 30%) | >= 3 | 2 | FAIL |
| Anchor Level (hold >= 50%) | >= 1 | 2 | PASS |
| Dead Zone | < 30.0% | 53.6% | FAIL |
| Price Range | $5.0-$30.0 | $16.19 | PASS |
| Cycle Data (>= 5 cycles) | >= 5 | 9 | PASS |
| Fill Consistency (>= 85%) | >= 85.0% | 100% | PASS |
| Strong Levels (hold >= 50%) | >= 2 | 2 | PASS |
| Swing Compression | >= 0.65 | 0.97 | PASS |

### Flags
- QBTS $14.95: cost $284.05 vs expected $149.50
- QBTS $14.4: cost $14.40 vs expected $144.00
- QBTS $6.68: cost $6.68 vs expected $106.88
- QBTS $6.05: cost $6.05 vs expected $96.80
- QBTS $5.77: cost $5.77 vs expected $92.32
- Active-reserve gap: 54%
- KPI gates failed: Active Levels (hold >= 30%), Dead Zone

### For Evaluator: Qualitative Questions
1. The 54% gap between active bottom and reserve top creates a dead zone. Can reserves realistically rescue the position?

---

## Candidate Detail: NTLA

### Quick Facts
| Field | Value |
| :--- | :--- |
| Sector | Biotech |
| Price | $13.26 |
| Median Swing | 44.2% |
| Consistency | 100.0% |
| Active Radius | 20.0% |

### Score Breakdown
| Criterion | Score | Max | Detail |
| :--- | :--- | :--- | :--- |
| Bullets & Tier Quality | 9 | 15 | Sum of tier points for active bullets |
| B1 Proximity | 5 | 5 | Distance from current price to first fill |
| Zone Coverage | 15 | 15 | Spread of active bullets across price range |
| Reserve Depth | 5 | 5 | Viable reserve levels with 30%+ hold |
| Swing Magnitude | 10 | 10 | Monthly swing opportunity |
| Sector Diversity | 8 | 10 | Diminishing returns by sector count |
| Cycle Efficiency | 20 | 20 | Cycle speed, fill rate, consistency |
| Hold Rate Quality | 0 | 20 | Reliable levels + floor bonus |
| **Total** | **72** | **100** | |

### Bullet Plan
| # | Zone | Support | Buy At | Hold% | Tier | Approaches | Shares | Cost |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | Active | $12.82 | $13.02 | 17% | Half | 12 | 10 | $130.16 |
| 2 | Active | $12.48 | $12.62 | 33% | Half | 9 | 6 | $75.75 |
| 3 | Active | $11.62 | $11.80 | 18% | Half | 11 | 4 | $47.18 |
| 4 | Active | $11.02 | $11.63 | 14% | Half | 7 | 4 | $46.52 |
| 5 | Reserve | $7.52 | $8.03 | 50% | Full | 6 | 1 | $8.03 |
| 6 | Reserve | $6.90 | $6.95 | 50% | Full | 8 | 1 | $6.95 |
| 7 | Reserve | $6.59 | $6.83 | 33% | Std | 3 | 1 | $6.83 |

- **Active total:** $299.61
- **Reserve total:** $21.81
- **All-in cost:** $321.42

### Recency Analysis
| Level | Overall Hold% | Last 90d Hold% | Recent Events | Trend |
| :--- | :--- | :--- | :--- | :--- |
| $12.82 | 17% | 17% | 6 | Stable |
| $12.48 | 33% | 25% | 4 | Deteriorating |
| $11.62 | 18% | 33% | 3 | Improving |
| $11.02 | 14% | 0% | 2 | Deteriorating |
| $7.52 | 50% | — | 0 | No recent data |
| $6.90 | 50% | — | 0 | No recent data |
| $6.59 | 33% | — | 0 | No recent data |

### Verification
- Tier check: PASS
- Bullet math: FAIL
- Pool deployment: PASS

### Stress Metrics
| Metric | Value | Assessment |
| :--- | :--- | :--- |
| Min active approaches | 7 | Strong |
| B1 distance | 1.8% | Ideal |
| Sector after onboard | 2x | OK |
| Budget feasible | $321 / $600 | Yes |
| Reserve 40%+ hold | 2 levels | Good |
| Active-reserve gap | 31% | Dead zone |

### KPI Card — FAIL
| KPI | Threshold | Actual | Status |
| :--- | :--- | :--- | :--- |
| Monthly Swing | >= 35.0% | 44.2% | PASS |
| Active Levels (hold >= 30%) | >= 3 | 1 | FAIL |
| Anchor Level (hold >= 50%) | >= 1 | 0 | FAIL |
| Dead Zone | < 30.0% | 31.0% | FAIL |
| Price Range | $5.0-$30.0 | $13.26 | PASS |
| Cycle Data (>= 5 cycles) | >= 5 | 11 | PASS |
| Fill Consistency (>= 85%) | >= 85.0% | 100% | PASS |
| Strong Levels (hold >= 50%) | >= 2 | 0 | FAIL |
| Swing Compression | >= 0.65 | 1.16 | PASS |

### Flags
- NTLA $13.02: cost $130.20 vs expected $78.12
- NTLA $11.8: cost $47.20 vs expected $70.80
- NTLA $11.63: cost $46.52 vs expected $69.78
- NTLA $8.03: cost $8.03 vs expected $120.45
- NTLA $6.95: cost $6.95 vs expected $90.35
- NTLA $6.83: cost $6.83 vs expected $88.79
- Active-reserve gap: 31%
- KPI gates failed: Active Levels (hold >= 30%), Anchor Level (hold >= 50%), Dead Zone, Strong Levels (hold >= 50%)

### For Evaluator: Qualitative Questions
1. The 31% gap between active bottom and reserve top creates a dead zone. Can reserves realistically rescue the position?

---

## Candidate Detail: IREN

### Quick Facts
| Field | Value |
| :--- | :--- |
| Sector | Crypto |
| Price | $41.43 |
| Median Swing | 60.9% |
| Consistency | 100.0% |
| Active Radius | 20.0% |

### Score Breakdown
| Criterion | Score | Max | Detail |
| :--- | :--- | :--- | :--- |
| Bullets & Tier Quality | 15 | 15 | Sum of tier points for active bullets |
| B1 Proximity | 5 | 5 | Distance from current price to first fill |
| Zone Coverage | 15 | 15 | Spread of active bullets across price range |
| Reserve Depth | 5 | 5 | Viable reserve levels with 30%+ hold |
| Swing Magnitude | 10 | 10 | Monthly swing opportunity |
| Sector Diversity | 6 | 10 | Diminishing returns by sector count |
| Cycle Efficiency | 13 | 20 | Cycle speed, fill rate, consistency |
| Hold Rate Quality | 17 | 20 | Reliable levels + floor bonus |
| **Total** | **86** | **100** | |

### Bullet Plan
| # | Zone | Support | Buy At | Hold% | Tier | Approaches | Shares | Cost |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | Active | $39.00 | $39.58 | 44% | Std | 9 | 1 | $39.58 |
| 2 | Active | $37.10 | $39.13 | 57% | Full | 14 | 4 | $156.52 |
| 3 | Active | $34.62 | $36.08 | 67% | Full | 6 | 1 | $36.08 |
| 4 | Active | $33.34 | $34.49 | 50% | Full | 4 | 1 | $34.49 |
| 5 | Reserve | $16.25 | $16.77 | 50% | Full | 4 | 1 | $16.77 |
| 6 | Reserve | $9.87 | $9.96 | 50% | Std | 4 | 1 | $9.96 |
| 7 | Reserve | $6.58 | $6.83 | 50% | Full | 4 | 1 | $6.83 |

- **Active total:** $266.67
- **Reserve total:** $33.56
- **All-in cost:** $300.23

### Recency Analysis
| Level | Overall Hold% | Last 90d Hold% | Recent Events | Trend |
| :--- | :--- | :--- | :--- | :--- |
| $39.00 | 44% | 0% | 4 | Deteriorating |
| $37.10 | 57% | 67% | 6 | Improving |
| $34.62 | 67% | 100% | 3 | Improving |
| $33.34 | 50% | 100% | 1 | Improving |
| $16.25 | 50% | — | 0 | No recent data |
| $9.87 | 50% | — | 0 | No recent data |
| $6.58 | 50% | — | 0 | No recent data |

### Verification
- Tier check: PASS
- Bullet math: FAIL
- Pool deployment: PASS

### Stress Metrics
| Metric | Value | Assessment |
| :--- | :--- | :--- |
| Min active approaches | 4 | Strong |
| B1 distance | 4.5% | Ideal |
| Sector after onboard | 4x | OK |
| Budget feasible | $300 / $600 | Yes |
| Reserve 40%+ hold | 3 levels | Good |
| Active-reserve gap | 51% | Dead zone |

### KPI Card — FAIL
| KPI | Threshold | Actual | Status |
| :--- | :--- | :--- | :--- |
| Monthly Swing | >= 35.0% | 60.9% | PASS |
| Active Levels (hold >= 30%) | >= 3 | 4 | PASS |
| Anchor Level (hold >= 50%) | >= 1 | 3 | PASS |
| Dead Zone | < 30.0% | 51.4% | FAIL |
| Price Range | $5.0-$30.0 | $41.43 | FAIL |
| Cycle Data (>= 5 cycles) | >= 5 | 4 | FAIL |
| Fill Consistency (>= 85%) | >= 85.0% | 100% | PASS |
| Strong Levels (hold >= 50%) | >= 2 | 3 | PASS |
| Swing Compression | >= 0.65 | 0.98 | PASS |

### Flags
- IREN $39.58: cost $39.58 vs expected $79.16
- IREN $39.13: cost $156.52 vs expected $78.26
- IREN $36.08: cost $36.08 vs expected $72.16
- IREN $34.49: cost $34.49 vs expected $68.98
- IREN $16.77: cost $16.77 vs expected $150.93
- IREN $9.96: cost $9.96 vs expected $89.64
- IREN $6.83: cost $6.83 vs expected $54.64
- Recency deterioration: 1 levels
- Active-reserve gap: 51%
- KPI gates failed: Dead Zone, Price Range, Cycle Data (>= 5 cycles)

### For Evaluator: Qualitative Questions
1. Is the recent hold-rate decline a temporary dip or structural support breakdown? Check if the sector/market regime changed.
2. The 51% gap between active bottom and reserve top creates a dead zone. Can reserves realistically rescue the position?

---

## Candidate Detail: HUT

### Quick Facts
| Field | Value |
| :--- | :--- |
| Sector | Crypto |
| Price | $55.62 |
| Median Swing | 57.0% |
| Consistency | 100.0% |
| Active Radius | 20.0% |

### Score Breakdown
| Criterion | Score | Max | Detail |
| :--- | :--- | :--- | :--- |
| Bullets & Tier Quality | 11 | 15 | Sum of tier points for active bullets |
| B1 Proximity | 5 | 5 | Distance from current price to first fill |
| Zone Coverage | 15 | 15 | Spread of active bullets across price range |
| Reserve Depth | 5 | 5 | Viable reserve levels with 30%+ hold |
| Swing Magnitude | 10 | 10 | Monthly swing opportunity |
| Sector Diversity | 6 | 10 | Diminishing returns by sector count |
| Cycle Efficiency | 15 | 20 | Cycle speed, fill rate, consistency |
| Hold Rate Quality | 0 | 20 | Reliable levels + floor bonus |
| **Total** | **67** | **100** | |

### Bullet Plan
| # | Zone | Support | Buy At | Hold% | Tier | Approaches | Shares | Cost |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | Active | $54.41 | $54.81 | 17% | Half | 6 | 1 | $54.81 |
| 2 | Active | $51.42 | $52.75 | 25% | Half | 12 | 1 | $52.75 |
| 3 | Active | $46.94 | $49.39 | 22% | Half | 9 | 1 | $49.39 |
| 4 | Active | $48.43 | $49.23 | 36% | Std | 11 | 2 | $98.45 |
| 5 | Reserve | $31.67 | $32.84 | 80% | Full | 5 | 1 | $32.84 |
| 6 | Reserve | $18.68 | $18.94 | 75% | Full | 4 | 1 | $18.94 |
| 7 | Reserve | $10.86 | $10.97 | 67% | Full | 3 | 1 | $10.97 |

- **Active total:** $255.40
- **Reserve total:** $62.75
- **All-in cost:** $318.15

### Recency Analysis
| Level | Overall Hold% | Last 90d Hold% | Recent Events | Trend |
| :--- | :--- | :--- | :--- | :--- |
| $54.41 | 17% | 20% | 5 | Stable |
| $51.42 | 25% | 25% | 8 | Stable |
| $46.94 | 22% | 40% | 5 | Improving |
| $48.43 | 36% | 50% | 8 | Improving |
| $31.67 | 80% | — | 0 | No recent data |
| $18.68 | 75% | — | 0 | No recent data |
| $10.86 | 67% | — | 0 | No recent data |

### Verification
- Tier check: PASS
- Bullet math: FAIL
- Pool deployment: PASS

### Stress Metrics
| Metric | Value | Assessment |
| :--- | :--- | :--- |
| Min active approaches | 6 | Strong |
| B1 distance | 1.5% | Ideal |
| Sector after onboard | 4x | OK |
| Budget feasible | $318 / $600 | Yes |
| Reserve 40%+ hold | 3 levels | Good |
| Active-reserve gap | 33% | Dead zone |

### KPI Card — FAIL
| KPI | Threshold | Actual | Status |
| :--- | :--- | :--- | :--- |
| Monthly Swing | >= 35.0% | 57.0% | PASS |
| Active Levels (hold >= 30%) | >= 3 | 1 | FAIL |
| Anchor Level (hold >= 50%) | >= 1 | 0 | FAIL |
| Dead Zone | < 30.0% | 33.3% | FAIL |
| Price Range | $5.0-$30.0 | $55.62 | FAIL |
| Cycle Data (>= 5 cycles) | >= 5 | 8 | PASS |
| Fill Consistency (>= 85%) | >= 85.0% | 100% | PASS |
| Strong Levels (hold >= 50%) | >= 2 | 0 | FAIL |
| Swing Compression | >= 0.65 | 0.87 | PASS |

### Flags
- HUT $32.84: cost $32.84 vs expected $164.20
- HUT $18.94: cost $18.94 vs expected $75.76
- HUT $10.97: cost $10.97 vs expected $54.85
- Active-reserve gap: 33%
- KPI gates failed: Active Levels (hold >= 30%), Anchor Level (hold >= 50%), Dead Zone, Price Range, Strong Levels (hold >= 50%)

### For Evaluator: Qualitative Questions
1. The 33% gap between active bottom and reserve top creates a dead zone. Can reserves realistically rescue the position?

---

## Candidate Detail: DNA

### Quick Facts
| Field | Value |
| :--- | :--- |
| Sector | Biotech |
| Price | $7.36 |
| Median Swing | 55.4% |
| Consistency | 100.0% |
| Active Radius | 20.0% |

### Score Breakdown
| Criterion | Score | Max | Detail |
| :--- | :--- | :--- | :--- |
| Bullets & Tier Quality | 6 | 15 | Sum of tier points for active bullets |
| B1 Proximity | 2 | 5 | Distance from current price to first fill |
| Zone Coverage | 4 | 15 | Spread of active bullets across price range |
| Reserve Depth | 0 | 5 | Viable reserve levels with 30%+ hold |
| Swing Magnitude | 10 | 10 | Monthly swing opportunity |
| Sector Diversity | 8 | 10 | Diminishing returns by sector count |
| Cycle Efficiency | 15 | 20 | Cycle speed, fill rate, consistency |
| Hold Rate Quality | 11 | 20 | Reliable levels + floor bonus |
| **Total** | **56** | **100** | |

### Bullet Plan
| # | Zone | Support | Buy At | Hold% | Tier | Approaches | Shares | Cost |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | Active | $6.26 | $6.42 | 71% | Full | 7 | 46 | $295.32 |

- **Active total:** $295.32
- **Reserve total:** $0.00
- **All-in cost:** $295.32

### Recency Analysis
| Level | Overall Hold% | Last 90d Hold% | Recent Events | Trend |
| :--- | :--- | :--- | :--- | :--- |
| $6.26 | 71% | 100% | 1 | Improving |

### Verification
- Tier check: PASS
- Bullet math: PASS
- Pool deployment: PASS

### Stress Metrics
| Metric | Value | Assessment |
| :--- | :--- | :--- |
| Min active approaches | 7 | Strong |
| B1 distance | 12.8% | Far |
| Sector after onboard | 2x | OK |
| Budget feasible | $295 / $600 | Yes |
| Reserve 40%+ hold | 0 levels | Weak |

### KPI Card — FAIL
| KPI | Threshold | Actual | Status |
| :--- | :--- | :--- | :--- |
| Monthly Swing | >= 35.0% | 55.4% | PASS |
| Active Levels (hold >= 30%) | >= 3 | 1 | FAIL |
| Anchor Level (hold >= 50%) | >= 1 | 1 | PASS |
| Dead Zone | < 30.0% | N/A | PASS |
| Price Range | $5.0-$30.0 | $7.36 | PASS |
| Cycle Data (>= 5 cycles) | >= 5 | 5 | PASS |
| Fill Consistency (>= 85%) | >= 85.0% | 100% | PASS |
| Strong Levels (hold >= 50%) | >= 2 | 1 | FAIL |
| Swing Compression | >= 0.65 | 0.80 | PASS |

### Flags
- KPI gates failed: Active Levels (hold >= 30%), Strong Levels (hold >= 50%)

### For Evaluator: Qualitative Questions
1. B1 requires a 12.8% pullback. Is the stock near resistance or mid-cycle? Entry timing affects capital efficiency.

---

## Portfolio Context

### Current Sectors
| Sector | Tickers | Count |
| :--- | :--- | :--- |
| AI | BBAI, SOUN, TEM | 3 |
| AI/Infra | SMCI | 1 |
| Biotech | STIM | 1 |
| Crypto | APLD, CIFR, CLSK | 3 |
| Energy | AR | 1 |
| Fintech | NU, RKT | 2 |
| Materials | TMC, UAMY, USAR | 3 |
| Nuclear | NNE, OKLO | 2 |
| Quantum | IONQ, RGTI | 2 |
| Semi | ARM, INTC, NVDA | 3 |
| Solar | RUN | 1 |
| Space | LUNR, RDW | 2 |
| Steel | CLF | 1 |
| Tech | OUST | 1 |
| eVTOL | ACHR | 1 |

### Concentration Thresholds
- No sectors at concentration limit

