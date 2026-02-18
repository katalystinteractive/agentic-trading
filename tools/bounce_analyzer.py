"""Bounce Analyzer — per-level support bounce statistics from hourly data.

Identifies support levels (volume profile HVN floors + price-action clusters),
then measures actual bounce magnitudes using hourly timestamps. Outputs
actionable trade setups for levels with proven bounce history.

Usage:
    python3 tools/bounce_analyzer.py APLD        # single stock
    python3 tools/bounce_analyzer.py APLD NU AR  # multiple stocks
"""
import sys
import json
import datetime
import numpy as np
import pandas as pd
import yfinance as yf
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"
AGENTS_DIR = _ROOT / "agents"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt_dollar(val):
    if val is None:
        return "N/A"
    return f"${val:.2f}"


def fmt_pct(val):
    if val is None:
        return "N/A"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.1f}%"


def _write_cache(ticker, filename, content):
    agent_dir = AGENTS_DIR / ticker
    agent_dir.mkdir(parents=True, exist_ok=True)
    with open(agent_dir / filename, "w") as f:
        f.write(content + "\n")


# ---------------------------------------------------------------------------
# Support-level detection (copied from wick_offset_analyzer.py — tools stay
# independent; no cross-imports)
# ---------------------------------------------------------------------------

def find_hvn_floors(hist, n_bins=40):
    """Build volume profile, return HVN floor prices."""
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
            duplicate = False
            for existing in all_levels:
                if existing["price"] > 0 and abs(p["price"] - existing["price"]) / existing["price"] < 0.02:
                    if "PA" not in existing["source"]:
                        existing["source"] += "+PA"
                    existing["touches"] = p.get("touches", 0)
                    duplicate = True
                    break
            if not duplicate:
                all_levels.append(p)

    all_levels.sort(key=lambda x: x["price"], reverse=True)
    return all_levels


# ---------------------------------------------------------------------------
# Approach detection (adapted from wick_offset_analyzer.py)
# ---------------------------------------------------------------------------

def find_approach_events(daily_df, level, proximity_pct=8.0):
    """Find distinct approach events to a support level on daily data.

    Returns one event per approach with the minimum wick low and the date
    of that minimum (used to locate the exact hourly timestamp).
    """
    events = []
    in_approach = False
    approach_min_low = None
    approach_min_date = None
    approach_start = None
    gap_days = 0
    max_gap = 3

    closes = daily_df["Close"].values
    lows = daily_df["Low"].values
    dates = daily_df.index

    for i in range(len(daily_df)):
        close = closes[i]
        low = lows[i]

        if close <= level:
            if in_approach:
                events.append({
                    "start": approach_start,
                    "min_low": approach_min_low,
                    "min_date": approach_min_date,
                    "offset_pct": ((approach_min_low - level) / level) * 100,
                    "held": approach_min_low >= level,
                })
                in_approach = False
            continue

        dist_pct = ((low - level) / level) * 100

        if dist_pct < proximity_pct:
            if not in_approach:
                in_approach = True
                approach_start = dates[i].strftime("%Y-%m-%d")
                approach_min_low = low
                approach_min_date = dates[i].strftime("%Y-%m-%d")
            else:
                if low < approach_min_low:
                    approach_min_low = low
                    approach_min_date = dates[i].strftime("%Y-%m-%d")
            gap_days = 0
        else:
            if in_approach:
                gap_days += 1
                if gap_days >= max_gap:
                    events.append({
                        "start": approach_start,
                        "min_low": approach_min_low,
                        "min_date": approach_min_date,
                        "offset_pct": ((approach_min_low - level) / level) * 100,
                        "held": approach_min_low >= level,
                    })
                    in_approach = False
                    gap_days = 0

    if in_approach:
        events.append({
            "start": approach_start,
            "min_low": approach_min_low,
            "min_date": approach_min_date,
            "offset_pct": ((approach_min_low - level) / level) * 100,
            "held": approach_min_low >= level,
        })

    return events


# ---------------------------------------------------------------------------
# Bounce measurement (hourly timestamps)
# ---------------------------------------------------------------------------

def find_hourly_min_timestamp(hourly_df, min_date_str, min_low):
    """Find the exact hourly timestamp of the minimum low on a given date."""
    tz = hourly_df.index.tz
    target_date = pd.Timestamp(min_date_str, tz=tz).normalize()
    day_bars = hourly_df[hourly_df.index.normalize() == target_date]
    if day_bars.empty:
        return None
    # Find the bar closest to the min_low
    idx = day_bars["Low"].sub(min_low).abs().idxmin()
    return idx


def measure_bounce(hourly_df, min_low_timestamp, min_low, n_days=(1, 2, 3)):
    """Measure bounce magnitude in 1/2/3 trading days after the hourly low."""
    after_low = hourly_df[hourly_df.index > min_low_timestamp]
    if after_low.empty:
        return {n: None for n in n_days}

    results = {}
    trading_dates = after_low.index.normalize().unique()

    for n in n_days:
        window_dates = trading_dates[:n]
        window = after_low[after_low.index.normalize().isin(window_dates)]
        if not window.empty:
            max_high = float(window["High"].max())
            bounce_pct = ((max_high - min_low) / min_low) * 100
            results[n] = {"max_high": max_high, "bounce_pct": bounce_pct}
        else:
            results[n] = None

    return results


# ---------------------------------------------------------------------------
# Per-level statistics
# ---------------------------------------------------------------------------

def compute_level_stats(events_with_bounces):
    """Compute aggregate bounce statistics for a single support level."""
    held = [e for e in events_with_bounces if e["held"]]
    total = len(events_with_bounces)

    if total == 0:
        return None

    hold_rate = len(held) / total

    # Collect bounce percentages for held events
    bounce_1d = [e["bounce"].get(1, {}).get("bounce_pct") for e in held if e.get("bounce") and e["bounce"].get(1)]
    bounce_2d = [e["bounce"].get(2, {}).get("bounce_pct") for e in held if e.get("bounce") and e["bounce"].get(2)]
    bounce_3d = [e["bounce"].get(3, {}).get("bounce_pct") for e in held if e.get("bounce") and e["bounce"].get(3)]

    def safe_median(lst):
        return float(np.median(lst)) if lst else None

    def safe_min(lst):
        return float(np.min(lst)) if lst else None

    def safe_max(lst):
        return float(np.max(lst)) if lst else None

    # % of holds producing >= 4.5% within 3 days
    above_4_5 = [b for b in bounce_3d if b >= 4.5]
    pct_above_4_5 = len(above_4_5) / len(bounce_3d) if bounce_3d else 0.0

    return {
        "total_approaches": total,
        "holds": len(held),
        "hold_rate": hold_rate,
        "bounce_1d_median": safe_median(bounce_1d),
        "bounce_2d_median": safe_median(bounce_2d),
        "bounce_3d_median": safe_median(bounce_3d),
        "bounce_1d_min": safe_min(bounce_1d),
        "bounce_1d_max": safe_max(bounce_1d),
        "bounce_3d_min": safe_min(bounce_3d),
        "bounce_3d_max": safe_max(bounce_3d),
        "pct_above_4_5": pct_above_4_5,
    }


def compute_verdict(stats):
    """Determine verdict from stats."""
    if stats is None or stats["total_approaches"] < 3:
        return "NO DATA"
    if stats["hold_rate"] >= 0.50 and stats["pct_above_4_5"] >= 0.60:
        return "STRONG BOUNCE"
    if stats["hold_rate"] >= 0.40 and stats["pct_above_4_5"] >= 0.40:
        return "BOUNCE"
    return "WEAK"


def _compute_buy_at(level_price, events):
    """Compute wick-adjusted buy price from held approach offsets."""
    held_offsets = [e["offset_pct"] for e in events if e["held"]]
    if not held_offsets:
        return level_price
    median_offset = float(np.median(held_offsets))
    return round(level_price * (1 + median_offset / 100), 2)


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------

def analyze_stock(ticker):
    """Full bounce analysis for a single ticker. Returns (report_str, json_data)."""
    # Fetch hourly data (~2 years)
    try:
        hourly = yf.download(ticker, period="730d", interval="1h", progress=False)
        if isinstance(hourly.columns, pd.MultiIndex):
            hourly.columns = hourly.columns.get_level_values(0)
    except Exception as e:
        print(f"*Error fetching hourly data for {ticker}: {e}*")
        return None, None

    if hourly.empty or len(hourly) < 100:
        print(f"*Skipping {ticker} — insufficient hourly data*")
        return None, None

    # Resample to daily for support-level detection
    daily = hourly.resample("D").agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }).dropna()

    if len(daily) < 60:
        print(f"*Skipping {ticker} — insufficient daily data after resample ({len(daily)} days)*")
        return None, None

    current_price = float(daily["Close"].iloc[-1])
    last_date = daily.index[-1].strftime("%Y-%m-%d")

    # Load portfolio config
    try:
        portfolio = json.loads(PORTFOLIO_PATH.read_text())
    except Exception:
        portfolio = {}
    bounce_cap = portfolio.get("bounce_capital", {})
    per_trade_size = bounce_cap.get("per_trade_size", 100)
    stop_loss_pct = bounce_cap.get("stop_loss_pct", 3.0)

    # Detect support levels
    hvn_floors = find_hvn_floors(daily)
    pa_supports = find_price_action_supports(daily, current_price)
    levels = merge_levels(hvn_floors, pa_supports, current_price)

    if not levels:
        print(f"*No support levels found below current price for {ticker}*")
        return None, None

    # Analyze each level
    level_results = []
    for lvl in levels:
        events = find_approach_events(daily, lvl["price"])
        if not events:
            continue

        # Enrich held events with hourly bounce measurement
        for event in events:
            event["bounce"] = {}
            if not event["held"]:
                continue
            ts = find_hourly_min_timestamp(hourly, event["min_date"], event["min_low"])
            if ts is not None:
                event["bounce"] = measure_bounce(hourly, ts, event["min_low"])

        stats = compute_level_stats(events)
        verdict = compute_verdict(stats)
        buy_at = _compute_buy_at(lvl["price"], events)

        # Trade setup for actionable levels
        setup = None
        if verdict in ("STRONG BOUNCE", "BOUNCE") and stats["bounce_3d_median"] is not None:
            sell_at = round(buy_at * (1 + stats["bounce_3d_median"] / 100), 2)
            stop = round(buy_at * (1 - stop_loss_pct / 100), 2)
            shares = max(1, int(per_trade_size / buy_at)) if buy_at > 0 else 0
            risk = buy_at - stop
            reward = sell_at - buy_at
            rr = round(reward / risk, 1) if risk > 0 else 0.0
            setup = {
                "buy_at": buy_at,
                "sell_at": sell_at,
                "stop": stop,
                "shares": shares,
                "rr": rr,
            }

        level_results.append({
            "level": lvl,
            "events": events,
            "stats": stats,
            "verdict": verdict,
            "buy_at": buy_at,
            "setup": setup,
        })

    # Build markdown report
    lines = []
    lines.append(f"*Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    lines.append("")
    lines.append(f"## Bounce Analysis: {ticker}")
    lines.append(f"**Current Price: {fmt_dollar(current_price)}** | Data: {len(daily)} days (hourly) | Date: {last_date}")
    lines.append("")

    # Support Levels & Bounce History table
    lines.append("### Support Levels & Bounce History")
    lines.append("| Level | Source | Approaches | Hold% | Bounce 1D | Bounce 2D | Bounce 3D | >= 4.5% | Verdict |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for r in level_results:
        lvl = r["level"]
        s = r["stats"]
        if s is None:
            continue
        b1 = fmt_pct(s["bounce_1d_median"]) if s["bounce_1d_median"] is not None else "N/A"
        b2 = fmt_pct(s["bounce_2d_median"]) if s["bounce_2d_median"] is not None else "N/A"
        b3 = fmt_pct(s["bounce_3d_median"]) if s["bounce_3d_median"] is not None else "N/A"
        pct45 = f"{s['pct_above_4_5']:.0%}" if s["pct_above_4_5"] is not None else "N/A"
        lines.append(
            f"| {fmt_dollar(lvl['price'])} | {lvl['source']} "
            f"| {s['total_approaches']} | {s['hold_rate']:.0%} "
            f"| {b1} | {b2} | {b3} "
            f"| {pct45} | {r['verdict']} |"
        )
    lines.append("")

    # Trade Setups (Actionable Levels)
    actionable = [r for r in level_results if r["setup"] is not None]
    if actionable:
        lines.append("### Trade Setups (Actionable Levels)")
        lines.append("| Level | Buy At | Sell At | Stop | Shares | R/R |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for r in actionable:
            lvl = r["level"]
            s = r["setup"]
            lines.append(
                f"| {fmt_dollar(lvl['price'])} | {fmt_dollar(s['buy_at'])} "
                f"| {fmt_dollar(s['sell_at'])} | {fmt_dollar(s['stop'])} "
                f"| {s['shares']} | {s['rr']}:1 |"
            )
        lines.append("")

    report = "\n".join(lines)

    # Build JSON cache
    json_data = {
        "ticker": ticker,
        "date": last_date,
        "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "current_price": round(current_price, 2),
        "levels": [],
    }
    for r in level_results:
        lvl = r["level"]
        s = r["stats"]
        if s is None:
            continue
        entry = {
            "price": round(lvl["price"], 2),
            "source": lvl["source"],
            "approaches": s["total_approaches"],
            "hold_rate": round(s["hold_rate"], 2),
            "bounce_1d_median": round(s["bounce_1d_median"], 2) if s["bounce_1d_median"] is not None else None,
            "bounce_2d_median": round(s["bounce_2d_median"], 2) if s["bounce_2d_median"] is not None else None,
            "bounce_3d_median": round(s["bounce_3d_median"], 2) if s["bounce_3d_median"] is not None else None,
            "pct_above_4_5": round(s["pct_above_4_5"], 2),
            "verdict": r["verdict"],
            "buy_at": r["buy_at"],
        }
        if r["setup"]:
            entry.update({
                "sell_at": r["setup"]["sell_at"],
                "stop": r["setup"]["stop"],
                "shares": r["setup"]["shares"],
            })
        json_data["levels"].append(entry)

    return report, json_data


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 bounce_analyzer.py <TICKER> [TICKER2 ...]")
        sys.exit(1)

    tickers = [t.upper() for t in sys.argv[1:]]

    for i, ticker in enumerate(tickers):
        if i > 0:
            print()
            print("---")
            print()

        report, json_data = analyze_stock(ticker)
        if report:
            print(report)
            _write_cache(ticker, "bounce_analysis.md", report)
        if json_data:
            agent_dir = AGENTS_DIR / ticker
            agent_dir.mkdir(parents=True, exist_ok=True)
            with open(agent_dir / "bounce_analysis.json", "w") as f:
                json.dump(json_data, f, indent=2)


if __name__ == "__main__":
    main()
