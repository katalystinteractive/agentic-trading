#!/usr/bin/env python3
"""Market Context Pre-Analyst — Phase 2 mechanical regime + gate engine.

Parses market-context-raw.md, classifies regime from raw indices + VIX,
applies the Market Context Entry Gate to all pending BUY orders, builds
Sector Alignment, and writes market-context-pre-analyst.md for the LLM
analyst to add qualitative narratives.

Usage: python3 tools/market_context_pre_analyst.py
"""

import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = PROJECT_ROOT / "market-context-raw.md"
PORTFOLIO_PATH = PROJECT_ROOT / "portfolio.json"
OUTPUT_PATH = PROJECT_ROOT / "market-context-pre-analyst.md"

# Same-directory imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
from news_sweep_collector import split_table_row
from sector_registry import SECTOR_ETF
from market_context_gatherer import SECTOR_MAP


# ---------------------------------------------------------------------------
# Thresholds (must match strategy.md and market_pulse.py)
# ---------------------------------------------------------------------------

VIX_RISK_ON_THRESHOLD = 20.0    # strict <  (VIX exactly 20.0 = Neutral)
VIX_RISK_OFF_THRESHOLD = 25.0   # strict >  (VIX exactly 25.0 = Neutral)
VIX_CAUTION_LOW = 20.0          # CAUTION applies when VIX >= 20.0
VIX_CAUTION_HIGH = 25.0         # ... and VIX <= 25.0
DEEP_SUPPORT_PCT = 15.0


# ---------------------------------------------------------------------------
# Section 1: Input Validation & Parsing
# ---------------------------------------------------------------------------

def validate_inputs():
    """Check inputs exist and load them. Returns (raw_text, portfolio) or exits."""
    if not RAW_PATH.exists():
        print(f"*Error: {RAW_PATH.name} not found — run market_context_gatherer.py first*",
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
    """Parse date from '# Market Context Raw Data — YYYY-MM-DD'."""
    m = re.search(r"# Market Context Raw Data — (\d{4}-\d{2}-\d{2})", raw_text)
    if m:
        return date.fromisoformat(m.group(1))
    print("Warning: Could not parse date from raw header, falling back to today()",
          file=sys.stderr)
    return date.today()


def _find_section(raw_text, header_prefix):
    """Find a section by header prefix, return its lines until the next ## header."""
    lines = raw_text.split("\n")
    in_section = False
    section_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("###") and header_prefix in stripped:
            in_section = True
            continue
        if in_section and stripped.startswith("###"):
            break
        if in_section:
            section_lines.append(line)
    return section_lines


def parse_indices(raw_text):
    """Parse Major Indices table from raw.

    Returns list of {name, etf, price, day_pct, five_d_pct, vs_50sma}.
    """
    section = _find_section(raw_text, "Major Indices")
    indices = []

    for line in section:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cols = split_table_row(stripped)
        if not cols or cols[0] in ("Index", ""):
            continue
        if any(c.startswith(":---") or c.startswith("---") for c in cols):
            continue
        if len(cols) < 6:
            continue

        name = cols[0]
        etf = cols[1]

        # Parse price
        price_str = cols[2].replace("$", "").replace(",", "").strip()
        try:
            price = float(price_str)
        except ValueError:
            price = None

        # Parse Day%
        day_pct = _parse_pct(cols[3])
        # Parse 5D%
        five_d_pct = _parse_pct(cols[4])
        # vs 50-SMA
        vs_50sma = cols[5].strip() if cols[5].strip() != "N/A" else None

        indices.append({
            "name": name,
            "etf": etf,
            "price": price,
            "day_pct": day_pct,
            "five_d_pct": five_d_pct,
            "vs_50sma": vs_50sma,
        })

    return indices


def _parse_pct(s):
    """Parse a percentage string like '+0.72%' or 'N/A'. Returns float or None."""
    s = s.strip().replace("%", "").replace("+", "")
    if s == "N/A" or s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_vix(raw_text):
    """Parse VIX from Volatility & Rates section.

    VIX output has two formats:
    - With 5D%: | VIX | 19.09 (-8.31% 5D) | Normal — Stable |
    - Without 5D%: | VIX | 19.09 | Normal — Stable |

    Returns {value: float, five_d_pct: float|None, interpretation: str}.
    """
    section = _find_section(raw_text, "Volatility & Rates")

    for line in section:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cols = split_table_row(stripped)
        if not cols or len(cols) < 3:
            continue
        if cols[0].strip() != "VIX":
            continue

        value_col = cols[1].strip()
        interpretation = cols[2].strip()

        # Parse VIX value — first number in the Value column
        val_match = re.match(r'^([\d.]+)', value_col)
        vix_value = float(val_match.group(1)) if val_match else None

        # Parse 5D% — may or may not be present
        five_d_match = re.search(r'\(([-+]?\d+\.?\d*)%\s*5D\)', value_col)
        five_d_pct = float(five_d_match.group(1)) if five_d_match else None

        return {
            "value": vix_value,
            "five_d_pct": five_d_pct,
            "interpretation": interpretation,
        }

    return {"value": None, "five_d_pct": None, "interpretation": "N/A"}


def parse_sectors(raw_text):
    """Parse Sector Performance table from raw.

    Returns list of {name, etf, day_pct, five_d_pct, twenty_d_pct}.
    """
    section_lines = _find_section(raw_text, "Sector Performance")

    sectors = []
    for line in section_lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cols = split_table_row(stripped)
        if not cols or cols[0] == "Sector":
            continue
        if any(c.startswith(":---") or c.startswith("---") for c in cols):
            continue
        if len(cols) < 5:
            continue

        sectors.append({
            "name": cols[0].strip(),
            "etf": cols[1].strip(),
            "day_pct": _parse_pct(cols[2]),
            "five_d_pct": _parse_pct(cols[3]),
            "twenty_d_pct": _parse_pct(cols[4]),
        })

    return sectors


def parse_tool_regime(raw_text):
    """Parse Market Regime as reported by market_pulse.py.

    Returns {regime: str, reasoning: str}.
    """
    section = _find_section(raw_text, "Market Regime")
    regime = None
    reasoning = None

    for line in section:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cols = split_table_row(stripped)
        if not cols or len(cols) < 2:
            continue
        if any(c.startswith(":---") or c.startswith("---") for c in cols):
            continue
        metric = cols[0].strip()
        value = cols[1].strip()

        if metric == "Regime":
            # Strip bold markers
            regime = value.replace("**", "").strip()
        elif metric == "Reasoning":
            reasoning = value

    return {"regime": regime or "Unknown", "reasoning": reasoning or ""}


def parse_pending_buy_orders(raw_text):
    """Parse Pending BUY Orders Detail table from raw.

    Returns list of dicts matching the 8-column format.
    """
    lines = raw_text.split("\n")
    in_section = False
    orders = []

    for line in lines:
        stripped = line.strip()
        if "## Pending BUY Orders Detail" in stripped:
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if in_section and stripped.startswith("---"):
            break
        if not in_section or not stripped.startswith("|"):
            continue

        cols = split_table_row(stripped)
        if not cols or cols[0] in ("Ticker", ""):
            continue
        if any(c.startswith(":---") or c.startswith("---") for c in cols):
            continue
        if len(cols) < 8:
            continue

        # Parse price
        price_str = cols[2].replace("$", "").replace(",", "").strip()
        try:
            order_price = float(price_str)
        except ValueError:
            order_price = None

        # Parse shares
        try:
            shares = int(cols[3].strip())
        except ValueError:
            shares = 0

        # Parse current price
        current_str = cols[4].replace("$", "").replace(",", "").strip()
        try:
            current_price = float(current_str)
        except ValueError:
            current_price = None

        # Parse % Below Current
        pct_str = cols[5].replace("%", "").strip()
        try:
            pct_below = float(pct_str)
        except ValueError:
            pct_below = None

        orders.append({
            "ticker": cols[0].strip(),
            "sector": cols[1].strip(),
            "order_price": order_price,
            "shares": shares,
            "current_price": current_price,
            "pct_below": pct_below,
            "active_position": cols[6].strip(),
            "note": cols[7].strip(),
        })

    return orders


def parse_active_positions(raw_text):
    """Parse Active Positions Summary table from raw.

    Returns list of dicts.
    """
    lines = raw_text.split("\n")
    in_section = False
    positions = []

    for line in lines:
        stripped = line.strip()
        if "## Active Positions Summary" in stripped:
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if in_section and stripped.startswith("---"):
            break
        if not in_section or not stripped.startswith("|"):
            continue

        cols = split_table_row(stripped)
        if not cols or cols[0] in ("Ticker", ""):
            continue
        if any(c.startswith(":---") or c.startswith("---") for c in cols):
            continue
        if len(cols) < 8:
            continue

        positions.append({
            "ticker": cols[0].strip(),
            "sector": cols[1].strip(),
            "shares": cols[2].strip(),
            "avg_cost": cols[3].strip(),
            "current_price": cols[4].strip(),
            "deployed": cols[5].strip(),
            "pending_buys": cols[6].strip(),
            "pending_sells": cols[7].strip(),
        })

    return positions


# ---------------------------------------------------------------------------
# Section 2: Regime Classification
# ---------------------------------------------------------------------------

def classify_regime(indices, vix):
    """Recompute regime from raw index + VIX data.

    Returns {regime, indices_above, indices_total, vix_value, reasoning}.
    """
    # Count indices above 50-SMA, excluding N/A
    valid_indices = [i for i in indices if i["vs_50sma"] is not None]
    indices_total = len(valid_indices)
    indices_above = sum(1 for i in valid_indices if i["vs_50sma"] == "Above 50-SMA")

    vix_value = vix.get("value")

    # Insufficient data fallback
    if indices_total == 0:
        return {
            "regime": "Neutral",
            "indices_above": 0,
            "indices_total": 0,
            "vix_value": vix_value,
            "reasoning": "Insufficient index data — defaulting to Neutral",
        }

    if vix_value is None:
        return {
            "regime": "Neutral",
            "indices_above": indices_above,
            "indices_total": indices_total,
            "vix_value": None,
            "reasoning": (f"{indices_above}/{indices_total} indices above 50-SMA, "
                          f"VIX data unavailable — defaulting to Neutral"),
        }

    majority_above = indices_above > indices_total / 2

    # Risk-On: majority above + VIX < 20 (strict)
    if majority_above and vix_value < VIX_RISK_ON_THRESHOLD:
        regime = "Risk-On"
        reasoning = (f"{indices_above}/{indices_total} indices above 50-SMA, "
                     f"VIX {vix_value:.1f} < {VIX_RISK_ON_THRESHOLD:.0f}")
    # Risk-Off: minority above + VIX > 25 (strict)
    elif not majority_above and vix_value > VIX_RISK_OFF_THRESHOLD:
        regime = "Risk-Off"
        reasoning = (f"{indices_above}/{indices_total} indices above 50-SMA, "
                     f"VIX {vix_value:.1f} > {VIX_RISK_OFF_THRESHOLD:.0f}")
    # Neutral: everything else
    else:
        regime = "Neutral"
        reasoning = (f"{indices_above}/{indices_total} indices above 50-SMA, "
                     f"VIX {vix_value:.1f} (mixed signals)")

    return {
        "regime": regime,
        "indices_above": indices_above,
        "indices_total": indices_total,
        "vix_value": vix_value,
        "reasoning": reasoning,
    }


def verify_regime_vs_tool(computed, tool_reported):
    """Compare Python regime vs market_pulse.py regime.

    Returns (match: bool, detail: str).
    """
    comp = computed["regime"]
    tool = tool_reported["regime"]
    if comp == tool:
        return True, f"MATCH — both classify as {comp}"
    return False, f"MISMATCH — Python: {comp}, Tool: {tool}"


# ---------------------------------------------------------------------------
# Section 3: Entry Gate Logic
# ---------------------------------------------------------------------------

def apply_entry_gate(regime, orders, portfolio, vix):
    """Apply entry gate to each pending BUY order.

    Returns list of dicts with gate_status and reasoning added.
    """
    positions = portfolio.get("positions", {})
    gated_orders = []

    for order in orders:
        ticker = order["ticker"]
        order_price = order["order_price"]
        pct_below = order["pct_below"]
        note = order.get("note", "")

        if regime == "Risk-On":
            gate = "ACTIVE"
            reasoning = "Risk-On — no constraint"

        elif regime == "Neutral":
            gate = "ACTIVE"
            reasoning = "Neutral — normal entry with advisory"

            # Escalate to CAUTION if VIX in caution range AND rising
            vix_value = vix.get("value")
            vix_5d = vix.get("five_d_pct")
            if (vix_value is not None
                    and VIX_CAUTION_LOW <= vix_value <= VIX_CAUTION_HIGH
                    and vix_5d is not None and vix_5d > 0):
                gate = "CAUTION"
                reasoning = (f"Neutral + VIX {vix_value:.1f} in {VIX_CAUTION_LOW:.0f}-"
                             f"{VIX_CAUTION_HIGH:.0f} range, 5D% +{vix_5d:.2f}% (rising)")

        elif regime == "Risk-Off":
            # Check position status using shares==0 check
            pos = positions.get(ticker, {})
            shares = pos.get("shares", 0)
            if not isinstance(shares, (int, float)) or shares == 0:
                gate = "PAUSE"
                reasoning = "Risk-Off — no active position (shares=0)"
            elif pct_below is not None and pct_below > DEEP_SUPPORT_PCT:
                gate = "ACTIVE"
                reasoning = (f"Risk-Off — deep support capitulation catcher "
                             f"({pct_below:.1f}% > {DEEP_SUPPORT_PCT:.0f}%)")
            else:
                gate = "REVIEW"
                pct_display = f"{pct_below:.1f}%" if pct_below is not None else "N/A"
                reasoning = (f"Risk-Off — near current price "
                             f"({pct_display} <= {DEEP_SUPPORT_PCT:.0f}%), review needed")
        else:
            gate = "ACTIVE"
            reasoning = "Regime unknown — defaulting to ACTIVE with advisory"

        gated_orders.append({
            "ticker": ticker,
            "sector": order.get("sector", "Unknown"),
            "order_price": order_price,
            "shares": order.get("shares", 0),
            "current_price": order.get("current_price"),
            "pct_below": pct_below,
            "gate_status": gate,
            "reasoning": reasoning,
            "note": note,
        })

    return gated_orders


def compute_gate_summary(gated_orders):
    """Count gate statuses. Returns dict {active, caution, review, pause, total}."""
    summary = {"active": 0, "caution": 0, "review": 0, "pause": 0}
    for o in gated_orders:
        status = o["gate_status"].upper()
        if status == "ACTIVE":
            summary["active"] += 1
        elif status == "CAUTION":
            summary["caution"] += 1
        elif status == "REVIEW":
            summary["review"] += 1
        elif status == "PAUSE":
            summary["pause"] += 1
    summary["total"] = len(gated_orders)
    return summary


# ---------------------------------------------------------------------------
# Section 4: Sector Alignment
# ---------------------------------------------------------------------------

def build_portfolio_sectors(gated_orders):
    """Group pending BUY order tickers by sector.

    Returns dict[sector_name, list[ticker]] (unique tickers per sector).
    """
    sector_tickers = {}
    for o in gated_orders:
        sector = o.get("sector", "Unknown")
        ticker = o["ticker"]
        if sector not in sector_tickers:
            sector_tickers[sector] = set()
        sector_tickers[sector].add(ticker)
    # Convert sets to sorted lists
    return {s: sorted(list(t)) for s, t in sector_tickers.items()}


def compute_sector_breadth(sectors):
    """Count sectors with positive day%.

    Returns (positive_count, total_count).
    """
    total = len(sectors)
    positive = sum(1 for s in sectors
                   if s.get("day_pct") is not None and s["day_pct"] > 0)
    return positive, total


def compute_sector_alignment(parsed_sectors, portfolio_sectors):
    """For each sector in portfolio_sectors, compute alignment.

    Returns list of {sector, tickers, etf, day_pct, alignment}.
    """
    # Build lookup from parsed sectors
    sector_lookup = {}
    for s in parsed_sectors:
        sector_lookup[s["name"]] = s

    alignment = []
    for sector, tickers in sorted(portfolio_sectors.items()):
        s_data = sector_lookup.get(sector)
        etf = SECTOR_ETF.get(sector, "N/A")
        if s_data and s_data["day_pct"] is not None:
            day_pct = s_data["day_pct"]
            aligned = "Aligned" if day_pct > 0 else "Misaligned — sector lagging"
        else:
            day_pct = None
            aligned = "N/A — no sector data"

        alignment.append({
            "sector": sector,
            "tickers": tickers,
            "etf": etf,
            "day_pct": day_pct,
            "alignment": aligned,
        })

    return alignment


# ---------------------------------------------------------------------------
# Section 5: Report Assembly
# ---------------------------------------------------------------------------

def _fmt_pct_signed(val):
    """Format a percentage with sign."""
    if val is None:
        return "N/A"
    return f"{val:+.2f}%"


def _fmt_price(val):
    """Format price with $."""
    if val is None:
        return "N/A"
    return f"${val:.2f}"


def build_regime_table(regime_data, vix, sector_breadth, regime_vs_tool):
    """Build the Market Regime table."""
    lines = []
    lines.append("| Metric | Value |")
    lines.append("| :--- | :--- |")

    lines.append(f"| Regime | **{regime_data['regime']}** |")

    # VIX row
    vix_val = vix.get("value")
    vix_interp = vix.get("interpretation", "N/A")
    if vix_val is not None:
        lines.append(f"| VIX | {vix_val:.2f} ({vix_interp}) |")
    else:
        lines.append("| VIX | N/A |")

    # VIX 5D%
    vix_5d = vix.get("five_d_pct")
    if vix_5d is not None:
        direction = "rising = increasing fear" if vix_5d > 0 else "falling = decreasing fear"
        lines.append(f"| VIX 5D% | {vix_5d:+.2f}% ({direction}) |")
    else:
        lines.append("| VIX 5D% | N/A (data unavailable) |")

    # Indices
    above = regime_data["indices_above"]
    total = regime_data["indices_total"]
    excluded = 3 - total  # assuming 3 indices monitored
    suffix = f" (excluding {excluded} N/A)" if excluded > 0 else ""
    lines.append(f"| Indices Above 50-SMA | {above}/{total}{suffix} |")

    # Sector Breadth
    pos, tot = sector_breadth
    lines.append(f"| Sector Breadth | {pos}/{tot} positive |")

    # Regime vs Tool
    match, detail = regime_vs_tool
    status = "MATCH" if match else "MISMATCH"
    lines.append(f"| Regime vs Tool | {status} ({detail}) |")

    return "\n".join(lines)


def build_index_detail(indices):
    """Build the Index Detail table."""
    lines = []
    lines.append("| Index | ETF | Price | Day% | 5D% | vs 50-SMA |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")

    for idx in indices:
        lines.append(
            f"| {idx['name']} | {idx['etf']} | {_fmt_price(idx['price'])} "
            f"| {_fmt_pct_signed(idx['day_pct'])} | {_fmt_pct_signed(idx['five_d_pct'])} "
            f"| {idx['vs_50sma'] or 'N/A'} |"
        )

    return "\n".join(lines)


def build_gate_decisions_table(gated_orders):
    """Build Entry Gate Decisions table, sorted: PAUSE > REVIEW > CAUTION > ACTIVE."""
    # Sort by gate priority
    priority = {"PAUSE": 0, "REVIEW": 1, "CAUTION": 2, "ACTIVE": 3}
    sorted_orders = sorted(gated_orders,
                           key=lambda o: (priority.get(o["gate_status"].upper(), 9),
                                          o["ticker"],
                                          -(o["pct_below"] or 0)))

    lines = []
    lines.append("| Ticker | Order Price | Shares | Current Price | % Below Current "
                  "| Gate Status | Reasoning | Notes |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for o in sorted_orders:
        pct_str = f"{o['pct_below']:.1f}%" if o["pct_below"] is not None else "N/A"
        lines.append(
            f"| {o['ticker']} | {_fmt_price(o['order_price'])} "
            f"| {o['shares']} | {_fmt_price(o['current_price'])} "
            f"| {pct_str} | **{o['gate_status']}** "
            f"| {o['reasoning']} | {o['note']} |"
        )

    return "\n".join(lines)


def build_gate_summary_table(summary):
    """Build the Gate Summary table."""
    lines = []
    lines.append("| Status | Count |")
    lines.append("| :--- | :--- |")
    lines.append(f"| ACTIVE | {summary['active']} |")
    lines.append(f"| CAUTION | {summary['caution']} |")
    lines.append(f"| REVIEW | {summary['review']} |")
    lines.append(f"| PAUSE | {summary['pause']} |")
    lines.append(f"| **Total** | **{summary['total']}** |")
    return "\n".join(lines)


def build_sector_alignment_table(alignment):
    """Build the Sector Alignment table."""
    lines = []
    lines.append("| Portfolio Sector | Tickers | Market Day% | Alignment |")
    lines.append("| :--- | :--- | :--- | :--- |")

    for a in alignment:
        day_str = _fmt_pct_signed(a["day_pct"]) if a["day_pct"] is not None else "N/A"
        lines.append(
            f"| {a['sector']} ({a['etf']}) | {', '.join(a['tickers'])} "
            f"| {day_str} | {a['alignment']} |"
        )

    return "\n".join(lines)


def assemble_pre_analyst(report_date, regime_data, vix, indices,
                         sector_breadth, regime_vs_tool, gated_orders,
                         gate_summary, sector_alignment):
    """Assemble the complete market-context-pre-analyst.md."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = []

    # Header
    parts.append(f"# Market Context Pre-Analyst — {report_date.isoformat()}")
    parts.append(f"*Generated: {now_str} | Tool: market_context_pre_analyst.py*")
    parts.append("")

    # Market Regime
    parts.append("## Market Regime")
    parts.append("")
    parts.append(build_regime_table(regime_data, vix, sector_breadth, regime_vs_tool))
    parts.append("")

    # Index Detail
    parts.append("## Index Detail")
    parts.append("")
    parts.append(build_index_detail(indices))
    parts.append("")

    # Entry Gate Decisions
    parts.append("## Entry Gate Decisions")
    parts.append("")
    parts.append(build_gate_decisions_table(gated_orders))
    parts.append("")

    # Gate Summary
    parts.append("## Gate Summary")
    parts.append("")
    parts.append(build_gate_summary_table(gate_summary))
    parts.append("")

    # Sector Alignment
    parts.append("## Sector Alignment")
    parts.append("")
    parts.append(build_sector_alignment_table(sector_alignment))
    parts.append("")

    # LLM task markers
    parts.append("---")
    parts.append("")
    parts.append("## LLM Tasks")
    parts.append("")
    parts.append(f"*LLM: Write Executive Summary (2-3 sentences: regime = "
                 f"**{regime_data['regime']}**, VIX = "
                 f"{vix.get('value', 'N/A')}, total orders = {gate_summary['total']}, "
                 f"gate breakdown: {gate_summary['active']} ACTIVE, "
                 f"{gate_summary['caution']} CAUTION, "
                 f"{gate_summary['review']} REVIEW, "
                 f"{gate_summary['pause']} PAUSE).*")
    parts.append("")
    parts.append("*LLM: Write Entry Actions (specific: which orders to pause, keep, review).*")
    parts.append("")
    parts.append("*LLM: Write Position Management (regime-appropriate advisory).*")
    parts.append("")
    parts.append("*LLM: Write Sector Rotation Notes (if leading/lagging sectors diverge).*")
    parts.append("")

    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    t0 = time.monotonic()

    print("Market Context Pre-Analyst")
    print("=" * 50)

    # Load inputs
    print("\n[1/5] Loading inputs...")
    raw_text, portfolio = validate_inputs()
    report_date = extract_report_date(raw_text)
    print(f"  Report date: {report_date.isoformat()}")

    # Parse raw data
    print("\n[2/5] Parsing raw data...")
    indices = parse_indices(raw_text)
    vix = parse_vix(raw_text)
    sectors = parse_sectors(raw_text)
    tool_regime = parse_tool_regime(raw_text)
    buy_orders = parse_pending_buy_orders(raw_text)

    print(f"  Indices parsed: {len(indices)}")
    print(f"  VIX: {vix.get('value', 'N/A')}")
    print(f"  Sectors: {len(sectors)}")
    print(f"  Pending BUY orders: {len(buy_orders)}")
    print(f"  Tool regime: {tool_regime['regime']}")

    # Classify regime
    print("\n[3/5] Classifying regime...")
    regime_data = classify_regime(indices, vix)
    regime_vs_tool = verify_regime_vs_tool(regime_data, tool_regime)
    sector_breadth = compute_sector_breadth(sectors)
    print(f"  Computed regime: {regime_data['regime']}")
    print(f"  Regime vs tool: {regime_vs_tool[1]}")
    print(f"  Sector breadth: {sector_breadth[0]}/{sector_breadth[1]} positive")

    # Apply entry gate
    print(f"\n[4/5] Applying entry gate to {len(buy_orders)} orders...")
    gated_orders = apply_entry_gate(regime_data["regime"], buy_orders, portfolio, vix)
    gate_summary = compute_gate_summary(gated_orders)
    print(f"  Gate summary: {gate_summary['active']} ACTIVE, "
          f"{gate_summary['caution']} CAUTION, "
          f"{gate_summary['review']} REVIEW, "
          f"{gate_summary['pause']} PAUSE")

    # Sector alignment
    portfolio_sectors = build_portfolio_sectors(gated_orders)
    sector_alignment = compute_sector_alignment(sectors, portfolio_sectors)

    # Assemble and write
    print("\n[5/5] Assembling market-context-pre-analyst.md...")
    content = assemble_pre_analyst(
        report_date, regime_data, vix, indices,
        sector_breadth, regime_vs_tool, gated_orders,
        gate_summary, sector_alignment
    )
    OUTPUT_PATH.write_text(content, encoding="utf-8")

    # Summary
    elapsed = time.monotonic() - t0
    size_kb = OUTPUT_PATH.stat().st_size / 1024

    print(f"\n{'=' * 50}")
    print(f"Output: market-context-pre-analyst.md ({size_kb:.1f} KB)")
    print(f"Regime: {regime_data['regime']}")
    print(f"Orders gated: {gate_summary['total']}")
    print(f"Elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
