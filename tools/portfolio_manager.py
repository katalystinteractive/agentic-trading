"""Portfolio manager: CRUD operations for portfolio.json.

Mechanizes all writes so the LLM never edits portfolio.json directly.

Usage:
    python3 tools/portfolio_manager.py fill TICKER --price 22.31 --shares 2
    python3 tools/portfolio_manager.py sell TICKER --price 45.65 --shares 7
    python3 tools/portfolio_manager.py order TICKER --type BUY --price 20.32 --shares 1 --note "A1"
    python3 tools/portfolio_manager.py cancel TICKER --price 37.56
    python3 tools/portfolio_manager.py watch TICKER
    python3 tools/portfolio_manager.py unwatch TICKER
    python3 tools/portfolio_manager.py place TICKER --price 3.88
    python3 tools/portfolio_manager.py unpause TICKER
"""
import sys
import json
import re
import argparse
import shutil
from datetime import date
from pathlib import Path

# Sibling imports (tools/ directory)
from trading_calendar import last_trading_day
from shared_constants import MATCH_TOLERANCE

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"
BACKUP_PATH = _ROOT / "portfolio.json.bak"
TRADE_HISTORY_PATH = _ROOT / "trade_history.json"

TODAY = last_trading_day().isoformat()


# ---------------------------------------------------------------------------
# Trade history ledger
# ---------------------------------------------------------------------------

def _record_trade(trade_dict):
    """Append a trade record to trade_history.json (auto-creates file).

    If the file exists but contains corrupt JSON, renames it to
    trade_history.json.corrupt and starts fresh so future trades
    are not permanently blocked.
    """
    if TRADE_HISTORY_PATH.exists():
        try:
            with open(TRADE_HISTORY_PATH, "r", encoding="utf-8") as f:
                history = json.load(f)
            if not isinstance(history, dict):
                raise ValueError("JSON root is not a dict")
        except (json.JSONDecodeError, ValueError):
            ts = date.today().isoformat()
            corrupt = TRADE_HISTORY_PATH.with_name(f"trade_history.json.corrupt.{ts}")
            TRADE_HISTORY_PATH.rename(corrupt)
            history = {"trades": []}
    else:
        history = {"trades": []}
    trades = history.setdefault("trades", [])
    if not isinstance(trades, list):
        history["trades"] = []
        trades = history["trades"]
    trade_dict["id"] = max((t.get("id", 0) for t in trades if isinstance(t, dict)), default=0) + 1
    trades.append(trade_dict)
    with open(TRADE_HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# Portfolio I/O
# ---------------------------------------------------------------------------

def _load():
    with open(PORTFOLIO_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(data):
    shutil.copy2(PORTFOLIO_PATH, BACKUP_PATH)
    data["last_updated"] = TODAY
    with open(PORTFOLIO_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _match_order(orders, price, tolerance=None):
    """Find order matching price within tolerance (default ±0.5%).

    Returns (index, order) or (None, None).
    """
    if tolerance is None:
        tolerance = MATCH_TOLERANCE
    for i, order in enumerate(orders):
        if order["price"] == 0:
            continue
        if abs(order["price"] - price) / order["price"] <= tolerance:
            return i, order
    return None, None


def _is_filled_order(order):
    """Check if order is a legacy filled marker: '(filled 20...' date-prefixed pattern."""
    return "(filled 20" in order.get("note", "")


def parse_bullets_used(raw, position_note=""):
    """Handle int (4), string ('3 active + R1'), or pre-strategy string.

    Mirrors bullet_recommender.py lines 44-60.
    """
    if isinstance(raw, (int, float)):
        note_lower = position_note.lower()
        is_pre = "pre-strategy" in note_lower or "recovery mode" in note_lower
        return {"active": int(raw), "reserve": 0, "pre_strategy": is_pre}
    if isinstance(raw, str):
        is_pre = "pre-strategy" in raw.lower()
        m = re.match(r'(\d+)', raw)
        active = int(m.group(1)) if m else 0
        reserve = len(re.findall(r'R\d+', raw))
        return {"active": active, "reserve": reserve, "pre_strategy": is_pre}
    return {"active": 0, "reserve": 0, "pre_strategy": False}


def _serialize_bullets_used(parsed):
    """Reverse of parse — converts dict back to portfolio.json format."""
    active = parsed["active"]
    reserve = parsed["reserve"]
    pre = parsed["pre_strategy"]

    if reserve == 0 and not pre:
        return active  # plain int
    if reserve == 0 and pre:
        return f"{active} active (pre-strategy)"

    reserve_str = " + ".join(f"R{i}" for i in range(1, reserve + 1))
    base = f"{active} active + {reserve_str}"
    if pre:
        base += " (pre-strategy)"
    return base


def _increment_bullets_used(current_value, position_note="", zone="active"):
    """Increment bullets_used respecting polymorphic format and zone."""
    parsed = parse_bullets_used(current_value, position_note)

    if zone == "reserve":
        parsed["reserve"] += 1
    else:
        parsed["active"] += 1

    return _serialize_bullets_used(parsed)


def _fmt_dollar(val):
    if val is None:
        return "N/A"
    if not isinstance(val, (int, float)):
        return str(val)
    return f"${val:.2f}"


def _print_table(rows):
    """Print a markdown table from list of (field, before, after) tuples."""
    print("| Field | Before | After |")
    print("| :--- | :--- | :--- |")
    for field, before, after in rows:
        print(f"| {field} | {before} | {after} |")


# ---------------------------------------------------------------------------
# Legacy migration — idempotent, runs every invocation but is a no-op
# after stale orders are cleaned
# ---------------------------------------------------------------------------

def _migrate_legacy(data):
    """Remove stale filled pending orders that are already recorded in fill_prices."""
    positions = data.get("positions", {})
    pending = data.get("pending_orders", {})
    migrated = []

    for ticker, pos in positions.items():
        fill_prices = pos.get("fill_prices", [])
        if not fill_prices:
            continue
        orders = pending.get(ticker, [])
        if not orders:
            continue

        to_remove = []
        for i, order in enumerate(orders):
            if not _is_filled_order(order):
                continue
            # Check if order price matches any fill_price
            for fp in fill_prices:
                if fp == 0:
                    continue
                if abs(order["price"] - fp) / fp <= MATCH_TOLERANCE:
                    to_remove.append(i)
                    break

        if to_remove:
            for idx in sorted(to_remove, reverse=True):
                orders.pop(idx)
            pending[ticker] = orders
            migrated.append(f"*Migrated {ticker}: removed {len(to_remove)} stale filled order(s) from pending_orders.*")

    if migrated:
        for msg in migrated:
            print(msg)
        _save(data)

    return data


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_fill(data, args):
    ticker = args.ticker.upper()
    price = args.price
    shares = args.shares
    fill_date = getattr(args, "trade_date", None) or TODAY

    if shares <= 0:
        print(f"*Error: shares must be positive (got {shares}).*")
        sys.exit(1)
    positions = data.setdefault("positions", {})
    pending = data.setdefault("pending_orders", {})
    watchlist = data.setdefault("watchlist", [])

    # Auto-create position if missing
    if ticker not in positions:
        was_on_watchlist = ticker in watchlist
        positions[ticker] = {
            "shares": 0,
            "avg_cost": 0,
            "bullets_used": 0,
            "entry_date": fill_date,
            "target_exit": None,
            "fill_prices": [],
            "note": "",
        }
        if not was_on_watchlist:
            watchlist.append(ticker)
        if ticker not in pending:
            pending[ticker] = []
        if not was_on_watchlist:
            print(f"*Created new position for {ticker} (was not on watchlist).*")
        else:
            print(f"*Created new position for {ticker}.*")

    pos = positions[ticker]
    old_shares = pos.get("shares", 0)
    old_avg = pos.get("avg_cost", 0)
    old_fill_prices = list(pos.get("fill_prices", []))
    old_bullets = pos.get("bullets_used", 0)

    # Recalc avg
    total_shares = old_shares + shares
    if total_shares > 0:
        new_avg = round((old_shares * old_avg + shares * price) / total_shares, 2)
    else:
        new_avg = 0

    pos["shares"] = total_shares
    pos["avg_cost"] = new_avg

    # Append to fill_prices (one entry per fill event)
    fill_prices = pos.setdefault("fill_prices", [])
    fill_prices.append(price)

    # Find and remove matching BUY pending order (skip SELLs)
    orders = pending.get(ticker, [])
    buy_orders = [(i, o) for i, o in enumerate(orders) if o["type"] == "BUY"]
    buy_only = [o for _, o in buy_orders]
    match_idx, matched_order = _match_order(buy_only, price)
    if match_idx is None:
        # Fallback: try 2% tolerance for market order slippage
        match_idx, matched_order = _match_order(buy_only, price, tolerance=0.02)
        if match_idx is not None:
            print(f"*Note: matched within 2% (order ${matched_order['price']:.2f}, fill ${price:.2f}).*")
    zone = "active"  # default

    if match_idx is not None:
        # Map back to original index in orders list
        idx = buy_orders[match_idx][0]
        matched_note = matched_order.get("note", "")
        if "reserve" in matched_note.lower():
            zone = "reserve"
        orders.pop(idx)
        pending[ticker] = orders
    else:
        idx = None
        matched_note = ""
        print(f"*Warning: no matching pending order found for {ticker} @ {_fmt_dollar(price)}.*")

    # Detect zone label for dual exit routing
    import re as _re
    _zone_match = _re.search(r'\b(A[1-5]|B[1-5]|R[1-3])\b', matched_note)
    zone_label = _zone_match.group(1) if _zone_match else None
    is_upper_zone = zone_label in ("A1", "A2") if zone_label else False
    is_daily_range = "dip-buy" in matched_note.lower() or "daily-range" in matched_note.lower()

    # Increment bullets_used
    pos_note = pos.get("note", "")
    pos["bullets_used"] = _increment_bullets_used(old_bullets, pos_note, zone)

    # Set entry_date if first fill (shares were 0)
    if old_shares == 0:
        pos["entry_date"] = fill_date

    _save(data)

    try:
        _record_trade({
            "ticker": ticker,
            "side": "BUY",
            "date": fill_date,
            "shares": shares,
            "price": round(price, 2),
            "avg_cost_before": round(old_avg, 2),
            "avg_cost_after": round(new_avg, 2),
            "total_shares_after": total_shares,
            "zone": zone,
            "note": matched_note,
        })
    except Exception as e:
        print(f"Warning: trade history not recorded: {e}", file=sys.stderr)

    # Print confirmation
    _print_table([
        ("Shares", old_shares, total_shares),
        ("Avg Cost", _fmt_dollar(old_avg), _fmt_dollar(new_avg)),
        ("Fill Prices", str(old_fill_prices), str(fill_prices)),
        ("Bullets Used", old_bullets, pos["bullets_used"]),
        ("Pending Order", f"@ {_fmt_dollar(price)}" if idx is not None else "—",
         "Removed" if idx is not None else "No match"),
    ])

    # Auto-show sell targets after fill
    try:
        _tools_dir = str(Path(__file__).resolve().parent)
        if _tools_dir not in sys.path:
            sys.path.insert(0, _tools_dir)
        from sell_target_calculator import analyze_ticker
        print()
        print("---")
        print()
        analyze_ticker(ticker, data)
    except Exception as e:
        print(f"(Sell target error: {e})")

    # Same-day 4% exit advisory for upper-zone or daily-range fills
    if (is_upper_zone or is_daily_range) and zone != "reserve":
        same_day_price = round(price * 1.04, 2)
        print(f"\n*Same-day exit eligible: SELL @ ${same_day_price:.2f} (+4% from ${price:.2f} fill)*")

    # Auto-store fill event in knowledge store
    try:
        _tools_dir = str(Path(__file__).resolve().parent)
        if _tools_dir not in sys.path:
            sys.path.insert(0, _tools_dir)
        from knowledge_store import store_fill
        store_fill(ticker, price, shares, total_shares, new_avg, zone)
    except Exception:
        pass  # Non-critical


def cmd_sell(data, args):
    ticker = args.ticker.upper()
    price = args.price
    shares = args.shares
    sell_date = getattr(args, "trade_date", None) or TODAY

    if shares <= 0:
        print(f"*Error: shares must be positive (got {shares}).*")
        sys.exit(1)

    positions = data.get("positions", {})
    pending = data.setdefault("pending_orders", {})

    if ticker not in positions:
        print(f"*Error: no position found for {ticker}.*")
        sys.exit(1)

    pos = positions[ticker]
    old_shares = pos.get("shares", 0)
    old_avg = pos.get("avg_cost", 0)

    if shares > old_shares:
        print(f"*Error: cannot sell {shares} shares — only {old_shares} held.*")
        sys.exit(1)

    orders = pending.get(ticker, [])

    if shares == old_shares:
        # Full close
        pct_change = round((price - old_avg) / old_avg * 100, 1) if old_avg > 0 else 0
        sign = "+" if pct_change >= 0 else ""
        close_note = (f"Position closed {sell_date} — sold {shares} @ ${price:.2f} "
                      f"({sign}{pct_change}% from ${old_avg:.2f} avg).")

        old_note = pos.get("note", "")
        if old_note:
            pos["note"] = f"{old_note} {close_note}"
        else:
            pos["note"] = close_note

        old_bullets = pos["bullets_used"]
        old_fill_prices = list(pos.get("fill_prices", []))

        pos["shares"] = 0
        pos["avg_cost"] = 0
        pos["fill_prices"] = []
        pos["bullets_used"] = 0
        pos["target_exit"] = None

        # Remove matching SELL pending orders only
        sell_removed = 0
        remaining = []
        for order in orders:
            if order["type"] == "SELL":
                sell_removed += 1
            else:
                remaining.append(order)
        pending[ticker] = remaining

        _save(data)

        # zone omitted from SELL — position doesn't track per-share zone;
        # cross-reference BUY records in trade_history.json if needed.
        try:
            _record_trade({
                "ticker": ticker,
                "side": "SELL",
                "date": sell_date,
                "shares": shares,
                "price": round(price, 2),
                "avg_cost_before": round(old_avg, 2),
                "avg_cost_after": 0,
                "total_shares_after": 0,
                "pnl_pct": round(pct_change, 1),
                "note": "Full close",
            })
        except Exception as e:
            print(f"Warning: trade history not recorded: {e}", file=sys.stderr)

        _print_table([
            ("Shares", old_shares, 0),
            ("Avg Cost", _fmt_dollar(old_avg), _fmt_dollar(0)),
            ("Fill Prices", str(old_fill_prices), "[]"),
            ("Bullets Used", old_bullets, 0),
            ("Target Exit", _fmt_dollar(pos.get("target_exit")), "null"),
            ("Note", "", close_note),
            ("SELL Orders Removed", sell_removed, "—"),
            ("BUY Orders Kept", sum(1 for o in remaining if o["type"] == "BUY"), "—"),
        ])

        # Auto-store sell event in knowledge store
        try:
            _tools_dir = str(Path(__file__).resolve().parent)
            if _tools_dir not in sys.path:
                sys.path.insert(0, _tools_dir)
            from knowledge_store import store_sell
            store_sell(ticker, price, shares, old_avg, pct_change)
        except Exception:
            pass
    else:
        # Partial sell
        new_shares = old_shares - shares

        # Remove matching SELL pending orders only (fill_prices tracks buy fills — not updated on partial sell)
        sell_idx = None
        for i, order in enumerate(orders):
            if order["type"] == "SELL":
                if order["price"] == 0 or abs(order["price"] - price) / order["price"] <= MATCH_TOLERANCE:
                    sell_idx = i
                    break
        if sell_idx is not None:
            orders.pop(sell_idx)
            pending[ticker] = orders

        pos["shares"] = new_shares

        _save(data)

        pct_change_partial = round((price - old_avg) / old_avg * 100, 1) if old_avg > 0 else 0
        try:
            _record_trade({
                "ticker": ticker,
                "side": "SELL",
                "date": sell_date,
                "shares": shares,
                "price": round(price, 2),
                "avg_cost_before": round(old_avg, 2),
                "avg_cost_after": round(old_avg, 2),
                "total_shares_after": new_shares,
                "pnl_pct": pct_change_partial,
                "note": "Partial sell",
            })
        except Exception as e:
            print(f"Warning: trade history not recorded: {e}", file=sys.stderr)

        _print_table([
            ("Shares", old_shares, new_shares),
            ("Avg Cost", _fmt_dollar(old_avg), _fmt_dollar(old_avg) + " (unchanged)"),
            ("SELL Order Removed", f"@ {_fmt_dollar(price)}" if sell_idx is not None else "—",
             "Removed" if sell_idx is not None else "No match"),
        ])

        # Auto-store partial sell event in knowledge store
        try:
            _tools_dir = str(Path(__file__).resolve().parent)
            if _tools_dir not in sys.path:
                sys.path.insert(0, _tools_dir)
            from knowledge_store import store_partial_sell
            store_partial_sell(ticker, price, shares, new_shares)
        except Exception:
            pass


def cmd_order(data, args):
    ticker = args.ticker.upper()
    pending = data.setdefault("pending_orders", {})
    orders = pending.setdefault(ticker, [])

    # Check for duplicate within same type (skip filled orders)
    for order in orders:
        if order["type"] != args.type:
            continue
        if _is_filled_order(order):
            continue
        if order["price"] == 0:
            continue
        if abs(order["price"] - args.price) / order["price"] <= MATCH_TOLERANCE:
            print(f"*Error: duplicate order — existing {order['type']} @ {_fmt_dollar(order['price'])} "
                  f"(\"{order.get('note', '')}\")*")
            sys.exit(1)

    new_order = {
        "type": args.type,
        "price": args.price,
        "shares": args.shares,
        "note": args.note,
    }
    if args.placed:
        new_order["placed"] = True

    orders.append(new_order)

    _save(data)

    print(f"Added {args.type} order for {ticker}:")
    print("| Field | Value |")
    print("| :--- | :--- |")
    print(f"| Type | {args.type} |")
    print(f"| Price | {_fmt_dollar(args.price)} |")
    print(f"| Shares | {args.shares} |")
    print(f"| Note | {args.note} |")
    if args.placed:
        print(f"| Placed | true |")


def cmd_cancel(data, args):
    ticker = args.ticker.upper()
    pending = data.get("pending_orders", {})
    orders = pending.get(ticker, [])

    if not orders:
        print(f"*Error: no pending orders for {ticker}.*")
        sys.exit(1)

    idx, order = _match_order(orders, args.price)

    if idx is None:
        print(f"*Error: no order found matching {_fmt_dollar(args.price)} for {ticker}.*")
        sys.exit(1)

    if _is_filled_order(order):
        print(f"*Error: cannot cancel filled order @ {_fmt_dollar(order['price'])} "
              f"(\"{order.get('note', '')}\")*")
        sys.exit(1)

    removed = orders.pop(idx)
    pending[ticker] = orders

    _save(data)

    print(f"Cancelled order for {ticker}:")
    print("| Field | Value |")
    print("| :--- | :--- |")
    print(f"| Type | {removed['type']} |")
    print(f"| Price | {_fmt_dollar(removed['price'])} |")
    print(f"| Shares | {removed.get('shares', '—')} |")
    print(f"| Note | {removed.get('note', '')} |")


def cmd_watch(data, args):
    ticker = args.ticker.upper()
    watchlist = data.setdefault("watchlist", [])
    pending = data.setdefault("pending_orders", {})

    if ticker in watchlist:
        print(f"*Error: {ticker} is already on the watchlist.*")
        sys.exit(1)

    watchlist.append(ticker)
    if ticker not in pending:
        pending[ticker] = []

    _save(data)

    print(f"Added {ticker} to watchlist.")
    print(f"*Watchlist now has {len(watchlist)} tickers.*")


def cmd_unwatch(data, args):
    ticker = args.ticker.upper()
    watchlist = data.setdefault("watchlist", [])
    pending = data.setdefault("pending_orders", {})
    positions = data.get("positions", {})

    if ticker not in watchlist:
        print(f"*Error: {ticker} is not on the watchlist.*")
        sys.exit(1)

    # Warn if active position or orders
    pos = positions.get(ticker, {})
    if pos.get("shares", 0) > 0:
        print(f"*Warning: {ticker} has {pos['shares']} shares in position.*")
    orders = pending.get(ticker, [])
    if orders:
        print(f"*Warning: {ticker} has {len(orders)} pending order(s).*")

    watchlist.remove(ticker)
    if ticker in pending:
        del pending[ticker]

    _save(data)

    print(f"Removed {ticker} from watchlist.")


def cmd_place(data, args):
    ticker = args.ticker.upper()
    pending = data.get("pending_orders", {})
    orders = pending.get(ticker, [])

    if not orders:
        print(f"*Error: no pending orders for {ticker}.*")
        sys.exit(1)

    idx, order = _match_order(orders, args.price)

    if idx is None:
        print(f"*Error: no order found matching {_fmt_dollar(args.price)} for {ticker}.*")
        sys.exit(1)

    if _is_filled_order(order):
        print(f"*Error: order @ {_fmt_dollar(order['price'])} is already filled.*")
        sys.exit(1)

    old_placed = order.get("placed", False)
    order["placed"] = True

    _save(data)

    _print_table([
        ("Ticker", ticker, ticker),
        ("Price", _fmt_dollar(order["price"]), _fmt_dollar(order["price"])),
        ("Placed", str(old_placed), "True"),
    ])


def cmd_unpause(data, args):
    ticker = args.ticker.upper()
    pending = data.get("pending_orders", {})
    orders = pending.get(ticker, [])

    if not orders:
        print(f"*Error: no pending orders for {ticker}.*")
        sys.exit(1)

    affected = []
    for order in orders:
        old_note = order.get("note", "")
        note = old_note
        # Pattern 1: "PAUSED until post-earnings Mon 3" (most specific)
        note = re.sub(r'PAUSED\s+until\s+post-earnings\s+\w+\s+\d+', '', note, flags=re.IGNORECASE)
        note = re.sub(r'\s+', ' ', note).strip()
        # Pattern 2: "paused - reason" or "paused: reason" (before standalone to avoid orphaned ": reason")
        note = re.sub(r'\bpaused\s*[-:]\s*[^,]*', '', note, flags=re.IGNORECASE)
        note = re.sub(r'\s+', ' ', note).strip()
        # Pattern 3: standalone "PAUSED" (least specific, catches remaining)
        note = re.sub(r'\bPAUSED\b', '', note, flags=re.IGNORECASE)
        note = re.sub(r'\s+', ' ', note).strip()

        if note != old_note:
            affected.append((order, old_note, note))
            order["note"] = note

    if not affected:
        print(f"*No PAUSED orders found for {ticker}.*")
        return

    _save(data)

    print(f"Unpaused {len(affected)} order(s) for {ticker}:")
    print("| Price | Before | After |")
    print("| :--- | :--- | :--- |")
    for order, old_note, new_note in affected:
        print(f"| {_fmt_dollar(order['price'])} | {old_note} | {new_note} |")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Portfolio manager — CRUD for portfolio.json")
    subparsers = parser.add_subparsers(dest="command")

    # fill TICKER --price P --shares N
    fill_p = subparsers.add_parser("fill")
    fill_p.add_argument("ticker")
    fill_p.add_argument("--price", type=float, required=True)
    fill_p.add_argument("--shares", type=int, required=True)
    fill_p.add_argument("--trade-date", type=str, default=None, dest="trade_date")

    # sell TICKER --price P --shares N
    sell_p = subparsers.add_parser("sell")
    sell_p.add_argument("ticker")
    sell_p.add_argument("--price", type=float, required=True)
    sell_p.add_argument("--shares", type=int, required=True)
    sell_p.add_argument("--trade-date", type=str, default=None, dest="trade_date")

    # order TICKER --type T --price P --shares N --note "..." [--placed]
    order_p = subparsers.add_parser("order")
    order_p.add_argument("ticker")
    order_p.add_argument("--type", required=True, choices=["BUY", "SELL"])
    order_p.add_argument("--price", type=float, required=True)
    order_p.add_argument("--shares", type=int, required=True)
    order_p.add_argument("--note", default="")
    order_p.add_argument("--placed", action="store_true")

    # cancel TICKER --price P
    cancel_p = subparsers.add_parser("cancel")
    cancel_p.add_argument("ticker")
    cancel_p.add_argument("--price", type=float, required=True)

    # watch TICKER
    watch_p = subparsers.add_parser("watch")
    watch_p.add_argument("ticker")

    # unwatch TICKER
    unwatch_p = subparsers.add_parser("unwatch")
    unwatch_p.add_argument("ticker")

    # place TICKER --price P
    place_p = subparsers.add_parser("place")
    place_p.add_argument("ticker")
    place_p.add_argument("--price", type=float, required=True)

    # unpause TICKER
    unpause_p = subparsers.add_parser("unpause")
    unpause_p.add_argument("ticker")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Load and migrate
    data = _load()
    data = _migrate_legacy(data)

    # Dispatch
    commands = {
        "fill": cmd_fill,
        "sell": cmd_sell,
        "order": cmd_order,
        "cancel": cmd_cancel,
        "watch": cmd_watch,
        "unwatch": cmd_unwatch,
        "place": cmd_place,
        "unpause": cmd_unpause,
    }
    commands[args.command](data, args)


if __name__ == "__main__":
    main()
