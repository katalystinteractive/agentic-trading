#!/usr/bin/env python3
"""
Morning Verifier — Verifies morning-briefing.md against ground truth data.

Reads morning-briefing.md, morning-briefing-condensed.md, and portfolio.json,
then performs 9 verification checks (P/L math, day count, verdict assignment,
earnings gate, regime, entry gate, data consistency, coverage, cross-domain).

Replaces the LLM-based morning-critic agent with pure Python for speed
and reliability (~5 seconds vs 900s timeout).

Usage: python3 tools/morning_verifier.py
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Imports from morning_assembler.py
# ---------------------------------------------------------------------------

from morning_assembler import (
    parse_table_row,
    parse_card_header,
    parse_earnings_days,
    parse_condensed_positions,
    parse_vix_5d_pct,
    aggregate_gate_counts,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BRIEFING = PROJECT_ROOT / "morning-briefing.md"
CONDENSED = PROJECT_ROOT / "morning-briefing-condensed.md"
PORTFOLIO = PROJECT_ROOT / "portfolio.json"
OUTPUT = PROJECT_ROOT / "morning-briefing-review.md"

# ---------------------------------------------------------------------------
# Tolerances
# ---------------------------------------------------------------------------

PL_PCT_TOL = 0.2       # +/- percentage points for P/L %
DEPLOYED_TOL = 0.02    # +/- absolute for deployed/current value
DAY_TOL = 1            # +/- days
PCT_BELOW_TOL = 0.5    # +/- percentage points for % Below Current

# Gate priority (lower = less restrictive)
GATE_PRIORITY = {"ACTIVE": 0, "CAUTION": 1, "REVIEW": 2, "PAUSE": 3, "GATED": 4}
GATE_PRIORITY_REV = {v: k for k, v in GATE_PRIORITY.items()}


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _safe_float(val, default=0.0):
    """Safely convert a value to float."""
    if isinstance(val, (int, float)):
        return float(val)
    try:
        cleaned = str(val).replace("$", "").replace(",", "").replace("%", "").strip()
        # Handle leading + sign
        if cleaned.startswith("+"):
            cleaned = cleaned[1:]
        return float(cleaned)
    except (ValueError, AttributeError):
        return default


def _safe_int_shares(pos):
    """Safely get shares as int from a portfolio position entry."""
    shares = pos.get("shares", 0)
    if isinstance(shares, str):
        return int(shares) if shares.isdigit() else 0
    return shares


def _is_recovery(portfolio_entry):
    """Check if a position is recovery/pre-strategy from portfolio.json note."""
    note = portfolio_entry.get("note", "")
    if not note:
        return False
    note_lower = note.lower()
    return "recovery" in note_lower or "pre-strategy" in note_lower


# ---------------------------------------------------------------------------
# Briefing card parsing
# ---------------------------------------------------------------------------

def parse_briefing_cards(briefing_text):
    """Split briefing into active and watchlist card dicts.

    Returns (active_cards, watchlist_cards) where each card is:
    {**parse_card_header(line), "text": str, "header": str}

    Tolerant of non-standard heading levels (# or ##) and non-standard
    card header formats. Falls back to section context for card type.
    """
    SECTION_HEADERS = {
        "Executive Summary", "Immediate Actions", "Market Regime",
        "Active Positions", "Watchlist", "Cross-Ticker Intelligence",
        "Fill Alerts", "Capital Summary", "Velocity & Bounce Positions",
        "Scouting", "Failed Tickers", "Morning Briefing",
        "Velocity", "Quality Notes",
    }

    active_cards = []
    watchlist_cards = []
    lines = briefing_text.split("\n")

    # Track briefing section for fallback card type inference
    current_section = None  # "active" or "watchlist"
    card_starts = []  # (line_index, section_hint)

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Track section transitions
        if stripped == "## Active Positions":
            current_section = "active"
            continue
        if stripped == "## Watchlist":
            current_section = "watchlist"
            continue
        if stripped.startswith("## "):
            section_name = stripped[3:].strip()
            if section_name in SECTION_HEADERS:
                current_section = None
                continue
            # Non-standard ## card header (e.g., ## TICKER — VERDICT — P/L X%)
            if current_section:
                if re.match(r'[A-Z]{1,6}\b.*\u2014', section_name):
                    card_starts.append((i, current_section))
                elif re.match(r'Action Card:\s*[A-Z]{1,6}', section_name):
                    card_starts.append((i, current_section))
            continue

        # Standard ### card headers — must start with a ticker (1-6 uppercase)
        if line.startswith("### "):
            m = re.match(r'^### ([A-Z]{1,6})\b', line)
            if m:
                card_starts.append((i, current_section))
            continue

        # Non-standard # headers that look like ticker cards
        m = re.match(r'^#\s+(.+)$', line)
        if m and current_section:
            content = m.group(1).strip()
            if any(content.startswith(h) for h in SECTION_HEADERS):
                continue
            # Must start with ticker + em-dash, or be "Action Card: TICKER"
            if re.match(r'[A-Z]{1,6}\b.*\u2014', content):
                card_starts.append((i, current_section))
            elif re.match(r'Action Card:\s*[A-Z]{1,6}', content):
                card_starts.append((i, current_section))

    for idx, (start, section_hint) in enumerate(card_starts):
        next_start = card_starts[idx + 1][0] if idx + 1 < len(card_starts) else len(lines)
        # Find the actual end: stop at --- or known section headers only.
        # Do NOT break at arbitrary ## lines (non-standard cards may use them).
        card_lines = []
        for j in range(start, next_start):
            line = lines[j]
            if j > start:
                if line.strip() == "---":
                    break
                if line.startswith("## "):
                    sec = line[3:].strip()
                    if sec in SECTION_HEADERS:
                        break
            card_lines.append(line)

        if not card_lines:
            continue

        first_line = card_lines[0]
        header_data = parse_card_header(first_line)
        card_text = "\n".join(card_lines)

        card_entry = {
            **header_data,
            "text": card_text,
            "header": first_line,
        }

        card_type = header_data.get("card_type")

        # Fall back to section context for unknown card types
        if card_type == "unknown" and section_hint:
            card_type = section_hint
            card_entry["card_type"] = card_type
            # For active cards without verdict, try to extract from Decision line
            if card_type == "active" and "verdict" not in card_entry:
                m = re.search(r'\*\*Decision:\*\*\s*(\w+)', card_text)
                if m:
                    card_entry["verdict"] = m.group(1)
            # For active cards without P/L, try to extract from text
            if card_type == "active" and "pl" not in card_entry:
                m = re.search(r'P/L\s+([+-]?\d+\.?\d*%)', card_text[:500])
                if m:
                    card_entry["pl"] = m.group(1)

        if card_type == "active":
            active_cards.append(card_entry)
        elif card_type == "watchlist":
            watchlist_cards.append(card_entry)

    # Deduplicate: if same ticker appears multiple times (e.g., non-standard
    # preamble + standard header), keep the one with richer parsed data.
    active_cards = _dedup_cards(active_cards)
    watchlist_cards = _dedup_cards(watchlist_cards)

    return active_cards, watchlist_cards


def _dedup_cards(cards):
    """Deduplicate cards by ticker, preferring standard-format over unknown."""
    seen = {}
    for card in cards:
        ticker = card["ticker"]
        if ticker in seen:
            existing = seen[ticker]
            existing_has_verdict = "verdict" in existing
            new_has_verdict = "verdict" in card
            # Prefer card with verdict (standard format) over one without
            if new_has_verdict and not existing_has_verdict:
                seen[ticker] = card
            # Same verdict status — prefer longer card text
            elif new_has_verdict == existing_has_verdict:
                if len(card.get("text", "")) > len(existing.get("text", "")):
                    seen[ticker] = card
        else:
            seen[ticker] = card
    return list(seen.values())


def parse_exit_criteria_table(card_text):
    """Extract 4-row Exit Criterion table from ACTIVE cards.

    Returns dict: {"time_stop": {"status": ..., "detail": ...}, ...}
    """
    KEY_MAP = {
        "Time Stop": "time_stop",
        "Profit Target": "profit_target",
        "Earnings Gate": "earnings_gate",
        "Momentum": "momentum",
    }
    result = {}
    in_table = False

    for line in card_text.split("\n"):
        stripped = line.strip()
        if "Exit Criterion" in stripped and "Status" in stripped:
            in_table = True
            continue
        if in_table:
            cells = parse_table_row(stripped)
            if not cells:
                if not stripped.startswith("|"):
                    break
                continue
            if cells[0].strip() in (":---", "---"):
                continue
            if len(cells) >= 3:
                key = cells[0].strip()
                if key in KEY_MAP:
                    result[KEY_MAP[key]] = {
                        "status": cells[1].strip(),
                        "detail": cells[2].strip() if len(cells) > 2 else "",
                    }

    return result


def parse_entry_gate_table(card_text):
    """Extract 3-row Entry Gate table from WATCHLIST cards.

    Returns dict: {"market_gate": {"status": ..., "detail": ...}, ...}
    """
    KEY_MAP = {
        "Market Gate": "market_gate",
        "Earnings Gate": "earnings_gate",
        "Overall": "overall",
    }
    result = {}
    in_table = False

    for line in card_text.split("\n"):
        stripped = line.strip()
        if "Entry Gate" in stripped and "Status" in stripped:
            in_table = True
            continue
        if in_table:
            cells = parse_table_row(stripped)
            if not cells:
                if not stripped.startswith("|"):
                    break
                continue
            if cells[0].strip() in (":---", "---"):
                continue
            if len(cells) >= 3:
                key = cells[0].strip()
                if key in KEY_MAP:
                    status = cells[1].strip().replace("**", "")
                    result[KEY_MAP[key]] = {
                        "status": status,
                        "detail": cells[2].strip() if len(cells) > 2 else "",
                    }

    return result


def extract_momentum_data(detail_text):
    """Extract RSI and MACD from momentum Detail column.

    Returns dict: {"rsi": float|None, "macd_vs_signal": str|None, "histogram": float|None}
    """
    rsi = None
    macd_vs_signal = None
    histogram = None

    m = re.search(r'RSI\s+([\d.]+)', detail_text)
    if m:
        rsi = float(m.group(1))

    m = re.search(r'histogram\s+([+-]?[\d.]+)', detail_text)
    if m:
        histogram = float(m.group(1))

    m = re.search(r'MACD\s+[+-]?[\d.]+\s+(above|below)\s+signal', detail_text)
    if m:
        macd_vs_signal = m.group(1)

    return {"rsi": rsi, "macd_vs_signal": macd_vs_signal, "histogram": histogram}


def compute_expected_momentum_label(momentum_data):
    """Determine expected Bullish/Neutral/Bearish label.

    Returns "Bullish", "Bearish", "Neutral", or "SKIPPED" if data unavailable.
    """
    rsi = momentum_data.get("rsi")
    macd_vs = momentum_data.get("macd_vs_signal")
    histogram = momentum_data.get("histogram")

    if rsi is None or macd_vs is None:
        return "SKIPPED"

    # Bullish: RSI > 50 AND MACD above signal
    if rsi > 50 and macd_vs == "above":
        return "Bullish"

    # Bearish: RSI < 40 OR (MACD below signal AND histogram negative)
    if rsi < 40:
        return "Bearish"
    if macd_vs == "below" and histogram is not None and histogram < 0:
        return "Bearish"

    return "Neutral"


# ---------------------------------------------------------------------------
# Condensed file parsing helpers
# ---------------------------------------------------------------------------

def parse_condensed_indices(condensed_text):
    """Extract Major Indices rows from condensed.

    Returns list of {"index": str, "above_50sma": bool}
    """
    indices = []
    in_section = False

    for line in condensed_text.split("\n"):
        if "Major Indices" in line:
            in_section = True
            continue
        if in_section:
            # Check section exit BEFORE parse_table_row (which skips non-table lines)
            stripped = line.strip()
            if stripped.startswith("###") and "Major" not in stripped:
                break
            if stripped == "---":
                break
            cells = parse_table_row(line)
            if not cells:
                continue
            if cells[0] in (":---", "---", "Index"):
                continue
            if len(cells) >= 6:
                index_name = cells[0].strip()
                trend = cells[5].strip()
                if index_name in ("S&P 500", "Nasdaq 100", "Russell 2000"):
                    indices.append({
                        "index": index_name,
                        "above_50sma": "Above" in trend,
                    })

    return indices


def parse_condensed_vix(condensed_text):
    """Extract VIX value (float) from condensed."""
    for line in condensed_text.split("\n"):
        cells = parse_table_row(line)
        if len(cells) >= 2 and cells[0].strip() == "VIX":
            m = re.search(r'([\d.]+)', cells[1])
            if m:
                return float(m.group(1))
    return None


def parse_condensed_regime(condensed_text):
    """Extract regime string from Market Regime table in condensed."""
    in_regime = False
    for line in condensed_text.split("\n"):
        if "### Market Regime" in line or "## Market Regime" in line:
            in_regime = True
            continue
        if in_regime:
            cells = parse_table_row(line)
            if len(cells) >= 2 and cells[0].strip() == "Regime":
                return cells[1].strip().replace("**", "")
    return None


def parse_condensed_earnings(condensed_text, ticker):
    """Extract earnings date and days for a ticker from condensed.

    Returns (date_str, days_int) or (None, None).
    """
    # Look in per-ticker sections for earnings data
    in_ticker = False
    earnings_date_str = None
    for line in condensed_text.split("\n"):
        if line.strip() == f"### {ticker}":
            in_ticker = True
            continue
        if in_ticker:
            if line.strip().startswith("### ") and ticker not in line:
                break
            cells = parse_table_row(line)
            if len(cells) >= 2:
                key = cells[0].strip()
                val = cells[1].strip()
                if key == "Earnings Date":
                    earnings_date_str = val
                if key == "Days Until":
                    try:
                        days = int(val)
                        return earnings_date_str, days
                    except ValueError:
                        pass

    # Try Pending Orders Detail table
    for line in condensed_text.split("\n"):
        cells = parse_table_row(line)
        if len(cells) >= 9 and cells[0].strip() == ticker:
            try:
                days = int(cells[7].strip())
                return None, days
            except ValueError:
                pass

    return None, None


def extract_reference_date(condensed_text):
    """Parse date from condensed header line."""
    m = re.search(r'(\d{4}-\d{2}-\d{2})', condensed_text[:500])
    if m:
        parts = m.group(1).split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    return date.today()


# ---------------------------------------------------------------------------
# Briefing parsing helpers
# ---------------------------------------------------------------------------

def parse_briefing_regime(briefing_text):
    """Extract regime from briefing's Market Regime table."""
    in_regime = False
    for line in briefing_text.split("\n"):
        if "## Market Regime" in line:
            in_regime = True
            continue
        if in_regime:
            cells = parse_table_row(line)
            if len(cells) >= 2 and cells[0].strip() == "Regime":
                return cells[1].strip().replace("**", "")
    return None


def parse_briefing_gate_summary(briefing_text):
    """Extract Entry Gate Summary counts from briefing.

    Returns dict: {"ACTIVE": int, "CAUTION": int, "REVIEW": int,
                    "PAUSE": int, "GATED": int, "total_buy": int}
    """
    for line in briefing_text.split("\n"):
        if "Entry Gate Summary" in line:
            counts = {}
            for label in ["ACTIVE", "CAUTION", "REVIEW", "PAUSE", "GATED"]:
                m = re.search(rf'(\d+)\s+{label}', line)
                counts[label] = int(m.group(1)) if m else 0
            m = re.search(r'\(of\s+(\d+)\s+BUY', line)
            counts["total_buy"] = int(m.group(1)) if m else sum(
                counts[k] for k in ["ACTIVE", "CAUTION", "REVIEW", "PAUSE", "GATED"]
            )
            return counts

    return {"ACTIVE": 0, "CAUTION": 0, "REVIEW": 0, "PAUSE": 0, "GATED": 0, "total_buy": 0}


def parse_pending_orders_from_card(card_text):
    """Extract all pending order rows from a card's Pending Orders table.

    Returns list of dicts with: type, price, shares, pct_below, market_gate,
    earnings_gate, combined, note
    """
    orders = []
    in_table = False
    header_found = False

    for line in card_text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("**Pending Orders:**"):
            in_table = True
            continue
        if in_table:
            cells = parse_table_row(stripped)
            if not cells:
                if header_found and not stripped.startswith("|"):
                    break
                continue
            if cells[0].strip() in ("Type", ":---"):
                header_found = True
                continue
            if len(cells) < 7:
                continue
            # Skip dash/placeholder rows
            if all(c.strip() in ("—", "-", "", "---") for c in cells[:6]):
                continue

            order_type = cells[0].strip()
            price_str = cells[1].strip().replace("$", "").replace(",", "")
            try:
                price = float(price_str)
            except ValueError:
                continue

            shares_str = cells[2].strip()
            try:
                shares = int(shares_str)
            except ValueError:
                shares = 0

            orders.append({
                "type": order_type,
                "price": price,
                "shares": shares,
                "pct_below": cells[3].strip() if len(cells) > 3 else "",
                "market_gate": cells[4].strip() if len(cells) > 4 else "",
                "earnings_gate": cells[5].strip() if len(cells) > 5 else "",
                "combined": cells[6].strip().replace("**", "") if len(cells) > 6 else "",
                "note": cells[7].strip() if len(cells) > 7 else "",
            })

    return orders


# ---------------------------------------------------------------------------
# Check 1: P/L Math
# ---------------------------------------------------------------------------

def check_pl_math(portfolio, condensed_positions, active_cards):
    """Verify P/L calculations for each active position."""
    findings = []
    positions = portfolio.get("positions", {})

    for card in active_cards:
        ticker = card["ticker"]
        pos = positions.get(ticker, {})
        cond = condensed_positions.get(ticker, {})

        if not pos or not cond:
            continue

        shares = pos.get("shares", 0)
        avg_cost = pos.get("avg_cost", 0)
        current_price = cond.get("current_price", 0)
        target_exit = pos.get("target_exit")

        if shares == 0 or avg_cost == 0 or current_price == 0:
            continue

        # Expected values
        exp_deployed = shares * avg_cost
        exp_current_val = shares * current_price
        exp_pl_dollar = exp_current_val - exp_deployed
        exp_pl_pct = (exp_pl_dollar / exp_deployed) * 100 if exp_deployed else 0

        # Parse from card header
        card_pl_str = card.get("pl", "")
        card_pl_pct = _safe_float(card_pl_str)

        # Check P/L %
        if abs(card_pl_pct - exp_pl_pct) > PL_PCT_TOL:
            findings.append({
                "severity": "Critical",
                "ticker": ticker,
                "message": f"P/L %: expected {exp_pl_pct:+.1f}%, briefing shows {card_pl_str}",
            })

        # Parse exit criteria for profit target status
        exit_criteria = parse_exit_criteria_table(card["text"])
        pt = exit_criteria.get("profit_target", {})
        pt_status = pt.get("status", "")

        # Check profit target status label
        if target_exit is not None:
            if exp_pl_pct >= 12:
                expected_pt = "EXCEEDED"
            elif exp_pl_pct >= 10:
                expected_pt = "AT TARGET"
            elif exp_pl_pct >= 7:
                expected_pt = "APPROACHING"
            else:
                expected_pt = "BELOW"

            # Normalize: some cards show "N/A" for recovery
            if pt_status and pt_status != "N/A" and expected_pt != pt_status:
                findings.append({
                    "severity": "Minor",
                    "ticker": ticker,
                    "message": f"Profit Target label: expected {expected_pt} (P/L {exp_pl_pct:+.1f}%), briefing shows {pt_status}",
                })

        # Distance to target
        if target_exit and current_price > 0:
            exp_dist = ((target_exit - current_price) / current_price) * 100
            # Try to parse from card
            m = re.search(r'target.*?(\d+\.?\d*)%\s*away', card["text"][:300])
            if m:
                card_dist = float(m.group(1))
                if abs(card_dist - exp_dist) > PL_PCT_TOL:
                    findings.append({
                        "severity": "Minor",
                        "ticker": ticker,
                        "message": f"Distance to target: expected {exp_dist:.1f}%, briefing shows {card_dist:.1f}%",
                    })

    return findings


# ---------------------------------------------------------------------------
# Check 2: Day Count Math
# ---------------------------------------------------------------------------

def check_day_count(portfolio, ref_date, active_cards):
    """Verify days held and time stop status for each active position."""
    findings = []
    positions = portfolio.get("positions", {})

    for card in active_cards:
        ticker = card["ticker"]
        pos = positions.get(ticker, {})
        entry_date_str = pos.get("entry_date", "")

        exit_criteria = parse_exit_criteria_table(card["text"])
        ts = exit_criteria.get("time_stop", {})
        ts_status = ts.get("status", "")
        ts_detail = ts.get("detail", "")

        if not entry_date_str:
            continue

        # Pre-strategy dates
        if entry_date_str.startswith("pre-"):
            # Should show EXCEEDED and mention pre-strategy
            if "EXCEEDED" not in ts_status:
                findings.append({
                    "severity": "Critical",
                    "ticker": ticker,
                    "message": f"Pre-strategy entry should be EXCEEDED, briefing shows {ts_status}",
                })
            continue

        # ISO date
        try:
            parts = entry_date_str.split("-")
            entry = date(int(parts[0]), int(parts[1]), int(parts[2]))
            exp_days = (ref_date - entry).days
        except (ValueError, IndexError):
            continue

        # Parse days from card detail
        m = re.search(r'(\d+)\s*days?', ts_detail)
        if m:
            card_days = int(m.group(1))
            if abs(card_days - exp_days) > DAY_TOL:
                findings.append({
                    "severity": "Critical" if abs(card_days - exp_days) > 3 else "Minor",
                    "ticker": ticker,
                    "message": f"Days held: expected {exp_days}, briefing shows {card_days}",
                })

        # Check time stop status
        if exp_days > 21:
            expected_ts = "EXCEEDED"
        elif exp_days >= 15:
            expected_ts = "APPROACHING"
        else:
            expected_ts = "WITHIN"

        # Normalize the card status (strip parenthetical remarks)
        card_ts_base = ts_status.split("(")[0].strip()
        if expected_ts != card_ts_base:
            findings.append({
                "severity": "Critical",
                "ticker": ticker,
                "message": f"Time stop: expected {expected_ts} ({exp_days}d), briefing shows {ts_status}",
            })

    return findings


# ---------------------------------------------------------------------------
# Check 3: Verdict Assignment
# ---------------------------------------------------------------------------

def check_verdicts(portfolio, active_cards, ref_date):
    """Verify verdict follows 16-rule logic."""
    findings = []
    positions = portfolio.get("positions", {})

    for card in active_cards:
        ticker = card["ticker"]
        pos = positions.get(ticker, {})
        verdict = card.get("verdict", "")

        if not pos:
            continue

        # Determine position characteristics
        avg_cost = pos.get("avg_cost", 0)
        entry_date_str = pos.get("entry_date", "")
        is_recov = _is_recovery(pos)

        exit_criteria = parse_exit_criteria_table(card["text"])

        # Use card's stated P/L
        pl_pct = 0.0
        if avg_cost > 0:
            card_pl_str = card.get("pl", "")
            pl_pct = _safe_float(card_pl_str)

        # Recovery reclassification: if P/L > 0%, treat as non-recovery
        effective_recovery = is_recov and pl_pct <= 0

        # Get exit criteria statuses
        ts = exit_criteria.get("time_stop", {})
        ts_status = ts.get("status", "").split("(")[0].strip()
        eg = exit_criteria.get("earnings_gate", {})
        eg_status = eg.get("status", "")
        mom = exit_criteria.get("momentum", {})
        mom_status = mom.get("status", "")
        mom_detail = mom.get("detail", "")

        # Determine days held for time stop
        days_held = 0
        if entry_date_str.startswith("pre-"):
            days_held = 999  # Definitely EXCEEDED
        else:
            try:
                parts = entry_date_str.split("-")
                entry = date(int(parts[0]), int(parts[1]), int(parts[2]))
                days_held = (ref_date - entry).days
            except (ValueError, IndexError):
                pass

        # Determine effective statuses
        is_gated = "GATED" in eg_status
        is_approaching = "APPROACHING" in eg_status
        is_clear = "CLEAR" in eg_status
        time_exceeded = days_held > 21 or "EXCEEDED" in ts_status
        time_approaching = 15 <= days_held <= 21 or "APPROACHING" in ts_status

        # Determine if bearish momentum
        momentum_data = extract_momentum_data(mom_detail)
        rsi = momentum_data.get("rsi")
        bearish_rsi = rsi is not None and rsi < 40

        # Apply rules — first match wins
        expected_verdict = None
        rule = None

        # Earnings GATED rules
        if is_gated and not effective_recovery:
            if pl_pct > 0:
                expected_verdict = "REDUCE"
                rule = "1 (non-recovery + GATED + P/L > 0%)"
            else:
                expected_verdict = "HOLD"
                rule = "2 (non-recovery + GATED + P/L <= 0%)"
        elif is_gated and effective_recovery:
            # Rules 3-5: recovery + GATED
            # Rule 3 requires thesis verification — skip
            if pl_pct > -10:
                expected_verdict = "REDUCE"
                rule = "4 (recovery + GATED + P/L > -10%)"
            else:
                expected_verdict = "HOLD"
                rule = "5 (recovery + GATED + P/L <= -10%)"

        # Profit target rules (non-GATED)
        if expected_verdict is None and not is_gated:
            if pl_pct >= 12:
                expected_verdict = "REDUCE"
                rule = "6a (P/L >= 12%)"
            elif pl_pct >= 10:
                expected_verdict = "HOLD"
                rule = "6 (AT TARGET 10-12%)"
            elif pl_pct >= 7:
                expected_verdict = "HOLD"
                rule = "7 (APPROACHING 7-10%)"

        # Recovery rules (non-GATED)
        if expected_verdict is None and effective_recovery:
            # Rules 8-10
            expected_verdict = None  # Could be HOLD or MONITOR
            rule = "8-10 (recovery)"
            # Can't fully determine without detailed squeeze/relief analysis
            # Flag only clear mismatches
            if verdict == "EXIT":
                findings.append({
                    "severity": "Critical",
                    "ticker": ticker,
                    "message": f"EXIT prohibited for recovery position (rule 10/11)",
                })
            continue  # Skip further rule checks for recovery

        # Time stop rules (non-recovery, non-GATED)
        if expected_verdict is None:
            if time_exceeded:
                if bearish_rsi and is_clear:
                    expected_verdict = "EXIT"
                    rule = "11 (EXCEEDED + bearish RSI + CLEAR)"
                elif is_approaching:
                    expected_verdict = "REDUCE"
                    rule = "13 (EXCEEDED + APPROACHING earnings)"
                else:
                    # EXCEEDED + non-bearish-RSI: HOLD (bullish justification) or REDUCE both valid
                    if verdict == "MONITOR":
                        findings.append({
                            "severity": "Critical",
                            "ticker": ticker,
                            "message": "MONITOR invalid for time-stop-EXCEEDED non-recovery (rule 14)",
                        })
                    continue
            elif time_approaching:
                expected_verdict = "MONITOR"
                rule = "15 (APPROACHING time stop)"
            else:
                expected_verdict = "MONITOR"
                rule = "16 (WITHIN time stop)"

        # Compare expected vs actual
        if expected_verdict and expected_verdict != verdict:
            # Some flexibility: HOLD and MONITOR can overlap in edge cases
            # Rule 3 (thesis) can produce HOLD for recovery+GATED
            if is_gated and effective_recovery and verdict == "HOLD":
                # Rule 3 may apply — skip (requires manual review)
                findings.append({
                    "severity": "Minor",
                    "ticker": ticker,
                    "message": f"SKIPPED — recovery + GATED verdict '{verdict}' may be valid via rule 3 (thesis). Requires manual review.",
                })
                continue

            findings.append({
                "severity": "Critical",
                "ticker": ticker,
                "message": f"Verdict: expected {expected_verdict} (rule {rule}), briefing shows {verdict}",
            })

        # Momentum label verification (reuse momentum_data from line 686)
        if mom_detail:
            expected_label = compute_expected_momentum_label(momentum_data)
            if expected_label != "SKIPPED":
                card_label = mom_status.strip()
                # Normalize: "Neutral-Bearish" → accept if expected is "Neutral" or "Bearish"
                label_match = (
                    expected_label == card_label
                    or expected_label in card_label
                )
                if not label_match:
                    sev = "Minor"
                    # Critical if it would affect verdict logic
                    if expected_label == "Bearish" and "Bearish" not in card_label and time_exceeded:
                        sev = "Critical"
                    findings.append({
                        "severity": sev,
                        "ticker": ticker,
                        "message": f"Momentum label: expected {expected_label}, briefing shows {card_label}",
                    })

    return findings


# ---------------------------------------------------------------------------
# Check 4: Earnings Gate Logic
# ---------------------------------------------------------------------------

def check_earnings_gate(condensed, active_cards, watchlist_cards):
    """Verify earnings gate status for active and watchlist positions."""
    findings = []

    for card in active_cards:
        ticker = card["ticker"]
        exit_criteria = parse_exit_criteria_table(card["text"])
        eg = exit_criteria.get("earnings_gate", {})
        eg_status = eg.get("status", "")

        # Parse claimed days from card
        card_days, _ = parse_earnings_days(card["text"])

        # Get expected days from condensed
        _, cond_days = parse_condensed_earnings(condensed, ticker)

        if card_days is not None and cond_days is not None:
            if abs(card_days - cond_days) > DAY_TOL:
                findings.append({
                    "severity": "Minor",
                    "ticker": ticker,
                    "message": f"Earnings days: condensed={cond_days}, card={card_days}",
                })

        # Verify gate status matches day count
        if card_days is not None:
            if card_days < 7:
                expected_gate = "GATED"
            elif card_days <= 14:
                expected_gate = "APPROACHING"
            else:
                expected_gate = "CLEAR"

            if expected_gate not in eg_status:
                findings.append({
                    "severity": "Critical",
                    "ticker": ticker,
                    "message": f"Earnings gate: expected {expected_gate} ({card_days}d), briefing shows {eg_status}",
                })

    # Watchlist cards
    for card in watchlist_cards:
        ticker = card["ticker"]
        entry_gates = parse_entry_gate_table(card["text"])
        eg = entry_gates.get("earnings_gate", {})
        eg_status = eg.get("status", "")

        card_days, _ = parse_earnings_days(card["text"])
        _, cond_days = parse_condensed_earnings(condensed, ticker)

        if card_days is not None and cond_days is not None:
            if abs(card_days - cond_days) > DAY_TOL:
                findings.append({
                    "severity": "Minor",
                    "ticker": ticker,
                    "message": f"Earnings days: condensed={cond_days}, card={card_days}",
                })

        if card_days is not None:
            if card_days < 7:
                expected_gate = "PAUSE"
            elif card_days <= 14:
                expected_gate = "REVIEW"
            else:
                expected_gate = "ACTIVE"

            if expected_gate not in eg_status:
                findings.append({
                    "severity": "Critical",
                    "ticker": ticker,
                    "message": f"Watchlist earnings gate: expected {expected_gate} ({card_days}d), briefing shows {eg_status}",
                })

    return findings


# ---------------------------------------------------------------------------
# Check 5: Regime Classification
# ---------------------------------------------------------------------------

def check_regime(condensed, briefing):
    """Verify regime assignment matches raw data."""
    findings = []

    indices = parse_condensed_indices(condensed)
    vix = parse_condensed_vix(condensed)
    condensed_regime = parse_condensed_regime(condensed)
    briefing_regime = parse_briefing_regime(briefing)

    above_count = sum(1 for i in indices if i["above_50sma"])

    # Compute expected regime
    if vix is not None:
        if 20 <= vix <= 25:
            expected_regime = "Neutral"
        elif above_count >= 2 and vix < 20:
            expected_regime = "Risk-On"
        elif above_count <= 1 and vix > 25:
            expected_regime = "Risk-Off"
        else:
            expected_regime = "Neutral"
    else:
        expected_regime = "Neutral"

    # Check condensed regime
    if condensed_regime and condensed_regime != expected_regime:
        findings.append({
            "severity": "Critical",
            "ticker": "REGIME",
            "message": f"Condensed regime '{condensed_regime}' != expected '{expected_regime}' (indices {above_count}/3 above 50-SMA, VIX {vix})",
        })

    # Check briefing regime matches condensed
    if briefing_regime and condensed_regime and briefing_regime != condensed_regime:
        findings.append({
            "severity": "Critical",
            "ticker": "REGIME",
            "message": f"Briefing regime '{briefing_regime}' != condensed regime '{condensed_regime}'",
        })

    # Check VIX matches
    if vix is not None:
        # Parse VIX from briefing
        for line in briefing.split("\n"):
            cells = parse_table_row(line)
            if len(cells) >= 2 and cells[0].strip() == "VIX":
                m = re.search(r'([\d.]+)', cells[1])
                if m:
                    briefing_vix = float(m.group(1))
                    if abs(briefing_vix - vix) > 0.1:
                        findings.append({
                            "severity": "Minor",
                            "ticker": "VIX",
                            "message": f"VIX: condensed={vix}, briefing={briefing_vix}",
                        })
                break

    return findings


# ---------------------------------------------------------------------------
# Check 6: Entry Gate Logic
# ---------------------------------------------------------------------------

def check_entry_gates(portfolio, condensed, active_cards, watchlist_cards):
    """Verify entry gate logic for pending BUY orders."""
    findings = []

    # Determine current regime and VIX
    regime = parse_condensed_regime(condensed) or "Neutral"
    vix = parse_condensed_vix(condensed)
    vix_5d = parse_vix_5d_pct(condensed)
    condensed_positions = parse_condensed_positions(condensed)

    all_cards = active_cards + watchlist_cards

    for card in all_cards:
        ticker = card["ticker"]
        orders = parse_pending_orders_from_card(card["text"])

        for order in orders:
            if order["type"] != "BUY":
                continue

            order_price = order["price"]
            combined = order["combined"]

            # Get current price
            if ticker in condensed_positions:
                current_price = condensed_positions[ticker]["current_price"]
            else:
                # Watchlist — get from watchlist table
                current_price = _get_watchlist_price(condensed, ticker)
                if current_price is None:
                    continue

            # Compute expected market gate
            if regime == "Risk-On":
                exp_market = "ACTIVE"
            elif regime == "Risk-Off":
                if card.get("card_type") == "watchlist":
                    exp_market = "PAUSE"
                else:
                    pct_below = ((current_price - order_price) / current_price) * 100 if current_price else 0
                    exp_market = "ACTIVE" if pct_below > 15 else "REVIEW"
            else:
                # Neutral
                exp_market = "ACTIVE"
                if vix and 20 <= vix <= 25:
                    if vix_5d and vix_5d != "N/A":
                        try:
                            vix_5d_val = float(vix_5d.replace("%", ""))
                            if vix_5d_val > 0:
                                exp_market = "CAUTION"
                        except ValueError:
                            pass

            # Compute expected earnings gate
            card_days, _ = parse_earnings_days(card["text"])
            if card_days is not None:
                if card_days < 7:
                    exp_earnings = "PAUSE"
                elif card_days <= 14:
                    exp_earnings = "REVIEW"
                else:
                    exp_earnings = "ACTIVE"
            else:
                exp_earnings = "ACTIVE"

            # Combined = worst of both
            exp_combined_val = max(GATE_PRIORITY.get(exp_market, 0), GATE_PRIORITY.get(exp_earnings, 0))
            exp_combined = GATE_PRIORITY_REV.get(exp_combined_val, "ACTIVE")

            # Compare
            if combined and exp_combined != combined:
                findings.append({
                    "severity": "Critical",
                    "ticker": ticker,
                    "message": f"BUY ${order_price:.2f}: expected combined gate {exp_combined} (market={exp_market}, earnings={exp_earnings}), briefing shows {combined}",
                })

            # Cross-check % Below Current
            if current_price > 0:
                exp_pct_below = -((current_price - order_price) / current_price) * 100
                card_pct_str = order.get("pct_below", "")
                if card_pct_str and card_pct_str != "N/A":
                    card_pct = _safe_float(card_pct_str)
                    if abs(card_pct - exp_pct_below) > PCT_BELOW_TOL:
                        findings.append({
                            "severity": "Minor",
                            "ticker": ticker,
                            "message": f"BUY ${order_price:.2f} % Below Current: expected {exp_pct_below:.1f}%, briefing shows {card_pct_str}",
                        })

    return findings


def _get_watchlist_price(condensed, ticker):
    """Get watchlist ticker price from condensed Watchlist table."""
    in_watchlist = False
    for line in condensed.split("\n"):
        if line.strip() == "## Watchlist":
            in_watchlist = True
            continue
        if in_watchlist:
            cells = parse_table_row(line)
            if len(cells) >= 2 and cells[0].strip() == ticker:
                return _safe_float(cells[1])
            if line.strip().startswith("## ") and "Watchlist" not in line:
                break
    return None


# ---------------------------------------------------------------------------
# Check 7: Data Consistency
# ---------------------------------------------------------------------------

def check_data_consistency(portfolio, condensed, condensed_positions, active_cards, watchlist_cards, briefing):
    """Verify data fields match source of truth."""
    findings = []
    positions = portfolio.get("positions", {})
    pending = portfolio.get("pending_orders", {})

    # Active position field checks
    for card in active_cards:
        ticker = card["ticker"]
        pos = positions.get(ticker, {})

        if not pos:
            findings.append({
                "severity": "Critical",
                "ticker": ticker,
                "message": f"Active card for {ticker} but no position in portfolio.json",
            })
            continue

        # Parse State line for shares and avg
        state_line = ""
        for line in card["text"].split("\n"):
            if line.startswith("**State:**"):
                state_line = line
                break

        # Check shares
        m = re.search(r'(\d+)\s+shares?\s+@', state_line)
        if m:
            card_shares = int(m.group(1))
            if card_shares != pos.get("shares", 0):
                findings.append({
                    "severity": "Critical",
                    "ticker": ticker,
                    "message": f"Shares: portfolio={pos.get('shares')}, briefing={card_shares}",
                })

        # Check avg cost
        m = re.search(r'@\s*\$?([\d.]+)', state_line)
        if m:
            card_avg = float(m.group(1))
            exp_avg = pos.get("avg_cost", 0)
            if abs(card_avg - exp_avg) > DEPLOYED_TOL:
                findings.append({
                    "severity": "Critical",
                    "ticker": ticker,
                    "message": f"Avg cost: portfolio=${exp_avg}, briefing=${card_avg}",
                })

        # Check current price matches condensed Active Positions (NOT Position Summary)
        cond = condensed_positions.get(ticker, {})
        if cond:
            cond_price = cond["current_price"]
            # Parse current price from card
            m = re.search(r'current\s+\$?([\d.]+)', card["text"][:600], re.IGNORECASE)
            if m:
                card_price = float(m.group(1))
                if abs(card_price - cond_price) > DEPLOYED_TOL:
                    findings.append({
                        "severity": "Critical",
                        "ticker": ticker,
                        "message": f"Current price: condensed=${cond_price}, briefing=${card_price}",
                    })

        # Check pending orders match portfolio.json
        card_orders = parse_pending_orders_from_card(card["text"])
        port_orders = pending.get(ticker, [])

        for po in port_orders:
            po_price = po["price"]
            po_shares = po["shares"]
            po_type = po["type"]
            # Find matching order in card
            matched = False
            for co in card_orders:
                if co["type"] == po_type and abs(co["price"] - po_price) < 0.01:
                    matched = True
                    if co["shares"] != po_shares:
                        findings.append({
                            "severity": "Critical",
                            "ticker": ticker,
                            "message": f"{po_type} ${po_price:.2f}: portfolio shares={po_shares}, briefing shares={co['shares']}",
                        })

                    # Check SELL orders have N/A gates
                    if po_type == "SELL" and co["combined"] and co["combined"] != "N/A":
                        findings.append({
                            "severity": "Minor",
                            "ticker": ticker,
                            "message": f"SELL ${po_price:.2f}: gate should be N/A, briefing shows {co['combined']}",
                        })
                    break

            if not matched:
                findings.append({
                    "severity": "Critical",
                    "ticker": ticker,
                    "message": f"Missing {po_type} ${po_price:.2f} ({po_shares} shares) from briefing card",
                })

    # Watchlist pending order checks
    for card in watchlist_cards:
        ticker = card["ticker"]
        card_orders = parse_pending_orders_from_card(card["text"])
        port_orders = pending.get(ticker, [])

        for po in port_orders:
            po_price = po["price"]
            po_shares = po["shares"]
            po_type = po["type"]
            matched = False
            for co in card_orders:
                if co["type"] == po_type and abs(co["price"] - po_price) < 0.01:
                    matched = True
                    if co["shares"] != po_shares:
                        findings.append({
                            "severity": "Critical",
                            "ticker": ticker,
                            "message": f"{po_type} ${po_price:.2f}: portfolio shares={po_shares}, briefing shares={co['shares']}",
                        })
                    break

            if not matched and po_type == "BUY":
                findings.append({
                    "severity": "Critical",
                    "ticker": ticker,
                    "message": f"Missing BUY ${po_price:.2f} ({po_shares} shares) from watchlist card",
                })

    # VIX consistency is checked in check_regime() — not duplicated here

    # Check for phantom tickers (in briefing but not in portfolio)
    all_portfolio_tickers = set(positions.keys()) | set(portfolio.get("watchlist", []))
    for card in active_cards + watchlist_cards:
        if card["ticker"] not in all_portfolio_tickers:
            findings.append({
                "severity": "Critical",
                "ticker": card["ticker"],
                "message": f"Phantom ticker — in briefing but not in portfolio.json",
            })

    return findings


# ---------------------------------------------------------------------------
# Check 8: Coverage & Completeness
# ---------------------------------------------------------------------------

def check_coverage(portfolio, briefing, active_cards, watchlist_cards):
    """Verify all positions and orders are covered in briefing."""
    findings = []
    positions = portfolio.get("positions", {})
    pending = portfolio.get("pending_orders", {})
    watchlist = portfolio.get("watchlist", [])

    active_tickers = {c["ticker"] for c in active_cards}
    watchlist_tickers = {c["ticker"] for c in watchlist_cards}

    # Every active position must appear
    for ticker, pos in positions.items():
        shares = _safe_int_shares(pos)
        if shares > 0 and ticker not in active_tickers:
            findings.append({
                "severity": "Critical",
                "ticker": ticker,
                "message": f"Active position ({shares} shares) missing from briefing Active Positions",
            })

    # Placement rules: shares > 0 = active, shares = 0 = watchlist
    for card in active_cards:
        ticker = card["ticker"]
        pos = positions.get(ticker, {})
        shares = _safe_int_shares(pos)
        if shares == 0:
            findings.append({
                "severity": "Critical",
                "ticker": ticker,
                "message": f"Ticker with 0 shares placed under Active Positions (should be Watchlist)",
            })

    for card in watchlist_cards:
        ticker = card["ticker"]
        pos = positions.get(ticker, {})
        shares = _safe_int_shares(pos)
        if shares > 0:
            findings.append({
                "severity": "Critical",
                "ticker": ticker,
                "message": f"Ticker with {shares} shares placed under Watchlist (should be Active)",
            })

    # Watchlist tickers with pending BUY orders should appear
    for ticker in watchlist:
        ticker_orders = pending.get(ticker, [])
        buy_orders = [o for o in ticker_orders if o["type"] == "BUY"]
        if buy_orders and ticker not in watchlist_tickers:
            # Check if it's a scouting ticker (mentioned in scouting section)
            if ticker not in active_tickers:
                # Could be in scouting section — use word boundary to avoid
                # false matches (e.g., "AR" matching inside "NEAR")
                if not re.search(rf'\b{re.escape(ticker)}\b', briefing):
                    findings.append({
                        "severity": "Critical",
                        "ticker": ticker,
                        "message": f"Watchlist ticker with {len(buy_orders)} BUY orders missing from briefing",
                    })

    # Immediate Actions table should exist if EXIT/REDUCE verdicts exist
    has_exit_reduce = any(c.get("verdict") in ("EXIT", "REDUCE") for c in active_cards)
    if has_exit_reduce:
        if "## Immediate Actions" not in briefing:
            findings.append({
                "severity": "Critical",
                "ticker": "STRUCTURE",
                "message": "Immediate Actions table missing despite EXIT/REDUCE verdicts",
            })

    # Capital Summary section present
    if "## Capital Summary" not in briefing:
        findings.append({
            "severity": "Minor",
            "ticker": "STRUCTURE",
            "message": "Capital Summary section missing",
        })

    # Executive Summary present
    if "## Executive Summary" not in briefing:
        findings.append({
            "severity": "Minor",
            "ticker": "STRUCTURE",
            "message": "Executive Summary section missing",
        })

    # Market Regime table present
    if "## Market Regime" not in briefing:
        findings.append({
            "severity": "Minor",
            "ticker": "STRUCTURE",
            "message": "Market Regime section missing",
        })

    return findings


# ---------------------------------------------------------------------------
# Check 9: Cross-Domain Consistency
# ---------------------------------------------------------------------------

def check_cross_domain(active_cards, watchlist_cards, briefing, condensed):
    """Cross-domain consistency checks."""
    findings = []

    all_cards = active_cards + watchlist_cards
    regime = parse_briefing_regime(briefing)

    # 9.1: GATED tickers' BUY orders should have PAUSE earnings gate
    for card in active_cards:
        ticker = card["ticker"]
        exit_criteria = parse_exit_criteria_table(card["text"])
        eg = exit_criteria.get("earnings_gate", {})
        if "GATED" in eg.get("status", ""):
            orders = parse_pending_orders_from_card(card["text"])
            for order in orders:
                if order["type"] == "BUY":
                    eg_col = order.get("earnings_gate", "")
                    if eg_col and "PAUSE" not in eg_col:
                        findings.append({
                            "severity": "Critical",
                            "ticker": ticker,
                            "message": f"Position GATED but BUY ${order['price']:.2f} earnings gate is {eg_col} (expected PAUSE)",
                        })

    # 9.6: Entry gate summary count verification
    stated_counts = parse_briefing_gate_summary(briefing)

    # Compute actual counts from all BUY orders across all cards
    computed_counts, _ = aggregate_gate_counts(all_cards)

    total_buy_computed = sum(computed_counts.get(k, 0) for k in ["ACTIVE", "CAUTION", "REVIEW", "PAUSE", "GATED"])

    for label in ["ACTIVE", "CAUTION", "REVIEW", "PAUSE", "GATED"]:
        stated = stated_counts.get(label, 0)
        computed = computed_counts.get(label, 0)
        if stated != computed:
            findings.append({
                "severity": "Critical",
                "ticker": "GATE_SUMMARY",
                "message": f"Entry Gate Summary {label}: stated={stated}, computed={computed}",
            })

    # Total BUY count
    if stated_counts["total_buy"] != total_buy_computed and total_buy_computed > 0:
        findings.append({
            "severity": "Critical",
            "ticker": "GATE_SUMMARY",
            "message": f"Total BUY orders: stated={stated_counts['total_buy']}, computed={total_buy_computed}",
        })

    # 9.7: Regime vs gate consistency
    if regime == "Risk-On":
        for card in all_cards:
            orders = parse_pending_orders_from_card(card["text"])
            for order in orders:
                if order["type"] != "BUY":
                    continue
                market_gate = order.get("market_gate", "")
                if "PAUSE" in market_gate or "REVIEW" in market_gate:
                    # Risk-On should not have PAUSE/REVIEW market gates
                    findings.append({
                        "severity": "Critical",
                        "ticker": card["ticker"],
                        "message": f"Risk-On regime but BUY ${order['price']:.2f} market gate is {market_gate}",
                    })

    return findings


# ---------------------------------------------------------------------------
# Report building
# ---------------------------------------------------------------------------

def build_report(ref_date, checks):
    """Build the verification report markdown."""
    date_str = ref_date.strftime("%Y-%m-%d") if ref_date else "unknown"

    # Determine overall verdict
    has_critical = False
    for _, check_findings in checks:
        for f in check_findings:
            if f["severity"] == "Critical":
                has_critical = True
                break
        if has_critical:
            break

    overall = "ISSUES" if has_critical else "PASS"

    lines = [
        f"# Morning Briefing Verification — {date_str}\n",
        f"## Verdict: {overall}\n",
        "## Verification Summary\n",
        "| Check | Result | Details |",
        "| :--- | :--- | :--- |",
    ]

    total_critical = 0
    total_minor = 0

    for i, (name, check_findings) in enumerate(checks):
        critical = sum(1 for f in check_findings if f["severity"] == "Critical")
        minor = sum(1 for f in check_findings if f["severity"] == "Minor")
        total_critical += critical
        total_minor += minor
        skipped = sum(1 for f in check_findings if "SKIPPED" in f.get("message", ""))
        result = "FAIL" if critical > 0 else "PASS"

        detail_parts = []
        if critical > 0:
            detail_parts.append(f"{critical} critical")
        if minor > 0:
            detail_parts.append(f"{minor} minor")
        if skipped > 0:
            detail_parts.append(f"{skipped} skipped")
        if not detail_parts:
            detail_parts.append("Clean")
        detail = ", ".join(detail_parts)

        lines.append(f"| {i+1}. {name} | {result} | {detail} |")

    lines.append("")

    # Detailed sections for each check
    check_headers = [
        ("P/L Math Errors",
         "| Ticker | Field | Detail | Severity |",
         "| :--- | :--- | :--- | :--- |"),
        ("Day Count Errors",
         "| Ticker | Detail | Severity |",
         "| :--- | :--- | :--- |"),
        ("Verdict Errors",
         "| Ticker | Detail | Severity |",
         "| :--- | :--- | :--- |"),
        ("Earnings Gate Errors",
         "| Ticker | Detail | Severity |",
         "| :--- | :--- | :--- |"),
        ("Regime Classification Errors",
         "| Metric | Detail | Severity |",
         "| :--- | :--- | :--- |"),
        ("Entry Gate Errors",
         "| Ticker | Detail | Severity |",
         "| :--- | :--- | :--- |"),
        ("Data Mismatches",
         "| Ticker | Detail | Severity |",
         "| :--- | :--- | :--- |"),
        ("Coverage Gaps",
         "| Description | Severity |",
         "| :--- | :--- |"),
        ("Cross-Domain Consistency Issues",
         "| Description | Tickers | Severity |",
         "| :--- | :--- | :--- |"),
    ]

    for i, (name, check_findings) in enumerate(checks):
        title, header, align = check_headers[i]
        lines.append(f"## Check {i+1}: {title}\n")

        if not check_findings:
            lines.append(f"No {title.lower()} found.\n")
            continue

        lines.append(header)
        lines.append(align)

        for f in check_findings:
            ticker = f.get("ticker", "")
            msg = f.get("message", "")
            sev = f.get("severity", "")

            if i == 0:
                # P/L Math: ticker, field, detail, severity
                field = msg.split(":")[0] if ":" in msg else msg
                detail = msg.split(":", 1)[1].strip() if ":" in msg else ""
                lines.append(f"| {ticker} | {field} | {detail} | {sev} |")
            elif i in (7,):
                # Coverage: description, severity
                lines.append(f"| {ticker}: {msg} | {sev} |")
            elif i in (8,):
                # Cross-domain: description, tickers, severity
                lines.append(f"| {msg} | {ticker} | {sev} |")
            else:
                # Default: ticker, detail, severity
                lines.append(f"| {ticker} | {msg} | {sev} |")

        lines.append("")

    # Quality Notes
    lines.append("## Quality Notes\n")
    lines.append(f"Verification run: {date_str}")
    lines.append(f"Total findings: {total_critical} critical, {total_minor} minor")
    if total_critical == 0:
        lines.append("All critical checks passed. Minor notes are informational only.")
    else:
        lines.append(f"**{total_critical} critical issue(s) require attention.**")
    lines.append("")

    return "\n".join(lines)


def print_summary(checks):
    """Print summary to stdout for agent to capture."""
    total_critical = 0
    total_minor = 0
    failed_checks = []

    for name, check_findings in checks:
        critical = sum(1 for f in check_findings if f["severity"] == "Critical")
        minor = sum(1 for f in check_findings if f["severity"] == "Minor")
        total_critical += critical
        total_minor += minor
        if critical > 0:
            failed_checks.append(name)

    verdict = "ISSUES" if total_critical > 0 else "PASS"
    passed = sum(1 for _, fs in checks if not any(f["severity"] == "Critical" for f in fs))

    print(f"\n--- Verification Complete ---")
    print(f"Verdict: {verdict}")
    print(f"Checks passed: {passed}/9")
    print(f"Issues found: {total_critical + total_minor} ({total_critical} critical, {total_minor} minor)")
    if failed_checks:
        print(f"Failed checks: {', '.join(failed_checks)}")
    print(f"Output: {OUTPUT}")


def write_error_report(message):
    """Write a minimal error report when inputs are missing."""
    report = f"# Morning Briefing Verification\n\n## Verdict: ERROR\n\n{message}\n"
    OUTPUT.write_text(report, encoding="utf-8")
    print(f"Error: {message}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Existence checks
    for path, label in [
        (BRIEFING, "morning-briefing.md"),
        (CONDENSED, "morning-briefing-condensed.md"),
        (PORTFOLIO, "portfolio.json"),
    ]:
        if not path.exists():
            write_error_report(f"{label} not found — cannot verify")
            sys.exit(1)

    portfolio = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
    condensed = CONDENSED.read_text(encoding="utf-8")
    briefing = BRIEFING.read_text(encoding="utf-8")

    ref_date = extract_reference_date(condensed)
    condensed_positions = parse_condensed_positions(condensed)
    active_cards, watchlist_cards = parse_briefing_cards(briefing)

    print(f"Reference date: {ref_date}")
    print(f"Active cards: {len(active_cards)} ({', '.join(c['ticker'] for c in active_cards)})")
    print(f"Watchlist cards: {len(watchlist_cards)} ({', '.join(c['ticker'] for c in watchlist_cards)})")

    checks = [
        ("P/L Math", check_pl_math(portfolio, condensed_positions, active_cards)),
        ("Day Count Math", check_day_count(portfolio, ref_date, active_cards)),
        ("Verdict Assignment", check_verdicts(portfolio, active_cards, ref_date)),
        ("Earnings Gate Logic", check_earnings_gate(condensed, active_cards, watchlist_cards)),
        ("Regime Classification", check_regime(condensed, briefing)),
        ("Entry Gate Logic", check_entry_gates(portfolio, condensed, active_cards, watchlist_cards)),
        ("Data Consistency", check_data_consistency(portfolio, condensed, condensed_positions, active_cards, watchlist_cards, briefing)),
        ("Coverage & Completeness", check_coverage(portfolio, briefing, active_cards, watchlist_cards)),
        ("Cross-Domain Consistency", check_cross_domain(active_cards, watchlist_cards, briefing, condensed)),
    ]

    report = build_report(ref_date, checks)
    OUTPUT.write_text(report, encoding="utf-8")
    print_summary(checks)


if __name__ == "__main__":
    main()
