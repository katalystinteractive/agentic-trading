#!/usr/bin/env python3
"""Status Gatherer — Phase 1 orchestrator for the status workflow.

Replaces the LLM gatherer's sequential tool-running with a Python script.
Runs portfolio_status.py, ticker_query.py for all tickers, reads cached
structural files, and assembles status-raw.md.

Usage: python3 tools/status_gatherer.py
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
PORTFOLIO_PATH = PROJECT_ROOT / "portfolio.json"
TICKERS_DIR = PROJECT_ROOT / "tickers"
TOOLS_DIR = PROJECT_ROOT / "tools"
OUTPUT_PATH = PROJECT_ROOT / "status-raw.md"

STRUCTURAL_FILES = ["earnings.md", "news.md", "short_interest.md", "institutional.md"]
STRUCTURAL_LABELS = {
    "earnings.md": "Earnings",
    "news.md": "News",
    "short_interest.md": "Short Interest",
    "institutional.md": "Institutional",
}
STRUCTURAL_LINE_LIMIT = 20


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


def classify_tickers(portfolio):
    """Classify tickers into active, watchlist_only, and pending_only.

    Returns dict with keys: active, watchlist_only, pending_only (each sorted).
    - active: shares > 0
    - watchlist_only: on watchlist, no active position
    - pending_only: has pending orders, not active, not on watchlist
    """
    positions = portfolio.get("positions", {})
    pending_orders = portfolio.get("pending_orders", {})
    watchlist = set(portfolio.get("watchlist", []))

    active = []
    watchlist_only = []
    pending_only = []

    # All tickers in the universe
    universe = set(positions.keys()) | set(pending_orders.keys()) | watchlist

    for ticker in sorted(universe):
        pos = positions.get(ticker, {})
        shares = pos.get("shares", 0)
        if isinstance(shares, (int, float)) and shares > 0:
            active.append(ticker)
        elif ticker in watchlist:
            watchlist_only.append(ticker)
        elif ticker in pending_orders and len(pending_orders.get(ticker, [])) > 0:
            pending_only.append(ticker)

    return {"active": active, "watchlist_only": watchlist_only, "pending_only": pending_only}


# ---------------------------------------------------------------------------
# Subprocess Runners
# ---------------------------------------------------------------------------

def run_portfolio_status():
    """Run portfolio_status.py, capture stdout. Returns (stdout, error_or_None)."""
    cmd = ["python3", str(TOOLS_DIR / "portfolio_status.py")]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
            cwd=str(PROJECT_ROOT)
        )
        if result.returncode != 0:
            err = result.stderr.strip() or f"Exit code {result.returncode}"
            return result.stdout.strip(), f"*Error running portfolio_status.py: {err}*"
        return result.stdout.strip(), None
    except subprocess.TimeoutExpired:
        return "", "*Error: portfolio_status.py timed out after 120s*"
    except Exception as e:
        return "", f"*Error running portfolio_status.py: {e}*"


def run_ticker_query(ticker, section=None):
    """Run ticker_query.py for a single ticker. Returns (stdout, error_or_None)."""
    cmd = ["python3", str(TOOLS_DIR / "ticker_query.py"), ticker]
    if section:
        cmd.extend(["--section", section])
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            cwd=str(PROJECT_ROOT)
        )
        if result.returncode != 0:
            err = result.stderr.strip() or f"Exit code {result.returncode}"
            return result.stdout.strip(), f"*Tool error: ticker_query failed for {ticker}: {err}*"
        return result.stdout.strip(), None
    except subprocess.TimeoutExpired:
        return "", f"*Tool error: ticker_query timed out for {ticker}*"
    except Exception as e:
        return "", f"*Tool error: ticker_query failed for {ticker}: {e}*"


# ---------------------------------------------------------------------------
# Structural Context
# ---------------------------------------------------------------------------

def read_structural_context(ticker, limit=STRUCTURAL_LINE_LIMIT):
    """Read first N lines of each cached structural file for a ticker.

    Returns markdown string with sections for each file.
    If file does not exist, outputs '**<Section>:** No cached file.'
    """
    ticker_dir = TICKERS_DIR / ticker
    parts = []

    for filename in STRUCTURAL_FILES:
        label = STRUCTURAL_LABELS[filename]
        filepath = ticker_dir / filename

        if not filepath.exists():
            parts.append(f"**{label}:** No cached file.")
            continue

        try:
            text = filepath.read_text(encoding="utf-8")
        except Exception:
            parts.append(f"**{label}:** *Error reading file.*")
            continue

        lines = text.splitlines()

        # Extract generation date from first line (*Generated: YYYY-MM-DD*)
        gen_date = ""
        if lines:
            m = re.search(r"Generated:\s*(\d{4}-\d{2}-\d{2})", lines[0])
            if m:
                gen_date = m.group(1)

        # Take first N lines (skip empty leading lines)
        content_lines = lines[:limit]
        content = "\n".join(content_lines)

        header = f"**{label} (tickers/{ticker}/{filename}"
        if gen_date:
            header += f" — generated {gen_date}"
        header += "):**"

        parts.append(header)
        parts.append("")
        parts.append(content)

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Velocity & Bounce
# ---------------------------------------------------------------------------

def _fmt_val(val, prefix="$", suffix=""):
    """Format a value with prefix/suffix if numeric, else return as string."""
    if isinstance(val, (int, float)):
        return f"{prefix}{val}{suffix}"
    return str(val)


def _fmt_or_na(val):
    """Format a numeric value as $X.XX, else return 'N/A'."""
    return f"${val:.2f}" if isinstance(val, (int, float)) else "N/A"


def build_velocity_bounce(portfolio):
    """Extract velocity/bounce data from portfolio.json."""
    parts = []

    # Check all velocity/bounce sections
    sections = [
        ("velocity_positions", "Velocity Positions"),
        ("velocity_pending", "Velocity Pending"),
        ("velocity_watchlist", "Velocity Watchlist"),
        ("bounce_positions", "Bounce Positions"),
        ("bounce_pending", "Bounce Pending"),
        ("bounce_watchlist", "Bounce Watchlist"),
    ]

    any_active = False
    status_rows = []
    for key, label in sections:
        data = portfolio.get(key, {})
        if isinstance(data, dict):
            is_empty = len(data) == 0
        elif isinstance(data, list):
            is_empty = len(data) == 0
        else:
            is_empty = True

        status_rows.append((key, "Empty" if is_empty else "Active"))
        if not is_empty:
            any_active = True

    if not any_active:
        parts.append("No active velocity/bounce trades.")
        parts.append("")

    parts.append("| Section | Status |")
    parts.append("| :--- | :--- |")
    for key, status in status_rows:
        parts.append(f"| {key} | {status} |")

    # Capital pools
    vel_cap = portfolio.get("velocity_capital", {})
    if vel_cap:
        total = vel_cap.get("total_pool", "N/A")
        per_trade = vel_cap.get("per_trade_size", "N/A")
        max_conc = vel_cap.get("max_concurrent", "N/A")
        stop = vel_cap.get("stop_loss_pct", "N/A")
        target = vel_cap.get("target_pct", "N/A")
        time_stop = vel_cap.get("time_stop_days", "N/A")
        parts.append(
            f"\n**Velocity Capital Pool:** {_fmt_val(total)} total | {_fmt_val(per_trade)}/trade | "
            f"max {max_conc} concurrent | {_fmt_val(stop, prefix='', suffix='%')} stop | "
            f"{_fmt_val(target, prefix='', suffix='%')} target | {time_stop}-day time stop"
        )

    bnc_cap = portfolio.get("bounce_capital", {})
    if bnc_cap:
        total = bnc_cap.get("total_pool", "N/A")
        per_trade = bnc_cap.get("per_trade_size", "N/A")
        max_conc = bnc_cap.get("max_concurrent", "N/A")
        stop = bnc_cap.get("stop_loss_pct", "N/A")
        time_stop = bnc_cap.get("time_stop_days", "N/A")
        parts.append(
            f"**Bounce Capital Pool:** {_fmt_val(total)} total | {_fmt_val(per_trade)}/trade | "
            f"max {max_conc} concurrent | {_fmt_val(stop, prefix='', suffix='%')} stop | "
            f"{time_stop}-day time stop"
        )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Watchlist / Pending-Only Levels
# ---------------------------------------------------------------------------

def build_watchlist_section(ticker, query_output, query_error, portfolio, is_pending_only=False):
    """Build a watchlist/pending-only ticker section with levels and pending orders."""
    pending_orders = portfolio.get("pending_orders", {})
    orders = pending_orders.get(ticker, [])

    parts = []

    suffix = " (Pending Only)" if is_pending_only else ""
    # Price info will come from the portfolio_status section; we just show levels here
    parts.append(f"### {ticker}{suffix}")

    if query_error and not query_output:
        parts.append(query_error)
    elif query_output:
        parts.append(query_output)
    else:
        parts.append(f"*No wick-adjusted levels found for {ticker}.*")

    # Add pending orders summary
    if orders:
        non_paused = [o for o in orders if "PAUSED" not in o.get("note", "").upper()]
        paused = [o for o in orders if "PAUSED" in o.get("note", "").upper()]

        if non_paused:
            order_strs = []
            buy_count = 0
            for o in non_paused:
                buy_count += 1 if o["type"] == "BUY" else 0
                note = o.get("note", "")
                # Extract zone label from note
                if note.startswith("Bullet") or note.startswith("Last active"):
                    zone = "Active"
                elif note.startswith("Reserve"):
                    zone = "Reserve"
                elif o["type"] == "SELL":
                    zone = "Sell"
                else:
                    zone = "—"
                label = f"B{buy_count}" if o["type"] == "BUY" else "S"
                order_strs.append(f"{label} ${o['price']:.2f} ({zone})")

            parts.append(f"\nPending orders: {', '.join(order_strs)}")

        if paused:
            paused_strs = []
            for o in paused:
                paused_strs.append(f"${o['price']:.2f} ({o['type']})")
            parts.append(f"Paused orders: {', '.join(paused_strs)}")
    else:
        parts.append(f"\nNo pending orders ({ticker} pending_orders: []).")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def assemble_raw(today_str, portfolio_status_output, ticker_details, watchlist_sections,
                 velocity_bounce, capital_note):
    """Assemble the complete status-raw.md."""
    parts = []

    # Title
    parts.append(f"# Status Raw Data — {today_str}")
    parts.append("")

    # Portfolio Status section
    parts.append("## Portfolio Status")
    parts.append("")
    if portfolio_status_output:
        # Strip the "# Portfolio Status — ..." title line (already under ## Portfolio Status)
        ps_lines = portfolio_status_output.split("\n")
        started = False
        for line in ps_lines:
            if not started:
                if line.startswith("# Portfolio Status"):
                    started = True
                    continue  # skip the title line itself
                elif line.strip() == "":
                    continue  # skip leading blank lines
            parts.append(line)
    else:
        parts.append("*Error: portfolio_status.py failed to produce output.*")
    parts.append("")

    # Separator
    parts.append("---")
    parts.append("")

    # Per-Ticker Detail
    parts.append("## Per-Ticker Detail")
    parts.append("")

    for ticker, detail in ticker_details:
        parts.append(f"### {ticker}")
        parts.append("")
        parts.append("#### Identity & Levels")
        parts.append("")
        if detail["query_output"]:
            parts.append(detail["query_output"])
        elif detail["query_error"]:
            parts.append(detail["query_error"])
        else:
            parts.append(f"*No data available for {ticker}.*")
        parts.append("")

        parts.append("#### Structural Context")
        parts.append("")
        parts.append(detail["structural"])
        parts.append("")
        parts.append("---")
        parts.append("")

    # Watchlist Levels
    parts.append("## Watchlist Levels")
    parts.append("")

    for section_text in watchlist_sections:
        parts.append(section_text)
        parts.append("")

    # Separator
    parts.append("---")
    parts.append("")

    # Velocity & Bounce
    parts.append("## Velocity & Bounce")
    parts.append("")
    parts.append(velocity_bounce)
    parts.append("")

    # Separator
    parts.append("---")
    parts.append("")

    # Capital Summary
    parts.append("## Capital Summary")
    parts.append("")
    parts.append(capital_note)

    return "\n".join(parts) + "\n"


def extract_capital_from_ps(portfolio_status_output):
    """Extract the Capital Summary table from portfolio_status.py output."""
    lines = portfolio_status_output.split("\n")
    in_section = False
    result = []
    for line in lines:
        if line.strip().startswith("## Capital Summary"):
            in_section = True
            continue
        if in_section and line.strip().startswith("## "):
            break
        if in_section:
            result.append(line)

    if result:
        # Strip trailing blank lines
        while result and not result[-1].strip():
            result.pop()
        return "\n".join(result)

    # Fallback: build from portfolio.json
    return ""


def build_capital_note(portfolio, ps_output):
    """Build the capital summary section."""
    parts = []

    # First try to extract from portfolio_status output
    cap_table = extract_capital_from_ps(ps_output) if ps_output else ""
    if cap_table:
        parts.append(cap_table)
    else:
        # Fallback — format with $X.XX if numeric, else N/A
        cap = portfolio.get("capital", {})
        positions = portfolio.get("positions", {})
        deployed = sum(
            pos["shares"] * pos["avg_cost"]
            for pos in positions.values()
            if isinstance(pos.get("shares"), (int, float)) and isinstance(pos.get("avg_cost"), (int, float))
        )
        parts.append("| Metric | Value |")
        parts.append("| :--- | :--- |")
        parts.append(f"| Deployed | ${deployed:,.2f} |")
        parts.append(f"| Per-Stock Budget | {_fmt_or_na(cap.get('per_stock_total'))} |")
        parts.append(f"| Active Bullet (Full/Std) | {_fmt_or_na(cap.get('active_bullet_full'))} |")
        parts.append(f"| Active Bullet (Half) | {_fmt_or_na(cap.get('active_bullet_half'))} |")
        parts.append(f"| Reserve Bullet | {_fmt_or_na(cap.get('reserve_bullet_size'))} |")

    parts.append("")
    parts.append(
        "Capital allocation note: Active pool = $300/stock, Reserve pool = $300/stock. "
        "Bullet sizing scales with share price (~$100 for $16+ stocks, ~$30 for $1.50 stocks)."
    )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Rename portfolio_status.py section headers to match raw format
# ---------------------------------------------------------------------------

def rename_ps_headers(ps_output):
    """Rename ## headers from portfolio_status.py to ### for embedding under ## Portfolio Status."""
    return ps_output.replace("## Active Positions", "### Active Positions") \
                     .replace("## Pending Orders", "### Pending Orders") \
                     .replace("## Watchlist", "### Watchlist Prices") \
                     .replace("## Capital Summary", "### Capital Summary")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    t0 = time.monotonic()
    today_str = date.today().isoformat()

    # Load portfolio
    portfolio = load_portfolio()

    # Classify tickers
    tickers = classify_tickers(portfolio)
    total = len(tickers["active"]) + len(tickers["watchlist_only"]) + len(tickers["pending_only"])

    print(f"Status Gatherer — {today_str}")
    print(f"Tickers: {total} (Active:{len(tickers['active'])} "
          f"Watchlist:{len(tickers['watchlist_only'])} "
          f"Pending-only:{len(tickers['pending_only'])})")

    # Step 1: Run portfolio_status.py (sequential — does yfinance fetch)
    print("Running portfolio_status.py...")
    ps_output, ps_error = run_portfolio_status()
    if ps_error:
        print(f"  Warning: {ps_error}", file=sys.stderr)
    if ps_output:
        ps_output = rename_ps_headers(ps_output)

    # Step 2: Run ticker_query.py for all tickers in parallel
    print(f"Running ticker_query.py for {len(tickers['active'])} active positions (4 workers)...")

    active_results = {}  # ticker -> (stdout, error)
    watchlist_results = {}  # ticker -> (stdout, error)
    pending_results = {}  # ticker -> (stdout, error)

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {}

        # Active positions: full query (identity + levels + memory)
        for ticker in tickers["active"]:
            future = executor.submit(run_ticker_query, ticker)
            futures[future] = ("active", ticker)

        # Watchlist-only: levels only
        for ticker in tickers["watchlist_only"]:
            future = executor.submit(run_ticker_query, ticker, "levels")
            futures[future] = ("watchlist", ticker)

        # Pending-only: levels only
        for ticker in tickers["pending_only"]:
            future = executor.submit(run_ticker_query, ticker, "levels")
            futures[future] = ("pending", ticker)

        for future in as_completed(futures):
            category, ticker = futures[future]
            try:
                stdout, error = future.result()
                if category == "active":
                    active_results[ticker] = (stdout, error)
                elif category == "watchlist":
                    watchlist_results[ticker] = (stdout, error)
                else:
                    pending_results[ticker] = (stdout, error)

                status = "OK" if not error else "WARN"
                print(f"  {ticker}: {status}")
            except Exception as e:
                error_msg = f"*Tool error: {e}*"
                if category == "active":
                    active_results[ticker] = ("", error_msg)
                elif category == "watchlist":
                    watchlist_results[ticker] = ("", error_msg)
                else:
                    pending_results[ticker] = ("", error_msg)
                print(f"  {ticker}: EXCEPTION")

    # Step 3: Read structural context for active positions
    print("Reading structural context for active positions...")
    structural_data = {}
    for ticker in tickers["active"]:
        structural_data[ticker] = read_structural_context(ticker)

    # Step 4: Build ticker detail sections (active positions)
    ticker_details = []
    for ticker in tickers["active"]:
        stdout, error = active_results.get(ticker, ("", None))
        detail = {
            "query_output": stdout,
            "query_error": error,
            "structural": structural_data.get(ticker, ""),
        }
        ticker_details.append((ticker, detail))

    # Step 5: Build watchlist + pending-only sections
    watchlist_sections = []
    for ticker in tickers["watchlist_only"]:
        stdout, error = watchlist_results.get(ticker, ("", None))
        section = build_watchlist_section(ticker, stdout, error, portfolio)
        watchlist_sections.append(section)

    for ticker in tickers["pending_only"]:
        stdout, error = pending_results.get(ticker, ("", None))
        section = build_watchlist_section(ticker, stdout, error, portfolio, is_pending_only=True)
        watchlist_sections.append(section)

    # Step 6: Velocity & Bounce
    velocity_bounce = build_velocity_bounce(portfolio)

    # Step 7: Capital note
    capital_note = build_capital_note(portfolio, ps_output)

    # Step 8: Assemble and write
    content = assemble_raw(today_str, ps_output, ticker_details, watchlist_sections,
                           velocity_bounce, capital_note)
    OUTPUT_PATH.write_text(content, encoding="utf-8")

    # Summary
    elapsed = time.monotonic() - t0
    size_kb = OUTPUT_PATH.stat().st_size / 1024

    print(f"\nOutput: status-raw.md ({size_kb:.1f} KB)")
    print(f"Active positions: {len(tickers['active'])}")
    print(f"Watchlist tickers: {len(tickers['watchlist_only'])}")
    print(f"Pending-only tickers: {len(tickers['pending_only'])}")
    print(f"Elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
