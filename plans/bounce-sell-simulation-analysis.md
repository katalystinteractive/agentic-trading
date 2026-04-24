# Analysis: Bounce-Derived Sell Targets — Per-Level Sell Discovery

**Date**: 2026-04-01 (Wednesday)
**Purpose**: Discover optimal sell targets by measuring actual bounce heights from each support level. Instead of flat percentages or resistance detection, use historical "bought at level X → bounced to Y" data to set per-level sell targets. When multiple fills exist, combine their individual bounce profiles into an optimal blended sell target with recency weighting.

---

## 1. Core Concept

### 1.1 Per-level bounce discovery

For each support level where price historically held:
1. Measure the **bounce height** — how high did price go after touching the level?
2. Track across 1-day, 2-day, 3-day, 5-day, and 10-day windows
3. Compute **recency-weighted median bounce** — recent bounces weighted higher than old ones
4. The sell target for a fill at this level = `fill_price + weighted_median_bounce`

**Example**: STIM $1.25 support held 4 times:
- 2026-03-15: bounced to $1.48 (+18.4%)
- 2026-02-20: bounced to $1.52 (+21.6%)
- 2026-01-10: bounced to $1.45 (+16.0%)
- 2025-10-05: bounced to $1.40 (+12.0%)

With 90-day half-life decay: recent bounces get higher weights. Weighted median might be ~$1.49 (+19.2%) instead of raw median $1.47 (+17.2%).

### 1.2 Multi-fill combination

When position has fills at multiple levels:
- A1 fill @ $1.33 → bounce profile says median target $1.52
- A2 fill @ $1.25 → bounce profile says median target $1.49

The combined sell target must account for:
- **Blended avg cost**: ($1.33 × shares₁ + $1.25 × shares₂) / total_shares
- **Weakest bounce ceiling**: The sell target can't exceed the minimum of the individual bounce targets (the shallowest fill limits the portfolio's upside before the first fill's bounce exhausts)
- **Weighted combination**: Weight each level's bounce target by shares at that level

**Formula**: `combined_sell = Σ(shares_i × bounce_target_i) / total_shares`

This gives a share-weighted average of individual bounce targets — deeper fills with larger share counts pull the target toward their bounce ceiling.

### 1.3 Recency weighting

Apply exponential decay to bounce observations:
```
weight = exp(-days_ago / half_life)
```
Where `half_life = 90 days` (matching the existing decay_half_life in `SurgicalSimConfig`).

Recent bounces that reached higher targets get more weight than older bounces with lower peaks. This naturally adapts to changing market conditions — a stock that's been bouncing higher recently gets a higher sell target.

---

## 2. Existing Infrastructure (FACT — verified)

### 2.1 `bounce_analyzer.py` — complete bounce measurement

**FACT**: `measure_bounce()` (lines 245-264) measures max high in 1/2/3-day windows after a support touch. Returns `{"max_high": float, "bounce_pct": float}` per window.

**FACT**: `compute_level_stats()` (lines 271-317) aggregates per-level: `bounce_1d_median`, `bounce_2d_median`, `bounce_3d_median`, `pct_above_4_5`, ATR-normalized metrics.

**FACT**: Trade setup generation (lines 440-455) already computes `sell_at = buy_at * (1 + bounce_3d_median / 100)` — a bounce-derived sell target.

**Gap**: No recency weighting in the current bounce analyzer. All bounces weighted equally. No per-event bounce tracking (only aggregated medians).

**CRITICAL**: `measure_bounce()` requires **hourly data** (`hourly_df` as first parameter). The bounce analyzer fetches this via `yf.download(ticker, period="730d", interval="1h")` at line 357. The backtest engine and wick offset analyzer operate on **daily data only** — they have no hourly data pipeline. This means `measure_bounce()` cannot be called directly from within the simulation.

**Resolution**: Build a daily-data bounce measurement function for the simulation. Instead of hourly max-high tracking, use daily data:
```python
def measure_bounce_daily(daily_df, approach_end_date, n_days=(2, 3, 5)):
    """Measure bounce from daily OHLC after a support hold event."""
    after = daily_df[daily_df.index > approach_end_date]
    results = {}
    for n in n_days:
        window = after.iloc[:n]
        if not window.empty:
            max_high = float(window["High"].max())
            results[n] = max_high
    return results
```
Daily data is coarser (misses intraday peaks) but is available during simulation without additional yfinance fetches. The bounce heights from daily data will be slightly lower than hourly (hourly captures intraday spikes), but the relative ranking between levels is preserved. For the live path (outside simulation), hourly `measure_bounce()` can still be used for more precise targets.

### 2.2 `wick_offset_analyzer.py` — approach events with `prior_high`

**FACT**: `find_approach_events()` (lines 503-594) returns per-event: `start`, `min_low`, `offset_pct`, `held`, `prior_high` (20-day lookback high before approach).

**FACT**: `prior_high` represents the ceiling the stock came from before approaching support. This is a natural upper bound for the bounce — the stock is unlikely to bounce past where it was before the pullback.

**Gap**: `prior_high` is in the event data but never used for sell target computation.

### 2.3 Backtest trade records

**FACT**: Simulation trades record `entry_price`, `exit_price`, `exit_reason`, `days_held`, `avg_cost`. But they do NOT record which support level triggered the entry.

**Gap**: No link between "filled at support level $X" and "this trade exited at $Y". The backtest knows the position avg_cost but not which specific level(s) were responsible.

### 2.4 Existing decay infrastructure

**FACT**: `SurgicalSimConfig.decay_half_life = 90` days (line 156 of backtest_config.py). Used by `wick_offset_analyzer.py` for decayed hold rates. The same decay constant can be reused for bounce recency weighting.

---

## 3. What Must Be Built (PROPOSED)

### 3.1 Per-level bounce profile computation

New function in a new tool `tools/bounce_sell_analyzer.py`:

```python
def compute_bounce_profiles(hist, levels, decay_half_life=90):
    """For each support level, compute recency-weighted bounce statistics.

    Returns: {level_price: {
        "median_bounce_pct": float,     # recency-weighted median
        "median_bounce_target": float,  # level_price * (1 + median_bounce_pct/100)
        "bounce_events": [{date, bounce_pct, max_high, weight}, ...],
        "prior_high_median": float,     # recency-weighted median of prior_high
        "n_held": int,
        "confidence": float,            # 0-1 based on sample size + recency
    }}
    """
```

For each level:
1. Call `find_approach_events(hist, level)` to get all approaches
2. Filter to `held=True` events only
3. For each held event, measure bounce height using `measure_bounce()` from `bounce_analyzer.py`
4. Apply decay weight: `weight = exp(-days_ago / half_life)`
5. Compute weighted median of `bounce_pct`
6. Compute weighted median of `prior_high` (natural ceiling)
7. `bounce_target = min(weighted_median_bounce, weighted_median_prior_high)` — capped by the historical ceiling

### 3.2 Multi-fill sell target computation

```python
def compute_combined_sell_target(fills, bounce_profiles):
    """Combine multiple fills' bounce profiles into a single sell target.

    Args:
        fills: [{price: float, shares: int, level_price: float}, ...]
        bounce_profiles: {level_price: {median_bounce_target: float, ...}}

    Returns: {
        "combined_sell": float,
        "per_fill_targets": [{level, shares, bounce_target}, ...],
        "blended_avg": float,
        "expected_pnl_pct": float,
    }
    """
```

Formula: `combined_sell = Σ(shares_i × bounce_target_i) / total_shares`

### 3.3 Backtest integration — `sell_mode = "bounce"`

Add to `backtest_engine.py`:
- At buy time: record which support level triggered the fill (level price from the bullet plan)
- At recompute time: compute bounce profiles for all levels the position was filled at
- At sell time: use `compute_combined_sell_target()` with the position's fills + bounce profiles
- Target price = the combined bounce sell target

New config fields:
```python
# Bounce sell params (backtest_config.py)
bounce_window_days: int = 3      # 1, 2, 3, 5, or 10 day bounce window
bounce_confidence_min: float = 0.3  # minimum confidence to use bounce target
bounce_cap_prior_high: bool = True  # cap bounce at prior_high median
```

### 3.4 Bounce parameter sweep

New tool `tools/bounce_parameter_sweeper.py`:

```python
BOUNCE_GRID = {
    "bounce_window_days": [2, 3, 5],
    "bounce_confidence_min": [0.2, 0.3, 0.5],
    "bounce_cap_prior_high": [True, False],
    "resistance_fallback_pct": [4, 6, 8],
}
# 3 × 3 × 2 × 3 = 54 combos
```

**Data isolation**: Writes to `data/bounce_sweep_results.json` (separate from support/resistance sweeps).

**Multi-period**: Uses `SWEEP_PERIODS = [12, 6, 3, 1]` + `compute_composite()`.

**Parallel workers**: `_sweep_bounce_worker()` + `Pool.map()` + `--workers N`.

### 3.5 Comparison framework

For each ticker, produce 3-way comparison:
```json
{
    "flat_composite": 33.6,
    "resistance_composite": 41.8,
    "bounce_composite": 45.2,
    "winner": "bounce",
    "improvement_over_flat": "+34.5%",
    "improvement_over_resistance": "+8.1%"
}
```

The live sell chain picks the winner — `compute_recommended_sell()` checks bounce → resistance → neural % → default 6%.

---

## 4. Key Differences from Resistance Approach

| Aspect | Resistance | Bounce |
| :--- | :--- | :--- |
| **What it finds** | Where price gets rejected (ceiling) | How far price bounces from support (floor-to-ceiling) |
| **Data source** | Daily Highs clustered into resistance levels | Approach events + post-hold bounce measurement |
| **Per-level?** | No — finds resistance above current price regardless of entry | Yes — each support level has its own bounce profile |
| **Multi-fill?** | No — one resistance target for the position | Yes — combines per-level bounces weighted by shares |
| **Recency?** | No — all resistance approaches weighted equally | Yes — exponential decay on bounce observations |
| **Natural cap** | Resistance reject rate | Prior high (stock came from there before pullback) |

---

## 5. Data Flow

```
Step 1: During backtest, at RECOMPUTE time (same schedule as wick analysis):
        compute bounce profiles from hist_slice (data up to current sim day ONLY)
        This prevents look-ahead bias — bounce heights computed only from
        approaches that have ALREADY completed before the current sim date.
Step 2: At fill time, record which support level triggered the fill
Step 3: At sell time, look up bounce profile for each fill's level
Step 4: Combine multi-fill bounce targets into combined sell price
Step 5: Sweep bounce params (window, confidence, cap) across 4 periods
Step 6: Compare bounce vs resistance vs flat composites
Step 7: Live tools use the winner's approach
```

**Look-ahead bias prevention**: Bounce profiles are computed from `hist_slice` (the same date-masked slice used for wick analysis at line 524 of `backtest_engine.py`: `hist_slice = full_df[mask]` where `mask = full_df.index.date <= d`). The `find_approach_events()` function receives `hist_slice` and only finds approaches that have already resolved. A bounce height is only known for past events where the approach started, the level held, and the subsequent bounce completed — all within the date range of `hist_slice`. No future data is used.

---

## 6. Files

| File | Action | Est. Lines |
| :--- | :--- | :--- |
| `tools/bounce_sell_analyzer.py` | **NEW** — per-level bounce profile computation + multi-fill combination | ~150 |
| `tools/backtest_engine.py` | Add `sell_mode="bounce"` exit logic, record entry levels in Position | ~40 |
| `tools/backtest_config.py` | Add bounce config fields | ~4 |
| `tools/bounce_parameter_sweeper.py` | **NEW** — sweep tool with multi-period + parallel workers | ~200 |
| `tools/broker_reconciliation.py` | Add bounce tier to `compute_recommended_sell()` | ~25 |
| `tools/support_parameter_sweeper.py` | Pass bounce_cache to `_simulate_with_config()` (if needed) | ~3 |
| **Total** | | **~422** |

---

## 7. Requirements Compliance

| Requirement | How Met |
| :--- | :--- |
| **Data isolation** | Writes to `data/bounce_sweep_results.json` — separate from support/resistance |
| **Multi-period scoring** | `SWEEP_PERIODS = [12, 6, 3, 1]` + `compute_composite()` |
| **Parallel workers** | `_sweep_bounce_worker()` + `Pool.map()` + `--workers N` |
| **Wire outputs to live tools** | Bounce tier added to `compute_recommended_sell()` priority chain |

---

## 8. Open Questions

1. **Bounce window**: 3-day median is the default in `bounce_analyzer.py`. Should the sweep also test 5-day and 10-day windows? Longer windows capture more upside but risk hitting time stops.

2. **Entry level tracking in Position**: The `Position` dataclass (backtest_engine.py line 36) has `fills: list` which records `{date, price, shares, zone}`. Adding `level_price` (the support level that triggered the buy) requires modifying the fill recording at line ~440. This is a structural change to the Position class.

3. **Bounce ceiling vs prior_high**: Should the bounce target be capped at the median prior_high? This prevents setting targets above where the stock was before the pullback — conservative but realistic. The sweep grid includes `bounce_cap_prior_high: [True, False]` to test both.

4. **When all bounce events are old**: If a level hasn't been tested in 6+ months, the decay weights all approach zero. Should we fall through to resistance/flat in this case? The `bounce_confidence_min` threshold handles this — low confidence = fall through.
