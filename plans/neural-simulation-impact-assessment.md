# Honest Impact Assessment: Neural Network Simulations

**Date**: 2026-04-02 (Thursday)
**Purpose**: Evaluate whether the 4 simulation types we built today are actually improving the trading system or adding complexity without proportional value.

---

## 1. What We Built (4 sweep types)

| Sweep | Tool | Output File | Combos | Runtime (8 workers) |
| :--- | :--- | :--- | :--- | :--- |
| Support (threshold + execution + level filters) | `support_parameter_sweeper.py` | `support_sweep_results.json` + `sweep_support_levels.json` | 30 + 144 + 100 | ~25 + 15 + 30 min |
| Resistance sell | `resistance_parameter_sweeper.py` | `resistance_sweep_results.json` | 54 | ~35 min |
| Bounce sell | `bounce_parameter_sweeper.py` | `bounce_sweep_results.json` | 54 | ~50 min |
| Entry gates | `entry_parameter_sweeper.py` | `entry_sweep_results.json` | 486 | ~190 min |

**Total weekly sweep time**: ~345 min (~5.75 hours) with 8 workers. The weekly cron currently only runs the support sweep.

---

## 2. What the Data Actually Shows

### Resistance Sweep Results
- **22/30 tickers**: resistance beats flat
- **Actual live impact**: 4 tickers adjusted (ACHR $6.99→$7.97, BBAI $3.91→$4.64, CIFR $15.80→$16.55, IONQ $47.98→$49.10)
- **But**: CLSK's resistance target was LOWER ($9.47 vs $10.07 flat) — resistance can reduce upside too

### Bounce Sweep Results
- **6/30 tickers**: bounce beats both flat AND resistance
- **Actual live impact**: Zero so far. BBAI was a bounce winner but bounce failed live (no qualifying levels from current data), fell back to resistance
- **Concern**: Bounce profiles require approach events with sufficient held events at specific levels. In practice, many tickers don't have enough data for confident bounce targets

### Entry Sweep Results
- **14/30 tickers**: benefited from recency-weighted offsets (decay 60 or 90 days)
- **9/30 tickers**: benefited from post-break cooldown (2-5 days)
- **0/30 tickers**: benefited from regime gates, VIX gates, velocity gates, or regime-aware offsets
- **Actual live impact on entry gates**: Decay-weighted offsets now active for 14 tickers (buy prices adapt to recent wicks). Cooldown active for 9 tickers. The share count changes (STIM 225→53, LUNR 12→4, NU 11→3) are from pool/bullet sizing (Stage 2), NOT from entry gates — they're coincidental with the same daily analyzer run

### Level Filter Results
- **STIM**: confirmed `zone_filter=active` (skip Reserve), `min_hold_rate=15` (baseline)
- **Note**: `sweep_support_levels.json` currently only contains STIM (file was overwritten during single-ticker runs). The full 29-ticker level filter results from the earlier sweep were lost. The file needs a full re-sweep to restore all ticker data.
- **Impact**: Cannot assess at scale — only STIM's result is available. The one data point confirmed the defaults.

---

## 3. Honest Concerns

### 3.1 Overfitting Risk
We sweep 486 entry combos × 4 periods on the SAME historical data. With this many combinations, some will show improvement by statistical chance. The 4-period composite scoring reduces this but doesn't eliminate it.

**No cross-validation**: The resistance, bounce, and entry sweeps have NO train/test split. The support sweep has `--split` but we never use it for the newer sweeps. We're selecting the best combo from in-sample data and assuming it generalizes.

### 3.2 Complexity vs Marginal Gain
| What | Lines of Code | Actual Unique Value |
| :--- | :--- | :--- |
| Resistance simulation | ~250 (sweeper) + ~50 (backtest) + ~40 (wiring) | 4 tickers with higher sell targets |
| Bounce simulation | ~250 (sweeper) + ~150 (analyzer) + ~55 (backtest) + ~25 (wiring) | 0 tickers with live bounce targets (all fell through) |
| Entry gates | ~220 (sweeper) + ~45 (wick analyzer) + ~35 (backtest) + ~35 (wiring) | 14 tickers with decay offsets, 10 with cooldown |
| Level filters | ~100 (stage 3) + ~30 (wiring) | Confirmed defaults — no unique findings |

Total: ~1,285 lines of new code. The bounce simulation has produced **zero live impact** so far.

### 3.3 Regime Gates Were Worthless
We built ~100 lines of regime-aware entry gates (per-level Risk-Off hold rates, per-ticker VIX thresholds, approach velocity filtering). The sweep found **0/30 tickers** benefited from ANY of these. The existing hardcoded 15% Risk-Off gate is sufficient. This code is dead weight.

### 3.4 Data Freshness Problem
We now have 4 sweep result files that need periodic re-runs. The weekly cron only runs support sweep + watchlist profiles. Resistance, bounce, and entry sweeps are not automated. As market conditions change, these results go stale.

### 3.5 Fallback Chain Complexity
`compute_recommended_sell()` now has a multi-step fallback: try winner strategy by composite order → try second strategy → neural % → default 6%. This replaced a simple 3-line function. When it works, it's smarter. When it breaks (like BBAI bounce failing live), the fallback behavior is hard to predict.

---

## 4. What IS Working Well

### 4.1 Resistance Sell Targets — Clear Win
4 tickers now have scientifically-grounded sell targets instead of arbitrary percentages. ACHR went from $6.99 (7% flat) to $7.97 (22.1% at a 50% rejection resistance level). This is real alpha — the stock historically reverses at $7.97, so that's where we should sell.

### 4.2 Recency-Weighted Offsets — Subtle but Correct
14 tickers now adapt their buy prices to recent wick behavior instead of using 13-month averages. This is directionally correct — a stock that's been bouncing tighter recently should have tighter buy prices.

### 4.3 Pool Sizing — Working
The neural watchlist sweeper's Stage 2 produces per-ticker pool sizes ($200-$500) and bullet counts (3/5/7) that flow through to all consumers. STIM got $500 pool instead of $300, with 7 bullets instead of 5.

### 4.4 Post-Break Cooldown — Smart Protection
9 tickers have learned cooldown periods after level breaks. This prevents cascade losses where A1 breaks and A2 immediately fills and also breaks.

### 4.5 Progress Logging — Operational Improvement
All sweeps now show combo progress, per-ticker timing, quality metrics, and error counts. You can tell if a sweep is working or hung.

---

## 5. Recommendations

### 5.1 Keep
- **Resistance simulation** — clear value, 4 tickers adjusted
- **Recency-weighted offsets** — directionally correct
- **Post-break cooldown** — cascade protection
- **Pool sizing** — working, per-ticker optimization

### 5.2 Evaluate
- **Bounce simulation** — zero live impact so far. Give it time (needs fills at specific levels to test). But if bounce continues to fall through to resistance for every ticker, consider deprecating.

### 5.3 Remove or Disable
- **Regime-aware entry gates** — 0/30 value. The config fields exist but should stay at defaults (0/False). Consider removing the sweep grid dimensions for `riskoff_min_hold_rate`, `regime_aware_offset`, `per_ticker_vix_gate`, `max_approach_velocity` to reduce the 486-combo grid to 9 combos (3 decay × 3 cooldown = 9). This would cut the entry sweep from 190 min to ~4 min.

### 5.4 Add Cross-Validation
All sweeps should have a `--split` option that trains on the first 70% of days and validates on the last 30%. This catches overfitting. The support sweep already has this but it's not used for resistance/bounce/entry.

### 5.5 Automate
Add resistance, bounce, and entry sweeps to the weekly cron. Currently only support + watchlist sweeps are automated. Without automation, results go stale.

---

## 6. Bottom Line

**Are we going in the right direction?** Yes, with caveats.

The resistance simulation is a clear win — selling at historically-validated price levels instead of arbitrary percentages is fundamentally better. Recency-weighted offsets and post-break cooldown are smart incremental improvements.

But we built significant complexity (bounce simulation, regime gates) that hasn't produced live value yet. The system went from a simple `avg_cost × 1.06` sell target to a multi-layer fallback chain across 4 sweep files. Each layer adds code that can break, data that goes stale, and edge cases we discover in production (BBAI bounce failing, RDW notification spam, CLSK resistance lowering the target).

**The honest test**: Run the full system for 2-4 weeks and compare actual P/L against what the flat 6% approach would have produced. If the resistance/bounce/entry-optimized targets produce measurably better returns, the complexity is justified. If returns are similar, simplify back.
