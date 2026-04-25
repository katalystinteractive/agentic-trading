#!/usr/bin/env python3
"""Status Pre-Critic — Phase 3 mechanical verification for the status workflow.

Reads status-raw.md, status-report.md, and portfolio.json. Runs 6 verification
checks and writes status-pre-critic.md for the LLM critic to add qualitative
assessment.

Usage: python3 tools/status_pre_critic.py
"""

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

# Same-directory imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
from status_pre_analyst import (
    parse_raw_data, extract_report_date, get_strategy_label,
    split_table_row, compute_sell_projections,
)

ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = ROOT / "status-raw.md"
REPORT_PATH = ROOT / "status-report.md"
PORTFOLIO_PATH = ROOT / "portfolio.json"
OUTPUT_PATH = ROOT / "status-pre-critic.md"


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
        print(f"*Error: {REPORT_PATH.name} not found — analyst phase must complete first*", file=sys.stderr)
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
# Report Parsing
# ---------------------------------------------------------------------------

def parse_report(report_text):
    """Master parser for status-report.md (LLM-generated).

    Returns dict with keys: heat_map, total_pl, fill_alerts, positions,
    watchlist, capital, actionable.
    """
    lines = report_text.split("\n")
    result = {
        "heat_map": [],
        "total_pl": None,
        "total_deployed": None,
        "fill_alerts": [],
        "positions": {},
        "watchlist": [],
        "capital": {},
        "actionable": [],
    }

    # Split by ## headers
    sections = {}
    current = None
    current_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") and not stripped.startswith("### "):
            if current is not None:
                sections[current] = current_lines
            current = stripped[3:].strip()
            current_lines = []
        elif current is not None:
            current_lines.append(line)
    if current is not None:
        sections[current] = current_lines

    # Parse Heat Map
    hm_section = sections.get("Portfolio Heat Map", [])
    result["heat_map"] = _parse_report_heat_map(hm_section)
    result["total_pl"], result["total_deployed"] = _parse_report_total_pl(hm_section)

    # Parse Fill Alerts
    fa_section = sections.get("Fill Alerts", [])
    result["fill_alerts"] = _parse_report_fill_alerts(fa_section)

    # Parse Per-Position Detail
    pd_section = sections.get("Per-Position Detail", [])
    result["positions"] = _parse_report_positions(pd_section)

    # Parse Watchlist
    wl_section = sections.get("Watchlist", [])
    result["watchlist"] = _parse_report_watchlist(wl_section)

    # Parse Capital Summary
    cs_section = sections.get("Capital Summary", [])
    result["capital"] = _parse_report_capital(cs_section)

    # Parse Actionable Items
    ai_section = sections.get("Actionable Items", [])
    result["actionable"] = _parse_report_actionable(ai_section)

    return result


def _parse_report_heat_map(lines):
    """Parse 7-column heat map table."""
    rows = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("| Ticker") or stripped.startswith("| :"):
            continue
        if "**" in stripped:  # Total row
            continue
        cols = split_table_row(stripped)
        if len(cols) < 7:
            continue
        try:
            pl_str = cols[4].replace("$", "").replace(",", "").replace("+", "")
            pct_str = cols[5].replace("%", "").replace("+", "")
            rows.append({
                "ticker": cols[0],
                "shares": int(float(cols[1])),
                "avg_cost": float(cols[2].replace("$", "").replace(",", "")),
                "current": float(cols[3].replace("$", "").replace(",", "")),
                "pl_dollar": float(pl_str),
                "pl_pct": float(pct_str),
                "strategy": cols[6],
            })
        except (ValueError, IndexError):
            continue
    return rows


def _parse_report_total_pl(lines):
    """Parse portfolio total P/L from bold line. Returns (total_pl, total_deployed)."""
    total_pl = None
    total_deployed = None
    for line in lines:
        stripped = line.strip()
        # Match: **Portfolio total unrealized P/L: -$308.32** across 9 positions ($2,126.60 deployed)
        m = re.search(r"P/L:\s*([+-]?\$?[\d,.]+)\*?\*?\s*across\s+\d+\s+positions\s*\(\$?([\d,.]+)\s*deployed\)", stripped)
        if m:
            pl_str = m.group(1).replace("$", "").replace(",", "").replace("+", "")
            total_pl = float(pl_str)
            dep_str = m.group(2).replace(",", "")
            total_deployed = float(dep_str)
            break
        # Try alternate patterns
        m2 = re.search(r"total.*P/L.*?(-?\$?[\d,.]+)", stripped)
        if m2 and total_pl is None:
            pl_str = m2.group(1).replace("$", "").replace(",", "").replace("+", "")
            try:
                total_pl = float(pl_str)
            except ValueError:
                pass
    return total_pl, total_deployed


def _parse_report_fill_alerts(lines):
    """Parse fill alert subsections. Returns list of dicts."""
    alerts = []
    current_alert = None

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### "):
            if current_alert:
                alerts.append(current_alert)
            current_alert = {"header": stripped[4:], "fields": {}}
        elif current_alert and stripped.startswith("|") and not stripped.startswith("| Field") and not stripped.startswith("| :"):
            cols = split_table_row(stripped)
            if len(cols) >= 2:
                current_alert["fields"][cols[0]] = cols[1]

    if current_alert:
        alerts.append(current_alert)

    # Check for "No fill alerts"
    if not alerts:
        text = "\n".join(lines)
        if "no fill alert" in text.lower():
            return []

    return alerts


def _parse_report_positions(lines):
    """Parse Per-Position Detail sections. Returns dict of ticker -> data."""
    positions = {}
    current_ticker = None
    current_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### "):
            if current_ticker:
                positions[current_ticker] = _parse_single_position(current_lines)
            # Extract ticker from "### IONQ — Recovery — -28.1%"
            parts = stripped[4:].split("—")
            current_ticker = parts[0].strip() if parts else stripped[4:].strip()
            current_lines = []
        elif current_ticker is not None:
            current_lines.append(line)

    if current_ticker:
        positions[current_ticker] = _parse_single_position(current_lines)

    return positions


def _parse_single_position(lines):
    """Parse a single position's detail sections."""
    result = {
        "current_avg": {},
        "pending_orders": [],
        "wick_levels": [],
        "sell_projection": {},
        "context_flags": [],
        "has_section": {1: False, 2: False, 3: False, 4: False, 5: False, 6: False},
    }

    current_section = None
    section_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#### "):
            if current_section:
                _process_position_section(result, current_section, section_lines)
            # Extract section number
            m = re.match(r"####\s+(\d+)\.", stripped)
            current_section = int(m.group(1)) if m else None
            section_lines = []
        elif current_section is not None:
            section_lines.append(line)

    if current_section:
        _process_position_section(result, current_section, section_lines)

    return result


def _process_position_section(result, section_num, lines):
    """Process a numbered section within a position."""
    result["has_section"][section_num] = True

    if section_num == 2:  # Current Average
        for line in lines:
            stripped = line.strip()
            if not stripped.startswith("|") or stripped.startswith("| Metric") or stripped.startswith("| :"):
                continue
            cols = split_table_row(stripped)
            if len(cols) >= 2:
                key = cols[0].strip()
                val = cols[1].strip()
                result["current_avg"][key] = val

    elif section_num == 5:  # Projected Sell Levels
        for line in lines:
            stripped = line.strip()
            if not stripped.startswith("|") or stripped.startswith("| Target") or stripped.startswith("| :"):
                continue
            cols = split_table_row(stripped)
            if len(cols) >= 3:
                try:
                    target = float(cols[0].replace("$", "").replace(",", ""))
                    from_current = float(cols[1].replace("%", "").replace("+", ""))
                    from_avg = float(cols[2].replace("%", "").replace("+", ""))
                    result["sell_projection"] = {
                        "target": target,
                        "from_current": from_current,
                        "from_avg": from_avg,
                    }
                except ValueError:
                    pass


def _parse_report_watchlist(lines):
    """Parse Watchlist table. Handles N/A in nearest-buy columns."""
    rows = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("| Ticker") or stripped.startswith("| :"):
            continue
        cols = split_table_row(stripped)
        if len(cols) < 6:
            continue
        try:
            b1_price = None
            dist_to_b1 = None
            b1_str = cols[3].replace("$", "").replace(",", "").replace("*", "")
            if b1_str.strip() != "N/A":
                try:
                    b1_price = float(b1_str)
                except ValueError:
                    pass
            dist_str = cols[4].replace("%", "").replace("+", "").replace("*", "")
            if dist_str.strip() != "N/A":
                try:
                    dist_to_b1 = float(dist_str)
                except ValueError:
                    pass

            rows.append({
                "ticker": cols[0],
                "price": float(cols[1].replace("$", "").replace(",", "")),
                "day_pct": cols[2],
                "b1_price": b1_price,
                "dist_to_b1": dist_to_b1,
                "orders_placed": cols[5] if len(cols) > 5 else "0",
            })
        except (ValueError, IndexError):
            continue
    return rows


def _parse_report_capital(lines):
    """Parse Capital Summary tables."""
    result = {"strategy_table": [], "per_position": [], "recovery": []}
    in_strategy = False
    in_per_pos = False
    in_recovery = False

    for line in lines:
        stripped = line.strip()

        if "Strategy" in stripped and "Deployed" in stripped and stripped.startswith("|"):
            in_strategy = True
            in_per_pos = False
            in_recovery = False
            continue
        elif "Ticker" in stripped and "Deployed" in stripped and "Budget" in stripped and stripped.startswith("|"):
            in_strategy = False
            in_per_pos = True
            in_recovery = False
            continue
        elif "Ticker" in stripped and "Deployed" in stripped and "Status" in stripped and stripped.startswith("|"):
            in_strategy = False
            in_per_pos = False
            in_recovery = True
            continue

        if stripped.startswith("| :"):
            continue

        if not stripped.startswith("|"):
            if in_strategy or in_per_pos or in_recovery:
                in_strategy = False
                in_per_pos = False
                in_recovery = False
            continue

        cols = split_table_row(stripped)

        if in_strategy and len(cols) >= 4:
            result["strategy_table"].append({
                "strategy": cols[0],
                "deployed": cols[1],
                "budget": cols[2],
                "utilization": cols[3],
            })
        elif in_per_pos and len(cols) >= 3:
            result["per_position"].append({
                "ticker": cols[0],
                "deployed": cols[1],
            })
        elif in_recovery and len(cols) >= 3:
            result["recovery"].append({
                "ticker": cols[0],
                "deployed": cols[1],
            })

    return result


def _parse_report_actionable(lines):
    """Parse Actionable Items table."""
    rows = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("| #") or stripped.startswith("| :"):
            continue
        cols = split_table_row(stripped)
        if len(cols) >= 4:
            rows.append({
                "num": cols[0],
                "priority": cols[1],
                "item": cols[2],
                "action": cols[3],
            })
    return rows


# ---------------------------------------------------------------------------
# Check Functions
# ---------------------------------------------------------------------------

def check_pl_math(raw_data, report, portfolio):
    """Check 1: P/L Math verification.

    Returns dict with {status, issues, notes}.
    """
    issues = []
    notes = []

    pj_positions = portfolio.get("positions", {})
    raw_price_map = {p["ticker"]: p["current"] for p in raw_data["active_positions"]}

    for row in report["heat_map"]:
        ticker = row["ticker"]
        pj = pj_positions.get(ticker, {})

        # From portfolio.json
        pj_shares = pj.get("shares", 0)
        pj_avg = pj.get("avg_cost", 0)
        expected_deployed = pj_shares * pj_avg

        # From raw data — get current price
        current = raw_price_map.get(ticker)

        if current is None:
            issues.append(f"{ticker}: current price not found in raw data (Critical)")
            continue

        expected_value = pj_shares * current
        expected_pl = expected_value - expected_deployed
        expected_pct = (expected_pl / expected_deployed * 100) if expected_deployed else 0

        # Check report values
        report_pl = row["pl_dollar"]
        report_pct = row["pl_pct"]
        report_deployed = row["shares"] * row["avg_cost"]

        # Deployed check ($0.02 tolerance)
        if abs(report_deployed - expected_deployed) > 0.02:
            issues.append(f"{ticker}: deployed ${report_deployed:.2f} vs expected ${expected_deployed:.2f} (Critical)")

        # P/L $ check ($0.04 tolerance)
        if abs(report_pl - expected_pl) > 0.04:
            issues.append(f"{ticker}: P/L $ {report_pl:.2f} vs expected {expected_pl:.2f} (Critical)")
        elif abs(report_pl - expected_pl) > 0.01:
            notes.append(f"{ticker}: P/L $ rounding {report_pl:.2f} vs {expected_pl:.2f} (Minor)")

        # P/L % check (±0.2%)
        if abs(report_pct - expected_pct) > 0.2:
            issues.append(f"{ticker}: P/L % {report_pct:.1f}% vs expected {expected_pct:.1f}% (Critical)")
        elif abs(report_pct - expected_pct) > 0.05:
            notes.append(f"{ticker}: P/L % rounding {report_pct:.1f}% vs {expected_pct:.1f}% (Minor)")

    # Check total P/L
    if report["total_pl"] is not None:
        expected_total = sum(
            pj_positions.get(row["ticker"], {}).get("shares", 0) *
            (raw_price_map.get(row["ticker"], 0)
             - pj_positions.get(row["ticker"], {}).get("avg_cost", 0))
            for row in report["heat_map"]
        )
        tolerance = 0.02 * len(report["heat_map"])
        if abs(report["total_pl"] - expected_total) > tolerance:
            issues.append(f"Total P/L {report['total_pl']:.2f} vs expected {expected_total:.2f} (Critical)")

    # Cross-check: total_deployed + total_pl ≈ total_current_value
    if report.get("total_deployed") is not None and report.get("total_pl") is not None:
        total_current = sum(
            pj_positions.get(row["ticker"], {}).get("shares", 0) *
            raw_price_map.get(row["ticker"], 0)
            for row in report["heat_map"]
        )
        reported_check = report["total_deployed"] + report["total_pl"]
        tolerance = 0.02 * len(report["heat_map"])
        if abs(reported_check - total_current) > tolerance:
            issues.append(f"Cross-check: deployed+P/L={reported_check:.2f} vs current_value={total_current:.2f} (Critical)")

    critical = [i for i in issues if "Critical" in i]
    status = "FAIL" if critical else "PASS"
    return {"status": status, "issues": issues, "notes": notes}


def check_fill_detection(raw_data, report, portfolio):
    """Check 2: Fill detection verification."""
    issues = []
    notes = []

    # Find all FILLED? markers in raw data
    raw_fills = [o for o in raw_data["pending_orders"] if o.get("filled")]
    report_fills = report.get("fill_alerts", [])

    # Every raw fill should have a corresponding report fill alert
    for rf in raw_fills:
        ticker = rf["ticker"]
        price = rf["price"]
        found = False
        for ra in report_fills:
            header = ra.get("header", "")
            if ticker in header and f"${price:.2f}" in header:
                found = True
                break
            # Also check fields
            order_field = ra.get("fields", {}).get("Order", "")
            if ticker in header and str(price) in order_field:
                found = True
                break
        if not found:
            issues.append(f"Missing fill alert for {ticker} @ ${price:.2f} — raw data has FILLED? marker (Critical)")

    # No false fills (report fill without raw marker)
    for ra in report_fills:
        header = ra.get("header", "")
        # Strip "Potential Fill: " prefix before extracting ticker/price
        clean_header = re.sub(r"^Potential\s+Fill:\s*", "", header)
        m = re.search(r"(\w+)\s+\w+\s+@\s+\$?([\d.]+)", clean_header)
        if m:
            ticker = m.group(1)
            price = float(m.group(2))
            found = False
            for rf in raw_fills:
                if rf["ticker"] == ticker and abs(rf["price"] - price) < 0.02:
                    found = True
                    break
            if not found:
                issues.append(f"False fill alert: {ticker} @ ${price:.2f} — no FILLED? marker in raw (Critical)")

    # Verify fill math (new avg)
    for ra in report_fills:
        fields = ra.get("fields", {})
        # Check if new avg is mentioned
        for key, val in fields.items():
            if "avg" in key.lower():
                # Try to extract and verify
                m = re.search(r"\$?([\d.]+)", val)
                if m:
                    reported_avg = float(m.group(1))
                    # We'd need to compute expected — skip if we can't identify ticker/order
                    notes.append(f"Fill avg reported: ${reported_avg:.2f} — manual verify")

    critical = [i for i in issues if "Critical" in i]
    status = "FAIL" if critical else "PASS"
    return {"status": status, "issues": issues, "notes": notes}


def check_data_consistency(raw_data, report, portfolio):
    """Check 3: Data consistency verification."""
    issues = []
    notes = []

    pj_positions = portfolio.get("positions", {})
    pj_pending = portfolio.get("pending_orders", {})
    pj_watchlist = set(portfolio.get("watchlist", []))

    # Shares & Avg Cost match portfolio.json
    for row in report["heat_map"]:
        ticker = row["ticker"]
        pj = pj_positions.get(ticker, {})
        if row["shares"] != pj.get("shares", 0):
            issues.append(f"{ticker}: shares {row['shares']} vs portfolio.json {pj.get('shares', 0)} (Critical)")
        pj_avg = pj.get("avg_cost", 0)
        if abs(row["avg_cost"] - pj_avg) > 0.01:
            issues.append(f"{ticker}: avg_cost ${row['avg_cost']:.2f} vs portfolio.json ${pj_avg:.2f} (Critical)")

    # Strategy labels
    for row in report["heat_map"]:
        ticker = row["ticker"]
        expected = get_strategy_label(portfolio, ticker)
        reported = row["strategy"]
        if expected.lower() != reported.lower():
            issues.append(f"{ticker}: strategy '{reported}' vs expected '{expected}' (Critical)")

    # Current prices match raw
    raw_price_map = {p["ticker"]: p["current"] for p in raw_data["active_positions"]}
    for row in report["heat_map"]:
        ticker = row["ticker"]
        raw_price = raw_price_map.get(ticker)
        if raw_price and abs(row["current"] - raw_price) > 0.01:
            issues.append(f"{ticker}: current ${row['current']:.2f} vs raw ${raw_price:.2f} (Critical)")

    # All active positions present
    for ticker in pj_positions:
        pj = pj_positions[ticker]
        if isinstance(pj.get("shares"), (int, float)) and pj["shares"] > 0:
            found = any(r["ticker"] == ticker for r in report["heat_map"])
            if not found:
                issues.append(f"{ticker}: active position missing from heat map (Critical)")

    # No extra tickers
    pj_all = set(pj_positions.keys()) | set(pj_pending.keys()) | pj_watchlist
    for row in report["heat_map"]:
        if row["ticker"] not in pj_all:
            issues.append(f"{row['ticker']}: in report but not in portfolio.json (Critical)")

    # Watchlist coverage
    active_tickers = {r["ticker"] for r in report["heat_map"]}
    report_watchlist_tickers = {w["ticker"] for w in report.get("watchlist", [])}
    for ticker in pj_watchlist:
        if ticker not in active_tickers and ticker not in report_watchlist_tickers:
            notes.append(f"{ticker}: on watchlist but not in report watchlist section (Minor)")

    critical = [i for i in issues if "Critical" in i]
    status = "FAIL" if critical else "PASS"
    return {"status": status, "issues": issues, "notes": notes}


def check_ordering(report):
    """Check 4: Sorting & ordering verification."""
    issues = []
    notes = []

    # Heat map sorted by P/L % ascending
    pcts = [r["pl_pct"] for r in report["heat_map"]]
    for i in range(len(pcts) - 1):
        if pcts[i] > pcts[i + 1] + 0.05:  # Small tolerance for rounding
            issues.append(
                f"Heat map not sorted: {report['heat_map'][i]['ticker']} ({pcts[i]:.1f}%) "
                f"before {report['heat_map'][i+1]['ticker']} ({pcts[i+1]:.1f}%) (Critical)"
            )

    # Position Reporting Order (6 sections)
    for ticker, pos_data in report.get("positions", {}).items():
        for sec_num in range(1, 7):
            if not pos_data.get("has_section", {}).get(sec_num, False):
                notes.append(f"{ticker}: missing section {sec_num} (Minor)")

    # Actionable items urgency ranking
    priority_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    last_priority = -1
    for item in report.get("actionable", []):
        p = priority_order.get(item.get("priority", "").upper(), 99)
        if p < last_priority:
            issues.append(f"Actionable items not ranked by urgency: {item.get('priority')} after higher priority (Critical)")
        last_priority = p

    critical = [i for i in issues if "Critical" in i]
    status = "FAIL" if critical else "PASS"
    return {"status": status, "issues": issues, "notes": notes}


def check_context_flags(raw_data, report, portfolio, report_date):
    """Check 5: Context flag arithmetic verification."""
    issues = []
    notes = []

    # Earnings day counts
    for ticker, detail in raw_data["ticker_details"].items():
        earnings = detail.get("structural", {}).get("earnings", {})
        if not earnings.get("exists"):
            continue
        date_str = earnings.get("earnings_date")
        if not date_str:
            continue
        try:
            earnings_date = date.fromisoformat(date_str)
            expected_days = (earnings_date - report_date).days

            # Check if this is an active position
            pj = portfolio.get("positions", {}).get(ticker, {})
            is_active = isinstance(pj.get("shares"), (int, float)) and pj["shares"] > 0

            # Missing EARNINGS GATE when <14 days for active positions
            if expected_days <= 14 and is_active:
                # Check if report mentions earnings gate
                pos_in_report = report.get("positions", {}).get(ticker)
                if not pos_in_report:
                    if ticker in {r["ticker"] for r in report["heat_map"]}:
                        issues.append(f"{ticker}: active position missing from Per-Position Detail (Critical)")
                # Also check actionable items
                actionable_text = " ".join(
                    a.get("item", "") + " " + a.get("action", "")
                    for a in report.get("actionable", [])
                )
                if ticker.lower() not in actionable_text.lower() or "earning" not in actionable_text.lower():
                    notes.append(f"{ticker}: earnings in {expected_days} days — verify EARNINGS GATE flagged")
        except ValueError:
            continue

    # Sell target distances for active positions
    for row in report["heat_map"]:
        ticker = row["ticker"]
        pos_report = report.get("positions", {}).get(ticker, {})
        sell = pos_report.get("sell_projection", {})
        if sell.get("target") is not None:
            target = sell["target"]
            current = row["current"]
            avg_cost = row["avg_cost"]
            expected_from_current = ((target - current) / current * 100) if current else 0
            expected_from_avg = ((target - avg_cost) / avg_cost * 100) if avg_cost else 0

            from_current = sell.get("from_current")
            from_avg = sell.get("from_avg")
            if from_current is not None and abs(from_current - expected_from_current) > 0.2:
                issues.append(
                    f"{ticker}: sell dist from current {from_current:.1f}% vs expected {expected_from_current:.1f}% (Critical)"
                )
            if from_avg is not None and abs(from_avg - expected_from_avg) > 0.2:
                issues.append(
                    f"{ticker}: sell dist from avg {from_avg:.1f}% vs expected {expected_from_avg:.1f}% (Critical)"
                )

    # Watchlist distance to nearest buy — skip N/A entries
    for wl in report.get("watchlist", []):
        if wl.get("b1_price") is None or wl.get("dist_to_b1") is None:
            continue  # N/A — skip validation
        ticker = wl["ticker"]
        price = wl["price"]
        b1 = wl["b1_price"]
        expected_dist = (b1 - price) / price * 100 if price else 0
        reported_dist = wl["dist_to_b1"]
        if abs(reported_dist - expected_dist) > 0.2:
            issues.append(
                f"{ticker}: watchlist Dist to Nearest {reported_dist:.1f}% vs expected {expected_dist:.1f}% (Critical)"
            )

    # Time stops
    for ticker, pj in portfolio.get("positions", {}).items():
        entry_str = pj.get("entry_date", "")
        if not entry_str:
            continue
        if entry_str.startswith("pre-"):
            stripped = entry_str[4:]
            if re.match(r"^\d{4}$", stripped):
                # Inherently exceeded
                pass
            else:
                try:
                    entry_date = date.fromisoformat(stripped)
                    days = (report_date - entry_date).days
                    if days >= 60:
                        notes.append(f"{ticker}: time stop {days} days (entry {entry_str}) — verify flagged")
                except ValueError:
                    pass
        else:
            try:
                entry_date = date.fromisoformat(entry_str)
                days = (report_date - entry_date).days
                if days >= 60:
                    notes.append(f"{ticker}: time stop {days} days — verify flagged")
            except ValueError:
                pass

    critical = [i for i in issues if "Critical" in i]
    status = "FAIL" if critical else "PASS"
    return {"status": status, "issues": issues, "notes": notes}


def check_capital_summary(raw_data, report, portfolio):
    """Check 6: Capital summary verification."""
    issues = []
    notes = []

    pj_positions = portfolio.get("positions", {})

    # Compute expected deployed
    expected_deployed = sum(
        pos.get("shares", 0) * pos.get("avg_cost", 0)
        for pos in pj_positions.values()
        if isinstance(pos.get("shares"), (int, float)) and isinstance(pos.get("avg_cost"), (int, float))
    )

    # Check report total deployed
    if report.get("total_deployed") is not None:
        tolerance = 0.02 * len(pj_positions)
        if abs(report["total_deployed"] - expected_deployed) > tolerance:
            issues.append(
                f"Total deployed ${report['total_deployed']:.2f} vs expected ${expected_deployed:.2f} (Critical)"
            )

    # Strategy breakdown
    surgical_deployed = 0.0
    recovery_deployed = 0.0
    for ticker, pj in pj_positions.items():
        shares = pj.get("shares", 0)
        avg = pj.get("avg_cost", 0)
        if not (isinstance(shares, (int, float)) and isinstance(avg, (int, float))):
            continue
        deployed = shares * avg
        label = get_strategy_label(portfolio, ticker)
        if label == "Surgical":
            surgical_deployed += deployed
        else:
            recovery_deployed += deployed

    # Check strategy table in report
    cap_table = report.get("capital", {}).get("strategy_table", [])
    for row in cap_table:
        strategy_str = row.get("strategy", "")
        deployed_str = row.get("deployed", "")
        try:
            reported = float(deployed_str.replace("$", "").replace(",", "").replace("*", ""))
        except ValueError:
            continue

        if "surgical" in strategy_str.lower():
            if abs(reported - surgical_deployed) > 0.10:
                issues.append(
                    f"Surgical deployed ${reported:.2f} vs expected ${surgical_deployed:.2f} (Critical)"
                )
        elif "recovery" in strategy_str.lower():
            if abs(reported - recovery_deployed) > 0.10:
                issues.append(
                    f"Recovery deployed ${reported:.2f} vs expected ${recovery_deployed:.2f} (Critical)"
                )
        elif "total" in strategy_str.lower() or "**" in strategy_str:
            if abs(reported - expected_deployed) > 0.20:
                issues.append(
                    f"Total deployed ${reported:.2f} vs expected ${expected_deployed:.2f} (Critical)"
                )

    # Velocity/Bounce status
    vel_pos = portfolio.get("velocity_positions", {})
    bnc_pos = portfolio.get("bounce_positions", {})
    if not vel_pos and not bnc_pos:
        # Verify report says "No active velocity/bounce trades" or similar
        pass  # This is a qualitative check

    critical = [i for i in issues if "Critical" in i]
    status = "FAIL" if critical else "PASS"
    return {"status": status, "issues": issues, "notes": notes}


# ---------------------------------------------------------------------------
# Report Builder
# ---------------------------------------------------------------------------

def build_report(checks):
    """Assemble status-pre-critic.md."""
    parts = []

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    parts.append("# Status Pre-Critic — Mechanical Verification")
    parts.append(f"*Generated: {now_str} | Tool: status_pre_critic.py*")
    parts.append("")

    # Verification Summary
    parts.append("## Verification Summary")
    parts.append("")
    parts.append("| Check | Result | Details |")
    parts.append("| :--- | :--- | :--- |")

    check_names = [
        ("P/L Math", "pl_math"),
        ("Fill Detection", "fill_detection"),
        ("Data Consistency", "data_consistency"),
        ("Sorting & Ordering", "ordering"),
        ("Context Flags", "context_flags"),
        ("Capital Summary", "capital_summary"),
    ]

    for label, key in check_names:
        check = checks[key]
        status = check["status"]
        n_issues = len([i for i in check["issues"] if "Critical" in i])
        n_minor = len(check.get("notes", []))
        details = []
        if n_issues:
            details.append(f"{n_issues} critical")
        if n_minor:
            details.append(f"{n_minor} minor")
        if not details:
            details.append("Clean")
        parts.append(f"| {label} | {status} | {', '.join(details)} |")

    parts.append("")

    # Overall verdict
    all_pass = all(checks[key]["status"] == "PASS" for _, key in check_names)
    total_critical = sum(
        len([i for i in checks[key]["issues"] if "Critical" in i])
        for _, key in check_names
    )
    total_minor = sum(len(checks[key].get("notes", [])) for _, key in check_names)

    verdict = "PASS" if all_pass else "ISSUES"
    parts.append(f"**Overall Verdict: {verdict}** — {total_critical} critical, {total_minor} minor")
    parts.append("")
    parts.append("---")
    parts.append("")

    # Detailed sections for each check
    section_titles = {
        "pl_math": "P/L Math Discrepancies",
        "fill_detection": "Fill Detection Issues",
        "data_consistency": "Data Consistency Issues",
        "ordering": "Ordering Issues",
        "context_flags": "Context Flag Issues",
        "capital_summary": "Capital Summary Issues",
    }

    for _, key in check_names:
        title = section_titles[key]
        check = checks[key]
        parts.append(f"## {title}")
        parts.append("")

        if not check["issues"] and not check.get("notes", []):
            clean_msg = title.replace("Issues", "issues").replace("Discrepancies", "discrepancies")
            parts.append(f"No {clean_msg.lower()} found.")
        else:
            if check["issues"]:
                for issue in check["issues"]:
                    severity = "Critical" if "Critical" in issue else "Minor"
                    clean_issue = issue.replace(" (Critical)", "").replace(" (Minor)", "")
                    parts.append(f"- **{severity}:** {clean_issue}")
            if check.get("notes"):
                for note in check["notes"]:
                    clean_note = note.replace(" (Minor)", "")
                    parts.append(f"- *Minor:* {clean_note}")

        parts.append("")

    # Qualitative Focus Areas
    parts.append("---")
    parts.append("")
    parts.append("## For Critic: Qualitative Focus Areas")
    parts.append("")
    parts.append("1. **Context flag narratives** — are they grounded in structural data?")
    parts.append("2. **Actionable items quality** — concrete, broker-actionable?")
    parts.append("3. **Fill scenarios** — reasonable projections?")
    parts.append("4. **Missing qualitative insights** — any overlooked data?")
    parts.append("")

    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Validate and load
    raw_text, report_text, portfolio = validate_inputs()
    report_date = extract_report_date(raw_text)

    print(f"Status Pre-Critic — {report_date.isoformat()}")

    # Parse raw data
    raw_data = parse_raw_data(raw_text)
    print(f"Raw: {len(raw_data['active_positions'])} active, {len(raw_data['pending_orders'])} orders")

    # Parse report
    report = parse_report(report_text)
    print(f"Report: {len(report['heat_map'])} heat map rows, {len(report['fill_alerts'])} fill alerts")

    # Run 6 checks
    checks = {
        "pl_math": check_pl_math(raw_data, report, portfolio),
        "fill_detection": check_fill_detection(raw_data, report, portfolio),
        "data_consistency": check_data_consistency(raw_data, report, portfolio),
        "ordering": check_ordering(report),
        "context_flags": check_context_flags(raw_data, report, portfolio, report_date),
        "capital_summary": check_capital_summary(raw_data, report, portfolio),
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
    print(f"\nOutput: status-pre-critic.md ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
