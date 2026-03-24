# Phase 3: Capital Intelligence — Deploy Smarter
*Status: Not Started | Depends on: Phase 1 (P/L data), Phase 2 (cycle frequency data) | Enables: Phase 5 (portfolio optimization)*

## Goal
Get capital cycling faster with less idle time. Measure and improve capital velocity — how fast each dollar completes a buy→sell cycle and starts earning again.

## Deliverable
Morning briefing enriched with fill probabilities, capital deployment recommendations, and a portfolio-wide capital efficiency dashboard.

## Gaps Addressed

| # | Gap | Impact | Effort |
| :--- | :--- | :--- | :--- |
| 5.5 | Fill probability model | High | Medium |
| 2.2 | Fill probability per order | High | Medium |
| 5.4 | Capital velocity metric | High | Medium |
| 5.3 | Staged bullet deployment | High | Low |
| 2.1 | Cycle phase detection | High | Medium |
| 2.5 | Distance-to-first-fill dashboard | Medium | Low |
| 5.1 | Opportunity cost calculation | High | Medium |
| 5.6 | Stale order alerting | Medium | Low |
| 2.4 | Automated cooldown evaluation | Medium | Low |

## Detailed Requirements

### 1. Fill Probability Model (Gaps 5.5, 2.2)

**Problem:** We treat all pending orders equally. B1 at 3% below price and B4 at 15% below are both "pending." But B1 has ~60% weekly fill probability and B4 has ~5%. This distinction matters for capital allocation.

**Solution:** New tool `tools/fill_probability.py` that for each pending order:

1. **Distance factor:** How far is the order price from current price? Closer = higher probability.
2. **Historical fill frequency:** How often has this support level been reached in the last 90 days? From wick analysis approach data.
3. **Approach velocity:** 3-day rate of change (ROC) toward the order level. Mechanical: `(close_today - close_3d_ago) / close_3d_ago`. Negative ROC toward a buy level = increasing fill probability.
4. **Volatility context:** Current 14-day ATR vs order distance. Mechanical ratio: `order_distance / ATR`. Ratio < 1.0 = high probability (within one ATR), ratio > 3.0 = very low probability.
5. **Regime modifier:** Import `classify_regime()` from `market_context_pre_analyst.py` (do NOT re-implement or summarize the logic — the function is the source of truth). Data acquisition: fetch SPY, QQQ, IWM via yfinance (`period="6mo"`), compute each index's 50-day SMA, build `indices` list of dicts with `{"vs_50sma": "Above 50-SMA" | "Below 50-SMA"}`. Fetch `^VIX` via yfinance, build `vix` dict with `{"value": float}`. Pass to `classify_regime(indices, vix)` — returns a dict; extract `result["regime"]` for the regime string. Apply mechanical multiplier per table below. No LLM judgment — pure function call + multiply.

**Regime multiplier table** (distance = order distance from current price):

| Regime | Distance | Multiplier |
| :--- | :--- | :--- |
| Risk-Off | deep (> 2× ATR) | × 1.3 |
| Risk-Off | shallow (≤ 2× ATR) | × 1.0 |
| Neutral | any | × 1.0 |
| Risk-On | deep (> 2× ATR) | × 0.8 |
| Risk-On | shallow (≤ 2× ATR) | × 1.0 |

**Note:** `fill_probability.py` computes probabilities for all pending orders regardless of entry gate status. Morning briefing displays gate status alongside fill probability — gate takes precedence over probability for order execution. ATR is computed from OHLCV data fetched via yfinance; pass high/low/close Series to `technical_scanner.calc_atr(high, low, close)`.

**Output per order:**
```
| Ticker | Order | Price | Distance | Fill Prob (5d) | Fill Prob (10d) | Fill Prob (30d) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| CLSK | B1 | $9.66 | -1.0% | 72% | 89% | 97% |
| CLSK | B2 | $9.09 | -6.9% | 18% | 34% | 62% |
| CLSK | B3 | $8.91 | -8.7% | 12% | 25% | 51% |
| CLSK | B4 | $8.40 | -13.9% | 4% | 10% | 28% |
| OUST | B1 | $20.89 | -2.7% | 55% | 78% | 94% |
```

**Model approach:** Empirical, not statistical. For each ticker:
- Count how many of the last 90 trading days had a low within X% of current price
- Weight recent days higher (exponential decay)
- Adjust for current momentum direction

---

### 2. Capital Velocity Metric (Gap 5.4)

**Problem:** We don't measure how fast capital cycles through trades. This is the core efficiency metric.

**Solution:** Add to `pnl_dashboard.py` (from Phase 1):

```
### Capital Velocity
| Metric | Value |
| :--- | :--- |
| Avg Cycle Duration (all tickers) | 4.3 days |
| Avg Days Capital Deployed per Cycle | 6.1 days (includes unfilled time) |
| Capital Turnover Rate | 5.9x per quarter |
| Annualized Velocity | 23.6x |
| Fastest Ticker | CLSK (2.1 day avg cycle) |
| Slowest Active Ticker | AR (18.3 day avg cycle) |
```

**Per-ticker velocity:**
```
| Ticker | Avg Cycle | Capital/Cycle | Profit/Cycle | $/Day Deployed | Annualized ROI |
| :--- | :--- | :--- | :--- | :--- | :--- |
| CLSK | 2.1d | $58 | $4.12 | $1.96/day | 130% |
| LUNR | 1.8d | $35 | $2.17 | $1.21/day | 88% |
| TMC | 4.5d | $152 | $10.50 | $2.33/day | 96% |
| USAR | 45d | $324 | -$97 | -$2.16/day | -58% |
```

The `$/Day Deployed` metric is the ultimate efficiency measure. Higher = better use of capital.

---

### 3. Staged Deployment Rules (Gap 5.3)

**Problem:** We place all 5 bullets at onboarding. Most capital sits idle in deep orders. That capital could be deployed to higher-probability fills elsewhere.

**Solution:** New deployment policy encoded in `tools/deployment_advisor.py`:

**Rules:**
1. **Always place B1 and B2** — these are the high-probability fills that drive most cycles
2. **Place B3 when:** price is within 2× ATR of B2, OR B2 has filled (cascade protection)
3. **Place B4-B5 when:** B3 has filled, OR regime is Risk-Off (import `classify_regime()` from `market_context_pre_analyst.py`; data acquisition same as fill_probability factor 5 — fetch SPY/QQQ/IWM + ^VIX via yfinance, build dicts, call function)
4. **Reserve bullets:** Only place when active bullets B3+ have filled (deep dive scenario)

**Output:**
```
### Deployment Recommendations
| Ticker | B1 | B2 | B3 | B4 | B5 | R1-R3 | Action |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| CLSK | Placed | Placed | Hold | Hold | Hold | Hold | B3 capital available: $71 |
| OUST | Placed | Placed | Placed | Hold | — | Hold | Price within 2× ATR of B2 |
| CLF | Filled | Filled | Filled | Filled | Filled | Hold | Fully deployed, await exit |
```

**Capital freed:** Sum of held bullet costs = capital available for other tickers or cash.

**Definition:** "Approaching" = price is within 2× ATR of the level. ATR is computed from
OHLCV data fetched via yfinance; pass high/low/close Series to `technical_scanner.calc_atr(high, low, close)`.

---

### 4. Cycle Phase Detection (Gap 2.1)

**Problem:** We don't know where a ticker is in its resistance→pullback→support→bounce cycle. This affects when to load bullets and what to expect.

**Solution:** New tool `tools/cycle_phase_detector.py` that for each ticker:

1. Identifies last local high and last local low using the same algorithm as `technical_scanner.py`:
   local high = bar whose high is the maximum in a ±10-bar window; local low = bar whose
   low is the minimum in a ±10-bar window. Levels within 1.5% are clustered (same as
   `find_support_resistance()` in `technical_scanner.py`).
2. Computes mechanical metrics:
   - Days since last local high
   - Days since last local low
   - Current price position: `(price - local_low) / (local_high - local_low)` → 0.0 = at support, 1.0 = at resistance
     Guard: if `local_high == local_low` OR range < 1.5% of local_high (flat zone, same
     clustering threshold as `find_support_resistance()`), set `position = 0.5`. Clamp to `[0.0, 1.0]`.
   - 3-day ROC (same as fill_probability factor 3)
3. Assigns phase label via deterministic rules. **Rules evaluated in order — first match wins:**

| Priority | Phase | Rule (all mechanical) |
| :--- | :--- | :--- |
| 1 | SUPPORT | Price position < 0.15 OR price within 1× ATR of nearest active support level (read from cached `tickers/<TICKER>/wick_analysis.md` bullet plan Active rows; fallback: portfolio.json pending_orders BUY prices) |
| 2 | RESISTANCE | Price position > 0.85 AND ROC flattening (abs(ROC) < 0.5%) |
| 3 | PULLBACK | Position ratio declining (position_today < position_yesterday) AND ROC < -0.5% |
| 4 | RECOVERY | Default — none of the above matched |

4. Reports historical median cycle duration: read `statistics.median_deep` from
   `tickers/<TICKER>/cycle_timing.json` (reflects full order-zone fill timing). If
   unavailable, fall back to `statistics.median_first`. If no cycle_timing.json exists,
   output "N/A". This is a mechanical lookup, not a prediction.

**Output:**
```
### Cycle Phase — All Tickers
| Ticker | Phase | Days in Phase | Position | B1 Distance | Median Cycle | Signal |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| CLSK | PULLBACK | 1d | 0.32 | -1.0% | 2.1d | B1 within 1 ATR |
| OUST | RECOVERY | 3d | 0.58 | -2.7% | 4.5d | Rising from support |
| CLF | SUPPORT | 2d | 0.08 | — (filled) | 3.8d | At support floor |
| LUNR | RESISTANCE | 4d | 0.91 | -7.2% | 1.8d | Near local high |
```

**Schema change:** Removed 'Est. Days to B1' (qualitative prediction) → replaced with
'Median Cycle' (mechanical lookup from backtest data).

**Signal column definitions** (mechanical, all 4 values):

| Signal | Rule |
| :--- | :--- |
| At support floor | Phase = SUPPORT |
| Near local high | Phase = RESISTANCE |
| B1 within 1 ATR | Phase = PULLBACK AND pending B1 exists AND `abs(order_distance) / ATR < 1.0` |
| Pulling back | Phase = PULLBACK AND (no pending B1 OR `abs(order_distance) / ATR >= 1.0`) |
| Rising from support | Phase = RECOVERY |

No LLM judgment — Signal is a direct mapping from phase.

---

### 5. Distance-to-First-Fill Dashboard (Gap 2.5)

**Problem:** No single view of which tickers are about to cycle vs dormant.

**Solution:** Simple output from `fill_probability.py` sorted by distance to B1:

```
### Nearest Fills
| Ticker | B1 Price | Current | Distance | Fill Prob (5d) | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| CLSK | $9.66 | $9.76 | -1.0% | 72% | Imminent |
| LUNR | $17.59 | $17.60 | -0.1% | 91% | At level |
| OUST | $20.89 | $21.47 | -2.7% | 55% | Approaching |
| SMCI | $29.95 | $30.75 | -2.6% | 48% | Approaching |
| TMC | $5.63 | $5.97 | -5.7% | 22% | Distant |
| OKLO | $58.04 | $58.37 | -0.6% | 65% | Imminent |
```

**Status label thresholds** (mechanical, based on absolute distance %, first match wins):

| Status | Rule |
| :--- | :--- |
| At level | distance < 0.5% |
| Imminent | distance < 1.5% |
| Approaching | distance < 5% |
| Near | distance < 10% |
| Distant | distance ≥ 10% |

**Note:** Comparison uses `abs(distance)` — all distances are treated as positive values
for threshold matching, regardless of whether the order is above or below current price.

---

### 6. Opportunity Cost Calculation (Gap 5.1)

**Problem:** Capital in low-probability orders has an opportunity cost — it could be earning returns in active cyclers.

**Solution:** For each pending order, compute:
- Expected value = fill_probability × expected_cycle_profit
- Opportunity cost = what that capital would earn if deployed in the highest-velocity ticker instead

```
### Opportunity Cost Analysis
| Ticker | Order | Capital | Fill Prob (30d) | EV (30d) | Best Alternative EV | Delta |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| CLSK B1 | $39 | 97% | $2.28 | — | — | Keep |
| CLSK B4 | $84 | 28% | $1.41 | $4.89 (→LUNR) | -$3.48 | Redeploy |
| AR B3 | $93 | 8% | $0.45 | $5.42 (→CLSK) | -$4.97 | Redeploy |
```

**Redeployment verdict** (mechanical, in Python):

| Verdict | Rule |
| :--- | :--- |
| REDEPLOY | Alternative EV exceeds current EV by ≥ 3× (i.e., `best_alt_ev / current_ev >= 3.0`) |
| REVIEW | Alternative EV exceeds current EV by ≥ 1.5× but < 3× |
| KEEP | Alternative EV < 1.5× current EV, or order is B1/B2 (never redeploy first-line defense) |

Python outputs the verdict. No LLM interpretation needed — the ratio is deterministic.
The 3× threshold reflects that redeployment has friction (cancel, re-place, timing risk),
so the alternative must be substantially better, not marginally better.

**EV computation** (defined earlier in Section 6 of Phase 3, preserved unchanged):
`current_ev = fill_probability × expected_cycle_profit` for this order.
`best_alt_ev = max(fill_probability × expected_cycle_profit)` across all other tickers'
highest-probability unfilled orders. Both values come from `fill_probability.py` output
(Violation 1) combined with per-ticker cycle profit from Phase 2 backtest data.

**Bullet label source:** Read the `note` field from each BUY entry in the ticker's
`pending_orders` array in `portfolio.json`. The note field contains the label directly
(e.g., "Bullet 1 —", "Bullet 2 —", "Reserve 1 —"). Parse the label prefix before the
em dash. Do NOT re-derive labels by sorting or numbering — use the note field as-is.

---

### 7. Stale Order Alerting (Gap 5.6)

**Problem:** Orders sitting unfilled for 14+ days without price approaching should be flagged.

**Solution:** Add to morning briefing:
```
### Stale Orders (>14 days, no approach)
| Ticker | Order | Price | Placed | Days | Last Approach | Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| AR | B3 $31.16 | $31.16 | 2026-02-28 | 15d | Never | REDEPLOY |
| USAR | — | — | pre-strategy | 45d | Never | REVIEW |
```

**Definitions:**
- **"No approach":** Day low never came within 2× ATR of order price during the stale period
  (14+ days). ATR is computed from OHLCV data fetched via yfinance; pass high/low/close
  Series to `technical_scanner.calc_atr(high, low, close)`.
- **Verdict:** Uses the same REDEPLOY/REVIEW/KEEP logic from Section 6 (Opportunity Cost).
  Compute EV ratio for the stale order vs best alternative; apply thresholds (3× = REDEPLOY,
  1.5× = REVIEW, else KEEP).

---

### 8. Automated Cooldown Evaluation (Gap 2.4)

**Problem:** We manually analyzed CLSK/RUN/OUST/TMC cooldown status. Should be automated.

**Solution:** New tool `tools/cooldown_evaluator.py` that:
1. Reads `cooldown.json`
2. For each ticker in cooldown, fetches current price and computes decay from sell
3. Evaluates: pullback %, active support freshness, cycle history, reserve dormancy
4. Outputs recommendation: EXIT COOLDOWN / HOLD COOLDOWN / EXTEND COOLDOWN

```
### Cooldown Status
| Ticker | Sold | Sell Price | Current | Decay | Reeval | Best Active Tier | Hold Rate | Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| RUN | Mar 10 | $11.81 | $12.14 | +2.8% | Mar 16 | Half | 22% | HOLD |
| CLSK | Mar 13 | $10.24 | $9.76 | -4.7% | — | Full | 58% | EXIT |
```

**Verdict rules** (deterministic, in Python):

| Verdict | Rule |
| :--- | :--- |
| EXTEND | All active support levels broke since sell date (no reliable floor to re-enter on). "Broke" = daily close below the individual level price for 2+ consecutive trading days. Single-day wicks below do not count. Check each level independently (not clustered groups). |
| EXIT | Decay < 0% (price pulled back from sell) AND best active tier is Std or Full (hold_rate ≥ 30%) |
| HOLD | Default — none of the above matched |

**Rules evaluated in order — first match wins** (same pattern as cycle_phase_detector).
EXTEND is checked first because structural breakdown overrides price/tier signals.

Support quality classification reuses the existing tier system from `wick_offset_analyzer.py`:
Full (≥50%), Std (30-49%), Half (15-29%), Skip (<15%). No new quality labels needed.

**"Best active tier" data source:** Read from cached `tickers/<TICKER>/wick_analysis.md` —
parse the "Suggested Bullet Plan" table, filter rows where Zone = "Active", read the Tier
column. Highest tier among active levels = best active tier (Full > Std > Half > Skip).
If no cache exists, call `wick_offset_analyzer.analyze_stock_data(ticker)` (pass ticker symbol only; function fetches its own data via yfinance) and read
`data["bullet_plan"]["active"]` entries' `"tier"` field from the returned dict.

**Note:** The `"tier"` field in bullet_plan entries is the effective_tier (recency-adjusted
via `compute_effective_tier()`), not the raw 13-month tier. This is correct for cooldown
evaluation — effective_tier reflects current reliability, which is what matters for
re-entry decisions.

Integrate into morning briefing — auto-run daily for all cooldown tickers.

---

## Implementation Order

1. `tools/fill_probability.py` — core model (distance + ATR + historical frequency)
2. `tools/cycle_phase_detector.py` — phase detection per ticker (reuses technical_scanner.py peak/trough algorithm, deterministic phase rules)
3. `tools/deployment_advisor.py` — staged deployment recommendations
4. `tools/cooldown_evaluator.py` — automated cooldown assessment
5. Capital velocity metric — add to pnl_dashboard.py
6. Opportunity cost calculation — add to fill_probability.py
7. Stale order alerting — add to morning briefing
8. Distance-to-fill dashboard — sort/format fill_probability output

## Estimated Effort
- fill_probability.py: ~250 lines, 1.5 sessions
- cycle_phase_detector.py: ~200 lines, 1 session
- deployment_advisor.py: ~150 lines, 1 session
- cooldown_evaluator.py: ~150 lines, 0.5 session
- Dashboard integrations: ~100 lines, 0.5 session
- Morning briefing integration + testing: 1 session
- **Total: ~5.5 sessions**

## Success Criteria
- [ ] Fill probability model produces reasonable estimates validated against actual fill history
- [ ] Cycle phase detection correctly identifies current phase for all active tickers
- [ ] Staged deployment frees measurable capital vs current all-at-once approach
- [ ] Capital velocity metric calculated for all tickers with completed cycles
- [ ] Cooldown evaluation matches manual analysis quality (tested against CLSK/RUN examples)
- [ ] Opportunity cost flags at least 3 redeployment candidates in current portfolio
- [ ] All outputs integrated into morning briefing workflow
- [ ] All Python tool specs produce deterministic output from mechanical rules — no qualitative labels without explicit threshold definitions
- [ ] fill_probability.py imports classify_regime() from market_context_pre_analyst.py (function call, not re-implementation)
- [ ] cycle_phase_detector.py phase rules are fully defined by numeric thresholds (position ratio + ROC), evaluated in priority order
- [ ] cooldown_evaluator.py reuses wick_offset_analyzer.py tier system for support quality
- [ ] Distance-to-fill Status labels have defined % thresholds
- [ ] Stale order alerting defines "no approach" mechanically (2× ATR) and uses EV-ratio verdicts
- [ ] Staged deployment defines "approaching" mechanically (2× ATR) and "deep pullback" via regime function
