# Exit Review Pre-Analyst — 2026-03-18
*Generated: 2026-03-18 09:23 | Tool: exit_review_pre_analyst.py*

**Positions reviewed:** 10 | EXIT: 0, REDUCE: 0, HOLD: 2, MONITOR: 8

## Exit Review Matrix

| Ticker | Days Held | Time Stop | P/L % | P/L $ | Target Dist | Earnings | Momentum | Squeeze | Verdict | Rule |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| IONQ | >60 days (pre-strategy) | EXCEEDED | -25.0% | -$166.80 | N/A | UNKNOWN | Neutral (+0) | N/A | **HOLD** | 10 |
| USAR | >60 days (pre-strategy) | EXCEEDED | -8.8% | -$28.35 | +17.1% | UNKNOWN | Neutral (+0) | N/A | **HOLD** | 10 |
| ACHR | 16 | WITHIN | -3.7% | -$22.08 | N/A | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |
| APLD | 29 | WITHIN | -5.3% | -$23.25 | +38.1% | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |
| CIFR | 1 | WITHIN | +1.8% | +$1.89 | N/A | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |
| CLF | 15 | WITHIN | -9.6% | -$50.73 | N/A | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |
| NNE | 13 | WITHIN | -6.5% | -$21.00 | N/A | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |
| NU | 33 | WITHIN | -10.1% | -$48.00 | +17.5% | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |
| TEM | 9 | WITHIN | -0.3% | -$0.14 | N/A | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |
| TMC | 5 | WITHIN | +1.0% | +$0.54 | N/A | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |

## Per-Position Detail

### IONQ — HOLD (Rule 10)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | EXCEEDED | >60 days (pre-strategy) days held (entered pre-2026) |
| Profit Target | BELOW | P/L -25.0%, No target (recovery) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=True, pre_strategy=True, reclassified=False
**Bullets:** 1/5 → still_building
**Verdict Trace:** Rule 10 — Recovery — default hold, time stop informational only
**Knowledge:** 1 observation, 1 trade. Top: Price $33.34 (-24.9% from avg $44.39). Earnings Feb 25. Multiple headwinds conve... (0.50)

*LLM: Write 2-3 sentence Reasoning connecting data to verdict.*
*LLM: Write specific Recommended Action (broker instructions).*

### USAR — HOLD (Rule 10)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | EXCEEDED | >60 days (pre-strategy) days held (entered pre-2026-02-12) |
| Profit Target | BELOW | P/L -8.8%, target $23.05 (+17.1% to target) (+17.1% from target) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=True, pre_strategy=True, reclassified=False
**Bullets:** 3/5 (pre-strategy), pool exhausted → fully_loaded
**Verdict Trace:** Rule 10 — Recovery — default hold, time stop informational only

*LLM: Write 2-3 sentence Reasoning connecting data to verdict.*
*LLM: Write specific Recommended Action (broker instructions).*

### ACHR — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 16 days held (entered 2026-03-02) |
| Profit Target | BELOW | P/L -3.7%, No target (recovery) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 5/5 → fully_loaded
**Verdict Trace:** Rule 16 — Within time window — standard tracking
**Knowledge:** 3 trades. Top: ACHR: BUY 15 shares @ $6.09 (reserve). Now 92 shares @ $6.53 avg. (0.75)

*LLM: Write 2-3 sentence Reasoning connecting data to verdict.*
*LLM: Write specific Recommended Action (broker instructions).*
*LLM: Opportunity cost: 4 cycles could have completed in 16d (expected 4d/cycle). Consider REDUCE.*

### APLD — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 29 days held (entered 2026-02-17) |
| Profit Target | BELOW | P/L -5.3%, target $38.00 (+38.1% to target) (+38.1% from target) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 5/5 → fully_loaded
**Verdict Trace:** Rule 16 — Within time window — standard tracking
**Knowledge:** 1 observation, 2 trades. Top: NVIDIA SOLD ENTIRE $177M STAKE.** Filed after market close Feb 17. Stock hit $30... (0.50)

*LLM: Write 2-3 sentence Reasoning connecting data to verdict.*
*LLM: Write specific Recommended Action (broker instructions).*
*LLM: Opportunity cost: 7 cycles could have completed in 29d (expected 4d/cycle). Consider REDUCE.*

### CIFR — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 1 days held (entered 2026-03-17) |
| Profit Target | BELOW | P/L +1.8%, No target (recovery) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 1/5 → still_building
**Verdict Trace:** Rule 16 — Within time window — standard tracking
**Knowledge:** 3 trades. Top: CIFR: BUY 7 shares @ $14.82 (active). Now 7 shares @ $14.82 avg. (0.74)

*LLM: Write 2-3 sentence Reasoning connecting data to verdict.*
*LLM: Write specific Recommended Action (broker instructions).*

### CLF — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 15 days held (entered 2026-03-03) |
| Profit Target | BELOW | P/L -9.6%, No target (recovery) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 6/5 → fully_loaded
**Verdict Trace:** Rule 16 — Within time window — standard tracking
**Knowledge:** 2 trades, 1 observation. Top: CLF: BUY 10 shares @ $8.55 (active). Now 57 shares @ $9.24 avg. (0.75)

*LLM: Write 2-3 sentence Reasoning connecting data to verdict.*
*LLM: Write specific Recommended Action (broker instructions).*
*LLM: Opportunity cost: 3 cycles could have completed in 15d (expected 4d/cycle). Consider REDUCE.*

### NNE — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 13 days held (entered 2026-03-05) |
| Profit Target | BELOW | P/L -6.5%, No target (recovery) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 6/5 → fully_loaded
**Verdict Trace:** Rule 16 — Within time window — standard tracking
**Knowledge:** 3 trades. Top: NNE: BUY 4 shares @ $21.45 (active). Now 14 shares @ $23.18 avg. (0.75)

*LLM: Write 2-3 sentence Reasoning connecting data to verdict.*
*LLM: Write specific Recommended Action (broker instructions).*
*LLM: Opportunity cost: 3 cycles could have completed in 13d (expected 4d/cycle). Consider REDUCE.*

### NU — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 33 days held (entered 2026-02-13) |
| Profit Target | BELOW | P/L -10.1%, target $16.75 (+17.5% to target) (+17.5% from target) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 6/5 → fully_loaded
**Verdict Trace:** Rule 16 — Within time window — standard tracking
**Knowledge:** 2 trades, 1 observation. Top: BUY 4 shares @ $14.70 + 2 shares @ $14.60 (R1 filled, 6 shares total; limit was ... (0.56)

*LLM: Write 2-3 sentence Reasoning connecting data to verdict.*
*LLM: Write specific Recommended Action (broker instructions).*
*LLM: Opportunity cost: 8 cycles could have completed in 33d (expected 4d/cycle). Consider REDUCE.*

### TEM — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 9 days held (entered 2026-03-09) |
| Profit Target | BELOW | P/L -0.3%, No target (recovery) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 1/5 → still_building
**Verdict Trace:** Rule 16 — Within time window — standard tracking
**Knowledge:** 3 trades. Top: TEM: BUY 1 shares @ $50.98 (active). Now 1 shares @ $50.98 avg. (0.68)

*LLM: Write 2-3 sentence Reasoning connecting data to verdict.*
*LLM: Write specific Recommended Action (broker instructions).*

### TMC — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 5 days held (entered 2026-03-13) |
| Profit Target | BELOW | P/L +1.0%, No target (recovery) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 1/5 → still_building
**Verdict Trace:** Rule 16 — Within time window — standard tracking
**Knowledge:** 3 trades. Top: TMC: SELL 26 shares @ $6.26 (full exit). Profit: +6.9% from $5.86 avg. Position ... (1.06)

*LLM: Write 2-3 sentence Reasoning connecting data to verdict.*
*LLM: Write specific Recommended Action (broker instructions).*

## Cross-Check Results

| Check | Result | Detail |
| :--- | :--- | :--- |
| All 8 invariant checks | PASS | No violations found |

## Capital Rotation Skeleton

No capital rotation needed at this time.

---

*LLM: Write Executive Summary (2-3 sentences: positions reviewed, verdict counts, key actions).*
*LLM: Write Prioritized Recommendations (ranked list: most urgent first).*

