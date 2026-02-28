"""Bullet recommender: bridges wick analysis and portfolio state.

Given a ticker, determines what bullets are already deployed (filled + pending),
which wick levels are covered, and recommends the next order(s) to place.

Usage:
    python3 tools/bullet_recommender.py APLD                    # recommend next order
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
from wick_offset_analyzer import analyze_stock_data, load_capital_config


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MATCH_TOLERANCE = 0.005   # 0.5% — tighter than 2% to handle SOUN B1/B2 0.7% apart
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
        reserve = len(re.findall(r'R\d+\s+filled', raw))
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
        # Reserve-zone Half-tier: not worth a reserve slot at $30 sizing
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
    """Tier-aware sizing.

    pool = "active" or "reserve" — the CALLER determines which budget pool
    this bullet draws from, NOT the level's geographic zone label.
    Half tier always uses active_bullet_half ($30) regardless of pool.
    """
    if level.get("effective_tier", level["tier"]) == "Half":
        size = cap["active_bullet_half"]   # $30 for Half, regardless of pool
    elif pool == "active":
        size = cap["active_bullet_full"]   # $60 for Full/Std in active pool
    else:
        size = cap["reserve_bullet_size"]  # $100 for Full/Std in reserve pool
    shares = max(1, int(size / level["recommended_buy"]))
    cost = round(shares * level["recommended_buy"], 2)
    return shares, cost, size


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
# Recommend mode
# ---------------------------------------------------------------------------

def run_recommend(ticker, type_filter, data, portfolio):
    """Recommend the next order(s) to place."""
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
        _print_no_levels(ticker, current_price)
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

    # --- Step 4b: Mark filled levels (display only) ---
    # Filled bullets are executed orders no longer pending. We don't track
    # individual fill prices, so use avg_cost as a proxy: candidate levels are
    # plausible fills only if their average buy price is within 20% of avg_cost.
    # This prevents marking deep levels as "Filled" when actual fills were at
    # prices above current (filtered out of valid_levels).
    total_fills = parsed["active"] + parsed["reserve"]
    fills_in_map = 0
    if total_fills > 0 and case == "A" and avg_cost > 0:
        candidates = uncovered_levels[:total_fills]
        if candidates:
            avg_candidate_buy = sum(l["recommended_buy"] for l in candidates) / len(candidates)
            if avg_candidate_buy >= avg_cost * 0.8:
                fills_in_map = len(candidates)
    filled_levels = uncovered_levels[:fills_in_map]
    uncovered_levels = uncovered_levels[fills_in_map:]

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

    # Budget computation
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
        active_budget_remaining = cap["active_pool"] - (parsed["active"] * cap["active_bullet_full"])
        reserve_budget_remaining = cap["reserve_pool"] - (parsed["reserve"] * cap["reserve_bullet_size"])
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
            shares, cost, _ = compute_sizing(lvl, pool, cap)
            if cost <= budget:
                return {"level": lvl, "shares": shares, "cost": cost,
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
        standard_target = avg_cost * 1.10
        sell_check = {
            "sell_price": sell_price,
            "pct_from_avg": pct_from_avg,
            "standard_target": standard_target,
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
        "pending_buys": pending_buys, "covered_levels": covered_levels,
        "orphaned_orders": orphaned_orders, "sell_check": sell_check,
        "recommendation": recommendation, "valid_levels": valid_levels,
        "filled_levels": filled_levels,
        "covered_active": covered_active, "covered_reserve": covered_reserve,
        "fully_deployed": fully_deployed, "warnings": warnings,
        "reasoning": reasoning, "cap": cap,
    }
    _print_recommend(ctx)


# ---------------------------------------------------------------------------
# Output formatting — recommend mode
# ---------------------------------------------------------------------------

def _fmt_dollar(val):
    if val is None:
        return "N/A"
    return f"${val:.2f}"


def _print_no_levels(ticker, current_price):
    """Print output when no eligible levels found."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"## Bullet Recommendation: {ticker}")
    print(f"*Generated: {now}*")
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
    covered_levels = ctx["covered_levels"]
    orphaned_orders = ctx["orphaned_orders"]
    sell_check = ctx["sell_check"]
    recommendation = ctx["recommendation"]
    valid_levels = ctx["valid_levels"]
    filled_levels = ctx["filled_levels"]
    covered_active = ctx["covered_active"]
    covered_reserve = ctx["covered_reserve"]
    fully_deployed = ctx["fully_deployed"]
    warnings = ctx["warnings"]
    reasoning = ctx["reasoning"]
    cap = ctx["cap"]
    effective_reserve_used = ctx["effective_reserve_used"]

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"## Bullet Recommendation: {ticker}")
    print(f"*Generated: {now}*")
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
    elif case == "C":
        print(f"| Shares | 0 |")
        if pending_buys:
            print(f"| Pending BUYs | {len(pending_buys)} orders covering {sum(1 for cl in covered_levels if not cl.get('duplicate'))} levels |")
        print(f"| Slots Remaining | Active: {active_slots_remaining} | Reserve: {reserve_slots_remaining} |")
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
    print("| # | Support | Buy At | Held/Approaches | Tier | Trend | Shares | ~Cost | Status |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    # Build covered lookup: level id -> list of cover entries
    covered_lookup = {}
    for cl in covered_levels:
        lid = id(cl["level"])
        covered_lookup.setdefault(lid, []).append(cl)

    rec_level_id = id(recommendation["level"]) if recommendation else None
    filled_lookup = set(id(fl) for fl in filled_levels)
    a_max = cap["active_bullets_max"]
    r_max = cap["reserve_bullets_max"]
    has_capped = False
    has_override = False

    # Label offset: fills not visible in the map still consumed slots
    if case == "A":
        fills_active_in_map = sum(1 for fl in filled_levels if fl["zone"] == "Active")
        fills_reserve_in_map = sum(1 for fl in filled_levels if fl["zone"] == "Reserve")
        a_idx = parsed["active"] - fills_active_in_map
        r_idx = parsed["reserve"] - fills_reserve_in_map
    else:
        a_idx = 0
        r_idx = 0

    for lvl in valid_levels:
        lid = id(lvl)
        capped_flag, was_tier = is_capped(lvl)
        tier_display = lvl.get("effective_tier", lvl["tier"])
        if lvl.get("tier_override", False):
            tier_display += "+"
            has_override = True
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

        # Assign bullet label — every level gets one (A1-A5, R1-R3, then —)
        if a_idx < a_max:
            a_idx += 1
            level_label = f"A{a_idx}"
            ref_pool = "active"
        elif r_idx < r_max:
            r_idx += 1
            level_label = f"R{r_idx}"
            ref_pool = "reserve"
        else:
            level_label = "—"
            ref_pool = "reserve"

        # Compute sizing
        ref_shares, ref_cost, _ = compute_sizing(lvl, ref_pool, cap)

        if lid in covered_lookup:
            for cl in covered_lookup[lid]:
                order = cl["order"]
                # DUP rows don't consume a label
                row_label = "—" if cl.get("duplicate") else level_label
                # Status based on placed flag + issue flags
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
                    status_str = f"Limit order placed{flags}"
                else:
                    status_str = f"Place limit order{flags}"
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
                  f"| {trend_str} | {ref_shares} | ~{_fmt_dollar(ref_cost)} | Order filled{dormant_tag} |")
        elif lid == rec_level_id:
            print(f"| {level_label} | {support_str} | {buy_str} | {hold_str} | {tier_display} "
                  f"| {trend_str} | {recommendation['shares']} | ~{_fmt_dollar(recommendation['cost'])} | **Place limit order**{dormant_tag} |")
        else:
            print(f"| {level_label} | {support_str} | {buy_str} | {hold_str} | {tier_display} "
                  f"| {trend_str} | {ref_shares} | ~{_fmt_dollar(ref_cost)} | {dormant_tag.strip()} |")

    if has_capped or has_override:
        markers = []
        if has_override:
            markers.append("+ = tier downgraded by recency")
        if has_capped:
            markers.append("* = capped to Std by approach count")
        print()
        print(f"*{'; '.join(markers)}*")
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


# ---------------------------------------------------------------------------
# Audit mode
# ---------------------------------------------------------------------------

def run_audit(ticker, data, portfolio):
    """Audit existing pending orders against current wick levels."""
    pending_all = portfolio.get("pending_orders", {})
    pending_orders = pending_all.get(ticker, [])
    pending_buys = [o for o in pending_orders if o["type"] == "BUY"]
    current_price = data["current_price"]

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"## Order Audit: {ticker}")
    print(f"*Generated: {now}*")
    print(f"*Current Price: {_fmt_dollar(current_price)}*")
    print()

    if not pending_buys:
        print(f"No pending BUY orders for {ticker}.")
        return

    # Build valid levels (include all for audit — don't filter by current price)
    all_levels = [lvl for lvl in data["levels"] if lvl["recommended_buy"] is not None]

    print("| Order | Price | Matched Level | Current Buy At | Drift | Hold Rate | Tier | Capped? | Status |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    verdicts = []
    for i, order in enumerate(pending_buys, 1):
        matched, dist = match_order_to_level(order["price"], all_levels)
        paused_flag = is_paused(order)

        if matched is not None:
            status = classify_drift(dist)
            drift_str = f"{dist * 100:.1f}%"
            level_str = f"{_fmt_dollar(matched['support_price'])} {matched['source']}"
            buy_at_str = _fmt_dollar(matched["recommended_buy"])
            hr_str = f"{matched['hold_rate']:.0f}%"
            tier_str = matched.get("effective_tier", matched["tier"])
            capped, was_tier = is_capped(matched)
            capped_str = f"Yes (was {was_tier}, <3 approaches)" if capped else "No"
        else:
            status = "ORPHANED"
            drift_str = "N/A"
            level_str = "—"
            buy_at_str = "—"
            hr_str = "—"
            tier_str = "—"
            capped_str = "—"

        if paused_flag:
            status += ", PAUSED"

        verdicts.append(status)
        label = f"B{i}"
        print(f"| {label} | {_fmt_dollar(order['price'])} | {level_str} | {buy_at_str} | {drift_str} | {hr_str} | {tier_str} | {capped_str} | {status} |")

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
    parser.add_argument("ticker", type=str, help="Stock ticker symbol")
    parser.add_argument("--mode", choices=["recommend", "audit"], default="recommend",
                        help="recommend (default) or audit existing orders")
    parser.add_argument("--type", choices=["active", "reserve", "any"], default="any",
                        dest="type_filter", help="Filter recommendations (default: any)")
    args = parser.parse_args()
    ticker = args.ticker.upper()

    # Load portfolio
    portfolio = _load_portfolio()

    # Run wick analysis
    data, err = analyze_stock_data(ticker)
    if data is None:
        print(f"*Error: wick analysis failed for {ticker}: {err}*")
        sys.exit(1)

    if args.mode == "recommend":
        run_recommend(ticker, args.type_filter, data, portfolio)
    elif args.mode == "audit":
        run_audit(ticker, data, portfolio)


if __name__ == "__main__":
    main()
