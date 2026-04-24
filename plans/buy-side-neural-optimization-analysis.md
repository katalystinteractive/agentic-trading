# Analysis: Buy-Side Neural Network Optimization — IMPLEMENTED

**Date**: 2026-04-02 (Thursday)
**Status**: ALL 6 OPTIMIZATIONS IMPLEMENTED (commits ad459dc + 6b949e3)
**Purpose**: Documents 6 buy-side neural optimizations. Originally an analysis of opportunities; now reflects the implemented state.

---

## 1. What We Currently Optimize (FACT — verified)

### 1.1 Level filters (Stage 3 sweep)

**FACT**: `support_parameter_sweeper.py` Stage 3 (`sweep_levels()`) sweeps `min_hold_rate`, `min_touch_freq`, `skip_dormant`, `zone_filter` per ticker. Results in `data/sweep_support_levels.json`. Applied via `_load_level_filters()` in `wick_offset_analyzer.py` line 109.

**What it does**: Filters OUT levels not worth trading — e.g., "CIFR: Active zone only, skip Reserve."

**What it doesn't do**: Doesn't adjust HOW we enter at the remaining levels.

### 1.2 Pool sizing (Stage 2 sweep)

**FACT**: `support_parameter_sweeper.py` Stage 2 (`sweep_execution()`) sweeps `active_pool`, `reserve_pool`, `active_bullets_max`, `reserve_bullets_max`. Results in watchlist profiles via `neural_watchlist_sweeper.py`.

**What it does**: Determines capital allocation per ticker ($200-$500 pool, 3/5/7 bullets).

### 1.3 Sell targets (threshold sweep + resistance + bounce)

**FACT**: Three sell strategies are swept and compared. The winner determines sell price per ticker.

### 1.4 Wick offsets (statistical, NOT neural)

**FACT**: `wick_offset_analyzer.py` computes `recommended_buy` from `median_offset` of all historical approaches at each level. This is a simple median — NO recency weighting, NO regime conditioning, NO neural optimization.

**FACT** (updated): When `offset_decay_half_life > 0` (configurable), the offset is recency-weighted using exponential decay (lines 767-783). When `offset_decay_half_life = 0` (default), falls back to raw unweighted median. The sweep tool tests `[0, 60, 90]` day half-lives.

---

## 2. Optimizations (IMPLEMENTED)

### 2.1 Recency-Weighted Wick Offsets

**Current**: `recommended_buy = level_price * (1 + median_offset / 100)` where `median_offset` is the unweighted median of ALL historical approach offsets.

**Proposed**: Apply 90-day half-life decay to approach events before computing the median. Recent approaches get higher weight — if recent wicks are tighter (stock bouncing sooner), the buy price moves closer to support. If recent wicks are deeper (more volatile), the buy price moves further below.

**Why it matters**: Market behavior changes. A stock that wicked 5% below support 10 months ago but only 1% below in the last 3 months should have a tighter buy price reflecting current conditions.

**Data available**: `find_approach_events()` returns dated events with `offset_pct`. The decay infrastructure exists (`decay_half_life=90` in `SurgicalSimConfig`).

**Sweep parameters**:
```python
OFFSET_GRID = {
    "offset_decay_half_life": [30, 60, 90, 180],  # days
    "offset_use_decayed": [True, False],            # toggle vs raw median
}
```

### 2.2 Regime-Conditioned Entry

**Current**: The entry gate in `daily_analyzer.py` pauses ALL buys during Risk-Off. The backtest engine has `vix_risk_off` threshold AND an existing Risk-Off fill suppression at lines 440-444: during Risk-Off, only orders more than 15% below current price are allowed to fill (hardcoded 15% threshold). This is a partial regime gate but is binary and not per-ticker optimized.

**Proposed**: Learn per-ticker regime sensitivity. Some tickers' support levels hold reliably even in Risk-Off (low-beta, value stocks). Others break consistently in Risk-Off (high-beta, momentum stocks). The neural network can discover:
- "STIM $1.25 holds 80% in Risk-On but 40% in Risk-Off → skip in Risk-Off"
- "CLF $7.40 holds 65% in Risk-On AND 60% in Risk-Off → deploy regardless"

**Data available**: The backtest already tracks `regime` per trading day. Each approach event can be tagged with the regime at that date. Hold rates can be computed separately for Risk-On vs Risk-Off.

**Sweep parameters**:
```python
REGIME_ENTRY_GRID = {
    "riskoff_min_hold_rate": [30, 50, 70],     # minimum hold rate in Risk-Off to deploy
    "riskoff_skip_levels": [True, False],        # skip levels that break >50% in Risk-Off
    "regime_aware_offset": [True, False],        # use regime-specific wick offsets
}
```

### 2.3 Adaptive Offset by Regime

**Current**: One offset per level regardless of market conditions.

**Proposed**: Compute two offsets per level:
- `risk_on_offset`: median offset from approaches during Risk-On periods
- `risk_off_offset`: median offset from approaches during Risk-Off periods

Use the regime-appropriate offset at order placement time. In Risk-Off, wicks are typically deeper — buying with the Risk-Off offset means setting the limit lower (more likely to fill AND hold). In Risk-On, wicks are shallower — buying tighter captures more fills.

**Data available**: Each approach event has a date. Regime data is available per date in the backtest. The wick analyzer can split approaches by regime at computation time.

### 2.4 Post-Break Cooldown

**Current**: After level A1 breaks, A2 is immediately available. No delay between sequential level breaks.

**Proposed**: Learn per-ticker cooldown: "After A1 breaks, wait N days before deploying at A2." Some tickers cascade (A1 break immediately triggers A2 break), others stabilize after one break.

**Data available**: `cycle_timing_analyzer.py` computes cooldown recommendations from resistance-to-support cycles (how long after a sell until price returns to support). However, support-to-support cascade timing (how long after A1 breaks until A2 breaks) is NOT currently measured — this is new analysis that must be built. The approach event data from `find_approach_events()` contains the dates needed to measure cascade timing.

**Sweep parameters**:
```python
COOLDOWN_GRID = {
    "post_break_cooldown_days": [0, 1, 3, 5],   # days to wait after a level breaks
    "cascade_detection": [True, False],           # detect multi-level cascade patterns
}
```

### 2.5 VIX-Conditioned Deployment

**Current**: Binary Risk-Off gate at VIX >= 25 (from `SurgicalSimConfig.vix_risk_off`).

**Proposed**: Per-ticker VIX threshold. Some tickers tolerate VIX 30 (their levels still hold). Others break at VIX 22. The sweep learns the optimal VIX gate per ticker.

**Data available**: VIX is tracked per day in the backtest. Each approach can be tagged with the VIX level at that date.

**Sweep parameters**:
```python
VIX_GATE_GRID = {
    "per_ticker_vix_gate": [20, 25, 30, 35],    # max VIX to deploy at this ticker's levels
}
```

### 2.6 Approach Velocity Gate

**Current**: No consideration of how fast price is falling toward support.

**Proposed**: Measure the rate of decline in the N days before the approach. Fast crashes (>5% in 2 days) have different hold probability than slow grinds (2% over 10 days). The neural network can learn the optimal velocity filter per ticker.

**Data available**: Price data is available — the decline rate can be computed from the 5-day return before the approach start date.

**Sweep parameters**:
```python
VELOCITY_GRID = {
    "max_2d_decline_pct": [3, 5, 8, 999],    # skip approaches after >N% 2-day decline (999=no filter)
    "min_5d_decline_pct": [0, 1, 2],          # minimum decline to confirm real pullback (not noise)
}
```

---

## 3. Impact Assessment

| Optimization | Data Exists? | Backtest Change? | New Sweep Tool? | Estimated Impact |
| :--- | :--- | :--- | :--- | :--- |
| **Recency-weighted offsets** | YES | DONE — `wick_offset_analyzer.py` lines 767-783 | DONE — `entry_parameter_sweeper.py` | HIGH |
| **Regime-conditioned entry** | YES | DONE — `backtest_engine.py` lines 447-458 | DONE — sweeps `riskoff_min_hold_rate` | HIGH |
| **Adaptive offset by regime** | YES | DONE — `wick_offset_analyzer.py` lines 806-815 | DONE — sweeps `regime_aware_offset` | MEDIUM |
| **Post-break cooldown** | YES | DONE — `backtest_engine.py` lines 475-487 | DONE — sweeps `post_break_cooldown` | MEDIUM |
| **VIX-conditioned deployment** | YES | DONE — `backtest_engine.py` lines 460-463 | DONE — sweeps `per_ticker_vix_gate` | MEDIUM |
| **Approach velocity gate** | YES | DONE — `backtest_engine.py` lines 465-472 | DONE — sweeps `max_approach_velocity` | LOW-MEDIUM |

---

## 4. Recommended Build Order

1. **#1 Recency-weighted offsets** — highest impact, simplest to implement. The decay infrastructure exists. Changes only the offset computation in wick analyzer + a sweep for the decay half-life.

2. **#2 + #3 Regime-conditioned entry + adaptive offsets** — second highest impact. Requires regime-tagging approach events and splitting hold rates / offsets by regime. More complex but uses existing data.

3. **#4 Post-break cooldown** — protects against cascade losses. Requires tracking level breaks in the backtest and adding a timer.

4. **#5 + #6 VIX gate + velocity** — refinements on top of #2. Add after regime conditioning proves valuable.

---

## 5. Requirements Compliance

All proposed optimizations MUST follow:
- **Data isolation**: Each new sweep writes to its own output file
- **Multi-period scoring**: 4-period composite (12mo/6mo/3mo/1mo)
- **Parallel workers**: `--workers N` support
- **Wire to live tools**: Results consumed by wick analyzer, bullet recommender, daily analyzer
- **Merge, not overwrite**: Single-ticker runs merge into existing results
