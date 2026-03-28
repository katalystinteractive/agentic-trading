# Reactive Dependency Graph — Architecture Analysis

**Date**: 2026-03-28 (Saturday)
**Status**: VERIFIED — converged in 2 iterations (4 fixes applied)
**Purpose**: Define the complete node/edge/signal architecture for the trading system's dependency graph. Every claim in this document is traced to actual code and verified against the codebase.

**Verification History**:
- Iteration 1: 7 findings → 4 FIX NOW (node count 12→14, total recalc, vix_5d_pct location, catastrophic line numbers), 3 ACKNOWLEDGE
- Iteration 2: 0 findings → converged

---

## 1. What Problem This Solves

The daily analyzer produces a 1,700-line report. Actions are buried. Reasons for actions are hand-coded strings in `_compute_buy_reason()` and `_compute_sell_reason()` — one level deep, not composable. When a new fill changes the average cost which changes the sell target which makes the broker sell order wrong, the user sees "Avg cost now $8.82 → 6% = $9.35 (was $9.95)" but NOT the full chain: "Fill at $7.79 on 3/23 → avg pulled from $9.82 to $8.82 → sell target moved $10.41 → $9.35 → broker has $9.95, needs ADJUST."

The graph solves this by:
1. **Declaring dependencies as edges** — not implicit in function call order
2. **Propagating signals with accumulated reasons** — each node adds its piece
3. **Persisting state** — diff against previous run to surface CHANGES
4. **Activating only "hot" report nodes** — unchanged items are silent

---

## 2. The System's Data Sources (Leaf Nodes)

Every leaf traces to a specific file or API call. No LLM generates any leaf value.

### 2.1 File-Based State (changes on user action)

| Leaf Node | File | Read By | Writer | Fields Used |
| :--- | :--- | :--- | :--- | :--- |
| `portfolio` | `portfolio.json` | `portfolio_manager._load()` | `cmd_fill()`, `cmd_sell()`, manual | positions, pending_orders, watchlist, capital |
| `ticker_profiles` | `ticker_profiles.json` | `broker_reconciliation._load_profiles()` | `sell_target_calculator.py` | optimal_target_pct per ticker |
| `multi_period_results` | `data/backtest/multi-period/multi-period-results.json` | `shared_utils._load_mp_data()` (mtime-cached) | `multi_period_scorer.py` | allocations[ticker] → active_pool, reserve_pool |
| `trade_history` | `trade_history.json` | `broker_reconciliation._load_trade_history_buys()` | `portfolio_manager._record_trade()` | trades[] with date, price, shares, zone |
| `cooldowns` | `cooldown.json` | `daily_analyzer.find_deployment_tickers()` | `cooldown_manager` | reeval_date per ticker |

### 2.2 Per-Ticker Files (changes on tool run)

| Leaf Node | File Pattern | Read By | Writer | Staleness Check |
| :--- | :--- | :--- | :--- | :--- |
| `{tk}:cycle_timing` | `tickers/{TK}/cycle_timing.json` | `shared_utils.load_cycle_timing()` | `cycle_timing_analyzer.py` | >14 days → stale flag |
| `{tk}:wick_data` | (recomputed fresh, not read from cache) | `wick_offset_analyzer.analyze_stock_data()` | yfinance 13mo OHLCV | Always fresh (fetched per call) |

### 2.3 Live Market Data (changes every run)

| Leaf Node | API | Function | Period | Fallback |
| :--- | :--- | :--- | :--- | :--- |
| `live_prices` | yfinance | `daily_analyzer._fetch_position_prices()` | 5d | `{}` empty dict |
| `live_vix` | yfinance ^VIX | `shared_regime._fetch_regime_data()` | 5d | None → regime defaults "Neutral" |
| `live_indices` | yfinance SPY/QQQ/IWM | `shared_regime._fetch_regime_data()` | 6mo (for 50-SMA) | Skip failed indices |
| `{tk}:live_earnings` | yfinance ticker.earnings_dates | `earnings_gate.check_earnings_gate()` | fresh per call | (None,None) → CLEAR |
| `{tk}:price_3mo` | yfinance | `daily_analyzer._fetch_technical_data()` | 3mo daily | {} → SKIPPED momentum |

---

## 3. Computed Nodes (Deterministic Transforms)

Each computed node has exactly one function, documented inputs, and a deterministic output.

### 3.1 Market-Level (one per run)

| Node | Function | File:Line | Inputs | Output | Used By |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `regime` | `shared_regime.fetch_regime_detail()` → `classify_regime()` | `shared_regime.py:59` | live_indices (50-SMA), live_vix | "Risk-On" / "Neutral" / "Risk-Off" | verdicts, entry_gates, deployment, dip_watchlist |
| `vix` | extracted from regime call | `shared_regime.py:59` | live_vix | float (e.g., 31.0) | entry_gates |
| `vix_5d_pct` | computed in `print_market_regime()` | `daily_analyzer.py:84` | live_vix 5d history | float (e.g., +18.7%) | entry_gates (CAUTION rule) |

### 3.2 Per-Ticker Computed Nodes

For each active ticker TK (27 tickers currently), these nodes are instantiated:

| Node | Function | File:Line | Inputs | Output |
| :--- | :--- | :--- | :--- | :--- |
| `{tk}:avg_cost` | direct read | `portfolio.json` | portfolio.positions[tk].avg_cost | float |
| `{tk}:shares` | direct read | `portfolio.json` | portfolio.positions[tk].shares | int |
| `{tk}:entry_date` | direct read | `portfolio.json` | portfolio.positions[tk].entry_date | str (YYYY-MM-DD or "pre-...") |
| `{tk}:price` | lookup | live_prices[tk] | live_prices | float |
| `{tk}:pl_pct` | arithmetic | inline | (price - avg_cost) / avg_cost × 100 | float |
| `{tk}:drawdown` | arithmetic | inline | same as pl_pct (negative = loss) | float |
| `{tk}:days_held` | `compute_days_held()` | `shared_utils.py:283` | entry_date, today | (int, str, bool) |
| `{tk}:time_status` | `compute_time_stop()` | `shared_utils.py:302` | days_held, is_pre, regime | WITHIN / APPROACHING / EXCEEDED |
| `{tk}:earnings_gate` | `check_earnings_gate()` | `earnings_gate.py:81` | ticker, yfinance | CLEAR / APPROACHING / BLOCKED / FALLING_KNIFE |
| `{tk}:rsi` | `calc_rsi()` | `technical_scanner.py:13` | price_3mo close series | float (0-100) |
| `{tk}:macd` | `calc_macd()` | `technical_scanner.py:23` | price_3mo close series | {macd, signal, histogram} |
| `{tk}:momentum` | `classify_momentum()` | `shared_utils.py:321` | rsi, macd_vs_signal, histogram | Bullish / Bearish / Neutral / SKIPPED |
| `{tk}:pool` | `get_ticker_pool()` | `shared_utils.py:55` | multi_period_results, portfolio capital | {active_pool, reserve_pool, source} |
| `{tk}:sell_target` | `compute_recommended_sell()` | `broker_reconciliation.py:137` | avg_cost, ticker_profiles, portfolio target_exit | (price, basis_str) — priority: optimized > target_exit > 6% |

---

## 4. Decision Nodes (Rule Engines)

These nodes apply deterministic rules and produce the verdicts/gates that drive actions.

### 4.1 Per-Position Decision Nodes (16 tickers with shares > 0)

| Node | Function | File:Line | Inputs | Output | Rules |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `{tk}:verdict` | `compute_verdict()` | `shared_utils.py:386` | avg_cost, price, entry_date, note, earnings_gate, momentum, regime | (verdict, rule, detail) | R1-R16, first-match-wins |
| `{tk}:catastrophic` | threshold check | `daily_analyzer.py:334-336` | drawdown | severity: WARNING(-15%), HARD_STOP(-25%), EXIT_REVIEW(-40%) | 3 thresholds |

### 4.2 Per-Order Decision Nodes (54 pending orders)

| Node | Function | File:Line | Inputs | Output |
| :--- | :--- | :--- | :--- | :--- |
| `{tk}:{label}:entry_gate` | `compute_entry_gate()` | `shared_utils.py:475` | regime, vix, vix_5d_pct, earnings_gate, order_price, live_price, is_watchlist | (market_gate, earnings_gate, combined) |

### 4.3 Per-Ticker Reconciliation (27 tickers)

| Node | Function | File:Line | Inputs | Output |
| :--- | :--- | :--- | :--- | :--- |
| `{tk}:recon` | `reconcile_ticker()` | `broker_reconciliation.py:266` | position, orders, wick_levels, trade_buys, profiles, pool | recon dict with actions[] |

Each recon action is itself a decision: OK / ADJUST price / ADJUST shares / CANCEL (orphaned) / PLACE.

---

## 5. Report Nodes (What Surfaces to the User)

Report nodes are the "leaves" of the OUTPUT tree. They activate only when something changed.

| Report Node | Depends On | Activates When | Dashboard Category |
| :--- | :--- | :--- | :--- |
| `{tk}:sell_order_action` | sell_target, shares, recon | broker sell order ≠ computed target | PLACE / ADJUST |
| `{tk}:buy_order_action` | wick_data, pool, recon | broker buy order ≠ wick-recommended | ADJUST / CANCEL |
| `{tk}:verdict_alert` | verdict | verdict changed since last run | CHANGED |
| `{tk}:gate_alert` | entry_gate | gate status changed since last run | CHANGED |
| `{tk}:catastrophic_alert` | catastrophic | threshold crossed | URGENT |
| `regime_change` | regime | regime label changed since last run | CHANGED |
| `{tk}:review` | verdict | verdict == "REVIEW" | REVIEW |

---

## 6. The Complete Edge Map

This is the dependency graph. Every edge represents "A depends on B."

```
LEAF NODES (data sources)
│
├─ portfolio ─────────────┬─→ {tk}:avg_cost ─────────────┬─→ {tk}:pl_pct ──────→ {tk}:verdict ──→ {tk}:verdict_alert [REPORT]
│                         ├─→ {tk}:shares ────────────────┤                      ↑                  {tk}:review [REPORT]
│                         ├─→ {tk}:entry_date ──→ {tk}:days_held ──→ {tk}:time_status
│                         └─→ {tk}:note (recovery check)  │
│                                                          │
├─ live_prices ───────────→ {tk}:price ───────────────────┘
│                              │
│                              ├─→ {tk}:drawdown ─────────→ {tk}:catastrophic ──→ {tk}:catastrophic_alert [REPORT]
│                              │
│                              └─→ {tk}:{label}:entry_gate ──→ {tk}:gate_alert [REPORT]
│                                    ↑
├─ live_vix ──→ vix ─────────────────┤
│              vix_5d_pct ───────────┤
│                                    │
├─ live_indices ──→ regime ──────────┘──→ (feeds verdict, entry_gate, time_status)
│                     │
│                     └──→ regime_change [REPORT]
│
├─ {tk}:live_earnings ──→ {tk}:earnings_gate ──→ (feeds verdict, entry_gate)
│
├─ {tk}:price_3mo ──→ {tk}:rsi ──┬─→ {tk}:momentum ──→ (feeds verdict)
│                    {tk}:macd ──┘
│
├─ multi_period_results ──→ {tk}:pool ──→ (feeds recon share sizing)
│
├─ ticker_profiles ──→ {tk}:sell_target ──→ {tk}:sell_order_action [REPORT]
│                         ↑
│                         {tk}:avg_cost ─┘
│
├─ trade_history ──→ {tk}:recon ──→ {tk}:sell_order_action [REPORT]
│                                   {tk}:buy_order_action [REPORT]
│
└─ {tk}:wick_data ──→ {tk}:recon
```

---

## 7. Signal Propagation Examples

### 7.1 New Fill → Sell Order Needs ADJUST

```
portfolio CHANGED (new fill $7.79, shares 47→80)
  │
  ├→ CLSK:avg_cost: 9.82 → 8.82
  │   reason: "Fill at $7.79 pulled avg from $9.82 to $8.82"
  │   │
  │   └→ CLSK:sell_target: $10.41 → $9.35
  │       reason: "6% target: $8.82 × 1.06 = $9.35"
  │       │
  │       └→ CLSK:sell_order_action: ACTIVATED [REPORT]
  │           reason: "Broker has $10.41, should be $9.35"
  │           FLAT: "Fill at $7.79 pulled avg from $9.82 to $8.82
  │                  → 6% target: $8.82 × 1.06 = $9.35
  │                  → Broker has $10.41, should be $9.35"
  │
  └→ CLSK:shares: 47 → 80
      reason: "Position grew 47→80 (fill 23sh on 3/23)"
      │
      └→ CLSK:sell_order_action: (already activated, adds to signal)
          reason: "Sell covers 47 shares, position is 80"
```

### 7.2 Regime Flip → Gate Changes for All Orders

```
live_vix CHANGED (18.3 → 31.0)
  │
  └→ regime: Neutral → Risk-Off
      reason: "VIX 18.3 → 31.0 (+69%)"
      │
      ├→ CIFR:A1:14.87:entry_gate: ACTIVE → REVIEW
      │   reason: "Market gate: Risk-Off → REVIEW for non-deep orders"
      │   FLAT: "VIX 18.3→31.0 → regime Neutral→Risk-Off → gate ACTIVE→REVIEW"
      │
      ├→ NU:A2:13.03:entry_gate: ACTIVE → REVIEW
      │   reason: "Market gate: Risk-Off → REVIEW"
      │   ...
      │
      └→ regime_change: ACTIVATED [REPORT]
          FLAT: "VIX 18.3→31.0 → regime Neutral→Risk-Off"
```

### 7.3 Wick Refresh → Buy Order Orphaned

```
{tk}:wick_data CHANGED (support levels shifted)
  │
  └→ APLD:recon: order at $24.64 no longer matches any level
      reason: "Wick refresh: $24.64 was near $23.60 PA, now level moved to $22.70"
      │
      └→ APLD:buy_order_action: ACTIVATED [REPORT]
          reason: "CANCEL — no matching support level"
          FLAT: "Wick refresh shifted $23.60→$22.70 PA
                 → $24.64 order orphaned (>5% from nearest level)
                 → CANCEL"
```

### 7.4 Pool Resize → Buy Order Shares Change

```
multi_period_results CHANGED (CLSK pool $300→$643)
  │
  └→ CLSK:pool: {active: 300} → {active: 321}
      reason: "Simulation rescore: composite $18.7/mo → pool $643"
      │
      └→ CLSK:recon: A1 level shares 4 → 36
          reason: "Pool $300→$643, Full tier at $8.40 → 36 shares"
          │
          └→ CLSK:buy_order_action: ACTIVATED [REPORT]
              reason: "Broker has 4sh, should be 36sh"
              FLAT: "Simulation rescore pool $300→$643
                     → A1 $8.40 Full tier: 4→36 shares
                     → Broker has 4sh, needs ADJUST"
```

---

## 8. Node Count Summary

| Category | Count | Pattern |
| :--- | :--- | :--- |
| Market-level leaf nodes | 5 | portfolio, live_prices, live_vix, live_indices, multi_period_results |
| Per-ticker leaf nodes | 27 × 3 = 81 | earnings, price_3mo, wick_data |
| Static file leaves | 3 | ticker_profiles, trade_history, cooldowns |
| Market-level computed | 3 | regime, vix, vix_5d_pct |
| Per-ticker computed | 27 × 14 = 378 | avg_cost, shares, entry_date, price, pl_pct, drawdown, days_held, time_status, earnings_gate, rsi, macd, momentum, pool, sell_target |
| Per-ticker decisions | 16 × 2 = 32 | verdict, catastrophic (positions only) |
| Per-order decisions | 54 × 1 = 54 | entry_gate |
| Per-ticker recon | 27 × 1 = 27 | recon |
| Report nodes | 27 × 4 + 1 = 109 | sell_order_action, buy_order_action, verdict_alert, catastrophic_alert, regime_change |
| **TOTAL** | **~692** | Dynamic, scales with ticker count |

---

## 9. Persistence Schema (graph_state.json)

**What gets saved** — decision outcomes, not raw data:

```json
{
  "run_date": "2026-03-28",
  "run_ts": "2026-03-28T17:45:30",
  "regime": "Risk-Off",
  "vix": 31.0,
  "vix_5d_pct": 18.7,
  "tickers": {
    "CLSK": {
      "avg_cost": 8.99,
      "shares": 42,
      "price": 8.66,
      "pl_pct": -3.7,
      "verdict": "MONITOR",
      "verdict_rule": "R16",
      "catastrophic": null,
      "momentum": "Bearish",
      "earnings_gate": "CLEAR",
      "time_status": "WITHIN",
      "pool": {"active": 321, "reserve": 322, "source": "multi-period-scorer"},
      "sell_target": {"price": 10.07, "basis": "optimized 12.0%"},
      "orders": {
        "A1:8.40": {"gate": "REVIEW", "action": "OK"},
        "SELL:10.07": {"action": "PLACE"}
      }
    }
  },
  "recon_actions": [
    {"side": "SELL", "ticker": "CLSK", "action": "PLACE", "rec_price": 10.07, "rec_shares": 42,
     "reason": "...", "signal_chain": "..."}
  ]
}
```

**What gets diffed** — only decision-level changes:
- Regime label change
- Per-ticker: verdict flip, catastrophic severity change, gate change
- Per-order: action flag change (OK → ADJUST, etc.)

**What does NOT get diffed** — noise:
- Raw price movements (only the RESULTING verdict/gate matters)
- Raw VIX value (only the RESULTING regime matters)
- Raw RSI/MACD (only the RESULTING momentum matters)

---

## 10. Design Decisions

### 10.1 Dynamic Node Creation (not static declaration)

Tickers come and go (new fills, closed positions). The graph must:
1. Load portfolio.json to discover active tickers
2. Create per-ticker nodes dynamically
3. Handle "ticker was in prev_state but not in current" (position closed → "Resolved" signal)
4. Handle "ticker is in current but not in prev_state" (new position → context signal, not action)

### 10.2 Wick Data is Recomputed, Not Cached

`analyze_stock_data()` fetches 13 months of OHLCV fresh every call. The wick_analysis.md file is human-readable output, NOT a cache input. The graph's `{tk}:wick_data` leaf always contains fresh data.

### 10.3 Sell Prices Are Pool-Independent

Pool size affects BUY share counts. It NEVER affects sell prices. The sell target chain is: avg_cost → sell_target (optimized/target_exit/6%) → sell_price. No pool edge exists in the sell path.

### 10.4 Subprocess Sections Stay Outside the Graph

Parts 3-6 (perf analysis, deployment, fitness, screening) are slow subprocesses (3-14 minutes). They don't feed the Action Dashboard. They stay as subprocesses, running AFTER the graph resolves and the dashboard prints.

### 10.5 First Run Behavior

On first run, `prev_state = {}`. Every node has `prev_value = None`. The CHANGED section shows "No previous state — first run." No false alerts.

### 10.6 Graph is a Wiring Layer, Not a Rewrite

The graph WRAPS existing Python functions — it does NOT replace them. `compute_verdict()`, `classify_momentum()`, `compute_entry_gate()`, `reconcile_ticker()`, `compute_recommended_sell()` stay exactly as they are. Graph nodes call these functions. No computation logic is duplicated or reimplemented inside the graph. If a function changes, the graph automatically uses the updated version.

### 10.7 Single-Edge Extensibility

Adding a new data source or dependency must require declaring ONE node and ONE edge — not modifying multiple files. If adding a new node requires touching main(), _build_graph_state(), _compute_state_diff(), and print_action_dashboard(), the graph has failed its purpose. The graph engine handles propagation, persistence, and dashboard rendering from the declared structure alone.

---

## 11. Integration Pattern

### 11.1 How main() Uses the Graph

The graph replaces `_build_graph_state()`, `_compute_state_diff()`, and the manual reason-building in broker_reconciliation. main() flow becomes:

```python
# Phase A: Fetch all leaf data (batch where possible)
prev_state = load_graph_state()
portfolio = _load()
live_prices = _fetch_position_prices(active_tickers)
regime, vix, vix_5d_pct = fetch_regime_detail()
tech_data = _fetch_technical_data(active_tickers)  # batch 3mo

# Phase B: Build and resolve graph
graph = build_daily_graph(portfolio, live_prices, regime, vix, vix_5d_pct, tech_data)
graph.load_prev_state(prev_state)
graph.resolve()
signals = graph.propagate_signals()

# Phase C: Print dashboard from signals, then print detail sections
print_action_dashboard_from_signals(signals, graph)
# ... print detail sections (same print_* functions, using graph.nodes[x].value) ...

# Phase D: Persist
write_graph_state(graph.get_state())
```

`build_daily_graph()` is a single function that declares all nodes and edges. Adding a new dependency means adding one line to this function.

### 11.2 Per-Ticker Node Creation

A builder function creates all per-ticker nodes in a loop:

```python
def build_daily_graph(portfolio, live_prices, regime, vix, vix_5d_pct, tech_data):
    graph = DependencyGraph()

    # Market-level leaves
    graph.add_node("regime", compute=lambda _: regime)
    graph.add_node("vix", compute=lambda _: vix)
    graph.add_node("live_prices", compute=lambda _: live_prices)

    # Per-ticker nodes
    for tk in active_tickers:
        pos = portfolio["positions"].get(tk, {})
        graph.add_node(f"{tk}:avg_cost", compute=lambda _, p=pos: p.get("avg_cost", 0))
        graph.add_node(f"{tk}:price", compute=lambda _, t=tk: live_prices.get(t))
        graph.add_node(f"{tk}:verdict",
            compute=lambda inputs, t=tk: compute_verdict(...inputs...),
            depends_on=[f"{t}:avg_cost", f"{t}:price", f"{t}:momentum", ...])
        # ... etc for all 14 per-ticker nodes

        # Per-order nodes (using order index for stable identity)
        for idx, order in enumerate(pending_orders.get(tk, [])):
            graph.add_node(f"{tk}:order_{idx}:entry_gate",
                compute=lambda inputs, o=order: compute_entry_gate(...),
                depends_on=["regime", "vix", f"{tk}:earnings_gate"])

    return graph
```

### 11.3 Order Node Naming

Order nodes use **array index** for stable identity, not price: `{tk}:order_{idx}:entry_gate`. Price is mutable (wick refresh can change recommended price). Array index within `pending_orders[ticker]` is stable within a run. Cross-run stability comes from matching by (ticker, index) pair in the persisted state.

### 11.4 Reconciliation Mapping

`reconcile_ticker()` returns a complex dict. It is called as a SINGLE node per ticker:

```python
graph.add_node(f"{tk}:recon",
    compute=lambda inputs, t=tk: reconcile_ticker(t, pos, orders, bullet_ctx, trade_buys, profiles),
    depends_on=[f"{tk}:avg_cost", f"{tk}:pool", f"{tk}:wick_data"])
```

Report nodes extract from the recon dict:

```python
graph.add_node(f"{tk}:sell_order_action",
    compute=lambda inputs, t=tk: _extract_sell_actions(inputs[f"{t}:recon"]),
    depends_on=[f"{tk}:recon"],
    is_report=True,
    reason_fn=lambda old, new, sigs: _sell_action_reason(old, new, sigs))

graph.add_node(f"{tk}:buy_order_action",
    compute=lambda inputs, t=tk: _extract_buy_actions(inputs[f"{t}:recon"]),
    depends_on=[f"{tk}:recon"],
    is_report=True,
    reason_fn=lambda old, new, sigs: _buy_action_reason(old, new, sigs))
```

Reason functions on report nodes compose the signal chain from child signals (which trace back through recon → pool/wick/avg_cost → leaf changes).

### 11.5 Verdict Tuple Handling

`compute_verdict()` returns `(verdict, rule, detail)`. The graph node stores the full tuple:

```python
graph.add_node(f"{tk}:verdict",
    compute=lambda inputs, t=tk: compute_verdict(
        inputs[f"{t}:avg_cost"], inputs[f"{t}:price"], ...),
    depends_on=[f"{t}:avg_cost", f"{t}:price", f"{t}:momentum", ...],
    reason_fn=lambda old, new, sigs: f"Verdict {old[0]}→{new[0]} ({new[1]})")
```

The verdict report node diffs `old[0] != new[0]` (verdict string only). Rule and detail are carried for the reason chain.

### 11.6 Error Handling — Partial Yfinance Failures

Leaf nodes that fail to fetch return a sentinel value (None for prices, "Neutral" for regime, "SKIPPED" for momentum). Per-ticker nodes check for None inputs and short-circuit:

```python
graph.add_node(f"{tk}:verdict",
    compute=lambda inputs, t=tk: (
        compute_verdict(...) if inputs[f"{t}:price"] is not None
        else ("REVIEW", "?", "No price data")),
    depends_on=[...])
```

A single ticker failing does NOT block other tickers. The graph resolves all nodes independently.

### 11.7 Signal Reasons Replace Manual Reason Functions

The graph's Signal.flat_reason() replaces `_compute_buy_reason()` and `_compute_sell_reason()` in broker_reconciliation.py. Those functions are no longer called for dashboard rendering. Instead:

- Each node declares a `reason_fn` that describes what THIS node changed
- Signals accumulate through the chain: leaf reason → intermediate reason → report reason
- `flat_reason()` concatenates them: "Fill at $7.79 → avg $9.82→$8.82 → sell $10.41→$9.35 → broker needs ADJUST"

The existing `_compute_*_reason()` functions stay in broker_reconciliation.py for its standalone output (when run outside the graph), but the dashboard uses signal chains.

### 11.8 Performance Budget

Graph resolve time budget (27 tickers):

| Phase | Time | Notes |
| :--- | :--- | :--- |
| Load portfolio + prev state | <0.1s | File reads |
| Batch live prices | ~2s | 1 yfinance call for all tickers |
| Batch technical data | ~3s | 1 yfinance call (3mo) for all tickers |
| Per-ticker earnings gate | ~5s | 27 sequential yfinance calls (cached in-session) |
| Regime (indices + VIX) | ~2s | 4 yfinance calls |
| Node resolution (692 nodes) | <0.5s | Pure Python computation |
| Signal propagation | <0.1s | Dict comparisons |
| **Total graph phase** | **~13s** | Before dashboard prints |

Wick data (13mo per ticker) is fetched only during **reconciliation** (Part 7), NOT during the graph leaf phase. Wick is the slowest operation (~30s for 27 tickers) but it feeds recon nodes, not the fast graph phase. The <5s claim in the original spec was wrong; the corrected budget is ~13s for the graph phase, ~30s including recon.

### 11.9 Persistence Schema — Canonical Format

The graph engine's `get_state()` produces the canonical persistence format. The current `_build_graph_state()` function is replaced. Schema:

```json
{
  "run_date": "2026-03-28",
  "run_ts": "2026-03-28T17:45:30",
  "regime": "Risk-Off",
  "vix": 31.0,
  "vix_5d_pct": 18.7,
  "tickers": {
    "CLSK": {
      "avg_cost": 8.99,
      "shares": 42,
      "pl_pct": -3.7,
      "verdict": ["MONITOR", "R16", "within time, bearish"],
      "catastrophic": null,
      "momentum": "Bearish",
      "earnings_gate": "CLEAR",
      "time_status": "WITHIN",
      "pool": {"active": 321, "reserve": 322, "source": "multi-period-scorer"},
      "sell_target": [10.07, "optimized 12.0%"],
      "recon_sell_actions": [...],
      "recon_buy_actions": [...]
    }
  },
  "orders": {
    "CLSK:order_0": {"gate": "REVIEW", "price": 8.40, "label": "A1"},
    "CLSK:order_1": {"gate": "ACTIVE", "price": 7.82, "label": "A2"}
  }
}
```

Orders are keyed by `{ticker}:order_{index}` for stable identity. The `label` field (A1, A2, etc.) is stored for display but NOT used as the key.

---

## 12. What the Graph Engine Must Support

Based on this analysis, the graph engine needs:

1. **Dynamic node creation** — add nodes at runtime based on portfolio contents
2. **Namespaced per-ticker nodes** — `{tk}:verdict`, `{tk}:order_0:entry_gate`
3. **Batch leaf loading** — load portfolio once, distribute to per-ticker nodes
4. **Signal propagation with reason composition** — leaf→intermediate→report chains
5. **State persistence** — save decision outcomes to JSON via get_state()
6. **State diffing via signals** — load_prev_state() + propagate_signals() replaces manual diff code
7. **Report node activation** — only "hot" nodes surface in dashboard
8. **Lifecycle handling** — new tickers, closed positions, removed orders
9. **~692 nodes, ~27 tickers** — graph phase ~13s, recon phase ~30s additional
10. **Wrap, don't rewrite** — graph nodes call existing functions, no logic duplication
11. **Single-edge extensibility** — new dependency = one node + one edge declaration
12. **Graceful degradation** — per-ticker failures don't block other tickers

---

## 13. Verification Checklist

After implementation, verify:

- [ ] Every report node's reason chain traces back to a specific leaf change
- [ ] "No change" between runs produces zero activated reports
- [ ] New fill → sell_order_action ACTIVATED with full chain (fill → avg → target → action)
- [ ] Regime flip → all entry gates re-evaluated, changed ones ACTIVATED
- [ ] Pool resize → buy order shares change, ACTIVATED with pool reason
- [ ] Wick refresh → orphaned orders ACTIVATED with level-shift reason
- [ ] Position closed → "Resolved" signal in CHANGED section
- [ ] graph_state.json written with all decision outcomes in canonical format
- [ ] Next run loads prev state and correctly diffs
- [ ] Dashboard shows ONLY activated reports, grouped by priority
- [ ] Single yfinance failure for one ticker does not crash the graph
- [ ] Adding a new node requires only build_daily_graph() changes, nothing else
