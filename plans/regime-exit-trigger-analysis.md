# Analysis: Early-Exit Trigger on Regime Change

**Date**: 2026-04-11
**Priority**: HIGH — $1.2K-$1.9K annual impact on $10K portfolio

---

## Problem

Positions entered during Risk-On (99.5% WR, +4.8% avg) get dragged underwater when regime shifts to Risk-Off (46.4% WR, -7.0% avg). Current system blocks new ENTRIES during Risk-Off but has NO exit trigger for existing positions.

28 positions held through Risk-Off produced -$335 in losses. If 50% were exited on regime change, ~$168 per episode × 4-6 episodes/year = $670-$1,008 saved.

---

## What Exists

**Entry side (working):**
- 15% proximity gate blocks fills during Risk-Off
- Per-level hold rate gate (optional)
- Budget reduction ($100→$50 for dip)

**Exit side (gap):**
- Time stop extended +14 days during Risk-Off
- Profit target upgrades suppressed
- **NO early-exit on regime change**

---

## Implementation

### 1. Backtest Engine — Add regime exit check

**File**: `tools/backtest_engine.py`
**Location**: In the CHECK EXITS section (lines 240-375), after catastrophic stop, before time stop.

**New config fields** in `tools/backtest_config.py`:
```python
regime_exit_enabled: bool = False
regime_exit_pct: float = 50.0      # % of position to sell
regime_exit_hold_days: int = 1     # days of Risk-Off before trigger
```

**Logic**:
- Track `_prev_regime` per day
- When regime transitions to Risk-Off AND position held ≥ `regime_exit_hold_days`:
  - Sell `regime_exit_pct`% of shares at day_close
  - Record as exit_reason "REGIME_EXIT"
  - Remaining shares continue with tighter stops

### 2. Regime Exit Sweep — New simulation stage

**File**: `tools/support_parameter_sweeper.py` — add Stage 5: `sweep_regime_exit()`
**Grid**:
```python
REGIME_EXIT_GRID = {
    "regime_exit_pct": [25, 50, 75, 100],
    "regime_exit_hold_days": [0, 1, 2, 3],
}
# 4 × 4 = 16 combos × 4 periods
```

**Output**: `data/regime_exit_sweep_results.json` (separate file, no contamination)

**Uses 4-period composite scoring** (12/6/3/1 month) matching all other sweeps.

### 3. Daily Analyzer Integration

**File**: `tools/daily_analyzer.py`
**Where**: After `print_market_regime()` (line ~67)

When regime is Risk-Off:
- Load regime_exit_sweep_results.json for each position ticker
- If ticker's optimal regime_exit_pct > 0:
  - Show "REGIME EXIT: Sell {pct}% of {ticker} ({shares} shares @ ${price})"
  - Include the sweep-learned optimal hold_days

### 4. Wire to Tournament + Bullet Recommender

- Tournament: add "regime_exit" to SWEEP_FILES for composite ranking
- Bullet recommender: when regime is Risk-Off, show "⚠ Risk-Off — regime exit may trigger" warning

---

## Verification

1. Run sweep on 5 tickers: `python3 tools/support_parameter_sweeper.py --stage regime_exit --ticker CIFR`
2. Check results: `data/regime_exit_sweep_results.json` exists with per-ticker optimal params
3. Daily analyzer: during Risk-Off, shows specific exit recommendations
4. Backtest: compare composite WITH regime exit vs WITHOUT — should improve for volatile tickers
5. No contamination: existing sweep files unchanged
