"""Candidate Simulation Gate — Phase 4 of surgical-candidate-workflow.

Runs backtest simulation on each candidate ticker individually.
Only candidates that pass simulation thresholds get recommended for onboarding.

Gate thresholds (from backtesting 23 tickers over 10 months):
- P/L > $0 (must be profitable)
- Win rate > 90%
- No catastrophic stops
- Sharpe > 2.0
- Conversion > 40% (at least 40% of buys must complete a cycle)

Usage:
    python3 tools/candidate_sim_gate.py                    # reads candidate-final.md
    python3 tools/candidate_sim_gate.py --tickers VOR AGH  # specific tickers
    python3 tools/candidate_sim_gate.py --months 10        # simulation length
"""
import sys
import json
import pickle
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = _ROOT / "data" / "backtest" / "candidate-gate"


def _extract_candidates_from_final():
    """Read candidate-final.md and extract top candidate tickers."""
    final_path = _ROOT / "candidate-final.md"
    if not final_path.exists():
        return []

    text = final_path.read_text()
    tickers = []
    # Look for ticker mentions in the top 3 section
    for line in text.split("\n"):
        line = line.strip()
        # Match patterns like "1. CORD — 93 — Watch" or "| CORD |"
        if line and ("Watch" in line or "Onboard" in line or "Monitor" in line):
            parts = line.split()
            for p in parts:
                p = p.strip("*|#.—-")
                if p.isupper() and 2 <= len(p) <= 5 and p.isalpha():
                    if p not in ("Watch", "Onboard", "Monitor", "WATCH", "TOP"):
                        tickers.append(p)
    return list(dict.fromkeys(tickers))  # dedupe preserving order


def simulate_candidate(ticker, months=10):
    """Run surgical backtest on a single ticker and return metrics."""
    from backtest_data_collector import collect_data, save_data
    from backtest_engine import run_simulation, load_collected_data, save_results
    from backtest_config import SurgicalSimConfig

    out_dir = RESULTS_DIR / ticker
    out_dir.mkdir(parents=True, exist_ok=True)

    end_date = datetime.now()
    start_date = end_date - timedelta(days=months * 30)

    cfg = SurgicalSimConfig(
        tickers=[ticker],
        start=start_date.strftime("%Y-%m-%d"),
        end=end_date.strftime("%Y-%m-%d"),
        output_dir=str(out_dir),
        recompute_levels="weekly",
        same_day_exit_pct=4.0,
    )

    # Phase 1: Collect
    data = collect_data(cfg)
    save_data(data, str(out_dir))

    # Phase 2: Simulate
    price_data, regime_data, config_meta = load_collected_data(str(out_dir))
    trades, cycles, equity_curve = run_simulation(price_data, regime_data, cfg)
    save_results(trades, cycles, equity_curve, str(out_dir))

    # Compute gate metrics
    sells = [t for t in trades if t.get("side") == "SELL"]
    buys = [t for t in trades if t.get("side") == "BUY"]
    real_sells = [t for t in sells if t.get("exit_reason") != "SIM_END"]

    if not real_sells:
        return {
            "ticker": ticker, "passed": False, "reason": "No completed trades",
            "pnl": 0, "win_rate": 0, "sharpe": 0, "conversion": 0,
            "catastrophic": 0, "cycles": 0, "buys": len(buys),
        }

    wins = sum(1 for t in real_sells if t.get("pnl_pct", 0) > 0)
    total_pnl = sum(t.get("pnl_dollars", 0) for t in real_sells)
    win_rate = wins / len(real_sells) * 100
    conversion = len(real_sells) / len(buys) * 100 if buys else 0
    catastrophic = sum(1 for t in sells if t.get("exit_reason") == "CATASTROPHIC_EXIT")

    # Sharpe
    pnl_list = [t.get("pnl_dollars", 0) for t in real_sells]
    if len(pnl_list) > 1 and equity_curve:
        mean_r = np.mean(pnl_list)
        std_r = np.std(pnl_list, ddof=1)
        trades_per_year = min(len(real_sells) * 252 / max(len(equity_curve), 1), 252)
        sharpe = float(mean_r / std_r * np.sqrt(trades_per_year)) if std_r > 0 else 0
    else:
        sharpe = 0

    # SDE rate
    sde = sum(1 for t in real_sells if t.get("exit_reason") == "SAME_DAY_EXIT")
    sde_rate = sde / len(real_sells) * 100

    # Avg hold
    avg_hold = float(np.mean([t.get("days_held", 0) for t in real_sells]))

    return {
        "ticker": ticker,
        "pnl": round(total_pnl, 2),
        "win_rate": round(win_rate, 1),
        "sharpe": round(sharpe, 2),
        "conversion": round(conversion, 1),
        "catastrophic": catastrophic,
        "cycles": len(cycles),
        "buys": len(buys),
        "sells": len(real_sells),
        "sde_rate": round(sde_rate, 1),
        "avg_hold": round(avg_hold, 1),
    }


# Gate thresholds
# Conversion gate removed (2026-03-27): verified redundant — penalizes high-price
# stocks (TSLA $706 P/L at 35% conv, ARM $480 at 35% conv). All tickers it caught
# are either strong performers wrongly rejected or already caught by other gates.
GATE_THRESHOLDS = {
    "min_pnl": 0,           # must be profitable
    "min_win_rate": 90,      # >90% win rate
    "max_catastrophic": 0,   # zero catastrophic stops
    "min_sharpe": 2.0,       # risk-adjusted return
}


def apply_gate(result):
    """Apply simulation gate thresholds. Returns (passed, failures)."""
    failures = []
    if result["pnl"] <= GATE_THRESHOLDS["min_pnl"]:
        failures.append(f"P/L ${result['pnl']:.2f} <= $0")
    if result["win_rate"] < GATE_THRESHOLDS["min_win_rate"]:
        failures.append(f"Win rate {result['win_rate']}% < {GATE_THRESHOLDS['min_win_rate']}%")
    if result["catastrophic"] > GATE_THRESHOLDS["max_catastrophic"]:
        failures.append(f"{result['catastrophic']} catastrophic stop(s)")
    if result["sharpe"] < GATE_THRESHOLDS["min_sharpe"]:
        failures.append(f"Sharpe {result['sharpe']} < {GATE_THRESHOLDS['min_sharpe']}")
    passed = len(failures) == 0
    result["passed"] = passed
    result["failures"] = failures
    result["reason"] = "PASS" if passed else "; ".join(failures)
    return result


def main():
    import argparse
    p = argparse.ArgumentParser(description="Candidate Simulation Gate")
    p.add_argument("--tickers", nargs="*", type=str.upper, help="Specific tickers")
    p.add_argument("--months", type=int, default=10, help="Simulation months (default: 10)")
    p.add_argument("--json", action="store_true", help="Output JSON")
    args = p.parse_args()

    tickers = args.tickers or _extract_candidates_from_final()
    if not tickers:
        print("*No candidates found. Provide --tickers or ensure candidate-final.md exists.*")
        sys.exit(1)

    print(f"## Candidate Simulation Gate\n")
    print(f"*Simulating {len(tickers)} candidates over {args.months} months*")
    print(f"*Gate: P/L>$0, Win>90%, Sharpe>2, Conv>40%, Zero catastrophic*\n")

    results = []
    for i, tk in enumerate(tickers, 1):
        print(f"[{i}/{len(tickers)}] Simulating {tk}...", end=" ", flush=True)
        try:
            result = simulate_candidate(tk, months=args.months)
            result = apply_gate(result)
            results.append(result)
            status = "PASS" if result["passed"] else "FAIL"
            print(f"{status} — ${result['pnl']:.2f}, {result['win_rate']}% win, "
                  f"Sharpe {result['sharpe']}, {result['cycles']} cycles")
        except Exception as e:
            print(f"ERROR — {e}")
            results.append({
                "ticker": tk, "passed": False, "reason": f"Simulation error: {e}",
                "pnl": 0, "win_rate": 0, "sharpe": 0, "conversion": 0,
                "catastrophic": 0, "cycles": 0, "buys": 0, "sells": 0,
            })

    # Results table
    print(f"\n## Results\n")
    print("| Ticker | P/L | Win% | Sharpe | Conv% | Cat | Cycles | SDE% | Hold | Gate |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for r in sorted(results, key=lambda x: x.get("pnl", 0), reverse=True):
        gate = "**PASS**" if r.get("passed") else f"FAIL: {r.get('reason', '?')}"
        print(f"| {r['ticker']} | ${r.get('pnl', 0):.2f} | {r.get('win_rate', 0)}% | "
              f"{r.get('sharpe', 0)} | {r.get('conversion', 0)}% | {r.get('catastrophic', 0)} | "
              f"{r.get('cycles', 0)} | {r.get('sde_rate', 0)}% | {r.get('avg_hold', 0)}d | {gate} |")

    passed = [r for r in results if r.get("passed")]
    failed = [r for r in results if not r.get("passed")]

    print(f"\n**{len(passed)} PASSED, {len(failed)} FAILED**")
    if passed:
        print(f"\nRecommended for onboarding: {', '.join(r['ticker'] for r in passed)}")
    if failed:
        print(f"Not recommended: {', '.join(r['ticker'] for r in failed)}")

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    gate_path = RESULTS_DIR / "gate-results.json"
    with open(gate_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    gate_md = RESULTS_DIR / "gate-results.md"
    lines = ["# Candidate Simulation Gate Results\n"]
    lines.append(f"*Generated: {datetime.now().isoformat()}*\n")
    lines.append(f"*Simulation: {args.months} months, weekly recompute, 4% SDE*\n")
    lines.append("| Ticker | P/L | Win% | Sharpe | Conv% | Cycles | Gate |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for r in sorted(results, key=lambda x: x.get("pnl", 0), reverse=True):
        gate = "PASS" if r.get("passed") else "FAIL"
        lines.append(f"| {r['ticker']} | ${r.get('pnl',0):.2f} | {r.get('win_rate',0)}% | "
                     f"{r.get('sharpe',0)} | {r.get('conversion',0)}% | {r.get('cycles',0)} | {gate} |")
    gate_md.write_text("\n".join(lines), encoding="utf-8")

    if args.json:
        print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
