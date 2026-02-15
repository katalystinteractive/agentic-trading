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


def load_tickers_from_portfolio():
    with open(PORTFOLIO_PATH, "r") as f:
        portfolio = json.load(f)
    tickers = set()
    tickers.update(portfolio.get("positions", {}).keys())
    tickers.update(portfolio.get("pending_orders", {}).keys())
    tickers.update(portfolio.get("watchlist", []))
    return sorted(tickers)


def fetch_history(ticker, months=13):
    """Fetch ~13 months of daily OHLCV data."""
    t = yf.Ticker(ticker)
    start = (datetime.datetime.now() - datetime.timedelta(days=months * 31)).strftime("%Y-%m-%d")
    hist = t.history(start=start)
    return hist


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
                    "source": "Price Action",
                })
            current_cluster = [all_lows[i]]

    if len(current_cluster) >= 3:
        clusters.append({
            "price": round(float(min(current_cluster)), 4),
            "touches": len(current_cluster),
            "source": "Price Action",
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
                    if "Price Action" not in existing["source"]:
                        existing["source"] += " + Price Action"
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
    """Full per-stock, per-level analysis. Returns report string."""
    lines = []
    try:
        hist = fetch_history(ticker, months=13)
    except Exception as e:
        return f"*Error fetching data for {ticker}: {e}*"
    if hist.empty or len(hist) < 60:
        return f"*Skipping {ticker} — insufficient data (need 60+ trading days)*"

    current_price = hist["Close"].iloc[-1]
    last_date = hist.index[-1].strftime("%Y-%m-%d")

    # Find support levels
    hvn_floors = find_hvn_floors(hist)
    pa_supports = find_price_action_supports(hist, current_price)
    levels = merge_levels(hvn_floors, pa_supports, current_price)

    if not levels:
        return f"*No support levels found below current price for {ticker}*"

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

    # Build report
    lines.append(f"*Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    lines.append("")
    lines.append(f"## Wick Offset Analysis: {ticker} (13-Month, as of {last_date})")
    lines.append(f"**Current Price: {fmt_dollar(current_price)}**")
    lines.append("")

    # Summary table
    lines.append("### Support Levels & Buy Recommendations")
    lines.append("| Support | Source | Approaches | Held | Hold Rate | Median Offset | Buy At |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for r in level_results:
        lvl = r["level"]
        buy_str = fmt_dollar(r["recommended_buy"]) if r["recommended_buy"] else "N/A (no holds)"
        offset_str = fmt_pct(r["median_offset"]) if r["median_offset"] is not None else "N/A"
        lines.append(
            f"| {fmt_dollar(lvl['price'])} | {lvl['source']} "
            f"| {r['total_approaches']} | {r['held']} "
            f"| {r['hold_rate']:.0f}% | {offset_str} "
            f"| {buy_str} |"
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
