"""Bullet recommender: bridges wick analysis and portfolio state.

Given a ticker, determines what bullets are already deployed (filled + pending),
which wick levels are covered, and recommends the next order(s) to place.

Usage:
    python3 tools/bullet_recommender.py APLD                    # recommend next order
    python3 tools/bullet_recommender.py SMCI ARM APLD           # multi-ticker
    python3 tools/bullet_recommender.py AR --mode audit          # audit existing orders
    python3 tools/bullet_recommender.py SMCI --type reserve      # only reserve recommendations
"""
import sys
import json
import re
import argparse
import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wick_offset_analyzer import analyze_stock_data, load_capital_config, compute_pool_sizing
from shared_constants import MATCH_TOLERANCE


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DRIFT_TOLERANCE = 0.05    # 5%
CONVERGENCE_TOLERANCE = 0.005  # 0.5% for merging nearby levels


# ---------------------------------------------------------------------------
# Portfolio helpers
# ---------------------------------------------------------------------------

def _load_portfolio():
    with open(PORTFOLIO_PATH, "r") as f:
        return json.load(f)


def parse_bullets_used(raw, position_note=""):
    """Handle int (4), string ('3 active + R1 filled'), or pre-strategy string.

    position_note is checked as secondary pre-strategy signal — covers IONQ where
    bullets_used is an int (1) but the note says 'Pre-strategy position, recovery mode.'
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


def is_paused(order):
    """Check if an order note contains PAUSED."""
    return "PAUSED" in order.get("note", "").upper()


# ---------------------------------------------------------------------------
# Level filtering and merging
# ---------------------------------------------------------------------------

def filter_valid_levels(levels, current_price):
    """Filter levels: drop None buy, above current, Skip tier, Reserve Half."""
    valid = []
    for lvl in levels:
        if lvl["recommended_buy"] is None:
            continue
        if lvl["recommended_buy"] >= current_price:
            continue
        if lvl.get("effective_tier", lvl["tier"]) == "Skip":
            continue
        # Reserve-zone Half-tier: gets ~half weight in pool distribution,
        # consuming a reserve slot for a small allocation. Filter retained
        # to preserve slot efficiency — reserve slots are scarce (max 3).
        if lvl["zone"] == "Reserve" and lvl.get("effective_tier", lvl["tier"]) == "Half":
            continue
        valid.append(lvl)
    # Sort by recommended_buy descending (closest to current price first)
    valid.sort(key=lambda x: x["recommended_buy"], reverse=True)
    return valid


def merge_convergent_levels(levels, tolerance=CONVERGENCE_TOLERANCE):
    """Merge levels where recommended_buy prices are within tolerance of each other.

    Keep the level with the higher hold rate. Return merged list + merge notes.
    """
    merged = []
    skip_indices = set()
    merge_notes = []
    for i in range(len(levels)):
        if i in skip_indices:
            continue
        best = levels[i]
        participants = [levels[i]]  # track all original levels in this merge group
        for j in range(i + 1, len(levels)):
            if j in skip_indices:
                continue
            min_buy = min(best["recommended_buy"], levels[j]["recommended_buy"])
            if min_buy > 0 and abs(best["recommended_buy"] - levels[j]["recommended_buy"]) / min_buy <= tolerance:
                skip_indices.add(j)
                participants.append(levels[j])
                if levels[j]["hold_rate"] > best["hold_rate"]:
                    best = levels[j]
        if len(participants) > 1:
            sources = [f"${l['support_price']:.2f} {l['source']}" for l in participants]
            merge_notes.append(f"Merged: {' + '.join(sources)} -> buy at ${best['recommended_buy']:.2f}")
        merged.append(best)
    return merged, merge_notes


# ---------------------------------------------------------------------------
# Order matching
# ---------------------------------------------------------------------------

def match_order_to_level(order_price, levels):
    """Find the nearest level within tolerance.

    Returns (level, distance_pct) or (None, None).
    """
    best_level = None
    best_dist = float('inf')
    for lvl in levels:
        buy = lvl["recommended_buy"]
        if buy is None or buy == 0:
            continue
        dist = abs(order_price - buy) / buy
        if dist < best_dist:
            best_dist = dist
            best_level = lvl
    # MATCH (<=0.5%) or DRIFT (0.5-5%) — caller uses classify_drift() to distinguish
    if best_dist <= DRIFT_TOLERANCE:
        return best_level, best_dist
    return None, None


def classify_drift(dist):
    """Classify drift distance into status label.

    Only receives dist <= DRIFT_TOLERANCE or None (match_order_to_level contract).
    """
    if dist is None:
        return "ORPHANED"
    if dist <= MATCH_TOLERANCE:
        return "MATCH"
    return "DRIFT"


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------

def compute_sizing(level, pool, cap):
    """Single-level fallback sizing. Prefer compute_pool_sizing() for batch."""
    budget = cap["active_pool"] if pool == "active" else cap["reserve_pool"]
    sized = compute_pool_sizing([level], budget, pool)
    if sized:
        s = sized[0]
        return s["shares"], s["cost"], s.get("dollar_alloc", s["cost"])
    shares = max(1, int(budget / level["recommended_buy"]))
    cost = round(shares * level["recommended_buy"], 2)
    return shares, cost, cost


def is_capped(level):
    """Check if a level's tier was capped from Full/Std to Half due to <3 approaches."""
    hr = level["hold_rate"]
    tier = level["tier"]
    approaches = level["total_approaches"]
    if tier == "Half" and approaches < 3:
        if hr >= 50:
            return True, "Full"
        elif hr >= 30:
            return True, "Std"
    return False, None


# ---------------------------------------------------------------------------
# Zone label helpers
# ---------------------------------------------------------------------------

def assign_zone_label(gap_pct, active_radius):
    """Classify a level into display zone based on distance from price.

    Returns zone letter: 'A' (Active), 'B' (Buffer), 'R' (Reserve).
    """
    if gap_pct <= active_radius:
        return "A"
    elif gap_pct <= 2 * active_radius:
        return "B"
    else:
        return "R"


ZONE_MAX = {"A": 5, "B": 5, "R": 3}


def build_zone_labels(valid_levels, active_radius):
    """Assign geographic A/B/R labels to levels (sorted descending by buy price).

    Returns list of labels parallel to valid_levels.
    """
    counters = {"A": 0, "B": 0, "R": 0}
    labels = []
    for lvl in valid_levels:
        gap = lvl.get("gap_pct", 0)
        zone_letter = assign_zone_label(gap, active_radius)
        if counters[zone_letter] < ZONE_MAX[zone_letter]:
            counters[zone_letter] += 1
            labels.append(f"{zone_letter}{counters[zone_letter]}")
        else:
            labels.append("—")
    return labels


# ---------------------------------------------------------------------------
# Recommend mode
# ---------------------------------------------------------------------------

def run_recommend(ticker, type_filter, data, portfolio, cap=None):
    """Recommend the next order(s) to place."""
    if cap is None:
        cap = load_capital_config()
    positions = portfolio.get("positions", {})
    pending_all = portfolio.get("pending_orders", {})
    pending_orders = pending_all.get(ticker, [])
    current_price = data["current_price"]

    warnings = []
    reasoning = []

    # --- Step 1: Determine position case ---
    if ticker in positions:
        pos = positions[ticker]
        shares = pos.get("shares", 0)
        avg_cost = pos.get("avg_cost", 0)
        bullets_used_raw = pos.get("bullets_used", 0)
        pos_note = pos.get("note", "")

        if shares > 0:
            case = "A"  # Active position
            status_label = "Active position"
        else:
            case = "B"  # Zero shares, re-entry mode
            status_label = "Re-entry mode — position closed, pending BUYs active"
    elif ticker in pending_all and any(o["type"] == "BUY" for o in pending_all.get(ticker, [])):
        case = "C"  # No position, but has pending BUY orders
        shares = 0
        avg_cost = 0
        bullets_used_raw = 0
        pos_note = ""
        status_label = "Watchlist — no position, pending BUYs placed"
    else:
        case = "D"  # Fully new ticker
        shares = 0
        avg_cost = 0
        bullets_used_raw = 0
        pos_note = ""
        status_label = "New ticker — no position, no orders"

    parsed = parse_bullets_used(bullets_used_raw, pos_note)
    is_pre_strategy = parsed["pre_strategy"]
    if is_pre_strategy:
        status_label = "Pre-strategy position"

    # Separate pending BUYs and SELLs
    pending_buys = [o for o in pending_orders if o["type"] == "BUY"]
    pending_sells = [o for o in pending_orders if o["type"] == "SELL"]

    # --- Step 2: Filter levels ---
    valid_levels = filter_valid_levels(data["levels"], current_price)
    if not valid_levels:
        _print_no_levels(ticker, current_price, data)
        return

    # --- Step 3: Convergence merge ---
    valid_levels, merge_notes = merge_convergent_levels(valid_levels)
    reasoning.extend(merge_notes)

    # --- Step 4: Mark covered levels ---
    covered_levels = []
    covered_set = set()  # indices into valid_levels
    orphaned_orders = []

    for order in pending_buys:
        matched_level, dist = match_order_to_level(order["price"], valid_levels)
        if matched_level is not None:
            idx = None
            for i, vl in enumerate(valid_levels):
                if vl is matched_level:
                    idx = i
                    break
            paused_flag = is_paused(order)
            if idx is not None and idx not in covered_set:
                covered_set.add(idx)
                covered_levels.append({
                    "level": matched_level,
                    "order": order,
                    "dist": dist,
                    "paused": paused_flag,
                    "duplicate": False,
                })
            elif idx is not None:
                # Second order targeting the same level — still show it
                covered_levels.append({
                    "level": matched_level,
                    "order": order,
                    "dist": dist,
                    "paused": paused_flag,
                    "duplicate": True,
                })
        else:
            orphaned_orders.append(order)

    uncovered_levels = [vl for i, vl in enumerate(valid_levels) if i not in covered_set]

    # --- Step 4b: Mark filled levels using fill_prices from portfolio.json ---
    fill_prices_list = []
    if ticker in positions:
        fill_prices_list = positions[ticker].get("fill_prices", [])

    filled_set = set()
    if fill_prices_list and case == "A":
        for fp in fill_prices_list:
            matched_level, dist = match_order_to_level(fp, uncovered_levels)
            if matched_level is not None:
                for i, ul in enumerate(uncovered_levels):
                    if ul is matched_level and i not in filled_set:
                        filled_set.add(i)
                        break
    filled_levels = [ul for i, ul in enumerate(uncovered_levels) if i in filled_set]
    uncovered_levels = [ul for i, ul in enumerate(uncovered_levels) if i not in filled_set]
    fills_above_price = len(fill_prices_list) - len(filled_set) if fill_prices_list and case == "A" else 0

    # --- Step 5: Compute deployment state ---
    # Slot counting: parsed values are authoritative for fills (from portfolio.json).
    # Case A: fills + pending are additive (disjoint — filled orders are removed).
    # Cases B/C/D: fills are stale or zero; only pending orders matter.
    covered_active = sum(1 for cl in covered_levels if cl["level"]["zone"] == "Active" and not cl.get("duplicate"))
    covered_reserve = sum(1 for cl in covered_levels if cl["level"]["zone"] == "Reserve" and not cl.get("duplicate"))
    if case == "A":
        effective_active_used = parsed["active"] + covered_active
        effective_reserve_used = parsed["reserve"] + covered_reserve
    else:
        effective_active_used = covered_active
        effective_reserve_used = covered_reserve

    # --- Batch sizing: size ALL valid_levels as one batch ---
    # IMPORTANT: id(lvl) relies on valid_levels keeping original dict references alive.
    # Do not copy/reconstruct level dicts between this point and lookup usage.
    all_active_levels = [lvl for lvl in valid_levels if lvl["zone"] == "Active"]
    all_reserve_levels = [lvl for lvl in valid_levels if lvl["zone"] == "Reserve"]

    active_sized = compute_pool_sizing(all_active_levels, cap["active_pool"], "active")
    reserve_sized = compute_pool_sizing(all_reserve_levels, cap["reserve_pool"], "reserve")

    sizing_lookup = {}
    for lvl, sized in zip(all_active_levels, active_sized):
        sizing_lookup[id(lvl)] = (sized["shares"], sized["cost"])
    for lvl, sized in zip(all_reserve_levels, reserve_sized):
        sizing_lookup[id(lvl)] = (sized["shares"], sized["cost"])

    # Budget computation — derive filled costs from batch sizing
    if is_pre_strategy:
        deployed_cost = shares * avg_cost
        active_budget_remaining = cap["active_pool"] - deployed_cost
        reserve_budget_remaining = cap["reserve_pool"]
        # Check for cancelled reserves
        if "reserves cancelled" in pos_note.lower():
            reserve_slots_remaining = 0
            reserve_budget_remaining = 0
        else:
            reserve_slots_remaining = cap["reserve_bullets_max"] - effective_reserve_used
        active_slots_remaining = cap["active_bullets_max"] - effective_active_used
    else:
        # Sum costs of filled levels from the full-batch sizing.
        # Include both uncovered fills (filled_levels) AND covered levels
        # that match a fill_price (fill at a level with pending order).
        all_filled_level_refs = list(filled_levels)
        if fill_prices_list and case == "A":
            for cl in covered_levels:
                lvl = cl["level"]
                for fp in fill_prices_list:
                    if lvl["recommended_buy"] and abs(fp - lvl["recommended_buy"]) / lvl["recommended_buy"] <= MATCH_TOLERANCE:
                        all_filled_level_refs.append(lvl)
                        break
        filled_active_cost = sum(
            sizing_lookup.get(id(fl), (0, 0))[1]
            for fl in all_filled_level_refs if fl["zone"] == "Active"
        )
        filled_reserve_cost = sum(
            sizing_lookup.get(id(fl), (0, 0))[1]
            for fl in all_filled_level_refs if fl["zone"] == "Reserve"
        )
        active_budget_remaining = cap["active_pool"] - filled_active_cost
        reserve_budget_remaining = cap["reserve_pool"] - filled_reserve_cost
        active_slots_remaining = cap["active_bullets_max"] - effective_active_used
        reserve_slots_remaining = cap["reserve_bullets_max"] - effective_reserve_used

    # Clamp to >= 0 for display (can go negative if overdeployed)
    active_slots_remaining = max(0, active_slots_remaining)
    reserve_slots_remaining = max(0, reserve_slots_remaining)

    # --- Slot overflow warning (V4-F1) ---
    total_occupied = parsed["active"] + parsed["reserve"] + len(pending_buys)
    max_slots = cap["active_bullets_max"] + cap["reserve_bullets_max"]
    if total_occupied > max_slots:
        warnings.append(
            f"WARNING: {ticker} has {total_occupied} occupied slots "
            f"({parsed['active'] + parsed['reserve']} filled + {len(pending_buys)} pending), "
            f"exceeding max {max_slots} slots ({cap['active_bullets_max']} active + "
            f"{cap['reserve_bullets_max']} reserve). Review for excess orders."
        )

    # --- Step 6: Find recommendation ---
    def _find_recommendation(pool, budget, slot_label):
        """Search uncovered levels for the first that fits within budget."""
        for lvl in uncovered_levels:
            ref_shares, ref_cost = sizing_lookup.get(id(lvl), (1, lvl["recommended_buy"]))
            if ref_cost <= budget:
                return {"level": lvl, "shares": ref_shares, "cost": ref_cost,
                        "pool": pool, "label": slot_label}
        return None

    recommendation = None

    # Build ordered list of (pool, budget, label) attempts based on type filter
    attempts = []
    if type_filter in ("active", "any") and active_slots_remaining > 0:
        attempts.append(("active", active_budget_remaining,
                         f"Active {effective_active_used + 1}"))
    elif type_filter == "active":
        reasoning.append("No active slots remaining.")
    if type_filter in ("reserve", "any") and reserve_slots_remaining > 0:
        attempts.append(("reserve", reserve_budget_remaining,
                         f"Reserve {effective_reserve_used + 1}"))
    elif type_filter == "reserve":
        reasoning.append("No reserve slots remaining.")

    for pool, budget, label in attempts:
        recommendation = _find_recommendation(pool, budget, label)
        if recommendation is not None:
            break

    # Check if fully deployed: no recommendation possible AND either no slots or no uncovered levels
    fully_deployed = (recommendation is None
                      and (not uncovered_levels
                           or (active_slots_remaining == 0 and reserve_slots_remaining == 0)))

    # --- Step 7: SELL target staleness check ---
    sell_check = None
    if pending_sells and shares > 0:
        sell_price = pending_sells[0]["price"]
        pct_from_avg = (sell_price - avg_cost) / avg_cost * 100
        sell_check = {
            "sell_price": sell_price,
            "pct_from_avg": pct_from_avg,
            "stale": abs(pct_from_avg) < 5,
        }

    # --- Output ---
    ctx = {
        "ticker": ticker, "current_price": current_price,
        "status_label": status_label, "case": case,
        "shares": shares, "avg_cost": avg_cost, "parsed": parsed,
        "effective_active_used": effective_active_used,
        "effective_reserve_used": effective_reserve_used,
        "active_slots_remaining": active_slots_remaining,
        "reserve_slots_remaining": reserve_slots_remaining,
        "active_budget_remaining": active_budget_remaining,
        "reserve_budget_remaining": reserve_budget_remaining,
        "is_pre_strategy": is_pre_strategy, "pos_note": pos_note,
        "pending_buys": pending_buys, "pending_sells": pending_sells,
        "covered_levels": covered_levels,
        "orphaned_orders": orphaned_orders, "sell_check": sell_check,
        "recommendation": recommendation, "valid_levels": valid_levels,
        "filled_levels": filled_levels, "fills_above_price": fills_above_price,
        "covered_active": covered_active, "covered_reserve": covered_reserve,
        "fully_deployed": fully_deployed, "warnings": warnings,
        "reasoning": reasoning, "cap": cap, "data": data,
        "sizing_lookup": sizing_lookup,
    }
    _print_recommend(ctx)


# ---------------------------------------------------------------------------
# Output formatting — recommend mode
# ---------------------------------------------------------------------------

def _fmt_dollar(val):
    if val is None:
        return "N/A"
    if not isinstance(val, (int, float)):
        return str(val)
    return f"${val:.2f}"


def _print_no_levels(ticker, current_price, data=None):
    """Print output when no eligible levels found."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    last_date = data.get("last_date", "unknown") if data else "unknown"
    print(f"## Bullet Recommendation: {ticker}")
    print(f"*Generated: {now} | Data as of: {last_date}*")
    print()
    print(f"No eligible support levels below current price ({_fmt_dollar(current_price)}) for {ticker}.")


def _print_recommend(ctx):
    """Print full recommendation output. ctx is a dict with all display data."""
    ticker = ctx["ticker"]
    current_price = ctx["current_price"]
    status_label = ctx["status_label"]
    case = ctx["case"]
    shares = ctx["shares"]
    avg_cost = ctx["avg_cost"]
    parsed = ctx["parsed"]
    effective_active_used = ctx["effective_active_used"]
    active_slots_remaining = ctx["active_slots_remaining"]
    reserve_slots_remaining = ctx["reserve_slots_remaining"]
    active_budget_remaining = ctx["active_budget_remaining"]
    reserve_budget_remaining = ctx["reserve_budget_remaining"]
    is_pre_strategy = ctx["is_pre_strategy"]
    pos_note = ctx["pos_note"]
    pending_buys = ctx["pending_buys"]
    pending_sells = ctx["pending_sells"]
    covered_levels = ctx["covered_levels"]
    orphaned_orders = ctx["orphaned_orders"]
    sell_check = ctx["sell_check"]
    recommendation = ctx["recommendation"]
    valid_levels = ctx["valid_levels"]
    filled_levels = ctx["filled_levels"]
    fills_above_price = ctx.get("fills_above_price", 0)
    covered_active = ctx["covered_active"]
    covered_reserve = ctx["covered_reserve"]
    fully_deployed = ctx["fully_deployed"]
    warnings = ctx["warnings"]
    reasoning = ctx["reasoning"]
    cap = ctx["cap"]
    sizing_lookup = ctx.get("sizing_lookup", {})
    effective_reserve_used = ctx["effective_reserve_used"]

    data = ctx["data"]
    active_radius = data.get("active_radius", 15.0)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    last_date = data.get("last_date", "unknown")
    print(f"## Bullet Recommendation: {ticker}")
    print(f"*Generated: {now} | Data as of: {last_date}*")
    print()

    # Warnings
    for w in warnings:
        print(f"> {w}")
        print()

    # Position State table
    print("### Position State")
    print("| Field | Value |")
    print("| :--- | :--- |")
    print(f"| Status | {status_label} |")

    if case == "A":
        print(f"| Shares | {shares} @ {_fmt_dollar(avg_cost)} avg |")
        if is_pre_strategy:
            deployed = shares * avg_cost
            print(f"| Deployed Cost | {_fmt_dollar(deployed)} (actual, not bullet-derived) |")
            pre_tag = " (pre-strategy)"
            print(f"| Bullets Used | {parsed['active']} active{pre_tag}, {parsed['reserve']} reserve |")
            print(f"| Active Budget | {_fmt_dollar(cap['active_pool'])} - {_fmt_dollar(deployed)} = {_fmt_dollar(active_budget_remaining)} remaining |")
            if "reserves cancelled" in pos_note.lower():
                print(f"| Reserve Budget | $0 (cancelled) |")
            else:
                print(f"| Reserve Budget | {_fmt_dollar(reserve_budget_remaining)} |")
        else:
            print(f"| Bullets Used | {parsed['active']} active, {parsed['reserve']} reserve |")
            print(f"| Effective Deployed | {effective_active_used} active ({parsed['active']} filled + {covered_active} pending), {effective_reserve_used} reserve ({parsed['reserve']} filled + {covered_reserve} pending) |")
            print(f"| Slots Remaining | Active: {active_slots_remaining} | Reserve: {reserve_slots_remaining} |")
            print(f"| Budget Remaining | Active: {_fmt_dollar(active_budget_remaining)} | Reserve: {_fmt_dollar(reserve_budget_remaining)} |")
        # Lowest pending/fill
        if pending_buys:
            lowest = min(pending_buys, key=lambda o: o["price"])
            print(f"| Lowest Pending | {_fmt_dollar(lowest['price'])} |")
    elif case == "B":
        print(f"| Shares | 0 (sold) |")
        print(f"| Prior Avg | {_fmt_dollar(avg_cost)} |")
        if pending_buys:
            print(f"| Pending BUYs | {len(pending_buys)} orders covering {sum(1 for cl in covered_levels if not cl.get('duplicate'))} levels |")
        print(f"| Slots Remaining | Active: {active_slots_remaining} | Reserve: {reserve_slots_remaining} |")
        print(f"| Budget Remaining | Active: {_fmt_dollar(active_budget_remaining)} | Reserve: {_fmt_dollar(reserve_budget_remaining)} |")
    elif case == "C":
        print(f"| Shares | 0 |")
        if pending_buys:
            print(f"| Pending BUYs | {len(pending_buys)} orders covering {sum(1 for cl in covered_levels if not cl.get('duplicate'))} levels |")
        print(f"| Slots Remaining | Active: {active_slots_remaining} | Reserve: {reserve_slots_remaining} |")
        print(f"| Budget Remaining | Active: {_fmt_dollar(active_budget_remaining)} | Reserve: {_fmt_dollar(reserve_budget_remaining)} |")
    else:  # case D
        print(f"| Shares | 0 |")
        print(f"| Slots Remaining | Active: {active_slots_remaining} | Reserve: {reserve_slots_remaining} |")
        print(f"| Budget | Active: {_fmt_dollar(cap['active_pool'])} | Reserve: {_fmt_dollar(cap['reserve_pool'])} |")

    # SELL target check
    if sell_check:
        pct_str = f"{sell_check['pct_from_avg']:+.1f}%"
        status = "STALE — too close to avg" if sell_check["stale"] else "OK"
        print(f"| SELL Target Check | {_fmt_dollar(sell_check['sell_price'])} = {pct_str} from avg ({status}) |")

    print()

    # --- Level Map (unified table) ---
    print("### Level Map")
    print("| # | Support | Buy At | Held | Tier | Trend | Shares | ~Cost | Status |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    # SELL target rows first
    for sell_order in pending_sells:
        sell_shares = sell_order.get("shares", "—")
        sell_cost = round(sell_shares * sell_order["price"], 2) if isinstance(sell_shares, (int, float)) else "—"
        sell_placed = "Limit Order" if sell_order.get("placed", True) else "Pending"
        print(f"| SELL | — | {_fmt_dollar(sell_order['price'])} | — | — | — "
              f"| {sell_shares} | {_fmt_dollar(sell_cost)} | {sell_placed} |")

    # Build covered lookup: level id -> list of cover entries
    covered_lookup = {}
    for cl in covered_levels:
        lid = id(cl["level"])
        covered_lookup.setdefault(lid, []).append(cl)

    rec_level_id = id(recommendation["level"]) if recommendation else None
    filled_lookup = set(id(fl) for fl in filled_levels)
    has_capped = False
    has_promotion = False
    has_demotion = False

    # Assign geographic A/B/R labels
    zone_labels = build_zone_labels(valid_levels, active_radius)

    for lvl_idx, lvl in enumerate(valid_levels):
        lid = id(lvl)
        capped_flag, was_tier = is_capped(lvl)
        tier_display = lvl.get("effective_tier", lvl["tier"])
        if lvl.get("tier_override", False):
            if lvl.get("tier_promoted", False):
                tier_display += "^"
                has_promotion = True
            else:
                tier_display += "v"
                has_demotion = True
        if capped_flag:
            tier_display += "*"
            has_capped = True
        # Trend column value
        trend_raw = lvl.get("trend", "—")
        trend_map = {"Improving": "^", "Deteriorating": "v", "Stable": "-", "—": "?"}
        trend_str = trend_map.get(trend_raw, "?")
        # Dormant tag for status
        dormant_tag = " [D]" if lvl.get("dormant", False) else ""
        support_str = f"{_fmt_dollar(lvl['support_price'])} {lvl['source']}"
        buy_str = _fmt_dollar(lvl["recommended_buy"])
        held = lvl.get("held", 0)
        approaches = lvl.get("total_approaches", 0)
        hold_str = f"{held}/{approaches} ({lvl['hold_rate']:.0f}%)"

        # Geographic zone label
        level_label = zone_labels[lvl_idx]

        # Compute sizing from batch
        ref_shares, ref_cost = sizing_lookup.get(id(lvl), (1, lvl["recommended_buy"]))

        if lid in covered_lookup:
            for cl in covered_lookup[lid]:
                order = cl["order"]
                # DUP rows don't consume a label
                row_label = "—" if cl.get("duplicate") else level_label
                # Status: Limit Order (placed) or Pending (not placed) + flags
                parts = []
                drift_status = classify_drift(cl["dist"])
                if drift_status != "MATCH":
                    parts.append(drift_status)
                if cl.get("duplicate"):
                    parts.append("DUP")
                if cl["paused"]:
                    parts.append("PAUSED")
                flags = f" ({', '.join(parts)})" if parts else ""
                if order.get("placed"):
                    status_str = f"Limit Order{flags}"
                else:
                    status_str = f"Pending{flags}"
                # Shares/cost from order
                ord_shares = order.get("shares")
                if ord_shares:
                    ord_cost = round(ord_shares * order["price"], 2)
                    shares_str = str(ord_shares)
                    cost_str = f"~{_fmt_dollar(ord_cost)}"
                else:
                    shares_str = str(ref_shares)
                    cost_str = f"~{_fmt_dollar(ref_cost)}"
                print(f"| {row_label} | {support_str} | {_fmt_dollar(order['price'])} | {hold_str} | {tier_display} "
                      f"| {trend_str} | {shares_str} | {cost_str} | {status_str}{dormant_tag} |")
        elif lid in filled_lookup:
            print(f"| {level_label} | {support_str} | {buy_str} | {hold_str} | {tier_display} "
                  f"| {trend_str} | {ref_shares} | ~{_fmt_dollar(ref_cost)} | Filled{dormant_tag} |")
        elif lid == rec_level_id:
            print(f"| {level_label} | {support_str} | {buy_str} | {hold_str} | {tier_display} "
                  f"| {trend_str} | {recommendation['shares']} | ~{_fmt_dollar(recommendation['cost'])} | **>> Next**{dormant_tag} |")
        else:
            # Uncovered level — Available or —
            pool = "active" if lvl["zone"] == "Active" else "reserve"
            if pool == "active":
                has_capacity = active_slots_remaining > 0 and active_budget_remaining >= ref_cost
            else:
                has_capacity = reserve_slots_remaining > 0 and reserve_budget_remaining >= ref_cost
            status_str = "Available" if has_capacity else "—"
            if dormant_tag:
                status_str = f"{status_str}{dormant_tag}" if status_str != "—" else f"—{dormant_tag}"
            print(f"| {level_label} | {support_str} | {buy_str} | {hold_str} | {tier_display} "
                  f"| {trend_str} | {ref_shares} | ~{_fmt_dollar(ref_cost)} | {status_str} |")

    if has_capped or has_promotion or has_demotion:
        markers = []
        if has_promotion:
            markers.append("^ = tier promoted by recent holds")
        if has_demotion:
            markers.append("v = tier demoted by recent breaks")
        if has_capped:
            markers.append("* = capped to Half by approach count (<3)")
        print()
        print(f"*{'; '.join(markers)}*")

    if fills_above_price > 0:
        print()
        print(f"*Note: {fills_above_price} fill(s) above current price — not shown in Level Map.*")
    print()

    # Fully deployed / no recommendation note
    if fully_deployed:
        print("*Fully deployed. No additional BUY orders recommended.*")
        print()
    elif recommendation is None:
        if active_slots_remaining == 0 and reserve_slots_remaining == 0:
            print("*All slots occupied. No room for additional orders.*")
        else:
            print("*No affordable levels within remaining budget.*")
        print()

    # Orphaned orders
    if orphaned_orders:
        print("### Orphaned Orders (no matching wick level)")
        print("| Order Price | Note |")
        print("| :--- | :--- |")
        for o in orphaned_orders:
            print(f"| {_fmt_dollar(o['price'])} | {o.get('note', '')} |")
        print()

    # Notes
    if recommendation or reasoning:
        print("### Notes")
        if recommendation:
            pool_label = "active" if recommendation["pool"] == "active" else "reserve"
            budget = active_budget_remaining if recommendation["pool"] == "active" else reserve_budget_remaining
            print(f"- Recommended cost: ~{_fmt_dollar(recommendation['cost'])} of {_fmt_dollar(budget)} {pool_label} budget")
            if recommendation["pool"] == "reserve" and recommendation["level"]["zone"] == "Active":
                print(f"- Active slots exhausted — reserve budget used at Active-zone price")
        for note in reasoning:
            print(f"- {note}")
        print()

    # Legend (always printed)
    _print_legend(active_radius, cap)


def _print_legend(active_radius, cap):
    """Print legend with zone definitions and tier sizing."""
    print("### Legend")
    print(f"- **A** = Active zone (within {active_radius:.0f}% of price)")
    print(f"- **B** = Buffer zone ({active_radius:.0f}–{2*active_radius:.0f}% from price)")
    print(f"- **R** = Reserve zone (beyond {2*active_radius:.0f}% from price)")
    print(f"- **Held** = Times support held / total approaches in 13 months (hold rate %)")
    print(f"- **Sizing** = ${cap['active_pool']} active / ${cap['reserve_pool']} reserve pool, distributed across all levels (equal impact)")
    print(f"- **Full** (>=50% hold) = full weight in pool distribution")
    print(f"- **Std** (30-49% hold) = same weight as Full, lower confidence signal")
    print(f"- **Half** (15-29% hold) = half weight in pool distribution")
    print(f"- **Tier ^/v** = tier promoted/demoted by recency | **Trend ^/v** = hold-rate trajectory")
    print(f"- **[D]** = dormant (not tested in 90+ days)")
    print(f"- **>> Next** = recommended next order to place")
    print()


# ---------------------------------------------------------------------------
# Audit mode
# ---------------------------------------------------------------------------

def run_audit(ticker, data, portfolio):
    """Audit existing pending orders against current wick levels."""
    pending_all = portfolio.get("pending_orders", {})
    pending_orders = pending_all.get(ticker, [])
    pending_buys = [o for o in pending_orders if o["type"] == "BUY"]
    current_price = data["current_price"]
    active_radius = data.get("active_radius", 15.0)

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    last_date = data.get("last_date", "unknown")
    print(f"## Order Audit: {ticker}")
    print(f"*Generated: {now} | Data as of: {last_date}*")
    print(f"*Current Price: {_fmt_dollar(current_price)}*")
    print()

    if not pending_buys:
        print(f"No pending BUY orders for {ticker}.")
        return

    # Build valid levels (include all for audit — don't filter by current price)
    all_levels = [lvl for lvl in data["levels"] if lvl["recommended_buy"] is not None]

    print("| Order | Price | Matched Level | Current Buy At | Drift | Hold Rate | Tier | Capped? | Status |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    # Pre-compute row data, then sort by matched price descending for correct zone labels
    rows = []
    for order in pending_buys:
        matched, dist = match_order_to_level(order["price"], all_levels)
        paused_flag = is_paused(order)

        if matched is not None:
            status = classify_drift(dist)
            drift_str = f"{dist * 100:.1f}%"
            level_str = f"{_fmt_dollar(matched['support_price'])} {matched['source']}"
            buy_at_str = _fmt_dollar(matched["recommended_buy"])
            hr_str = f"{matched['hold_rate']:.0f}%"
            tier_str = matched.get("effective_tier", matched["tier"])
            if matched.get("tier_override", False):
                tier_str += "^" if matched.get("tier_promoted", False) else "v"
            capped, was_tier = is_capped(matched)
            capped_str = f"Yes (was {was_tier}, <3 approaches)" if capped else "No"
            gap = matched.get("gap_pct", 0)
            sort_key = gap  # lower gap = closer to price = sorted first
        else:
            status = "ORPHANED"
            drift_str = "N/A"
            level_str = "—"
            buy_at_str = "—"
            hr_str = "—"
            tier_str = "—"
            capped_str = "—"
            gap = float('inf')
            sort_key = float('inf')  # orphans sort last

        if paused_flag:
            status += ", PAUSED"

        rows.append({
            "order": order, "status": status, "drift_str": drift_str,
            "level_str": level_str, "buy_at_str": buy_at_str, "hr_str": hr_str,
            "tier_str": tier_str, "capped_str": capped_str, "gap": gap,
            "sort_key": sort_key, "is_orphan": gap == float('inf'),
        })

    # Sort by gap ascending (nearest to price first) for geographic label assignment
    rows.sort(key=lambda r: r["sort_key"])

    zone_counters = {"A": 0, "B": 0, "R": 0}
    orphan_idx = 0
    verdicts = []
    for row in rows:
        if row["is_orphan"]:
            orphan_idx += 1
            label = f"?{orphan_idx}"
        else:
            zone_letter = assign_zone_label(row["gap"], active_radius)
            if zone_counters[zone_letter] < ZONE_MAX[zone_letter]:
                zone_counters[zone_letter] += 1
                label = f"{zone_letter}{zone_counters[zone_letter]}"
            else:
                label = "—"
        verdicts.append(row["status"])
        print(f"| {label} | {_fmt_dollar(row['order']['price'])} | {row['level_str']} | {row['buy_at_str']} | {row['drift_str']} | {row['hr_str']} | {row['tier_str']} | {row['capped_str']} | {row['status']} |")

    print()

    # Summary verdict
    has_issues = any(v not in ("MATCH", "MATCH, PAUSED") for v in verdicts)
    if not has_issues:
        all_paused = all("PAUSED" in v for v in verdicts)
        if all_paused:
            print("**Verdict: All orders current but PAUSED. Review pause conditions.**")
        else:
            print("**Verdict: All orders current. No adjustment needed.**")
    else:
        issues = [v for v in verdicts if v not in ("MATCH", "MATCH, PAUSED")]
        print(f"**Verdict: {len(issues)} order(s) need review — {', '.join(set(issues))}.**")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Bullet recommender — next order based on portfolio + wick analysis")
    parser.add_argument("tickers", nargs="+", type=str.upper,
                        help="One or more stock ticker symbols")
    parser.add_argument("--mode", choices=["recommend", "audit"], default="recommend",
                        help="recommend (default) or audit existing orders")
    parser.add_argument("--type", choices=["active", "reserve", "any"], default="any",
                        dest="type_filter", help="Filter recommendations (default: any)")
    args = parser.parse_args()

    # Load portfolio and capital config once
    portfolio = _load_portfolio()
    cap = load_capital_config()

    any_success = False
    for i, ticker in enumerate(args.tickers):
        if i > 0:
            print("\n---\n")

        # Run wick analysis
        data, err = analyze_stock_data(ticker)
        if data is None:
            print(f"*Error: wick analysis failed for {ticker}: {err}*")
            continue

        any_success = True
        if args.mode == "recommend":
            run_recommend(ticker, args.type_filter, data, portfolio, cap)
        elif args.mode == "audit":
            run_audit(ticker, data, portfolio)

    if not any_success:
        sys.exit(1)


if __name__ == "__main__":
    main()
