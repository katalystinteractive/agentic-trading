"""Order proximity monitor — alerts when price approaches placed limit orders.

Runs every 5 minutes during market hours via cron. Sends email alerts when
price is within 2% (APPROACHING) or 1% (IMMINENT) of a placed limit order.
Suppresses duplicate alerts until price moves back beyond the outer threshold.

Usage:
    python3 tools/order_proximity_monitor.py           # normal run
    python3 tools/order_proximity_monitor.py --dry-run  # print without email
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yfinance as yf
from trading_calendar import get_market_phase
from notify import send_summary_email

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"
STATE_PATH = _ROOT / "data" / "proximity_alerts_state.json"

APPROACHING_PCT = 2.0
IMMINENT_PCT = 1.0
MAX_CONSECUTIVE_FAILURES = 3
ENTRY_SWEEP_PATH = _ROOT / "data" / "entry_sweep_results.json"


def _load_entry_sweep():
    """Load entry sweep results for VIX gate thresholds."""
    try:
        if ENTRY_SWEEP_PATH.exists():
            with open(ENTRY_SWEEP_PATH) as f:
                return json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    return {}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_placed_orders():
    """Extract all placed (not filled) limit orders from portfolio.json."""
    try:
        with open(PORTFOLIO_PATH) as f:
            portfolio = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"*Cannot load portfolio: {e}*", file=sys.stderr)
        return []

    orders = []
    for tk, tk_orders in portfolio.get("pending_orders", {}).items():
        for o in tk_orders:
            if o.get("placed") and not o.get("filled"):
                orders.append({
                    "ticker": tk,
                    "side": o["type"],
                    "price": o["price"],
                    "shares": o.get("shares", 0),
                })
    return orders


def load_monitored_levels():
    """Load unplaced bullet levels from wick analysis for proximity monitoring.

    Returns the NEXT unplaced level per ticker (within active_bullets_max window).
    Format matches load_placed_orders: {ticker, side, price, shares, monitored: True}
    """
    try:
        with open(PORTFOLIO_PATH) as f:
            portfolio = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []

    from shared_wick import parse_wick_active_levels
    from shared_utils import get_ticker_pool

    tracked = set(portfolio.get("watchlist", [])) | set(portfolio.get("positions", {}).keys())
    pending = portfolio.get("pending_orders", {})

    positions = portfolio.get("positions", {})
    monitored = []
    for tk in tracked:
        # Skip winding-down tickers
        pos = positions.get(tk, {})
        if pos.get("winding_down"):
            continue

        # Skip fully deployed tickers (capital exhausted)
        shares = pos.get("shares", 0)
        avg_cost = pos.get("avg_cost", 0)
        deployed = shares * avg_cost
        pool = get_ticker_pool(tk)
        active_pool = pool.get("active_pool", 300)
        if deployed >= active_pool:
            continue

        # Get placed + filled BUY prices to exclude
        placed_prices = set()
        filled_prices = set()
        for o in pending.get(tk, []):
            if o.get("type") == "BUY":
                if o.get("placed") and not o.get("filled"):
                    placed_prices.add(round(o["price"], 2))
                elif o.get("filled"):
                    filled_prices.add(round(o["price"], 2))

        # Also exclude fill_prices from position
        for fp in pos.get("fill_prices", []):
            filled_prices.add(round(fp, 2))

        levels = parse_wick_active_levels(tk)
        if not levels:
            continue

        max_bullets = pool.get("active_bullets_max") or 5
        placed_count = len(placed_prices)

        for lvl in levels:
            price = round(lvl["price"], 2)
            if price in placed_prices or price in filled_prices:
                continue  # already placed or already filled
            if placed_count >= max_bullets:
                break
            monitored.append({
                "ticker": tk,
                "side": "BUY",
                "price": price,
                "shares": 0,
                "monitored": True,
            })
            break  # only the NEXT unplaced level

    return monitored


def auto_record_fill(ticker, price, shares, dry_run=False):
    """Auto-record a detected fill via portfolio_manager record_fill.

    Returns (success: bool, summary: str) tuple.
    summary contains position update + sell targets for email.
    """
    if shares <= 0:
        return False, f"*{ticker}: shares={shares}, skipping auto-fill*"

    if dry_run:
        return True, f"[DRY RUN] Would record: {ticker} BUY {shares} @ ${price:.2f}"

    import io
    import contextlib

    args = argparse.Namespace(
        ticker=ticker,
        price=price,
        shares=shares,
        trade_date=None,
        auto_detected=True,
    )

    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            from portfolio_manager import record_fill
            record_fill(args)
        return True, buf.getvalue()
    except SystemExit:
        return False, f"*{ticker}: cmd_fill rejected fill @ ${price:.2f}*"
    except Exception as e:
        return False, f"*{ticker}: auto-fill error: {e}*"


def get_next_bullet(ticker):
    """Get next bullet recommendation for email cascade.

    Returns dict {level, price, shares} or None if no next bullet.
    Uses cached wick analysis (no yfinance download) to keep cron fast.
    """
    try:
        wick_path = _ROOT / "tickers" / ticker / "wick_analysis.md"
        if not wick_path.exists():
            return None

        import subprocess
        result = subprocess.run(
            [sys.executable, str(_ROOT / "tools" / "bullet_recommender.py"),
             ticker, "--mode", "recommend", "--json"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return None

        recs = json.loads(result.stdout)
        if not recs or not recs[0].get("recommendation"):
            return None
        rec = recs[0]["recommendation"]
        return {
            "level": rec.get("label", ""),
            "price": rec.get("level", {}).get("recommended_buy", 0),
            "shares": rec.get("shares", 0),
        }
    except Exception:
        return None


def fetch_prices(tickers):
    """Batch-fetch latest prices via yfinance. Returns {ticker: price} or None on failure."""
    try:
        import warnings
        warnings.filterwarnings("ignore")
        data = yf.download(tickers, period="1d", interval="5m",
                           progress=False, threads=True)
        if data.empty:
            return None
        prices = {}
        for tk in tickers:
            try:
                if len(tickers) == 1:
                    prices[tk] = float(data["Close"].iloc[-1])
                else:
                    prices[tk] = float(data["Close"][tk].iloc[-1])
            except (KeyError, IndexError):
                continue
        return prices if prices else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Alert computation
# ---------------------------------------------------------------------------

def compute_alerts(orders, prices, state):
    """Check each order for proximity alerts. Returns list of new alerts."""
    alerts = []
    active_keys = set()

    # Fetch current VIX once for BUY alert suppression (only if BUY orders exist)
    _vix_now = None
    _entry_data = {}
    _has_buys = any(o["side"] == "BUY" for o in orders)
    if _has_buys:
        _entry_data = _load_entry_sweep()
        try:
            import warnings
            warnings.filterwarnings("ignore")
            _vd = yf.download(["^VIX"], period="1d", interval="5m", progress=False)
            if not _vd.empty:
                try:
                    _vix_now = float(_vd["Close"]["^VIX"].iloc[-1])
                except (KeyError, TypeError):
                    _vix_now = float(_vd["Close"].iloc[-1])
        except Exception:
            pass

    for o in orders:
        tk, side, order_price = o["ticker"], o["side"], o["price"]
        current_price = prices.get(tk)
        if current_price is None:
            continue

        # Distance calculation — positive means price is approaching but hasn't crossed
        if side == "BUY":
            distance = (current_price - order_price) / order_price * 100
        else:  # SELL
            distance = (order_price - current_price) / order_price * 100

        # VIX gate: suppress BUY APPROACH/IMMINENT alerts when VIX exceeds threshold
        # BUT: never suppress FILLED? — a placed order fills regardless of VIX
        if distance > 0 and side == "BUY" and _vix_now is not None:
            _vix_gate = _entry_data.get(tk, {}).get("params", {}).get("per_ticker_vix_gate", 0)
            if _vix_gate > 0 and _vix_now > _vix_gate:
                continue

        key = f"{tk}:{side}:{order_price}"
        active_keys.add(key)

        # Determine alert level
        _is_monitored = o.get("monitored", False)
        if distance <= 0:
            level = "PLACE_NOW" if _is_monitored else "FILLED?"
        elif distance <= IMMINENT_PCT:
            level = "PLACE_NOW" if _is_monitored else "IMMINENT"
        elif distance <= APPROACHING_PCT:
            level = "APPROACHING"
        else:
            # Beyond threshold — do NOT reset state (one-way escalation only)
            # State clears only when the order is removed from portfolio.json
            continue

        # Check suppression — one-way escalation: APPROACHING → IMMINENT → FILLED?
        # Once a level is reached, same or lower levels never re-fire
        existing = state.get(key)
        if existing:
            existing_level = existing.get("level", "")
            # Define escalation order
            LEVEL_RANK = {"APPROACHING": 1, "IMMINENT": 2, "PLACE_NOW": 2, "FILLED?": 3}
            existing_rank = LEVEL_RANK.get(existing_level, 0)
            new_rank = LEVEL_RANK.get(level, 0)
            if new_rank <= existing_rank:
                continue  # same or lower level — suppress

        # New alert
        alerts.append({
            "ticker": tk,
            "side": side,
            "price": order_price,
            "current": current_price,
            "distance": max(distance, 0),
            "level": level,
            "shares": o["shares"],
        })
        state[key] = {
            "level": level,
            "alerted_at": datetime.now().isoformat(),
        }

        # Mark fill for auto-recording (handled by main() where args is in scope)
        # Only BUY fills — SELL fills use cmd_sell, not cmd_fill
        if level == "FILLED?" and side == "BUY" and not o.get("monitored"):
            state.setdefault("_auto_fills", []).append({
                "ticker": tk,
                "price": order_price,
                "shares": o.get("shares", 0),
            })

    # Clean up state entries for orders that no longer exist
    stale_keys = [k for k in state if not k.startswith("_") and k not in active_keys]
    for k in stale_keys:
        del state[k]

    return alerts


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_state():
    """Load suppression state. Remove entries older than 24 hours."""
    if not STATE_PATH.exists():
        return {}
    try:
        with open(STATE_PATH) as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    # Cleanup stale entries (>24h old)
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    stale = [k for k, v in state.items()
             if not k.startswith("_") and v.get("alerted_at", "") < cutoff]
    for k in stale:
        del state[k]

    return state


def save_state(state):
    """Write suppression state to disk."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# Email formatting
# ---------------------------------------------------------------------------

def format_email(alerts):
    """Format alerts as plain-text aligned columns."""
    lines = []
    for a in sorted(alerts, key=lambda x: x["distance"]):
        lines.append(
            f"  {a['ticker']:<6s} {a['side']:<4s} "
            f"${a['price']:<8.2f} -> ${a['current']:<8.2f} "
            f"{a['distance']:>5.1f}%  {a['level']}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Order Proximity Monitor")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print alerts without sending email")
    parser.add_argument("--auto-fill-dry-run", action="store_true",
                        help="Log detected fills without recording them")
    parser.add_argument("--enable-auto-fill", action="store_true",
                        help="Opt in to auto-recording fills via cmd_fill at the order's limit price. "
                             "OFF by default — auto-fill was found to create phantom fills when the "
                             "order wasn't actually live at the broker, or when the broker's real "
                             "fill price was better than the limit. Leave off unless you've verified "
                             "the monitor's detection is reliable for your setup.")
    args = parser.parse_args()

    # Market hours check
    phase = get_market_phase()
    if phase in ("CLOSED", "PRE_MARKET", "AFTER_HOURS"):
        return  # silent exit outside market hours

    # Load placed orders + monitored (unplaced) bullet levels
    orders = load_placed_orders()
    monitored = load_monitored_levels()
    all_orders = orders + monitored
    if not all_orders:
        return  # nothing to monitor

    tickers = list(set(o["ticker"] for o in all_orders))
    state = load_state()

    # Fetch prices
    prices = fetch_prices(tickers)
    if prices is None:
        # Track consecutive failures
        failures = state.get("_failures", 0) + 1
        state["_failures"] = failures
        if failures >= MAX_CONSECUTIVE_FAILURES and not state.get("_degraded_alerted"):
            if not args.dry_run:
                send_summary_email("Order Monitor — Degraded",
                                   f"yfinance failed {failures} consecutive times. "
                                   f"Price monitoring is not running.")
            state["_degraded_alerted"] = True
        save_state(state)
        print(f"yfinance failed (consecutive: {failures})", file=sys.stderr)
        return

    # Reset failure counter on success
    state.pop("_failures", None)
    state.pop("_degraded_alerted", None)

    # Compute alerts
    alerts = compute_alerts(all_orders, prices, state)

    # Auto-record detected fills — OFF by default (see --enable-auto-fill).
    # Reason: this loop calls cmd_fill with the order's LIMIT price as the fill
    # price, creating phantom fills when (a) the order isn't actually live at
    # the broker, or (b) the broker executes at a better price than the limit
    # and the user later records the real fill, double-counting the position.
    # Drain the queue unconditionally so stale entries don't accumulate across
    # runs, but only execute when explicitly opted in.
    _auto_fills_raw = state.pop("_auto_fills", [])
    _auto_fill_results = []
    if args.enable_auto_fill:
        for af in _auto_fills_raw:
            success, summary = auto_record_fill(
                af["ticker"], af["price"], af["shares"],
                dry_run=args.auto_fill_dry_run or args.dry_run,
            )
            next_bullet = get_next_bullet(af["ticker"]) if success else None
            _auto_fill_results.append({
                **af,
                "success": success,
                "summary": summary,
                "next_bullet": next_bullet,
            })
            _is_dry = args.auto_fill_dry_run or args.dry_run
            action = "dry-run" if _is_dry else ("recorded" if success else "FAILED")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Auto-fill {action}: "
                  f"{af['ticker']} {af['shares']} @ ${af['price']:.2f}")

        if _auto_fill_results and not args.dry_run and not args.auto_fill_dry_run:
            from notify import send_fill_cascade_alert
            send_fill_cascade_alert(_auto_fill_results)
    elif _auto_fills_raw:
        # Auto-fill disabled — log what would have been recorded, but don't touch state.
        # The FILLED? alerts below still email the user so they can verify at broker
        # and manually run: python3 tools/portfolio_manager.py fill TICKER --price X --shares N
        for af in _auto_fills_raw:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Auto-fill DISABLED (no action): "
                  f"{af['ticker']} {af['shares']} @ ${af['price']:.2f} — verify at broker + manually fill")

    if alerts:
        body = format_email(alerts)
        if len(alerts) == 1:
            a = alerts[0]
            subject = f"{a['level']}: {a['ticker']} {a['side']} @ ${a['price']:.2f} — ${a['current']:.2f} ({a['distance']:.1f}%)"
        else:
            subject = f"Order Alerts: {len(alerts)} approaching"

        print(f"[{datetime.now().strftime('%H:%M:%S')}] {len(alerts)} alert(s):")
        print(body)

        if not args.dry_run:
            send_summary_email(subject, body)
    else:
        # No alerts — silent (runs every 5 min, don't spam logs)
        pass

    save_state(state)


if __name__ == "__main__":
    main()
