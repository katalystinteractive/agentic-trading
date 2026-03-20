"""Broker Reconciliation — per-ticker reconciliation of portfolio state vs broker.

Shows fills, limit BUY/SELL orders with action flags (OK/ADJUST/CANCEL/PLACE),
available bullets, and a consolidated action summary.

Usage:
    python3 tools/broker_reconciliation.py              # all active tickers
    python3 tools/broker_reconciliation.py CIFR LUNR     # specific tickers
"""
import sys
import json
import io
import contextlib
import warnings
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"
TRADE_HISTORY_PATH = _ROOT / "trade_history.json"
PROFILES_PATH = _ROOT / "ticker_profiles.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared_constants import MATCH_TOLERANCE
from shared_utils import is_active_buy as _is_active_buy, is_active_sell as _is_active_sell

SELL_DEFAULT_PCT = 6.0
FILL_MATCH_TOLERANCE = 0.001  # 0.1% — tighter than MATCH_TOLERANCE


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_portfolio():
    with open(PORTFOLIO_PATH, "r") as f:
        return json.load(f)


def _load_profiles():
    try:
        with open(PROFILES_PATH, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _load_trade_history_buys():
    """Load trade_history.json, return dict[ticker -> list[BUY trades]] sorted by date."""
    try:
        with open(TRADE_HISTORY_PATH, "r") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    result = {}
    for trade in data.get("trades", []):
        if trade.get("side") != "BUY":
            continue
        ticker = trade.get("ticker", "")
        result.setdefault(ticker, []).append(trade)
    # Sort by date then id for stable ordering
    for ticker in result:
        result[ticker].sort(key=lambda t: (t.get("date", ""), t.get("id", 0)))
    return result


# ---------------------------------------------------------------------------
# Bullet recommender integration
# ---------------------------------------------------------------------------

def _get_bullet_ctx(ticker, portfolio, cap):
    """Get bullet recommender ctx via direct import, suppressing print output.

    ALL stdout from run_recommend() is suppressed — reconciliation only needs
    the ctx dict, not console output.
    """
    try:
        from wick_offset_analyzer import analyze_stock_data
        data, err = analyze_stock_data(ticker)
        if data is None:
            return None
        from bullet_recommender import run_recommend
        with contextlib.redirect_stdout(io.StringIO()):
            ctx = run_recommend(ticker, "any", data, portfolio, cap)
        return ctx
    except (FileNotFoundError, ValueError, KeyError):
        return None
    except Exception as e:
        warnings.warn(f"broker_reconciliation: unexpected error for {ticker}: {e}")
        return None


# ---------------------------------------------------------------------------
# Fill date matching
# ---------------------------------------------------------------------------

def match_fills_to_history(fill_prices, trade_buys):
    """Match position fill_prices to trade_history BUY records.

    Greedy matching: for each fill_price, find first unmatched trade
    within FILL_MATCH_TOLERANCE. Returns list of {date, price, shares, zone}.
    """
    matched_indices = set()
    results = []
    for fp in fill_prices:
        if fp == 0:
            continue
        found = False
        for i, trade in enumerate(trade_buys):
            if i in matched_indices:
                continue
            if abs(trade["price"] - fp) / fp <= FILL_MATCH_TOLERANCE:
                results.append({
                    "date": trade.get("date", "—"),
                    "price": fp,
                    "shares": trade.get("shares", "—"),
                    "zone": trade.get("zone", "—").lower(),
                })
                matched_indices.add(i)
                found = True
                break
        if not found:
            results.append({
                "date": "—",
                "price": fp,
                "shares": "—",
                "zone": "—",
            })
    return results


# ---------------------------------------------------------------------------
# Sell target recommendation
# ---------------------------------------------------------------------------

def compute_recommended_sell(ticker, avg_cost, pos, profiles):
    """Compute what the SELL price SHOULD be based on approved targets.

    Priority: optimized target > target_exit > default 6%.
    Returns (0, "no avg cost") if avg_cost is 0 (data inconsistency guard).
    """
    if avg_cost <= 0:
        return 0, "no avg cost"
    profile = profiles.get(ticker, {})
    opt = profile.get("optimal_target_pct")
    if opt is not None:
        return round(avg_cost * (1 + opt / 100), 2), f"optimized {opt:.1f}%"
    te = pos.get("target_exit")
    if te is not None:
        return te, "target_exit"
    return round(avg_cost * (1 + SELL_DEFAULT_PCT / 100), 2), f"standard {SELL_DEFAULT_PCT:.1f}%"


# ---------------------------------------------------------------------------
# Action flag logic
# ---------------------------------------------------------------------------

def _compute_buy_action(broker_price, broker_shares, rec_price, rec_shares,
                        drift_status, is_duplicate):
    """Determine BUY order action flag."""
    if drift_status == "ORPHANED":
        return "CANCEL (orphaned)"
    if is_duplicate:
        return "CANCEL (duplicate)"

    price_ok = rec_price > 0 and abs(broker_price - rec_price) / rec_price <= MATCH_TOLERANCE
    shares_ok = broker_shares == rec_shares

    if price_ok and shares_ok:
        return "OK"
    if not price_ok and not shares_ok:
        return "ADJUST price+shares"
    if not price_ok:
        return "ADJUST price"
    return "ADJUST shares"


def _compute_sell_action(broker_price, broker_shares, rec_price, rec_shares):
    """Determine SELL order action flag."""
    price_ok = rec_price > 0 and abs(broker_price - rec_price) / rec_price <= MATCH_TOLERANCE
    shares_ok = broker_shares == rec_shares

    if price_ok and shares_ok:
        return "OK"
    if not price_ok and not shares_ok:
        return "ADJUST price+shares"
    if not price_ok:
        return "ADJUST price"
    return "ADJUST shares"


# ---------------------------------------------------------------------------
# Zone label computation
# ---------------------------------------------------------------------------

def _build_zone_labels_from_ctx(ctx):
    """Build zone labels from bullet recommender ctx."""
    valid_levels = ctx.get("valid_levels", [])
    data = ctx.get("data", {})
    active_radius = data.get("active_radius", 15.0)
    from bullet_recommender import build_zone_labels as br_build_zone_labels
    labels_list = br_build_zone_labels(valid_levels, active_radius)
    result = {}
    for lvl, label in zip(valid_levels, labels_list):
        result[id(lvl)] = label
    return result


# ---------------------------------------------------------------------------
# Reconciliation engine
# ---------------------------------------------------------------------------

def reconcile_ticker(ticker, pos, orders, bullet_ctx, trade_buys, profiles):
    """Produce reconciliation data for a single ticker.

    Returns recon dict with fills, buy_orders, available_bullets, sell_orders, actions.
    """
    shares = pos.get("shares", 0) if pos else 0
    avg_cost = pos.get("avg_cost", 0) if pos else 0
    fill_prices = pos.get("fill_prices", []) if pos else []
    wick_available = bullet_ctx is not None

    # --- Fills ---
    fills = []
    if shares > 0 and fill_prices:
        # Filter trade_buys to current cycle (avoid matching old-cycle fills)
        entry_date = pos.get("entry_date", "") if pos else ""
        if entry_date and not entry_date.startswith("pre-"):
            cycle_buys = [t for t in trade_buys if t.get("date", "") >= entry_date]
        else:
            cycle_buys = trade_buys
        fills = match_fills_to_history(fill_prices, cycle_buys)

    # --- Zone labels from bullet ctx ---
    zone_labels = {}
    sizing_lookup = {}
    if bullet_ctx:
        zone_labels = _build_zone_labels_from_ctx(bullet_ctx)
        sizing_lookup = bullet_ctx.get("sizing_lookup", {})

    # --- BUY orders ---
    buy_orders = []
    actions = []

    if bullet_ctx:
        from bullet_recommender import classify_drift

        # Process covered levels (orders matched to wick levels)
        for cl in bullet_ctx.get("covered_levels", []):
            lvl = cl["level"]
            order = cl["order"]
            # Only process active unfilled placed orders
            if "filled" in order or not order.get("placed", False):
                continue
            drift_status = classify_drift(cl["dist"])
            rec_shares = sizing_lookup.get(id(lvl), (1, 0))[0]
            rec_price = lvl.get("recommended_buy", 0)
            label = zone_labels.get(id(lvl), "?")
            source = lvl.get("source", "")
            support = lvl.get("support_price", 0)
            zone_label = f"{label} (${support:.2f} {source})" if support else label

            action = _compute_buy_action(
                order["price"], order.get("shares", 0),
                rec_price, rec_shares,
                drift_status, cl.get("duplicate", False),
            )
            buy_orders.append({
                "zone_label": zone_label,
                "broker_price": order["price"],
                "broker_shares": order.get("shares", 0),
                "rec_price": rec_price,
                "rec_shares": rec_shares,
                "action": action,
            })
            if action != "OK":
                actions.append(
                    _format_buy_action(ticker, action, order["price"],
                                       order.get("shares", 0), rec_price, rec_shares)
                )

        # Orphaned orders
        for o in bullet_ctx.get("orphaned_orders", []):
            if "filled" in o or not o.get("placed", False):
                continue
            buy_orders.append({
                "zone_label": "?",
                "broker_price": o["price"],
                "broker_shares": o.get("shares", 0),
                "rec_price": 0,
                "rec_shares": 0,
                "action": "CANCEL (orphaned)",
            })
            actions.append(f"BUY {ticker}: CANCEL (orphaned) @ ${o['price']:.2f}")
    else:
        # No wick data — show active BUY orders with ? action
        for o in orders:
            if _is_active_buy(o):
                buy_orders.append({
                    "zone_label": "?",
                    "broker_price": o["price"],
                    "broker_shares": o.get("shares", 0),
                    "rec_price": 0,
                    "rec_shares": 0,
                    "action": "? (no wick data)",
                })

    # --- Available bullets ---
    available_bullets = []
    if bullet_ctx:
        uncovered = bullet_ctx.get("uncovered_levels", [])
        rec = bullet_ctx.get("recommendation")
        rec_id = id(rec["level"]) if rec else None
        for lvl in uncovered:
            rec_shares_avail, rec_cost_avail = sizing_lookup.get(
                id(lvl), (1, lvl.get("recommended_buy", 0)))
            label = zone_labels.get(id(lvl), "?")
            is_next = (id(lvl) == rec_id)
            available_bullets.append({
                "zone": label,
                "support": lvl.get("support_price", 0),
                "buy_at": lvl.get("recommended_buy", 0),
                "source": lvl.get("source", ""),
                "tier": lvl.get("tier", ""),
                "shares": rec_shares_avail,
                "cost": rec_cost_avail,
                "is_next": is_next,
            })

    # --- SELL orders ---
    sell_orders = []
    if shares > 0:
        rec_sell_price, rec_sell_basis = compute_recommended_sell(
            ticker, avg_cost, pos or {}, profiles)

        active_sells = [o for o in orders if _is_active_sell(o)]

        if active_sells:
            # Multi-tranche: compare aggregate shares vs position
            total_sell_shares = sum(o.get("shares", 0) for o in active_sells)
            is_multi_tranche = len(active_sells) > 1
            shares_covered = (total_sell_shares == shares)

            for o in active_sells:
                broker_price = o["price"]
                broker_shares = o.get("shares", 0)
                price_ok = (rec_sell_price > 0 and
                            abs(broker_price - rec_sell_price) / rec_sell_price <= MATCH_TOLERANCE)

                if is_multi_tranche:
                    # Multi-tranche: check price per order, shares at aggregate level
                    if price_ok and shares_covered:
                        action = "OK"
                    elif price_ok and not shares_covered:
                        action = "OK (price)"  # individual price OK, total shares issue
                    else:
                        action = "ADJUST price"
                else:
                    # Single SELL: check both price and shares
                    action = _compute_sell_action(
                        broker_price, broker_shares,
                        rec_sell_price, shares,
                    )

                sell_orders.append({
                    "broker_price": broker_price,
                    "broker_shares": broker_shares,
                    "rec_price": rec_sell_price,
                    "rec_shares": shares,
                    "action": action,
                    "basis": rec_sell_basis,
                })
                if action not in ("OK", "OK (price)"):
                    actions.append(
                        f"SELL {ticker}: {action} from ${broker_price:.2f} to "
                        f"${rec_sell_price:.2f} ({rec_sell_basis})"
                    )

            # Aggregate shares mismatch note for multi-tranche
            if is_multi_tranche and not shares_covered:
                actions.append(
                    f"SELL {ticker}: total SELL shares ({total_sell_shares}) != "
                    f"position ({shares}) — review tranche sizing"
                )
        else:
            # No SELL order exists
            sell_orders.append({
                "broker_price": 0,
                "broker_shares": 0,
                "rec_price": rec_sell_price,
                "rec_shares": shares,
                "action": "PLACE",
                "basis": rec_sell_basis,
            })
            actions.append(
                f"SELL {ticker}: PLACE @ ${rec_sell_price:.2f} x {shares} ({rec_sell_basis})"
            )

    return {
        "ticker": ticker,
        "shares": shares,
        "avg_cost": avg_cost,
        "fills": fills,
        "buy_orders": buy_orders,
        "available_bullets": available_bullets,
        "sell_orders": sell_orders,
        "actions": actions,
        "wick_available": wick_available,
    }


def _format_buy_action(ticker, action, broker_price, broker_shares, rec_price, rec_shares):
    """Format a BUY action item string. Always includes broker price for identification."""
    if "CANCEL" in action:
        return f"BUY {ticker}: {action} @ ${broker_price:.2f}"
    parts = [f"BUY {ticker}"]
    if "price" in action:
        parts.append(f"@ ${broker_price:.2f}: {action} → ${rec_price:.2f} x {rec_shares}")
    elif "shares" in action:
        parts.append(f"@ ${broker_price:.2f}: {action} x {broker_shares} → {rec_shares}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Markdown formatting
# ---------------------------------------------------------------------------

def format_ticker_report(recon):
    """Format reconciliation data as markdown for a single ticker."""
    lines = []
    ticker = recon["ticker"]
    shares = recon["shares"]
    avg_cost = recon["avg_cost"]
    is_watchlist_only = shares == 0

    if is_watchlist_only:
        lines.append(f"### {ticker} (no position — pending orders only)")
    else:
        lines.append(f"### {ticker} ({shares} sh @ ${avg_cost:.2f} avg)")
    lines.append("")

    # --- Fills ---
    lines.append("**Fills**")
    if is_watchlist_only:
        lines.append("*No position — pending orders only.*")
    elif not recon["fills"]:
        lines.append("*No fill records.*")
    else:
        lines.append("| # | Date | Price | Shares | Zone |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        total_shares = 0
        for i, fill in enumerate(recon["fills"], 1):
            sh_str = str(fill["shares"]) if isinstance(fill["shares"], int) else fill["shares"]
            lines.append(
                f"| {i} | {fill['date']} | ${fill['price']:.2f} | "
                f"{sh_str} | {fill['zone']} |"
            )
            if isinstance(fill["shares"], int):
                total_shares += fill["shares"]
        if total_shares > 0:
            lines.append(
                f"| **Avg** | — | **${avg_cost:.2f}** | "
                f"**{shares} sh** | — |"
            )
    lines.append("")

    # --- Limit BUYs ---
    if recon["buy_orders"]:
        lines.append("**Limit BUYs**")
        lines.append("| Level | Broker Price | Shares | Rec Price | Rec Shares | Action |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for bo in recon["buy_orders"]:
            rec_p = f"${bo['rec_price']:.2f}" if bo['rec_price'] > 0 else "—"
            rec_s = str(bo['rec_shares']) if bo['rec_shares'] > 0 else "—"
            lines.append(
                f"| {bo['zone_label']} | ${bo['broker_price']:.2f} | "
                f"{bo['broker_shares']} | {rec_p} | {rec_s} | {bo['action']} |"
            )
        lines.append("")

    # --- Available Bullets ---
    if recon["available_bullets"]:
        lines.append("**Available Bullets**")
        lines.append("| Zone | Support | Buy At | Tier | Shares | ~Cost |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for ab in recon["available_bullets"]:
            prefix = ">> " if ab["is_next"] else ""
            lines.append(
                f"| {prefix}{ab['zone']} | ${ab['support']:.2f} {ab['source']} | "
                f"${ab['buy_at']:.2f} | {ab['tier']} | {ab['shares']} | "
                f"~${ab['cost']:.2f} |"
            )
        lines.append("")

    # --- Limit SELLs ---
    if recon["sell_orders"]:
        lines.append("**Limit SELLs**")
        lines.append("| Broker Price | Shares | Rec Price | Rec Shares | Action |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for so in recon["sell_orders"]:
            bp = f"${so['broker_price']:.2f}" if so['broker_price'] > 0 else "—"
            bs = str(so['broker_shares']) if so['broker_shares'] > 0 else "—"
            action_str = so['action']
            if so['basis'] and not action_str.startswith("OK"):
                action_str += f" ({so['basis']})"
            lines.append(
                f"| {bp} | {bs} | ${so['rec_price']:.2f} | "
                f"{so['rec_shares']} | {action_str} |"
            )
        lines.append("")

    if not recon["wick_available"]:
        lines.append("*Wick analysis unavailable — BUY actions cannot be verified.*")
        lines.append("")

    return "\n".join(lines)


def format_action_summary(all_recons):
    """Format consolidated action summary across all tickers."""
    lines = []
    lines.append("## Action Items")
    lines.append("")

    total_actions = 0
    for recon in all_recons:
        for action in recon["actions"]:
            lines.append(f"- {action}")
            total_actions += 1
        # Also report OK tickers
        if not recon["actions"]:
            # Check if anything was checked
            has_items = recon["buy_orders"] or recon["sell_orders"]
            if has_items:
                lines.append(f"- {recon['ticker']}: OK")
                total_actions += 1

    if total_actions == 0:
        lines.append("*No active orders to reconcile.*")
    else:
        lines.append("")
        non_ok = sum(len(r["actions"]) for r in all_recons)
        lines.append(f"*{total_actions} item(s) checked, {non_ok} action(s) needed. "
                      f"Review and confirm changes at broker.*")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    portfolio = _load_portfolio()
    profiles = _load_profiles()
    trade_buys = _load_trade_history_buys()

    from wick_offset_analyzer import load_capital_config
    cap = load_capital_config()

    # Determine tickers
    if len(sys.argv) > 1:
        tickers = [t.upper() for t in sys.argv[1:]]
    else:
        # Default: union of active positions + tickers with active placed BUY orders
        positions = portfolio.get("positions", {})
        pending = portfolio.get("pending_orders", {})
        ticker_set = set()
        for ticker, pos in positions.items():
            if pos.get("shares", 0) > 0:
                ticker_set.add(ticker)
        for ticker, orders in pending.items():
            if any(_is_active_buy(o) for o in orders):
                ticker_set.add(ticker)
        tickers = sorted(ticker_set)

    if not tickers:
        print("*No active positions or placed BUY orders to reconcile.*")
        return

    print(f"## Part 7 — Broker Reconciliation ({len(tickers)} tickers)")
    print()

    all_recons = []
    for ticker in tickers:
        pos = portfolio.get("positions", {}).get(ticker)
        orders = portfolio.get("pending_orders", {}).get(ticker, [])
        ticker_trade_buys = trade_buys.get(ticker, [])

        bullet_ctx = _get_bullet_ctx(ticker, portfolio, cap)
        recon = reconcile_ticker(ticker, pos, orders, bullet_ctx,
                                 ticker_trade_buys, profiles)
        all_recons.append(recon)
        print(format_ticker_report(recon))

    print(format_action_summary(all_recons))


if __name__ == "__main__":
    main()
