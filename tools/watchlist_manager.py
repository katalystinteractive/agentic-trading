#!/usr/bin/env python3
"""Watchlist Manager — tiered monitoring with automatic classification.

Tiers derived from portfolio.json state (no schema change):
  ACTIVE   — shares > 0 (full monitoring: 4 tools/ticker)
  ENGAGED  — watchlist + pending BUYs (standard: 2 tools/ticker)
  SCOUTING — watchlist, no orders (light: news only, weekly)
  CANDIDATE — passed screening, not onboarded (none; re-screened weekly)

Usage:
    python3 tools/watchlist_manager.py status              # tier distribution
    python3 tools/watchlist_manager.py promote MARA        # tier up (add orders/onboard)
    python3 tools/watchlist_manager.py demote CLF          # tier down (remove orders)
    python3 tools/watchlist_manager.py drop CLF WOLF       # remove from watchlist + cleanup
    python3 tools/watchlist_manager.py rebalance           # auto from fitness scores
    python3 tools/watchlist_manager.py --json status       # JSON output
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sector_registry import get_sector, shard_tickers

_ROOT = Path(__file__).resolve().parent.parent
_PORTFOLIO = _ROOT / "portfolio.json"
_FITNESS_JSON = _ROOT / "watchlist-fitness.json"
_CANDIDATES = _ROOT / "data" / "candidates.json"


def _load_portfolio():
    try:
        return json.loads(_PORTFOLIO.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"positions": {}, "pending_orders": {}, "watchlist": []}


def _save_portfolio(portfolio):
    _PORTFOLIO.write_text(json.dumps(portfolio, indent=2) + "\n")


def classify_tier(ticker, portfolio):
    """Determine tier for a single ticker from portfolio state."""
    positions = portfolio.get("positions", {})
    pending = portfolio.get("pending_orders", {})
    watchlist = portfolio.get("watchlist", [])

    pos = positions.get(ticker, {})
    shares = pos.get("shares", 0)
    if isinstance(shares, (int, float)) and shares > 0:
        return "ACTIVE"

    if ticker in watchlist or ticker in pending:
        has_buy = any(o.get("type", "").upper() == "BUY"
                      for o in pending.get(ticker, []))
        if has_buy:
            return "ENGAGED"
        return "SCOUTING"

    return "CANDIDATE"


def _get_all_tickers(portfolio):
    """Get all unique tickers across positions, pending, watchlist."""
    tickers = set()
    tickers.update(portfolio.get("positions", {}).keys())
    tickers.update(portfolio.get("pending_orders", {}).keys())
    tickers.update(portfolio.get("watchlist", []))
    return sorted(tickers)


def _tier_distribution(portfolio):
    """Compute tier distribution. Returns dict[tier, list[ticker]]."""
    tiers = {"ACTIVE": [], "ENGAGED": [], "SCOUTING": [], "CANDIDATE": []}
    for ticker in _get_all_tickers(portfolio):
        tier = classify_tier(ticker, portfolio)
        tiers[tier].append(ticker)
    return tiers


def cmd_status(args):
    """Show tier distribution."""
    portfolio = _load_portfolio()
    tiers = _tier_distribution(portfolio)

    # Also check candidates file
    candidates = []
    try:
        cdata = json.loads(_CANDIDATES.read_text())
        candidates = [c["ticker"] for c in cdata.get("candidates", [])]
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    if args.json:
        output = {
            "date": date.today().isoformat(),
            "tiers": {k: v for k, v in tiers.items()},
            "candidates": candidates,
            "totals": {k: len(v) for k, v in tiers.items()},
        }
        output["totals"]["CANDIDATE"] = len(candidates)
        print(json.dumps(output, indent=2))
        return

    print("# Watchlist Tier Distribution")
    print(f"*{date.today().isoformat()}*\n")

    print("| Tier | Count | Monitoring | Tickers |")
    print("| :--- | :--- | :--- | :--- |")
    monitoring = {
        "ACTIVE": "Full (4 tools/ticker)",
        "ENGAGED": "Standard (2 tools/ticker)",
        "SCOUTING": "Light (news only, weekly)",
        "CANDIDATE": "None (re-screened weekly)",
    }
    for tier in ["ACTIVE", "ENGAGED", "SCOUTING"]:
        tickers = tiers[tier]
        tickers_str = ", ".join(tickers[:20])
        if len(tickers) > 20:
            tickers_str += f" (+{len(tickers) - 20} more)"
        print(f"| {tier} | {len(tickers)} | {monitoring[tier]} | {tickers_str} |")
    print(f"| CANDIDATE | {len(candidates)} | {monitoring['CANDIDATE']} | "
          f"{', '.join(candidates[:10])}{'...' if len(candidates) > 10 else ''} |")

    total = sum(len(v) for v in tiers.values()) + len(candidates)
    print(f"\n**Total tracked: {total}**")

    # Sector breakdown for engaged+active
    engaged_active = tiers["ACTIVE"] + tiers["ENGAGED"]
    if engaged_active:
        shards = shard_tickers(engaged_active)
        print("\n### Sector Distribution (Active + Engaged)")
        print("| Sector | Count | Tickers |")
        print("| :--- | :--- | :--- |")
        for name, tickers in sorted(shards.items(), key=lambda x: -len(x[1])):
            print(f"| {name} | {len(tickers)} | {', '.join(tickers)} |")


def cmd_promote(args):
    """Promote ticker to higher tier (SCOUTING→ENGAGED or CANDIDATE→SCOUTING)."""
    portfolio = _load_portfolio()
    watchlist = portfolio.get("watchlist", [])
    changed = False

    for ticker in args.tickers:
        ticker = ticker.upper()
        tier = classify_tier(ticker, portfolio)

        if tier == "ACTIVE":
            print(f"  {ticker}: already ACTIVE — cannot promote further")
            continue
        if tier == "ENGAGED":
            print(f"  {ticker}: already ENGAGED — promote by adding more orders manually")
            continue
        if tier == "SCOUTING":
            print(f"  {ticker}: SCOUTING → ENGAGED requires placing BUY orders")
            print(f"  Use: python3 tools/bullet_recommender.py {ticker}")
            continue
        if tier == "CANDIDATE":
            # Add to watchlist
            if ticker not in watchlist:
                watchlist.append(ticker)
                portfolio["watchlist"] = sorted(watchlist)
                changed = True
                print(f"  {ticker}: CANDIDATE → SCOUTING (added to watchlist)")
            else:
                print(f"  {ticker}: already on watchlist")

    if changed:
        _save_portfolio(portfolio)


def cmd_demote(args):
    """Demote ticker to lower tier."""
    portfolio = _load_portfolio()
    pending = portfolio.get("pending_orders", {})

    for ticker in args.tickers:
        ticker = ticker.upper()
        tier = classify_tier(ticker, portfolio)

        if tier == "ACTIVE":
            print(f"  {ticker}: ACTIVE — cannot auto-demote (has shares). Sell first.")
            continue
        if tier == "ENGAGED":
            # Remove pending BUY orders → becomes SCOUTING
            if ticker in pending:
                buys = [o for o in pending[ticker] if o.get("type", "").upper() == "BUY"]
                non_buys = [o for o in pending[ticker] if o.get("type", "").upper() != "BUY"]
                if buys:
                    pending[ticker] = non_buys
                    if not pending[ticker]:
                        del pending[ticker]
                    portfolio["pending_orders"] = pending
                    _save_portfolio(portfolio)
                    print(f"  {ticker}: ENGAGED → SCOUTING (removed {len(buys)} BUY orders)")
                else:
                    print(f"  {ticker}: no BUY orders to remove")
            continue
        if tier == "SCOUTING":
            print(f"  {ticker}: already SCOUTING — use 'drop' to remove entirely")
            continue
        print(f"  {ticker}: tier={tier}, nothing to demote")


def cmd_drop(args):
    """Remove ticker from watchlist and clean up."""
    portfolio = _load_portfolio()
    watchlist = portfolio.get("watchlist", [])
    pending = portfolio.get("pending_orders", {})

    for ticker in args.tickers:
        ticker = ticker.upper()
        removed_from = []

        if ticker in watchlist:
            watchlist.remove(ticker)
            removed_from.append("watchlist")

        if ticker in pending:
            del pending[ticker]
            removed_from.append("pending_orders")

        # Clean up zero-share position entry
        positions = portfolio.get("positions", {})
        if ticker in positions and positions[ticker].get("shares", 0) == 0:
            del positions[ticker]
            removed_from.append("positions (0 shares)")

        if removed_from:
            portfolio["watchlist"] = watchlist
            portfolio["pending_orders"] = pending
            _save_portfolio(portfolio)
            print(f"  {ticker}: dropped from {', '.join(removed_from)}")
        else:
            print(f"  {ticker}: not found in watchlist or pending")


def cmd_rebalance(args):
    """Auto-rebalance based on watchlist fitness verdicts."""
    try:
        fitness = json.loads(_FITNESS_JSON.read_text())
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"*Error loading fitness data: {e}*")
        print("Run: python3 tools/watchlist_fitness.py first")
        return

    portfolio = _load_portfolio()
    proposals = []

    for entry in fitness.get("tickers", []):
        ticker = entry.get("ticker")
        verdict = entry.get("verdict", "")
        tier = classify_tier(ticker, portfolio)

        # REMOVE verdict → propose drop or demote
        if verdict == "REMOVE":
            if tier == "ENGAGED":
                proposals.append({"ticker": ticker, "action": "demote",
                                  "from": tier, "to": "SCOUTING", "reason": "Fitness: REMOVE"})
            elif tier == "SCOUTING":
                proposals.append({"ticker": ticker, "action": "drop",
                                  "from": tier, "to": "DROPPED", "reason": "Fitness: REMOVE"})

        # ENGAGE verdict → propose promote
        elif verdict == "ENGAGE":
            if tier == "SCOUTING":
                proposals.append({"ticker": ticker, "action": "promote",
                                  "from": tier, "to": "ENGAGED", "reason": "Fitness: ENGAGE"})

    if args.json:
        print(json.dumps({"proposals": proposals}, indent=2))
        return

    if not proposals:
        print("No rebalancing needed — all tiers match fitness verdicts.")
        return

    print("# Rebalance Proposals")
    print(f"*Based on watchlist-fitness.json*\n")
    print("| # | Ticker | Action | From | To | Reason |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- |")
    for i, p in enumerate(proposals, 1):
        print(f"| {i} | {p['ticker']} | {p['action']} | {p['from']} | {p['to']} | {p['reason']} |")

    print(f"\n*{len(proposals)} proposals. Review and apply with promote/demote/drop commands.*")


def main():
    parser = argparse.ArgumentParser(description="Watchlist Manager — tiered monitoring")
    parser.add_argument("--json", action="store_true", help="JSON output")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Show tier distribution")
    promote_p = sub.add_parser("promote", help="Promote ticker to higher tier")
    promote_p.add_argument("tickers", nargs="+")
    demote_p = sub.add_parser("demote", help="Demote ticker to lower tier")
    demote_p.add_argument("tickers", nargs="+")
    drop_p = sub.add_parser("drop", help="Remove from watchlist")
    drop_p.add_argument("tickers", nargs="+")
    sub.add_parser("rebalance", help="Auto from fitness scores")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status(args)
    elif args.command == "promote":
        cmd_promote(args)
    elif args.command == "demote":
        cmd_demote(args)
    elif args.command == "drop":
        cmd_drop(args)
    elif args.command == "rebalance":
        cmd_rebalance(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
