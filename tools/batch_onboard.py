#!/usr/bin/env python3
"""Batch Onboard — onboard multiple tickers with full infrastructure setup.

Per ticker: create tickers/<TICKER>/ directory, generate identity.md + memory.md
from templates, run wick_offset_analyzer, run cycle_timing_analyzer, add to
portfolio.json watchlist.

Usage:
    python3 tools/batch_onboard.py MARA RIOT HUT          # onboard specific tickers
    python3 tools/batch_onboard.py --from-screening 15    # top 15 from universe cache
    python3 tools/batch_onboard.py --dry-run MARA         # preview only
    python3 tools/batch_onboard.py --json MARA RIOT       # JSON output
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sector_registry import get_sector
from wick_offset_analyzer import analyze_stock_data
from cycle_timing_analyzer import analyze_ticker as _analyze_cycle_timing

_ROOT = Path(__file__).resolve().parent.parent
_PORTFOLIO = _ROOT / "portfolio.json"
_UNIVERSE_CACHE = _ROOT / "data" / "universe_screen_cache.json"


def _load_portfolio():
    try:
        return json.loads(_PORTFOLIO.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"positions": {}, "pending_orders": {}, "watchlist": []}


def _save_portfolio(portfolio):
    _PORTFOLIO.write_text(json.dumps(portfolio, indent=2) + "\n")


def _get_basic_info(ticker):
    """Fetch basic stock info from yfinance."""
    try:
        info = yf.Ticker(ticker).info
        return {
            "name": info.get("shortName", info.get("longName", ticker)),
            "price": info.get("currentPrice", info.get("regularMarketPrice")),
        }
    except Exception:
        return {"name": ticker, "price": None}


def _generate_identity(ticker, info, sector, screening_data=None):
    """Generate identity.md content from template."""
    today = date.today().isoformat()
    price_str = f"${info['price']:.2f}" if info.get("price") else "N/A"

    swing_str = "N/A"
    consistency_str = "N/A"
    score_str = "N/A"
    if screening_data:
        swing_str = f"{screening_data.get('median_swing', 'N/A')}%"
        consistency_str = f"{screening_data.get('consistency', 'N/A')}%"
        score_str = str(screening_data.get("score", "N/A"))

    return f"""# {ticker} — {info.get('name', ticker)}

## Core Identity
- **Sector**: {sector}
- **Price Range**: {price_str} (as of {today})
- **Monthly Swing**: {swing_str} median ({consistency_str} consistency)
- **Strategy Cycle**: SCOUTING
- **Status**: Newly onboarded — pending first entry

## Key Levels
See `wick_analysis.md` for full support level table with wick offsets.

## Cycle Data
See `cycle_timing.json` for validated cycle statistics.

## Notes
- Onboarded: {today} via batch_onboard.py
- Screening score: {score_str}/100
"""


def _generate_memory(ticker, info, sector, screening_data=None):
    """Generate memory.md content from template."""
    today = date.today().isoformat()
    price_str = f"${info['price']:.2f}" if info.get("price") else "N/A"

    swing_str = "N/A"
    if screening_data:
        swing_str = f"{screening_data.get('median_swing', 'N/A')}%"

    return f"""# Agent Memory: {info.get('name', ticker)} ({ticker})

## Trade Log
(No trades yet)

## Observations
- **{today}:** Onboarded via batch screening. {sector} sector, {price_str}, {swing_str} monthly swing.

## Lessons
(None yet)
"""


def onboard_one(ticker, screening_data=None, dry_run=False):
    """Onboard a single ticker. Returns result dict."""
    result = {"ticker": ticker, "status": "ok", "steps": [], "errors": []}
    ticker_dir = _ROOT / "tickers" / ticker

    # Get basic info
    info = _get_basic_info(ticker)
    sector = get_sector(ticker)
    result["name"] = info.get("name", ticker)
    result["sector"] = sector

    if dry_run:
        result["status"] = "dry_run"
        result["steps"].append("Would create directory + identity + memory")
        result["steps"].append("Would run wick analysis + cycle timing")
        result["steps"].append("Would add to portfolio.json watchlist")
        return result

    # Create directory
    ticker_dir.mkdir(parents=True, exist_ok=True)
    result["steps"].append(f"Created {ticker_dir}")

    # Generate identity.md (only if doesn't exist)
    identity_path = ticker_dir / "identity.md"
    if not identity_path.exists():
        identity_path.write_text(_generate_identity(ticker, info, sector, screening_data))
        result["steps"].append("Generated identity.md")
    else:
        result["steps"].append("identity.md already exists — skipped")

    # Generate memory.md (only if doesn't exist)
    memory_path = ticker_dir / "memory.md"
    if not memory_path.exists():
        memory_path.write_text(_generate_memory(ticker, info, sector, screening_data))
        result["steps"].append("Generated memory.md")
    else:
        result["steps"].append("memory.md already exists — skipped")

    # Run wick analysis
    wick_path = ticker_dir / "wick_analysis.md"
    if not wick_path.exists():
        try:
            data, error = analyze_stock_data(ticker)
            if data:
                # Write wick analysis summary
                levels = data.get("levels", [])
                bp = data.get("bullet_plan", {})
                lines = [f"# {ticker} — Wick Offset Analysis", ""]
                lines.append(f"Current Price: ${data.get('current_price', 0):.2f}")
                lines.append(f"Active Radius: {data.get('active_radius', 0):.1f}%")
                lines.append("")
                lines.append("## Support Level Table")
                lines.append("| Support | Hold% | Approaches | Offset | Buy At | Zone | Tier |")
                lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
                active_levels = bp.get("active", [])
                active_set = {id(b) for b in active_levels}
                for b in active_levels + bp.get("reserve", []):
                    zone = "Active" if id(b) in active_set else "Reserve"
                    lines.append(
                        f"| ${b['support_price']:.2f} | {b['hold_rate']:.0f}% "
                        f"| {b['approaches']} | ${b.get('offset', 0):.2f} "
                        f"| ${b['buy_at']:.2f} | {zone} | {b['tier']} |"
                    )
                wick_path.write_text("\n".join(lines) + "\n")
                result["steps"].append(f"Wrote wick_analysis.md ({len(levels)} levels)")
            else:
                result["errors"].append(f"Wick analysis: {error}")
        except Exception as e:
            result["errors"].append(f"Wick analysis error: {e}")
    else:
        result["steps"].append("wick_analysis.md already exists — skipped")

    # Run cycle timing
    ct_path = ticker_dir / "cycle_timing.json"
    if not ct_path.exists():
        try:
            _, ct_result, ct_err = _analyze_cycle_timing(ticker)
            if ct_result:
                ct_path.write_text(json.dumps(ct_result, indent=2, default=str) + "\n")
                cycles = ct_result.get("statistics", {}).get("total_cycles", 0)
                result["steps"].append(f"Wrote cycle_timing.json ({cycles} cycles)")
            elif ct_err:
                result["errors"].append(f"Cycle timing: {ct_err}")
        except Exception as e:
            result["errors"].append(f"Cycle timing error: {e}")
    else:
        result["steps"].append("cycle_timing.json already exists — skipped")

    if result["errors"]:
        result["status"] = "partial"

    return result


def batch_onboard(tickers, screening_data_map=None, dry_run=False, max_workers=6):
    """Onboard multiple tickers in parallel."""
    if screening_data_map is None:
        screening_data_map = {}

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(onboard_one, t, screening_data_map.get(t), dry_run): t
            for t in tickers
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            status_icon = "OK" if result["status"] == "ok" else (
                "DRY" if result["status"] == "dry_run" else "PARTIAL")
            print(f"  {result['ticker']}: {status_icon} — {', '.join(result['steps'][:3])}")

    # Sort by ticker for consistent output
    results.sort(key=lambda r: r["ticker"])
    return results


def _add_to_watchlist(tickers, dry_run=False):
    """Add tickers to portfolio.json watchlist if not already present."""
    if dry_run:
        return

    portfolio = _load_portfolio()
    watchlist = portfolio.get("watchlist", [])
    added = []
    for t in tickers:
        if t not in watchlist:
            watchlist.append(t)
            added.append(t)
    if added:
        portfolio["watchlist"] = sorted(watchlist)
        _save_portfolio(portfolio)
        print(f"Added {len(added)} to watchlist: {', '.join(added)}")


def _load_screening_passers(n):
    """Load top N passers from universe screening cache."""
    try:
        data = json.loads(_UNIVERSE_CACHE.read_text())
        passers = data.get("passers", [])[:n]
        return {p["ticker"]: p for p in passers}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"*Error loading screening cache: {e}*")
        print("Run: python3 tools/universe_screener.py first")
        return {}


def format_markdown(results):
    """Format results as markdown."""
    lines = ["# Batch Onboard Results", ""]
    lines.append(f"*{len(results)} tickers processed on {date.today().isoformat()}*")
    lines.append("")
    lines.append("| Ticker | Name | Sector | Status | Steps | Errors |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
    for r in results:
        steps = "; ".join(r["steps"][:3])
        errors = "; ".join(r["errors"]) if r["errors"] else "None"
        lines.append(f"| {r['ticker']} | {r.get('name', '?')} | {r.get('sector', '?')} "
                      f"| {r['status']} | {steps} | {errors} |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Batch Onboard — set up ticker infrastructure")
    parser.add_argument("tickers", nargs="*", help="Tickers to onboard")
    parser.add_argument("--from-screening", type=int, metavar="N",
                        help="Onboard top N from universe screening cache")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no changes")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    t0 = time.monotonic()

    # Determine tickers
    screening_data_map = {}
    if args.from_screening:
        screening_data_map = _load_screening_passers(args.from_screening)
        if not screening_data_map:
            sys.exit(1)
        tickers = list(screening_data_map.keys())
    elif args.tickers:
        tickers = [t.upper() for t in args.tickers]
    else:
        parser.print_help()
        sys.exit(1)

    # Filter out already-onboarded tickers (have ticker dir + identity.md)
    existing = []
    new_tickers = []
    for t in tickers:
        identity = _ROOT / "tickers" / t / "identity.md"
        if identity.exists():
            existing.append(t)
        new_tickers.append(t)  # still process for partial setup (wick, cycle)

    print(f"Batch Onboard")
    print(f"=" * 50)
    print(f"Tickers: {len(tickers)} ({len(existing)} have existing identity)")
    if args.dry_run:
        print("Mode: DRY RUN")
    print()

    # Onboard
    results = batch_onboard(new_tickers, screening_data_map, dry_run=args.dry_run)

    # Add successful tickers to watchlist
    successful = [r["ticker"] for r in results if r["status"] in ("ok", "partial")]
    _add_to_watchlist(successful, dry_run=args.dry_run)

    elapsed = time.monotonic() - t0
    ok_count = sum(1 for r in results if r["status"] == "ok")
    partial_count = sum(1 for r in results if r["status"] == "partial")

    print(f"\n{'=' * 50}")
    print(f"Results: {ok_count} OK, {partial_count} partial, {len(results) - ok_count - partial_count} other")
    print(f"Elapsed: {elapsed:.1f}s")

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        print()
        print(format_markdown(results))


if __name__ == "__main__":
    main()
