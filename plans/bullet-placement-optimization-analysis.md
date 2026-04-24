# Analysis: Optimal Bullet Placement — Per-Ticker Live Orders vs Monitored Levels

**Date**: 2026-04-08
**Trigger**: User identified that placing A1-A4 simultaneously ties up capital and creates catastrophic risk on deep dips. Sweep data shows optimal bullet count varies per ticker (1-7).

---

## 1. What the Data Shows

Sweep across 10 tickers with `active_bullets_max = [1, 2, 3, 4, 5, 7]`:

| Ticker | Optimal | At 2 | Current | Pattern |
| :--- | :--- | :--- | :--- | :--- |
| CIFR | 1b ($43.4) | $34.2 | 3b | Fast bouncer — fewer bullets = better |
| NUAI | 1b ($42.9) | $41.7 | 3b | Fast bouncer |
| LUNR | 1b ($64.9) | $49.8 | 3b | Fast bouncer |
| STIM | 2b ($49.7) | $49.7 | 3b | Medium — A1+A2 optimal |
| RGTI | 2b ($47.8) | $47.8 | 3b | Medium |
| NU | 2b ($39.6) | $39.6 | 7b | Medium (current over-allocated) |
| NNE | 3b ($57.3) | $31.0 | 3b | Needs averaging |
| BBAI | 4b ($51.7) | $3.4 | 7b | Deep dip recovery |
| ACHR | 7b ($42.5) | $2.5 | 3b | Deep dip — needs all bullets |
| RDW | 7b ($45.6) | $38.6 | 3b | Deep dip (current under-allocated) |

**Key insight**: There is NO universal optimal count. It's per-ticker, driven by the stock's bounce behavior. Fast bouncers (CIFR, LUNR) profit from 1 bullet. Deep dippers (BBAI, ACHR) need 4-7.

---

## 2. Current System State

### What `support_sweep_results.json` already has
Each ticker has `params.active_bullets_max` — the sweep-optimized count. This was computed by Stage 2 (execution sweep) which tests `[3, 5, 7]` for active bullets.

### What `shared_utils.get_ticker_pool()` returns
Returns `active_bullets_max` from sweep results. This flows to `bullet_recommender.py` which uses it to size the Level Map.

### What's missing
1. **The Level Map doesn't mark which levels to PLACE vs MONITOR** — all levels get the same treatment
2. **The proximity monitor only checks placed orders** — it ignores unplaced bullet levels
3. **The execution sweep grid [3, 5, 7] doesn't include [1, 2, 4]** — can't find the optimal for fast bouncers
4. **The new bullet placement sweep data is in a separate research file** — not wired to live tools

---

## 3. What Needs to Change

### 3.1 Expand execution sweep grid to include [1, 2, 3, 4, 5, 7]

**File**: `tools/support_parameter_sweeper.py`
**Current**: `EXECUTION_GRID["active_bullets_max"] = [3, 5, 7]`
**New**: `EXECUTION_GRID["active_bullets_max"] = [1, 2, 3, 4, 5, 7]`

This doubles the execution sweep combos from 144 to 288, but the result is a properly optimized `active_bullets_max` per ticker that includes 1-2 bullet options for fast bouncers.

**Runtime impact**: Stage 2 goes from ~3 min/ticker to ~6 min/ticker. With 8 workers and ~37 tickers, total ~28 min (was ~14 min). Acceptable for Saturday cron.

### 3.2 Bullet recommender: mark PLACE vs MONITOR levels

**File**: `tools/bullet_recommender.py`

The Level Map already shows all levels. Add a status distinction:
- Levels 1 through `active_bullets_max` that are unfilled = **>> Place** (live limit order)
- Levels beyond `active_bullets_max` = **Monitor** (proximity alert only)
- Existing placed orders stay as **Limit Order**
- Filled levels stay as **Filled**

The `active_bullets_max` from `get_ticker_pool()` determines the cutoff. Example for CIFR (optimal 1 bullet):
```
| A1 | $14.93 | ... | >> Place |      ← live order
| A2 | $14.52 | ... | Monitor |       ← proximity alert only
| A3 | $14.30 | ... | Monitor |
```

For BBAI (optimal 4 bullets):
```
| A1 | $3.50 | ... | >> Place |       ← live order
| A2 | $3.35 | ... | >> Place |       ← live order
| A3 | $3.20 | ... | >> Place |       ← live order
| A4 | $3.05 | ... | >> Place |       ← live order
| A5 | $2.90 | ... | Monitor |        ← proximity alert only
```

### 3.3 Proximity monitor: add unplaced bullet monitoring

**File**: `tools/order_proximity_monitor.py`

Currently `load_placed_orders()` only reads `portfolio.json` pending_orders. Add a second source:

```python
def load_monitored_levels():
    """Load unplaced bullet levels from wick_analysis.md for monitored tickers."""
```

This reads each tracked ticker's wick_analysis.md via `shared_wick.parse_wick_active_levels()`, gets the full level list, subtracts already-placed orders, and monitors the remaining levels for proximity alerts.

**Alert difference**:
- Placed orders: APPROACHING (2%) → IMMINENT (1%) → FILLED?
- Monitored levels: APPROACHING (2%) → **PLACE NOW** (1%) — prompts user to place the order, doesn't say "filled"

### 3.4 Reserve bullets: unchanged

Reserve bullets (`reserve_bullets_max`) operate independently of active bullet placement optimization. They target deep structural/capitulation levels (40%+ below price) and are rarely triggered. Current behavior stays:
- Reserve levels continue to appear in the Level Map as "Available" or "Available [D]"
- Reserve placement is the user's decision (typically not placed until active levels are exhausted)
- The execution sweep grid for `reserve_bullets_max` stays at `[2, 3]` — no change needed
- Reserve bullets are NOT included in the ">> Place" vs "Monitor" distinction (they're always "Available" unless manually placed)

### 3.5 Fill trigger: manual workflow (unchanged)

When a bullet fills, the user must:
1. Record the fill: `python3 tools/portfolio_manager.py fill TICKER --price X --shares N`
2. Re-run bullet recommender: `python3 tools/bullet_recommender.py TICKER`
3. The updated Level Map shows the next ">> Place" level (the one that was previously "Monitor" becomes ">> Place" if it's now within the active_bullets_max window)
4. User places the new order manually

There is NO auto-trigger after a fill. The proximity monitor will alert on the NEXT monitored level if price approaches it, giving the user time to place the order. This is the existing design — no change.

### 3.6 Saturday cron: no new entry needed

The execution sweep grid expansion (3.1) happens within the existing Stage 2 of `weekly_reoptimize.py`. No new cron job. The sweep just tests more `active_bullets_max` values within the same run. The bullet placement research sweep (`data/bullet_placement_sweep_results.json`) was one-time research — the expanded Stage 2 grid replaces it permanently.

---

## 4. User Action Required After Implementation

Once built, you need to:
1. **Cancel excess limit orders** — tickers where you have more placed than the sweep recommends
2. **The bullet recommender will show which orders to keep** — ">> Place" vs "Monitor" makes it clear

Example: If CIFR's optimal is 1 bullet but you have A1+A2+A3+A4 placed, cancel A2-A4.

---

## 5. Files Modified

| File | Change | Lines |
| :--- | :--- | :--- |
| `tools/support_parameter_sweeper.py` | Expand active_bullets_max grid [3,5,7] → [1,2,3,4,5,7] | ~1 |
| `tools/bullet_recommender.py` | Mark levels as ">> Place" vs "Monitor" based on active_bullets_max | ~15 |
| `tools/order_proximity_monitor.py` | Add `load_monitored_levels()` + "PLACE NOW" alert type | ~40 |
| `tools/shared_wick.py` | May need helper to get full level list with zones | ~0 (already has parse_wick_active_levels) |
| **Total** | | **~56** |

---

## 6. Risks

1. **Expanded grid runtime**: 288 combos vs 144 — doubles Stage 2 time. Acceptable.
2. **Alert noise**: Monitoring 5+ unplaced levels per ticker could generate many APPROACHING alerts on volatile days. Mitigation: only alert on the NEXT unplaced level (A3), not all deeper ones. Once A3 is placed and fills, start monitoring A4.
3. **Stale wick data**: If wick_analysis.md is outdated, monitored levels may be wrong. Already addressed by weekly wick refresh in Saturday pipeline.
