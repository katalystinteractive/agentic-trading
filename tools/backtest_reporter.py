"""Surgical Backtest Reporter — Phase 3 of backtest-surgical-workflow.

Reads simulation results (trades.json, cycles.json, equity_curve.json)
and generates comprehensive markdown report with risk-adjusted metrics.

Usage:
    python3 tools/backtest_reporter.py --data-dir data/backtest/latest
"""
import sys
import json
import csv
import math
from pathlib import Path
from collections import defaultdict

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent


def load_results(data_dir):
    p = Path(data_dir)
    results = {}
    for name in ["trades.json", "cycles.json", "equity_curve.json", "config.json"]:
        path = p / name
        if path.exists():
            with open(path) as f:
                results[name] = json.load(f)
    return results


def compute_metrics(trades, cycles, equity_curve, config_meta):
    """Compute all analysis metrics."""
    m = {}
    sell_trades = [t for t in trades if t.get("side") == "SELL"]
    buy_trades = [t for t in trades if t.get("side") == "BUY"]

    if not sell_trades:
        return {"error": "No completed trades"}

    # --- Basic ---
    wins = [t for t in sell_trades if t.get("pnl_pct", 0) > 0]
    losses = [t for t in sell_trades if t.get("pnl_pct", 0) <= 0]
    total_pnl = sum(t.get("pnl_dollars", 0) for t in sell_trades)

    m["total_buys"] = len(buy_trades)
    m["total_sells"] = len(sell_trades)
    m["total_cycles"] = len(cycles)
    m["wins"] = len(wins)
    m["losses"] = len(losses)
    m["win_rate"] = round(len(wins) / len(sell_trades) * 100, 1) if sell_trades else 0
    m["total_pnl"] = round(total_pnl, 2)
    m["avg_pnl_pct"] = round(float(np.mean([t["pnl_pct"] for t in sell_trades])), 2)
    m["avg_hold_days"] = round(float(np.mean([t.get("days_held", 0) for t in sell_trades])), 1)

    # --- Profit factor ---
    win_sum = sum(t["pnl_dollars"] for t in wins) if wins else 0
    loss_sum = abs(sum(t["pnl_dollars"] for t in losses)) if losses else 0
    m["profit_factor"] = round(win_sum / loss_sum, 2) if loss_sum > 0 else float("inf")

    # --- Risk metrics ---
    pnl_list = [t["pnl_dollars"] for t in sell_trades]
    if len(pnl_list) > 1:
        arr = np.array(pnl_list)
        mean_r = np.mean(arr)
        std_r = np.std(arr, ddof=1)
        if std_r > 0 and equity_curve:
            trades_per_year = min(len(sell_trades) * 252 / max(len(equity_curve), 1), 252)
            m["sharpe"] = round(float(mean_r / std_r * math.sqrt(trades_per_year)), 2)
        downside = arr[arr < 0]
        if len(downside) > 1:
            ds = np.std(downside, ddof=1)
            if ds > 0 and equity_curve:
                m["sortino"] = round(float(mean_r / ds * math.sqrt(trades_per_year)), 2)

    # --- Equity curve ---
    if equity_curve:
        totals = [e.get("total_pnl", 0) for e in equity_curve]
        peak = totals[0]
        max_dd = 0
        for t in totals:
            if t > peak:
                peak = t
            dd = t - peak
            if dd < max_dd:
                max_dd = dd
        m["max_drawdown"] = round(max_dd, 2)
        m["final_pnl"] = round(totals[-1], 2)
        m["peak_pnl"] = round(max(totals), 2)

    # --- Exit reasons ---
    reasons = defaultdict(lambda: {"count": 0, "pnl": 0.0, "pcts": []})
    for t in sell_trades:
        r = t.get("exit_reason", "UNKNOWN")
        reasons[r]["count"] += 1
        reasons[r]["pnl"] += t.get("pnl_dollars", 0)
        reasons[r]["pcts"].append(t.get("pnl_pct", 0))
    m["exit_reasons"] = {
        r: {"count": d["count"], "total_pnl": round(d["pnl"], 2),
            "avg_pnl": round(float(np.mean(d["pcts"])), 2)}
        for r, d in reasons.items()
    }

    # --- Per-zone ---
    zone_stats = defaultdict(lambda: {"fills": 0, "pnl": 0.0})
    for t in buy_trades:
        z = t.get("zone", "Unknown")
        zone_stats[z]["fills"] += 1
    for c in cycles:
        for z in c.get("zones", []):
            zone_stats[z]["pnl"] += c.get("pnl_pct", 0) / max(len(c.get("zones", [1])), 1)
    m["zone_stats"] = dict(zone_stats)

    # --- Per-regime ---
    regime_stats = defaultdict(lambda: {"sells": 0, "pnl": 0.0, "wins": 0})
    for t in sell_trades:
        r = t.get("regime", "Neutral")
        regime_stats[r]["sells"] += 1
        regime_stats[r]["pnl"] += t.get("pnl_dollars", 0)
        if t.get("pnl_pct", 0) > 0:
            regime_stats[r]["wins"] += 1
    m["regime_stats"] = {
        r: {"sells": d["sells"], "pnl": round(d["pnl"], 2),
            "win_rate": round(d["wins"] / d["sells"] * 100, 1) if d["sells"] else 0}
        for r, d in regime_stats.items()
    }

    # --- Per-ticker ---
    ticker_stats = defaultdict(lambda: {"buys": 0, "sells": 0, "pnl": 0.0, "wins": 0, "cycles": 0})
    for t in buy_trades:
        ticker_stats[t["ticker"]]["buys"] += 1
    for t in sell_trades:
        tk = t["ticker"]
        ticker_stats[tk]["sells"] += 1
        ticker_stats[tk]["pnl"] += t.get("pnl_dollars", 0)
        if t.get("pnl_pct", 0) > 0:
            ticker_stats[tk]["wins"] += 1
    for c in cycles:
        ticker_stats[c["ticker"]]["cycles"] += 1
    m["per_ticker"] = {
        tk: {"buys": d["buys"], "sells": d["sells"], "cycles": d["cycles"],
             "pnl": round(d["pnl"], 2),
             "win_rate": round(d["wins"] / d["sells"] * 100, 1) if d["sells"] else 0}
        for tk, d in sorted(ticker_stats.items(), key=lambda x: x[1]["pnl"], reverse=True)
    }

    # --- Monthly ---
    monthly = defaultdict(lambda: {"sells": 0, "pnl": 0.0, "wins": 0})
    for t in sell_trades:
        mo = t["date"][:7]
        monthly[mo]["sells"] += 1
        monthly[mo]["pnl"] += t.get("pnl_dollars", 0)
        if t.get("pnl_pct", 0) > 0:
            monthly[mo]["wins"] += 1
    m["monthly"] = {
        mo: {"sells": d["sells"], "wins": d["wins"], "pnl": round(d["pnl"], 2),
             "win_rate": round(d["wins"] / d["sells"] * 100, 1) if d["sells"] else 0}
        for mo, d in sorted(monthly.items())
    }

    return m


def format_report(m, config_meta):
    """Generate markdown report."""
    lines = []
    lines.append("# Surgical Mean-Reversion Backtest Report\n")

    cfg = config_meta.get("config", {})
    dr = config_meta.get("date_range", {})
    lines.append(f"*Sim: {dr.get('sim_start', '?')} to {dr.get('end', '?')} | "
                 f"Tickers: {len(config_meta.get('tickers', []))} | "
                 f"Recompute: {cfg.get('recompute_levels', 'weekly')}*\n")

    # Summary
    lines.append("## Summary\n")
    lines.append("| Metric | Value |")
    lines.append("| :--- | :--- |")
    lines.append(f"| Total Buys | {m.get('total_buys', 0)} |")
    lines.append(f"| Completed Sells | {m.get('total_sells', 0)} |")
    lines.append(f"| Completed Cycles | {m.get('total_cycles', 0)} |")
    lines.append(f"| Win Rate | {m.get('win_rate', 0)}% |")
    lines.append(f"| Total P/L | ${m.get('total_pnl', 0):.2f} |")
    lines.append(f"| Avg P/L per Sell | {m.get('avg_pnl_pct', 0):+.2f}% |")
    lines.append(f"| Avg Hold Days | {m.get('avg_hold_days', 0)} |")
    lines.append(f"| Profit Factor | {m.get('profit_factor', 0)} |")
    if "sharpe" in m:
        lines.append(f"| Sharpe Ratio | {m['sharpe']} |")
    if "sortino" in m:
        lines.append(f"| Sortino Ratio | {m['sortino']} |")
    lines.append(f"| Max Drawdown | ${m.get('max_drawdown', 0):.2f} |")
    lines.append(f"| Final P/L | ${m.get('final_pnl', 0):.2f} |")
    lines.append("")

    # Exit reasons
    if "exit_reasons" in m:
        lines.append("## Exit Reasons\n")
        lines.append("| Reason | Count | Avg P/L% | Total P/L$ |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for reason in ["PROFIT_TARGET", "TIME_STOP", "CATASTROPHIC_EXIT",
                       "SAME_DAY_EXIT", "SIM_END"]:
            if reason in m["exit_reasons"]:
                r = m["exit_reasons"][reason]
                lines.append(f"| {reason} | {r['count']} | {r['avg_pnl']:+.1f}% | ${r['total_pnl']:.2f} |")
        lines.append("")

    # Per-zone
    if "zone_stats" in m:
        lines.append("## Performance by Zone\n")
        lines.append("| Zone | Fills |")
        lines.append("| :--- | :--- |")
        for z in ["Active", "Buffer", "Reserve", "Unknown"]:
            if z in m["zone_stats"]:
                lines.append(f"| {z} | {m['zone_stats'][z]['fills']} |")
        lines.append("")

    # Per-regime
    if "regime_stats" in m:
        lines.append("## Performance by Regime\n")
        lines.append("| Regime | Sells | Win% | P/L$ |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for r in ["Risk-On", "Neutral", "Risk-Off"]:
            if r in m["regime_stats"]:
                rs = m["regime_stats"][r]
                lines.append(f"| {r} | {rs['sells']} | {rs['win_rate']}% | ${rs['pnl']:.2f} |")
        lines.append("")

    # Monthly
    if "monthly" in m:
        lines.append("## Monthly Breakdown\n")
        lines.append("| Month | Sells | Wins | Win% | P/L$ | Cumulative |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        cum = 0
        for mo, d in m["monthly"].items():
            cum += d["pnl"]
            lines.append(f"| {mo} | {d['sells']} | {d['wins']} | "
                        f"{d['win_rate']}% | ${d['pnl']:.2f} | ${cum:.2f} |")
        lines.append("")

    # Per-ticker
    if "per_ticker" in m:
        lines.append("## Per-Ticker Performance\n")
        lines.append("| Ticker | Buys | Sells | Cycles | Win% | P/L$ |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for tk, d in m["per_ticker"].items():
            lines.append(f"| {tk} | {d['buys']} | {d['sells']} | {d['cycles']} | "
                        f"{d['win_rate']}% | ${d['pnl']:.2f} |")
        lines.append("")

    return "\n".join(lines)


def main():
    import argparse
    p = argparse.ArgumentParser(description="Surgical Backtest Reporter")
    p.add_argument("--data-dir", required=True)
    p.add_argument("--csv", action="store_true")
    args = p.parse_args()

    results = load_results(args.data_dir)
    if "trades.json" not in results:
        print("*Error: trades.json not found*")
        sys.exit(1)

    trades = results["trades.json"]
    cycles = results.get("cycles.json", [])
    equity_curve = results.get("equity_curve.json", [])
    config_meta = results.get("config.json", {})

    metrics = compute_metrics(trades, cycles, equity_curve, config_meta)
    report = format_report(metrics, config_meta)

    out_dir = Path(args.data_dir)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    with open(out_dir / "summary.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)

    print(f"Wrote report.md and summary.json to {out_dir}/")
    print(report)

    if args.csv:
        csv_path = out_dir / "trades.csv"
        with open(csv_path, "w", newline="") as f:
            if trades:
                writer = csv.DictWriter(f, fieldnames=list(trades[0].keys()))
                writer.writeheader()
                writer.writerows(trades)
        print(f"Wrote {csv_path}")


if __name__ == "__main__":
    main()
