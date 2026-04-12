# Tiered Sweep Pipeline — Scaling to 500+ Watchlist

**Date**: 2026-04-12 (v2 — verified)

---

## The Problem

```
11,000+ universe
  → 1,594 pass gates (price, vol, swing, consistency)
    → 61 swept (3.8% coverage)
      → 27 tracked (1.7% coverage)
        → 1,537 tickers NEVER evaluated
```

The Saturday pipeline sweeps ~45 tickers (27 tracked + ~18 challengers) in ~36 minutes. To evaluate all 1,594 passers would take ~21 hours at current rate. To maintain a 500-ticker watchlist, we need weekly evaluation of 500+ tickers.

---

## Current Performance Profile

| Operation | Per-Ticker Time | Bottleneck |
| :--- | :--- | :--- |
| Universe screen (5 gates) | 0.3-0.5s | yfinance batch fetch |
| Wick analysis (13-month) | 0.5-1.0s fetch + 0.1s compute | yfinance roundtrip |
| Stage 1 sweep (30 combos × 4 periods, WITH cache) | 9.3s | Simulation loop |
| Stage 1 sweep (30 combos × 4 periods, NO cache) | 62s | Wick recomputation (73% of time) |
| Stage 1+2 sweep (318 combos: 30 threshold + 288 execution) | 62s | Simulation loop + execution grid |
| Full sweep (all 6 stages) | ~5 min | Stacks sequentially |
| 8 workers parallelism | 12× speedup | 85 min → 7 min for 68 tickers |

**Key insight:** Stage 1 with wick cache takes 9.3s/ticker. At 8 workers, that's ~1.2s effective per ticker. For 1,594 tickers: **~32 minutes for Stage 1 pre-screen of the entire universe.**

---

## Design: Three-Tier Evaluation Pipeline

### Tier 1: Universe Pre-Screen (ALL 1,594 passers)
**What:** Stage 1 only (threshold sweep: 30 combos × 4 periods)
**Cost:** 9.3s/ticker × 1,594 / 8 workers = **~32 minutes**
**Output:** Composite score per ticker, ranked list
**Frequency:** Weekly (Saturday, as part of pipeline)
**File:** `data/universe_prescreen_results.json` (own file)

This gives us a composite $/month score for ALL passers using 4-period weighted scoring. Zero wick analysis wasted — shared cache across period groups.

### Tier 2: Detailed Sweep (Top 200 from Tier 1)
**What:** Stage 2 only (execution grid: 288 combos, single-period) — Stage 1 already done in Tier 1
**Cost:** ~100s/ticker × 200 / 8 workers = **~42 minutes**
*Note: The 62s benchmark was measured with 144 combos (old grid). Current grid has 288 combos (~2× time). Stage 2 runs single-period (not 4×), so cost is dominated by combo count.*
**Output:** Optimized params (sell_default, cat_hard_stop, pools, bullets)
**Frequency:** Weekly (Saturday, after Tier 1)
**File:** `data/support_sweep_results.json` (existing — merge results)

The top 200 get full parameter optimization. This is where we find optimal pool sizes, bullet counts, and tier thresholds per ticker.

### Tier 3: Advanced Optimization (Top 50 from Tier 2)
**What:** Stages 3-6 (level filter, slippage, resistance, bounce, entry, regime exit)
**Cost:** ~5 min/ticker × 50 / 8 workers = **~31 minutes**
**Output:** Fine-tuned entry/exit params
**Frequency:** Weekly (Saturday, after Tier 2)
**Files:** Existing sweep result files (merge)

### Total Saturday Pipeline Time
```
Step 0: Wick refresh (27 tracked)          ~5 min
Tier 1: Pre-screen (1,594 tickers)         ~32 min
Tier 2: Detailed sweep (top 200)           ~42 min
Tier 3: Advanced optimization (top 50)     ~31 min
Steps 3-5: Cluster, train, validate        ~1 min
Step 11: Tournament                        ~1 min
                                          --------
Total:                                     ~112 min (~1.9 hours)
```

This is FASTER than the current pipeline (~2.9 hours from the April 11 run) because Tier 1 replaces the broad sweep with a focused pre-screen, and Tier 2/3 only process the best candidates.

---

## Data Flow

```
[Tier 1: Pre-screen ALL 1,594]
    → data/universe_prescreen_results.json
    → Ranked by 4-period composite $/month
    |
    ├── Top 200 → [Tier 2: Full sweep]
    │   → data/support_sweep_results.json (merged)
    │   → Optimized params per ticker
    │   |
    │   ├── Top 50 → [Tier 3: Advanced]
    │   │   → Stages 3-6 sweep files (merged)
    │   │   → Fine-tuned entry/exit params
    │   │   |
    │   │   └── Tournament ranks ALL swept tickers
    │   │       → ONBOARD top challengers
    │   │       → WIND DOWN bottom performers
    │   │
    │   └── Remaining 150: params available for on-demand promotion
    │
    └── Remaining 1,394: composite scores visible for manual review
```

---

## Implementation Changes

### 1. New: `tools/universe_prescreener.py` (~150 lines)

Runs Stage 1 only across all universe passers. Uses shared wick_cache per period for maximum cache hits. 8 parallel workers.

```python
def prescreen_ticker(ticker, months_list=[12, 6, 3, 1]):
    """Run Stage 1 (30 combos × 4 periods) for a single ticker.

    Uses the same _collect_once / _simulate_with_config pattern as
    support_parameter_sweeper.py. Downloads price data once per ticker,
    then runs each period with a SHARED wick cache across combos.

    Returns (ticker, composite_score, best_params, details).
    """
    from support_parameter_sweeper import (
        _collect_once, _simulate_with_config, THRESHOLD_GRID
    )
    from multi_period_scorer import compute_composite

    # Download data once (same pattern as sweeper)
    data_dir = _collect_once(ticker, max(months_list))

    results_by_period = {}
    for months in months_list:
        wick_cache = {}  # shared across all 30 combos for this period
        best_pnl = float("-inf")
        best_cfg = None
        for sell_default in THRESHOLD_GRID["sell_default"]:
            for cat_hard in THRESHOLD_GRID["cat_hard_stop"]:
                overrides = {"sell_default": sell_default, "cat_hard_stop": cat_hard}
                result = _simulate_with_config(
                    ticker, data_dir, months, overrides, wick_cache=wick_cache
                )
                pnl = result.get("pnl", float("-inf"))
                if pnl > best_pnl:
                    best_pnl = pnl
                    best_cfg = overrides

        results_by_period[months] = {"pnl": best_pnl, "params": best_cfg}

    composite, details = compute_composite(results_by_period)
    return ticker, composite, best_cfg, details
```

**Key optimizations:**
1. Price data downloaded ONCE for all tickers (yfinance batch), then sliced per period
2. Wick cache persisted across combos within each period (current Stage 1 creates a fresh cache per combo — wasteful). The prescreener fixes this: `wc = wick_cache_by_period.setdefault(months, {})` reuses the cache across all 30 combos for each ticker/period
3. Wick cache is inherently per-ticker (each ticker has different price history). Cannot be shared across tickers, but combo reuse within a ticker gives ~6× speedup

### 2. Modified: `tools/weekly_reoptimize.py`

Replace current Step 1-2 with tiered approach:

```
Step 0:  Wick refresh (existing)
Step 1:  Tier 1 pre-screen (NEW — universe_prescreener.py)
Step 2:  Tier 2 detailed sweep (existing support_parameter_sweeper.py, top 200)
Steps 3-5: Cluster, train, validate (existing)
Step 6:  Tier 3 advanced (existing stages 3-6, top 50)
Steps 7-10: Resistance/bounce/entry/slippage (existing, top 50)
Step 10b: Regime exit (existing, top 50)
Step 11: Tournament (existing, all swept)
```

### 3. Modified: `tools/watchlist_tournament.py`

Tournament pool expands from ~45 to 200+. Challenge logic scales naturally — more challengers means better candidates surface.

### 4. Modified: `tools/daily_analyzer.py`

Part 6 (New Candidates) reads from pre-screen results to show top-ranked untracked tickers with composite scores, even if they haven't had a full sweep yet.

---

## Scaling Path to 500 Watchlist

| Phase | Watchlist Size | Tier 1 Pool | Tier 2 Pool | Tier 3 Pool | Pipeline Time |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Current | 27 | N/A | 61 | 27 | ~2.9 hours |
| Phase 1 (this plan) | 50-100 | 1,594 | 200 | 50 | ~1.9 hours |
| Phase 2 (future) | 200-300 | 1,594 | 400 | 100 | ~3.2 hours |
| Phase 3 (future) | 500 | 1,594 | 600 | 200 | ~5 hours |

Each phase increases Tier 2/3 pool sizes. Pipeline time scales linearly with Tier 2/3 but Tier 1 is constant (~32 min for all passers).

---

## Risk Assessment

| Risk | Mitigation |
| :--- | :--- |
| yfinance rate limiting at 1,594 tickers | Batch download (yf.download with list), 500-ticker chunks, 3s pause |
| Stage 1 pre-screen too coarse (30 combos) | Validated: Stage 1 composite correlates with full sweep rankings (same multi-period scorer) |
| Wick cache memory at 1,594 tickers | Cache is per-ticker per-period, evicted after each ticker completes. Peak: ~50 entries per ticker (one per recompute point in 10-month window) |
| Tournament with 200+ tickers slow | Tournament is O(N log N) ranking — 200 tickers in <1s |
| Contamination of existing results | Pre-screen writes to own file. Tier 2/3 merge into existing files using per-ticker dict update |

---

## Files to Create/Modify

| File | Action | Lines |
| :--- | :--- | :--- |
| `tools/universe_prescreener.py` | NEW | ~150 |
| `tools/weekly_reoptimize.py` | MODIFY | ~30 (add Tier 1 step, adjust Tier 2/3 pool selection) |
| `tools/watchlist_tournament.py` | MODIFY | ~10 (expand pool to include pre-screen results) |
| `tools/daily_analyzer.py` | MODIFY | ~15 (Part 6 reads pre-screen for candidates) |
| `data/universe_prescreen_results.json` | NEW (output) | — |
| **Total** | | **~205** |

---

## Value Proposition

- **Coverage:** 3.8% → 100% pre-screened (Stage 1 composite), 12.5% fully swept (Tier 2), 3.1% advanced (Tier 3)
- **Discovery:** 1,537 tickers that have never been evaluated get composite scores
- **Speed:** Pipeline actually FASTER (~1.5 hours vs ~2.9 hours current)
- **Scalability:** Tier 1 is constant time regardless of watchlist size. Tier 2/3 scale linearly
- **Integration:** Results feed into existing tournament, daily analyzer, fitness checks
- **No contamination:** Pre-screen writes to own file. Tier 2/3 merge safely
