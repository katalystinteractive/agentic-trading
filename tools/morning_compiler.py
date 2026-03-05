#!/usr/bin/env python3
"""
Morning Compiler — Mechanical file concatenation tool.

Reads morning-tools-raw.md (from gather phase) and all cached ticker files,
merges them into morning-briefing-raw.md (full archive) and
morning-briefing-condensed.md (analyst-friendly, <200KB).

The condensed version strips verbose sections that exceed the LLM context
window: news headlines (keep only sentiment summary), wick analysis per-level
details (keep only summary table), and trims earnings/revenue history.

Usage: python3 tools/morning_compiler.py
"""

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOOLS_RAW = PROJECT_ROOT / "morning-tools-raw.md"
PORTFOLIO = PROJECT_ROOT / "portfolio.json"
TICKERS_DIR = PROJECT_ROOT / "tickers"
OUTPUT = PROJECT_ROOT / "morning-briefing-raw.md"
CONDENSED = PROJECT_ROOT / "morning-briefing-condensed.md"

# Files to read for active positions (shares > 0)
ACTIVE_FILES = ["identity.md", "memory.md", "institutional.md", "wick_analysis.md"]
ACTIVE_LABELS = {
    "identity.md": "Identity Context",
    "memory.md": "Memory Context",
    "institutional.md": "Institutional Context",
    "wick_analysis.md": "Wick Analysis",
}

# Files to read for watchlist tickers (shares = 0, has pending BUY orders)
WATCHLIST_FILES = ["identity.md", "wick_analysis.md"]
WATCHLIST_LABELS = {
    "identity.md": "Identity Context",
    "wick_analysis.md": "Wick Analysis",
}


def load_portfolio():
    """Load portfolio.json and classify tickers."""
    with open(PORTFOLIO) as f:
        data = json.load(f)

    active = []
    watchlist_with_orders = []
    scouting = []

    for ticker, pos in data.get("positions", {}).items():
        shares = pos.get("shares", 0)
        if isinstance(shares, str):
            shares = int(shares) if shares.isdigit() else 0
        if shares > 0:
            active.append(ticker)

    # Check watchlist for pending BUY orders
    for ticker in data.get("watchlist", []):
        if ticker in [t for t in active]:
            continue  # already an active position
        has_buy = False
        for order in data.get("pending_orders", {}).get(ticker, []):
            if order.get("type", "").upper() == "BUY":
                has_buy = True
                break
        if has_buy:
            watchlist_with_orders.append(ticker)
        else:
            scouting.append(ticker)

    return active, watchlist_with_orders, scouting


def read_cached_file(ticker, filename):
    """Read a cached ticker file, return content or None."""
    path = TICKERS_DIR / ticker / filename
    if path.exists():
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return None
    return None


def find_section_boundaries(lines, section_header):
    """Find start index of a ## section header."""
    for i, line in enumerate(lines):
        if line.strip() == section_header:
            return i
    return None


def find_ticker_sections(lines, start_idx, end_idx):
    """Find all ### TICKER sections between start_idx and end_idx.
    Returns list of (ticker, section_start, section_end) tuples.
    section_end is the line BEFORE the next ### or ## header.
    """
    sections = []
    current_ticker = None
    current_start = None

    for i in range(start_idx, end_idx):
        line = lines[i].strip()
        if line.startswith("### ") and not line.startswith("### Next") and not line.startswith("### Earnings") and not line.startswith("### Short") and not line.startswith("### Squeeze") and not line.startswith("### Trend") and not line.startswith("### Momentum") and not line.startswith("### Volatility") and not line.startswith("### Key ") and not line.startswith("### Signal") and not line.startswith("### Revenue") and not line.startswith("### Headlines") and not line.startswith("### Sentiment") and not line.startswith("### Detected") and not line.startswith("### Context"):
            # Check if this looks like a ticker header (all caps, short)
            potential_ticker = line[4:].strip()
            if potential_ticker and re.match(r'^[A-Z]{1,6}$', potential_ticker):
                if current_ticker is not None:
                    sections.append((current_ticker, current_start, i))
                current_ticker = potential_ticker
                current_start = i

    if current_ticker is not None:
        sections.append((current_ticker, current_start, end_idx))

    return sections


def build_cached_section(ticker, file_list, label_map):
    """Build the cached file sections for a ticker (full version for raw output)."""
    parts = []
    files_read = 0
    missing = []

    for filename in file_list:
        label = label_map[filename]
        content = read_cached_file(ticker, filename)
        parts.append(f"\n#### {label}\n")
        if content is not None:
            parts.append(content.rstrip() + "\n")
            files_read += 1
        else:
            parts.append(f'No cached {label.lower()}\n')
            missing.append(f"{ticker}/{filename}")

    return "\n".join(parts), files_read, missing


def extract_identity_summary(content):
    """Extract key fields from identity.md: cycle, key levels, status, target."""
    if not content:
        return "No identity data"
    lines = content.split("\n")
    summary_parts = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        # Capture cycle
        if "**Cycle:**" in stripped or "**cycle:**" in stripped.lower():
            summary_parts.append(stripped)
        # Capture target/resistance
        elif "Resistance:" in stripped or "Target" in stripped:
            summary_parts.append(stripped)
        # Capture status
        elif "**Status:**" in stripped:
            summary_parts.append(stripped)
        # Capture sector if present
        elif stripped.startswith("**Sector:") or stripped.startswith("* **Sector:"):
            summary_parts.append(stripped)
    return "\n".join(summary_parts) if summary_parts else "No key fields found"


def extract_memory_summary(content):
    """Extract last 3 trade fills and last observation from memory.md."""
    if not content:
        return "No trade history"
    lines = content.split("\n")
    trades = []
    observations = []
    in_trade_log = False
    in_observations = False

    for line in lines:
        stripped = line.strip()
        if "## Trade Log" in stripped:
            in_trade_log = True
            in_observations = False
            continue
        elif "## Observations" in stripped:
            in_trade_log = False
            in_observations = True
            continue
        elif stripped.startswith("## "):
            in_trade_log = False
            in_observations = False
            continue

        if in_trade_log and stripped.startswith("- **"):
            trades.append(stripped)
        elif in_observations and stripped.startswith("- **"):
            observations.append(stripped)

    parts = []
    if trades:
        # Keep last 3 trades
        parts.append("**Recent Trades:**")
        for t in trades[-3:]:
            parts.append(t)
    else:
        parts.append("**Recent Trades:** none")

    if observations:
        # Keep last 2 observations
        parts.append("**Latest Observations:**")
        for o in observations[-2:]:
            parts.append(o)

    return "\n".join(parts)


def extract_wick_bullet_plan(content):
    """Extract only the Suggested Bullet Plan table from wick_analysis.md."""
    if not content:
        return "No wick analysis"
    lines = content.split("\n")
    result = []
    in_bullet_plan = False
    # Also grab the header stats line
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("**Monthly Swing:"):
            result.append(stripped)
        elif stripped.startswith("**Current Price:"):
            result.append(stripped)
        elif "### Suggested Bullet Plan" in stripped:
            in_bullet_plan = True
            result.append(stripped)
            continue
        elif in_bullet_plan:
            if stripped.startswith("### ") or stripped.startswith("## "):
                break
            if stripped:  # skip blanks
                result.append(stripped)

    return "\n".join(result) if result else "No bullet plan found"


def extract_institutional_summary(content):
    """Extract 1-2 line summary from institutional.md."""
    if not content:
        return "No institutional data"
    lines = content.split("\n")
    # Look for summary/key lines
    summary_parts = []
    for line in lines:
        stripped = line.strip()
        if any(kw in stripped.lower() for kw in
               ["holders increasing", "holders decreasing", "insider",
                "accumulation", "distribution", "top holder", "avg change"]):
            summary_parts.append(stripped)
            if len(summary_parts) >= 3:
                break
    return "\n".join(summary_parts) if summary_parts else "See morning-briefing-raw.md for details"


def build_condensed_cached_section(ticker, file_list, label_map):
    """Build compact cached data extracts for condensed output (~1-2 KB per ticker)."""
    parts = []
    files_read = 0
    missing = []

    for filename in file_list:
        label = label_map[filename]
        content = read_cached_file(ticker, filename)

        if content is None:
            missing.append(f"{ticker}/{filename}")
            continue

        files_read += 1

        if filename == "identity.md":
            summary = extract_identity_summary(content)
            if summary != "No key fields found":
                parts.append(f"\n**Identity:** {summary}")
        elif filename == "memory.md":
            summary = extract_memory_summary(content)
            parts.append(f"\n{summary}")
        elif filename == "wick_analysis.md":
            summary = extract_wick_bullet_plan(content)
            parts.append(f"\n#### Wick Bullet Plan\n{summary}")
        elif filename == "institutional.md":
            summary = extract_institutional_summary(content)
            if summary != "No institutional data":
                parts.append(f"\n**Institutional:** {summary}")

    return "\n".join(parts), files_read, missing


def parse_active_positions(lines):
    """Extract per-ticker data from Active Positions table in Portfolio Status Output.
    Returns dict[ticker] → {"shares": str, "avg_cost": str, "current": str,
    "pl_dollar": str, "pl_pct": str}."""
    snapshots = {}
    in_portfolio_status = False
    in_active_positions = False
    header_validated = False
    for line in lines:
        stripped = line.strip()
        # Phase 1: enter Portfolio Status Output section
        if stripped == "## Portfolio Status Output":
            in_portfolio_status = True
            continue
        if not in_portfolio_status:
            continue
        # Phase 2: find Active Positions sub-header within Portfolio Status
        # Entry guard: set flag when we encounter the "Active Positions" header.
        # The break on line 317 won't execute until in_active_positions is True,
        # so this condition must check the guard before other branches.
        if not in_active_positions and "Active Positions" in stripped and stripped.startswith("#"):
            in_active_positions = True
            continue
        if in_active_positions and stripped.startswith("#"):
            break  # Hit next sub-section (Pending Orders, etc.)
        if not in_active_positions:
            continue
        # Header validation
        if stripped.startswith("| Ticker"):
            if "Avg Cost" in stripped and "Current" in stripped and "P/L" in stripped:
                header_validated = True
            else:
                print("*Warning: Active Positions header format unexpected, skipping snapshot extraction*")
                return {}
            continue
        if stripped.startswith("| :"):
            continue
        # Data rows
        if header_validated and stripped.startswith("|"):
            parts = [p.strip() for p in stripped.split("|")]
            if len(parts) >= 9:
                shares = parts[2].strip()
                if shares == "0":
                    continue  # Skip zero-share positions
                ticker = parts[1].strip()
                snapshots[ticker] = {
                    "shares": shares,
                    "avg_cost": parts[3].strip(),
                    "current": parts[4].strip(),
                    "pl_dollar": parts[7].strip(),
                    "pl_pct": parts[8].strip(),
                }
    if not header_validated:
        print("*Warning: Active Positions table not found in Portfolio Status Output*")
    return snapshots


def condense_tool_output(text):
    """Strip verbose sections from tool output for analyst-friendly condensed file.

    Removes:
    - News headline rows (keeps Sentiment Summary + Detected Catalysts)
    - News article body text (keeps title, source/sentiment line, catalysts)
    - Earnings history beyond 2 most recent quarters
    - Revenue trend beyond 2 most recent quarters
    """
    lines = text.split("\n")
    output = []
    skip_until_next_header = False
    in_article_body = False
    in_table_trim = None  # "earnings" or "revenue" when trimming
    table_data_rows = 0

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # --- Skip news headlines table ---
        if stripped.startswith("### Headlines"):
            skip_until_next_header = True
            output.append("")
            output.append("*[Headlines omitted — see morning-briefing-raw.md]*")
            output.append("")
            i += 1
            continue

        if skip_until_next_header:
            if stripped.startswith("### ") or stripped.startswith("## ") or stripped.startswith("#### "):
                skip_until_next_header = False
                # Fall through to process this line normally
            else:
                i += 1
                continue

        # --- Strip news article body text (keep title + source + catalysts) ---
        # Article headers look like: #### Article Title
        # Followed by: *Source: ... | Date: ... | Sentiment: ...*
        # Then blockquote paragraphs (> ...)
        # Then **Catalysts:** line
        if in_article_body:
            if stripped.startswith(">"):
                # Skip blockquote body text
                i += 1
                continue
            elif stripped == "":
                # Skip blank lines between blockquote paragraphs
                # Peek ahead: if next non-blank line is also > or empty, skip
                i += 1
                continue
            elif stripped.startswith("**Catalysts:"):
                # Keep catalysts line, end article body mode
                output.append(line)
                in_article_body = False
                i += 1
                continue
            elif stripped.startswith("####") or stripped.startswith("###") or stripped.startswith("##"):
                # Next section — end article body mode, process this line
                in_article_body = False
                # Fall through
            else:
                # Any other content in article — skip
                i += 1
                continue

        # Detect start of a news article (#### Title after ### Sentiment Summary)
        if stripped.startswith("#### ") and not stripped.startswith("#### Earnings") and \
           not stripped.startswith("#### Technical") and not stripped.startswith("#### Short") and \
           not stripped.startswith("#### News") and not stripped.startswith("#### Identity") and \
           not stripped.startswith("#### Memory") and not stripped.startswith("#### Institutional") and \
           not stripped.startswith("#### Wick"):
            # Check if next line is a source/sentiment line
            if i + 1 < len(lines) and lines[i + 1].strip().startswith("*Source:"):
                # This is a news article — keep title and source line, enter body mode
                output.append(line)  # Keep title
                i += 1
                output.append(lines[i])  # Keep source/sentiment line
                in_article_body = True
                i += 1
                continue

        # --- Trim earnings history to 2 most recent quarters ---
        if stripped == "### Earnings History":
            output.append(line)
            in_table_trim = "earnings"
            table_data_rows = 0
            i += 1
            continue

        # --- Trim revenue trend to 2 most recent quarters ---
        if stripped == "### Revenue Trend":
            output.append(line)
            in_table_trim = "revenue"
            table_data_rows = 0
            i += 1
            continue

        if in_table_trim:
            if stripped.startswith("|"):
                if stripped.startswith("| :") or stripped.startswith("| Quarter") or stripped.startswith("| Period"):
                    output.append(line)
                else:
                    table_data_rows += 1
                    if table_data_rows <= 2:
                        output.append(line)
                    elif table_data_rows == 3:
                        output.append("| ... | *[trimmed — see morning-briefing-raw.md]* | | | | | |")
            elif stripped == "" or stripped == "---":
                in_table_trim = None
                table_data_rows = 0
                output.append(line)
            else:
                output.append(line)
            i += 1
            continue

        # --- Default: keep the line ---
        output.append(line)
        i += 1

    return "\n".join(output)


def main():
    # Validate inputs exist
    if not TOOLS_RAW.exists():
        print(f"*Error: {TOOLS_RAW} not found. Run the gather phase first.*")
        sys.exit(1)
    if not PORTFOLIO.exists():
        print(f"*Error: {PORTFOLIO} not found.*")
        sys.exit(1)

    # Load portfolio data
    active_tickers, watchlist_tickers, scouting_tickers = load_portfolio()
    print(f"Active positions: {len(active_tickers)} ({', '.join(active_tickers)})")
    print(f"Watchlist with orders: {len(watchlist_tickers)} ({', '.join(watchlist_tickers)})")
    print(f"Scouting (no orders): {len(scouting_tickers)} ({', '.join(scouting_tickers)})")

    # Read the tools raw file
    raw_content = TOOLS_RAW.read_text(encoding="utf-8")
    lines = raw_content.split("\n")

    # Parse Active Positions table for per-ticker snapshots
    position_snapshots = parse_active_positions(lines)
    if position_snapshots:
        print(f"Position snapshots parsed: {len(position_snapshots)} ({', '.join(position_snapshots)})")

    # Find key section boundaries
    active_section_start = find_section_boundaries(lines, "## Per-Ticker Active Tool Outputs")
    watchlist_section_start = find_section_boundaries(lines, "## Per-Ticker Watchlist Tool Outputs")
    scouting_section_start = find_section_boundaries(lines, "## Scouting Tickers (No Orders)")
    crosscheck_start = find_section_boundaries(lines, "## Cross-Check Summary")

    if active_section_start is None:
        print("*Error: Could not find '## Per-Ticker Active Tool Outputs' section.*")
        sys.exit(1)

    # Determine section end boundaries
    active_section_end = watchlist_section_start or scouting_section_start or crosscheck_start or len(lines)
    watchlist_section_end = scouting_section_start or crosscheck_start or len(lines) if watchlist_section_start else active_section_end

    # Parse active ticker sections
    active_sections = find_ticker_sections(lines, active_section_start, active_section_end)
    print(f"\nActive ticker sections found: {len(active_sections)} ({', '.join(t for t, _, _ in active_sections)})")

    # Parse watchlist ticker sections
    watchlist_sections = []
    if watchlist_section_start:
        watchlist_sections = find_ticker_sections(lines, watchlist_section_start, watchlist_section_end)
        print(f"Watchlist ticker sections found: {len(watchlist_sections)} ({', '.join(t for t, _, _ in watchlist_sections)})")

    # Build the merged output
    output_parts = []
    total_active_compiled = 0
    total_watchlist_compiled = 0
    total_files_read = 0
    all_missing = []
    files_by_type = {"identity": 0, "memory": 0, "wick_analysis": 0, "institutional": 0}

    # --- Header sections (everything before Per-Ticker Active Tool Outputs) ---
    # Replace title line
    header_lines = lines[:active_section_start]
    header_text = "\n".join(header_lines)
    # Update the title from "Morning Tools Raw Data" to "Morning Briefing Raw Data"
    header_text = header_text.replace("# Morning Tools Raw Data", "# Morning Briefing Raw Data", 1)
    output_parts.append(header_text)

    # --- Active position sections with cached data injected ---
    output_parts.append("\n## Per-Ticker Active Position Data\n")

    for ticker, sec_start, sec_end in active_sections:
        # Get the tool output lines for this ticker
        tool_lines = "\n".join(lines[sec_start:sec_end]).rstrip()
        output_parts.append(tool_lines)

        # Inject cached files
        cached_text, n_read, missing = build_cached_section(ticker, ACTIVE_FILES, ACTIVE_LABELS)
        output_parts.append(cached_text)
        total_active_compiled += 1
        total_files_read += n_read
        all_missing.extend(missing)

        # Track by type
        for f in ACTIVE_FILES:
            key = f.replace(".md", "")
            if read_cached_file(ticker, f) is not None:
                files_by_type[key] = files_by_type.get(key, 0) + 1

        output_parts.append("\n---\n")

    # --- Watchlist sections with cached data injected ---
    if watchlist_section_start:
        output_parts.append("\n## Watchlist Ticker Data\n")

        for ticker, sec_start, sec_end in watchlist_sections:
            tool_lines = "\n".join(lines[sec_start:sec_end]).rstrip()
            output_parts.append(tool_lines)

            cached_text, n_read, missing = build_cached_section(ticker, WATCHLIST_FILES, WATCHLIST_LABELS)
            output_parts.append(cached_text)
            total_watchlist_compiled += 1
            total_files_read += n_read
            all_missing.extend(missing)

            for f in WATCHLIST_FILES:
                key = f.replace(".md", "")
                if read_cached_file(ticker, f) is not None:
                    files_by_type[key] = files_by_type.get(key, 0) + 1

            output_parts.append("\n---\n")

    # --- Footer sections (scouting, velocity, capital, cross-check) ---
    # Find the start of footer sections
    footer_start = scouting_section_start or crosscheck_start
    if footer_start and crosscheck_start:
        # Everything from scouting to just before cross-check
        footer_lines = "\n".join(lines[footer_start:crosscheck_start])
        output_parts.append(footer_lines)

        # Enhanced cross-check summary
        original_crosscheck = "\n".join(lines[crosscheck_start:])
        output_parts.append(original_crosscheck.rstrip())
        output_parts.append(f"\n- Cached files read for active positions: **{total_active_compiled}** tickers")
        output_parts.append(f"- Cached files read for watchlist tickers: **{total_watchlist_compiled}** tickers")
        output_parts.append(f"- Identity files: **{files_by_type.get('identity', 0)}**")
        output_parts.append(f"- Memory files: **{files_by_type.get('memory', 0)}**")
        output_parts.append(f"- Wick analysis files: **{files_by_type.get('wick_analysis', 0)}**")
        output_parts.append(f"- Institutional files: **{files_by_type.get('institutional', 0)}**")
        if all_missing:
            output_parts.append(f"- Missing files: {', '.join(all_missing)}")
        else:
            output_parts.append("- Missing files: none")
        output_parts.append("")
    elif footer_start:
        footer_lines = "\n".join(lines[footer_start:])
        output_parts.append(footer_lines)

    # Write output
    merged = "\n".join(output_parts)
    OUTPUT.write_text(merged, encoding="utf-8")

    # Summary
    size_kb = OUTPUT.stat().st_size / 1024
    print(f"\n--- Compilation Complete ---")
    print(f"Output: {OUTPUT} ({size_kb:.1f} KB)")
    print(f"Active positions compiled: {total_active_compiled}")
    print(f"Watchlist tickers compiled: {total_watchlist_compiled}")
    print(f"Cached files read: identity x{files_by_type.get('identity', 0)}, "
          f"memory x{files_by_type.get('memory', 0)}, "
          f"wick_analysis x{files_by_type.get('wick_analysis', 0)}, "
          f"institutional x{files_by_type.get('institutional', 0)}")
    if all_missing:
        print(f"Missing files: {', '.join(all_missing)}")
    else:
        print("Missing files: none")

    # Coverage check
    raw_active = {t for t, _, _ in active_sections}
    raw_watchlist = {t for t, _, _ in watchlist_sections}
    portfolio_active = set(active_tickers)
    portfolio_watchlist = set(watchlist_tickers)

    missing_active = portfolio_active - raw_active
    missing_watchlist = portfolio_watchlist - raw_watchlist

    if missing_active:
        print(f"\n*WARNING: Active tickers in portfolio.json missing from tools raw: {', '.join(missing_active)}*")
    if missing_watchlist:
        print(f"\n*WARNING: Watchlist tickers in portfolio.json missing from tools raw: {', '.join(missing_watchlist)}*")

    if not missing_active and not missing_watchlist:
        print("\nCoverage: COMPLETE — all tickers from portfolio.json present in output")

    # --- Generate condensed version for analyst ---
    # Built separately with compact extracts (not post-processed from raw)
    print("\n--- Generating Condensed Version ---")
    condensed_parts = []

    # Header (market context, portfolio status, derived fields) — condense tool output
    header_text_condensed = "\n".join(header_lines)
    header_text_condensed = header_text_condensed.replace(
        "# Morning Tools Raw Data", "# Morning Briefing Data (Condensed)", 1)
    condensed_parts.append(condense_tool_output(header_text_condensed))

    # Active positions — tool outputs (condensed) + compact cached extracts
    condensed_parts.append("\n## Per-Ticker Active Position Data\n")
    for ticker, sec_start, sec_end in active_sections:
        tool_text = "\n".join(lines[sec_start:sec_end]).rstrip()
        condensed_parts.append(condense_tool_output(tool_text))
        # Inject mechanically-computed position snapshot before cached files
        snapshot = position_snapshots.get(ticker)
        if snapshot:
            condensed_parts.append(
                f"\n**Position Snapshot:** {snapshot['shares']} shares @ {snapshot['avg_cost']}, "
                f"current {snapshot['current']}, P/L {snapshot['pl_pct']} ({snapshot['pl_dollar']})"
            )
        # Compact cached extracts instead of full files
        cached_text, _, _ = build_condensed_cached_section(
            ticker, ACTIVE_FILES, ACTIVE_LABELS)
        condensed_parts.append(cached_text)
        condensed_parts.append("\n---\n")

    # Watchlist tickers — tool outputs (condensed) + compact cached extracts
    if watchlist_section_start:
        condensed_parts.append("\n## Watchlist Ticker Data\n")
        for ticker, sec_start, sec_end in watchlist_sections:
            tool_text = "\n".join(lines[sec_start:sec_end]).rstrip()
            condensed_parts.append(condense_tool_output(tool_text))
            cached_text, _, _ = build_condensed_cached_section(
                ticker, WATCHLIST_FILES, WATCHLIST_LABELS)
            condensed_parts.append(cached_text)
            condensed_parts.append("\n---\n")

    # Footer (scouting, cross-check)
    if footer_start:
        footer_text = "\n".join(lines[footer_start:])
        condensed_parts.append(footer_text)

    condensed = "\n".join(condensed_parts)
    CONDENSED.write_text(condensed, encoding="utf-8")
    condensed_kb = CONDENSED.stat().st_size / 1024
    condensed_lines = len(condensed.split("\n"))
    print(f"Condensed: {CONDENSED} ({condensed_kb:.1f} KB, {condensed_lines} lines)")
    print(f"Reduction: {size_kb:.0f} KB → {condensed_kb:.0f} KB ({(1 - condensed_kb/size_kb)*100:.0f}% smaller)")
    print(f"Per-ticker avg: {condensed_kb / max(len(active_sections) + len(watchlist_sections), 1):.1f} KB")


if __name__ == "__main__":
    main()
