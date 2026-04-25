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
import io
import contextlib
import argparse
import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wick_offset_analyzer import analyze_stock_data, load_capital_config, compute_pool_sizing, sizing_description
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
        # Reserve/Buffer-zone Half-tier: gets ~half weight in pool distribution,
        # consuming a slot for a small allocation. Filter retained
        # to preserve slot efficiency — reserve slots are scarce (max 3).
        if lvl["zone"] in ("Reserve", "Buffer") and lvl.get("effective_tier", lvl["tier"]) == "Half":
            continue
        valid.append(lvl)
    # Display starts with the best support score; fallback to closest to price.
    valid.sort(key=lambda x: (x.get("support_score", 0), x["recommended_buy"]), reverse=True)
    return valid


def merge_convergent_levels(levels, tolerance=CONVERGENCE_TOLERANCE):
    """Merge levels where recommended_buy prices are within tolerance of each other.

    Keep the level with the higher hold rate. Return merged list + merge notes.
    Each surviving level gains a ``merged_from`` list of absorbed participants
    (empty list when no merge occurred) so downstream diffing can resolve
    merged-away support prices.
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
        absorbed = [p for p in participants if p is not best]
        best["merged_from"] = [
            {"price": p["support_price"], "source": p["source"]} for p in absorbed
        ]
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
# Level helpers
# ---------------------------------------------------------------------------

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
# Fill/zone label helpers
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
    """Assign display labels by fill sequence, not support score.

    F1/F2/F3 mean nearest-to-current fill order by Buy At price. This avoids the
    old A1/A2/A3 ambiguity where users could read the label as either score
    rank or fill order. Reserve levels keep R labels, also by fill sequence.

    Returns list of labels parallel to valid_levels.
    """
    labels = ["—"] * len(valid_levels)
    fill_rows = [
        (idx, lvl) for idx, lvl in enumerate(valid_levels)
        if lvl.get("zone") != "Reserve" and lvl.get("recommended_buy")
    ]
    fill_rows.sort(key=lambda item: item[1]["recommended_buy"], reverse=True)
    for seq, (idx, _lvl) in enumerate(fill_rows, 1):
        labels[idx] = f"F{seq}"

    reserve_rows = [
        (idx, lvl) for idx, lvl in enumerate(valid_levels)
        if lvl.get("zone") == "Reserve" and lvl.get("recommended_buy")
    ]
    reserve_rows.sort(key=lambda item: item[1]["recommended_buy"], reverse=True)
    for seq, (idx, _lvl) in enumerate(reserve_rows, 1):
        labels[idx] = f"R{seq}"

    return labels


# ---------------------------------------------------------------------------
# Recommend mode
# ---------------------------------------------------------------------------

def run_recommend(ticker, type_filter, data, portfolio, cap=None):
    """Recommend the next order(s) to place."""
    if cap is None:
        cap = load_capital_config(ticker)
    positions = portfolio.get("positions", {})
    pending_all = portfolio.get("pending_orders", {})
    pending_orders = pending_all.get(ticker, [])
    current_price = data["current_price"]

    warnings = []
    reasoning = []

    # --- Earnings Gate Check ---
    # If earnings are BLOCKED (inside the 7d-before-through-3d-after blackout window),
    # hard-block the bullet output entirely. Previously advisory-only, which allowed
    # orders to be placed during blackout and catch a gap risk. APPROACHING status
    # remains a soft warning.
    try:
        from earnings_gate import check_earnings_gate, format_gate_warning
        gate = check_earnings_gate(ticker)
        if gate["blocked"]:
            now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
            last_date = data.get("as_of", "?")
            print(f"## Bullet Recommendation: {ticker}")
            print(f"*Generated: {now} | Data as of: {last_date}*\n")
            print(f"> ⚠ **EARNINGS BLACKOUT — RECOMMENDATION SUPPRESSED**")
            print(f"> {format_gate_warning(gate)}")
            print(f"> Re-run `bullet_recommender.py {ticker}` after earnings clear.")
            return
        elif gate["status"] == "APPROACHING":
            warnings.append(format_gate_warning(gate))
    except Exception:
        pass  # earnings gate is advisory on import failure, don't crash

    # --- Winding Down Check ---
    if positions.get(ticker, {}).get("winding_down"):
        print(f"## Bullet Recommendation: {ticker}")
        print(f"*{ticker} is winding down — no new bullets. Monitor until position closes.*")
        return

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

            # --- Capital Exhaustion Check ---
            # Hard gate: if actual deployed capital >= pool, no more bullets
            _deployed = shares * avg_cost
            _pool_limit = cap.get("active_pool", 300) if cap else 300
            if _deployed >= _pool_limit:
                print(f"## Bullet Recommendation: {ticker}")
                print(f"*{ticker} is FULLY DEPLOYED — ${_deployed:.0f} deployed "
                      f"vs ${_pool_limit:.0f} pool ({_deployed/_pool_limit*100:.0f}%). "
                      f"No new bullets until position closes or sells down.*")
                # Still show sell target if exists
                for o in pending_orders:
                    if o.get("type") == "SELL":
                        print(f"\nSELL target: ${o['price']:.2f} "
                              f"({(o['price'] - avg_cost) / avg_cost * 100:.1f}% from avg ${avg_cost:.2f})")
                        break
                return
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
        # Fallback: try daily range oscillation analysis
        try:
            from daily_range_analyzer import analyze_daily_range, print_daily_range
            dr = analyze_daily_range(ticker)
            if dr.get("viable"):
                _pool = cap.get("active_pool", 300) if cap else 300
                _dip_budget = round(_pool * 0.245)  # Half-Kelly 24.5% from dip simulation
                print_daily_range(dr, pool_budget=_dip_budget)
                return
        except Exception:
            pass
        _print_no_levels(ticker, current_price, data)
        return

    # --- Strategy Type Check ---
    # Tickers with <3 active-zone levels can't be traded surgically (no averaging).
    # Show daily range as primary strategy instead of useless single-bullet Level Map.
    # Use LIVE wick data (valid_levels), not cached wick_analysis.md.
    _active_count = sum(1 for l in valid_levels
                        if l.get("zone") == "Active"
                        and l.get("effective_tier", l.get("tier", "")) not in ("Skip", ""))
    _strategy_type = "surgical" if _active_count >= 3 else "daily_range"
    if _strategy_type in ("daily_range", "unknown"):
        print(f"## Bullet Recommendation: {ticker}")
        print(f"*Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} | Data as of: {data.get('as_of', '?')}*\n")
        print(f"*{ticker} has {_active_count} active-zone level(s) — insufficient for surgical bullet stacking.*")
        print(f"*Strategy: daily range entry only (dip buy). Surgical bullets not recommended.*\n")
        try:
            from daily_range_analyzer import analyze_daily_range, print_daily_range
            dr = analyze_daily_range(ticker)
            if dr.get("viable"):
                _pool = cap.get("active_pool", 300) if cap else 300
                _dip_budget = round(_pool * 0.245)
                print_daily_range(dr, pool_budget=_dip_budget)
            else:
                print("*Daily range entry not viable for this ticker currently.*")
        except Exception:
            print("*Daily range analysis unavailable.*")
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
    # Buffer levels (dormant, non-promoted) are intentionally excluded from both pools.
    # They get 1-share fallback via sizing_lookup.get() default in the Level Map.
    all_active_levels = [lvl for lvl in valid_levels if lvl["zone"] == "Active"]
    all_reserve_levels = [lvl for lvl in valid_levels if lvl["zone"] == "Reserve"]

    # Concentrated sizing: fresh levels get full pool, dormant get 1-share minimum
    def _concentrated_pool_sizing(levels, pool_budget, pool_name):
        fresh = [lvl for lvl in levels if not lvl.get("dormant", False)]
        dormant = [lvl for lvl in levels if lvl.get("dormant", False)]
        dormant_cost = sum(lvl["recommended_buy"] for lvl in dormant)
        fresh_budget = max(pool_budget - dormant_cost, 0)
        fresh_sized = compute_pool_sizing(fresh, fresh_budget, pool_name) if fresh else []
        dormant_sized = [{
            "shares": 1,
            "cost": lvl["recommended_buy"],
            "dollar_alloc": lvl["recommended_buy"],
            "allocation_action": "reduced",
            "allocation_multiplier": 0.45,
            "allocation_reason": "dormant penalty",
        } for lvl in dormant]
        return fresh, fresh_sized, dormant, dormant_sized

    fresh_a, fresh_a_sized, dormant_a, dormant_a_sized = _concentrated_pool_sizing(
        all_active_levels, cap["active_pool"], "active")
    fresh_r, fresh_r_sized, dormant_r, dormant_r_sized = _concentrated_pool_sizing(
        all_reserve_levels, cap["reserve_pool"], "reserve")

    sizing_lookup = {}
    allocation_lookup = {}
    for lvl, sized in zip(fresh_a, fresh_a_sized):
        sizing_lookup[id(lvl)] = (sized["shares"], sized["cost"])
        allocation_lookup[id(lvl)] = sized
    for lvl, sized in zip(dormant_a, dormant_a_sized):
        sizing_lookup[id(lvl)] = (sized["shares"], sized["cost"])
        allocation_lookup[id(lvl)] = sized
    for lvl, sized in zip(fresh_r, fresh_r_sized):
        sizing_lookup[id(lvl)] = (sized["shares"], sized["cost"])
        allocation_lookup[id(lvl)] = sized
    for lvl, sized in zip(dormant_r, dormant_r_sized):
        sizing_lookup[id(lvl)] = (sized["shares"], sized["cost"])
        allocation_lookup[id(lvl)] = sized

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

    # Clamp to >= 0 for display (can go negative if overdeployed or wick data drifts)
    active_budget_remaining = max(0, active_budget_remaining)
    reserve_budget_remaining = max(0, reserve_budget_remaining)
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
        """Search uncovered levels matching pool zone for the first that fits within budget."""
        target_zone = "Active" if pool == "active" else "Reserve"
        ranked_uncovered = sorted(
            uncovered_levels,
            key=lambda lvl: (lvl.get("support_score", 0), lvl.get("recommended_buy", 0)),
            reverse=True,
        )
        for lvl in ranked_uncovered:
            if lvl["zone"] != target_zone:
                continue
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

    # Earnings gate: suppress recommendation if blocked
    earnings_blocked = any("EARNINGS GATE" in w or "FALLING KNIFE" in w for w in warnings)
    if earnings_blocked and recommendation is not None:
        reasoning.append("Recommendation suppressed — earnings blackout active.")
        recommendation = None

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
        "allocation_lookup": allocation_lookup,
        "uncovered_levels": uncovered_levels,
    }
    _print_recommend(ctx)
    return ctx


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
    allocation_lookup = ctx.get("allocation_lookup", {})
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

    # Show sweep-optimized sell target for comparison
    try:
        from broker_reconciliation import compute_recommended_sell, _load_profiles as _br_load_profiles
        _profiles = _br_load_profiles()
        _rec_price, _rec_source = compute_recommended_sell(ticker, avg_cost, {}, _profiles)
        if _rec_price > 0 and avg_cost > 0:
            _rec_pct = (_rec_price - avg_cost) / avg_cost * 100
            print(f"| Sweep Sell Target | {_fmt_dollar(_rec_price)} = +{_rec_pct:.1f}% ({_rec_source}) |")
    except Exception:
        pass

    print()

    # --- Level Map (unified table) ---
    print("### Level Map")
    print("| Fill Seq | Score | Support | Buy At | Held | Freq | Tier | Trend | Alloc | Shares | ~Cost | Status |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    # SELL target rows first
    for sell_order in pending_sells:
        sell_shares = sell_order.get("shares", "—")
        sell_cost = round(sell_shares * sell_order["price"], 2) if isinstance(sell_shares, (int, float)) else "—"
        sell_placed = "Limit Order" if sell_order.get("placed", True) else "Pending"
        print(f"| SELL | — | {_fmt_dollar(sell_order['price'])} | — | — | — | — "
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
    has_promoted_zone = False
    has_baseline_zone = False

    # Assign fill-sequence labels
    zone_labels = build_zone_labels(valid_levels, active_radius)

    # Track Place vs Monitor counter for active levels
    _place_counter_active = 0

    display_order = sorted(
        range(len(valid_levels)),
        key=lambda i: (
            valid_levels[i].get("zone") == "Reserve",
            -(valid_levels[i].get("recommended_buy") or 0),
        ),
    )

    for lvl_idx in display_order:
        lvl = valid_levels[lvl_idx]
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
        # Zone state tags for status
        zone_tag = ""
        if lvl.get("zone_promoted", False):
            zone_tag = " [P]"
            has_promoted_zone = True
        elif lvl.get("dormant", False):
            zone_tag = " [D]"
        elif lvl.get("zone_baseline", False):
            zone_tag = " [B]"
            has_baseline_zone = True
        support_str = f"{_fmt_dollar(lvl['support_price'])} {lvl['source']}"
        buy_str = _fmt_dollar(lvl["recommended_buy"])
        held = lvl.get("held", 0)
        approaches = lvl.get("total_approaches", 0)
        hold_str = f"{held}/{approaches} ({lvl['hold_rate']:.0f}%)"
        freq_str = f"{lvl.get('monthly_touch_freq', 0):.1f}"

        # Geographic zone label
        level_label = zone_labels[lvl_idx]

        # Compute sizing from batch
        ref_shares, ref_cost = sizing_lookup.get(id(lvl), (1, lvl["recommended_buy"]))
        allocation = allocation_lookup.get(id(lvl), {})
        alloc_str = (
            f"{allocation.get('allocation_action', 'baseline')} "
            f"{allocation.get('allocation_multiplier', 1.0):.2f}x"
        )

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
                # Shares/cost: always show pool-sized values (authoritative).
                # Flag when actual order differs so user knows to resize.
                shares_str = str(ref_shares)
                cost_str = f"~{_fmt_dollar(ref_cost)}"
                ord_shares = order.get("shares")
                if ord_shares and ord_shares != ref_shares:
                    shares_str = f"{ref_shares} (order has {ord_shares})"
                print(f"| {row_label} | {lvl.get('support_score', 0):.1f} | {support_str} | {_fmt_dollar(order['price'])} | {hold_str} | {freq_str} | {tier_display} "
                      f"| {trend_str} | {alloc_str} | {shares_str} | {cost_str} | {status_str}{zone_tag} |")
        elif lid in filled_lookup:
            print(f"| {level_label} | {lvl.get('support_score', 0):.1f} | {support_str} | {buy_str} | {hold_str} | {freq_str} | {tier_display} "
                  f"| {trend_str} | {alloc_str} | {ref_shares} | ~{_fmt_dollar(ref_cost)} | Filled{zone_tag} |")
        elif lid == rec_level_id:
            print(f"| {level_label} | {lvl.get('support_score', 0):.1f} | {support_str} | {buy_str} | {hold_str} | {freq_str} | {tier_display} "
                  f"| {trend_str} | {alloc_str} | {recommendation['shares']} | ~{_fmt_dollar(recommendation['cost'])} | **>> Next**{zone_tag} |")
            # >> Next counts as a Place slot
            if lvl["zone"] == "Active":
                _place_counter_active += 1
        else:
            # Uncovered level — Place, Monitor, or reference-only
            if lvl["zone"] == "Active":
                has_capacity = active_slots_remaining > 0 and active_budget_remaining >= ref_cost
                if has_capacity and _place_counter_active < active_slots_remaining:
                    status_str = ">> Place"
                    _place_counter_active += 1
                elif has_capacity:
                    status_str = "Monitor"
                else:
                    status_str = "—"
            elif lvl["zone"] == "Reserve":
                has_capacity = reserve_slots_remaining > 0 and reserve_budget_remaining >= ref_cost
                status_str = "Available" if has_capacity else "—"
            else:
                status_str = "—"
            if zone_tag:
                status_str = f"{status_str}{zone_tag}" if status_str not in ("—", "Monitor") else f"{status_str}{zone_tag}"
            print(f"| {level_label} | {lvl.get('support_score', 0):.1f} | {support_str} | {buy_str} | {hold_str} | {freq_str} | {tier_display} "
                  f"| {trend_str} | {alloc_str} | {ref_shares} | ~{_fmt_dollar(ref_cost)} | {status_str} |")

    if has_capped or has_promotion or has_demotion or has_promoted_zone or has_baseline_zone:
        markers = []
        if has_promotion:
            markers.append("^ = tier promoted by recent holds")
        if has_demotion:
            markers.append("v = tier demoted by recent breaks")
        if has_capped:
            markers.append("* = capped to Half by approach count (<3)")
        if has_promoted_zone:
            markers.append("[P] = promoted from Buffer to Active (pullback-tested)")
        if has_baseline_zone:
            markers.append("[B] = recent activity near level, not a pullback from above")
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

    # Daily fluctuation supplement — shown for all qualifying tickers
    if data.get("days_above_3pct", 0) >= 60:
        try:
            from daily_range_analyzer import analyze_daily_range, print_daily_range
            dr = analyze_daily_range(ticker)
            if dr.get("viable"):
                print()
                print("### Daily Fluctuation Entry")
                print("*Supplement to support-level bullets — daily oscillation play*\n")
                _pool = cap.get("active_pool", 300) if cap else 300
                _dip_budget = round(_pool * 0.245)  # Half-Kelly 24.5% from dip simulation
                print_daily_range(dr, pool_budget=_dip_budget)
        except Exception:
            pass

    # Legend (always printed)
    _print_legend(active_radius, cap)


def _print_legend(active_radius, cap):
    """Print legend with zone definitions and tier sizing."""
    print("### Legend")
    print("- **Fill Seq** = expected fill order by Buy At price; F1 is the nearest active/buffer BUY")
    print(f"- **A** = Active zone (within {active_radius:.0f}% of price)")
    print(f"- **B** = Buffer zone ({active_radius:.0f}–{2*active_radius:.0f}% from price)")
    print(f"- **R** = Reserve zone (beyond {2*active_radius:.0f}% from price)")
    print(f"- **Held** = Times support held / total approaches in 13 months (hold rate %)")
    desc = sizing_description(cap)
    print(f"- **Sizing** = {desc['one_liner']}")
    print("- **Score** = support quality rank from edge, fill odds, recency, tier, dormancy, and capital lockup")
    print("- **Alloc** = edge-adjusted capital multiplier from expected edge, confidence, fill odds, and risk")
    tw = desc['tier_weights']
    print(f"- **Full** (>=50% hold) = full weight in pool distribution")
    print(f"- **Std** (30-49% hold) = same weight as Full, lower confidence signal")
    print(f"- **Half** (15-29% hold) = {tw['Half']}x weight in pool distribution")
    print(f"- **Tier ^/v** = tier promoted/demoted by recency | **Trend ^/v** = hold-rate trajectory")
    print(f"- **[D]** = dormant (not tested in 90+ days)")
    print(f"- **[P]** = promoted from Buffer to Active (pullback-tested)")
    print(f"- **[B]** = recent activity near level, not a pullback from above")
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

    print("| Fill Seq | Price | Matched Level | Current Buy At | Drift | Hold Rate | Tier | Capped? | Status |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    # Pre-compute row data, then sort by matched price descending for correct zone labels
    rows = []
    for order in pending_buys:
        matched, dist = match_order_to_level(order["price"], all_levels)
        paused_flag = is_paused(order)

        if matched is not None:
            status = classify_drift(dist)
            # Zone state tag (display only, not part of verdict)
            zone_tag = ""
            if matched.get("zone_promoted", False):
                zone_tag = " [P]"
            elif matched.get("dormant", False):
                zone_tag = " [D]"
            elif matched.get("zone_baseline", False):
                zone_tag = " [B]"
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
            sort_key = -(matched.get("recommended_buy") or 0)
        else:
            status = "ORPHANED"
            zone_tag = ""
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
            "order": order, "status": status, "zone_tag": zone_tag,
            "drift_str": drift_str,
            "level_str": level_str, "buy_at_str": buy_at_str, "hr_str": hr_str,
            "tier_str": tier_str, "capped_str": capped_str, "gap": gap,
            "sort_key": sort_key, "is_orphan": gap == float('inf'),
        })

    # Sort by Buy At descending for fill-sequence label assignment.
    rows.sort(key=lambda r: r["sort_key"])

    fill_counter = 0
    reserve_counter = 0
    orphan_idx = 0
    verdicts = []
    for row in rows:
        if row["is_orphan"]:
            orphan_idx += 1
            label = f"?{orphan_idx}"
        else:
            zone_letter = assign_zone_label(row["gap"], active_radius)
            if zone_letter == "R":
                reserve_counter += 1
                label = f"R{reserve_counter}"
            else:
                fill_counter += 1
                label = f"F{fill_counter}"
        verdicts.append(row["status"])
        display_status = f"{row['status']}{row['zone_tag']}"
        print(f"| {label} | {_fmt_dollar(row['order']['price'])} | {row['level_str']} | {row['buy_at_str']} | {row['drift_str']} | {row['hr_str']} | {row['tier_str']} | {row['capped_str']} | {display_status} |")

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
# JSON serialization helpers
# ---------------------------------------------------------------------------

def _level_to_dict(lvl, sizing_lookup):
    """Convert a wick level dict to JSON-serializable form."""
    shares, cost = sizing_lookup.get(id(lvl), (1, lvl.get("recommended_buy") or 0.0))
    return {
        "support_price": lvl.get("support_price"),
        "recommended_buy": lvl.get("recommended_buy"),
        "source": lvl.get("source"),
        "hold_rate": lvl.get("hold_rate"),
        "tier": lvl.get("tier"),
        "zone": lvl.get("zone"),
        "rec_shares": shares,
        "rec_cost": cost,
    }


def _ctx_to_json(ctx):
    """Extract JSON-serializable subset of ctx for machine consumption."""
    sizing = ctx.get("sizing_lookup", {})
    parsed = ctx["parsed"]

    covered = []
    for cl in ctx["covered_levels"]:
        covered.append({
            "level": _level_to_dict(cl["level"], sizing),
            "order_price": cl["order"]["price"],
            "order_shares": cl["order"].get("shares", 0),
            "drift_status": classify_drift(cl["dist"]),
            "duplicate": cl.get("duplicate", False),
            "paused": cl.get("paused", False),
        })

    orphaned = []
    for o in ctx["orphaned_orders"]:
        orphaned.append({
            "price": o["price"],
            "shares": o.get("shares", 0),
            "note": o.get("note", ""),
        })

    filled = [_level_to_dict(fl, sizing) for fl in ctx["filled_levels"]]
    available = [_level_to_dict(ul, sizing) for ul in ctx.get("uncovered_levels", [])]

    rec = ctx["recommendation"]
    rec_out = None
    if rec is not None:
        rec_out = {
            "level": _level_to_dict(rec["level"], sizing),
            "shares": rec["shares"],
            "cost": rec["cost"],
            "pool": rec["pool"],
            "label": rec["label"],
        }

    pending_sells_out = []
    for ps in ctx["pending_sells"]:
        pending_sells_out.append({
            "price": ps["price"],
            "shares": ps.get("shares", 0),
            "placed": ps.get("placed", False),
        })

    sc = ctx["sell_check"]
    sell_check_out = None
    if sc is not None:
        sell_check_out = {
            "sell_price": sc["sell_price"],
            "pct_from_avg": sc["pct_from_avg"],
            "stale": sc["stale"],
        }

    return {
        "ticker": ctx["ticker"],
        "current_price": ctx["current_price"],
        "shares": ctx["shares"],
        "avg_cost": ctx["avg_cost"],
        "bullets_used": {
            "active": parsed["active"],
            "reserve": parsed["reserve"],
            "pre_strategy": parsed["pre_strategy"],
        },
        "active_slots_remaining": ctx["active_slots_remaining"],
        "reserve_slots_remaining": ctx["reserve_slots_remaining"],
        "active_budget_remaining": ctx["active_budget_remaining"],
        "reserve_budget_remaining": ctx["reserve_budget_remaining"],
        "is_pre_strategy": ctx["is_pre_strategy"],
        "covered_levels": covered,
        "orphaned_orders": orphaned,
        "filled_levels": filled,
        "available_levels": available,
        "recommendation": rec_out,
        "pending_sells": pending_sells_out,
        "sell_check": sell_check_out,
        "fully_deployed": ctx["fully_deployed"],
    }


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
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Output structured JSON instead of markdown")
    args = parser.parse_args()

    # Load portfolio once; capital config loaded per-ticker in each path
    portfolio = _load_portfolio()

    if args.json_output:
        if args.mode == "audit":
            print("Error: --json is only supported with --mode recommend", file=sys.stderr)
            sys.exit(1)
        results = []
        for ticker in args.tickers:
            ticker_cap_json = load_capital_config(ticker)  # per-ticker pool
            data, err = analyze_stock_data(ticker, capital_config=ticker_cap_json)
            if data is None:
                continue
            with contextlib.redirect_stdout(io.StringIO()):
                ctx = run_recommend(ticker, args.type_filter, data, portfolio, ticker_cap_json)
            if ctx is not None:
                results.append(_ctx_to_json(ctx))
        print(json.dumps(results, indent=2))
    else:
        any_success = False
        for i, ticker in enumerate(args.tickers):
            if i > 0:
                print("\n---\n")

            # Per-ticker pool allocation (simulation-backed if available)
            ticker_cap = load_capital_config(ticker)

            # Run wick analysis with per-ticker pool for correct bullet sizing
            data, err = analyze_stock_data(ticker, capital_config=ticker_cap)
            if data is None:
                print(f"*Error: wick analysis failed for {ticker}: {err}*")
                continue

            # Wick data freshness check
            last_date = data.get("last_date", "")
            if last_date:
                try:
                    from datetime import datetime, date
                    wick_date = datetime.strptime(last_date, "%Y-%m-%d").date()
                    age = (date.today() - wick_date).days
                    if age > 7:
                        print(f"\n> *WARNING: Wick data is {age} days old ({last_date}). "
                              f"Re-run `python3 tools/wick_offset_analyzer.py {ticker}` for fresh levels.*")
                except (ValueError, TypeError):
                    pass

            any_success = True
            if args.mode == "recommend":
                run_recommend(ticker, args.type_filter, data, portfolio, ticker_cap)
            elif args.mode == "audit":
                run_audit(ticker, data, portfolio)

        if not any_success:
            sys.exit(1)


if __name__ == "__main__":
    main()
