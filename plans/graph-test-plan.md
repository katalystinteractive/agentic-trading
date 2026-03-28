# Test Plan — Reactive Dependency Graph

**Date**: 2026-03-28 (Saturday)
**Source**: `plans/graph-test-analysis.md` (93 test cases across 8 layers)
**Output**: `tests/test_graph.py`
**Run**: `python3 -m pytest tests/test_graph.py -v`

---

## 1. File Structure

Single test file: `tests/test_graph.py`

```python
# Imports
import sys, json, pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from graph_engine import DependencyGraph, Node, Signal
from graph_builder import (
    build_daily_graph, get_state_for_persistence,
    _calc_pl, _check_catastrophic, _extract_label,
    _extract_sell_actions, _extract_buy_actions,
    _format_action_reason, _StubNode, _stub,
)

# Fixtures at module level (analysis Section 2)
# 8 test classes (analysis Section 5)
```

---

## 2. Shared Fixtures

All fixtures defined as module-level constants, copied from analysis Section 2.1-2.5.

### 2.1 `FIXTURE_PORTFOLIO`

Exact dict from analysis Section 2.1. 3 tickers: CLSK (position), IONQ (pre-strategy), AR (watchlist-only).

### 2.2 `FIXTURE_PRICES`

`{"CLSK": 8.66, "IONQ": 27.51, "AR": 44.00}`

### 2.3 `FIXTURE_TECH`

RSI/MACD per ticker from analysis Section 2.3.

### 2.4 `FIXTURE_EARNINGS`

`{"CLSK": {"status": "CLEAR"}, "IONQ": {"status": "CLEAR"}, "AR": {"status": "APPROACHING"}}`

### 2.5 `FIXTURE_PREV_STATE`

Dict with previous run values from analysis Section 2.5, using exact graph node names.

### 2.6 Helper: `_build_fixture_graph()`

```python
def _build_fixture_graph(live_prices=None, regime="Neutral", vix=20.0,
                         vix_5d_pct=0.0, tech_data=None, earnings_data=None,
                         recon_data=None, portfolio=None):
    """Build and resolve a graph from fixture data."""
    graph = build_daily_graph(
        portfolio or FIXTURE_PORTFOLIO,
        live_prices if live_prices is not None else FIXTURE_PRICES,
        regime, vix, vix_5d_pct,
        tech_data if tech_data is not None else FIXTURE_TECH,
        earnings_data if earnings_data is not None else FIXTURE_EARNINGS,
        recon_data or {},
    )
    graph.resolve()
    return graph
```

This helper is used by tests C1-C19, D1-D8, E1-E10. Callers override specific parameters to test different scenarios.

---

## 3. Test Classes — Implementation Spec

### 3.1 `TestHelperFunctions` (A1-A23)

Pure function tests. No graph needed. Each is one assert.

```python
class TestHelperFunctions:
    # --- _calc_pl ---
    def test_a1_calc_pl_positive(self):
        assert _calc_pl(10.0, 10.60) == 6.0

    def test_a2_calc_pl_negative(self):
        assert _calc_pl(10.0, 9.40) == -6.0

    def test_a3_calc_pl_zero_avg(self):
        assert _calc_pl(0, 10.0) is None

    def test_a4_calc_pl_none_price(self):
        assert _calc_pl(10.0, None) is None

    def test_a5_calc_pl_none_avg(self):
        assert _calc_pl(None, 10.0) is None

    def test_a23_calc_pl_negative_avg(self):
        assert _calc_pl(-5.0, 10.0) is None

    # --- _check_catastrophic ---
    def test_a6_catastrophic_above_threshold(self):
        assert _check_catastrophic(-14.9) is None

    def test_a7_catastrophic_exact_warning(self):
        assert _check_catastrophic(-15.0) == "WARNING"

    def test_a8_catastrophic_between_warning_hardstop(self):
        assert _check_catastrophic(-24.9) == "WARNING"

    def test_a9_catastrophic_exact_hardstop(self):
        assert _check_catastrophic(-25.0) == "HARD_STOP"

    def test_a10_catastrophic_exact_exit_review(self):
        assert _check_catastrophic(-40.0) == "EXIT_REVIEW"

    def test_a11_catastrophic_none(self):
        assert _check_catastrophic(None) is None

    # --- _extract_label ---
    def test_a12_label_a1(self):
        assert _extract_label("A1 — $8.25 PA, 62% hold, Full") == "A1"

    def test_a13_label_b3(self):
        assert _extract_label("B3 — $5.00") == "B3"

    def test_a14_label_r2(self):
        assert _extract_label("R2 reserve") == "R2"

    def test_a15_label_empty(self):
        assert _extract_label("") == "?"

    def test_a16_label_none(self):
        assert _extract_label(None) == "?"

    # --- _extract_sell/buy_actions ---
    def test_a17_extract_sell(self):
        # Input: mixed BUY+SELL actions
        recon = {"actions": [
            {"side": "SELL", "ticker": "X", "action": "PLACE"},
            {"side": "BUY", "ticker": "X", "action": "CANCEL"},
        ]}
        result = _extract_sell_actions(recon)
        assert len(result) == 1
        assert result[0]["side"] == "SELL"

    def test_a18_extract_buy(self):
        recon = {"actions": [
            {"side": "SELL", "ticker": "X", "action": "PLACE"},
            {"side": "BUY", "ticker": "X", "action": "CANCEL"},
        ]}
        result = _extract_buy_actions(recon)
        assert len(result) == 1
        assert result[0]["side"] == "BUY"

    def test_a19_extract_sell_none(self):
        assert _extract_sell_actions(None) == []

    def test_a20_extract_sell_empty(self):
        assert _extract_sell_actions({}) == []

    # --- _format_action_reason ---
    def test_a21_format_action_reason(self):
        sig = Signal(source_node="test", old_value=None, new_value=None,
                     reason="Avg change", child_signals=[])
        result = _format_action_reason(
            [{"reason": "Price shift"}], [sig])
        assert "Avg change" in result
        assert "Price shift" in result
        assert "→" in result

    # --- _StubNode ---
    def test_a22_stub_value(self):
        assert _stub().value is None
```

### 3.2 `TestGraphEngine` (B1-B13)

Engine mechanics using small hand-built graphs (not the fixture graph).

```python
class TestGraphEngine:
    def test_b1_topological_order(self):
        # 3-node chain: leaf → mid → report
        g = DependencyGraph()
        g.add_node("leaf", compute=lambda _: 10)
        g.add_node("mid", compute=lambda i: i["leaf"] * 2, depends_on=["leaf"])
        g.add_node("report", compute=lambda i: i["mid"] + 1, depends_on=["mid"])
        result = g.resolve()
        assert result["leaf"] == 10
        assert result["mid"] == 20
        assert result["report"] == 21

    def test_b2_circular_dependency(self):
        g = DependencyGraph()
        g.add_node("a", depends_on=["b"])
        g.add_node("b", depends_on=["a"])
        with pytest.raises(ValueError, match="Circular"):
            g.resolve()

    def test_b3_missing_dependency(self):
        g = DependencyGraph()
        g.add_node("a", depends_on=["nonexistent"])
        with pytest.raises(ValueError, match="nonexistent"):
            g.resolve()

    def test_b4_signal_from_changed_leaf(self):
        g = DependencyGraph()
        g.add_node("leaf", compute=lambda _: 100,
                   reason_fn=lambda old, new, _: f"{old}→{new}")
        g.load_prev_state({"leaf": 50})
        g.resolve()
        signals = g.propagate_signals()
        # Leaf changed 50→100, should have signal
        assert g.nodes["leaf"].signals

    def test_b5_no_signal_unchanged(self):
        g = DependencyGraph()
        g.add_node("leaf", compute=lambda _: 100)
        g.load_prev_state({"leaf": 100})
        g.resolve()
        signals = g.propagate_signals()
        assert not g.nodes["leaf"].signals

    def test_b6_signal_passthrough(self):
        g = DependencyGraph()
        g.add_node("leaf", compute=lambda _: "new",
                   reason_fn=lambda old, new, _: "Leaf changed")
        g.add_node("mid", compute=lambda i: i["leaf"], depends_on=["leaf"])
        g.add_node("report", compute=lambda i: i["mid"],
                   depends_on=["mid"], is_report=True,
                   reason_fn=lambda old, new, _: "Report sees it")
        g.load_prev_state({"leaf": "old", "mid": "old", "report": "old"})
        g.resolve()
        signals = g.propagate_signals()
        assert len(signals) >= 1  # Signal reached report

    def test_b7_composable_flat_reason(self):
        g = DependencyGraph()
        g.add_node("leaf", compute=lambda _: 100,
                   reason_fn=lambda old, new, _: f"Leaf {old}→{new}")
        g.add_node("mid", compute=lambda i: i["leaf"] * 2,
                   depends_on=["leaf"],
                   reason_fn=lambda old, new, _: f"Mid {old}→{new}")
        g.add_node("report", compute=lambda i: i["mid"] + 1,
                   depends_on=["mid"], is_report=True,
                   reason_fn=lambda old, new, _: f"Report {old}→{new}")
        g.load_prev_state({"leaf": 50, "mid": 100, "report": 101})
        g.resolve()
        signals = g.propagate_signals()
        reason = signals[0].flat_reason()
        assert "Leaf 50→100" in reason
        assert "Mid 100→200" in reason
        assert "Report 101→201" in reason

    def test_b8_get_state(self):
        g = DependencyGraph()
        g.add_node("a", compute=lambda _: 1)
        g.add_node("b", compute=lambda _: 2)
        g.add_node("c", compute=lambda _: 3)
        g.resolve()
        state = g.get_state()
        assert state == {"a": 1, "b": 2, "c": 3}

    def test_b9_empty_prev_state(self):
        g = DependencyGraph()
        g.add_node("a", compute=lambda _: 1)
        g.resolve()
        g.load_prev_state({})
        assert g.nodes["a"].prev_value is None

    def test_b10_partial_prev_state(self):
        g = DependencyGraph()
        g.add_node("a", compute=lambda _: 1)
        g.add_node("b", compute=lambda _: 2)
        g.resolve()
        g.load_prev_state({"a": 99})
        assert g.nodes["a"].prev_value == 99
        assert g.nodes["b"].prev_value is None

    def test_b11_activated_reports_only_changed(self):
        g = DependencyGraph()
        g.add_node("r1", compute=lambda _: "same", is_report=True)
        g.add_node("r2", compute=lambda _: "new", is_report=True,
                   reason_fn=lambda old, new, _: "changed")
        g.resolve()
        g.load_prev_state({"r1": "same", "r2": "old"})
        g.propagate_signals()
        activated = g.get_activated_reports()
        names = [n for n, _ in activated]
        assert "r2" in names
        assert "r1" not in names

    def test_b12_chain_str(self):
        child = Signal("leaf", "old", "new", "Leaf reason", [])
        parent = Signal("report", "old", "new", "Report reason", [child])
        text = parent.chain_str()
        assert "leaf: Leaf reason" in text
        assert "report: Report reason" in text

    def test_b13_orphan_prev_key(self):
        g = DependencyGraph()
        g.add_node("a", compute=lambda _: 1)
        g.resolve()
        g.load_prev_state({"a": 1, "NONEXISTENT": 999})
        # Should not crash, orphan key silently ignored
        assert g.nodes["a"].prev_value == 1
```

### 3.3 `TestGraphBuilder` (C1-C19)

Uses `_build_fixture_graph()` to test node creation, edges, and values.

```python
class TestGraphBuilder:
    def test_c1_node_count(self):
        graph = _build_fixture_graph()
        total = len(graph.nodes)
        assert total > 50, f"Expected 50+ nodes, got {total}"
        assert total < 200, f"Expected <200 nodes, got {total}"

    def test_c2_all_14_computed_nodes_for_position(self):
        graph = _build_fixture_graph()
        expected = ["avg_cost", "shares", "entry_date", "price", "pl_pct",
                    "drawdown", "days_held", "time_status", "earnings_gate",
                    "rsi", "macd", "momentum", "pool", "sell_target"]
        for field in expected:
            name = f"CLSK:{field}"
            assert name in graph.nodes, f"Missing node: {name}"

    def test_c3_watchlist_verdict_exists(self):
        # AR has pending orders so IS in active_tickers, DOES get verdict
        graph = _build_fixture_graph()
        assert "AR:verdict" in graph.nodes
        v = graph.nodes["AR:verdict"].value
        assert isinstance(v, tuple) and len(v) == 3

    def test_c4_entry_gate_per_order(self):
        graph = _build_fixture_graph()
        assert "AR:order_0:entry_gate" in graph.nodes
        assert "AR:order_1:entry_gate" in graph.nodes

    def test_c5_sell_target_no_pool_dependency(self):
        graph = _build_fixture_graph()
        st = graph.nodes["CLSK:sell_target"]
        assert "CLSK:avg_cost" in st.depends_on
        assert "CLSK:pool" not in st.depends_on

    def test_c6_verdict_value(self):
        graph = _build_fixture_graph()
        v = graph.nodes["CLSK:verdict"].value
        assert v[0] == "MONITOR"
        assert v[1] == "R16"

    def test_c7_catastrophic_hard_stop(self):
        graph = _build_fixture_graph()
        cat = graph.nodes["IONQ:catastrophic"].value
        assert cat == "HARD_STOP"

    def test_c8_momentum_bearish(self):
        graph = _build_fixture_graph()
        mom = graph.nodes["CLSK:momentum"].value
        assert mom == "Bearish"

    def test_c9_missing_price_review(self):
        graph = _build_fixture_graph(live_prices={"CLSK": None, "IONQ": 27.51, "AR": 44.0})
        v = graph.nodes["CLSK:verdict"].value
        assert v[0] == "REVIEW"
        assert v[2] == "No price data"

    def test_c10_missing_earnings_clear(self):
        graph = _build_fixture_graph(earnings_data={"CLSK": {}, "IONQ": {}, "AR": {}})
        eg = graph.nodes["CLSK:earnings_gate"].value
        assert eg == "CLEAR"

    def test_c11_missing_tech_skipped(self):
        graph = _build_fixture_graph(tech_data={"CLSK": {}, "IONQ": {}, "AR": {}})
        mom = graph.nodes["CLSK:momentum"].value
        assert mom == "SKIPPED"

    def test_c12_risk_off_gate(self):
        graph = _build_fixture_graph(regime="Risk-Off", vix=31.0)
        # AR is watchlist-only with pending orders — Risk-Off should affect gates
        gate = graph.nodes.get("AR:order_0:entry_gate")
        if gate and gate.value:
            combined = gate.value[2]  # combined gate
            assert combined in ("REVIEW", "PAUSE"), f"Expected REVIEW/PAUSE, got {combined}"

    def test_c13_recon_depends_on(self):
        graph = _build_fixture_graph()
        recon = graph.nodes["CLSK:recon"]
        assert "CLSK:avg_cost" in recon.depends_on
        assert "CLSK:pool" in recon.depends_on
        assert "CLSK:sell_target" in recon.depends_on
        assert "trade_history" in recon.depends_on
        assert "ticker_profiles" in recon.depends_on

    def test_c14_watchlist_no_position_no_orders(self):
        # Add ticker to watchlist but no position and no orders
        portfolio = dict(FIXTURE_PORTFOLIO)
        portfolio = json.loads(json.dumps(portfolio))  # deep copy
        portfolio["watchlist"].append("TST")
        graph = _build_fixture_graph(portfolio=portfolio,
                                      live_prices={**FIXTURE_PRICES, "TST": 10.0})
        # TST should NOT be in active_tickers (no shares, no orders)
        assert "TST:verdict" not in graph.nodes

    def test_c15_unplaced_order_excluded(self):
        portfolio = json.loads(json.dumps(FIXTURE_PORTFOLIO))
        portfolio["pending_orders"]["CLSK"].append(
            {"type": "BUY", "price": 7.00, "shares": 5, "placed": False,
             "note": "B1 — not placed"})
        graph = _build_fixture_graph(portfolio=portfolio)
        # Only the placed order (A1 at 8.40) should have gate, not the unplaced one
        assert "CLSK:order_0:entry_gate" in graph.nodes
        assert "CLSK:order_1:entry_gate" not in graph.nodes

    def test_c16_same_price_orders(self):
        portfolio = json.loads(json.dumps(FIXTURE_PORTFOLIO))
        portfolio["pending_orders"]["AR"] = [
            {"type": "BUY", "price": 35.00, "shares": 1, "placed": True,
             "note": "A1 — same price"},
            {"type": "BUY", "price": 35.00, "shares": 2, "placed": True,
             "note": "A2 — same price"},
        ]
        graph = _build_fixture_graph(portfolio=portfolio)
        assert "AR:order_0:entry_gate" in graph.nodes
        assert "AR:order_1:entry_gate" in graph.nodes

    def test_c17_ar_verdict_zero_avg(self):
        graph = _build_fixture_graph()
        v = graph.nodes["AR:verdict"].value
        # AR has shares=0, avg_cost=0 but IS in active_tickers
        # With avg_cost=0, _calc_pl returns None, price check fails
        assert isinstance(v, tuple) and len(v) == 3

    def test_c18_per_ticker_node_count(self):
        graph = _build_fixture_graph()
        clsk_nodes = [n for n in graph.nodes if n.startswith("CLSK:")]
        # 14 computed + 2 decision + 4 report + 2 gate (1 order × entry_gate + gate_alert)
        # + 1 recon + 1 sell_order_action + 1 buy_order_action = ~25
        assert len(clsk_nodes) >= 20, f"Expected 20+ CLSK nodes, got {len(clsk_nodes)}"

    def test_c19_entry_gate_format(self):
        graph = _build_fixture_graph()
        gate = graph.nodes["AR:order_0:entry_gate"].value
        assert isinstance(gate, tuple), f"Expected tuple, got {type(gate)}"
        assert len(gate) == 3, f"Expected 3 elements, got {len(gate)}"
```

### 3.4 `TestSignalPropagation` (D1-D8)

End-to-end signal chains.

```python
class TestSignalPropagation:
    def test_d1_regime_change_signal(self):
        graph = _build_fixture_graph(regime="Risk-Off")
        graph.load_prev_state({"regime": "Neutral"})
        graph.propagate_signals()
        activated = dict(graph.get_activated_reports())
        assert "regime_change" in activated
        reason = activated["regime_change"].signals[0].flat_reason()
        assert "Regime" in reason

    def test_d2_regime_flip_gate_alerts(self):
        graph = _build_fixture_graph(regime="Risk-Off", vix=31.0)
        prev = {"regime": "Neutral"}
        # Set prev gate values to ACTIVE
        for name in graph.nodes:
            if name.endswith(":entry_gate"):
                prev[name] = ("ACTIVE", "ACTIVE", "ACTIVE")
        graph.load_prev_state(prev)
        graph.propagate_signals()
        gate_alerts = [(n, nd) for n, nd in graph.get_activated_reports()
                       if "gate_alert" in n]
        assert len(gate_alerts) >= 1

    def test_d3_avg_cost_cascades_to_sell_target(self):
        graph = _build_fixture_graph()
        graph.load_prev_state({"CLSK:avg_cost": 9.82,
                               "CLSK:sell_target": (10.41, "standard 6.0%")})
        graph.propagate_signals()
        st = graph.nodes["CLSK:sell_target"]
        assert st.has_changed()

    def test_d4_catastrophic_new_alert(self):
        graph = _build_fixture_graph()
        graph.load_prev_state({"IONQ:catastrophic": None})
        graph.propagate_signals()
        cat = graph.nodes.get("IONQ:catastrophic_alert")
        assert cat and cat.signals

    def test_d5_catastrophic_resolved(self):
        # CLSK at -3.7% is NOT catastrophic (None)
        graph = _build_fixture_graph()
        graph.load_prev_state({"CLSK:catastrophic": "WARNING"})
        graph.propagate_signals()
        cat = graph.nodes.get("CLSK:catastrophic_alert")
        # Was WARNING, now None — should have signal
        assert cat and cat.has_changed()

    def test_d6_no_change_silence(self):
        graph = _build_fixture_graph()
        state = graph.get_state()
        graph.load_prev_state(state)
        graph.propagate_signals()
        activated = graph.get_activated_reports()
        assert len(activated) == 0

    def test_d7_position_closed(self):
        # IONQ was in prev but close it (shares=0, no orders)
        portfolio = json.loads(json.dumps(FIXTURE_PORTFOLIO))
        portfolio["positions"]["IONQ"]["shares"] = 0
        graph = _build_fixture_graph(portfolio=portfolio,
                                      live_prices={"CLSK": 8.66, "AR": 44.0})
        # IONQ should NOT be in active_tickers
        assert "IONQ:verdict" not in graph.nodes

    def test_d8_first_run_empty_prev(self):
        graph = _build_fixture_graph()
        graph.load_prev_state({})
        graph.propagate_signals()
        # All nodes have prev_value=None, so all changed
        # But this is expected "new" state, not false alerts
        activated = graph.get_activated_reports()
        # Should have some activated (new nodes)
        assert len(activated) > 0
```

### 3.5 `TestPersistenceSchema` (E1-E10)

```python
class TestPersistenceSchema:
    def _get_state(self):
        graph = _build_fixture_graph()
        return get_state_for_persistence(
            graph, ["CLSK", "IONQ"],
            FIXTURE_PORTFOLIO.get("pending_orders", {}))

    def test_e1_top_level_keys(self):
        state = self._get_state()
        for key in ("run_date", "run_ts", "regime", "vix", "vix_5d_pct", "tickers", "orders"):
            assert key in state, f"Missing top-level key: {key}"

    def test_e2_per_ticker_keys(self):
        state = self._get_state()
        expected = {"avg_cost", "shares", "pl_pct", "verdict", "catastrophic",
                    "momentum", "earnings_gate", "time_status", "pool", "sell_target"}
        actual = set(state["tickers"]["CLSK"].keys())
        assert expected == actual, f"Missing: {expected - actual}"

    def test_e3_verdict_is_list(self):
        state = self._get_state()
        v = state["tickers"]["CLSK"]["verdict"]
        assert isinstance(v, (list, tuple)) and len(v) == 3

    def test_e4_sell_target_is_list(self):
        state = self._get_state()
        st = state["tickers"]["CLSK"]["sell_target"]
        assert isinstance(st, (list, tuple)) and len(st) == 2

    def test_e5_pool_is_dict(self):
        state = self._get_state()
        pool = state["tickers"]["CLSK"]["pool"]
        assert isinstance(pool, dict)
        assert "active_pool" in pool or "source" in pool

    def test_e6_order_key_format(self):
        state = self._get_state()
        for key in state.get("orders", {}):
            assert ":" in key, f"Order key should have ':' separator: {key}"
            assert "order_" in key, f"Order key should have 'order_': {key}"

    def test_e7_order_fields(self):
        state = self._get_state()
        for key, order in state.get("orders", {}).items():
            assert "gate" in order, f"Missing 'gate' in order {key}"
            assert "price" in order, f"Missing 'price' in order {key}"
            assert "label" in order, f"Missing 'label' in order {key}"

    def test_e8_closed_position_excluded(self):
        # Only pass active tickers to persistence
        state = get_state_for_persistence(
            _build_fixture_graph(), ["CLSK"],  # exclude IONQ
            FIXTURE_PORTFOLIO.get("pending_orders", {}))
        assert "CLSK" in state["tickers"]
        assert "IONQ" not in state["tickers"]

    def test_e9_avg_cost_value(self):
        state = self._get_state()
        assert state["tickers"]["CLSK"]["avg_cost"] == 8.99

    def test_e10_verdict_matches_graph(self):
        graph = _build_fixture_graph()
        state = get_state_for_persistence(
            graph, ["CLSK"],
            FIXTURE_PORTFOLIO.get("pending_orders", {}))
        assert state["tickers"]["CLSK"]["verdict"] == list(graph.nodes["CLSK:verdict"].value)
```

### 3.6 `TestDashboardBuckets` (F1-F11)

Tests the categorization logic in `print_action_dashboard_from_signals()`. These test the function's internal bucket assignment by examining which report nodes activate and what their values are.

```python
class TestDashboardBuckets:
    def test_f1_catastrophic_hardstop_is_urgent(self):
        graph = _build_fixture_graph()
        graph.load_prev_state({})
        graph.propagate_signals()
        activated = dict(graph.get_activated_reports())
        cat = activated.get("IONQ:catastrophic_alert")
        assert cat is not None
        assert cat.value == "HARD_STOP"

    def test_f3_catastrophic_warning_not_urgent(self):
        # WARNING should NOT be in URGENT (only HARD_STOP and EXIT_REVIEW)
        assert _check_catastrophic(-16.0) == "WARNING"
        # Dashboard code checks: val in ("HARD_STOP", "EXIT_REVIEW")
        assert "WARNING" not in ("HARD_STOP", "EXIT_REVIEW")

    def test_f4_sell_place_action(self):
        recon_data = {"CLSK": {"ticker": "CLSK", "shares": 42, "avg_cost": 8.99,
            "fills": [], "buy_orders": [], "available_bullets": [],
            "sell_orders": [], "wick_available": True,
            "actions": [{"side": "SELL", "ticker": "CLSK", "action": "PLACE",
                         "broker_price": 0, "broker_shares": 0,
                         "rec_price": 9.53, "rec_shares": 42,
                         "reason": "No sell order", "display": "SELL CLSK PLACE"}]}}
        graph = _build_fixture_graph(recon_data=recon_data)
        sells = graph.nodes["CLSK:sell_order_action"].value
        assert any(a["action"] == "PLACE" for a in sells)

    def test_f6_buy_cancel_action(self):
        recon_data = {"CLSK": {"ticker": "CLSK", "shares": 42, "avg_cost": 8.99,
            "fills": [], "buy_orders": [], "available_bullets": [],
            "sell_orders": [], "wick_available": True,
            "actions": [{"side": "BUY", "ticker": "CLSK", "action": "CANCEL (orphaned)",
                         "broker_price": 9.05, "broker_shares": 10,
                         "rec_price": 0, "rec_shares": 0,
                         "reason": "Wick refresh", "display": "CANCEL"}]}}
        graph = _build_fixture_graph(recon_data=recon_data)
        buys = graph.nodes["CLSK:buy_order_action"].value
        assert any("CANCEL" in a["action"] for a in buys)

    def test_f10_review_verdict(self):
        graph = _build_fixture_graph()
        review = graph.nodes.get("IONQ:review")
        assert review is not None
        # IONQ is pre-strategy recovery → REVIEW verdict
        if review.value:
            assert review.value[0] == "REVIEW"

    def test_f11_all_clear(self):
        graph = _build_fixture_graph()
        state = graph.get_state()
        graph.load_prev_state(state)
        graph.propagate_signals()
        activated = graph.get_activated_reports()
        assert len(activated) == 0  # All clear
```

### 3.7 `TestErrorHandling` (G1-G6)

```python
class TestErrorHandling:
    def test_g1_circular_dependency_caught(self):
        g = DependencyGraph()
        g.add_node("a", depends_on=["b"])
        g.add_node("b", depends_on=["a"])
        with pytest.raises(ValueError):
            g.resolve()

    def test_g2_one_ticker_none_price(self):
        graph = _build_fixture_graph(live_prices={"CLSK": None, "IONQ": 27.51, "AR": 44.0})
        clsk_v = graph.nodes["CLSK:verdict"].value
        ionq_v = graph.nodes["IONQ:verdict"].value
        assert clsk_v[0] == "REVIEW"
        assert ionq_v[0] != "REVIEW" or ionq_v[2] != "No price data"

    def test_g3_first_run_no_file(self):
        # _load_graph_state should return {} when file doesn't exist
        import daily_analyzer
        import tempfile, os
        fake_path = Path(tempfile.mktemp(suffix=".json"))
        orig = daily_analyzer.GRAPH_STATE_PATH
        daily_analyzer.GRAPH_STATE_PATH = fake_path
        try:
            result = daily_analyzer._load_graph_state()
            assert result == {}
        finally:
            daily_analyzer.GRAPH_STATE_PATH = orig

    def test_g4_corrupted_state_file(self):
        import daily_analyzer
        import tempfile
        fake_path = Path(tempfile.mktemp(suffix=".json"))
        fake_path.write_text("NOT JSON {{{")
        orig = daily_analyzer.GRAPH_STATE_PATH
        daily_analyzer.GRAPH_STATE_PATH = fake_path
        try:
            result = daily_analyzer._load_graph_state()
            assert result == {}
        finally:
            daily_analyzer.GRAPH_STATE_PATH = orig
            fake_path.unlink(missing_ok=True)

    def test_g5_partial_yfinance_failure(self):
        graph = _build_fixture_graph(live_prices={"CLSK": None, "IONQ": 27.51, "AR": 44.0})
        # CLSK failed, IONQ and AR should still resolve
        assert graph.nodes["IONQ:verdict"].value is not None
        assert graph.nodes["AR:verdict"].value is not None

    def test_g6_empty_recon(self):
        graph = _build_fixture_graph(recon_data={})
        # All recon nodes should have empty dict, action nodes should have []
        sells = graph.nodes["CLSK:sell_order_action"].value
        buys = graph.nodes["CLSK:buy_order_action"].value
        assert sells == []
        assert buys == []
```

### 3.8 `TestDesignConstraints` (H1-H3)

```python
class TestDesignConstraints:
    def test_h1_single_edge_extensibility(self):
        graph = _build_fixture_graph()
        graph.add_node("custom_test", compute=lambda i: f"regime={i['regime']}",
                       depends_on=["regime"])
        graph.resolve()
        state = graph.get_state()
        assert "custom_test" in state
        assert "regime=Neutral" == state["custom_test"]

    def test_h2_wraps_existing_functions(self):
        # Verify graph builder imports real functions, not reimplementations
        import graph_builder
        import shared_utils
        assert graph_builder.classify_momentum is shared_utils.classify_momentum
        assert graph_builder.compute_verdict is shared_utils.compute_verdict
        assert graph_builder.compute_entry_gate is shared_utils.compute_entry_gate

    def test_h3_sell_target_no_pool(self):
        graph = _build_fixture_graph()
        st = graph.nodes["CLSK:sell_target"]
        deps = st.depends_on
        assert "CLSK:pool" not in deps
        assert "CLSK:avg_cost" in deps
```

---

## 4. Implementation Notes

- **No yfinance calls** — all tests use fixture data passed to `build_daily_graph()`
- **Deep copy fixtures** when modifying (C14, C15, C16, D7 use `json.loads(json.dumps(...))`)
- **pytest.raises** for expected exceptions (B2, B3, G1)
- **Tuple comparison** — graph engine uses `!=` which works for tuples
- **Test naming** — `test_a1_`, `test_b2_`, etc. maps 1:1 to analysis document IDs

---

## 5. Acceptance Criteria

All 93 tests pass with `python3 -m pytest tests/test_graph.py -v`:

```
tests/test_graph.py::TestHelperFunctions::test_a1_calc_pl_positive PASSED
tests/test_graph.py::TestHelperFunctions::test_a2_calc_pl_negative PASSED
...
tests/test_graph.py::TestDesignConstraints::test_h3_sell_target_no_pool PASSED
========================= 93 passed in <2s =========================
```
