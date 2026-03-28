# Code Plan: Reactive Dependency Graph Implementation

**Date**: 2026-03-28 (Saturday)
**Source**: `plans/graph-analysis-verified.md` (727-line verified analysis)
**Approach**: Build graph_builder.py (new), refactor daily_analyzer.py main(), delete ad-hoc state functions
**Verification status**: Checked against analysis — 18 gaps identified and closed in this version

---

## Context

The verified analysis defines a 681-node reactive dependency graph with 5 layers, composable signal propagation, and cross-run state diffing. The graph engine (tools/graph_engine.py) is already built and tested (15/15 tests pass). What remains is:

1. **graph_builder.py** — NEW file that declares all nodes and edges using the engine
2. **daily_analyzer.py refactor** — replace buffering + manual state functions with graph calls
3. **Delete** 6 ad-hoc functions that the graph replaces

---

## Phase 1: Build `tools/graph_builder.py` (~300 lines)

This is the trading-specific graph declaration. It calls `graph_engine.DependencyGraph.add_node()` for every node in the analysis. This file has NO side effects — it builds and returns a graph, nothing else.

### 1.1 Function Signature

```python
def build_daily_graph(portfolio, live_prices, regime, vix, vix_5d_pct,
                      tech_data, earnings_data, recon_data):
    """Build the complete daily analyzer dependency graph.

    All data is fetched BEFORE calling this function. Leaf node compute
    functions are simple lookups into pre-fetched dicts, NOT API calls.
    This keeps resolve() fast (<0.5s for pure computation).

    Returns: DependencyGraph with ~681 nodes, ready for resolve()
    """
```

### 1.2 Market-Level Nodes (5 nodes)

```python
graph.add_node("regime", compute=lambda _: regime,
    reason_fn=lambda old, new, _: f"Regime {old}→{new}")
graph.add_node("vix", compute=lambda _: vix,
    reason_fn=lambda old, new, _: f"VIX {old:.1f}→{new:.1f}")
graph.add_node("vix_5d_pct", compute=lambda _: vix_5d_pct)
graph.add_node("live_prices", compute=lambda _: live_prices)
graph.add_node("regime_change", compute=lambda i: i["regime"],
    depends_on=["regime"], is_report=True,
    reason_fn=lambda old, new, sigs: f"Regime shifted to {new}")
```

### 1.3 Per-Ticker Nodes — ALL 14 Computed + 2 Decision + 4 Report

For each active ticker (positions with shares > 0, plus watchlist tickers with pending orders):

```python
for tk in active_tickers:
    pos = positions.get(tk, {})
    td = tech_data.get(tk, {})
    eg = earnings_data.get(tk, {})

    # NOTE: Default parameter binding (p=pos, t=tk, etc.) is REQUIRED.
    # Without it, Python's late-binding closures capture the LAST loop value.

    # --- 14 Computed nodes (analysis Section 3.2) ---

    # 1. avg_cost — direct read from portfolio
    graph.add_node(f"{tk}:avg_cost", compute=lambda _, p=pos: p.get("avg_cost", 0),
        reason_fn=lambda old, new, _: f"Avg ${old:.2f}→${new:.2f}" if old else "")

    # 2. shares — direct read from portfolio
    graph.add_node(f"{tk}:shares", compute=lambda _, p=pos: p.get("shares", 0),
        reason_fn=lambda old, new, _: f"Shares {old}→{new}")

    # 3. entry_date — direct read from portfolio
    graph.add_node(f"{tk}:entry_date", compute=lambda _, p=pos: p.get("entry_date", ""))

    # 4. price — lookup from batch-fetched live_prices
    graph.add_node(f"{tk}:price", compute=lambda _, t=tk: live_prices.get(t),
        reason_fn=lambda old, new, _: f"Price ${old:.2f}→${new:.2f}" if old and new else "")

    # 5. pl_pct — arithmetic: (price - avg) / avg * 100
    graph.add_node(f"{tk}:pl_pct",
        compute=lambda i, t=tk: _calc_pl(i[f"{t}:avg_cost"], i[f"{t}:price"]),
        depends_on=[f"{tk}:avg_cost", f"{tk}:price"])

    # 6. drawdown — same as pl_pct (used by catastrophic check)
    graph.add_node(f"{tk}:drawdown",
        compute=lambda i, t=tk: i[f"{t}:pl_pct"],
        depends_on=[f"{tk}:pl_pct"],
        reason_fn=lambda old, new, _: f"Drawdown {old:.1f}%→{new:.1f}%" if old is not None else "")

    # 7. days_held — date arithmetic
    graph.add_node(f"{tk}:days_held",
        compute=lambda _, p=pos: compute_days_held(p.get("entry_date", ""), None),
        reason_fn=lambda old, new, _: f"Days {old[0]}→{new[0]}" if old else "")

    # 8. time_status — threshold check (regime-aware)
    graph.add_node(f"{tk}:time_status",
        compute=lambda i, t=tk: compute_time_stop(
            i[f"{t}:days_held"][0], i[f"{t}:days_held"][2], i["regime"]),
        depends_on=[f"{tk}:days_held", "regime"])

    # 9. earnings_gate — pre-fetched from batch earnings call
    graph.add_node(f"{tk}:earnings_gate",
        compute=lambda _, e=eg: e.get("status", "CLEAR"),
        reason_fn=lambda old, new, _: f"Earnings {old}→{new}" if old != new else "")

    # 10. rsi — pre-computed from batch technical data
    graph.add_node(f"{tk}:rsi", compute=lambda _, d=td: d.get("rsi"))

    # 11. macd — pre-computed from batch technical data
    graph.add_node(f"{tk}:macd", compute=lambda _, d=td: {
        "macd_vs_signal": d.get("macd_vs_signal"),
        "histogram": d.get("histogram")})

    # 12. momentum — deterministic classification from rsi + macd
    graph.add_node(f"{tk}:momentum",
        compute=lambda i, t=tk: classify_momentum(
            i[f"{t}:rsi"], (i[f"{t}:macd"] or {}).get("macd_vs_signal"),
            (i[f"{t}:macd"] or {}).get("histogram")),
        depends_on=[f"{tk}:rsi", f"{tk}:macd"],
        reason_fn=lambda old, new, _: f"Momentum {old}→{new}" if old != new else "")

    # 13. pool — per-ticker pool from simulation results (no dependency on sell path)
    graph.add_node(f"{tk}:pool",
        compute=lambda _, t=tk: get_ticker_pool(t),
        reason_fn=lambda old, new, _: (
            f"Pool ${old.get('active_pool',0)}→${new.get('active_pool',0)}"
            if old and new and old.get('active_pool') != new.get('active_pool') else ""))

    # 14. sell_target — priority: optimized > target_exit > 6%
    #     NOTE: sell_target depends on avg_cost and ticker_profiles, NOT on pool.
    #     Pool NEVER affects sell prices. (Analysis Section 10.3)
    graph.add_node(f"{tk}:sell_target",
        compute=lambda i, t=tk, p=pos: compute_recommended_sell(
            t, i[f"{t}:avg_cost"], p, profiles),
        depends_on=[f"{tk}:avg_cost"],
        reason_fn=lambda old, new, _: (
            f"Sell target ${old[0]:.2f}→${new[0]:.2f} ({new[1]})"
            if old and new else ""))

    # --- Decision nodes (analysis Section 4) ---

    # Verdict — calls compute_verdict() with all 7 parameters
    # Returns (verdict_str, rule_id, detail) tuple
    graph.add_node(f"{tk}:verdict",
        compute=lambda i, t=tk, p=pos: (
            compute_verdict(
                i[f"{t}:avg_cost"], i[f"{t}:price"],
                p.get("entry_date", ""), p.get("note", ""),
                i[f"{t}:earnings_gate"], i[f"{t}:momentum"], i["regime"])
            if i[f"{t}:price"] is not None
            else ("REVIEW", "?", "No price data")),
        depends_on=[f"{tk}:avg_cost", f"{tk}:price", f"{tk}:momentum",
                    f"{tk}:earnings_gate", f"{tk}:time_status", "regime"],
        reason_fn=lambda old, new, _: (
            f"Verdict {old[0]}→{new[0]} ({new[1]})" if old and old[0] != new[0] else ""))

    # Catastrophic — threshold check on drawdown
    graph.add_node(f"{tk}:catastrophic",
        compute=lambda i, t=tk: _check_catastrophic(i[f"{t}:drawdown"]),
        depends_on=[f"{tk}:drawdown"],
        reason_fn=lambda old, new, _: f"Alert: {new}" if new and old != new else "")

    # --- Report nodes (analysis Section 5) ---

    graph.add_node(f"{tk}:verdict_alert",
        compute=lambda i, t=tk: i[f"{t}:verdict"],
        depends_on=[f"{tk}:verdict"], is_report=True,
        reason_fn=lambda old, new, sigs: f"{new[0]} ({new[1]})")

    graph.add_node(f"{tk}:catastrophic_alert",
        compute=lambda i, t=tk: i[f"{t}:catastrophic"],
        depends_on=[f"{tk}:catastrophic"], is_report=True,
        reason_fn=lambda old, new, _: f"Severity: {new}" if new else "")

    graph.add_node(f"{tk}:review",
        compute=lambda i, t=tk: (
            i[f"{t}:verdict"] if i[f"{t}:verdict"][0] == "REVIEW" else None),
        depends_on=[f"{tk}:verdict"], is_report=True,
        reason_fn=lambda old, new, _: f"Needs human review: {new[2]}" if new else "")
```

### 1.4 Per-Order Entry Gate Nodes (~54 nodes)

```python
    # Inside the per-ticker loop
    pending = pending_orders.get(tk, [])
    active_buys = [o for o in pending if o.get("type") == "BUY"
                   and o.get("placed") and not o.get("filled")]
    for idx, order in enumerate(active_buys):
        label = _extract_label(order.get("note", ""))
        graph.add_node(f"{tk}:order_{idx}:entry_gate",
            compute=lambda i, o=order, t=tk: compute_entry_gate(
                i["regime"], i["vix"], i["vix_5d_pct"],
                i[f"{t}:earnings_gate"], o["price"], i[f"{t}:price"],
                is_watchlist=(i[f"{t}:shares"] == 0)),
            depends_on=["regime", "vix", "vix_5d_pct",
                        f"{tk}:earnings_gate", f"{tk}:price", f"{tk}:shares"],
            reason_fn=lambda old, new, _: (
                f"Gate {old[2]}→{new[2]}" if old and old[2] != new[2] else ""))

        graph.add_node(f"{tk}:order_{idx}:gate_alert",
            compute=lambda i, t=tk, x=idx: i[f"{t}:order_{x}:entry_gate"],
            depends_on=[f"{tk}:order_{idx}:entry_gate"], is_report=True,
            reason_fn=lambda old, new, sigs: f"Gate → {new[2]}")
```

### 1.5 Reconciliation Nodes (per-ticker: 1 recon + 2 report)

```python
    # Inside the per-ticker loop — recon is pre-computed and passed in
    recon = recon_data.get(tk, {})
    graph.add_node(f"{tk}:recon", compute=lambda _, r=recon: r,
        depends_on=[f"{tk}:avg_cost", f"{tk}:pool", f"{tk}:sell_target",
                    "trade_history", "ticker_profiles"],
        reason_fn=lambda old, new, _: "Reconciliation changed")

    graph.add_node(f"{tk}:sell_order_action",
        compute=lambda i, t=tk: _extract_sell_actions(i[f"{t}:recon"]),
        depends_on=[f"{tk}:recon"], is_report=True,
        reason_fn=lambda old, new, sigs: _format_sell_reason(new, sigs))

    graph.add_node(f"{tk}:buy_order_action",
        compute=lambda i, t=tk: _extract_buy_actions(i[f"{t}:recon"]),
        depends_on=[f"{tk}:recon"], is_report=True,
        reason_fn=lambda old, new, sigs: _format_buy_reason(new, sigs))
```

### 1.6 Helper Functions (~10 functions)

```python
def _calc_pl(avg_cost, price):
    """(price - avg) / avg * 100. Returns None if inputs missing."""
    if not avg_cost or not price or avg_cost <= 0:
        return None
    return round((price - avg_cost) / avg_cost * 100, 1)

def _check_catastrophic(pl_pct):
    """Apply analysis Section 4.1 thresholds. Returns severity or None."""
    if pl_pct is None:
        return None
    if pl_pct <= -40:
        return "EXIT_REVIEW"
    if pl_pct <= -25:
        return "HARD_STOP"
    if pl_pct <= -15:
        return "WARNING"
    return None

def _extract_label(note):
    """Parse A1/B2/R3 from order note. Returns '?' if not found."""
    import re
    m = re.search(r'\b(A[1-5]|B[1-5]|R[1-3])\b', note)
    return m.group() if m else "?"

def _extract_sell_actions(recon):
    """Extract sell actions from recon dict."""
    if not recon:
        return []
    return [a for a in recon.get("actions", [])
            if isinstance(a, dict) and a.get("side") == "SELL"]

def _extract_buy_actions(recon):
    """Extract buy actions from recon dict."""
    if not recon:
        return []
    return [a for a in recon.get("actions", [])
            if isinstance(a, dict) and a.get("side") == "BUY"]

def _format_sell_reason(actions, child_signals):
    """Build sell reason from signal chain + action details."""
    if not actions:
        return ""
    parts = []
    for sig in child_signals:
        if sig.reason:
            parts.append(sig.reason)
    for a in actions:
        parts.append(a.get("reason", ""))
    return " → ".join(p for p in parts if p)

def _format_buy_reason(actions, child_signals):
    """Build buy reason from signal chain + action details."""
    if not actions:
        return ""
    parts = []
    for sig in child_signals:
        if sig.reason:
            parts.append(sig.reason)
    for a in actions:
        parts.append(a.get("reason", ""))
    return " → ".join(p for p in parts if p)

def get_state_for_persistence(graph, active_tickers, pending_orders):
    """Restructure graph.get_state() into canonical nested format (analysis Section 11.9).

    Flat graph state → nested {tickers: {TK: {...}}, orders: {TK:order_N: {...}}}
    """
    from datetime import date, datetime
    state = {
        "run_date": date.today().isoformat(),
        "run_ts": datetime.now().isoformat(timespec="seconds"),
        "regime": graph.nodes["regime"].value,
        "vix": graph.nodes["vix"].value,
        "vix_5d_pct": graph.nodes["vix_5d_pct"].value,
        "tickers": {},
        "orders": {},
    }
    for tk in active_tickers:
        n = graph.nodes
        state["tickers"][tk] = {
            "avg_cost": n.get(f"{tk}:avg_cost", _stub()).value,
            "shares": n.get(f"{tk}:shares", _stub()).value,
            "pl_pct": n.get(f"{tk}:pl_pct", _stub()).value,
            "verdict": n.get(f"{tk}:verdict", _stub()).value,
            "catastrophic": n.get(f"{tk}:catastrophic", _stub()).value,
            "momentum": n.get(f"{tk}:momentum", _stub()).value,
            "earnings_gate": n.get(f"{tk}:earnings_gate", _stub()).value,
            "time_status": n.get(f"{tk}:time_status", _stub()).value,
            "pool": n.get(f"{tk}:pool", _stub()).value,
            "sell_target": n.get(f"{tk}:sell_target", _stub()).value,
        }
        # Per-order gate state
        for idx, order in enumerate(pending_orders.get(tk, [])):
            key = f"{tk}:order_{idx}"
            gate_node = n.get(f"{key}:entry_gate")
            if gate_node:
                label = _extract_label(order.get("note", ""))
                state["orders"][key] = {
                    "gate": gate_node.value,
                    "price": order.get("price", 0),
                    "label": label,
                }
    return state
```

### 1.7 Self-Test (`python3 tools/graph_builder.py --test`)

```python
if __name__ == "__main__":
    if "--test" in sys.argv:
        portfolio = json.load(open(_ROOT / "portfolio.json"))
        # Use empty dicts for live data (test node wiring, not yfinance)
        graph = build_daily_graph(portfolio, {}, "Neutral", 20.0, 0.0, {}, {}, {})
        graph.resolve()

        # Count nodes by type
        leaves = [n for n in graph.nodes.values() if not n.depends_on]
        computed = [n for n in graph.nodes.values() if n.depends_on and not n.is_report]
        reports = [n for n in graph.nodes.values() if n.is_report]
        print(f"Nodes: {len(leaves)} leaves + {len(computed)} computed + {len(reports)} reports = {len(graph.nodes)} total")
        print(f"Expected ~681 (varies with ticker/order count)")

        # Test signal propagation with fake prev state
        graph.load_prev_state({"regime": "Risk-On"})
        signals = graph.propagate_signals()
        activated = graph.get_activated_reports()
        print(f"Activated reports: {len(activated)}")
        for name, node in activated[:5]:
            for sig in node.signals:
                print(f"  {name}: {sig.flat_reason()}")
        print("SELF-TEST PASSED")
```

---

## Phase 2: Refactor `tools/daily_analyzer.py` main()

### 2.1 New main() Flow

```python
def main():
    args = parse_args()
    fills, sells, parse_errors = _parse_transaction_args(args)

    # Part 0: Market Regime (prints immediately — before graph)
    regime, vix, vix_5d_pct = print_market_regime()

    # Part 1: Process transactions (prints immediately — before graph)
    if fills or sells or parse_errors:
        print("## Part 1 — Processing Transactions\n")
        process_transactions(fills, sells, parse_errors)

    # Phase A: Fetch all leaf data (batch where possible)
    portfolio = _load()
    active_tickers = _get_active_tickers(portfolio)
    live_prices = _fetch_position_prices(active_tickers)
    tech_data = _fetch_technical_data(active_tickers)
    earnings_data = _batch_earnings(active_tickers)

    # Phase A2: Pre-compute reconciliation (expensive — wick fetches happen here)
    recon_data = {}
    if not args.no_recon:
        recon_data = _run_recon_for_graph(portfolio, active_tickers)

    # Phase B: Build graph, load prev state, resolve, propagate signals
    from graph_builder import build_daily_graph
    prev_state = _load_graph_state()  # {} on first run
    graph = build_daily_graph(portfolio, live_prices, regime, vix, vix_5d_pct,
                              tech_data, earnings_data, recon_data)
    graph.load_prev_state(prev_state)

    try:
        graph.resolve()
        signals = graph.propagate_signals()
    except Exception as e:
        print(f"\n*Graph resolve failed: {e}. Running in status-only mode.*\n")
        print_consolidated_orders()
        print_tier_summary()
        return  # Don't write graph_state (preserve previous)

    # Phase C: Dashboard FIRST (from signals), then detail sections (from graph.nodes)
    print_action_dashboard_from_signals(signals, graph)
    print_detail_sections(graph, regime)

    # Parts 3-6: Subprocesses (unchanged, outside graph)
    if not args.no_deploy and not args.no_perf:
        run_ticker_perf_analysis() if regime != "Risk-Off" else ...
    if not args.no_deploy:
        deploy_tickers = find_deployment_tickers()
        print_deployment_recs(deploy_tickers, paused=_get_paused(graph))
    if not args.no_deploy and not args.no_fitness:
        run_watchlist_fitness()
    if not args.no_deploy and not args.no_fitness and not args.no_screen:
        run_candidate_screening(wide_screen=args.wide_screen)

    # Phase D: Persist canonical state
    from graph_builder import get_state_for_persistence
    state = get_state_for_persistence(graph, active_tickers, portfolio.get("pending_orders", {}))
    _write_graph_state(state)
```

### 2.2 New Function: `_batch_earnings(tickers)` (~10 lines)

```python
def _batch_earnings(tickers):
    """Call check_earnings_gate() per ticker. Returns {ticker: gate_dict}."""
    from earnings_gate import check_earnings_gate
    result = {}
    for tk in tickers:
        try:
            result[tk] = check_earnings_gate(tk)
        except Exception:
            result[tk] = {"status": "CLEAR"}
    return result
```

### 2.3 New Function: `_run_recon_for_graph(portfolio, tickers)` (~25 lines)

Same as current `run_broker_reconciliation_direct()` but returns `{ticker: recon_dict}` without printing. Printing happens later in `print_detail_sections()`.

### 2.4 New Function: `print_action_dashboard_from_signals(signals, graph)` (~60 lines)

Groups activated report node signals into 6 buckets (analysis Section 11.0.3):

| Bucket | Source Report Nodes | Condition | Sort |
| :--- | :--- | :--- | :--- |
| URGENT | `{tk}:catastrophic_alert` | severity HARD_STOP or EXIT_REVIEW | severity desc |
| PLACE | `{tk}:sell_order_action`, `{tk}:buy_order_action` | action == "PLACE" | ticker alpha |
| ADJUST | `{tk}:sell_order_action`, `{tk}:buy_order_action` | "ADJUST" in action | ticker alpha |
| CANCEL | `{tk}:buy_order_action` | "CANCEL" in action | ticker alpha |
| CHANGED | `regime_change`, `{tk}:verdict_alert`, `{tk}:gate_alert` | any signal present | regime first |
| REVIEW | `{tk}:review` | verdict[0] == "REVIEW" | ticker alpha |

**Reason column**: Each row uses `signal.flat_reason()` — the composable chain from leaf to report.

**Worked example** (analysis Section 7.1):
```
Signal chain: portfolio → CLSK:avg_cost → CLSK:sell_target → CLSK:sell_order_action

flat_reason output:
"Avg $9.82→$8.82 → Sell target $10.41→$9.35 (standard 6.0%) → Broker has $10.41, should be $9.35"

Dashboard row:
| SELL | CLSK | $10.41/42sh | $9.35/42sh | Avg $9.82→$8.82 → Sell target $10.41→$9.35 (6%) → Broker $10.41→$9.35 |
```

### 2.5 New Function: `print_detail_sections(graph, regime)` (~50 lines)

Reads from `graph.nodes[name].value` and prints the existing detail tables. Output format IDENTICAL to today.

- `print_consolidated_orders_from_graph(graph)` — reads shares, avg_cost, pending_orders from graph nodes
- `print_position_age_from_graph(graph)` — reads days_held, time_status from graph nodes
- `print_pool_allocations_from_graph(graph)` — reads pool from graph nodes
- `print_catastrophic_from_graph(graph)` — reads catastrophic from graph nodes
- `print_verdicts_from_graph(graph)` — reads verdict from graph nodes
- `print_entry_gates_from_graph(graph)` — reads entry_gate from graph nodes
- `print_recon_from_graph(graph)` — reads recon from graph nodes, prints ticker reports + action summary
- `print_sell_projections()` — UNCHANGED (transient, not in graph)
- `print_exit_strategy_summary()` — UNCHANGED (fetches own data)
- `print_daily_fluctuation_watchlist()` — UNCHANGED (fetches own data)
- `print_unfilled_same_day_exits()` — UNCHANGED
- `print_pdt_status()` — UNCHANGED

### 2.6 Functions DELETED (analysis Section 11.0.1)

- `_build_graph_state()` → replaced by `get_state_for_persistence()`
- `_compute_state_diff()` → replaced by `graph.propagate_signals()`
- `_load_prev_state()` → kept but simplified (just JSON load)
- `_write_graph_state()` → kept but simplified (just JSON dump)
- `print_action_dashboard()` → replaced by `print_action_dashboard_from_signals()`
- `run_broker_reconciliation_direct()` → replaced by `_run_recon_for_graph()`
- `io.StringIO` buffering block → no longer needed

### 2.7 Functions RETAINED (not in graph scope)

- `print_market_regime()` — runs before graph, provides regime/vix
- `process_transactions()` — runs before graph, mutates portfolio.json
- `print_sell_projections()` — transient scenarios
- `print_exit_strategy_summary()` — fetches own data
- `print_daily_fluctuation_watchlist()` — fetches own data
- `print_unfilled_same_day_exits()` — simple read
- `print_pdt_status()` — simple count
- Parts 3-6 subprocess runners — unchanged

---

## Phase 3: Error Recovery (analysis Section 11.0.5)

### 3.1 Graph Resolve Failure

Wrapped in try/except in main() (Section 2.1 above). Falls back to basic portfolio status. Does NOT write graph_state.json (preserves previous state for next run).

### 3.2 Per-Ticker Yfinance Failure

Each node's compute function handles None inputs:
- Missing price → verdict returns `("REVIEW", "?", "No price data")`
- Missing earnings → defaults to `"CLEAR"`
- Missing RSI/MACD → momentum returns `"SKIPPED"`
- One ticker failing does NOT block others

### 3.3 First Run (no prev_state)

`_load_graph_state()` returns `{}` if file doesn't exist. `graph.load_prev_state({})` sets all prev_values to None. `propagate_signals()` treats everything as "new" — CHANGED section shows "No previous run data" or stays empty (no false alerts).

---

## Phase 4: Persistence (analysis Section 11.9)

### 4.1 Schema

`get_state_for_persistence()` in graph_builder.py produces the canonical nested format defined in analysis Section 9/11.9. See Section 1.6 for implementation.

### 4.2 Cross-Run Order Matching (analysis Section 11.0.6)

When loading prev_state, orders are matched by **(ticker, label)** not array index:
- SELL orders: matched by ticker (at most 1 per ticker)
- BUY orders: matched by `(ticker, label)` e.g., "CLSK:A1"
- Fallback for legacy orders without label: price ± 1% tolerance
- Unmatched in prev → "Order removed" signal
- Unmatched in curr → "New order" (context, not action)

### 4.3 Position Lifecycle

- **New position** (ticker in curr, not in prev): nodes have prev_value=None, signals show as new context
- **Closed position** (ticker in prev, not in curr): detected during diff, generates "Position closed" in CHANGED

---

## Performance Budget (analysis Section 11.8)

| Phase | Time | Notes |
| :--- | :--- | :--- |
| Market regime | ~2s | 4 yfinance calls (SPY/QQQ/IWM/VIX) |
| Batch live prices | ~2s | 1 yfinance call for all tickers |
| Batch technical data | ~3s | 1 yfinance call (3mo) for all tickers |
| Per-ticker earnings | ~8s | 27 tickers × up to 3 yfinance calls each |
| Reconciliation (wick) | ~30s | 27 × 13-month OHLCV fetches |
| Graph resolve | <0.5s | Pure Python computation |
| Signal propagation | <0.1s | Dict comparisons |
| **Total** | **~46s** | Before Parts 3-6 subprocesses |

---

## Design Constraints (from analysis Section 10)

1. **10.3 Sell prices are pool-independent**: `{tk}:sell_target` depends on `{tk}:avg_cost` and `ticker_profiles`, NOT `{tk}:pool`. No pool edge in sell path.
2. **10.6 Wrap, don't rewrite**: Graph nodes call existing functions. No logic duplication.
3. **10.7 Single-edge extensibility**: Adding a new computed node = ONE change in `build_daily_graph()`. Adding a new leaf = TWO changes (fetch in Phase A + node declaration). ZERO changes in propagation/persistence/dashboard.

---

## Files Modified

| File | Action | Est. Lines |
| :--- | :--- | :--- |
| `tools/graph_builder.py` | **NEW** — all node/edge declarations, helpers, reason_fns, persistence formatter | ~300 |
| `tools/daily_analyzer.py` | **MODIFY** — new main() flow, delete 6 functions, add 5 new functions | ~-250, +200 |
| `tools/graph_engine.py` | **NO CHANGES** | 0 |
| `tools/broker_reconciliation.py` | **NO CHANGES** | 0 |
| `tools/shared_utils.py` | **NO CHANGES** | 0 |
| `data/graph_state.json` | **MODIFIED** — canonical nested format | auto |

---

## Implementation Order

1. **Phase 1**: Build `graph_builder.py` with self-test. Verify: `python3 tools/graph_builder.py --test`
2. **Phase 2**: Refactor daily_analyzer.py main(). Delete old functions. Wire graph.
3. **Phase 3**: Add error recovery and first-run handling.
4. **Phase 4**: Verify persistence schema matches analysis Section 11.9.

Each phase is independently testable. Phase 1 runs standalone before daily_analyzer changes.

---

## Verification (maps to Analysis Section 13)

After implementation, verify each item:

1. [ ] **Composable reason chain**: Dashboard shows "Avg $X→$Y → Sell target $A→$B → Broker has $C, needs ADJUST" (not one-level inline strings)
2. [ ] **Silence on no change**: Run twice with no portfolio changes → zero CHANGED items, zero activated reports
3. [ ] **Fill → sell action**: Simulate fill → verify sell_order_action activated with chain: fill → avg → sell_target → broker ADJUST
4. [ ] **Regime flip → gates**: Change regime in test → verify ALL entry gates re-evaluated, changed ones show in CHANGED
5. [ ] **Pool resize → shares**: Change pool allocation → verify buy_order_action activated with "Pool $X→$Y → shares A→B"
6. [ ] **Wick → orphan**: Refresh wick data → verify orphaned order shows CANCEL with "Wick refresh shifted level"
7. [ ] **Position closed**: Close a position → verify "Position closed" appears in CHANGED
8. [ ] **Canonical schema**: Check graph_state.json has nested tickers/orders format per analysis Section 9
9. [ ] **Prev state loads**: Delete graph_state.json, run twice, second run shows diffs correctly
10. [ ] **Yfinance failure**: Mock one ticker's price as None → verify other tickers still resolve, failed ticker shows REVIEW
11. [ ] **Self-test**: `python3 tools/graph_builder.py --test` prints node count near 681 and passes
12. [ ] **Single-edge extensibility**: Add a dummy test node to build_daily_graph() → verify it appears in graph.summary() without touching any other file
13. [ ] **Detail tables identical**: Compare verdict table, gate table, age table output against pre-graph version — format must be identical
