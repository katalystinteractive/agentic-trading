#!/usr/bin/env python3
"""Status Pre-Analyst — Phase 2 mechanical pre-processor for the status workflow.

Reads status-raw.md and portfolio.json. Produces status-pre-analyst.md with
deterministic heat map, fill alerts, per-position data, watchlist, capital
summary, and actionable items skeleton. The LLM analyst reads this output
and adds qualitative narratives only.

Usage: python3 tools/status_pre_analyst.py
"""

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

# Same-directory imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
from news_sweep_collector import split_table_row

ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = ROOT / "status-raw.md"
PORTFOLIO_PATH = ROOT / "portfolio.json"
OUTPUT_PATH = ROOT / "status-pre-analyst.md"


# ---------------------------------------------------------------------------
# Input Validation
# ---------------------------------------------------------------------------

def validate_inputs():
    """Check inputs exist and load them. Returns (raw_text, portfolio) or exits."""
    if not RAW_PATH.exists():
        print(f"*Error: {RAW_PATH.name} not found — run status_gatherer.py first*", file=sys.stderr)
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
    """Parse date from '# Status Raw Data — YYYY-MM-DD'. Returns datetime.date."""
    m = re.search(r"# Status Raw Data — (\d{4}-\d{2}-\d{2})", raw_text)
    if m:
        return date.fromisoformat(m.group(1))
    # Fallback to today — warn since this affects day-count arithmetic
    print("Warning: Could not parse date from status-raw.md header, falling back to today()", file=sys.stderr)
    return date.today()


# ---------------------------------------------------------------------------
# Raw Data Parsing
# ---------------------------------------------------------------------------

def parse_raw_data(raw_text):
    """Master parser for status-raw.md → structured dict.

    Returns dict with keys:
    - active_positions: list of dicts (from Active Positions table)
    - pending_orders: list of dicts (from Pending Orders table)
    - watchlist_prices: list of dicts (from Watchlist Prices table)
    - capital_raw: dict (from Capital Summary table)
    - ticker_details: dict of ticker -> {identity, wick_levels, trade_log, structural}
    - watchlist_levels: dict of ticker -> section text
    - velocity_bounce: str (raw text of Velocity & Bounce section)
    """
    lines = raw_text.split("\n")
    result = {
        "active_positions": [],
        "pending_orders": [],
        "watchlist_prices": [],
        "capital_raw": {},
        "ticker_details": {},
        "watchlist_levels": {},
        "velocity_bounce": "",
    }

    # Split into major sections by ## headers
    sections = _split_sections(lines)

    # Parse Portfolio Status subsections
    ps_section = sections.get("Portfolio Status", [])
    ps_subsections = _split_subsections(ps_section)

    result["active_positions"] = _parse_active_positions(ps_subsections.get("Active Positions", []))
    result["watchlist_prices"] = _parse_watchlist_prices(ps_subsections.get("Watchlist Prices", []))
    result["pending_orders"] = _parse_pending_orders(
        ps_subsections.get("Pending Orders", []),
        result["active_positions"],
        result["watchlist_prices"]
    )
    result["capital_raw"] = _parse_capital_raw(ps_subsections.get("Capital Summary", []))

    # Parse Per-Ticker Detail
    td_section = sections.get("Per-Ticker Detail", [])
    result["ticker_details"] = _parse_ticker_details(td_section)

    # Parse Watchlist Levels
    wl_section = sections.get("Watchlist Levels", [])
    result["watchlist_levels"] = _parse_watchlist_levels(wl_section)

    # Parse Velocity & Bounce
    vb_section = sections.get("Velocity & Bounce", [])
    result["velocity_bounce"] = "\n".join(vb_section).strip()

    # Also capture the second Capital Summary at bottom
    cs_section = sections.get("Capital Summary", [])
    if cs_section and not result["capital_raw"]:
        result["capital_raw"] = _parse_capital_raw(cs_section)

    # Post-parse validation
    missing = []
    if not result["active_positions"]:
        missing.append("Active Positions")
    if not result["capital_raw"]:
        missing.append("Capital Summary")
    # Pending orders can legitimately be empty
    if missing:
        print(f"Warning: Missing sections in status-raw.md: {', '.join(missing)}", file=sys.stderr)

    return result


def _split_sections(lines):
    """Split lines by ## headers. Returns dict of section_name -> list of lines."""
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

    return sections


def _split_subsections(lines):
    """Split lines by ### headers. Returns dict of subsection_name -> list of lines."""
    subs = {}
    current = None
    current_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### ") and not stripped.startswith("#### "):
            if current is not None:
                subs[current] = current_lines
            current = stripped[4:].strip()
            current_lines = []
        elif current is not None:
            current_lines.append(line)

    if current is not None:
        subs[current] = current_lines

    return subs


def _parse_active_positions(lines):
    """Parse 10-column Active Positions table → list of dicts."""
    rows = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("| Ticker") or stripped.startswith("| :"):
            continue
        cols = split_table_row(stripped)
        if len(cols) < 10:
            continue
        try:
            rows.append({
                "ticker": cols[0],
                "shares": int(float(cols[1])),
                "avg_cost": float(cols[2].replace("$", "").replace(",", "")),
                "current": float(cols[3].replace("$", "").replace(",", "")),
                "day_low": float(cols[4].replace("$", "").replace(",", "")) if cols[4] != "N/A" else None,
                "day_high": float(cols[5].replace("$", "").replace(",", "")) if cols[5] != "N/A" else None,
                "pl_dollar": cols[6].replace("$", "").replace(",", ""),
                "pl_pct": cols[7],
                "target": cols[8].replace("$", "").replace(",", "") if cols[8] != "N/A" else None,
                "dist_to_target": cols[9],
            })
        except (ValueError, IndexError):
            continue
    return rows


def _parse_pending_orders(lines, active_positions=None, watchlist_prices=None):
    """Parse Pending Orders table. Handles both 10-column (with Status) and 9-column formats.

    Returns list of dicts with normalized 'filled' boolean.
    """
    rows = []
    # Detect column count from header row
    col_count = 9
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("| Ticker") and "Status" in stripped:
            col_count = 10
            break
        elif stripped.startswith("| Ticker"):
            col_count = len(split_table_row(stripped))
            break

    # Build day_low/day_high lookup from active positions + watchlist prices
    day_data = {}
    if active_positions:
        for pos in active_positions:
            day_data[pos["ticker"]] = {
                "day_low": pos.get("day_low"),
                "day_high": pos.get("day_high"),
            }
    if watchlist_prices:
        for wp in watchlist_prices:
            if wp["ticker"] not in day_data:  # Don't override active positions
                day_data[wp["ticker"]] = {
                    "day_low": wp.get("day_low"),
                    "day_high": wp.get("day_high"),
                }

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("| Ticker") or stripped.startswith("| :"):
            continue
        if "no pending orders" in stripped.lower():
            continue
        cols = split_table_row(stripped)
        if len(cols) < 9:
            continue

        try:
            ticker = cols[0]
            order_type = cols[1]
            zone = cols[2]
            price = float(cols[3].replace("$", "").replace(",", ""))
            current = float(cols[4].replace("$", "").replace(",", ""))

            if col_count >= 10 and len(cols) >= 10:
                # 10-column format with Status
                status_str = cols[8].strip()
                note = cols[9]
                filled = "FILLED" in status_str.upper()
            else:
                # 9-column format: detect fills from day_low/day_high
                note = cols[8] if len(cols) > 8 else ""
                filled = False
                dd = day_data.get(ticker, {})
                if order_type == "BUY" and dd.get("day_low") is not None:
                    if dd["day_low"] <= price:
                        filled = True
                elif order_type == "SELL" and dd.get("day_high") is not None:
                    if dd["day_high"] >= price:
                        filled = True

            rows.append({
                "ticker": ticker,
                "type": order_type,
                "zone": zone,
                "price": price,
                "current": current,
                "note": note,
                "filled": filled,
            })
        except (ValueError, IndexError):
            continue

    return rows


def _parse_watchlist_prices(lines):
    """Parse 5-column Watchlist Prices table → list of dicts."""
    rows = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("| Ticker") or stripped.startswith("| :"):
            continue
        cols = split_table_row(stripped)
        if len(cols) < 5:
            continue
        try:
            rows.append({
                "ticker": cols[0],
                "price": float(cols[1].replace("$", "").replace(",", "")),
                "day_low": float(cols[2].replace("$", "").replace(",", "")) if cols[2] != "N/A" else None,
                "day_high": float(cols[3].replace("$", "").replace(",", "")) if cols[3] != "N/A" else None,
                "day_pct": cols[4],
            })
        except (ValueError, IndexError):
            continue
    return rows


def _parse_capital_raw(lines):
    """Parse Metric/Value capital table → dict."""
    result = {}
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("| Metric") or stripped.startswith("| :"):
            continue
        cols = split_table_row(stripped)
        if len(cols) >= 2:
            result[cols[0]] = cols[1]
    return result


def _parse_ticker_details(lines):
    """Parse Per-Ticker Detail section. Split by ### TICKER headers.

    Returns dict of ticker -> {identity: dict, wick_levels: list, trade_log: list, structural: dict}
    """
    # Split into per-ticker blocks
    tickers = {}
    current_ticker = None
    current_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### ") and not stripped.startswith("#### "):
            if current_ticker:
                tickers[current_ticker] = _parse_single_ticker_detail(current_lines)
            current_ticker = stripped[4:].strip()
            current_lines = []
        elif current_ticker is not None:
            current_lines.append(line)

    if current_ticker:
        tickers[current_ticker] = _parse_single_ticker_detail(current_lines)

    return tickers


def _parse_single_ticker_detail(lines):
    """Parse a single ticker's detail block."""
    result = {
        "identity": {},
        "wick_levels": [],
        "trade_log": [],
        "structural": {
            "earnings": {"exists": False},
            "news": {"exists": False},
            "short_interest": {"exists": False},
            "institutional": {"exists": False},
        },
    }

    # Split by #### headers
    sub_sections = {}
    current_header = None
    current_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#### "):
            if current_header:
                sub_sections[current_header] = current_lines
            current_header = stripped[5:].strip()
            current_lines = []
        elif current_header is not None:
            current_lines.append(line)

    if current_header:
        sub_sections[current_header] = current_lines

    # Parse Identity & Levels
    if "Identity & Levels" in sub_sections:
        id_lines = sub_sections["Identity & Levels"]
        result["identity"] = _parse_identity_table(id_lines)
        result["wick_levels"] = _parse_wick_table(id_lines)
        result["trade_log"] = _parse_trade_log(id_lines)

    # Parse Structural Context
    if "Structural Context" in sub_sections:
        sc_lines = sub_sections["Structural Context"]
        result["structural"] = _parse_structural_context(sc_lines)

    return result


def _parse_identity_table(lines):
    """Parse Field/Value identity table → dict."""
    result = {}
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("| Field") or stripped.startswith("| :"):
            continue
        cols = split_table_row(stripped)
        if len(cols) >= 2:
            result[cols[0]] = cols[1]
    return result


def _parse_wick_table(lines):
    """Parse 7-column wick levels table → list of dicts."""
    rows = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if "Support" in stripped and "Buy At" in stripped and stripped.startswith("|"):
            in_table = True
            continue
        if in_table and stripped.startswith("| :"):
            continue
        if in_table and stripped.startswith("|"):
            cols = split_table_row(stripped)
            if len(cols) >= 7:
                try:
                    # Extract numeric Buy At price (remove ↑above suffix)
                    buy_at_str = cols[4].replace("↑above", "").strip()
                    buy_at = float(buy_at_str.replace("$", "").replace(",", ""))
                    rows.append({
                        "support": cols[0],
                        "source": cols[1],
                        "hold_pct": cols[2],
                        "offset": cols[3],
                        "buy_at": buy_at,
                        "buy_at_raw": cols[4],
                        "zone": cols[5],
                        "tier": cols[6],
                    })
                except ValueError:
                    continue
        elif in_table and not stripped.startswith("|"):
            in_table = False
    return rows


def _parse_trade_log(lines):
    """Parse trade log table → list of dicts."""
    rows = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("| Date") and "Action" in stripped and "Price" in stripped:
            in_table = True
            continue
        if in_table and stripped.startswith("| :"):
            continue
        if in_table and stripped.startswith("|"):
            cols = split_table_row(stripped)
            if len(cols) >= 5:
                rows.append({
                    "date": cols[0],
                    "action": cols[1],
                    "price": cols[2],
                    "shares": cols[3],
                    "note": cols[4],
                })
        elif in_table and not stripped.startswith("|"):
            in_table = False
    return rows


def _parse_structural_context(lines):
    """Parse structural context sub-sections."""
    text = "\n".join(lines)
    result = {
        "earnings": _parse_earnings_context(text),
        "news": _parse_news_context(text),
        "short_interest": _parse_short_interest_context(text),
        "institutional": _parse_institutional_context(text),
    }
    return result


def _parse_earnings_context(text):
    """Extract earnings data from structural context."""
    result = {"exists": False}

    # Check for "No cached file" or "No cached data"
    if re.search(r"\*\*Earnings[:\*]*\*?\*?\s*No cached (file|data)", text):
        return result

    # Find earnings section
    m = re.search(r"\*\*Earnings\s*\((.+?)\)\s*:\*\*", text)
    if not m:
        return result

    result["exists"] = True
    result["file_ref"] = m.group(1)

    # Extract generation date
    gm = re.search(r"generated\s+(\d{4}-\d{2}-\d{2})", m.group(1))
    if gm:
        result["gen_date"] = gm.group(1)

    # Parse metrics table
    # Find lines after the Earnings header until next ** header or ---
    earnings_block = text[m.end():]
    # Truncate at next structural section
    next_section = re.search(r"\n\*\*(?:News|Short Interest|Institutional)", earnings_block)
    if next_section:
        earnings_block = earnings_block[:next_section.start()]

    # Parse Metric/Value table
    for line in earnings_block.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("| Metric") or stripped.startswith("| :"):
            if stripped.startswith("| Quarter"):
                break
            continue
        cols = split_table_row(stripped)
        if len(cols) >= 2:
            key = cols[0].strip()
            val = cols[1].strip()
            if key == "Earnings Date":
                result["earnings_date"] = val
            elif key == "Days Until":
                result["days_until_cached"] = val
            elif key == "EPS Estimate":
                result["eps_estimate"] = val
            elif key == "Revenue Estimate":
                result["revenue_estimate"] = val
            elif key == "Earnings Rule":
                result["earnings_rule"] = val

    # Parse historical reactions table
    reactions = []
    in_reactions = False
    for line in earnings_block.split("\n"):
        stripped = line.strip()
        if stripped.startswith("| Quarter"):
            in_reactions = True
            continue
        if in_reactions and stripped.startswith("| :"):
            continue
        if in_reactions and stripped.startswith("|"):
            cols = split_table_row(stripped)
            if len(cols) >= 7:
                reactions.append({
                    "quarter": cols[0],
                    "eps_est": cols[1],
                    "eps_actual": cols[2],
                    "surprise_pct": cols[3],
                    "one_day_pct": cols[4],
                    "five_day_pct": cols[5],
                    "reaction": cols[6],
                })
        elif in_reactions and not stripped.startswith("|"):
            break
    result["reactions"] = reactions

    return result


def _parse_news_context(text):
    """Extract news data from structural context."""
    result = {"exists": False}

    if re.search(r"\*\*News[:\*]*\*?\*?\s*No cached (file|data)", text):
        return result

    m = re.search(r"\*\*News\s*\((.+?)\)\s*:\*\*", text)
    if not m:
        return result

    result["exists"] = True
    result["file_ref"] = m.group(1)

    gm = re.search(r"generated\s+(\d{4}-\d{2}-\d{2})", m.group(1))
    if gm:
        result["gen_date"] = gm.group(1)

    # Parse headlines table
    news_block = text[m.end():]
    next_section = re.search(r"\n\*\*(?:Short Interest|Institutional)", news_block)
    if next_section:
        news_block = news_block[:next_section.start()]

    headlines = []
    in_table = False
    for line in news_block.split("\n"):
        stripped = line.strip()
        if stripped.startswith("| Date") and "Headline" in stripped:
            in_table = True
            continue
        if in_table and stripped.startswith("| :"):
            continue
        if in_table and stripped.startswith("|"):
            cols = split_table_row(stripped)
            if len(cols) >= 3:
                sentiment = cols[2] if len(cols) > 2 else ""
                score = cols[3] if len(cols) > 3 else ""
                catalysts = cols[4] if len(cols) > 4 else ""
                headlines.append({
                    "date": cols[0],
                    "headline": cols[1],
                    "sentiment": sentiment,
                    "score": score,
                    "catalysts": catalysts,
                })
        elif in_table and not stripped.startswith("|"):
            break
    result["headlines"] = headlines
    result["article_count"] = len(headlines)

    # Compute sentiment distribution
    pos = sum(1 for h in headlines if h["sentiment"].lower().startswith("pos"))
    neg = sum(1 for h in headlines if h["sentiment"].lower().startswith("neg"))
    neu = len(headlines) - pos - neg
    result["sentiment_dist"] = {"positive": pos, "negative": neg, "neutral": neu}

    return result


def _parse_short_interest_context(text):
    """Extract short interest data from structural context."""
    result = {"exists": False}

    if re.search(r"\*\*Short Interest[:\*]*\*?\*?\s*No cached (file|data)", text):
        return result

    m = re.search(r"\*\*Short Interest\s*\((.+?)\)\s*:\*\*", text)
    if not m:
        return result

    result["exists"] = True
    result["file_ref"] = m.group(1)

    gm = re.search(r"generated\s+(\d{4}-\d{2}-\d{2})", m.group(1))
    if gm:
        result["gen_date"] = gm.group(1)

    si_block = text[m.end():]
    next_section = re.search(r"\n\*\*(?:Institutional|Earnings|News)", si_block)
    if next_section:
        si_block = si_block[:next_section.start()]

    for line in si_block.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("| Metric") or stripped.startswith("| :"):
            continue
        cols = split_table_row(stripped)
        if len(cols) >= 2:
            key = cols[0].strip()
            val = cols[1].strip()
            if key == "Score":
                result["score"] = val
            elif key == "Risk Rating":
                result["risk_label"] = val
            elif "Short % Float" in key:
                result["short_pct_float"] = val
            elif key == "Short Ratio (DTC)":
                result["dtc"] = val
            elif "Change" in key:
                result["change"] = val
            elif key == "Shares Short":
                result["shares_short"] = val

    return result


def _parse_institutional_context(text):
    """Extract institutional holder data from structural context."""
    result = {"exists": False}

    if re.search(r"\*\*Institutional[:\*]*\*?\*?\s*No cached (file|data)", text):
        return result

    m = re.search(r"\*\*Institutional\s*\((.+?)\)\s*:\*\*", text)
    if not m:
        return result

    result["exists"] = True
    result["file_ref"] = m.group(1)

    gm = re.search(r"generated\s+(\d{4}-\d{2}-\d{2})", m.group(1))
    if gm:
        result["gen_date"] = gm.group(1)

    inst_block = text[m.end():]
    next_section = re.search(r"\n\*\*(?:Earnings|News|Short Interest)", inst_block)
    if next_section:
        inst_block = inst_block[:next_section.start()]
    # Also stop at --- separator
    sep = inst_block.find("\n---")
    if sep >= 0:
        inst_block = inst_block[:sep]

    holders = []
    in_table = False
    for line in inst_block.split("\n"):
        stripped = line.strip()
        if stripped.startswith("| Holder"):
            in_table = True
            continue
        if in_table and stripped.startswith("| :"):
            continue
        if in_table and stripped.startswith("|"):
            cols = split_table_row(stripped)
            if len(cols) >= 4:
                holders.append({
                    "holder": cols[0],
                    "shares": cols[1],
                    "pct_out": cols[2],
                    "pct_change": cols[3],
                })
        elif in_table and not stripped.startswith("|"):
            break

    result["holders"] = holders
    return result


def _parse_watchlist_levels(lines):
    """Parse Watchlist Levels section, split by ### TICKER headers."""
    tickers = {}
    current_ticker = None
    current_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### "):
            if current_ticker:
                tickers[current_ticker] = "\n".join(current_lines).strip()
            # Extract ticker name (may have price/pct suffix like "### AR — $35.54 (+1.5%)")
            header = stripped[4:].strip()
            current_ticker = header.split(" ")[0].split("—")[0].strip()
            current_lines = []
        elif current_ticker is not None:
            current_lines.append(line)

    if current_ticker:
        tickers[current_ticker] = "\n".join(current_lines).strip()

    return tickers


# ---------------------------------------------------------------------------
# Computation Functions
# ---------------------------------------------------------------------------

def get_strategy_label(portfolio, ticker):
    """Classify ticker as Recovery or Surgical based on portfolio.json note."""
    pos = portfolio.get("positions", {}).get(ticker, {})
    note = pos.get("note", "").lower()
    if any(kw in note for kw in ["recovery", "underwater", "pre-strategy"]):
        return "Recovery"
    return "Surgical"


def get_pending_orders(portfolio):
    """Extract all pending orders from portfolio.json, skipping PAUSED orders.

    Returns dict of ticker -> list of order dicts.
    """
    result = {}
    for ticker, orders in portfolio.get("pending_orders", {}).items():
        if not isinstance(orders, list):
            continue
        active_orders = [o for o in orders if "PAUSED" not in o.get("note", "").upper()]
        paused_orders = [o for o in orders if "PAUSED" in o.get("note", "").upper()]
        result[ticker] = {"active": active_orders, "paused": paused_orders}
    return result


def compute_heat_map(raw_data, portfolio):
    """Compute heat map: sort by P/L % ascending, add strategy labels.

    Returns (rows, total_pl, total_deployed).
    """
    positions = []
    for pos in raw_data["active_positions"]:
        ticker = pos["ticker"]
        shares = pos["shares"]
        avg_cost = pos["avg_cost"]
        current = pos["current"]

        deployed = shares * avg_cost
        current_value = shares * current
        pl_dollar = current_value - deployed
        pl_pct = (pl_dollar / deployed * 100) if deployed != 0 else 0.0

        strategy = get_strategy_label(portfolio, ticker)

        positions.append({
            "ticker": ticker,
            "shares": shares,
            "avg_cost": avg_cost,
            "current": current,
            "deployed": deployed,
            "current_value": current_value,
            "pl_dollar": pl_dollar,
            "pl_pct": pl_pct,
            "strategy": strategy,
        })

    # Sort by P/L % ascending (worst first)
    positions.sort(key=lambda x: x["pl_pct"])

    total_pl = sum(p["pl_dollar"] for p in positions)
    total_deployed = sum(p["deployed"] for p in positions)

    return positions, total_pl, total_deployed


def detect_fill_alerts(raw_data, portfolio):
    """Detect FILLED? markers in pending orders.

    Returns list of fill alert dicts.
    """
    alerts = []
    for order in raw_data["pending_orders"]:
        if not order.get("filled"):
            continue

        ticker = order["ticker"]
        pos = portfolio.get("positions", {}).get(ticker, {})
        old_shares = pos.get("shares", 0)
        old_avg = pos.get("avg_cost", 0)

        # Look up order shares from portfolio.json
        pj_orders = portfolio.get("pending_orders", {}).get(ticker, [])
        fill_shares = None
        for pj_order in pj_orders:
            if abs(pj_order.get("price", 0) - order["price"]) < 0.01 and pj_order.get("type") == order["type"]:
                fill_shares = pj_order.get("shares")
                break

        alert = {
            "ticker": ticker,
            "type": order["type"],
            "price": order["price"],
            "shares": fill_shares,
            "note": order["note"],
            "current": order["current"],
        }

        if order["type"] == "BUY" and fill_shares and old_shares > 0:
            new_shares = old_shares + fill_shares
            new_avg = (old_shares * old_avg + fill_shares * order["price"]) / new_shares
            alert["new_avg"] = new_avg
            alert["new_shares"] = new_shares
            alert["new_deployed"] = new_shares * new_avg
        elif order["type"] == "BUY" and fill_shares and old_shares == 0:
            # New position
            alert["new_avg"] = order["price"]
            alert["new_shares"] = fill_shares
            alert["new_deployed"] = fill_shares * order["price"]
        elif order["type"] == "SELL" and fill_shares and old_avg > 0:
            realized_pl = (order["price"] - old_avg) * fill_shares
            alert["realized_pl"] = realized_pl
            alert["remaining_shares"] = old_shares - fill_shares

        alerts.append(alert)

    return alerts


def group_orders_by_zone(ticker, portfolio):
    """Group pending orders by zone: Active, Reserve, Sell. Skip PAUSED.

    Returns dict with keys: active, reserve, sell, paused.
    """
    orders = portfolio.get("pending_orders", {}).get(ticker, [])
    grouped = {"active": [], "reserve": [], "sell": [], "paused": []}

    for order in orders:
        note = order.get("note", "")
        if "PAUSED" in note.upper():
            grouped["paused"].append(order)
            continue
        if note.startswith("Bullet") or note.startswith("Last active"):
            grouped["active"].append(order)
        elif note.startswith("Reserve"):
            grouped["reserve"].append(order)
        elif order.get("type") == "SELL":
            grouped["sell"].append(order)
        else:
            grouped["active"].append(order)  # Default to active zone

    return grouped


def annotate_wick_levels(wick_levels, pending_orders_for_ticker):
    """Cross-reference wick levels against pending orders.

    For each level, check if a pending order exists at that price (within $0.05).
    Returns list of wick level dicts with added 'status' field: 'placed' or 'available'.
    """
    # Collect all pending buy prices
    buy_prices = set()
    for order in pending_orders_for_ticker:
        if order.get("type") == "BUY":
            buy_prices.add(order["price"])

    annotated = []
    for level in wick_levels:
        placed = False
        for bp in buy_prices:
            if abs(bp - level["buy_at"]) < 0.06:  # $0.05 tolerance
                placed = True
                break
        level_copy = dict(level)
        level_copy["status"] = "placed" if placed else "available"
        annotated.append(level_copy)

    return annotated


def compute_sell_projections(portfolio, ticker, current_price):
    """Compute sell target distance from current and from avg.

    Returns dict or None if no target.
    """
    pos = portfolio.get("positions", {}).get(ticker, {})
    target = pos.get("target_exit")
    avg_cost = pos.get("avg_cost", 0)

    if target is None:
        return {"target": None, "note": "No target set (recovery mode)"}

    dist_from_current = ((target - current_price) / current_price * 100) if current_price else 0
    dist_from_avg = ((target - avg_cost) / avg_cost * 100) if avg_cost else 0

    return {
        "target": target,
        "dist_from_current": dist_from_current,
        "dist_from_avg": dist_from_avg,
    }


def compute_near_fill_orders(raw_orders, threshold=3.0):
    """Find orders within threshold % of current price.

    Returns list of dicts with ticker, type, price, current, distance_pct.
    """
    near = []
    for order in raw_orders:
        if order.get("filled"):
            continue
        price = order["price"]
        current = order["current"]
        if current == 0:
            continue
        if order["type"] == "BUY":
            dist = (current - price) / current * 100
        else:
            dist = (price - current) / current * 100
        if 0 < dist <= threshold:
            near.append({
                "ticker": order["ticker"],
                "type": order["type"],
                "price": price,
                "current": current,
                "distance_pct": dist,
                "note": order.get("note", ""),
            })
    return near


def compute_earnings_gates(raw_data, report_date):
    """Find tickers with earnings within 14 days.

    Always recomputes day_count from report_date, never trusts cached Days Until.
    Returns list of dicts.
    """
    gates = []
    for ticker, detail in raw_data["ticker_details"].items():
        earnings = detail.get("structural", {}).get("earnings", {})
        if not earnings.get("exists"):
            continue
        date_str = earnings.get("earnings_date")
        if not date_str:
            continue
        try:
            earnings_date = date.fromisoformat(date_str)
            day_count = (earnings_date - report_date).days
            if day_count <= 14:
                gates.append({
                    "ticker": ticker,
                    "earnings_date": date_str,
                    "day_count": day_count,
                    "eps_estimate": earnings.get("eps_estimate", "N/A"),
                    "reactions": earnings.get("reactions", []),
                })
        except ValueError:
            continue
    return gates


def compute_time_stops(portfolio, report_date):
    """Check positions for 60+ day time stops.

    Entry date formats:
    - ISO: "2026-02-13" → compute normally
    - "pre-YYYY" (year only) → inherently exceeded
    - "pre-YYYY-MM-DD" → strip prefix, compute normally
    """
    stops = []
    for ticker, pos in portfolio.get("positions", {}).items():
        if not pos.get("shares", 0):
            continue  # Skip exited positions
        entry_str = pos.get("entry_date", "")
        if not entry_str:
            continue

        days_held = None
        inherently_exceeded = False

        if entry_str.startswith("pre-"):
            stripped = entry_str[4:]
            # Check if it's just a year (e.g., "2026") or a full date (e.g., "2026-02-12")
            if re.match(r"^\d{4}$", stripped):
                # Year only — inherently exceeded
                inherently_exceeded = True
                days_held = None
            else:
                try:
                    entry_date = date.fromisoformat(stripped)
                    days_held = (report_date - entry_date).days
                except ValueError:
                    inherently_exceeded = True
        else:
            try:
                entry_date = date.fromisoformat(entry_str)
                days_held = (report_date - entry_date).days
            except ValueError:
                continue

        exceeded = inherently_exceeded or (days_held is not None and days_held >= 60)
        if exceeded:
            stops.append({
                "ticker": ticker,
                "entry_date": entry_str,
                "days_held": days_held,
                "inherently_exceeded": inherently_exceeded,
            })

    return stops


def compute_stale_data(raw_data, report_date):
    """Find cached files older than 7 days.

    Returns list of dicts.
    """
    stale = []
    for ticker, detail in raw_data["ticker_details"].items():
        structural = detail.get("structural", {})
        for section_key in ["earnings", "news", "short_interest", "institutional"]:
            section = structural.get(section_key, {})
            if not section.get("exists"):
                continue
            gen_date_str = section.get("gen_date")
            if not gen_date_str:
                continue
            try:
                gen_date = date.fromisoformat(gen_date_str)
                days_old = (report_date - gen_date).days
                if days_old >= 7:
                    stale.append({
                        "ticker": ticker,
                        "section": section_key,
                        "gen_date": gen_date_str,
                        "days_old": days_old,
                    })
            except ValueError:
                continue
    return stale


def compute_capital_summary(portfolio, heat_map_positions):
    """Compute capital deployment by strategy.

    Returns dict with surgical/recovery/velocity/bounce breakdown.
    """
    surgical_deployed = 0.0
    surgical_tickers = []
    recovery_deployed = 0.0
    recovery_tickers = []

    for pos in heat_map_positions:
        if pos["strategy"] == "Surgical":
            surgical_deployed += pos["deployed"]
            surgical_tickers.append(pos)
        else:
            recovery_deployed += pos["deployed"]
            recovery_tickers.append(pos)

    total_deployed = surgical_deployed + recovery_deployed

    # Budget
    cap = portfolio.get("capital", {})
    surgical_count = len(surgical_tickers)
    surgical_budget = surgical_count * cap.get("per_stock_total", 600)
    surgical_util = (surgical_deployed / surgical_budget * 100) if surgical_budget else 0

    vel_cap = portfolio.get("velocity_capital", {})
    vel_deployed = sum(
        p.get("shares", 0) * p.get("avg_cost", 0)
        for p in portfolio.get("velocity_positions", {}).values()
    )
    bnc_cap = portfolio.get("bounce_capital", {})
    bnc_deployed = sum(
        p.get("shares", 0) * p.get("avg_cost", 0)
        for p in portfolio.get("bounce_positions", {}).values()
    )

    total_budget = surgical_budget + vel_cap.get("total_pool", 0) + bnc_cap.get("total_pool", 0)
    # Utilization excludes recovery (fixed legacy positions with no budget concept)
    active_deployed = surgical_deployed + vel_deployed + bnc_deployed
    total_util = (active_deployed / total_budget * 100) if total_budget else 0

    return {
        "surgical": {
            "deployed": surgical_deployed,
            "count": surgical_count,
            "budget": surgical_budget,
            "utilization": surgical_util,
            "tickers": surgical_tickers,
        },
        "recovery": {
            "deployed": recovery_deployed,
            "count": len(recovery_tickers),
            "tickers": recovery_tickers,
        },
        "velocity": {
            "deployed": vel_deployed,
            "budget": vel_cap.get("total_pool", 0),
        },
        "bounce": {
            "deployed": bnc_deployed,
            "budget": bnc_cap.get("total_pool", 0),
        },
        "total_deployed": total_deployed,
        "total_budget": total_budget,
        "total_utilization": total_util,
    }


def build_actionable_skeleton(fill_alerts, earnings_gates, near_fills, time_stops, stale_data):
    """Build ranked actionable items skeleton.

    Returns list of (priority, item_text, findings).
    """
    items = []

    # CRITICAL: Fill confirmations
    for alert in fill_alerts:
        ticker = alert["ticker"]
        price = alert["price"]
        shares = alert.get("shares", "?")
        if alert["type"] == "BUY":
            new_avg = alert.get("new_avg")
            new_shares = alert.get("new_shares")
            if new_avg:
                detail = f"If filled: {new_shares} shares @ ${new_avg:.2f} avg"
            else:
                detail = f"New position: {shares} shares @ ${price:.2f}"
            items.append(("CRITICAL", f"{ticker} {alert['type']} fill @ ${price:.2f}", detail))
        else:
            realized = alert.get("realized_pl")
            if realized is not None:
                detail = f"If filled: realized P/L ${realized:.2f}"
            else:
                detail = f"SELL fill @ ${price:.2f}"
            items.append(("CRITICAL", f"{ticker} {alert['type']} fill @ ${price:.2f}", detail))

    # HIGH: Earnings gates
    for gate in earnings_gates:
        ticker = gate["ticker"]
        days = gate["day_count"]
        items.append(("HIGH", f"{ticker} earnings gate — {gate['earnings_date']} ({days} days)",
                       f"No new entries within 14 days of earnings"))

    # MEDIUM: Near-fill orders
    for nf in near_fills:
        ticker = nf["ticker"]
        items.append(("MEDIUM", f"{ticker} {nf['type']} near trigger — ${nf['price']:.2f} ({nf['distance_pct']:.1f}%)",
                       nf["note"]))

    # LOW: Time stops
    if time_stops:
        tickers = ", ".join(ts["ticker"] for ts in time_stops)
        items.append(("LOW", f"Time stop review — {tickers}",
                       "60+ day positions without progress toward exit targets"))

    # LOW: Stale data
    if stale_data:
        stale_desc = "; ".join(f"{s['ticker']} {s['section']} ({s['days_old']}d)" for s in stale_data)
        items.append(("LOW", f"Stale data — {stale_desc}", "Cached files older than 7 days"))

    return items


# ---------------------------------------------------------------------------
# Report Builder
# ---------------------------------------------------------------------------

def fmt_dollar(val):
    if val is None:
        return "N/A"
    sign = "+" if val >= 0 else ""
    return f"{sign}${val:.2f}" if val >= 0 else f"-${abs(val):.2f}"


def fmt_pct(val):
    if val is None:
        return "N/A"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.1f}%"


def build_report(report_date, heat_map, total_pl, total_deployed, fill_alerts,
                 per_position_data, watchlist_data, velocity_bounce_raw,
                 capital_summary, actionable_items, portfolio):
    """Assemble status-pre-analyst.md."""
    parts = []

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    parts.append(f"# Status Pre-Analyst — Mechanical Analysis")
    parts.append(f"*Generated: {now_str} | Tool: status_pre_analyst.py*")
    parts.append("")

    # --- Fill Alerts ---
    parts.append("## Fill Alerts")
    parts.append("")
    if fill_alerts:
        for alert in fill_alerts:
            ticker = alert["ticker"]
            parts.append(f"### Potential Fill: {ticker} {alert['type']} @ ${alert['price']:.2f}")
            parts.append("")
            parts.append("| Field | Value |")
            parts.append("| :--- | :--- |")
            parts.append(f"| Order | {alert['type']} {alert.get('shares', '?')} shares @ ${alert['price']:.2f} |")
            parts.append(f"| Note | {alert.get('note', '')} |")

            if alert["type"] == "BUY" and alert.get("new_avg"):
                parts.append(f"| New Avg (if filled) | ${alert['new_avg']:.2f} |")
                parts.append(f"| New Shares | {alert['new_shares']} |")
                parts.append(f"| New Deployed | ${alert['new_deployed']:.2f} |")
            elif alert["type"] == "BUY" and alert.get("new_deployed"):
                parts.append(f"| New Position | {alert.get('shares', '?')} shares @ ${alert['price']:.2f} |")
                parts.append(f"| Deployed | ${alert['new_deployed']:.2f} |")
            elif alert["type"] == "SELL" and alert.get("realized_pl") is not None:
                parts.append(f"| Realized P/L | {fmt_dollar(alert['realized_pl'])} |")
                parts.append(f"| Remaining Shares | {alert.get('remaining_shares', '?')} |")

            parts.append("")
            parts.append("*LLM: Write verification instructions and what-if scenario narrative.*")
            parts.append("")
    else:
        parts.append("No fill alerts.")
    parts.append("")
    parts.append("---")
    parts.append("")

    # --- Heat Map ---
    parts.append("## Portfolio Heat Map")
    parts.append("")
    parts.append("| Ticker | Shares | Avg Cost | Current | P/L $ | P/L % | Strategy |")
    parts.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for pos in heat_map:
        pl_str = fmt_dollar(pos["pl_dollar"])
        pct_str = fmt_pct(pos["pl_pct"])
        parts.append(
            f"| {pos['ticker']} | {pos['shares']} | ${pos['avg_cost']:.2f} "
            f"| ${pos['current']:.2f} | {pl_str} | {pct_str} | {pos['strategy']} |"
        )
    parts.append("")
    parts.append(f"**Portfolio total unrealized P/L: {fmt_dollar(total_pl)}** "
                 f"across {len(heat_map)} positions (${total_deployed:,.2f} deployed)")
    parts.append("")
    parts.append("---")
    parts.append("")

    # --- Per-Position Detail ---
    parts.append("## Per-Position Detail")
    parts.append("")

    for pos_data in per_position_data:
        ticker = pos_data["ticker"]
        strategy = pos_data["strategy"]
        pl_pct = pos_data["pl_pct"]

        parts.append(f"### {ticker} — {strategy} — {fmt_pct(pl_pct)}")
        parts.append("")

        # 1. Trades Executed
        parts.append("#### 1. Trades Executed")
        if pos_data["trade_log"]:
            parts.append("")
            parts.append("| Date | Action | Price | Shares | Note |")
            parts.append("| :--- | :--- | :--- | :--- | :--- |")
            for trade in pos_data["trade_log"]:
                parts.append(f"| {trade['date']} | {trade['action']} | {trade['price']} "
                             f"| {trade['shares']} | {trade['note']} |")
        else:
            parts.append("No trade log entries.")
        parts.append("")

        # 2. Current Average
        parts.append("#### 2. Current Average")
        parts.append("")
        parts.append("| Metric | Value |")
        parts.append("| :--- | :--- |")
        parts.append(f"| Shares | {pos_data['shares']} |")
        parts.append(f"| Avg Cost | ${pos_data['avg_cost']:.2f} |")
        parts.append(f"| Total Deployed | ${pos_data['deployed']:.2f} |")
        parts.append(f"| Current Value | ${pos_data['current_value']:.2f} |")
        parts.append(f"| Unrealized P/L | {fmt_dollar(pos_data['pl_dollar'])} ({fmt_pct(pos_data['pl_pct'])}) |")
        parts.append("")

        # 3. Pending Limit Orders
        parts.append("#### 3. Pending Limit Orders")
        grouped = pos_data["grouped_orders"]
        has_orders = any(grouped[z] for z in ["active", "reserve", "sell"])

        if not has_orders:
            parts.append("No pending orders.")
        else:
            for zone_key, zone_label in [("active", "Active Zone"), ("reserve", "Reserve Zone"), ("sell", "Sell Zone")]:
                zone_orders = grouped[zone_key]
                if zone_orders:
                    parts.append("")
                    parts.append(f"**{zone_label}**")
                    parts.append("")
                    parts.append("| Type | Price | Shares | Note |")
                    parts.append("| :--- | :--- | :--- | :--- |")
                    for o in zone_orders:
                        parts.append(f"| {o['type']} | ${o['price']:.2f} | {o.get('shares', '?')} | {o.get('note', '')} |")

        if grouped["paused"]:
            parts.append("")
            parts.append("**Paused Orders**")
            parts.append("")
            parts.append("| Type | Price | Shares | Note |")
            parts.append("| :--- | :--- | :--- | :--- |")
            for o in grouped["paused"]:
                parts.append(f"| {o['type']} | ${o['price']:.2f} | {o.get('shares', '?')} | {o.get('note', '')} |")
        parts.append("")

        # 4. Wick-Adjusted Buy Levels
        parts.append("#### 4. Wick-Adjusted Buy Levels")
        wick = pos_data["wick_levels"]
        if wick:
            parts.append("")
            parts.append("| Support | Source | Hold% | Buy At | Zone | Tier | Status |")
            parts.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            placed_count = sum(1 for w in wick if w["status"] == "placed")
            available_count = sum(1 for w in wick if w["status"] == "available")
            for w in wick:
                parts.append(
                    f"| {w['support']} | {w['source']} | {w['hold_pct']} "
                    f"| {w['buy_at_raw']} | {w['zone']} | {w['tier']} | ({w['status']}) |"
                )
            parts.append("")
            parts.append(f"*{placed_count} of {len(wick)} levels placed as orders, {available_count} available.*")
        else:
            parts.append("No wick analysis cached.")
        parts.append("")

        # 5. Projected Sell Levels
        parts.append("#### 5. Projected Sell Levels")
        sell_proj = pos_data["sell_projection"]
        if sell_proj.get("target") is not None:
            parts.append("")
            parts.append("| Target | From Current | From Avg |")
            parts.append("| :--- | :--- | :--- |")
            parts.append(
                f"| ${sell_proj['target']:.2f} "
                f"| {fmt_pct(sell_proj['dist_from_current'])} "
                f"| {fmt_pct(sell_proj['dist_from_avg'])} |"
            )
        else:
            parts.append(sell_proj.get("note", "No target set."))
        parts.append("")

        # 6. Context Flags (data points for LLM to write narratives)
        parts.append("#### 6. Context Flags — Data Points")
        parts.append("")
        struct = pos_data["structural"]

        # Earnings
        earnings = struct.get("earnings", {})
        if earnings.get("exists"):
            ed = earnings.get("earnings_date", "?")
            day_count = pos_data.get("earnings_day_count")
            if day_count is not None:
                flag = " **EARNINGS GATE**" if day_count <= 14 else ""
                parts.append(f"- **Earnings:** {ed} ({day_count} days){flag}")
            else:
                parts.append(f"- **Earnings:** {ed}")
            if earnings.get("eps_estimate"):
                parts.append(f"  - EPS Estimate: {earnings['eps_estimate']}")
            if earnings.get("reactions"):
                reactions_str = ", ".join(
                    f"{r['quarter']} {r['one_day_pct']}" for r in earnings["reactions"]
                )
                parts.append(f"  - Historical: {reactions_str}")
        else:
            parts.append("- **Earnings:** No cached data")

        # News
        news = struct.get("news", {})
        if news.get("exists"):
            dist = news.get("sentiment_dist", {})
            count = news.get("article_count", 0)
            pos_n = dist.get("positive", 0)
            neg_n = dist.get("negative", 0)
            neu_n = dist.get("neutral", 0)
            parts.append(f"- **News:** {count} articles (Pos:{pos_n} Neg:{neg_n} Neu:{neu_n})")
            if news.get("gen_date"):
                parts.append(f"  - Generated: {news['gen_date']}")
        else:
            parts.append("- **News:** No cached data")

        # Short Interest
        si = struct.get("short_interest", {})
        if si.get("exists"):
            score = si.get("score", "?")
            label = si.get("risk_label", "?")
            short_pct = si.get("short_pct_float", "?")
            dtc = si.get("dtc", "?")
            change = si.get("change", "?")
            parts.append(f"- **Short Interest:** Score {score}, {label} risk, {short_pct} short, DTC {dtc}, Change {change}")
            if si.get("gen_date"):
                parts.append(f"  - Generated: {si['gen_date']}")
        else:
            parts.append("- **Short Interest:** No cached data")

        # Institutional
        inst = struct.get("institutional", {})
        if inst.get("exists"):
            holders = inst.get("holders", [])
            if holders:
                top3 = holders[:3]
                holder_str = ", ".join(f"{h['holder']} {h['pct_change']}" for h in top3)
                parts.append(f"- **Institutional:** Top holders: {holder_str}")
            else:
                parts.append("- **Institutional:** Data available (no holders parsed)")
            if inst.get("gen_date"):
                parts.append(f"  - Generated: {inst['gen_date']}")
        else:
            parts.append("- **Institutional:** No cached data")

        parts.append("")
        parts.append("*LLM: Write context flag narratives interpreting these data points.*")
        parts.append("")
        parts.append("---")
        parts.append("")

    # --- Watchlist ---
    parts.append("## Watchlist")
    parts.append("")
    parts.append("| Ticker | Price | Day % | B1 Price | Dist to B1 | Orders Placed |")
    parts.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
    for wd in watchlist_data:
        b1_str = f"${wd['b1_price']:.2f}" if wd.get("b1_price") else "N/A"
        dist_str = fmt_pct(wd["dist_to_b1"]) if wd.get("dist_to_b1") is not None else "N/A"
        parts.append(
            f"| {wd['ticker']} | ${wd['price']:.2f} | {wd['day_pct']} "
            f"| {b1_str} | {dist_str} | {wd['orders_placed']} |"
        )
    parts.append("")
    parts.append("*LLM: Write qualitative notes per watchlist ticker (observations, dead zones).*")
    parts.append("")
    parts.append("---")
    parts.append("")

    # --- Velocity & Bounce ---
    parts.append("## Velocity & Bounce")
    parts.append("")
    parts.append(velocity_bounce_raw if velocity_bounce_raw else "No active velocity/bounce trades.")
    parts.append("")
    parts.append("---")
    parts.append("")

    # --- Capital Summary ---
    parts.append("## Capital Summary")
    parts.append("")
    cs = capital_summary
    parts.append("| Strategy | Deployed | Budget | Utilization |")
    parts.append("| :--- | :--- | :--- | :--- |")

    surg = cs["surgical"]
    parts.append(
        f"| Surgical ({surg['count']} positions) | ${surg['deployed']:.2f} "
        f"| ${surg['budget']:,.0f} ({surg['count']} × $600) | {surg['utilization']:.1f}% |"
    )

    rec = cs["recovery"]
    parts.append(
        f"| Recovery ({rec['count']} pre-strategy) | ${rec['deployed']:.2f} "
        f"| Fixed — no new capital | N/A |"
    )

    vel = cs["velocity"]
    vel_util = (vel['deployed'] / vel['budget'] * 100) if vel['budget'] else 0
    parts.append(f"| Velocity | ${vel['deployed']:.2f} | ${vel['budget']:,.0f} | {vel_util:.0f}% |")

    bnc = cs["bounce"]
    bnc_util = (bnc['deployed'] / bnc['budget'] * 100) if bnc['budget'] else 0
    parts.append(f"| Bounce | ${bnc['deployed']:.2f} | ${bnc['budget']:,.0f} | {bnc_util:.0f}% |")

    parts.append(
        f"| **Total** | **${cs['total_deployed']:,.2f}** "
        f"| **${cs['total_budget']:,.0f} (excl. recovery)** | **{cs['total_utilization']:.1f}%** |"
    )
    parts.append("")

    # Per-position deployment
    parts.append("**Surgical per-position deployment:**")
    parts.append("")
    parts.append("| Ticker | Deployed | Budget | Bullets Used |")
    parts.append("| :--- | :--- | :--- | :--- |")
    for pos in surg["tickers"]:
        ticker = pos["ticker"]
        pj_pos = portfolio.get("positions", {}).get(ticker, {})
        bullets = pj_pos.get("bullets_used", "?")
        parts.append(f"| {ticker} | ${pos['deployed']:.2f} | $600 | {bullets} |")
    parts.append("")

    parts.append("**Recovery exposure (pre-strategy, fixed):**")
    parts.append("")
    parts.append("| Ticker | Deployed | Note |")
    parts.append("| :--- | :--- | :--- |")
    for pos in rec["tickers"]:
        ticker = pos["ticker"]
        pj_pos = portfolio.get("positions", {}).get(ticker, {})
        note = pj_pos.get("note", "")
        # Truncate long notes
        if len(note) > 60:
            note = note[:57] + "..."
        parts.append(f"| {ticker} | ${pos['deployed']:.2f} | {note} |")
    parts.append("")
    parts.append("---")
    parts.append("")

    # --- Actionable Items ---
    parts.append("## Actionable Items")
    parts.append("")
    if actionable_items:
        parts.append("| # | Priority | Item | Findings |")
        parts.append("| :--- | :--- | :--- | :--- |")
        for i, (priority, item, findings) in enumerate(actionable_items, 1):
            parts.append(f"| {i} | {priority} | {item} | {findings} |")
        parts.append("")
        parts.append("*LLM: Expand each item with nuanced guidance narratives (broker instructions, risk context).*")
    else:
        parts.append("No actionable items detected.")
    parts.append("")

    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Validate and load inputs
    raw_text, portfolio = validate_inputs()
    report_date = extract_report_date(raw_text)

    print(f"Status Pre-Analyst — {report_date.isoformat()}")

    # Parse raw data
    raw_data = parse_raw_data(raw_text)
    print(f"Parsed: {len(raw_data['active_positions'])} active, "
          f"{len(raw_data['pending_orders'])} pending orders, "
          f"{len(raw_data['watchlist_prices'])} watchlist")

    # Compute heat map
    heat_map, total_pl, total_deployed = compute_heat_map(raw_data, portfolio)
    print(f"Heat map: {len(heat_map)} positions, total P/L {fmt_dollar(total_pl)}")

    # Detect fill alerts
    fill_alerts = detect_fill_alerts(raw_data, portfolio)
    print(f"Fill alerts: {len(fill_alerts)}")

    # Per-position detail
    per_position_data = []
    all_pj_orders = portfolio.get("pending_orders", {})
    for pos in heat_map:
        ticker = pos["ticker"]
        detail = raw_data["ticker_details"].get(ticker, {})

        # Group orders
        grouped = group_orders_by_zone(ticker, portfolio)

        # Annotate wick levels
        ticker_orders = all_pj_orders.get(ticker, [])
        wick_levels = annotate_wick_levels(
            detail.get("wick_levels", []),
            ticker_orders
        )

        # Sell projection
        sell_proj = compute_sell_projections(portfolio, ticker, pos["current"])

        # Earnings day count (recomputed)
        earnings = detail.get("structural", {}).get("earnings", {})
        earnings_day_count = None
        if earnings.get("exists") and earnings.get("earnings_date"):
            try:
                ed = date.fromisoformat(earnings["earnings_date"])
                earnings_day_count = (ed - report_date).days
            except ValueError:
                pass

        per_position_data.append({
            "ticker": ticker,
            "strategy": pos["strategy"],
            "shares": pos["shares"],
            "avg_cost": pos["avg_cost"],
            "current": pos["current"],
            "deployed": pos["deployed"],
            "current_value": pos["current_value"],
            "pl_dollar": pos["pl_dollar"],
            "pl_pct": pos["pl_pct"],
            "trade_log": detail.get("trade_log", []),
            "grouped_orders": grouped,
            "wick_levels": wick_levels,
            "sell_projection": sell_proj,
            "structural": detail.get("structural", {}),
            "earnings_day_count": earnings_day_count,
        })

    # Watchlist data
    watchlist_data = []
    # Build price lookup from raw watchlist table
    wl_price_lookup = {wp["ticker"]: wp for wp in raw_data["watchlist_prices"]}

    # Determine watchlist tickers (on watchlist but not active)
    active_tickers = {pos["ticker"] for pos in heat_map}
    watchlist_tickers = [t for t in portfolio.get("watchlist", []) if t not in active_tickers]

    # Also include pending-only tickers in watchlist table
    pending_only = set(portfolio.get("pending_orders", {}).keys()) - active_tickers - set(watchlist_tickers)
    pending_only_with_orders = sorted(
        t for t in pending_only
        if any(True for o in portfolio.get("pending_orders", {}).get(t, [])
               if "PAUSED" not in o.get("note", "").upper())
    )

    for ticker in watchlist_tickers + pending_only_with_orders:
        wp = wl_price_lookup.get(ticker, {})
        price = wp.get("price", 0)
        day_pct = wp.get("day_pct", "N/A")

        # Find B1 price: first from pending orders, then from wick levels in raw data
        b1_price = None
        dist_to_b1 = None

        # Check pending orders for first (highest) non-paused BUY
        pj_orders = all_pj_orders.get(ticker, [])
        buy_orders = sorted(
            [o for o in pj_orders if o.get("type") == "BUY" and "PAUSED" not in o.get("note", "").upper()],
            key=lambda o: o["price"],
            reverse=True  # Highest first (closest to current)
        )
        if buy_orders:
            b1_price = buy_orders[0]["price"]

        # Fallback: parse wick levels from raw watchlist_levels section
        if b1_price is None:
            wl_text = raw_data["watchlist_levels"].get(ticker, "")
            if wl_text:
                wl_wick = _parse_wick_table(wl_text.split("\n"))
                if wl_wick:
                    # Highest buy_at price = B1 (closest to current)
                    b1_price = max(w["buy_at"] for w in wl_wick)

        if price and b1_price:
            dist_to_b1 = (b1_price - price) / price * 100

        # Count orders placed
        non_paused = [o for o in pj_orders if "PAUSED" not in o.get("note", "").upper()]
        orders_placed = len(non_paused)

        watchlist_data.append({
            "ticker": ticker,
            "price": price,
            "day_pct": day_pct,
            "b1_price": b1_price,
            "dist_to_b1": dist_to_b1,
            "orders_placed": orders_placed,
        })

    # Earnings gates
    earnings_gates = compute_earnings_gates(raw_data, report_date)
    print(f"Earnings gates: {len(earnings_gates)}")

    # Near-fill orders
    near_fills = compute_near_fill_orders(raw_data["pending_orders"])
    # Sort by distance ascending
    near_fills.sort(key=lambda x: x["distance_pct"])
    print(f"Near-fill orders: {len(near_fills)}")

    # Time stops
    time_stops = compute_time_stops(portfolio, report_date)
    print(f"Time stops: {len(time_stops)}")

    # Stale data
    stale_data = compute_stale_data(raw_data, report_date)
    print(f"Stale data: {len(stale_data)}")

    # Capital summary
    capital_summary = compute_capital_summary(portfolio, heat_map)

    # Actionable skeleton
    actionable_items = build_actionable_skeleton(fill_alerts, earnings_gates, near_fills,
                                                  time_stops, stale_data)
    print(f"Actionable items: {len(actionable_items)}")

    # Build report
    content = build_report(
        report_date, heat_map, total_pl, total_deployed, fill_alerts,
        per_position_data, watchlist_data, raw_data["velocity_bounce"],
        capital_summary, actionable_items, portfolio
    )

    # Write output
    OUTPUT_PATH.write_text(content, encoding="utf-8")
    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"\nOutput: status-pre-analyst.md ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
