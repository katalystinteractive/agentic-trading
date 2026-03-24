# Deep Dive Raw Data — CIFR — 2026-03-16

## Ticker Status
- **Classification:** EXISTING
- **Current price:** $15.06
- **Portfolio context:** **Pending orders:** 5
  - BUY 5 @ $14.82 — Bullet 1 — $14.28 HVN+PA, 50% hold rate, Full tier, wick-adjusted (2026-03-16)
  - BUY 5 @ $14.18 — Bullet 2 — $13.66 HVN+PA, 40% hold rate, Std tier, wick-adjusted (2026-03-16)
  - BUY 6 @ $13.09 — Bullet 3 — $13.02 PA, 71% hold rate, Full tier, wick-adjusted (2026-03-16)
  - BUY 5 @ $13.03 — Bullet 4 — $12.41 PA, 60% hold rate, Full tier, wick-adjusted (2026-03-16)
  - BUY 22 @ $5.38 — Reserve 1 — $5.27 PA, 67% hold rate, Full tier, wick-adjusted (2026-03-16)

## Existing Context

### Current Identity
# Agent Identity: Cipher Digital (CIFR)

## Persona
**The Digital Infrastructure Pivot.** Cipher Digital (formerly Cipher Mining) is transitioning from Bitcoin mining to HPC/AI data center development, with $9.3B in contracted lease revenue from AWS, Fluidstack, and Google. Massive monthly swings (67.8% median, 100% of months hit 10%+) make it a prime mean reversion target. Support structure starts at $14.28 HVN+PA (50% hold) with dense active levels down to $12.41, then a 59% dead zone gap to reserve territory at $5.38. 5/5 cycles profitable since onboarding.

## Strategy Specifics
*   **Cycle:** Early — bottoms Days 1-8 in 9/13 months (69%). Consistent early-month dip buyer.
*   **Key Levels:**
    *   Resistance: $16.02-$16.43 HVN (342M vol), $17.26-$17.68 HVN (298M vol), $18.50-$18.92 HVN (329M vol).
    *   Support: See `wick_analysis.md` (auto-updated by wick offset analyzer).
    *   **Wick-Adjusted Buy Levels (run 2026-03-16):**

        | Raw Support | Source | Hold Rate | Median Offset | Buy At | Zone | Tier |
        | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
        | $14.28 | HVN+PA | 50% | +3.77% | $14.82 | Active | Full |
        | $13.66 | HVN+PA | 40% | +3.86% | $14.18 | Active | Std |
        | $13.02 | PA | 71% | +0.54% | $13.09 | Active | Full |
        | $12.41 | PA | 60% | +5.00% | $13.03 | Active | Full |
        | $5.42 | PA | 40% | +4.06% | $5.64 | Reserve | Half |
        | $5.27 | PA | 67% | +2.18% | $5.38 | Reserve | Full |
        | $4.82 | PA | 25% | +0.00% | $4.82 | Reserve | Std |
        | $3.17 | PA | 33% | +4.10% | $3.30 | Reserve | Std |
        | $3.02 | HVN+PA | 25% | +1.04% | $3.05 | Reserve | Std |
        | $2.87 | PA | 50% | +5.23% | $3.02 | Reserve | Full |
        | $2.77 | PA | 50% | +2.53% | $2.84 | Reserve | Half |
        | $2.18 | PA | 33% | +0.00% | $2.18 | Reserve | Std |

    *   **Warning:** Convergence: $13.02 PA and $12.41 PA merge at buy-at $13.09 / $13.03 (within 0.5%). Both are legitimate support sources — keep both bullets.
    *   **Warning:** Gap: Last active bullet ($13.03) to first reserve ($5.38) is 59% gap. Intermediate level $5.42 at 40% hold provides partial coverage.
    *   **Monthly Swing:** 67.8% median swing, 100% of months hit 10%+. Source: ETF-sourced screener (BLOK ETF holding).
*   **Bullet Plan (Active Pool — $300):**
    *   B1: $14.82 (5 shares, ~$74.10) — $14.28 HVN+PA, 50% hold rate, Full tier. **PENDING.**
    *   B2: $14.18 (5 shares, ~$70.91) — $13.66 HVN+PA, 40% hold rate, Std tier. **PENDING.**
    *   B3: $13.09 (6 shares, ~$78.54) — $13.02 PA, 71% hold rate, Full tier. **PENDING.**
    *   B4: $13.03 (5 shares, ~$65.15) — $12.41 PA, 60% hold rate, Full tier. **PENDING.**
    *   Total active deployment: ~$289 if all fill.
*   **Reserve Plan ($300):**
    *   R1: $5.38 (22 shares, ~$118.47) — $5.27 PA, 67% hold rate, Full tier. **PENDING.**
    *   R2: $3.30 (28 shares, ~$92.40) — $3.17 PA, 33% hold rate, Std tier. **PENDING.**
    *   R3: $3.02 (29 shares, ~$87.58) — $2.87 PA, 50% hold rate, Full tier. **PENDING.**
    *   Total pending reserve: ~$298 if all fill.
*   **Projected Averages (if bullets fill):**

        | Scenario | Total Shares | Avg Cost | 10% Target |
        | :--- | :--- | :--- | :--- |
        | No current position | 0 | — | — |
        | + B1 fills | 5 | $14.82 | $16.30 |
        | + B2 fills | 10 | $14.50 | $15.95 |
        | + B3 fills | 16 | $13.97 | $15.37 |
        | + B4 fills | 21 | $13.75 | $15.12 |
        | + R1 fills | 43 | $9.47 | $10.41 |
        | + R2 fills | 71 | $7.03 | $7.74 |
        | + R3 fills | 100 | $5.87 | $6.46 |

*   **Short Interest:** 20.85% of float (64.4M shares), HIGH squeeze risk (score 55/100). Days to cover: 1.9. Shorts increasing +5.8%.
*   **Institutional Flow:** STRONG ACCUMULATION — 9/10 top holders increasing. Aggressive accumulators: D.E. Shaw +288%, Morgan Stanley +281%, Situational Awareness +100%, Jane Street +49%, Vanguard +43%.
*   **Sector Correlation:** Fellow BTC miner/HPC pivot with CLSK — monitor for correlation.
*   **Earnings:** Next 2026-05-05 (50 days) — CLEAR. Q1 2026 EPS miss (-207.7% surprise), but revenue trend strong (YoY +41.4%). Company pivoting to HPC leases (AWS 300MW, Fluidstack/Google 300MW).
*   **Status:** **RE-ENTRY MODE — Position closed 2026-03-16 (+4.5%, cycle 5). 5/5 cycles profitable (+5.9%, +7.2%, +7.0%, +7.8%, +4.5%). Wick data refreshed 2026-03-16. New bullet plan: B1 $14.82, B2 $14.18, B3 $13.09, B4 $13.03 pending. R1-R3 pending.**

### Current Memory
# Agent Memory: Cipher Mining (CIFR)

## Trade Log
- **2026-02-19:** BUY 7 shares @ $14.82 (Bullet 1 filled). Day low $14.66, triggered on midday dip. Cost: $103.74.
- **2026-02-19:** SELL 7 shares @ $15.70 (daily bounce exit). Revenue: $109.90. **Profit: +$6.16 (+5.9%).** Took the intraday bounce instead of waiting for $16.30 target. Position closed, no shares held.
- **2026-02-20:** BUY 3 shares @ $14.98 (B1 re-entry filled). Cost: $44.94.
- **2026-02-20:** BUY 7 shares @ $14.82 (B2 re-entry filled). Cost: $103.74. Day low $14.54. **Now holding 10 shares, avg $14.87. Target exit: $16.36 (~10%).**
- **2026-02-24:** SELL 13 shares @ $15.905 (full exit). Revenue: $206.77. Avg cost $14.83. **Profit: +$13.98 (+7.2%).** Position closed.
- **2026-03-02:** BUY 4 shares @ $14.90 (Bullet 2 filled, pre-market). Cost: $59.60. Now 4 shares @ $14.90 avg.
- **2026-03-02:** SELL 4 shares @ $15.95 (full exit). Revenue: $63.80. **Profit: +$4.20 (+7.0%).** Position closed.
- **2026-03-03:** BUY 2 shares @ $14.98 (B1 re-entry). Cost: $29.96. BUY 4 shares @ $14.87 (B2). Cost: $59.48. Total: 6 shares @ $14.91 avg.
- **2026-03-04:** SELL 6 shares @ $16.08 (full exit). Revenue: $96.48. **Profit: +$7.04 (+7.8%).** Position closed. 4/4 cycles profitable.

## Observations
- **2026-02-19:** Originally selected as bounce candidate from ETF-sourced screener (BLOK ETF holding). Converted to surgical strategy after monthly swing analysis revealed 67.8% median swing with 100% of months hitting 10%+.
- Wick analysis: $14.26 PA is the first reliable level at 62% hold rate. The $14.91 HVN+PA level above it has only 22% hold (2/9) — dead zone.
- CIFR limit adjusted from $15.00 (original bounce level at $14.86 HVN+PA) to $14.82 (wick-adjusted from $14.26 PA with 62% hold).

## Lessons
- *Originally misclassified as bounce-only. Monthly swing analysis proved it's a surgical-grade swing stock with reliable support structure.*

## Tool Outputs

### 1. Wick Offset Analysis
*Generated: 2026-03-16 21:06 | Data as of: 2026-03-16*

## Wick Offset Analysis: CIFR (13-Month, as of 2026-03-16)
**Current Price: $15.06**
**Monthly Swing: 67.8%** | 100% of months hit 10%+ | Active Zone: within 23.5% of current price

### Support Levels & Buy Recommendations
| Support | Source | Approaches | Held | Hold Rate | Median Offset | Buy At | Zone | Tier | Decayed | Trend | Fresh |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| $14.91 | HVN+PA | 12 | 2 | 17% | +0.51% | $14.98 | Active | Skip | 14% (Skipv) | - | 2026-03-16 |
| $14.28 | HVN+PA | 10 | 5 | 50% | +3.77% | $14.82 | Active | Full | 51% | ^ | 2026-03-16 |
| $13.66 | HVN+PA | 10 | 4 | 40% | +3.86% | $14.18 | Active | Std | 45% | ^ | 2026-03-09 |
| $13.02 | PA | 7 | 5 | 71% | +0.54% | $13.09 | Active | Full | 74% | - | 2026-03-06 |
| $12.41 | PA | 5 | 3 | 60% | +5.00% | $13.03 | Active | Full | 80% | ^ | 2026-03-09 |
| $11.40 | PA | 1 | 0 | 0% | N/A | N/A (no holds) | Reserve | Skip | 0% | ? | 2025-09-16 [D] |
| $7.17 | PA | 1 | 0 | 0% | N/A | N/A (no holds) | Reserve | Skip | 0% | ? | 2025-08-29 [D] |
| $6.95 | PA | 1 | 0 | 0% | N/A | N/A (no holds) | Reserve | Skip | 0% | ? | 2025-08-26 [D] |
| $6.15 | HVN+PA | 3 | 0 | 0% | N/A | N/A (no holds) | Reserve | Skip | 0% | ? | 2025-08-22 [D] |
| $5.84 | PA | 6 | 0 | 0% | N/A | N/A (no holds) | Reserve | Skip | 0% | ? | 2025-08-20 [D] |
| $5.67 | PA | 4 | 0 | 0% | N/A | N/A (no holds) | Reserve | Skip | 0% | ? | 2025-08-18 [D] |
| $5.42 | PA | 5 | 2 | 40% | +4.06% | $5.64 | Reserve | Half | 28% (Halfv) | ? | 2025-08-18 [D] |
| $5.27 | PA | 6 | 4 | 67% | +2.18% | $5.38 | Reserve | Full | 58% | ? | 2025-08-18 [D] |
| $4.82 | PA | 4 | 1 | 25% | +0.00% | $4.82 | Reserve | Std | 31% (Std^) | ? | 2025-08-13 [D] |
| $4.67 | PA | 3 | 1 | 33% | +1.71% | $4.75 | Reserve | Skip | 14% (Skipv) | ? | 2025-08-01 [D] |
| $3.94 | PA | 4 | 0 | 0% | N/A | N/A (no holds) | Reserve | Skip | 0% | ? | 2025-06-26 [D] |
| $3.83 | PA | 7 | 0 | 0% | N/A | N/A (no holds) | Reserve | Skip | 0% | ? | 2025-06-24 [D] |
| $3.73 | PA | 7 | 1 | 14% | +0.27% | $3.74 | Reserve | Half | 16% (Half^) | ? | 2025-06-24 [D] |
| $3.64 | HVN+PA | 5 | 0 | 0% | N/A | N/A (no holds) | Reserve | Skip | 0% | ? | 2025-06-24 [D] |
| $3.44 | PA | 4 | 0 | 0% | N/A | N/A (no holds) | Reserve | Skip | 0% | ? | 2025-06-13 [D] |
| $3.34 | PA | 5 | 0 | 0% | N/A | N/A (no holds) | Reserve | Skip | 0% | ? | 2025-06-17 [D] |
| $3.17 | PA | 6 | 2 | 33% | +4.10% | $3.30 | Reserve | Std | 36% | ? | 2025-06-23 [D] |
| $3.02 | HVN+PA | 8 | 2 | 25% | +1.04% | $3.05 | Reserve | Std | 31% (Std^) | ? | 2025-05-29 [D] |
| $2.87 | PA | 6 | 3 | 50% | +5.23% | $3.02 | Reserve | Full | 59% | ? | 2025-05-30 [D] |
| $2.77 | PA | 2 | 1 | 50% | +2.53% | $2.84 | Reserve | Half | 42% | ? | 2025-04-23 [D] |
| $2.25 | PA | 3 | 0 | 0% | N/A | N/A (no holds) | Reserve | Skip | 0% | ? | 2025-04-11 [D] |
| $2.18 | PA | 3 | 1 | 33% | +0.00% | $2.18 | Reserve | Std | 32% | ? | 2025-04-09 [D] |

### Detail: $14.91 (HVN+PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-10-06 | $14.33 | -3.87% | **BROKE** |
| 2025-10-22 | $15.04 | +0.89% | Yes |
| 2025-11-13 | $14.75 | -1.05% | **BROKE** |
| 2025-11-24 | $14.82 | -0.58% | **BROKE** |
| 2025-12-16 | $13.67 | -8.30% | **BROKE** |
| 2025-12-18 | $14.62 | -1.93% | **BROKE** |
| 2026-01-02 | $14.78 | -0.85% | **BROKE** |
| 2026-01-30 | $14.93 | +0.12% | Yes |
| 2026-02-09 | $14.66 | -1.66% | **BROKE** |
| 2026-02-23 | $14.07 | -5.62% | **BROKE** |
| 2026-03-04 | $14.46 | -2.99% | **BROKE** |
| 2026-03-16 | $14.67 | -1.59% | **BROKE** |

### Detail: $14.28 (HVN+PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-10-03 | $14.28 | -0.01% | **BROKE** |
| 2025-10-22 | $15.04 | +5.31% | Yes |
| 2025-11-13 | $13.55 | -5.12% | **BROKE** |
| 2025-11-24 | $14.82 | +3.77% | Yes |
| 2025-12-15 | $13.67 | -4.28% | **BROKE** |
| 2025-12-26 | $14.52 | +1.67% | Yes |
| 2026-02-02 | $14.93 | +4.51% | Yes |
| 2026-02-06 | $13.45 | -5.82% | **BROKE** |
| 2026-03-09 | $13.05 | -8.62% | **BROKE** |
| 2026-03-16 | $14.67 | +2.72% | Yes |

### Detail: $13.66 (HVN+PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-09-22 | $12.09 | -11.47% | **BROKE** |
| 2025-10-02 | $13.02 | -4.66% | **BROKE** |
| 2025-11-14 | $13.09 | -4.14% | **BROKE** |
| 2025-12-15 | $13.67 | +0.10% | Yes |
| 2025-12-29 | $14.52 | +6.33% | Yes |
| 2026-02-04 | $12.74 | -6.67% | **BROKE** |
| 2026-02-06 | $13.45 | -1.51% | **BROKE** |
| 2026-02-19 | $14.07 | +3.03% | Yes |
| 2026-03-03 | $14.30 | +4.68% | Yes |
| 2026-03-09 | $13.03 | -4.58% | **BROKE** |

### Detail: $13.02 (PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-09-22 | $12.09 | -7.14% | **BROKE** |
| 2025-10-02 | $13.02 | +0.00% | Yes |
| 2025-11-14 | $13.09 | +0.54% | Yes |
| 2025-12-16 | $13.67 | +4.99% | Yes |
| 2026-02-04 | $12.74 | -2.11% | **BROKE** |
| 2026-02-06 | $13.45 | +3.30% | Yes |
| 2026-03-06 | $13.03 | +0.08% | Yes |

### Detail: $12.41 (PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-09-22 | $12.09 | -2.58% | **BROKE** |
| 2025-09-29 | $11.40 | -8.10% | **BROKE** |
| 2025-11-21 | $13.09 | +5.48% | Yes |
| 2026-02-04 | $12.64 | +1.81% | Yes |
| 2026-03-09 | $13.03 | +5.00% | Yes |

### Detail: $11.40 (PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-09-16 | $10.49 | -8.02% | **BROKE** |

### Detail: $7.17 (PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-08-29 | $6.95 | -3.07% | **BROKE** |

### Detail: $6.95 (PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-08-26 | $6.48 | -6.76% | **BROKE** |

### Detail: $6.15 (HVN+PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-07-09 | $5.98 | -2.72% | **BROKE** |
| 2025-07-16 | $5.95 | -3.21% | **BROKE** |
| 2025-08-22 | $5.71 | -7.11% | **BROKE** |

### Detail: $5.84 (PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-02-06 | $5.71 | -2.23% | **BROKE** |
| 2025-02-13 | $5.56 | -4.79% | **BROKE** |
| 2025-07-03 | $5.76 | -1.37% | **BROKE** |
| 2025-07-08 | $5.81 | -0.51% | **BROKE** |
| 2025-08-18 | $5.29 | -9.42% | **BROKE** |
| 2025-08-20 | $5.32 | -8.90% | **BROKE** |

### Detail: $5.67 (PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-02-06 | $5.53 | -2.47% | **BROKE** |
| 2025-07-02 | $4.99 | -11.99% | **BROKE** |
| 2025-07-28 | $5.64 | -0.53% | **BROKE** |
| 2025-08-18 | $5.29 | -6.70% | **BROKE** |

### Detail: $5.42 (PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-02-06 | $5.47 | +0.92% | Yes |
| 2025-07-02 | $4.99 | -7.93% | **BROKE** |
| 2025-07-15 | $5.81 | +7.20% | Yes |
| 2025-07-29 | $5.30 | -2.21% | **BROKE** |
| 2025-08-18 | $5.29 | -2.40% | **BROKE** |

### Detail: $5.27 (PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-02-11 | $5.53 | +4.93% | Yes |
| 2025-02-21 | $5.47 | +3.80% | Yes |
| 2025-07-02 | $4.99 | -5.31% | **BROKE** |
| 2025-07-29 | $5.30 | +0.57% | Yes |
| 2025-08-14 | $4.91 | -6.83% | **BROKE** |
| 2025-08-18 | $5.29 | +0.38% | Yes |

### Detail: $4.82 (PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-02-24 | $4.75 | -1.45% | **BROKE** |
| 2025-07-01 | $4.55 | -5.60% | **BROKE** |
| 2025-08-01 | $4.82 | +0.00% | Yes |
| 2025-08-13 | $4.71 | -2.28% | **BROKE** |

### Detail: $4.67 (PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-02-24 | $4.75 | +1.71% | Yes |
| 2025-06-30 | $4.29 | -8.14% | **BROKE** |
| 2025-08-01 | $4.55 | -2.57% | **BROKE** |

### Detail: $3.94 (PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-02-25 | $3.85 | -2.41% | **BROKE** |
| 2025-03-05 | $3.78 | -4.06% | **BROKE** |
| 2025-06-09 | $3.87 | -1.78% | **BROKE** |
| 2025-06-26 | $3.65 | -7.36% | **BROKE** |

### Detail: $3.83 (PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-02-25 | $3.81 | -0.52% | **BROKE** |
| 2025-03-05 | $3.78 | -1.31% | **BROKE** |
| 2025-03-07 | $3.64 | -4.96% | **BROKE** |
| 2025-05-16 | $3.17 | -17.23% | **BROKE** |
| 2025-06-06 | $3.63 | -5.22% | **BROKE** |
| 2025-06-16 | $3.74 | -2.35% | **BROKE** |
| 2025-06-24 | $3.63 | -5.22% | **BROKE** |

### Detail: $3.73 (PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-02-25 | $3.31 | -11.26% | **BROKE** |
| 2025-05-16 | $3.17 | -15.01% | **BROKE** |
| 2025-06-04 | $3.35 | -10.16% | **BROKE** |
| 2025-06-06 | $3.63 | -2.68% | **BROKE** |
| 2025-06-16 | $3.74 | +0.27% | Yes |
| 2025-06-18 | $3.59 | -3.75% | **BROKE** |
| 2025-06-24 | $3.63 | -2.68% | **BROKE** |

### Detail: $3.64 (HVN+PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-02-25 | $3.31 | -9.17% | **BROKE** |
| 2025-05-16 | $3.17 | -13.01% | **BROKE** |
| 2025-06-04 | $3.35 | -8.05% | **BROKE** |
| 2025-06-06 | $3.59 | -1.49% | **BROKE** |
| 2025-06-24 | $3.63 | -0.39% | **BROKE** |

### Detail: $3.44 (PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-03-04 | $3.31 | -3.78% | **BROKE** |
| 2025-05-16 | $3.17 | -7.85% | **BROKE** |
| 2025-06-04 | $3.35 | -2.59% | **BROKE** |
| 2025-06-13 | $3.29 | -4.36% | **BROKE** |

### Detail: $3.34 (PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-03-04 | $3.31 | -0.90% | **BROKE** |
| 2025-05-13 | $3.22 | -3.53% | **BROKE** |
| 2025-05-16 | $3.17 | -5.09% | **BROKE** |
| 2025-06-03 | $3.26 | -2.54% | **BROKE** |
| 2025-06-17 | $3.29 | -1.50% | **BROKE** |

### Detail: $3.17 (PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-03-04 | $3.31 | +4.42% | Yes |
| 2025-03-11 | $2.87 | -9.46% | **BROKE** |
| 2025-03-24 | $3.02 | -4.73% | **BROKE** |
| 2025-05-13 | $3.02 | -4.73% | **BROKE** |
| 2025-06-02 | $3.08 | -2.84% | **BROKE** |
| 2025-06-23 | $3.29 | +3.79% | Yes |

### Detail: $3.02 (HVN+PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-03-10 | $2.87 | -4.92% | **BROKE** |
| 2025-03-19 | $2.88 | -4.59% | **BROKE** |
| 2025-03-24 | $2.96 | -1.94% | **BROKE** |
| 2025-04-25 | $2.93 | -2.93% | **BROKE** |
| 2025-05-01 | $2.91 | -3.59% | **BROKE** |
| 2025-05-06 | $2.88 | -4.75% | **BROKE** |
| 2025-05-12 | $3.02 | +0.05% | Yes |
| 2025-05-29 | $3.08 | +2.04% | Yes |

### Detail: $2.87 (PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-03-10 | $2.87 | +-0.00% | **BROKE** |
| 2025-03-19 | $2.84 | -1.05% | **BROKE** |
| 2025-04-24 | $2.81 | -2.09% | **BROKE** |
| 2025-05-01 | $2.88 | +0.17% | Yes |
| 2025-05-15 | $3.02 | +5.23% | Yes |
| 2025-05-30 | $3.08 | +7.32% | Yes |

### Detail: $2.77 (PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-03-10 | $2.84 | +2.53% | Yes |
| 2025-04-23 | $2.77 | +-0.00% | **BROKE** |

### Detail: $2.25 (PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-03-28 | $2.18 | -3.11% | **BROKE** |
| 2025-04-09 | $2.03 | -9.78% | **BROKE** |
| 2025-04-11 | $2.20 | -2.22% | **BROKE** |

### Detail: $2.18 (PA)
| Date | Wick Low | Offset | Held |
| :--- | :--- | :--- | :--- |
| 2025-03-28 | $2.18 | +0.00% | Yes |
| 2025-04-07 | $1.86 | -14.68% | **BROKE** |
| 2025-04-09 | $2.03 | -6.88% | **BROKE** |

### Suggested Bullet Plan
*Based on 67.8% monthly swing — Active zone within 23.5% of current price.*

| # | Zone | Level | Buy At | Hold% | Tier | Shares | ~Cost |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | Active | $14.28 | $14.82 | 50% | Full | 5 | $74.10 |
| 2 | Active | $13.66 | $14.18 | 40% | Std | 5 | $70.91 |
| 3 | Active | $13.02 | $13.09 | 71% | Full | 6 | $78.54 |
| 4 | Active | $12.41 | $13.03 | 60% | Full | 5 | $65.15 |
| 5 | Reserve | $5.27 | $5.38 | 67% | Full | 22 | $118.47 |
| 6 | Reserve | $3.17 | $3.30 | 33% | Std | 28 | $92.40 |
| 7 | Reserve | $2.87 | $3.02 | 50% | Full | 29 | $87.58 |

*Bullet plan is a suggestion — adjust based on cycle timing and position.*

### 2. Stock Verification
### 2. The 13-Month Cycle Audit Table (CIFR)
| Month | Low ($) & Date | High ($) & Date | Swing % | Drop from Prev High | Bottom Timing |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Mar 2026 | $13.03 (12) | $16.28 (4) | 24.9% | -27.4% | Mid |
| Feb 2026 | $12.64 (5) | $17.96 (10) | 42.1% | -35.8% | Early |
| Jan 2026 | $14.78 (2) | $19.70 (16) | 33.3% | -28.7% | Early |
| Dec 2025 | $13.67 (16) | $20.74 (9) | 51.7% | -46.4% | Mid |
| Nov 2025 | $13.09 (21) | $25.52 (5) | 95.0% | -40.5% | Late |
| Oct 2025 | $13.02 (2) | $22.00 (15) | 69.0% | -16.2% | Early |
| Sep 2025 | $7.08 (5) | $15.54 (24) | 119.4% | -18.7% | Early |
| Aug 2025 | $4.55 (8) | $8.71 (29) | 91.4% | -35.9% | Early |
| Jul 2025 | $4.99 (2) | $7.10 (22) | 42.3% | --2.7% | Early |
| Jun 2025 | $3.08 (2) | $4.86 (30) | 57.8% | -21.2% | Early |
| May 2025 | $2.88 (6) | $3.91 (16) | 36.0% | -9.4% | Early |
| Apr 2025 | $1.86 (4) | $3.17 (25) | 70.7% | -59.6% | Early |
| Mar 2025 | $2.18 (31) | $4.60 (3) | 111.0% | - | Late |

### 3. The High Volume Node (HVN) Audit Table (Last 6 Months)
| Price Zone ($) | Volume Intensity | Role | Approx Date |
| :--- | :--- | :--- | :--- |
| $13.95 - $14.37 | 464.7M | HVN | Sep |
| $14.37 - $14.78 | 453.3M | HVN | Oct |
| $16.02 - $16.43 | 342.1M | HVN | Oct |
| $18.50 - $18.92 | 329.1M | HVN | Oct |
| $17.26 - $17.68 | 298.3M | HVN | Oct |

### 3. Technical Scanner
## Technical Scan: Cipher Digital Inc. (CIFR)
**Current Price: $15.06** | Date: 2026-03-16

### Trend Indicators
| Indicator | Value | Price Position | Signal |
| :--- | :--- | :--- | :--- |
| SMA 20 | $15.15 | Below | Bearish |
| SMA 50 | $16.19 | Below | Bearish |
| SMA 200 | $12.53 | Above | Bullish |
| EMA 9 | $14.54 | Above | Bullish |
| EMA 21 | $15.06 | Above | Bullish |

### Momentum Indicators
| Indicator | Value | Zone | Signal |
| :--- | :--- | :--- | :--- |
| RSI (14) | 49.0 | Bearish zone | Neutral-Bear |
| MACD | -0.544 | Below signal | Bearish |
| MACD Signal | -0.496 | Histogram: -0.048 | — |
| Stochastic %K/%D | 42.4/26.2 | Neutral | Bullish |

### Volatility
| Indicator | Value | Position | Signal |
| :--- | :--- | :--- | :--- |
| Bollinger Upper | $17.16 | 48% of band | Neutral |
| Bollinger Lower | $13.15 | Width: $4.01 | — |
| ATR (14) | $1.34 (8.9%) | High volatility | — |

### Key Support/Resistance Levels
| Level | Price | Type | Touches | Last Tested |
| :--- | :--- | :--- | :--- | :--- |
| Support | $15.04 (-0.1%) | Support | 1 | 2025-10-22 |
| Support | $13.67 (-9.2%) | Support | 1 | 2025-12-16 |
| Support | $13.09 (-13.1%) | Support | 1 | 2025-11-21 |
| Support | $12.64 (-16.1%) | Support | 1 | 2026-02-05 |
| Resistance | $19.70 (+30.8%) | Resistance | 1 | 2026-01-16 |
| Resistance | $21.16 (+40.5%) | Resistance | 1 | 2025-11-28 |
| Resistance | $22.00 (+46.1%) | Resistance | 1 | 2025-10-15 |
| Resistance | $7.10 (-52.9%) | Resistance | 1 | 2025-07-22 |

### Signal Summary
| Metric | Value |
| :--- | :--- |
| Overall Signal | **Neutral-Bullish** |
| Score | +0 |
| Bullish Factors | Above SMA 200, Above EMA 9, Above EMA 21 |
| Bearish Factors | Below SMA 20, Below SMA 50, MACD bearish |

### 4. Earnings Analysis
*Generated: 2026-03-16 21:06*

## Earnings Analysis: Cipher Digital Inc. (CIFR)

### Next Earnings
| Metric | Value |
| :--- | :--- |
| Earnings Date | 2026-05-05 |
| Days Until | 50 |
| EPS Estimate | $-0.11 |
| Revenue Estimate | $36.3M |
| Earnings Rule | Clear (>50d out) |

### Earnings History
| Quarter | EPS Est | EPS Actual | Surprise% | 1-Day% | 5-Day% | Reaction |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Q1 2026 | $0.13 | $-0.14 | -207.7% | -3.0% | -14.1% | Bearish |
| Q4 2025 | $0.11 | $0.10 | -6.2% | -1.1% | -13.7% | Bearish |
| Q3 2025 | $0.06 | $0.08 | 33.3% | -2.5% | +9.2% | Bearish |
| Q2 2025 | $0.04 | $0.02 | -46.7% | -0.7% | +12.8% | Bearish |
| Q1 2025 | $0.05 | $0.14 | 200.0% | +1.8% | -8.5% | Bullish |
| Q4 2024 | $-0.08 | $-0.26 | -225.0% | +6.5% | +41.0% | Strong Bull |
| Q3 2024 | $0.06 | $-0.01 | -115.8% | -6.9% | +0.8% | Strong Bear |
| Q2 2024 | N/A | $0.21 | 8184.0% | -0.4% | -2.1% | Bearish |

### Revenue Trend
| Quarter | Revenue | QoQ Growth% | YoY Growth% |
| :--- | :--- | :--- | :--- |
| Q4 2025 | $59.7M | -16.7% | +41.4% |
| Q3 2025 | $71.7M | +64.6% | N/A |
| Q2 2025 | $43.6M | -11.0% | N/A |
| Q1 2025 | $49.0M | +16.0% | N/A |
| Q4 2024 | $42.2M | N/A | N/A |

### 5. News Sentiment
*Generated: 2026-03-16 21:06*

## News & Sentiment: Cipher Digital Inc. (CIFR)
*Sources: Finviz (100), Google News (100), yfinance (10) | Method: VADER | Deep Dives: 5*

### Headlines (Top 30, Deduplicated)
| Date | Source | Headline | Sentiment | Score | Catalysts |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-03-16 | MarketBeat | 80,000 Shares in Cipher Mining Inc. $CIFR Bought by Ionic Ca... | Positive | +0.30 | Earnings, Corporate |
| 2026-03-16 | Benzinga | Cipher Digital Stock Moves Higher As Bitcoin Surges Past $74... | Neutral | +0.00 | — |
| 2026-03-16 | TipRanks | Why Cipher Mining Stock Is Suddenly Losing Altitude - TipRan... | Negative | -0.38 | — |
| 2026-03-16 | Benzinga | 10 Information Technology Stocks With Whale Alerts In Today'... | Neutral | +0.00 | — |
| 2026-03-16 | Insider Monkey | Cipher Digital (CIFR) Reaffirms Focus on AI Infrastructure | Neutral | +0.00 | — |
| 2026-03-15 | MarketBeat | Clearline Capital LP Purchases Shares of 1,220,530 Cipher Mi... | Positive | +0.30 | Earnings |
| 2026-03-15 | MarketBeat | Cantor Fitzgerald L. P. Sells 617,979 Shares of Cipher Minin... | Positive | +0.30 | Earnings |
| 2026-03-15 | National Today | Clearline Capital Buys Over 1.2 Million Shares of Cipher Min... | Positive | +0.30 | — |
| 2026-03-14 | MarketBeat | FORA Capital LLC Purchases New Position in Cipher Mining Inc... | Neutral | +0.00 | Earnings |
| 2026-03-14 | TipRanks | Crypto Currents: SEC, CFTC sign MOU for Joint Harmonization ... | Positive | +0.44 | Regulatory |
| 2026-03-13 | GuruFocus.com | Crypto Stocks Jump As Bitcoin Finds Its Footing | Neutral | +0.00 | — |
| 2026-03-13 | Blockspace | Cipher Digital undervalued on enterprise valuation per megaw... | Neutral | +0.00 | — |
| 2026-03-13 | MarketBeat | Aurelius Capital Management LP Acquires Shares of 500,000 Ci... | Positive | +0.30 | Earnings, Corporate |
| 2026-03-13 | MarketBeat | Cipher Mining (NASDAQ:CIFR) Shares Up 8.1% - Here's What Hap... | Positive | +0.30 | Earnings |
| 2026-03-13 | MarketBeat | Van ECK Associates Corp Reduces Holdings in Cipher Mining In... | Neutral | +0.00 | Earnings |
| 2026-03-13 | TechStock² | Cipher Digital Stock Price Falls After KBW Target Cut; CIFR ... | Negative | -0.27 | — |
| 2026-03-13 | Simply Wall St. | Assessing Cipher Digital (CIFR) Valuation As It Shifts From ... | Neutral | +0.00 | — |
| 2026-03-12 | simplywall.st | Cipher Digital (CIFR) Valuation Check As AI Infrastructure P... | Positive | +0.46 | Short |
| 2026-03-12 | TipRanks | Why Cipher Mining Stock Is Suddenly Sliding - TipRanks | Neutral | +0.00 | — |
| 2026-03-12 | Simply Wall St. | Cipher Digital (CIFR) Deepens AI Pivot: Do Long-Term HPC Lea... | Negative | -0.64 | — |
| 2026-03-11 | Blockspace | Why Canaan bought Cipher Digitals JV assets in West Texas | Positive | +0.18 | — |
| 2026-03-11 | Blockspace | The Last Bitcoin Mining Bull Market Ever? BTC Mining Expert ... | Negative | -0.10 | — |
| 2026-03-11 | 24/7 Wall St. | Wall Street Cuts Cipher Mining (CIFR) and TeraWulf (WULF) Pr... | Negative | -0.30 | Analyst |
| 2026-03-11 | Yahoo Finance | Cipher Digital Inc. (CIFR) Gains As Market Dips: What You Sh... | Positive | +0.34 | — |
| 2026-03-11 | MarketBeat | Cipher Mining Inc. $CIFR Shares Acquired by American Century... | Positive | +0.30 | Earnings |
| 2026-03-11 | MarketBeat | Keefe, Bruyette & Woods Has Lowered Expectations for Cipher ... | Negative | -0.13 | Earnings |
| 2026-03-10 | simplywall.st | Why Cipher Digital (CIFR) Is Down 9.2% After Surging Revenue... | Negative | -0.55 | Earnings |
| 2026-03-09 | Zacks | Wall Street Analysts Think Cipher Digital Inc. (CIFR) Is a G... | Positive | +0.44 | — |
| 2026-03-08 | MarketBeat | 239,015 Shares in Cipher Mining Inc. $CIFR Acquired by Regal... | Positive | +0.30 | Earnings |
| 2026-03-05 | Trefis | Cipher Digital Stock (+9.0%): AI Pivot Gains Traction at Mor... | Positive | +0.34 | — |

### Sentiment Summary
| Metric | Value |
| :--- | :--- |
| Articles Analyzed | 30 |
| Positive | 14 (47%) |
| Neutral | 9 (30%) |
| Negative | 7 (23%) |
| Average Score | +0.073 |
| Overall Sentiment | **Neutral** |
| Total Unique Headlines | 183 |

### Detected Catalysts
| Category | Count | Headlines |
| :--- | :--- | :--- |
| Earnings | 11 | 80,000 Shares in Cipher Mining Inc. $CIF..; Clearline Capital LP Purchases Shares of.. |
| Corporate | 2 | 80,000 Shares in Cipher Mining Inc. $CIF..; Aurelius Capital Management LP Acquires .. |
| Regulatory | 1 | Crypto Currents: SEC, CFTC sign MOU for .. |
| Short | 1 | Cipher Digital (CIFR) Valuation Check As.. |
| Analyst | 1 | Wall Street Cuts Cipher Mining (CIFR) an.. |

### Deep Dive Articles

#### Wall Street Analysts Think Cipher Digital Inc. (CIFR) Is a Good Investment: Is It?
*Source: Zacks | Date: 2026-03-09 | Sentiment: Positive (+0.97)*

> Investors often turn to recommendations made by Wall Street analysts before making a Buy, Sell, or Hold decision about a stock. While media reports about rating changes by these brokerage-firm employed (or sell-side) analysts often affect a stock's price, do they really matter?

> Let's take a look at what these Wall Street heavyweights have to say aboutCipher Digital Inc.(CIFR) before we discuss the reliability of brokerage recommendations and how to use them to your advantage.

> Cipher Digital Inc. currently has an average brokerage recommendation (ABR) of 1.50, on a scale of 1 to 5 (Strong Buy to Strong Sell), calculated based on the actual recommendations (Buy, Hold, Sell, etc.) made by 16 brokerage firms. An ABR of 1.50 approximates between Strong Buy and Buy.

> Of the 16 recommendations that derive the current ABR, 12 are Strong Buy and two are Buy. Strong Buy and Buy respectively account for 75% and 12.5% of all recommendations.

> Check price target & stock forecast for Cipher Digital Inc. here>>>

**Catalysts:** Analyst

#### Clear Street Cuts PT on Cipher Digital (CIFR) to $32 From $34 - Here's Why
*Source: Insider Monkey | Date: 2026-02-28 | Sentiment: Positive (+0.96)*

> Cipher Digital (NASDAQ:CIFR) is one ofthe best hot stocks under $20 to buy. On February 25, Clear Street cut the price target on Cipher Digital (NASDAQ:CIFR) to $32 from $34 and maintained a Buy rating on the shares. The firm told investors that it is remaining bullish on the stock coming out of the fiscal Q4 earnings as it sees a clear step-change in its earnings profile beginning in Q4, as lease revenue from Amazon and Fluidstack begins contributing in earnest. It believes that the inflection is underappreciated, especially given the quality of counterparties and the long-duration nature of the leases.

> The rating update came after Cipher Digital (NASDAQ:CIFR) released its fiscal Q4 and full-year 2025 earnings on February 24, announcing that it rebranded from Cipher Mining to Cipher Digital, reflecting its pivot from bitcoin mining to HPC data center development. Fiscal Q4 2025 revenue came up to $60 million, with an adjusted net loss of $55 million. The company further reported that it secured 600 MW gross of total contracted HPC capacity to date across two leases, a 15-year 300 MW lease with AWS and a 10-year 300 MW lease with Fluidstack and Google. In addition, Cipher Digital (NASDAQ:CIFR) completed three bond offerings to finance HPC data center buildouts for aggregate proceeds of $3.73 billion.

> Cipher Digital (NASDAQ:CIFR) develops and operates bitcoin mining data centers. The company specializes in industrial-scale Bitcoin mining and is dedicated to enhancing and fortifying the critical infrastructure of the Bitcoin network in the US.

> While we acknowledge the potential of CIFR as an investment, we believe certain AI stocks offer greater upside potential and carry less downside risk. If you’re looking for an extremely undervalued AI stock that also stands to benefit significantly from Trump-era tariffs and the onshoring trend, see our free report on thebest short-term AI stock.

> READ NEXT:30 Stocks That Should Double in 3 Yearsand11 Hidden AI Stocks to Buy Right Now.

**Catalysts:** Earnings, Regulatory, Equity, Analyst, Short

#### Cipher Digital Q4 Loss Wider Than Expected, Revenues Down Sequentially
*Source: Zacks | Date: 2026-02-25 | Sentiment: Negative (-0.66)*

> Cipher DigitalCIFR reported a fourth-quarter 2025 loss of $1.92 per share, significantly wider than the 12-cent loss projected by the Zacks Consensus Estimate.Cipher Digital reported a GAAP loss of $1.85 per share, which represents a sharp year-over-year deterioration from earnings of 5 cents. On an adjusted basis, the company posted a loss of 14 cents per share, deteriorating sequentially from earnings of 10 cents.CIFR reported revenues of $59.7 million for the fourth quarter of 2025, marking a significant decrease of 16.7% from $71.7 million reported in the previous quarter. The sequential decline was primarily caused by reduced mining capacity following the decommissioning of Black Pearl and the divestiture of joint venture sites as part of the mining exit strategy. The figure missed the Zacks Consensus Estimate by 23.31%.Cipher Digital officially rebranded from Cipher Mining to Cipher Digital, reflecting a full pivot from bitcoin mining to high-performance computing (HPC) data center development.

> Cipher Mining Inc. price-consensus-eps-surprise-chart - Cipher Mining Inc. Quote

> In the fourth quarter of 2025, total costs and operating expenses rose sharply to $360.3 million, up from $109.3 million in the prior quarter.The company reported a net loss of $734.2 million in the fourth quarter, compared with a modest loss of $3.3 million in the previous quarter. A major driver of the quarterly loss was the $410.3 million change in fair value of warrant liability, a non-cash accounting adjustment.On an adjusted basis, Cipher Digital reported a loss of $54.5 million, marking a substantial quarter-over-quarter deterioration from $40.7 million in adjusted earnings.Cipher Digital reported an operating loss of $300.6 million in the fourth quarter, widening sharply from a $37.6 million loss in the prior quarter.Adjusted EBITDA reported a loss of $38.9 million in the fourth quarter, marking a sharp sequential deterioration of $40.8 million.

> In the fourth quarter of 2025, the company completed the sale of its 49% ownership interests in the Alborz, Bear and Chief joint venture sites, marking a decisive step in exiting non-core mining assets.In parallel, Black Pearl was fully decommissioned from bitcoin mining operations in February 2026. The company has secured 600 MW of total contracted HPC capacity to date across two long-term leases, including a 15-year, 300 MW agreement with AWS and a 10-year, 300 MW lease with Fluidstack and Google.As part of the wind-down, the company recorded losses related to miners held for sale, asset impairments and disposal of mining equipment during the fourth quarter of 2025. Cipher Digital is strategically monetizing its bitcoin holdings, with approximately 1,166 BTC being managed down as part of its transition plan.In the fourth quarter of 2025, total operating hashrate declined to roughly 11.6 EH/s from 23.6 EH/s in the third quarter of 2025, reflecting the decommissioning of Black Pearl and divested joint venture sites.

> As of Dec. 31, 2025, Cipher Digital had cash and cash equivalents of $628.3 million compared with $1.2 billion as of Sept. 30, 2025.As of Dec. 31, 2025, total assets expanded to $4.29 billion, up from $2.84 billion as of Sept. 30, 2025.The company reported $2.04 billion in restricted cash, including $1.76 billion classified as current and $275.1 million as noncurrent, largely tied to project-level financing.

**Catalysts:** Earnings, Regulatory

#### Cipher Mining (CIFR) Pivot Toward Hyperscale Infrastructure Follows $734M Q4 Net Loss
*Source: Insider Monkey | Date: 2026-02-25 | Sentiment: Positive (+0.98)*

> Cipher Mining Inc. (NASDAQ:CIFR) is one of thebest high volume stocks to invest in now. On February 24, Cipher Mining reported Q4 2025 revenue of $60 million, which was a decline attributed to a challenging Bitcoin mining environment and lower asset prices. The company posted a GAAP net loss of $734 million, primarily driven by non-cash items, including a $450 million mark-to-market loss on convertible notes and $141 million in impairments at its Black Pearl and Odessa facilities.

> Despite these losses, the company maintains a strong liquidity position with $754 million in cash and Bitcoin as of year-end 2025. The quarter marked a strategic pivot toward digital infrastructure and hyperscale computing, supported by a successful $2 billion bond offering that was oversubscribed 6.5 times. This funding secures the remaining capital expenditures for the Black Pearl project and supports a 3.4-gigawatt development pipeline.

> Cipher Mining Inc. (NASDAQ:CIFR) has already secured $9.3 billion in contracted revenue from data center leases, with expectations for significant annualized net operating income to begin in late 2026 as it transitions away from its legacy mining operations. Management expressed confidence in the Texas market, noting that West Texas is well-positioned to become a global hub for data centers.

> Cipher Mining Inc. (NASDAQ:CIFR), together with its subsidiaries, develops and operates industrial-scale data centers in the US.

> While we acknowledge the potential of CIFR as an investment, we believe certain AI stocks offer greater upside potential and carry less downside risk. If you’re looking for an extremely undervalued AI stock that also stands to benefit significantly from Trump-era tariffs and the onshoring trend, see our free report on thebest short-term AI stock.

**Catalysts:** Earnings, Regulatory, Corporate, Equity, Short

#### Cipher Mining (CIFR) Jumps 12.5% on Strong Revenues, Business Transition
*Source: Insider Monkey | Date: 2026-02-25 | Sentiment: Positive (+0.98)*

> We recently published10 Stocks Winning the Market. Cipher Mining Inc. (NASDAQ:CIFR) was one of the best performers on Tuesday.

> Cipher Mining saw its share prices jump by 12.48 percent on Tuesday to finish at $17.12 apiece as investors cheered the company’s strong bitcoin mining performance, while digesting its rebranding initiative to reflect its business transition.

> In an updated report, Cipher Mining Inc. (NASDAQ:CIFR) said that it would change its name to Cipher Digital to reflect its strategic transition toward high-performance computing.

> “Cipher is focused on sourcing and securing power, developing advanced data centers purpose-built for HPC workloads, and leasing capacity to the world’s leading technology companies. While bitcoin mining played a foundational role in building Cipher’s power origination expertise and large-scale development capabilities, the Company’s identity has evolved to focus on enabling next-generation compute at industrial scale,” Cipher Mining Inc. (NASDAQ:CIFR) said.

> In line with the initiative, the company divested its 49 percent stake in three 40 MW joint venture sites, Alborz, Bear, and Chief, as well as select bitcoin mining machines previously deployed at Black Pearl.

**Catalysts:** Regulatory

### 6. Short Interest
## Short Interest Analysis

### Short Interest Summary
| Ticker | Shares Short | Short Ratio | Short % Float | Change from Prior |
| :--- | :--- | :--- | :--- | :--- |
| CIFR | 64.37M | 1.95 | 20.85% | +5.8% (increasing) |

### Squeeze Risk Assessment
| Ticker | Risk Rating | Score (/100) | Key Factors |
| :--- | :--- | :--- | :--- |
| CIFR | HIGH | 55 | High short% (20.8%); Low DTC (1.9); Shorts slowly increasing |

### Context
| Ticker | Float | Shares Outstanding | Avg Volume | Days to Cover |
| :--- | :--- | :--- | :--- | :--- |
| CIFR | 330.08M | 405.12M | 29.31M | 1.9 |

### 7. Institutional Flow
*Generated: 2026-03-16 21:06*

## Institutional & Insider Flow: Cipher Digital Inc. (CIFR)

### Top Institutional Holders
| # | Holder | Shares | Value | % Out | % Change | Date Reported |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | V3 Holding Ltd                           | 61.32M | $923.4M | 15.14% | -6.89% | 2025-12-31 |
| 2 | Vanguard Group Inc | 32.68M | $492.2M | 8.07% | 43.24% | 2025-12-31 |
| 3 | Blackrock Inc. | 28.16M | $424.0M | 6.95% | 17.07% | 2025-12-31 |
| 4 | Jane Street Group, LLC | 16.42M | $247.3M | 4.05% | 48.72% | 2025-12-31 |
| 5 | Shaw D.E. & Co., Inc. | 15.39M | $231.7M | 3.80% | 287.59% | 2025-12-31 |
| 6 | Situational Awareness LP                           | 10.47M | $157.7M | 2.58% | 100.00% | 2025-12-31 |
| 7 | Geode Capital Management, LLC | 8.16M | $123.0M | 2.02% | 7.34% | 2025-12-31 |
| 8 | State Street Corporation | 8.08M | $121.7M | 1.99% | 10.16% | 2025-12-31 |
| 9 | Value Aligned Research Advisors, LLC                           | 7.45M | $112.2M | 1.84% | 45.90% | 2025-12-31 |
| 10 | Morgan Stanley | 5.64M | $85.0M | 1.39% | 280.91% | 2025-12-31 |

### Top Mutual Fund Holders
| # | Fund | Shares | Value | % Out | % Change | Date Reported |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | VANGUARD INDEX FUNDS-Vanguard Total Stock Market Index Fund | 11.81M | $177.9M | 2.92% | 26.37% | 2025-12-31 |
| 2 | iShares Trust-iShares Russell 2000 ETF | 8.22M | $123.8M | 2.03% | 23.99% | 2025-12-31 |
| 3 | VANGUARD WORLD FUND-Vanguard Information Technology Index Fund | 6.35M | $95.6M | 1.57% | 2.95% | 2025-11-30 |
| 4 | VANGUARD INDEX FUNDS-Vanguard Small-Cap Index Fund | 4.26M | $64.1M | 1.05% | 100.00% | 2025-12-31 |
| 5 | JANUS INVESTMENT FUND-Janus Henderson Contrarian Fund | 3.62M | $54.5M | 0.89% | 100.00% | 2025-12-31 |
| 6 | Fidelity Salem Street Trust-Fidelity Small Cap Index Fund | 3.18M | $47.9M | 0.79% | 18.92% | 2025-12-31 |
| 7 | VANGUARD INDEX FUNDS-Vanguard Extended Market Index Fund | 3.15M | $47.5M | 0.78% | 1.22% | 2025-12-31 |
| 8 | Valkyrie ETF Trust II-Valkyrie Bitcoin Miners ETF | 3.04M | $45.8M | 0.75% | -1.33% | 2025-12-31 |
| 9 | iShares Trust-iShares Russell 2000 Value ETF | 2.85M | $42.9M | 0.70% | 26.23% | 2025-12-31 |
| 10 | Amplify ETF Trust-Amplify Blockchain Technology ETF | 2.60M | $39.2M | 0.64% | -55.39% | 2025-12-31 |

### Recent Insider Transactions
| Date | Insider | Title | Type | Shares | Value | Signal |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-03-04 | NEWSOME JAMES E | Director | SELL | 45K | $711K | — |
| 2026-02-25 | DUDA THOMAS DAVID | Director | OTHER | 4K | $0 | — |
| 2026-02-17 | KELLY PATRICK ARTHUR | President | SELL | 36K | $552K | — |
| 2026-01-15 | KELLY PATRICK ARTHUR | President | SELL | 36K | $632K | — |
| 2025-12-19 | IWASCHUK WILLIAM | President | OTHER | 26K | $0 | — |
| 2025-12-19 | NEWSOME JAMES E | Director | SELL | 22K | $350K | — |
| 2025-12-19 | WILLIAMS WESLEY HASTIE | Director | SELL | 50K | $802K | — |
| 2025-12-19 | PAGE TYLER | Chief Executive Of.. | OTHER | 1.02M | N/A | — |
| 2025-12-19 | IWASCHUK WILLIAM | President | OTHER | 306K | N/A | — |
| 2025-12-19 | KELLY PATRICK ARTHUR | President | OTHER | 306K | N/A | — |
| 2025-12-15 | KELLY PATRICK ARTHUR | President | SELL | 36K | $536K | — |
| 2025-12-15 | PAGE TYLER | Chief Executive Of.. | OTHER | 1.68M | N/A | — |
| 2025-12-15 | IWASCHUK WILLIAM | President | OTHER | 504K | N/A | — |
| 2025-12-15 | KELLY PATRICK ARTHUR | President | OTHER | 504K | N/A | — |
| 2025-11-26 | GROSSMAN CARY M | Director | SELL | 25K | $475K | — |
| 2025-11-26 | EVANS HOLLY MORROW | Director | SELL | 15K | $281K | — |
| 2025-11-17 | KELLY PATRICK ARTHUR | President | SELL | 27K | $377K | — |
| 2025-11-12 | EVANS HOLLY MORROW | Director | SELL | 16K | $283K | — |
| 2025-11-12 | WILLIAMS WESLEY HASTIE | Director | SELL | 19K | $329K | — |
| 2025-11-10 | PAGE TYLER | Chief Executive Of.. | OTHER | 238K | $0 | — |

### Flow Summary (Last 90 Days)
| Metric | Value |
| :--- | :--- |
| Net Insider Activity | 0 buys, 5 sells |
| Net Shares | -188K |
| Cluster Buy Signal | No |
| Largest Inst. Change | V3 Holding Ltd                          : -6.89% |

### Smart Money Signal
| Metric | Value |
| :--- | :--- |
| Signal | **STRONG ACCUMULATION** |
| Holders Increasing | 9/10 |
| Holders Decreasing | 1/10 |
| Avg Position Change | +83.4% |

### Aggressive Accumulators (>20% increase)
| Holder | % Change | Shares | Value |
| :--- | :--- | :--- | :--- |
| Shaw D.E. & Co., Inc. | +287.6% | 15.39M | $231.7M |
| Morgan Stanley | +280.9% | 5.64M | $85.0M |
| Situational Awareness LP                           | +100.0% | 10.47M | $157.7M |
| Jane Street Group, LLC | +48.7% | 16.42M | $247.3M |
| Value Aligned Research Advisors, LLC                           | +45.9% | 7.45M | $112.2M |
| Vanguard Group Inc | +43.2% | 32.68M | $492.2M |

### 8. Volume Profile
## Volume Profile & Order Flow Audit

### Key Levels
| Metric | Value |
| :--- | :--- |
| Current Price | $15.06 |
| VWAP (Period) | $16.76 |
| POC (High Vol Node) | $14.78 |
| Distance to POC | -1.8% |

### Volume Distribution (Top Nodes)
| Price Range | Volume | Buy % | Sell % | Note |
| :--- | :--- | :--- | :--- | :--- |
| 20.30-20.88 | 180.5M | 59% | 41% |  |
| 19.71-20.30 | 194.1M | 48% | 52% |  |
| 19.13-19.71 | 188.9M | 39% | 61% |  |
| 18.55-19.13 | 204.9M | 58% | 42% |  |
| 17.97-18.55 | 187.6M | 55% | 45% |  |
| 17.39-17.97 | 253.2M | 40% | 60% |  |
| 16.81-17.39 | 282.1M | 43% | 57% | HVN |
| 16.23-16.81 | 234.4M | 62% | 38% |  |
| 15.65-16.23 | 275.4M | 62% | 38% | HVN |
| 15.07-15.65 | 321.7M | 43% | 57% | HVN |
| 14.49-15.07 | 368.1M | 54% | 46% | **POC** |
| 13.91-14.49 | 261.8M | 49% | 51% | HVN |
| 13.33-13.91 | 149.4M | 48% | 52% |  |
| 12.75-13.33 | 120.4M | 35% | 65% |  |
| 12.17-12.75 | 164.4M | 50% | 50% |  |

## Tool Failures
All tools completed successfully

## Capital Configuration

| Parameter | Value |
| :--- | :--- |
| per_stock_total | 600 |
| active_pool | 300 |
| reserve_pool | 300 |
| active_bullets_max | 5 |
| reserve_bullets_max | 3 |
| sizing_method | pool-distributed (equal impact) |
