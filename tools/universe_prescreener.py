"""Universe pre-screener — Stage 1 sweep across all universe passers.

Runs the threshold grid (30 combos x 4 periods = 120 sims per ticker)
for every ticker in data/universe_screen_cache.json. Produces composite
$/month scores using the same multi_period_scorer as the full sweeper.

Output: data/universe_prescreen_results.json (OWN FILE — never touches
existing sweep data that drives daily decisions).

Usage:
    python3 tools/universe_prescreener.py                    # full run
    python3 tools/universe_prescreener.py --workers 8        # parallel
    python3 tools/universe_prescreener.py --top 20           # show top N
    python3 tools/universe_prescreener.py --cached           # show cached results
"""
import sys
import json
import argparse
import time
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).resolve().parent))

from support_parameter_sweeper import (
    _collect_once, _simulate_with_config, THRESHOLD_GRID, SWEEP_PERIODS,
)
from multi_period_scorer import compute_composite

_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = _ROOT / "data" / "universe_screen_cache.json"
OUTPUT_PATH = _ROOT / "data" / "universe_prescreen_results.json"


def load_universe_tickers():
    """Load ticker symbols from universe screening cache."""
    if not CACHE_PATH.exists():
        print("*No universe cache. Run universe_screener.py first.*", file=sys.stderr)
        return []
    with open(CACHE_PATH) as f:
        cache = json.load(f)
    return [p["ticker"] for p in cache.get("passers", [])]


def prescreen_ticker(ticker):
    """Run Stage 1 (30 combos x 4 periods) for a single ticker.

    Uses shared wick cache across all 30 combos per period (fixes the
    per-combo cache reset in the current sweeper — ~6x speedup).

    Returns dict with ticker, composite, best_params, period_details,
    or None on failure.
    """
    try:
        data_dir = _collect_once(ticker, max(SWEEP_PERIODS))
        if data_dir is None:
            return None

        results_by_period = {}
        for months in SWEEP_PERIODS:
            wick_cache = {}  # shared across all 30 combos for this period
            best = {"pnl": float("-inf"), "params": None, "sells": 0,
                    "cycles": 0, "win_rate": 0}
            for sell_default in THRESHOLD_GRID["sell_default"]:
                for cat_hard in THRESHOLD_GRID["cat_hard_stop"]:
                    overrides = {
                        "sell_default": sell_default,
                        "cat_hard_stop": cat_hard,
                    }
                    result = _simulate_with_config(
                        ticker, months, overrides,
                        data_dir=data_dir, wick_cache=wick_cache,
                    )
                    if result and result.get("pnl", float("-inf")) > best["pnl"]:
                        best = {
                            "pnl": result["pnl"],
                            "params": overrides,
                            "sells": result.get("sells", 0),
                            "cycles": result.get("cycles", 0),
                            "win_rate": result.get("win_rate", 0),
                        }

            results_by_period[months] = best

        composite, details = compute_composite(results_by_period)
        if composite <= 0:
            return None

        return {
            "ticker": ticker,
            "composite": round(composite, 2),
            "best_params": best["params"],
            "sells_12mo": results_by_period.get(12, {}).get("sells", 0),
            "win_rate_12mo": results_by_period.get(12, {}).get("win_rate", 0),
        }
    except Exception:
        return None


def run_prescreen(tickers, workers=8):
    """Pre-screen all tickers in parallel. Returns ranked list."""
    results = []
    failed = 0
    total = len(tickers)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(prescreen_ticker, tk): tk for tk in tickers}
        done = 0
        for future in as_completed(futures):
            done += 1
            if done % 100 == 0:
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                eta = (total - done) / rate if rate > 0 else 0
                print(f"  Progress: {done}/{total} ({rate:.1f}/s, "
                      f"ETA {eta:.0f}s)", flush=True)
            try:
                r = future.result()
                if r:
                    results.append(r)
                else:
                    failed += 1
            except Exception:
                failed += 1

    elapsed = time.time() - t0
    print(f"  Completed: {len(results)} with signal, "
          f"{failed} failed/no-signal, {elapsed:.0f}s")

    return sorted(results, key=lambda x: -x["composite"])


def save_results(rankings):
    """Save pre-screen results to own file (no contamination)."""
    output = {
        "_meta": {
            "source": "universe_prescreener.py",
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "tickers_screened": len(rankings),
            "top_composite": rankings[0]["composite"] if rankings else 0,
        },
        "rankings": rankings,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"  Results saved to {OUTPUT_PATH}")


def print_top(rankings, n=20):
    """Print top N tickers by composite."""
    print(f"\n## Universe Pre-Screen — Top {min(n, len(rankings))}\n")
    print("| Rank | Ticker | Composite $/mo | Sells (12mo) | Win Rate | "
          "Best Sell% | Best Stop% |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for i, r in enumerate(rankings[:n], 1):
        bp = r.get("best_params") or {}
        print(f"| {i} | {r['ticker']} | ${r['composite']:.1f} | "
              f"{r.get('sells_12mo', '?')} | "
              f"{r.get('win_rate_12mo', 0):.0f}% | "
              f"{bp.get('sell_default', '?')}% | "
              f"{bp.get('cat_hard_stop', '?')}% |")


def main():
    parser = argparse.ArgumentParser(description="Universe Pre-Screener")
    parser.add_argument("--workers", type=int, default=8,
                        help="Parallel workers (default: 8)")
    parser.add_argument("--top", type=int, default=20,
                        help="Show top N results (default: 20)")
    parser.add_argument("--cached", action="store_true",
                        help="Show cached results without re-running")
    args = parser.parse_args()

    if args.cached:
        if not OUTPUT_PATH.exists():
            print("*No cached results. Run without --cached first.*")
            return
        with open(OUTPUT_PATH) as f:
            data = json.load(f)
        rankings = data.get("rankings", [])
        meta = data.get("_meta", {})
        print(f"Cached results from {meta.get('updated', 'unknown')}: "
              f"{meta.get('tickers_screened', '?')} tickers")
        print_top(rankings, args.top)
        return

    tickers = load_universe_tickers()
    if not tickers:
        return

    print(f"Pre-screening {len(tickers)} universe passers "
          f"with {args.workers} workers...")
    print(f"Grid: {len(THRESHOLD_GRID['sell_default'])} sell × "
          f"{len(THRESHOLD_GRID['cat_hard_stop'])} stop × "
          f"{len(SWEEP_PERIODS)} periods = "
          f"{len(THRESHOLD_GRID['sell_default']) * len(THRESHOLD_GRID['cat_hard_stop']) * len(SWEEP_PERIODS)} "
          f"sims/ticker\n")

    rankings = run_prescreen(tickers, workers=args.workers)
    save_results(rankings)
    print_top(rankings, args.top)


if __name__ == "__main__":
    main()
