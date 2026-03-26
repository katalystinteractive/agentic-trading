"""Dip Simulator Analyzer — Phase 3 of dip-sim-workflow.

Reads simulation results and produces:
- Risk-adjusted metrics (Sharpe, Sortino, profit factor)
- Equity curve analysis (max drawdown, recovery time)
- Regime-filtered performance (Risk-On vs Risk-Off)
- PDT violation summary
- Buy-and-hold comparison
- Sensitivity sweep (if --sweep mode)
- Trade log CSV export

Usage:
    python3 tools/dip_sim_analyzer.py                             # analyze last run
    python3 tools/dip_sim_analyzer.py --output-dir dip-sim-results
"""
import sys
import json
import csv
import math
from datetime import date
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))

_ROOT = Path(__file__).resolve().parent.parent


def _load_results(output_dir):
    """Load simulation results from Phase 2 outputs."""
    base = Path(output_dir)
    results = {}
    for name in ["sim-data.json", "trades-raw.json", "daily-log.json",
                  "equity-curve-raw.json", "pdt-log.json"]:
        path = base / name
        if path.exists():
            with open(path) as f:
                results[name] = json.load(f)
    return results


def compute_metrics(trades, equity_curve, daily_log, sim_data):
    """Compute comprehensive analysis metrics from simulation results."""
    import numpy as np

    metrics = {}

    if not trades:
        return {"error": "No trades to analyze"}

    # --- Basic stats ---
    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    total_pnl = sum(t["pnl_dollars"] for t in trades)
    pnl_list = [t["pnl_pct"] for t in trades]
    dollar_list = [t["pnl_dollars"] for t in trades]

    metrics["total_trades"] = len(trades)
    metrics["wins"] = len(wins)
    metrics["losses"] = len(losses)
    metrics["win_rate"] = round(len(wins) / len(trades) * 100, 1) if trades else 0
    metrics["total_pnl"] = round(total_pnl, 2)
    metrics["avg_pnl_pct"] = round(float(np.mean(pnl_list)), 2)
    metrics["avg_hold_days"] = round(float(np.mean([t["days_held"] for t in trades])), 1)

    if wins:
        metrics["avg_win_pct"] = round(float(np.mean([t["pnl_pct"] for t in wins])), 2)
        metrics["avg_win_dollars"] = round(float(np.mean([t["pnl_dollars"] for t in wins])), 2)
    if losses:
        metrics["avg_loss_pct"] = round(float(np.mean([t["pnl_pct"] for t in losses])), 2)
        metrics["avg_loss_dollars"] = round(float(np.mean([t["pnl_dollars"] for t in losses])), 2)

    # --- Profit factor ---
    win_sum = sum(t["pnl_dollars"] for t in wins)
    loss_sum = abs(sum(t["pnl_dollars"] for t in losses))
    metrics["profit_factor"] = round(win_sum / loss_sum, 2) if loss_sum > 0 else float("inf")

    # --- Expectancy ---
    wr = len(wins) / len(trades) if trades else 0
    avg_win = np.mean([t["pnl_dollars"] for t in wins]) if wins else 0
    avg_loss = np.mean([t["pnl_dollars"] for t in losses]) if losses else 0
    metrics["expectancy"] = round(wr * avg_win + (1 - wr) * avg_loss, 2)

    # --- Risk-adjusted metrics ---
    if len(dollar_list) > 1:
        daily_returns = np.array(dollar_list)
        mean_ret = np.mean(daily_returns)
        std_ret = np.std(daily_returns, ddof=1)
        if std_ret > 0:
            # Annualize: assume ~250 trading days, ~1 trade per day average
            trades_per_year = min(len(trades) * 252 / max(len(equity_curve), 1), 252)
            metrics["sharpe_ratio"] = round(float(mean_ret / std_ret * math.sqrt(trades_per_year)), 2)
        else:
            metrics["sharpe_ratio"] = 0

        # Sortino: only downside deviation
        downside = daily_returns[daily_returns < 0]
        if len(downside) > 1:
            downside_std = np.std(downside, ddof=1)
            if downside_std > 0:
                metrics["sortino_ratio"] = round(float(mean_ret / downside_std * math.sqrt(trades_per_year)), 2)

    # --- Equity curve analysis ---
    if equity_curve:
        cum_pnls = [e["cumulative_pnl"] for e in equity_curve]
        peak = cum_pnls[0]
        max_dd = 0
        max_dd_start = None
        max_dd_trough = None
        current_dd_start = None

        for i, pnl in enumerate(cum_pnls):
            if pnl > peak:
                peak = pnl
                current_dd_start = None
            dd = pnl - peak
            if dd < max_dd:
                max_dd = dd
                max_dd_trough = equity_curve[i]["date"]
                max_dd_start = current_dd_start or equity_curve[i]["date"]
            if dd < 0 and current_dd_start is None:
                current_dd_start = equity_curve[i]["date"]

        metrics["max_drawdown_dollars"] = round(max_dd, 2)
        metrics["max_drawdown_start"] = max_dd_start
        metrics["max_drawdown_trough"] = max_dd_trough
        metrics["final_pnl"] = round(cum_pnls[-1], 2)
        metrics["peak_pnl"] = round(max(cum_pnls), 2)

    # --- Exit reason breakdown ---
    reasons = defaultdict(lambda: {"count": 0, "pnl_sum": 0.0, "pnl_list": []})
    for t in trades:
        r = t["exit_reason"]
        reasons[r]["count"] += 1
        reasons[r]["pnl_sum"] += t["pnl_dollars"]
        reasons[r]["pnl_list"].append(t["pnl_pct"])
    metrics["exit_reasons"] = {
        r: {
            "count": d["count"],
            "total_pnl": round(d["pnl_sum"], 2),
            "avg_pnl_pct": round(float(np.mean(d["pnl_list"])), 2),
        }
        for r, d in reasons.items()
    }

    # --- Signal distribution ---
    if daily_log:
        signals = defaultdict(int)
        for d in daily_log:
            sig = d.get("signal", "UNKNOWN")
            signals[sig] += 1
        metrics["signal_distribution"] = dict(signals)
        metrics["total_trading_days"] = len(daily_log)

    # --- Regime-filtered performance ---
    if daily_log and any(d.get("regime") for d in daily_log):
        regime_trades = defaultdict(list)
        regime_dates = {}
        for d in daily_log:
            regime_dates[str(d["date"])] = d.get("regime", "Neutral")
        for t in trades:
            entry_date = str(t["entry_date"])
            regime = regime_dates.get(entry_date, "Neutral")
            regime_trades[regime].append(t)

        metrics["regime_performance"] = {}
        for regime, rt in regime_trades.items():
            rw = sum(1 for t in rt if t["pnl_pct"] > 0)
            metrics["regime_performance"][regime] = {
                "trades": len(rt),
                "wins": rw,
                "win_rate": round(rw / len(rt) * 100, 1) if rt else 0,
                "total_pnl": round(sum(t["pnl_dollars"] for t in rt), 2),
                "avg_pnl": round(float(np.mean([t["pnl_pct"] for t in rt])), 2),
            }

    # --- Monthly breakdown ---
    monthly = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
    for t in trades:
        key = str(t["exit_date"])[:7]
        monthly[key]["trades"] += 1
        monthly[key]["pnl"] += t["pnl_dollars"]
        if t["pnl_pct"] > 0:
            monthly[key]["wins"] += 1
    metrics["monthly"] = {
        k: {"trades": v["trades"], "wins": v["wins"],
            "win_rate": round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else 0,
            "pnl": round(v["pnl"], 2)}
        for k, v in sorted(monthly.items())
    }

    # --- Per-ticker breakdown ---
    ticker_perf = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
    for t in trades:
        tk = t["ticker"]
        ticker_perf[tk]["trades"] += 1
        ticker_perf[tk]["pnl"] += t["pnl_dollars"]
        if t["pnl_pct"] > 0:
            ticker_perf[tk]["wins"] += 1
    metrics["per_ticker"] = {
        tk: {"trades": v["trades"], "wins": v["wins"],
             "win_rate": round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else 0,
             "pnl": round(v["pnl"], 2)}
        for tk, v in sorted(ticker_perf.items(), key=lambda x: x[1]["pnl"], reverse=True)
    }

    # --- Buy-and-hold comparison ---
    if sim_data and "buy_hold_baseline" in sim_data:
        bh = sim_data["buy_hold_baseline"]
        budget = sim_data.get("config", {}).get("budget", 100)
        bh_total = 0
        for tk, data in bh.items():
            bh_total += budget * data["return_pct"] / 100
        metrics["buy_hold_total_pnl"] = round(bh_total, 2)
        metrics["strategy_edge"] = round(total_pnl - bh_total, 2)

    return metrics


def format_report(metrics, pdt_log=None):
    """Format metrics as markdown report."""
    lines = []
    lines.append("# Dip Strategy Simulation Report\n")

    # Summary
    lines.append("## Summary Metrics\n")
    lines.append("| Metric | Value |")
    lines.append("| :--- | :--- |")
    lines.append(f"| Total Trades | {metrics.get('total_trades', 0)} |")
    lines.append(f"| Win Rate | {metrics.get('win_rate', 0)}% |")
    lines.append(f"| Total P/L | ${metrics.get('total_pnl', 0):.2f} |")
    lines.append(f"| Avg P/L per Trade | {metrics.get('avg_pnl_pct', 0):+.2f}% |")
    lines.append(f"| Profit Factor | {metrics.get('profit_factor', 0)} |")
    lines.append(f"| Expectancy | ${metrics.get('expectancy', 0):.2f}/trade |")
    if "sharpe_ratio" in metrics:
        lines.append(f"| Sharpe Ratio | {metrics['sharpe_ratio']} |")
    if "sortino_ratio" in metrics:
        lines.append(f"| Sortino Ratio | {metrics['sortino_ratio']} |")
    lines.append(f"| Max Drawdown | ${metrics.get('max_drawdown_dollars', 0):.2f} |")
    lines.append(f"| Final P/L | ${metrics.get('final_pnl', 0):.2f} |")
    lines.append("")

    # Buy-and-hold comparison
    if "buy_hold_total_pnl" in metrics:
        lines.append("## Strategy vs Buy & Hold\n")
        lines.append("| Strategy | Total P/L |")
        lines.append("| :--- | :--- |")
        lines.append(f"| Daily Dip | ${metrics['total_pnl']:.2f} |")
        lines.append(f"| Buy & Hold | ${metrics['buy_hold_total_pnl']:.2f} |")
        lines.append(f"| **Edge** | **${metrics['strategy_edge']:.2f}** |")
        lines.append("")

    # Exit reasons
    if "exit_reasons" in metrics:
        lines.append("## Exit Reasons\n")
        lines.append("| Reason | Count | Avg P/L% | Total P/L$ |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for reason in ["TARGET", "STOP_LOSS", "MAX_HOLD", "RISK_OFF_SKIP", "PDT_BLOCKED", "SIM_END"]:
            if reason in metrics["exit_reasons"]:
                r = metrics["exit_reasons"][reason]
                lines.append(f"| {reason} | {r['count']} | {r['avg_pnl_pct']:+.1f}% | ${r['total_pnl']:.2f} |")
        lines.append("")

    # Signal distribution
    if "signal_distribution" in metrics:
        lines.append("## Signal Distribution\n")
        lines.append("| Signal | Days | % |")
        lines.append("| :--- | :--- | :--- |")
        total_days = metrics.get("total_trading_days", 1)
        for sig in ["CONFIRMED", "MIXED", "STAY_OUT", "NO_DIP", "RISK_OFF_SKIP", "PDT_BLOCKED", "NO_DATA"]:
            count = metrics["signal_distribution"].get(sig, 0)
            if count:
                lines.append(f"| {sig} | {count} | {count / total_days * 100:.0f}% |")
        lines.append("")

    # Regime performance
    if "regime_performance" in metrics:
        lines.append("## Performance by Regime\n")
        lines.append("| Regime | Trades | Win% | Avg P/L% | Total P/L$ |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for regime in ["Neutral", "Risk-Off"]:
            if regime in metrics["regime_performance"]:
                r = metrics["regime_performance"][regime]
                lines.append(f"| {regime} | {r['trades']} | {r['win_rate']}% | {r['avg_pnl']:+.1f}% | ${r['total_pnl']:.2f} |")
        lines.append("")

    # Monthly
    if "monthly" in metrics:
        lines.append("## Monthly Breakdown\n")
        lines.append("| Month | Trades | Wins | Win% | P/L$ | Cumulative |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        cum = 0
        for month, m in metrics["monthly"].items():
            cum += m["pnl"]
            lines.append(f"| {month} | {m['trades']} | {m['wins']} | {m['win_rate']}% | ${m['pnl']:.2f} | ${cum:.2f} |")
        lines.append("")

    # Per-ticker
    if "per_ticker" in metrics:
        lines.append("## Per-Ticker Performance\n")
        lines.append("| Ticker | Trades | Wins | Win% | Total P/L$ |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for tk, s in metrics["per_ticker"].items():
            lines.append(f"| {tk} | {s['trades']} | {s['wins']} | {s['win_rate']}% | ${s['pnl']:.2f} |")
        lines.append("")

    # PDT violations
    if pdt_log:
        lines.append("## PDT Violations\n")
        lines.append("| Date | Trades in Window | Action |")
        lines.append("| :--- | :--- | :--- |")
        for p in pdt_log:
            lines.append(f"| {p['date']} | {p['trades_in_window']} | {p['action']} |")
        lines.append("")

    return "\n".join(lines)


def export_trades_csv(trades, output_path):
    """Export trade log as CSV."""
    if not trades:
        return
    fieldnames = ["ticker", "entry_date", "exit_date", "entry_price", "exit_price",
                  "shares", "pnl_pct", "pnl_dollars", "days_held", "exit_reason"]
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for t in trades:
            row = {k: str(v) if isinstance(v, date) else v for k, v in t.items()}
            writer.writerow(row)


def export_equity_csv(equity_curve, output_path):
    """Export equity curve as CSV."""
    if not equity_curve:
        return
    fieldnames = ["date", "cumulative_pnl", "day_pnl", "positions", "regime"]
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(equity_curve)


def main():
    """Analyze simulation results from Phase 2 outputs or run standalone."""
    import argparse
    parser = argparse.ArgumentParser(description="Dip Simulator Analyzer")
    parser.add_argument("--output-dir", default="dip-sim-results")
    parser.add_argument("--csv", action="store_true", help="Export trade log + equity curve as CSV")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    results = _load_results(out_dir)

    if "trades-raw.json" not in results:
        print("*Error: trades-raw.json not found. Run simulation first.*")
        sys.exit(1)

    trades = results["trades-raw.json"]
    daily_log = results.get("daily-log.json", [])
    equity_curve = results.get("equity-curve-raw.json", [])
    pdt_log = results.get("pdt-log.json", [])
    sim_data = results.get("sim-data.json")

    metrics = compute_metrics(trades, equity_curve, daily_log, sim_data)
    report = format_report(metrics, pdt_log)

    # Write outputs
    report_path = out_dir / "sim-report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"Wrote {report_path}")

    json_path = out_dir / "sim-report.json"
    with open(json_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print(f"Wrote {json_path}")

    if args.csv:
        trades_csv = out_dir / "trades.csv"
        export_trades_csv(trades, trades_csv)
        print(f"Wrote {trades_csv}")

        equity_csv = out_dir / "equity-curve.csv"
        export_equity_csv(equity_curve, equity_csv)
        print(f"Wrote {equity_csv}")

    # Print summary to stdout
    print(f"\n{report}")


if __name__ == "__main__":
    main()
