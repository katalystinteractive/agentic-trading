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

        # VIX gate: suppress BUY alerts when VIX exceeds ticker's learned threshold
        if side == "BUY" and _vix_now is not None:
            _vix_gate = _entry_data.get(tk, {}).get("params", {}).get("per_ticker_vix_gate", 0)
            if _vix_gate > 0 and _vix_now > _vix_gate:
                continue  # VIX too high for this ticker

        # Distance calculation — positive means price is approaching but hasn't crossed
        if side == "BUY":
            distance = (current_price - order_price) / order_price * 100
        else:  # SELL
            distance = (order_price - current_price) / order_price * 100

        key = f"{tk}:{side}:{order_price}"
        active_keys.add(key)

        # Determine alert level
        if distance <= 0:
            level = "FILLED?"
        elif distance <= IMMINENT_PCT:
            level = "IMMINENT"
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
            LEVEL_RANK = {"APPROACHING": 1, "IMMINENT": 2, "FILLED?": 3}
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
    args = parser.parse_args()

    # Market hours check
    phase = get_market_phase()
    if phase in ("CLOSED", "PRE_MARKET", "AFTER_HOURS"):
        return  # silent exit outside market hours

    # Load orders
    orders = load_placed_orders()
    if not orders:
        return  # no placed orders to monitor

    tickers = list(set(o["ticker"] for o in orders))
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
    alerts = compute_alerts(orders, prices, state)

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
