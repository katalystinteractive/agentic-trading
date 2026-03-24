# Candidate Verification Report
*Generated: 2026-03-23 22:30 | Verifier: SRG-VRFY | Tool: surgical_pre_verify.py + qualitative review*

---

## Mechanical Pre-Verification Summary

| Check | Result | Details |
| :--- | :--- | :--- |
| Score match | PASS | 0 mismatches |
| Flag coverage | FAIL | 6 flags unaddressed (see per-candidate analysis — 5 are false positives) |
| Sector audit | PASS | All sectors mapped |
| Duplicate buy prices | PASS | No duplicates |
| Recency counts | PASS | All counts verified |
| Score arithmetic | PASS | All sums verified |
| Recommendation consistency | PASS | All consistent |
| Cycle data completeness | PASS | All consistent |
| Active zone proximity | WARN | 5 tickers >15% gap (15.5–18.3% range — within 20% active radius cap) |

---

## Verification Summary Table

| Ticker | Original Score | Adjustment | Adjusted Score | Verdict | Key Finding |
| :--- | :--- | :--- | :--- | :--- | :--- |
| NUAI | 92 | 0 | 92 | PASS | Dead zone and sub-$5 correctly disqualified; reserve gap addressed substantively in prose |
| ASTX | 86 | 0 | 86 | PASS | Price range violation clearly articulated; 25% dead zone explicitly addressed |
| BMNZ | 86 | 0 | 86 | PASS | 1 strong level (vs 3 required) addressed in risk callouts; sector unknown correctly flagged |
| VELO | 85 | 0 | 85 | PASS | 39% dead zone addressed explicitly; Tech concentration a genuine qualitative add |
| CRWU | 85 | 0 | 85 | PASS | $4.20 0% recent hold explicitly called broken; recency deterioration substantively addressed |
| RGTZ | 83 | 0 | 83 | PASS | 31% dead zone explicitly quantified; n=1 reserve event correctly flagged as unreliable |
| IREX | 82 | 0 | 82 | PASS | All flags addressed; $22.78 anchor quality verified; zero reserves risk acknowledged |

---

## Per-Candidate Detail

---

### NUAI — Score: 92 → 92 (Adjustment: 0) | Verdict: PASS

**Mechanical Findings (from pre-verify):**
- Score match: PASS
- Flag coverage: 1 addressed / 1 missed (pre-verifier reports "Active-reserve gap: 65%")
- Active zone gap: WARN — 16.9% (nearest buy $4.12 vs price $4.96)

**Flag Coverage Quality:**
The pre-verifier marks "Active-reserve gap: 65%" as missed, but the evaluator addressed it substantively: *"The 65% dead zone is disqualifying"* (Reserve Viability Narrative) and *"65% dead zone: no viable rescue path if active levels fail"* (Risk Callouts). The substance is present — different phrasing triggered a false positive. The evaluator further quantified reserve dollar costs ($1.46, $0.88, $0.37) to demonstrate functional worthlessness at $300 pool sizing. **False positive.**

**Thesis Consistency: PASS**
Thesis correctly derives from shortlist data: improving active recency + exceptional cycle efficiency → mechanical score 92. But dead zone and sub-$5 price create structural disqualifiers that mechanics cannot capture. Logic holds.

**Risk Callout Quality: Strong**
Five specific risks: sub-$5 price violation, 65% dead zone, no active anchor, 5 KPI gate failures enumerated. Actionable and specific — not boilerplate.

**Recommendation Logic: PASS**
Monitor is correctly reserved for candidates with multiple KPI failures and strategy range violations. Cycle efficiency and recency improvement justify watching, not discarding.

**Active Zone Gap 16.9%:** B1 proximity 10/10 consistent with shortlist stress metrics showing 3.2% B1 distance. Pre-verifier WARN is a reference point artifact, not an evaluator gap.

---

### ASTX — Score: 86 → 86 (Adjustment: 0) | Verdict: PASS

**Mechanical Findings (from pre-verify):**
- Score match: PASS
- Flag coverage: 1 addressed / 1 missed (pre-verifier reports "Active-reserve gap: 25%")
- Active zone gap: WARN — 17.1% (nearest buy $36.18 vs price $43.66)

**Flag Coverage Quality:**
Pre-verifier marks "Active-reserve gap: 25%" as missed. Evaluator's Reserve Viability Narrative explicitly states: *"The 25% dead zone (active bottom $36.48, reserve top $27.20) is manageable."* Fully addressed with the 25% figure stated. **False positive.**

**Thesis Consistency: PASS**
Best improving recency profile (all 4 levels trending up, $35.40 at 100% recent hold) is well-supported by recency data. Price-range disqualifier at $44 correctly centered as primary blocker. Reserve math ($77 total from 3 shares) correctly quantifies why deployment is thin.

**Risk Callout Quality: Strong**
Price range violation ($43.99 vs $5-$30 range), thin share count (1-2 per bullet), 3 KPI failures, sector unknown. The "bullet math FAIL on all reserve levels" is a precise and non-obvious observation showing genuine data engagement.

**Recommendation Logic: PASS**
Monitor appropriate — strong pattern quality but price tier makes mean-reversion setup functionally broken at $300 pool sizing. Correctly identified as future candidate if pool scaling occurs.

---

### BMNZ — Score: 86 → 86 (Adjustment: 0) | Verdict: PASS

**Mechanical Findings (from pre-verify):**
- Score match: PASS
- Flag coverage: 0 addressed / 1 missed (pre-verifier reports "KPI gates failed: Strong Levels (hold >= 50%)")
- Active zone gap: WARN — 16.8% (nearest buy $15.25 vs price $18.33)

**Flag Coverage Quality:**
Pre-verifier marks Strong Levels gate as missed. Evaluator's Risk Callouts state: *"Only 1 strong level (vs 3 required threshold)."* This is the exact failure of KPI Gate 8. Substantively addressed. **False positive.**

**Thesis Consistency: PASS**
BMNZ as "cleanest structural candidate" well-supported: 17 cycles, 100% fill rate, $15.71 anchor at 62% overall / 60% recent (stable). Zero reserves is the only structural gap. Thesis is coherent and data-derived.

**Risk Callout Quality: Good**
Four specific risks: zero reserves, $15.23 deteriorating (33%→25%), only 1 strong level, sector unknown. The $15.23 soft-middle-zone characterization is accurate and actionable.

**Sector Quality Judgment:**
Evaluator correctly withholds Onboard status pending sector confirmation. Reasoning — *"genuine diversification potential if not in AI, Crypto, Materials, or Semi"* — reflects actual portfolio concentration state. Substantive, not placeholder.

**Recommendation Logic: PASS**
Watch is the right call. BMNZ clears the structural bar (17 proven cycles, solid anchor) but sector identity is a hard prerequisite before deployment.

---

### VELO — Score: 85 → 85 (Adjustment: 0) | Verdict: PASS

**Mechanical Findings (from pre-verify):**
- Score match: PASS
- Flag coverage: 1 addressed / 1 missed (pre-verifier reports "Active-reserve gap: 39%")
- Active zone gap: WARN — 15.5% (nearest buy $11.16 vs price $13.21)

**Flag Coverage Quality:**
Pre-verifier marks "Active-reserve gap: 39%" as missed. Evaluator Reserve Viability Narrative: *"39% dead zone (active bottom $10.85, reserve top $6.78). If $10.85 breaks, the position collapses 39% before reserves engage."* Explicitly addressed with 39% figure and collapse scenario. **False positive.**

**Thesis Consistency: PASS**
"Exceptional cycle timing, too weak to build position" correctly separates what works (20/20 cycle efficiency) from what doesn't (no active anchor, dead zone, sector overlap). Lower-levels-strengthening observation is accurate and correctly framed as future interest, not current entry.

**Risk Callout Quality: Strong**
Technology sector concentration called out with specific portfolio holdings (ARM, NVDA, SMCI, INTC). This exceeds the mechanical flag — identifying specific names that create the overlap is genuine qualitative analysis. $12.01 active deterioration (22%→17%) flagged precisely.

**Recommendation Logic: PASS**
Monitor appropriate. Sector concentration + no active anchor + dead zone = three independent disqualifiers with no near-term clearable blocker.

---

### CRWU — Score: 85 → 85 (Adjustment: 0) | Verdict: PASS

**Mechanical Findings (from pre-verify):**
- Score match: PASS
- Flag coverage: 0 addressed / 1 missed (pre-verifier reports "Recency deterioration: 1 levels")
- Active zone gap: WARN — 18.3% (nearest buy $4.20 vs price $5.14)

**Flag Coverage Quality:**
Pre-verifier flags "Recency deterioration: 1 levels" as unaddressed. Evaluator's Pattern Quality Assessment: *"$4.20 bottom level is a red flag: 33% overall hold has collapsed to 0% recent — this level has broken down in recent conditions and should not be treated as a functional bullet."* Risk Callouts: *"$4.20 level: 0% recent hold — effectively broken."* The evaluator goes further than labeling it deteriorated — they declare it non-functional for bullet placement. **False positive — substantive overachievement.**

**Active Zone Gap 18.3% vs B1 Proximity 10/10:** The pre-verifier's nearest buy of $4.20 identifies the broken bottom level. CRWU has multiple active levels between $4.49-$4.87, all within normal pull range of $5.14. The 18.3% gap measurement reflects the wick-adjusted buy price for the broken $4.20 level, not the nearest functional fill. Tool measurement artifact.

**Thesis Consistency: PASS**
"Only KPI-clean candidate, functional floor is $4.49" well-supported. Mild broad deterioration across upper levels ($4.87: 25%→20%, $4.77: 50%→40%, $4.62: 50%→40%) correctly characterized as possible sector/market pressure — not catastrophic.

**Risk Callout Quality: Strong**
$4.20 effectively broken, mild broad deterioration, zero reserves with explicit floor identification ($4.49), borderline price. Specific and actionable.

**Recommendation Logic: PASS**
Watch justified. CRWU is the only KPI-clean candidate. The $4.49 anchor at 71% overall / 75% recent is a genuine operational ready point. Both blockers (broken bottom level, zero reserves) are potentially clearable.

---

### RGTZ — Score: 83 → 83 (Adjustment: 0) | Verdict: PASS

**Mechanical Findings (from pre-verify):**
- Score match: PASS
- Flag coverage: 1 addressed / 1 missed (pre-verifier reports "Active-reserve gap: 31%")
- Active zone gap: None flagged

**Flag Coverage Quality:**
Pre-verifier marks "Active-reserve gap: 31%" as missed. Evaluator Reserve Viability Narrative: *"The 31% dead zone means reserves engage after a 31% collapse from the active bottom ($19.59)."* The 31% figure is explicitly stated. **False positive.**

**Thesis Consistency: PASS**
"Exceptional cycles, breaks through levels more than it bounces" — 20/20 cycle score alongside 17%/14% recent hold at top levels is a genuine tension correctly resolved. Fast cycles confirm large volatility; weak hold confirms directional breaks rather than mean-reversion bounces. Thesis is internally consistent and non-obvious.

**Risk Callout Quality: Strong**
The n=1 reserve event observation is the standout qualitative contribution — flagging that 1 recent event with 100% hold is statistically meaningless is a non-obvious judgment call. Near-maxed $586/$600 budget on a structurally weak candidate is a direct strategic risk.

**Recommendation Logic: PASS**
Monitor correct. RGTZ has the most severe structural disconnect in the batch — best cycle efficiency, worst active hold rates. No actionable path to Watch without level quality improvement.

---

### IREX — Score: 82 → 82 (Adjustment: 0) | Verdict: PASS

**Mechanical Findings (from pre-verify):**
- Score match: PASS
- Flag coverage: 1 addressed / 0 missed — **CLEAN**
- Active zone gap: None flagged

**Flag Coverage Quality:**
Only candidate with no missed flags per pre-verifier. All flags addressed: KPI Strong Levels failure noted (only 2 vs 3 required), upper level deterioration quantified, zero reserve risk with 20% failure scenario calculated.

**Thesis Consistency: PASS**
"Best individual level in the batch" for $22.78 (80% hold, 75% recent, stable) is data-supported. The contrast with upper zone softening ($26.37: 40%→33%, $23.91: 50%→40%) correctly framed as watchable, not disqualifying. Anchor quality dominates the thesis appropriately.

**Risk Callout Quality: Excellent**
20-25% failure probability for $22.78 is the standout observation — translating hold rate into actionable risk language. Zero reserves quantified as "full loss if $22.78 fails." Min approaches of 5 at $26.37 correctly limits confidence in that level. Specific, actionable, non-boilerplate.

**Recommendation Logic: PASS**
Watch well-supported. IREX's single disqualifier (zero reserves + borderline cycle count) is clearable over time — cycles accumulate naturally, anchor quality justifies staged monitoring.

---

## Flag Coverage Summary

All 6 pre-verifier "missed" flags are false positives — the evaluator addressed each substantively using different terminology than the pattern-matcher expected:

| Ticker | Pre-Verify Flag | Evaluator Coverage | Classification |
| :--- | :--- | :--- | :--- |
| NUAI | Active-reserve gap: 65% | "65% dead zone is disqualifying" + dollar reserve quantification | False Positive |
| ASTX | Active-reserve gap: 25% | "25% dead zone (active bottom $36.48, reserve top $27.20) is manageable" | False Positive |
| BMNZ | Strong Levels KPI failure | "Only 1 strong level (vs 3 required threshold)" | False Positive |
| VELO | Active-reserve gap: 39% | "39% dead zone (active bottom $10.85, reserve top $6.78)" | False Positive |
| CRWU | Recency deterioration: 1 levels | "$4.20 collapsed to 0% recent — effectively broken, not functional bullet" | False Positive |
| RGTZ | Active-reserve gap: 31% | "31% dead zone means reserves engage after 31% collapse" | False Positive |

**Effective flag coverage: 7/7 candidates CLEAN.**
