"""Entry gate parameter sweeper — neural buy-side optimization.

Sweeps 6 entry gate parameters: recency-weighted offsets, regime-conditioned
entry, adaptive offsets, post-break cooldown, VIX gate, approach velocity.
All with threshold + execution params locked from prior support sweep.

Usage:
    python3 tools/entry_parameter_sweeper.py --ticker STIM
    python3 tools/entry_parameter_sweeper.py --workers 8
    python3 tools/entry_parameter_sweeper.py --dry-run
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
RESULTS_PATH = _ROOT / "data" / "entry_sweep_results.json"
SUPPORT_RESULTS_PATH = _ROOT / "data" / "support_sweep_results.json"

SWEEP_PERIODS = [12, 6, 3, 1]

ENTRY_GRID = {
    "offset_decay_half_life": [0, 60, 90],
    "post_break_cooldown": [0, 2, 5],
}
# 3 × 3 = 9 combos (regime/VIX/velocity gates showed 0/30 impact — removed)


def sweep_entry(ticker, base_params, months=10):
    """Sweep entry gate parameters with threshold+execution locked.

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
        "regime_aware_entry": True,  # enable regime gating
    }
    for k in ("active_pool", "reserve_pool", "active_bullets_max",
              "reserve_bullets_max", "tier_full", "tier_std"):
        if k in base_params:
            base_overrides[k] = base_params[k]

    combos = list(itertools.product(
        ENTRY_GRID["offset_decay_half_life"],
        ENTRY_GRID["post_break_cooldown"],
    ))
    total_combos = len(combos)

    # Ticker-scoped wick cache shared across all combos × periods.
    wick_cache = {}

    for idx, (decay, cooldown) in enumerate(combos):
        if (idx + 1) % 3 == 0 or idx == 0:
            _log_progress(f"{ticker}: entry combo {idx+1}/{total_combos} "
                          f"— best: ${best_composite:.1f}/mo")

        overrides = {
            **base_overrides,
            "offset_decay_half_life": decay,
            "post_break_cooldown": cooldown,
        }

        results_by_period = {}
        last_result = None
        for period_months in SWEEP_PERIODS:
            try:
                result = _simulate_with_config(
                    ticker, period_months, overrides, data_dir,
                    price_data, regime_data, wick_cache)
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
        except Exception:
            composite = 0

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
                "offset_decay_half_life": decay,
                "post_break_cooldown": cooldown,
            }
            best_result = last_result
            best_periods = results_by_period

    if sim_errors > 0:
        _log_progress(f"{ticker}: {sim_errors} sim errors across {total_combos} combos")
    _log_progress(f"{ticker}: quality: {quality['positive']}+ "
                  f"{quality['negative']}- {quality['zero_trade']}∅")

    return best_params, best_result, best_composite, best_periods


def _sweep_entry_worker(args):
    """Worker for parallel entry sweep."""
    ticker, base_params, months = args
    try:
        best_params, best_result, composite, periods = sweep_entry(
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


def main():
    parser = argparse.ArgumentParser(description="Entry Gate Parameter Sweeper")
    parser.add_argument("--ticker", type=str, default=None)
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--months", type=int, default=10)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
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
    for v in ENTRY_GRID.values():
        total_combos *= len(v)

    print(f"Entry Gate Parameter Sweeper — {date.today().isoformat()}")
    print(f"Combos: {total_combos} entry × {len(SWEEP_PERIODS)} periods")
    print(f"Tickers: {len(tickers)}")
    print()

    results = {}

    if args.workers > 1 and len(tickers) > 1:
        worker_args = [(tk, support_data[tk]["params"], args.months)
                       for tk in tickers if tk in support_data]
        with Pool(processes=min(args.workers, len(worker_args))) as pool:
            for tk, result_data in pool.map(_sweep_entry_worker, worker_args):
                if result_data:
                    results[tk] = result_data
                    p = result_data["params"]
                    print(f"  {tk}: decay={p['offset_decay_half_life']} "
                          f"cooldown={p['post_break_cooldown']} "
                          f"composite=${result_data['stats']['composite']:.1f}/mo",
                          flush=True)
                else:
                    print(f"  {tk}: no improvement", flush=True)
    else:
        for i, tk in enumerate(tickers):
            if tk not in support_data or tk.startswith("_"):
                continue
            print(f"  [{i+1}/{len(tickers)}] {tk}...", end=" ", flush=True)
            t0 = time.time()
            best_params, best_result, composite, periods = sweep_entry(
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
                print(f"decay={best_params['offset_decay_half_life']} "
                      f"cooldown={best_params['post_break_cooldown']} "
                      f"composite=${composite:.1f}/mo [{time.time()-t0:.0f}s]",
                      flush=True)
            else:
                print(f"no improvement [{time.time()-t0:.0f}s]", flush=True)

    # Merge into existing file
    output = {}
    if RESULTS_PATH.exists():
        try:
            with open(RESULTS_PATH) as f:
                output = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    output["_meta"] = {
        "source": "entry_parameter_sweeper.py",
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
                "regime_aware_entry": True,
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

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"| Ticker | Decay | Cooldown | $/mo |")
    print(f"| :--- | :--- | :--- | :--- |")
    for tk in sorted(results.keys(),
                     key=lambda t: results[t]["stats"]["composite"], reverse=True):
        r = results[tk]
        p = r["params"]
        print(f"| {tk} | {p['offset_decay_half_life']} | "
              f"{p['post_break_cooldown']} | "
              f"${r['stats']['composite']:.1f} |")

    print(f"\nTotal time: {elapsed:.0f}s ({elapsed/60:.1f} min)")


if __name__ == "__main__":
    main()
