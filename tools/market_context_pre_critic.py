#!/usr/bin/env python3
"""Market Context Pre-Critic — Phase 3 mechanical verification for market-context workflow.

Reads market-context-raw.md, market-context-report.md, and portfolio.json.
Runs 5 verification checks and writes market-context-pre-critic.md for the
LLM critic to add qualitative assessment.

Usage: python3 tools/market_context_pre_critic.py
"""

import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = PROJECT_ROOT / "market-context-raw.md"
REPORT_PATH = PROJECT_ROOT / "market-context-report.md"
PORTFOLIO_PATH = PROJECT_ROOT / "portfolio.json"
OUTPUT_PATH = PROJECT_ROOT / "market-context-pre-critic.md"

# Same-directory imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
from news_sweep_collector import split_table_row
from market_context_gatherer import SECTOR_MAP
from market_context_pre_analyst import (
    parse_indices, parse_vix, parse_sectors, parse_tool_regime,
    parse_pending_buy_orders, parse_active_positions,
    classify_regime, apply_entry_gate, compute_gate_summary,
    VIX_RISK_ON_THRESHOLD, VIX_RISK_OFF_THRESHOLD,
    VIX_CAUTION_LOW, VIX_CAUTION_HIGH, DEEP_SUPPORT_PCT,
)


# ---------------------------------------------------------------------------
# Input Validation
# ---------------------------------------------------------------------------

def validate_inputs():
    """Load all 3 input files + raw text. Returns (raw_text, report_text, portfolio)."""
    if not RAW_PATH.exists():
        print(f"*Error: {RAW_PATH.name} not found*", file=sys.stderr)
        sys.exit(1)
    raw_text = RAW_PATH.read_text(encoding="utf-8")

    if not REPORT_PATH.exists():
        print(f"*Error: {REPORT_PATH.name} not found — analyst phase must complete first*",
              file=sys.stderr)
        sys.exit(1)
    report_text = REPORT_PATH.read_text(encoding="utf-8")

    if not PORTFOLIO_PATH.exists():
        print(f"*Error: {PORTFOLIO_PATH.name} not found*", file=sys.stderr)
        sys.exit(1)
    try:
        portfolio = json.loads(PORTFOLIO_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"*Error: {PORTFOLIO_PATH.name} malformed JSON: {e}*", file=sys.stderr)
        sys.exit(1)

    return raw_text, report_text, portfolio


def extract_report_date(text):
    """Parse date from report header."""
    m = re.search(r"# Market Context (?:Report|Raw Data|Pre-Analyst|Pre-Critic) — (\d{4}-\d{2}-\d{2})", text)
    if m:
        return date.fromisoformat(m.group(1))
    return date.today()


# ---------------------------------------------------------------------------
# Report Parsing (analyst output — market-context-report.md)
# ---------------------------------------------------------------------------

def parse_report_regime(report_text):
    """Parse Market Regime table from report.

    Returns dict with regime, vix_value, vix_5d_pct, indices_above, indices_total,
    sector_breadth, reasoning.
    """
    result = {
        "regime": None, "vix_value": None, "vix_5d_pct": None,
        "indices_above": None, "indices_total": None,
        "sector_breadth": None, "reasoning": None,
    }

    lines = report_text.split("\n")
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Market Regime"):
            in_section = True
            continue
        if in_section and stripped.startswith("## ") and "Market Regime" not in stripped:
            break
        if not in_section or not stripped.startswith("|"):
            continue
        cols = split_table_row(stripped)
        if not cols or len(cols) < 2:
            continue
        if any(c.startswith(":---") or c.startswith("---") for c in cols):
            continue

        metric = cols[0].strip()
        value = cols[1].strip()

        if metric == "Regime":
            result["regime"] = value.replace("**", "").strip()
        elif metric == "VIX":
            # Parse "19.09 (Normal — Stable, -8.31% 5D)" or "19.09 (Normal — Stable)"
            val_match = re.match(r'^([\d.]+)', value)
            if val_match:
                result["vix_value"] = float(val_match.group(1))
            five_d_match = re.search(r'([-+]?\d+\.?\d*)%\s*5D', value)
            if five_d_match:
                result["vix_5d_pct"] = float(five_d_match.group(1))
        elif metric == "VIX 5D%":
            five_d_match = re.match(r'^([-+]?\d+\.?\d*)%', value)
            if five_d_match:
                result["vix_5d_pct"] = float(five_d_match.group(1))
        elif "Indices Above" in metric:
            m = re.search(r'(\d+)/(\d+)', value)
            if m:
                result["indices_above"] = int(m.group(1))
                result["indices_total"] = int(m.group(2))
        elif "Sector Breadth" in metric:
            m = re.search(r'(\d+)/(\d+)', value)
            if m:
                result["sector_breadth"] = (int(m.group(1)), int(m.group(2)))
        elif metric == "Reasoning":
            result["reasoning"] = value

    return result


def _get_col(header_map, cols, name, default=""):
    """Extract a column value by header name from a parsed table row."""
    idx = header_map.get(name)
    if idx is not None and idx < len(cols):
        return cols[idx].strip()
    return default


def parse_report_gate_decisions(report_text):
    """Parse Entry Gate Decisions table from report.

    Identifies columns by header name (handles both 6-col v1 and 8-col v2).
    Returns list of dicts.
    """
    lines = report_text.split("\n")
    in_section = False
    header_map = {}
    orders = []

    for line in lines:
        stripped = line.strip()
        if "## Entry Gate Decisions" in stripped:
            in_section = True
            continue
        if in_section and stripped.startswith("## ") and "Entry Gate" not in stripped:
            break
        if not in_section or not stripped.startswith("|"):
            continue

        cols = split_table_row(stripped)
        if not cols:
            continue

        # Skip separator rows
        if any(c.startswith(":---") or c.startswith("---") for c in cols):
            continue

        # Detect header row
        if cols[0].strip() == "Ticker" and not header_map:
            for i, c in enumerate(cols):
                header_map[c.strip()] = i
            continue

        if not header_map:
            continue

        ticker = _get_col(header_map, cols, "Ticker")
        if not ticker:
            continue

        # Parse price
        price_str = _get_col(header_map, cols, "Order Price").replace("$", "").replace(",", "")
        try:
            order_price = float(price_str)
        except ValueError:
            order_price = None

        # Parse shares
        try:
            shares = int(_get_col(header_map, cols, "Shares", "0"))
        except ValueError:
            shares = 0

        # Parse current price (may not exist in v1 format)
        current_str = _get_col(header_map, cols, "Current Price", "").replace("$", "").replace(",", "")
        try:
            current_price = float(current_str) if current_str else None
        except ValueError:
            current_price = None

        # Parse % Below Current
        pct_str = _get_col(header_map, cols, "% Below Current", "").replace("%", "")
        try:
            pct_below = float(pct_str) if pct_str else None
        except ValueError:
            pct_below = None

        # Gate Status — strip bold markers
        gate = _get_col(header_map, cols, "Gate Status").replace("**", "").strip()

        orders.append({
            "ticker": ticker,
            "order_price": order_price,
            "shares": shares,
            "current_price": current_price,
            "pct_below": pct_below,
            "gate_status": gate,
            "reasoning": _get_col(header_map, cols, "Reasoning"),
            "notes": _get_col(header_map, cols, "Notes"),
        })

    return orders


def parse_report_index_detail(report_text):
    """Parse Index Detail table from report. Returns list of dicts."""
    lines = report_text.split("\n")
    in_section = False
    header_map = {}
    indices = []

    for line in lines:
        stripped = line.strip()
        if "## Index Detail" in stripped:
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if not in_section or not stripped.startswith("|"):
            continue
        cols = split_table_row(stripped)
        if not cols:
            continue
        if any(c.startswith(":---") or c.startswith("---") for c in cols):
            continue

        # Detect header row
        if cols[0].strip() == "Index" and not header_map:
            for i, c in enumerate(cols):
                header_map[c.strip()] = i
            continue

        if not header_map:
            continue

        indices.append({
            "name": _get_col(header_map, cols, "Index"),
            "vs_50sma": _get_col(header_map, cols, "vs 50-SMA"),
        })

    return indices


def parse_report_executive_summary(report_text):
    """Parse gate counts from Executive Summary.

    Looks for patterns like "N ACTIVE, N CAUTION, N REVIEW, N PAUSE".
    Returns dict {active, caution, review, pause} or None.
    """
    lines = report_text.split("\n")
    in_section = False

    for line in lines:
        stripped = line.strip()
        if "## Executive Summary" in stripped:
            in_section = True
            continue
        if in_section and stripped.startswith("## ") and "Executive" not in stripped:
            break
        if not in_section:
            continue

        # Look for gate count pattern
        m = re.search(r'(\d+)\s*ACTIVE.*?(\d+)\s*CAUTION.*?(\d+)\s*REVIEW.*?(\d+)\s*PAUSE',
                       stripped)
        if m:
            return {
                "active": int(m.group(1)),
                "caution": int(m.group(2)),
                "review": int(m.group(3)),
                "pause": int(m.group(4)),
            }

    return None


# ---------------------------------------------------------------------------
# Check 1: Regime Classification
# ---------------------------------------------------------------------------

def check_regime_classification(raw_text, report_regime):
    """Verify regime classification against raw data.

    Returns {status, issues, notes}.
    """
    issues = []
    notes = []

    # Re-parse raw data
    indices = parse_indices(raw_text)
    vix = parse_vix(raw_text)

    # Recompute regime
    computed = classify_regime(indices, vix)

    # Compare regime
    report_label = report_regime.get("regime", "Unknown")
    computed_label = computed["regime"]
    if report_label != computed_label:
        issues.append(f"Regime mismatch: report says '{report_label}', "
                      f"computed '{computed_label}' "
                      f"({computed['reasoning']}) (Critical)")
    else:
        notes.append(f"Regime '{report_label}' matches computed")

    # VIX value
    raw_vix = vix.get("value")
    report_vix = report_regime.get("vix_value")
    if raw_vix is not None and report_vix is not None:
        if abs(raw_vix - report_vix) > 0.05:
            issues.append(f"VIX mismatch: raw={raw_vix:.2f}, report={report_vix:.2f} (Critical)")
        else:
            notes.append(f"VIX matches: {raw_vix:.2f}")
    elif raw_vix is None:
        notes.append("VIX data unavailable in raw")

    # VIX 5D%
    raw_5d = vix.get("five_d_pct")
    report_5d = report_regime.get("vix_5d_pct")
    if raw_5d is not None and report_5d is not None:
        if abs(raw_5d - report_5d) > 0.1:
            issues.append(f"VIX 5D% mismatch: raw={raw_5d:+.2f}%, "
                          f"report={report_5d:+.2f}% (Minor)")

    # Indices count
    report_above = report_regime.get("indices_above")
    report_total = report_regime.get("indices_total")
    if report_above is not None and report_total is not None:
        if report_above != computed["indices_above"]:
            issues.append(f"Indices above count: report={report_above}, "
                          f"computed={computed['indices_above']} (Critical)")
        if report_total != computed["indices_total"]:
            issues.append(f"Indices total count: report={report_total}, "
                          f"computed={computed['indices_total']} (Minor)")
    else:
        notes.append("Could not parse indices count from report")

    # Edge case: VIX exactly 20.0 or 25.0 should be Neutral
    if raw_vix is not None and (raw_vix == 20.0 or raw_vix == 25.0):
        if report_label != "Neutral":
            issues.append(f"Edge case: VIX exactly {raw_vix:.1f} should produce Neutral, "
                          f"report says '{report_label}' (Critical)")
        else:
            notes.append(f"Edge case correctly handled: VIX {raw_vix:.1f} → Neutral")

    status = "FAIL" if any("(Critical)" in i for i in issues) else "PASS"
    return {"status": status, "issues": issues, "notes": notes}


# ---------------------------------------------------------------------------
# Check 2: Entry Gate Logic
# ---------------------------------------------------------------------------

def check_entry_gate_logic(raw_text, report_orders, portfolio):
    """Re-apply entry gate and compare per-order.

    Returns {status, issues, notes}.
    """
    issues = []
    notes = []

    # Re-parse raw data and classify regime
    indices = parse_indices(raw_text)
    vix = parse_vix(raw_text)
    raw_orders = parse_pending_buy_orders(raw_text)
    regime_data = classify_regime(indices, vix)
    regime = regime_data["regime"]

    # Re-apply gate logic
    expected_orders = apply_entry_gate(regime, raw_orders, portfolio, vix)

    # Build lookup for report orders: (ticker, price) → gate_status
    report_lookup = {}
    for o in report_orders:
        key = (o["ticker"], o.get("order_price"))
        report_lookup[key] = o

    # Compare each expected order
    matched = 0
    for exp in expected_orders:
        key = (exp["ticker"], exp.get("order_price"))
        rep = report_lookup.get(key)

        if rep is None:
            issues.append(f"{exp['ticker']} ${exp['order_price']:.2f}: "
                          f"missing from report Entry Gate table (Critical)")
            continue

        exp_gate = exp["gate_status"].upper()
        rep_gate = rep["gate_status"].upper()

        if exp_gate != rep_gate:
            issues.append(
                f"{exp['ticker']} ${exp['order_price']:.2f}: "
                f"report='{rep_gate}', expected='{exp_gate}' — "
                f"{exp['reasoning']} (Critical)"
            )
        else:
            matched += 1

        # Verify % Below Current math (tolerance 0.2%)
        if exp["pct_below"] is not None and rep.get("pct_below") is not None:
            diff = abs(exp["pct_below"] - rep["pct_below"])
            if diff > 0.2:
                issues.append(
                    f"{exp['ticker']} ${exp['order_price']:.2f}: "
                    f"% Below Current mismatch: raw={exp['pct_below']:.1f}%, "
                    f"report={rep['pct_below']:.1f}% (diff {diff:.1f}%) (Critical)"
                )

    notes.append(f"{matched}/{len(expected_orders)} orders gate status matches")
    notes.append(f"Regime: {regime} (strategy compliance verified in Check 5)")

    status = "FAIL" if any("(Critical)" in i for i in issues) else "PASS"
    return {"status": status, "issues": issues, "notes": notes}


# ---------------------------------------------------------------------------
# Check 3: Data Consistency
# ---------------------------------------------------------------------------

def check_data_consistency(raw_text, report_orders, portfolio):
    """Cross-reference order data against raw + portfolio.json.

    Returns {status, issues, notes}.
    """
    issues = []
    notes = []

    # Build expected orders from portfolio.json
    pending = portfolio.get("pending_orders", {})
    pj_orders = {}  # (ticker, price) → {shares, note}
    for ticker, ticker_orders in pending.items():
        if not ticker_orders:
            continue
        for order in ticker_orders:
            if order.get("type") != "BUY":
                continue
            key = (ticker, order["price"])
            pj_orders[key] = {"shares": order["shares"], "note": order.get("note", "")}

    # Parse raw orders for current prices
    raw_orders = parse_pending_buy_orders(raw_text)
    raw_lookup = {}
    for o in raw_orders:
        key = (o["ticker"], o["order_price"])
        raw_lookup[key] = o

    # Check each report order
    phantom_count = 0
    for o in report_orders:
        key = (o["ticker"], o.get("order_price"))

        # Check against portfolio.json
        pj = pj_orders.get(key)
        if pj is None:
            issues.append(f"Phantom order: {o['ticker']} ${o.get('order_price', 'N/A')} "
                          f"not in portfolio.json (Critical)")
            phantom_count += 1
            continue

        # Check shares match
        if o["shares"] != pj["shares"]:
            issues.append(f"{o['ticker']} ${o['order_price']:.2f}: "
                          f"shares mismatch: report={o['shares']}, "
                          f"pj={pj['shares']} (Critical)")

        # Check current price matches raw
        raw_order = raw_lookup.get(key)
        if raw_order and o.get("current_price") is not None:
            if raw_order["current_price"] is not None:
                diff = abs(o["current_price"] - raw_order["current_price"])
                if diff > 0.02:
                    issues.append(
                        f"{o['ticker']} ${o['order_price']:.2f}: current price mismatch: "
                        f"report=${o['current_price']:.2f}, "
                        f"raw=${raw_order['current_price']:.2f} (Critical)"
                    )

    # Check for missing orders (in PJ but not in report)
    report_keys = {(o["ticker"], o.get("order_price")) for o in report_orders}
    for key in pj_orders:
        if key not in report_keys:
            issues.append(f"Missing order: {key[0]} ${key[1]:.2f} in portfolio.json "
                          f"but not in report (Critical)")

    # Summary notes
    if phantom_count == 0:
        notes.append("No phantom orders")
    if not any("Missing order" in i for i in issues):
        notes.append("No missing orders")

    notes.append(f"Checked {len(report_orders)} report orders against "
                 f"{len(pj_orders)} portfolio.json BUY orders")

    status = "FAIL" if any("(Critical)" in i for i in issues) else "PASS"
    return {"status": status, "issues": issues, "notes": notes}


# ---------------------------------------------------------------------------
# Check 4: Coverage & Completeness
# ---------------------------------------------------------------------------

def check_coverage(raw_text, report_text, report_orders, report_regime, portfolio):
    """Verify coverage of all orders, sections, and counts.

    Returns {status, issues, notes}.
    """
    issues = []
    notes = []

    # Count expected BUY orders from portfolio.json
    pending = portfolio.get("pending_orders", {})
    expected_count = 0
    expected_tickers = set()
    for ticker, ticker_orders in pending.items():
        if not ticker_orders:
            continue
        buy_count = sum(1 for o in ticker_orders if o.get("type") == "BUY")
        if buy_count > 0:
            expected_count += buy_count
            expected_tickers.add(ticker)

    # Check total orders in report
    report_count = len(report_orders)
    if report_count != expected_count:
        issues.append(f"Order count mismatch: report has {report_count} rows, "
                      f"portfolio.json has {expected_count} BUY orders (Critical)")
    else:
        notes.append(f"All {expected_count} BUY orders present in report")

    # Check Executive Summary gate counts
    exec_counts = parse_report_executive_summary(report_text)
    if exec_counts:
        exec_total = sum(exec_counts.values())
        if exec_total != report_count:
            issues.append(
                f"Executive Summary total ({exec_total}) doesn't match "
                f"Entry Gate table rows ({report_count}) (Critical)"
            )
        else:
            notes.append("Executive Summary counts match table rows")

        # Also verify per-status counts
        actual_counts = {"ACTIVE": 0, "CAUTION": 0, "REVIEW": 0, "PAUSE": 0}
        for o in report_orders:
            gate = o["gate_status"].upper()
            if gate in actual_counts:
                actual_counts[gate] += 1
        for status_name in ["active", "caution", "review", "pause"]:
            upper_name = status_name.upper()
            exec_val = exec_counts.get(status_name, 0)
            actual_val = actual_counts.get(upper_name, 0)
            if exec_val != actual_val:
                issues.append(
                    f"Executive Summary {upper_name} count "
                    f"({exec_val}) doesn't match "
                    f"table ({actual_val}) (Critical)"
                )
    else:
        notes.append("Could not parse Executive Summary gate counts")

    # Check Market Regime table completeness
    required_regime_fields = ["regime", "vix_value"]
    for field in required_regime_fields:
        if report_regime.get(field) is None:
            issues.append(f"Market Regime table missing '{field}' (Critical)")

    # Check Index Detail — should have 3 indices
    report_indices = parse_report_index_detail(report_text)
    if len(report_indices) < 3:
        issues.append(f"Index Detail has {len(report_indices)} indices, expected 3 (Critical)")
    else:
        notes.append("All 3 indices present in Index Detail")

    # Check Recommendations section exists
    if "## Recommendations" not in report_text:
        issues.append("Recommendations section missing (Critical)")
    else:
        notes.append("Recommendations section present")

    # Check Sector Alignment exists
    if "## Sector Alignment" not in report_text:
        issues.append("Sector Alignment section missing (Minor)")

    status = "FAIL" if any("(Critical)" in i for i in issues) else "PASS"
    return {"status": status, "issues": issues, "notes": notes}


# ---------------------------------------------------------------------------
# Check 5: Strategy Compliance
# ---------------------------------------------------------------------------

def check_strategy_compliance(raw_text, report_text, report_orders, portfolio):
    """Verify gate decisions comply with strategy rules.

    Returns {status, issues, notes}.
    """
    issues = []
    notes = []

    # Recompute regime
    indices = parse_indices(raw_text)
    vix = parse_vix(raw_text)
    regime_data = classify_regime(indices, vix)
    regime = regime_data["regime"]

    positions = portfolio.get("positions", {})

    if regime == "Risk-On":
        # All must be ACTIVE
        non_active = [o for o in report_orders if o["gate_status"].upper() != "ACTIVE"]
        if non_active:
            for o in non_active:
                issues.append(
                    f"Strategy violation: Risk-On requires all ACTIVE, but "
                    f"{o['ticker']} ${o.get('order_price', 'N/A')} is "
                    f"'{o['gate_status']}' (Critical)"
                )
        else:
            notes.append("Risk-On: all orders ACTIVE — compliant")

    elif regime == "Neutral":
        for o in report_orders:
            gate = o["gate_status"].upper()
            if gate not in ("ACTIVE", "CAUTION"):
                issues.append(
                    f"Strategy violation: Neutral allows only ACTIVE/CAUTION, "
                    f"but {o['ticker']} is '{gate}' (Critical)"
                )
        notes.append("Neutral regime strategy check complete")

    elif regime == "Risk-Off":
        for o in report_orders:
            gate = o["gate_status"].upper()
            ticker = o["ticker"]
            pct_below = o.get("pct_below")

            # CAUTION is NOT valid in Risk-Off
            if gate == "CAUTION":
                issues.append(
                    f"Strategy violation: CAUTION not valid in Risk-Off, "
                    f"{ticker} ${o.get('order_price', 'N/A')} (Critical)"
                )
                continue

            # Check shares=0 → PAUSE
            pos = positions.get(ticker, {})
            shares = pos.get("shares", 0)
            if not isinstance(shares, (int, float)) or shares == 0:
                if gate != "PAUSE":
                    issues.append(
                        f"Strategy violation: Risk-Off watchlist ticker {ticker} "
                        f"should be PAUSE, is '{gate}' (Critical)"
                    )
            else:
                # Active position: >15% = ACTIVE, <=15% = REVIEW
                if pct_below is not None and pct_below > DEEP_SUPPORT_PCT:
                    if gate != "ACTIVE":
                        issues.append(
                            f"Strategy: {ticker} ${o.get('order_price', 'N/A')} is "
                            f"{pct_below:.1f}% below (deep support) — expected ACTIVE, "
                            f"got '{gate}' (Critical)"
                        )
                elif pct_below is not None and pct_below <= DEEP_SUPPORT_PCT:
                    if gate != "REVIEW":
                        issues.append(
                            f"Strategy: {ticker} ${o.get('order_price', 'N/A')} is "
                            f"{pct_below:.1f}% below (near price) — expected REVIEW, "
                            f"got '{gate}' (Critical)"
                        )

    # Check for "cancel" language (Critical violation)
    # Only flag if "cancel" is used as a recommendation, not in prohibitive context
    cancel_pattern = re.compile(r'\b(cancel|canceling|cancelling)\b', re.IGNORECASE)
    for line in report_text.split("\n"):
        if cancel_pattern.search(line):
            stripped = line.strip()
            # Skip prohibitive usage: "no orders should be paused, cancelled"
            if any(neg in stripped.lower() for neg in
                   ["should not", "no orders should", "do not cancel",
                    "not cancel", "don't cancel", "not be cancel"]):
                notes.append(f"Cancel language in prohibitive context: acceptable")
            else:
                issues.append(
                    f"Strategy violation: 'cancel' language used in recommendation "
                    f"context — strategy says PAUSE, not cancel (Critical)"
                )

    # Earnings gate interaction
    if "earnings gate" not in report_text.lower() and "both gates" not in report_text.lower():
        notes.append("Earnings gate interaction not explicitly mentioned (Minor)")

    status = "FAIL" if any("(Critical)" in i for i in issues) else "PASS"
    return {"status": status, "issues": issues, "notes": notes}


# ---------------------------------------------------------------------------
# Report Assembly
# ---------------------------------------------------------------------------

def build_verification_report(report_date, checks):
    """Assemble market-context-pre-critic.md."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Overall verdict
    all_pass = all(c["result"]["status"] == "PASS" for c in checks)
    verdict = "PASS" if all_pass else "ISSUES"

    critical_count = sum(
        sum(1 for i in c["result"]["issues"] if "(Critical)" in i)
        for c in checks
    )
    minor_count = sum(
        sum(1 for i in c["result"]["issues"] if "(Minor)" in i)
        for c in checks
    ) + sum(
        sum(1 for n in c["result"]["notes"] if "(Minor)" in n)
        for c in checks
    )

    parts = []

    # Header
    parts.append(f"# Market Context Pre-Critic — {report_date.isoformat()}")
    parts.append(f"*Generated: {now_str} | Tool: market_context_pre_critic.py*")
    parts.append("")

    # Verdict
    parts.append(f"## Verdict: {verdict}")
    parts.append("")

    # Verification Summary table
    parts.append("## Verification Summary")
    parts.append("")
    parts.append("| Check | Result | Details |")
    parts.append("| :--- | :--- | :--- |")

    for c in checks:
        result = c["result"]
        status = result["status"]
        crit = sum(1 for i in result["issues"] if "(Critical)" in i)
        minor = sum(1 for i in result["issues"] if "(Minor)" in i)
        detail_parts = []
        if crit:
            detail_parts.append(f"{crit} critical")
        if minor:
            detail_parts.append(f"{minor} minor")
        if result["notes"]:
            if not detail_parts:
                detail_parts.append(result["notes"][0])
            else:
                detail_parts.append(f"{len(result['notes'])} notes")
        detail = "; ".join(detail_parts) if detail_parts else "Clean"
        if status == "PASS" and minor:
            status_str = f"PASS ({minor} minor)"
        else:
            status_str = status
        parts.append(f"| {c['name']} | {status_str} | {detail} |")

    parts.append("")
    parts.append(f"**Total: {critical_count} critical, {minor_count} minor issues**")
    parts.append("")

    # Per-check details
    for c in checks:
        result = c["result"]
        parts.append(f"---")
        parts.append("")
        parts.append(f"## {c['name']}")
        parts.append("")

        if not result["issues"]:
            parts.append(f"No {c['name'].lower()} issues found.")
        else:
            for issue in result["issues"]:
                parts.append(f"- {issue}")
        parts.append("")

        if result["notes"]:
            parts.append("**Notes:**")
            for note in result["notes"]:
                parts.append(f"- {note}")
            parts.append("")

    # Qualitative focus areas
    parts.append("---")
    parts.append("")
    parts.append("## For Critic: Qualitative Focus Areas")
    parts.append("")
    parts.append("*The 5 mechanical checks above are complete. The LLM critic should focus on:*")
    parts.append("")
    parts.append("1. **Reasoning quality** — Are the analyst's reasoning sentences data-grounded?")
    parts.append("2. **Recommendation specificity** — Are entry actions specific (named tickers, prices)?")
    parts.append("3. **Sector alignment insight** — Does the sector commentary add value?")
    parts.append("4. **Position management** — Is the advisory appropriate for the regime?")
    parts.append("5. **Edge case awareness** — Any regime boundary conditions worth noting?")
    parts.append("")

    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    t0 = time.monotonic()

    print("Market Context Pre-Critic")
    print("=" * 50)

    # Load inputs
    print("\n[1/3] Loading inputs...")
    raw_text, report_text, portfolio = validate_inputs()
    report_date = extract_report_date(report_text)
    print(f"  Report date: {report_date.isoformat()}")

    # Parse report
    print("\n[2/3] Parsing report...")
    report_regime = parse_report_regime(report_text)
    report_orders = parse_report_gate_decisions(report_text)
    print(f"  Report regime: {report_regime.get('regime', 'Unknown')}")
    print(f"  Report orders: {len(report_orders)}")

    # Run checks
    print("\n[3/3] Running 5 verification checks...")

    checks = [
        {
            "name": "Regime Classification",
            "result": check_regime_classification(raw_text, report_regime),
        },
        {
            "name": "Entry Gate Logic",
            "result": check_entry_gate_logic(raw_text, report_orders, portfolio),
        },
        {
            "name": "Data Consistency",
            "result": check_data_consistency(raw_text, report_orders, portfolio),
        },
        {
            "name": "Coverage",
            "result": check_coverage(raw_text, report_text, report_orders,
                                      report_regime, portfolio),
        },
        {
            "name": "Strategy Compliance",
            "result": check_strategy_compliance(raw_text, report_text,
                                                 report_orders, portfolio),
        },
    ]

    for c in checks:
        r = c["result"]
        crit = sum(1 for i in r["issues"] if "(Critical)" in i)
        minor = sum(1 for i in r["issues"] if "(Minor)" in i)
        print(f"  {c['name']}: {r['status']} "
              f"({crit} critical, {minor} minor)")

    # Assemble and write
    content = build_verification_report(report_date, checks)
    OUTPUT_PATH.write_text(content, encoding="utf-8")

    # Summary
    elapsed = time.monotonic() - t0
    size_kb = OUTPUT_PATH.stat().st_size / 1024
    all_pass = all(c["result"]["status"] == "PASS" for c in checks)

    print(f"\n{'=' * 50}")
    print(f"Output: market-context-pre-critic.md ({size_kb:.1f} KB)")
    print(f"Verdict: {'PASS' if all_pass else 'ISSUES'}")
    print(f"Elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
