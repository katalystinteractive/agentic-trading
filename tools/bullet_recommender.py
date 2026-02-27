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
        if lvl["tier"] == "Skip":
            continue
        # Reserve-zone Half-tier: not worth a reserve slot at $30 sizing
        if lvl["zone"] == "Reserve" and lvl["tier"] == "Half":
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
    if level["tier"] == "Half":
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

    # --- Step 5: Compute deployment state ---
    # Derive effective slot usage from UNIQUE covered levels (V4-F2)
    # Don't double-count duplicates (two orders at same level = 1 slot)
    covered_active = sum(1 for cl in covered_levels if cl["level"]["zone"] == "Active" and not cl.get("duplicate"))
    covered_reserve = sum(1 for cl in covered_levels if cl["level"]["zone"] == "Reserve" and not cl.get("duplicate"))
    effective_active_used = max(parsed["active"], covered_active)
    effective_reserve_used = max(parsed["reserve"], covered_reserve)

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
    next_available = []

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

    # Gather next available after recommendation
    if recommendation is not None:
        rec_level = recommendation["level"]
        remaining_after = [lvl for lvl in uncovered_levels if lvl is not rec_level]
        # Figure out what pool/label subsequent levels get
        if recommendation["pool"] == "active":
            remaining_active = active_slots_remaining - 1
            remaining_reserve = reserve_slots_remaining
        else:
            remaining_active = 0  # active already exhausted
            remaining_reserve = reserve_slots_remaining - 1

        slot_idx_active = effective_active_used + (1 if recommendation["pool"] == "active" else 0)
        slot_idx_reserve = effective_reserve_used + (1 if recommendation["pool"] == "reserve" else 0)

        for lvl in remaining_after[:2]:
            if remaining_active > 0:
                p = "active"
                slot_idx_active += 1
                label = f"A{slot_idx_active}"
                remaining_active -= 1
            elif remaining_reserve > 0:
                p = "reserve"
                slot_idx_reserve += 1
                label = f"R{slot_idx_reserve}"
                remaining_reserve -= 1
            else:
                break
            s, c, _ = compute_sizing(lvl, p, cap)
            capped, was_tier = is_capped(lvl)
            next_available.append({
                "level": lvl, "shares": s, "cost": c, "pool": p, "label": label,
                "capped": capped, "was_tier": was_tier,
            })

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
        "recommendation": recommendation, "next_available": next_available,
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
    next_available = ctx["next_available"]
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
            print(f"| Effective Deployed | {effective_active_used} active ({parsed['active']} filled + {effective_active_used - parsed['active']} pending), {effective_reserve_used} reserve |")
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

    # Covered levels table
    if covered_levels:
        print("### Covered Levels")
        print("| # | Level | Order Price | Drift | Status |")
        print("| :--- | :--- | :--- | :--- | :--- |")
        for i, cl in enumerate(covered_levels, 1):
            lvl = cl["level"]
            order = cl["order"]
            drift_pct = f"{cl['dist'] * 100:.1f}%" if cl["dist"] is not None else "N/A"
            status = classify_drift(cl["dist"])
            if cl.get("duplicate"):
                status += ", DUP"
            if cl["paused"]:
                # Extract paused reason from note
                note = order.get("note", "")
                paused_match = re.search(r'PAUSED\s*(.*?)$', note, re.IGNORECASE)
                paused_reason = paused_match.group(1).strip(" —-") if paused_match else ""
                status += f" (PAUSED{' — ' + paused_reason if paused_reason else ''})"
            print(f"| B{i} | {_fmt_dollar(lvl['support_price'])} {lvl['source']} | {_fmt_dollar(order['price'])} | {drift_pct} | {status} |")
        print()

    # Orphaned orders
    if orphaned_orders:
        print("### Orphaned Orders (no matching wick level)")
        print("| Order Price | Note |")
        print("| :--- | :--- |")
        for o in orphaned_orders:
            print(f"| {_fmt_dollar(o['price'])} | {o.get('note', '')} |")
        print()

    # Recommendation
    if fully_deployed:
        print("### Fully Deployed")
        print("No additional BUY orders recommended. All slots filled or covered.")
        print()
    elif recommendation is not None:
        lvl = recommendation["level"]
        capped, was_tier = is_capped(lvl)
        capped_str = f"Yes (was {was_tier}, <3 approaches)" if capped else "No"
        dist_pct = (current_price - lvl["recommended_buy"]) / current_price * 100
        print(f"### Recommendation: {recommendation['label']}")
        print("| Field | Value |")
        print("| :--- | :--- |")
        print(f"| Raw Support | {_fmt_dollar(lvl['support_price'])} {lvl['source']} |")
        print(f"| Buy At | {_fmt_dollar(lvl['recommended_buy'])} |")
        print(f"| Hold Rate | {lvl['hold_rate']:.0f}% ({lvl['tier']} tier) |")
        print(f"| Approaches | {lvl['total_approaches']} |")
        print(f"| Capped? | {capped_str} |")
        print(f"| Shares | {recommendation['shares']} |")
        print(f"| Est. Cost | ~{_fmt_dollar(recommendation['cost'])} |")
        print(f"| Distance | {dist_pct:.1f}% below current ({_fmt_dollar(current_price)}) |")
        print()

        # Reasoning
        print("### Reasoning")
        print(f"- First uncovered support below current price with hold rate >= 15%")
        if recommendation["pool"] == "reserve" and lvl["zone"] == "Active":
            print(f"- Active slots exhausted — drawing from reserve budget at Active-zone price")
        budget_label = "active" if recommendation["pool"] == "active" else "reserve"
        budget_remaining = active_budget_remaining if recommendation["pool"] == "active" else reserve_budget_remaining
        print(f"- Budget: ~{_fmt_dollar(recommendation['cost'])} of {_fmt_dollar(budget_remaining)} {budget_label} remaining")
        for note in reasoning:
            print(f"- {note}")
        print()

        # Next available
        if next_available:
            print("### Next Available")
            print("| # | Level | Buy At | Hold% | Tier | Capped? | Shares | ~Cost |")
            print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            for na in next_available:
                nl = na["level"]
                c_flag = f"Yes (was {na['was_tier']}, <3 approaches)" if na["capped"] else "No"
                print(f"| {na['label']} | {_fmt_dollar(nl['support_price'])} {nl['source']} | "
                      f"{_fmt_dollar(nl['recommended_buy'])} | {nl['hold_rate']:.0f}% | "
                      f"{nl['tier']} | {c_flag} | {na['shares']} | ~{_fmt_dollar(na['cost'])} |")
            print()
    else:
        print("### No Recommendation")
        if active_slots_remaining == 0 and reserve_slots_remaining == 0:
            print("All slots occupied. No room for additional orders.")
        elif not reasoning:
            print("No uncovered levels available within budget.")
        else:
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
            tier_str = matched["tier"]
            capped, was_tier = is_capped(matched)
            capped_str = f"Yes (was {was_tier}, <3 approaches)" if capped else "No"
            # Check if level now has 0% hold rate
            if matched["hold_rate"] == 0:
                status = "DEAD"
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
