#!/usr/bin/env python3
"""Portfolio alignment checker — scan all tickers or compare one against broker data.

Usage:
    python3 tools/alignment_checker.py                    # scan mode
    python3 tools/alignment_checker.py CLSK 3 9.71        # per-ticker: TICKER SHARES AVG
"""

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = PROJECT_ROOT / "portfolio.json"
TICKERS_DIR = PROJECT_ROOT / "tickers"
OUTPUT_PATH = PROJECT_ROOT / "alignment-report.md"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bullet_recommender import parse_bullets_used as _br_parse_bullets_used


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_buy_at(value: str) -> float | None:
    """Parse a Buy At cell value into a float, or None for excluded/dead levels.

    Returns None for: N/A variants, ↑above suffix, unparseable values.
    Strips bold markers (**), dollar signs, commas before parsing.
    """
    if value is None:
        return None
    v = value.strip().replace("**", "")
    if v.startswith("N/A"):
        return None
    if "above" in v.lower():
        return None
    v = v.replace("$", "").replace(",", "")
    try:
        return float(v)
    except ValueError:
        return None


def parse_dollar(value: str) -> float | None:
    """Parse a dollar cell like '$9.16' or '**$14.88**' into a float."""
    if value is None:
        return None
    v = value.strip().replace("**", "").replace("$", "").replace(",", "")
    if v.startswith("N/A") or v == "—" or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def parse_pct(value: str) -> str:
    """Normalise a hold-rate cell: strip bold, whitespace."""
    if value is None:
        return ""
    return value.strip().replace("**", "")


def is_pre_strategy(position: dict) -> bool:
    """Return True if position is pre-strategy (before our system started)."""
    entry = position.get("entry_date", "")
    note = position.get("note", "")
    if str(entry).startswith("pre-"):
        return True
    if re.search(r"(?i)pre-strategy|recovery", note):
        return True
    return False


def parse_zone_from_note(note: str) -> str:
    """Derive zone label from an order's note field."""
    if not note:
        return ""
    if re.match(r"(?i)^(Bullet|Last active)", note):
        return "Active"
    if re.match(r"(?i)^Reserve", note):
        return "Reserve"
    return ""


def detect_pause(note: str) -> dict | None:
    """Detect PAUSED keyword and extract until-date from note."""
    if not note or "PAUSED" not in note.upper():
        return None
    m = re.search(r"(?:until\s+(?:post-earnings\s+)?|post-earnings\s+)(\w+\s+\d+)", note)
    if not m:
        return {"paused": True, "until": "unknown", "days_away": None}
    date_str = m.group(1)
    try:
        # Parse "Feb 26" style dates — try current year, bump to next if in past
        today = date.today()
        dt = datetime.strptime(f"{date_str} {today.year}", "%b %d %Y").date()
        if dt < today:
            dt = datetime.strptime(f"{date_str} {today.year + 1}", "%b %d %Y").date()
        days = (dt - today).days
        return {"paused": True, "until": date_str, "days_away": days}
    except ValueError:
        return {"paused": True, "until": date_str, "days_away": None}


def is_bounce_derived(note: str) -> bool:
    """Return True if order comes from bounce analysis (hourly data)."""
    return "bounce-derived" in (note or "").lower()


# ---------------------------------------------------------------------------
# Table parsing
# ---------------------------------------------------------------------------

def parse_markdown_table(text: str, header_pattern: str) -> list[dict]:
    """Parse a markdown table following a header that matches *header_pattern*.

    Column-count-agnostic: reads header row dynamically.
    Handles 8-space indentation, bold markers, and varying column counts.
    Returns list[dict] keyed by stripped header names.
    """
    lines = text.split("\n")
    # Find the header line
    start_idx = None
    for i, line in enumerate(lines):
        if re.search(header_pattern, line):
            start_idx = i
            break
    if start_idx is None:
        return []

    # Find the first "|" table row after the header
    table_start = None
    for i in range(start_idx, min(start_idx + 5, len(lines))):
        stripped = lines[i].strip()
        if stripped.startswith("|") and "---" not in stripped:
            table_start = i
            break
    if table_start is None:
        return []

    # Parse column headers
    header_line = lines[table_start].strip()
    headers = [h.strip().replace("**", "") for h in header_line.split("|")]
    headers = [h for h in headers if h]  # drop empty from leading/trailing |

    # Skip alignment row
    data_start = table_start + 1
    if data_start < len(lines) and "---" in lines[data_start]:
        data_start += 1

    # Parse data rows
    rows = []
    for i in range(data_start, len(lines)):
        stripped = lines[i].strip()
        if not stripped.startswith("|"):
            break
        cells = [c.strip() for c in stripped.split("|")]
        # Drop only leading/trailing empties from pipe splitting, not interior empties
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        if len(cells) < len(headers):
            # Pad short rows
            cells.extend([""] * (len(headers) - len(cells)))
        row = {}
        for j, hdr in enumerate(headers):
            row[hdr] = cells[j] if j < len(cells) else ""
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_portfolio() -> dict:
    with open(PORTFOLIO_PATH, "r") as f:
        return json.load(f)


def load_identity_wick_table(ticker: str) -> list[dict]:
    """Parse Wick-Adjusted Buy Levels table from tickers/TICKER/identity.md.

    Returns empty list if file or section not found.
    """
    path = TICKERS_DIR / ticker / "identity.md"
    if not path.exists():
        return []
    text = path.read_text()
    return parse_markdown_table(text, r"Wick-Adjusted Buy Levels")


def load_wick_analysis_table(ticker: str) -> tuple[str, list[dict]]:
    """Parse Support Levels & Buy Recommendations from wick_analysis.md.

    Returns (generation_date, rows). Date is '' if not found.
    """
    path = TICKERS_DIR / ticker / "wick_analysis.md"
    if not path.exists():
        return ("", [])
    text = path.read_text()
    # Extract generation date
    gen_date = ""
    m = re.search(r"\*Generated:\s*(\d{4}-\d{2}-\d{2})", text)
    if m:
        gen_date = m.group(1)
    rows = parse_markdown_table(text, r"Support Levels & Buy Recommendations")
    return (gen_date, rows)


# ---------------------------------------------------------------------------
# Comparison logic
# ---------------------------------------------------------------------------

def _support_price(row: dict) -> float | None:
    """Extract support price from either identity or wick table row."""
    for key in ("Raw Support", "Support"):
        if key in row:
            return parse_dollar(row[key])
    return None


def compare_wick_tables(identity_table: list[dict],
                        wick_table: list[dict]) -> list[dict]:
    """Compare identity.md wick table against wick_analysis.md table.

    Match by support price within $0.10 tolerance.
    Returns list of changes and structural differences.
    """
    changes = []
    wick_by_price = {}
    for row in wick_table:
        price = _support_price(row)
        if price is not None:
            wick_by_price[price] = row

    matched_wick_prices = set()

    for irow in identity_table:
        iprice = _support_price(irow)
        if iprice is None:
            continue
        # Find matching wick row by price tolerance (prefer closest)
        match = None
        match_price = None
        best_delta = 999
        for wp, wrow in wick_by_price.items():
            delta = abs(wp - iprice)
            if delta <= 0.10 and delta < best_delta:
                best_delta = delta
                match = wrow
                match_price = wp
        if match is None:
            # Level in identity but not in wick — removed
            changes.append({
                "support": f"${iprice:.2f}",
                "field": "REMOVED",
                "identity_val": "present",
                "wick_val": "absent from wick_analysis"
            })
            continue
        matched_wick_prices.add(match_price)

        # Skip rows where BOTH Buy At are None (dead levels)
        i_buy = parse_buy_at(irow.get("Buy At", ""))
        w_buy = parse_buy_at(match.get("Buy At", ""))
        if i_buy is None and w_buy is None:
            continue

        # Compare Hold Rate
        i_hold = parse_pct(irow.get("Hold Rate", ""))
        w_hold = parse_pct(match.get("Hold Rate", ""))
        if i_hold and w_hold and i_hold != w_hold:
            changes.append({
                "support": f"${iprice:.2f}",
                "field": "Hold Rate",
                "identity_val": i_hold,
                "wick_val": w_hold,
            })

        # Compare Buy At — handle transition case (float → None / above)
        if i_buy is not None and w_buy is None:
            changes.append({
                "support": f"${iprice:.2f}",
                "field": "Buy At",
                "identity_val": f"${i_buy:.2f}",
                "wick_val": "EXCLUDED (now above market)",
            })
        elif i_buy is None and w_buy is not None:
            changes.append({
                "support": f"${iprice:.2f}",
                "field": "Buy At",
                "identity_val": irow.get("Buy At", "N/A"),
                "wick_val": f"${w_buy:.2f}",
            })
        elif i_buy is not None and w_buy is not None and abs(i_buy - w_buy) > 0.005:
            changes.append({
                "support": f"${iprice:.2f}",
                "field": "Buy At",
                "identity_val": f"${i_buy:.2f}",
                "wick_val": f"${w_buy:.2f}",
            })

        # Compare Tier if BOTH tables have it
        if "Tier" in irow and "Tier" in match:
            i_tier = irow["Tier"].strip().replace("**", "")
            w_tier = match["Tier"].strip().replace("**", "")
            if i_tier and w_tier and i_tier != w_tier:
                changes.append({
                    "support": f"${iprice:.2f}",
                    "field": "Tier",
                    "identity_val": i_tier,
                    "wick_val": w_tier,
                })

    # Levels in wick but not in identity (new)
    for wp, wrow in wick_by_price.items():
        if wp not in matched_wick_prices:
            # Check if any identity price is close
            found = False
            for irow in identity_table:
                ip = _support_price(irow)
                if ip is not None and abs(ip - wp) <= 0.10:
                    found = True
                    break
            if not found:
                changes.append({
                    "support": f"${wp:.2f}",
                    "field": "NEW",
                    "identity_val": "absent from identity",
                    "wick_val": "present in wick_analysis",
                })

    return changes


def validate_pending_orders(pending: list[dict],
                            wick_analysis_table: list[dict],
                            pre_strategy: bool = False) -> dict:
    """Validate pending BUY orders against wick_analysis.md table.

    Uses wick_analysis_table (9-col with Zone) — NOT identity table.
    """
    result = {
        "matched": [],
        "mismatched": [],
        "missing_from_orders": [],
        "bounce_derived": [],
        "paused": [],
        "zone_mismatches": [],
    }

    buy_orders = [o for o in pending if o.get("type") == "BUY"]

    # Group wick levels by Buy At price (for converged levels)
    wick_by_buy_at: dict[float, list[dict]] = {}
    for row in wick_analysis_table:
        ba = parse_buy_at(row.get("Buy At", ""))
        if ba is not None:
            wick_by_buy_at.setdefault(ba, []).append(row)

    matched_wick_prices = set()

    for order in buy_orders:
        note = order.get("note", "")
        price = order["price"]

        # Bounce-derived — skip wick validation
        if is_bounce_derived(note):
            result["bounce_derived"].append({
                "order": order,
                "status": "bounce-derived (skip wick validation)",
            })
            continue

        # Pause detection
        pause_info = detect_pause(note)
        if pause_info:
            result["paused"].append({
                "order": order,
                "pause": pause_info,
            })

        # Find matching wick level by buy_at price (±$0.10, prefer closest)
        match_ba = None
        match_rows = None
        best_delta = 999
        for ba, rows in wick_by_buy_at.items():
            delta = abs(ba - price)
            if delta <= 0.10 and delta < best_delta:
                best_delta = delta
                match_ba = ba
                match_rows = rows

        if match_rows:
            matched_wick_prices.add(match_ba)
            # Build description
            if len(match_rows) > 1:
                parts = []
                for r in match_rows:
                    sp = r.get("Support", "?")
                    src = r.get("Source", "?")
                    hr = parse_pct(r.get("Hold Rate", "?"))
                    parts.append(f"{sp} {src} {hr}")
                desc = f"Converged: {' + '.join(parts)} → ${match_ba:.2f}"
            else:
                r = match_rows[0]
                desc = f"${match_ba:.2f} ({parse_pct(r.get('Hold Rate', '?'))})"

            entry = {
                "order": order,
                "wick_match": desc,
                "status": "OK",
            }

            # Zone check
            order_zone = parse_zone_from_note(note)
            if order_zone and match_rows:
                wick_zone = match_rows[0].get("Zone", "").strip()
                if wick_zone and order_zone != wick_zone:
                    result["zone_mismatches"].append({
                        "order": order,
                        "order_zone": order_zone,
                        "wick_zone": wick_zone,
                        "support": match_rows[0].get("Support", "?"),
                    })
                    entry["status"] = f"ZONE MISMATCH ({order_zone} vs {wick_zone})"

            # Pause annotation — append to existing status, don't overwrite
            if pause_info:
                days_str = f"{pause_info['days_away']} days" if pause_info['days_away'] is not None else "?"
                pause_str = f"PAUSED until {pause_info['until']} ({days_str})"
                if entry["status"] != "OK":
                    entry["status"] += f" + {pause_str}"
                else:
                    entry["status"] = pause_str

            result["matched"].append(entry)
        else:
            # No match — mismatched or orphan order
            result["mismatched"].append({
                "order": order,
                "status": "no matching wick level",
            })

    # Missing from orders: wick levels (Active zone only) with no order
    if not pre_strategy:
        for ba, rows in wick_by_buy_at.items():
            if ba in matched_wick_prices:
                continue
            # Check if any bounce-derived order matches this price
            bounce_match = False
            for bd in result["bounce_derived"]:
                if abs(bd["order"]["price"] - ba) <= 0.10:
                    bounce_match = True
                    break
            if bounce_match:
                continue
            # Only report Active zone levels
            zone = rows[0].get("Zone", "").strip()
            if zone != "Active":
                continue
            # Exclude ↑above levels
            raw_buy = rows[0].get("Buy At", "")
            if "above" in raw_buy.lower():
                continue
            result["missing_from_orders"].append({
                "buy_at": ba,
                "rows": rows,
            })

    return result


def _sum_pending_by_zone(buy_orders: list[dict]) -> tuple[float, float, float]:
    """Sum pending BUY order costs by zone. Returns (active, reserve, unclassified)."""
    active = reserve = unclassified = 0.0
    for o in buy_orders:
        cost = o["price"] * o["shares"]
        zone = parse_zone_from_note(o.get("note", ""))
        if zone == "Active":
            active += cost
        elif zone == "Reserve":
            reserve += cost
        else:
            unclassified += cost
    return active, reserve, unclassified


def compute_pool_usage(position: dict | None, pending: list[dict],
                       capital: dict) -> dict:
    """Compute pool budget usage with separate active/reserve tracking."""
    buy_orders = [o for o in pending if o.get("type") == "BUY"]
    active_budget = capital.get("active_pool", 300)
    reserve_budget = capital.get("reserve_pool", 300)
    pending_active, pending_reserve, pending_unclassified = _sum_pending_by_zone(buy_orders)

    # Watchlist-only
    if position is None:
        return {
            "watchlist_only": True,
            "deployed": 0,
            "pending_active": pending_active,
            "pending_reserve": pending_reserve,
            "pending_unclassified": pending_unclassified,
            "active_budget": active_budget,
            "reserve_budget": reserve_budget,
            "active_remaining": active_budget - pending_active,
            "reserve_remaining": reserve_budget - pending_reserve,
            "active_overrun": pending_active > active_budget,
            "reserve_overrun": pending_reserve > reserve_budget,
        }

    # Pre-strategy
    if is_pre_strategy(position):
        return {
            "pre_strategy": True,
            "note": "Pre-strategy recovery mode — standard validation bypassed",
        }

    # Deployed capital (shares * avg) counts toward the active pool budget because
    # initial entries always come from active bullets.  Reserve pool only funds
    # deeper pending BUY orders, so reserve_remaining excludes deployed.
    deployed = position["shares"] * position["avg_cost"]
    return {
        "deployed": deployed,
        "pending_active": pending_active,
        "pending_reserve": pending_reserve,
        "pending_unclassified": pending_unclassified,
        "active_budget": active_budget,
        "reserve_budget": reserve_budget,
        "active_remaining": active_budget - (deployed + pending_active),
        "reserve_remaining": reserve_budget - pending_reserve,
        "active_overrun": (deployed + pending_active) > active_budget,
        "reserve_overrun": pending_reserve > reserve_budget,
    }


def check_sell_target(position: dict | None, pending: list[dict]) -> dict:
    """Return informational sell target data."""
    if position is None:
        return {"status": "No position"}
    target = position.get("target_exit")
    if target is None:
        return {"status": "No target (recovery mode)"}
    avg = position["avg_cost"]
    pct = (target - avg) / avg * 100

    # Find SELL order
    sell_note = "—"
    for o in pending:
        if o.get("type") == "SELL":
            sell_note = o.get("note", "—")
            break

    return {
        "current_target": target,
        "avg_cost": avg,
        "target_pct": pct,
        "sell_note": sell_note,
        "status": "Info",
    }


def detect_watchlist_conflicts(portfolio: dict) -> list[str]:
    """Return tickers that appear in both positions (shares > 0) and watchlist."""
    positions = set(portfolio.get("positions", {}).keys())
    watchlist = set(portfolio.get("watchlist", []))
    return sorted(positions & watchlist)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_dollar(val: float | None) -> str:
    if val is None:
        return "N/A"
    return f"${val:.2f}"


def fmt_pct(val: float | None) -> str:
    if val is None:
        return "N/A"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.1f}%"


def days_ago(date_str: str) -> int | None:
    """Return days between date_str (YYYY-MM-DD) and today."""
    if not date_str:
        return None
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        return (date.today() - dt).days
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Per-ticker mode
# ---------------------------------------------------------------------------

def run_ticker(ticker: str, broker_shares: int, broker_avg: float,
               portfolio: dict) -> str:
    """Run alignment for a single ticker with broker data."""
    lines = []
    today_str = date.today().isoformat()
    position = portfolio.get("positions", {}).get(ticker)
    pending = portfolio.get("pending_orders", {}).get(ticker, [])
    capital = portfolio.get("capital", {})
    pre_strat = position is not None and is_pre_strategy(position)
    tag = "  [PRE-STRATEGY]" if pre_strat else ""

    lines.append(f"# Alignment: {ticker} — {today_str}{tag}")
    lines.append("")

    # --- Position Comparison ---
    lines.append("## Position Comparison")
    lines.append("| Field | Broker | Portfolio | Delta | Status |")
    lines.append("| :--- | :--- | :--- | :--- | :--- |")
    port_shares = position["shares"] if position else 0
    port_avg = position["avg_cost"] if position else 0.0
    share_delta = broker_shares - port_shares
    if share_delta > 0:
        share_status = f"**POSSIBLE FILL: +{share_delta} shares**"
    elif share_delta < 0:
        share_status = f"**POSSIBLE PARTIAL SELL: {share_delta} shares**"
    else:
        share_status = "Shares match."
    lines.append(f"| Shares | {broker_shares} | {port_shares} | "
                 f"{'—' if share_delta == 0 else f'{share_delta:+d}'} | {share_status} |")
    avg_delta = broker_avg - port_avg
    if abs(avg_delta) < 0.005:
        avg_delta_str = "—"
    elif avg_delta > 0:
        avg_delta_str = f"**+${avg_delta:.2f}**"
    else:
        avg_delta_str = f"**-${abs(avg_delta):.2f}**"
    lines.append(f"| Avg Cost | {fmt_dollar(broker_avg)} | {fmt_dollar(port_avg)} | "
                 f"{avg_delta_str} | — |")
    lines.append("")

    # --- Wick Data ---
    wick_date, wick_table = load_wick_analysis_table(ticker)
    identity_table = load_identity_wick_table(ticker)
    da = days_ago(wick_date)

    if wick_date:
        lines.append(f"## Wick Data (generated {da} day{'s' if da != 1 else ''} ago)")
    else:
        lines.append("## Wick Data")
        lines.append("*No wick_analysis.md found.*")

    if identity_table and wick_table:
        changes = compare_wick_tables(identity_table, wick_table)
        if changes:
            lines.append("| Support | Field | Identity | Wick | Status |")
            lines.append("| :--- | :--- | :--- | :--- | :--- |")
            for c in changes:
                lines.append(f"| {c['support']} | {c['field']} | {c['identity_val']} | "
                             f"{c['wick_val']} | **STALE** |")
        else:
            lines.append("*Identity table matches wick_analysis — no stale data.*")
    elif wick_table and not identity_table:
        lines.append(f"*wick_analysis.md exists ({wick_date}) but identity.md has no wick table — data not synced.*")
    elif not wick_table:
        lines.append("*No wick data available.*")
    lines.append("")

    # --- Pending Orders ---
    lines.append("## Pending Orders")
    if pending:
        buy_orders = [o for o in pending if o.get("type") == "BUY"]
        if buy_orders:
            validation = validate_pending_orders(pending, wick_table, pre_strategy=pre_strat)
            lines.append("| Order | Price | Shares | Wick Match | Status |")
            lines.append("| :--- | :--- | :--- | :--- | :--- |")
            for m in validation["matched"]:
                o = m["order"]
                note = o.get("note", "")
                label = _order_label(note)
                lines.append(f"| {label} | {fmt_dollar(o['price'])} | {o['shares']} | "
                             f"{m['wick_match']} | {m['status']} |")
            for bd in validation["bounce_derived"]:
                o = bd["order"]
                note = o.get("note", "")
                label = _order_label(note)
                lines.append(f"| {label} | {fmt_dollar(o['price'])} | {o['shares']} | "
                             f"{bd['status']} | OK |")
            for mm in validation["mismatched"]:
                o = mm["order"]
                note = o.get("note", "")
                label = _order_label(note)
                lines.append(f"| {label} | {fmt_dollar(o['price'])} | {o['shares']} | "
                             f"{mm['status']} | **REVIEW** |")
            if validation["missing_from_orders"]:
                lines.append("")
                lines.append("**Missing orders for active wick levels:**")
                for miss in validation["missing_from_orders"]:
                    rows_desc = ", ".join(
                        f"${sp:.2f} {r.get('Source', '?')}"
                        for r in miss["rows"]
                        if (sp := _support_price(r)) is not None
                    )
                    lines.append(f"- Buy At ${miss['buy_at']:.2f} ({rows_desc})")
            if validation["zone_mismatches"]:
                lines.append("")
                lines.append("**Zone mismatches:**")
                for zm in validation["zone_mismatches"]:
                    o = zm["order"]
                    lines.append(f"- {fmt_dollar(o['price'])} order says {zm['order_zone']}, "
                                 f"wick says {zm['wick_zone']} (support {zm['support']})")
        else:
            lines.append("*No pending BUY orders.*")
    else:
        lines.append("*No pending orders.*")
    lines.append("")

    # --- Pool Usage ---
    lines.append("## Pool Usage")
    pool = compute_pool_usage(position, pending, capital)
    if pool.get("pre_strategy"):
        lines.append(f"*{pool['note']}*")
    else:
        lines.append("| Zone | Deployed | Pending | Budget | Remaining | Status |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        deployed = pool.get("deployed", 0)
        lines.append(f"| Active | {fmt_dollar(deployed)} | {fmt_dollar(pool['pending_active'])} | "
                     f"{fmt_dollar(pool['active_budget'])} | {fmt_dollar(pool['active_remaining'])} | "
                     f"{'**OVER**' if pool['active_overrun'] else 'OK'} |")
        lines.append(f"| Reserve | — | {fmt_dollar(pool['pending_reserve'])} | "
                     f"{fmt_dollar(pool['reserve_budget'])} | {fmt_dollar(pool['reserve_remaining'])} | "
                     f"{'**OVER**' if pool['reserve_overrun'] else 'OK'} |")
        if pool.get("pending_unclassified", 0) > 0.005:
            lines.append(f"\n*Warning: {fmt_dollar(pool['pending_unclassified'])} in pending orders not classified as Active or Reserve.*")
    lines.append("")

    # --- Sell Target ---
    lines.append("## Sell Target")
    sell = check_sell_target(position, pending)
    if sell["status"] in ("No position", "No target (recovery mode)"):
        lines.append(f"*{sell['status']}*")
    else:
        lines.append("| Target | Avg | Target % | Note |")
        lines.append("| :--- | :--- | :--- | :--- |")
        # Use broker avg for pct calc
        broker_pct = ((sell["current_target"] - broker_avg) / broker_avg * 100
                      if broker_avg > 0 else None)
        lines.append(f"| {fmt_dollar(sell['current_target'])} | {fmt_dollar(broker_avg)} | "
                     f"{fmt_pct(broker_pct)} | {sell['sell_note']} |")
    lines.append("")

    # --- Recommended Updates ---
    lines.append("## Recommended Updates")
    updates = []
    if share_delta != 0 or abs(avg_delta) > 0.005:
        updates.append(f'  "shares": {broker_shares},')
        updates.append(f'  "avg_cost": {broker_avg},')
    if updates:
        lines.append("```json")
        lines.append(f'"{ticker}": {{')
        lines.extend(updates)
        lines.append("}")
        lines.append("```")
    else:
        lines.append("*No updates needed.*")

    return "\n".join(lines)


def _order_label(note: str) -> str:
    """Extract short label like 'F2', legacy 'B2', or 'R1' from note."""
    if not note:
        return "?"
    m = re.match(r"(F\d+|A\d+|B\d+|R\d+)", note, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    m = re.match(r"(Bullet|Reserve|Last active)\s*(\d*)", note)
    if m:
        kind = m.group(1)
        num = m.group(2)
        if kind == "Bullet":
            return f"F{num}"
        elif kind == "Last active":
            return "Last"
        elif kind == "Reserve":
            return f"R{num}"
    return note[:10]


# ---------------------------------------------------------------------------
# Scan mode
# ---------------------------------------------------------------------------

def run_scan(portfolio: dict) -> str:
    """Generate full portfolio alignment scan."""
    lines = []
    today_str = date.today().isoformat()
    lines.append(f"# Portfolio Alignment Scan — {today_str}")
    lines.append("")

    positions = portfolio.get("positions", {})
    pending_orders = portfolio.get("pending_orders", {})
    watchlist = set(portfolio.get("watchlist", []))
    capital = portfolio.get("capital", {})

    # Data-driven ticker set
    all_tickers = sorted(
        set(positions.keys())
        | {k for k, v in pending_orders.items() if v}
        | watchlist
    )

    # Collect data per ticker
    pre_strat_rows = []
    wick_freshness_rows = []
    earnings_rows = []
    watchlist_no_orders = []
    conflicts = detect_watchlist_conflicts(portfolio)
    pool_rows = []
    sell_rows = []
    unsync_rows = []
    zone_mismatch_rows = []
    mismatch_rows = []
    bounce_rows = []
    converged_rows = []
    missing_rows = []
    fill_gap_rows = []

    for ticker in all_tickers:
        position = positions.get(ticker)
        pending = pending_orders.get(ticker, [])
        pre_strat = position is not None and is_pre_strategy(position)

        # Pre-strategy
        if pre_strat:
            note = position.get("note", "")
            # Condense note
            if "Active pool exhausted" in note:
                short_note = "Active pool exhausted — reserve orders pending"
            elif "recovery" in note.lower():
                short_note = "Recovery mode — pool validation bypassed"
            else:
                short_note = note[:60]
            pre_strat_rows.append({
                "ticker": ticker,
                "shares": position["shares"],
                "avg": position["avg_cost"],
                "note": short_note,
            })

        # Wick freshness
        wick_date, wick_table = load_wick_analysis_table(ticker)
        identity_table = load_identity_wick_table(ticker)
        da = days_ago(wick_date)

        # Unsync detection
        if wick_table and not identity_table:
            unsync_rows.append({
                "ticker": ticker,
                "issue": f"wick_analysis.md exists ({wick_date}) but identity.md has no wick table — data not synced",
            })

        # Wick staleness
        stale_changes = []
        if identity_table and wick_table:
            changes = compare_wick_tables(identity_table, wick_table)
            stale_changes = changes

        stale_summary = ""
        if stale_changes:
            parts = []
            for c in stale_changes[:3]:  # Limit summary
                parts.append(f"{c['support']}: {c['field']} {c['identity_val']}→{c['wick_val']}")
            stale_summary = "; ".join(parts)
            if len(stale_changes) > 3:
                stale_summary += f" (+{len(stale_changes)-3} more)"

        if wick_date:
            wick_freshness_rows.append({
                "ticker": ticker,
                "generated": wick_date,
                "days_ago": da,
                "stale_count": len(stale_changes),
                "stale_summary": stale_summary,
            })

        # Pending order validation
        if pending:
            buy_orders = [o for o in pending if o.get("type") == "BUY"]
            if buy_orders:
                validation = validate_pending_orders(pending, wick_table, pre_strategy=pre_strat)

                # Earnings/paused
                for p in validation["paused"]:
                    o = p["order"]
                    pi = p["pause"]
                    days_str = f"{pi['days_away']}" if pi['days_away'] is not None else "?"
                    earnings_rows.append({
                        "ticker": ticker,
                        "label": _order_label(o.get("note", "")),
                        "order_desc": f"{fmt_dollar(o['price'])} ({o['shares']}sh)",
                        "until": pi["until"],
                        "days_away": days_str,
                    })

                # Mismatches
                for mm in validation["mismatched"]:
                    o = mm["order"]
                    mismatch_rows.append({
                        "ticker": ticker,
                        "label": _order_label(o.get("note", "")),
                        "current": fmt_dollar(o["price"]),
                        "wick_says": mm["status"],
                    })

                # Bounce-derived
                for bd in validation["bounce_derived"]:
                    o = bd["order"]
                    bounce_rows.append({
                        "ticker": ticker,
                        "label": _order_label(o.get("note", "")),
                        "price": fmt_dollar(o["price"]),
                        "shares": o["shares"],
                    })

                # Zone mismatches
                for zm in validation["zone_mismatches"]:
                    o = zm["order"]
                    zone_mismatch_rows.append({
                        "ticker": ticker,
                        "label": _order_label(o.get("note", "")),
                        "price": fmt_dollar(o["price"]),
                        "shares": o["shares"],
                        "order_zone": zm["order_zone"],
                        "wick_zone": zm["wick_zone"],
                        "support": zm["support"],
                    })

                # Converged levels
                for m in validation["matched"]:
                    if "Converged:" in m.get("wick_match", ""):
                        o = m["order"]
                        converged_rows.append({
                            "ticker": ticker,
                            "label": _order_label(o.get("note", "")),
                            "price": fmt_dollar(o["price"]),
                            "shares": o["shares"],
                            "levels": m["wick_match"].replace("Converged: ", ""),
                        })

                # Missing from orders
                for miss in validation["missing_from_orders"]:
                    rows_desc = ", ".join(
                        f"${sp:.2f} {r.get('Source', '?')}"
                        for r in miss["rows"]
                        if (sp := _support_price(r)) is not None
                    )
                    missing_rows.append({
                        "ticker": ticker,
                        "buy_at": fmt_dollar(miss["buy_at"]),
                        "desc": rows_desc,
                    })

        # Watchlist no orders
        if ticker in watchlist and not pending and position is None:
            has_wick = bool(wick_date)
            watchlist_no_orders.append({
                "ticker": ticker,
                "wick_data": "Yes" if has_wick else "No",
                "generated": wick_date if has_wick else "—",
                "days_ago": str(da) if da is not None else "—",
            })

        # Pool usage — skip tickers with no capital at risk
        if position or pending:
            pool = compute_pool_usage(position, pending, capital)
        else:
            pool = None
        if pool and not pool.get("pre_strategy"):
            deployed = pool.get("deployed", 0)
            pool_rows.append({
                "ticker": ticker,
                "deployed": deployed,
                "pending_active": pool["pending_active"],
                "active_budget": pool["active_budget"],
                "active_status": "**OVER**" if pool["active_overrun"] else "OK",
                "pending_reserve": pool["pending_reserve"],
                "reserve_budget": pool["reserve_budget"],
                "reserve_status": "**OVER**" if pool["reserve_overrun"] else "OK",
                "watchlist_only": pool.get("watchlist_only", False),
                "pending_unclassified": pool.get("pending_unclassified", 0),
            })

        # Fill prices gap check
        if position and position.get("shares", 0) > 0:
            fp = position.get("fill_prices")
            bu = position.get("bullets_used", 0)
            parsed_bullets = _br_parse_bullets_used(bu, position.get("note", ""))
            if fp is not None and len(fp) > 0:
                expected_fills = parsed_bullets["active"] + parsed_bullets["reserve"]
                if len(fp) != expected_fills:
                    fill_gap_rows.append({"ticker": ticker, "bullets_used": str(bu),
                                          "expected": expected_fills, "actual": len(fp)})

        # Sell target
        sell = check_sell_target(position, pending)
        if sell.get("current_target"):
            sell_rows.append({
                "ticker": ticker,
                "target": fmt_dollar(sell["current_target"]),
                "avg": fmt_dollar(sell["avg_cost"]),
                "target_pct": fmt_pct(sell["target_pct"]),
                "note": sell.get("sell_note", "—"),
            })

    # --- Render sections ---

    # Pre-strategy
    if pre_strat_rows:
        lines.append("## Pre-Strategy Positions")
        lines.append("| Ticker | Shares | Avg | Note |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for r in pre_strat_rows:
            lines.append(f"| {r['ticker']} | {r['shares']} | {fmt_dollar(r['avg'])} | {r['note']} |")
        lines.append("")

    # Wick freshness
    if wick_freshness_rows:
        lines.append("## Wick Analysis Freshness")
        lines.append("| Ticker | Generated | Days Ago | Stale Levels |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for r in wick_freshness_rows:
            stale_str = f"{r['stale_count']}"
            if r["stale_summary"]:
                stale_str += f" ({r['stale_summary']})"
            lines.append(f"| {r['ticker']} | {r['generated']} | {r['days_ago']} | {stale_str} |")
        lines.append("")

    # Earnings gates / paused
    if earnings_rows:
        lines.append("## Earnings Gates / Paused Orders")
        lines.append("| Ticker | Order | Paused Until | Days Away |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for r in earnings_rows:
            lines.append(f"| {r['ticker']} {r['label']} | {r['order_desc']} | {r['until']} | {r['days_away']} |")
        lines.append("")

    # Watchlist no orders
    if watchlist_no_orders:
        lines.append("## Watchlist — No Orders")
        lines.append("| Ticker | Wick Data | Generated | Days Ago |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for r in watchlist_no_orders:
            lines.append(f"| {r['ticker']} | {r['wick_data']} | {r['generated']} | {r['days_ago']} |")
        lines.append("")

    # Watchlist conflicts
    if conflicts:
        lines.append("## Watchlist Conflicts")
        for t in conflicts:
            lines.append(f"- {t}")
        lines.append("")

    # Pool summary
    if pool_rows:
        lines.append("## Active Pool Summary")
        lines.append("| Ticker | Deployed | Pending Active | Active Budget | Status | Pending Reserve | Reserve Budget | Status |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for r in pool_rows:
            lines.append(
                f"| {r['ticker']} | {fmt_dollar(r['deployed'])} | {fmt_dollar(r['pending_active'])} | "
                f"{fmt_dollar(r['active_budget'])} | {r['active_status']} | "
                f"{fmt_dollar(r['pending_reserve'])} | {fmt_dollar(r['reserve_budget'])} | {r['reserve_status']} |"
            )
        unclassified = [r for r in pool_rows if r["pending_unclassified"] > 0.005]
        if unclassified:
            lines.append("")
            lines.append("**Unclassified pending orders** (zone not detected from note):")
            for r in unclassified:
                lines.append(f"- {r['ticker']}: {fmt_dollar(r['pending_unclassified'])} not assigned to Active or Reserve")
        lines.append("")

    # Sell target summary
    if sell_rows:
        lines.append("## Sell Target Summary")
        lines.append("| Ticker | Target | Avg | Target % | Note |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for r in sell_rows:
            lines.append(f"| {r['ticker']} | {r['target']} | {r['avg']} | {r['target_pct']} | {r['note']} |")
        lines.append("")

    # Unsynchronized wick data
    if unsync_rows:
        lines.append("## Unsynchronized Wick Data")
        lines.append("| Ticker | Issue |")
        lines.append("| :--- | :--- |")
        for r in unsync_rows:
            lines.append(f"| {r['ticker']} | {r['issue']} |")
        lines.append("")

    # Zone mismatches
    if zone_mismatch_rows:
        lines.append("## Zone Mismatches (order zone vs wick zone)")
        lines.append("| Ticker | Order | Order Zone | Wick Zone | Support |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for r in zone_mismatch_rows:
            lines.append(f"| {r['ticker']} {r['label']} | {r['price']} ({r['shares']}sh) | "
                         f"{r['order_zone']} | {r['wick_zone']} | {r['support']} |")
        lines.append("")

    # Pending order mismatches
    if mismatch_rows:
        lines.append("## Pending Order Mismatches")
        lines.append("| Ticker | Order | Current | Wick Says | Action |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for r in mismatch_rows:
            lines.append(f"| {r['ticker']} | {r['label']} | {r['current']} | {r['wick_says']} | Review |")
        lines.append("")

    # Bounce-derived
    if bounce_rows:
        lines.append("## Bounce-Derived Orders (no wick validation)")
        lines.append("| Ticker | Order | Price | Shares |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for r in bounce_rows:
            lines.append(f"| {r['ticker']} | {r['label']} | {r['price']} | {r['shares']} |")
        lines.append("")

    # Converged levels
    if converged_rows:
        lines.append("## Converged Levels")
        lines.append("| Ticker | Order | Buy At | Levels |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for r in converged_rows:
            lines.append(f"| {r['ticker']} {r['label']} | {r['price']} ({r['shares']}sh) | {r['levels']} |")
        lines.append("")

    # Missing orders
    if missing_rows:
        lines.append("## Missing Orders (active wick levels with no pending order)")
        lines.append("| Ticker | Buy At | Level(s) |")
        lines.append("| :--- | :--- | :--- |")
        for r in missing_rows:
            lines.append(f"| {r['ticker']} | {r['buy_at']} | {r['desc']} |")
        lines.append("")

    # Fill prices gaps
    if fill_gap_rows:
        lines.append("## Fill Prices Gaps")
        lines.append("| Ticker | bullets_used | Expected Fills | Actual fill_prices | Gap |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for r in fill_gap_rows:
            diff = r["expected"] - r["actual"]
            gap_str = f"{diff} missing" if diff > 0 else f"{-diff} extra"
            lines.append(f"| {r['ticker']} | {r['bullets_used']} | {r['expected']} | {r['actual']} | {gap_str} |")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    portfolio = load_portfolio()

    if len(sys.argv) == 1:
        # Scan mode
        report = run_scan(portfolio)
        OUTPUT_PATH.write_text(report + "\n")
        print(report)
    elif len(sys.argv) == 4:
        # Per-ticker mode: TICKER SHARES AVG
        ticker = sys.argv[1].upper()
        try:
            shares = int(sys.argv[2])
            avg = float(sys.argv[3])
        except ValueError:
            print("*Usage: python3 tools/alignment_checker.py TICKER SHARES AVG*")
            sys.exit(1)
        report = run_ticker(ticker, shares, avg, portfolio)
        print(report)
    else:
        print("*Usage:*")
        print("*  python3 tools/alignment_checker.py                    # scan mode*")
        print("*  python3 tools/alignment_checker.py TICKER SHARES AVG  # per-ticker*")
        sys.exit(1)


if __name__ == "__main__":
    main()
