# Test Analysis — Reactive Dependency Graph

**Date**: 2026-03-28 (Saturday)
**Source**: `plans/graph-analysis-verified.md` (analysis), `plans/graph-code-plan.md` (plan)
**Purpose**: Define what tests are needed, what inputs they use, what outputs they expect, and why each test matters. This document drives the test plan, which drives the test code.

---

## 1. Test Philosophy

All tests use **fixture data** — no yfinance calls, no live API. This means:
- Tests are fast (<2s total)
- Tests are deterministic (same input → same output every time)
- Tests run offline (weekends, no internet)
- Tests don't depend on market state

The fixture is a minimal portfolio with 2-3 tickers that exercises every node type and every signal path.

---

## 2. Test Fixture

### 2.1 Fixture Portfolio

```python
FIXTURE_PORTFOLIO = {
    "positions": {
        "CLSK": {"shares": 42, "avg_cost": 8.99, "entry_date": "2026-03-23",
                 "note": "", "bullets_used": 5, "fill_prices": [9.89, 9.74, 9.05, 8.91, 8.40],
                 "target_exit": None},
        "IONQ": {"shares": 15, "avg_cost": 44.43, "entry_date": "pre-2025",
                 "note": "recovery underwater", "bullets_used": 1,
                 "fill_prices": [], "target_exit": None},
        "AR": {"shares": 0, "avg_cost": 0, "entry_date": "",
               "note": "", "bullets_used": 0, "fill_prices": [],
               "target_exit": None},
    },
    "pending_orders": {
        "CLSK": [{"type": "BUY", "price": 8.40, "shares": 10, "placed": True,
                  "note": "A1 — $8.25 PA, 62% hold, Full"}],
        "AR": [{"type": "BUY", "price": 35.00, "shares": 1, "placed": True,
                "note": "Bullet 1 — $34.61 HVN+PA, 30% hold"},
               {"type": "BUY", "price": 32.68, "shares": 3, "placed": True,
                "note": "B2 — $31.36 HVN+PA, 50% hold"}],
        "IONQ": [],
    },
    "watchlist": ["CLSK", "IONQ", "AR"],
    "capital": {"active_pool": 300, "reserve_pool": 300,
                "active_bullets_max": 5, "reserve_bullets_max": 3},
}
```

**Why these tickers:**
- **CLSK**: Active position (shares > 0), has pending BUY, has fills — exercises avg_cost, sell_target, verdict, entry_gate, recon paths
- **IONQ**: Pre-strategy recovery position, deep drawdown (-38%) — exercises catastrophic thresholds, REVIEW verdict, recovery classification
- **AR**: Watchlist-only (shares = 0), has pending BUYs — exercises is_watchlist entry gate path, no verdict (no position)

### 2.2 Fixture Live Prices

```python
FIXTURE_PRICES = {"CLSK": 8.66, "IONQ": 27.51, "AR": 44.00}
```

**Why these prices:**
- CLSK at 8.66: P/L = (8.66 - 8.99) / 8.99 = -3.7% → not catastrophic, MONITOR verdict
- IONQ at 27.51: P/L = (27.51 - 44.43) / 44.43 = -38.1% → HARD_STOP catastrophic, REVIEW verdict (pre-strategy)
- AR at 44.00: no position, price used for entry gate proximity check

### 2.3 Fixture Technical Data

```python
FIXTURE_TECH = {
    "CLSK": {"rsi": 35.0, "macd_vs_signal": "below", "histogram": -0.2},
    "IONQ": {"rsi": 28.0, "macd_vs_signal": "below", "histogram": -1.5},
    "AR": {"rsi": 55.0, "macd_vs_signal": "above", "histogram": 0.3},
}
```

**Why these values:**
- CLSK RSI 35 + MACD below + histogram < 0 → Bearish momentum
- IONQ RSI 28 (<40) → Bearish (unconditional)
- AR RSI 55 + MACD above → Bullish

### 2.4 Fixture Earnings Data

```python
FIXTURE_EARNINGS = {
    "CLSK": {"status": "CLEAR"},
    "IONQ": {"status": "CLEAR"},
    "AR": {"status": "APPROACHING"},
}
```

**Why:** AR APPROACHING exercises the earnings gate REVIEW path.

### 2.5 Fixture Previous State

```python
FIXTURE_PREV_STATE = {
    "regime": "Neutral",
    "vix": 18.3,
    "CLSK:avg_cost": 9.82,
    "CLSK:sell_target": (10.41, "standard 6.0%"),
    "CLSK:verdict": ("MONITOR", "R16", "Time WITHIN (2d)"),
    "CLSK:catastrophic": None,
    "CLSK:momentum": "Bearish",
    "IONQ:verdict": ("MONITOR", "R16", "Time EXCEEDED"),
    "IONQ:catastrophic": "WARNING",
    "regime_change": "Neutral",
}
```

**Why:** Simulates a previous run with different avg_cost (9.82 → 8.99) and different regime (Neutral → Risk-Off), so diff signals fire.

---

## 3. What to Test — Organized by Layer

### Layer A: Helper Functions (graph_builder.py)

Pure functions, no dependencies. Each has exact input→output.

| # | Function | Input | Expected Output | Edge Case | Why It Matters |
| :--- | :--- | :--- | :--- | :--- | :--- |
| A1 | `_calc_pl(10.0, 10.60)` | avg=10, price=10.60 | 6.0 | — | Core P/L math |
| A2 | `_calc_pl(10.0, 9.40)` | avg=10, price=9.40 | -6.0 | Negative P/L | Drawdown detection |
| A3 | `_calc_pl(0, 10.0)` | avg=0 | None | Division by zero guard | Prevents crash |
| A4 | `_calc_pl(10.0, None)` | price missing | None | Yfinance failure | Graceful degradation |
| A5 | `_calc_pl(None, 10.0)` | avg missing | None | Data corruption | Graceful degradation |
| A6 | `_check_catastrophic(-14.9)` | Just above -15% | None | Boundary | No false WARNING |
| A7 | `_check_catastrophic(-15.0)` | Exact -15% | "WARNING" | Boundary | Threshold inclusivity |
| A8 | `_check_catastrophic(-24.9)` | Between -15 and -25 | "WARNING" | — | Correct tier |
| A9 | `_check_catastrophic(-25.0)` | Exact -25% | "HARD_STOP" | Boundary | Threshold escalation |
| A10 | `_check_catastrophic(-40.0)` | Exact -40% | "EXIT_REVIEW" | Boundary | Highest severity |
| A11 | `_check_catastrophic(None)` | No data | None | Missing P/L | No crash |
| A12 | `_extract_label("A1 — $8.25 PA")` | Normal note | "A1" | — | Order identification |
| A13 | `_extract_label("B3 — $5.00")` | B-zone | "B3" | — | Buffer zone |
| A14 | `_extract_label("R2 reserve")` | R-zone | "R2" | — | Reserve zone |
| A15 | `_extract_label("")` | Empty note | "?" | No label | Fallback |
| A16 | `_extract_label(None)` | None note | "?" | Null safety | No crash |
| A17 | `_extract_sell_actions(recon_with_mixed)` | BUY+SELL actions | Only SELL actions | — | Correct filtering |
| A18 | `_extract_buy_actions(recon_with_mixed)` | BUY+SELL actions | Only BUY actions | — | Correct filtering |
| A19 | `_extract_sell_actions(None)` | No recon | [] | Missing data | No crash |
| A20 | `_extract_sell_actions({})` | Empty recon | [] | No actions key | No crash |

### Layer B: Graph Engine (graph_engine.py)

Core infrastructure — node resolution, signal propagation, state management.

| # | What | Input Setup | Expected Behavior | Why It Matters |
| :--- | :--- | :--- | :--- | :--- |
| B1 | Topological sort — correct order | 3-node chain: A→B→C | resolve() computes A first, then B, then C | Dependency ordering |
| B2 | Circular dependency detection | A depends on B, B depends on A | ValueError raised with "Circular" | Prevents infinite loops |
| B3 | Missing dependency detection | A depends on "nonexistent" | ValueError raised | Clear error message |
| B4 | Signal from changed leaf | leaf prev=50, curr=100 | Signal created with reason | Change detection works |
| B5 | No signal from unchanged leaf | leaf prev=100, curr=100 | No signal | Silence on no change |
| B6 | Signal passthrough | leaf changed → mid unchanged → report | Report gets signal from leaf via mid | Intermediate passthrough |
| B7 | Composable flat_reason | 3-node chain with reasons | "Leaf reason → Mid reason → Report reason" | Reason composition |
| B8 | get_state exports all nodes | Graph with 3 nodes | Dict with all 3 values | Persistence completeness |
| B9 | load_prev_state({}) | Empty prev state | All prev_values are None | First-run handling |
| B10 | load_prev_state partial | Only 1 of 3 nodes in prev | 1 has prev_value, 2 have None | Partial state |
| B11 | get_activated_reports | 2 reports, 1 changed | Only changed report in list | Report filtering |

### Layer C: Graph Builder (graph_builder.py)

Graph construction — correct node types, correct edges, correct reason_fns.

| # | What | Input | Expected | Why It Matters |
| :--- | :--- | :--- | :--- | :--- |
| C1 | Node count for fixture | 3-ticker fixture | ~100-150 nodes (leaves + computed + reports) | Correct graph size |
| C2 | 14 computed nodes per position ticker | CLSK (has position) | CLSK:avg_cost through CLSK:sell_target all exist | Complete per-ticker coverage |
| C3 | No verdict for watchlist-only | AR (shares=0) | AR:verdict exists but returns REVIEW (no price context) | Watchlist doesn't get false verdicts |
| C4 | Entry gate per pending order | AR has 2 BUY orders | AR:order_0:entry_gate and AR:order_1:entry_gate exist | Per-order gates created |
| C5 | Sell target pool-independent | Check CLSK:sell_target depends_on | Contains avg_cost, does NOT contain pool | Analysis Section 10.3 |
| C6 | Verdict calls compute_verdict | CLSK with Bearish momentum | Verdict = ("MONITOR", "R16", "...") | Wraps existing function correctly |
| C7 | Catastrophic threshold | IONQ at -38.1% | catastrophic = "HARD_STOP" | Correct severity |
| C8 | Momentum classification | CLSK RSI 35, MACD below | momentum = "Bearish" | Wraps classify_momentum correctly |
| C9 | Missing price → REVIEW | CLSK price=None | verdict = ("REVIEW", "?", "No price data") | Graceful degradation |
| C10 | Missing earnings → CLEAR | CLSK earnings={} | earnings_gate = "CLEAR" | Safe default |
| C11 | Missing technicals → SKIPPED | CLSK tech={} | momentum = "SKIPPED" | No crash on missing data |
| C12 | Entry gate with Risk-Off | Regime="Risk-Off", watchlist ticker | Combined gate includes "REVIEW" or "PAUSE" | Regime affects gates |
| C13 | Recon depends_on complete | Check recon node | depends_on includes avg_cost, pool, sell_target, trade_history, ticker_profiles | Analysis Section 4.3 |

### Layer D: Signal Propagation (graph_engine.py + graph_builder.py)

End-to-end signal chains from the 4 examples in analysis Section 7.

| # | Signal Chain | Setup | Expected Signal | Flat Reason Contains |
| :--- | :--- | :--- | :--- | :--- |
| D1 | Regime flip → regime_change | prev regime="Neutral", curr="Risk-Off" | regime_change activated | "Regime" and "→" |
| D2 | Regime flip → gate alerts | prev regime="Neutral", curr="Risk-Off", prev gates ACTIVE | gate_alert(s) activated | "Regime" and "Gate" |
| D3 | Avg cost change → sell target | prev CLSK:avg_cost=9.82, curr=8.99 | sell_target changed | "Avg" |
| D4 | Catastrophic new alert | prev IONQ:catastrophic=None, curr=HARD_STOP | catastrophic_alert activated | "Alert" or "HARD_STOP" |
| D5 | Catastrophic resolved | prev IONQ:catastrophic=WARNING, curr=None | catastrophic_alert shows change | — |
| D6 | No change = silence | prev state matches curr state exactly | Zero activated reports | — |

### Layer E: Persistence Schema (graph_builder.py)

Canonical format from analysis Section 9/11.9.

| # | What | Expected |
| :--- | :--- | :--- |
| E1 | Top-level keys | run_date, run_ts, regime, vix, vix_5d_pct, tickers, orders |
| E2 | Per-ticker keys (10) | avg_cost, shares, pl_pct, verdict, catastrophic, momentum, earnings_gate, time_status, pool, sell_target |
| E3 | Verdict format | list with 3 elements [str, str, str] (not a plain string) |
| E4 | Sell target format | list with 2 elements [float, str] (not an object) |
| E5 | Pool format | dict with active_pool, reserve_pool, source keys |
| E6 | Order keys | {ticker}:order_{idx} format |
| E7 | Order fields | gate (tuple), price (float), label (str) |
| E8 | Closed position excluded | Ticker with shares=0 not in tickers dict |

### Layer F: Dashboard Categorization (daily_analyzer.py)

Bucket assignment from analysis Section 11.0.3.

| # | Report Node | Node Value | Expected Bucket |
| :--- | :--- | :--- | :--- |
| F1 | catastrophic_alert | "HARD_STOP" | URGENT |
| F2 | catastrophic_alert | "EXIT_REVIEW" | URGENT |
| F3 | catastrophic_alert | "WARNING" | NOT urgent (omitted from URGENT) |
| F4 | sell_order_action | action="PLACE" | PLACE |
| F5 | sell_order_action | action="ADJUST price" | ADJUST |
| F6 | buy_order_action | action="CANCEL (orphaned)" | CANCEL |
| F7 | verdict_alert | changed from prev | CHANGED |
| F8 | regime_change | changed from prev | CHANGED |
| F9 | gate_alert | changed from prev | CHANGED |
| F10 | review | verdict[0]="REVIEW" | REVIEW |
| F11 | All empty | No signals | "All clear — no actions needed." |

### Layer G: Error Handling

| # | Scenario | Expected Behavior |
| :--- | :--- | :--- |
| G1 | graph.resolve() raises exception | main() catches, prints status-only, doesn't write graph_state.json |
| G2 | One ticker price=None | That ticker gets REVIEW, others resolve normally |
| G3 | First run (no graph_state.json) | _load_graph_state() returns {}, graph proceeds normally |
| G4 | Corrupted graph_state.json | _load_graph_state() returns {}, treated as first run |

### Layer H: Design Constraints

| # | Constraint | How to Verify |
| :--- | :--- | :--- |
| H1 | Single-edge extensibility | Add custom node to graph, verify it appears in get_state() without touching other files |
| H2 | Wrap, don't rewrite | Verify graph nodes call compute_verdict/classify_momentum/etc., not reimplementations |
| H3 | Sell target pool-independent | CLSK:sell_target.depends_on has NO pool reference |

### Layer A Additional (from gap analysis)

| # | Function | Input | Expected Output | Why It Matters |
| :--- | :--- | :--- | :--- | :--- |
| A21 | `_format_action_reason([{reason:"Price shift"}], [Signal(reason="Avg change")])` | Action + child signal | "Avg change → Price shift" | Reason composition for recon report nodes |
| A22 | `_stub().value` | Stub node | None | Missing node graceful degradation in persistence |
| A23 | `_calc_pl(-5.0, 10.0)` | Negative avg_cost | None | Data corruption guard |

### Layer B Additional

| # | What | Input Setup | Expected | Why It Matters |
| :--- | :--- | :--- | :--- | :--- |
| B12 | `Signal.chain_str()` | 3-node signal chain | Multi-line indented string | Debug view correctness |
| B13 | `load_prev_state` with orphan key | prev has "NONEXISTENT:field" | No error, key ignored | Robustness to old/stale state |

### Layer C Additional

| # | What | Input | Expected | Why It Matters |
| :--- | :--- | :--- | :--- | :--- |
| C14 | Watchlist ticker with NO position AND NO orders | Ticker in watchlist only | Zero nodes created for it | Not in active_tickers |
| C15 | Pending order with `placed: False` | BUY order not yet placed | No entry_gate node created | Unplaced orders excluded |
| C16 | Two orders at same price | Same ticker, same price, different idx | Both get unique nodes (order_0, order_1) | Index-based naming no collision |
| C17 | AR verdict with avg_cost=0 | Watchlist with pending orders but no position | Verify actual verdict value | Correct handling of zero avg |
| C18 | Per-ticker node count pattern | CLSK (position + 1 order) | Exactly: 14 computed + 2 decision + 4 report + 2 gate = 22 nodes | Node count per analysis |
| C19 | Entry gate value format | AR:order_0:entry_gate | Tuple with 3 elements (market, earnings, combined) | Gate format correct |

### Layer D Additional

| # | Signal Chain | Setup | Expected |
| :--- | :--- | :--- | :--- |
| D7 | Position closed | prev has IONQ, curr graph has no IONQ (shares=0, no orders) | IONQ nodes absent from curr, prev state orphaned |
| D8 | First run (empty prev_state) | prev_state = {} | All nodes have prev_value=None, signals fire but represent "new" not "changed" |

### Layer E Additional

| # | What | Expected |
| :--- | :--- | :--- |
| E9 | Persisted CLSK avg_cost value | state["tickers"]["CLSK"]["avg_cost"] == 8.99 (from fixture) |
| E10 | Persisted verdict matches graph | state["tickers"]["CLSK"]["verdict"] == graph.nodes["CLSK:verdict"].value |

### Layer G Additional

| # | Scenario | Expected |
| :--- | :--- | :--- |
| G5 | One ticker price=None in full graph | CLSK→REVIEW, IONQ resolves normally, no crash |
| G6 | Recon data empty for all tickers | recon={}, sell/buy_order_action=[], no crash |

---

## 4. What NOT to Test

- **yfinance API calls** — mocked via fixture data
- **Subprocess sections** (Parts 3-6) — outside graph scope
- **print_sell_projections, print_exit_strategy_summary** — unchanged, not graph-driven
- **portfolio_manager.py** — separate module, has its own test concerns

---

## 5. Test Structure

```
tests/test_graph.py
├── TestHelperFunctions (A1-A23)      — pure function unit tests
├── TestGraphEngine (B1-B13)           — engine mechanics
├── TestGraphBuilder (C1-C19)          — node creation and edges
├── TestSignalPropagation (D1-D8)      — end-to-end signal chains
├── TestPersistenceSchema (E1-E10)     — canonical format + value validation
├── TestDashboardBuckets (F1-F11)      — action categorization
├── TestErrorHandling (G1-G6)          — graceful degradation
├── TestDesignConstraints (H1-H3)      — architectural properties
```

**Total: ~83 test cases across 8 test classes.**

---

## 6. Acceptance Criteria

All tests pass. Specifically:
- A1-A23: Every helper returns the expected value for each input including edge cases
- B1-B13: Engine resolves correctly, signals propagate, state persists, debug view works
- C1-C19: Graph has correct nodes with correct edges, per-ticker count verified
- D1-D8: Signal chains produce composable reason strings, first-run and position-closed handled
- E1-E10: Schema matches analysis Section 9/11.9, actual values verified not just keys
- F1-F11: Dashboard buckets match analysis Section 11.0.3 categorization rules
- G1-G6: No crashes on any error scenario including partial failures
- H1-H3: Design constraints from analysis Section 10 hold
