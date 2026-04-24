# Analysis: Entry Sweep Results Wiring Gap

**Date**: 2026-04-02 (Thursday)
**Purpose**: The entry parameter sweep produces per-ticker optimal buy-side params in `data/entry_sweep_results.json`, but no live tool reads this file. The sweep-learned entry gate parameters (offset_decay_half_life, riskoff_min_hold_rate, regime_aware_offset, post_break_cooldown, per_ticker_vix_gate, max_approach_velocity) are not applied to live bullet plan computation or order recommendations.

---

## 1. Current State (FACT — verified)

**FACT**: `entry_parameter_sweeper.py` writes to `data/entry_sweep_results.json` with per-ticker entries containing `params` dict with 6 entry gate fields.

**FACT**: Zero tools read `entry_sweep_results.json`. Verified: `grep -r "entry_sweep_results" tools/ --include="*.py"` returns only the sweeper itself.

**FACT**: The 6 entry gate params are used in two places during simulation:
1. `wick_offset_analyzer.py` — `offset_decay_half_life` and `regime_aware_offset` affect the WickConfig used for offset computation (lines 767-815)
2. `backtest_engine.py` — `riskoff_min_hold_rate`, `post_break_cooldown`, `per_ticker_vix_gate`, `max_approach_velocity` are checked in the fill section (lines 447-487)

**FACT**: In live usage, `WickConfig` defaults are used (`offset_decay_half_life=0`, `regime_aware_offset=False`) — meaning recency-weighted offsets and regime-adaptive offsets are disabled in production.

**FACT**: In live usage, entry gates in the backtest engine don't run — the backtest only runs during sweeps. The daily analyzer's entry gate section (Risk-Off/Risk-On display) is separate from the backtest engine's fill gates.

---

## 2. What Needs Wiring

### 2.1 Wick offset params → live bullet plan

The sweep discovers optimal `offset_decay_half_life` per ticker. This needs to flow into the `WickConfig` when `analyze_stock_data()` is called by:
- `bullet_recommender.py` (line 1123/1141 via `analyze_stock_data`)
- `broker_reconciliation.py` (via `reconcile_ticker` → wick analysis)
- `daily_analyzer.py` (via broker recon)

**Integration point**: `load_capital_config(ticker)` in `wick_offset_analyzer.py` (lines 47-97) already loads per-ticker pool/bullet params from neural JSON files (including `neural_support_candidates.json` at lines 70-82). This is the established pattern for loading neural sweep overrides. A parallel function `_load_entry_config(ticker)` follows the same mtime-cached pattern as `_load_level_filters()` (line 109).

**Design choice**: Separate function (`_load_entry_config`) rather than extending `load_capital_config` — separation of concerns: pool sizing vs entry timing. Both use the same caching pattern but serve different config domains.

### 2.2 Entry gate params → live order placement

The 4 backtest-only gates (`riskoff_min_hold_rate`, `post_break_cooldown`, `per_ticker_vix_gate`, `max_approach_velocity`) are meaningful during live order placement too:
- **riskoff_min_hold_rate**: During Risk-Off, the daily analyzer could flag levels with low Risk-Off hold rates as "paused" instead of recommending buy orders
- **per_ticker_vix_gate**: When VIX exceeds the ticker's gate, flag as "VIX-gated"
- **post_break_cooldown**: After a level breaks, delay re-deployment for N days
- **max_approach_velocity**: Flag rapid declines as "velocity-gated"

**Integration point**: The daily analyzer's entry gate section and `_compute_bullet_plan()` can filter/flag levels based on these params. The order proximity monitor could also use VIX gate for alert suppression.

---

## 3. Proposed Approach

### 3.1 Load entry sweep results in `wick_offset_analyzer.py`

Add `_load_entry_config(ticker)` alongside `_load_level_filters(ticker)`:

```python
def _load_entry_config(ticker):
    """Load per-ticker entry gate params from neural sweep."""
    # Same mtime-cached pattern as _load_level_filters
    ...
    return entry.get("params")  # {offset_decay_half_life, regime_aware_offset, ...}
```

In `analyze_stock_data()`, load entry config and apply to WickConfig:

```python
entry_cfg = _load_entry_config(ticker)
if entry_cfg:
    c.offset_decay_half_life = entry_cfg.get("offset_decay_half_life", 0)
    c.regime_aware_offset = entry_cfg.get("regime_aware_offset", False)
```

### 3.2 Apply entry gates in `_compute_bullet_plan()` or daily analyzer

For live usage, the entry gates affect which levels are DISPLAYED as deployable:
- Levels with `risk_off_hold_rate < riskoff_min_hold_rate` get flagged during Risk-Off
- This is a display/recommendation change, not a fill-prevention change (that's broker-side)

---

## 4. Files

| File | Change | Est. Lines |
| :--- | :--- | :--- |
| `tools/wick_offset_analyzer.py` | Add `_load_entry_config()`, apply offset_decay + regime_aware to WickConfig in `analyze_stock_data()` | ~20 |
| `tools/order_proximity_monitor.py` | Load `per_ticker_vix_gate` from entry sweep, suppress BUY alerts when VIX exceeds gate | ~10 |
| **Total** | | **~30** |

The live system benefits from:
- **`offset_decay_half_life`** and **`regime_aware_offset`**: Directly affect buy prices in the bullet plan
- **`per_ticker_vix_gate`**: Can suppress BUY proximity alerts in `order_proximity_monitor.py` when VIX exceeds the ticker's learned threshold — prevents misleading alerts during high-volatility periods
- **`riskoff_min_hold_rate`**: Can flag low-reliability levels as "paused" in the daily analyzer during Risk-Off

The remaining 2 gates (`post_break_cooldown`, `max_approach_velocity`) are execution-specific and primarily backtest-applicable — they require real-time tracking of recent breaks and intraday price movement that the live system doesn't currently maintain.
