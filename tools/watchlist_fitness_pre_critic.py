#!/usr/bin/env python3
"""Watchlist fitness pre-critic — mechanical verification (6 checks).

Reads watchlist-fitness.json + watchlist-fitness-report.md + portfolio.json.
Writes watchlist-fitness-pre-critic.md.

Usage:
    python3 tools/watchlist_fitness_pre_critic.py
"""
import json
import re
import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
JSON_PATH = _ROOT / "watchlist-fitness.json"
REPORT_PATH = _ROOT / "watchlist-fitness-report.md"
PORTFOLIO_PATH = _ROOT / "portfolio.json"
OUTPUT_PATH = _ROOT / "watchlist-fitness-pre-critic.md"


def _load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def _load_text(path):
    if not path.exists():
        return ""
    with open(path, "r") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Verdict re-derivation
# ---------------------------------------------------------------------------
def _rederive_base_verdict(t):
    """Re-derive the expected verdict from JSON fields."""
    if t.get("recovery"):
        return "RECOVERY"

    swing = t.get("monthly_swing")
    consistency = t.get("swing_consistency")

    if (swing is not None and swing < 10) or (consistency is not None and consistency < 80):
        return "REMOVE"  # position modifier → EXIT-REVIEW
    if (swing is not None and swing < 12) or (consistency is not None and consistency < 85):
        return "REVIEW"  # position modifier → HOLD-WAIT

    oi = t.get("order_info", {})
    # RESTRUCTURE has 3 conditions (any triggers it)
    if oi.get("orphaned", 0) > 0:
        return "RESTRUCTURE"
    if oi.get("all_active_skip", False):
        return "RESTRUCTURE"
    if oi.get("has_non_paused_orders", False) and oi.get("all_above_price", False):
        return "RESTRUCTURE"

    return "ENGAGE"  # position modifier → ADD


def _rederive_cycle_state(cd):
    """Re-derive cycle state from raw cycle_data fields."""
    if cd is None:
        return None
    rsi = cd.get("rsi")
    sma50_dist = cd.get("sma50_dist_pct")
    if rsi is None or sma50_dist is None:
        return "NEUTRAL"
    if rsi > 70 and sma50_dist > 10:
        return "OVERBOUGHT"
    if rsi < 30 and sma50_dist < -10:
        return "OVERSOLD"
    if rsi > 65 and sma50_dist > 5:
        return "EXTENDED"
    if rsi < 40 and sma50_dist < -5:
        return "PULLBACK"
    return "NEUTRAL"


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def check_verdict_consistency(data):
    """Check 1: Re-derive base verdict from JSON fields, flag mismatches."""
    issues = []
    for t in data.get("tickers", []):
        expected_base = _rederive_base_verdict(t)
        actual = t.get("verdict", "")
        # Map position modifiers back to base
        modifier_map = {
            "EXIT-REVIEW": "REMOVE",
            "HOLD-WAIT": ["REVIEW", "RESTRUCTURE"],
            "ADD": "ENGAGE",
        }
        # Check if actual is consistent with expected base
        if actual in modifier_map:
            expected_options = modifier_map[actual]
            if isinstance(expected_options, str):
                expected_options = [expected_options]
            if expected_base not in expected_options:
                issues.append(f"{t['ticker']}: verdict={actual} implies base in {expected_options}, but derived={expected_base}")
        elif actual != expected_base:
            issues.append(f"{t['ticker']}: expected base={expected_base}, got verdict={actual}")

    status = "PASS" if not issues else "FAIL"
    return {"check": "Verdict Consistency", "status": status, "issues": issues}


def check_cycle_state(data):
    """Check 2: Re-derive cycle state from rsi + sma50_dist_pct."""
    issues = []
    for t in data.get("tickers", []):
        cd = t.get("cycle_data")
        if cd is None:
            continue
        expected = _rederive_cycle_state(cd)
        actual = cd.get("cycle_state", "")
        if expected != actual:
            issues.append(f"{t['ticker']}: expected cycle_state={expected}, got={actual}")

    status = "PASS" if not issues else "FAIL"
    return {"check": "Cycle State Consistency", "status": status, "issues": issues}


def check_order_count(data, portfolio):
    """Check 3: Total BUY order count in portfolio.json vs JSON totals."""
    issues = []
    pending_all = portfolio.get("pending_orders", {})
    for t in data.get("tickers", []):
        ticker = t["ticker"]
        orders = pending_all.get(ticker, [])
        buy_orders = [o for o in orders if o.get("type") == "BUY"]
        json_total = t.get("order_info", {}).get("total_buy_orders", 0)
        if len(buy_orders) != json_total:
            issues.append(f"{ticker}: portfolio.json has {len(buy_orders)} BUY orders, JSON reports {json_total}")

    status = "PASS" if not issues else "FAIL"
    return {"check": "Order Count Cross-check", "status": status, "issues": issues}


def check_paused_annotation(data, report_text):
    """Check 4: all_paused==true tickers have annotation in report."""
    issues = []
    report_lower = report_text.lower()
    for t in data.get("tickers", []):
        if t.get("order_info", {}).get("all_paused") and t.get("order_info", {}).get("total_buy_orders", 0) > 0:
            ticker = t["ticker"]
            if ticker not in report_text:
                issues.append(f"{ticker}: all_paused=true but ticker not found in report")
                continue
            # Check for "paused" mention within 500 chars after ticker in report
            idx = report_lower.find(ticker.lower())
            if idx >= 0:
                after = report_lower[idx:idx + 500]
                if "paused" not in after:
                    issues.append(f"{ticker}: all_paused=true but no 'paused' annotation found near ticker in report")

    status = "PASS" if not issues else "MINOR"
    return {"check": "PAUSED Annotation", "status": status, "issues": issues}


def check_llm_coverage(data, report_text):
    """Check 5: Every JSON ticker mentioned in report."""
    issues = []
    for t in data.get("tickers", []):
        ticker = t["ticker"]
        if ticker not in report_text:
            issues.append(f"{ticker}: present in JSON but missing from report")

    status = "PASS" if not issues else "FAIL"
    return {"check": "LLM Coverage", "status": status, "issues": issues}


def check_override_gate(report_text):
    """Check 6: LLM overrides have explicit justification text."""
    issues = []
    # Look for override patterns: ENGAGE→WAIT, REVIEW→KEEP
    override_patterns = [
        (r"ENGAGE\s*→\s*WAIT", "ENGAGE→WAIT"),
        (r"REVIEW\s*→\s*KEEP", "REVIEW→KEEP"),
        (r"override.*?(?:ENGAGE|REVIEW|WAIT|KEEP)", "override mention"),
    ]
    for pattern, label in override_patterns:
        matches = re.findall(pattern, report_text, re.IGNORECASE)
        for match in matches:
            # Check if there's justification text nearby (at least 20 chars after)
            idx = report_text.lower().find(match.lower() if isinstance(match, str) else label.lower())
            if idx >= 0:
                after = report_text[idx:idx + 200]
                # Simple heuristic: override should have explanation
                if len(after.strip()) < 30:
                    issues.append(f"{label}: override found but lacks justification")

    status = "PASS" if not issues else "FAIL"
    return {"check": "Override Gate", "status": status, "issues": issues}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    data = _load_json(JSON_PATH)
    portfolio = _load_json(PORTFOLIO_PATH)
    report_text = _load_text(REPORT_PATH)

    checks = [
        check_verdict_consistency(data),
        check_cycle_state(data),
        check_order_count(data, portfolio),
        check_paused_annotation(data, report_text),
        check_llm_coverage(data, report_text),
        check_override_gate(report_text),
    ]

    # Build output
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Watchlist Fitness Pre-Critic Verification",
        f"",
        f"*Generated: {now}*",
        f"",
        f"## Verification Summary",
        f"",
        f"| # | Check | Status | Issues |",
        f"| :--- | :--- | :--- | :--- |",
    ]

    total_pass = 0
    total_issues = 0
    for i, check in enumerate(checks, 1):
        issue_count = len(check["issues"])
        total_issues += issue_count
        if check["status"] == "PASS":
            total_pass += 1
        lines.append(f"| {i} | {check['check']} | {check['status']} | {issue_count} |")

    lines.append("")
    lines.append(f"**Result: {total_pass}/{len(checks)} checks passed, {total_issues} issue(s) found.**")
    lines.append("")

    # Detail sections
    for i, check in enumerate(checks, 1):
        lines.append(f"## Check {i}: {check['check']}")
        lines.append(f"")
        lines.append(f"**Status: {check['status']}**")
        lines.append("")
        if check["issues"]:
            for issue in check["issues"]:
                lines.append(f"- {issue}")
            lines.append("")
        else:
            lines.append("No issues found.")
            lines.append("")

    # Qualitative focus areas for LLM critic
    lines.append("## For Critic: Qualitative Focus Areas")
    lines.append("")
    lines.append("- **ENGAGE/ADD tickers**: Is entry timing sound given cycle data, or is analyst ignoring OVERBOUGHT?")
    lines.append("- **RESTRUCTURE/HOLD-WAIT**: Is the re-entry signal realistic?")
    lines.append("- **EXIT-REVIEW**: Confirms deferral to exit-review-workflow is appropriate?")
    lines.append("- **Overrides**: Is justification credible and specific?")
    lines.append("")

    content = "\n".join(lines)
    with open(OUTPUT_PATH, "w") as f:
        f.write(content)

    print(f"Pre-critic verification complete: {total_pass}/{len(checks)} passed, {total_issues} issues")
    print(f"Written: {OUTPUT_PATH.name}")


if __name__ == "__main__":
    main()
