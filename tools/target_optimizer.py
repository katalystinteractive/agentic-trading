#!/usr/bin/env python3
"""
Target Optimizer — Backtest strategy at 2%-10% targets (0.5% steps)
using 13-month OHLC per ticker.

Usage:
  python3 tools/target_optimizer.py CLSK
  python3 tools/target_optimizer.py --all
  python3 tools/target_optimizer.py CLSK --compound
  python3 tools/target_optimizer.py CLSK --range 3.0-8.0 --step 0.25
  python3 tools/target_optimizer.py CLSK --timeout 45
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from statistics import mean

from wick_offset_analyzer import (
    fetch_history, analyze_stock_data, compute_pool_sizing,
    load_capital_config, load_tickers_from_portfolio
)
from trading_calendar import as_of_date_label

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def compute_simulation_levels(ticker, hist):
    """Compute support levels for simulation using analyze_stock_data.
    Returns (sim_levels, base_levels, data_levels, current_price) or (None, None, None, error_str).
    """
    if hist is None or len(hist) < 60:
        n = len(hist) if hist is not None else 0
        return None, None, None, f"insufficient data ({n} rows, need 60+)"

    data, err = analyze_stock_data(ticker, hist)
    if err:
        return None, None, None, err

    current_price = data["current_price"]
    capital = load_capital_config()

    sim_levels = data.get("bullet_plan", {}).get("active", [])
    if not sim_levels:
        return None, None, None, "no qualifying support levels"

    # Sort descending by buy_at (F1 first)
    sim_levels = sorted(sim_levels, key=lambda l: l.get("buy_at", 0), reverse=True)

    # Prepare base_levels for compound re-sizing
    base_levels = [
        {
            "recommended_buy": lv["buy_at"],
            "effective_tier": lv.get("tier", "Half"),
            "hold_rate": lv.get("hold_rate", 0),
            "support_price": lv.get("support_price", lv["buy_at"]),
        }
        for lv in sim_levels
    ]

    data_levels = data.get("levels", [])

    return sim_levels, base_levels, data_levels, current_price


def simulate_single(hist, sim_levels, base_levels, target_pct, active_pool,
                    timeout_days=30, compound=False):
    """Run simulation for a single target %. Returns dict with cycles and metrics."""
    shares_held = 0
    avg_cost = 0.0
    total_cost = 0.0
    entry_day_idx = None
    cycle_low = None
    cooldown_remaining = 0
    cumulative_profit = 0.0
    pool_budget = active_pool
    pool_exhausted = False
    fills = []
    unfilled_levels = list(sim_levels)
    cycles = []

    for day_idx in range(len(hist)):
        day = hist.iloc[day_idx]

        if cooldown_remaining > 0:
            cooldown_remaining -= 1
            continue

        # ENTRIES
        filled_this_day = []
        for level in sorted(unfilled_levels, key=lambda l: l.get("buy_at", 0), reverse=True):
            buy_at = level.get("buy_at", 0)
            if buy_at <= 0:
                continue
            if day["Low"] <= buy_at:
                fill_price = min(day["Open"], buy_at)
                shares = level.get("shares", 1)
                total_cost += fill_price * shares
                shares_held += shares
                avg_cost = total_cost / shares_held
                if entry_day_idx is None:
                    entry_day_idx = day_idx
                    cycle_low = day["Low"]
                fills.append({"price": fill_price, "shares": shares, "day_idx": day_idx})
                filled_this_day.append(id(level))
                cycle_low = min(cycle_low, day["Low"])

        unfilled_levels = [l for l in unfilled_levels if id(l) not in filled_this_day]

        # EXIT
        if shares_held > 0:
            cycle_low = min(cycle_low, day["Low"])
            target_price = avg_cost * (1 + target_pct / 100)

            if day["High"] >= target_price:
                exit_price = target_price
                profit = (exit_price - avg_cost) * shares_held
                cycles.append({
                    "entry_day_idx": entry_day_idx,
                    "exit_day_idx": day_idx,
                    "fills": list(fills),
                    "avg_cost": round(avg_cost, 4),
                    "exit_price": round(exit_price, 4),
                    "shares": shares_held,
                    "profit": round(profit, 2),
                    "profit_pct": round((exit_price - avg_cost) / avg_cost * 100, 2),
                    "won": profit > 0,
                    "cycle_days": day_idx - entry_day_idx + 1,
                    "cycle_low": round(cycle_low, 4),
                    "max_drawdown_pct": round((cycle_low - avg_cost) / avg_cost * 100, 2),
                    "timeout": False,
                    "open_at_end": False,
                    "pool_budget": round(pool_budget, 2),
                })
                cumulative_profit += profit
                shares_held = 0; avg_cost = 0.0; total_cost = 0.0
                entry_day_idx = None; cycle_low = None; fills = []
                cooldown_remaining = 1
                unfilled_levels = list(sim_levels)

                if compound:
                    pool_budget = active_pool + cumulative_profit
                    if pool_budget <= 0:
                        pool_exhausted = True
                        break
                    resized = compute_pool_sizing(base_levels, pool_budget, "active")
                    for lv, base in zip(resized, base_levels):
                        lv["buy_at"] = lv.pop("recommended_buy", base["recommended_buy"])
                        lv["tier"] = base["effective_tier"]
                        lv["support_price"] = base["support_price"]
                    sim_levels = resized
                    unfilled_levels = list(sim_levels)
                continue

            # TIMEOUT
            if (day_idx - entry_day_idx + 1) > timeout_days:
                exit_price = day["Close"]
                profit = (exit_price - avg_cost) * shares_held
                cycles.append({
                    "entry_day_idx": entry_day_idx,
                    "exit_day_idx": day_idx,
                    "fills": list(fills),
                    "avg_cost": round(avg_cost, 4),
                    "exit_price": round(exit_price, 4),
                    "shares": shares_held,
                    "profit": round(profit, 2),
                    "profit_pct": round((exit_price - avg_cost) / avg_cost * 100, 2),
                    "won": profit > 0,
                    "cycle_days": day_idx - entry_day_idx + 1,
                    "cycle_low": round(cycle_low, 4),
                    "max_drawdown_pct": round((cycle_low - avg_cost) / avg_cost * 100, 2),
                    "timeout": True,
                    "open_at_end": False,
                    "pool_budget": round(pool_budget, 2),
                })
                cumulative_profit += profit
                shares_held = 0; avg_cost = 0.0; total_cost = 0.0
                entry_day_idx = None; cycle_low = None; fills = []
                cooldown_remaining = 1
                unfilled_levels = list(sim_levels)

                if compound:
                    pool_budget = active_pool + cumulative_profit
                    if pool_budget <= 0:
                        pool_exhausted = True
                        break
                    resized = compute_pool_sizing(base_levels, pool_budget, "active")
                    for lv, base in zip(resized, base_levels):
                        lv["buy_at"] = lv.pop("recommended_buy", base["recommended_buy"])
                        lv["tier"] = base["effective_tier"]
                        lv["support_price"] = base["support_price"]
                    sim_levels = resized
                    unfilled_levels = list(sim_levels)

    # POST-LOOP: record open position
    if shares_held > 0:
        last_close = hist.iloc[-1]["Close"]
        unrealized = (last_close - avg_cost) * shares_held
        cycles.append({
            "entry_day_idx": entry_day_idx,
            "exit_day_idx": len(hist) - 1,
            "fills": list(fills),
            "avg_cost": round(avg_cost, 4),
            "exit_price": round(float(last_close), 4),
            "shares": shares_held,
            "profit": round(unrealized, 2),
            "profit_pct": round((last_close - avg_cost) / avg_cost * 100, 2),
            "won": None,
            "cycle_days": len(hist) - 1 - entry_day_idx + 1,
            "cycle_low": round(cycle_low, 4) if cycle_low else 0,
            "max_drawdown_pct": round((cycle_low - avg_cost) / avg_cost * 100, 2) if cycle_low and avg_cost > 0 else 0,
            "timeout": False,
            "open_at_end": True,
            "pool_budget": round(pool_budget, 2),
        })

    return {
        "cycles": cycles,
        "cumulative_profit": round(cumulative_profit, 2),
        "pool_exhausted": pool_exhausted,
        "pool_budget_final": round(pool_budget, 2),
    }


def sweep_targets(hist, sim_levels, base_levels, active_pool,
                  range_low, range_high, step, timeout_days=30, compound=False):
    """Run simulation across target range. Returns results dict."""
    results = []
    target = range_low
    targets = []
    while target <= range_high + 0.001:
        targets.append(round(target, 2))
        target += step

    for tgt in targets:
        sim = simulate_single(hist, list(sim_levels), list(base_levels), tgt,
                              active_pool, timeout_days, compound)
        cycles = sim["cycles"]
        completed = [c for c in cycles if not c.get("open_at_end")]

        n = len(completed)
        months = len(hist) / 21 if len(hist) > 0 else 1

        row = {
            "target_pct": tgt,
            "cycles_completed": n,
            "cycles_per_month": round(n / months, 1) if months > 0 else 0,
            "avg_cycle_days": round(mean(c["cycle_days"] for c in completed), 1) if n > 0 else None,
            "win_rate": round(len([c for c in completed if c["won"]]) / n * 100, 1) if n > 0 else 0.0,
            "total_profit_simple": round(sum(c["profit"] for c in completed), 2) if not compound else None,
            "total_profit_compound": round(sum(c["profit"] for c in completed), 2) if compound else None,
            "max_drawdown_pct": round(min((c["max_drawdown_pct"] for c in completed), default=0), 2),
            "longest_cycle_days": max((c["cycle_days"] for c in completed), default=0),
            "timeout_cycles": len([c for c in completed if c.get("timeout")]),
            "open_at_end": any(c.get("open_at_end") for c in cycles),
            "pool_exhausted": sim["pool_exhausted"],
        }

        # For non-compound mode, total_profit_simple
        if not compound:
            row["total_profit_simple"] = round(sum(c["profit"] for c in completed), 2)
            row["total_profit_compound"] = None
        else:
            row["total_profit_simple"] = None
            row["total_profit_compound"] = round(sim["cumulative_profit"], 2)

        results.append(row)

    # Find optimal
    profit_key = "total_profit_compound" if compound else "total_profit_simple"
    valid = [r for r in results if r[profit_key] is not None]
    if valid:
        best = max(valid, key=lambda r: r[profit_key])
        optimal_entry = {"target_pct": best["target_pct"], "total_profit": best[profit_key]}
    else:
        optimal_entry = None

    optimal = {
        "simple": optimal_entry if not compound else None,
        "compound": optimal_entry if compound else None,
    }

    # Open position at end from optimal run
    open_pos = None
    if optimal_entry:
        opt_sim = simulate_single(hist, list(sim_levels), list(base_levels),
                                  optimal_entry["target_pct"], active_pool, timeout_days, compound)
        open_cycles = [c for c in opt_sim["cycles"] if c.get("open_at_end")]
        if open_cycles:
            oc = open_cycles[-1]
            open_pos = {
                "avg_cost": oc["avg_cost"],
                "shares": oc["shares"],
                "unrealized_pct": oc["profit_pct"],
            }

    return {
        "results": results,
        "optimal": optimal,
        "open_position_at_end": open_pos,
    }


def run_both_modes(hist, sim_levels, base_levels, active_pool, range_low, range_high, step, timeout_days):
    """Run simple mode, optionally compound. Returns combined results."""
    simple = sweep_targets(hist, sim_levels, base_levels, active_pool,
                           range_low, range_high, step, timeout_days, compound=False)
    return simple


def run_with_compound(hist, sim_levels, base_levels, active_pool, range_low, range_high, step, timeout_days):
    """Run both simple and compound modes, merge results."""
    simple = sweep_targets(hist, sim_levels, base_levels, active_pool,
                           range_low, range_high, step, timeout_days, compound=False)
    compound = sweep_targets(hist, sim_levels, base_levels, active_pool,
                             range_low, range_high, step, timeout_days, compound=True)

    # Merge compound profits into simple results
    for sr, cr in zip(simple["results"], compound["results"]):
        sr["total_profit_compound"] = cr["total_profit_compound"]
        sr["pool_exhausted"] = cr["pool_exhausted"]

    simple["optimal"]["compound"] = compound["optimal"]["compound"]

    return simple


def format_report(ticker, sweep_result, support_levels, capital_config, compound=False):
    """Format markdown report."""
    lines = []
    today = date.today()
    lines.append(f"# Target Optimization — {ticker} — as of {as_of_date_label(today)}")
    lines.append("")

    # Configuration
    lines.append("## Configuration")
    lines.append("| Setting | Value |")
    lines.append("| :--- | :--- |")
    lines.append(f"| Active Pool | ${capital_config['active_pool']:.0f} |")
    lines.append(f"| Max Bullets | {capital_config['active_bullets_max']} |")
    lines.append(f"| Levels Used | {capital_config['levels_used']} |")
    lines.append(f"| Bias | Forward-looking (static levels) |")
    lines.append("")

    # Support levels
    lines.append("## Support Levels Used")
    lines.append("| Level | Buy At | Hold Rate | Tier | Shares | Source |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
    for i, lv in enumerate(support_levels, 1):
        lines.append(f"| B{i} | ${lv['buy_at']:.2f} | {lv['hold_rate']:.0f}% | {lv['tier']} | {lv['shares']} | {lv.get('source', 'N/A')} |")
    lines.append("")

    # Results table
    results = sweep_result["results"]
    lines.append("## Results by Target %")

    if compound:
        lines.append("| Target % | Cycles | Cycles/Mo | Avg Days | Win Rate | Profit (Simple) | Profit (Compound) | Max DD | Timeouts |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    else:
        lines.append("| Target % | Cycles | Cycles/Mo | Avg Days | Win Rate | Total Profit | Max DD | Longest | Timeouts |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    for r in results:
        avg_d = f"{r['avg_cycle_days']:.0f}" if r['avg_cycle_days'] is not None else "--"
        wr = f"{r['win_rate']:.0f}%" if r['cycles_completed'] > 0 else "--"

        if compound:
            sp = f"${r['total_profit_simple']:.2f}" if r['total_profit_simple'] is not None else "--"
            cp = f"${r['total_profit_compound']:.2f}" if r['total_profit_compound'] is not None else "--"
            dd = f"{r['max_drawdown_pct']:.1f}%"
            lines.append(f"| {r['target_pct']:.1f}% | {r['cycles_completed']} | {r['cycles_per_month']:.1f} | {avg_d} | {wr} | {sp} | {cp} | {dd} | {r['timeout_cycles']} |")
        else:
            profit = f"${r['total_profit_simple']:.2f}" if r['total_profit_simple'] is not None else "--"
            dd = f"{r['max_drawdown_pct']:.1f}%"
            lines.append(f"| {r['target_pct']:.1f}% | {r['cycles_completed']} | {r['cycles_per_month']:.1f} | {avg_d} | {wr} | {profit} | {dd} | {r['longest_cycle_days']}d | {r['timeout_cycles']} |")
    lines.append("")

    # Optimal
    opt = sweep_result["optimal"]
    lines.append("## Optimal Target")
    if opt.get("simple"):
        lines.append(f"- **Simple:** {opt['simple']['target_pct']:.1f}% → ${opt['simple']['total_profit']:.2f}")
    if opt.get("compound"):
        lines.append(f"- **Compound:** {opt['compound']['target_pct']:.1f}% → ${opt['compound']['total_profit']:.2f}")
    lines.append("")

    # Profit curve
    lines.append("## Profit Curve")
    profit_key = "total_profit_simple"
    valid_profits = [r[profit_key] for r in results if r[profit_key] is not None]
    if valid_profits:
        max_profit = max(valid_profits)
        if max_profit > 0:
            opt_pct = opt.get("simple", {}).get("target_pct") if opt.get("simple") else None
            for r in results:
                p = r[profit_key]
                if p is None:
                    continue
                filled = round(max(0, p) / max_profit * 30) if max_profit > 0 else 0
                bar = "█" * filled + "░" * (30 - filled)
                marker = " <-- OPTIMAL" if opt_pct and r["target_pct"] == opt_pct else ""
                lines.append(f"{r['target_pct']:4.1f}%  | ${p:>7.2f} | {bar}{marker}")
        else:
            lines.append("No profitable cycles — bar chart skipped.")
    lines.append("")

    return "\n".join(lines)


def process_ticker(ticker, args):
    """Process a single ticker. Returns (markdown, json_data) or (None, error_str)."""
    hist = fetch_history(ticker, months=13)
    result = compute_simulation_levels(ticker, hist)

    if isinstance(result[3], str) and result[0] is None:
        return None, result[3]

    sim_levels, base_levels, data_levels, current_price = result
    capital = load_capital_config()
    active_pool = capital["active_pool"]

    # Parse range
    range_low, range_high = args.range_low, args.range_high
    step = args.step
    timeout = args.timeout

    if args.compound:
        sweep_result = run_with_compound(hist, sim_levels, base_levels, active_pool,
                                         range_low, range_high, step, timeout)
    else:
        sweep_result = run_both_modes(hist, sim_levels, base_levels, active_pool,
                                      range_low, range_high, step, timeout)

    # Build support_levels_used with source from data_levels
    data_level_map = {round(l.get("support_price", 0), 2): l for l in data_levels}
    support_levels = []
    for lv in sim_levels:
        sp = round(lv.get("support_price", lv.get("buy_at", 0)), 2)
        dl = data_level_map.get(sp, {})
        support_levels.append({
            "support_price": sp,
            "buy_at": lv.get("buy_at", 0),
            "hold_rate": lv.get("hold_rate", 0),
            "tier": lv.get("tier", "Half"),
            "shares": lv.get("shares", 1),
            "source": dl.get("source", "N/A"),
        })

    capital_config = {
        "active_pool": active_pool,
        "active_bullets_max": capital["active_bullets_max"],
        "levels_used": len(sim_levels),
    }

    md = format_report(ticker, sweep_result, support_levels, capital_config, args.compound)

    # Build JSON output
    json_data = {
        "ticker": ticker,
        "run_date": date.today().isoformat(),
        "data_period": {
            "start": hist.index[0].strftime("%Y-%m-%d"),
            "end": hist.index[-1].strftime("%Y-%m-%d"),
            "trading_days": len(hist),
        },
        "forward_looking_bias": "static",
        "support_levels_used": support_levels,
        "capital_config": capital_config,
        "results": sweep_result["results"],
        "optimal": sweep_result["optimal"],
        "open_position_at_end": sweep_result["open_position_at_end"],
    }

    # Write files
    ticker_dir = PROJECT_ROOT / "tickers" / ticker
    ticker_dir.mkdir(parents=True, exist_ok=True)
    (ticker_dir / "target_optimization.json").write_text(
        json.dumps(json_data, indent=2, default=str), encoding="utf-8"
    )
    (ticker_dir / "target_optimization.md").write_text(md, encoding="utf-8")

    return md, json_data


def main():
    parser = argparse.ArgumentParser(description="Target % Optimizer")
    parser.add_argument("ticker", nargs="?", help="Ticker symbol")
    parser.add_argument("--all", action="store_true", help="Run for all portfolio tickers")
    parser.add_argument("--compound", action="store_true", help="Include compound mode")
    parser.add_argument("--range", default="2.0-10.0", help="Target range (default: 2.0-10.0)")
    parser.add_argument("--step", type=float, default=0.5, help="Step size (default: 0.5)")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout days (default: 30)")
    args = parser.parse_args()

    # Parse range
    parts = args.range.split("-")
    args.range_low = float(parts[0])
    args.range_high = float(parts[1])

    if args.all:
        tickers = load_tickers_from_portfolio()
        print(f"# Target Optimizer — All Tickers ({len(tickers)})\n")

        all_results = []
        for ticker in tickers:
            print(f"Processing {ticker}...", file=sys.stderr)
            md, result = process_ticker(ticker, args)
            if md is None:
                print(f"  Skipped {ticker}: {result}", file=sys.stderr)
                continue
            opt = result.get("optimal", {})
            simple_opt = opt.get("simple", {}) or {}
            compound_opt = opt.get("compound", {}) or {}
            n_cycles = 0
            timeouts = 0
            for r in result.get("results", []):
                if r["target_pct"] == simple_opt.get("target_pct"):
                    n_cycles = r["cycles_completed"]
                    timeouts = r["timeout_cycles"]
                    break
            all_results.append({
                "ticker": ticker,
                "simple_pct": simple_opt.get("target_pct"),
                "simple_profit": simple_opt.get("total_profit"),
                "compound_pct": compound_opt.get("target_pct"),
                "compound_profit": compound_opt.get("total_profit"),
                "cycles": n_cycles,
                "timeouts": timeouts,
            })

        # Cross-ticker table
        print("| Ticker | Optimal % (Simple) | Profit (Simple) | Cycles | Timeouts |")
        print("| :--- | :--- | :--- | :--- | :--- |")
        all_results.sort(key=lambda r: -(r["simple_profit"] or 0))
        for r in all_results:
            sp = f"{r['simple_pct']:.1f}%" if r['simple_pct'] else "--"
            profit = f"${r['simple_profit']:.2f}" if r['simple_profit'] else "--"
            print(f"| {r['ticker']} | {sp} | {profit} | {r['cycles']} | {r['timeouts']} |")

    elif args.ticker:
        md, result = process_ticker(args.ticker.upper(), args)
        if md is None:
            print(f"Error: {result}", file=sys.stderr)
            sys.exit(1)
        print(md)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
