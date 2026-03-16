#!/usr/bin/env python3
"""Exit Review Pre-Analyst — Phase 2 mechanical verdict engine for exit-review workflow.

Parses exit-review-raw.md, applies the 18-point verdict ruleset in deterministic
Python, builds the exit review matrix + per-position detail + cross-checks, and
writes exit-review-pre-analyst.md for the LLM analyst to add qualitative reasoning.

Usage: python3 tools/exit_review_pre_analyst.py
"""

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared_utils import load_cycle_timing

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = PROJECT_ROOT / "exit-review-raw.md"
PORTFOLIO_PATH = PROJECT_ROOT / "portfolio.json"
OUTPUT_PATH = PROJECT_ROOT / "exit-review-pre-analyst.md"

# ---------------------------------------------------------------------------
# Thresholds (module-level constants)
# ---------------------------------------------------------------------------

TIME_STOP_EXCEEDED_DAYS = 60
TIME_STOP_APPROACHING_DAYS = 45

SQUEEZE_HIGH_THRESHOLD = 60
RSI_BEARISH_THRESHOLD = 40
RSI_BULLISH_THRESHOLD = 50

RECOVERY_NEAR_BREAKEVEN_PCT = -10.0

PROFIT_TARGET_EXCEEDED_PCT = 12.0
PROFIT_TARGET_AT_TARGET_PCT = 10.0
PROFIT_TARGET_APPROACHING_PCT = 7.0

EARNINGS_GATED_DAYS = 7
EARNINGS_APPROACHING_DAYS = 14


# ---------------------------------------------------------------------------
# Section 1: Parsing
# ---------------------------------------------------------------------------

def split_table_row(line):
    """Split a markdown table row into columns, stripping padding."""
    cols = [p.strip() for p in line.split("|")]
    if cols and cols[0] == "":
        cols = cols[1:]
    if cols and cols[-1] == "":
        cols = cols[:-1]
    return cols


def validate_inputs():
    """Check inputs exist and load them. Returns (raw_text, portfolio) or exits."""
    if not RAW_PATH.exists():
        print(f"*Error: {RAW_PATH.name} not found — run exit_review_gatherer.py first*",
              file=sys.stderr)
        sys.exit(1)
    raw_text = RAW_PATH.read_text(encoding="utf-8")

    if not PORTFOLIO_PATH.exists():
        print(f"*Error: {PORTFOLIO_PATH.name} not found*", file=sys.stderr)
        sys.exit(1)
    try:
        portfolio = json.loads(PORTFOLIO_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"*Error: {PORTFOLIO_PATH.name} malformed JSON: {e}*", file=sys.stderr)
        sys.exit(1)

    return raw_text, portfolio


def extract_report_date(raw_text):
    """Parse date from '# Exit Review Raw Data — YYYY-MM-DD'. Returns datetime.date."""
    m = re.search(r"# Exit Review Raw Data — (\d{4}-\d{2}-\d{2})", raw_text)
    if m:
        return date.fromisoformat(m.group(1))
    print("Warning: Could not parse date from exit-review-raw.md header, "
          "falling back to today()", file=sys.stderr)
    return date.today()


def parse_position_summary(raw_text):
    """Parse Position Summary table → list[dict].
    Supports both 11-column (v2.0.0 with Bullets Used) and 10-column (v1.0.0) formats."""
    rows = []
    in_table = False
    has_bullets_col = None  # detected from header

    for line in raw_text.split("\n"):
        stripped = line.strip()
        if "## Position Summary" in stripped:
            in_table = True
            continue
        if in_table and stripped.startswith("## "):
            break
        if in_table and stripped.startswith("---"):
            break
        if not in_table or not stripped.startswith("|"):
            continue

        # Detect column format from header
        if stripped.startswith("| Ticker"):
            has_bullets_col = "Bullets Used" in stripped
            continue
        if stripped.startswith("| :"):
            continue

        cols = split_table_row(stripped)

        # 11-col (v2.0.0): Ticker, Shares, Avg, Current, P/L%, Entry, Days, TimeStop, Bullets, Target, Note
        # 10-col (v1.0.0): Ticker, Shares, Avg, Current, P/L%, Entry, Days, TimeStop, Target, Note
        min_cols = 11 if has_bullets_col else 10
        if len(cols) < min_cols:
            continue

        try:
            current_str = cols[3].replace("$", "").replace(",", "")
            current = float(current_str) if current_str != "N/A" else None

            pl_str = cols[4].replace("%", "").replace("+", "")
            pl_pct = float(pl_str) if pl_str != "N/A" else None

            if has_bullets_col:
                row_data = {
                    "ticker": cols[0],
                    "shares": int(float(cols[1])),
                    "avg_cost": float(cols[2].replace("$", "").replace(",", "")),
                    "current": current,
                    "pl_pct": pl_pct,
                    "entry_date": cols[5],
                    "days_held_str": cols[6],
                    "time_stop_str": cols[7],
                    "bullets_str": cols[8],
                    "target_str": cols[9],
                    "note": cols[10] if len(cols) > 10 else "—",
                }
            else:
                # v1.0.0 — no Bullets Used column, fill from portfolio.json later
                row_data = {
                    "ticker": cols[0],
                    "shares": int(float(cols[1])),
                    "avg_cost": float(cols[2].replace("$", "").replace(",", "")),
                    "current": current,
                    "pl_pct": pl_pct,
                    "entry_date": cols[5],
                    "days_held_str": cols[6],
                    "time_stop_str": cols[7],
                    "bullets_str": "",  # filled below from portfolio.json
                    "target_str": cols[8],
                    "note": cols[9] if len(cols) > 9 else "—",
                }

            rows.append(row_data)
        except (ValueError, IndexError):
            continue

    return rows


def parse_per_ticker_data(raw_text):
    """Parse per-ticker sections from exit-review-raw.md.
    Returns dict of {ticker: {earnings, technical, short_interest, identity, news}}."""
    tickers = {}
    lines = raw_text.split("\n")

    # Find "## Per-Ticker Exit Data" section
    start_idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("## Per-Ticker Exit Data"):
            start_idx = i + 1
            break

    if start_idx is None:
        return tickers

    # Split by ### TICKER headers
    current_ticker = None
    current_lines = []

    for i in range(start_idx, len(lines)):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("### ") and not stripped.startswith("#### "):
            if current_ticker:
                tickers[current_ticker] = _parse_ticker_sections(current_lines)
            current_ticker = stripped[4:].strip()
            current_lines = []
        elif stripped.startswith("## ") and not stripped.startswith("### "):
            # New top-level section — stop
            break
        else:
            current_lines.append(line)

    if current_ticker:
        tickers[current_ticker] = _parse_ticker_sections(current_lines)

    return tickers


def _parse_ticker_sections(lines):
    """Parse sub-sections within a ticker's exit data."""
    result = {
        "earnings": "",
        "technical": "",
        "short_interest": "",
        "identity": "",
        "news": "",
    }

    section_map = {
        "Earnings": "earnings",
        "Technical Signals": "technical",
        "Short Interest": "short_interest",
        "Identity Context": "identity",
        "Recent News": "news",
    }

    current_key = None
    current_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#### "):
            if current_key:
                result[current_key] = "\n".join(current_lines).strip()
            header = stripped[5:].strip()
            current_key = section_map.get(header)
            current_lines = []
        elif current_key is not None:
            current_lines.append(line)

    if current_key:
        result[current_key] = "\n".join(current_lines).strip()

    return result


def parse_technical_signals(text):
    """Parse technical signals from technical_scanner output.
    Returns dict with rsi, macd_value, macd_signal, overall_score, momentum_label."""
    result = {
        "rsi": None,
        "macd_value": None,
        "macd_signal": None,
        "overall_score": 0,
        "momentum_label": "Unknown",
    }

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue

        cols = split_table_row(stripped)
        if len(cols) < 2:
            continue

        indicator = cols[0].replace("*", "").strip()
        value = cols[1].replace("*", "").strip()

        # RSI
        if "RSI" in indicator and "(" in indicator:
            try:
                result["rsi"] = float(value)
            except ValueError:
                pass

        # MACD
        if indicator == "MACD" or indicator.startswith("MACD"):
            try:
                result["macd_value"] = float(value)
            except ValueError:
                pass
            if len(cols) >= 3:
                signal_text = cols[2].replace("*", "").strip()
                result["macd_signal"] = signal_text

        # Overall Signal
        if "Overall Signal" in indicator or "Overall" in indicator:
            # Match pattern like "+2 Bullish" or "-3 Bearish"
            m = re.search(r"([+-]?\d+)\s+(.+)", value)
            if m:
                result["overall_score"] = int(m.group(1))
                result["momentum_label"] = m.group(2).strip()
            else:
                # Try just the number
                try:
                    result["overall_score"] = int(value)
                except ValueError:
                    pass

    return result


def parse_earnings_data(text):
    """Parse earnings data from earnings_analyzer output.
    Returns dict with earnings_date (str or None), days_until (int or None)."""
    result = {"earnings_date": None, "days_until": None}

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue

        cols = split_table_row(stripped)
        if len(cols) < 2:
            continue

        label = cols[0].strip()
        value = cols[1].strip()

        if "Next Earnings" in label or "Earnings Date" in label:
            # Try to parse date
            m = re.search(r"(\d{4}-\d{2}-\d{2})", value)
            if m:
                result["earnings_date"] = m.group(1)

        if "Days Until" in label:
            try:
                result["days_until"] = int(value)
            except ValueError:
                pass

    return result


def parse_short_interest_data(text):
    """Parse short interest from short_interest output.
    Returns dict with squeeze_score (int), short_pct (float or None)."""
    result = {"squeeze_score": 0, "short_pct": None}

    # Look for squeeze score
    m = re.search(r"score\s+(\d+)/100", text, re.IGNORECASE)
    if m:
        result["squeeze_score"] = int(m.group(1))

    # Look for short % in table
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cols = split_table_row(stripped)
        if len(cols) < 2:
            continue
        label = cols[0].strip()
        value = cols[1].strip()

        if "Short % of Float" in label or "Short Interest" in label:
            try:
                result["short_pct"] = float(value.replace("%", ""))
            except ValueError:
                pass

    return result


# ---------------------------------------------------------------------------
# Section 2: Classification & Computation
# ---------------------------------------------------------------------------

def compute_days_held(entry_date_str, as_of_date):
    """Compute days held from entry_date relative to as_of_date.
    Returns (days_int, display_str, is_pre_strategy).
    Local version — uses as_of_date parameter, NOT date.today()."""
    if entry_date_str.startswith("pre-"):
        return None, f">{TIME_STOP_EXCEEDED_DAYS} days (pre-strategy)", True
    try:
        entry = datetime.strptime(entry_date_str, "%Y-%m-%d").date()
        days = (as_of_date - entry).days
        return days, str(days), False
    except ValueError:
        return None, "Unknown", False


def compute_time_stop(days_held, is_pre_strategy):
    """Compute time stop status."""
    if is_pre_strategy:
        return "EXCEEDED"
    if days_held is None:
        return "Unknown"
    if days_held > TIME_STOP_EXCEEDED_DAYS:
        return "EXCEEDED"
    if days_held >= TIME_STOP_APPROACHING_DAYS:
        return "APPROACHING"
    return "WITHIN"


def classify_position(ticker, portfolio, pl_pct):
    """Classify a position: is_recovery, is_pre_strategy, effective_recovery.
    effective_recovery = False if recovery but P/L > 0% (reclassified)."""
    pos = portfolio.get("positions", {}).get(ticker, {})
    note = pos.get("note", "")

    is_recovery = any(kw in note.lower() for kw in ["recovery", "underwater", "pre-strategy"])
    is_pre_strategy = "pre-strategy" in note.lower() or str(pos.get("entry_date", "")).startswith("pre-")

    # Reclassify: recovery with P/L > 0% → non-recovery
    effective_recovery = is_recovery
    reclassified = False
    if is_recovery and pl_pct is not None and pl_pct > 0:
        effective_recovery = False
        reclassified = True

    return {
        "is_recovery": is_recovery,
        "is_pre_strategy": is_pre_strategy,
        "effective_recovery": effective_recovery,
        "reclassified": reclassified,
    }


def compute_pl(shares, avg_cost, current):
    """Compute deployed, P/L dollar, P/L percent."""
    deployed = shares * avg_cost
    if current is None:
        return deployed, None, None
    value = shares * current
    pl_dollar = value - deployed
    pl_pct = (pl_dollar / deployed * 100) if deployed else 0
    return deployed, pl_dollar, pl_pct


def compute_target_distance(target_str, current):
    """Compute distance to target as percentage. Returns float or None."""
    if current is None:
        return None
    # Try to extract target price from target_str
    m = re.search(r"\$([\d.]+)", target_str)
    if not m:
        return None
    try:
        target = float(m.group(1))
        return (target - current) / current * 100
    except (ValueError, ZeroDivisionError):
        return None


def compute_earnings_gate(days_to_earnings):
    """Compute earnings gate status."""
    if days_to_earnings is None:
        return "UNKNOWN"
    if days_to_earnings < EARNINGS_GATED_DAYS:
        return "GATED"
    if days_to_earnings <= EARNINGS_APPROACHING_DAYS:
        return "APPROACHING"
    return "CLEAR"


def compute_profit_target_status(pl_pct):
    """Compute profit target status."""
    if pl_pct is None:
        return "UNKNOWN"
    if pl_pct >= PROFIT_TARGET_EXCEEDED_PCT:
        return "EXCEEDED"
    if pl_pct >= PROFIT_TARGET_AT_TARGET_PCT:
        return "AT_TARGET"
    if pl_pct >= PROFIT_TARGET_APPROACHING_PCT:
        return "APPROACHING"
    return "BELOW"


def compute_momentum_label(overall_score):
    """Compute momentum label from overall technical score."""
    if overall_score >= 3:
        return "Bullish"
    if overall_score >= 1:
        return "Neutral-Bull"
    if overall_score >= -1:
        return "Neutral"
    if overall_score >= -3:
        return "Neutral-Bear"
    return "Bearish"


def parse_bullets_status(bullets_str, note):
    """Determine if position is fully loaded or still building.
    Returns (is_fully_loaded, is_still_building, bullets_used_int, max_bullets_int)."""
    # Parse bullets used and max from "N/M" pattern
    m = re.match(r"(\d+)/(\d+)", bullets_str)
    if not m:
        return False, False, None, None

    used = int(m.group(1))
    max_b = int(m.group(2))

    # Check for pool exhausted
    is_exhausted = "pool exhausted" in bullets_str.lower() or "exhausted" in (note or "").lower()

    is_fully_loaded = used >= max_b or is_exhausted
    is_still_building = not is_fully_loaded

    return is_fully_loaded, is_still_building, used, max_b


# ---------------------------------------------------------------------------
# Section 3: Verdict Engine (18-point ruleset, first match wins)
# ---------------------------------------------------------------------------

def compute_verdict(pos_data):
    """Apply the 18-point verdict ruleset. Returns (verdict, rule_num, reason, flags)."""
    pl_pct = pos_data["pl_pct"]
    classification = pos_data["classification"]
    earnings_gate = pos_data["earnings_gate"]
    time_stop = pos_data["time_stop"]
    tech = pos_data["technical"]
    short_data = pos_data["short_interest"]
    bullets = pos_data["bullets"]

    is_recovery = classification["effective_recovery"]
    rsi = tech["rsi"]
    macd_signal = tech["macd_signal"] or ""
    overall_score = tech["overall_score"]
    squeeze_score = short_data["squeeze_score"]
    is_fully_loaded = bullets["is_fully_loaded"]
    is_still_building = bullets["is_still_building"]

    flags = []

    # --- GATED rules (fire first) ---
    if earnings_gate == "GATED":
        # Rule 1: non-recovery + GATED + P/L > 0%
        if not is_recovery and pl_pct is not None and pl_pct > 0:
            return "REDUCE", "1", "Profitable + GATED — lock in gains before binary event", flags

        # Rule 2: non-recovery + GATED + P/L <= 0%
        if not is_recovery and (pl_pct is None or pl_pct <= 0):
            sub = "still building" if is_still_building else "fully loaded"
            return "HOLD", "2", f"Underwater + GATED — hold shares, pause orders ({sub})", flags

        # Rule 3 candidate: recovery + GATED + thesis (qualitative — LLM override)
        # Python defaults to Rule 4 or 5, flags for LLM
        if is_recovery:
            if pl_pct is not None and pl_pct > RECOVERY_NEAR_BREAKEVEN_PCT:
                # Rule 4: recovery + GATED + no thesis + P/L > -10%
                flags.append("Rule 3 CANDIDATE — LLM: evaluate thesis from identity/news context")
                return "REDUCE", "4", "Recovery + GATED + near breakeven — protect near-recovery", flags
            else:
                # Rule 5: recovery + GATED + no thesis + P/L <= -10%
                # No Rule 3 flag — verdict is already HOLD, no override possible
                return "HOLD", "5", "Recovery + GATED + deep underwater — marginal downside limited", flags

    # --- Profit target rules ---
    if pl_pct is not None:
        # Rule 6a: P/L >= 12%
        if pl_pct >= PROFIT_TARGET_EXCEEDED_PCT:
            return "REDUCE", "6a", f"P/L {pl_pct:.1f}% exceeds target range — take profits", flags

        # Rule 6: 10% <= P/L < 12%
        if pl_pct >= PROFIT_TARGET_AT_TARGET_PCT:
            return "HOLD", "6", f"P/L {pl_pct:.1f}% at target range — hold for full target", flags

        # Rule 7: 7% <= P/L < 10%
        if pl_pct >= PROFIT_TARGET_APPROACHING_PCT:
            return "HOLD", "7", f"P/L {pl_pct:.1f}% approaching target — do not exit", flags

    # --- Recovery rules (non-GATED) ---
    if is_recovery:
        # Rule 8: recovery + squeeze catalyst or bullish relief rally
        has_squeeze = squeeze_score >= SQUEEZE_HIGH_THRESHOLD
        has_relief = (rsi is not None and rsi > 30 and overall_score > -4)
        if has_squeeze or has_relief:
            catalysts = []
            if has_squeeze:
                catalysts.append(f"squeeze {squeeze_score}/100")
            if has_relief:
                catalysts.append(f"RSI {rsi:.0f}, score {overall_score:+d}")
            return "HOLD", "8", f"Recovery + catalyst: {', '.join(catalysts)}", flags

        # Rule 9: recovery + bearish across all signals
        all_bearish = (
            (rsi is not None and rsi < RSI_BEARISH_THRESHOLD) and
            overall_score <= -4 and
            squeeze_score < SQUEEZE_HIGH_THRESHOLD
        )
        if all_bearish:
            return "MONITOR", "9", "Recovery + all bearish — no catalyst, exit consideration", flags

        # Rule 10: recovery + other
        return "HOLD", "10", "Recovery — default hold, time stop informational only", flags

    # --- Time stop rules (non-recovery, non-GATED) ---
    if time_stop == "EXCEEDED":
        # Rule 11: EXCEEDED + RSI < 40 + CLEAR
        if rsi is not None and rsi < RSI_BEARISH_THRESHOLD and earnings_gate in ("CLEAR", "UNKNOWN"):
            return "EXIT", "11", f"Time exceeded + bearish RSI {rsi:.0f} + earnings clear", flags

        # Rule 12: EXCEEDED + bullish technicals + CLEAR
        macd_bullish = ("bullish" in macd_signal.lower() or "above" in macd_signal.lower())
        if (rsi is not None and rsi > RSI_BULLISH_THRESHOLD and
                macd_bullish and earnings_gate in ("CLEAR", "UNKNOWN")):
            return "HOLD", "12", f"Time exceeded but bullish: RSI {rsi:.0f}, MACD bullish + clear", flags

        # Rule 13: EXCEEDED + earnings APPROACHING
        if earnings_gate == "APPROACHING":
            return "REDUCE", "13", "Time exceeded + earnings approaching — partial exit", flags

        # Rule 14: EXCEEDED + other
        return "REDUCE", "14", "Time exceeded without clear bullish case", flags

    # Rule 15: APPROACHING
    if time_stop == "APPROACHING":
        reason = "Time approaching (45-60 days)"
        if earnings_gate == "APPROACHING":
            reason += " — earnings also approaching, flag for review"
        return "MONITOR", "15", reason, flags

    # Rule 16: WITHIN
    if time_stop == "WITHIN" or time_stop == "Unknown":
        reason = "Within time window — standard tracking"
        if earnings_gate == "APPROACHING":
            reason += " — earnings approaching, flag for review"
        return "MONITOR", "16", reason, flags

    # Fallback (should not reach here)
    return "MONITOR", "16", "Default — standard tracking", flags


# ---------------------------------------------------------------------------
# Section 3b: Cycle Speed Annotation (post-check)
# ---------------------------------------------------------------------------

def _cycle_speed_annotation(ticker, verdict, days_held):
    """Post-check: annotate verdict with cycle speed opportunity cost.
    Returns annotation string or None."""
    ct = load_cycle_timing(ticker)
    if ct is None:
        return None

    median_deep = ct.get("median_deep")
    total_cycles = ct.get("total_cycles", 0)

    if median_deep is None or total_cycles < 3:
        return None

    expected_cycle = median_deep + 3  # recovery buffer
    if days_held is not None and days_held > expected_cycle * 3 and verdict == "MONITOR":
        cycles_missed = days_held // expected_cycle
        return (f"Opportunity cost: {cycles_missed} cycles could have completed in "
                f"{days_held}d (expected {expected_cycle}d/cycle). Consider REDUCE.")

    return None


# ---------------------------------------------------------------------------
# Section 4: Cross-Checks (8 invariant checks)
# ---------------------------------------------------------------------------

def cross_check_verdicts(positions):
    """Run 8 invariant cross-checks on computed verdicts.
    Returns list of {check, result, detail}."""
    checks = []

    # Check 1: No GATED profitable non-recovery gets HOLD
    for p in positions:
        if (p["earnings_gate"] == "GATED" and
                not p["classification"]["effective_recovery"] and
                p["pl_pct"] is not None and p["pl_pct"] > 0):
            if p["verdict"] != "REDUCE":
                checks.append({
                    "check": "GATED profitable must REDUCE",
                    "result": "FAIL",
                    "detail": f"{p['ticker']}: {p['verdict']} but Rule 1 requires REDUCE"
                })

    # Check 2: No GATED underwater non-recovery gets REDUCE
    for p in positions:
        if (p["earnings_gate"] == "GATED" and
                not p["classification"]["effective_recovery"] and
                (p["pl_pct"] is None or p["pl_pct"] <= 0)):
            if p["verdict"] == "REDUCE":
                checks.append({
                    "check": "GATED underwater must HOLD",
                    "result": "FAIL",
                    "detail": f"{p['ticker']}: REDUCE but Rule 2 requires HOLD"
                })

    # Check 3: No recovery position gets EXIT
    for p in positions:
        if p["classification"]["effective_recovery"] and p["verdict"] == "EXIT":
            checks.append({
                "check": "Recovery never EXIT",
                "result": "FAIL",
                "detail": f"{p['ticker']}: EXIT but recovery positions max out at MONITOR"
            })

    # Check 4: P/L 7-12% (non-GATED) must not EXIT
    for p in positions:
        if (p["pl_pct"] is not None and
                PROFIT_TARGET_APPROACHING_PCT <= p["pl_pct"] < PROFIT_TARGET_EXCEEDED_PCT and
                p["earnings_gate"] != "GATED" and
                p["verdict"] == "EXIT"):
            checks.append({
                "check": "7-12% P/L must not EXIT",
                "result": "FAIL",
                "detail": f"{p['ticker']}: EXIT with P/L {p['pl_pct']:.1f}% — Rules 6/7 protect"
            })

    # Check 5: P/L >= 12% must REDUCE (non-GATED)
    for p in positions:
        if (p["pl_pct"] is not None and
                p["pl_pct"] >= PROFIT_TARGET_EXCEEDED_PCT and
                p["earnings_gate"] != "GATED" and
                p["verdict"] != "REDUCE"):
            checks.append({
                "check": "P/L >= 12% must REDUCE",
                "result": "FAIL",
                "detail": f"{p['ticker']}: {p['verdict']} with P/L {p['pl_pct']:.1f}% — Rule 6a"
            })

    # Check 6: Recovery reclassified if P/L > 0%
    for p in positions:
        if (p["classification"]["is_recovery"] and
                p["pl_pct"] is not None and p["pl_pct"] > 0 and
                not p["classification"]["reclassified"]):
            checks.append({
                "check": "Recovery with P/L>0 must reclassify",
                "result": "FAIL",
                "detail": f"{p['ticker']}: recovery but P/L {p['pl_pct']:.1f}% > 0% — should reclassify"
            })

    # Check 7: Time stop EXCEEDED non-recovery must not be MONITOR
    for p in positions:
        if (p["time_stop"] == "EXCEEDED" and
                not p["classification"]["effective_recovery"] and
                p["verdict"] == "MONITOR"):
            checks.append({
                "check": "EXCEEDED non-recovery must not MONITOR",
                "result": "FAIL",
                "detail": f"{p['ticker']}: MONITOR but EXCEEDED requires action (Rules 11-14)"
            })

    # Check 8: Every position has all 4 criteria
    for p in positions:
        missing = []
        if p.get("time_stop") is None:
            missing.append("Time Stop")
        if p.get("profit_target_status") is None:
            missing.append("Profit Target")
        if p.get("earnings_gate") is None:
            missing.append("Earnings Gate")
        if p.get("momentum_label") is None:
            missing.append("Momentum")
        if missing:
            checks.append({
                "check": "All 4 criteria present",
                "result": "FAIL",
                "detail": f"{p['ticker']}: missing {', '.join(missing)}"
            })

    # If all passed
    if not checks:
        checks.append({
            "check": "All 8 invariant checks",
            "result": "PASS",
            "detail": "No violations found"
        })

    return checks


# ---------------------------------------------------------------------------
# Section 5: Report Assembly
# ---------------------------------------------------------------------------

def fmt_pct(val):
    """Format percentage with sign."""
    if val is None:
        return "N/A"
    return f"+{val:.1f}%" if val >= 0 else f"{val:.1f}%"


def fmt_dollar(val):
    """Format dollar value with sign."""
    if val is None:
        return "N/A"
    return f"+${val:.2f}" if val >= 0 else f"-${abs(val):.2f}"


def verdict_priority(verdict):
    """Sort priority: EXIT=0, REDUCE=1, HOLD=2, MONITOR=3."""
    return {"EXIT": 0, "REDUCE": 1, "HOLD": 2, "MONITOR": 3}.get(verdict, 4)


def build_exit_review_matrix(positions):
    """Build the sorted exit review matrix table."""
    sorted_pos = sorted(positions, key=lambda p: (verdict_priority(p["verdict"]), p["ticker"]))

    rows = []
    rows.append("| Ticker | Days Held | Time Stop | P/L % | P/L $ | Target Dist "
                "| Earnings | Momentum | Squeeze | Verdict | Rule |")
    rows.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for p in sorted_pos:
        squeeze = f"{p['short_interest']['squeeze_score']}/100" if p['short_interest']['squeeze_score'] else "N/A"
        earnings_str = p["earnings_gate"]
        if p["earnings_data"]["days_until"] is not None:
            earnings_str += f" ({p['earnings_data']['days_until']}d)"

        rows.append(
            f"| {p['ticker']} | {p['days_display']} | {p['time_stop']} "
            f"| {fmt_pct(p['pl_pct'])} | {fmt_dollar(p['pl_dollar'])} "
            f"| {fmt_pct(p['target_distance'])} "
            f"| {earnings_str} | {p['momentum_label']} ({p['technical']['overall_score']:+d}) "
            f"| {squeeze} | **{p['verdict']}** | {p['rule']} |"
        )

    return "\n".join(rows)


def build_per_position_detail(positions):
    """Build per-position detail sections."""
    sorted_pos = sorted(positions, key=lambda p: (verdict_priority(p["verdict"]), p["ticker"]))
    parts = []

    for p in sorted_pos:
        ticker = p["ticker"]
        verdict = p["verdict"]
        rule = p["rule"]

        parts.append(f"### {ticker} — {verdict} (Rule {rule})")
        parts.append("")

        # Exit Criteria Summary table
        parts.append("**Exit Criteria Summary:**")
        parts.append("")
        parts.append("| Criterion | Status | Detail |")
        parts.append("| :--- | :--- | :--- |")

        # Time Stop
        entry_str = p["entry_date"]
        parts.append(f"| Time Stop | {p['time_stop']} | {p['days_display']} days held "
                     f"(entered {entry_str}) |")

        # Profit Target
        pt_status = p["profit_target_status"]
        target_str = p["target_str"]
        if p["pl_pct"] is not None:
            pt_detail = f"P/L {fmt_pct(p['pl_pct'])}"
            if p["target_distance"] is not None:
                pt_detail += f", target {target_str} ({fmt_pct(p['target_distance'])} from target)"
            else:
                pt_detail += f", {target_str}"
        else:
            pt_detail = "N/A"
        parts.append(f"| Profit Target | {pt_status} | {pt_detail} |")

        # Earnings Gate
        eg = p["earnings_gate"]
        ed = p["earnings_data"]
        if ed["days_until"] is not None:
            eg_detail = f"{ed['days_until']} days to earnings"
            if ed["earnings_date"]:
                eg_detail += f" ({ed['earnings_date']})"
        else:
            eg_detail = "Unknown/unavailable"
        parts.append(f"| Earnings Gate | {eg} | {eg_detail} |")

        # Momentum
        tech = p["technical"]
        rsi_str = f"RSI {tech['rsi']:.0f}" if tech["rsi"] is not None else "RSI Unknown"
        macd_str = f"MACD {tech['macd_value']:.3f}" if tech["macd_value"] is not None else "MACD Unknown"
        if tech["macd_signal"]:
            macd_str += f" ({tech['macd_signal']})"
        score_str = f"overall {tech['overall_score']:+d} {p['momentum_label']}"
        parts.append(f"| Momentum | {p['momentum_label']} | {rsi_str}, {macd_str}, {score_str} |")

        parts.append("")

        # Classification
        cl = p["classification"]
        parts.append(f"**Classification:** recovery={cl['effective_recovery']}, "
                     f"pre_strategy={cl['is_pre_strategy']}, reclassified={cl['reclassified']}")

        # Bullets
        b = p["bullets"]
        if b["bullets_used"] is not None:
            status = "fully_loaded" if b["is_fully_loaded"] else "still_building"
            parts.append(f"**Bullets:** {p['bullets_str']} → {status}")
        else:
            parts.append(f"**Bullets:** {p['bullets_str']}")

        # Verdict Trace
        parts.append(f"**Verdict Trace:** Rule {rule} — {p['reason']}")

        # Knowledge store context
        try:
            from knowledge_store import query_ticker_knowledge
            ks = query_ticker_knowledge(ticker, f"{ticker} exit sell outcome profit loss")
            if ks:
                parts.append(ks)
        except Exception:
            pass

        parts.append("")

        # LLM tasks
        parts.append("*LLM: Write 2-3 sentence Reasoning connecting data to verdict.*")
        parts.append("*LLM: Write specific Recommended Action (broker instructions).*")
        if p["flags"]:
            for flag in p["flags"]:
                parts.append(f"*LLM: {flag}*")
        if verdict in ("EXIT", "REDUCE"):
            parts.append("*LLM: Suggest rotate-to candidates from watchlist.*")
        parts.append("")

    return "\n".join(parts)


def build_capital_rotation(positions):
    """Build capital rotation skeleton for EXIT/REDUCE positions."""
    exit_reduce = [p for p in positions if p["verdict"] in ("EXIT", "REDUCE")]

    if not exit_reduce:
        return "No capital rotation needed at this time."

    rows = []
    rows.append("| Ticker | Verdict | Shares | Current Price | Capital Freed |")
    rows.append("| :--- | :--- | :--- | :--- | :--- |")

    total_freed = 0
    for p in exit_reduce:
        if p["current"] is not None:
            freed = p["shares"] * p["current"]
            total_freed += freed
            rows.append(f"| {p['ticker']} | {p['verdict']} | {p['shares']} "
                        f"| ${p['current']:.2f} | ${freed:.2f} |")
        else:
            rows.append(f"| {p['ticker']} | {p['verdict']} | {p['shares']} | N/A | N/A |")

    rows.append("")
    rows.append(f"**Total capital freed (if all executed):** ${total_freed:.2f}")

    return "\n".join(rows)


def assemble_pre_analyst(report_date, matrix, per_position, cross_checks, capital_rotation,
                         position_count, verdict_counts):
    """Assemble the complete exit-review-pre-analyst.md."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = []

    parts.append(f"# Exit Review Pre-Analyst — {report_date.isoformat()}")
    parts.append(f"*Generated: {now_str} | Tool: exit_review_pre_analyst.py*")
    parts.append("")

    # Verdict count summary
    parts.append(f"**Positions reviewed:** {position_count} | "
                 f"EXIT: {verdict_counts.get('EXIT', 0)}, "
                 f"REDUCE: {verdict_counts.get('REDUCE', 0)}, "
                 f"HOLD: {verdict_counts.get('HOLD', 0)}, "
                 f"MONITOR: {verdict_counts.get('MONITOR', 0)}")
    parts.append("")

    # Matrix
    parts.append("## Exit Review Matrix")
    parts.append("")
    parts.append(matrix)
    parts.append("")

    # Per-Position Detail
    parts.append("## Per-Position Detail")
    parts.append("")
    parts.append(per_position)

    # Cross-Check Results
    parts.append("## Cross-Check Results")
    parts.append("")
    parts.append("| Check | Result | Detail |")
    parts.append("| :--- | :--- | :--- |")
    for c in cross_checks:
        parts.append(f"| {c['check']} | {c['result']} | {c['detail']} |")
    parts.append("")

    # Capital Rotation
    parts.append("## Capital Rotation Skeleton")
    parts.append("")
    parts.append(capital_rotation)
    parts.append("")

    # LLM tasks
    parts.append("---")
    parts.append("")
    parts.append("*LLM: Write Executive Summary (2-3 sentences: positions reviewed, "
                 "verdict counts, key actions).*")
    parts.append("*LLM: Write Prioritized Recommendations (ranked list: most urgent first).*")
    parts.append("")

    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Validate and load
    raw_text, portfolio = validate_inputs()
    report_date = extract_report_date(raw_text)

    print(f"Exit Review Pre-Analyst — {report_date.isoformat()}")

    # Parse raw data
    summary_rows = parse_position_summary(raw_text)
    per_ticker = parse_per_ticker_data(raw_text)

    print(f"Parsed: {len(summary_rows)} positions, {len(per_ticker)} ticker sections")

    if not summary_rows:
        print("No positions found in raw data.", file=sys.stderr)
        sys.exit(1)

    # Backfill bullets_str from portfolio.json for v1.0.0 raw files (no Bullets Used column)
    capital = portfolio.get("capital", {})
    max_bullets = capital.get("active_bullets_max", 5)
    for row in summary_rows:
        if not row["bullets_str"]:
            ticker = row["ticker"]
            pos = portfolio.get("positions", {}).get(ticker, {})
            bullets_raw = pos.get("bullets_used", 0)
            note = pos.get("note", "")
            if isinstance(bullets_raw, int):
                row["bullets_str"] = f"{bullets_raw}/{max_bullets}"
            elif isinstance(bullets_raw, str):
                m = re.match(r"(\d+)", bullets_raw)
                if m:
                    row["bullets_str"] = f"{m.group(1)}/{max_bullets}"
                    if "pre-strategy" in bullets_raw:
                        row["bullets_str"] += " (pre-strategy)"
                else:
                    row["bullets_str"] = f"?/{max_bullets}"
            else:
                row["bullets_str"] = f"?/{max_bullets}"
            if note:
                if "exhausted" in note.lower():
                    row["bullets_str"] += ", pool exhausted"
                remaining = re.search(r'~?\$(\d+)\s*remaining', note)
                if remaining:
                    row["bullets_str"] += f", ~${remaining.group(1)} remaining"

    # Process each position
    positions = []

    for row in summary_rows:
        ticker = row["ticker"]
        shares = row["shares"]
        avg_cost = row["avg_cost"]
        current = row["current"]

        if current is None:
            print(f"  WARNING: {ticker} — missing current price, skipping")
            continue

        # Compute P/L
        deployed, pl_dollar, pl_pct = compute_pl(shares, avg_cost, current)

        # Days held (relative to report_date)
        entry_date = row["entry_date"]
        days_held, days_display, is_pre = compute_days_held(entry_date, report_date)
        time_stop = compute_time_stop(days_held, is_pre)

        # Classification
        classification = classify_position(ticker, portfolio, pl_pct)

        # Parse technical signals
        ticker_data = per_ticker.get(ticker, {})
        tech = parse_technical_signals(ticker_data.get("technical", ""))

        # Parse earnings
        earnings_data = parse_earnings_data(ticker_data.get("earnings", ""))
        earnings_gate = compute_earnings_gate(earnings_data["days_until"])

        # Parse short interest
        short_data = parse_short_interest_data(ticker_data.get("short_interest", ""))

        # Profit target status
        profit_target_status = compute_profit_target_status(pl_pct)

        # Momentum label
        momentum_label = compute_momentum_label(tech["overall_score"])

        # Bullets status
        bullets_fully, bullets_building, b_used, b_max = parse_bullets_status(
            row["bullets_str"], row["note"]
        )
        bullets = {
            "is_fully_loaded": bullets_fully,
            "is_still_building": bullets_building,
            "bullets_used": b_used,
            "max_bullets": b_max,
        }

        # Target distance
        target_distance = compute_target_distance(row["target_str"], current)

        # Build position data
        pos_data = {
            "ticker": ticker,
            "shares": shares,
            "avg_cost": avg_cost,
            "current": current,
            "deployed": deployed,
            "pl_dollar": pl_dollar,
            "pl_pct": pl_pct,
            "entry_date": entry_date,
            "days_held": days_held,
            "days_display": days_display,
            "time_stop": time_stop,
            "classification": classification,
            "technical": tech,
            "earnings_data": earnings_data,
            "earnings_gate": earnings_gate,
            "short_interest": short_data,
            "profit_target_status": profit_target_status,
            "momentum_label": momentum_label,
            "bullets": bullets,
            "bullets_str": row["bullets_str"],
            "target_str": row["target_str"],
            "target_distance": target_distance,
        }

        # Compute verdict
        verdict, rule, reason, flags = compute_verdict(pos_data)
        pos_data["verdict"] = verdict
        pos_data["rule"] = rule
        pos_data["reason"] = reason
        pos_data["flags"] = flags

        # Post-check: cycle speed annotation
        cycle_annotation = _cycle_speed_annotation(ticker, verdict, days_held)
        if cycle_annotation:
            pos_data["flags"].append(cycle_annotation)

        positions.append(pos_data)
        print(f"  {ticker}: {verdict} (Rule {rule})")

    # Cross-checks
    cross_checks = cross_check_verdicts(positions)
    for c in cross_checks:
        if c["result"] == "FAIL":
            print(f"  CROSS-CHECK FAIL: {c['detail']}")

    # Verdict counts
    verdict_counts = {}
    for p in positions:
        v = p["verdict"]
        verdict_counts[v] = verdict_counts.get(v, 0) + 1

    # Build report sections
    matrix = build_exit_review_matrix(positions)
    per_position = build_per_position_detail(positions)
    capital_rotation = build_capital_rotation(positions)

    # Assemble
    content = assemble_pre_analyst(
        report_date, matrix, per_position, cross_checks, capital_rotation,
        len(positions), verdict_counts
    )

    OUTPUT_PATH.write_text(content, encoding="utf-8")
    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"\nOutput: exit-review-pre-analyst.md ({size_kb:.1f} KB)")
    print(f"Verdicts: {verdict_counts}")


if __name__ == "__main__":
    main()
