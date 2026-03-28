"""Reactive Dependency Graph Engine.

Core infrastructure for the trading system's dependency graph.
Nodes represent observable values, edges represent dependencies.
When a leaf node changes, signals propagate upward through dependents,
accumulating reason chains. Report nodes surface as actionable items.

Usage:
    from graph_engine import DependencyGraph, Node, Signal

    graph = DependencyGraph()
    graph.add_node("portfolio", compute=load_portfolio)
    graph.add_node("avg_cost", compute=calc_avg, depends_on=["portfolio"])
    graph.add_node("sell_price", compute=calc_sell, depends_on=["avg_cost"])

    graph.resolve()  # bottom-up computation
    graph.diff(prev_state)  # compare against previous run
    actions = graph.get_activated_reports()  # only changed report nodes
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


@dataclass
class Signal:
    """A change notification that propagates up through the graph.

    Signals accumulate reason text as they traverse edges.
    A report node's final reason is the concatenation of all
    signal reasons from leaf to report.
    """
    source_node: str
    old_value: Any
    new_value: Any
    reason: str
    child_signals: list[Signal] = field(default_factory=list)

    def chain_str(self, depth: int = 0) -> str:
        """Human-readable signal chain for debugging."""
        indent = "  " * depth
        parts = [f"{indent}{self.source_node}: {self.reason}"]
        for child in self.child_signals:
            parts.append(child.chain_str(depth + 1))
        return "\n".join(parts)

    def flat_reason(self, separator: str = " → ") -> str:
        """Flatten the signal chain into a single reason string.

        Walks from deepest child (leaf) to self (report node),
        producing: "leaf reason → intermediate reason → report reason"
        """
        parts = []
        self._collect_reasons(parts)
        return separator.join(parts)

    def _collect_reasons(self, parts: list[str]) -> None:
        for child in self.child_signals:
            child._collect_reasons(parts)
        if self.reason:
            parts.append(self.reason)


class Node:
    """A single node in the dependency graph.

    Attributes:
        name: Unique identifier (e.g., "regime", "CLSK:avg_cost")
        compute: Function that takes {dep_name: value} and returns this node's value
        depends_on: List of node names this node reads from
        is_report: If True, this node surfaces in the action dashboard when activated
        value: Current computed value (set after resolve())
        prev_value: Value from previous run (loaded from graph_state.json)
        signals: List of Signals that activated this node (non-empty = "hot")
        reason_fn: Optional function(old_value, new_value, input_signals) -> str
                   that produces a human-readable reason for why this node changed.
                   If None, a default reason is generated.
    """

    def __init__(
        self,
        name: str,
        compute: Callable[[dict[str, Any]], Any] | None = None,
        depends_on: list[str] | None = None,
        is_report: bool = False,
        reason_fn: Callable[[Any, Any, list[Signal]], str] | None = None,
    ):
        self.name = name
        self.compute = compute
        self.depends_on = depends_on or []
        self.is_report = is_report
        self.reason_fn = reason_fn

        self.value: Any = None
        self.prev_value: Any = None
        self.signals: list[Signal] = []
        self._resolved = False

    def resolve(self, inputs: dict[str, Any]) -> Any:
        """Compute this node's value from its dependencies."""
        if self.compute is not None:
            self.value = self.compute(inputs)
        self._resolved = True
        return self.value

    def has_changed(self) -> bool:
        """Check if value differs from previous run."""
        if self.prev_value is None and self.value is None:
            return False
        if self.prev_value is None or self.value is None:
            return True
        return self.prev_value != self.value

    def make_signal(self, child_signals: list[Signal] | None = None) -> Signal | None:
        """Create a Signal if this node changed. Returns None if unchanged.

        Uses reason_fn if provided, otherwise generates a default reason.
        """
        if not self.has_changed():
            return None

        children = child_signals or []

        if self.reason_fn:
            reason = self.reason_fn(self.prev_value, self.value, children)
        else:
            reason = f"{self.name}: {_format_value(self.prev_value)} → {_format_value(self.value)}"

        return Signal(
            source_node=self.name,
            old_value=self.prev_value,
            new_value=self.value,
            reason=reason,
            child_signals=children,
        )

    def __repr__(self) -> str:
        status = "resolved" if self._resolved else "pending"
        report = " [REPORT]" if self.is_report else ""
        return f"Node({self.name}, {status}{report})"


class DependencyGraph:
    """Directed acyclic graph of computation nodes.

    Resolves bottom-up (leaves first, then dependents).
    After resolution, compares against previous state to find changes.
    Changed nodes propagate signals upward to report nodes.
    """

    def __init__(self):
        self.nodes: dict[str, Node] = {}
        self._resolve_order: list[str] | None = None

    def add_node(
        self,
        name: str,
        compute: Callable[[dict[str, Any]], Any] | None = None,
        depends_on: list[str] | None = None,
        is_report: bool = False,
        reason_fn: Callable[[Any, Any, list[Signal]], str] | None = None,
    ) -> Node:
        """Add a node to the graph. Returns the node for chaining."""
        node = Node(name, compute, depends_on, is_report, reason_fn)
        self.nodes[name] = node
        self._resolve_order = None  # invalidate cached order
        return node

    def _topological_sort(self) -> list[str]:
        """Compute resolution order: leaves first, dependents after dependencies."""
        visited: set[str] = set()
        order: list[str] = []
        visiting: set[str] = set()  # cycle detection

        def visit(name: str) -> None:
            if name in visited:
                return
            if name in visiting:
                raise ValueError(f"Circular dependency detected involving '{name}'")
            visiting.add(name)
            node = self.nodes.get(name)
            if node is None:
                raise ValueError(f"Node '{name}' referenced but not defined")
            for dep in node.depends_on:
                visit(dep)
            visiting.discard(name)
            visited.add(name)
            order.append(name)

        for name in self.nodes:
            visit(name)

        return order

    def resolve(self) -> dict[str, Any]:
        """Resolve all nodes bottom-up. Returns {name: value} for all nodes."""
        if self._resolve_order is None:
            self._resolve_order = self._topological_sort()

        for name in self._resolve_order:
            node = self.nodes[name]
            inputs = {dep: self.nodes[dep].value for dep in node.depends_on}
            node.resolve(inputs)

        return {name: node.value for name, node in self.nodes.items()}

    def load_prev_state(self, state: dict[str, Any]) -> None:
        """Load previous run's state into nodes for diffing."""
        for name, value in state.items():
            if name in self.nodes:
                self.nodes[name].prev_value = value

    def propagate_signals(self) -> list[Signal]:
        """After resolve(), propagate change signals bottom-up.

        Leaf nodes that changed create signals. These propagate
        to dependent nodes, accumulating reason chains. Returns
        all signals that reached report nodes.
        """
        if self._resolve_order is None:
            self._resolve_order = self._topological_sort()

        # Phase 1: Create signals for changed leaf nodes
        for name in self._resolve_order:
            node = self.nodes[name]
            if not node.depends_on:
                # Leaf node — create signal if changed
                sig = node.make_signal()
                if sig:
                    node.signals = [sig]

        # Phase 2: Propagate signals upward through the graph
        for name in self._resolve_order:
            node = self.nodes[name]
            if not node.depends_on:
                continue  # already handled leaves

            # Collect signals from dependencies
            child_signals = []
            for dep_name in node.depends_on:
                dep_node = self.nodes[dep_name]
                child_signals.extend(dep_node.signals)

            # This node is "activated" if any dependency has signals OR if this node changed
            if child_signals or node.has_changed():
                sig = node.make_signal(child_signals)
                if sig:
                    node.signals = [sig]
                elif child_signals:
                    # Node didn't change itself but passes through child signals
                    node.signals = child_signals

        # Phase 3: Collect signals from report nodes
        report_signals = []
        for name in self._resolve_order:
            node = self.nodes[name]
            if node.is_report and node.signals:
                report_signals.extend(node.signals)

        return report_signals

    def get_activated_reports(self) -> list[tuple[str, Node]]:
        """Return report nodes that have signals (i.e., something changed)."""
        return [(name, node) for name, node in self.nodes.items()
                if node.is_report and node.signals]

    def get_state(self) -> dict[str, Any]:
        """Export current node values for persistence."""
        return {name: node.value for name, node in self.nodes.items()
                if node.value is not None}

    def summary(self) -> str:
        """Human-readable graph summary for debugging."""
        lines = [f"DependencyGraph: {len(self.nodes)} nodes"]
        leaves = [n for n in self.nodes.values() if not n.depends_on]
        computed = [n for n in self.nodes.values() if n.depends_on and not n.is_report]
        reports = [n for n in self.nodes.values() if n.is_report]
        lines.append(f"  Leaves: {len(leaves)}")
        lines.append(f"  Computed: {len(computed)}")
        lines.append(f"  Reports: {len(reports)}")

        activated = self.get_activated_reports()
        if activated:
            lines.append(f"  Activated: {len(activated)}")
            for name, node in activated:
                for sig in node.signals:
                    lines.append(f"    {name}: {sig.flat_reason()}")

        return "\n".join(lines)


def _format_value(v: Any) -> str:
    """Format a value for display in reason strings."""
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.2f}"
    if isinstance(v, dict):
        return json.dumps(v, default=str)[:80]
    return str(v)
