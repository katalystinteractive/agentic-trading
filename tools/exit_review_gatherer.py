#!/usr/bin/env python3
"""Exit Review Gatherer — Phase 1 orchestrator for the exit-review workflow.

Replaces the LLM gatherer's sequential tool-running with Python subprocess
orchestration. Runs portfolio_status.py, earnings_analyzer.py,
technical_scanner.py, and short_interest.py for all active positions.
Reads identity/news context. Assembles exit-review-raw.md.

Usage: python3 tools/exit_review_gatherer.py
"""

import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = PROJECT_ROOT / "portfolio.json"
TOOLS_DIR = PROJECT_ROOT / "tools"
TICKERS_DIR = PROJECT_ROOT / "tickers"
OUTPUT_PATH = PROJECT_ROOT / "exit-review-raw.md"

# Time stop thresholds (calendar days) — must match strategy.md
TIME_STOP_EXCEEDED_DAYS = 60
TIME_STOP_APPROACHING_DAYS = 45

# Default capital settings
DEFAULT_BULLETS_MAX = 5

# Identity context: first N lines
IDENTITY_LINE_LIMIT = 40

# News context: normal vs recovery
NEWS_LINES_NORMAL = 15
NEWS_LINES_RECOVERY = 30


# ---------------------------------------------------------------------------
# Reusable helpers (same patterns as morning_gatherer.py)
# ---------------------------------------------------------------------------

def run_tool(tool_name, args=None, timeout=60):
    """Run a Python tool and capture stdout. Returns (stdout, error_msg)."""
    cmd = ["python3", str(TOOLS_DIR / tool_name)]
    if args:
        cmd.extend(args)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            cwd=str(PROJECT_ROOT)
        )
        if result.returncode != 0:
            err = result.stderr.strip() or f"Exit code {result.returncode}"
            return result.stdout.strip(), f"*Error running {tool_name}: {err}*"
        return result.stdout.strip(), None
    except subprocess.TimeoutExpired:
        return "", f"*Error: {tool_name} timed out after {timeout}s*"
    except Exception as e:
        return "", f"*Error running {tool_name}: {e}*"


def format_price(price):
    """Format price with $ and 2 decimals."""
    if price is None:
        return "N/A"
    return f"${price:.2f}"


def compute_days_held(entry_date_str):
    """Compute days held from entry_date using today (real-time).
    Returns (days_int, display_str, is_pre_strategy)."""
    today = date.today()
    if entry_date_str.startswith("pre-"):
        return None, f">{TIME_STOP_EXCEEDED_DAYS} days (pre-strategy)", True
    try:
        entry = datetime.strptime(entry_date_str, "%Y-%m-%d").date()
        days = (today - entry).days
        return days, str(days), False
    except ValueError:
        return None, "Unknown", False


def compute_time_stop(days_held, is_pre_strategy):
    """Compute time stop status."""
    if is_pre_strategy:
        return "EXCEEDED (pre-strategy)"
    if days_held is None:
        return "Unknown"
    if days_held > TIME_STOP_EXCEEDED_DAYS:
        return "EXCEEDED"
    if days_held >= TIME_STOP_APPROACHING_DAYS:
        return "APPROACHING"
    return "WITHIN"


def compute_bullets_used(bullets_raw, note, capital):
    """Compute bullets_used display string."""
    max_bullets = capital.get("active_bullets_max", DEFAULT_BULLETS_MAX)

    if isinstance(bullets_raw, int):
        result = f"{bullets_raw}/{max_bullets}"
    elif isinstance(bullets_raw, str):
        match = re.match(r"(\d+)", bullets_raw)
        if match:
            n = match.group(1)
            result = f"{n}/{max_bullets}"
            if "pre-strategy" in bullets_raw:
                result += " (pre-strategy)"
        else:
            result = f"?/{max_bullets}"
    else:
        result = f"?/{max_bullets}"

    if note:
        if "exhausted" in note.lower() or "active pool exhausted" in note.lower():
            result += ", pool exhausted"
        remaining = re.search(r'~?\$(\d+)\s*remaining', note)
        if remaining:
            result += f", ~${remaining.group(1)} remaining"

    return result


def extract_days_to_earnings(earnings_output):
    """Extract 'Days Until' from earnings_analyzer output. Returns int or None."""
    for line in earnings_output.split("\n"):
        if "Days Until" in line and "|" in line:
            parts = [p.strip() for p in line.split("|")]
            for p in parts:
                try:
                    return int(p)
                except ValueError:
                    continue
    return None


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

def load_portfolio():
    """Load portfolio.json. Exit with error if missing/malformed."""
    try:
        with open(PORTFOLIO_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"*Error: {PORTFOLIO_PATH} not found*", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"*Error: {PORTFOLIO_PATH} malformed JSON: {e}*", file=sys.stderr)
        sys.exit(1)


def get_active_positions(portfolio):
    """Filter positions with shares > 0, sorted alphabetically."""
    positions = portfolio.get("positions", {})
    active = []
    for ticker, pos in sorted(positions.items()):
        shares = pos.get("shares", 0)
        if isinstance(shares, (int, float)) and shares > 0:
            active.append(ticker)
    return active


# ---------------------------------------------------------------------------
# Portfolio Status
# ---------------------------------------------------------------------------

def run_portfolio_status():
    """Run portfolio_status.py, capture stdout."""
    return run_tool("portfolio_status.py", timeout=120)


def get_current_prices(portfolio_status_output):
    """Parse current prices from portfolio_status.py raw stdout.
    Only parses the Active Positions table — stops at the next section header
    to avoid overwriting with Watchlist Day High values.

    Note: single-phase section detection (just '# Active Positions') because
    this parses raw portfolio_status.py stdout, NOT the wrapped markdown in
    morning-tools-raw.md. See morning_compiler.parse_active_positions() for
    the two-phase version that navigates the '## Portfolio Status Output' wrapper."""
    prices = {}
    in_active = False
    for line in portfolio_status_output.split("\n"):
        stripped = line.strip()
        if "Active Positions" in stripped and stripped.startswith("#"):
            in_active = True
            continue
        if in_active and stripped.startswith("#"):
            break
        if in_active and stripped.startswith("|") and not stripped.startswith("| Ticker") and not stripped.startswith("| :"):
            parts = [p.strip() for p in stripped.split("|")]
            if len(parts) >= 5:
                ticker = parts[1].strip()
                price_str = parts[4].strip().replace("$", "").replace(",", "")
                try:
                    prices[ticker] = float(price_str)
                except ValueError:
                    pass
    return prices


# ---------------------------------------------------------------------------
# Per-Ticker Tools
# ---------------------------------------------------------------------------

EXIT_TOOLS = ["earnings_analyzer.py", "technical_scanner.py", "short_interest.py"]


def run_exit_tools(ticker):
    """Run earnings, technical, short interest tools for one ticker.
    Returns dict of {tool: (output, error)}."""
    results = {}
    for tool_name in EXIT_TOOLS:
        output, error = run_tool(tool_name, [ticker])
        results[tool_name] = (output, error)
    return results


def run_all_tickers(active_tickers):
    """Run exit tools for all tickers using ThreadPoolExecutor.
    Returns dict of {ticker: {tool: (output, error)}}."""
    all_results = {}
    all_errors = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {}
        for ticker in active_tickers:
            futures[executor.submit(run_exit_tools, ticker)] = ticker

        for future in as_completed(futures):
            ticker = futures[future]
            try:
                results = future.result()
                all_results[ticker] = results
                errors = [e for _, (_, e) in results.items() if e]
                all_errors.extend(errors)
                status = "OK" if not errors else f"{len(errors)} errors"
                print(f"  {ticker}: {status}")
            except Exception as e:
                all_results[ticker] = {t: ("", f"*Error: {e}*") for t in EXIT_TOOLS}
                all_errors.append(f"*Error running tools for {ticker}: {e}*")
                print(f"  {ticker}: EXCEPTION")

    return all_results, all_errors


# ---------------------------------------------------------------------------
# Identity & News Context
# ---------------------------------------------------------------------------

def read_identity_context(ticker):
    """Read first N lines of identity.md for cycle, status, levels."""
    filepath = TICKERS_DIR / ticker / "identity.md"
    if not filepath.exists():
        return "No cached identity"
    try:
        text = filepath.read_text(encoding="utf-8")
        lines = text.splitlines()[:IDENTITY_LINE_LIMIT]
        return "\n".join(lines)
    except Exception:
        return "*Error reading identity.md*"


def read_news_context(ticker, is_recovery):
    """Read first N lines of news.md. Recovery positions get more lines."""
    filepath = TICKERS_DIR / ticker / "news.md"
    if not filepath.exists():
        return "No cached news"
    limit = NEWS_LINES_RECOVERY if is_recovery else NEWS_LINES_NORMAL
    try:
        text = filepath.read_text(encoding="utf-8")
        lines = text.splitlines()[:limit]
        return "\n".join(lines)
    except Exception:
        return "*Error reading news.md*"


def is_recovery_position(pos):
    """Check if a position is recovery/pre-strategy from the note field."""
    note = pos.get("note", "")
    return any(kw in note.lower() for kw in ["recovery", "underwater", "pre-strategy"])


# ---------------------------------------------------------------------------
# Position Summary Table
# ---------------------------------------------------------------------------

def build_position_summary_table(active_tickers, portfolio, prices):
    """Build the 11-column Position Summary table rows."""
    positions = portfolio.get("positions", {})
    capital = portfolio.get("capital", {})
    rows = []

    for ticker in active_tickers:
        pos = positions[ticker]
        shares = pos["shares"]
        avg_cost = pos["avg_cost"]
        current = prices.get(ticker)

        if current:
            pl_pct = (current - avg_cost) / avg_cost * 100
            pl_str = f"+{pl_pct:.1f}%" if pl_pct >= 0 else f"{pl_pct:.1f}%"
        else:
            pl_str = "N/A"

        entry_date = pos.get("entry_date", "Unknown")
        days_held, days_display, is_pre = compute_days_held(entry_date)
        time_stop = compute_time_stop(days_held, is_pre)
        bullets = compute_bullets_used(pos.get("bullets_used", 0), pos.get("note", ""), capital)

        target = pos.get("target_exit")
        if target and current:
            dist = (target - current) / current * 100
            target_str = f"{format_price(target)} ({dist:+.1f}% to target)"
        elif target:
            target_str = format_price(target)
        else:
            target_str = "No target (recovery)"

        note = pos.get("note", "")
        if note:
            note_short = note.split(".")[0]
            if "Pre-strategy" in note_short:
                note_short = note_short.replace("Pre-strategy position, ", "Pre-strategy, ")
        else:
            note_short = "—"

        rows.append(
            f"| {ticker} | {shares} | ${avg_cost:.2f} | {format_price(current)} "
            f"| {pl_str} | {entry_date} | {days_display} | {time_stop} "
            f"| {bullets} | {target_str} | {note_short} |"
        )

    return rows


# ---------------------------------------------------------------------------
# Per-Ticker Sections
# ---------------------------------------------------------------------------

def build_per_ticker_sections(active_tickers, portfolio, tool_results, now_str):
    """Build per-ticker exit data sections."""
    positions = portfolio.get("positions", {})
    parts = []

    for ticker in active_tickers:
        pos = positions[ticker]
        results = tool_results.get(ticker, {})
        recovery = is_recovery_position(pos)

        parts.append(f"### {ticker}")
        parts.append("")

        # Earnings
        parts.append("#### Earnings")
        parts.append(f"*Generated: {now_str}*")
        out, err = results.get("earnings_analyzer.py", ("", None))
        parts.append(out if out else (err or "*No data*"))
        parts.append("")

        # Technical Signals
        parts.append("#### Technical Signals")
        out, err = results.get("technical_scanner.py", ("", None))
        parts.append(out if out else (err or "*No data*"))
        parts.append("")

        # Short Interest
        parts.append("#### Short Interest")
        out, err = results.get("short_interest.py", ("", None))
        parts.append(out if out else (err or "*No data*"))
        parts.append("")

        # Identity Context
        parts.append("#### Identity Context")
        identity = read_identity_context(ticker)
        parts.append(identity)
        parts.append("")

        # Recent News
        parts.append("#### Recent News")
        news = read_news_context(ticker, recovery)
        parts.append(news)

        parts.append("")
        parts.append("---")
        parts.append("")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def assemble_raw(today_str, now_str, position_summary_rows, portfolio_status_output,
                 per_ticker_sections, all_errors):
    """Assemble the complete exit-review-raw.md."""
    parts = []

    # Title
    parts.append(f"# Exit Review Raw Data — {today_str}")
    parts.append("")

    # Position Summary
    parts.append("## Position Summary")
    parts.append("")
    parts.append("| Ticker | Shares | Avg Cost | Current Price | P/L % | Entry Date "
                 "| Days Held | Time Stop Status | Bullets Used | Target Exit | Note |")
    parts.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for row in position_summary_rows:
        parts.append(row)
    parts.append("")
    parts.append("")
    parts.append("---")
    parts.append("")

    # Portfolio Status
    parts.append("## Portfolio Status")
    parts.append("")
    if portfolio_status_output:
        parts.append(portfolio_status_output)
    else:
        parts.append("*Error: portfolio_status.py failed to produce output.*")
    parts.append("")
    parts.append("")
    parts.append("---")
    parts.append("")

    # Per-Ticker Exit Data
    parts.append("## Per-Ticker Exit Data")
    parts.append("")
    parts.append(per_ticker_sections)

    # Errors section (if any)
    if all_errors:
        parts.append("## Tool Errors")
        parts.append("")
        for err in all_errors:
            parts.append(f"- {err}")
        parts.append("")

    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    t0 = time.monotonic()
    today_str = date.today().isoformat()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    print(f"Exit Review Gatherer — {today_str}")
    print("=" * 50)

    # Load portfolio
    portfolio = load_portfolio()
    active_tickers = get_active_positions(portfolio)
    print(f"Active positions: {len(active_tickers)} ({', '.join(active_tickers)})")

    if not active_tickers:
        print("No active positions to review.")
        OUTPUT_PATH.write_text(
            f"# Exit Review Raw Data — {today_str}\n\nNo active positions to review.\n",
            encoding="utf-8"
        )
        return

    all_errors = []

    # Step 1: Run portfolio_status.py
    print("\n[1/3] Running portfolio_status.py...")
    ps_output, ps_err = run_portfolio_status()
    if ps_err:
        all_errors.append(ps_err)
        print(f"  {ps_err}")
    else:
        print("  OK")

    # Parse current prices
    prices = get_current_prices(ps_output)

    # Step 2: Run per-ticker exit tools in parallel
    print(f"\n[2/3] Running exit tools for {len(active_tickers)} positions (4 workers)...")
    tool_results, tool_errors = run_all_tickers(active_tickers)
    all_errors.extend(tool_errors)

    # Step 3: Build output
    print("\n[3/3] Assembling exit-review-raw.md...")

    # Position Summary table
    summary_rows = build_position_summary_table(active_tickers, portfolio, prices)

    # Per-ticker sections
    per_ticker = build_per_ticker_sections(active_tickers, portfolio, tool_results, now_str)

    # Assemble
    content = assemble_raw(today_str, now_str, summary_rows, ps_output, per_ticker, all_errors)
    OUTPUT_PATH.write_text(content, encoding="utf-8")

    # Summary
    elapsed = time.monotonic() - t0
    size_kb = OUTPUT_PATH.stat().st_size / 1024

    print(f"\n{'=' * 50}")
    print(f"Output: exit-review-raw.md ({size_kb:.1f} KB)")
    print(f"Active positions: {len(active_tickers)}")
    print(f"Tool errors: {len(all_errors)}")
    print(f"Elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
