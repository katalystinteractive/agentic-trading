# Analysis: Neural Network Level Optimization — Which Levels Are Worth Deploying Capital At

**Date**: 2026-03-30 (Monday, 11:48 PM local / 4:48 PM ET)
**Purpose**: Use the neural network to determine which support levels are worth targeting, which waste capital by never filling, and which lose money by always breaking. Optimize level selection for capital efficiency, not just win rate on executed trades.

**Honesty note**: Every claim labeled FACT (verified) or PROPOSED.

---

## 1. The Real Problem

### 1.1 What the 99.3% win rate hides (FACT)

**FACT** (verified): 1,215 executed sell trades across 65 tickers have 99.3% win rate (1,206 wins, 9 losses). But this only measures trades that FILLED and CLOSED. It ignores:

- **Capital locked in unfilled orders** — limit buys sitting at levels the stock never reaches. That money earns zero return while deployed elsewhere could produce P/L. (This is a recognized problem in the system — `range_uplift_analyzer.py` exists specifically to detect dormant orders — but the exact magnitude is UNMEASURED.)
- **Levels with low touch frequency** — levels the stock rarely reaches. Even if they'd hold when tested, they tie up capital for months waiting.
- **Levels we don't trade that we should** — the wick analyzer may skip levels (low approach count, no PA/HVN confluence) that would actually be profitable.

### 1.2 What data exists to learn from (FACT)

**FACT** (verified): The wick analysis markdown table for each ticker has these columns:
`Support | Source | Approaches | Held | Freq/mo | Hold Rate | Median Offset | Buy At | Zone | Tier | Decayed | Trend | Fresh`

**FACT** (verified): The bullet plan dict from `analyze_stock_data()` contains per-level fields (from `_bullet_entry()` in wick_offset_analyzer.py):
- `support_price` — the raw support price
- `buy_at` — wick-adjusted buy price
- `hold_rate` — raw hold rate percentage
- `decayed_hold_rate` — recency-weighted hold rate (used for tier classification)
- `effective_tier` — tier after recency promotion/demotion
- `zone` — Active/Buffer/Reserve
- `monthly_touch_freq` — how often the level is tested per month (ALREADY EXISTS)
- `dormant` — boolean True/False flag (NOT a day count — set when level not tested in 90+ days)
- `approaches` — total approach count
- `shares` — computed share count for this bullet
- `cost` — estimated cost for this bullet

**FACT**: The simulation trades.json has per-trade outcomes that can be linked back to entry levels.

**FACT**: `cycle_timing.json` files exist for 100+ tickers with: fill rates, median fill days, cycle speed per level.

### 1.3 Three optimizations the neural network can learn (PROPOSED)

**Optimization 1: Level filtering** — Don't deploy capital at levels that waste it.
- Skip levels with touch frequency < X per month (never gets hit)
- Skip levels with hold rate < Y% (always breaks)
- Skip levels in certain zones for certain tickers (some tickers never reach Reserve)

**Optimization 2: Level weighting** — Deploy MORE capital at high-probability levels.
- Currently all Active/Full levels get equal weight in pool distribution
- A level with 90% hold rate and 3x/month touches deserves more capital than one with 50% hold rate and 0.5x/month touches
- The neural network can learn the optimal weight per level characteristic

**Optimization 3: Level timing** — When to activate/deactivate a level.
- A level that was tested 3 months ago (dormant) may not be relevant anymore
- A level that was just tested and held (fresh) is more reliable
- The neural network can learn how recency affects level profitability

---

## 2. How to Implement as a Sweep

### 2.1 Level characteristics as sweep parameters (PROPOSED)

Add these to the parameter sweep grid:

| Parameter | Current default | Sweep range | What it controls |
| :--- | :--- | :--- | :--- |
| `min_hold_rate` | 15% (FACT — already exists in SurgicalSimConfig) | [15, 30, 50, 60, 70] | Sweep ABOVE current default |
| `min_touch_freq` | 0 (NEW — not currently filtered) | [0, 0.5, 1.0, 2.0, 3.0] | Skip levels touched less than X/month |
| `skip_dormant` | False (NEW — dormant flag exists but not checked) | [False, True] | Skip levels flagged as dormant (>90 days untested) |
| `zone_filter` | "all" (NEW — all zones get orders) | ["active", "active_buffer", "all"] | Which zones to trade |

### 2.2 How the sweep works (PROPOSED)

For each ticker, for each combination of level filters:
1. Load wick analysis levels
2. Filter levels by min_hold_rate, min_touch_freq, skip_dormant, zone
3. Run backtest simulation with ONLY the filtered levels
4. Measure P/L + capital efficiency (P/L per dollar deployed)

The sweep discovers: "For CIFR, only trade levels with hold rate >= 60% and touch frequency >= 1.0/month. This produces 90% of the P/L with 40% of the capital deployed."

### 2.3 The key metric: capital efficiency (PROPOSED)

Currently we measure P/L. But a level that produces $10 P/L using $300 deployed for 30 days is WORSE than a level that produces $8 P/L using $100 deployed for 5 days.

**Capital efficiency = P/L / (capital_deployed × days_deployed)**

The neural network should optimize for capital efficiency, not raw P/L. A ticker with 3 high-efficiency levels beats a ticker with 7 levels where 4 sit unfilled for months.

---

## 3. What Needs to Change in backtest_engine.py

### 3.1 Current filtering (FACT — verified against code)

**FACT**: `backtest_engine.py` already filters levels before placing orders (lines 554-558):

```python
tier = bullet.get("effective_tier", bullet.get("tier", "Skip"))
if tier == "Skip":
    continue
hr = bullet.get("decayed_hold_rate", bullet.get("hold_rate", 0))
if hr < cfg.min_hold_rate:
    continue
```

**FACT**: `SurgicalSimConfig` already has `min_hold_rate: int = 15` (backtest_config.py line 148). Skip tier levels are always excluded. Levels with decayed_hold_rate below 15% are excluded.

**FACT**: The simulation does NOT currently filter by:
- Touch frequency (`monthly_touch_freq` exists in bullet plan but is not checked)
- Dormancy (`dormant` boolean exists but is not checked)
- Zone (all zones get orders if they pass tier + hold rate gates)

### 3.2 What needs to change (PROPOSED)

Add NEW filter parameters to `SurgicalSimConfig` (alongside the existing `min_hold_rate`):

```python
# In backtest_config.py — NEW fields only
min_touch_freq: float = 0       # skip levels touched less than X/month
skip_dormant: bool = False      # skip levels flagged as dormant (>90 days untested)
zone_filter: str = "all"        # "active", "active_buffer", "all"
```

**NOTE**: `min_hold_rate` already exists with default 15. The sweep should vary it ABOVE the current default: [15, 30, 50, 60, 70]. Setting it below 15 would loosen filtering vs current behavior.

**NOTE**: Dormancy is a boolean in the bullet plan (`dormant: True/False`), NOT a day count. The sweep uses `skip_dormant: bool` (True/False), not `skip_dormant: int`. If finer granularity is needed later, the wick analyzer would need to output days-since-last-touch.

In `backtest_engine.py`, after the existing tier + hold_rate filters (line 558), add:

```python
# NEW filters (after existing tier + hold_rate checks):
if cfg.min_touch_freq > 0:
    tf = bullet.get("monthly_touch_freq", 0)
    if tf < cfg.min_touch_freq:
        continue
if cfg.skip_dormant and bullet.get("dormant", False):
    continue
if cfg.zone_filter != "all":
    zone = bullet.get("zone", "").lower()
    if cfg.zone_filter == "active" and zone != "active":
        continue
    if cfg.zone_filter == "active_buffer" and zone not in ("active", "buffer"):
        continue
```

### 3.3 What data the wick analyzer already provides (FACT)

**FACT**: Each level in the bullet plan has:
- `buy_at` — wick-adjusted price
- `support_price` — the support price
- `hold_rate` — percentage (e.g., 80%)
- `tier` — Full/Std/Half/Skip
- `zone` — Active/Buffer/Reserve

**VERIFIED**: The bullet plan dict already contains `monthly_touch_freq` (usable directly) and `dormant` as a boolean (True when >90 days untested). No new fields need to be added to the wick analyzer for the proposed filtering.

---

## 4. Implementation Approach

### 4.1 Add level filter parameters to SurgicalSimConfig (~10 lines)

### 4.2 Add level filtering in backtest_engine.py (~15 lines)

### 4.3 Add level filters to sweep grid in support_parameter_sweeper.py (~20 lines)

```python
LEVEL_FILTER_GRID = {
    "min_hold_rate": [15, 30, 50, 60, 70],       # 15 = current default
    "min_touch_freq": [0, 0.5, 1.0, 2.0, 3.0],   # 0 = current (no filter)
    "skip_dormant": [False, True],                 # boolean, not days
    "zone_filter": ["active", "active_buffer", "all"],
}
```

### 4.4 Sweep as a new Stage 3 (after threshold + execution)

Stage 1: Sweep sell target + catastrophic stop (existing)
Stage 2: Sweep pool + bullets + tier (existing)
**Stage 3: Sweep level filters (NEW)** — with thresholds and execution params locked, vary which levels are traded

This keeps the two-stage independence assumption — level filtering is approximately independent of sell target and pool sizing.

### 4.5 Output: per-ticker level filter profile

```json
{
  "CIFR": {
    "sell_default": 10.0,
    "active_pool": 500,
    "min_hold_rate": 60,
    "min_touch_freq": 1.0,
    "skip_dormant": true,
    "zone_filter": "active_buffer"
  }
}
```

---

## 5. Data Preservation — No Overwriting of Existing Results

### 5.1 Current problem (FACT)

Multiple tools overwrite the same output files. Running one sweep destroys results from a prior sweep:

| File | Overwritten by | Risk |
| :--- | :--- | :--- |
| `data/ticker_profiles.json` | `parameter_sweeper.py` AND `ticker_clusterer.py` | Dip profiles overwritten by clustering |
| `data/synapse_weights.json` | `weight_learner.py` AND `historical_trade_trainer.py` | Dip weights overwritten by support training |
| `data/support_sweep_results.json` | `support_parameter_sweeper.py` | Previous sweep results destroyed on re-run |
| `data/neural_support_candidates.json` | `neural_support_discoverer.py` | Previous candidate rankings destroyed on re-run |
| `data/sweep_results.json` | `parameter_sweeper.py` | Previous dip sweep destroyed on re-run |

The level optimization sweep would add another overwrite risk — Stage 3 results replacing Stage 1+2 results.

### 5.2 What must be preserved (PROPOSED)

Each sweep/optimization produces a distinct result set that should be accessible independently:

| Result set | Purpose | Should persist as |
| :--- | :--- | :--- |
| Dip strategy profiles | Per-ticker dip/target/stop/breadth thresholds | Separate file, never overwritten by support sweep |
| Support strategy profiles | Per-ticker sell target/pool/bullets | Separate file, never overwritten by dip sweep |
| Level filter profiles | Per-ticker min_hold_rate/touch_freq/dormancy/zone | Separate file, never overwritten by threshold sweep |
| Synapse weights (dip) | Dip gate weights from dip trade outcomes | Separate namespace in weights file |
| Synapse weights (support) | Support gate weights from support trade outcomes | Separate namespace in weights file |
| Watchlist profiles | Guaranteed profiles for every tracked ticker | Separate file from candidate discovery |

### 5.3 Implementation approach (PROPOSED)

**Option A: Separate output files per sweep type**

Each sweep stage writes to its own file. Nothing overwrites anything else:

```
data/sweep_dip_profiles.json          ← dip strategy (parameter_sweeper.py)
data/sweep_support_threshold.json     ← support Stage 1 (sell target + stop)
data/sweep_support_execution.json     ← support Stage 2 (pool + bullets)
data/sweep_support_levels.json        ← support Stage 3 (level filters) — NEW
data/neural_candidates.json           ← dip candidate discovery (read-only after creation)
data/neural_support_candidates.json   ← support candidate discovery (read-only after creation)
data/neural_watchlist_profiles.json   ← watchlist sweep (read-only between weekly runs)
data/synapse_weights.json             ← all weights (dip + support coexist via gate namespaces)
```

**Option B: Timestamped results with "latest" symlink**

Each run writes to a timestamped file. A "latest" symlink points to the most recent:

```
data/support_sweep_2026-03-30.json    ← this run
data/support_sweep_2026-03-23.json    ← last week's run
data/support_sweep_latest.json        → symlink to 2026-03-30
```

This preserves all historical runs for comparison but adds filesystem complexity.

**Recommendation**: Option A for now (simpler). Level filter results go to `data/sweep_support_levels.json`. The combined profile that the daily analyzer reads is assembled from ALL sweep files at load time, not stored as a single overwritable file.

### 5.4 How the daily analyzer assembles the full profile

**Current priority chains (FACT — verified against code):**

Pool sizing (`shared_utils.py::get_ticker_pool()`):
```
1. multi-period-results.json (simulation-backed allocation — highest)
2. neural_watchlist_profiles.json
3. neural_support_candidates.json
4. portfolio.json capital section
5. hardcoded $300/$300
```

Sell targets (`broker_reconciliation.py::_load_profiles()` + `compute_recommended_sell()`):
```
1. Manual target_exit in portfolio.json position (checked in compute_recommended_sell)
2. ticker_profiles.json (dip profiles — loaded first)
3. neural_watchlist_profiles.json (fills gaps only)
4. neural_support_candidates.json (fills gaps only)
5. SELL_DEFAULT_PCT = 6.0% hardcoded
```

**PROPOSED addition** for level filters — a new file read:
```
Level filter profiles (sweep_support_levels.json) — NEW
  Provides: min_hold_rate, min_touch_freq, skip_dormant, zone_filter
  Read by: backtest_engine.py when placing orders (or passed via SurgicalSimConfig)
  Does NOT overlap with pool or sell target fields — separate concern
```

Each file contributes different fields. No file overwrites another's fields:
- multi-period / watchlist / support candidates provide: pool, sell_default, active_bullets_max
- Level filter profiles provide: min_hold_rate, min_touch_freq, skip_dormant, zone_filter
- Dip profiles provide: dip_threshold, bounce_threshold, target_pct, breadth_threshold

### 5.5 Synapse weights are already namespace-safe (FACT)

**FACT** (verified): The synapse weights file uses gate-name keys as namespaces:
- Dip gates: `CIFR:dip_gate`, `CIFR:bounce_gate` — from dip trade training
- Support gates: `CIFR:profit_gate`, `CIFR:hold_gate` — from support trade training

These don't collide. Both `weight_learner.py` and `historical_trade_trainer.py` load existing weights before training and only update their own gate keys. The other strategy's weights are preserved.

**BUT**: Both tools call `save_weights()` which overwrites the `_meta.stats` section with the latest training run's stats. This means the stats show only the LAST training source, not both. This should be fixed to track stats per source.

---

## 6. What This Would Discover (HYPOTHETICAL)

**NOTE**: These are HYPOTHETICAL examples — actual values come from the sweep.

**HYPOTHETICAL examples** — actual values come from the sweep:

- "CIFR: skip levels with hold rate < 50%. This eliminates 3 weak levels, concentrates capital on 4 strong ones. P/L drops 5% but capital deployed drops 40% → capital efficiency doubles."
- "LUNR: skip dormant levels (>90 days). 8 of 21 levels are stale. Removing them doesn't change P/L (they never fill anyway) but frees $240 of deployed capital."
- "RDW: only trade Active zone. Buffer/Reserve levels never fill for this ticker. 100% of P/L comes from Active zone with 30% of capital."

---

## 7. Files

| File | Change | Lines |
| :--- | :--- | :--- |
| `tools/backtest_config.py` | Add level filter fields to SurgicalSimConfig | ~6 |
| `tools/backtest_engine.py` | Add level filters after existing tier + hold_rate checks | ~15 |
| `tools/support_parameter_sweeper.py` | Add Stage 3 level filter sweep, write to `data/sweep_support_levels.json` (separate from threshold/execution results) | ~40 |
| `tools/weight_learner.py` | Fix `_meta.stats` to track per-source stats instead of overwriting | ~10 |
| **Total** | | **~71** |

**Output files** (NEW, never overwrite existing):
- `data/sweep_support_levels.json` — level filter profiles per ticker

---

## 8. Open Questions

1. ~~**Does the bullet plan dict contain touch_freq and dormant_days?**~~ **RESOLVED**: `monthly_touch_freq` exists. `dormant` is a boolean (True/False), not a day count. Sweep uses `skip_dormant: bool` instead of `skip_dormant: int`.

2. **Capital efficiency metric** — How exactly to measure "P/L per dollar deployed per day"? The simulation tracks equity curve but not per-level capital deployment duration. May need to add this tracking to backtest_engine.py.

3. **Stage 3 independence** — Is level filtering independent of sell target? Probably yes — filtering levels changes WHICH trades happen, but the sell target determines WHEN to exit each trade. But should verify by checking whether Stage 3 results change when Stage 1 thresholds vary.

4. **Grid size** — 5 × 5 × 2 × 3 = 150 level filter combos per ticker (updated from 240 — `skip_dormant` is boolean not 4-value). Runtime is UNMEASURED — must benchmark before estimating.

5. **Capital redistribution** — When level filtering removes levels, the remaining levels share the same pool. The simulation handles this correctly (fewer bullets = more capital per bullet), but the freed capital is NOT redistributed to other tickers. This is a separate optimization beyond the scope of level filtering.
