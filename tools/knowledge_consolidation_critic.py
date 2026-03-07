#!/usr/bin/env python3
"""Knowledge Consolidation Critic — Phase 3 pre-script.

Runs 6 mechanical verification checks on the analyst's report and updates.json:
1. Coverage — every contradiction score > 0.3 has a classification
2. Evidence citations — every classification has ≥2 numeric/date references
3. JSON well-formedness — updates.json parses, required fields non-empty
4. Superseded-replacement pairing — every superseded ID has a new_lesson
5. Stats transcription — report metrics match raw data
6. Portfolio lesson threshold — sample_size >= 5

Writes knowledge-consolidation-pre-critic.md.

Usage: python3 tools/knowledge_consolidation_critic.py
"""

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = PROJECT_ROOT / "knowledge-consolidation-raw.md"
REPORT_PATH = PROJECT_ROOT / "knowledge-consolidation-report.md"
UPDATES_PATH = PROJECT_ROOT / "knowledge-consolidation-updates.json"
OUTPUT_PATH = PROJECT_ROOT / "knowledge-consolidation-pre-critic.md"

# Regex for evidence citations: $, %, YYYY-MM-DD, or standalone numbers
_CITATION_RE = re.compile(r'\$\d|%|\d{4}-\d{2}-\d{2}|\b\d+\.\d+\b')


def check_coverage(raw_text: str, report_text: str) -> dict:
    """Check 1: every contradiction > 0.3 in raw has classification in report."""
    issues = []

    # Extract contradictions from raw
    contradiction_tickers = []
    for m in re.finditer(
        r'\|\s*\d+\s*\|\s*(\w+)\s*\|.*?\|\s*(\w+)\s*\|\s*([\d.]+)\s*\|',
        raw_text
    ):
        ticker, entry_id, score = m.group(1), m.group(2), float(m.group(3))
        if score > 0.3:
            contradiction_tickers.append((ticker, entry_id, score))

    if not contradiction_tickers:
        return {"name": "Coverage", "result": "PASS", "details": "No contradictions above threshold."}

    # Check each has a classification in report
    missing = []
    for ticker, entry_id, score in contradiction_tickers:
        # Look for classification pattern near ticker mention
        pattern = rf'(?i)\[?{re.escape(ticker)}\]?\s.*?(?:TEMPORARY|STRUCTURAL)'
        if not re.search(pattern, report_text):
            # Fallback: just check ticker + classification exist
            has_ticker = ticker in report_text
            has_class = bool(re.search(
                rf'{re.escape(ticker)}.*?(?:Classification|TEMPORARY|STRUCTURAL)',
                report_text, re.DOTALL | re.IGNORECASE
            ))
            if not (has_ticker and has_class):
                missing.append(f"{ticker} (ID: {entry_id}, score: {score})")

    if missing:
        return {
            "name": "Coverage",
            "result": "FAIL",
            "details": f"Missing classifications: {', '.join(missing)}",
        }
    return {
        "name": "Coverage",
        "result": "PASS",
        "details": f"All {len(contradiction_tickers)} contradictions classified.",
    }


def check_evidence_citations(report_text: str) -> dict:
    """Check 2: every classification section has ≥2 numeric/date references."""
    issues = []

    # Find all classification sections
    sections = re.split(r'###\s+\[?\w+\]?\s+Belief:', report_text)
    if len(sections) <= 1:
        # Try alternate heading format
        sections = re.split(r'\*\*Classification:\*\*', report_text)

    classified_count = 0
    for section in sections[1:]:  # skip pre-first-heading content
        # Only check sections with TEMPORARY or STRUCTURAL
        if not re.search(r'TEMPORARY|STRUCTURAL', section):
            continue
        classified_count += 1

        # Count citation-like patterns
        citations = _CITATION_RE.findall(section[:500])  # first 500 chars of section
        if len(citations) < 2:
            # Extract section identifier
            heading = section[:60].strip().split("\n")[0]
            issues.append(f"Section '{heading[:40]}...' has {len(citations)} citations (need ≥2)")

    if issues:
        return {
            "name": "Evidence Citations",
            "result": "FAIL",
            "details": "; ".join(issues),
        }
    return {
        "name": "Evidence Citations",
        "result": "PASS",
        "details": f"{classified_count} classification sections verified.",
    }


def check_json_wellformedness(updates_path: Path) -> dict:
    """Check 3: updates.json parses, all required fields non-empty."""
    if not updates_path.exists():
        return {"name": "JSON Well-formedness", "result": "FAIL",
                "details": "knowledge-consolidation-updates.json not found."}
    try:
        data = json.loads(updates_path.read_text())
    except json.JSONDecodeError as e:
        return {"name": "JSON Well-formedness", "result": "FAIL",
                "details": f"JSON parse error: {e}"}

    issues = []
    # Check required top-level keys
    for key in ("superseded", "new_lessons", "annotations", "portfolio_lessons"):
        if key not in data:
            issues.append(f"Missing key: {key}")
        elif not isinstance(data[key], list):
            issues.append(f"{key} is not a list")

    # Check superseded entries
    for i, entry in enumerate(data.get("superseded", [])):
        if not entry.get("id"):
            issues.append(f"superseded[{i}] missing 'id'")
        if not entry.get("reason"):
            issues.append(f"superseded[{i}] missing 'reason'")

    # Check new_lessons
    for i, entry in enumerate(data.get("new_lessons", [])):
        for field in ("ticker", "category", "text"):
            if not entry.get(field):
                issues.append(f"new_lessons[{i}] missing '{field}'")

    # Check annotations
    for i, entry in enumerate(data.get("annotations", [])):
        if not entry.get("id"):
            issues.append(f"annotations[{i}] missing 'id'")
        if not entry.get("append_text"):
            issues.append(f"annotations[{i}] missing 'append_text'")

    if issues:
        return {"name": "JSON Well-formedness", "result": "FAIL",
                "details": "; ".join(issues)}
    return {"name": "JSON Well-formedness", "result": "PASS",
            "details": "All fields valid."}


def check_superseded_pairing(updates_path: Path) -> dict:
    """Check 4: every superseded ID has matching new_lesson with same ticker."""
    if not updates_path.exists():
        return {"name": "Superseded-Replacement Pairing", "result": "SKIP",
                "details": "No updates.json."}
    try:
        data = json.loads(updates_path.read_text())
    except json.JSONDecodeError:
        return {"name": "Superseded-Replacement Pairing", "result": "SKIP",
                "details": "JSON parse error (caught in Check 3)."}

    superseded_ids = {e["id"] for e in data.get("superseded", []) if e.get("id")}
    if not superseded_ids:
        return {"name": "Superseded-Replacement Pairing", "result": "PASS",
                "details": "No superseded entries."}

    # Build map of new_lessons by consolidated_from
    covered_ids = set()
    for lesson in data.get("new_lessons", []):
        for src_id in lesson.get("consolidated_from", []):
            covered_ids.add(src_id)

    unpaired = superseded_ids - covered_ids
    if unpaired:
        return {
            "name": "Superseded-Replacement Pairing",
            "result": "FAIL",
            "details": f"Superseded IDs without replacement: {', '.join(sorted(unpaired))}",
        }
    return {"name": "Superseded-Replacement Pairing", "result": "PASS",
            "details": f"All {len(superseded_ids)} superseded entries have replacements."}


def check_stats_transcription(raw_text: str, report_text: str) -> dict:
    """Check 5: ticker card metrics in report match raw."""
    issues = []

    # Extract win rates from raw
    raw_win_rates = {}
    for m in re.finditer(r'###\s+(\w+)\s+\(.*?\).*?Win Rate\s*\|\s*(\d+)%', raw_text, re.DOTALL):
        raw_win_rates[m.group(1)] = int(m.group(2))

    # Extract win rates from report
    for ticker, raw_rate in raw_win_rates.items():
        report_match = re.search(
            rf'{re.escape(ticker)}.*?[Ww]in [Rr]ate.*?(\d+)%',
            report_text, re.DOTALL
        )
        if report_match:
            report_rate = int(report_match.group(1))
            if report_rate != raw_rate:
                issues.append(f"{ticker} win rate: raw={raw_rate}%, report={report_rate}%")

    if issues:
        return {"name": "Stats Transcription", "result": "FAIL",
                "details": "; ".join(issues)}
    return {"name": "Stats Transcription", "result": "PASS",
            "details": f"Checked {len(raw_win_rates)} ticker win rates."}


def check_portfolio_lesson_threshold(updates_path: Path) -> dict:
    """Check 6: all portfolio lessons have sample_size >= 5."""
    if not updates_path.exists():
        return {"name": "Portfolio Lesson Threshold", "result": "SKIP",
                "details": "No updates.json."}
    try:
        data = json.loads(updates_path.read_text())
    except json.JSONDecodeError:
        return {"name": "Portfolio Lesson Threshold", "result": "SKIP",
                "details": "JSON parse error."}

    lessons = data.get("portfolio_lessons", [])
    if not lessons:
        return {"name": "Portfolio Lesson Threshold", "result": "PASS",
                "details": "No portfolio lessons."}

    violations = []
    for i, lesson in enumerate(lessons):
        size = lesson.get("sample_size", 0)
        if size < 5:
            violations.append(f"portfolio_lessons[{i}] sample_size={size}")

    if violations:
        return {"name": "Portfolio Lesson Threshold", "result": "FAIL",
                "details": "; ".join(violations)}
    return {"name": "Portfolio Lesson Threshold", "result": "PASS",
            "details": f"All {len(lessons)} lessons meet threshold."}


def main():
    # Read inputs
    if not RAW_PATH.exists():
        print("*Error: knowledge-consolidation-raw.md not found.*")
        sys.exit(1)
    if not REPORT_PATH.exists():
        print("*Error: knowledge-consolidation-report.md not found.*")
        sys.exit(1)

    raw_text = RAW_PATH.read_text()
    report_text = REPORT_PATH.read_text()

    # Run all 6 checks
    checks = [
        check_coverage(raw_text, report_text),
        check_evidence_citations(report_text),
        check_json_wellformedness(UPDATES_PATH),
        check_superseded_pairing(UPDATES_PATH),
        check_stats_transcription(raw_text, report_text),
        check_portfolio_lesson_threshold(UPDATES_PATH),
    ]

    # Count results
    passed = sum(1 for c in checks if c["result"] == "PASS")
    failed = sum(1 for c in checks if c["result"] == "FAIL")

    # Write output
    out = []
    out.append("# Knowledge Consolidation — Mechanical Verification")
    out.append("")
    out.append(f"**Result: {passed}/{len(checks)} checks passed" +
               (f", {failed} FAILED**" if failed else "**"))
    out.append("")
    out.append("## Verification Summary")
    out.append("| # | Check | Result | Details |")
    out.append("| :--- | :--- | :--- | :--- |")
    for i, c in enumerate(checks, 1):
        out.append(f"| {i} | {c['name']} | {c['result']} | {c['details']} |")

    out.append("")
    out.append("## Failed Checks Detail")
    failed_checks = [c for c in checks if c["result"] == "FAIL"]
    if failed_checks:
        for c in failed_checks:
            out.append(f"\n### {c['name']}")
            out.append(c["details"])
    else:
        out.append("\n*All checks passed.*")

    content = "\n".join(out) + "\n"
    OUTPUT_PATH.write_text(content)
    print(f"Wrote {OUTPUT_PATH.name} ({passed}/{len(checks)} passed, {failed} failed)")


if __name__ == "__main__":
    main()
