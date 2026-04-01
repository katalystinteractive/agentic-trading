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
from bullet_recommender import classify_drift, build_zone_labels as _br_build_zone_labels
from wick_offset_analyzer import analyze_stock_data, load_capital_config

SELL_DEFAULT_PCT = 6.0
FILL_MATCH_TOLERANCE = 0.001  # 0.1% — tighter than MATCH_TOLERANCE
_ACTION_ADJUST_BOTH = "ADJUST price+shares"


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_portfolio():
    with open(PORTFOLIO_PATH, "r") as f:
        return json.load(f)


def _load_profiles():
    """Load ticker profiles. Merges neural support candidates as secondary source."""
    profiles = {}
    try:
        with open(PROFILES_PATH, "r") as f:
            profiles = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # Merge neural watchlist profiles (guaranteed for every tracked ticker)
    try:
        wl_path = _ROOT / "data" / "neural_watchlist_profiles.json"
        if wl_path.exists():
            with open(wl_path) as f:
                wl_data = json.load(f)
            for c in wl_data.get("candidates", []):
                tk = c["ticker"]
                if tk not in profiles:
                    profiles[tk] = {}
                if not profiles[tk].get("optimal_target_pct"):
                    profiles[tk]["optimal_target_pct"] = c["params"].get("sell_default")
                    profiles[tk]["_neural_source"] = "neural_watchlist"
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass

    # Merge neural support candidates (candidate discovery fallback)
    try:
        ns_path = _ROOT / "data" / "neural_support_candidates.json"
        if ns_path.exists():
            with open(ns_path) as f:
                ns_data = json.load(f)
            for c in ns_data.get("candidates", []):
                tk = c["ticker"]
                if tk not in profiles:
                    profiles[tk] = {}
                if not profiles[tk].get("optimal_target_pct"):
                    profiles[tk]["optimal_target_pct"] = c["params"].get("sell_default")
                    profiles[tk]["_neural_source"] = "neural_support"
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass

    return profiles


_resistance_profiles_cache = {"mtime": 0, "data": {}}


def _load_resistance_profiles():
    """Load per-ticker resistance sweep results. Cached with mtime check."""
    res_path = _ROOT / "data" / "resistance_sweep_results.json"
    try:
        if not res_path.exists():
            return {}
        mt = res_path.stat().st_mtime
        if mt != _resistance_profiles_cache["mtime"]:
            with open(res_path) as f:
                _resistance_profiles_cache["data"] = json.load(f)
            _resistance_profiles_cache["mtime"] = mt
        return _resistance_profiles_cache["data"]
    except (OSError, json.JSONDecodeError):
        return {}


_bounce_profiles_cache = {"mtime": 0, "data": {}}


def _load_bounce_profiles():
    """Load per-ticker bounce sweep results. Cached with mtime check."""
    bounce_path = _ROOT / "data" / "bounce_sweep_results.json"
    try:
        if not bounce_path.exists():
            return {}
        mt = bounce_path.stat().st_mtime
        if mt != _bounce_profiles_cache["mtime"]:
            with open(bounce_path) as f:
                _bounce_profiles_cache["data"] = json.load(f)
            _bounce_profiles_cache["mtime"] = mt
        return _bounce_profiles_cache["data"]
    except (OSError, json.JSONDecodeError):
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

def compute_recommended_sell(ticker, avg_cost, pos, profiles, hist=None):
    """Compute what the SELL price SHOULD be based on approved targets.

    Priority: target_exit (manual) > resistance (if winner) > bounce (if winner) > neural % > default 6%.
    Manual target_exit always wins — user intent overrides neural recommendations.
    Returns (0, "no avg cost") if avg_cost is 0 (data inconsistency guard).
    """
    if avg_cost <= 0:
        return 0, "no avg cost"
    # 1. Manual override always wins
    te = pos.get("target_exit")
    if te is not None:
        return te, "target_exit"
    # 1.5 Resistance-based target (if sweep determined resistance wins)
    res_data = _load_resistance_profiles()
    res_entry = res_data.get(ticker)
    if (res_entry and res_entry.get("vs_flat", {}).get("winner") == "resistance"
            and hist is not None and not hist.empty):
        try:
            from sell_target_calculator import (
                find_pa_resistances, find_hvn_ceilings,
                merge_resistance_levels, count_resistance_approaches)
            params = res_entry["params"]
            cur_price = float(hist["Close"].iloc[-1])
            # Zone must cover above avg_cost even when underwater
            zone_low = max(cur_price * 1.02, avg_cost * 1.01)
            zone_high = max(cur_price * 1.20, avg_cost * 1.20)
            pa = find_pa_resistances(hist, zone_low, zone_high)
            hvn = find_hvn_ceilings(hist, zone_low, zone_high)
            merged = merge_resistance_levels(pa, hvn)
            for lv in merged:
                stats = count_resistance_approaches(hist, lv["price"])
                lv.update(stats)
            qualifying = [r for r in merged
                          if r["price"] > avg_cost
                          and r.get("reject_rate", 0) >= params.get("min_reject_rate", 40)
                          and r.get("approaches", 0) >= params.get("min_resistance_approaches", 2)]
            if qualifying:
                strategy = params.get("resistance_strategy", "first")
                if strategy == "first":
                    target = min(r["price"] for r in qualifying)
                else:
                    target = max(qualifying, key=lambda r: r.get("reject_rate", 0))["price"]
                best = next(r for r in qualifying if r["price"] == target)
                pct = round((target - avg_cost) / avg_cost * 100, 1)
                return round(target, 2), f"resistance {pct}% (${target:.2f}, {best.get('reject_rate', 0):.0f}% reject)"
        except Exception:
            pass  # Fall through to bounce/neural %
    # 1.6 Bounce-derived target (if sweep determined bounce wins)
    bounce_data = _load_bounce_profiles()
    bounce_entry = bounce_data.get(ticker)
    if (bounce_entry and bounce_entry.get("vs_others", {}).get("winner") == "bounce"
            and hist is not None and not hist.empty):
        try:
            from bounce_sell_analyzer import compute_bounce_profiles, compute_combined_sell_target
            from wick_offset_analyzer import analyze_stock_data
            # Get support levels from wick analysis
            wick_data, _ = analyze_stock_data(ticker, hist=hist)
            if wick_data:
                levels = [r["support_price"] for r in wick_data.get("levels", [])
                          if r.get("hold_rate", 0) >= 15]
                if levels:
                    params = bounce_entry["params"]
                    profiles_b = compute_bounce_profiles(
                        hist, levels,
                        bounce_window=params.get("bounce_window_days", 3))
                    # Find best bounce target from levels near avg_cost
                    # Use actual support levels as fill level_prices (not avg_cost)
                    min_conf = params.get("bounce_confidence_min", 0.3)
                    qualifying = [(lp, p) for lp, p in profiles_b.items()
                                  if p["confidence"] >= min_conf
                                  and p["median_bounce_target"] > avg_cost]
                    if qualifying:
                        # Pick the level closest to avg_cost (most relevant)
                        best_lp, best_prof = min(qualifying,
                                                 key=lambda x: abs(x[0] - avg_cost))
                        target = best_prof["median_bounce_target"]
                        if params.get("bounce_cap_prior_high", True):
                            target = min(target, best_prof.get("prior_high_median", target))
                    else:
                        target = avg_cost * (1 + params.get("bounce_fallback_pct", 6.0) / 100)
                    if target > avg_cost:
                        pct = round((target - avg_cost) / avg_cost * 100, 1)
                        return round(target, 2), f"bounce {pct}% (${target:.2f})"
        except Exception:
            pass  # Fall through to neural %
    # 2. Profile (ticker_profiles.json or neural_support fallback)
    profile = profiles.get(ticker, {})
    opt = profile.get("optimal_target_pct")
    if opt is not None:
        source = profile.get("_neural_source", "optimized")
        return round(avg_cost * (1 + opt / 100), 2), f"{source} {opt:.1f}%"
    # 3. Hardcoded fallback
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
        return _ACTION_ADJUST_BOTH
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
        return _ACTION_ADJUST_BOTH
    if not price_ok:
        return "ADJUST price"
    return "ADJUST shares"


# ---------------------------------------------------------------------------
# Reason computation — deterministic explanation for every action
# ---------------------------------------------------------------------------

def _compute_buy_reason(action, broker_price, broker_shares, rec_price, rec_shares,
                        support_price=0, source="", hold_rate=None, effective_tier="",
                        pool_active=0, pool_reserve=0):
    """Compute a deterministic reason string for a BUY action.

    Every action must trace back to: wick refresh, pool resize, or orphaned level.
    """
    if "orphaned" in action.lower():
        return f"Wick refresh moved support levels — ${broker_price:.2f} no longer matches any level"
    if "duplicate" in action.lower():
        return f"Duplicate order at ${broker_price:.2f} — already covered by another order"

    parts = []
    # Price change reason
    if rec_price > 0 and abs(broker_price - rec_price) / rec_price > MATCH_TOLERANCE:
        level_str = f"${support_price:.2f} {source}" if support_price else "level"
        parts.append(f"Wick refresh: buy-at for {level_str} moved ${broker_price:.2f}→${rec_price:.2f}")

    # Share count change reason
    if broker_shares != rec_shares:
        pool_str = (f" (pool ${pool_active}+${pool_reserve}=${pool_active + pool_reserve})"
                    if pool_active is not None and pool_reserve is not None else "")
        parts.append(f"Pool sizing: {broker_shares}→{rec_shares} shares{pool_str}")

    return ". ".join(parts) if parts else "OK"


def _compute_sell_reason(action, broker_price, broker_shares, rec_price, rec_shares,
                         avg_cost, basis, old_avg_cost=0):
    """Compute a deterministic reason string for a SELL action.

    Sells are driven by: avg cost change (from fills), position size change (from fills),
    target source (optimized/target_exit/standard %). Pool size NEVER affects sells.
    """
    if action == "PLACE":
        return f"No sell order exists. Avg ${avg_cost:.2f} × {basis} = ${rec_price:.2f} × {rec_shares} shares"

    parts = []
    # Price change reason
    if rec_price > 0 and abs(broker_price - rec_price) / rec_price > MATCH_TOLERANCE:
        parts.append(f"Avg cost now ${avg_cost:.2f} → {basis} = ${rec_price:.2f} (was ${broker_price:.2f})")

    # Share count change reason
    if broker_shares != rec_shares:
        parts.append(f"Position now {rec_shares} shares (sell had {broker_shares})")

    return ". ".join(parts) if parts else "OK"


# ---------------------------------------------------------------------------
# Zone label computation
# ---------------------------------------------------------------------------

def _build_zone_labels_from_ctx(ctx):
    """Build zone labels from bullet recommender ctx."""
    valid_levels = ctx.get("valid_levels", [])
    data = ctx.get("data", {})
    active_radius = data.get("active_radius", 15.0)
    labels_list = _br_build_zone_labels(valid_levels, active_radius)
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

    # --- Pool info for reason strings (None = no pool data available) ---
    pool_active = None
    pool_reserve = None
    if bullet_ctx:
        cap = bullet_ctx.get("cap") or {}
        pool_active = cap.get("active_pool")
        pool_reserve = cap.get("reserve_pool")

    # --- BUY orders ---
    buy_orders = []
    actions = []

    if bullet_ctx:
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
            reason = _compute_buy_reason(
                action, order["price"], order.get("shares", 0),
                rec_price, rec_shares,
                support_price=support, source=source,
                hold_rate=lvl.get("hold_rate"),
                effective_tier=lvl.get("effective_tier", lvl.get("tier", "")),
                pool_active=pool_active, pool_reserve=pool_reserve,
            )
            buy_orders.append({
                "zone_label": zone_label,
                "broker_price": order["price"],
                "broker_shares": order.get("shares", 0),
                "rec_price": rec_price,
                "rec_shares": rec_shares,
                "action": action,
                "reason": reason,
            })
            if action != "OK":
                actions.append({
                    "side": "BUY", "ticker": ticker, "action": action,
                    "broker_price": order["price"],
                    "broker_shares": order.get("shares", 0),
                    "rec_price": rec_price, "rec_shares": rec_shares,
                    "reason": reason,
                    "display": _format_buy_action(
                        ticker, action, order["price"],
                        order.get("shares", 0), rec_price, rec_shares,
                        source=lvl.get("source", ""),
                        hold_rate=lvl.get("hold_rate"),
                        effective_tier=lvl.get("effective_tier", lvl.get("tier", "")),
                        support_price=lvl.get("support_price", 0)),
                })

        # Orphaned orders
        for o in bullet_ctx.get("orphaned_orders", []):
            if "filled" in o or not o.get("placed", False):
                continue
            reason = _compute_buy_reason(
                "CANCEL (orphaned)", o["price"], o.get("shares", 0), 0, 0)
            buy_orders.append({
                "zone_label": "?",
                "broker_price": o["price"],
                "broker_shares": o.get("shares", 0),
                "rec_price": 0,
                "rec_shares": 0,
                "action": "CANCEL (orphaned)",
                "reason": reason,
            })
            actions.append({
                "side": "BUY", "ticker": ticker, "action": "CANCEL (orphaned)",
                "broker_price": o["price"],
                "broker_shares": o.get("shares", 0),
                "rec_price": 0, "rec_shares": 0,
                "reason": reason,
                "display": _format_buy_action(
                    ticker, "CANCEL (orphaned)", o["price"],
                    o.get("shares", 0), 0, 0),
            })
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
                    "reason": "No wick analysis available — cannot verify",
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
        # Fetch hist for resistance/bounce sell targets
        _hist = None
        _res_data = _load_resistance_profiles()
        _bounce_data = _load_bounce_profiles()
        if (_res_data.get(ticker, {}).get("vs_flat", {}).get("winner") == "resistance" or
                _bounce_data.get(ticker, {}).get("vs_others", {}).get("winner") == "bounce"):
            try:
                import yfinance as yf
                import warnings
                warnings.filterwarnings("ignore")
                _hist_df = yf.download(ticker, period="13mo", progress=False)
                if not _hist_df.empty:
                    _hist = _hist_df
            except Exception:
                pass

        rec_sell_price, rec_sell_basis = compute_recommended_sell(
            ticker, avg_cost, pos or {}, profiles, hist=_hist)

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

                reason = _compute_sell_reason(
                    action, broker_price, broker_shares,
                    rec_sell_price, shares, avg_cost, rec_sell_basis)

                sell_orders.append({
                    "broker_price": broker_price,
                    "broker_shares": broker_shares,
                    "rec_price": rec_sell_price,
                    "rec_shares": shares,
                    "action": action,
                    "basis": rec_sell_basis,
                    "reason": reason,
                })
                if action not in ("OK", "OK (price)"):
                    if action in (_ACTION_ADJUST_BOTH, "ADJUST shares"):
                        display = (f"SELL {ticker}: {action} ${broker_price:.2f}/{broker_shares}sh "
                                   f"→ ${rec_sell_price:.2f}/{shares}sh ({rec_sell_basis})")
                    else:
                        display = (f"SELL {ticker}: {action} ${broker_price:.2f} "
                                   f"→ ${rec_sell_price:.2f} x {broker_shares} ({rec_sell_basis})")
                    actions.append({
                        "side": "SELL", "ticker": ticker, "action": action,
                        "broker_price": broker_price,
                        "broker_shares": broker_shares,
                        "rec_price": rec_sell_price, "rec_shares": shares,
                        "reason": reason,
                        "display": display,
                    })

            # Aggregate shares mismatch note for multi-tranche
            if is_multi_tranche and not shares_covered:
                actions.append({
                    "side": "SELL", "ticker": ticker, "action": "REVIEW",
                    "broker_price": 0, "broker_shares": total_sell_shares,
                    "rec_price": rec_sell_price, "rec_shares": shares,
                    "reason": f"Total sell shares ({total_sell_shares}) != position ({shares}) — review tranche sizing",
                    "display": (f"SELL {ticker}: total SELL shares ({total_sell_shares}) != "
                                f"position ({shares}) — review tranche sizing"),
                })
        else:
            # No SELL order exists
            reason = _compute_sell_reason(
                "PLACE", 0, 0, rec_sell_price, shares, avg_cost, rec_sell_basis)
            sell_orders.append({
                "broker_price": 0,
                "broker_shares": 0,
                "rec_price": rec_sell_price,
                "rec_shares": shares,
                "action": "PLACE",
                "basis": rec_sell_basis,
                "reason": reason,
            })
            actions.append({
                "side": "SELL", "ticker": ticker, "action": "PLACE",
                "broker_price": 0, "broker_shares": 0,
                "rec_price": rec_sell_price, "rec_shares": shares,
                "reason": reason,
                "display": f"SELL {ticker}: PLACE @ ${rec_sell_price:.2f} x {shares} ({rec_sell_basis})",
            })

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


def _format_buy_action(ticker, action, broker_price, broker_shares, rec_price, rec_shares,
                       source="", hold_rate=None, effective_tier="", support_price=0):
    """Format a BUY action item string. Always includes broker price for identification."""
    if "CANCEL" in action:
        return f"BUY {ticker}: {action} @ ${broker_price:.2f}"

    # Build justification suffix from level metadata
    jparts = []
    if support_price and source:
        jparts.append(f"${support_price:.2f} {source}")
    if hold_rate is not None:
        jparts.append(f"{hold_rate:.0f}% hold")
    if effective_tier:
        jparts.append(effective_tier)
    justification = f" ({', '.join(jparts)})" if jparts else ""

    parts = [f"BUY {ticker}"]
    if action == _ACTION_ADJUST_BOTH:
        # Show both deltas: old price/shares → new price/shares
        parts.append(f"@ ${broker_price:.2f}/{broker_shares}sh: {action} "
                     f"→ ${rec_price:.2f}/{rec_shares}sh{justification}")
    elif action == "ADJUST price":
        parts.append(f"@ ${broker_price:.2f}: {action} → ${rec_price:.2f} x {rec_shares}{justification}")
    elif action == "ADJUST shares":
        parts.append(f"@ ${broker_price:.2f}: {action} x {broker_shares} → {rec_shares}{justification}")
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
    """Format consolidated action summary across all tickers.

    Each action is a dict with 'display' and 'reason' keys.
    Output includes the reason for every non-OK action.
    """
    lines = []
    lines.append("## Action Items")
    lines.append("")

    total_checked = 0
    total_actions = 0
    for recon in all_recons:
        has_items = recon["buy_orders"] or recon["sell_orders"]
        if has_items:
            total_checked += len(recon["buy_orders"]) + len(recon["sell_orders"])
        for action in recon["actions"]:
            if isinstance(action, dict):
                lines.append(f"- {action['display']}")
                lines.append(f"  - *Why: {action['reason']}*")
            else:
                # Fallback for any plain string actions
                lines.append(f"- {action}")
            total_actions += 1

    if total_actions == 0:
        lines.append("*No active orders to reconcile.*")
    else:
        lines.append("")
        lines.append(f"*{total_checked} item(s) checked, {total_actions} action(s) needed. "
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

    # cap loaded per-ticker in loop below (simulation-backed pools)

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

        ticker_cap = load_capital_config(ticker)  # per-ticker simulation-backed pool
        bullet_ctx = _get_bullet_ctx(ticker, portfolio, ticker_cap)
        recon = reconcile_ticker(ticker, pos, orders, bullet_ctx,
                                 ticker_trade_buys, profiles)
        all_recons.append(recon)
        print(format_ticker_report(recon))

    print(format_action_summary(all_recons))


if __name__ == "__main__":
    main()
