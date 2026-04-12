"""Resistance sell strategy parameter sweeper.

Sweeps resistance exit parameters with threshold + execution params locked
from prior support sweep. Produces per-ticker optimal resistance strategy.
Compares resistance vs flat exits and writes results to separate output file.

Usage:
    python3 tools/resistance_parameter_sweeper.py --ticker CIFR
    python3 tools/resistance_parameter_sweeper.py --workers 8
    python3 tools/resistance_parameter_sweeper.py --dry-run
"""
import sys
import json
import time
import argparse
import itertools
from pathlib import Path
from datetime import date
from multiprocessing import Pool

sys.path.insert(0, str(Path(__file__).resolve().parent))

from support_parameter_sweeper import (
    _simulate_with_config, _collect_once, _log_progress,
)
from multi_period_scorer import compute_composite

_ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = _ROOT / "data" / "resistance_sweep_results.json"
SUPPORT_RESULTS_PATH = _ROOT / "data" / "support_sweep_results.json"

SWEEP_PERIODS = [12, 6, 3, 1]

RESISTANCE_GRID = {
    "resistance_strategy": ["first", "best"],
    "min_reject_rate": [30, 50, 70],
    "min_resistance_approaches": [2, 3, 5],
    "resistance_fallback_pct": [4, 6, 8],
}
# 2 × 3 × 3 × 3 = 54 combos


# ---------------------------------------------------------------------------
# Sweep function
# ---------------------------------------------------------------------------

def sweep_resistance(ticker, base_params, months=10):
    """Sweep resistance exit strategy with threshold+execution locked.

    Uses multi-period composite scoring (12mo/6mo/3mo/1mo).

    Args:
        ticker: stock ticker
        base_params: dict with sell_default, cat_hard_stop, active_pool, etc.
                     from prior support sweep results
        months: ignored (uses SWEEP_PERIODS)

    Returns: (best_params, best_result, best_composite, best_periods)
    """
    data_dir = _collect_once(ticker, max(SWEEP_PERIODS))
    from backtest_engine import load_collected_data
    price_data, regime_data, _ = load_collected_data(data_dir)

    best_composite = 0  # require positive composite to accept
    best_params = None
    best_result = None
    best_periods = None
    sim_errors = 0
    quality = {"positive": 0, "negative": 0, "zero_trade": 0}

    # Build base overrides from prior support sweep
    base_overrides = {
        "sell_default": base_params.get("sell_default", 6.0),
        "sell_fast_cycler": base_params.get("sell_default", 6.0) + 2.0,
        "sell_exceptional": base_params.get("sell_default", 6.0) + 4.0,
        "cat_hard_stop": base_params.get("cat_hard_stop", 25),
        "cat_warning": max(base_params.get("cat_hard_stop", 25) - 10, 5),
        "sell_mode": "resistance",  # enable resistance exits
    }
    # Include execution params if available
    for k in ("active_pool", "reserve_pool", "active_bullets_max",
              "reserve_bullets_max", "tier_full", "tier_std"):
        if k in base_params:
            base_overrides[k] = base_params[k]

    combos = list(itertools.product(
        RESISTANCE_GRID["resistance_strategy"],
        RESISTANCE_GRID["min_reject_rate"],
        RESISTANCE_GRID["min_resistance_approaches"],
        RESISTANCE_GRID["resistance_fallback_pct"],
    ))
    total_combos = len(combos)

    for idx, (strategy, reject_rate, min_approaches, fallback_pct) in enumerate(combos):
        if (idx + 1) % 10 == 0 or idx == 0:
            _log_progress(f"{ticker}: resistance combo {idx+1}/{total_combos} "
                          f"— best: ${best_composite:.1f}/mo")

        overrides = {
            **base_overrides,
            "resistance_strategy": strategy,
            "min_reject_rate": reject_rate,
            "min_resistance_approaches": min_approaches,
            "resistance_fallback_pct": fallback_pct,
        }

        # Multi-period scoring
        results_by_period = {}
        last_result = None
        resistance_cache = {}  # shared across periods within same combo
        for period_months in SWEEP_PERIODS:
            period_wick_cache = {}
            try:
                result = _simulate_with_config(
                    ticker, period_months, overrides, data_dir,
                    price_data, regime_data, period_wick_cache,
                    resistance_cache)
                results_by_period[period_months] = {
                    "pnl": result.get("pnl", 0),
                    "cycles": result.get("cycles", 0),
                    "trades": result.get("sells", 0),
                    "win_rate": result.get("win_rate", 0),
                }
                last_result = result
            except Exception as e:
                results_by_period[period_months] = {"pnl": 0, "cycles": 0}
                sim_errors += 1
                if sim_errors <= 3:
                    _log_progress(f"{ticker}: sim error ({period_months}mo): "
                                  f"{type(e).__name__}: {e}")

        try:
            composite, _ = compute_composite(results_by_period)
        except Exception as e:
            composite = 0
            sim_errors += 1
            if sim_errors <= 3:
                _log_progress(f"{ticker}: composite error: {type(e).__name__}: {e}")

        # Quality tracking
        if last_result:
            if last_result.get("sells", 0) == 0:
                quality["zero_trade"] += 1
            elif last_result.get("pnl", 0) < 0:
                quality["negative"] += 1
            else:
                quality["positive"] += 1

        if composite > best_composite:
            best_composite = composite
            best_params = {
                "resistance_strategy": strategy,
                "min_reject_rate": reject_rate,
                "min_resistance_approaches": min_approaches,
                "resistance_fallback_pct": fallback_pct,
            }
            best_result = last_result
            best_periods = results_by_period

    if sim_errors > 0:
        _log_progress(f"{ticker}: {sim_errors} sim errors across {total_combos} combos")
    _log_progress(f"{ticker}: quality: {quality['positive']}+ "
                  f"{quality['negative']}- {quality['zero_trade']}∅")

    return best_params, best_result, best_composite, best_periods


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

def _sweep_resistance_worker(args):
    """Worker for parallel resistance sweep."""
    ticker, base_params, months = args
    try:
        best_params, best_result, composite, periods = sweep_resistance(
            ticker, base_params, months)
        if best_params:
            return ticker, {
                "params": best_params,
                "stats": {
                    "composite": round(composite, 2) if composite else 0,
                    "pnl": best_result.get("pnl", 0) if best_result else 0,
                    "trades": best_result.get("sells", 0) if best_result else 0,
                },
                "periods": periods,
            }
        return ticker, None
    except Exception:
        return ticker, None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Resistance Sell Strategy Sweeper")
    parser.add_argument("--ticker", type=str, default=None,
                        help="Sweep a single ticker")
    parser.add_argument("--top", type=int, default=30,
                        help="Number of tickers to sweep (default: 30)")
    parser.add_argument("--months", type=int, default=10,
                        help="Simulation months (default: 10)")
    parser.add_argument("--workers", type=int, default=1,
                        help="Parallel workers (default: 1)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show results without writing")
    parser.add_argument("--tickers-file", type=str, default=None,
                        help="JSON file with ticker list (overrides default pool)")
    parser.add_argument("--split", action="store_true",
                        help="Cross-validate: validate on last 30%% of months")
    args = parser.parse_args()

    start = time.time()

    val_months = 0
    if args.split:
        val_months = max(1, args.months - int(args.months * 0.7))
        print(f"Cross-validation: validate on last {val_months} months")

    # Load prior support sweep results (prerequisite)
    if not SUPPORT_RESULTS_PATH.exists():
        print("*Support sweep results not found. Run support_parameter_sweeper.py "
              "--stage both first.*")
        return

    with open(SUPPORT_RESULTS_PATH) as f:
        support_data = json.load(f)

    # Determine tickers
    if args.ticker:
        tickers = [args.ticker]
    elif args.tickers_file:
        try:
            with open(args.tickers_file) as f:
                _pool = json.load(f)
            tickers = [tk for tk in _pool if tk in support_data and not tk.startswith("_")]
        except (OSError, json.JSONDecodeError):
            tickers = []
    else:
        try:
            with open(_ROOT / "portfolio.json") as f:
                _portfolio = json.load(f)
            tracked = set(_portfolio.get("watchlist", [])) | set(_portfolio.get("positions", {}).keys())
        except (OSError, json.JSONDecodeError):
            tracked = set()
        tracked_with_data = [tk for tk in tracked if tk in support_data and not tk.startswith("_")]
        challengers = sorted(
            [(tk, d) for tk, d in support_data.items()
             if not tk.startswith("_") and tk not in tracked],
            key=lambda x: x[1].get("stats", {}).get("composite", 0), reverse=True)
        n_challengers = max(len(tracked_with_data) // 2, 10)
        tickers = tracked_with_data + [tk for tk, _ in challengers[:n_challengers]]

    total_combos = 1
    for v in RESISTANCE_GRID.values():
        total_combos *= len(v)

    print(f"Resistance Sell Strategy Sweeper — {date.today().isoformat()}")
    print(f"Combos: {total_combos} resistance × {len(SWEEP_PERIODS)} periods")
    print(f"Tickers: {len(tickers)}")
    print()

    results = {}

    if args.workers > 1 and len(tickers) > 1:
        worker_args = [(tk, support_data[tk]["params"], args.months)
                       for tk in tickers if tk in support_data]
        with Pool(processes=min(args.workers, len(worker_args))) as pool:
            for tk, result_data in pool.map(_sweep_resistance_worker, worker_args):
                if result_data:
                    results[tk] = result_data
                    print(f"  {tk}: strategy={result_data['params']['resistance_strategy']} "
                          f"reject>={result_data['params']['min_reject_rate']}% "
                          f"composite=${result_data['stats']['composite']:.1f}/mo",
                          flush=True)
                else:
                    print(f"  {tk}: no improvement over flat", flush=True)
    else:
        for i, tk in enumerate(tickers):
            if tk not in support_data or tk.startswith("_"):
                continue
            print(f"  [{i+1}/{len(tickers)}] {tk}...", end=" ", flush=True)
            t0 = time.time()
            best_params, best_result, composite, periods = sweep_resistance(
                tk, support_data[tk]["params"], args.months)
            if best_params:
                results[tk] = {
                    "params": best_params,
                    "stats": {
                        "composite": round(composite, 2) if composite else 0,
                        "pnl": best_result.get("pnl", 0) if best_result else 0,
                        "trades": best_result.get("sells", 0) if best_result else 0,
                    },
                    "periods": periods,
                }
                print(f"strategy={best_params['resistance_strategy']} "
                      f"reject>={best_params['min_reject_rate']}% "
                      f"composite=${composite:.1f}/mo [{time.time()-t0:.0f}s]",
                      flush=True)
            else:
                print(f"no improvement [{time.time()-t0:.0f}s]", flush=True)

    # Add vs_flat comparison
    for tk in results:
        flat_composite = support_data.get(tk, {}).get("stats", {}).get("composite", 0)
        res_composite = results[tk]["stats"]["composite"]
        improvement = ((res_composite - flat_composite) / flat_composite * 100
                       if flat_composite > 0 else 0)
        results[tk]["vs_flat"] = {
            "flat_composite": round(flat_composite, 2),
            "resistance_composite": round(res_composite, 2),
            "improvement_pct": round(improvement, 1),
            "winner": "resistance" if res_composite > flat_composite else "flat",
        }

    # Write results — MERGE into existing file (never overwrite other tickers)
    output = {}
    if RESULTS_PATH.exists():
        try:
            with open(RESULTS_PATH) as f:
                output = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    output["_meta"] = {
        "source": "resistance_parameter_sweeper.py",
        "updated": date.today().isoformat(),
        "combos": total_combos,
        "tickers_swept": len(tickers),
        "with_results": len(results),
    }
    for tk, r in results.items():
        output[tk] = r

    # Cross-validation
    if args.split and val_months > 0 and results:
        print(f"\nValidating on last {val_months} months...")
        for tk in list(results.keys()):
            sp = support_data.get(tk, {}).get("params", {})
            overrides = {
                "sell_default": sp.get("sell_default", 6.0),
                "sell_fast_cycler": sp.get("sell_default", 6.0) + 2.0,
                "sell_exceptional": sp.get("sell_default", 6.0) + 4.0,
                "cat_hard_stop": sp.get("cat_hard_stop", 25),
                "cat_warning": max(sp.get("cat_hard_stop", 25) - 10, 5),
                "sell_mode": "resistance",
                **results[tk]["params"],
            }
            try:
                val_result = _simulate_with_config(tk, val_months, overrides)
                results[tk]["cross_validation"] = {
                    "pnl": val_result.get("pnl", 0),
                    "trades": val_result.get("sells", 0),
                    "win_rate": val_result.get("win_rate", 0),
                }
                cv = results[tk]["cross_validation"]
                flag = " OVERFIT" if results[tk]["stats"].get("pnl", 0) > 0 and cv["pnl"] < 0 else ""
                print(f"  {tk}: val P/L=${cv['pnl']:.2f} ({cv['trades']}t){flag}", flush=True)
            except Exception:
                results[tk]["cross_validation"] = {"pnl": 0, "trades": 0, "win_rate": 0}

    if not args.dry_run and results:
        with open(RESULTS_PATH, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\nResults saved to {RESULTS_PATH}")

    # Summary table
    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"| Ticker | Strategy | Reject | Approaches | Fallback | $/mo | vs Flat |")
    print(f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for tk in sorted(results.keys(),
                     key=lambda t: results[t]["stats"]["composite"], reverse=True):
        r = results[tk]
        p = r["params"]
        vf = r["vs_flat"]
        print(f"| {tk} | {p['resistance_strategy']} | {p['min_reject_rate']}% | "
              f"{p['min_resistance_approaches']} | {p['resistance_fallback_pct']}% | "
              f"${r['stats']['composite']:.1f} | {vf['winner']} ({vf['improvement_pct']:+.1f}%) |")

    winners = sum(1 for r in results.values() if r["vs_flat"]["winner"] == "resistance")
    print(f"\nResistance wins: {winners}/{len(results)} tickers")
    print(f"Total time: {elapsed:.0f}s ({elapsed/60:.1f} min)")


if __name__ == "__main__":
    main()
