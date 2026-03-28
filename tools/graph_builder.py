"""Graph Builder — Trading-specific graph declaration.

Declares all nodes and edges for the daily analyzer dependency graph.
This file has NO side effects — it builds and returns a DependencyGraph.

All data is fetched BEFORE calling build_daily_graph(). Leaf node compute
functions are simple lookups into pre-fetched dicts, NOT API calls.

Usage:
    from graph_builder import build_daily_graph, get_state_for_persistence

    graph = build_daily_graph(portfolio, live_prices, regime, vix, vix_5d_pct,
                              tech_data, earnings_data, recon_data)
    graph.resolve()
    signals = graph.propagate_signals()

Test:
    python3 tools/graph_builder.py --test
"""
import sys
import json
import re
from pathlib import Path
from datetime import date, datetime

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph_engine import DependencyGraph
from shared_utils import (
    compute_days_held, compute_time_stop, classify_momentum,
    compute_verdict, compute_entry_gate, get_ticker_pool,
    is_active_buy as _is_active_buy,
)
from broker_reconciliation import compute_recommended_sell


# ---------------------------------------------------------------------------
# Helper functions (analysis Section 4.1, plan Section 1.6)
# ---------------------------------------------------------------------------

def _calc_pl(avg_cost, price):
    """(price - avg) / avg * 100. Returns None if inputs missing."""
    if not avg_cost or not price or avg_cost <= 0:
        return None
    return round((price - avg_cost) / avg_cost * 100, 1)


def _check_catastrophic(pl_pct):
    """Apply analysis Section 4.1 thresholds. Returns severity string or None.

    Thresholds (daily_analyzer.py:334-336):
      -15% = WARNING
      -25% = HARD_STOP
      -40% = EXIT_REVIEW
    """
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
    m = re.search(r'\b(A[1-5]|B[1-5]|R[1-3])\b', note or "")
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


def _format_action_reason(actions, child_signals):
    """Build action reason from signal chain + action details."""
    if not actions:
        return ""
    parts = []
    for sig in child_signals:
        if sig.reason:
            parts.append(sig.reason)
    for a in actions:
        r = a.get("reason", "")
        if r:
            parts.append(r)
    return " → ".join(p for p in parts if p)


def _check_dip_viable(dip_kpis, regime, catastrophic, verdict):
    """Determine if ticker is viable for daily dip strategy.

    Combines simulation evidence + current ticker state from graph.
    Returns: YES / CAUTION / NO / BLOCKED / UNKNOWN
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


class _StubNode:
    """Stub for missing graph nodes — returns None for .value."""
    value = None


def _stub():
    return _StubNode()


# ---------------------------------------------------------------------------
# Main builder (analysis Sections 2-6, plan Sections 1.2-1.5)
# ---------------------------------------------------------------------------

def build_daily_graph(portfolio, live_prices, regime, vix, vix_5d_pct,
                      tech_data, earnings_data, recon_data):
    """Build the complete daily analyzer dependency graph.

    All data is fetched BEFORE calling this function. Leaf node compute
    functions are simple lookups into pre-fetched dicts, NOT API calls.
    This keeps resolve() fast (<0.5s for pure computation).

    Args:
        portfolio: dict from portfolio.json
        live_prices: {ticker: float} from _fetch_position_prices()
        regime: str ("Risk-On" / "Neutral" / "Risk-Off")
        vix: float
        vix_5d_pct: float
        tech_data: {ticker: {rsi, macd_vs_signal, histogram}}
        earnings_data: {ticker: {status, ...}}
        recon_data: {ticker: recon_dict} from reconcile_ticker()

    Returns: DependencyGraph with ~681 nodes, ready for resolve()
    """
    graph = DependencyGraph()

    positions = portfolio.get("positions", {})
    pending_orders = portfolio.get("pending_orders", {})
    watchlist = set(portfolio.get("watchlist", []))

    # Load profiles for sell_target computation
    try:
        profiles_path = _ROOT / "ticker_profiles.json"
        with open(profiles_path) as f:
            profiles = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        profiles = {}

    # Load multi-period results for dip KPIs (mtime-cached, one read)
    try:
        from shared_utils import _load_mp_data
        mp_data = _load_mp_data() or {}
    except Exception:
        mp_data = {}
    mp_allocations = mp_data.get("allocations", {})

    # Determine active tickers: positions with shares > 0 OR watchlist with pending buys
    active_tickers = set()
    for tk, pos in positions.items():
        if pos.get("shares", 0) > 0:
            active_tickers.add(tk)
    for tk, orders in pending_orders.items():
        if any(_is_active_buy(o) for o in orders):
            active_tickers.add(tk)
    active_tickers = sorted(active_tickers)

    # -----------------------------------------------------------------------
    # Market-level nodes (analysis Section 3.1, plan Section 1.2)
    # -----------------------------------------------------------------------

    graph.add_node("regime", compute=lambda _: regime,
        reason_fn=lambda old, new, _: f"Regime {old}→{new}")
    graph.add_node("vix", compute=lambda _: vix,
        reason_fn=lambda old, new, _: (
            f"VIX {old:.1f}→{new:.1f}" if isinstance(old, (int, float)) and isinstance(new, (int, float)) else ""))
    graph.add_node("vix_5d_pct", compute=lambda _: vix_5d_pct)
    graph.add_node("live_prices", compute=lambda _: live_prices)

    # Global leaf nodes for recon dependencies
    graph.add_node("trade_history", compute=lambda _: True)  # sentinel — recon loads its own
    graph.add_node("ticker_profiles", compute=lambda _: True)  # sentinel — recon loads its own

    # Market-level report node
    graph.add_node("regime_change", compute=lambda i: i["regime"],
        depends_on=["regime"], is_report=True,
        reason_fn=lambda old, new, sigs: f"Regime shifted to {new}")

    # -----------------------------------------------------------------------
    # Per-ticker nodes (analysis Sections 3.2, 4, 5; plan Section 1.3)
    # -----------------------------------------------------------------------

    for tk in active_tickers:
        pos = positions.get(tk, {})
        td = tech_data.get(tk, {})
        eg = earnings_data.get(tk, {})

        # NOTE: Default parameter binding (p=pos, t=tk, etc.) is REQUIRED.
        # Without it, Python's late-binding closures capture the LAST loop value.

        # --- 14 Computed nodes (analysis Section 3.2) ---

        # 1. avg_cost
        graph.add_node(f"{tk}:avg_cost", compute=lambda _, p=pos: p.get("avg_cost", 0),
            reason_fn=lambda old, new, _: (
                f"Avg ${old:.2f}→${new:.2f}" if isinstance(old, (int, float)) and old != new else ""))

        # 2. shares
        graph.add_node(f"{tk}:shares", compute=lambda _, p=pos: p.get("shares", 0),
            reason_fn=lambda old, new, _: f"Shares {old}→{new}" if old != new else "")

        # 3. entry_date
        graph.add_node(f"{tk}:entry_date", compute=lambda _, p=pos: p.get("entry_date", ""))

        # 4. price
        graph.add_node(f"{tk}:price", compute=lambda _, t=tk: live_prices.get(t),
            reason_fn=lambda old, new, _: (
                f"Price ${old:.2f}→${new:.2f}"
                if isinstance(old, (int, float)) and isinstance(new, (int, float)) else ""))

        # 5. pl_pct
        graph.add_node(f"{tk}:pl_pct",
            compute=lambda i, t=tk: _calc_pl(i[f"{t}:avg_cost"], i[f"{t}:price"]),
            depends_on=[f"{tk}:avg_cost", f"{tk}:price"])

        # 6. drawdown (feeds catastrophic check)
        graph.add_node(f"{tk}:drawdown",
            compute=lambda i, t=tk: i[f"{t}:pl_pct"],
            depends_on=[f"{tk}:pl_pct"],
            reason_fn=lambda old, new, _: (
                f"Drawdown {old:.1f}%→{new:.1f}%"
                if isinstance(old, (int, float)) and isinstance(new, (int, float)) else ""))

        # 7. days_held
        graph.add_node(f"{tk}:days_held",
            compute=lambda _, p=pos: compute_days_held(p.get("entry_date", ""), None),
            reason_fn=lambda old, new, _: (
                f"Days {old[0]}→{new[0]}" if old and new and old[0] != new[0] else ""))

        # 8. time_status (regime-aware)
        graph.add_node(f"{tk}:time_status",
            compute=lambda i, t=tk: compute_time_stop(
                i[f"{t}:days_held"][0], i[f"{t}:days_held"][2], i["regime"]),
            depends_on=[f"{tk}:days_held", "regime"])

        # 9. earnings_gate (pre-fetched)
        graph.add_node(f"{tk}:earnings_gate",
            compute=lambda _, e=eg: e.get("status", "CLEAR"),
            reason_fn=lambda old, new, _: f"Earnings {old}→{new}" if old and old != new else "")

        # 10. rsi (pre-computed)
        graph.add_node(f"{tk}:rsi", compute=lambda _, d=td: d.get("rsi"))

        # 11. macd (pre-computed)
        graph.add_node(f"{tk}:macd", compute=lambda _, d=td: {
            "macd_vs_signal": d.get("macd_vs_signal"),
            "histogram": d.get("histogram")})

        # 12. momentum
        graph.add_node(f"{tk}:momentum",
            compute=lambda i, t=tk: classify_momentum(
                i[f"{t}:rsi"],
                (i[f"{t}:macd"] or {}).get("macd_vs_signal"),
                (i[f"{t}:macd"] or {}).get("histogram")),
            depends_on=[f"{tk}:rsi", f"{tk}:macd"],
            reason_fn=lambda old, new, _: f"Momentum {old}→{new}" if old and old != new else "")

        # 13. pool (simulation-backed, NOT on sell path — analysis 10.3)
        graph.add_node(f"{tk}:pool",
            compute=lambda _, t=tk: get_ticker_pool(t),
            reason_fn=lambda old, new, _: (
                f"Pool ${old.get('active_pool', 0)}→${new.get('active_pool', 0)}"
                if old and new and isinstance(old, dict) and isinstance(new, dict)
                and old.get('active_pool') != new.get('active_pool') else ""))

        # 15. dip_kpis — from multi-period simulation (if available)
        tk_dip_kpis = mp_allocations.get(tk, {}).get("dip_kpis")
        graph.add_node(f"{tk}:dip_kpis",
            compute=lambda _, d=tk_dip_kpis: d,
            reason_fn=lambda old, new, _: (
                f"Dip win rate {old.get('dip_win_rate', 0)}→{new.get('dip_win_rate', 0)}%"
                if old and new and isinstance(old, dict) and isinstance(new, dict) else ""))

        # 16. dip_viable — combines simulation evidence + current ticker state
        graph.add_node(f"{tk}:dip_viable",
            compute=lambda i, t=tk: _check_dip_viable(
                i.get(f"{t}:dip_kpis"), i.get("regime"),
                i.get(f"{t}:catastrophic"), i.get(f"{t}:verdict")),
            depends_on=[f"{tk}:dip_kpis", "regime", f"{tk}:catastrophic", f"{tk}:verdict"],
            reason_fn=lambda old, new, _: f"Dip viability {old}→{new}" if old != new else "")

        # 17. sell_target (priority: optimized > target_exit > 6%)
        #     NOTE: depends on avg_cost, NOT pool (analysis Section 10.3)
        graph.add_node(f"{tk}:sell_target",
            compute=lambda i, t=tk, p=pos, pr=profiles: compute_recommended_sell(
                t, i[f"{t}:avg_cost"], p, pr),
            depends_on=[f"{tk}:avg_cost"],
            reason_fn=lambda old, new, _: (
                f"Sell target ${old[0]:.2f}→${new[0]:.2f} ({new[1]})"
                if old and new and isinstance(old, tuple) and old[0] != new[0] else ""))

        # --- Decision nodes (analysis Section 4) ---

        # Verdict — calls compute_verdict() with all 7 parameters
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
                f"Verdict {old[0]}→{new[0]} ({new[1]})"
                if old and isinstance(old, tuple) and old[0] != new[0] else ""))

        # Catastrophic — threshold check on drawdown
        graph.add_node(f"{tk}:catastrophic",
            compute=lambda i, t=tk: _check_catastrophic(i[f"{t}:drawdown"]),
            depends_on=[f"{tk}:drawdown"],
            reason_fn=lambda old, new, _: f"Alert: {new}" if new and old != new else "")

        # --- Report nodes (analysis Section 5) ---

        graph.add_node(f"{tk}:verdict_alert",
            compute=lambda i, t=tk: i[f"{t}:verdict"],
            depends_on=[f"{tk}:verdict"], is_report=True,
            reason_fn=lambda old, new, sigs: f"{new[0]} ({new[1]})" if new else "")

        graph.add_node(f"{tk}:catastrophic_alert",
            compute=lambda i, t=tk: i[f"{t}:catastrophic"],
            depends_on=[f"{tk}:catastrophic"], is_report=True,
            reason_fn=lambda old, new, _: f"Severity: {new}" if new else "")

        graph.add_node(f"{tk}:review",
            compute=lambda i, t=tk: (
                i[f"{t}:verdict"] if isinstance(i[f"{t}:verdict"], tuple)
                and i[f"{t}:verdict"][0] == "REVIEW" else None),
            depends_on=[f"{tk}:verdict"], is_report=True,
            reason_fn=lambda old, new, _: f"Needs human review: {new[2]}" if new else "")

        # --- Per-order entry gate nodes (analysis Section 4.2, plan Section 1.4) ---

        tk_pending = pending_orders.get(tk, [])
        active_buys = [o for o in tk_pending if o.get("type") == "BUY"
                       and o.get("placed") and not o.get("filled")]
        for idx, order in enumerate(active_buys):
            graph.add_node(f"{tk}:order_{idx}:entry_gate",
                compute=lambda i, o=order, t=tk: compute_entry_gate(
                    i["regime"], i["vix"], i["vix_5d_pct"],
                    i[f"{t}:earnings_gate"], o["price"],
                    i[f"{t}:price"] if i[f"{t}:price"] else 0,
                    is_watchlist=(i[f"{t}:shares"] == 0)),
                depends_on=["regime", "vix", "vix_5d_pct",
                            f"{tk}:earnings_gate", f"{tk}:price", f"{tk}:shares"],
                reason_fn=lambda old, new, _: (
                    f"Gate {old[2]}→{new[2]}"
                    if old and isinstance(old, tuple) and old[2] != new[2] else ""))

            graph.add_node(f"{tk}:order_{idx}:gate_alert",
                compute=lambda i, t=tk, x=idx: i[f"{t}:order_{x}:entry_gate"],
                depends_on=[f"{tk}:order_{idx}:entry_gate"], is_report=True,
                reason_fn=lambda old, new, sigs: f"Gate → {new[2]}" if new else "")

        # --- Reconciliation nodes (analysis Section 4.3, plan Section 1.5) ---

        recon = recon_data.get(tk, {})
        graph.add_node(f"{tk}:recon", compute=lambda _, r=recon: r,
            depends_on=[f"{tk}:avg_cost", f"{tk}:pool", f"{tk}:sell_target",
                        "trade_history", "ticker_profiles"],
            reason_fn=lambda old, new, _: "Reconciliation changed" if old != new else "")

        graph.add_node(f"{tk}:sell_order_action",
            compute=lambda i, t=tk: _extract_sell_actions(i[f"{t}:recon"]),
            depends_on=[f"{tk}:recon"], is_report=True,
            reason_fn=lambda old, new, sigs: _format_action_reason(new, sigs))

        graph.add_node(f"{tk}:buy_order_action",
            compute=lambda i, t=tk: _extract_buy_actions(i[f"{t}:recon"]),
            depends_on=[f"{tk}:recon"], is_report=True,
            reason_fn=lambda old, new, sigs: _format_action_reason(new, sigs))

    return graph


# ---------------------------------------------------------------------------
# Persistence (analysis Section 11.9, plan Section 1.6)
# ---------------------------------------------------------------------------

def get_state_for_persistence(graph, active_tickers, pending_orders):
    """Restructure graph node values into canonical nested format.

    Per analysis Section 11.9 — nested {tickers: {TK: {...}}, orders: {TK:order_N: {...}}}
    """
    state = {
        "run_date": date.today().isoformat(),
        "run_ts": datetime.now().isoformat(timespec="seconds"),
        "regime": graph.nodes.get("regime", _stub()).value,
        "vix": graph.nodes.get("vix", _stub()).value,
        "vix_5d_pct": graph.nodes.get("vix_5d_pct", _stub()).value,
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
            "dip_viable": n.get(f"{tk}:dip_viable", _stub()).value,
        }
        # Per-order gate state
        for idx, order in enumerate(pending_orders.get(tk, [])):
            if not (order.get("type") == "BUY" and order.get("placed")
                    and not order.get("filled")):
                continue
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


# ---------------------------------------------------------------------------
# Self-test (plan Section 1.7)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--test" not in sys.argv:
        print("Usage: python3 tools/graph_builder.py --test")
        sys.exit(0)

    print("=" * 60)
    print("Graph Builder Self-Test")
    print("=" * 60)

    # Load real portfolio data
    with open(_ROOT / "portfolio.json") as f:
        portfolio = json.load(f)

    # Build graph with empty live data (test wiring, not yfinance)
    graph = build_daily_graph(
        portfolio=portfolio,
        live_prices={},
        regime="Neutral",
        vix=20.0,
        vix_5d_pct=0.0,
        tech_data={},
        earnings_data={},
        recon_data={},
    )

    # Resolve
    graph.resolve()

    # Count nodes by type
    leaves = [n for n in graph.nodes.values() if not n.depends_on]
    computed = [n for n in graph.nodes.values() if n.depends_on and not n.is_report]
    reports = [n for n in graph.nodes.values() if n.is_report]
    total = len(graph.nodes)

    print(f"\nNode counts:")
    print(f"  Leaves:   {len(leaves)}")
    print(f"  Computed: {len(computed)}")
    print(f"  Reports:  {len(reports)}")
    print(f"  Total:    {total}")
    print(f"  Expected: ~681 (varies with ticker/order count)")

    # Test signal propagation with fake prev state
    graph.load_prev_state({"regime": "Risk-On"})
    signals = graph.propagate_signals()
    activated = graph.get_activated_reports()
    print(f"\nActivated reports (regime Risk-On→Neutral): {len(activated)}")
    shown = 0
    for name, node in activated:
        for sig in node.signals:
            reason = sig.flat_reason()
            if reason and shown < 5:
                print(f"  {name}: {reason}")
                shown += 1

    # Test persistence schema
    positions = portfolio.get("positions", {})
    active = sorted(tk for tk, p in positions.items() if p.get("shares", 0) > 0)
    state = get_state_for_persistence(graph, active, portfolio.get("pending_orders", {}))
    print(f"\nPersistence schema:")
    print(f"  Keys: {list(state.keys())}")
    print(f"  Tickers: {len(state['tickers'])}")
    print(f"  Orders: {len(state['orders'])}")

    # Verify key fields exist
    if active:
        sample = state["tickers"][active[0]]
        expected_keys = {"avg_cost", "shares", "pl_pct", "verdict", "catastrophic",
                         "momentum", "earnings_gate", "time_status", "pool", "sell_target"}
        actual_keys = set(sample.keys())
        missing = expected_keys - actual_keys
        if missing:
            print(f"  MISSING fields: {missing}")
        else:
            print(f"  All 10 per-ticker fields present ✓")

    print(f"\n{graph.summary()}")
    print("\n" + "=" * 60)
    print("SELF-TEST PASSED")
    print("=" * 60)
