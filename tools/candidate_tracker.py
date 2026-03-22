#!/usr/bin/env python3
"""Candidate Tracker — manage post-screening candidates not yet on watchlist.

Tracks candidates from screening runs, supports promotion (onboard via
batch_onboard) and age-out (drop stale >30-day candidates).

Usage:
    python3 tools/candidate_tracker.py list                # show candidate pool
    python3 tools/candidate_tracker.py add MARA RIOT       # add manually
    python3 tools/candidate_tracker.py promote MARA        # onboard via batch_onboard
    python3 tools/candidate_tracker.py age-out             # drop >30-day stale candidates
    python3 tools/candidate_tracker.py import-screening    # import from universe cache
    python3 tools/candidate_tracker.py --json list         # JSON output
"""
import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sector_registry import get_sector

_ROOT = Path(__file__).resolve().parent.parent
_CANDIDATES = _ROOT / "data" / "candidates.json"
_UNIVERSE_CACHE = _ROOT / "data" / "universe_screen_cache.json"
_PORTFOLIO = _ROOT / "portfolio.json"

AGE_OUT_DAYS = 30


def _load_candidates():
    try:
        return json.loads(_CANDIDATES.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"candidates": [], "last_updated": None}


def _save_candidates(data):
    data["last_updated"] = datetime.now().isoformat(timespec="seconds")
    _CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    _CANDIDATES.write_text(json.dumps(data, indent=2) + "\n")


def _load_portfolio_tickers():
    """Get all tickers already in portfolio (positions + watchlist + pending)."""
    try:
        portfolio = json.loads(_PORTFOLIO.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return set()
    tickers = set(portfolio.get("positions", {}).keys())
    tickers.update(portfolio.get("watchlist", []))
    tickers.update(portfolio.get("pending_orders", {}).keys())
    return tickers


def cmd_list(args):
    """List all candidates."""
    data = _load_candidates()
    candidates = data["candidates"]

    if not candidates:
        print("No candidates in pool.")
        return

    if args.json:
        print(json.dumps(data, indent=2))
        return

    today = date.today()
    print(f"# Candidate Pool ({len(candidates)} tickers)")
    print(f"*Last updated: {data.get('last_updated', 'never')}*")
    print()
    print("| # | Ticker | Sector | Swing% | Price | Added | Age (days) | Source |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for i, c in enumerate(candidates, 1):
        added = c.get("added", "?")
        try:
            age = (today - date.fromisoformat(added)).days
        except (ValueError, TypeError):
            age = "?"
        print(f"| {i} | {c['ticker']} | {c.get('sector', '?')} "
              f"| {c.get('median_swing', '?')}% | ${c.get('price', 0):.2f} "
              f"| {added} | {age} | {c.get('source', '?')} |")


def cmd_add(args):
    """Add tickers manually."""
    data = _load_candidates()
    existing = {c["ticker"] for c in data["candidates"]}
    portfolio_tickers = _load_portfolio_tickers()
    today = date.today().isoformat()

    added = []
    for ticker in args.tickers:
        ticker = ticker.upper()
        if ticker in existing:
            print(f"  {ticker}: already in candidates — skipped")
            continue
        if ticker in portfolio_tickers:
            print(f"  {ticker}: already in portfolio — skipped")
            continue
        data["candidates"].append({
            "ticker": ticker,
            "sector": get_sector(ticker),
            "added": today,
            "source": "manual",
            "median_swing": None,
            "price": None,
        })
        added.append(ticker)
        print(f"  {ticker}: added")

    _save_candidates(data)
    print(f"\nAdded {len(added)} candidates")


def cmd_promote(args):
    """Promote candidates to watchlist via batch_onboard."""
    data = _load_candidates()
    candidate_map = {c["ticker"]: c for c in data["candidates"]}

    to_promote = []
    for ticker in args.tickers:
        ticker = ticker.upper()
        if ticker not in candidate_map:
            print(f"  {ticker}: not in candidates — skipped")
            continue
        to_promote.append(ticker)

    if not to_promote:
        print("No candidates to promote.")
        return

    # Run batch_onboard
    cmd = ["python3", str(_ROOT / "tools" / "batch_onboard.py")] + to_promote
    if args.dry_run:
        cmd.append("--dry-run")

    print(f"Promoting {len(to_promote)} via batch_onboard...")
    result = subprocess.run(cmd, cwd=str(_ROOT))

    if result.returncode == 0 and not args.dry_run:
        # Remove promoted from candidates
        data["candidates"] = [c for c in data["candidates"] if c["ticker"] not in to_promote]
        _save_candidates(data)
        print(f"Removed {len(to_promote)} from candidate pool")


def cmd_age_out(args):
    """Drop candidates older than AGE_OUT_DAYS."""
    data = _load_candidates()
    today = date.today()
    cutoff = today - timedelta(days=AGE_OUT_DAYS)

    kept = []
    dropped = []
    for c in data["candidates"]:
        try:
            added = date.fromisoformat(c.get("added", "2000-01-01"))
        except (ValueError, TypeError):
            added = date(2000, 1, 1)
        if added < cutoff:
            dropped.append(c["ticker"])
        else:
            kept.append(c)

    data["candidates"] = kept
    _save_candidates(data)
    print(f"Aged out {len(dropped)} candidates (>{AGE_OUT_DAYS} days): {', '.join(dropped) if dropped else 'none'}")
    print(f"Remaining: {len(kept)}")


def cmd_import_screening(args):
    """Import candidates from universe screening cache."""
    try:
        cache = json.loads(_UNIVERSE_CACHE.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"*Error loading universe cache: {e}*")
        return

    data = _load_candidates()
    existing = {c["ticker"] for c in data["candidates"]}
    portfolio_tickers = _load_portfolio_tickers()
    today = date.today().isoformat()

    added = 0
    for p in cache.get("passers", []):
        ticker = p["ticker"]
        if ticker in existing or ticker in portfolio_tickers:
            continue
        data["candidates"].append({
            "ticker": ticker,
            "sector": p.get("sector", get_sector(ticker)),
            "added": today,
            "source": "universe_screen",
            "median_swing": p.get("median_swing"),
            "price": p.get("price"),
            "consistency": p.get("consistency"),
        })
        existing.add(ticker)
        added += 1

    _save_candidates(data)
    print(f"Imported {added} new candidates from universe screening "
          f"(total: {len(data['candidates'])})")


def main():
    parser = argparse.ArgumentParser(description="Candidate Tracker — manage screening candidates")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="Show candidate pool")
    add_p = sub.add_parser("add", help="Add tickers manually")
    add_p.add_argument("tickers", nargs="+")
    promote_p = sub.add_parser("promote", help="Onboard via batch_onboard")
    promote_p.add_argument("tickers", nargs="+")
    sub.add_parser("age-out", help=f"Drop >{AGE_OUT_DAYS}-day stale candidates")
    sub.add_parser("import-screening", help="Import from universe cache")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list(args)
    elif args.command == "add":
        cmd_add(args)
    elif args.command == "promote":
        cmd_promote(args)
    elif args.command == "age-out":
        cmd_age_out(args)
    elif args.command == "import-screening":
        cmd_import_screening(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
