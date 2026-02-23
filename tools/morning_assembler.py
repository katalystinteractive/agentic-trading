#!/usr/bin/env python3
"""
Morning Assembler — Assembles per-ticker cards into morning-briefing.md.

Reads morning-work/manifest.json + all morning-work/*-card.md files +
portfolio.json + morning-briefing-condensed.md, then writes morning-briefing.md.

Replaces the LLM-based morning-assembler agent with pure Python for speed
and reliability (~5 seconds vs 600s timeout).

Usage: python3 tools/morning_assembler.py
"""

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MORNING_WORK = PROJECT_ROOT / "morning-work"
MANIFEST = MORNING_WORK / "manifest.json"
PORTFOLIO = PROJECT_ROOT / "portfolio.json"
CONDENSED = PROJECT_ROOT / "morning-briefing-condensed.md"
OUTPUT = PROJECT_ROOT / "morning-briefing.md"


# ---------------------------------------------------------------------------
# Dollar parsing (reused from morning_splitter.py)
# ---------------------------------------------------------------------------

def _parse_dollar(val):
    """Parse a dollar string like '$2,126.60' or '-$187.35' into a float."""
    if isinstance(val, (int, float)):
        return val
    try:
        cleaned = val.replace("$", "").replace(",", "").strip()
        return float(cleaned)
    except (ValueError, AttributeError):
        return 0.0


def parse_table_row(line):
    """Split a markdown table row into cells, stripping whitespace."""
    if not line.strip().startswith("|"):
        return []
    cells = line.split("|")
    return [c.strip() for c in cells[1:-1]]


# ---------------------------------------------------------------------------
# Card header parsing
# ---------------------------------------------------------------------------

def parse_card_header(first_line):
    """Extract ticker, verdict/gate, P/L from card header line.

    Active:    ### TICKER — VERDICT — P/L +X%
    Watchlist: ### TICKER — WATCHLIST — GATE_STATUS [⚠️ ...]

    Tolerant of 1-3 heading levels and multi-word verdicts.
    """
    first_line = first_line.strip()

    # Normalize: strip 1-3 leading # and whitespace
    m = re.match(r'^#{1,3}\s+(.+)$', first_line)
    if not m:
        return {"ticker": "UNKNOWN", "card_type": "unknown"}
    content = m.group(1)

    # Active card pattern — non-greedy .+? allows multi-word verdicts
    m = re.match(r'(\w+) — (.+?) — P/L (.+)$', content)
    if m:
        return {
            "ticker": m.group(1),
            "verdict": m.group(2).strip(),
            "pl": m.group(3),
            "card_type": "active",
        }

    # Watchlist card pattern: TICKER — WATCHLIST — GATE_STATUS [⚠️ ...]
    m = re.match(r'(\w+) — WATCHLIST — (.+?)(\s*⚠️.*)?$', content)
    if m:
        gate_text = m.group(2).strip()
        gate_bare = gate_text.split()[0].strip()
        return {
            "ticker": m.group(1),
            "gate": gate_text,
            "gate_bare": gate_bare,
            "card_type": "watchlist",
        }

    # Watchlist shorthand: TICKER — Watching/Scouting [...]
    m = re.match(r'(\w+) — (?:Watching|Scouting)(.*)?$', content)
    if m:
        return {
            "ticker": m.group(1),
            "gate": "ACTIVE",
            "gate_bare": "ACTIVE",
            "card_type": "watchlist",
        }

    # Fallback: "Action Card: TICKER ..." format
    m = re.match(r'Action Card:\s*(\w+)', content)
    if m:
        return {"ticker": m.group(1), "card_type": "unknown"}

    # Generic fallback — extract ticker from start
    m = re.match(r'(\w+)', content)
    ticker = m.group(1) if m else "UNKNOWN"
    return {
        "ticker": ticker,
        "card_type": "unknown",
    }


# ---------------------------------------------------------------------------
# Fill alert parsing
# ---------------------------------------------------------------------------

_BUY_ALERT_RE = re.compile(
    r'(B\d+)\s+\$([0-9.]+)\s+(TOUCHED|NEAR|HIT)\s*—\s*(.*)'
)
_SELL_ALERT_RE = re.compile(
    r'SELL\s+\$([0-9.]+)\s+(NEAR\s+FILL|TOUCHED|NEAR|HIT)?\s*—?\s*(.*)'
)


def parse_fill_alerts(card_text, ticker):
    """Extract fill alert entries from **Fill Alerts:** section.

    Returns list of {"ticker", "type", "order", "price", "status", "detail"} dicts.
    """
    alerts = []

    # Find the Fill Alerts line(s)
    in_fill_section = False
    fill_lines = []
    for line in card_text.split("\n"):
        if line.startswith("**Fill Alerts:**"):
            in_fill_section = True
            # The content may be on the same line after the label
            after = line.split("**Fill Alerts:**", 1)[1].strip()
            if after:
                fill_lines.append(after)
            continue
        if in_fill_section:
            stripped = line.strip()
            # Section ends at next ** section header or empty line after content
            if stripped.startswith("**") and stripped.endswith("**"):
                break
            if stripped.startswith("**") and ":" in stripped:
                break
            if stripped:
                fill_lines.append(stripped)
            else:
                # Empty line — stop
                break

    full_text = " ".join(fill_lines)

    # Check for "None" or no alerts
    if not full_text or full_text.startswith("None"):
        return alerts

    # Split on ⚠️ to handle multi-alert lines
    fragments = full_text.split("⚠️")
    fragments = [f.strip() for f in fragments if f.strip()]

    for frag in fragments:
        # Try BUY alert first
        m = _BUY_ALERT_RE.search(frag)
        if m:
            alerts.append({
                "ticker": ticker,
                "type": "BUY",
                "order": m.group(1),
                "price": float(m.group(2)),
                "status": m.group(3),
                "detail": m.group(4).strip().rstrip("."),
            })
            continue

        # Try SELL alert
        m = _SELL_ALERT_RE.search(frag)
        if m:
            status = m.group(2) or ""
            status = status.strip()
            detail = m.group(3).strip().rstrip(".")
            if not status and "within" in detail.lower():
                status = "NEAR"
            if not status:
                status = "NEAR"
            alerts.append({
                "ticker": ticker,
                "type": "SELL",
                "order": "SELL",
                "price": float(m.group(1)),
                "status": status,
                "detail": detail,
            })
            continue

        # Neither matched — skip with warning
        print(f"  Warning: unparsed fill alert fragment for {ticker}: {frag[:80]}")

    return alerts


# ---------------------------------------------------------------------------
# Pending order gate parsing
# ---------------------------------------------------------------------------

def _is_dash_row(cells):
    """Check if all cells are dashes or empty (placeholder row)."""
    return all(c.strip() in ("—", "-", "", "---", ":---") for c in cells[:6])


def parse_pending_order_gates(card_text, ticker):
    """Extract Combined gate status from Pending Orders table (BUY only).

    Returns list of {"ticker", "price", "gate"} dicts for Entry Gate Summary.
    """
    rows = _parse_order_table(card_text, buy_only=True, as_gate_dict=False)
    for row in rows:
        row["ticker"] = ticker
    return rows


def parse_all_order_gates(card_text):
    """Extract Combined gate for ALL orders (BUY + SELL) from Pending Orders table.

    Returns dict: {price_str: gate_str} where price_str is f"{price:.2f}".
    Uses string keys to avoid float comparison fragility.
    """
    return _parse_order_table(card_text, buy_only=False, as_gate_dict=True)


def _parse_order_table(card_text, buy_only=False, as_gate_dict=False):
    """Shared parser for Pending Orders table.

    Args:
        buy_only: If True, skip SELL rows.
        as_gate_dict: If True, return {price_str: gate_str} dict.
                      If False, return list of {"price", "gate"} dicts.

    Ticker is not set in either mode; caller adds it post-hoc.
    """
    results = {} if as_gate_dict else []
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
            if cells[0] in ("Type", ":---"):
                header_found = True
                continue
            if _is_dash_row(cells):
                continue
            if len(cells) < 7:
                continue

            order_type = cells[0].strip()
            if buy_only and order_type == "SELL":
                continue

            price_str = cells[1].strip().replace("$", "").replace(",", "")
            try:
                price = float(price_str)
            except ValueError:
                continue

            combined = cells[6].strip().replace("**", "")
            price_key = f"{price:.2f}"

            if as_gate_dict:
                results[price_key] = combined
            else:
                results.append({
                    "price": price,
                    "gate": combined,
                })

    return results


# ---------------------------------------------------------------------------
# Sector parsing
# ---------------------------------------------------------------------------

def parse_sector(card_text):
    """Extract sector name and ETF from **Sector Context:** line.

    Handles variants:
      - "Technology — XLK (+0.48%..."        → Technology, XLK
      - "Technology (XLK: +0.48%..."         → Technology, XLK
      - "Technology sector (XLK)"            → Technology, XLK
      - "Financial sector (XLF) +0.65%..."   → Financial, XLF
      - "Materials (XLB: +0.25%..."          → Materials, XLB
      - "Industrials/Aerospace (XLI: ..."    → Industrials, XLI
      - "Utilities/Nuclear (XLU: ..."        → Utilities, XLU
    """
    # Pattern 1: Sector — ETF (...)
    m = re.search(
        r'\*\*Sector Context:\*\*\s*(.+?)\s*—\s*([A-Z]{2,4})\s',
        card_text
    )
    if m:
        return {
            "sector_name": _normalize_sector_name(m.group(1)),
            "etf": m.group(2),
        }

    # Pattern 2: Sector (ETF... or Sector (ETF:...
    m = re.search(
        r'\*\*Sector Context:\*\*\s*([^(]+?)\s*\(([A-Z]{2,4})',
        card_text
    )
    if m:
        return {
            "sector_name": _normalize_sector_name(m.group(1)),
            "etf": m.group(2),
        }

    return None


def _normalize_sector_name(raw):
    """Normalize sector name: remove 'sector' suffix, sub-sector slash, etc."""
    name = raw.strip().rstrip("—").strip()
    # Remove " sector" suffix
    name = re.sub(r'\s+sector$', '', name, flags=re.IGNORECASE)
    # Remove sub-sector after slash: "Industrials/Aerospace" → "Industrials"
    if "/" in name:
        name = name.split("/")[0].strip()
    return name


# ---------------------------------------------------------------------------
# Earnings parsing
# ---------------------------------------------------------------------------

def parse_earnings_days(card_text):
    """Extract days to earnings AND date string from card.

    Returns tuple (int_days, date_str) or (None, None).
    """
    # Try exit criterion table first — most reliable
    # ISO date: "N days to event (2026-02-24)"
    m = re.search(
        r'Earnings Gate\s*\|\s*(?:GATED|CLEAR|PAUSE)\s*\|\s*(\d+)\s+days?\s+to\s+(?:event|earnings)\s*\((\d{4}-\d{2}-\d{2})\)',
        card_text
    )
    if m:
        return int(m.group(1)), _format_date(m.group(2))

    # Human date in exit table: "N days to event (Feb 25, 2026)"
    m = re.search(
        r'Earnings Gate\s*\|\s*(?:GATED|CLEAR|PAUSE)\s*\|\s*(\d+)\s+days?\s+to\s+(?:event|earnings)\s*\((\w+\s+\d{1,2})',
        card_text
    )
    if m:
        return int(m.group(1)), m.group(2)

    # ISO date in gate table
    m = re.search(
        r'(\d+)\s+days?\s+to\s+earnings\s*\((\d{4}-\d{2}-\d{2})\)',
        card_text
    )
    if m:
        return int(m.group(1)), _format_date(m.group(2))

    # "Earnings in N days (ISO date)"
    m = re.search(
        r'[Ee]arnings\s+in\s+(\d+)\s+days?\s*\((\d{4}-\d{2}-\d{2})\)',
        card_text
    )
    if m:
        return int(m.group(1)), _format_date(m.group(2))

    # "Earnings in N days (human date)"
    m = re.search(
        r'[Ee]arnings\s+in\s+(\d+)\s+days?\s*\((\w+\s+\d{1,2})',
        card_text
    )
    if m:
        return int(m.group(1)), m.group(2)

    # "Earnings in N days" — find date from "Earnings MON DD" or "Feb 25" nearby
    m = re.search(r'[Ee]arnings\s+in\s+(\d+)\s+days?', card_text)
    if m:
        days = int(m.group(1))
        date_str = _find_earnings_date(card_text)
        return days, date_str

    # "N days to event (ISO date)" generic
    m = re.search(
        r'(\d+)\s+days?\s+to\s+event\s*\((\d{4}-\d{2}-\d{2})\)',
        card_text
    )
    if m:
        return int(m.group(1)), _format_date(m.group(2))

    # "N days to earnings" without date
    m = re.search(r'(\d+)\s+days?\s+to\s+earnings', card_text)
    if m:
        days = int(m.group(1))
        date_str = _find_earnings_date(card_text)
        return days, date_str

    # Safety net: "Earnings Gate | CLEAR | N days to YYYY-MM-DD" (no parens, no event/earnings keyword)
    m = re.search(
        r'Earnings Gate\s*\|\s*CLEAR\s*\|\s*(\d+)\s+days?\s+to\s+(\d{4}-\d{2}-\d{2})',
        card_text
    )
    if m:
        return int(m.group(1)), _format_date(m.group(2))

    return None, None


def _find_earnings_date(card_text):
    """Try to find an earnings date string from card text.

    Looks for patterns like "Earnings Feb 25", "earnings 2026-02-25",
    "Earnings Gate ... (Feb 25, 2026)".
    """
    # ISO date in text (word boundary prevents matching "pre-earnings")
    m = re.search(r'\b[Ee]arnings\s+(\d{4}-\d{2}-\d{2})', card_text)
    if m:
        return _format_date(m.group(1))

    # "Earnings MON DD" pattern (e.g., "Earnings Feb 25")
    m = re.search(r'\b[Ee]arnings\s+((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2})', card_text)
    if m:
        return m.group(1)

    # "earnings (MON DD" in gate table
    m = re.search(r'earnings\s*\(((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2})', card_text)
    if m:
        return m.group(1)

    return "N/A"


def _format_date(iso_date):
    """Convert '2026-02-24' to 'Feb 24'."""
    try:
        parts = iso_date.split("-")
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        return f"{months[int(parts[1]) - 1]} {int(parts[2])}"
    except (IndexError, ValueError):
        return iso_date


# ---------------------------------------------------------------------------
# Condensed file parsing
# ---------------------------------------------------------------------------

def parse_condensed_positions(condensed_content):
    """Parse ## Active Positions table from condensed file content.

    Returns dict keyed by ticker: {"current_price": float, "pl_dollars": float, "pl_pct": str}.
    """
    positions = {}
    lines = condensed_content.split("\n")

    start = None
    for i, line in enumerate(lines):
        if line.strip() == "## Active Positions":
            start = i
            break

    if start is None:
        return positions

    for i in range(start + 1, len(lines)):
        line = lines[i].strip()
        if line.startswith("## ") or line == "---":
            break
        cells = parse_table_row(line)
        if len(cells) < 8:
            continue
        ticker = cells[0].strip()
        if not re.match(r'^[A-Z]{1,6}$', ticker):
            continue
        positions[ticker] = {
            "current_price": _parse_dollar(cells[3]),
            "pl_dollars": _parse_dollar(cells[6]),
            "pl_pct": cells[7].strip(),
        }

    return positions


def parse_vix_5d_pct(condensed_content):
    """Extract VIX 5D% from condensed file content.

    Returns string like "-8.31%" or "N/A".
    """
    lines = condensed_content.split("\n")

    in_vol = False
    for line in lines:
        if line.strip() == "### Volatility & Rates":
            in_vol = True
            continue
        if in_vol:
            cells = parse_table_row(line)
            if len(cells) >= 2 and cells[0] == "VIX":
                m = re.search(r'\(([+-]?[\d.]+)%\s*5D\)', cells[1])
                if m:
                    return m.group(1) + "%"
            if line.strip().startswith("###") or line.strip().startswith("---"):
                break

    return "N/A"


# ---------------------------------------------------------------------------
# Aggregate fill alerts
# ---------------------------------------------------------------------------

def aggregate_fill_alerts(cards, earnings_by_ticker, order_gates_by_ticker):
    """Parse fill alerts from all cards and enrich with earnings/gate data.

    Returns list of enriched alert dicts.
    """
    all_alerts = []

    for card in cards:
        ticker = card["ticker"]
        alerts = parse_fill_alerts(card["text"], ticker)
        for alert in alerts:
            # Enrich with earnings data
            days, date_str = earnings_by_ticker.get(ticker, (None, None))
            alert["earnings_days"] = days
            alert["earnings_date"] = date_str

            # Enrich with gate data for this specific order price
            # Use string key to avoid float comparison fragility
            gates = order_gates_by_ticker.get(ticker, {})
            price_key = f"{alert['price']:.2f}"
            alert["gate"] = gates.get(price_key, "N/A")

        all_alerts.extend(alerts)

    return all_alerts


# ---------------------------------------------------------------------------
# Aggregate gate counts (BUY orders only)
# ---------------------------------------------------------------------------

def aggregate_gate_counts(cards):
    """Count BUY order gate statuses across all cards.

    Returns (counts, per_ticker) where:
      counts: {"ACTIVE": N, "CAUTION": N, "REVIEW": N, "PAUSE": N, "GATED": N}
      per_ticker: {"ACTIVE": [tickers], "CAUTION": [...], ...}
    """
    counts = {"ACTIVE": 0, "CAUTION": 0, "REVIEW": 0, "PAUSE": 0, "GATED": 0}
    per_ticker = {"ACTIVE": [], "CAUTION": [], "REVIEW": [], "PAUSE": [], "GATED": []}

    for card in cards:
        ticker = card["ticker"]
        gates = parse_pending_order_gates(card["text"], ticker)
        if not gates:
            continue
        ticker_gates = {}
        for g in gates:
            gate_label = _normalize_gate(g["gate"])
            counts[gate_label] = counts.get(gate_label, 0) + 1
            ticker_gates[gate_label] = ticker_gates.get(gate_label, 0) + 1

        for gate_label, count in ticker_gates.items():
            if gate_label in per_ticker:
                per_ticker[gate_label].append(f"{ticker} x{count}" if count > 1 else ticker)

    return counts, per_ticker


def _normalize_gate(gate_str):
    """Normalize gate string to ACTIVE/CAUTION/REVIEW/PAUSE/GATED."""
    gate_str = gate_str.upper().strip()
    if "PAUSE" in gate_str:
        return "PAUSE"
    if "REVIEW" in gate_str:
        return "REVIEW"
    if "CAUTION" in gate_str:
        return "CAUTION"
    if "GATED" in gate_str:
        return "GATED"
    return "ACTIVE"


# ---------------------------------------------------------------------------
# Sector data computation
# ---------------------------------------------------------------------------

def compute_sector_data(active_cards, portfolio):
    """Compute sector deployment data from active positions.

    Returns dict with:
      sectors: {sector_name: {"etf", "tickers": [], "deployed": float}}
      total_deployed: float
    """
    positions = portfolio.get("positions", {})
    sectors = {}

    for card in active_cards:
        ticker = card["ticker"]
        sector_info = parse_sector(card["text"])
        if not sector_info:
            continue
        sector_name = sector_info["sector_name"]
        etf = sector_info["etf"]

        pos = positions.get(ticker, {})
        shares = pos.get("shares", 0)
        if isinstance(shares, str):
            shares = int(shares) if shares.isdigit() else 0
        avg_cost = pos.get("avg_cost", 0)
        if isinstance(avg_cost, str):
            try:
                avg_cost = float(avg_cost)
            except ValueError:
                avg_cost = 0.0
        deployed = shares * avg_cost

        if sector_name not in sectors:
            sectors[sector_name] = {"etf": etf, "tickers": [], "deployed": 0.0}
        sectors[sector_name]["tickers"].append(ticker)
        sectors[sector_name]["deployed"] += deployed

    total = sum(s["deployed"] for s in sectors.values())
    return {"sectors": sectors, "total_deployed": total}


# ---------------------------------------------------------------------------
# Sort keys
# ---------------------------------------------------------------------------

_VERDICT_PRIORITY = {"EXIT": 0, "REDUCE": 1, "HOLD": 2, "MONITOR": 3}
_GATE_PRIORITY = {"PAUSE": 0, "REVIEW": 1, "ACTIVE": 2}
_ALERT_STATUS_ORDER = {"TOUCHED": 0, "HIT": 0, "NEAR": 1, "NEAR FILL": 1}


def verdict_sort_key(card):
    """Sort active cards: EXIT > REDUCE > HOLD > MONITOR, then alphabetical."""
    verdict = card.get("verdict", "MONITOR")
    return (_VERDICT_PRIORITY.get(verdict, 99), card["ticker"])


def gate_sort_key(card):
    """Sort watchlist cards: PAUSE > REVIEW > ACTIVE, then alphabetical."""
    gate = card.get("gate_bare", "ACTIVE")
    return (_GATE_PRIORITY.get(gate, 99), card["ticker"])


# ---------------------------------------------------------------------------
# Assembly: Executive Summary
# ---------------------------------------------------------------------------

def build_executive_summary(manifest, active_cards,
                            sector_data, fill_alerts, condensed_positions,
                            earnings_by_ticker):
    """Build the Executive Summary section."""
    regime = manifest.get("regime", "Unknown")
    vix = manifest.get("regime_detail", {}).get("vix", "N/A")
    indices = manifest.get("regime_detail", {}).get("indices_above_sma", 0)
    breadth = manifest.get("regime_detail", {}).get("sector_breadth", 0)
    deployed = manifest.get("capital", {}).get("deployed", 0)

    # Count verdicts
    verdict_counts = {}
    for card in active_cards:
        v = card.get("verdict", "MONITOR")
        verdict_counts[v] = verdict_counts.get(v, 0) + 1

    # Compute total unrealized P/L and list top losers
    total_pl = 0.0
    ticker_pls = []
    active_tickers = {c["ticker"] for c in active_cards}
    for ticker, pos_data in condensed_positions.items():
        if ticker not in active_tickers:
            continue
        pl = pos_data["pl_dollars"]
        total_pl += pl
        ticker_pls.append((ticker, pl))

    # Sort by absolute loss (most negative first)
    ticker_pls.sort(key=lambda x: x[1])
    top_losers = [(t, p) for t, p in ticker_pls[:3] if p < 0]

    loser_text = ""
    if top_losers:
        loser_parts = [f"{t} (-${abs(p):.0f})" for t, p in top_losers]
        loser_text = f", driven primarily by {', '.join(loser_parts)}"

    # Earnings cluster (tickers within 7 days)
    earnings_cluster = []
    for card in active_cards:
        days, date_str = earnings_by_ticker.get(card["ticker"], (None, None))
        if days is not None and days <= 7:
            earnings_cluster.append((card["ticker"], days, date_str))

    # Positive-only P/L count
    positive_count = sum(1 for _, p in ticker_pls if p > 0)

    # Build summary paragraph
    lines = ["## Executive Summary\n"]

    regime_tone = "broad macro tailwind" if regime == "Risk-On" else "macro headwinds"
    summary = (
        f"Regime is **{regime}** (VIX {vix}, {indices}/3 indices above 50-SMA, "
        f"{breadth}/11 sectors positive) with {regime_tone}. "
        f"Portfolio has {len(active_cards)} active positions "
        f"(${deployed:,.2f} deployed)"
    )

    if positive_count == 0:
        summary += " all with negative P/L"
    elif positive_count == len(ticker_pls):
        summary += " all with positive P/L"
    else:
        pos_tickers = [t for t, p in ticker_pls if p > 0]
        summary += f" with {positive_count} positive ({', '.join(pos_tickers)})"

    summary += (
        f"; total unrealized P/L ${total_pl:+,.0f}"
        f"{loser_text}."
    )

    # Earnings cluster
    if earnings_cluster:
        cluster_parts = []
        for t, d, ds in sorted(earnings_cluster, key=lambda x: x[1]):
            day_word = "day" if d == 1 else "days"
            cluster_parts.append(f"{t} in {d} {day_word} ({ds})")
        summary += (
            f" **Earnings cluster is the key near-term risk**: "
            f"{', '.join(cluster_parts)}."
        )

    # Most urgent action from fill alerts
    if any(v in verdict_counts for v in ["EXIT", "REDUCE"]):
        exit_tickers = [c["ticker"] for c in active_cards
                        if c.get("verdict") in ("EXIT", "REDUCE")]
        summary += f" **Most urgent**: {', '.join(exit_tickers)} requires action."
    elif fill_alerts:
        touched = [a for a in fill_alerts if a["status"] == "TOUCHED"]
        if touched:
            t = touched[0]
            summary += (
                f" **Most urgent action**: {t['ticker']} {t['order']} "
                f"(${t['price']:.2f}) {t['status']}."
            )

    # Sector concentration
    if sector_data["total_deployed"] > 0:
        for sname, sdata in sector_data["sectors"].items():
            pct = sdata["deployed"] / sector_data["total_deployed"] * 100
            if pct > 40:
                n = len(sdata["tickers"])
                summary += (
                    f" {sname} sector concentration is elevated at "
                    f"{n}/{len(active_cards)} active positions "
                    f"({pct:.0f}% of deployed capital)."
                )
                break

    lines.append(summary)
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Assembly: Immediate Actions
# ---------------------------------------------------------------------------

def build_immediate_actions(active_cards, fill_alerts, earnings_by_ticker,
                            order_gates_by_ticker):
    """Build the Immediate Actions table."""
    lines = [
        "## Immediate Actions\n",
        "| # | Ticker | Action | Urgency | Detail |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]

    actions = []

    # 1. EXIT/REDUCE verdicts
    for card in active_cards:
        verdict = card.get("verdict", "")
        if verdict in ("EXIT", "REDUCE"):
            actions.append({
                "ticker": card["ticker"],
                "action": f"{verdict} position",
                "urgency": "HIGH",
                "urgency_order": 0,
                "detail": f"{verdict} — see card for details",
            })

    # 2. Fill alerts
    alert_tickers_used = set()
    status_order = {"TOUCHED": 1, "HIT": 1, "NEAR": 2, "NEAR FILL": 2}
    for alert in fill_alerts:
        urgency = "HIGH" if alert["status"] in ("TOUCHED", "HIT") else "MEDIUM"

        # Determine action based on gate
        gate = alert.get("gate", "N/A")
        gate_upper = gate.upper()
        if "PAUSE" in gate_upper:
            if alert["type"] == "BUY":
                action_text = "CANCEL / HOLD fill"
            else:
                action_text = "Monitor — PAUSED"
        elif "GATED" in gate_upper:
            if alert["type"] == "SELL":
                date = alert.get("earnings_date", "N/A")
                action_text = f"Monitor SELL trigger — GATED until earnings {date}"
            else:
                action_text = "HOLD — GATED"
        elif "REVIEW" in gate_upper:
            action_text = f"Review {alert['order']} fill"
        else:
            if alert["type"] == "BUY":
                action_text = f"Watch {alert['order']} fill"
            else:
                action_text = "Watch SELL fill"

        # Build detail
        detail_parts = [
            f"{alert['order']} ${alert['price']:.2f} {alert['status']}"
        ]
        if "PAUSE" in gate_upper and alert["type"] == "BUY":
            days = alert.get("earnings_days")
            detail_parts.append(
                f"PAUSED (earnings {alert.get('earnings_date', 'N/A')}"
                f"{f', {days}d' if days else ''}). Do NOT act on fill"
            )
        elif "GATED" in gate_upper and alert["type"] == "SELL":
            days = alert.get("earnings_days")
            detail_parts.append(
                f"GATED — earnings {alert.get('earnings_date', 'N/A')}"
                f"{f' ({days}d)' if days else ''}"
            )
        else:
            if alert["detail"]:
                detail_parts.append(alert["detail"])
            gate_label = _normalize_gate(gate)
            if gate_label != "ACTIVE":
                detail_parts.append(f"Gate: {gate_label}")
            else:
                detail_parts.append("All gates ACTIVE")

        actions.append({
            "ticker": alert["ticker"],
            "action": action_text,
            "urgency": urgency,
            "urgency_order": status_order.get(alert["status"], 3),
            "detail": ". ".join(detail_parts) + ".",
        })
        alert_tickers_used.add(alert["ticker"])

    # 3. GATED hold-throughs (active positions with earnings <= 7 days, no fill alerts)
    for card in active_cards:
        ticker = card["ticker"]
        if ticker in alert_tickers_used:
            continue
        if card.get("verdict") in ("EXIT", "REDUCE"):
            continue
        days, date_str = earnings_by_ticker.get(ticker, (None, None))
        if days is not None and days <= 7:
            # Check if there are pending orders that are PAUSED
            pause_note = ""
            order_gates = order_gates_by_ticker.get(ticker, {})
            paused = [p for p, g in order_gates.items() if "PAUSE" in g.upper()]
            if paused:
                pause_note = f" Pending orders PAUSED."

            day_word = "day" if days == 1 else "days"
            actions.append({
                "ticker": ticker,
                "action": "Hold through earnings",
                "urgency": "MEDIUM",
                "urgency_order": 4,
                "detail": (
                    f"GATED — earnings {date_str or 'N/A'} ({days} {day_word})."
                    f"{pause_note} No action."
                ),
            })

    # Sort by urgency then alphabetical
    urgency_map = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    actions.sort(key=lambda a: (urgency_map.get(a["urgency"], 9), a["urgency_order"], a["ticker"]))

    for i, action in enumerate(actions, 1):
        urg = f"**{action['urgency']}**" if action["urgency"] == "HIGH" else action["urgency"]
        lines.append(
            f"| {i} | {action['ticker']} | {action['action']} | {urg} | {action['detail']} |"
        )

    if len(actions) == 0:
        lines.append("| — | — | No immediate actions required | — | — |")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Assembly: Market Regime
# ---------------------------------------------------------------------------

def build_market_regime(manifest, gate_counts, gate_per_ticker, vix_5d_pct):
    """Build the Market Regime section."""
    regime = manifest.get("regime", "Unknown")
    detail = manifest.get("regime_detail", {})
    vix = detail.get("vix", "N/A")
    indices = detail.get("indices_above_sma", 0)
    breadth = detail.get("sector_breadth", 0)
    reasoning = detail.get("reasoning", "")

    # VIX direction label
    if vix_5d_pct and vix_5d_pct != "N/A":
        try:
            pct_val = float(vix_5d_pct.replace("%", ""))
            direction = "declining, favorable" if pct_val < 0 else "rising, cautious"
        except ValueError:
            direction = ""
        vix_display = f"{vix} (5D% {vix_5d_pct} — {direction})"
    else:
        vix_display = str(vix)

    # Entry Gate Summary with per-ticker breakdown
    gate_parts = []
    for label in ["ACTIVE", "CAUTION", "REVIEW", "PAUSE", "GATED"]:
        count = gate_counts.get(label, 0)
        if count > 0:
            tickers = gate_per_ticker.get(label, [])
            if tickers and label != "ACTIVE":
                ticker_list = ", ".join(tickers)
                gate_parts.append(f"{count} {label} ({ticker_list})")
            else:
                gate_parts.append(f"{count} {label}")
    gate_summary = ", ".join(gate_parts) if gate_parts else "No BUY orders"

    lines = [
        "## Market Regime\n",
        "| Metric | Value |",
        "| :--- | :--- |",
        f"| Regime | **{regime}** |",
        f"| VIX | {vix_display} |",
        f"| Indices Above 50-SMA | {indices}/3 |",
        f"| Sector Breadth | {breadth}/11 positive |",
        f"| Entry Gate Summary | {gate_summary} |",
        f"| Reasoning | {reasoning} |",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Assembly: Cross-Ticker Intelligence
# ---------------------------------------------------------------------------

def build_cross_ticker_intelligence(active_cards, watchlist_cards,
                                    sector_data, earnings_by_ticker):
    """Build the Cross-Ticker Intelligence section."""
    lines = ["## Cross-Ticker Intelligence\n"]

    # Sector concentration
    if sector_data["total_deployed"] > 0:
        lines.append("**Sector Concentration:**")
        for sname, sdata in sorted(
            sector_data["sectors"].items(),
            key=lambda x: -x[1]["deployed"]
        ):
            pct = sdata["deployed"] / sector_data["total_deployed"] * 100
            tickers_str = ", ".join(sdata["tickers"])
            flag = " ⚠️ >40%" if pct > 40 else ""
            lines.append(
                f"- {sname} ({sdata['etf']}): "
                f"${sdata['deployed']:,.0f} ({pct:.0f}%) — {tickers_str}{flag}"
            )
        lines.append("")

    # Earnings cluster
    cluster = []
    for card in active_cards + watchlist_cards:
        ticker = card["ticker"]
        days, date_str = earnings_by_ticker.get(ticker, (None, None))
        if days is not None and days <= 7:
            cluster.append((ticker, days, date_str))

    if cluster:
        cluster.sort(key=lambda x: x[1])
        lines.append("**Earnings Cluster (within 7 days):**")
        for t, d, ds in cluster:
            day_word = "day" if d == 1 else "days"
            lines.append(f"- {t}: {d} {day_word} ({ds})")
        lines.append("")

    # Capital rotation
    exit_reduce = [c for c in active_cards if c.get("verdict") in ("EXIT", "REDUCE")]
    if exit_reduce:
        active_watchlist = [c for c in watchlist_cards
                           if c.get("gate_bare") == "ACTIVE"]
        lines.append("**Capital Rotation:**")
        for c in exit_reduce:
            lines.append(
                f"- {c['ticker']}: {c.get('verdict', '')} verdict — capital freed on exit"
            )
        if active_watchlist:
            wl_tickers = [c["ticker"] for c in active_watchlist]
            lines.append(
                f"- Redeployment candidates (ACTIVE gates): {', '.join(wl_tickers)}"
            )
        lines.append("")
    else:
        lines.append("**Capital Rotation:** No EXIT/REDUCE verdicts — no rotation needed.\n")

    # Materials consistency check
    materials_tickers = []
    if "Materials" in sector_data.get("sectors", {}):
        materials_tickers = sector_data["sectors"]["Materials"]["tickers"]
    if len(materials_tickers) > 1:
        verdicts = {}
        for card in active_cards:
            if card["ticker"] in materials_tickers:
                verdicts[card["ticker"]] = card.get("verdict", "MONITOR")
        if len(set(verdicts.values())) > 1:
            lines.append("**Materials Consistency Warning:**")
            for t, v in verdicts.items():
                lines.append(f"- {t}: {v}")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Assembly: Fill Alerts Table
# ---------------------------------------------------------------------------

def build_fill_alerts_table(all_fill_alerts):
    """Build the aggregate Fill Alerts table."""
    lines = [
        "## Fill Alerts\n",
    ]

    if not all_fill_alerts:
        lines.append("No fill alerts.\n")
        return "\n".join(lines)

    # Sort by urgency: TOUCHED/HIT first, then NEAR/NEAR FILL, then alphabetical
    sorted_alerts = sorted(
        all_fill_alerts,
        key=lambda a: (_ALERT_STATUS_ORDER.get(a["status"], 9), a["ticker"])
    )

    lines.extend([
        "| Ticker | Order | Price | Status | Gate | Action |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    for alert in sorted_alerts:
        gate = alert.get("gate", "N/A")
        gate_norm = _normalize_gate(gate)

        # Determine action based on order type and gate
        if alert["type"] == "BUY":
            if gate_norm == "PAUSE":
                days = alert.get("earnings_days")
                date_str = alert.get("earnings_date", "N/A")
                action = (
                    f"Cancel/hold — PAUSED (earnings {date_str}, {days}d). Do NOT fill."
                )
            elif gate_norm == "REVIEW":
                action = "Review — approaching earnings window."
            else:
                action = "ACTIVE — fill likely on next down session."
        else:
            # SELL orders
            if "GATED" in gate.upper():
                date_str = alert.get("earnings_date", "N/A")
                action = f"Monitor — GATED until earnings {date_str}. May fill pre-earnings."
            elif gate_norm == "PAUSE":
                action = "Monitor — PAUSED."
            else:
                action = "ACTIVE — watch for fill."

        lines.append(
            f"| {alert['ticker']} | {alert['order']} | "
            f"${alert['price']:.2f} | {alert['status']} | "
            f"{gate_norm} | {action} |"
        )

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Assembly: Scouting section
# ---------------------------------------------------------------------------

def build_scouting(scouting_tickers):
    """Build the Scouting section."""
    if not scouting_tickers:
        return ""
    tickers_str = ", ".join(scouting_tickers)
    return (
        f"## Scouting (No Orders)\n\n"
        f"**{tickers_str}** — no orders set. "
        f"Use news-sweep or deep-dive for detailed analysis before activating.\n"
    )


# ---------------------------------------------------------------------------
# Assembly: Capital Summary
# ---------------------------------------------------------------------------

def build_capital_summary(manifest, sector_data):
    """Build the Capital Summary section."""
    capital = manifest.get("capital", {})
    deployed = capital.get("deployed", 0)
    velocity = capital.get("velocity_pool", 0)
    bounce = capital.get("bounce_pool", 0)
    total = deployed + velocity + bounce

    lines = [
        "## Capital Summary\n",
        "| Category | Amount |",
        "| :--- | :--- |",
        f"| Deployed | ${deployed:,.2f} |",
        f"| Velocity Pool | ${velocity:,.2f} |",
        f"| Bounce Pool | ${bounce:,.2f} |",
        f"| Total | ${total:,.2f} |",
        "",
    ]

    # Sector deployment table
    if sector_data["sectors"] and sector_data["total_deployed"] > 0:
        lines.extend([
            "**Sector Deployment:**",
            "| Sector | Deployed | % | Tickers |",
            "| :--- | :--- | :--- | :--- |",
        ])
        for sname, sdata in sorted(
            sector_data["sectors"].items(),
            key=lambda x: -x[1]["deployed"]
        ):
            pct = sdata["deployed"] / sector_data["total_deployed"] * 100
            tickers_str = ", ".join(sdata["tickers"])
            warn = " ⚠️" if pct > 40 else ""
            lines.append(
                f"| {sname} ({sdata['etf']}) | "
                f"${sdata['deployed']:,.0f} | {pct:.0f}%{warn} | {tickers_str} |"
            )
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Validate inputs
    if not MANIFEST.exists():
        print(f"*Error: {MANIFEST} not found. Run the splitter phase first.*")
        sys.exit(1)
    if not PORTFOLIO.exists():
        print(f"*Error: {PORTFOLIO} not found.*")
        sys.exit(1)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    portfolio = json.loads(PORTFOLIO.read_text(encoding="utf-8"))

    # Parse condensed file for current prices, P/L $, and VIX 5D%
    if CONDENSED.exists():
        condensed_content = CONDENSED.read_text(encoding="utf-8")
        condensed_positions = parse_condensed_positions(condensed_content)
        vix_5d_pct = parse_vix_5d_pct(condensed_content)
    else:
        condensed_positions = {}
        vix_5d_pct = "N/A"

    # Read all card files
    active_cards = []
    watchlist_cards = []
    scouting_tickers = []
    failed_tickers = []

    for t in manifest.get("tickers", []):
        ticker = t["ticker"]
        ticker_type = t["type"]

        # Scouting tickers have no card files
        if ticker_type == "scouting":
            scouting_tickers.append(ticker)
            continue

        card_path = MORNING_WORK / f"{ticker}-card.md"
        if not card_path.exists():
            failed_tickers.append(ticker)
            print(f"  Warning: missing card for {ticker}")
            continue

        card_text = card_path.read_text(encoding="utf-8")
        first_line = card_text.split("\n")[0]
        header = parse_card_header(first_line)

        card_entry = {
            **header,
            "text": card_text,
        }

        if ticker_type == "active":
            active_cards.append(card_entry)
        elif ticker_type == "watchlist":
            watchlist_cards.append(card_entry)

    # Sort
    active_cards.sort(key=verdict_sort_key)
    watchlist_cards.sort(key=gate_sort_key)

    print(f"Active cards: {len(active_cards)} ({', '.join(c['ticker'] for c in active_cards)})")
    print(f"Watchlist cards: {len(watchlist_cards)} ({', '.join(c['ticker'] for c in watchlist_cards)})")
    print(f"Scouting: {len(scouting_tickers)} ({', '.join(scouting_tickers)})")
    if failed_tickers:
        print(f"Failed: {len(failed_tickers)} ({', '.join(failed_tickers)})")

    # Parse per-card metadata
    earnings_by_ticker = {}
    order_gates_by_ticker = {}
    for card in active_cards + watchlist_cards:
        t = card["ticker"]
        earnings_by_ticker[t] = parse_earnings_days(card["text"])
        order_gates_by_ticker[t] = parse_all_order_gates(card["text"])

    # Parse cross-card data
    all_fill_alerts = aggregate_fill_alerts(
        active_cards + watchlist_cards, earnings_by_ticker, order_gates_by_ticker
    )
    gate_counts, gate_per_ticker = aggregate_gate_counts(active_cards + watchlist_cards)
    sector_data = compute_sector_data(active_cards, portfolio)

    print(f"\nFill alerts: {len(all_fill_alerts)}")
    print(f"Gate counts: {gate_counts}")
    print(f"Sectors: {list(sector_data['sectors'].keys())}")

    # Build document sections
    date = manifest.get("date", "unknown")
    sections = [
        f"# Morning Briefing — {date}\n",
        build_executive_summary(
            manifest, active_cards,
            sector_data, all_fill_alerts, condensed_positions,
            earnings_by_ticker
        ),
        "---\n",
        build_immediate_actions(active_cards, all_fill_alerts, earnings_by_ticker,
                               order_gates_by_ticker),
        "---\n",
        build_market_regime(manifest, gate_counts, gate_per_ticker, vix_5d_pct),
        "---\n",
        "## Active Positions\n",
    ]

    # Active cards pasted verbatim
    for card in active_cards:
        sections.append(card["text"].rstrip())
        sections.append("\n---\n")

    # Cross-ticker intelligence
    sections.append(
        build_cross_ticker_intelligence(
            active_cards, watchlist_cards,
            sector_data, earnings_by_ticker
        )
    )
    sections.append("---\n")

    # Watchlist
    sections.append("## Watchlist\n")
    for card in watchlist_cards:
        sections.append(card["text"].rstrip())
        sections.append("\n---\n")

    # Scouting
    scouting_section = build_scouting(scouting_tickers)
    if scouting_section:
        sections.append(scouting_section)
        sections.append("---\n")

    # Velocity & Bounce
    sections.append("## Velocity & Bounce Positions\n\nNo active velocity/bounce positions.\n")
    sections.append("---\n")

    # Fill Alerts
    sections.append(
        build_fill_alerts_table(all_fill_alerts)
    )
    sections.append("---\n")

    # Capital Summary
    sections.append(
        build_capital_summary(manifest, sector_data)
    )

    # Handle failed tickers — insert error cards
    if failed_tickers:
        error_section = "\n## Failed Tickers\n\n"
        for ticker in failed_tickers:
            error_section += (
                f"### {ticker} — ERROR\n"
                f"Analysis failed. Re-run workflow or check manually.\n\n---\n\n"
            )
        sections.append(error_section)

    # Write output
    output = "\n".join(sections)
    OUTPUT.write_text(output, encoding="utf-8")
    file_size = OUTPUT.stat().st_size
    line_count = output.count("\n") + 1

    # Summary for agent to capture
    print(f"\n--- Assembly Complete ---")
    print(f"Wrote {OUTPUT} ({file_size / 1024:.1f} KB, {line_count} lines)")
    print(f"Active: {len(active_cards)}")

    verdict_counts = {}
    for c in active_cards:
        v = c.get("verdict", "MONITOR")
        verdict_counts[v] = verdict_counts.get(v, 0) + 1
    v_parts = [f"{n} {v}" for v, n in sorted(verdict_counts.items(),
               key=lambda x: _VERDICT_PRIORITY.get(x[0], 99))]
    print(f"Verdicts: {', '.join(v_parts)}")
    print(f"Watchlist: {len(watchlist_cards)}")
    print(f"Scouting: {len(scouting_tickers)}")
    print(f"Fill alerts: {len(all_fill_alerts)}")
    if failed_tickers:
        print(f"Failed: {', '.join(failed_tickers)}")
    else:
        print(f"Failed: none")


if __name__ == "__main__":
    main()
