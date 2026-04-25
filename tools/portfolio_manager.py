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
import os
import shutil
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import fcntl

# Sibling imports (tools/ directory)
from trading_calendar import last_trading_day
from shared_constants import MATCH_TOLERANCE

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"
TRADE_HISTORY_PATH = _ROOT / "trade_history.json"
LOCK_PATH = _ROOT / ".portfolio.lock"

TODAY = last_trading_day().isoformat()
_LOCK_DEPTH = 0


class StateValidationError(ValueError):
    """Raised when portfolio/trade-history JSON does not match expected shape."""


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require(condition, message):
    if not condition:
        raise StateValidationError(message)


@contextmanager
def _state_lock():
    """Process-level lock for portfolio and trade-history mutations."""
    global _LOCK_DEPTH
    if _LOCK_DEPTH > 0:
        _LOCK_DEPTH += 1
        try:
            yield
        finally:
            _LOCK_DEPTH -= 1
        return

    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_PATH, "a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        _LOCK_DEPTH = 1
        try:
            yield
        finally:
            _LOCK_DEPTH = 0
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _backup_existing(path):
    if not path.exists():
        return None
    backup = path.with_name(f"{path.name}.bak.{_timestamp()}")
    # Avoid collisions in fast tests or repeated same-second writes.
    if backup.exists():
        backup = path.with_name(f"{path.name}.bak.{_timestamp()}.{os.getpid()}")
    shutil.copy2(path, backup)
    return backup


def _atomic_write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp.{os.getpid()}.{int(time.time() * 1000)}")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        try:
            dir_fd = os.open(str(path.parent), os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _load_json_or_recover(path, empty_payload):
    if not path.exists():
        return empty_payload
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        corrupt = path.with_name(f"{path.name}.corrupt.{_timestamp()}")
        path.rename(corrupt)
        print(f"Warning: renamed corrupt JSON to {corrupt}", file=sys.stderr)
        return empty_payload


def _validate_order(order, path):
    _require(isinstance(order, dict), f"{path}: order must be an object")
    _require(order.get("type") in ("BUY", "SELL"), f"{path}: type must be BUY or SELL")
    _require(_is_number(order.get("price")), f"{path}: price must be numeric")
    _require(order["price"] >= 0, f"{path}: price must be non-negative")
    if "shares" in order:
        _require(_is_number(order["shares"]), f"{path}: shares must be numeric")
        _require(order["shares"] >= 0, f"{path}: shares must be non-negative")
    if "note" in order:
        _require(isinstance(order["note"], str), f"{path}: note must be a string")
    for key in ("placed", "filled"):
        if key in order:
            _require(isinstance(order[key], bool), f"{path}: {key} must be boolean")


def _validate_position(pos, path):
    _require(isinstance(pos, dict), f"{path}: position must be an object")
    for key in ("shares", "avg_cost"):
        _require(_is_number(pos.get(key, 0)), f"{path}.{key}: must be numeric")
        _require(pos.get(key, 0) >= 0, f"{path}.{key}: must be non-negative")
    if "target_exit" in pos and pos["target_exit"] is not None:
        _require(_is_number(pos["target_exit"]), f"{path}.target_exit: must be numeric or null")
    if "fill_prices" in pos:
        _require(isinstance(pos["fill_prices"], list), f"{path}.fill_prices: must be a list")
        for i, price in enumerate(pos["fill_prices"]):
            _require(_is_number(price), f"{path}.fill_prices[{i}]: must be numeric")
    if "note" in pos:
        _require(isinstance(pos["note"], str), f"{path}.note: must be a string")
    if "entry_date" in pos:
        _require(isinstance(pos["entry_date"], str), f"{path}.entry_date: must be a string")
    if "winding_down" in pos:
        _require(isinstance(pos["winding_down"], bool), f"{path}.winding_down: must be boolean")


def validate_portfolio(data):
    _require(isinstance(data, dict), "portfolio root must be an object")
    positions = data.setdefault("positions", {})
    pending = data.setdefault("pending_orders", {})
    watchlist = data.setdefault("watchlist", [])
    _require(isinstance(positions, dict), "positions must be an object")
    _require(isinstance(pending, dict), "pending_orders must be an object")
    _require(isinstance(watchlist, list), "watchlist must be a list")
    for i, ticker in enumerate(watchlist):
        _require(isinstance(ticker, str), f"watchlist[{i}] must be a string")
    for ticker, pos in positions.items():
        _require(isinstance(ticker, str), "position ticker keys must be strings")
        _validate_position(pos, f"positions.{ticker}")
    for ticker, orders in pending.items():
        _require(isinstance(ticker, str), "pending_orders ticker keys must be strings")
        _require(isinstance(orders, list), f"pending_orders.{ticker}: must be a list")
        for i, order in enumerate(orders):
            _validate_order(order, f"pending_orders.{ticker}[{i}]")
    return data


def validate_trade_history(history):
    _require(isinstance(history, dict), "trade history root must be an object")
    trades = history.setdefault("trades", [])
    _require(isinstance(trades, list), "trade history trades must be a list")
    for i, trade in enumerate(trades):
        _require(isinstance(trade, dict), f"trades[{i}] must be an object")
        if "id" in trade:
            _require(isinstance(trade["id"], int), f"trades[{i}].id must be an integer")
        if "ticker" in trade:
            _require(isinstance(trade["ticker"], str), f"trades[{i}].ticker must be a string")
        if "side" in trade:
            _require(trade["side"] in ("BUY", "SELL"), f"trades[{i}].side must be BUY or SELL")
        for key in ("shares", "price"):
            if key in trade:
                _require(_is_number(trade[key]), f"trades[{i}].{key} must be numeric")
    return history


# ---------------------------------------------------------------------------
# Trade history ledger
# ---------------------------------------------------------------------------

def _record_trade(trade_dict):
    """Append a trade record to trade_history.json (auto-creates file).

    If the file exists but contains corrupt JSON, renames it to
    trade_history.json.corrupt and starts fresh so future trades
    are not permanently blocked.
    """
    with _state_lock():
        history = _load_json_or_recover(TRADE_HISTORY_PATH, {"trades": []})
        try:
            validate_trade_history(history)
        except StateValidationError:
            corrupt = TRADE_HISTORY_PATH.with_name(f"{TRADE_HISTORY_PATH.name}.corrupt.{_timestamp()}")
            if TRADE_HISTORY_PATH.exists():
                TRADE_HISTORY_PATH.rename(corrupt)
                print(f"Warning: renamed invalid trade history to {corrupt}", file=sys.stderr)
            history = {"trades": []}
        trades = history.setdefault("trades", [])
        trade_dict["id"] = max((t.get("id", 0) for t in trades if isinstance(t, dict)), default=0) + 1
        trades.append(trade_dict)
        validate_trade_history(history)
        _backup_existing(TRADE_HISTORY_PATH)
        _atomic_write_json(TRADE_HISTORY_PATH, history)


# ---------------------------------------------------------------------------
# Portfolio I/O
# ---------------------------------------------------------------------------

def _load():
    with _state_lock():
        data = _load_json_or_recover(PORTFOLIO_PATH, {
            "positions": {},
            "pending_orders": {},
            "watchlist": [],
        })
        return validate_portfolio(data)


def _save(data):
    with _state_lock():
        data["last_updated"] = TODAY
        validate_portfolio(data)
        _backup_existing(PORTFOLIO_PATH)
        _atomic_write_json(PORTFOLIO_PATH, data)


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


def _repair_shell_expanded_note_price(note, order_price):
    """Repair notes like `$129.79` that the shell delivered as `29.79`."""
    if not note or order_price < 100:
        return note

    match = re.search(r"(—\s+)(?!\$)(\d{1,2}(?:\.\d+)?)(\s+[A-Za-z+]+)", note)
    if not match:
        return note

    observed_text = match.group(2)
    try:
        observed = float(observed_text)
    except ValueError:
        return note
    if observed >= 100:
        return note

    candidates = []
    for prefix in "123456789":
        try:
            candidate = float(f"{prefix}{observed_text}")
        except ValueError:
            continue
        if candidate < 100:
            continue
        distance = abs(candidate - order_price) / order_price
        candidates.append((distance, candidate))

    if not candidates:
        return note
    distance, repaired = min(candidates, key=lambda item: item[0])
    if distance > 0.20:
        return note

    replacement = f"{match.group(1)}${repaired:.2f}{match.group(3)}"
    return note[:match.start()] + replacement + note[match.end():]


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
    _zone_match = _re.search(r'\b(F[1-9]|A[1-5]|B[1-5]|R[1-3])\b', matched_note)
    zone_label = _zone_match.group(1) if _zone_match else None
    is_upper_zone = zone_label in ("F1", "F2", "A1", "A2") if zone_label else False
    is_daily_range = "dip-buy" in matched_note.lower() or "daily-range" in matched_note.lower()

    # Increment bullets_used
    pos_note = pos.get("note", "")
    pos["bullets_used"] = _increment_bullets_used(old_bullets, pos_note, zone)

    # Set entry_date if first fill (shares were 0)
    if old_shares == 0:
        pos["entry_date"] = fill_date

    _save(data)

    try:
        record = {
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
        }
        if getattr(args, "auto_detected", False):
            record["auto_detected"] = True
        _record_trade(record)
    except Exception as e:
        print(f"Warning: trade history not recorded: {e}", file=sys.stderr)

    try:
        from prediction_ledger import link_fill
        link_fill(ticker, price, shares, fill_date)
    except Exception as e:
        print(f"Warning: prediction ledger fill link failed: {e}", file=sys.stderr)

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

        # Remove SELL orders + filled BUY orders (keep unfilled placed BUYs for re-entry)
        sell_removed = 0
        remaining = []
        for order in orders:
            if order["type"] == "SELL":
                sell_removed += 1
            elif order.get("filled"):
                pass  # drop filled BUY orders on position close
            else:
                remaining.append(order)
        pending[ticker] = remaining

        # If winding down: full cleanup — drop from watchlist + remove position
        if pos.get("winding_down"):
            watchlist = data.get("watchlist", [])
            if ticker in watchlist:
                watchlist.remove(ticker)
                data["watchlist"] = sorted(watchlist)
                print(f"  {ticker} dropped from watchlist (winding down, position closed)")
            # Remove position entry entirely
            del positions[ticker]
            # Remove any remaining pending orders
            if ticker in pending:
                del pending[ticker]

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

        try:
            from prediction_ledger import link_sell
            link_sell(ticker, price, shares, sell_date,
                      pnl_pct=round(pct_change, 1), exit_reason="Full close")
        except Exception as e:
            print(f"Warning: prediction ledger sell link failed: {e}", file=sys.stderr)

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

        try:
            from prediction_ledger import link_sell
            link_sell(ticker, price, shares, sell_date,
                      pnl_pct=pct_change_partial, exit_reason="Partial sell")
        except Exception as e:
            print(f"Warning: prediction ledger sell link failed: {e}", file=sys.stderr)

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
    note = _repair_shell_expanded_note_price(args.note, args.price)

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
        "note": note,
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
    print(f"| Note | {note} |")
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
# Transactional entry points for imported callers
# ---------------------------------------------------------------------------

def _run_transaction(command_name, args):
    """Load fresh state, migrate, dispatch, and persist under one state lock."""
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
    if command_name not in commands:
        raise ValueError(f"unknown portfolio command: {command_name}")

    with _state_lock():
        data = _load()
        data = _migrate_legacy(data)
        commands[command_name](data, args)


def record_fill(args):
    """Transactionally record a fill using fresh portfolio state."""
    _run_transaction("fill", args)


def record_sell(args):
    """Transactionally record a sell using fresh portfolio state."""
    _run_transaction("sell", args)


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
    fill_p.add_argument("--shares", type=float, required=True)
    fill_p.add_argument("--trade-date", type=str, default=None, dest="trade_date")

    # sell TICKER --price P --shares N
    sell_p = subparsers.add_parser("sell")
    sell_p.add_argument("ticker")
    sell_p.add_argument("--price", type=float, required=True)
    sell_p.add_argument("--shares", type=float, required=True)
    sell_p.add_argument("--trade-date", type=str, default=None, dest="trade_date")

    # order TICKER --type T --price P --shares N --note "..." [--placed]
    order_p = subparsers.add_parser("order")
    order_p.add_argument("ticker")
    order_p.add_argument("--type", required=True, choices=["BUY", "SELL"])
    order_p.add_argument("--price", type=float, required=True)
    order_p.add_argument("--shares", type=float, required=True)
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

    _run_transaction(args.command, args)


if __name__ == "__main__":
    main()
