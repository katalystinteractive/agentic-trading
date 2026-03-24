# Candidate Final — Surgical Critic Report
*Generated: 2026-03-23 | Critic: SRG-CRIT | Source: candidate-pre-critic.md + qualitative adversarial review*

---

## Elimination Log

*(copied from pre-critic — no mechanical eliminations)*
No candidates eliminated at mechanical pre-critic stage.

**Adversarial eliminations (qualitative):**

None eliminated outright. Two candidates (NUAI, ASTX) carry hard strategy violations (sub-$5 and $44 respectively) that prevent Watch status — demoted to Monitor in final recommendations. Remaining candidates survive adversarial testing to Watch or Monitor with specific blockers documented.

---

## Scoring Table

| Ticker | Adjusted Score | Mechanical Modifier | Pre-Critic Score | Qualitative Adjustment | Final Score | Recommendation |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| BMNZ | 86 | +9 | 95 | +5 | **100** | Watch |
| IREX | 82 | +10 | 92 | +5 | **97** | Watch |
| NUAI | 92 | +15 | 107 | -10 | **97** | Monitor |
| VELO | 85 | +15 | 100 | -8 | **92** | Monitor |
| ASTX | 86 | +15 | 101 | -10 | **91** | Monitor |
| RGTZ | 83 | +15 | 98 | -10 | **88** | Monitor |
| CRWU | 85 | +8 | 93 | -5 | **88** | Watch |

---

## Adversarial Stress-Test Notes

### NUAI — Pre-Critic #1 (107) → Final #3 (97) — Monitor
**Thesis challenge:** The pre-critic ranked NUAI #1 because of perfect cycle efficiency (+5), full portfolio fit (+5), and strong sample size (+5). These modifiers mechanically rewarded what is technically impressive but operationally unusable. Sub-$5 price ($4.96) is a hard strategy range violation — not a borderline miss but a micro-cap price tier with wider spreads, lower liquidity, and different market dynamics than the $5-$30 range the strategy was calibrated for. This is not a timing issue.

**Why the mechanical score overreached:** The pre-critic sees 11 cycles / 100% fill rate → +5 cycle modifier, and B1 at 3.2% proximity → +3 entry timing. Both are genuinely correct mechanical signals. But they apply to a stock that violates the strategy's foundational price range. The 65% dead zone makes reserves ($1.46, $0.88, $0.37) functionally $0 — the reserve score of 10/10 is a scoring artifact, not a deployment reality.

**Adversarial finding:** A stock with 5 KPI failures (Price Range, Active Levels, Anchor Level, Dead Zone, Strong Levels) should not be Watch-eligible. The cycle efficiency is impressive but irrelevant when entry price is below strategy minimum. Qualitative adjustment: **-10**.

---

### ASTX — Pre-Critic #2 (101) → Final #5 (91) — Monitor
**Thesis challenge:** ASTX has the best improving recency profile in the batch — every active level trending up, $35.40 at 100% recent hold. This is genuinely impressive. But "best recency profile among candidates the strategy cannot use" is not a reason to rank it highly.

**Price range violation is structural, not timing:** At $44, bullet sizes of 1-2 shares mean the mean-reversion strategy is functionally broken. The $300 pool yields only 6-7 shares across all active levels combined. Every mathematical advantage of the strategy (level averaging, reserve rescue, cycle compounding) requires more granular share access than $44 allows. This is the wrong vehicle for the pool architecture.

**Adversarial finding:** Sector unknown compounds the problem — if ASTX is in a concentrated sector (AI, Semi), the +5 portfolio fit modifier (assigned from "unknown = new") is wrong. At $44 with strategy range FAIL, this cannot advance beyond Monitor regardless of recency quality. Qualitative adjustment: **-10**.

---

### VELO — Pre-Critic #3 (100) → Final #4 (92) — Monitor
**Thesis challenge:** The pre-critic assigned +5 portfolio fit because Technology is coded as a "new sector." This is mechanically wrong in spirit. VELO is a Technology stock entering a portfolio that already holds ARM, NVDA, SMCI, and INTC — all high-beta tech plays at or near semiconductor concentration limits. The sector registry distinguishes "Technology" from "Semiconductor," but from a portfolio-risk perspective, adding another volatile tech name creates real correlation, not diversification.

**Sub-sector overlap the mechanical tool cannot detect:** The verifier explicitly named this as a genuine qualitative contribution. In a Tech drawdown, VELO moves with the existing positions. The +5 portfolio fit modifier was awarded mechanically but is qualitatively wrong.

**Structural compounding:** No active anchor (0 levels ≥50% hold), $12.01 actively deteriorating (22%→17%), 39% dead zone, AND real sector overlap. The 20/20 cycle efficiency is VELO's only genuine strength — applied to a structurally deficient setup. Qualitative adjustment: **-8**.

---

### RGTZ — Pre-Critic #4 (98) → Final #6 (88) — Monitor
**Thesis challenge:** RGTZ's 18 cycles / 100% fill earned +5 cycle modifier. But the cycle efficiency modifier rewards fast mean-reversion behavior — fill, recover, repeat. RGTZ's 17% and 14% recent hold at top active levels tells a contradictory story: this stock breaks through support rather than bouncing from it. Fast cycles + sub-20% hold rates = fast directional breaks, not mean-reversion bounces. The modifier is mechanically correct but perversely applied.

**Adversarial finding:** A fast cycler that breaks support fills bullets on the way down and keeps falling. $586/$600 budget nearly maxed on the weakest support structure in the batch. n=1 recent event at the reserve level is statistically worthless ($292 concentrated in a single entry with one recent data point). RGTZ's cycle data confirms large volatility — not reliable mean-reversion. Qualitative adjustment: **-10**.

---

### BMNZ — Pre-Critic #5 (95) → Final #1 (100) — Watch
**Thesis challenge:** Zero reserve levels — if all four active levels break, no recovery path exists. $15.23 deteriorating (33%→25%) is a soft middle zone. Sector unknown could reveal concentration.

**Why BMNZ survives adversarial testing:** The $15.71 anchor (62% overall, 60% recent, stable) is embedded in a four-level active structure with improving floor dynamics at $14.72 (40%→50%). 17 cycles / 100% fill is top-tier — only NUAI matches this, and NUAI has a hard price violation. At $18.24, BMNZ is firmly within strategy range. The zero-reserve gap is structural but the anchor's 4/5 bounce reliability provides intrinsic resilience. The sector confirmation blocker is specifically clearable with one lookup. After clearance, this is the most deployable candidate in the batch. Qualitative adjustment: **+5**.

---

### IREX — Pre-Critic #7 (92) → Final #2 (97) — Watch
**Thesis challenge:** Only 5 cycles — barely above the KPI minimum. Zero reserve levels mean the 20% anchor failure probability maps directly to full position loss. Upper levels deteriorating simultaneously ($26.37: 40%→33%, $23.91: 50%→40%).

**Why IREX survives adversarial testing:** The $22.78 anchor at 80% overall / 75% recent hold is the most reliable individual support level in this entire batch — by a significant margin. The evaluator's "20-25% failure probability" framing is honest risk quantification: 4 of 5 approaches bounce, consistently and stably in recent conditions. This is the kind of anchor quality the strategy is built to exploit. Upper zone softening is real and watchable, not disqualifying. Five cycles with 100% fill is a clean unbroken record — at $27.36 in-range price, Watch status correctly stages monitoring while cycles accumulate. Qualitative adjustment: **+5**.

---

### CRWU — Pre-Critic #6 (93) → Final #7 (88) — Watch
**Thesis challenge:** The -7 recency modifier is the strongest adversarial signal. The $4.20 level collapsed to 0% recent hold AND all three upper levels show simultaneous mild deterioration. When an entire zone degrades simultaneously, it suggests systemic pressure (sector-wide or company-specific), not one bad level. The $4.49 anchor holding at 75% recent is a lone bastion surrounded by deteriorating structure. If that anchor cracks, there is nothing below.

**Adversarial finding:** CRWU retains Watch — the $4.49 anchor is genuine and the only KPI-clean candidate matters. But the systematic deterioration pattern requires stabilization evidence before bullet placement. The pre-critic's score overweights KPI cleanliness at the expense of trend direction. Qualitative adjustment: **-5**. (Retains Watch, lower priority than BMNZ and IREX.)

---

## Top 3 Deep Profiles

---

### #1 BMNZ — Final Score: 100 — Watch

**Score Breakdown:** Original 86 → +0 verifier adjustment → +9 mechanical modifier → +5 qualitative → **100**

**Thesis:**
BMNZ is the structurally cleanest candidate in this batch: 17 proven cycles with 100% fill rate (top-tier cycle data, matched only by NUAI which fails on price range), a solid $15.71 anchor at 62% hold that has remained stable in recent conditions, and an improving floor at $14.72 (40%→50%). Within the $5-$30 strategy price range at $18.24, the four-level active zone provides natural position averaging. The only structural gap is zero reserve levels — but the anchor's reliability (4/5 bounces historically) provides intrinsic resilience within the active zone. Sector identity must be confirmed before any bullet placement to prevent hidden concentration.

**Risk Callouts:**
- Sector unknown: confirm before onboarding — any overlap with AI/Crypto/Semi/Materials disqualifies
- Zero reserve levels: no recovery path below $14.72; entire bet lives and dies in the active zone

**Bullet Summary (from candidate-pre-critic.md):**

| Zone | Support | Buy At | Hold Rate | Tier | Shares | Cost |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Active | $16.70 | $17.25 | 20% | Half | 3 | $51.75 |
| Active | $15.71 | $16.64 | 62% | Full | 6 | $99.84 |
| Active | $15.23 | $15.79 | 33% | Half | 3 | $47.36 |
| Active | $14.72 | $15.25 | 40% | Std | 6 | $91.47 |
| **Totals** | | | | | | Active: $290.42, Reserve: $0.00, All-in: $290.42 |

**Recommendation: Watch** — Confirm sector identity first. If sector is not concentrated, proceed to wick analysis and bullet placement.

---

### #2 IREX — Final Score: 97 — Watch

**Score Breakdown:** Original 82 → +0 verifier adjustment → +10 mechanical modifier → +5 qualitative → **97**

**Thesis:**
IREX's $22.78 anchor (80% overall hold, 75% recent, stable) is the highest-quality individual support level in this screening batch — 4 out of 5 historical approaches have bounced from this level, and reliability has held in recent conditions. The mean-reversion thesis is anchored in a demonstrably reliable bounce level at a price ($27.36) within strategy range. Upper levels ($26.37, $23.91) are softening but functional. Zero reserve levels create a full-loss scenario if the anchor breaks (~20% probability), and only 5 cycles places IREX at the KPI minimum. Watch status correctly stages monitoring: anchor quality justifies entry interest while cycles accumulate and upper zone behavior is observed.

**Risk Callouts:**
- Zero reserves: if $22.78 fails (~20% of the time), no safety net — full loss on the $298 deployment
- Only 5 cycles: at KPI minimum; needs further accumulation before highest-confidence sizing

**Bullet Summary (from candidate-pre-critic.md):**

| Zone | Support | Buy At | Hold Rate | Tier | Shares | Cost |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Active | $26.37 | $26.84 | 40% | Std | 4 | $107.34 |
| Active | $23.91 | $24.43 | 50% | Std | 4 | $97.70 |
| Active | $22.78 | $23.32 | 80% | Full | 4 | $93.30 |
| **Totals** | | | | | | Active: $298.34, Reserve: $0.00, All-in: $298.34 |

**Recommendation: Watch** — Monitor upper level behavior. Enter if $22.78 anchor remains stable through next 2-3 price cycles and cycle count grows beyond 5.

---

### #3 NUAI — Final Score: 97 — Monitor

**Score Breakdown:** Original 92 → +0 verifier adjustment → +15 mechanical modifier → -10 qualitative → **97**

**Thesis:**
NUAI achieved the highest adjusted score (92) in this batch due to perfect cycle efficiency (11 cycles, 100% fill) and full B1 proximity — both legitimate mechanical signals. Active recency is genuinely improving ($4.04: 40%→67%, $4.39: 17%→29%), confirming the mean-reversion pattern is strengthening. However, two hard strategy violations prevent Watch status: sub-$5 price ($4.96, below the strategy's $5.00 minimum) and a 65% dead zone that makes the reserve structure ($1.46/$0.88/$0.37 per bullet) functionally worthless at $300 pool sizing. Monitor is appropriate — if price sustains above $5.00, revisit for Watch upgrade.

**Risk Callouts:**
- Sub-$5 price: hard strategy range violation — micro-cap dynamics, wider spreads, lower liquidity; reserves are decorative
- 65% dead zone: 5 KPI failures including Price Range, Anchor Level, and Dead Zone; no viable rescue path

**Bullet Summary (from candidate-pre-critic.md):**

| Zone | Support | Buy At | Hold Rate | Tier | Shares | Cost |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Active | $4.63 | $4.80 | 33% | Half | 19 | $91.11 |
| Active | $4.39 | $4.53 | 17% | Half | 19 | $85.98 |
| Active | $4.04 | $4.12 | 40% | Std | 29 | $119.48 |
| Reserve | $1.43 | $1.46 | 40% | Full | 1 | $1.46 |
| Reserve | $0.85 | $0.88 | 50% | Full | 1 | $0.88 |
| Reserve | $0.37 | $0.37 | 67% | Full | 1 | $0.37 |
| **Totals** | | | | | | Active: $296.57, Reserve: $2.71, All-in: $299.28 |

**Recommendation: Monitor** — Hard price range violation prevents Watch or Onboard. Re-evaluate if NUAI closes and holds above $5.00 for 2+ consecutive weeks.

---

## Portfolio Impact (Top 3 Onboarded)

*Pre-critic top 3 was NUAI/ASTX/VELO. Critic re-ranked to BMNZ/IREX/NUAI — rebuilt from per-candidate bullet summaries and sector context lines.*

| Ticker | Sector | Active Cost | Reserve Cost | All-In Cost |
| :--- | :--- | :--- | :--- | :--- |
| BMNZ | Unknown — new (pending confirmation) | $290.42 | $0.00 | $290.42 |
| IREX | Unknown — new | $298.34 | $0.00 | $298.34 |
| NUAI | Technology — new | $296.57 | $2.71 | $299.28 |
| **Total** | | $885.33 | $2.71 | $888.04 |

- **New sectors:** BMNZ (Unknown — confirm before deploy), IREX (Unknown — new), NUAI (Technology — new)
- **Active positions:** 23 → 26
- **Contingency:** If BMNZ sector confirms as concentrated (AI/Crypto/Semi/Materials), substitute CRWU (Watch, Final Score 88) as #3 candidate.

---
*Critic: 7 candidates stress-tested. 2 promoted (+5): BMNZ, IREX. 4 demoted (-5 to -10): NUAI, ASTX, VELO, RGTZ. 1 demoted (-5): CRWU. Net re-ranking: BMNZ rises from #5 to #1; IREX rises from #7 to #2; NUAI drops from #1 to #3 (Monitor). Pre-critic mechanical inflation at top corrected for hard strategy violations and sub-sector overlap.*
