# Phase 5: Full System — Backtested Screening + Portfolio Optimization
*Status: Not Started | Depends on: All previous phases | Enables: Autonomous operation*

## Goal
Close the loop — screening predicts profitability, the portfolio is globally optimized across all tickers, and the system operates with minimal manual intervention.

## Deliverable
Fully integrated system where: screening score correlates with actual profitability, capital is globally optimized across tickers, reserves deploy conditionally, and targets adapt to market regime.

## Gaps Addressed

| # | Gap | Impact | Effort |
| :--- | :--- | :--- | :--- |
| 1.1 | Backtested success metric for screening | High | High |
| 1.2 | Post-onboard performance vs score tracking | High | Medium |
| 1.3 | Formal KPI card for screening | Medium | Low |
| 5.2 | Cross-portfolio capital optimization | High | High |
| 4.4 | Deep dive vs cut losses threshold (enhanced) | High | Medium |
| 4.2 | Conditional reserve deployment | Medium | Medium |
| 9.5 | Regime-adaptive targets | Medium | Medium |
| 2.5 | Distance-to-first-fill (enhanced) | Medium | Low |
| 8.3 | Split-sell optimization model | Medium | Medium |

## Detailed Requirements

### 1. Backtested Screening Score (Gaps 1.1, 1.2)

**Problem:** Screening scores tickers on support quality metrics but never validates whether those metrics predict actual cycling profitability.

**Solution:** Use Phase 2's `target_optimizer.py` as a backtesting engine for screening:

1. For each candidate ticker, run `target_optimizer.py` with the ticker's optimal target %
2. The simulated 13-month profit becomes the **backtested score** — the definitive "would this have worked?" metric
3. Compare backtested score against the surgical screening score
4. Build a correlation model: which screening factors best predict backtested profitability

**New screening output:**
```
### Candidate Evaluation (with Backtest)
| Ticker | Screen Score | Backtest Profit (13mo) | Backtest Cycles | Backtest Win% | Combined Score |
| :--- | :--- | :--- | :--- | :--- | :--- |
| RGTI | 90 | $412 | 31 | 97% | 95 |
| OKLO | 88 | $189 | 8 | 100% | 72 |
| NTLA | 87 | $256 | 18 | 89% | 78 |
```

OKLO drops significantly — high screening score but low backtest profit due to price/pool mismatch. RGTI's backtest confirms the screening score. This validation layer prevents bad onboards.

**Correlation analysis output:**
```
### Screening Factor Correlation with Backtest Profit
| Factor | Correlation | Significance |
| :--- | :--- | :--- |
| Monthly Swing % | 0.72 | High — strongest predictor |
| Active Level Count | 0.45 | Medium |
| Avg Hold Rate | 0.38 | Medium |
| Dead Zone % | -0.61 | High — strong negative |
| Price Range ($5-15) | 0.52 | Medium — pool efficiency |
| Recency (levels tested <30d) | 0.33 | Low-Medium |
```

Use these correlations to re-weight the screening formula.

---

### 2. Formal KPI Card (Gap 1.3)

**Problem:** Screening thresholds are implicit and evolved organically.

**Solution:** Based on correlation analysis (above), define explicit pass/fail KPIs:

```
### Surgical Screening KPI Card v2.0
| KPI | Threshold | Weight | Rationale |
| :--- | :--- | :--- | :--- |
| Monthly Swing | >= 35% | 25% | Strongest profit predictor |
| Active Levels (hold >= 30%) | >= 3 | 15% | Minimum averaging structure |
| Anchor Level (hold >= 50%) | >= 1 | 10% | At least one reliable floor |
| Dead Zone | < 30% | 20% | Strong negative predictor |
| Price Range | $5 - $30 | 15% | Pool efficiency ($300 sizing) |
| Recency | >= 2 levels tested in 30d | 10% | Current regime relevance |
| Sector Concentration | <= 2x post-onboard | 5% | Portfolio risk |
| **Backtested Profit (13mo)** | **>= $200** | **Pass/Fail gate** | **Must be profitable** |
```

The backtested profit becomes a hard gate — no ticker onboards without a simulated proof of profitability.

---

### 3. Cross-Portfolio Capital Optimization (Gap 5.2)

**Problem:** We optimize per-ticker but not across the portfolio. Capital in low-probability orders for one ticker could earn more in high-probability fills for another.

**Solution:** New tool `tools/portfolio_optimizer.py` that:

1. Reads all pending orders with fill probabilities (Phase 3)
2. Reads per-ticker capital velocity (Phase 3) and optimal targets (Phase 2)
3. Computes expected value per dollar deployed for each order:
   `EV = fill_probability × (cycle_profit / cycle_days) × capital_deployed`
4. Ranks ALL orders across ALL tickers by EV per dollar
5. Recommends capital reallocation from low-EV to high-EV orders

**Output:**
```
### Portfolio Capital Optimization
| Action | From | To | Amount | EV Gain/Month |
| :--- | :--- | :--- | :--- | :--- |
| Redeploy | AR B3 ($93) | CLSK B1 ($93) | $93 | +$12.40 |
| Redeploy | USAR R1 ($87) | LUNR B2 ($80) | $80 | +$8.20 |
| Redeploy | OUST B3 ($76) | TMC B2 ($60) | $60 | +$4.50 |
| **Total monthly EV gain** | | | **$233** | **+$25.10** |
```

**Constraints:**
- Never redeploy B1 or B2 from any ticker (always maintain first-line defense)
- Never exceed $600 total per ticker (active + reserve cap)
- Maintain minimum 2 active bullets per ticker
- Respect sector concentration limits

---

### 4. Conditional Reserve Deployment (Gap 4.2)

**Problem:** Reserves are set-and-forget. Market context should influence whether reserves fire.

**Solution:** Reserve deployment rules based on market regime (from market-context-workflow):

```
### Reserve Deployment Rules
| Regime | VIX Range | Action |
| :--- | :--- | :--- |
| Risk-On | VIX < 18 | Hold reserves — pullback likely shallow, recovers fast |
| Neutral | VIX 18-25 | Deploy R1 only — moderate pullback, some support |
| Risk-Off | VIX 25-35 | Deploy R1 + R2 — deep pullback likely, averaging helps |
| Crisis | VIX > 35 | Hold ALL — indiscriminate selling, support levels unreliable |
```

**Deployment status decision tree** (evaluated by `deployment_advisor.py`):

Step 1 — VIX regime sets base status:

| Regime | VIX Range | Base Status | Action |
| :--- | :--- | :--- | :--- |
| Risk-On | VIX < 18 | HOLD_VIX_RISK_ON | Hold reserves — shallow pullback, recovers fast |
| Neutral | VIX 18-25 | DEPLOY_R1_ONLY | Deploy R1 only — moderate pullback |
| Risk-Off | VIX 25-35 | DEPLOY_R1_R2 | Deploy R1 + R2 — deep pullback likely |
| Crisis | VIX > 35 | HOLD_VIX_CRISIS | Hold ALL — indiscriminate selling |

Step 2 — If base allows deployment (DEPLOY_R1_ONLY or DEPLOY_R1_R2), apply mechanical
gates in order. First gate that fires overrides the base status:

a. Position age < 7 days → override to HOLD_MECHANICAL (too early to double down)
b. Reserve level dormant [D] (not tested in 90 days) → override to HOLD_MECHANICAL
c. SECTOR_MAP lookup (import from `market_context_gatherer.py`) → if sector flagged,
   override to DEPLOY_PENDING_SECTOR_REVIEW

Step 3 — If no gate fires, keep base status.

**deployment_status enum** (6 values):

| Status | Source | LLM Review? |
| :--- | :--- | :--- |
| DEPLOY_R1_ONLY | VIX Neutral, all gates pass | No |
| DEPLOY_R1_R2 | VIX Risk-Off, all gates pass | No |
| HOLD_MECHANICAL | Position age or dormancy gate fired | No |
| HOLD_VIX_RISK_ON | VIX < 18 | No |
| HOLD_VIX_CRISIS | VIX > 35 | No |
| DEPLOY_PENDING_SECTOR_REVIEW | Sector gate fired | **Yes** — LLM assesses structural vs cyclical |

Only DEPLOY_PENDING_SECTOR_REVIEW requires LLM attention. The LLM (market-context-workflow
or morning briefing analyst) reads the sector flag and assesses whether the decline is
structural (hold reserves) or cyclical (proceed with deployment).

`deployment_advisor.py` writes the status to `ticker_profiles.json` under `deployment_status`.

---

### 5. Regime-Adaptive Targets (Gap 9.5)

**Problem:** Optimal target % shifts with market volatility. High-VIX months allow higher targets.

**Solution:** Extend `target_optimizer.py` to segment backtests by VIX regime:

1. Classify each trading day as Low-VIX (<18), Normal (18-25), or High-VIX (>25)
2. Run target optimization separately for each regime
3. Output regime-specific optimal targets

```
### Regime-Adaptive Targets — CLSK
| Regime | Optimal Target | Cycles/Month | Total Profit (annualized) |
| :--- | :--- | :--- | :--- |
| Low VIX (<18) | 3.0% | 3.5 | $126/month |
| Normal (18-25) | 4.0% | 2.8 | $134/month |
| High VIX (>25) | 5.5% | 2.0 | $132/month |
```

**Implementation:** Morning briefing checks current VIX, selects the regime-appropriate target for each ticker, and updates sell orders if the target has changed.

---

### 6. Split-Sell Optimization (Gap 8.3)

**Problem:** When to sell all at one price vs split across two resistance levels?

**Solution:** Using post-sell tracking data (Phase 1) and backtesting (Phase 2):

1. For each ticker with 10+ completed cycles, simulate split vs all-at-once sells
2. Compute EV of split: `0.6 × T1_price × shares + 0.4 × probability_of_reaching_T2 × T2_price × shares`
3. Compare against EV of all-at-T1: `1.0 × T1_price × shares`
4. If split EV > all-at-once EV by > 1%, recommend split

```
### Split-Sell Analysis — CLSK
| Strategy | Expected Value | Risk |
| :--- | :--- | :--- |
| All at T1 ($10.24) | $788.48 | None — guaranteed if T1 hit |
| Split 60/40 at T1/T2 ($10.24/$10.67) | $801.22 | 40% of shares may not sell at T2 |
| EV Difference | +$12.74 (+1.6%) | |
| **Recommendation** | **Split** — continuation probability 65% |
```

---

### 7. Enhanced Distance-to-Fill (Gap 2.5 enhanced)

**Problem:** Phase 3 provides basic distance-to-fill. Phase 5 adds portfolio-level prioritization.

**Solution:** Combine fill probability (Phase 3) with capital velocity (Phase 3) and optimal target (Phase 2):

```
### Portfolio Fill Priority
| Priority | Ticker | Order | Fill Prob (5d) | EV/Day | Capital | Action |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | LUNR | B1 $17.59 | 91% | $1.21 | $35 | Monitor closely |
| 2 | CLSK | B1 $9.66 | 72% | $1.96 | $39 | Ready to fill |
| 3 | OKLO | B1 $58.04 | 65% | $0.42 | $58 | Low EV — consider skip |
| ... | | | | | | |
| 15 | AR | B3 $31.16 | 2% | $0.03 | $93 | Stale — redeploy |
```

This is the "command center" view — shows where to focus attention and where capital is wasted.

---

## Implementation Order

1. Backtested screening integration — run target_optimizer for all candidates in surgical_filter
2. Correlation analysis — screening factors vs backtest profit
3. Formal KPI card v2.0 — update surgical_filter thresholds
4. `tools/portfolio_optimizer.py` — cross-portfolio capital optimization
5. Conditional reserve deployment — extend deployment_advisor.py with VIX decision tree, mechanical gates (age, dormancy), SECTOR_MAP import from market_context_gatherer.py, writes deployment_status to ticker_profiles.json
6. Regime-adaptive targets — extend target_optimizer with VIX segmentation
7. Split-sell optimization — extend sell_target_calculator
8. Enhanced distance-to-fill — integrate all Phase 3-5 data into morning briefing
9. Ticker profile v2.0 — update ticker_profiles.json with all Phase 5 outputs

## Estimated Effort
- Backtested screening: ~200 lines, 1 session
- Correlation analysis: ~150 lines, 1 session
- KPI card + screening formula update: ~100 lines, 0.5 session
- portfolio_optimizer.py: ~300 lines, 2 sessions
- Conditional reserves: ~100 lines, 0.5 session
- Regime-adaptive targets: ~150 lines, 1 session
- Split-sell optimization: ~100 lines, 0.5 session
- Integration + command center view: ~200 lines, 1 session
- End-to-end testing: 1 session
- **Total: ~8.5 sessions**

## Success Criteria
- [ ] Backtested profit is a mandatory gate in screening — no ticker onboards without simulated profit > $200
- [ ] Screening score correlates with actual cycling profitability (R > 0.5)
- [ ] Cross-portfolio optimizer identifies at least $200/month in reallocation gains
- [ ] Conditional reserve deployment prevents at least 1 bad reserve firing per quarter
- [ ] Regime-adaptive targets outperform static 6% in backtested simulation
- [ ] Split-sell recommendations produce measurable EV improvement
- [ ] Morning briefing provides complete "command center" view of portfolio
- [ ] System requires < 15 minutes of daily manual intervention (vs current ~45 min)
- [ ] deployment_advisor outputs DEPLOY_PENDING_SECTOR_REVIEW for sector-ambiguous cases; decision tree produces deterministic status for all VIX/gate combinations

---

## End State Vision

After Phase 5, the system operates as:

1. **Screening** finds candidates with backtested profitability proof
2. **Onboarding** sets per-ticker optimal targets, bullet counts, and level spacing
3. **Daily briefing** shows fill priorities, capital reallocation recommendations, regime-adaptive targets
4. **Deployment advisor** stages bullets, manages cooldowns, flags stale orders
5. **Loss evaluator** auto-flags trapped capital with quantified redeployment ROI
6. **Post-sell tracker** feeds adaptive sell targets continuously
7. **Portfolio optimizer** reallocates capital across tickers monthly

The user's daily workflow becomes:
1. Read morning briefing (2 min)
2. Place/adjust recommended orders (5 min)
3. Confirm fills and exits (3 min)
4. Review any flagged positions (5 min)
5. **Total: ~15 min/day**
