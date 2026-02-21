"""Ticker Query — structured interface for querying ticker data.

Provides a CLI for workflow agents and scripts to access ticker structural
data without reading raw markdown files directly.

Usage:
    python3 tools/ticker_query.py CLSK                    # Full summary
    python3 tools/ticker_query.py CLSK --section identity  # Identity only
    python3 tools/ticker_query.py CLSK --section levels    # Wick-adjusted buy levels only
    python3 tools/ticker_query.py CLSK --section memory    # Trade log only
    python3 tools/ticker_query.py --all --section levels   # All tickers' buy levels
    python3 tools/ticker_query.py --portfolio-summary      # Portfolio-wide summary
"""
import argparse
import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
TICKERS_DIR = _ROOT / "tickers"
PORTFOLIO_PATH = _ROOT / "portfolio.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_portfolio():
    try:
        return json.loads(PORTFOLIO_PATH.read_text())
    except Exception:
        return {}


def _read_file(path):
    try:
        return path.read_text()
    except Exception:
        return None


def _all_tickers():
    """Return sorted list of ticker symbols that have identity.md.

    Filters out non-ticker directories (templates, test dirs) by requiring
    the name to be all-uppercase letters (valid ticker symbols).
    """
    if not TICKERS_DIR.exists():
        return []
    return sorted(
        d.name for d in TICKERS_DIR.iterdir()
        if d.is_dir() and (d / "identity.md").exists() and d.name.isalpha() and d.name.isupper()
    )


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def _parse_identity_summary(content):
    """Extract key fields from identity.md content."""
    result = {}

    # Persona — first bold text after ## Persona
    m = re.search(r"\*\*(.+?)\.\*\*", content)
    result["persona"] = m.group(1) if m else "N/A"

    # Cycle
    m = re.search(r"\*\*Cycle:\*\*\s*(.+?)(?:\n|$)", content)
    result["cycle"] = m.group(1).strip().rstrip(".") if m else "N/A"

    # Monthly Swing
    m = re.search(r"(\d+\.?\d*)%\s*median swing", content)
    result["monthly_swing"] = f"{m.group(1)}%" if m else "N/A"

    # Status
    m = re.search(r"\*\*Status:\*\*\s*\*\*(.+?)\*\*", content)
    result["status"] = m.group(1) if m else "N/A"

    return result


def _parse_wick_table(content):
    """Extract wick-adjusted buy levels table from identity.md."""
    lines = content.splitlines()
    rows = []
    in_table = False
    header_found = False

    for line in lines:
        stripped = line.strip()
        if "Raw Support" in stripped and "Buy At" in stripped:
            in_table = True
            header_found = False
            continue
        if in_table:
            if stripped.startswith("| :---"):
                header_found = True
                continue
            if header_found and stripped.startswith("|"):
                cells = [c.strip() for c in stripped.split("|")[1:-1]]
                if len(cells) >= 7:
                    rows.append({
                        "support": cells[0],
                        "source": cells[1],
                        "hold_rate": cells[2],
                        "offset": cells[3],
                        "buy_at": cells[4],
                        "zone": cells[5],
                        "tier": cells[6],
                    })
            elif not stripped.startswith("|"):
                in_table = False

    return rows


def _parse_trade_log(content):
    """Extract trade log entries from memory.md."""
    entries = []
    for m in re.finditer(
        r"\*\*(\d{4}-\d{2}-\d{2}):\*\*\s*(BUY|SELL)\s+(\d+)\s+shares?\s*@\s*\$?([\d.]+)\s*(.+?)(?:\n|$)",
        content,
    ):
        entries.append({
            "date": m.group(1),
            "action": m.group(2),
            "shares": m.group(3),
            "price": m.group(4),
            "note": m.group(5).strip().rstrip("."),
        })
    return entries


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def _fmt_identity(ticker, summary):
    lines = [
        f"## {ticker} — Identity",
        "",
        "| Field | Value |",
        "| :--- | :--- |",
        f"| Ticker | {ticker} |",
        f"| Persona | {summary['persona']} |",
        f"| Cycle | {summary['cycle']} |",
        f"| Monthly Swing | {summary['monthly_swing']} |",
        f"| Status | {summary['status']} |",
    ]
    return "\n".join(lines)


def _fmt_levels(ticker, rows):
    if not rows:
        return f"*No wick-adjusted levels found for {ticker}.*"
    lines = [
        f"## {ticker} — Wick-Adjusted Buy Levels",
        "",
        "| Support | Source | Hold% | Offset | Buy At | Zone | Tier |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['support']} | {r['source']} | {r['hold_rate']} "
            f"| {r['offset']} | {r['buy_at']} | {r['zone']} | {r['tier']} |"
        )
    return "\n".join(lines)


def _fmt_memory(ticker, entries):
    if not entries:
        return f"*No trade log entries found for {ticker}.*"
    lines = [
        f"## {ticker} — Trade Log",
        "",
        "| Date | Action | Price | Shares | Note |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ]
    for e in entries:
        lines.append(
            f"| {e['date']} | {e['action']} | ${e['price']} "
            f"| {e['shares']} | {e['note']} |"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------

def query_ticker(ticker, section=None):
    """Query data for a single ticker. Returns markdown string."""
    ticker = ticker.upper()
    ticker_dir = TICKERS_DIR / ticker

    if not ticker_dir.exists():
        return f"*Ticker directory not found: {ticker}*"

    parts = []

    if section in (None, "identity"):
        content = _read_file(ticker_dir / "identity.md")
        if content:
            summary = _parse_identity_summary(content)
            parts.append(_fmt_identity(ticker, summary))
        else:
            parts.append(f"*No identity.md found for {ticker}.*")

    if section in (None, "levels"):
        content = _read_file(ticker_dir / "identity.md")
        if content:
            rows = _parse_wick_table(content)
            parts.append(_fmt_levels(ticker, rows))
        else:
            # Try wick_analysis.md as fallback
            content = _read_file(ticker_dir / "wick_analysis.md")
            if content:
                rows = _parse_wick_table(content)
                parts.append(_fmt_levels(ticker, rows))
            else:
                parts.append(f"*No wick data found for {ticker}.*")

    if section in (None, "memory"):
        content = _read_file(ticker_dir / "memory.md")
        if content:
            entries = _parse_trade_log(content)
            parts.append(_fmt_memory(ticker, entries))
        else:
            parts.append(f"*No memory.md found for {ticker}.*")

    return "\n\n".join(parts)


def portfolio_summary():
    """Build a portfolio-wide summary table. Returns markdown string."""
    portfolio = _load_portfolio()
    positions = portfolio.get("positions", {})
    pending = portfolio.get("pending_orders", {})
    watchlist = portfolio.get("watchlist", [])

    all_tickers = sorted(set(
        list(positions.keys()) + list(pending.keys()) + watchlist
    ))

    lines = [
        "# Portfolio Summary",
        "",
        "| Ticker | Shares | Avg Cost | Active Bullets | Pending Buys | Pending Sells | Status |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for ticker in all_tickers:
        pos = positions.get(ticker, {})
        shares = pos.get("shares", 0)
        avg = pos.get("avg_cost", 0)
        bullets = pos.get("bullets_used", 0)

        orders = pending.get(ticker, [])
        buys = sum(1 for o in orders if o.get("type") == "BUY")
        sells = sum(1 for o in orders if o.get("type") == "SELL")

        if shares > 0:
            status = "Position"
        elif ticker in watchlist:
            status = "Watchlist"
        else:
            status = "Pending Only"

        avg_str = f"${avg:.2f}" if avg else "—"
        shares_str = str(shares) if shares else "—"
        bullets_str = str(bullets) if bullets else "—"

        lines.append(
            f"| {ticker} | {shares_str} | {avg_str} | {bullets_str} "
            f"| {buys} | {sells} | {status} |"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Query ticker data from tickers/ directory and portfolio.json"
    )
    parser.add_argument("ticker", nargs="?", help="Ticker symbol (e.g., CLSK)")
    parser.add_argument("--section", choices=["identity", "levels", "memory"],
                        help="Specific section to query")
    parser.add_argument("--all", action="store_true",
                        help="Query all tickers (use with --section)")
    parser.add_argument("--portfolio-summary", action="store_true",
                        help="Show portfolio-wide summary")

    args = parser.parse_args()

    if args.portfolio_summary:
        print(portfolio_summary())
        return

    if args.all:
        tickers = _all_tickers()
        if not tickers:
            print("*No ticker directories found.*")
            return
        results = []
        for t in tickers:
            results.append(query_ticker(t, section=args.section))
        print("\n\n---\n\n".join(results))
        return

    if not args.ticker:
        parser.error("Provide a ticker symbol, --all, or --portfolio-summary")

    print(query_ticker(args.ticker, section=args.section))


if __name__ == "__main__":
    main()
