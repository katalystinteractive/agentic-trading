"""Per-stock, per-level wick offset analysis against historical support.

Identifies support levels (volume profile HVN floors + price-action clusters),
then measures how actual wicks behaved at EACH level over 13 months.
Outputs a concrete recommended buy price for every support level.

Usage:
    python3 tools/wick_offset_analyzer.py STIM         # single stock, per-level detail
    python3 tools/wick_offset_analyzer.py STIM NU AR   # multiple stocks
    python3 tools/wick_offset_analyzer.py              # all portfolio tickers
"""
import sys
import json
import datetime
import math
import numpy as np
import yfinance as yf
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"
TICKERS_DIR = _ROOT / "tickers"


def _write_cache(ticker, filename, report):
    ticker_dir = TICKERS_DIR / ticker
    ticker_dir.mkdir(parents=True, exist_ok=True)
    with open(ticker_dir / filename, "w") as f:
        f.write(report + "\n")


def _load_portfolio():
    with open(PORTFOLIO_PATH, "r") as f:
        return json.load(f)


def load_tickers_from_portfolio():
    portfolio = _load_portfolio()
    tickers = set()
    tickers.update(portfolio.get("positions", {}).keys())
    tickers.update(portfolio.get("pending_orders", {}).keys())
    tickers.update(portfolio.get("watchlist", []))
    return sorted(tickers)


def load_capital_config():
    """Load bullet sizing config from portfolio.json capital section."""
    portfolio = _load_portfolio()
    cap = portfolio.get("capital", {})
    return {
        "active_pool": cap.get("active_pool", 300),
        "reserve_pool": cap.get("reserve_pool", 300),
        "active_bullets_max": cap.get("active_bullets_max", 5),
        "reserve_bullets_max": cap.get("reserve_bullets_max", 3),
    }


# Pool sizing constants
POOL_TIER_MULT = {"Full": 1.0, "Std": 1.0, "Half": 0.5}
POOL_MAX_FRACTION = 0.60  # per-bullet cap: 60% of pool (raised for frequency weighting)
ACTIVE_RADIUS_CAP = 20.0  # max active zone radius (%)


def sizing_description(cap=None):
    """Return human-readable sizing strings derived from actual constants.

    Single source of truth for sizing descriptions. All display tools
    and agent personas should use these strings instead of hardcoding.
    """
    if cap is None:
        cap = load_capital_config()
    return {
        "method": "pool-distributed (equal impact)",
        "active_pool": cap["active_pool"],
        "reserve_pool": cap["reserve_pool"],
        "active_max": cap["active_bullets_max"],
        "reserve_max": cap["reserve_bullets_max"],
        "tier_weights": dict(POOL_TIER_MULT),
        "max_fraction_pct": int(POOL_MAX_FRACTION * 100),
        # Pre-built display strings
        "one_liner": (
            f"${cap['active_pool']} active / ${cap['reserve_pool']} reserve pool, "
            f"distributed across all levels (equal impact)"
        ),
        "capital_note": (
            f"Active pool = ${cap['active_pool']}/stock (up to {cap['active_bullets_max']} bullets), "
            f"Reserve pool = ${cap['reserve_pool']}/stock (up to {cap['reserve_bullets_max']} bullets). "
            f"Pool-distributed sizing: each bullet buys roughly equal shares "
            f"(equal averaging impact). Half-tier = {POOL_TIER_MULT['Half']}x weight. "
            f"Per-bullet cap: {int(POOL_MAX_FRACTION * 100)}% of pool."
        ),
        "tier_rules": (
            f"Full (>=50% hold) = full weight in pool distribution. "
            f"Std (30-49%) = same weight as Full. "
            f"Half (15-29%) = {POOL_TIER_MULT['Half']}x weight. "
            f"Skip (<15%) = excluded."
        ),
        "verification_note": (
            "Bullet shares/costs are computed by compute_pool_sizing() — "
            "do NOT verify against fixed dollar amounts. "
            f"Verify: total active cost <= ${cap['active_pool']}, "
            f"total reserve cost <= ${cap['reserve_pool']}, "
            f"active count <= {cap['active_bullets_max']}, "
            f"reserve count <= {cap['reserve_bullets_max']}."
        ),
    }


def compute_pool_sizing(levels, pool_budget, pool_name="active"):
    """Distribute pool_budget across levels for equal averaging impact.

    Args:
        levels: list of dicts with keys: recommended_buy, effective_tier (or tier),
                hold_rate (used for residual redistribution)
        pool_budget: total dollars to distribute (e.g. 300 for active)
        pool_name: "active" or "reserve" (for logging only)

    Returns:
        list of dicts (same order as input) with added keys: shares, cost, dollar_alloc
    """
    if not levels:
        return []
    if pool_budget <= 0:
        return [{"recommended_buy": lv["recommended_buy"], "hold_rate": lv.get("hold_rate", 0),
                 "monthly_touch_freq": lv.get("monthly_touch_freq", 0),
                 "shares": 1, "cost": lv["recommended_buy"],
                 "dollar_alloc": lv["recommended_buy"]} for lv in levels]

    result = []
    for lv in levels:
        price = lv["recommended_buy"]
        tier = lv.get("effective_tier", lv.get("tier", "Full"))
        mult = POOL_TIER_MULT.get(tier, 1.0)
        freq = lv.get("monthly_touch_freq", 1.0)
        freq_boost = max(1.0, freq)  # floor at 1.0 — no penalty for low freq
        weight = price * mult * freq_boost
        result.append({
            "recommended_buy": price,
            "hold_rate": lv.get("hold_rate", 0),
            "monthly_touch_freq": freq,
            "_weight": weight, "_tier_mult": mult,
        })

    total_weight = sum(r["_weight"] for r in result)
    if total_weight == 0:
        return result

    # First pass: allocate dollars proportional to weight, apply per-bullet cap
    cap_dollars = pool_budget * POOL_MAX_FRACTION
    uncapped = []
    uncapped_weight = 0
    remaining_budget = pool_budget

    for r in result:
        raw_alloc = (r["_weight"] / total_weight) * pool_budget
        if raw_alloc > cap_dollars:
            r["_capped"] = True
            r["_dollar_alloc"] = cap_dollars
            remaining_budget -= cap_dollars
        else:
            r["_capped"] = False
            uncapped_weight += r["_weight"]
            uncapped.append(r)

    # Second pass: redistribute remaining budget among uncapped levels
    for r in uncapped:
        if uncapped_weight > 0:
            r["_dollar_alloc"] = (r["_weight"] / uncapped_weight) * remaining_budget
        else:
            r["_dollar_alloc"] = 0

    # Convert dollars to shares (floor), compute actual cost
    for r in result:
        price = r["recommended_buy"]
        shares = max(1, int(r["_dollar_alloc"] / price))
        cost = round(shares * price, 2)
        r["shares"] = shares
        r["cost"] = cost
        r["dollar_alloc"] = round(r["_dollar_alloc"], 2)

    # Residual redistribution: leftover dollars → extra shares to highest frequency levels
    total_spent = sum(r["cost"] for r in result)
    leftover = pool_budget - total_spent
    if leftover > 0:
        by_freq = sorted(range(len(result)),
                         key=lambda i: result[i].get("monthly_touch_freq", 0), reverse=True)
        for i in by_freq:
            price = result[i]["recommended_buy"]
            if leftover >= price:
                extra = int(leftover / price)
                result[i]["shares"] += extra
                result[i]["cost"] = round(result[i]["shares"] * price, 2)
                leftover = round(leftover - extra * price, 6)

    # Clean up internal keys
    for r in result:
        r.pop("_weight", None)
        r.pop("_tier_mult", None)
        r.pop("_capped", None)
        r.pop("_dollar_alloc", None)

    return result


def fetch_history(ticker, months=13):
    """Fetch ~13 months of daily OHLCV data."""
    t = yf.Ticker(ticker)
    start = (datetime.datetime.now() - datetime.timedelta(days=months * 31)).strftime("%Y-%m-%d")
    hist = t.history(start=start)
    return hist


def _monthly_swings(hist):
    """Compute per-month swing percentages, excluding incomplete current month."""
    monthly = hist.resample('ME').agg({'High': 'max', 'Low': 'min'})
    monthly = monthly.dropna()
    # Drop incomplete current month — partial data skews swing downward
    now = datetime.datetime.now()
    if len(monthly) > 0 and monthly.index[-1].month == now.month and monthly.index[-1].year == now.year:
        monthly = monthly.iloc[:-1]
    if len(monthly) < 3:
        return None
    return ((monthly['High'] - monthly['Low']) / monthly['Low'] * 100).values


def compute_monthly_swing(hist):
    """Median monthly (high-low)/low % from daily data."""
    swings = _monthly_swings(hist)
    if swings is None:
        return None
    return float(np.median(swings))


def compute_swing_consistency(hist, threshold=10.0):
    """Percentage of months where swing >= threshold%. Returns 0-100 float."""
    swings = _monthly_swings(hist)
    if swings is None:
        return None
    above = sum(1 for s in swings if s >= threshold)
    return round(above / len(swings) * 100, 1)


def classify_level(hold_rate, gap_pct, active_radius, approaches=0):
    """Classify a support level into Zone (Active/Buffer/Reserve) and Tier.

    Zone: Active if gap_pct <= active_radius, Buffer if <= 2× active_radius, else Reserve.
    Buffer levels are candidates for recency-based promotion to Active.
    Tier (hold_rate is 0-100%): Full (50%+), Std (30-49%), Half (15-29%), Skip (<15%).
    Confidence gate: Full/Std require 3+ approaches; fewer approaches cap at Half.
    """
    if gap_pct <= active_radius:
        zone = "Active"
    elif gap_pct <= 2 * active_radius:
        zone = "Buffer"
    else:
        zone = "Reserve"
    if hold_rate >= 50:
        tier = "Full"
    elif hold_rate >= 30:
        tier = "Std"
    elif hold_rate >= 15:
        tier = "Half"
    else:
        tier = "Skip"
    # Confidence gate: cap at Half if insufficient sample size
    if tier in ("Full", "Std") and approaches < 3:
        tier = "Half"
    return zone, tier


def compute_effective_tier(raw_tier, decayed_tier):
    """Compute effective tier from raw and decayed tiers.

    Effective tier follows decayed tier (recent behavior determines sizing).
    Promotion floor: never promote more than one tier above raw.
    Demotions are unrestricted.
    """
    tier_order = {"Skip": 0, "Half": 1, "Std": 2, "Full": 3}
    tier_names = {v: k for k, v in tier_order.items()}
    if tier_order[decayed_tier] > tier_order[raw_tier] + 1:
        effective = tier_names[tier_order[raw_tier] + 1]
    else:
        effective = decayed_tier
    promoted = tier_order[effective] > tier_order[raw_tier]
    return effective, promoted


def find_hvn_floors(hist, n_bins=40):
    """Build volume profile, return HVN floor prices with their volume."""
    lows = hist["Low"].values
    highs = hist["High"].values
    volumes = hist["Volume"].values
    dates = hist.index

    price_min, price_max = lows.min(), highs.max()
    bin_edges = np.linspace(price_min * 0.95, price_max * 1.05, n_bins + 1)

    # 180-day half-life decay for volume (institutional zones are stickier)
    reference = dates[-1].to_pydatetime().replace(tzinfo=None)

    vol_by_bin = np.zeros(n_bins)
    for i in range(len(hist)):
        days_old = (reference - dates[i].to_pydatetime().replace(tzinfo=None)).days
        decay = math.exp(-days_old * math.log(2) / 180)
        weighted_vol = volumes[i] * decay

        day_low, day_high = lows[i], highs[i]
        day_range = day_high - day_low if day_high > day_low else 0.01
        for b in range(n_bins):
            bin_lo, bin_hi = bin_edges[b], bin_edges[b + 1]
            if day_low <= bin_hi and day_high >= bin_lo:
                overlap = min(day_high, bin_hi) - max(day_low, bin_lo)
                vol_by_bin[b] += weighted_vol * (overlap / day_range)

    threshold = np.percentile(vol_by_bin, 70)
    floors = []
    for b in range(n_bins):
        if vol_by_bin[b] >= threshold:
            floors.append({"price": round(bin_edges[b], 4), "volume": vol_by_bin[b], "source": "HVN"})

    return floors


def find_price_action_supports(hist, current_price):
    """Find support levels from clustered daily lows (3+ touches within 2%)."""
    all_lows = np.sort(hist["Low"].values)
    # Only consider lows below current price
    all_lows = all_lows[all_lows < current_price]
    if len(all_lows) == 0:
        return []

    clusters = []
    current_cluster = [all_lows[0]]

    for i in range(1, len(all_lows)):
        cluster_med = np.median(current_cluster)
        if cluster_med > 0 and (all_lows[i] - cluster_med) / cluster_med < 0.02:
            current_cluster.append(all_lows[i])
        else:
            if len(current_cluster) >= 3:
                clusters.append({
                    "price": round(float(min(current_cluster)), 4),
                    "touches": len(current_cluster),
                    "source": "PA",
                })
            current_cluster = [all_lows[i]]

    if len(current_cluster) >= 3:
        clusters.append({
            "price": round(float(min(current_cluster)), 4),
            "touches": len(current_cluster),
            "source": "PA",
        })

    return clusters


def merge_levels(hvn_floors, pa_supports, current_price):
    """Merge HVN and price-action levels, dedup within 2%, keep below current price."""
    all_levels = []

    for h in hvn_floors:
        if h["price"] < current_price:
            all_levels.append(h)

    for p in pa_supports:
        if p["price"] < current_price:
            # Check if already covered by an HVN level within 2%
            duplicate = False
            for existing in all_levels:
                if existing["price"] > 0 and abs(p["price"] - existing["price"]) / existing["price"] < 0.02:
                    # Merge: mark as both sources
                    if "PA" not in existing["source"]:
                        existing["source"] += "+PA"
                    existing["touches"] = p.get("touches", 0)
                    duplicate = True
                    break
            if not duplicate:
                all_levels.append(p)

    # Sort by price descending (highest support first)
    all_levels.sort(key=lambda x: x["price"], reverse=True)
    return all_levels


def find_approach_events(hist, level, proximity_pct=8.0):
    """Find distinct approach events to a support level.

    An approach starts when the daily low enters the proximity zone
    (within proximity_pct above the level) and ends when it moves away.
    Returns one event per approach with the minimum wick low observed.
    """
    events = []
    in_approach = False
    approach_min_low = None
    approach_start = None
    gap_days = 0
    max_gap = 3  # days away before we consider the approach over

    closes = hist["Close"].values
    lows = hist["Low"].values
    highs = hist["High"].values
    dates = hist.index

    LOOKBACK = 20  # trading days for prior-high computation
    approach_prior_high = None

    for i in range(len(hist)):
        close = closes[i]
        low = lows[i]

        # Skip if close is at or below the level (level broken)
        if close <= level:
            if in_approach:
                events.append({
                    "start": approach_start,
                    "min_low": approach_min_low,
                    "offset_pct": ((approach_min_low - level) / level) * 100,
                    "held": approach_min_low >= level,
                    "prior_high": approach_prior_high,
                })
                in_approach = False
            continue

        dist_pct = ((low - level) / level) * 100

        if 0 <= dist_pct < proximity_pct:
            # Low is in the proximity zone (above level, within range)
            if not in_approach:
                in_approach = True
                approach_start = dates[i].strftime("%Y-%m-%d")
                approach_min_low = low
                lb = max(0, i - LOOKBACK)
                approach_prior_high = float(highs[lb:i].max()) if i > 0 else float(highs[0])
            else:
                approach_min_low = min(approach_min_low, low)
            gap_days = 0
        elif dist_pct < 0:
            # Low pierced through the level
            if not in_approach:
                in_approach = True
                approach_start = dates[i].strftime("%Y-%m-%d")
                approach_min_low = low
                lb = max(0, i - LOOKBACK)
                approach_prior_high = float(highs[lb:i].max()) if i > 0 else float(highs[0])
            else:
                approach_min_low = min(approach_min_low, low)
            gap_days = 0
        else:
            # Low is far above level
            if in_approach:
                gap_days += 1
                if gap_days >= max_gap:
                    events.append({
                        "start": approach_start,
                        "min_low": approach_min_low,
                        "offset_pct": ((approach_min_low - level) / level) * 100,
                        "held": approach_min_low >= level,
                        "prior_high": approach_prior_high,
                    })
                    in_approach = False
                    gap_days = 0

    # Close any open approach
    if in_approach:
        events.append({
            "start": approach_start,
            "min_low": approach_min_low,
            "offset_pct": ((approach_min_low - level) / level) * 100,
            "held": approach_min_low >= level,
            "prior_high": approach_prior_high,
        })

    return events


def fmt_dollar(val):
    if val is None:
        return "N/A"
    return f"${val:.2f}"


def fmt_pct(val):
    if val is None:
        return "N/A"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.2f}%"


def _compute_bullet_plan(level_results, current_price, cap=None):
    """Build structured bullet plan from level results.

    INPUT: level_results in INTERNAL format (r["level"]["price"], r["recommended_buy"]).
    OUTPUT: dict with FLATTENED keys (bullet["support_price"], bullet["buy_at"]).
    Called ONCE inside analyze_stock_data() before JSON serialization.
    Result is cached in JSON as data["bullet_plan"].
    surgical_filter.py reads the cached plan — never calls this function.
    Always returns {"active": [...], "reserve": [...], ...} — empty lists, never None.
    """
    if cap is None:
        cap = load_capital_config()
    active_candidates = [r for r in level_results
                         if r["zone"] == "Active" and r["effective_tier"] != "Skip"
                         and r["recommended_buy"] and r["recommended_buy"] < current_price]
    # Sort: fresh first, then by proximity (highest price = closest)
    active_candidates.sort(key=lambda r: (r.get("dormant", False), -r["recommended_buy"]))
    active_bullets = active_candidates[:cap["active_bullets_max"]]

    reserve_candidates = [r for r in level_results
                          if r["zone"] == "Reserve" and r["effective_tier"] in ("Full", "Std")
                          and r["recommended_buy"] and r["recommended_buy"] < current_price]
    reserve_candidates.sort(key=lambda r: -r["hold_rate"])
    reserve_bullets = reserve_candidates[:cap["reserve_bullets_max"]]
    reserve_bullets.sort(key=lambda r: -r["recommended_buy"])

    # Prepare level dicts for compute_pool_sizing()
    def _sizing_input(r):
        return {
            "recommended_buy": r["recommended_buy"],
            "effective_tier": r["effective_tier"],
            "tier": r.get("tier", r["effective_tier"]),
            "hold_rate": r["hold_rate"],
            "monthly_touch_freq": r.get("monthly_touch_freq", 0),
        }

    # Concentrated sizing: fresh levels get full pool, dormant get 1-share minimum
    def _concentrated_sizing(bullets, pool_budget, pool_name):
        """Split fresh vs dormant for concentrated pool sizing."""
        fresh = [(i, r) for i, r in enumerate(bullets) if not r.get("dormant", False)]
        dormant = [(i, r) for i, r in enumerate(bullets) if r.get("dormant", False)]

        fresh_input = [_sizing_input(r) for _, r in fresh]
        dormant_cost = sum(r["recommended_buy"] for _, r in dormant)  # 1 share each
        fresh_budget = max(pool_budget - dormant_cost, 0)

        fresh_sized = compute_pool_sizing(fresh_input, fresh_budget, pool_name) if fresh_input else []
        dormant_sized = [{"shares": 1, "cost": r["recommended_buy"],
                          "dollar_alloc": r["recommended_buy"]}
                         for _, r in dormant]

        # Reassemble in original order
        result = [None] * len(bullets)
        for (orig_i, _), sized in zip(fresh, fresh_sized):
            result[orig_i] = sized
        for (orig_i, _), sized in zip(dormant, dormant_sized):
            result[orig_i] = sized
        return result

    active_sized = _concentrated_sizing(active_bullets, cap["active_pool"], "active")
    reserve_sized = _concentrated_sizing(reserve_bullets, cap["reserve_pool"], "reserve")

    def _bullet_entry(r, sized, zone_label):
        return {
            "zone": zone_label,
            "support_price": round(float(r["level"]["price"]), 2),
            "buy_at": round(float(r["recommended_buy"]), 2),
            "hold_rate": round(float(r["hold_rate"]), 1),
            "decayed_hold_rate": round(float(r["decayed_hold_rate"]), 1),
            "tier": r["effective_tier"],
            "raw_tier": r["tier"],
            "tier_promoted": r.get("tier_promoted", False),
            "approaches": int(r["total_approaches"]),
            "shares": int(sized["shares"]),
            "cost": round(sized["cost"], 2),
            "dormant": r.get("dormant", False),
            "zone_promoted": r.get("zone_promoted", False),
            "monthly_touch_freq": round(float(r.get("monthly_touch_freq", 0)), 1),
        }

    active = [_bullet_entry(r, s, "Active") for r, s in zip(active_bullets, active_sized)]
    reserve = [_bullet_entry(r, s, "Reserve") for r, s in zip(reserve_bullets, reserve_sized)]

    return {
        "active": active,
        "reserve": reserve,
        "active_total_cost": round(sum(b["cost"] for b in active), 2),
        "reserve_total_cost": round(sum(b["cost"] for b in reserve), 2),
        "active_bullet_count": len(active),
        "reserve_bullet_count": len(reserve),
    }


def analyze_stock_data(ticker, hist=None):
    """Full per-stock, per-level analysis. Returns (data_dict, error_str) tuple.

    Returns (dict, None) on success, (None, "reason") on failure.
    NEVER prints — pure data function for batch callers.
    If hist is provided, skips internal fetch_history() call (saves one yfinance round-trip).
    """
    if hist is None:
        try:
            hist = fetch_history(ticker, months=13)
        except Exception as e:
            return None, f"*Error fetching data for {ticker}: {e}*"
    if hist.empty or len(hist) < 60:
        return None, f"*Skipping {ticker} — insufficient data (need 60+ trading days)*"

    current_price = hist["Close"].iloc[-1]
    last_date = hist.index[-1].strftime("%Y-%m-%d")

    # Find support levels
    hvn_floors = find_hvn_floors(hist)
    pa_supports = find_price_action_supports(hist, current_price)
    levels = merge_levels(hvn_floors, pa_supports, current_price)

    if not levels:
        return None, f"*No support levels found below current price for {ticker}*"

    # Recency constants — compute ONCE before loops
    reference_date = hist.index[-1].to_pydatetime().replace(tzinfo=None)
    cutoff_90d = (reference_date - datetime.timedelta(days=90)).strftime("%Y-%m-%d")
    LN2 = math.log(2)
    HALF_LIFE = 90

    # Analyze approaches at each level
    level_results = []
    for lvl in levels:
        events = find_approach_events(hist, lvl["price"])
        if not events:
            continue

        held_events = [e for e in events if e["held"]]
        held_offsets = [e["offset_pct"] for e in held_events]

        if held_offsets:
            median_offset = float(np.median(held_offsets))
            recommended_buy = lvl["price"] * (1 + median_offset / 100)
        else:
            median_offset = None
            recommended_buy = None

        # Time-decayed hold rate (90-day half-life)
        weights = []
        for e in events:
            days_old = (reference_date - datetime.datetime.strptime(e["start"], "%Y-%m-%d")).days
            weights.append(math.exp(-days_old * LN2 / HALF_LIFE))
        total_weight = sum(weights)
        weighted_held = sum(w * (1 if e["held"] else 0) for w, e in zip(weights, events))
        decayed_hold_rate = (weighted_held / total_weight * 100) if total_weight > 0 else 0

        level_results.append({
            "level": lvl,
            "events": events,
            "total_approaches": len(events),
            "held": len(held_events),
            "hold_rate": len(held_events) / len(events) * 100 if events else 0,
            "median_offset": median_offset,
            "recommended_buy": recommended_buy,
            "decayed_hold_rate": decayed_hold_rate,
        })

    # Compute monthly swing, consistency, and active radius
    monthly_swing = compute_monthly_swing(hist)
    swing_consistency = compute_swing_consistency(hist, threshold=10.0)
    # Recency-weighted active radius: use last 4 months' swing, floor at 1/3 of 13-month median
    swings = _monthly_swings(hist)
    if swings is not None and len(swings) >= 4:
        recent_swing = float(np.median(swings[-4:]))
        active_radius = max(recent_swing / 2, monthly_swing / 3)
    else:
        recent_swing = None
        active_radius = monthly_swing / 2 if monthly_swing else 15.0
    active_radius = min(active_radius, ACTIVE_RADIUS_CAP)

    # Daily range metrics
    daily_ranges = ((hist["High"] - hist["Low"]) / hist["Low"] * 100).values
    median_daily_range = float(np.median(daily_ranges[-21:])) if len(daily_ranges) >= 21 else (float(np.median(daily_ranges)) if len(daily_ranges) > 0 else None)
    days_above_3pct = round(sum(1 for d in daily_ranges[-63:] if d >= 3.0) / min(63, len(daily_ranges)) * 100, 1) if len(daily_ranges) > 0 else None

    # Add zone/tier classification and recency metrics to each level result
    for r in level_results:
        lvl_price = r["level"]["price"]
        gap_pct = ((current_price - lvl_price) / current_price) * 100
        zone, tier = classify_level(r["hold_rate"], gap_pct, active_radius, r["total_approaches"])
        r["zone"] = zone
        r["tier"] = tier
        r["gap_pct"] = gap_pct

        # Decayed tier is the effective tier — recent behavior determines sizing
        # Promotion floor: never promote more than one tier above raw
        _, decayed_tier = classify_level(r["decayed_hold_rate"], gap_pct, active_radius, r["total_approaches"])
        effective_tier, promoted = compute_effective_tier(tier, decayed_tier)
        r["decayed_tier"] = decayed_tier
        r["effective_tier"] = effective_tier
        r["tier_override"] = (effective_tier != tier)
        r["tier_promoted"] = promoted

        # Level freshness & approach velocity
        last_tested = max(e["start"] for e in r["events"])
        recent_approaches = sum(1 for e in r["events"] if e["start"] >= cutoff_90d)
        approach_velocity = recent_approaches / len(r["events"])
        dormant = last_tested < cutoff_90d

        # Hold rate trend
        recent_events_list = [e for e in r["events"] if e["start"] >= cutoff_90d]
        if recent_events_list:
            recent_held_count = sum(1 for e in recent_events_list if e["held"])
            recent_hold_pct = recent_held_count / len(recent_events_list) * 100
        else:
            recent_held_count = 0
            recent_hold_pct = None

        hold_rate = r["hold_rate"]
        if recent_hold_pct is None:
            trend = "—"
        elif recent_hold_pct > hold_rate + 5:
            trend = "Improving"
        elif recent_hold_pct < hold_rate - 5:
            trend = "Deteriorating"
        else:
            trend = "Stable"

        r["last_tested"] = last_tested
        r["recent_approaches"] = recent_approaches
        r["approach_velocity"] = approach_velocity
        r["dormant"] = dormant
        r["recent_hold_pct"] = recent_hold_pct
        r["recent_held"] = recent_held_count
        r["trend"] = trend
        r["monthly_touch_freq"] = round(recent_approaches / 3.0, 1)

        # Zone promotion: fresh Buffer levels → Active (recency + pullback validated)
        # Skip promotion if the level was forced into Buffer by the radius cap —
        # it would have been Active under the uncapped radius, so promotion defeats the cap.
        capped = active_radius >= ACTIVE_RADIUS_CAP and gap_pct > active_radius
        if r["zone"] == "Buffer" and not dormant and not capped:
            # Require at least one recent approach to be a genuine pullback
            recent_pullback = False
            for e in r["events"]:
                if e["start"] >= cutoff_90d:
                    rally_pct = ((e["prior_high"] - lvl_price) / lvl_price) * 100
                    if rally_pct >= active_radius:
                        recent_pullback = True
                        break

            if recent_pullback:
                r["zone"] = "Active"       # Mutate — all downstream sees "Active"
                r["zone_promoted"] = True   # Display flag for [P] marker
                r["zone_baseline"] = False
            else:
                r["zone_promoted"] = False
                r["zone_baseline"] = True   # Fresh but NOT a pullback
        else:
            r["zone_promoted"] = False
            r["zone_baseline"] = False

    # Build structured output — all values must be Python-native types
    data = {
        "current_price": float(current_price),
        "last_date": last_date,
        "monthly_swing": round(float(monthly_swing), 1) if monthly_swing is not None else None,
        "swing_consistency": round(float(swing_consistency), 1) if swing_consistency is not None else None,
        "active_radius": round(float(active_radius), 1),
        "recent_swing": round(float(recent_swing), 1) if recent_swing is not None else None,
        "recent_active_radius": round(float(active_radius), 1),
        "median_daily_range": round(float(median_daily_range), 1) if median_daily_range is not None else None,
        "days_above_3pct": days_above_3pct,
        "levels": [
            {
                "support_price": round(float(r["level"]["price"]), 4),
                "source": r["level"]["source"],
                "total_approaches": int(r["total_approaches"]),
                "held": int(r["held"]),
                "hold_rate": round(float(r["hold_rate"]), 1),
                "median_offset": round(float(r["median_offset"]), 2) if r["median_offset"] is not None else None,
                "recommended_buy": round(float(r["recommended_buy"]), 2) if r["recommended_buy"] is not None else None,
                "zone": r["zone"],
                "tier": r["tier"],
                "gap_pct": round(float(r["gap_pct"]), 1),
                "decayed_hold_rate": round(float(r["decayed_hold_rate"]), 1),
                "decayed_tier": r.get("decayed_tier"),
                "effective_tier": r.get("effective_tier", r["tier"]),
                "tier_override": r.get("tier_override", False),
                "tier_promoted": r.get("tier_promoted", False),
                "last_tested": r.get("last_tested"),
                "recent_approaches": r.get("recent_approaches", 0),
                "approach_velocity": round(float(r.get("approach_velocity", 0)), 2),
                "dormant": r.get("dormant", False),
                "zone_promoted": r.get("zone_promoted", False),
                "zone_baseline": r.get("zone_baseline", False),
                "recent_hold_pct": round(float(r["recent_hold_pct"]), 1) if r.get("recent_hold_pct") is not None else None,
                "recent_held": r.get("recent_held", 0),
                "monthly_touch_freq": round(float(r.get("monthly_touch_freq", 0)), 1),
                "trend": r.get("trend", "—"),
                "events": [
                    {
                        "date": e["start"],
                        "min_low": round(float(e["min_low"]), 2),
                        "offset_pct": round(float(e["offset_pct"]), 2),
                        "held": bool(e["held"]),
                        "prior_high": round(float(e["prior_high"]), 2),
                    }
                    for e in r["events"]
                ],
            }
            for r in level_results
        ],
        "bullet_plan": _compute_bullet_plan(level_results, current_price, load_capital_config()),
    }

    return data, None


def _format_stock_report(ticker, data):
    """Format structured data dict into the existing markdown report.

    Uses data["bullet_plan"] directly — does NOT recompute bullet selection.
    """
    lines = []

    # Header
    lines.append(f"*Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} | Data as of: {data['last_date']}*")
    lines.append("")
    lines.append(f"## Wick Offset Analysis: {ticker} (13-Month, as of {data['last_date']})")
    lines.append(f"**Current Price: {fmt_dollar(data['current_price'])}**")
    if data["monthly_swing"] is not None:
        consistency_str = f" | {data['swing_consistency']:.0f}% of months hit 10%+" if data["swing_consistency"] is not None else ""
        lines.append(f"**Monthly Swing: {data['monthly_swing']:.1f}%**{consistency_str} | Active Zone: within {data['active_radius']:.1f}% of current price")
    else:
        lines.append(f"**Monthly Swing: N/A** (< 3 months data) | Active Zone: using {data['active_radius']:.1f}% fallback radius")
    lines.append("")

    # Summary table
    lines.append("### Support Levels & Buy Recommendations")
    lines.append("| Support | Source | Approaches | Held | Freq/mo | Hold Rate | Median Offset | Buy At | Zone | Tier | Decayed | Trend | Fresh |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for lvl in data["levels"]:
        if lvl["recommended_buy"] is not None and lvl["recommended_buy"] >= data["current_price"]:
            buy_str = f"{fmt_dollar(lvl['recommended_buy'])} ↑above"
        elif lvl["recommended_buy"] is not None:
            buy_str = fmt_dollar(lvl["recommended_buy"])
        else:
            buy_str = "N/A (no holds)"
        offset_str = fmt_pct(lvl["median_offset"]) if lvl["median_offset"] is not None else "N/A"
        # New columns
        decayed_hr = lvl.get("decayed_hold_rate")
        eff_tier = lvl.get("effective_tier", lvl["tier"])
        override = lvl.get("tier_override", False)
        promoted = lvl.get("tier_promoted", False)
        if decayed_hr is not None and override:
            arrow = "^" if promoted else "v"
            decayed_str = f"{decayed_hr:.0f}% ({eff_tier}{arrow})"
        elif decayed_hr is not None:
            decayed_str = f"{decayed_hr:.0f}%"
        else:
            decayed_str = "N/A"
        trend_raw = lvl.get("trend", "—")
        trend_map = {"Improving": "^", "Deteriorating": "v", "Stable": "-", "—": "?"}
        trend_str = trend_map.get(trend_raw, "?")
        last_tested = lvl.get("last_tested", "N/A")
        dormant = lvl.get("dormant", False)
        zone_promoted = lvl.get("zone_promoted", False)
        if zone_promoted:
            fresh_str = f"{last_tested} [P]"
        elif dormant:
            fresh_str = f"{last_tested} [D]"
        elif lvl.get("zone_baseline", False):
            fresh_str = f"{last_tested} [B]"
        else:
            fresh_str = last_tested
        lines.append(
            f"| {fmt_dollar(lvl['support_price'])} | {lvl['source']} "
            f"| {lvl['total_approaches']} | {lvl['held']} "
            f"| {lvl.get('monthly_touch_freq', 0):.1f} | {lvl['hold_rate']:.0f}% | {offset_str} "
            f"| {buy_str} | {lvl['zone']} | {eff_tier} "
            f"| {decayed_str} | {trend_str} | {fresh_str} |"
        )
    lines.append("")

    # Per-level approach detail
    for lvl in data["levels"]:
        if not lvl["events"]:
            continue
        lines.append(f"### Detail: {fmt_dollar(lvl['support_price'])} ({lvl['source']})")
        lines.append("| Date | Wick Low | Offset | Prior High | Held |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for e in lvl["events"]:
            held_str = "Yes" if e["held"] else "**BROKE**"
            prior_high_str = fmt_dollar(e.get("prior_high"))
            lines.append(f"| {e['date']} | {fmt_dollar(e['min_low'])} | {fmt_pct(e['offset_pct'])} | {prior_high_str} | {held_str} |")
        lines.append("")

    # Bullet plan from pre-computed data
    bp = data["bullet_plan"]
    lines.append("### Suggested Bullet Plan")
    if data["monthly_swing"] is not None:
        lines.append(f"*Based on {data['monthly_swing']:.1f}% monthly swing — Active zone within {data['active_radius']:.1f}% of current price.*")
    lines.append("")

    if bp["active"] or bp["reserve"]:
        lines.append("| # | Zone | Level | Buy At | Hold% | Tier | Shares | ~Cost |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        bullet_num = 1
        for b in bp["active"]:
            lines.append(
                f"| {bullet_num} | Active | {fmt_dollar(b['support_price'])} "
                f"| {fmt_dollar(b['buy_at'])} | {b['hold_rate']:.0f}% | {b['tier']} "
                f"| {b['shares']} | ${b['cost']:.2f} |"
            )
            bullet_num += 1
        for b in bp["reserve"]:
            lines.append(
                f"| {bullet_num} | Reserve | {fmt_dollar(b['support_price'])} "
                f"| {fmt_dollar(b['buy_at'])} | {b['hold_rate']:.0f}% | {b['tier']} "
                f"| {b['shares']} | ${b['cost']:.2f} |"
            )
            bullet_num += 1
        lines.append("")
        # Flag Active levels excluded by above-market guard
        above_market = [lvl for lvl in data["levels"]
                        if lvl["zone"] == "Active" and lvl.get("effective_tier", lvl["tier"]) != "Skip"
                        and lvl["recommended_buy"] is not None
                        and lvl["recommended_buy"] >= data["current_price"]]
        if above_market:
            excluded_str = ", ".join(fmt_dollar(lvl["support_price"]) for lvl in above_market)
            lines.append(f"*Note: {len(above_market)} Active level(s) excluded — buy price at or above current price: {excluded_str}*")
        lines.append("*Bullet plan is a suggestion — adjust based on cycle timing and position.*")
    else:
        lines.append("*No qualifying levels for bullet plan — all levels below 15% hold rate.*")
    lines.append("")

    return "\n".join(lines)


def analyze_stock(ticker):
    """Full per-stock, per-level analysis. Returns markdown report string.

    Preserves ALL CLI error messages from the original implementation
    by printing the error string returned by analyze_stock_data().
    """
    data, error = analyze_stock_data(ticker)
    if data is None:
        print(error)
        return None
    return _format_stock_report(ticker, data)


def main():
    if len(sys.argv) > 1:
        tickers = [t.upper() for t in sys.argv[1:]]
    else:
        tickers = load_tickers_from_portfolio()

    for i, ticker in enumerate(tickers):
        if i > 0:
            print()
            print("---")
            print()
        report = analyze_stock(ticker)
        if report:
            print(report)
            _write_cache(ticker, "wick_analysis.md", report)


if __name__ == "__main__":
    main()
