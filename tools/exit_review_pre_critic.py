#!/usr/bin/env python3
"""Exit Review Pre-Critic — Phase 3 mechanical verification for exit-review workflow.

Reads exit-review-raw.md, exit-review-report.md, and portfolio.json. Runs 6
verification checks and writes exit-review-pre-critic.md for the LLM critic
to add qualitative assessment.

Usage: python3 tools/exit_review_pre_critic.py
"""

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

# Same-directory imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
from exit_review_pre_analyst import (
    split_table_row,
    extract_report_date,
    parse_position_summary,
    parse_per_ticker_data,
    parse_technical_signals,
    parse_earnings_data,
    parse_short_interest_data,
    compute_days_held,
    compute_time_stop,
    classify_position,
    compute_pl,
    compute_earnings_gate,
    compute_profit_target_status,
    compute_momentum_label,
    compute_verdict,
    parse_bullets_status,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = PROJECT_ROOT / "exit-review-raw.md"
REPORT_PATH = PROJECT_ROOT / "exit-review-report.md"
PORTFOLIO_PATH = PROJECT_ROOT / "portfolio.json"
OUTPUT_PATH = PROJECT_ROOT / "exit-review-pre-critic.md"

# Tolerances
DAY_TOLERANCE = 1
DOLLAR_TOLERANCE = 0.04
PCT_TOLERANCE = 0.2
DEPLOYED_TOLERANCE = 0.02


# ---------------------------------------------------------------------------
# Input Validation
# ---------------------------------------------------------------------------

def validate_inputs():
    """Load all 3 input files. Returns (raw_text, report_text, portfolio) or exits."""
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


# ---------------------------------------------------------------------------
# Report Parsing (analyst output: exit-review-report.md)
# ---------------------------------------------------------------------------

def parse_report_positions(report_text):
    """Parse per-position headers and their exit criteria from report.
    Returns dict of {ticker: {verdict, criteria, has_action, action_text, has_reasoning}}."""
    positions = {}
    lines = report_text.split("\n")

    current_ticker = None
    current_verdict = None
    current_lines = []

    for line in lines:
        stripped = line.strip()
        # Match "### TICKER — VERDICT" (em-dash)
        m = re.match(r'^###\s+(\w+)\s+[—–-]\s+(EXIT|REDUCE|HOLD|MONITOR)', stripped)
        if m:
            if current_ticker:
                positions[current_ticker] = _parse_position_detail(
                    current_verdict, current_lines)
            current_ticker = m.group(1)
            current_verdict = m.group(2)
            current_lines = []
        elif current_ticker is not None:
            # Stop at next ### or ##
            if stripped.startswith("## ") and not stripped.startswith("### "):
                positions[current_ticker] = _parse_position_detail(
                    current_verdict, current_lines)
                current_ticker = None
                current_verdict = None
                current_lines = []
            else:
                current_lines.append(line)

    if current_ticker:
        positions[current_ticker] = _parse_position_detail(current_verdict, current_lines)

    return positions


def _parse_position_detail(verdict, lines):
    """Parse detail within a single position section."""
    result = {
        "verdict": verdict,
        "criteria": {},
        "has_action": False,
        "action_text": "",
        "has_reasoning": False,
        "reasoning_text": "",
    }

    # Parse Exit Criteria Summary table
    in_criteria = False
    for line in lines:
        stripped = line.strip()
        if "Exit Criteria Summary" in stripped:
            in_criteria = True
            continue
        if in_criteria and stripped.startswith("| :"):
            continue
        if in_criteria and stripped.startswith("| Criterion"):
            continue
        if in_criteria and stripped.startswith("|"):
            cols = split_table_row(stripped)
            if len(cols) >= 3:
                result["criteria"][cols[0]] = {
                    "status": cols[1],
                    "detail": cols[2],
                }
        elif in_criteria and stripped and not stripped.startswith("|"):
            in_criteria = False

    # Check for Reasoning
    text = "\n".join(lines)
    if "**Reasoning:**" in text or "**Reasoning**" in text:
        result["has_reasoning"] = True
        # Extract reasoning text
        m = re.search(r'\*\*Reasoning:?\*\*\s*(.*?)(?:\n\n|\n\*\*)', text, re.DOTALL)
        if m:
            result["reasoning_text"] = m.group(1).strip()

    # Check for Recommended Action
    if "**Recommended Action:**" in text or "**Recommended Action**" in text:
        result["has_action"] = True
        m = re.search(r'\*\*Recommended Action:?\*\*\s*(.*?)(?:\n\n|\n\*\*|\Z)', text, re.DOTALL)
        if m:
            result["action_text"] = m.group(1).strip()

    return result


def parse_report_matrix(report_text):
    """Parse Exit Review Matrix table from report.
    Returns list of dicts with ticker, verdict, etc."""
    rows = []
    in_matrix = False

    for line in report_text.split("\n"):
        stripped = line.strip()
        if "## Exit Review Matrix" in stripped:
            in_matrix = True
            continue
        if in_matrix and stripped.startswith("## "):
            break
        if not in_matrix or not stripped.startswith("|"):
            continue
        if stripped.startswith("| Ticker") or stripped.startswith("| :"):
            continue

        cols = split_table_row(stripped)
        if len(cols) >= 8:
            # Extract verdict (may be bold)
            verdict_str = cols[-2] if len(cols) >= 10 else cols[7]
            verdict_str = verdict_str.replace("*", "").strip()

            try:
                pl_str = cols[3].replace("%", "").replace("+", "").strip()
                pl_pct = float(pl_str) if pl_str != "N/A" else None
            except ValueError:
                pl_pct = None

            rows.append({
                "ticker": cols[0].replace("*", "").strip(),
                "days_held_str": cols[1],
                "time_stop": cols[2],
                "pl_pct": pl_pct,
                "verdict": verdict_str,
            })

    return rows


def parse_report_capital_rotation(report_text):
    """Check if Capital Rotation Summary section exists."""
    return "## Capital Rotation" in report_text


def parse_report_executive_summary(report_text):
    """Extract executive summary section text."""
    m = re.search(r'## Executive Summary\s*\n(.*?)(?=\n## |\Z)', report_text, re.DOTALL)
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------------------
# Check Functions
# ---------------------------------------------------------------------------

def check_day_count_math(raw_summary, report_date, report_positions):
    """Check 1: Day count math verification."""
    issues = []
    notes = []

    for row in raw_summary:
        ticker = row["ticker"]
        # Use raw.md entry_date (same source the analyst used), not portfolio.json
        entry_date = row["entry_date"]

        # Recompute
        days, display, is_pre = compute_days_held(entry_date, report_date)
        expected_ts = compute_time_stop(days, is_pre)

        # Check report
        report_pos = report_positions.get(ticker, {})
        criteria = report_pos.get("criteria", {})
        ts_criteria = criteria.get("Time Stop", {})
        report_status = ts_criteria.get("status", "")
        report_detail = ts_criteria.get("detail", "")

        # Verify time stop status
        if report_status and expected_ts:
            # Normalize for comparison
            norm_expected = expected_ts.upper().strip()
            norm_report = report_status.upper().strip()
            if norm_expected not in norm_report and norm_report not in norm_expected:
                issues.append(
                    f"{ticker}: time stop '{report_status}' vs expected '{expected_ts}' (Critical)"
                )

        # Verify days held (extract from detail)
        if days is not None and report_detail:
            m = re.search(r'(\d+)\s*days?\s*held', report_detail)
            if m:
                report_days = int(m.group(1))
                if abs(report_days - days) > DAY_TOLERANCE:
                    issues.append(
                        f"{ticker}: days held {report_days} vs expected {days} (Critical)"
                    )

    critical = [i for i in issues if "Critical" in i]
    status = "FAIL" if critical else "PASS"
    return {"status": status, "issues": issues, "notes": notes}


def check_pl_math(raw_summary, report_positions):
    """Check 2: P/L math verification."""
    issues = []
    notes = []

    for row in raw_summary:
        ticker = row["ticker"]

        # Use raw.md values (same source the analyst used), not portfolio.json
        shares = row["shares"]
        avg_cost = row["avg_cost"]
        current = row["current"]

        if current is None:
            continue

        expected_deployed = shares * avg_cost
        expected_value = shares * current
        expected_pl = expected_value - expected_deployed
        expected_pct = (expected_pl / expected_deployed * 100) if expected_deployed else 0

        # Check report values from criteria
        report_pos = report_positions.get(ticker, {})
        criteria = report_pos.get("criteria", {})
        pt_criteria = criteria.get("Profit Target", {})
        pt_detail = pt_criteria.get("detail", "")

        # Extract P/L % from detail
        m = re.search(r'P/L\s*([+-]?\d+\.?\d*)%', pt_detail)
        if m:
            report_pct = float(m.group(1))
            if abs(report_pct - expected_pct) > PCT_TOLERANCE:
                issues.append(
                    f"{ticker}: P/L % {report_pct:.1f}% vs expected {expected_pct:.1f}% (Critical)"
                )
            elif abs(report_pct - expected_pct) > 0.05:
                notes.append(
                    f"{ticker}: P/L % rounding {report_pct:.1f}% vs {expected_pct:.1f}% (Minor)"
                )

        # Check profit target label
        pt_status = pt_criteria.get("status", "")
        expected_pt_status = compute_profit_target_status(expected_pct)
        if pt_status and expected_pt_status:
            if expected_pt_status.replace("_", " ").upper() not in pt_status.upper().replace("_", " "):
                # Allow some flexibility in naming
                norm_expected = expected_pt_status.replace("_", " ").lower()
                norm_report = pt_status.lower().replace("_", " ")
                if norm_expected != norm_report and norm_expected not in norm_report:
                    issues.append(
                        f"{ticker}: profit target status '{pt_status}' vs expected "
                        f"'{expected_pt_status}' (Critical)"
                    )

    critical = [i for i in issues if "Critical" in i]
    status = "FAIL" if critical else "PASS"
    return {"status": status, "issues": issues, "notes": notes}


def check_verdict_assignment(raw_summary, per_ticker_data, portfolio, report_date,
                             report_positions):
    """Check 3: Verdict assignment verification.
    Re-apply verdict ruleset independently and compare."""
    issues = []
    notes = []

    for row in raw_summary:
        ticker = row["ticker"]
        current = row["current"]
        if current is None:
            continue

        shares = row["shares"]
        avg_cost = row["avg_cost"]
        deployed, pl_dollar, pl_pct = compute_pl(shares, avg_cost, current)

        days_held, days_display, is_pre = compute_days_held(row["entry_date"], report_date)
        time_stop = compute_time_stop(days_held, is_pre)
        classification = classify_position(ticker, portfolio, pl_pct)

        ticker_data = per_ticker_data.get(ticker, {})
        tech = parse_technical_signals(ticker_data.get("technical", ""))
        earnings_data = parse_earnings_data(ticker_data.get("earnings", ""))
        short_data = parse_short_interest_data(ticker_data.get("short_interest", ""))
        earnings_gate = compute_earnings_gate(earnings_data["days_until"])
        profit_target_status = compute_profit_target_status(pl_pct)
        momentum_label = compute_momentum_label(tech["overall_score"])

        bullets_fully, bullets_building, b_used, b_max = parse_bullets_status(
            row["bullets_str"], row["note"]
        )

        pos_data = {
            "ticker": ticker,
            "pl_pct": pl_pct,
            "classification": classification,
            "earnings_gate": earnings_gate,
            "time_stop": time_stop,
            "technical": tech,
            "short_interest": short_data,
            "bullets": {
                "is_fully_loaded": bullets_fully,
                "is_still_building": bullets_building,
                "bullets_used": b_used,
                "max_bullets": b_max,
            },
        }

        expected_verdict, expected_rule, _, _ = compute_verdict(pos_data)

        # Get report verdict
        report_pos = report_positions.get(ticker, {})
        report_verdict = report_pos.get("verdict", "")

        if report_verdict and report_verdict != expected_verdict:
            # Rule 3 override: LLM can override REDUCE→HOLD for GATED recovery with thesis
            if (expected_rule in ("4", "5") and report_verdict == "HOLD" and
                    classification["effective_recovery"] and earnings_gate == "GATED"):
                # Check if thesis is documented
                if report_pos.get("has_reasoning") and report_pos.get("reasoning_text"):
                    notes.append(
                        f"{ticker}: Rule 3 override applied (REDUCE→HOLD) — "
                        f"thesis documented (Minor)"
                    )
                else:
                    issues.append(
                        f"{ticker}: Rule 3 override without documented thesis (Critical)"
                    )
            else:
                issues.append(
                    f"{ticker}: verdict '{report_verdict}' vs expected "
                    f"'{expected_verdict}' (Rule {expected_rule}) (Critical)"
                )

    critical = [i for i in issues if "Critical" in i]
    status = "FAIL" if critical else "PASS"
    return {"status": status, "issues": issues, "notes": notes}


def check_earnings_gate(raw_summary, per_ticker_data, report_positions):
    """Check 4: Earnings gate logic verification."""
    issues = []
    notes = []

    for row in raw_summary:
        ticker = row["ticker"]
        ticker_data = per_ticker_data.get(ticker, {})
        earnings_data = parse_earnings_data(ticker_data.get("earnings", ""))

        expected_gate = compute_earnings_gate(earnings_data["days_until"])

        # Get report earnings gate
        report_pos = report_positions.get(ticker, {})
        criteria = report_pos.get("criteria", {})
        eg_criteria = criteria.get("Earnings Gate", {})
        report_status = eg_criteria.get("status", "")
        report_detail = eg_criteria.get("detail", "")

        if report_status:
            norm_expected = expected_gate.upper()
            norm_report = report_status.upper()
            if norm_expected not in norm_report and norm_report not in norm_expected:
                issues.append(
                    f"{ticker}: earnings gate '{report_status}' vs expected "
                    f"'{expected_gate}' (Critical)"
                )

        # Check days-to-earnings
        if earnings_data["days_until"] is not None and report_detail:
            m = re.search(r'(\d+)\s*days?\s*to\s*earnings', report_detail)
            if m:
                report_days = int(m.group(1))
                if abs(report_days - earnings_data["days_until"]) > DAY_TOLERANCE:
                    issues.append(
                        f"{ticker}: days to earnings {report_days} vs expected "
                        f"{earnings_data['days_until']} (Critical)"
                    )

    critical = [i for i in issues if "Critical" in i]
    status = "FAIL" if critical else "PASS"
    return {"status": status, "issues": issues, "notes": notes}


def check_data_consistency(raw_summary, portfolio, report_positions, report_matrix):
    """Check 5: Data consistency verification."""
    issues = []
    notes = []

    pj_positions = portfolio.get("positions", {})

    # Check shares & avg_cost match portfolio.json
    for row in raw_summary:
        ticker = row["ticker"]
        pj = pj_positions.get(ticker, {})

        pj_shares = pj.get("shares", 0)
        pj_avg = pj.get("avg_cost", 0)

        if row["shares"] != pj_shares:
            issues.append(
                f"{ticker}: raw shares {row['shares']} vs portfolio.json {pj_shares} (Critical)"
            )
        if abs(row["avg_cost"] - pj_avg) > 0.01:
            issues.append(
                f"{ticker}: raw avg_cost ${row['avg_cost']:.2f} vs portfolio.json "
                f"${pj_avg:.2f} (Critical)"
            )

    # Check no phantom tickers in report
    active_tickers = {row["ticker"] for row in raw_summary}
    for ticker in report_positions:
        if ticker not in active_tickers:
            issues.append(f"{ticker}: in report but not in raw data (Critical)")

    # Check matrix verdict matches position detail verdict
    for matrix_row in report_matrix:
        ticker = matrix_row["ticker"]
        report_pos = report_positions.get(ticker, {})
        if report_pos.get("verdict") and matrix_row["verdict"]:
            if report_pos["verdict"] != matrix_row["verdict"]:
                issues.append(
                    f"{ticker}: matrix verdict '{matrix_row['verdict']}' vs "
                    f"detail verdict '{report_pos['verdict']}' (Critical)"
                )

    critical = [i for i in issues if "Critical" in i]
    status = "FAIL" if critical else "PASS"
    return {"status": status, "issues": issues, "notes": notes}


def check_coverage(raw_summary, portfolio, report_positions, report_text):
    """Check 6: Coverage & completeness verification."""
    issues = []
    notes = []

    pj_positions = portfolio.get("positions", {})

    # Every active position must be reviewed
    for ticker, pj in pj_positions.items():
        shares = pj.get("shares", 0)
        if isinstance(shares, (int, float)) and shares > 0:
            if ticker not in report_positions:
                issues.append(f"{ticker}: active position not reviewed in report (Critical)")

    # Every position has all 4 criteria
    required_criteria = ["Time Stop", "Profit Target", "Earnings Gate", "Momentum"]
    for ticker, pos in report_positions.items():
        for crit in required_criteria:
            if crit not in pos.get("criteria", {}):
                issues.append(f"{ticker}: missing '{crit}' criterion (Critical)")

    # EXIT/REDUCE must have recommended action
    for ticker, pos in report_positions.items():
        if pos["verdict"] in ("EXIT", "REDUCE"):
            if not pos["has_action"]:
                issues.append(f"{ticker}: {pos['verdict']} without Recommended Action (Critical)")
            # Verdict-action consistency: REDUCE must actually sell shares
            if pos["verdict"] == "REDUCE" and pos["has_action"]:
                action_lower = pos["action_text"].lower()
                if ("hold" in action_lower and "sell" not in action_lower and
                        "close" not in action_lower and "reduce" not in action_lower):
                    issues.append(
                        f"{ticker}: REDUCE verdict but action says 'hold' — "
                        f"should be HOLD (Critical)"
                    )

    # Capital Rotation present if EXIT/REDUCE exists
    has_exit_reduce = any(p["verdict"] in ("EXIT", "REDUCE") for p in report_positions.values())
    has_rotation = parse_report_capital_rotation(report_text)
    if has_exit_reduce and not has_rotation:
        issues.append("Capital Rotation Summary missing with EXIT/REDUCE verdicts (Critical)")

    # Executive Summary present
    exec_summary = parse_report_executive_summary(report_text)
    if not exec_summary:
        notes.append("Executive Summary section empty or missing (Minor)")

    critical = [i for i in issues if "Critical" in i]
    status = "FAIL" if critical else "PASS"
    return {"status": status, "issues": issues, "notes": notes}


# ---------------------------------------------------------------------------
# Report Builder
# ---------------------------------------------------------------------------

def build_report(checks):
    """Assemble exit-review-pre-critic.md."""
    parts = []

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    parts.append("# Exit Review Pre-Critic — Mechanical Verification")
    parts.append(f"*Generated: {now_str} | Tool: exit_review_pre_critic.py*")
    parts.append("")

    # Verification Summary
    parts.append("## Verification Summary")
    parts.append("")
    parts.append("| Check | Result | Details |")
    parts.append("| :--- | :--- | :--- |")

    check_names = [
        ("Day Count Math", "day_count"),
        ("P/L Math", "pl_math"),
        ("Verdict Assignment", "verdict"),
        ("Earnings Gate Logic", "earnings_gate"),
        ("Data Consistency", "data_consistency"),
        ("Coverage", "coverage"),
    ]

    for label, key in check_names:
        check = checks[key]
        n_critical = len([i for i in check["issues"] if "Critical" in i])
        n_minor = len(check.get("notes", []))
        details = []
        if n_critical:
            details.append(f"{n_critical} critical")
        if n_minor:
            details.append(f"{n_minor} minor")
        if not details:
            details.append("Clean")
        parts.append(f"| {label} | {check['status']} | {', '.join(details)} |")

    parts.append("")

    # Overall verdict
    all_pass = all(checks[key]["status"] == "PASS" for _, key in check_names)
    total_critical = sum(
        len([i for i in checks[key]["issues"] if "Critical" in i])
        for _, key in check_names
    )
    total_minor = sum(len(checks[key].get("notes", [])) for _, key in check_names)

    verdict = "PASS" if all_pass else "ISSUES"
    parts.append(f"**Overall Verdict: {verdict}** — {total_critical} critical, "
                 f"{total_minor} minor")
    parts.append("")
    parts.append("---")
    parts.append("")

    # Detailed sections for each check
    section_titles = {
        "day_count": "Day Count Errors",
        "pl_math": "P/L Math Errors",
        "verdict": "Verdict Assignment Errors",
        "earnings_gate": "Earnings Gate Errors",
        "data_consistency": "Data Consistency Issues",
        "coverage": "Coverage Gaps",
    }

    for _, key in check_names:
        title = section_titles[key]
        check = checks[key]
        parts.append(f"## {title}")
        parts.append("")

        if not check["issues"] and not check.get("notes", []):
            parts.append(f"No {title.lower()} found.")
        else:
            if check["issues"]:
                for issue in check["issues"]:
                    severity = "Critical" if "Critical" in issue else "Minor"
                    clean = issue.replace(" (Critical)", "").replace(" (Minor)", "")
                    parts.append(f"- **{severity}:** {clean}")
            if check.get("notes"):
                for note in check["notes"]:
                    clean = note.replace(" (Minor)", "")
                    parts.append(f"- *Minor:* {clean}")

        parts.append("")

    # Qualitative Focus Areas
    parts.append("---")
    parts.append("")
    parts.append("## For Critic: Qualitative Focus Areas")
    parts.append("")
    parts.append("1. **Reasoning quality** — are verdicts supported by data-grounded arguments?")
    parts.append("2. **Action plausibility** — are broker instructions specific and executable?")
    parts.append("3. **Rule 3 thesis quality** — for GATED recovery overrides, "
                 "is the thesis well-documented?")
    parts.append("4. **Rotate-to suggestions** — for EXIT/REDUCE, are watchlist candidates named?")
    parts.append("5. **Executive summary** — does it accurately reflect verdict counts and actions?")
    parts.append("")

    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Validate and load
    raw_text, report_text, portfolio = validate_inputs()
    report_date = extract_report_date(raw_text)

    print(f"Exit Review Pre-Critic — {report_date.isoformat()}")

    # Parse raw data
    raw_summary = parse_position_summary(raw_text)
    per_ticker_data = parse_per_ticker_data(raw_text)
    print(f"Raw: {len(raw_summary)} positions, {len(per_ticker_data)} ticker sections")

    # Parse report
    report_positions = parse_report_positions(report_text)
    report_matrix = parse_report_matrix(report_text)
    print(f"Report: {len(report_positions)} position sections, "
          f"{len(report_matrix)} matrix rows")

    # Run 6 checks
    checks = {
        "day_count": check_day_count_math(
            raw_summary, report_date, report_positions),
        "pl_math": check_pl_math(
            raw_summary, report_positions),
        "verdict": check_verdict_assignment(
            raw_summary, per_ticker_data, portfolio, report_date, report_positions),
        "earnings_gate": check_earnings_gate(
            raw_summary, per_ticker_data, report_positions),
        "data_consistency": check_data_consistency(
            raw_summary, portfolio, report_positions, report_matrix),
        "coverage": check_coverage(
            raw_summary, portfolio, report_positions, report_text),
    }

    # Print summary
    for name, check in checks.items():
        n_crit = len([i for i in check["issues"] if "Critical" in i])
        n_minor = len(check.get("notes", []))
        print(f"  {name}: {check['status']} ({n_crit} critical, {n_minor} minor)")

    # Build and write report
    content = build_report(checks)
    OUTPUT_PATH.write_text(content, encoding="utf-8")
    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"\nOutput: exit-review-pre-critic.md ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
