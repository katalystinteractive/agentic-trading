#!/usr/bin/env python3
"""
Deep Dive Collector — Runs all 8 analysis tools for a single ticker.

Replaces the LLM-based collector agent that ran tools sequentially with no
qualitative judgment. This script runs all tools as subprocesses in parallel,
reads portfolio context, and writes deep-dive-raw.md.

Usage: python3 tools/deep_dive_collector.py <TICKER>
"""

import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO = PROJECT_ROOT / "portfolio.json"
TOOLS_DIR = PROJECT_ROOT / "tools"
OUTPUT = PROJECT_ROOT / "deep-dive-raw.md"
TICKERS_DIR = PROJECT_ROOT / "tickers"

TOOL_SECTIONS = [
    ("wick_offset_analyzer.py", "1. Wick Offset Analysis"),
    ("verify_stock.py", "2. Stock Verification"),
    ("technical_scanner.py", "3. Technical Scanner"),
    ("earnings_analyzer.py", "4. Earnings Analysis"),
    ("news_sentiment.py", "5. News Sentiment"),
    ("short_interest.py", "6. Short Interest"),
    ("institutional_flow.py", "7. Institutional Flow"),
    ("volume_profile.py", "8. Volume Profile"),
]


def run_tool(tool_name, args=None, timeout=90):
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


def determine_status(ticker, portfolio):
    """Determine if ticker is EXISTING or NEW based on portfolio and file state."""
    positions = portfolio.get("positions", {})
    if ticker in positions and isinstance(positions[ticker].get("shares", 0), int) and positions[ticker]["shares"] > 0:
        return "EXISTING"

    pending_orders = portfolio.get("pending_orders", {})
    if ticker in pending_orders and len(pending_orders[ticker]) > 0:
        return "EXISTING"

    watchlist = portfolio.get("watchlist", [])
    if ticker in watchlist:
        return "EXISTING"

    if (TICKERS_DIR / ticker / "identity.md").exists():
        return "EXISTING"

    return "NEW"


def read_existing_context(ticker):
    """Read identity.md and memory.md for an existing ticker."""
    context = {"identity": None, "memory": None}
    identity_path = TICKERS_DIR / ticker / "identity.md"
    memory_path = TICKERS_DIR / ticker / "memory.md"

    if identity_path.exists():
        context["identity"] = identity_path.read_text(encoding="utf-8").strip()
    if memory_path.exists():
        context["memory"] = memory_path.read_text(encoding="utf-8").strip()

    return context


def get_portfolio_context(ticker, portfolio):
    """Extract portfolio context for the ticker."""
    lines = []
    positions = portfolio.get("positions", {})
    pending_orders = portfolio.get("pending_orders", {})

    if ticker in positions:
        pos = positions[ticker]
        shares = pos.get("shares", 0)
        if isinstance(shares, int) and shares > 0:
            lines.append(f"**Active position:** {shares} shares @ ${pos.get('avg_cost', 0):.2f} avg")
            lines.append(f"  - Entry date: {pos.get('entry_date', 'Unknown')}")
            target = pos.get("target_exit") or "Not set"
            if isinstance(target, (int, float)):
                target = f"${target:.2f}"
            lines.append(f"  - Target exit: {target}")
            lines.append(f"  - Bullets used: {str(pos.get('bullets_used', 'N/A'))}")
            note = pos.get("note", "")
            if note:
                lines.append(f"  - Note: {note}")

    if ticker in pending_orders and pending_orders[ticker]:
        orders = pending_orders[ticker]
        lines.append(f"**Pending orders:** {len(orders)}")
        for o in orders:
            note = o.get("note", "")
            note_suffix = f" — {note}" if note else ""
            lines.append(f"  - {o.get('type', '?')} {o.get('shares', '?')} @ ${o.get('price', 0):.2f}{note_suffix}")

    watchlist = portfolio.get("watchlist", [])
    if not lines:
        if ticker in watchlist:
            lines.append("On watchlist (no active position)")
        elif (TICKERS_DIR / ticker / "identity.md").exists():
            lines.append("Previously tracked (identity.md exists, no active position)")
        else:
            lines.append("Not in portfolio")

    return "\n".join(lines)


def run_all_tools(ticker):
    """Run all tools in parallel. Returns dict of {tool_name: (stdout, error_msg)}."""
    results = {}
    tools = [(name, [ticker]) for name, _ in TOOL_SECTIONS]

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {}
        for tool_name, args in tools:
            futures[executor.submit(run_tool, tool_name, args)] = tool_name
        for future in as_completed(futures):
            tool_name = futures[future]
            try:
                output, error = future.result()
                results[tool_name] = (output, error)
            except Exception as e:
                results[tool_name] = ("", f"*Error: {e}*")

    return results


def extract_current_price(tool_results):
    """Extract current price from wick_offset_analyzer.py stdout."""
    wick_output = tool_results.get("wick_offset_analyzer.py", ("", None))[0]
    if not wick_output:
        return None
    match = re.search(r'\*\*Current Price:\s*\$(\d+\.?\d*)\*\*', wick_output)
    return float(match.group(1)) if match else None


def build_output(ticker, status, existing_context, portfolio_context, tool_results, capital):
    """Assemble deep-dive-raw.md content."""
    today_str = date.today().isoformat()
    current_price = extract_current_price(tool_results)
    price_str = f"${current_price:.2f}" if current_price else "N/A (see tool outputs)"

    parts = []
    parts.append(f"# Deep Dive Raw Data — {ticker} — {today_str}\n")

    # Ticker Status
    parts.append("## Ticker Status")
    parts.append(f"- **Classification:** {status}")
    parts.append(f"- **Current price:** {price_str}")
    parts.append(f"- **Portfolio context:** {portfolio_context}")
    parts.append("")

    # Existing Context
    if status == "EXISTING":
        parts.append("## Existing Context\n")
        parts.append("### Current Identity")
        parts.append(existing_context.get("identity") or "No identity.md found")
        parts.append("")
        parts.append("### Current Memory")
        parts.append(existing_context.get("memory") or "No memory.md found")
        parts.append("")

    # Tool Outputs
    parts.append("## Tool Outputs\n")
    for tool_name, section_title in TOOL_SECTIONS:
        parts.append(f"### {section_title}")
        output, error = tool_results.get(tool_name, ("", None))
        if output and error:
            parts.append(f"*Note: tool exited with error (see Tool Failures section)*\n")
            parts.append(output)
        elif output:
            parts.append(output)
        elif error:
            parts.append(error)
        else:
            parts.append("*No output*")
        parts.append("")

    # Tool Failures
    failures = []
    for tool_name, _ in TOOL_SECTIONS:
        _, error = tool_results.get(tool_name, ("", None))
        if error:
            failures.append(f"- {tool_name}: {error}")

    parts.append("## Tool Failures")
    if failures:
        for f in failures:
            parts.append(f)
    else:
        parts.append("All tools completed successfully")
    parts.append("")

    # Capital Configuration
    parts.append("## Capital Configuration\n")
    parts.append("| Parameter | Value |")
    parts.append("| :--- | :--- |")
    parts.append(f"| per_stock_total | {capital.get('per_stock_total', 600)} |")
    parts.append(f"| active_pool | {capital.get('active_pool', 300)} |")
    parts.append(f"| reserve_pool | {capital.get('reserve_pool', 300)} |")
    parts.append(f"| active_bullets_max | {capital.get('active_bullets_max', 5)} |")
    parts.append(f"| reserve_bullets_max | {capital.get('reserve_bullets_max', 3)} |")
    parts.append(f"| active_bullet_full | {capital.get('active_bullet_full', 60)} |")
    parts.append(f"| active_bullet_half | {capital.get('active_bullet_half', 30)} |")
    parts.append(f"| reserve_bullet_size | {capital.get('reserve_bullet_size', 100)} |")
    parts.append("")

    return "\n".join(parts)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 tools/deep_dive_collector.py <TICKER>")
        sys.exit(1)

    ticker = sys.argv[1].upper()
    t0 = time.monotonic()

    # Load portfolio
    with open(PORTFOLIO) as f:
        portfolio = json.load(f)
    capital = portfolio.get("capital", {})

    # Determine status
    status = determine_status(ticker, portfolio)

    # Read existing context
    existing_context = read_existing_context(ticker) if status == "EXISTING" else {"identity": None, "memory": None}

    # Get portfolio context
    portfolio_context = get_portfolio_context(ticker, portfolio)

    # Run all tools
    tool_results = run_all_tools(ticker)

    # Build and write output
    content = build_output(ticker, status, existing_context, portfolio_context, tool_results, capital)
    OUTPUT.write_text(content, encoding="utf-8")

    # Summary
    completed = sum(1 for name, _ in TOOL_SECTIONS if tool_results.get(name, ("", None))[1] is None)
    failed_tools = [name for name, _ in TOOL_SECTIONS if tool_results.get(name, ("", None))[1] is not None]
    size_kb = OUTPUT.stat().st_size / 1024

    print(f"Deep Dive Collector — {ticker}")
    print(f"Status: {status}")
    print(f"Tools completed: {completed}/{len(TOOL_SECTIONS)}")
    if failed_tools:
        print(f"Tool failures: [{', '.join(failed_tools)}]")
    elapsed = time.monotonic() - t0
    print(f"Output: deep-dive-raw.md ({size_kb:.1f} KB)")
    print(f"Elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
