#!/usr/bin/env python3
"""Deep Dive Pre-Analyst — mechanical computation for identity.md sections.

Reads deep-dive-raw.md (Phase 1 output) and portfolio.json. Computes all
deterministic sections: wick-adjusted buy levels table, bullet plan with
fill annotations, projected averages, and warnings. Writes
deep-dive-pre-analyst.md for the LLM analyst to transcribe into identity.md.

Usage:
    python3 tools/deep_dive_pre_analyst.py [--ticker TICKER]
"""

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_PATH = ROOT / "deep-dive-raw.md"
PORTFOLIO_PATH = ROOT / "portfolio.json"
OUTPUT_PATH = ROOT / "deep-dive-pre-analyst.md"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_header(raw_text):
    """Extract ticker, date, status, current_price from deep-dive-raw.md header."""
    result = {}

    # Ticker and date from first line: # Deep Dive Raw Data — <TICKER> — <date>
    m = re.search(r"^# Deep Dive Raw Data\s*[—–-]+\s*(\S+)\s*[—–-]+\s*(.+)$", raw_text, re.MULTILINE)
    if m:
        result["ticker"] = m.group(1).strip()
        result["date"] = m.group(2).strip()
    else:
        result["ticker"] = "UNKNOWN"
        result["date"] = datetime.date.today().isoformat()

    # Status: NEW or EXISTING
    m = re.search(r"\*\*Classification:\*\*\s*(NEW|EXISTING)", raw_text)
    result["status"] = m.group(1) if m else "UNKNOWN"

    # Current price from header
    m = re.search(r"\*\*Current price:\*\*\s*\$([0-9]+\.?\d*)", raw_text)
    if m:
        result["current_price"] = float(m.group(1))
    else:
        # Fallback: parse from wick section **Current Price: $X.XX**
        m = re.search(r"\*\*Current Price:\s*\$([0-9]+\.?\d*)\*\*", raw_text)
        result["current_price"] = float(m.group(1)) if m else None

    return result


def parse_wick_section(raw_text):
    """Extract wick tool output from deep-dive-raw.md.

    Returns dict with monthly_swing, swing_consistency, active_radius,
    support_table, bullet_plan_table — or None if wick tool failed.
    """
    # Find wick section boundaries
    wick_start = raw_text.find("### 1. Wick Offset Analysis")
    if wick_start == -1:
        return None
    wick_end = raw_text.find("### 2.", wick_start + 1)
    if wick_end == -1:
        wick_end = len(raw_text)
    section = raw_text[wick_start:wick_end]

    # Check for error indicators
    if "*Error" in section and "Support Levels" not in section:
        return None

    result = {}

    # Monthly swing
    m = re.search(r"\*\*Monthly Swing:\s*([0-9]+\.?\d*)%\*\*", section)
    result["monthly_swing"] = float(m.group(1)) if m else None

    # Swing consistency
    m = re.search(r"(\d+)% of months hit 10%\+", section)
    result["swing_consistency"] = int(m.group(1)) if m else None

    # Active radius
    m = re.search(r"Active Zone:\s*within\s*([0-9]+\.?\d*)%", section)
    result["active_radius"] = float(m.group(1)) if m else None

    # Parse 9-column support table
    result["support_table"] = _parse_support_table(section)
    if not result["support_table"]:
        return None

    # Parse 8-column bullet plan table
    result["bullet_plan_table"] = _parse_bullet_plan_table(section)

    return result


def _parse_support_table(section):
    """Parse the 9-column Support Levels & Buy Recommendations table."""
    rows = []
    lines = section.split("\n")
    in_table = False
    header_found = False

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            if in_table:
                break
            continue

        # Detect header row
        if "Support" in stripped and "Source" in stripped and "Hold Rate" in stripped:
            in_table = True
            header_found = True
            continue

        if not header_found:
            continue

        # Skip alignment row
        if re.match(r"^\|\s*:?-+", stripped):
            continue

        # Parse data row
        cells = [c.strip() for c in stripped.split("|")[1:-1]]
        if len(cells) < 9:
            continue

        # Parse dollar amounts
        support_m = re.search(r"\$([0-9]+\.?\d*)", cells[0])
        support = float(support_m.group(1)) if support_m else None
        if support is None:
            continue

        source = cells[1].strip()

        approaches_m = re.search(r"(\d+)", cells[2])
        approaches = int(approaches_m.group(1)) if approaches_m else 0

        held_m = re.search(r"(\d+)", cells[3])
        held = int(held_m.group(1)) if held_m else 0

        hold_rate_m = re.search(r"(\d+)%", cells[4])
        hold_rate = int(hold_rate_m.group(1)) if hold_rate_m else 0

        median_offset = cells[5].strip()

        # Buy At — handle $X.XX, $X.XX ↑above, N/A (no holds)
        buy_at_cell = cells[6].strip()
        buy_at_m = re.search(r"\$([0-9]+\.?\d*)", buy_at_cell)
        if buy_at_m:
            buy_at = float(buy_at_m.group(1))
        else:
            buy_at = None  # N/A (no holds)

        above = "above" in buy_at_cell.lower()

        zone = cells[7].strip()
        tier = cells[8].strip()

        rows.append({
            "support": support,
            "source": source,
            "approaches": approaches,
            "held": held,
            "hold_rate": hold_rate,
            "median_offset": median_offset,
            "buy_at": buy_at,
            "above": above,
            "zone": zone,
            "tier": tier,
        })

    return rows


def _parse_bullet_plan_table(section):
    """Parse the 8-column Suggested Bullet Plan table."""
    rows = []
    lines = section.split("\n")
    in_table = False
    header_found = False

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            if in_table:
                break
            continue

        # Detect header row by # | Zone | Level pattern
        if re.search(r"#\s*\|.*Zone\s*\|.*Level", stripped):
            in_table = True
            header_found = True
            continue

        if not header_found:
            continue

        # Skip alignment row
        if re.match(r"^\|\s*:?-+", stripped):
            continue

        # Parse data row
        cells = [c.strip() for c in stripped.split("|")[1:-1]]
        if len(cells) < 8:
            continue

        num_m = re.search(r"(\d+)", cells[0])
        num = int(num_m.group(1)) if num_m else 0

        zone = cells[1].strip()

        level_m = re.search(r"\$([0-9]+\.?\d*)", cells[2])
        level = float(level_m.group(1)) if level_m else 0.0

        buy_at_m = re.search(r"\$([0-9]+\.?\d*)", cells[3])
        buy_at = float(buy_at_m.group(1)) if buy_at_m else 0.0

        hold_m = re.search(r"(\d+)%", cells[4])
        hold_pct = int(hold_m.group(1)) if hold_m else 0

        tier = cells[5].strip()

        shares_m = re.search(r"(\d+)", cells[6])
        shares = int(shares_m.group(1)) if shares_m else 0

        cost_m = re.search(r"\$?([0-9]+\.?\d*)", cells[7])
        cost = float(cost_m.group(1)) if cost_m else 0.0

        rows.append({
            "num": num,
            "zone": zone,
            "level": level,
            "buy_at": buy_at,
            "hold_pct": hold_pct,
            "tier": tier,
            "shares": shares,
            "cost": cost,
        })

    return rows


def parse_tool_failures(raw_text):
    """Extract the Tool Failures section. Return list of failed tool names."""
    m = re.search(r"## Tool Failures\n(.+?)(?:\n##|\Z)", raw_text, re.DOTALL)
    if not m:
        return []
    section = m.group(1).strip()
    if section == "All tools completed successfully":
        return []
    failures = []
    for line in section.split("\n"):
        line = line.strip()
        if line.startswith("- "):
            # Format: - tool_name.py: *Error ...*
            tool_m = re.match(r"- (\S+?):", line)
            if tool_m:
                failures.append(tool_m.group(1))
    return failures


# ---------------------------------------------------------------------------
# Portfolio Loading
# ---------------------------------------------------------------------------

def load_portfolio(ticker):
    """Load portfolio.json and extract ticker-specific data."""
    if not PORTFOLIO_PATH.exists():
        print(f"*Error: {PORTFOLIO_PATH.name} not found*", file=sys.stderr)
        sys.exit(1)
    try:
        portfolio = json.loads(PORTFOLIO_PATH.read_text())
    except json.JSONDecodeError as e:
        print(f"*Error: {PORTFOLIO_PATH.name} is malformed JSON: {e}*", file=sys.stderr)
        sys.exit(1)

    positions = portfolio.get("positions", {})
    position = positions.get(ticker)

    pending_orders = portfolio.get("pending_orders", {})
    orders = pending_orders.get(ticker, [])

    capital = portfolio.get("capital", {})

    watchlist = portfolio.get("watchlist", [])
    on_watchlist = ticker in watchlist

    return {
        "position": position,
        "pending_orders": orders,
        "capital": capital,
        "on_watchlist": on_watchlist,
        "fill_prices": position.get("fill_prices", []) if position else [],
    }


def parse_bullets_used(bullets_used_val):
    """Parse bullets_used field from portfolio.json.

    Returns (active_filled_count, reserve_filled_count).
    """
    if bullets_used_val is None:
        return (0, 0)

    if isinstance(bullets_used_val, (int, float)):
        return (int(bullets_used_val), 0)

    if isinstance(bullets_used_val, str):
        s = bullets_used_val

        # Try: "N active + RN filled"
        active_m = re.search(r"(\d+)\s*active", s)
        reserve_m = re.search(r"R(\d+)", s)

        if active_m:
            active = int(active_m.group(1))
            reserve = int(reserve_m.group(1)) if reserve_m else 0
            return (active, reserve)

        # Catch-all: first number found
        first_m = re.search(r"(\d+)", s)
        if first_m:
            return (int(first_m.group(1)), 0)

        print(f"WARNING: Cannot parse bullets_used: {bullets_used_val}", file=sys.stderr)
        return (0, 0)

    return (0, 0)


# ---------------------------------------------------------------------------
# Identity Table Builder
# ---------------------------------------------------------------------------

def build_identity_table(support_rows):
    """Transform 9-column support table → 7-column identity table.

    Returns (table_lines, warnings_list).
    """
    filtered = []
    warnings = []

    for row in support_rows:
        # Filter Skip-tier rows
        if row["tier"] == "Skip" or row["hold_rate"] < 15:
            continue
        # Filter N/A buy_at rows
        if row["buy_at"] is None:
            print(f"INFO: Skipping ${row['support']:.2f} {row['source']} — buy_at is N/A (no holds)", file=sys.stderr)
            continue
        filtered.append(row)

    # Build table lines
    table_lines = []
    table_lines.append("| Raw Support | Source | Hold Rate | Median Offset | Buy At | Zone | Tier |")
    table_lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    if not filtered:
        table_lines.append("| — | No eligible levels (all below 15% hold rate or N/A) | — | — | — | — | — |")

    for row in filtered:
        buy_at_str = f"${row['buy_at']:.2f}"
        if row["above"]:
            buy_at_str += " ↑above"
        table_lines.append(
            f"| ${row['support']:.2f} | {row['source']} "
            f"| {row['hold_rate']}% | {row['median_offset']} "
            f"| {buy_at_str} | {row['zone']} | {row['tier']} |"
        )

    # Convergence detection: rows where buy_at values are within 0.5% of each other
    buy_at_rows = [(row, row["buy_at"]) for row in filtered if row["buy_at"] is not None and not row["above"]]
    for i in range(len(buy_at_rows)):
        for j in range(i + 1, len(buy_at_rows)):
            row_a, ba_a = buy_at_rows[i]
            row_b, ba_b = buy_at_rows[j]
            min_ba = min(ba_a, ba_b)
            if min_ba > 0 and abs(ba_a - ba_b) / min_ba <= 0.005:
                warnings.append(
                    f"Convergence: ${row_a['support']:.2f} [{row_a['source']}] and "
                    f"${row_b['support']:.2f} [{row_b['source']}] merge → "
                    f"buy-at ${ba_a:.2f} / ${ba_b:.2f} (within 0.5%)"
                )

    return table_lines, warnings


# ---------------------------------------------------------------------------
# Bullet Plan Builder
# ---------------------------------------------------------------------------

FILL_MATCH_TOLERANCE = 0.05  # 5%, same as bullet_recommender DRIFT_TOLERANCE


def _match_fill_to_bullet(fill_price, bullets):
    """Match fill price to nearest bullet by buy_at within 5%. Returns 1-based index or None."""
    best_idx, best_dist = None, float('inf')
    for i, b in enumerate(bullets):
        ba = b.get("buy_at", 0)
        if ba <= 0:
            continue
        dist = abs(fill_price - ba) / ba
        if dist < best_dist:
            best_dist, best_idx = dist, i + 1
    return best_idx if best_dist <= FILL_MATCH_TOLERANCE else None


def build_bullet_plan(bullet_plan_rows, support_rows, position, active_filled, reserve_filled,
                      fill_prices=None, status="EXISTING"):
    """Build B1-B5 / R1-R3 formatted entries from wick tool's suggested bullet plan.

    support_rows is the raw 9-column table (before filtering).
    status is "NEW" or "EXISTING" from the deep-dive-raw.md header.
    fill_prices is a list of actual fill prices from portfolio.json (or None for legacy).
    """
    # Separate active and reserve bullets
    active_bullets = [b for b in bullet_plan_rows if b["zone"] == "Active"]
    reserve_bullets = [b for b in bullet_plan_rows if b["zone"] == "Reserve"]

    # Guard: cap filled counts to plan size
    original_active = active_filled
    original_reserve = reserve_filled
    active_filled = min(active_filled, len(active_bullets))
    reserve_filled = min(reserve_filled, len(reserve_bullets))

    if active_filled < original_active:
        print(f"WARNING: bullets_used active ({original_active}) exceeds fresh bullet plan count "
              f"({len(active_bullets)}). Capped to {len(active_bullets)}.", file=sys.stderr)
    if reserve_filled < original_reserve:
        print(f"WARNING: bullets_used reserve ({original_reserve}) exceeds fresh bullet plan count "
              f"({len(reserve_bullets)}). Capped to {len(reserve_bullets)}.", file=sys.stderr)

    has_position = position is not None and position.get("shares", 0) > 0

    # Build filled index sets: per-bullet matching via fill_prices, or sequential fallback
    if fill_prices and has_position:
        active_filled_indices = set()
        reserve_filled_indices = set()
        remaining_fps = list(fill_prices)
        for fp in list(remaining_fps):
            idx = _match_fill_to_bullet(fp, active_bullets)
            if idx is not None and idx not in active_filled_indices:
                active_filled_indices.add(idx)
                remaining_fps.remove(fp)
        for fp in remaining_fps:
            idx = _match_fill_to_bullet(fp, reserve_bullets)
            if idx is not None and idx not in reserve_filled_indices:
                reserve_filled_indices.add(idx)
    else:
        # Legacy fallback: sequential fill assumption
        active_filled_indices = set(range(1, active_filled + 1))
        reserve_filled_indices = set(range(1, reserve_filled + 1))

    # Build source lookup from support table: dollar-formatted level → source
    # Concatenate sources if multiple rows share the same price
    source_lookup = {}
    for sr in support_rows:
        key = f"${sr['support']:.2f}"
        if key in source_lookup:
            source_lookup[key] += f" / {sr['source']}"
        else:
            source_lookup[key] = sr["source"]

    active_lines = []
    reserve_lines = []
    active_pending_cost = 0.0
    reserve_pending_cost = 0.0

    # Active bullets
    if has_position and active_filled_indices:
        filled_nums = sorted(active_filled_indices)
        if len(filled_nums) == 1:
            range_str = f"B{filled_nums[0]}"
        else:
            range_str = "B" + ",".join(str(n) for n in filled_nums)
        active_lines.append(
            f"{range_str}: FILLED ({len(filled_nums)} active bullet{'s' if len(filled_nums) > 1 else ''} "
            f"used — see memory.md for fill details)."
        )

    for idx, b in enumerate(active_bullets):
        bullet_num = idx + 1
        if has_position and bullet_num in active_filled_indices:
            continue  # Already covered by FILLED summary

        level_key = f"${b['level']:.2f}"
        source = source_lookup.get(level_key, "Unknown")
        if source == "Unknown":
            print(f"WARNING: No source match for level {level_key}", file=sys.stderr)

        tag = "**PENDING.** (new)" if status == "NEW" else "**PENDING.**"
        active_lines.append(
            f"B{bullet_num}: ${b['buy_at']:.2f} ({b['shares']} shares, ~${b['cost']:.2f}) — "
            f"${b['level']:.2f} {source}, {b['hold_pct']}% hold rate, {b['tier']} tier. {tag}"
        )
        active_pending_cost += b["cost"]

    # Reserve bullets
    if has_position and reserve_filled_indices:
        filled_nums = sorted(reserve_filled_indices)
        if len(filled_nums) == 1:
            range_str = f"R{filled_nums[0]}"
        else:
            range_str = "R" + ",".join(str(n) for n in filled_nums)
        reserve_lines.append(
            f"{range_str}: FILLED ({len(filled_nums)} reserve bullet{'s' if len(filled_nums) > 1 else ''} "
            f"used — see memory.md for fill details)."
        )

    for idx, b in enumerate(reserve_bullets):
        bullet_num = idx + 1
        if has_position and bullet_num in reserve_filled_indices:
            continue

        level_key = f"${b['level']:.2f}"
        source = source_lookup.get(level_key, "Unknown")
        if source == "Unknown":
            print(f"WARNING: No source match for level {level_key}", file=sys.stderr)

        tag = "**PENDING.** (new)" if status == "NEW" else "**PENDING.**"
        reserve_lines.append(
            f"R{bullet_num}: ${b['buy_at']:.2f} ({b['shares']} shares, ~${b['cost']:.2f}) — "
            f"${b['level']:.2f} {source}, {b['hold_pct']}% hold rate, {b['tier']} tier. {tag}"
        )
        reserve_pending_cost += b["cost"]

    return {
        "active_lines": active_lines,
        "reserve_lines": reserve_lines,
        "active_pending": active_pending_cost,
        "reserve_pending": reserve_pending_cost,
        "active_count": len(active_bullets),
        "reserve_count": len(reserve_bullets),
        "active_filled_count": len(active_filled_indices),
        "reserve_filled_count": len(reserve_filled_indices),
        "active_bullets_raw": active_bullets,
        "reserve_bullets_raw": reserve_bullets,
        "active_filled_indices": active_filled_indices,
        "reserve_filled_indices": reserve_filled_indices,
    }


# ---------------------------------------------------------------------------
# Warning Detection
# ---------------------------------------------------------------------------

def detect_warnings(support_rows, bullet_plan_rows, current_price, capital):
    """Detect and format warnings."""
    warnings = []
    if current_price is None:
        warnings.append("Warning: current_price unavailable — dead zone and gap checks skipped.")
        return warnings
    active_bullets_max = capital.get("active_bullets_max", 5)

    # 1. Dead zones: buy_at >= current_price
    for row in support_rows:
        if row["buy_at"] is not None and row["buy_at"] >= current_price and row["tier"] != "Skip" and row["hold_rate"] >= 15:
            warnings.append(
                f"Dead Zone Warning: ${row['support']:.2f} {row['source']} buy-at ${row['buy_at']:.2f} "
                f"is above current price (${current_price:.2f}) — excluded from bullet plan."
            )

    # 2. Unfunded active levels: eligible active levels that didn't get a bullet
    active_bullets = [b for b in bullet_plan_rows if b["zone"] == "Active"]
    bullet_levels = {f"${b['level']:.2f}" for b in active_bullets}

    eligible_active = [
        row for row in support_rows
        if row["zone"] == "Active"
        and row["tier"] != "Skip"
        and row["hold_rate"] >= 15
        and row["buy_at"] is not None
        and row["buy_at"] < current_price
    ]

    if len(eligible_active) > active_bullets_max:
        for row in eligible_active:
            level_key = f"${row['support']:.2f}"
            if level_key not in bullet_levels:
                warnings.append(
                    f"Unfunded Active Level: ${row['support']:.2f} {row['source']} → "
                    f"buy-at ${row['buy_at']:.2f}, {row['hold_rate']}% hold, {row['tier']} tier. "
                    f"Not funded — {active_bullets_max}-bullet active cap reached. "
                    f"Zone stays 'Active' in the wick table — do NOT relabel or move to Reserve bullet plan."
                )

    # 3. Gap warning between last active and first reserve bullet
    reserve_bullets = [b for b in bullet_plan_rows if b["zone"] == "Reserve"]
    if active_bullets and reserve_bullets:
        last_active_buy = active_bullets[-1]["buy_at"]
        first_reserve_buy = reserve_bullets[0]["buy_at"]
        if last_active_buy > 0:
            gap_pct = ((last_active_buy - first_reserve_buy) / last_active_buy) * 100
            if gap_pct > 10:
                # Find intermediate levels
                intermediate = []
                for row in support_rows:
                    if (row["buy_at"] is not None
                            and first_reserve_buy < row["buy_at"] < last_active_buy
                            and row["hold_rate"] >= 15
                            and row["tier"] != "Skip"
                            and f"${row['support']:.2f}" not in bullet_levels):
                        intermediate.append(f"${row['support']:.2f} at {row['hold_rate']}%")
                inter_str = f" Intermediate levels: {', '.join(intermediate)}." if intermediate else ""
                warnings.append(
                    f"Gap Warning: Last active bullet (${last_active_buy:.2f}) to first reserve "
                    f"(${first_reserve_buy:.2f}) is {gap_pct:.0f}% gap.{inter_str}"
                )

    return warnings


# ---------------------------------------------------------------------------
# Projected Averages
# ---------------------------------------------------------------------------

def compute_projected_averages(position, bullet_plan, active_filled_indices, reserve_filled_indices):
    """Compute projected averages for each unfilled bullet filling sequentially."""
    rows = []

    if position is not None and position.get("shares", 0) > 0:
        running_shares = position["shares"]
        running_cost = position["shares"] * position["avg_cost"]
        current_avg = position["avg_cost"]
        target_10 = current_avg * 1.10
        rows.append(f"| Current position | {running_shares} | ${current_avg:.2f} | ${target_10:.2f} |")
    else:
        running_shares = 0
        running_cost = 0.0
        rows.append("| No current position | 0 | — | — |")

    # Get unfilled active bullets
    active_bullets = bullet_plan.get("active_bullets_raw", [])
    reserve_bullets = bullet_plan.get("reserve_bullets_raw", [])

    for idx, b in enumerate(active_bullets):
        bullet_num = idx + 1
        if bullet_num in active_filled_indices:
            continue  # skip THIS specific filled bullet
        running_shares += b["shares"]
        running_cost += b["shares"] * b["buy_at"]
        new_avg = running_cost / running_shares if running_shares > 0 else 0
        target_10 = new_avg * 1.10
        rows.append(f"| + B{bullet_num} fills | {running_shares} | ${new_avg:.2f} | ${target_10:.2f} |")

    for idx, b in enumerate(reserve_bullets):
        bullet_num = idx + 1
        if bullet_num in reserve_filled_indices:
            continue  # skip THIS specific filled bullet
        running_shares += b["shares"]
        running_cost += b["shares"] * b["buy_at"]
        new_avg = running_cost / running_shares if running_shares > 0 else 0
        target_10 = new_avg * 1.10
        rows.append(f"| + R{bullet_num} fills | {running_shares} | ${new_avg:.2f} | ${target_10:.2f} |")

    return rows


# ---------------------------------------------------------------------------
# Output Builder
# ---------------------------------------------------------------------------

def _format_position_context(header, portfolio_data):
    """Format the Position Context section lines (shared by OK and BLOCKED output)."""
    lines = []
    position = portfolio_data["position"]
    lines.append("## Position Context")
    lines.append(f"- Status: {header['status']}")
    if position and position.get("shares", 0) > 0:
        lines.append(f"- Current position: {position['shares']} shares @ ${position['avg_cost']:.2f} avg")
        active_f, reserve_f = parse_bullets_used(position.get("bullets_used"))
        bullets_str = f"{active_f} active"
        if reserve_f > 0:
            bullets_str += f" + R{reserve_f} reserve"
        lines.append(f"- Bullets used: {bullets_str}")
    else:
        lines.append("- Current position: No position")
        lines.append("- Bullets used: None")
    orders = portfolio_data["pending_orders"]
    if orders:
        lines.append(f"- Pending orders: {len(orders)}")
    else:
        lines.append("- Pending orders: None")
    return lines


def build_output(header, wick_data, portfolio_data, identity_table, identity_warnings,
                 bullet_plan, all_warnings, projected_rows):
    """Assemble deep-dive-pre-analyst.md."""
    lines = []
    ticker = header["ticker"]
    date_str = header["date"]
    current_price = header["current_price"]

    lines.append(f"# Deep Dive Pre-Analyst — {ticker} — {date_str}")
    lines.append("")

    lines.append("## Wick Data Status")
    lines.append("OK")
    lines.append("")

    lines.append("## Current Price")
    lines.append(f"${current_price:.2f}" if current_price else "Unknown")
    lines.append("")

    # Monthly Swing
    lines.append("## Monthly Swing")
    swing = wick_data.get("monthly_swing")
    consistency = wick_data.get("swing_consistency")
    radius = wick_data.get("active_radius")
    if swing is not None:
        parts = [f"{swing:.1f}% median"]
        if consistency is not None:
            parts.append(f"{consistency}% of months hit 10%+")
        if radius is not None:
            parts.append(f"Active zone: within {radius:.1f}% of current price")
        lines.append(" | ".join(parts))
    else:
        lines.append("N/A")
    lines.append("")

    # Wick-Adjusted Buy Levels
    lines.append(f"## Wick-Adjusted Buy Levels (run {date_str})")
    lines.append("")
    for tl in identity_table:
        lines.append(tl)
    lines.append("")

    # Level Warnings (from both identity_table convergence and detect_warnings)
    lines.append("## Level Warnings")
    combined_warnings = identity_warnings + all_warnings
    if combined_warnings:
        for w in combined_warnings:
            lines.append(f"- {w}")
    else:
        lines.append("No warnings.")
    lines.append("")

    # Bullet Plan
    active_filled = bullet_plan["active_filled_count"]
    active_count = bullet_plan["active_count"]
    active_filled_indices = bullet_plan.get("active_filled_indices", set())
    lines.append("## Bullet Plan (Active Pool — $300)")
    if bullet_plan["active_lines"]:
        for al in bullet_plan["active_lines"]:
            lines.append(al)
        # Pending summary — use actual unfilled indices for non-contiguous fills
        unfilled_active = sorted(set(range(1, active_count + 1)) - active_filled_indices)
        if unfilled_active:
            range_str = "B" + ",".join(str(n) for n in unfilled_active)
            lines.append(f"Pending: ~${bullet_plan['active_pending']:.2f} ({range_str}) if all unfilled fill.")
        elif active_filled > 0:
            lines.append(f"All {active_filled} active bullets filled. No pending.")
    else:
        lines.append("No active bullets in plan.")
    lines.append("")

    # Reserve Plan
    lines.append("## Reserve Plan ($300)")
    reserve_filled = bullet_plan["reserve_filled_count"]
    reserve_count = bullet_plan["reserve_count"]
    reserve_filled_indices = bullet_plan.get("reserve_filled_indices", set())
    if bullet_plan["reserve_lines"]:
        for rl in bullet_plan["reserve_lines"]:
            lines.append(rl)
        unfilled_reserve = sorted(set(range(1, reserve_count + 1)) - reserve_filled_indices)
        if unfilled_reserve:
            lines.append(f"Total pending reserve: ~${bullet_plan['reserve_pending']:.2f} if all unfilled fill.")
        elif reserve_filled > 0:
            lines.append(f"All {reserve_filled} reserve bullets filled. No pending.")
    else:
        lines.append("No reserve bullets in plan.")
    lines.append("")

    # Projected Averages
    lines.append("## Projected Averages")
    lines.append("")
    lines.append("| Scenario | Total Shares | Avg Cost | 10% Target |")
    lines.append("| :--- | :--- | :--- | :--- |")
    for pr in projected_rows:
        lines.append(pr)
    lines.append("")

    # Position Context
    lines.extend(_format_position_context(header, portfolio_data))
    lines.append("")

    return "\n".join(lines)


def build_blocked_output(header, portfolio_data, failure_text):
    """Build minimal output when wick data is unavailable."""
    lines = []
    ticker = header["ticker"]
    date_str = header["date"]

    lines.append(f"# Deep Dive Pre-Analyst — {ticker} — {date_str}")
    lines.append("")
    lines.append("## Wick Data Status")
    lines.append(f"BLOCKED — wick_offset_analyzer.py failed. {failure_text}")
    lines.append("")
    lines.extend(_format_position_context(header, portfolio_data))
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Deep Dive Pre-Analyst")
    parser.add_argument("--ticker", default=None, help="Expected ticker for validation")
    args = parser.parse_args()

    # 1. Read raw file
    if not RAW_PATH.exists():
        print(f"*Error: {RAW_PATH.name} not found — run deep-dive collector first*", file=sys.stderr)
        sys.exit(1)
    raw_text = RAW_PATH.read_text(encoding="utf-8")

    # 2. Parse header
    header = parse_header(raw_text)
    ticker = header["ticker"]
    current_price = header["current_price"]

    # 2b. Ticker validation
    if args.ticker and args.ticker != ticker:
        print(f"*Error: Expected ticker {args.ticker} but deep-dive-raw.md contains {ticker}*", file=sys.stderr)
        sys.exit(1)

    print(f"Deep Dive Pre-Analyst — {ticker}")
    print("=" * 40)

    # 3. Parse wick section
    wick_data = parse_wick_section(raw_text)

    # 4. Parse tool failures
    failures = parse_tool_failures(raw_text)
    wick_failed = "wick_offset_analyzer.py" in failures

    # 5. Load portfolio
    portfolio_data = load_portfolio(ticker)
    position = portfolio_data["position"]

    # 6. BLOCKED short-circuit
    if wick_data is None or wick_failed:
        failure_text = ""
        if wick_failed:
            failure_text = "(listed in Tool Failures)"
        elif wick_data is None:
            failure_text = "(no support table found in wick section)"
        output = build_blocked_output(header, portfolio_data, failure_text)
        OUTPUT_PATH.write_text(output, encoding="utf-8")
        size_kb = len(output.encode("utf-8")) / 1024
        print(f"Wick status: BLOCKED")
        print(f"Output: {OUTPUT_PATH.name} ({size_kb:.1f} KB)")
        return

    # 7. Build identity table
    support_rows = wick_data["support_table"]
    identity_table, identity_warnings = build_identity_table(support_rows)

    # 8. Build bullet plan
    active_filled, reserve_filled = (0, 0)
    if position and position.get("shares", 0) > 0:
        active_filled, reserve_filled = parse_bullets_used(position.get("bullets_used"))

    bullet_plan_rows = wick_data.get("bullet_plan_table", [])
    fill_prices = portfolio_data.get("fill_prices", [])
    bullet_plan = build_bullet_plan(bullet_plan_rows, support_rows, position, active_filled, reserve_filled,
                                    fill_prices=fill_prices, status=header["status"])

    # 9. Detect warnings
    capital = portfolio_data["capital"]
    all_warnings = detect_warnings(support_rows, bullet_plan_rows, current_price, capital)

    # 10. Compute projected averages
    projected_rows = compute_projected_averages(
        position, bullet_plan,
        bullet_plan.get("active_filled_indices", set()),
        bullet_plan.get("reserve_filled_indices", set()),
    )

    # 11. Build and write output
    output = build_output(header, wick_data, portfolio_data, identity_table, identity_warnings,
                          bullet_plan, all_warnings, projected_rows)
    OUTPUT_PATH.write_text(output, encoding="utf-8")
    size_kb = len(output.encode("utf-8")) / 1024

    # 12. Print summary
    print(f"Wick status: OK")
    print(f"Active bullets: {bullet_plan['active_count']}, Reserve bullets: {bullet_plan['reserve_count']}")
    print(f"Output: {OUTPUT_PATH.name} ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
