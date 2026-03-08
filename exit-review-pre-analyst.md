# Exit Review Pre-Analyst — 2026-02-27
*Generated: 2026-02-27 09:48 | Tool: exit_review_pre_analyst.py*

**Positions reviewed:** 8 | EXIT: 0, REDUCE: 1, HOLD: 3, MONITOR: 4

## Exit Review Matrix

| Ticker | Days Held | Time Stop | P/L % | P/L $ | Target Dist | Earnings | Momentum | Squeeze | Verdict | Rule |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| STIM | 12 | WITHIN | +32.6% | +$62.92 | +0.0% | UNKNOWN | Neutral (+0) | N/A | **REDUCE** | 6a |
| INTC | >60 days (pre-strategy) | EXCEEDED | -22.2% | -$52.00 | +40.8% | UNKNOWN | Neutral (+0) | N/A | **HOLD** | 10 |
| IONQ | >60 days (pre-strategy) | EXCEEDED | -8.0% | -$53.25 | N/A | UNKNOWN | Neutral (+0) | N/A | **HOLD** | 10 |
| USAR | >60 days (pre-strategy) | EXCEEDED | -6.7% | -$21.60 | +14.5% | UNKNOWN | Neutral (+0) | N/A | **HOLD** | 10 |
| APLD | 10 | WITHIN | -11.7% | -$29.44 | +37.1% | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |
| LUNR | 2 | WITHIN | -61.0% | -$93.60 | +182.2% | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |
| NU | 14 | WITHIN | -9.7% | -$28.80 | +24.3% | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |
| SMCI | 4 | WITHIN | -7.9% | -$7.38 | +19.4% | UNKNOWN | Neutral (+0) | N/A | **MONITOR** | 16 |

## Per-Position Detail

### STIM — REDUCE (Rule 6a)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 12 days held (entered 2026-02-15) |
| Profit Target | EXCEEDED | P/L +32.6%, target $1.79 (+0.0% to target) (+0.0% from target) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 3/5 → still_building
**Verdict Trace:** Rule 6a — P/L 32.6% exceeds target range — take profits

*LLM: Write 2-3 sentence Reasoning connecting data to verdict.*
*LLM: Write specific Recommended Action (broker instructions).*
*LLM: Suggest rotate-to candidates from watchlist.*

### INTC — HOLD (Rule 10)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | EXCEEDED | >60 days (pre-strategy) days held (entered pre-2026-02-12) |
| Profit Target | BELOW | P/L -22.2%, target $51.21 (+40.8% to target) (+40.8% from target) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=True, pre_strategy=True, reclassified=False
**Bullets:** 3/5 (pre-strategy), ~$67 remaining → still_building
**Verdict Trace:** Rule 10 — Recovery — default hold, time stop informational only

*LLM: Write 2-3 sentence Reasoning connecting data to verdict.*
*LLM: Write specific Recommended Action (broker instructions).*

### IONQ — HOLD (Rule 10)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | EXCEEDED | >60 days (pre-strategy) days held (entered pre-2026) |
| Profit Target | BELOW | P/L -8.0%, No target (recovery) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=True, pre_strategy=True, reclassified=False
**Bullets:** 1/5 → still_building
**Verdict Trace:** Rule 10 — Recovery — default hold, time stop informational only

*LLM: Write 2-3 sentence Reasoning connecting data to verdict.*
*LLM: Write specific Recommended Action (broker instructions).*

### USAR — HOLD (Rule 10)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | EXCEEDED | >60 days (pre-strategy) days held (entered pre-2026-02-12) |
| Profit Target | BELOW | P/L -6.7%, target $23.05 (+14.5% to target) (+14.5% from target) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=True, pre_strategy=True, reclassified=False
**Bullets:** 3/5 (pre-strategy), pool exhausted → fully_loaded
**Verdict Trace:** Rule 10 — Recovery — default hold, time stop informational only

*LLM: Write 2-3 sentence Reasoning connecting data to verdict.*
*LLM: Write specific Recommended Action (broker instructions).*

### APLD — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 10 days held (entered 2026-02-17) |
| Profit Target | BELOW | P/L -11.7%, target $38.00 (+37.1% to target) (+37.1% from target) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 4/5 → still_building
**Verdict Trace:** Rule 16 — Within time window — standard tracking

*LLM: Write 2-3 sentence Reasoning connecting data to verdict.*
*LLM: Write specific Recommended Action (broker instructions).*

### LUNR — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 2 days held (entered 2026-02-25) |
| Profit Target | BELOW | P/L -61.0%, target $18.74 (+182.2% to target) (+182.2% from target) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 3/5 → still_building
**Verdict Trace:** Rule 16 — Within time window — standard tracking

*LLM: Write 2-3 sentence Reasoning connecting data to verdict.*
*LLM: Write specific Recommended Action (broker instructions).*

### NU — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 14 days held (entered 2026-02-13) |
| Profit Target | BELOW | P/L -9.7%, target $18.50 (+24.3% to target) (+24.3% from target) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 3/5 → still_building
**Verdict Trace:** Rule 16 — Within time window — standard tracking

*LLM: Write 2-3 sentence Reasoning connecting data to verdict.*
*LLM: Write specific Recommended Action (broker instructions).*

### SMCI — MONITOR (Rule 16)

**Exit Criteria Summary:**

| Criterion | Status | Detail |
| :--- | :--- | :--- |
| Time Stop | WITHIN | 4 days held (entered 2026-02-23) |
| Profit Target | BELOW | P/L -7.9%, target $34.43 (+19.4% to target) (+19.4% from target) |
| Earnings Gate | UNKNOWN | Unknown/unavailable |
| Momentum | Neutral | RSI Unknown, MACD Unknown, overall +0 Neutral |

**Classification:** recovery=False, pre_strategy=False, reclassified=False
**Bullets:** 1/5 → still_building
**Verdict Trace:** Rule 16 — Within time window — standard tracking

*LLM: Write 2-3 sentence Reasoning connecting data to verdict.*
*LLM: Write specific Recommended Action (broker instructions).*

## Cross-Check Results

| Check | Result | Detail |
| :--- | :--- | :--- |
| All 8 invariant checks | PASS | No violations found |

## Capital Rotation Skeleton

| Ticker | Verdict | Shares | Current Price | Capital Freed |
| :--- | :--- | :--- | :--- | :--- |
| STIM | REDUCE | 143 | $1.79 | $255.97 |

**Total capital freed (if all executed):** $255.97

---

*LLM: Write Executive Summary (2-3 sentences: positions reviewed, verdict counts, key actions).*
*LLM: Write Prioritized Recommendations (ranked list: most urgent first).*

