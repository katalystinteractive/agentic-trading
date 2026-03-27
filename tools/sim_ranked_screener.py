"""Simulation-Ranked Screener — replaces scoring-based candidate selection.

Flow:
1. Load universe screen passers (pre-filtered by swing/vol/consistency gates)
2. Select top N by swing × volume (proxy for tradability)
3. Run backtest simulation on each ticker individually
4. Rank by simulated P/L
5. Apply gate thresholds
6. Output ranked candidates with simulation metrics

Usage:
    python3 tools/sim_ranked_screener.py                     # top 30 passers
    python3 tools/sim_ranked_screener.py --top 50            # top 50
    python3 tools/sim_ranked_screener.py --months 6          # shorter sim
    python3 tools/sim_ranked_screener.py --min-swing 25      # tighter gate
"""
import sys
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).resolve().parent))

_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = _ROOT / "data" / "universe_screen_cache.json"
RESULTS_DIR = _ROOT / "data" / "backtest" / "sim-ranked"


def _fresh_swing(ticker):
    """Compute fresh median monthly swing from live yfinance data."""
    import yfinance as yf
    import numpy as np
    try:
        hist = yf.Ticker(ticker).history(period="13mo")
        if hist.empty or len(hist) < 60:
            return None
        monthly = hist.resample("ME").agg({"High": "max", "Low": "min"}).dropna()
        if len(monthly) > 1:
            monthly = monthly.iloc[:-1]
        if len(monthly) < 3:
            return None
        swings = ((monthly["High"] - monthly["Low"]) / monthly["Low"] * 100).values
        return float(np.median(swings))
    except Exception:
        return None


def load_passers(min_swing=25, min_vol=1_000_000):
    """Load universe passers with tightened gates."""
    with open(CACHE_PATH) as f:
        cache = json.load(f)

    passers = cache.get("passers", [])

    # Apply tightened gates from CACHE (initial filter)
    filtered = [
        p for p in passers
        if p.get("median_swing", 0) >= min_swing
        and p.get("avg_vol", 0) >= min_vol
    ]

    # Sort by swing × volume (tradability proxy — not a performance predictor,
    # just determines which tickers to simulate first)
    for p in filtered:
        p["tradability"] = p["median_swing"] * p["avg_vol"] / 1e6

    filtered.sort(key=lambda x: x["tradability"], reverse=True)
    return filtered


def simulate_one(ticker, months, results_dir):
    """Run simulation on a single ticker. Returns metrics dict."""
    import warnings
    warnings.filterwarnings("ignore")

    try:
        from candidate_sim_gate import simulate_candidate, apply_gate
        result = simulate_candidate(ticker, months=months)
        result = apply_gate(result)
        return result
    except Exception as e:
        return {
            "ticker": ticker, "passed": False,
            "reason": f"Error: {e}", "pnl": 0, "win_rate": 0,
            "sharpe": 0, "conversion": 0, "catastrophic": 0,
            "cycles": 0, "buys": 0, "sells": 0,
        }


def main():
    import argparse
    p = argparse.ArgumentParser(description="Simulation-Ranked Screener")
    p.add_argument("--top", type=int, default=30, help="Top N passers to simulate")
    p.add_argument("--months", type=int, default=10, help="Simulation months")
    p.add_argument("--min-swing", type=float, default=25, help="Min monthly swing %")
    p.add_argument("--min-vol", type=float, default=1_000_000, help="Min avg volume")
    p.add_argument("--exclude", nargs="*", type=str.upper, default=[],
                   help="Tickers to exclude (already in watchlist)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    # Load existing watchlist to exclude
    try:
        with open(_ROOT / "portfolio.json") as f:
            portfolio = json.load(f)
        watchlist = set(portfolio.get("watchlist", []))
        watchlist.update(portfolio.get("positions", {}).keys())
    except Exception:
        watchlist = set()

    exclude = set(args.exclude) | watchlist

    # Load and filter passers
    passers = load_passers(min_swing=args.min_swing, min_vol=args.min_vol)
    candidates = [p for p in passers if p["ticker"] not in exclude]

    print(f"## Simulation-Ranked Screener\n")
    print(f"*Gates: swing >= {args.min_swing}%, vol >= {args.min_vol/1e6:.0f}M*")
    print(f"*Passers: {len(passers)} total, {len(candidates)} after excluding watchlist*")
    print(f"*Simulating top {min(args.top, len(candidates))} by tradability over {args.months} months*\n")

    to_simulate_raw = candidates[:args.top]

    # FRESH VALIDATION: re-check swing from live data before simulating.
    # Cache can be stale — real money is on the line.
    print(f"Validating swing from fresh data...")
    to_simulate = []
    for passer in to_simulate_raw:
        tk = passer["ticker"]
        fresh = _fresh_swing(tk)
        if fresh is None:
            print(f"  {tk}: skipped (no fresh data)")
            continue
        if fresh < args.min_swing:
            print(f"  {tk}: REJECTED (fresh swing {fresh:.1f}% < {args.min_swing}%, cache had {passer['median_swing']:.1f}%)")
            continue
        passer["fresh_swing"] = round(fresh, 1)
        to_simulate.append(passer)
    print(f"  {len(to_simulate)}/{len(to_simulate_raw)} passed fresh validation\n")

    # Run simulations sequentially (wick analysis is not thread-safe with yfinance)
    results = []
    start_time = time.time()
    for i, passer in enumerate(to_simulate, 1):
        tk = passer["ticker"]
        sw = passer["median_swing"]
        vol = passer["avg_vol"] / 1e6
        print(f"[{i}/{len(to_simulate)}] {tk} (swing={sw:.0f}%, vol={vol:.1f}M)...", end=" ", flush=True)

        result = simulate_one(tk, args.months, RESULTS_DIR)
        result["screener_swing"] = round(sw, 1)
        result["screener_vol"] = round(vol, 1)
        results.append(result)

        status = "PASS" if result.get("passed") else "FAIL"
        print(f"{status} ${result.get('pnl', 0):.0f} | {result.get('win_rate', 0)}% win | "
              f"Sharpe {result.get('sharpe', 0)} | {result.get('cycles', 0)} cycles")

    elapsed = time.time() - start_time
    print(f"\n*Completed {len(results)} simulations in {elapsed/60:.1f} minutes*\n")

    # Rank by simulation P/L
    results.sort(key=lambda x: x.get("pnl", 0), reverse=True)
    passed = [r for r in results if r.get("passed")]
    failed = [r for r in results if not r.get("passed")]

    # Results table
    print("## Simulation Rankings\n")
    print("| # | Ticker | Swing | P/L | Win% | Sharpe | Conv% | Cycles | SDE% | Gate |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for i, r in enumerate(results, 1):
        gate = "**PASS**" if r.get("passed") else "FAIL"
        print(f"| {i} | {r['ticker']} | {r.get('screener_swing', 0)}% | "
              f"${r.get('pnl', 0):.2f} | {r.get('win_rate', 0)}% | "
              f"{r.get('sharpe', 0)} | {r.get('conversion', 0)}% | "
              f"{r.get('cycles', 0)} | {r.get('sde_rate', 0)}% | {gate} |")

    print(f"\n**{len(passed)} PASSED, {len(failed)} FAILED out of {len(results)} simulated**")

    if passed:
        print(f"\n## Top 10 Recommended for Onboarding\n")
        print("| # | Ticker | Sim P/L | Sharpe | Cycles | Action |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for i, r in enumerate(passed[:10], 1):
            print(f"| {i} | **{r['ticker']}** | **${r['pnl']:.2f}** | "
                  f"{r['sharpe']} | {r['cycles']} | Onboard |")

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "sim-ranked-results.json"
    with open(out_path, "w") as f:
        json.dump({
            "generated": datetime.now().isoformat(),
            "config": {
                "min_swing": args.min_swing, "min_vol": args.min_vol,
                "top_n": args.top, "months": args.months,
                "excluded": list(exclude),
            },
            "results": results,
            "passed": [r["ticker"] for r in passed],
            "failed": [r["ticker"] for r in failed],
        }, f, indent=2, default=str)

    md_path = RESULTS_DIR / "sim-ranked-results.md"
    lines = [
        f"# Simulation-Ranked Screening Results\n",
        f"*Generated: {datetime.now().isoformat()}*",
        f"*{len(passed)} passed / {len(results)} simulated / {args.months} months*\n",
        "| # | Ticker | P/L | Win% | Sharpe | Conv% | Cycles | Gate |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for i, r in enumerate(results, 1):
        gate = "PASS" if r.get("passed") else "FAIL"
        lines.append(f"| {i} | {r['ticker']} | ${r.get('pnl',0):.2f} | "
                     f"{r.get('win_rate',0)}% | {r.get('sharpe',0)} | "
                     f"{r.get('conversion',0)}% | {r.get('cycles',0)} | {gate} |")
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"\nSaved: {out_path}")
    print(f"Saved: {md_path}")


if __name__ == "__main__":
    main()
