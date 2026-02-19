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
import numpy as np
import yfinance as yf
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"
AGENTS_DIR = _ROOT / "agents"


def _write_cache(ticker, filename, report):
    agent_dir = AGENTS_DIR / ticker
    agent_dir.mkdir(parents=True, exist_ok=True)
    with open(agent_dir / filename, "w") as f:
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
        "active_bullets_max": cap.get("active_bullets_max", 5),
        "reserve_bullets_max": cap.get("reserve_bullets_max", 3),
        "active_bullet_full": cap.get("active_bullet_full", 60),
        "active_bullet_half": cap.get("active_bullet_half", 30),
        "reserve_bullet_size": cap.get("reserve_bullet_size", 100),
    }


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
    """Classify a support level into Zone (Active/Reserve) and Tier (Full/Std/Half/Skip).

    Zone: Active if gap_pct <= active_radius, else Reserve.
    Tier (hold_rate is 0-100%): Full (50%+), Std (30-49%), Half (15-29%), Skip (<15%).
    Confidence gate: Full/Std require 3+ approaches; fewer approaches cap at Half.
    """
    zone = "Active" if gap_pct <= active_radius else "Reserve"
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


def find_hvn_floors(hist, n_bins=40):
    """Build volume profile, return HVN floor prices with their volume."""
    lows = hist["Low"].values
    highs = hist["High"].values
    volumes = hist["Volume"].values

    price_min, price_max = lows.min(), highs.max()
    bin_edges = np.linspace(price_min * 0.95, price_max * 1.05, n_bins + 1)

    vol_by_bin = np.zeros(n_bins)
    for i in range(len(hist)):
        day_low, day_high = lows[i], highs[i]
        day_range = day_high - day_low if day_high > day_low else 0.01
        for b in range(n_bins):
            bin_lo, bin_hi = bin_edges[b], bin_edges[b + 1]
            if day_low <= bin_hi and day_high >= bin_lo:
                overlap = min(day_high, bin_hi) - max(day_low, bin_lo)
                vol_by_bin[b] += volumes[i] * (overlap / day_range)

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
    dates = hist.index

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
            else:
                approach_min_low = min(approach_min_low, low)
            gap_days = 0
        elif dist_pct < 0:
            # Low pierced through the level
            if not in_approach:
                in_approach = True
                approach_start = dates[i].strftime("%Y-%m-%d")
                approach_min_low = low
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


def analyze_stock(ticker):
    """Full per-stock, per-level analysis. Returns report string.

    If monthly swing data is insufficient (< 3 complete months),
    active_radius defaults to 15% as a fallback.
    """
    lines = []
    try:
        hist = fetch_history(ticker, months=13)
    except Exception as e:
        print(f"*Error fetching data for {ticker}: {e}*")
        return None
    if hist.empty or len(hist) < 60:
        print(f"*Skipping {ticker} — insufficient data (need 60+ trading days)*")
        return None

    current_price = hist["Close"].iloc[-1]
    last_date = hist.index[-1].strftime("%Y-%m-%d")

    # Find support levels
    hvn_floors = find_hvn_floors(hist)
    pa_supports = find_price_action_supports(hist, current_price)
    levels = merge_levels(hvn_floors, pa_supports, current_price)

    if not levels:
        print(f"*No support levels found below current price for {ticker}*")
        return None

    # Analyze approaches at each level
    level_results = []
    for lvl in levels:
        events = find_approach_events(hist, lvl["price"])
        if not events:
            continue

        held_events = [e for e in events if e["held"]]
        held_offsets = [e["offset_pct"] for e in held_events]

        if held_offsets:
            median_offset = np.median(held_offsets)
            recommended_buy = lvl["price"] * (1 + median_offset / 100)
        else:
            median_offset = None
            recommended_buy = None

        level_results.append({
            "level": lvl,
            "events": events,
            "total_approaches": len(events),
            "held": len(held_events),
            "hold_rate": len(held_events) / len(events) * 100 if events else 0,
            "median_offset": median_offset,
            "recommended_buy": recommended_buy,
        })

    # Compute monthly swing, consistency, and active radius
    monthly_swing = compute_monthly_swing(hist)
    swing_consistency = compute_swing_consistency(hist, threshold=10.0)
    active_radius = monthly_swing / 2 if monthly_swing else 15.0  # fallback 15%

    # Add zone/tier classification to each level result
    for r in level_results:
        lvl_price = r["level"]["price"]
        # gap_pct measured from level (not current_price), matching monthly_swing denominator (low-based)
        gap_pct = ((current_price - lvl_price) / lvl_price) * 100
        zone, tier = classify_level(r["hold_rate"], gap_pct, active_radius, r["total_approaches"])
        r["zone"] = zone
        r["tier"] = tier
        r["gap_pct"] = gap_pct

    # Build report
    lines.append(f"*Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    lines.append("")
    lines.append(f"## Wick Offset Analysis: {ticker} (13-Month, as of {last_date})")
    lines.append(f"**Current Price: {fmt_dollar(current_price)}**")
    if monthly_swing is not None:
        consistency_str = f" | {swing_consistency:.0f}% of months hit 10%+" if swing_consistency is not None else ""
        lines.append(f"**Monthly Swing: {monthly_swing:.1f}%**{consistency_str} | Active Zone: within {active_radius:.1f}% of current price")
    else:
        lines.append(f"**Monthly Swing: N/A** (< 3 months data) | Active Zone: using {active_radius:.1f}% fallback radius")
    lines.append("")

    # Summary table
    lines.append("### Support Levels & Buy Recommendations")
    lines.append("| Support | Source | Approaches | Held | Hold Rate | Median Offset | Buy At | Zone | Tier |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for r in level_results:
        lvl = r["level"]
        if r["recommended_buy"] and r["recommended_buy"] >= current_price:
            buy_str = f"{fmt_dollar(r['recommended_buy'])} ↑above"
        elif r["recommended_buy"]:
            buy_str = fmt_dollar(r["recommended_buy"])
        else:
            buy_str = "N/A (no holds)"
        offset_str = fmt_pct(r["median_offset"]) if r["median_offset"] is not None else "N/A"
        lines.append(
            f"| {fmt_dollar(lvl['price'])} | {lvl['source']} "
            f"| {r['total_approaches']} | {r['held']} "
            f"| {r['hold_rate']:.0f}% | {offset_str} "
            f"| {buy_str} | {r['zone']} | {r['tier']} |"
        )
    lines.append("")

    # Per-level approach detail
    for r in level_results:
        lvl = r["level"]
        if not r["events"]:
            continue
        lines.append(f"### Detail: {fmt_dollar(lvl['price'])} ({lvl['source']})")
        lines.append("| Date | Wick Low | Offset | Held |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for e in r["events"]:
            held_str = "Yes" if e["held"] else "**BROKE**"
            lines.append(f"| {e['start']} | {fmt_dollar(e['min_low'])} | {fmt_pct(e['offset_pct'])} | {held_str} |")
        lines.append("")

    # Suggested bullet plan
    cap = load_capital_config()
    lines.append("### Suggested Bullet Plan")
    if monthly_swing is not None:
        lines.append(f"*Based on {monthly_swing:.1f}% monthly swing — Active zone within {active_radius:.1f}% of current price.*")
    lines.append("")

    # Active bullets: up to N from Active zone, tier != Skip (Half allowed — lighter position at speed bumps)
    active_candidates = [r for r in level_results if r["zone"] == "Active" and r["tier"] != "Skip" and r["recommended_buy"] and r["recommended_buy"] < current_price]
    active_candidates.sort(key=lambda r: r["recommended_buy"], reverse=True)
    active_bullets = active_candidates[:cap["active_bullets_max"]]

    # Reserve bullets: up to N from Reserve zone, Full or Std only (deep levels need proven reliability)
    reserve_candidates = [r for r in level_results if r["zone"] == "Reserve" and r["tier"] in ("Full", "Std") and r["recommended_buy"] and r["recommended_buy"] < current_price]
    reserve_candidates.sort(key=lambda r: -r["hold_rate"])
    reserve_bullets = reserve_candidates[:cap["reserve_bullets_max"]]
    # Re-sort selected reserves by price descending for intuitive cascade display
    reserve_bullets.sort(key=lambda r: -r["recommended_buy"])

    if active_bullets or reserve_bullets:
        lines.append("| # | Zone | Level | Buy At | Hold% | Tier | Shares | ~Cost |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        bullet_num = 1
        for r in active_bullets:
            buy_price = r["recommended_buy"]
            size = cap["active_bullet_half"] if r["tier"] == "Half" else cap["active_bullet_full"]
            shares = max(1, int(size / buy_price))
            cost = round(shares * buy_price, 2)
            lines.append(
                f"| {bullet_num} | Active | {fmt_dollar(r['level']['price'])} "
                f"| {fmt_dollar(buy_price)} | {r['hold_rate']:.0f}% | {r['tier']} "
                f"| {shares} | ${cost:.2f} |"
            )
            bullet_num += 1
        for r in reserve_bullets:
            buy_price = r["recommended_buy"]
            size = cap["reserve_bullet_size"]
            shares = max(1, int(size / buy_price))
            cost = round(shares * buy_price, 2)
            lines.append(
                f"| {bullet_num} | Reserve | {fmt_dollar(r['level']['price'])} "
                f"| {fmt_dollar(buy_price)} | {r['hold_rate']:.0f}% | {r['tier']} "
                f"| {shares} | ${cost:.2f} |"
            )
            bullet_num += 1
        lines.append("")
        # Flag Active levels excluded by above-market guard
        above_market = [r for r in level_results if r["zone"] == "Active" and r["tier"] != "Skip" and r["recommended_buy"] and r["recommended_buy"] >= current_price]
        if above_market:
            excluded_str = ", ".join(fmt_dollar(r["level"]["price"]) for r in above_market)
            lines.append(f"*Note: {len(above_market)} Active level(s) excluded — buy price at or above current price: {excluded_str}*")
        lines.append("*Bullet plan is a suggestion — adjust based on cycle timing and position.*")
    else:
        lines.append("*No qualifying levels for bullet plan — all levels below 15% hold rate.*")
    lines.append("")

    return "\n".join(lines)


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
