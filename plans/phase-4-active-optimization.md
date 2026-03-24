# Phase 4: Active Optimization — Fine-Tune the Strategy
*Status: Not Started | Depends on: Phase 1 (trade history), Phase 2 (backtesting engine), Phase 3 (fill probability) | Enables: Phase 5 (full system)*

## Goal
Optimize bullet placement, sell targets, and loss management using data collected in Phases 1-3. Move from generic rules to per-ticker optimized profiles.

## Deliverable
Per-ticker strategy profile: optimal bullet count, level spacing, adaptive sell target, abandon threshold. Output as `ticker_profiles.json` consumed by all tools.

## Gaps Addressed

| # | Gap | Impact | Effort |
| :--- | :--- | :--- | :--- |
| 3.1 | Pullback depth profiling | High | Medium |
| 3.2 | Optimal bullet count per ticker | High | Medium |
| 3.3 | Averaging efficiency metric | Medium | Low |
| 8.2 | Adaptive sell targets | High | Medium |
| 6.1 | Break-even time estimate | High | Medium |
| 6.2 | Formal abandon-position criteria | High | Medium |
| 6.3 | Redeployment ROI calculator | High | Medium |
| 6.4 | Capital trap alerting | Medium | Low |
| 2.4 | Automated cooldown evaluation (enhanced) | Medium | Low |
| 4.1 | Reserve utilization rate | Medium | Low |
| 4.4 | Deep dive vs cut losses threshold | High | Medium |
| 2.3 | Velocity/momentum filter | Medium | Medium |

## Detailed Requirements

### 1. Pullback Depth Profiling (Gap 3.1)

**Problem:** We know monthly swing but not pullback depth distribution. "80% of CLSK pullbacks reach -5%, 45% reach -8%, 15% reach -12%." This determines how many bullets are useful.

**Solution:** New tool `tools/pullback_profiler.py` that:

1. Identifies all pullback events in 13-month OHLC data (local high → local low)
2. Measures each pullback's depth as % from the preceding local high
3. Builds a cumulative distribution: what % of pullbacks reach each depth level
4. Maps distribution to current bullet levels: "B1 at -3% would have filled in 85% of pullbacks. B4 at -12% would have filled in 18%."

**Output per ticker:**
```
### Pullback Depth Profile — CLSK
| Depth | % of Pullbacks Reaching | Cumulative Fills | Mapped Bullet |
| :--- | :--- | :--- | :--- |
| -2% | 95% | — | — |
| -3% | 85% | B1 ($9.66) | 85% fill rate |
| -5% | 62% | — | — |
| -7% | 45% | B2 ($9.09) | 45% fill rate |
| -9% | 32% | B3 ($8.91) | 32% fill rate |
| -12% | 18% | B4 ($8.40) | 18% fill rate |
| -15% | 8% | — | — |
| -20% | 3% | — | — |

Pullback count (13 months): 28
Avg depth: -7.2%
Median depth: -5.8%
```

**This directly answers:** "Is B4 worth deploying? It fills only 18% of the time — $84 sitting idle 82% of the time."

---

### 2. Optimal Bullet Count Per Ticker (Gap 3.2)

**Problem:** We use up to 5 active bullets for all tickers. Some tickers might be better with 3 concentrated bullets.

**Solution:** Extend `target_optimizer.py` (Phase 2) to also sweep bullet counts:

For each bullet count (1 through 5), simulate 13 months using the optimal target % (from Phase 2):
- 1 bullet: all $300 at B1
- 2 bullets: $150 each at B1, B2
- 3 bullets: $100 each at B1, B2, B3
- 4 bullets: $75 each at B1-B4
- 5 bullets: $60 each at B1-B5

Compare total profit. The optimal count maximizes profit while keeping capital utilization high.

**Output:**
```
### Optimal Bullet Count — CLSK (at 3.5% target)
| Bullets | Total Profit (13mo) | Avg Cost Improvement | Capital Utilization | Recommendation |
| :--- | :--- | :--- | :--- | :--- |
| 1 | $298 | 0% | 95% | Underdiversified |
| 2 | $318 | 2.1% | 88% | Good |
| 3 | $325 | 3.4% | 78% | Optimal ← |
| 4 | $320 | 3.9% | 65% | Diminishing returns |
| 5 | $312 | 4.2% | 52% | Over-deployed |
```

---

### 3. Averaging Efficiency Metric (Gap 3.3)

**Problem:** Do additional bullets actually improve outcomes, or does B1 alone drive most cycles?

**Solution:** From Phase 1 trade_history.json, analyze each completed cycle:
- How many bullets filled?
- What was the cost basis improvement from averaging?
- Would B1-only have been profitable? At what target?

```
### Averaging Efficiency — All Completed Cycles
| Bullets Filled | Cycles | Avg Cost Improvement | Avg Profit | B1-Only Would Have Worked? |
| :--- | :--- | :--- | :--- | :--- |
| 1 | 28 (60%) | 0% | +6.4% | Yes (100%) |
| 2 | 12 (25%) | -3.2% | +5.8% | Yes (83%) |
| 3 | 5 (11%) | -6.1% | +5.2% | Yes (60%) |
| 4+ | 2 (4%) | -9.4% | +4.1% | No (0%) |
```

If 60% of cycles fill only B1 and still profit, the deeper bullets are insurance — useful but not driving revenue.

---

### 4. Adaptive Sell Targets (Gap 8.2)

**Problem:** Sell targets are static. If a ticker consistently runs past our sell level, we're leaving money on the table. If it consistently reverses before our sell, we're missing exits.

**Solution:** Using post-sell tracking data (from Phase 1, gap 8.1), compute adaptive adjustment:

1. For each ticker with 3+ completed cycles, analyze post-sell continuation
2. If average peak-after-sell > 2% above sell price → raise target by 0.5-1.0%
3. If sell target was NOT hit in >30% of attempts (price reversed before reaching it) → lower target by 0.5-1.0%
4. Combine with Phase 2 optimal target % for final recommendation

```
### Adaptive Sell Target — CLSK
| Metric | Value |
| :--- | :--- |
| Current Target | 6.0% |
| Phase 2 Optimal (backtested) | 3.5% |
| Avg Post-Sell Continuation | +2.3% |
| Sell Hit Rate | 100% (4/4) |
| Adaptive Adjustment | +0.5% (continuation suggests room) |
| **Final Recommended Target** | **4.0%** |
```

**Important:** Adaptive targets use BOTH backtested optimal (Phase 2) AND actual post-sell data (Phase 1). The backtest provides the structural answer; the post-sell data provides the fine-tuning.

---

### 5. Loss Recognition Framework (Gaps 6.1, 6.2, 6.3, 6.4)

**Problem:** No quantitative framework for when to cut losses and redeploy capital.

**Solution:** New tool `tools/loss_evaluator.py` with four components:

**A. Break-Even Time Estimate (Gap 6.1)**
For each underwater position:
- Compute distance to break-even price
- Use historical bounce rate from current support level
- Estimate days to reach break-even based on typical recovery speed at this depth

```
| Ticker | Avg Cost | Current | Loss | Support Below | Bounce Rate | Est Break-Even |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| CLF | $9.39 | $8.46 | -9.9% | $8.25 (58%) | 4.2 days avg | 8-12 days |
| ACHR | $6.61 | $6.03 | -8.8% | $5.85 (50%) | 5.1 days avg | 10-15 days |
| USAR | $21.57 | $17.50 | -18.9% | None active | N/A | 30+ days |
```

**Implementation note:** When no active support level exists below the current price,
`loss_evaluator.py` outputs "30+ days" as a hard-coded mechanical ceiling representing
"recovery horizon unknown, exceeds 30-day opportunity cost threshold." This is NOT a
qualitative assessment. The 30-day value here and C2's 30-day threshold are independent:
C2 reads position age from portfolio.json, not from this estimate.

**B. Formal Abandon Criteria (Gap 6.2)**

`loss_evaluator.py` flags a position for exit review when ANY mechanical criterion triggers:

1. All active support levels broke in last 30 days (no floor)
2. Capital trapped > 30 days without cycling (opportunity cost too high).
   Data source: position age from portfolio.json, NOT from Section 5A break-even estimate.
3. Loss > 20% AND no reserve support can reduce break-even to within 15% of current price
   — aligned with Section 7's reserve effectiveness ceiling (15% = reserves cannot rescue).
   **Note:** This threshold was 10% in the original spec; changed to 15% to be consistent
   with Section 7's cut-losses gate. This is a deliberate tightening.
4. Redeployment ROI (see C) exceeds hold-and-recover ROI by > 50%

**Mechanical Verdict rules** (deterministic, implemented in Python):

| Verdict | Rule |
| :--- | :--- |
| ABANDON_CANDIDATE | 2+ criteria triggered, OR C1 alone (no floor = immediate danger) |
| REVIEW | Exactly 1 criterion triggered (except C1) |
| HOLD | 0 criteria triggered |

When any mechanical criterion triggers, `loss_evaluator.py` writes the handoff table to
`loss-evaluator-flags.md` (see Data Contract below) and sets `abandon_flags` in
`ticker_profiles.json`. The LLM layer (exit-review workflow or morning briefing analyst)
then applies one qualitative check:

5. **Fundamental thesis validity** (LLM only, never evaluated by Python) — Is the decline
   structural (sector collapse, company-specific deterioration) or cyclical (market-wide
   pullback, temporary sentiment)? Structural → confirm exit. Cyclical → override to HOLD
   if support structure is intact.

**Data Contract — loss_evaluator.py → LLM handoff**

File: `loss-evaluator-flags.md` (follows project's file-based handoff pattern, same as
`exit-review-pre-analyst.md` feeds the LLM critic).

| Ticker | Days Stuck | Loss % | Trigger | Redeploy ROI | Est Break-Even | Mechanical Verdict | LLM Check Needed |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| USAR | 45d | -18.9% | C2, C4 | 14 days | 30+ days | ABANDON_CANDIDATE | YES — thesis validity |
| ARM | 13d | -11.2% | C4 | 6 days | 8-12 days | REVIEW | YES — thesis validity |
| CLF | 8d | -9.9% | — | — | 8-12 days | HOLD | NO |

- **Trigger**: Which mechanical criteria (C1-C4) fired; `—` if none
- **Mechanical Verdict**: Per decision rules above
- **LLM Check Needed**: YES when verdict is ABANDON_CANDIDATE or REVIEW; NO otherwise
- LLM persona reads this table only — never reads portfolio.json/identity.md/memory.md for abandon decisions

**C. Redeployment ROI Calculator (Gap 6.3)**
Compare: "Hold and wait for recovery" vs "Sell at loss and redeploy to best cycler"

```
### Redeployment Analysis — USAR
| Scenario | Action | Expected Outcome | Timeline |
| :--- | :--- | :--- | :--- |
| Hold | Wait for recovery to $21.57 | +$0 (break even) | 30+ days |
| Redeploy | Sell at $17.50 (-$61.05 loss) | | |
| | Deploy $263 to CLSK pool | +$15.78 per 3.5d cycle | |
| | After 4 cycles (14 days) | +$63.12 recovered | 14 days |
| | **Net after 14 days** | **+$2.07 (loss recovered)** | **14 days** |
| | **Net after 30 days** | **+$68.75** | **30 days** |
```

When redeployment recovers the loss faster than holding, flag the position.

**D. Capital Trap Alerting (Gap 6.4)**
Auto-flag in morning briefing:
```
### Capital Trap Alert
| Ticker | Days Stuck | Loss | Est. Recovery | Redeploy Recovery | Verdict |
| :--- | :--- | :--- | :--- | :--- | :--- |
| USAR | 45d | -18.9% | 30+ days | 14 days | REDEPLOY |
| ARM | 13d | -11.2% | 8-12 days | 6 days | REVIEW |
```

---

### 6. Reserve Utilization Rate (Gap 4.1)

**Problem:** Don't know how often reserves actually fire.

**Solution:** From trade_history.json, compute:
```
### Reserve Utilization
| Metric | Value |
| :--- | :--- |
| Total Reserve Orders (all time) | 42 |
| Reserve Orders Filled | 3 (7.1%) |
| Reserve Capital Committed | $6,300 |
| Reserve Capital Utilized | $448 |
| Idle Reserve Capital | $5,852 (93%) |
```

If utilization is <10%, consider reducing reserve allocation or using conditional deployment (Phase 5).

---

### 7. Deep Dive vs Cut Losses Threshold (Gap 4.4)

**Problem:** At what point does deploying reserves become irrational?

**Solution:** Define mathematical threshold:
- Compute: if all reserves deploy, what is the new break-even price?
- If break-even price is still > 15% above current price after full reserve deployment → reserves can't rescue the position → cut losses
- If break-even price is within 8% of current price → reserves are meaningful → deploy

```
### Reserve Effectiveness — CLF (if all reserves deployed)
| Metric | Active Only | With Reserves |
| :--- | :--- | :--- |
| Shares | 47 | 58 |
| Avg Cost | $9.39 | $9.08 |
| Break-Even | $9.39 | $9.08 |
| Distance to Break-Even | +11.0% | +7.3% |
| Reserve Impact | — | -3.3% improvement |
| Verdict | — | DEPLOY (meaningful improvement) |
```

---

### 8. Velocity/Momentum Filter (Gap 2.3)

**Problem:** A stock dropping 3%/day toward B1 will likely overshoot. A stock drifting slowly is more likely to hold.

**Solution:** Add to `fill_probability.py`:
- Compute 3-day rate of change (ROC)
- If ROC < -2%/day toward a buy level → high cascade probability → expect B2-B3 fills
- If ROC > -0.5%/day → slow approach → B1 likely to hold

Flag in morning briefing: "CLSK approaching B1 at -2.3%/day — cascade to B2/B3 likely."

---

## Output: Per-Ticker Strategy Profile

All Phase 4 analysis consolidates into `ticker_profiles.json`:

```json
{
  "CLSK": {
    "optimal_target_pct": 4.0,
    "optimal_bullet_count": 3,
    "avg_pullback_depth_pct": 7.2,
    "b1_fill_rate_pct": 85,
    "avg_cycle_days": 2.1,
    "capital_velocity_per_day": 1.96,
    "reserve_utilization_pct": 5,
    "abandon_threshold_pct": -25,
    "abandon_flags": [],
    "deployment_status": null,
    "current_phase": "PULLBACK",
    "last_updated": "2026-03-15"
  }
}
```

- `abandon_flags`: array of triggered criterion codes (e.g., `["C2", "C4"]`). Empty = no flags.
  Populated by `loss_evaluator.py` (Phase 4).
- `deployment_status`: string from `deployment_advisor.py`. Null in Phase 4 output; populated
  by Phase 5. See Phase 5 Section 4 for enum values.

This file becomes the input for `bullet_recommender.py`, `sell_target_calculator.py`, and `deployment_advisor.py` — replacing hardcoded defaults with per-ticker optimized values.

---

## Implementation Order

1. `tools/pullback_profiler.py` — depth distribution per ticker
2. Bullet count optimization — extend target_optimizer.py
3. Averaging efficiency analysis — from trade_history.json
4. `tools/loss_evaluator.py` — break-even, abandon criteria (C1-C4 mechanical flags), redeployment ROI, writes loss-evaluator-flags.md and populates abandon_flags in ticker_profiles.json
5. Adaptive sell target logic — extend sell_target_calculator.py
6. Reserve utilization + deep dive threshold calculations
7. Velocity/momentum filter — extend fill_probability.py
8. `ticker_profiles.json` generation — consolidate all outputs
9. Integration — update bullet_recommender, sell_target_calculator, morning briefing to read profiles

## Estimated Effort
- pullback_profiler.py: ~200 lines, 1 session
- Bullet count optimization: ~100 lines, 0.5 session
- loss_evaluator.py: ~300 lines, 1.5 sessions
- Adaptive sell target extension: ~100 lines, 0.5 session
- Reserve analysis: ~100 lines, 0.5 session
- Momentum filter extension: ~50 lines, 0.5 session
- Profile generation + integration: ~150 lines, 1 session
- Testing across all tickers: 1 session
- **Total: ~6.5 sessions**

## Success Criteria
- [ ] Pullback depth distribution computed for all active tickers
- [ ] Optimal bullet count varies by ticker (proving 5-for-all is suboptimal for some)
- [ ] Loss evaluator produces actionable redeployment recommendations
- [ ] Adaptive sell targets differ from static 6% for tickers with sufficient history
- [ ] ticker_profiles.json generated and consumed by bullet_recommender and sell_target_calculator
- [ ] At least 1 position identified as capital trap with quantified redeployment benefit
- [ ] Reserve utilization rate measured — confirms or contradicts $300 reserve allocation
- [ ] loss_evaluator.py produces loss-evaluator-flags.md with correct Mechanical Verdict per decision rules; abandon_flags populated in ticker_profiles.json
