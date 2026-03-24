# Watchlist Fitness Report — 2026-03-16

## Executive Summary

26 tickers analyzed across the full watchlist. The portfolio skews constructive: 15 tickers are ENGAGE or ADD, with the cycle-validated cohort (OUST, CLSK, SMCI, LUNR, TMC, AR) showing the strongest structural confidence. Order hygiene is the primary drag on several otherwise-fit names (ACHR, CLF, NNE), blocking engagement until orphaned orders are resolved. Two RECOVERY positions (IONQ, USAR) require exit-review workflow before any action.

---

## Per-Ticker Analysis

### ACHR — HOLD-WAIT (Score: 52/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (40.7%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (1 Active Half+) | 4 | 15 |
| Hold Rate (33.3%) | 3 | 10 |
| Order Hygiene (1 orphaned) | 15 | 25 |
| Cycle Efficiency (No cycle data) | 0 | 20 |
| **Total** | **52** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 38.1 |
| 50-SMA distance | -18.1% |
| 200-SMA distance | -33.4% |
| 3-month range pctile | 5th |
| Up days (last 20) | 10/20 |
| Cycle State | PULLBACK |

**Thesis Assessment**
ACHR's mean-reversion character is under pressure — only 1 Active Half+ level and a 33% hold rate indicate the support structure has degraded. The swing amplitude (40.7%) confirms volatility is present, but the stock's lack of reliable level infrastructure makes systematic reversion plays difficult. Thesis is weakened but not broken; needs level refresh.

**Cycle Efficiency**
No cycle timing data exists. HOLD-WAIT is sustained by order hygiene failure (1 orphaned order), not cycle data alone. Running `cycle_timing_analyzer.py` is a prerequisite for any future ENGAGE upgrade.

**Cycle Context**
PULLBACK at the 5th percentile with RSI 38 signals price compression — this looks like a buying zone, not capitulation. However, the low hold rate (33%) means support levels have been failing at a high rate, so "deep pullback" may not be a reversion opportunity but a structural breakdown — proceed with caution.

**Order Sanity**: 0 matched, 0 drifted, 1 orphaned, 0 paused

**Verdict**: HOLD-WAIT — Strategy fits, orders need adjustment: 1 orphaned order(s). Keep position, don't add bullets until orders fixed.

**Re-entry signals**: Pullback estimate: $4.48 (from 20d high $7.55)

---

### APLD — ADD (Score: 75/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (71.5%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (7 Active Half+) | 15 | 15 |
| Hold Rate (50.0%) | 5 | 10 |
| Order Hygiene (0 orphaned) | 25 | 25 |
| Cycle Efficiency (No cycle data) | 0 | 20 |
| **Total** | **75** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 45.0 |
| 50-SMA distance | -14.8% |
| 200-SMA distance | +19.0% |
| 3-month range pctile | 28th |
| Up days (last 20) | 10/20 |
| Cycle State | NEUTRAL |

**Thesis Assessment**
APLD's mean-reversion thesis is intact — 71.5% monthly swing with 100% consistency and 7 active levels represents a well-structured, high-volatility play. The 50% hold rate is modest but acceptable given the AI infrastructure tailwind making levels less sticky. The missing piece is cycle timing validation.

**Cycle Efficiency**
No cycle data. Grace period applies as an existing watchlist ticker — ADD verdict is preserved. Running `cycle_timing_analyzer.py` would unlock the full 20 cycle points and provide timing confidence; until then, engagement is at reduced signal quality.

**Cycle Context**
NEUTRAL state at 28th percentile, 15% below the 50-SMA. This is a mid-pullback setup — not at the bottom of the range but also not extended. Standard entry conditions; the stock is digesting a prior run while the fundamental AI data center thesis remains in play.

**Order Sanity**: 1 matched, 0 drifted, 0 orphaned, 0 paused

**Verdict**: ADD — Strategy fits, ready for engagement. WARNING: No cycle timing data — run cycle_timing_analyzer.py to validate.

---

### AR — RESTRUCTURE (Score: 75/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (18.0%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (0 Active Half+) | 0 | 15 |
| Hold Rate (0.0%) | 0 | 10 |
| Order Hygiene (0 orphaned) | 25 | 25 |
| Cycle Efficiency (21 cycles, 100% fill, median 1d) | 20 | 20 |
| **Total** | **75** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 69.7 |
| 50-SMA distance | +17.2% |
| 200-SMA distance | +18.3% |
| 3-month range pctile | 93th |
| Up days (last 20) | 12/20 |
| Cycle State | EXTENDED |

**Thesis Assessment**
AR's mean-reversion thesis is structurally sound — 21 validated cycles with 100% fill at median 1d proves this is a reliable, fast-cycling instrument. However, the current level map is broken: all Active-zone levels are Skip tier, leaving 0 usable entry points. The stock needs to pull back for the level structure to reset into tradeable territory.

**Cycle Efficiency**
Proven fast cycler: 21 cycles, 100% fill rate, median 1-day deep. This is the strongest cycle profile on the watchlist. When levels reset post-pullback, AR should be a priority engagement. The 20 cycle efficiency points underscore long-term conviction here.

**Cycle Context**
EXTENDED at the 93rd percentile with RSI 69.7 — this is momentum exhaustion, not a structural breakout. At +17% above the 50-SMA, AR is overbought by mean-reversion standards. This is not a buying zone; it's a waiting zone. The RESTRUCTURE verdict correctly holds back engagement until a pullback aligns price with usable levels.

**Order Sanity**: 3 matched, 0 drifted, 0 orphaned, 0 paused

**Verdict**: RESTRUCTURE — Strategy fits, orders need adjustment: all Active-zone levels are Skip tier

**Re-entry signals**: Pullback estimate: $34.26 (from 20d high $41.78)

---

### ARM — ADD (Score: 77/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (32.1%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (5 Active Half+) | 15 | 15 |
| Hold Rate (75.0%) | 7 | 10 |
| Order Hygiene (0 orphaned) | 25 | 25 |
| Cycle Efficiency (No cycle data) | 0 | 20 |
| **Total** | **77** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 51.6 |
| 50-SMA distance | +3.7% |
| 200-SMA distance | -11.9% |
| 3-month range pctile | 59th |
| Up days (last 20) | 13/20 |
| Cycle State | NEUTRAL |

**Thesis Assessment**
ARM's thesis is intact — 75% hold rate on 5 active levels is strong, and 32% monthly swing with perfect consistency defines a reliable reversion instrument. One drifted order warrants a price check, but overall the level structure is well-maintained. ARM is a semiconductor royalty model that tends to cycle cleanly with sector rotation.

**Cycle Efficiency**
No cycle data. Grace period applies. The 1 drifted order suggests prices have moved enough to require level validation before new bullets are placed. Running `cycle_timing_analyzer.py` is the next unlock for ARM engagement confidence.

**Cycle Context**
NEUTRAL at 59th percentile, just +3.7% above the 50-SMA — this is a mid-range equilibrium position, neither oversold nor extended. ARM is in a holding pattern; entry here is not at the optimal pullback zone but is acceptable given the strong level quality.

**Order Sanity**: 0 matched, 1 drifted, 0 orphaned, 0 paused

**Verdict**: ADD — Strategy fits, ready for engagement. WARNING: No cycle timing data — run cycle_timing_analyzer.py to validate.

---

### BBAI — ENGAGE (Score: 76/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (55.6%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (4 Active Half+) | 15 | 15 |
| Hold Rate (66.7%) | 6 | 10 |
| Order Hygiene (0 orphaned) | 25 | 25 |
| Cycle Efficiency (No cycle data) | 0 | 20 |
| **Total** | **76** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 42.1 |
| 50-SMA distance | -19.2% |
| 200-SMA distance | -32.3% |
| 3-month range pctile | 8th |
| Up days (last 20) | 9/20 |
| Cycle State | NEUTRAL |

**Thesis Assessment**
BBAI's mean-reversion thesis is intact — 55.6% swing with perfect consistency and 66.7% hold rate on 4 active levels is a well-functioning setup. The AI/defense software niche provides a narrative catalyst cycle (contract announcements, earnings beats) that drives reliable bounces. Level structure is healthy.

**Cycle Efficiency**
No cycle timing data. Grace period applies as existing watchlist ticker — ENGAGE verdict is preserved. The 8th percentile position and 9 bearish up-days out of 20 suggest price has been under sustained selling pressure, which is exactly when cycle timing data would add confidence to entry decisions.

**Cycle Context**
NEUTRAL label at the 8th percentile with RSI 42 and -19% from 50-SMA — this is a deep pullback entry zone, not a sideways drift. The "NEUTRAL" cycle state combined with 8th percentile range position means price is compressing at the low end without technical exhaustion signals, a favorable risk/reward setup for mean reversion.

**Order Sanity**: 2 matched, 1 drifted, 0 orphaned, 0 paused

**Verdict**: ENGAGE — Strategy fits, ready for engagement. WARNING: No cycle timing data — run cycle_timing_analyzer.py to validate.

---

### CIFR — ENGAGE (Score: 77/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (67.8%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (4 Active Half+) | 15 | 15 |
| Hold Rate (71.4%) | 7 | 10 |
| Order Hygiene (0 orphaned) | 25 | 25 |
| Cycle Efficiency (No cycle data) | 0 | 20 |
| **Total** | **77** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 49.4 |
| 50-SMA distance | -6.5% |
| 200-SMA distance | +20.8% |
| 3-month range pctile | 35th |
| Up days (last 20) | 10/20 |
| Cycle State | NEUTRAL |

**Thesis Assessment**
CIFR's mean-reversion thesis remains strong — 67.8% monthly swing with 71.4% hold rate on 4 active levels is a proven crypto miner setup. The 4 matched orders confirm the level map is current and actionable. Bitcoin correlation provides predictable volatility cycles, making CIFR one of the more structured plays on the watchlist.

**Cycle Efficiency**
No cycle timing data. Grace period applies. CIFR's Bitcoin correlation effectively provides an external cycle clock — BTC move → CIFR amplified move → reversion. Running `cycle_timing_analyzer.py` would formalize this but the thesis doesn't depend on it.

**Cycle Context**
NEUTRAL at 35th percentile with RSI 49.4 — balanced mid-range position with 4 fully matched orders. This is a healthy setup: price is neither extended nor oversold, and orders are correctly positioned. ENGAGE is well-supported here.

**Order Sanity**: 4 matched, 0 drifted, 0 orphaned, 0 paused

**Verdict**: ENGAGE — Strategy fits, ready for engagement. WARNING: No cycle timing data — run cycle_timing_analyzer.py to validate.

---

### CLF — HOLD-WAIT (Score: 45/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (32.2%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (2 Active Half+) | 8 | 15 |
| Hold Rate (75.0%) | 7 | 10 |
| Order Hygiene (3 orphaned) | 0 | 25 |
| Cycle Efficiency (No cycle data) | 0 | 20 |
| **Total** | **45** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 28.5 |
| 50-SMA distance | -29.1% |
| 200-SMA distance | -23.4% |
| 3-month range pctile | 3th |
| Up days (last 20) | 7/20 |
| Cycle State | OVERSOLD |

**Thesis Assessment**
CLF's thesis is under strain — 3 orphaned orders means the level map has significantly drifted from current price, and the stock is in active freefall (3rd percentile, RSI 28.5). The 75% hold rate and 32% swing confirm the underlying reversion character is valid, but the order structure needs complete rebuilding before any engagement. This is a steelmaker in a tariff/macro storm, so structural headwinds are real.

**Cycle Efficiency**
No cycle data, 3 orphaned orders scoring zero on hygiene. With no cycle validation and a destroyed order map, this is the highest-priority housekeeping item on the watchlist. Order map must be rebuilt first.

**Cycle Context**
OVERSOLD at the 3rd percentile with RSI 28.5 and only 7 up days out of 20 — this is capitulation-territory technical distress. This could be a genuine reversion opportunity once orders are fixed, but it could also be fundamental value destruction if steel demand outlook has deteriorated structurally. Do not engage until the order map is rebuilt and the macro context is reassessed.

**Order Sanity**: 1 matched, 0 drifted, 3 orphaned, 0 paused

**Verdict**: HOLD-WAIT — Strategy fits, orders need adjustment: 3 orphaned order(s). Keep position, don't add bullets until orders fixed.

**Re-entry signals**: First reliable Active Half+ level: $8.44 (support $8.25) | Pullback estimate: $7.76 (from 20d high $11.45)

---

### CLSK — ENGAGE (Score: 95/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (43.8%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (7 Active Half+) | 15 | 15 |
| Hold Rate (58.3%) | 5 | 10 |
| Order Hygiene (0 orphaned) | 25 | 25 |
| Cycle Efficiency (11 cycles, 100% fill, median 1d) | 20 | 20 |
| **Total** | **95** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 48.6 |
| 50-SMA distance | -8.7% |
| 200-SMA distance | -17.9% |
| 3-month range pctile | 24th |
| Up days (last 20) | 10/20 |
| Cycle State | NEUTRAL |

**Thesis Assessment**
CLSK is a top-tier name on the watchlist — 11 validated cycles at 100% fill with median 1-day deep is the definition of a proven fast cycler. 7 active Half+ levels with zero orphaned orders makes this a fully operational, systemized setup. Bitcoin miner exposure with clean level structure and validated cycle timing makes this a first-call ENGAGE.

**Cycle Efficiency**
Proven fast cycler: 11 cycles, 100% fill rate, median 1-day deep. Full 20 cycle points earned. Engagement risk is low and cycle timing is reliable. One drifted order should be reviewed but does not block engagement.

**Cycle Context**
NEUTRAL at 24th percentile with RSI 48.6 — this is a mild pullback from recent highs, well within the standard reversion setup. At -8.7% from the 50-SMA with balanced up/down days, CLSK is in the buy zone, not a danger zone.

**Order Sanity**: 3 matched, 1 drifted, 0 orphaned, 0 paused

**Verdict**: ENGAGE — Strategy fits, ready for engagement

---

### INTC — HOLD-WAIT (Score: 72/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (26.8%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (3 Active Half+) | 12 | 15 |
| Hold Rate (50.0%) | 5 | 10 |
| Order Hygiene (0 orphaned) | 25 | 25 |
| Cycle Efficiency (No cycle data) | 0 | 20 |
| **Total** | **72** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 50.0 |
| 50-SMA distance | -0.9% |
| 200-SMA distance | +35.8% |
| 3-month range pctile | 55th |
| Up days (last 20) | 11/20 |
| Cycle State | NEUTRAL |

**Thesis Assessment**
INTC's mean-reversion thesis is mechanically sound — 26.8% swing, 100% consistency, 3 active levels — but this is a structural transformation story (foundry pivot, market share recovery) that adds idiosyncratic risk beyond normal reversion. The +35.8% premium to the 200-SMA is elevated for a stock that has been a long-term underperformer, suggesting the recent run may have outpaced fundamentals.

**Cycle Efficiency**
No cycle timing data — HOLD-WAIT is triggered by `cycle_pts < 8`. Clean order hygiene with zero orders means the system is idle here. Running `cycle_timing_analyzer.py` is the necessary next step before any bullets can be placed.

**Cycle Context**
NEUTRAL at 55th percentile with RSI exactly 50 — a textbook equilibrium reading. The +35.8% premium to the 200-SMA is the standout data point: INTC has historically been a value trap, and this premium could compress if the foundry thesis disappoints. Caution is warranted before deploying capital into this name.

**Order Sanity**: 0 matched, 0 drifted, 0 orphaned, 0 paused

**Verdict**: HOLD-WAIT — Strategy fits, but no cycle timing validation (cycle_pts < 8). Run cycle_timing_analyzer.py first.

**Re-entry signals**: First reliable Active Half+ level: $44.45 (support $43.14) | Pullback estimate: $35.99 (from 20d high $49.17)

---

### IONQ — RECOVERY

**Thesis Assessment**
Pre-strategy position — fitness scoring does not apply. IONQ's quantum computing thesis is long-dated and speculative; mean-reversion mechanics may not apply cleanly. The exit-review workflow will determine whether to hold for recovery, reduce, or exit based on position cost basis and current pricing.

**Cycle Efficiency**
N/A — recovery position.

**Cycle Context**
N/A — exit-review workflow takes precedence.

**Order Sanity**: N/A

**Verdict**: RECOVERY — Pre-strategy position — use exit-review-workflow for assessment.

---

### LUNR — ADD (Score: 96/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (43.8%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (5 Active Half+) | 15 | 15 |
| Hold Rate (66.7%) | 6 | 10 |
| Order Hygiene (0 orphaned) | 25 | 25 |
| Cycle Efficiency (17 cycles, 100% fill, median 1d) | 20 | 20 |
| **Total** | **96** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 49.7 |
| 50-SMA distance | -3.9% |
| 200-SMA distance | +38.7% |
| 3-month range pctile | 57th |
| Up days (last 20) | 12/20 |
| Cycle State | NEUTRAL |

**Thesis Assessment**
LUNR is the highest-scoring ADD on the watchlist at 96/100. 17 validated cycles at 100% fill with median 1-day deep establishes this as one of the most reliably documented fast cyclers. Active position with 6 matched orders and zero hygiene issues — the level map is in excellent health. Space/lunar economy exposure provides strong narrative-driven volatility cycles.

**Cycle Efficiency**
Proven fast cycler: 17 cycles, 100% fill rate, median 1-day deep. Full 20 cycle points earned — second only to AR (21 cycles) in raw cycle count. With an active position and orders already matched, LUNR is the priority ADD candidate.

**Cycle Context**
NEUTRAL at 57th percentile with RSI 49.7 — mid-range equilibrium. At -3.9% from the 50-SMA, price is very close to the moving average, suggesting this is neither an ideal pullback entry nor a dangerous extension. The +38.7% premium to the 200-SMA reflects LUNR's run from lows; new bullets should target identified support levels rather than current price.

**Order Sanity**: 6 matched, 1 drifted, 0 orphaned, 0 paused

**Verdict**: ADD — Strategy fits, ready for engagement. Active position — ready to add bullets.

---

### NNE — HOLD-WAIT (Score: 59/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (57.3%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (3 Active Half+) | 12 | 15 |
| Hold Rate (75.0%) | 7 | 10 |
| Order Hygiene (1 orphaned) | 10 | 25 |
| Cycle Efficiency (No cycle data) | 0 | 20 |
| **Total** | **59** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 35.1 |
| 50-SMA distance | -23.4% |
| 200-SMA distance | -36.2% |
| 3-month range pctile | 7th |
| Up days (last 20) | 10/20 |
| Cycle State | PULLBACK |

**Thesis Assessment**
NNE's mean-reversion thesis is structurally solid — 75% hold rate and 57.3% swing with 3 active levels confirms the stock's cyclical character. The orphaned order plus all non-paused orders above current price indicates the stock has dropped below the entire order stack, suggesting a more severe pullback than anticipated. Nuclear energy small-cap thesis remains compelling but requires order rebuild before re-entry.

**Cycle Efficiency**
No cycle data. The orphaned order combined with all remaining orders being above price means this stock has pulled back sharply through the entire level map. HOLD-WAIT is correct — fix orders first, then assess cycle timing.

**Cycle Context**
PULLBACK at 7th percentile with RSI 35.1 and -23.4% from 50-SMA — a significant drawdown from recent peaks. Given NNE's nuclear energy theme, this type of sharp pullback often precedes strong recoveries, but the orphaned order situation indicates the pullback exceeded the level map design. This is a buying opportunity IF orders are restructured to current price levels.

**Portfolio Note**
NNE competes with OKLO for nuclear energy exposure — both are HOLD-WAIT/ADD respectively. Consider prioritizing OKLO (cleaner order hygiene) until NNE's order map is rebuilt.

**Order Sanity**: 0 matched, 0 drifted, 1 orphaned, 0 paused

**Verdict**: HOLD-WAIT — Strategy fits, orders need adjustment: 1 orphaned order(s); all non-paused orders above current price. Keep position, don't add bullets until orders fixed.

**Re-entry signals**: First reliable Active Half+ level: $20.50 (support $20.12) | Pullback estimate: $12.07 (from 20d high $28.27)

---

### NU — ADD (Score: 70/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (17.3%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (2 Active Half+) | 8 | 15 |
| Hold Rate (75.0%) | 7 | 10 |
| Order Hygiene (0 orphaned) | 25 | 25 |
| Cycle Efficiency (No cycle data) | 0 | 20 |
| **Total** | **70** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 34.8 |
| 50-SMA distance | -14.4% |
| 200-SMA distance | -5.7% |
| 3-month range pctile | 9th |
| Up days (last 20) | 14/20 |
| Cycle State | PULLBACK |

**Thesis Assessment**
NU's mean-reversion thesis is valid — 75% hold rate with perfect consistency confirms reliable level behavior, and the Latin American fintech growth story provides cyclical momentum. The 17.3% monthly swing is the lowest among ADD-verdicts, making it a lower-volatility, capital-efficient play. Only 2 active levels is the main constraint; more levels would improve scoring significantly.

**Cycle Efficiency**
No cycle timing data. Grace period applies. With 14 up-days out of 20 and a PULLBACK state, the stock shows resilience even in a down trend — buyers are active. Cycle data would help confirm whether current price is near a validated cycle bottom.

**Cycle Context**
PULLBACK at 9th percentile with RSI 34.8 — a clear oversold-approaching state despite being near the 200-SMA (-5.7%). The 14/20 up days is unusually high for a 9th-percentile stock, suggesting buyers are absorbing selling pressure. This looks more like a supported pullback than a deteriorating downtrend — ADD conditions are valid.

**Order Sanity**: 1 matched, 0 drifted, 0 orphaned, 0 paused

**Verdict**: ADD — Strategy fits, ready for engagement. WARNING: No cycle timing data — run cycle_timing_analyzer.py to validate.

---

### NVDA — REVIEW (Score: 64/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (19.3%) | 15 | 15 |
| Consistency (84.6%) | 10 | 15 |
| Level Quality (2 Active Half+) | 8 | 15 |
| Hold Rate (63.6%) | 6 | 10 |
| Order Hygiene (0 orphaned) | 25 | 25 |
| Cycle Efficiency (No cycle data) | 0 | 20 |
| **Total** | **64** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 48.8 |
| 50-SMA distance | -1.2% |
| 200-SMA distance | +3.2% |
| 3-month range pctile | 47th |
| Up days (last 20) | 14/20 |
| Cycle State | NEUTRAL |

**Thesis Assessment**
NVDA's mean-reversion thesis is under pressure — swing consistency has slipped to 84.6% (near the 80% floor) and only 2 active Half+ levels indicates the support map is thinning. NVDA is a large-cap AI infrastructure bellwether where macro forces (export restrictions, earnings beats, competitor announcements) can override technical levels. The stock is approaching the structural boundary for this mean-reversion strategy.

**Cycle Efficiency**
No cycle timing data. With 4 matched orders and zero hygiene issues, the operational state is clean, but the strategy-fit question is the priority here. NVDA's large-cap character means cycle timing data, if generated, would likely show longer cycle durations given slower price reversion dynamics.

**Cycle Context**
NEUTRAL at 47th percentile with RSI 48.8 and 14/20 up days — genuine equilibrium. Price is essentially at the 50-SMA (-1.2%) with a modest 200-SMA premium. No urgent entry or exit signal; the REVIEW verdict is a prompt to monitor the consistency trend, not an immediate action signal.

**Order Sanity**: 4 matched, 0 drifted, 0 orphaned, 0 paused

**Verdict**: REVIEW — Approaching strategy boundary (consistency 84.6% near 80% floor)

---

### OKLO — ADD (Score: 76/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (63.3%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (5 Active Half+) | 15 | 15 |
| Hold Rate (66.7%) | 6 | 10 |
| Order Hygiene (0 orphaned) | 25 | 25 |
| Cycle Efficiency (No cycle data) | 0 | 20 |
| **Total** | **76** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 40.9 |
| 50-SMA distance | -21.4% |
| 200-SMA distance | -30.5% |
| 3-month range pctile | 5th |
| Up days (last 20) | 11/20 |
| Cycle State | NEUTRAL |

**Thesis Assessment**
OKLO is the cleaner nuclear energy play relative to NNE — 5 active Half+ levels, 63.3% monthly swing, 100% consistency, and zero orphaned orders. The SMR (small modular reactor) development thesis provides explosive volatility cycles around regulatory milestones and partnership announcements, making it a natural mean-reversion candidate.

**Cycle Efficiency**
No cycle timing data. Grace period applies. The 5th percentile position with 3 matched orders suggests this is a well-mapped pullback setup. Running `cycle_timing_analyzer.py` would determine whether OKLO recycles quickly (ENGAGE-worthy) or slowly (ADD remains appropriate).

**Cycle Context**
NEUTRAL at 5th percentile with RSI 40.9 and -21.4% from 50-SMA — a deep pullback within a NEUTRAL regime. At 5th percentile this is near the extreme of the recent range, making it a high-reward entry zone. 3 matched orders confirms existing positioning is already capturing this zone.

**Portfolio Note**
OKLO and NNE share nuclear energy sector exposure. With NNE in HOLD-WAIT, OKLO is the preferred active engagement vehicle in this sector.

**Order Sanity**: 3 matched, 0 drifted, 0 orphaned, 0 paused

**Verdict**: ADD — Strategy fits, ready for engagement. WARNING: No cycle timing data — run cycle_timing_analyzer.py to validate.

---

### OUST — ENGAGE (Score: 100/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (56.3%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (5 Active Half+) | 15 | 15 |
| Hold Rate (100.0%) | 10 | 10 |
| Order Hygiene (0 orphaned) | 25 | 25 |
| Cycle Efficiency (12 cycles, 100% fill, median 1d) | 20 | 20 |
| **Total** | **100** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 50.4 |
| 50-SMA distance | -4.2% |
| 200-SMA distance | -14.7% |
| 3-month range pctile | 31th |
| Up days (last 20) | 9/20 |
| Cycle State | NEUTRAL |

**Thesis Assessment**
OUST achieves a perfect 100/100 — the only ticker on the watchlist to do so. 100% hold rate across 5 active levels means every support level has held reliably on approach, which is the defining characteristic of an ideal mean-reversion instrument. 12 validated cycles with 100% fill and median 1-day deep confirms execution reliability. LiDAR sensor technology exposure with consistent institutional activity drives the swing pattern.

**Cycle Efficiency**
Proven fast cycler: 12 cycles, 100% fill rate, median 1-day deep. Full 20 cycle points. This is the most systematically validated name on the watchlist after AR. The combination of perfect hold rate AND perfect cycle efficiency is rare.

**Cycle Context**
NEUTRAL at 31st percentile with RSI 50.4 — balanced entry conditions. At -4.2% from the 50-SMA with 9/20 up days, price is drifting slightly below equilibrium without oversold conditions. This is a moderate pullback within a well-defined cycle — a standard ENGAGE setup.

**Order Sanity**: 4 matched, 0 drifted, 0 orphaned, 0 paused

**Verdict**: ENGAGE — Strategy fits, ready for engagement

---

### RGTI — ENGAGE (Score: 91/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (54.9%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (6 Active Half+) | 15 | 15 |
| Hold Rate (60.0%) | 6 | 10 |
| Order Hygiene (0 orphaned) | 25 | 25 |
| Cycle Efficiency (6 cycles, 100% fill, median 1d) | 15 | 20 |
| **Total** | **91** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 41.5 |
| 50-SMA distance | -17.7% |
| 200-SMA distance | -27.4% |
| 3-month range pctile | 11th |
| Up days (last 20) | 12/20 |
| Cycle State | NEUTRAL |

**Thesis Assessment**
RGTI's mean-reversion thesis is intact — 6 validated cycles with 100% fill confirms reliable execution, and 6 active Half+ levels provides the broadest coverage on any ENGAGE-verdict ticker. Quantum computing exposure gives it strong narrative volatility. The hold rate at 60% is healthy, and zero hygiene issues makes this immediately actionable.

**Cycle Efficiency**
Early-stage validation: 6 cycles at 100% fill, median 1-day deep. Scores 15/20 — good but not yet in the proven tier (10+ cycles). If the next 4 cycles fill cleanly, RGTI joins the proven fast-cycler cohort. Confidence in cycle timing is building but not definitive.

**Cycle Context**
NEUTRAL at 11th percentile with RSI 41.5 and -17.7% from 50-SMA — a genuine buying zone with 12/20 up days showing resilience. Quantum computing plays tend to move in correlated waves; with IONQ in RECOVERY, RGTI is the functional quantum computing engagement vehicle.

**Portfolio Note**
RGTI is the active quantum computing exposure while IONQ is in RECOVERY mode. Capital deployment in RGTI serves the sector thesis without adding to a distressed position.

**Order Sanity**: 4 matched, 0 drifted, 0 orphaned, 0 paused

**Verdict**: ENGAGE — Strategy fits, ready for engagement

---

### RKT — HOLD-WAIT (Score: 74/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (29.7%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (5 Active Half+) | 15 | 15 |
| Hold Rate (44.4%) | 4 | 10 |
| Order Hygiene (0 orphaned) | 25 | 25 |
| Cycle Efficiency (No cycle data) | 0 | 20 |
| **Total** | **74** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 35.4 |
| 50-SMA distance | -22.7% |
| 200-SMA distance | -16.0% |
| 3-month range pctile | 7th |
| Up days (last 20) | 8/20 |
| Cycle State | PULLBACK |

**Thesis Assessment**
RKT's mean-reversion thesis is structurally sound — 5 active levels, 100% consistency — but the 44.4% hold rate is a yellow flag, indicating support is failing more often than it holds. The mortgage/fintech business is highly rate-sensitive, meaning Fed policy shifts can cause level breaks that undermine the reversion pattern. Cycle timing data is the necessary validation before re-engaging.

**Cycle Efficiency**
No cycle timing data — HOLD-WAIT triggered by `cycle_pts < 8`. The 5 active levels and zero orphaned orders means the level map is ready; cycle validation is the only missing piece. Once `cycle_timing_analyzer.py` is run and confirms fast-cycling behavior, this could upgrade to ENGAGE.

**Cycle Context**
PULLBACK at 7th percentile with RSI 35.4 and only 8/20 up days — sustained selling, not a brief pullback. With -22.7% from the 50-SMA and -16% from 200-SMA, both moving averages are now resistance. Waiting for cycle validation before adding bullets is the correct posture.

**Order Sanity**: 0 matched, 0 drifted, 0 orphaned, 0 paused

**Verdict**: HOLD-WAIT — Strategy fits, but no cycle timing validation (cycle_pts < 8). Run cycle_timing_analyzer.py first.

**Re-entry signals**: First reliable Active Half+ level: $14.08 (support $13.99) | Pullback estimate: $13.28 (from 20d high $18.89)

---

### RUN — ENGAGE (Score: 82/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (37.9%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (3 Active Half+) | 12 | 15 |
| Hold Rate (20.0%) | 2 | 10 |
| Order Hygiene (0 orphaned) | 25 | 25 |
| Cycle Efficiency (4 cycles, 100% fill, median 1d) | 13 | 20 |
| **Total** | **82** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 38.3 |
| 50-SMA distance | -27.0% |
| 200-SMA distance | -18.3% |
| 3-month range pctile | 18th |
| Up days (last 20) | 12/20 |
| Cycle State | PULLBACK |

**Thesis Assessment**
RUN's mean-reversion thesis shows a mixed picture — the 20% hold rate (1/5 levels holding) is the lowest on any ENGAGE ticker and is a meaningful concern. Only 4 validated cycles means the timing data is early-stage. The solar installer business is exposed to IRA subsidy risk and rate sensitivity, which may explain why levels break more often than expected. The 2 drifted orders need price review.

**Cycle Efficiency**
Early-stage validation: 4 cycles at 100% fill, median 1-day deep. Scores 13/20. The 100% fill and 1-day deep are promising signals, but with only 4 cycles and a 20% hold rate, the sample is insufficient to draw strong conclusions. The next 6 cycles will be decisive in determining whether RUN belongs in the proven tier.

**Cycle Context**
PULLBACK at 18th percentile with RSI 38.3 and -27% from 50-SMA — a significant compression. 12/20 up days shows buyers are active despite the trend. The PULLBACK state with price well below both moving averages could be entry-zone or falling-knife depending on whether the solar subsidy/rate environment stabilizes. The 20% hold rate makes this a cautious ENGAGE — size conservatively.

**Order Sanity**: 5 matched, 2 drifted, 0 orphaned, 0 paused

**Verdict**: ENGAGE — Strategy fits, ready for engagement

---

### SMCI — ENGAGE (Score: 93/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (34.9%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (3 Active Half+) | 12 | 15 |
| Hold Rate (66.7%) | 6 | 10 |
| Order Hygiene (0 orphaned) | 25 | 25 |
| Cycle Efficiency (11 cycles, 100% fill, median 1d) | 20 | 20 |
| **Total** | **93** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 51.1 |
| 50-SMA distance | +2.0% |
| 200-SMA distance | -22.4% |
| 3-month range pctile | 57th |
| Up days (last 20) | 9/20 |
| Cycle State | NEUTRAL |

**Thesis Assessment**
SMCI is a top-tier ENGAGE — 11 validated cycles at 100% fill with median 1-day deep alongside a clean order map. The AI server infrastructure play remains structural, with SMCI's liquid cooling and GPU rack business benefiting from hyperscaler capex cycles. 66.7% hold rate is respectable for an AI-adjacent name with high institutional volatility.

**Cycle Efficiency**
Proven fast cycler: 11 cycles, 100% fill rate, median 1-day deep. Full 20 cycle points. Combined with 0 orphaned orders and 2 matched orders, execution confidence is high. SMCI is among the top validation-quality names on the watchlist.

**Cycle Context**
NEUTRAL at 57th percentile with RSI 51.1 and just +2.0% above the 50-SMA — equilibrium, not extension. SMCI is consolidating after a prior run without showing technical stress. With 9/20 up days and the 200-SMA 22% below, there's downside cushion before long-term support. Standard ENGAGE setup.

**Order Sanity**: 2 matched, 0 drifted, 0 orphaned, 0 paused

**Verdict**: ENGAGE — Strategy fits, ready for engagement

---

### SOUN — ADD (Score: 75/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (47.8%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (3 Active Half+) | 12 | 15 |
| Hold Rate (80.0%) | 8 | 10 |
| Order Hygiene (0 orphaned) | 25 | 25 |
| Cycle Efficiency (No cycle data) | 0 | 20 |
| **Total** | **75** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 39.0 |
| 50-SMA distance | -16.8% |
| 200-SMA distance | -38.2% |
| 3-month range pctile | 9th |
| Up days (last 20) | 12/20 |
| Cycle State | PULLBACK |

**Thesis Assessment**
SOUN's mean-reversion thesis is healthy — 80% hold rate is the best among ADD-verdict tickers without cycle data, and 47.8% swing with 100% consistency confirms reliable volatility cycles. Voice AI/automotive software exposure makes SOUN a high-narrative play. The one drifted order needs a price check before new bullets.

**Cycle Efficiency**
No cycle timing data. Grace period applies. The 80% hold rate provides indirect evidence of cycle reliability — levels that hold consistently are a precursor to strong cycle data. SOUN is a high-priority candidate for `cycle_timing_analyzer.py` given the strong hold rate suggesting fast, clean cycles.

**Cycle Context**
PULLBACK at 9th percentile with RSI 39.0 and -16.8% from 50-SMA — meaningful compression. 12/20 up days shows resilience. The -38.2% distance from the 200-SMA indicates SOUN has been in a multi-month downtrend from peak; the PULLBACK state here represents a retest of lows rather than a fresh high-to-low move. Entry risk is elevated but so is the reversion potential given the 80% hold rate.

**Order Sanity**: 0 matched, 1 drifted, 0 orphaned, 0 paused

**Verdict**: ADD — Strategy fits, ready for engagement. WARNING: No cycle timing data — run cycle_timing_analyzer.py to validate.

---

### STIM — HOLD-WAIT (Score: 74/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (55.0%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (3 Active Half+) | 12 | 15 |
| Hold Rate (75.0%) | 7 | 10 |
| Order Hygiene (0 orphaned) | 25 | 25 |
| Cycle Efficiency (No cycle data) | 0 | 20 |
| **Total** | **74** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 47.0 |
| 50-SMA distance | -16.4% |
| 200-SMA distance | -48.0% |
| 3-month range pctile | 17th |
| Up days (last 20) | 10/20 |
| Cycle State | NEUTRAL |

**Thesis Assessment**
STIM's mean-reversion thesis is mechanically solid — 75% hold rate, 55% swing, 100% consistency — but the -48% distance from the 200-SMA is a significant structural concern. This level of underperformance relative to the 200-SMA suggests either a prolonged downtrend or a very early recovery stage; mean reversion from these levels carries higher-than-typical risk. Cycle validation is required before engagement.

**Cycle Efficiency**
No cycle timing data — HOLD-WAIT triggered by `cycle_pts < 8`. Zero orders matched (no existing position or pending orders). This is a dormant watchlist position requiring full cycle validation before any capital is deployed. Running `cycle_timing_analyzer.py` is the mandatory first step.

**Cycle Context**
NEUTRAL at 17th percentile with RSI 47.0 — technically mid-range despite being at the low end of the 3-month range. The -48% from the 200-SMA is the dominant data point: STIM is structurally far from recovery. NEUTRAL cycle state here likely reflects recent price stabilization at depressed levels rather than a genuine reversion setup.

**Order Sanity**: 0 matched, 0 drifted, 0 orphaned, 0 paused

**Verdict**: HOLD-WAIT — Strategy fits, but no cycle timing validation (cycle_pts < 8). Run cycle_timing_analyzer.py first.

**Re-entry signals**: First reliable Active Half+ level: $1.33 (support $1.29) | Pullback estimate: $0.69 (from 20d high $1.53)

---

### TEM — ADD (Score: 77/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (37.0%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (4 Active Half+) | 15 | 15 |
| Hold Rate (75.0%) | 7 | 10 |
| Order Hygiene (0 orphaned) | 25 | 25 |
| Cycle Efficiency (No cycle data) | 0 | 20 |
| **Total** | **77** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 41.5 |
| 50-SMA distance | -13.8% |
| 200-SMA distance | -26.7% |
| 3-month range pctile | 8th |
| Up days (last 20) | 10/20 |
| Cycle State | NEUTRAL |

**Thesis Assessment**
TEM's mean-reversion thesis is intact — 75% hold rate on 4 active levels with 100% consistency defines a reliable setup. AI-enabled healthcare/oncology data platform exposure gives TEM a distinct sector niche with institutional catalyst cycles (partnerships, FDA developments). The 1 drifted order warrants price review before new bullets.

**Cycle Efficiency**
No cycle timing data. Grace period applies. The 4 matched zero-orphaned order structure is well-maintained; cycle validation would be the upgrade path to ENGAGE. TEM is a priority for `cycle_timing_analyzer.py` given the strong level infrastructure already in place.

**Cycle Context**
NEUTRAL at 8th percentile with RSI 41.5 and -13.8% from 50-SMA — a deep-ish pullback in NEUTRAL regime, similar to BBAI's profile. 10/20 balanced up/down days shows orderly selling. At 8th percentile, TEM is near the low of its recent range, representing a favorable entry zone for ADD.

**Order Sanity**: 0 matched, 1 drifted, 0 orphaned, 0 paused

**Verdict**: ADD — Strategy fits, ready for engagement. WARNING: No cycle timing data — run cycle_timing_analyzer.py to validate.

---

### TMC — ADD (Score: 95/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (53.0%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (7 Active Half+) | 15 | 15 |
| Hold Rate (54.5%) | 5 | 10 |
| Order Hygiene (0 orphaned) | 25 | 25 |
| Cycle Efficiency (10 cycles, 100% fill, median 1d) | 20 | 20 |
| **Total** | **95** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 46.2 |
| 50-SMA distance | -10.1% |
| 200-SMA distance | -5.5% |
| 3-month range pctile | 12th |
| Up days (last 20) | 11/20 |
| Cycle State | NEUTRAL |

**Thesis Assessment**
TMC is the top ADD at 95/100 with an active position already in place. 10 validated cycles at 100% fill with median 1-day deep, plus 7 active Half+ levels — the broadest level coverage among ADD tickers. Deep-sea mineral mining exposure provides unique volatility cycles tied to regulatory approvals and geopolitical news, making the 53% swing highly reliable.

**Cycle Efficiency**
Proven fast cycler: 10 cycles, 100% fill rate, median 1-day deep. Full 20 cycle points earned. At exactly the 10-cycle threshold, TMC has crossed into the proven tier. The 1 drifted order needs review, but the overall structure is excellent.

**Cycle Context**
NEUTRAL at 12th percentile with RSI 46.2 and -10.1% from 50-SMA — a moderate pullback with nearly balanced up/down days. With an active position and 1 matched order, this is a standard add-to-position environment. The -5.5% from 200-SMA indicates TMC is near its long-term value zone, reinforcing the ADD thesis.

**Order Sanity**: 1 matched, 1 drifted, 0 orphaned, 0 paused

**Verdict**: ADD — Strategy fits, ready for engagement. Active position — ready to add bullets.

---

### UAMY — HOLD-WAIT (Score: 66/100)

**Fitness Score Table**

| Component | Points | Max |
| :--- | :--- | :--- |
| Swing (78.1%) | 15 | 15 |
| Consistency (100.0%) | 15 | 15 |
| Level Quality (2 Active Half+) | 8 | 15 |
| Hold Rate (30.0%) | 3 | 10 |
| Order Hygiene (0 orphaned) | 25 | 25 |
| Cycle Efficiency (No cycle data) | 0 | 20 |
| **Total** | **66** | **100** |

**Cycle Data**

| Indicator | Value |
| :--- | :--- |
| RSI(14) | 59.9 |
| 50-SMA distance | +26.9% |
| 200-SMA distance | +73.9% |
| 3-month range pctile | 87th |
| Up days (last 20) | 11/20 |
| Cycle State | NEUTRAL |

**Thesis Assessment**
UAMY presents a concerning profile — 78.1% swing is impressive but the 30% hold rate means 7 out of 10 support approaches result in breaks, undermining mean-reversion reliability. The +73.9% premium to the 200-SMA is extreme; UAMY has run far above its long-term equilibrium. Antimony/rare earth mining is highly speculative with thin trading, making level reliability difficult to maintain.

**Cycle Efficiency**
No cycle timing data — HOLD-WAIT triggered by `cycle_pts < 8`. The 30% hold rate already raises systemic concerns about whether this stock's behavior is genuinely cyclical or random. Cycle data could clarify whether the lack of level reliability is structural or situational.

**Cycle Context**
NEUTRAL at 87th percentile with RSI 59.9 and +27% above 50-SMA and +74% above 200-SMA — this is momentum exhaustion territory. Despite the "NEUTRAL" cycle state label, the technical picture shows a significantly extended stock. The HOLD-WAIT is prudent: this is not a buying zone by any mean-reversion measure, and engaging at these levels would be momentum chasing, not mean reversion.

**Order Sanity**: 0 matched, 0 drifted, 0 orphaned, 0 paused

**Verdict**: HOLD-WAIT — Strategy fits, but no cycle timing validation (cycle_pts < 8). Run cycle_timing_analyzer.py first.

**Re-entry signals**: First reliable Active Half+ level: $9.50 (support $9.46) | Pullback estimate: $2.52 (from 20d high $11.49)

---

### USAR — RECOVERY

**Thesis Assessment**
Pre-strategy position — fitness scoring does not apply. Use exit-review workflow for current assessment of cost basis vs. current pricing and recovery probability.

**Cycle Efficiency**
N/A — recovery position.

**Cycle Context**
N/A — exit-review workflow takes precedence.

**Order Sanity**: N/A

**Verdict**: RECOVERY — Pre-strategy position — use exit-review-workflow for assessment.

---

## Verdict Summary

| Ticker | Score | Verdict | Cycle | Note |
| :--- | :--- | :--- | :--- | :--- |
| ACHR | 52 | HOLD-WAIT | PULLBACK | Strategy fits, orders need adjustment: 1 orphaned order(s). ... |
| APLD | 75 | ADD | NEUTRAL | Strategy fits, ready for engagement. WARNING: No cycle timin... |
| AR | 75 | RESTRUCTURE | EXTENDED | Strategy fits, orders need adjustment: all Active-zone level... |
| ARM | 77 | ADD | NEUTRAL | Strategy fits, ready for engagement. WARNING: No cycle timin... |
| BBAI | 76 | ENGAGE | NEUTRAL | Strategy fits, ready for engagement. WARNING: No cycle timin... |
| CIFR | 77 | ENGAGE | NEUTRAL | Strategy fits, ready for engagement. WARNING: No cycle timin... |
| CLF | 45 | HOLD-WAIT | OVERSOLD | Strategy fits, orders need adjustment: 3 orphaned order(s). ... |
| CLSK | 95 | ENGAGE | NEUTRAL | Strategy fits, ready for engagement |
| INTC | 72 | HOLD-WAIT | NEUTRAL | Strategy fits, but no cycle timing validation (cycle_pts < 8... |
| IONQ | — | RECOVERY | — | Pre-strategy position — use exit-review-workflow for assessm... |
| LUNR | 96 | ADD | NEUTRAL | Strategy fits, ready for engagement. Active position — ready... |
| NNE | 59 | HOLD-WAIT | PULLBACK | Strategy fits, orders need adjustment: 1 orphaned order(s); ... |
| NU | 70 | ADD | PULLBACK | Strategy fits, ready for engagement. WARNING: No cycle timin... |
| NVDA | 64 | REVIEW | NEUTRAL | Approaching strategy boundary (consistency 84.6% near 80% fl... |
| OKLO | 76 | ADD | NEUTRAL | Strategy fits, ready for engagement. WARNING: No cycle timin... |
| OUST | 100 | ENGAGE | NEUTRAL | Strategy fits, ready for engagement |
| RGTI | 91 | ENGAGE | NEUTRAL | Strategy fits, ready for engagement |
| RKT | 74 | HOLD-WAIT | PULLBACK | Strategy fits, but no cycle timing validation (cycle_pts < 8... |
| RUN | 82 | ENGAGE | PULLBACK | Strategy fits, ready for engagement |
| SMCI | 93 | ENGAGE | NEUTRAL | Strategy fits, ready for engagement |
| SOUN | 75 | ADD | PULLBACK | Strategy fits, ready for engagement. WARNING: No cycle timin... |
| STIM | 74 | HOLD-WAIT | NEUTRAL | Strategy fits, but no cycle timing validation (cycle_pts < 8... |
| TEM | 77 | ADD | NEUTRAL | Strategy fits, ready for engagement. WARNING: No cycle timin... |
| TMC | 95 | ADD | NEUTRAL | Strategy fits, ready for engagement. Active position — ready... |
| UAMY | 66 | HOLD-WAIT | NEUTRAL | Strategy fits, but no cycle timing validation (cycle_pts < 8... |
| USAR | — | RECOVERY | — | Pre-strategy position — use exit-review-workflow for assessm... |

## Override Log

No overrides applied.
