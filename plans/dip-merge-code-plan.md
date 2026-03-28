# Code Plan: Merge Daily Dip KPIs into Surgical Simulation

**Date**: 2026-03-29 (Sunday)
**Source**: `plans/dip-simulation-merge-analysis.md` (verified analysis)
**Goal**: One simulation run produces both surgical (support-level) AND daily dip KPIs per ticker, per period, per regime.

---

## Context

The surgical strategy has simulation-backed pool allocation via multi-period scoring (12mo/6mo/3mo/1mo). The dip strategy uses hardcoded thresholds (`recovery_rate ≥ 60%`) computed on-the-fly from 1-month yfinance data. This plan extends the surgical simulation to track dip metrics as a side-channel — same data, same loop, no separate simulation needed.

---

## Phase 1: Add dip side-channel to `backtest_engine.py` (~45 lines)

### 1.1 Add `day_open` extraction

Currently the daily loop (line 206-222) extracts High, Low, Close but NOT Open. Add Open extraction alongside existing OHLCV reads.

**Location**: Line 209 (exit check OHLCV block) and Line 307 (fill check OHLCV block)

```python
# Add alongside existing day_high/day_low/day_close extractions:
day_open = float(tk_data["Open"].loc[d])
```

### 1.2 Add dip tracking dataclass

**Location**: Near top of file, after existing imports (~line 30)

```python
@dataclass
class DailyDipMetrics:
    """Side-channel: tracks daily dip viability per ticker during surgical sim."""
    days: int = 0
    dip_days: int = 0        # days with open-to-low >= 1%
    recovery_days: int = 0   # dip days where low-to-high >= 3%
    dip_trades: int = 0
    dip_wins: int = 0        # hit +4% target
    dip_losses: int = 0      # hit -3% stop
    dip_cuts: int = 0        # EOD exit (neither target nor stop)
    dip_pnl: float = 0.0
    # Per-regime tracking
    by_regime: dict = field(default_factory=lambda: {
        "Risk-On": {"days": 0, "dip_days": 0, "wins": 0, "trades": 0, "pnl": 0.0},
        "Neutral": {"days": 0, "dip_days": 0, "wins": 0, "trades": 0, "pnl": 0.0},
        "Risk-Off": {"days": 0, "dip_days": 0, "wins": 0, "trades": 0, "pnl": 0.0},
    })
```

### 1.3 Initialize tracker in `run_simulation()`

**Location**: Line ~190, before the daily loop starts

```python
# Initialize dip side-channel (all tickers, not just positions)
dip_metrics = {tk: DailyDipMetrics() for tk in tickers}
```

### 1.4 Compute dip metrics in daily loop

**Location**: Inside the daily loop (line 192), in the fill-check section (Section 3, line 301+) where we already iterate over ALL tickers and have OHLCV data.

After extracting `day_open`, `day_low`, `day_high`, `day_close` for each ticker:

```python
# --- Dip side-channel (no impact on surgical logic) ---
dm = dip_metrics[tk]
dm.days += 1
dip_pct = (day_open - day_low) / day_open * 100 if day_open > 0 else 0
recovery_pct = (day_high - day_low) / day_low * 100 if day_low > 0 else 0

regime_bucket = dm.by_regime.get(regime, dm.by_regime["Neutral"])
regime_bucket["days"] += 1

if dip_pct >= 1.0:
    dm.dip_days += 1
    regime_bucket["dip_days"] += 1

    # Theoretical dip-buy: enter at open - 1%
    dip_entry = day_open * 0.99
    dip_target = dip_entry * 1.04
    dip_stop = dip_entry * 0.97
    dm.dip_trades += 1
    regime_bucket["trades"] += 1

    # Check stop first (conservative assumption: adverse move before favorable)
    if day_low <= dip_stop:
        dm.dip_losses += 1
        dm.dip_pnl += dip_stop - dip_entry
        regime_bucket["pnl"] += dip_stop - dip_entry
    elif day_high >= dip_target:
        dm.dip_wins += 1
        dm.dip_pnl += dip_target - dip_entry
        regime_bucket["wins"] += 1
        regime_bucket["pnl"] += dip_target - dip_entry
    else:
        dm.dip_cuts += 1
        dm.dip_pnl += day_close - dip_entry
        regime_bucket["pnl"] += day_close - dip_entry

    if recovery_pct >= 3.0:
        dm.recovery_days += 1
```

**Note**: Uses `(day_high - day_low) / day_low` for recovery (matches daily_analyzer's `low_to_high` formula, NOT `low_to_close`).

**Note**: Stop checked first — same conservative assumption as surgical sim.

### 1.5 Return dip metrics

**Location**: Line 580, change return from 3-tuple to 4-tuple

```python
# Before:
return trades, all_cycles, equity_curve

# After:
return trades, all_cycles, equity_curve, dip_metrics
```

---

## Phase 2: Pass dip metrics through `candidate_sim_gate.py` (~15 lines)

### 2.1 Unpack 4-tuple

**Location**: Line 82

```python
# Before:
trades, cycles, equity_curve = run_simulation(price_data, regime_data, cfg)

# After:
trades, cycles, equity_curve, dip_metrics = run_simulation(price_data, regime_data, cfg)
```

### 2.2 Add dip KPIs to result dict

**Location**: Line 120-132, add to the return dict

```python
# Aggregate dip metrics for this ticker
dip_kpis = None
if dip_metrics:
    dm = dip_metrics.get(ticker)
    if dm and dm.days > 0:
        dip_kpis = {
            "dip_frequency_pct": round(dm.dip_days / dm.days * 100, 1),
            "recovery_rate_pct": round(dm.recovery_days / dm.dip_days * 100, 1) if dm.dip_days > 0 else 0,
            "dip_win_rate_pct": round(dm.dip_wins / dm.dip_trades * 100, 1) if dm.dip_trades > 0 else 0,
            "dip_pnl": round(dm.dip_pnl, 2),
            "dip_trades": dm.dip_trades,
            "by_regime": {
                r: {
                    "win_rate": round(v["wins"] / v["trades"] * 100, 1) if v["trades"] > 0 else 0,
                    "pnl": round(v["pnl"], 2),
                    "trades": v["trades"],
                }
                for r, v in dm.by_regime.items() if v["days"] > 0
            },
        }

return {
    "ticker": ticker,
    "pnl": round(total_pnl, 2),
    # ... existing keys ...
    "dip_kpis": dip_kpis,  # NEW
}
```

---

## Phase 3: Include dip KPIs in `multi_period_scorer.py` (~20 lines)

### 3.1 Extract dip_kpis from simulation results

**Location**: Lines 138-142, where results are processed per period

```python
for months, result in results_by_period.items():
    pnl = result.get("pnl", 0)
    cycles = result.get("cycles", 0)
    dip = result.get("dip_kpis")  # NEW
    rate = pnl / months if months > 0 else pnl
```

### 3.2 Compute composite dip score across periods

**Location**: After the per-period loop, aggregate dip metrics using the same weighting as surgical composite

```python
# Weighted dip metrics across periods (same weights as surgical)
dip_composite = None
if any(r.get("dip_kpis") for r in results_by_period.values()):
    weighted_win = 0
    weighted_pnl = 0
    total_weight = 0
    for months, result in results_by_period.items():
        dk = result.get("dip_kpis")
        if dk and dk.get("dip_trades", 0) > 0:
            w = weights.get(months, 0)
            weighted_win += dk["dip_win_rate_pct"] * w
            weighted_pnl += dk["dip_pnl"] * w
            total_weight += w
    if total_weight > 0:
        dip_composite = {
            "dip_win_rate": round(weighted_win / total_weight, 1),
            "dip_pnl_weighted": round(weighted_pnl / total_weight, 2),
            "by_regime": results_by_period.get(12, {}).get("dip_kpis", {}).get("by_regime", {}),
        }
```

### 3.3 Include in output JSON

**Location**: Line 293-311, add to the output dict under each ticker's allocation

```python
# In allocations dict per ticker:
alloc[tk] = {
    "active_pool": active,
    "reserve_pool": reserve,
    "total_pool": active + reserve,
    "composite": composite,
    "dip_kpis": dip_composite,  # NEW
}
```

---

## Phase 4: Add graph nodes in `graph_builder.py` (~15 lines)

### 4.1 Add `{tk}:dip_kpis` leaf node

**Location**: Inside the per-ticker loop, after `{tk}:pool` node (line ~268)

```python
# Dip KPIs from multi-period simulation (if available)
pool_data = get_ticker_pool(tk)  # already called for pool node
dip_kpis_data = pool_data.get("dip_kpis") if isinstance(pool_data, dict) else None

graph.add_node(f"{tk}:dip_kpis",
    compute=lambda _, d=dip_kpis_data: d,
    reason_fn=lambda old, new, _: (
        f"Dip win rate {old.get('dip_win_rate', 0)}→{new.get('dip_win_rate', 0)}%"
        if old and new and isinstance(old, dict) and isinstance(new, dict) else ""))
```

### 4.2 Add `{tk}:dip_viable` computed node

```python
graph.add_node(f"{tk}:dip_viable",
    compute=lambda i, t=tk: _check_dip_viable(
        i.get(f"{t}:dip_kpis"), i.get("regime"), i.get(f"{t}:catastrophic"),
        i.get(f"{t}:verdict")),
    depends_on=[f"{tk}:dip_kpis", "regime", f"{tk}:catastrophic", f"{tk}:verdict"],
    reason_fn=lambda old, new, _: f"Dip viability {old}→{new}" if old != new else "")
```

### 4.3 Add helper function

```python
def _check_dip_viable(dip_kpis, regime, catastrophic, verdict):
    """Determine if ticker is viable for daily dip strategy.

    Combines simulation evidence + current ticker state from graph.
    """
    # Block if main strategy says stop buying
    if catastrophic in ("HARD_STOP", "EXIT_REVIEW"):
        return "BLOCKED"
    if isinstance(verdict, tuple) and verdict[0] in ("EXIT", "REDUCE"):
        return "BLOCKED"

    # No simulation data — fall back to unknown
    if not dip_kpis or not isinstance(dip_kpis, dict):
        return "UNKNOWN"

    win_rate = dip_kpis.get("dip_win_rate", 0)

    # Check regime-specific performance
    regime_data = dip_kpis.get("by_regime", {}).get(regime, {})
    regime_win = regime_data.get("win_rate", win_rate)  # fallback to overall

    if win_rate >= 50 and regime_win >= 40:
        return "YES"
    elif win_rate >= 40:
        return "CAUTION"
    else:
        return "NO"
```

---

## Phase 5: Use dip_viable in daily_analyzer.py (~15 lines)

### 5.1 Pass graph to dip watchlist function

**Location**: Line 1652, change the call to include graph

```python
# Before:
print_daily_fluctuation_watchlist(regime=regime)

# After (in print_detail_sections):
print_daily_fluctuation_watchlist(regime=regime, graph=graph)
```

### 5.2 Modify `print_daily_fluctuation_watchlist()` signature and filter

**Location**: Line 519, update signature

```python
# Before:
def print_daily_fluctuation_watchlist(regime="Neutral"):

# After:
def print_daily_fluctuation_watchlist(regime="Neutral", graph=None):
```

### 5.3 Add graph-based filtering

**Location**: Line 596, after the hardcoded threshold check, add graph-based viability check

```python
# Existing hardcoded gate (keep as fallback when no graph):
if med_range < 3.0 or recovery_2 < 60:
    continue

# Graph-based gate (when simulation data available):
dip_status = None
if graph is not None:
    dip_node = graph.nodes.get(f"{tk}:dip_viable")
    if dip_node and dip_node.value:
        dip_status = dip_node.value
        if dip_status == "BLOCKED":
            # Blocked by catastrophic or verdict — show with reason
            blocked_tickers.append(tk)
            continue
        elif dip_status == "NO":
            continue  # simulation says dip play doesn't work for this ticker
```

### 5.4 Show dip viability in output table

Add a column showing simulation-backed viability:

```python
# In the table row, append dip status if available:
status_str = ""
if dip_status == "BLOCKED":
    status_str = "BLOCKED"
elif dip_status == "CAUTION":
    status_str = "CAUTION (low win rate)"
elif dip_status == "YES":
    status_str = ""  # good — no annotation needed
elif dip_status == "UNKNOWN":
    status_str = "No sim data"
```

---

## Phase 6: Update `get_state_for_persistence()` in `graph_builder.py` (~5 lines)

**Location**: In the per-ticker state dict, add dip_kpis and dip_viable

```python
state["tickers"][tk] = {
    # ... existing 10 fields ...
    "dip_viable": n.get(f"{tk}:dip_viable", _stub()).value,  # NEW
}
```

---

## Files Modified

| File | Action | Lines Changed |
| :--- | :--- | :--- |
| `tools/backtest_engine.py` | Add DailyDipMetrics, day_open extraction, side-channel in loop, 4-tuple return | ~45 |
| `tools/candidate_sim_gate.py` | Unpack 4-tuple, aggregate dip metrics, add to result dict | ~15 |
| `tools/multi_period_scorer.py` | Extract dip_kpis, compute weighted composite, include in output JSON | ~20 |
| `tools/graph_builder.py` | Add dip_kpis leaf, dip_viable computed node, _check_dip_viable helper, persistence field | ~20 |
| `tools/daily_analyzer.py` | Pass graph to dip watchlist, add viability filter, show status in output | ~15 |
| **Total** | | **~115** |

---

## Backward Compatibility

### Breaking change: `run_simulation()` 3-tuple → 4-tuple

All callers must update:
1. `candidate_sim_gate.py` line 82 — updated in Phase 2
2. `backtest_reporter.py` — check if it calls run_simulation directly. If so, update.
3. Workflow agents — they call candidate_sim_gate, not run_simulation directly. No change needed.

### Fallback when no dip data

- `dip_kpis = None` when simulation didn't produce dip data
- `dip_viable = "UNKNOWN"` when no simulation data available
- Hardcoded `recovery_rate ≥ 60%` still applies as fallback gate
- Graph node returns None gracefully via `_stub()`

---

## Verification

After implementation:

1. [ ] `python3 tools/backtest_engine.py` (if it has a main) — produces dip_kpis in output
2. [ ] `python3 tools/candidate_sim_gate.py CLSK` — result dict includes `dip_kpis` key
3. [ ] Run multi-period scorer — `multi-period-results.json` includes `dip_kpis` per ticker
4. [ ] `python3 tools/graph_builder.py --test` — `CLSK:dip_kpis` and `CLSK:dip_viable` nodes exist
5. [ ] `python3 tools/daily_analyzer.py --no-deploy` — dip watchlist shows BLOCKED for IONQ/USAR
6. [ ] Run daily analyzer twice — graph_state.json includes `dip_viable` field per ticker
7. [ ] Existing surgical simulation results unchanged (zero regression)
8. [ ] `python3 -m pytest tests/test_graph.py -v` — all 93 existing tests still pass

---

## Implementation Order

1. **Phase 1** (backtest_engine.py) — add side-channel. Test: existing surgical results unchanged.
2. **Phase 2** (candidate_sim_gate.py) — pass through dip_kpis. Test: result dict has key.
3. **Phase 3** (multi_period_scorer.py) — composite dip score. Test: output JSON has dip_kpis.
4. **Phase 4** (graph_builder.py) — graph nodes. Test: `--test` shows dip nodes.
5. **Phase 5** (daily_analyzer.py) — dip watchlist reads graph. Test: BLOCKED tickers excluded.
6. **Phase 6** (persistence) — save dip_viable. Test: graph_state.json has field.
