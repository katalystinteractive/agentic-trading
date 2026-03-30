# Analysis: Training the Neural Network with Historical Data

**Date**: 2026-03-30 (Monday, 8:10 AM local / 1:10 AM ET)
**Purpose**: The neural network is undertrained (27 trades, 19/40 weights unchanged). Analyze how to use existing and obtainable historical data to train it properly before relying on weekly live accumulation.

**Honesty note**: Every claim labeled FACT (verified) or PROPOSED.

---

## 1. Current Training Data Problem

### 1.1 What we have (FACT — verified)

| Data source | Volume | Problem |
| :--- | :--- | :--- |
| Synapse weights | Trained on 27 trades | Need 100+ for convergence. 19/40 weights unchanged. |
| Dip validation | 2.1 trades/ticker avg | Need 20+ per ticker. 9/19 overfit. |
| Support candidates | 0/30 cross-validated | Single 10-month window, no out-of-sample testing |
| Watchlist profiles | 27 tickers, multi-period | Best data — but only covers current watchlist |

### 1.2 Why weekly live accumulation is too slow

**FACT**: The dip strategy fires on ~20% of trading days (12 of 60 signal days). At 1-3 trades per signal day, that's ~2-5 trades per week. To reach 100 trades for weight convergence: 20-50 weeks (5-12 months).

**FACT**: The support strategy fires more often (~1 trade per ticker per week on average from the backtests), but we have 27 tickers: ~27 trades/week. To reach 100 per ticker: ~4 weeks. Better, but still slow.

---

## 2. Historical Data Available (FACT — verified)

### 2.1 yfinance data limits

| Interval | Max lookback | Current use | Trade potential |
| :--- | :--- | :--- | :--- |
| 5-minute | 60 days | Dip sweeper, dip backtester | ~12 signal days × 5 tickers = ~60 trades |
| 1-hour | 730 days (~2 years) | NOT USED | Could extend dip training to ~240 signal days × 20+ tickers = ~1,000+ trades |
| Daily | Unlimited (30+ years) | Support backtester | Already used — 70 tickers × 10 months = ~2,400 trades |

### 2.2 Existing backtest data on disk

**FACT**: `data/backtest/candidate-gate/` has 68 tickers with `trades.json` files (66 with actual trade data — AR and USAR have 0 trades):
- `trades.json` — every buy/sell with P/L, days held, tier, zone, regime, exit reason
- `equity_curve.json` — daily portfolio snapshots
- `price_data.pkl` — 13-month OHLCV for reproducibility
- `regime_data.json` — daily VIX + index regime classification

**FACT**: CIFR alone has 92 trades (56 buy, 36 sell). Across 68 tickers: **3,428 total trades** on disk (avg 50.4/ticker). Buy trades have: `ticker, side, date, price, shares, zone, tier, avg_cost, regime`. Sell trades have: `ticker, side, date, price, shares, pnl_pct, pnl_dollars, exit_reason, days_held, avg_cost, regime`. Fields differ between buy and sell — not all fields on every trade.

### 2.3 What's NOT available

- No tick/order-book data (can't learn microstructure)
- 5-min bars capped at 60 days (can't train intraday patterns beyond 3 months)
- No intraday VIX (regime is daily-level only)

---

## 3. Three Training Approaches

### 3.1 Approach A: Train weights from existing backtest trades (IMMEDIATE)

**What**: The 70 tickers in `candidate-gate/` already have `trades.json` with complete trade outcomes. Extract all trades, add `fired_inputs` retroactively, and run `weight_learner.py` on them.

**How**:
```
For each ticker in candidate-gate/:
  Load trades.json
  For each sell trade (has pnl_dollars, exit_reason):
    Construct fired_inputs from trade context:
      - profit_gate: pnl_pct at exit
      - support_gate: distance from entry to support level
    Append to training set

Run weight_learner.py on the full training set (~500-2000 trades)
```

**Training volume**: ~3,428 trades from 68 tickers (verified on disk) — well above the 100+ needed for weight convergence.

**Limitation**: The `fired_inputs` would be synthetic (reconstructed from trade data, not recorded during live evaluation). The inputs available are: pnl_pct, exit_reason, days_held, regime, tier, zone. These are EXIT-TIME features, not ENTRY-TIME features. For weight learning to be meaningful, we need ENTRY-TIME features (what the network saw when it decided to buy).

**Feasibility**: MODERATE. Entry-time features aren't in the existing trade records. We'd need to reconstruct them from price_data.pkl (compute RSI/MACD/support_distance at the entry date). This is doable but adds complexity.

**Estimated effort**: ~100 lines (trade extractor + fired_inputs reconstruction)
**Estimated time**: Compute ~5 minutes, coding ~1 hour

### 3.2 Approach B: Extend dip training to 1-hour bars (730 days)

**What**: The dip strategy currently trains on 60 days of 5-min bars (yfinance limit). Switch to 1-hour bars for 730 days of lookback — 12x more data.

**How**:
```
Download 1-hour bars for all tickers: yf.download(tickers, period="730d", interval="1h")
Replay through neural dip evaluator (same build_first_hour_graph + build_decision_graph)
Adjust time windows: first-hour = bars 0-1, decision = bars 1-2 (instead of 0-12 and 0-18)
Sweep parameters on 730 days instead of 60
```

**Training volume**: ESTIMATE — signal rate at 1-hour resolution is UNKNOWN and likely different from the 20% observed at 5-min. With 1-hour bars, the first bar (9:30-10:30) gives one open-to-close data point for dip magnitude, vs 12 separate 5-min snapshots. The breadth pattern may fire at a different rate. Must measure empirically before estimating trade volume.

**Limitation**: 1-hour bars have lower granularity — can't detect exact first-hour dip timing as precisely as 5-min. The "dip in first hour then bounce by 11 AM" pattern needs adaptation for hourly resolution. The first bar covers the entire first hour, so the dip IS the first bar's open-to-close.

**FACT**: `neural_dip_backtester.py` already imports `build_first_hour_graph` and `build_decision_graph`. These use `_extract_open()` and `_extract_price_at()` which use actual UTC timestamps, NOT bar indices. They are genuinely interval-agnostic. `_extract_first_hour_low()` filters by time range (9:30-10:30 ET), not bar position.

**What actually needs changing**: NOT bar index references (those use timestamps). Instead: (1) download parameter `interval="5m"` → configurable in `neural_dip_backtester.py` line 48, (2) cache path from `intraday_5min_cache.pkl` → interval-aware naming, (3) period from `60d` → `730d` for 1-hour.

**Feasibility**: HIGH. The evaluator functions are already interval-agnostic. Only the backtester's download and cache logic needs updating.

**Estimated effort**: ~50 lines (download config + cache path + period adjustment)
**Estimated time**: Download ~2 minutes for 21 tickers, compute ~30 minutes for full sweep

### 3.3 Approach C: Re-run support sweep with full multi-period + cross-validation (MOST IMPACTFUL)

**What**: The support candidates were swept WITHOUT multi-period scoring and WITHOUT cross-validation. Re-run the full discoverer with the multi-period sweep code that's now in `support_parameter_sweeper.py`.

**How**:
```
python3 tools/neural_support_discoverer.py --exec-top 10 --workers 8
```

This uses `sweep_threshold()` which now runs 4 periods (12/6/3/1 months) and calls `compute_composite()`. The output will have `composite` scores and `periods` data.

**Training volume**: Same 68 tickers × 30 combos × 4 periods = 8,160 simulations. Each produces ~30 trades = ~240,000 trade observations for weight learning.

**Limitation**: Runtime is UNMEASURED for multi-period mode. Prior single-period run was 7 min with 8 workers + wick cache. Multi-period (4x simulations) is estimated at ~28 min but must be benchmarked.

**FACT**: The watchlist profiles (27 tickers) ALREADY have multi-period data. The support candidates (30 tickers) do NOT — they're from the old single-period run.

**Feasibility**: HIGH. The code exists. Just needs to be re-run.

**Estimated effort**: 0 lines (just run the existing tool)
**Estimated time**: ~45 minutes with 8 workers

---

## 4. Recommended Training Plan

### Phase 1: Re-run support discoverer with multi-period (TODAY)

```bash
python3 tools/neural_support_discoverer.py --exec-top 10 --workers 8
```

This populates `composite` and `periods` for all 30 support candidates. The reason chains in the order adjuster immediately become richer.

**Outcome**: Support candidates with cross-validated, multi-period-scored profiles.

### Phase 2: Train synapse weights from existing backtest trades (THIS WEEK)

Build a trade extractor that:
1. Reads `trades.json` from all 70 tickers in `candidate-gate/`
2. For each trade, reconstructs entry-time features from `price_data.pkl`
3. Formats as `fired_inputs` for `weight_learner.py`
4. Trains on ~500-2,000 trades

**Outcome**: Synapse weights trained on 500+ trades instead of 27. Weights will differentiate meaningfully between reliable and unreliable signals.

### Phase 3: Extend dip training to 1-hour 730-day lookback (THIS WEEK)

Modify `neural_dip_backtester.py` to support `--interval 1h` for 730-day lookback:
- Download 1-hour bars: `yf.download(tickers, period="730d", interval="1h")`
- Adjust bar indices for hourly resolution
- Run full parameter sweep on 730 days
- Re-train dip synapse weights on ~730 trades

**Outcome**: Dip profiles based on 730 days of data (vs 60). Cross-validation on ~240 validation days (vs 5). Overfitting detection becomes statistically meaningful.

### Phase 4: Ongoing weekly accumulation (AUTOMATIC)

The crons are already set. Each Saturday:
1. `weekly_reoptimize.py` re-sweeps with latest data
2. `neural_watchlist_sweeper.py` updates watchlist profiles
3. Weight learner trains on accumulated trade outcomes

Each week adds ~27 support trades + ~2-5 dip trades to the training set.

---

## 5. Expected Impact

| Metric | Current | After Phase 1-3 |
| :--- | :--- | :--- |
| Synapse weight training trades | 27 | ~3,428 (verified on disk) |
| Weights at 1.0 (unchanged) | 19/40 | Estimated <5/40 |
| Dip validation trades/ticker | 2.1 | UNKNOWN (depends on 1h signal rate, must measure) |
| Dip overfit rate | 9/19 (47%) | Estimated <20% |
| Support cross-validation | 0/30 | 30/30 |
| Support multi-period scoring | 0/30 | 30/30 |
| Dip training window | 60 days | 730 days |
| Dip parameter confidence | Low | Moderate-High |

---

## 6. Files Needed

| Phase | File | Action | Lines |
| :--- | :--- | :--- | :--- |
| 1 | (none — just re-run existing tool) | Run `neural_support_discoverer.py` | 0 |
| 2 | `tools/historical_trade_trainer.py` | NEW — extract trades, reconstruct inputs, train | ~100 |
| 3 | `tools/neural_dip_backtester.py` | MODIFY — add `--interval 1h` support | ~50 |
| 3 | `tools/parameter_sweeper.py` | MODIFY — 1-hour bar index constants | ~20 |
| **Total** | | | **~170** |

---

## 7. What This Does NOT Solve

1. **Per-ticker weight learning** — Even with 2,000 trades, that's ~29 per ticker (70 tickers). Per-ticker weights need ~100+ each. Cluster-level weights (shared across similar tickers) are more feasible.

2. **Intraday regime** — All regime data is daily-level. The neural network can't learn "buy dips during morning selloffs in Risk-On" vs "avoid dips during morning selloffs in Risk-Off" with current data granularity.

3. **New ticker cold start** — A ticker with zero historical trades gets cluster defaults. This is the intended behavior — the cluster provides the prior, live trades refine it.
