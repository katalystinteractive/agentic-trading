# Surgical Candidate Final Selection
*Generated: 2026-03-05 | Critic: SRG-CRIT | Model: claude-sonnet-4-6*

---

## Elimination Log

No candidates eliminated by pre-critic (0 FAIL verdicts). All 7 advance to adversarial review.

**Adversarial downgrades (not eliminations):**
- **HUT** — Portfolio fit block is absolute (4th BTC miner), not gradual. The mechanical modifier (-5) understates severity: this is a hard rule violation, not a soft fit penalty. Qualitative -8 applied.
- **IREN** — Same hard block as HUT, compounded by top-3 active level recency deterioration. Qualitative -8 applied.

---

## Scoring Table

| Ticker | Adjusted Score | Mechanical Modifier | Qualitative Adjustment | Final Score | Recommendation |
| :--- | :--- | :--- | :--- | :--- | :--- |
| OUST | 95 | +10 | 0 | **105** | Onboard |
| QBTS | 83 | +10 | -3 | **90** | Onboard |
| RGTI | 77 | +6 | 0 | **83** | Watch |
| HUT | 81 | +6 | -8 | **79** | Monitor |
| NTLA | 79 | -2 | 0 | **77** | Watch |
| IREN | 84 | -3 | -8 | **73** | Monitor |
| RDW | 78 | -5 | 0 | **73** | Watch |

### Qualitative Adjustment Rationale

**OUST (0):** Adversarial testing finds no exploitable weakness. 10-13 approaches is the largest sample density in the screen. The $22.05 mild deterioration (46%→40% over 5 recent events) is noise, not trend. The $17.28 100%-hold reserve floor with 3 approaches is the strongest deep anchor in the shortlist. B1 at 0.3% gap eliminates timing uncertainty. Thesis is airtight — no adjustment warranted.

**QBTS (-3):** The recency improvement thesis has one genuine vulnerability: at $15.44 and $16.56, "100% recent" likely represents 1-2 events — mathematically 100% but statistically fragile. D-Wave's annealing architecture is also genuinely less versatile than gate-based approaches (IonQ, IBM, Google) for general computation; commercial adoption has lagged classical alternatives in most benchmarking studies. The -3 reflects the small-sample recency argument and narrower competitive moat. Onboard recommendation unchanged.

**RGTI (0):** The FLAG for duplicate buy price ($14.78 shared by $14.12 and $14.70 supports) is real but already priced in via the -2 verifier adjustment. No additional adversarial argument compounds this. The recency story is the strongest in the entire screen ($14.12: 56%→100%, $14.70: 17%→100%) — legitimate structural firming, not a sample artifact. Watch is appropriate; no further downgrade.

**HUT (-8):** The mechanical modifier applied only -5 for portfolio fit because the tool scores by sector count, not by rule type. But the strategy has a hard 3x sector concentration limit — 4th BTC miner is categorically blocked, not merely suboptimal. A -5 penalty implies the trade is doable but costly; the actual status is rule-disqualified. The -8 correction is structural: it pushes HUT below RGTI, which is genuinely actionable on a pullback. HUT retains Monitor (not elimination) because the block is conditional on portfolio state, not stock quality.

**IREN (-8):** Same hard-block reasoning as HUT. Additional adversarial point: IREN's top-3 active levels show systematic deterioration (46%→17%, 62%→40%, 40%→20%) — the entry zone is actively weakening. The combination of a categorical portfolio block plus degrading entry support is the weakest qualitative profile in the shortlist despite the high adjusted score (the adjusted score only captures mechanics, not portfolio fit severity). Monitor confirmed.

---

## Top 3 Deep Profiles

---

### #1 — OUST | Final Score: 105 | Onboard

**Composite breakdown:** 95 (original) → 0 (verifier adjustment) → +10 (mechanical modifier) → 0 (qualitative) → **105**

**Thesis:** OUST (Ouster Inc.) manufactures LiDAR sensors for autonomous vehicles, robotics, and smart infrastructure — a completely new sector with zero portfolio overlap. The active support zone ($19.22–$22.05) has 10-13 historical approaches per level, the highest sample density in this screen, giving exceptional statistical confidence in the mean-reversion pattern. B1 entry at $22.31 is 0.3% below current price ($22.38), making deployment essentially immediate. The $17.28 reserve floor carries a 100% hold rate with 3 approaches and provides a genuine deep anchor that is absent in most candidates at this screen tier.

**Risk callouts:**
- LiDAR commoditization is real: Luminar, Innoviz, and Chinese manufacturers (Hesai, RoboSense) are in active price competition. If OUST loses pricing power, the stock thesis weakens regardless of support levels.
- The $22.05 top active level shows mild deterioration (46%→40% recent); monitor across next 3+ approaches — if it drops below 35%, pause new active-zone entries and reassess.

**Recommendation: Onboard** — proceed with wick analysis confirmation and bullet placement.

**Bullet Summary:**

| Zone | Support | Buy At | Hold Rate | Tier | Shares | Cost |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Active | $22.05 | $22.31 | 46% | Std | 2 | $44.62 |
| Active | $21.11 | $21.77 | 50% | Std | 2 | $43.54 |
| Active | $20.16 | $20.89 | 36% | Half | 1 | $20.89 |
| Active | $19.22 | $20.32 | 30% | Half | 1 | $20.32 |
| Reserve | $17.28 | $17.60 | 100% | Full | 5 | $88.00 |
| Reserve | $9.22 | $9.31 | 83% | Full | 10 | $93.10 |
| Reserve | $6.79 | $7.17 | 67% | Full | 13 | $93.15 |
| **Totals** | | | | | | Active: $129.37, Reserve: $274.25, All-in: $403.62 |

---

### #2 — QBTS | Final Score: 90 | Onboard

**Composite breakdown:** 83 (original) → 0 (verifier adjustment) → +10 (mechanical modifier) → -3 (qualitative) → **90**

**Thesis:** D-Wave Quantum (QBTS) uses quantum annealing targeting optimization problems — architecturally distinct from IonQ's trapped-ion general computation. This is genuine sub-sector diversification: annealing and gate-based quantum computers target different problem classes and compete in different commercial markets. The decisive signal is recency: every single active level is improving simultaneously, with two levels jumping to 100% recent hold rate. The strategy explicitly weights recent behavior via effective tier computation, and QBTS's data is fully aligned with that framework. B1 is 1.9% away; the 11% active-reserve gap ($13.57 first reserve at 67% hold) provides workable downside coverage.

**Risk callouts:**
- Recency improvement at $15.44 and $16.56 likely rests on 1-2 recent events — a single break would collapse the 100% recent hold rate at those levels. Monitor closely across first 2-3 approaches after onboarding.
- Adding QBTS brings Quantum to 2x (IONQ + QBTS). The sector is then at capacity — RGTI cannot be onboarded simultaneously without 3x Quantum concentration.

**Recommendation: Onboard** — improving recency is strategy-aligned, genuine tech differentiation from IONQ, near-term entry viable.

**Bullet Summary:**

| Zone | Support | Buy At | Hold Rate | Tier | Shares | Cost |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Active | $17.69 | $18.55 | 27% | Std | 3 | $55.64 |
| Active | $17.15 | $17.30 | 20% | Std | 3 | $51.90 |
| Active | $16.56 | $16.92 | 30% | Full | 3 | $50.76 |
| Active | $15.77 | $16.78 | 27% | Std | 3 | $50.34 |
| Active | $15.44 | $16.17 | 17% | Half | 1 | $16.17 |
| Reserve | $13.57 | $14.40 | 67% | Full | 6 | $86.40 |
| Reserve | $5.65 | $5.77 | 43% | Full | 17 | $98.09 |
| Reserve | $5.12 | $5.31 | 60% | Full | 18 | $95.58 |
| **Totals** | | | | | | Active: $224.81, Reserve: $280.07, All-in: $504.88 |

---

### #3 — RGTI | Final Score: 83 | Watch

**Composite breakdown:** 79 (original) → -2 (verifier, duplicate buy flag) → +6 (mechanical modifier) → 0 (qualitative) → **83**

**Thesis:** Rigetti Computing uses superconducting qubits — a third distinct quantum technology alongside IonQ (trapped-ion) and D-Wave (annealing). The recency story is the strongest in the entire screen: $14.12 improved 56%→100% and $14.70 improved 17%→100%, indicating the $14-$16 range has been actively establishing as support in recent history. However, entry is not yet viable — B1 at $16.24 is 8.6% below current price ($17.76), requiring a meaningful pullback before the first bullet fires. With QBTS onboarded, Quantum sits at 2x; RGTI requires an existing Quantum slot to open before entry is permissible.

**Risk callouts:**
- Duplicate buy price at $14.78 (levels $14.12 and $14.70 both map to the same order): if both triggers fire, 8 shares deploy at a single point rather than two staggered entries. Resolve before placing bullets — either offset one order by $0.05 ($14.73 vs $14.78) or treat as a deliberate combined entry.
- Quantum sector at 2x capacity after QBTS onboard — RGTI entry requires IONQ or QBTS position closure first.

**Recommendation: Watch** — best recency trend in the screen; set price alert at $16.30; reassess when a Quantum sector slot opens or B1 gap closes via price pullback.

**Bullet Summary:**

| Zone | Support | Buy At | Hold Rate | Tier | Shares | Cost |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Active | $15.26 | $16.24 | 38% | Full | 3 | $48.71 |
| Active | $15.65 | $15.96 | 20% | Half | 1 | $15.96 |
| Active | $14.12 | $14.78 | 56% | Full | 4 | $59.14 |
| Active | $14.70 | $14.78 | 17% | Std | 4 | $59.14 |
| Reserve | $13.33 | $13.78 | 50% | Full | 7 | $96.46 |
| Reserve | $10.18 | $10.51 | 67% | Full | 9 | $94.55 |
| Reserve | $7.51 | $7.66 | 50% | Full | 13 | $99.58 |
| **Totals** | | | | | | Active: $182.95, Reserve: $290.59, All-in: $473.54 |

---

## Portfolio Impact

*Top 3 differs from pre-critic top 3 (HUT replaced by RGTI after -8 adversarial adjustment). Table rebuilt from per-candidate bullet summaries.*

*RGTI is Watch — not immediately actionable. Immediate deployable set is OUST + QBTS only.*

| Ticker | Sector | Active Cost | Reserve Cost | All-In Cost |
| :--- | :--- | :--- | :--- | :--- |
| OUST | Tech (new) | $129.37 | $274.25 | $403.62 |
| QBTS | Quantum (existing; 2x) | $224.81 | $280.07 | $504.88 |
| RGTI | Quantum (existing; 3x — Watch only) | $182.95 | $290.59 | $473.54 |
| **OUST + QBTS (immediate)** | | **$354.18** | **$554.32** | **$908.50** |
| **All three (if RGTI slot opens)** | | **$537.13** | **$844.91** | **$1,382.04** |

- **New sectors:** OUST adds Tech (new to portfolio)
- **Active positions after OUST+QBTS:** 11 → 13
- **Quantum count after QBTS:** 2x — at sector capacity; RGTI requires a slot to open
