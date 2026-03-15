# Phase 2: Core Optimizer — Optimal Profit Target % Per Ticker
*Status: Not Started | Depends on: Nothing (self-contained backtest) | Enables: Phase 4 (adaptive sells)*
*Optional validation (compare simulated vs actual) depends on Phase 1 cycle_history.json.*

**Key constraint:** Phase 2 is 100% mechanical — ZERO qualitative/LLM work. Every output is deterministic from input data.

## Goal
Answer: What is the optimal sell target % for each ticker that maximizes total profit over time?
Currently sell_target_calculator.py scores resistance levels near three fixed math targets
(4.5%/6.0%/7.5%) with 6.0% as the scoring anchor. Phase 2 answers: should CLSK use 3.5%
instead? Should LUNR use 4.0%?

**Relationship to sell_target_calculator.py:** Phase 2 does NOT modify sell_target_calculator.py.
It produces an optimal target % per ticker. Phase 4 will later feed this as a dynamic input
replacing the hardcoded MATH_TARGETS anchor. Phase 2 purely answers "what target % maximizes profit?"

## Deliverable
`python3 tools/target_optimizer.py CLSK` — backtests 2%-10% targets, outputs optimal %, profit curve, cycle frequency analysis.

## Gaps Addressed

| # | Gap | Impact | Effort |
| :--- | :--- | :--- | :--- |
| 9.3 | Historical backtesting of target %s | **Critical** | Medium |
| 9.1 | Cycle frequency analysis by target % | **Critical** | Medium |
| 9.2 | Per-ticker optimal target % | **Critical** | Medium |
| 9.4 | Frequency-magnitude tradeoff visualization | High | Low |
| 9.6 | Compound effect modeling | High | Medium |

### Existing Infrastructure (do NOT rebuild)

| Asset | Location | Reuse How |
| :--- | :--- | :--- |
| `fetch_history(ticker, months=13)` | `tools/wick_offset_analyzer.py:200` | 13-month OHLCV via yfinance. Import directly. |
| `find_price_action_supports(hist, current_price)` | `:313` | Clusters daily Lows, min 3 touches. Returns `[{price, touches, source}]`. Note: requires `current_price` arg. |
| `find_hvn_floors(hist, n_bins=40)` | `:277` | Volume profile HVN floors, 180-day decay, 70th pctl. Returns `[{price, volume, source}]`. |
| `merge_levels(hvn_floors, pa_supports, current_price)` | `:347` | Dedup within 2%, keeps below current_price, sorts descending. |
| `find_approach_events(hist, level, proximity_pct=8.0)` | `:375` | Returns `[{start, min_low, offset_pct, held}]` per approach. |
| `classify_level(hold_rate, gap_pct, active_radius, approaches)` | `:238` | Zone + Tier classification. <3 approaches caps at Half. |
| `compute_effective_tier(raw_tier, decayed_tier)` | `:260` | Effective tier with promotion floor. Returns `(effective_tier, promoted)`. |
| `_monthly_swings(hist)` | `:208` | Per-month swing % list. Returns numpy array or None if <3 months. Needed internally by `analyze_stock_data` for recency-weighted active_radius. |
| `compute_monthly_swing(hist)` | `:221` | Median monthly (high-low)/low %. Calls `_monthly_swings` internally. |
| `analyze_stock_data(ticker, hist=None)` | `:535` | **Primary reuse target.** Full per-stock analysis: finds supports, computes approach events, hold rates, wick offsets, decayed tiers (90-day half-life), recency-weighted active_radius, effective tiers, and bullet plan with sizing. Returns `(data_dict, error_str)`. `data_dict["bullet_plan"]["active"]` = sized levels ready for simulation. Passing `hist` skips internal fetch. Returns `(None, "reason")` on failure. |
| `compute_pool_sizing(levels, pool_budget, pool_name)` | `:108` | Pool-distributed sizing. **Expects `recommended_buy` key on each level, not `buy_at`.** Returns `[{shares, cost, dollar_alloc}]`. |
| `load_capital_config()` | `:46` | Returns `{active_pool, reserve_pool, active_bullets_max, reserve_bullets_max}`. |
| `load_tickers_from_portfolio()` | `:37` | Sorted list of all tickers for `--all` mode. |
| `is_trading_day(d)` | `tools/trading_calendar.py` | US market trading day check. |
| `as_of_date_label(d)` | `tools/trading_calendar.py` | Data freshness label for report header. |
| `portfolio.json capital` | Root | `{per_stock_total: 600, active_pool: 300, reserve_pool: 300, active_bullets_max: 5}` |

## Detailed Requirements

### 1A. Support Level Computation (once per ticker, before sweep)

**Uses `analyze_stock_data(ticker, hist)` (`:535`) — the canonical implementation.** Do NOT
reimplement level-finding, approach analysis, wick offsets, decayed tiers, or active_radius.
That function already computes all of it (including recency-weighted active_radius at `:604-614`
and decayed hold rate with 90-day half-life at `:584-601`) and prevents divergence.

```python
hist = fetch_history(ticker, months=13)
data, err = analyze_stock_data(ticker, hist)
if err:
    return None, err  # skip ticker

current_price = data["current_price"]
capital = load_capital_config()
```

`data["levels"]` contains per-level: `support_price`, `recommended_buy`, `effective_tier`,
`hold_rate`, `decayed_tier`, `gap_pct`, `zone`, `source`, `events[]`.

`data["bullet_plan"]["active"]` contains the sized active bullets. **Key field name:**
`_compute_bullet_plan` emits `buy_at` (not `recommended_buy`). Each entry has: `buy_at`,
`shares`, `cost`, `tier`, `hold_rate`, `support_price`, `zone`, `raw_tier`, `approaches`.
Already filtered (Skip removed, capped at `active_bullets_max`, sized via `compute_pool_sizing`).

**Post-processing for simulation:**
1. Extract `sim_levels = data["bullet_plan"]["active"]` — levels with sizing already computed
2. Filter is redundant (`_compute_bullet_plan` already excludes None and >= current_price) — skip
3. Sort descending by `buy_at` (highest = B1)
4. `active_pool = capital["active_pool"]`
5. Prepare `base_levels` for compound mode re-sizing (maps `buy_at` → `recommended_buy` for
   `compute_pool_sizing`, preserves tier metadata for re-attachment after re-sizing):
   ```python
   base_levels = [{"recommended_buy": lv["buy_at"], "effective_tier": lv["tier"],
                   "hold_rate": lv["hold_rate"], "support_price": lv["support_price"]}
                  for lv in sim_levels]
   ```
   **Note:** `_bullet_entry` does NOT emit `"source"`. The `source` field ("PA"/"HVN") lives
   in `data["levels"]` only. For JSON output's `support_levels_used`, join via `support_price`
   from `data["levels"]` at report time — NOT from sim_levels or base_levels.

This replaces the prior 11-step manual reimplementation. Any bug fixes or formula changes
to `analyze_stock_data` automatically propagate to the optimizer.

**Forward-looking bias:** Static levels computed from full 13-month history. Support clusters
(3+ touches) are structural and change slowly. Expected bias: overstates win rate by ~5-10%.
Rolling-window enhancement (Phase 2.1) would recompute monthly. Start static; bias is
documented and bounded.

---

### 1B. Simulation Engine (per target %)

**State variables:**
```python
shares_held = 0; avg_cost = 0.0; total_cost = 0.0
entry_day_idx = None; cycle_low = None
cooldown_remaining = 0; cumulative_profit = 0.0
pool_budget = active_pool  # tracks current pool; updated in compound mode after each exit
fills = []; unfilled_levels = list(sim_levels)
cycles = []
```

**Per-day loop** (iterate hist rows chronologically):
```python
for day_idx in range(len(hist)):
    day = hist.iloc[day_idx]  # Open, High, Low, Close
    if cooldown_remaining > 0:
        cooldown_remaining -= 1
        continue

    # ENTRIES — process regardless of position state (adds bullets to open position)
    for level in sorted(unfilled_levels, key=lambda l: l["buy_at"], reverse=True):
        if day["Low"] <= level["buy_at"]:
            fill_price = min(day["Open"], level["buy_at"])
            shares = level["shares"]
            total_cost += fill_price * shares
            shares_held += shares
            avg_cost = total_cost / shares_held
            if entry_day_idx is None:
                entry_day_idx = day_idx
                cycle_low = day["Low"]
            fills.append({"price": fill_price, "shares": shares, "day_idx": day_idx})
            unfilled_levels = [l for l in unfilled_levels if l is not level]
            cycle_low = min(cycle_low, day["Low"])

    # EXIT — check after entries
    if shares_held > 0:
        cycle_low = min(cycle_low, day["Low"])
        target_price = avg_cost * (1 + target_pct / 100)
        if day["High"] >= target_price:
            exit_price = target_price  # limit sell fills at target
            profit = (exit_price - avg_cost) * shares_held
            cycles.append({
                "entry_day_idx": entry_day_idx,
                "exit_day_idx": day_idx,
                "fills": list(fills),           # [{price, shares, day_idx}, ...]
                "avg_cost": avg_cost,
                "exit_price": exit_price,
                "shares": shares_held,
                "profit": round(profit, 2),
                "profit_pct": round((exit_price - avg_cost) / avg_cost * 100, 2),
                "won": profit > 0,
                "cycle_days": day_idx - entry_day_idx + 1,
                "cycle_low": cycle_low,
                "max_drawdown_pct": round((cycle_low - avg_cost) / avg_cost * 100, 2),
                "timeout": False,
                "open_at_end": False,
                "pool_budget": pool_budget if compound else active_pool,
            })
            cumulative_profit += profit
            # Reset
            shares_held = 0; avg_cost = 0.0; total_cost = 0.0
            entry_day_idx = None; cycle_low = None; fills = []
            cooldown_remaining = 1
            unfilled_levels = list(sim_levels)  # reset for next cycle
            # Compound mode: recompute sizing
            if compound:
                pool_budget = active_pool + cumulative_profit
                if pool_budget <= 0:
                    break  # pool exhausted
                sim_levels = compute_pool_sizing(base_levels, pool_budget, "active")
                # Translate back: compute_pool_sizing returns recommended_buy; sim uses buy_at
                # Also re-attach tier metadata from base_levels (lost during pool_sizing)
                for lv, base in zip(sim_levels, base_levels):
                    lv["buy_at"] = lv.pop("recommended_buy")
                    lv["tier"] = base["effective_tier"]
                    lv["support_price"] = base["support_price"]
                unfilled_levels = list(sim_levels)

    # TIMEOUT — timeout_days trading days stuck
    if shares_held > 0 and (day_idx - entry_day_idx + 1) > timeout_days:
        cycle_low = min(cycle_low, day["Low"])  # refresh before recording
        exit_price = day["Close"]  # force-close at close
        profit = (exit_price - avg_cost) * shares_held
        cycles.append({
                "entry_day_idx": entry_day_idx,
                "exit_day_idx": day_idx,
                "fills": list(fills),
                "avg_cost": avg_cost,
                "exit_price": exit_price,
                "shares": shares_held,
                "profit": round(profit, 2),
                "profit_pct": round((exit_price - avg_cost) / avg_cost * 100, 2),
                "won": profit > 0,
                "cycle_days": day_idx - entry_day_idx + 1,
                "cycle_low": cycle_low,
                "max_drawdown_pct": round((cycle_low - avg_cost) / avg_cost * 100, 2),
                "timeout": True,
                "open_at_end": False,
                "pool_budget": pool_budget if compound else active_pool,
            })
        # Reset (same as normal exit)
        cumulative_profit += profit
        shares_held = 0; avg_cost = 0.0; total_cost = 0.0
        entry_day_idx = None; cycle_low = None; fills = []
        cooldown_remaining = 1
        unfilled_levels = list(sim_levels)
        if compound:
            pool_budget = active_pool + cumulative_profit
            if pool_budget <= 0:
                break
            sim_levels = compute_pool_sizing(base_levels, pool_budget, "active")
            for lv, base in zip(sim_levels, base_levels):
                lv["buy_at"] = lv.pop("recommended_buy")
                lv["tier"] = base["effective_tier"]
                lv["support_price"] = base["support_price"]
            unfilled_levels = list(sim_levels)

# POST-LOOP: record open position at end of data
if shares_held > 0:
    last_close = hist.iloc[-1]["Close"]
    unrealized = (last_close - avg_cost) * shares_held
    cycles.append({
        "entry_day_idx": entry_day_idx,
        "exit_day_idx": len(hist) - 1,
        "fills": list(fills),
        "avg_cost": avg_cost,
        "exit_price": last_close,  # mark-to-market, not realized
        "shares": shares_held,
        "profit": round(unrealized, 2),
        "profit_pct": round((last_close - avg_cost) / avg_cost * 100, 2),
        "won": None,  # unrealized — not counted in win_rate
        "cycle_days": len(hist) - 1 - entry_day_idx + 1,
        "cycle_low": cycle_low,
        "max_drawdown_pct": round((cycle_low - avg_cost) / avg_cost * 100, 2),
        "timeout": False,
        "open_at_end": True,
        "pool_budget": pool_budget,
    })
```

---

### 1C. Simulation Formulas

| Formula | Definition |
| :--- | :--- |
| `fill_price` | `min(day_open, level["buy_at"])` — gap-down fills at open, otherwise at limit |
| `avg_cost` | `total_cost / shares_held` where `total_cost = sum(fill_price_i * shares_i)` |
| `target_price` | `avg_cost * (1 + target_pct / 100)` |
| `exit_price` | `target_price` for normal exit, `day_close` for timeout |
| `profit` | `(exit_price - avg_cost) * shares_held` |
| `profit_pct` | `(exit_price - avg_cost) / avg_cost * 100` |
| `cooldown` | 1 trading day (skip 1 hist row after exit) |
| `timeout` | `day_idx - entry_day_idx + 1 > timeout_days` (default 30, CLI `--timeout`) |
| `max_concurrent` | 1 cycle at a time (no overlapping positions) |

### 1D. Multiple Fills Same Day

Process levels from **highest `buy_at` to lowest** (B1 before B2). Each fill updates `avg_cost` immediately. All fills happen before exit check. Exit uses final `avg_cost`.

### 1E. Pool Management

| Mode | Pool after cycle N exit | Sizing |
| :--- | :--- | :--- |
| Simple (default) | `active_pool` (constant $300) | Computed once at start |
| Compound (`--compound`) | `active_pool + cumulative_profit` | Recomputed after each exit via `compute_pool_sizing()` |

**Pool exhaustion guard (compound):** If `pool_budget <= 0`, simulation stops. Set `pool_exhausted = True`
on the simulation return dict (see JSON schema `results[].pool_exhausted`). Not a per-cycle field —
it's a simulation-level flag indicating early termination.
**Guard ordering is load-bearing:** The `pool_budget <= 0` check MUST precede `compute_pool_sizing()`.
If called with `pool_budget <= 0`, `compute_pool_sizing` returns 1-share fallback entries (not empty),
which would create phantom trades instead of a clean stop.

---

### 2. Cycle Frequency Analysis (Gap 9.1)

Output table generated mechanically from simulation `results[]` — no fabricated examples.

| Target % | Cycles (13mo) | Cycles/Month | Avg Days | Win Rate | Total Profit | Timeouts |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |

Each row populated from `results[i]`. Peak of "Total Profit" = optimal target.
"Timeouts" column shows 30-day timeout hits — high count means target is unreachable.

---

### 3. Per-Ticker Optimal Target (Gap 9.2)

`--all` mode runs optimizer for every ticker from `load_tickers_from_portfolio()`.

| Ticker | Optimal % (Simple) | Profit (Simple) | Optimal % (Compound) | Profit (Compound) | Cycles | Timeouts |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |

Sorted by simple profit descending. Skip tickers with errors (print reason, don't crash).

**No "Current Target" column:** sell_target_calculator uses a 3-tier system with resistance
scoring — comparing against a single optimal % is misleading. Phase 4 handles integration.

---

### 4. Profit Curve Visualization (Gap 9.4)

Text bar chart generated from results[]:
```python
max_profit = max(r["total_profit_simple"] for r in results)
if max_profit <= 0:
    print("No profitable cycles — bar chart skipped.")
else:
    for r in results:
        filled = round(r["total_profit_simple"] / max_profit * 30)
        bar = "█" * filled + "░" * (30 - filled)
        marker = " <-- OPTIMAL" if r == optimal else ""
        print(f"{r['target_pct']:4.1f}%  | ${r['total_profit_simple']:>7.2f} | {bar}{marker}")
```

Both simple and compound curves printed when `--compound` used.

---

### 5. Compound Effect Modeling (Gap 9.6)

| Mode | Pool after cycle N | Notes |
| :--- | :--- | :--- |
| Simple | `active_pool` (constant) | Sizing stays fixed |
| Compound | `active_pool + sum(cycle[i].profit for i in 0..N)` | Sizing grows via `compute_pool_sizing()` |

**Compounding bonus:** `total_profit_compound - total_profit_simple` for each target %.
The target maximizing compound profit may differ from simple — both optima reported.

**Pool exhaustion:** If compound `pool_budget <= 0`, simulation halts. Recorded in output.

---

## Simulation Edge Cases

1. **Gap-down:** `fill_price = min(day_open, buy_at)`. If open < buy_at, fill at open (worse than limit).
2. **Same-day entry+exit:** Process entries first, then exit check. Valid 1-trading-day cycle.
3. **Timeout:** `day_idx - entry_day_idx + 1 > timeout_days` (default 30, CLI `--timeout`) → force-close at `day_close`. Can still be a win if close > avg_cost.
4. **Partial cascade:** Each level checked independently. Only levels where `day_low <= buy_at` fill.
5. **No levels found:** Skip ticker. Print `"Skipped {TICKER}: no qualifying support levels"`.
6. **Insufficient data:** `len(hist) < 60` → skip. Print reason.
7. **Open at end of data:** Do NOT force-close. Record `open_at_end: true`. Only count completed cycles in metrics.

---

## Metric Formulas

**Formal filter binding (compute once, reuse for all metrics):**
```python
completed = [c for c in cycles if not c.get("open_at_end")]
```
All metrics below use `completed`. The `open_at_end` record has `won: None` which would
corrupt boolean filters — the formal binding ensures it is excluded consistently.

| Metric | Formula | Zero-guard |
| :--- | :--- | :--- |
| `cycles_completed` | `len(completed)` | 0 is valid |
| `cycles_per_month` | `cycles_completed / (len(hist) / 21)` | 0.0 if no cycles |
| `avg_cycle_days` | `mean(exit_day_idx - entry_day_idx + 1 for completed)` (trading days) | `null` if 0 cycles |
| `win_rate` | `len([c for c in completed if c["won"]]) / len(completed) * 100` | 0.0 if 0 cycles |
| `total_profit_simple` | `sum(c["profit"] for completed)` in simple mode | 0.0 |
| `total_profit_compound` | `sum(c["profit"] for completed)` in compound mode | 0.0 |
| `max_drawdown_pct` | `min(c["max_drawdown_pct"] for c in completed)` — worst intra-cycle drawdown from cost basis (uses `completed`, excludes open_at_end) | 0.0 if none |
| `longest_cycle_days` | `max(exit_day_idx - entry_day_idx + 1 for completed)` | 0 |
| `timeout_cycles` | `len([c for c in completed if c.get("timeout")])` | 0 |

---

## Output Schema

### JSON (`tickers/{TICKER}/target_optimization.json`)

```json
{
  "ticker": "CLSK",
  "run_date": "2026-03-15",
  "data_period": {"start": "...", "end": "...", "trading_days": 252},
  "forward_looking_bias": "static",
  "support_levels_used": [
    {"support_price": 10.50, "buy_at": 10.22, "hold_rate": 67.0,
     "tier": "Full", "shares": 6, "source": "PA"}
  ],
  "capital_config": {"active_pool": 300, "active_bullets_max": 5, "levels_used": 4},
  "results": [
    {"target_pct": 2.0, "cycles_completed": 0, "cycles_per_month": 0.0,
     "avg_cycle_days": null, "win_rate": 0.0, "total_profit_simple": 0.0,
     "total_profit_compound": 0.0, "max_drawdown_pct": 0.0,
     "longest_cycle_days": 0, "timeout_cycles": 0,
     "open_at_end": false, "pool_exhausted": false}
  ],
  "optimal": {
    "simple": {"target_pct": 3.5, "total_profit": 325.50},
    "compound": {"target_pct": 3.0, "total_profit": 412.80}
  },
  "open_position_at_end": null
}
```

- `avg_cycle_days`: `null` when 0 cycles
- `results[].open_at_end`: **boolean** per target-% row — `true` if simulation at that target %
  ended with an open (unrealized) position. Used for filtering: rows with `open_at_end: true`
  have an unrealized last cycle not counted in `win_rate` or `cycles_completed`.
- `open_position_at_end`: **object or null** — top-level, populated once from the *last* simulation
  run (the optimal target %). Contains `{"avg_cost": X, "shares": N, "unrealized_pct": Y}` or `null`.
  This is the detail view of the open position; `results[].open_at_end` is the flag.
- `results[].pool_exhausted`: **boolean** — `true` if compound mode pool hit ≤ 0 and simulation
  stopped early. Only meaningful when `--compound` is used.
- `optimal.simple` and `.compound` may differ

### Markdown (`tickers/{TICKER}/target_optimization.md`)

Header: `# Target Optimization — {TICKER} — as of {as_of_date_label(today)}`
Tables: Configuration, Support Levels Used, Results by Target %, Optimal, Profit Curves.
All tables use `| :--- |` alignment.

### stdout

Full markdown printed to stdout (matching portfolio_status.py convention).

### CLI

```
python3 tools/target_optimizer.py CLSK                  # single ticker
python3 tools/target_optimizer.py --all                 # all portfolio tickers
python3 tools/target_optimizer.py CLSK --compound       # show compound columns
python3 tools/target_optimizer.py CLSK --range 3.0-8.0  # custom range (default 2.0-10.0)
python3 tools/target_optimizer.py CLSK --step 0.25      # custom step (default 0.5)
python3 tools/target_optimizer.py CLSK --timeout 45     # custom timeout (default 30)
```

Uses `argparse` (matching sell_target_calculator.py pattern).

---

## Implementation Order

1. CLI skeleton + imports:
   ```python
   from wick_offset_analyzer import fetch_history, analyze_stock_data, compute_pool_sizing, \
       load_capital_config, load_tickers_from_portfolio
   from trading_calendar import as_of_date_label
   import datetime, argparse, json
   # Header usage: as_of_date_label(datetime.date.today())
   ```
2. `compute_simulation_levels(ticker, hist)` — wraps 1A steps, returns `(sim_levels, base_levels, hist, current_price)` where sim_levels has `buy_at` + `shares` keys, base_levels has `recommended_buy` + `effective_tier` for compound re-sizing
3. `simulate_single(hist, sim_levels, base_levels, target_pct, active_pool, timeout_days=30, compound=False)` — core loop from 1B. `base_levels` required for compound re-sizing; `timeout_days` parameterizes the stuck-position force-close threshold.
4. `sweep_targets(hist, sim_levels, base_levels, active_pool, range_low, range_high, step, timeout_days=30, compound=False)` — loops simulate_single across target range, finds optimal. Passes `base_levels`, `active_pool`, `compound` through to each simulation.
5. `format_report(ticker, sweep_result)` — markdown tables + bar chart
6. `--all` batch mode — loop tickers, cross-ticker comparison table
7. Optional Phase 1 validation — compare vs cycle_history.json if it exists

## Success Criteria

- [ ] Single ticker produces results table with correct row count (e.g., 17 rows for 2.0–10.0 at 0.5)
- [ ] Results are deterministic — same ticker + date = identical output
- [ ] Optimal target varies by ticker (uniform optimal = broken engine)
- [ ] Compound and simple profits both computed; compound can underperform simple when losing cycles shrink the pool — this is correct behavior, not a bug
- [ ] `win_rate` uses `won = profit > 0` with zero-cycle guard returning 0.0
- [ ] `fill_price = min(day_open, buy_at)` — never above either
- [ ] Timeout cycles appear for high target %s on low-volatility tickers
- [ ] Same-day entry+exit counted as valid 1-day cycle
- [ ] Cooldown: no entries on trading day immediately after exit
- [ ] `max_drawdown_pct` is 0.0 when no cycles; can be positive for cycles where low stayed above avg_cost (valid, means no drawdown below cost)
- [ ] JSON validates against schema (all fields present, correct types)
- [ ] Markdown uses `| :--- |` alignment
- [ ] Header uses `as_of_date_label()` from trading_calendar
- [ ] `--all` skips tickers with errors (no crash), prints skip reason
- [ ] Pool exhaustion in compound mode handled gracefully
- [ ] Zero LLM work — every output deterministic from OHLC + capital config
- [ ] Forward-looking bias documented in plan AND output JSON
- [ ] `compute_pool_sizing()` used for compound re-sizing (base_levels maps `buy_at` → `recommended_buy`, result translated back)
- [ ] `open_at_end` position recorded post-loop with mark-to-market unrealized P/L
- [ ] `pool_budget` initialized before loop (available in both simple and compound modes)

## Verification Checklist

- [ ] No fabricated example data in tables (all tables are format templates, not fake numbers)
- [ ] Every metric has an explicit formula
- [ ] All edge cases have mechanical rules (no "handle appropriately")
- [ ] Strategy conflict resolved (acknowledges 3-tier system, not "fixed at 6%")
- [ ] Reuse inventory lists every function with file:line and correct signature
- [ ] `compute_pool_sizing` called with `recommended_buy` key (not `buy_at`)
- [ ] `find_price_action_supports` called with `(hist, current_price)` (not just `(hist)`)
- [ ] Output schema complete with null/zero guards documented
- [ ] Phase 4 relationship explained (Phase 2 produces optimal %, Phase 4 integrates it)
- [ ] No "Effective Annual Return" metric (undefined, removed)
- [ ] win = strictly `profit > 0`, zero-profit = loss
- [ ] `analyze_stock_data()` is the single source for level computation — no reimplemented support-finding
- [ ] Cycle record schema explicitly defined with all 15 fields (no `{...}` placeholders)
- [ ] Timeout reset block is explicit (not a comment reference to "same as exit above")
- [ ] Compound can underperform simple (not a bug — losses shrink pool)
