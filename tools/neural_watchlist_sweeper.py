"""Neural Watchlist Sweeper — guaranteed profiles for every tracked ticker.

Runs support parameter sweep on ALL tickers in portfolio.json positions +
watchlist. Ensures no ticker falls back to 'standard 6.0%' in the daily analyzer.

Usage:
    python3 tools/neural_watchlist_sweeper.py              # full sweep
    python3 tools/neural_watchlist_sweeper.py --workers 4   # parallel
    python3 tools/neural_watchlist_sweeper.py --dry-run      # no file writes
"""
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent))

from support_parameter_sweeper import (
    sweep_threshold, sweep_execution, extract_support_features,
    _collect_once, SWEEP_PERIODS,
)

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"
WATCHLIST_PROFILES_PATH = _ROOT / "data" / "neural_watchlist_profiles.json"


def get_tracked_tickers():
    """Get ALL tickers the user has positions in or is watching."""
    try:
        with open(PORTFOLIO_PATH) as f:
            portfolio = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    tickers = set(portfolio.get("positions", {}).keys())
    tickers.update(portfolio.get("watchlist", []))
    return sorted(tickers)


def main():
    parser = argparse.ArgumentParser(description="Neural Watchlist Sweeper")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start = time.time()
    tickers = get_tracked_tickers()
    print(f"Neural Watchlist Sweeper — {date.today().isoformat()}")
    print(f"Tracked tickers: {len(tickers)}\n")

    if not tickers:
        print("*No tickers in portfolio. Nothing to sweep.*")
        return

    # Collect data for any ticker missing it
    print("Ensuring data collected for all tickers...")
    for tk in tickers:
        try:
            _collect_once(tk, max(SWEEP_PERIODS))
        except Exception as e:
            print(f"  {tk}: collection failed ({e})")

    # Sweep each ticker
    results = {}
    skipped = []

    if args.workers > 1 and len(tickers) > 1:
        from multiprocessing import Pool
        from support_parameter_sweeper import _sweep_threshold_worker

        worker_args = [(tk, 10) for tk in tickers]
        with Pool(processes=min(args.workers, len(tickers))) as pool:
            for tk, result_data in pool.map(_sweep_threshold_worker, worker_args):
                if result_data:
                    results[tk] = result_data
                    s = result_data["stats"]
                    p = result_data["params"]
                    comp = s.get("composite", 0)
                    print(f"  {tk}: sell={p['sell_default']}% "
                          f"P/L=${s['pnl']:.2f} composite=${comp:.1f}/mo",
                          flush=True)
                else:
                    skipped.append((tk, "no profitable combo"))
                    print(f"  {tk}: skipped (no profitable combo)", flush=True)

        # Stage 2: sequential execution sweep on profitable tickers
        if results:
            print(f"\n  Stage 2: Execution sweep on {len(results)} profitable tickers...")
            for tk in list(results.keys()):
                print(f"  Stage 2: {tk}...", end=" ", flush=True)
                try:
                    exec_params, exec_result = sweep_execution(tk, results[tk]["params"])
                    if exec_params:
                        results[tk]["params"] = exec_params
                        print(f"pool=${exec_params['active_pool']} "
                              f"bullets={exec_params['active_bullets_max']}", flush=True)
                    else:
                        print("no improvement", flush=True)
                except Exception:
                    print("error", flush=True)
    else:
        for i, tk in enumerate(tickers):
            print(f"  [{i+1}/{len(tickers)}] {tk}...", end=" ", flush=True)
            t0 = time.time()
            try:
                params, result, composite, periods = sweep_threshold(tk)
                if params and result:
                    # Stage 2: optimize pool/bullets with thresholds locked
                    try:
                        exec_params, exec_result = sweep_execution(tk, params)
                        if exec_params:
                            params = exec_params  # merged threshold + execution
                    except Exception:
                        pass  # Stage 2 failure is non-fatal

                    features = extract_support_features(tk, result)
                    results[tk] = {
                        "params": params,
                        "stats": {
                            "pnl": result.get("pnl", 0),
                            "win_rate": result.get("win_rate", 0),
                            "trades": result.get("sells", 0),
                            "cycles": result.get("cycles", 0),
                            "composite": composite,
                        },
                        "features": features,
                        "periods": periods,
                    }
                    pool_info = f" pool=${params.get('active_pool', '?')}" if 'active_pool' in params else ""
                    print(f"sell={params['sell_default']}% "
                          f"P/L=${result.get('pnl', 0):.2f} "
                          f"composite=${composite:.1f}/mo{pool_info} [{time.time()-t0:.0f}s]", flush=True)
                else:
                    skipped.append((tk, "no profitable combo"))
                    print(f"skipped (no profitable combo) [{time.time()-t0:.0f}s]", flush=True)
            except Exception as e:
                skipped.append((tk, str(e)))
                print(f"error: {e} [{time.time()-t0:.0f}s]", flush=True)

    # Report skipped
    if skipped:
        print(f"\nSkipped {len(skipped)} tickers:")
        for tk, reason in skipped:
            print(f"  {tk}: {reason}")

    # Build output
    candidates = []
    for tk in sorted(results.keys()):
        r = results[tk]
        candidates.append({
            "ticker": tk,
            "params": r["params"],
            "stats": r["stats"],
            "pnl": r["stats"].get("pnl", 0),
            "composite": r["stats"].get("composite", 0),
            "win_rate": r["stats"].get("win_rate", 0),
            "trades": r["stats"].get("trades", 0),
            "periods": r.get("periods"),
        })

    output = {
        "_meta": {
            "source": "neural_watchlist_sweeper.py",
            "updated": date.today().isoformat(),
            "tracked_tickers": len(tickers),
            "profiles_created": len(results),
            "skipped": len(skipped),
        },
        "candidates": candidates,
    }

    if args.dry_run:
        print(f"\n--- DRY RUN — would write {len(candidates)} profiles ---")
    else:
        with open(WATCHLIST_PROFILES_PATH, "w") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"\nWrote {len(candidates)} profiles to {WATCHLIST_PROFILES_PATH}")

    elapsed = time.time() - start
    print(f"Total time: {elapsed:.0f}s ({elapsed/60:.1f} min)")


if __name__ == "__main__":
    main()
