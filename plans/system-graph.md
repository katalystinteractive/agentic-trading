# System Graph — Agentic Trading Architecture

**Version**: 1.1 | **Date**: 2026-04-08 | **Living Document**

---

## Node Types

- **TOOL** — Python script (120 total)
- **DATA** — JSON/MD/PKL file produced and consumed
- **CRON** — Automated scheduled job
- **WORKFLOW** — Multi-phase orchestrated pipeline (13 total)
- **USER** — Manual human action

---

## 1. Saturday Pipeline (Weekly Optimization)

```
[CRON 09:00] universe_screener.py
    → WRITES: data/universe_screen_cache.json (1,600 passers)

[CRON 10:00] weekly_reoptimize.py (SINGLE ORCHESTRATOR)
    │
    ├─ Step 0: wick_offset_analyzer (in-process refresh)
    │   → READS: yfinance 13-month data for all tracked non-winding tickers
    │   → WRITES: tickers/*/wick_analysis.md (refreshed support levels)
    │
    ├─ Step 1: parameter_sweeper.py (dip sweep)
    │   → WRITES: data/sweep_results.json (stats.composite added)
    │
    ├─ Step 2: support_parameter_sweeper.py --stage both (Stage 1+2)
    │   → WRITES: data/support_sweep_results.json
    │
    ├─ Step 3: ticker_clusterer.py
    │   → WRITES: data/ticker_profiles.json
    │
    ├─ Step 4: weight_learner.py
    │   → WRITES: data/synapse_weights.json
    │
    ├─ Step 5: overfitting + confidence checks
    │
    ├─ Step 6: candidate sweep (Stage 1 for top 15 universe passers)
    │   → READS: data/universe_screen_cache.json
    │   → WRITES: data/support_sweep_results.json (merged)
    │
    ├─ Step 7: resistance_parameter_sweeper.py --workers 8
    │   → READS: data/support_sweep_results.json (base params)
    │   → WRITES: data/resistance_sweep_results.json
    │
    ├─ Step 8: bounce_parameter_sweeper.py --workers 8
    │   → READS: data/support_sweep_results.json (base params)
    │   → WRITES: data/bounce_sweep_results.json
    │
    ├─ Step 9: entry_parameter_sweeper.py --workers 8
    │   → READS: data/support_sweep_results.json (base params)
    │   → WRITES: data/entry_sweep_results.json
    │
    ├─ Step 10: support_parameter_sweeper.py --stage slippage --workers 8
    │   → READS: data/support_sweep_results.json (base params)
    │   → WRITES: data/support_sweep_results.json (slippage_params merged)
    │
    ├─ Step 10b: support_parameter_sweeper.py --stage regime_exit --workers 8
    │   → WRITES: data/regime_exit_sweep_results.json
    │
    └─ Step 11: watchlist_tournament.py
        → READS: ALL 6 sweep result files
        → READS: portfolio.json (tracked tickers)
        → WRITES: data/tournament_results.json
        → WRITES: portfolio.json (winding_down flags, watchlist changes)
        → SENDS: email via notify.py

[CRON 15:30] watchlist_tournament.py (SAFETY RE-RUN, idempotent)
    → Skips if already ran today with fresh data
```

### Ticker Pool for Sweeps (Steps 7-10)
```
ALL tracked tickers (positions + watchlist with sweep data)
  + top N challengers by composite (N = half of tracked, min 10)
  = ~37 tickers currently
```

---

## 2. Daily Pipeline (Mon-Fri Trading Days)

```
[CRON 15:30] neural_support_evaluator.py
    → WRITES: data/support_eval.log

[CRON 16:30-23:00 every 5 min] order_proximity_monitor.py
    → READS: portfolio.json (pending orders)
    → READS: data/entry_sweep_results.json (VIX gate, exempted for FILLED?)
    → WRITES: data/proximity_alerts_state.json
    → SENDS: email on APPROACHING / IMMINENT / FILLED?
    → AUTO-FILL: on FILLED?, calls cmd_fill → sell targets → next bullet
    → SENDS: cascade email (FILL RECORDED + sell target + next bullet action)

[CRON 17:30] neural_dip_evaluator.py --phase first_hour
    → READS: data/ticker_profiles.json, data/synapse_weights.json
    → SENDS: email if signal

[CRON 18:00] neural_dip_evaluator.py --phase decision
    → SENDS: email with decision

[CRON 22:45] neural_dip_evaluator.py --phase eod_check
    → SENDS: email with EOD verification
```

### Manual Daily Tools
```
[USER] daily_analyzer.py
    → READS: portfolio.json, cooldown.json
    → CALLS: portfolio_status.py, bullet_recommender.py, watchlist_fitness.py
    → CALLS: broker_reconciliation.py (Part 7 — sweep-driven sell targets)
    → Shows: fills, deployment recs, order adjustments, fitness verdicts

[USER] bullet_recommender.py TICKER
    → READS: tickers/TICKER/wick_analysis.md (cached)
    → READS: portfolio.json
    → CHECKS: winding_down flag → skips if true
    → CHECKS: earnings_gate → warns if near earnings
    → Falls back to daily_range_analyzer if 0 levels
    → OUTPUT: Level Map with >> Next recommendation

[USER] sell_target_calculator.py TICKER
    → READS: portfolio.json, resistance_sweep_results.json
    → COMPUTES: math targets (4.5/6/7.5%) + PA/HVN resistance
    → OUTPUT: Sell target table

[USER] neural_order_adjuster.py
    → READS: portfolio.json, resistance_sweep_results.json, bounce_sweep_results.json
    → CALLS: compute_recommended_sell() with hist data
    → OUTPUT: Sell order adjustment recommendations
```

---

## 3. Sell Target Chain (Critical Path)

```
SWEEP DATA                          LIVE COMPUTATION
─────────────                       ─────────────────
support_sweep_results.json
  → sell_default % ──────────────┐
resistance_sweep_results.json    │
  → resistance strategy ─────────┤
bounce_sweep_results.json        │
  → bounce strategy ─────────────┤
                                 ↓
                    broker_reconciliation.py
                    compute_recommended_sell()
                    ┌─────────────────────────────┐
                    │ Priority chain:              │
                    │ 1. target_exit (manual)       │
                    │ 2. Best composite strategy    │
                    │    (resistance > bounce)      │
                    │ 3. Neural % (from sweep)      │
                    │ 4. Default 6%                 │
                    └─────────────────────────────┘
                                 │
                    ┌────────────┼────────────┐
                    ↓            ↓            ↓
            daily_analyzer  neural_order   bullet_
            (Part 7)        _adjuster     recommender
                                          (Sweep Sell
                                           Target row)
```

---

## 4. Buy Entry Chain (Critical Path)

```
SWEEP DATA                          LIVE COMPUTATION
─────────────                       ─────────────────
sweep_support_levels.json
  → min_hold_rate, touch_freq ───┐
  → zone_filter, skip_dormant    │
entry_sweep_results.json         │
  → offset_decay_half_life ──────┤
  → post_break_cooldown          │
                                 ↓
                    wick_offset_analyzer.py
                    analyze_stock_data()
                    ┌─────────────────────────────┐
                    │ Applies:                     │
                    │ • Level filters from sweep   │
                    │ • Recency-weighted offsets    │
                    │ • Zone classification         │
                    │ • Tier assignment             │
                    └─────────────────────────────┘
                                 │
                                 ↓
                    bullet_recommender.py
                    ┌─────────────────────────────┐
                    │ • Pool sizing from sweep     │
                    │ • Bullet counts from sweep   │
                    │ • Strategy type gate          │
                    │   (SUR → bullets, DAI → dip) │
                    │ • Winding_down check          │
                    │ • Earnings gate check         │
                    └─────────────────────────────┘
                                 │
                                 ↓
                         Level Map output
                         >> Next recommendation
```

---

## 5. Onboarding Chain

```
[TRIGGER: Tournament challenge OR manual onboard]
                    │
                    ↓
            batch_onboard.py
            ┌───────────────────────────┐
            │ Creates:                   │
            │ • tickers/TICKER/identity.md│
            │ • tickers/TICKER/memory.md  │
            │ • tickers/TICKER/wick_analysis.md │
            │ • tickers/TICKER/cycle_timing.json │
            │ Adds to: portfolio.json watchlist │
            └───────────────────────────┘
                    │
                    ↓
            run_post_onboard_sweeps()
            ┌───────────────────────────┐
            │ Strategy-aware:            │
            │                            │
            │ ALL tickers:               │
            │ • Support Stage 1+2        │
            │ • Entry sweep              │
            │ • Slippage sweep           │
            │                            │
            │ SURGICAL only (≥3 levels): │
            │ • Level filters (Stage 3)  │
            │ • Resistance sweep         │
            │ • Bounce sweep             │
            └───────────────────────────┘
                    │
                    ↓
            Ticker ready for daily_analyzer
            + bullet_recommender + tournament
```

---

## 6. Tournament Decision Chain

```
            watchlist_tournament.py
            ┌───────────────────────────────────┐
            │ READS: 5 sweep files              │
            │ READS: portfolio.json              │
            │                                    │
            │ RANKS: best-of composite per ticker│
            │ CLASSIFIES: SUR / DAI / UNK        │
            │ GATES:                              │
            │   • 20% beat margin for challenges  │
            │   • 3/week swap cap                 │
            │   • 4-week newcomer protection      │
            │   • Never force-sell positions       │
            │                                    │
            │ ACTIONS:                            │
            │   • ONBOARD → batch_onboard()       │
            │   • CHALLENGE → displace incumbent  │
            │   • WIND DOWN → set winding_down    │
            │   • DROP → remove watchlist + cleanup│
            │   • PROTECTED → <4 weeks, skip      │
            └───────────────────────────────────┘
```

---

## 7. Data File → Consumer Map

| Data File | Producers | Consumers | Freshness |
| :--- | :--- | :--- | :--- |
| portfolio.json | portfolio_manager, batch_onboard, tournament | 40+ tools | Real-time |
| support_sweep_results.json | support_sweeper, neural_watchlist_sweeper | resistance/bounce/entry/slippage sweepers, tournament, broker_recon | Weekly |
| resistance_sweep_results.json | resistance_sweeper | broker_recon, neural_order_adjuster, tournament | Weekly |
| bounce_sweep_results.json | bounce_sweeper | broker_recon, neural_order_adjuster, tournament | Weekly |
| entry_sweep_results.json | entry_sweeper | wick_offset_analyzer, order_proximity_monitor, tournament | Weekly |
| sweep_support_levels.json | support_sweeper Stage 3 | wick_offset_analyzer | Weekly |
| sweep_results.json (dip) | parameter_sweeper | tournament (via composite) | Weekly |
| neural_watchlist_profiles.json | neural_watchlist_sweeper | broker_recon, shared_utils.get_ticker_pool() | Weekly |
| ticker_profiles.json | ticker_clusterer | neural_dip_evaluator, broker_recon, sell_target_calc | Weekly |
| synapse_weights.json | weight_learner | neural_dip_evaluator | Weekly |
| tournament_results.json | watchlist_tournament | tournament (idempotency check) | Weekly |
| universe_screen_cache.json | universe_screener | step_candidate_sweep (weekly_reoptimize) | 3-day cache |
| tickers/*/wick_analysis.md | wick_offset_analyzer | bullet_recommender, shared_wick, strategy gate | Weekly (Step 0) + on demand |
| tickers/*/cycle_timing.json | cycle_timing_analyzer | surgical_filter, watchlist_fitness | On demand |

---

## 8. Identified Gaps (Disconnected / Missing Edges)

### 8.1 Trigger Gaps (Event → Action Not Automated)

| Event | Current | Should Be | Priority |
| :--- | :--- | :--- | :--- |
| Fill recorded → sell targets | ✅ Automated in portfolio_manager.py cmd_fill() | Already calls sell_target_calculator.analyze_ticker() | DONE |
| Fill recorded → audit bullets | Manual user action | Auto-show remaining bullets after fill | LOW |
| Position close → cleanup | Manual (leaves dead entries) | Auto-remove 0-share positions (**FIXED this session**) | ✅ DONE |
| Onboarding (CLI) → all sweeps | batch_onboard main() calls run_post_onboard_sweeps | Auto-triggered in CLI path | ✅ DONE |
| Tournament → onboard+sweep | Tournament execute_actions calls batch_onboard + run_post_onboard_sweeps | Fully automated with strategy_types | ✅ DONE |
| Earnings date → order pause | Manual check | Auto-pause pending buys near earnings | LOW |
| Risk-Off → order pause | Manual market context check | Auto-pause watchlist pending buys | LOW |
| Watchlist fitness REMOVE → drop | Manual action needed | Auto-trigger drop via watchlist_manager | MEDIUM |
| Wick refresh → level shift | Orphaned fills noted | Auto-flag when buy prices shift >2% | LOW |

### 8.2 Data Gaps (Produced But Not Consumed)

| Data | Producer | Missing Consumer | Impact |
| :--- | :--- | :--- | :--- |
| tickers/*/pullback_profile.json | pullback_profiler.py | No tool reads this | LOW — informational |
| tickers/*/bounce_analysis.json | bounce_analyzer.py | Only bounce_dashboard reads | LOW |
| data/baseline_support_results.json | Old baseline run | Orphaned — superseded by support_sweep_results | NONE — delete |
| data/reoptimize_history.json | weekly_reoptimize | Only weekly_reoptimize reads (confidence check) | OK — self-contained |
| cycle_history.json | cycle_grouper | post_sell_tracker reads | OK — connected |

### 8.3 Dead Code / Unused Tools

| Tool | Status | Evidence |
| :--- | :--- | :--- |
| morning_gatherer.py (v1) | Replaced by morning_gatherer_v2.py | Memory says "daily analyzer is primary" |
| alignment_checker.py | Dead — not in any pipeline | No imports, no workflow/cron references |
| loss_evaluator.py | Output orphaned | Tool is called by morning_gatherer but `loss-evaluator-flags.md` is never read by any tool |

**Note**: `graph_engine.py` and `graph_builder.py` are ACTIVE — imported by `neural_dip_evaluator.py` and `daily_analyzer.py` for dependency graph construction.

### 8.4 Methodology Gaps

| Gap | Description | Impact |
| :--- | :--- | :--- |
| Dip composite is crude | total_pnl / months, not multi-period weighted | DAI tickers have directional but imprecise scores |
| Backtest assumes perfect execution | Slippage/pullback/earnings gates added but defaults are 0 | Sweep scores may overstate live P/L |
| No portfolio-level simulation | Each ticker simulated independently with own $300 pool | Can't model capital constraints across 30 tickers |
| No cross-ticker correlation | Sector crash not modeled | Crypto tickers (CIFR/CLSK/MARA) could all fail together |

---

## 9. System Health Metrics

```
Tools: 121 Python scripts (+ portfolio_stress_test.py)
Data files: 553+ in data/, 1000+ in tickers/
Workflows: 13 (8 daily, 5 weekly/periodic)
Cron jobs: 7 (5 weekday, 2 Saturday + 1 safety re-run)
Sweep types: 6 (dip, support, resistance, bounce, entry, slippage)
Tracked tickers: 29 watchlist + positions
Swept tickers: 42 (25 tracked + 12 challengers + 5 extras)
Tournament pool: 42 tickers ranked weekly
```

---

---

## 10. User Action Completeness Audit

Every user-facing output must contain ALL information needed to act — no mental math, no cross-referencing.

| Output | Ticker | Price | Shares | Cost | Action | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Dip alert email** (notify.send_dip_alert) | ✅ | ✅ entry/target/stop | ✅ Shares | ✅ Cost | ✅ BUY | ✅ Complete |
| **Daily range section** (bullet_recommender) | ✅ | ✅ dip entry/target | ✅ Shares | ✅ Cost | ✅ Dip Buy | ✅ Complete |
| **Surgical bullets** (bullet_recommender) | ✅ | ✅ Buy At | ✅ Shares | ✅ ~Cost | ✅ >> Next | ✅ Complete |
| **Tournament report** (watchlist_tournament) | ✅ | ✅ Score | N/A | N/A | ✅ Action column | ✅ Complete |
| **Neural order adjuster** | ✅ | ✅ Current/Rec | ✅ Shares | N/A | ✅ RAISE/LOWER/OK | ✅ Complete |
| **Proximity alert email** (order_proximity_monitor) | ✅ | ✅ Order/Current | ✅ Shares | N/A | ✅ APPROACHING/IMMINENT | ✅ Complete |
| **Tournament ONBOARD/CHALLENGE** (watchlist_tournament) | ✅ | ✅ Score | ❌ No entry shares | ❌ No entry cost | ✅ Action | **GAP** — 2-step handoff |
| **Watchlist fitness verdicts** (watchlist_fitness) | ✅ | N/A | N/A | N/A | ❌ No actionable steps | **GAP** — verdict without instructions |
| **Sell target calculator** (sell_target_calculator) | ✅ | ✅ Price | ✅ Shares | ✅ Basis | ✅ Level | ✅ Complete |
| **Daily analyzer** (daily_analyzer) | ✅ | ✅ | ✅ (Part 7) | ✅ | ✅ | ✅ Complete (95%) |
| **Morning briefing** (morning-briefing.md) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ Complete |

### Gaps to Fix
1. ~~**Dip alert email**: Add shares field~~ — RESOLVED (shares param already implemented + caller passes it)
2. ~~**Daily range section**: Add shares + cost~~ — RESOLVED (pool_budget param + bullet_recommender passes half-Kelly)
3. **Tournament ONBOARD/CHALLENGE**: Two-step handoff — user must run bullet_recommender separately to see entry details. Add "run `bullet_recommender.py TICKER` for entry levels" note, or inline first bullet info.
4. **Watchlist fitness REMOVE/RESTRUCTURE verdicts**: Shows verdict but no actionable next steps (which orders to cancel, what to adjust). Add recommended action per verdict.

---

*This document should be updated when new tools, data files, or workflows are added.*
