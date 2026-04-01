"""Bounce-derived sell strategy parameter sweeper.

Sweeps bounce exit parameters with threshold + execution params locked
from prior support sweep. Produces per-ticker optimal bounce strategy.
Compares bounce vs resistance vs flat exits.

Usage:
    python3 tools/bounce_parameter_sweeper.py --ticker STIM
    python3 tools/bounce_parameter_sweeper.py --workers 8
    python3 tools/bounce_parameter_sweeper.py --dry-run
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
RESULTS_PATH = _ROOT / "data" / "bounce_sweep_results.json"
SUPPORT_RESULTS_PATH = _ROOT / "data" / "support_sweep_results.json"
RESISTANCE_RESULTS_PATH = _ROOT / "data" / "resistance_sweep_results.json"

SWEEP_PERIODS = [12, 6, 3, 1]

BOUNCE_GRID = {
    "bounce_window_days": [2, 3, 5],
    "bounce_confidence_min": [0.2, 0.3, 0.5],
    "bounce_cap_prior_high": [True, False],
    "bounce_fallback_pct": [4, 6, 8],
}
# 3 × 3 × 2 × 3 = 54 combos


# ---------------------------------------------------------------------------
# Sweep function
# ---------------------------------------------------------------------------

def sweep_bounce(ticker, base_params, months=10):
    """Sweep bounce exit strategy with threshold+execution locked.

    Uses multi-period composite scoring (12mo/6mo/3mo/1mo).

    Returns: (best_params, best_result, best_composite, best_periods)
    """
    data_dir = _collect_once(ticker, max(SWEEP_PERIODS))
    from backtest_engine import load_collected_data
    price_data, regime_data, _ = load_collected_data(data_dir)

    best_composite = 0
    best_params = None
    best_result = None
    best_periods = None
    sim_errors = 0
    quality = {"positive": 0, "negative": 0, "zero_trade": 0}

    base_overrides = {
        "sell_default": base_params.get("sell_default", 6.0),
        "sell_fast_cycler": base_params.get("sell_default", 6.0) + 2.0,
        "sell_exceptional": base_params.get("sell_default", 6.0) + 4.0,
        "cat_hard_stop": base_params.get("cat_hard_stop", 25),
        "cat_warning": max(base_params.get("cat_hard_stop", 25) - 10, 5),
        "sell_mode": "bounce",
    }
    for k in ("active_pool", "reserve_pool", "active_bullets_max",
              "reserve_bullets_max", "tier_full", "tier_std"):
        if k in base_params:
            base_overrides[k] = base_params[k]

    combos = list(itertools.product(
        BOUNCE_GRID["bounce_window_days"],
        BOUNCE_GRID["bounce_confidence_min"],
        BOUNCE_GRID["bounce_cap_prior_high"],
        BOUNCE_GRID["bounce_fallback_pct"],
    ))
    total_combos = len(combos)

    for idx, (window, confidence, cap_ph, fallback) in enumerate(combos):
        if (idx + 1) % 10 == 0 or idx == 0:
            _log_progress(f"{ticker}: bounce combo {idx+1}/{total_combos} "
                          f"— best: ${best_composite:.1f}/mo")

        overrides = {
            **base_overrides,
            "bounce_window_days": window,
            "bounce_confidence_min": confidence,
            "bounce_cap_prior_high": cap_ph,
            "bounce_fallback_pct": fallback,
        }

        results_by_period = {}
        last_result = None
        bounce_cache = {}
        for period_months in SWEEP_PERIODS:
            period_wick_cache = {}
            try:
                result = _simulate_with_config(
                    ticker, period_months, overrides, data_dir,
                    price_data, regime_data, period_wick_cache,
                    resistance_cache=None, bounce_cache=bounce_cache)
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
                "bounce_window_days": window,
                "bounce_confidence_min": confidence,
                "bounce_cap_prior_high": cap_ph,
                "bounce_fallback_pct": fallback,
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

def _sweep_bounce_worker(args):
    """Worker for parallel bounce sweep."""
    ticker, base_params, months = args
    try:
        best_params, best_result, composite, periods = sweep_bounce(
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
    parser = argparse.ArgumentParser(description="Bounce Sell Strategy Sweeper")
    parser.add_argument("--ticker", type=str, default=None)
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--months", type=int, default=10)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start = time.time()

    if not SUPPORT_RESULTS_PATH.exists():
        print("*Support sweep results not found. Run support_parameter_sweeper.py "
              "--stage both first.*")
        return

    with open(SUPPORT_RESULTS_PATH) as f:
        support_data = json.load(f)

    # Load resistance results for 3-way comparison
    resistance_data = {}
    if RESISTANCE_RESULTS_PATH.exists():
        try:
            with open(RESISTANCE_RESULTS_PATH) as f:
                resistance_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    if args.ticker:
        tickers = [args.ticker]
    else:
        ranked = sorted(
            [(tk, d) for tk, d in support_data.items() if not tk.startswith("_")],
            key=lambda x: x[1].get("stats", {}).get("pnl", 0), reverse=True)
        tickers = [tk for tk, _ in ranked[:args.top]]

    total_combos = 1
    for v in BOUNCE_GRID.values():
        total_combos *= len(v)

    print(f"Bounce Sell Strategy Sweeper — {date.today().isoformat()}")
    print(f"Combos: {total_combos} bounce × {len(SWEEP_PERIODS)} periods")
    print(f"Tickers: {len(tickers)}")
    print()

    results = {}

    if args.workers > 1 and len(tickers) > 1:
        worker_args = [(tk, support_data[tk]["params"], args.months)
                       for tk in tickers if tk in support_data]
        with Pool(processes=min(args.workers, len(worker_args))) as pool:
            for tk, result_data in pool.map(_sweep_bounce_worker, worker_args):
                if result_data:
                    results[tk] = result_data
                    print(f"  {tk}: window={result_data['params']['bounce_window_days']}d "
                          f"conf>={result_data['params']['bounce_confidence_min']} "
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
            best_params, best_result, composite, periods = sweep_bounce(
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
                print(f"window={best_params['bounce_window_days']}d "
                      f"conf>={best_params['bounce_confidence_min']} "
                      f"composite=${composite:.1f}/mo [{time.time()-t0:.0f}s]",
                      flush=True)
            else:
                print(f"no improvement [{time.time()-t0:.0f}s]", flush=True)

    # 3-way comparison
    for tk in results:
        flat_comp = support_data.get(tk, {}).get("stats", {}).get("composite", 0)
        res_comp = resistance_data.get(tk, {}).get("stats", {}).get("composite", 0)
        bounce_comp = results[tk]["stats"]["composite"]
        best_of_three = max(flat_comp, res_comp, bounce_comp)
        if best_of_three == bounce_comp and bounce_comp > 0:
            winner = "bounce"
        elif best_of_three == res_comp and res_comp > 0:
            winner = "resistance"
        else:
            winner = "flat"
        results[tk]["vs_others"] = {
            "flat_composite": round(flat_comp, 2),
            "resistance_composite": round(res_comp, 2),
            "bounce_composite": round(bounce_comp, 2),
            "winner": winner,
        }

    # Merge into existing file (never overwrite other tickers)
    output = {}
    if RESULTS_PATH.exists():
        try:
            with open(RESULTS_PATH) as f:
                output = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    output["_meta"] = {
        "source": "bounce_parameter_sweeper.py",
        "updated": date.today().isoformat(),
        "combos": total_combos,
        "tickers_swept": len(tickers),
        "with_results": len(results),
    }
    for tk, r in results.items():
        output[tk] = r

    if not args.dry_run and results:
        with open(RESULTS_PATH, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\nResults saved to {RESULTS_PATH}")

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"| Ticker | Window | Confidence | Cap PH | Fallback | $/mo | Winner |")
    print(f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for tk in sorted(results.keys(),
                     key=lambda t: results[t]["stats"]["composite"], reverse=True):
        r = results[tk]
        p = r["params"]
        vf = r["vs_others"]
        print(f"| {tk} | {p['bounce_window_days']}d | {p['bounce_confidence_min']} | "
              f"{p['bounce_cap_prior_high']} | {p['bounce_fallback_pct']}% | "
              f"${r['stats']['composite']:.1f} | {vf['winner']} |")

    winners = {"bounce": 0, "resistance": 0, "flat": 0}
    for r in results.values():
        winners[r["vs_others"]["winner"]] += 1
    print(f"\nWinners: bounce={winners['bounce']}, "
          f"resistance={winners['resistance']}, flat={winners['flat']}")
    print(f"Total time: {elapsed:.0f}s ({elapsed/60:.1f} min)")


if __name__ == "__main__":
    main()
