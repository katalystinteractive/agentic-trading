#!/usr/bin/env python3
"""Cycle timing pre-critic — mechanical verification (5 checks).

Reads per-ticker cycle_timing.json files + cycle-timing-report.md.
Discovers tickers from cycle-timing-raw.md headers.
Writes cycle-timing-pre-critic.md.

Usage:
    python3 tools/cycle_timing_pre_critic.py
"""
import json
import re
import datetime
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = _ROOT / "cycle-timing-raw.md"
REPORT_PATH = _ROOT / "cycle-timing-report.md"
OUTPUT_PATH = _ROOT / "cycle-timing-pre-critic.md"


def _load_text(path):
    if not path.exists():
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _discover_tickers(raw_text):
    """Parse cycle-timing-raw.md for '## Cycle Timing Analysis: TICKER' headers."""
    return re.findall(r"## Cycle Timing Analysis:\s+([A-Z]{1,5})", raw_text)


# ---------------------------------------------------------------------------
# Check 1: Math verification
# ---------------------------------------------------------------------------
def check_math(data):
    """Recompute median/min/max from cycle event log, compare to statistics."""
    issues = []
    cycles = data.get("cycles", [])
    stats = data.get("statistics", {})

    first_days = [c["days_first"] for c in cycles if c.get("days_first") is not None]
    deep_days = [c["days_deep"] for c in cycles if c.get("days_deep") is not None]

    # First touch stats
    if first_days:
        exp_median = int(np.median(first_days))
        exp_min = int(min(first_days))
        exp_max = int(max(first_days))
        if stats.get("median_first") != exp_median:
            issues.append(f"median_first: expected {exp_median}, got {stats.get('median_first')}")
        if stats.get("min_first") != exp_min:
            issues.append(f"min_first: expected {exp_min}, got {stats.get('min_first')}")
        if stats.get("max_first") != exp_max:
            issues.append(f"max_first: expected {exp_max}, got {stats.get('max_first')}")

    # Deep touch stats
    if deep_days:
        exp_median = int(np.median(deep_days))
        exp_min = int(min(deep_days))
        exp_max = int(max(deep_days))
        if stats.get("median_deep") != exp_median:
            issues.append(f"median_deep: expected {exp_median}, got {stats.get('median_deep')}")
        if stats.get("min_deep") != exp_min:
            issues.append(f"min_deep: expected {exp_min}, got {stats.get('min_deep')}")
        if stats.get("max_deep") != exp_max:
            issues.append(f"max_deep: expected {exp_max}, got {stats.get('max_deep')}")

    # Decay median verification — exclude cycles with empty decay dicts
    decay_agg = data.get("post_resistance_decay", {})
    # Collect per-cycle decays (deduped by date)
    seen_dates = set()
    per_date_decays = []
    for c in cycles:
        rd = c.get("resistance_date")
        decay = c.get("post_resistance_decay", {})
        if rd not in seen_dates and decay:
            per_date_decays.append(decay)
            seen_dates.add(rd)

    for offset in ["1", "3", "5", "10"]:
        vals = [d.get(offset) for d in per_date_decays if d.get(offset) is not None]
        if vals:
            exp = round(float(np.median(vals)), 1)
            got = decay_agg.get(offset)
            if got is not None and abs(got - exp) > 0.15:
                issues.append(f"decay +{offset}d: expected {exp}, got {got}")

    return issues


# ---------------------------------------------------------------------------
# Check 2: Cooldown formula
# ---------------------------------------------------------------------------
def check_cooldown(data):
    """Verify cooldown = max(3, int(median_deep * 0.6)), fallback to median_first."""
    issues = []
    stats = data.get("statistics", {})
    rec = data.get("recommendation", {})

    median_deep = stats.get("median_deep")
    median_first = stats.get("median_first")
    base = median_deep if median_deep is not None else median_first
    expected_cd = max(3, int(base * 0.6)) if base is not None else None

    if rec.get("cooldown_days") != expected_cd:
        issues.append(f"cooldown_days: expected {expected_cd}, got {rec.get('cooldown_days')}")

    return issues


# ---------------------------------------------------------------------------
# Check 3: Immediate fill consistency
# ---------------------------------------------------------------------------
def check_immediate_fill(data):
    """Verify immediate_fill_pct >= 40 ↔ immediate_reentry_viable."""
    issues = []
    stats = data.get("statistics", {})
    rec = data.get("recommendation", {})

    pct = stats.get("immediate_fill_pct", 0)
    viable = rec.get("immediate_reentry_viable", False)

    if (pct >= 40) != viable:
        issues.append(
            f"immediate_fill_pct={pct}% but immediate_reentry_viable={viable}"
        )

    return issues


# ---------------------------------------------------------------------------
# Check 4: LLM coverage
# ---------------------------------------------------------------------------
def check_coverage(tickers, report_text):
    """Every JSON ticker should be mentioned in the report."""
    issues = []
    for t in tickers:
        if t not in report_text:
            issues.append(f"{t} missing from cycle-timing-report.md")
    return issues


# ---------------------------------------------------------------------------
# Check 5: Recency + completeness
# ---------------------------------------------------------------------------
def check_recency(data):
    """Most recent cycle >90 days = stale. days_deep >= days_first for all cycles."""
    issues = []
    cycles = data.get("cycles", [])

    # Staleness — use last_date from data (not date.today()) per data staleness convention
    if cycles:
        most_recent = max(c["resistance_date"] for c in cycles)
        try:
            rd = datetime.date.fromisoformat(most_recent)
            last_date_str = data.get("last_date", "")
            ref_date = (datetime.date.fromisoformat(last_date_str)
                        if last_date_str else datetime.date.today())
            age = (ref_date - rd).days
            if age > 90:
                issues.append(f"[Minor] Most recent cycle is {age} days old (stale)")
        except ValueError:
            pass

    # days_deep >= days_first for all cycles where both are not None
    for i, c in enumerate(cycles, 1):
        df = c.get("days_first")
        dd = c.get("days_deep")
        if df is not None and dd is not None and dd < df:
            issues.append(
                f"Cycle {i}: days_deep ({dd}) < days_first ({df})"
            )

    # current_cycle excluded from stats (verify total_cycles matches len(cycles))
    stats = data.get("statistics", {})
    if stats.get("total_cycles") != len(cycles):
        issues.append(
            f"total_cycles ({stats.get('total_cycles')}) != completed cycles ({len(cycles)})"
        )

    return issues


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    raw_text = _load_text(RAW_PATH)
    report_text = _load_text(REPORT_PATH)
    tickers = _discover_tickers(raw_text)

    if not tickers:
        OUTPUT_PATH.write_text(
            "# Cycle Timing Pre-Critic\n\n*No tickers found in cycle-timing-raw.md.*\n",
            encoding="utf-8",
        )
        print("*No tickers found in cycle-timing-raw.md.*")
        return

    check_names = [
        "Math verification",
        "Cooldown formula",
        "Immediate fill consistency",
        "LLM coverage",
        "Recency + completeness",
    ]
    global_issues = {name: [] for name in check_names}

    for ticker in tickers:
        json_path = _ROOT / "tickers" / ticker / "cycle_timing.json"
        if not json_path.exists():
            global_issues["Math verification"].append(
                f"{ticker}: cycle_timing.json not found"
            )
            continue

        data = _load_json(json_path)

        # Checks 1-3, 5 (per-ticker)
        for issue in check_math(data):
            global_issues["Math verification"].append(f"{ticker}: {issue}")
        for issue in check_cooldown(data):
            global_issues["Cooldown formula"].append(f"{ticker}: {issue}")
        for issue in check_immediate_fill(data):
            global_issues["Immediate fill consistency"].append(f"{ticker}: {issue}")
        for issue in check_recency(data):
            global_issues["Recency + completeness"].append(f"{ticker}: {issue}")

    # Check 4: LLM coverage (global)
    if report_text:
        for issue in check_coverage(tickers, report_text):
            global_issues["LLM coverage"].append(issue)
    else:
        global_issues["LLM coverage"].append("cycle-timing-report.md not found")

    # Build output
    lines = []
    lines.append(f"# Cycle Timing Pre-Critic — {datetime.date.today().isoformat()}")
    lines.append("")

    # Summary table
    lines.append("## Verification Summary")
    lines.append("")
    lines.append("| # | Check | Result |")
    lines.append("| :--- | :--- | :--- |")
    total_pass = 0
    for i, name in enumerate(check_names, 1):
        issues = global_issues[name]
        # Minor issues don't fail the check
        real_issues = [x for x in issues if "[Minor]" not in x]
        if not real_issues:
            lines.append(f"| {i} | {name} | PASS |")
            total_pass += 1
        else:
            lines.append(f"| {i} | {name} | FAIL ({len(real_issues)} issue(s)) |")
    lines.append("")
    lines.append(f"**Result: {total_pass}/5 checks passed**")
    lines.append("")

    # Detail sections
    for i, name in enumerate(check_names, 1):
        issues = global_issues[name]
        lines.append(f"### Check {i}: {name}")
        if not issues:
            lines.append("PASS — no issues found.")
        else:
            for issue in issues:
                lines.append(f"- {issue}")
        lines.append("")

    lines.append(f"**Tickers verified:** {', '.join(tickers)}")
    lines.append("")

    output = "\n".join(lines)
    OUTPUT_PATH.write_text(output, encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
