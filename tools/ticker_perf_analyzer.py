#!/usr/bin/env python3
"""Per-ticker performance analysis — KPIs from trade history.

Reconstructs completed cycles from trade_history.json, computes 5 KPIs
(deployment depth, capture ratio, reserve breach, cycle velocity, drawdown),
and generates sell target recommendations for tickers with consistent
underperformance.

Usage:
    python3 tools/ticker_perf_analyzer.py              # all tickers, stdout
    python3 tools/ticker_perf_analyzer.py LUNR CIFR     # specific tickers only
    python3 tools/ticker_perf_analyzer.py --json        # also write ticker-perf-analysis.json
"""
import sys
import json
import argparse
import warnings
from datetime import date
from pathlib import Path
from statistics import median

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
TRADE_HISTORY_PATH = _ROOT / "trade_history.json"
PORTFOLIO_PATH = _ROOT / "portfolio.json"
PROFILES_PATH = _ROOT / "ticker_profiles.json"
PERF_OUTPUT_PATH = _ROOT / "ticker-perf-analysis.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wick_offset_analyzer import fetch_history

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_CYCLES_FOR_RECS = 3
CAPTURE_RATIO_THRESHOLD = 70
CAPTURE_RATIO_CAP = 100.0
SHALLOW_DEPTH_THRESHOLD = 25
MAX_TARGET_PCT = 12.0
MIN_TARGET_PCT = 4.5
POST_SELL_PEAK_DAYS = 5


def _ts(date_str, hist):
    """Create a tz-aware Timestamp matching hist.index timezone."""
    ts = pd.Timestamp(date_str)
    if hist.index.tz is not None:
        ts = ts.tz_localize(hist.index.tz)
    return ts


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_trade_history():
    try:
        with open(TRADE_HISTORY_PATH) as f:
            data = json.load(f)
        return data.get("trades", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _load_portfolio():
    try:
        with open(PORTFOLIO_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _load_active_pool():
    portfolio = _load_portfolio()
    return portfolio.get("capital", {}).get("active_pool", 300)


def _build_ticker_universe():
    portfolio = _load_portfolio()
    trade_history = _load_trade_history()

    universe = set()
    universe.update(portfolio.get("watchlist", []))
    universe.update(portfolio.get("positions", {}).keys())
    for trade in trade_history:
        universe.add(trade["ticker"])

    return sorted(universe)


# ---------------------------------------------------------------------------
# Backfill normalization
# ---------------------------------------------------------------------------

def _filter_pre_strategy(trades):
    return [t for t in trades if not t.get("pre_strategy", False)]


def _sort_trades(trades):
    return sorted(trades, key=lambda t: (t["date"], t.get("id", 0)))


def _reconstruct_avg_cost(buys_so_far):
    total_cost = sum(b["shares"] * b["price"] for b in buys_so_far)
    total_shares = sum(b["shares"] for b in buys_so_far)
    if total_shares == 0:
        return None
    return total_cost / total_shares


def _reconstruct_pnl_pct(sell_trade, avg_cost):
    if avg_cost is None or avg_cost <= 0:
        return None
    return (sell_trade["price"] - avg_cost) / avg_cost * 100


# ---------------------------------------------------------------------------
# Cycle reconstruction
# ---------------------------------------------------------------------------

def reconstruct_cycles(trades, ticker):
    """Reconstruct completed cycles from trade list for a ticker.

    Returns (completed_cycles, open_cycle_or_None).
    """
    filtered = _filter_pre_strategy(trades)
    ticker_trades = [t for t in filtered if t["ticker"] == ticker]
    ticker_trades = _sort_trades(ticker_trades)

    completed = []
    current_buys = []
    current_sells = []
    running_shares = 0
    avg_cost_timeline = []  # (date, avg_cost) tuples
    data_incomplete = False

    for trade in ticker_trades:
        side = trade.get("side", "").upper()

        if side == "BUY":
            current_buys.append(trade)
            running_shares += trade["shares"]
            avg = _reconstruct_avg_cost(current_buys)
            avg_cost_timeline.append((trade["date"], avg))

        elif side == "SELL":
            running_shares -= trade["shares"]
            current_sells.append(trade)

            if running_shares == 0:
                # Cycle complete
                cycle = _build_cycle(current_buys, current_sells,
                                     avg_cost_timeline, data_incomplete)
                completed.append(cycle)
                current_buys = []
                current_sells = []
                avg_cost_timeline = []
                data_incomplete = False

            elif running_shares < 0:
                # Negative shares guard — orphaned SELL or missing BUY
                cycle = _build_cycle(current_buys, current_sells,
                                     avg_cost_timeline, True)
                completed.append(cycle)
                current_buys = []
                current_sells = []
                avg_cost_timeline = []
                running_shares = 0
                data_incomplete = False

    # Open cycle
    open_cycle = None
    if current_buys:
        avg = _reconstruct_avg_cost(current_buys)
        open_cycle = {
            "buys": current_buys,
            "sells": current_sells,
            "avg_cost": avg,
            "running_shares": running_shares,
        }

    return completed, open_cycle


def _build_cycle(buys, sells, avg_cost_timeline, data_incomplete):
    """Build a completed cycle dict from buys/sells."""
    avg_cost = _reconstruct_avg_cost(buys)
    total_invested = sum(b["shares"] * b["price"] for b in buys)

    # Blended sell price (weighted average across all sells)
    total_sell_shares = sum(s["shares"] for s in sells)
    if total_sell_shares > 0:
        blended_sell = sum(s["shares"] * s["price"] for s in sells) / total_sell_shares
    else:
        blended_sell = None

    # Blended pnl
    blended_pnl = None
    if blended_sell and avg_cost and avg_cost > 0:
        blended_pnl = (blended_sell - avg_cost) / avg_cost * 100

    # Final pnl from closing sell
    final_pnl = sells[-1].get("pnl_pct") if sells else None
    if final_pnl is None and sells and avg_cost:
        final_pnl = _reconstruct_pnl_pct(sells[-1], avg_cost)

    # Reserve breach
    unknown_zone = 0
    used_reserve = False
    for b in buys:
        zone = b.get("zone")
        if zone is None:
            unknown_zone += 1
        elif zone == "reserve":
            used_reserve = True

    # Cycle days
    if buys and sells:
        first_buy_date = buys[0]["date"]
        last_sell_date = sells[-1]["date"]
        from datetime import datetime
        d1 = datetime.strptime(first_buy_date, "%Y-%m-%d")
        d2 = datetime.strptime(last_sell_date, "%Y-%m-%d")
        cycle_days = (d2 - d1).days
    else:
        cycle_days = 0

    return {
        "buys": buys,
        "sells": sells,
        "total_invested": total_invested,
        "used_reserve": used_reserve,
        "unknown_zone_count": unknown_zone,
        "cycle_days": cycle_days,
        "avg_cost": avg_cost,
        "avg_cost_timeline": avg_cost_timeline,
        "blended_sell_price": blended_sell,
        "blended_pnl_pct": blended_pnl,
        "final_pnl_pct": final_pnl,
        "data_incomplete": data_incomplete,
    }


# ---------------------------------------------------------------------------
# KPI computations
# ---------------------------------------------------------------------------

def compute_deployment_depth(cycle, active_pool):
    if active_pool <= 0:
        return 0.0
    return cycle["total_invested"] / active_pool * 100


def compute_capture_ratio(cycle, hist):
    """Compute capture ratio for a cycle. Returns float or None if skipped."""
    avg_cost = cycle.get("avg_cost")
    blended_sell = cycle.get("blended_sell_price")
    if not avg_cost or avg_cost <= 0 or not blended_sell:
        return None

    actual_pnl_pct = (blended_sell - avg_cost) / avg_cost * 100

    # Find post-sell peak
    last_sell_date = cycle["sells"][-1]["date"]

    post_sell = hist[hist.index > _ts(last_sell_date, hist)].head(POST_SELL_PEAK_DAYS)
    if len(post_sell) == 0:
        return None  # Skip — no trading days after sell

    max_high = float(post_sell["High"].max())
    peak_profit = (max_high - avg_cost) / avg_cost * 100

    if peak_profit <= 0:
        return CAPTURE_RATIO_CAP  # Stock cratered post-sell — perfect exit

    ratio = actual_pnl_pct / peak_profit * 100
    return min(ratio, CAPTURE_RATIO_CAP)


def compute_reserve_breach(cycle):
    return cycle.get("used_reserve", False)


def compute_cycle_velocity(cycle):
    return cycle.get("cycle_days", 0)


def compute_drawdown(cycle, hist):
    """Compute max drawdown during a cycle using running avg_cost timeline."""
    timeline = cycle.get("avg_cost_timeline", [])
    if not timeline:
        return None

    first_buy_date = cycle["buys"][0]["date"]
    last_sell_date = cycle["sells"][-1]["date"]

    cycle_hist = hist[
        (hist.index >= _ts(first_buy_date, hist)) &
        (hist.index <= _ts(last_sell_date, hist))
    ]
    if cycle_hist.empty:
        return None

    # Build avg_cost lookup: for each date, use the most recent avg_cost
    # When multiple BUYs on same day, keep only the last (final avg after all same-day fills)
    date_to_avg = {}
    for d, avg in timeline:
        date_to_avg[d] = avg  # Last entry per date wins
    sorted_dates = sorted(date_to_avg.keys())

    max_dd = 0.0
    for idx in range(len(cycle_hist)):
        row_date = cycle_hist.index[idx].strftime("%Y-%m-%d")
        day_low = float(cycle_hist["Low"].iloc[idx])

        # Find applicable avg_cost (most recent on or before this date)
        applicable_avg = None
        for d in sorted_dates:
            if d <= row_date:
                applicable_avg = date_to_avg[d]
            else:
                break

        if applicable_avg and applicable_avg > 0:
            dd = (day_low - applicable_avg) / applicable_avg * 100
            if dd < max_dd:
                max_dd = dd

    return round(max_dd, 2) if max_dd < 0 else None


def compute_all_kpis(ticker, cycles, hist, active_pool):
    """Compute all 5 KPIs for a ticker. Returns dict."""
    if not cycles:
        return {
            "completed_cycles": 0,
            "deployment_depth_pct": None,
            "capture_ratio_pct": None,
            "reserve_breach_pct": None,
            "median_cycle_days": None,
            "max_drawdown_pct": None,
            "unknown_zone_trades": 0,
            "incomplete_cycles": 0,
        }

    # KPI 1: Deployment depth
    depths = [compute_deployment_depth(c, active_pool) for c in cycles]

    # KPI 2: Capture ratio
    capture_ratios = []
    for c in cycles:
        if hist is not None:
            cr = compute_capture_ratio(c, hist)
            if cr is not None:
                capture_ratios.append(cr)

    # KPI 3: Reserve breach
    reserve_breaches = sum(1 for c in cycles if compute_reserve_breach(c))

    # KPI 4: Cycle velocity
    velocities = [compute_cycle_velocity(c) for c in cycles]

    # KPI 5: Drawdown
    drawdowns = []
    for c in cycles:
        if hist is not None:
            dd = compute_drawdown(c, hist)
            if dd is not None:
                drawdowns.append(dd)

    # Data quality
    unknown_zones = sum(c.get("unknown_zone_count", 0) for c in cycles)
    incomplete = sum(1 for c in cycles if c.get("data_incomplete", False))

    return {
        "completed_cycles": len(cycles),
        "deployment_depth_pct": round(median(depths), 1) if depths else None,
        "capture_ratio_pct": round(median(capture_ratios), 1) if capture_ratios else None,
        "reserve_breach_pct": round(reserve_breaches / len(cycles) * 100, 1) if cycles else None,
        "median_cycle_days": int(median(velocities)) if velocities else None,
        "max_drawdown_pct": round(median(drawdowns), 1) if drawdowns else None,
        "unknown_zone_trades": unknown_zones,
        "incomplete_cycles": incomplete,
    }


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

def generate_recommendations(ticker, kpis, cycles, hist, active_pool):
    """Generate recommendations based on KPIs. Returns list of rec dicts."""
    recs = []
    n = kpis["completed_cycles"]

    if n < MIN_CYCLES_FOR_RECS:
        return recs

    # Sell target recommendation
    capture = kpis.get("capture_ratio_pct")
    if capture is not None and capture < CAPTURE_RATIO_THRESHOLD:
        # Compute optimal target from post-sell peaks
        peak_profits = []
        avg_costs = []
        for c in cycles:
            avg_cost = c.get("avg_cost")
            if not avg_cost or avg_cost <= 0 or not c["sells"]:
                continue
            last_sell_date = c["sells"][-1]["date"]
            post_sell = hist[hist.index > _ts(last_sell_date, hist)].head(POST_SELL_PEAK_DAYS)
            if len(post_sell) == 0:
                continue
            max_high = float(post_sell["High"].max())
            peak_profit_pct = (max_high - avg_cost) / avg_cost * 100
            if peak_profit_pct > 0:
                peak_profits.append(peak_profit_pct)
                avg_costs.append(avg_cost)

        if peak_profits:
            median_peak = median(peak_profits)
            # Round to nearest 0.5%
            optimal = round(median_peak * 2) / 2
            optimal = max(MIN_TARGET_PCT, min(optimal, MAX_TARGET_PCT))

            median_avg_cost = median(avg_costs)
            median_peak_price = median_avg_cost * (1 + median_peak / 100)

            recs.append({
                "ticker": ticker,
                "type": "sell_target",
                "current_value": 6.0,
                "proposed_value": optimal,
                "basis": f"Capture {capture:.0f}%, {n} cycles, median peak ${median_peak_price:.2f}",
                "approved": False,
            })

    # Sizing mode recommendation (informational)
    depth = kpis.get("deployment_depth_pct")
    if depth is not None and depth < SHALLOW_DEPTH_THRESHOLD:
        recs.append({
            "ticker": ticker,
            "type": "sizing_mode",
            "current_value": "spread",
            "proposed_value": "compact",
            "basis": f"Median deployment {depth:.0f}%, {n} cycles",
            "approved": False,
        })

    return recs


# ---------------------------------------------------------------------------
# Frequency self-assessment
# ---------------------------------------------------------------------------

def load_previous_run():
    try:
        with open(PERF_OUTPUT_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def compute_frequency(prev, current_recs):
    """Compare recommendations to previous run, track consecutive no-change."""
    if prev is None:
        return {"consecutive_no_change": 0, "recommendation": "daily"}

    prev_recs = prev.get("recommendations", [])
    # Compare using (ticker, type, proposed_value) tuples
    prev_set = {(r["ticker"], r["type"], r["proposed_value"]) for r in prev_recs}
    curr_set = {(r["ticker"], r["type"], r["proposed_value"]) for r in current_recs}

    if curr_set == prev_set:
        count = prev.get("frequency", {}).get("consecutive_no_change", 0) + 1
    else:
        count = 0

    if count <= 3:
        rec = "daily"
    elif count <= 6:
        rec = "every 2 days"
    else:
        rec = "every 3 days"

    return {"consecutive_no_change": count, "recommendation": rec}


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_stdout(all_results, frequency):
    """Print markdown tables to stdout."""
    today = date.today().isoformat()
    tickers_with_cycles = sum(1 for r in all_results if r["kpis"]["completed_cycles"] > 0)

    print(f"## Ticker Performance Analysis")
    print()
    print(f"*Analyzed {len(all_results)} tickers ({tickers_with_cycles} with completed cycles, as of {today})*")
    print()

    # Recommendations table
    all_recs = []
    for r in all_results:
        all_recs.extend(r.get("recommendations", []))

    sell_recs = [r for r in all_recs if r["type"] == "sell_target"]
    if sell_recs:
        print(f"### Recommendations ({len(sell_recs)} tickers)")
        print()
        print("| Ticker | Rec | Current | Proposed | Basis |")
        print("| :--- | :--- | :--- | :--- | :--- |")
        for rec in sell_recs:
            print(f"| {rec['ticker']} | Sell Target | {rec['current_value']:.1f}% "
                  f"| {rec['proposed_value']:.1f}% | {rec['basis']} |")
        print()

    # All tickers table
    print("### All Tickers")
    print()
    print("| Ticker | Cycles | Depth | Capture | Velocity | Reserve | Drawdown | Data Gaps | Status |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for r in all_results:
        ticker = r["ticker"]
        kpis = r["kpis"]
        n = kpis["completed_cycles"]
        recs = r.get("recommendations", [])

        if n == 0:
            if r.get("open_cycle"):
                status = "Open (0 completed)"
            else:
                status = "No history"
            print(f"| {ticker} | 0 | — | — | — | — | — | — | {status} |")
            continue

        depth = f"{kpis['deployment_depth_pct']:.0f}%" if kpis["deployment_depth_pct"] is not None else "—"
        capture = f"{kpis['capture_ratio_pct']:.0f}%" if kpis["capture_ratio_pct"] is not None else "—"
        velocity = f"{kpis['median_cycle_days']}d" if kpis["median_cycle_days"] is not None else "—"
        reserve = f"{kpis['reserve_breach_pct']:.0f}%" if kpis["reserve_breach_pct"] is not None else "—"
        drawdown = f"{kpis['max_drawdown_pct']:.1f}%" if kpis["max_drawdown_pct"] is not None else "—"

        # Data gaps
        gaps = []
        if kpis["unknown_zone_trades"] > 0:
            gaps.append(f"{kpis['unknown_zone_trades']} no-zone")
        if kpis["incomplete_cycles"] > 0:
            gaps.append(f"{kpis['incomplete_cycles']} incomplete")
        gaps_str = ", ".join(gaps) if gaps else "—"

        # Status
        sell_rec = [rec for rec in recs if rec["type"] == "sell_target"]
        if sell_rec:
            status = f"**Sell target: {sell_rec[0]['proposed_value']:.1f}%**"
        elif n < MIN_CYCLES_FOR_RECS:
            status = f"< {MIN_CYCLES_FOR_RECS} cycles"
        else:
            status = "No change"

        print(f"| {ticker} | {n} | {depth} | {capture} | {velocity} "
              f"| {reserve} | {drawdown} | {gaps_str} | {status} |")

    print()

    # Frequency assessment
    count = frequency.get("consecutive_no_change", 0)
    rec = frequency.get("recommendation", "daily")
    if count > 0:
        print(f"*Run {count}/{count} with no new recommendations. Consider extending to {rec}.*")
    else:
        print(f"*Frequency: {rec}.*")
    print()


def write_json(all_results, frequency, active_pool):
    """Write ticker-perf-analysis.json."""
    today = date.today().isoformat()
    tickers_with_cycles = sum(1 for r in all_results if r["kpis"]["completed_cycles"] > 0)

    all_recs = []
    for r in all_results:
        all_recs.extend(r.get("recommendations", []))

    kpis_dict = {}
    for r in all_results:
        ticker = r["ticker"]
        kpis = r["kpis"]
        recs = r.get("recommendations", [])

        # Determine status
        n = kpis["completed_cycles"]
        sell_rec = [rec for rec in recs if rec["type"] == "sell_target"]
        if sell_rec:
            status = "sell_target_advisory"
        elif n == 0:
            status = "no_history" if not r.get("open_cycle") else "open_only"
        elif n < MIN_CYCLES_FOR_RECS:
            status = "insufficient_data"
        else:
            status = "no_change"

        kpis_dict[ticker] = {
            "completed_cycles": n,
            "deployment_depth_pct": kpis["deployment_depth_pct"],
            "capture_ratio_pct": kpis["capture_ratio_pct"],
            "reserve_breach_pct": kpis["reserve_breach_pct"],
            "median_cycle_days": kpis["median_cycle_days"],
            "max_drawdown_pct": kpis["max_drawdown_pct"],
            "unknown_zone_trades": kpis["unknown_zone_trades"],
            "open_cycle": r.get("open_cycle") is not None,
            "status": status,
        }

    output = {
        "as_of": today,
        "tickers_analyzed": len(all_results),
        "tickers_with_cycles": tickers_with_cycles,
        "active_pool": active_pool,
        "recommendations": all_recs,
        "kpis": kpis_dict,
        "frequency": frequency,
    }

    with open(PERF_OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Per-ticker performance analysis from trade history")
    parser.add_argument("tickers", nargs="*", type=str.upper,
                        help="Specific tickers to analyze (default: all)")
    parser.add_argument("--json", action="store_true",
                        help="Also write ticker-perf-analysis.json")
    args = parser.parse_args()

    warnings.filterwarnings("ignore", category=FutureWarning)

    all_trades = _load_trade_history()
    active_pool = _load_active_pool()

    if args.tickers:
        universe = sorted(set(args.tickers))
    else:
        universe = _build_ticker_universe()

    # Load previous run for frequency comparison
    prev_run = load_previous_run()

    all_results = []
    # Cache hist per ticker (only fetch for tickers with completed cycles)
    hist_cache = {}

    for ticker in universe:
        cycles, open_cycle = reconstruct_cycles(all_trades, ticker)

        hist = None
        if cycles:
            if ticker not in hist_cache:
                try:
                    hist_cache[ticker] = fetch_history(ticker, months=13)
                except Exception:
                    hist_cache[ticker] = None
            hist = hist_cache[ticker]

        kpis = compute_all_kpis(ticker, cycles, hist, active_pool)
        recs = generate_recommendations(ticker, kpis, cycles, hist, active_pool)

        all_results.append({
            "ticker": ticker,
            "kpis": kpis,
            "recommendations": recs,
            "open_cycle": open_cycle,
        })

    # Frequency
    all_recs = []
    for r in all_results:
        all_recs.extend(r.get("recommendations", []))
    frequency = compute_frequency(prev_run, all_recs)

    # Output
    format_stdout(all_results, frequency)

    if args.json:
        write_json(all_results, frequency, active_pool)


if __name__ == "__main__":
    main()
