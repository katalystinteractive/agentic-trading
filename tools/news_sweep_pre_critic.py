#!/usr/bin/env python3
"""News Sweep Pre-Critic — mechanical verification for Phase 3.

Reads news-sweep-raw.md, news-sweep-report.md, and portfolio.json.
Runs 5 verification checks and writes news-sweep-pre-critic.md with
findings for the LLM critic.

Usage: python3 tools/news_sweep_pre_critic.py
"""
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

# Same-directory imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
from news_sweep_pre_analyst import parse_raw_data, get_pending_orders, detect_risk_flags
from news_sweep_collector import split_table_row

ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = ROOT / "news-sweep-raw.md"
REPORT_PATH = ROOT / "news-sweep-report.md"
PORTFOLIO_PATH = ROOT / "portfolio.json"
OUTPUT_PATH = ROOT / "news-sweep-pre-critic.md"


# ---------------------------------------------------------------------------
# Input Validation
# ---------------------------------------------------------------------------

def validate_inputs():
    """Load all 3 input files. Returns (raw_text, report_text, portfolio) or exits."""
    if not RAW_PATH.exists():
        print(f"*Error: {RAW_PATH.name} not found*")
        sys.exit(1)
    raw_text = RAW_PATH.read_text(encoding="utf-8")

    if not REPORT_PATH.exists():
        print(f"*Error: {REPORT_PATH.name} not found — analyst phase must complete first*")
        sys.exit(1)
    report_text = REPORT_PATH.read_text(encoding="utf-8")

    if not PORTFOLIO_PATH.exists():
        print(f"*Error: {PORTFOLIO_PATH.name} not found*")
        sys.exit(1)
    try:
        portfolio = json.loads(PORTFOLIO_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"*Error: {PORTFOLIO_PATH.name} malformed JSON: {e}*")
        sys.exit(1)

    return raw_text, report_text, portfolio


# ---------------------------------------------------------------------------
# Report Parsing
# ---------------------------------------------------------------------------

def _parse_report_heatmap(lines):
    """Parse heatmap tables from the report, handling tier sub-headers.

    Returns list of dicts with keys: ticker, tier, current_price, overall_sentiment,
    avg_score, pos_pct, neg_pct, top_catalyst.
    """
    rows = []
    in_section = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Sentiment Heatmap"):
            in_section = True
            continue
        if in_section and stripped.startswith("## ") and not stripped.startswith("## Sentiment"):
            break
        if not in_section:
            continue
        # Skip sub-headers and repeated header/alignment rows
        if stripped.startswith("###"):
            continue
        if stripped.startswith("| Ticker"):
            continue
        if stripped.startswith("| :"):
            continue
        if not stripped.startswith("|"):
            continue

        cols = split_table_row(stripped)
        if len(cols) < 8:
            continue

        ticker = cols[0].strip()
        tier_str = cols[1].strip()
        price_str = cols[2].strip().replace("$", "").replace(",", "")
        overall = cols[3].strip()
        avg_str = cols[4].strip()
        pos_str = cols[5].strip().replace("%", "")
        neg_str = cols[6].strip().replace("%", "")
        top_cat = cols[7].strip()

        try:
            tier = int(tier_str)
        except ValueError:
            tier = 0

        try:
            current_price = float(price_str)
        except ValueError:
            current_price = None

        try:
            avg_score = float(avg_str)
        except ValueError:
            avg_score = None

        try:
            pos_pct = int(pos_str) if pos_str != "N/A" else None
        except ValueError:
            pos_pct = None

        try:
            neg_pct = int(neg_str) if neg_str != "N/A" else None
        except ValueError:
            neg_pct = None

        rows.append({
            "ticker": ticker,
            "tier": tier,
            "current_price": current_price,
            "overall_sentiment": overall,
            "avg_score": avg_score,
            "pos_pct": pos_pct,
            "neg_pct": neg_pct,
            "top_catalyst": top_cat,
        })

    return rows


def _parse_distribution(lines):
    """Parse distribution line from report. Returns dict or None."""
    for line in lines:
        m = re.search(
            r'\*\*Distribution:\*\*\s*(\d+)\s*Bullish\s*/\s*(\d+)\s*Neutral\s*/\s*(\d+)\s*Bearish\s*/\s*(\d+)\s*No Data',
            line
        )
        if m:
            return {
                "bullish": int(m.group(1)),
                "neutral": int(m.group(2)),
                "bearish": int(m.group(3)),
                "no_data": int(m.group(4)),
            }
    return None


def _parse_risk_flags_table(lines):
    """Parse risk flags table from report. Returns list of dicts."""
    flags = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Risk Flags"):
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if not in_section:
            continue
        if stripped.startswith("### "):
            break  # Stop at Flag Detail subsection
        if not stripped.startswith("|") or stripped.startswith("| #") or stripped.startswith("| :"):
            continue

        cols = split_table_row(stripped)
        if len(cols) >= 4:
            try:
                flag_num = int(cols[0].strip())
            except ValueError:
                continue
            flags.append({
                "num": flag_num,
                "type": cols[1].strip(),
                "ticker": cols[2].strip(),
                "finding": cols[3].strip(),
            })
    return flags


def _count_flag_details(lines):
    """Count **Flag N** pattern occurrences in the report."""
    count = 0
    for line in lines:
        if re.search(r'\*\*Flag\s+\d+', line):
            count += 1
    return count


def _parse_themes(lines):
    """Parse cross-ticker themes from report.

    Returns list of dicts with name, tickers, direction, urgency.
    """
    themes = []
    in_section = False
    current_theme = None

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Cross-Ticker Themes"):
            in_section = True
            continue
        if in_section and stripped.startswith("## ") and not stripped.startswith("## Cross"):
            break
        if not in_section:
            continue

        # Theme header
        if stripped.startswith("### "):
            if current_theme:
                themes.append(current_theme)
            current_theme = {"name": stripped[4:].strip(), "tickers": [], "direction": "", "urgency": ""}
            continue

        if current_theme and stripped.startswith("**Tickers:**"):
            # Parse: **Tickers:** A, B, C | **Direction:** Mixed | **Urgency:** High
            ticker_match = re.search(r'\*\*Tickers:\*\*\s*([^|]+)', stripped)
            if ticker_match:
                tickers_str = ticker_match.group(1).strip()
                current_theme["tickers"] = [t.strip() for t in tickers_str.split(",")]

            dir_match = re.search(r'\*\*Direction:\*\*\s*(\w+)', stripped)
            if dir_match:
                current_theme["direction"] = dir_match.group(1).strip()

            urg_match = re.search(r'\*\*Urgency:\*\*\s*(\w+)', stripped)
            if urg_match:
                current_theme["urgency"] = urg_match.group(1).strip()

    if current_theme:
        themes.append(current_theme)

    return themes


def _parse_recommendations(lines):
    """Parse numbered recommendation list from report.

    Returns list of dicts with category, ticker, finding.
    """
    recs = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Actionable Recommendations"):
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if not in_section:
            continue

        # Match: N. **Category** — Ticker: finding
        m = re.match(r'\d+\.\s*\*\*([^*]+)\*\*\s*[—–-]+\s*([A-Z,\s]+?):\s*(.+)', stripped)
        if m:
            recs.append({
                "category": m.group(1).strip(),
                "ticker": m.group(2).strip(),
                "finding": m.group(3).strip(),
            })

    return recs


def _parse_metadata(lines):
    """Extract Tickers Analyzed from Sweep Metadata table."""
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Sweep Metadata"):
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if not in_section:
            continue
        if not stripped.startswith("|"):
            continue
        cols = split_table_row(stripped)
        if len(cols) >= 2 and cols[0].strip() == "Tickers Analyzed":
            try:
                return int(cols[1].strip())
            except ValueError:
                return None
    return None


def parse_report(report_text):
    """Parse analyst report into structured dict."""
    lines = report_text.split("\n")
    return {
        "heatmap": _parse_report_heatmap(lines),
        "distribution": _parse_distribution(lines),
        "risk_flags": _parse_risk_flags_table(lines),
        "flag_detail_count": _count_flag_details(lines),
        "themes": _parse_themes(lines),
        "recommendations": _parse_recommendations(lines),
        "tickers_analyzed": _parse_metadata(lines),
    }


# ---------------------------------------------------------------------------
# Check 1: Sentiment Accuracy
# ---------------------------------------------------------------------------

def check_sentiment_accuracy(raw_data, report):
    """Cross-reference every heatmap row against raw data.

    Returns dict with status, issues (Critical), notes (Minor).
    """
    issues = []
    notes = []
    pc_lookup = {pc["ticker"]: pc for pc in raw_data["portfolio_context"]}

    # Build raw sentiment lookup
    raw_sentiment = {}
    for ticker, data in raw_data["tickers"].items():
        if data["no_news"] or data["failure"] or data["sentiment"] is None:
            raw_sentiment[ticker] = None
        else:
            # Top catalyst
            top_cat = "\u2014"
            if data["catalysts"]:
                sorted_cats = sorted(data["catalysts"], key=lambda c: (-c["count"], c["category"]))
                top_cat = sorted_cats[0]["category"]
            raw_sentiment[ticker] = {
                "overall": data["sentiment"]["overall_sentiment"],
                "avg_score": data["sentiment"]["avg_score"],
                "pos_pct": data["sentiment"]["positive_pct"],
                "neg_pct": data["sentiment"]["negative_pct"],
                "top_catalyst": top_cat,
            }

    for row in report["heatmap"]:
        ticker = row["ticker"]
        pc = pc_lookup.get(ticker, {})
        raw = raw_sentiment.get(ticker)
        raw_tier = pc.get("tier")

        # Check tier
        if raw_tier is not None and row["tier"] != raw_tier:
            issues.append({
                "ticker": ticker, "field": "Tier",
                "raw": str(raw_tier), "report": str(row["tier"]),
                "severity": "Critical",
            })

        # Check current price
        raw_price = pc.get("current_price")
        if raw_price is not None and row["current_price"] is not None:
            if abs(raw_price - row["current_price"]) > 0.01:
                issues.append({
                    "ticker": ticker, "field": "Current Price",
                    "raw": f"${raw_price:.2f}", "report": f"${row['current_price']:.2f}",
                    "severity": "Critical",
                })

        # N/A handling
        if raw is None:
            if row["overall_sentiment"] != "N/A":
                issues.append({
                    "ticker": ticker, "field": "Overall Sentiment",
                    "raw": "N/A (no data)", "report": row["overall_sentiment"],
                    "severity": "Critical",
                })
            continue
        else:
            if row["overall_sentiment"] == "N/A":
                issues.append({
                    "ticker": ticker, "field": "Overall Sentiment",
                    "raw": raw["overall"], "report": "N/A (false N/A)",
                    "severity": "Critical",
                })
                continue

        # Check sentiment fields
        if row["overall_sentiment"] != raw["overall"]:
            issues.append({
                "ticker": ticker, "field": "Overall Sentiment",
                "raw": raw["overall"], "report": row["overall_sentiment"],
                "severity": "Critical",
            })

        if row["avg_score"] is not None and abs(row["avg_score"] - raw["avg_score"]) > 0.005:
            issues.append({
                "ticker": ticker, "field": "Avg Score",
                "raw": f"{raw['avg_score']:+.3f}", "report": f"{row['avg_score']:+.3f}",
                "severity": "Critical",
            })

        if row["pos_pct"] is not None and row["pos_pct"] != raw["pos_pct"]:
            issues.append({
                "ticker": ticker, "field": "Pos%",
                "raw": f"{raw['pos_pct']}%", "report": f"{row['pos_pct']}%",
                "severity": "Critical",
            })

        if row["neg_pct"] is not None and row["neg_pct"] != raw["neg_pct"]:
            issues.append({
                "ticker": ticker, "field": "Neg%",
                "raw": f"{raw['neg_pct']}%", "report": f"{row['neg_pct']}%",
                "severity": "Critical",
            })

        # Top Catalyst: lenient — raw category name must appear as case-insensitive substring
        if raw["top_catalyst"] != "\u2014":
            if raw["top_catalyst"].lower() not in row["top_catalyst"].lower():
                notes.append({
                    "ticker": ticker, "field": "Top Catalyst",
                    "raw": raw["top_catalyst"], "report": row["top_catalyst"],
                    "severity": "Minor",
                })

    # Check sort order (ascending avg_score within tier)
    prev_tier = 0
    prev_score = float('-inf')
    for row in report["heatmap"]:
        if row["tier"] < prev_tier:
            issues.append({
                "ticker": row["ticker"], "field": "Sort Order",
                "raw": f"Tier {row['tier']} after Tier {prev_tier}",
                "report": "Wrong tier order",
                "severity": "Critical",
            })
        if row["tier"] == prev_tier:
            score = row["avg_score"] if row["avg_score"] is not None else float('inf')
            if score < prev_score - 0.001:  # Small tolerance for floating point
                notes.append({
                    "ticker": row["ticker"], "field": "Sort Order",
                    "raw": f"Score {score:+.3f} < prev {prev_score:+.3f}",
                    "report": "Not ascending within tier",
                    "severity": "Minor",
                })
        if row["tier"] > prev_tier:
            prev_score = float('-inf')
        prev_tier = row["tier"]
        prev_score = row["avg_score"] if row["avg_score"] is not None else float('inf')

    # Check distribution arithmetic
    if report["distribution"]:
        dist = report["distribution"]
        total = dist["bullish"] + dist["neutral"] + dist["bearish"] + dist["no_data"]
        expected = raw_data["sweep_summary"]["tickers_swept"]
        if total != expected:
            issues.append({
                "ticker": "ALL", "field": "Distribution Total",
                "raw": str(expected), "report": str(total),
                "severity": "Critical",
            })

    status = "FAIL" if issues else "PASS"
    return {"status": status, "issues": issues, "notes": notes}


# ---------------------------------------------------------------------------
# Check 2: Conflict Classification
# ---------------------------------------------------------------------------

def check_conflict_classification(raw_data, report, pending_orders):
    """Verify flags and detect missing/extra flags.

    Returns dict with status, issues, notes.
    """
    issues = []
    notes = []

    # Run the same detection as pre-analyst
    expected_flags = detect_risk_flags(raw_data, pending_orders)

    report_flags = report["risk_flags"]

    # Count-based comparison to handle duplicate (type, ticker) pairs
    # (e.g., multiple Type C flags for the same ticker with different SELL orders)
    expected_counts = Counter((f["type"], f["ticker"]) for f in expected_flags)
    report_counts = Counter((f["type"], f["ticker"]) for f in report_flags)

    # Note: Type E flags may be filtered by LLM for imminence.
    # Only flag missing non-E types as Critical. Missing E types are noted as Minor.
    for (ftype, ticker), count in sorted(expected_counts.items()):
        missing_count = count - report_counts.get((ftype, ticker), 0)
        for _ in range(missing_count):
            if ftype == "E":
                notes.append({
                    "ticker": ticker,
                    "detail": f"Missing Type {ftype} flag — may have been filtered by LLM imminence check",
                    "severity": "Minor",
                })
            else:
                issues.append({
                    "ticker": ticker,
                    "detail": f"Missing Type {ftype} flag — condition met in raw data but not flagged",
                    "severity": "Critical",
                })

    for (ftype, ticker), count in sorted(report_counts.items()):
        extra_count = count - expected_counts.get((ftype, ticker), 0)
        for _ in range(extra_count):
            issues.append({
                "ticker": ticker,
                "detail": f"Extra Type {ftype} flag — condition NOT met in raw data",
                "severity": "Critical",
            })

    # Verify Type C percentage arithmetic
    for rf in report_flags:
        if rf["type"] != "C":
            continue
        # Try to extract stated percentage from finding
        pct_match = re.search(r'(\d+\.?\d*)%\s*of\s*target', rf["finding"])
        if not pct_match:
            continue
        stated_pct = float(pct_match.group(1))
        # Find the closest matching expected C flag for this ticker
        expected_c = [f for f in expected_flags
                      if f["type"] == "C" and f["ticker"] == rf["ticker"]
                      and "pct_of_target" in f]
        if expected_c:
            # Match against the expected flag with the closest percentage
            closest = min(expected_c, key=lambda f: abs(f["pct_of_target"] - stated_pct))
            if abs(stated_pct - closest["pct_of_target"]) > 0.5:
                issues.append({
                    "ticker": rf["ticker"],
                    "detail": (f"Type C percentage: stated {stated_pct:.1f}% "
                               f"vs actual {closest['pct_of_target']:.1f}%"),
                    "severity": "Critical",
                })

    # Check flag detail count matches
    if report["flag_detail_count"] != len(report_flags):
        notes.append({
            "ticker": "ALL",
            "detail": (f"Flag Detail count ({report['flag_detail_count']}) != "
                       f"Risk Flags table rows ({len(report_flags)})"),
            "severity": "Minor",
        })

    status = "FAIL" if issues else "PASS"
    return {"status": status, "issues": issues, "notes": notes}


# ---------------------------------------------------------------------------
# Check 3: Theme Validity
# ---------------------------------------------------------------------------

def check_theme_validity(raw_data, report):
    """Verify theme mechanical aspects: min count, ticker existence, catalyst basis.

    Returns dict with status, issues, notes.
    """
    issues = []
    notes = []

    raw_tickers = set(raw_data["tickers"].keys())

    for theme in report["themes"]:
        name = theme["name"]
        tickers = theme["tickers"]

        # Min 2 tickers
        if len(tickers) < 2:
            issues.append({
                "theme": name,
                "detail": f"Only {len(tickers)} ticker(s) — minimum is 2",
                "severity": "Critical",
            })

        # All tickers exist in raw data
        for t in tickers:
            if t not in raw_tickers:
                issues.append({
                    "theme": name,
                    "detail": f"Ticker {t} not in raw data — may be fabricated",
                    "severity": "Critical",
                })

        # Note: headline basis is qualitative — left for LLM critic
        notes.append({
            "theme": name,
            "detail": f"{len(tickers)} tickers — headline basis requires qualitative assessment",
            "severity": "Info",
        })

    status = "FAIL" if issues else "PASS"
    return {"status": status, "issues": issues, "notes": notes}


# ---------------------------------------------------------------------------
# Check 4: Recommendation Coverage
# ---------------------------------------------------------------------------

def check_recommendation_coverage(report):
    """Verify flagged tickers are in recommendations and priority is correct.

    Returns dict with status, issues, notes.
    """
    issues = []
    notes = []

    # Collect all flagged tickers
    flagged_tickers = set()
    for f in report["risk_flags"]:
        flagged_tickers.add(f["ticker"])

    # Collect all tickers in recommendations
    rec_tickers = set()
    for r in report["recommendations"]:
        # Handle comma-separated tickers
        for t in r["ticker"].split(","):
            rec_tickers.add(t.strip())

    # Check coverage
    missing = flagged_tickers - rec_tickers
    for t in sorted(missing):
        # Type E flags may be dropped by imminence filtering — check
        flag_types = {f["type"] for f in report["risk_flags"] if f["ticker"] == t}
        if flag_types == {"E"}:
            notes.append({
                "ticker": t,
                "detail": "Flagged (Type E only) but not in recommendations — may be filtered by imminence",
                "severity": "Minor",
            })
        else:
            issues.append({
                "ticker": t,
                "detail": f"Flagged ({', '.join(sorted(flag_types))}) but not in any recommendation",
                "severity": "Critical",
            })

    # Check priority ordering
    category_priority = {
        "Immediate Review": 0,
        "Earnings Gate": 1,
        "Earnings Gates": 1,
        "Dilution Risk": 2,
        "Pending Order Review": 3,
        "Positive Momentum": 4,
        "Theme Awareness": 5,
    }
    prev_priority = -1
    for r in report["recommendations"]:
        cat = r["category"]
        priority = category_priority.get(cat, 99)
        if priority < prev_priority:
            notes.append({
                "ticker": r["ticker"],
                "detail": f"'{cat}' after higher-priority category — ordering issue",
                "severity": "Minor",
            })
        prev_priority = priority

    status = "FAIL" if issues else "PASS"
    return {"status": status, "issues": issues, "notes": notes}


# ---------------------------------------------------------------------------
# Check 5: Report Consistency
# ---------------------------------------------------------------------------

def check_report_consistency(raw_data, report):
    """Verify ticker count, date, no missing/extra tickers.

    Returns dict with status, issues, notes.
    """
    issues = []
    notes = []

    raw_tickers = set(raw_data["tickers"].keys())
    heatmap_tickers = {r["ticker"] for r in report["heatmap"]}
    expected_count = raw_data["sweep_summary"]["tickers_swept"]

    # Ticker count in metadata
    if report["tickers_analyzed"] is not None:
        if report["tickers_analyzed"] != expected_count:
            issues.append({
                "field": "Tickers Analyzed",
                "raw": str(expected_count),
                "report": str(report["tickers_analyzed"]),
                "severity": "Critical",
            })

    # Heatmap row count
    if len(report["heatmap"]) != expected_count:
        issues.append({
            "field": "Heatmap Rows",
            "raw": str(expected_count),
            "report": str(len(report["heatmap"])),
            "severity": "Critical",
        })

    # Missing tickers
    missing = raw_tickers - heatmap_tickers
    for t in sorted(missing):
        issues.append({
            "field": "Missing Ticker",
            "raw": t,
            "report": "Not in heatmap",
            "severity": "Critical",
        })

    # Extra tickers
    extra = heatmap_tickers - raw_tickers
    for t in sorted(extra):
        issues.append({
            "field": "Extra Ticker",
            "raw": "Not in raw data",
            "report": t,
            "severity": "Critical",
        })

    status = "FAIL" if issues else "PASS"
    return {"status": status, "issues": issues, "notes": notes}


# ---------------------------------------------------------------------------
# Report Builder
# ---------------------------------------------------------------------------

def build_report(checks):
    """Assemble news-sweep-pre-critic.md from check results."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = []

    lines.append("# News Sweep Pre-Critic — Mechanical Verification")
    lines.append(f"*Generated: {now} | Tool: news_sweep_pre_critic.py*")
    lines.append("")

    # --- Verification Summary ---
    lines.append("## Verification Summary")
    lines.append("| Check | Result | Details |")
    lines.append("| :--- | :--- | :--- |")

    check_names = [
        ("Sentiment Accuracy", "sentiment"),
        ("Conflict Classification", "conflicts"),
        ("Theme Validity", "themes"),
        ("Recommendation Coverage", "recommendations"),
        ("Report Consistency", "consistency"),
    ]
    for name, key in check_names:
        check = checks[key]
        issue_count = len(check["issues"])
        note_count = len(check["notes"])
        detail = f"{issue_count} critical"
        if note_count:
            detail += f", {note_count} minor/info"
        lines.append(f"| {name} | {check['status']} | {detail} |")
    lines.append("")

    # --- Sentiment Discrepancies ---
    lines.append("## Sentiment Discrepancies")
    sent_check = checks["sentiment"]
    if sent_check["issues"] or sent_check["notes"]:
        lines.append("| Ticker | Field | Raw | Report | Severity |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for issue in sent_check["issues"]:
            lines.append(f"| {issue['ticker']} | {issue['field']} | {issue['raw']} | {issue['report']} | {issue['severity']} |")
        for note in sent_check["notes"]:
            lines.append(f"| {note['ticker']} | {note['field']} | {note['raw']} | {note['report']} | {note['severity']} |")
    else:
        lines.append("No discrepancies found.")
    lines.append("")

    # --- Conflict Errors ---
    lines.append("## Conflict Errors")
    conflict_check = checks["conflicts"]
    if conflict_check["issues"] or conflict_check["notes"]:
        for item in conflict_check["issues"] + conflict_check["notes"]:
            severity = item.get("severity", "")
            lines.append(f"- **{severity}** — {item.get('ticker', 'ALL')}: {item['detail']}")
    else:
        lines.append("No conflict errors found.")
    lines.append("")

    # --- Theme Issues ---
    lines.append("## Theme Issues")
    theme_check = checks["themes"]
    if theme_check["issues"]:
        for item in theme_check["issues"]:
            lines.append(f"- **{item['severity']}** — {item['theme']}: {item['detail']}")
    else:
        lines.append("No mechanical theme issues found.")
    if theme_check["notes"]:
        lines.append("")
        lines.append("**Notes (for qualitative review):**")
        for note in theme_check["notes"]:
            lines.append(f"- {note['theme']}: {note['detail']}")
    lines.append("")

    # --- Recommendation Gaps ---
    lines.append("## Recommendation Gaps")
    rec_check = checks["recommendations"]
    if rec_check["issues"] or rec_check["notes"]:
        for item in rec_check["issues"] + rec_check["notes"]:
            severity = item.get("severity", "")
            lines.append(f"- **{severity}** — {item.get('ticker', 'ALL')}: {item['detail']}")
    else:
        lines.append("No recommendation gaps found.")
    lines.append("")

    # --- Consistency Issues ---
    lines.append("## Consistency Issues")
    cons_check = checks["consistency"]
    if cons_check["issues"]:
        for item in cons_check["issues"]:
            lines.append(f"- **{item['severity']}** — {item['field']}: raw={item['raw']}, report={item['report']}")
    else:
        lines.append("No consistency issues found.")
    lines.append("")

    # --- Qualitative Focus Areas ---
    lines.append("## For Critic: Qualitative Focus Areas")
    lines.append("1. **Theme headline basis:** Do the headlines actually support each theme narrative? "
                 "Mechanical PASS covers structure only — assess substance.")
    lines.append("2. **Recommendation quality:** Are next steps actionable and grounded in data? "
                 "No fabricated earnings dates, prices, or percentages.")
    lines.append("3. **Executive Summary consistency:** Does it contradict the heatmap distribution or risk flags?")
    lines.append("4. **Earnings imminence filtering:** Were Type E flags appropriately filtered? "
                 "Only imminent earnings (within 14 days) should remain in the final report.")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("News Sweep Pre-Critic")
    print("=" * 40)

    raw_text, report_text, portfolio = validate_inputs()
    raw_data = parse_raw_data(raw_text)
    report = parse_report(report_text)
    pending_orders = get_pending_orders(portfolio)

    print(f"Raw: {raw_data['sweep_summary']['tickers_swept']} tickers")
    print(f"Report: {len(report['heatmap'])} heatmap rows, "
          f"{len(report['risk_flags'])} flags, "
          f"{len(report['themes'])} themes, "
          f"{len(report['recommendations'])} recommendations")

    checks = {
        "sentiment": check_sentiment_accuracy(raw_data, report),
        "conflicts": check_conflict_classification(raw_data, report, pending_orders),
        "themes": check_theme_validity(raw_data, report),
        "recommendations": check_recommendation_coverage(report),
        "consistency": check_report_consistency(raw_data, report),
    }

    output = build_report(checks)
    OUTPUT_PATH.write_text(output, encoding="utf-8")

    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"\nWrote {OUTPUT_PATH.name} ({size_kb:.1f} KB)")

    for name, key in [
        ("Sentiment", "sentiment"),
        ("Conflicts", "conflicts"),
        ("Themes", "themes"),
        ("Recommendations", "recommendations"),
        ("Consistency", "consistency"),
    ]:
        check = checks[key]
        print(f"  {name}: {check['status']} "
              f"({len(check['issues'])} critical, {len(check['notes'])} notes)")


if __name__ == "__main__":
    main()
