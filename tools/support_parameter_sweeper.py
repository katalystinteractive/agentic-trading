"""Support Strategy Parameter Sweeper — find optimal thresholds + execution params.

Two-stage sweep using backtest_engine.py as the simulator:
  Stage 1: Sweep sell target + catastrophic stop (30 combos, ~36s/ticker)
  Stage 2: Sweep pool/bullets/tier on top N from Stage 1 (144 combos)

Usage:
    python3 tools/support_parameter_sweeper.py --ticker CIFR
    python3 tools/support_parameter_sweeper.py --top 30
    python3 tools/support_parameter_sweeper.py --top 30 --stage threshold
    python3 tools/support_parameter_sweeper.py --top 30 --stage execution
    python3 tools/support_parameter_sweeper.py --top 30 --split
    python3 tools/support_parameter_sweeper.py --top 30 --workers 8
"""
import sys
import json
import time
import argparse
import itertools
from pathlib import Path
from datetime import datetime, date
from collections import defaultdict
from multiprocessing import Pool
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

from multi_period_scorer import compute_composite

_ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = _ROOT / "data" / "support_sweep_results.json"
GATE_RESULTS_DIR = _ROOT / "data" / "backtest" / "candidate-gate"

SWEEP_PERIODS = [12, 6, 3, 1]  # multi-period simulation months


def _log_progress(msg):
    """Timestamped progress to stderr (keeps stdout clean for results)."""
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Sweep grids
# ---------------------------------------------------------------------------

THRESHOLD_GRID = {
    "sell_default": [4.0, 5.0, 6.0, 7.0, 8.0, 10.0],
    "cat_hard_stop": [15, 20, 25, 30, 40],
}

EXECUTION_GRID = {
    "active_pool": [200, 300, 500],
    "reserve_pool": [200, 300],
    "active_bullets_max": [3, 5, 7],
    "reserve_bullets_max": [2, 3],
    "tier_full": [40, 60],
    "tier_std": [20, 30],
}
# Reduced grid: 3×2×3×2×2×2 = 144 combos (vs 4800 full)

LEVEL_FILTER_GRID = {
    "min_hold_rate": [15, 30, 50, 60, 70],
    "min_touch_freq": [0, 0.5, 1.0, 2.0, 3.0],
    "skip_dormant": [False, True],
    "zone_filter": ["active", "all"],
}
# 5 × 5 × 2 × 2 = 100 combos per ticker


# ---------------------------------------------------------------------------
# Single-ticker sweep
# ---------------------------------------------------------------------------

def _collect_once(ticker, months):
    """Collect data once, return data dir. Skip if already collected."""
    from backtest_data_collector import collect_data, save_data
    from backtest_config import SurgicalSimConfig

    out_dir = GATE_RESULTS_DIR / ticker
    out_dir.mkdir(parents=True, exist_ok=True)

    # Skip collection if data exists and is recent
    price_pkl = out_dir / "price_data.pkl"
    if price_pkl.exists():
        import os
        age_hours = (time.time() - os.path.getmtime(price_pkl)) / 3600
        if age_hours < 24:
            return str(out_dir)

    from datetime import timedelta
    end_date = datetime.now()
    start_date = end_date - timedelta(days=months * 30)
    cfg = SurgicalSimConfig(
        tickers=[ticker],
        start=start_date.strftime("%Y-%m-%d"),
        end=end_date.strftime("%Y-%m-%d"),
        output_dir=str(out_dir),
    )
    data = collect_data(cfg)
    save_data(data, str(out_dir))
    return str(out_dir)


def _simulate_with_config(ticker, months, config_overrides, data_dir=None,
                          price_data=None, regime_data=None, wick_cache=None,
                          resistance_cache=None):
    """Run simulation with custom config on pre-collected data.

    For sweep efficiency: pass price_data/regime_data/wick_cache/resistance_cache
    to avoid reloading data and recomputing analysis across parameter combos.
    """
    import warnings
    warnings.filterwarnings("ignore")
    from backtest_engine import run_simulation, load_collected_data
    from backtest_config import SurgicalSimConfig
    from candidate_sim_gate import apply_gate

    if data_dir is None:
        data_dir = _collect_once(ticker, months)

    if price_data is None or regime_data is None:
        price_data, regime_data, _ = load_collected_data(data_dir)

    cfg = SurgicalSimConfig(**config_overrides)
    cfg.tickers = [ticker]
    cfg.output_dir = data_dir
    # Set simulation window based on period_months
    from datetime import timedelta
    end_date = datetime.now()
    start_date = end_date - timedelta(days=months * 30)
    cfg.start = start_date.strftime("%Y-%m-%d")
    cfg.end = end_date.strftime("%Y-%m-%d")

    trades, cycles, equity, dip = run_simulation(
        price_data, regime_data, cfg, wick_cache, resistance_cache)

    # Build result dict matching simulate_candidate output format
    sells = [t for t in trades if t.get("side", "").upper() == "SELL"
             and t.get("exit_reason") != "SIM_END"]
    buys = [t for t in trades if t.get("side", "").upper() == "BUY"]
    total_pnl = sum(t.get("pnl_dollars", 0) for t in sells)
    wins = sum(1 for t in sells if t.get("pnl_dollars", 0) > 0)
    n_sells = len(sells)

    catastrophic = sum(1 for t in sells
                       if "CATASTROPHIC" in str(t.get("exit_reason", "")))

    result = {
        "ticker": ticker,
        "pnl": round(total_pnl, 2),
        "win_rate": round(wins / n_sells * 100, 1) if n_sells else 0,
        "sells": n_sells,
        "buys": len(buys),
        "cycles": len(cycles),
        "catastrophic": catastrophic,
        "conversion": round(n_sells / len(buys) * 100, 1) if buys else 0,
        "sde_rate": 0,
        "trades_detail": trades,
        "sharpe": 0,
    }

    # Compute sharpe
    if n_sells > 1:
        pnl_arr = [t.get("pnl_dollars", 0) for t in sells]
        mean_pnl = np.mean(pnl_arr)
        std_pnl = np.std(pnl_arr, ddof=1)
        if std_pnl > 0:
            result["sharpe"] = round(mean_pnl / std_pnl * np.sqrt(252 / max(1, len(pnl_arr))), 2)

    result = apply_gate(result)
    return result


def sweep_threshold(ticker, months=10):
    """Stage 1: Sweep sell target + catastrophic stop across multi-period.

    Runs each combo across 4 periods (12/6/3/1mo), ranks by composite $/month.
    Loads data ONCE for longest period. Separate wick_cache per period.

    Returns: (best_params, best_result, best_composite, best_periods)
    """
    # Collect + load data once for longest period
    data_dir = _collect_once(ticker, max(SWEEP_PERIODS))
    from backtest_engine import load_collected_data
    price_data, regime_data, _ = load_collected_data(data_dir)

    best_composite = 0  # require positive composite to accept
    best_params = None
    best_result = None
    best_periods = None

    combos = list(itertools.product(
        THRESHOLD_GRID["sell_default"],
        THRESHOLD_GRID["cat_hard_stop"],
    ))
    total_combos = len(combos)
    sim_errors = 0
    quality = {"positive": 0, "negative": 0, "zero_trade": 0}

    for idx, (sell_target, cat_stop) in enumerate(combos):
        if (idx + 1) % 10 == 0 or idx == 0:
            _log_progress(f"threshold combo {idx+1}/{total_combos} — best: ${best_composite:.1f}/mo")

        overrides = {
            "sell_default": sell_target,
            "sell_fast_cycler": sell_target + 2.0,
            "sell_exceptional": sell_target + 4.0,
            "cat_hard_stop": cat_stop,
            "cat_warning": max(cat_stop - 10, 5),
        }

        # Run each period with isolated wick_cache
        results_by_period = {}
        last_result = None
        for period_months in SWEEP_PERIODS:
            period_wick_cache = {}
            try:
                result = _simulate_with_config(
                    ticker, period_months, overrides, data_dir,
                    price_data, regime_data, period_wick_cache)
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
                    _log_progress(f"sim error ({period_months}mo): {type(e).__name__}: {e}")

        # Compute composite $/month
        try:
            composite, _ = compute_composite(results_by_period)
        except Exception as e:
            composite = 0
            sim_errors += 1
            if sim_errors <= 3:
                _log_progress(f"composite error: {type(e).__name__}: {e}")

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
                "sell_default": sell_target,
                "cat_hard_stop": cat_stop,
            }
            best_result = last_result
            best_periods = results_by_period

    if sim_errors > 0:
        _log_progress(f"{sim_errors} sim errors across {total_combos} combos")
    _log_progress(f"quality: {quality['positive']}+ {quality['negative']}- {quality['zero_trade']}∅")

    return best_params, best_result, best_composite, best_periods


def sweep_execution(ticker, threshold_params, months=10):
    """Stage 2: Sweep pool/bullets/tier with thresholds locked.

    Groups combos by (pool, bullets) to share wick_cache within each group.
    """
    data_dir = _collect_once(ticker, months)
    from backtest_engine import load_collected_data
    price_data, regime_data, _ = load_collected_data(data_dir)

    best_pnl = 0  # require positive P/L to accept
    best_params = None
    best_result = None
    combo_idx = 0
    sim_errors = 0
    total_exec_combos = 1
    for v in EXECUTION_GRID.values():
        total_exec_combos *= len(v)

    # Group by (pool, bullets) — combos in same group share wick cache
    for pool in EXECUTION_GRID["active_pool"]:
        for bullets in EXECUTION_GRID["active_bullets_max"]:
            wick_cache = {}  # new cache per (pool, bullets) group

            for res_pool in EXECUTION_GRID["reserve_pool"]:
                for res_bullets in EXECUTION_GRID["reserve_bullets_max"]:
                    for t_full in EXECUTION_GRID["tier_full"]:
                        for t_std in EXECUTION_GRID["tier_std"]:
                            combo_idx += 1
                            if combo_idx % 25 == 0 or combo_idx == 1:
                                _log_progress(f"exec combo {combo_idx}/{total_exec_combos} — best P/L: ${best_pnl:.2f}")

                            overrides = {
                                "sell_default": threshold_params["sell_default"],
                                "sell_fast_cycler": threshold_params["sell_default"] + 2.0,
                                "sell_exceptional": threshold_params["sell_default"] + 4.0,
                                "cat_hard_stop": threshold_params["cat_hard_stop"],
                                "cat_warning": max(threshold_params["cat_hard_stop"] - 10, 5),
                                "active_pool": pool,
                                "reserve_pool": res_pool,
                                "active_bullets_max": bullets,
                                "reserve_bullets_max": res_bullets,
                                "tier_full": t_full,
                                "tier_std": t_std,
                            }

                            try:
                                result = _simulate_with_config(
                                    ticker, months, overrides, data_dir,
                                    price_data, regime_data, wick_cache)
                            except Exception as e:
                                sim_errors += 1
                                if sim_errors <= 3:
                                    _log_progress(f"exec sim error: {type(e).__name__}: {e}")
                                continue

                            pnl = result.get("pnl", 0)
                            if pnl > best_pnl:
                                best_pnl = pnl
                                best_params = {
                                    **threshold_params,
                                    "active_pool": pool,
                                    "reserve_pool": res_pool,
                                    "active_bullets_max": bullets,
                                    "reserve_bullets_max": res_bullets,
                                    "tier_full": t_full,
                                    "tier_std": t_std,
                                }
                                best_result = result

    if sim_errors > 0:
        _log_progress(f"{sim_errors} exec sim errors across {total_exec_combos} combos")

    return best_params, best_result


# ---------------------------------------------------------------------------
# Stage 3: Level filter sweep
# ---------------------------------------------------------------------------

LEVEL_RESULTS_PATH = _ROOT / "data" / "sweep_support_levels.json"


def sweep_levels(ticker, threshold_params, execution_params=None, months=10):
    """Stage 3: Sweep level filters with thresholds + execution params locked.

    Uses multi-period composite scoring (12mo/6mo/3mo/1mo) matching Stages 1-2.
    """
    data_dir = _collect_once(ticker, max(SWEEP_PERIODS))
    from backtest_engine import load_collected_data
    price_data, regime_data, _ = load_collected_data(data_dir)

    best_composite = 0  # require positive composite to accept
    best_params = None
    best_result = None
    best_periods = None

    base_overrides = {
        "sell_default": threshold_params["sell_default"],
        "sell_fast_cycler": threshold_params["sell_default"] + 2.0,
        "sell_exceptional": threshold_params["sell_default"] + 4.0,
        "cat_hard_stop": threshold_params["cat_hard_stop"],
        "cat_warning": max(threshold_params["cat_hard_stop"] - 10, 5),
    }
    if execution_params:
        base_overrides.update(execution_params)

    combos = list(itertools.product(
        LEVEL_FILTER_GRID["min_hold_rate"],
        LEVEL_FILTER_GRID["min_touch_freq"],
        LEVEL_FILTER_GRID["skip_dormant"],
        LEVEL_FILTER_GRID["zone_filter"],
    ))
    total_combos = len(combos)
    sim_errors = 0
    quality = {"positive": 0, "negative": 0, "zero_trade": 0}

    for idx, (min_hr, min_tf, skip_dorm, zone_f) in enumerate(combos):
        if (idx + 1) % 25 == 0 or idx == 0:
            _log_progress(f"{ticker}: level combo {idx+1}/{total_combos} — best: ${best_composite:.1f}/mo")

        overrides = {
            **base_overrides,
            "min_hold_rate": min_hr,
            "min_touch_freq": min_tf,
            "skip_dormant": skip_dorm,
            "zone_filter": zone_f,
        }

        # Multi-period scoring (matching Stage 1 pattern)
        results_by_period = {}
        last_result = None
        for period_months in SWEEP_PERIODS:
            period_wick_cache = {}
            try:
                result = _simulate_with_config(
                    ticker, period_months, overrides, data_dir,
                    price_data, regime_data, period_wick_cache)
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
                    _log_progress(f"{ticker}: sim error ({period_months}mo): {type(e).__name__}: {e}")

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
                "min_hold_rate": min_hr,
                "min_touch_freq": min_tf,
                "skip_dormant": skip_dorm,
                "zone_filter": zone_f,
            }
            best_result = last_result
            best_periods = results_by_period

    if sim_errors > 0:
        _log_progress(f"{ticker}: {sim_errors} sim errors across {total_combos} combos")
    _log_progress(f"{ticker}: quality: {quality['positive']}+ {quality['negative']}- {quality['zero_trade']}∅")

    return best_params, best_result, best_composite, best_periods


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def extract_support_features(ticker, result):
    """Extract behavioral features from support simulation result."""
    if not result:
        return None

    trades = result.get("trades_detail", [])
    sells = [t for t in trades if t.get("side", "").upper() == "SELL"
             and t.get("exit_reason") != "SIM_END"]
    buys = [t for t in trades if t.get("side", "").upper() == "BUY"]

    if not sells:
        return {
            "target_hit_rate": 0, "stop_hit_rate": 0,
            "mean_pnl_pct": 0, "trade_count": 0,
            "median_hold_days": 0, "avg_bullets_per_cycle": 0,
            "pool_efficiency": 0, "cycle_count": 0,
        }

    target_hits = sum(1 for s in sells if "TARGET" in str(s.get("exit_reason", "")))
    stop_hits = sum(1 for s in sells
                    if "CATASTROPHIC" in str(s.get("exit_reason", ""))
                    or "STOP" in str(s.get("exit_reason", "")))
    n_sells = len(sells)

    pnl_pcts = [s.get("pnl_pct", 0) for s in sells if s.get("pnl_pct") is not None]
    hold_days = [s.get("days_held", 0) for s in sells if s.get("days_held")]

    cycles = result.get("cycles", 0)
    total_pnl = result.get("pnl", 0)
    n_buys = len(buys)

    return {
        "target_hit_rate": round(target_hits / n_sells, 3) if n_sells else 0,
        "stop_hit_rate": round(stop_hits / n_sells, 3) if n_sells else 0,
        "mean_pnl_pct": round(float(np.mean(pnl_pcts)), 3) if pnl_pcts else 0,
        "trade_count": n_sells,
        "median_hold_days": round(float(np.median(hold_days)), 1) if hold_days else 0,
        "avg_bullets_per_cycle": round(n_buys / cycles, 1) if cycles else 0,
        "pool_efficiency": round(total_pnl / 300, 3) if total_pnl else 0,
        "cycle_count": cycles,
    }


# ---------------------------------------------------------------------------
# Parallel sweep
# ---------------------------------------------------------------------------

def _sweep_threshold_worker(args):
    """Worker for parallel threshold sweep."""
    ticker, months = args
    try:
        params, result, composite, periods = sweep_threshold(ticker, months)
        if params and result:
            features = extract_support_features(ticker, result)
            trades_detail = result.get("trades_detail", [])
            for t in trades_detail:
                if t.get("side", "").upper() == "BUY":
                    t["fired_inputs"] = {
                        f"{ticker}:profit_gate": {
                            f"{ticker}:pnl_pct": t.get("pnl_pct", 0)},
                        f"{ticker}:stop_gate": {
                            f"{ticker}:pnl_pct": t.get("pnl_pct", 0)},
                    }
            return ticker, {
                "params": params,
                "stats": {
                    "pnl": result.get("pnl", 0),
                    "win_rate": result.get("win_rate", 0),
                    "trades": result.get("sells", 0),
                    "cycles": result.get("cycles", 0),
                    "sharpe": result.get("sharpe", 0),
                    "composite": composite,
                },
                "features": features,
                "trades": trades_detail,
                "periods": periods,
            }
        return ticker, None
    except Exception as e:
        return ticker, None


def _sweep_levels_worker(args):
    """Worker for parallel level filter sweep."""
    ticker, threshold_params, execution_params, months = args
    try:
        best_params, best_result, composite, periods = sweep_levels(
            ticker, threshold_params, execution_params, months)
        if best_params:
            return ticker, {
                "level_params": best_params,
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
    parser = argparse.ArgumentParser(description="Support Strategy Parameter Sweeper")
    parser.add_argument("--ticker", type=str, default=None,
                        help="Sweep a single ticker")
    parser.add_argument("--top", type=int, default=30,
                        help="Number of universe passers to sweep (default: 30)")
    parser.add_argument("--months", type=int, default=10,
                        help="Simulation months (default: 10)")
    parser.add_argument("--stage", choices=["threshold", "execution", "both", "level"],
                        default="both", help="Which stage to run")
    parser.add_argument("--split", action="store_true",
                        help="Cross-validate: train first 7mo, validate last 3mo")
    parser.add_argument("--workers", type=int, default=1,
                        help="Parallel workers (default: 1)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start = time.time()
    threshold_combos = len(THRESHOLD_GRID["sell_default"]) * len(THRESHOLD_GRID["cat_hard_stop"])
    execution_combos = 1
    for v in EXECUTION_GRID.values():
        execution_combos *= len(v)

    print(f"Support Strategy Parameter Sweeper — {date.today().isoformat()}")
    print(f"Stage 1: {threshold_combos} threshold combos")
    print(f"Stage 2: {execution_combos} execution combos")
    print()

    # Determine tickers to sweep
    if args.ticker:
        tickers = [args.ticker]
    else:
        # Load tickers that have collected data
        available = [d.name for d in GATE_RESULTS_DIR.iterdir()
                     if d.is_dir() and (d / "price_data.pkl").exists()]
        # Sort by existing sim results if available
        available.sort()
        tickers = available[:args.top]

    print(f"Tickers: {len(tickers)} (with collected data)")

    # Cross-validation: train on first 7 months, validate on last 3
    train_months = args.months
    val_months = 0
    if args.split:
        train_months = int(args.months * 0.7)
        val_months = args.months - train_months
        print(f"Cross-validation: train={train_months}mo, validate={val_months}mo")
    print()

    # Stage 1: Threshold sweep
    results = {}
    if args.stage in ("threshold", "both"):
        print(f"Stage 1: Sweeping {len(tickers)} tickers × {threshold_combos} combos...")

        if args.workers > 1 and len(tickers) > 1:
            worker_args = [(tk, train_months) for tk in tickers]
            with Pool(processes=min(args.workers, len(tickers))) as pool:
                for tk, result in pool.map(_sweep_threshold_worker, worker_args):
                    if result:
                        results[tk] = result
                        s = result["stats"]
                        p = result["params"]
                        print(f"  {tk}: P/L=${s['pnl']:.2f} "
                              f"({s['trades']}t, {s['win_rate']}%WR) "
                              f"sell={p['sell_default']}% "
                              f"cat={p['cat_hard_stop']}%", flush=True)
                    else:
                        print(f"  {tk}: no profitable combo", flush=True)
        else:
            for i, tk in enumerate(tickers):
                print(f"  [{i+1}/{len(tickers)}] {tk}...", end=" ", flush=True)
                t0 = time.time()
                params, result, composite, periods = sweep_threshold(tk, train_months)
                if params and result:
                    features = extract_support_features(tk, result)
                    results[tk] = {
                        "params": params,
                        "stats": {
                            "pnl": result.get("pnl", 0),
                            "win_rate": result.get("win_rate", 0),
                            "trades": result.get("sells", 0),
                            "cycles": result.get("cycles", 0),
                            "sharpe": result.get("sharpe", 0),
                            "composite": composite,
                        },
                        "features": features,
                        "trades": result.get("trades_detail", []),
                        "periods": periods,
                    }
                    s = results[tk]["stats"]
                    print(f"P/L=${s['pnl']:.2f} ({s['trades']}t) "
                          f"composite=${composite:.1f}/mo "
                          f"sell={params['sell_default']}% cat={params['cat_hard_stop']}% "
                          f"[{time.time()-t0:.0f}s]",
                          flush=True)
                else:
                    print(f"no profitable combo [{time.time()-t0:.0f}s]", flush=True)

    # Cross-validation
    if args.split and val_months > 0 and results:
        print(f"\nValidating on last {val_months} months...")
        for tk in list(results.keys()):
            params = results[tk]["params"]
            overrides = {
                "sell_default": params["sell_default"],
                "sell_fast_cycler": params["sell_default"] + 2.0,
                "sell_exceptional": params["sell_default"] + 4.0,
                "cat_hard_stop": params["cat_hard_stop"],
                "cat_warning": max(params["cat_hard_stop"] - 10, 5),
            }
            try:
                val_result = _simulate_with_config(tk, val_months, overrides)
                results[tk]["cross_validation"] = {
                    "pnl": val_result.get("pnl", 0),
                    "trades": val_result.get("sells", 0),
                    "win_rate": val_result.get("win_rate", 0),
                }
                cv = results[tk]["cross_validation"]
                flag = " OVERFIT" if results[tk]["stats"]["pnl"] > 0 and cv["pnl"] < 0 else ""
                print(f"  {tk}: val P/L=${cv['pnl']:.2f} ({cv['trades']}t){flag}",
                      flush=True)
            except Exception:
                results[tk]["cross_validation"] = {"pnl": 0, "trades": 0, "win_rate": 0}

    # Stage 2: Execution sweep on top tickers
    if args.stage in ("execution", "both") and results:
        # Rank by P/L, take top for execution sweep
        ranked = sorted(results.items(), key=lambda x: x[1]["stats"]["pnl"], reverse=True)
        top_for_exec = [tk for tk, r in ranked[:min(10, len(ranked))]
                        if r["stats"]["pnl"] > 0]

        if top_for_exec:
            print(f"\nStage 2: Execution sweep on {len(top_for_exec)} profitable tickers "
                  f"× {execution_combos} combos...")
            for tk in top_for_exec:
                print(f"  {tk}...", end=" ", flush=True)
                t0 = time.time()
                threshold_params = results[tk]["params"]
                exec_params, exec_result = sweep_execution(tk, threshold_params, train_months)
                if exec_params:
                    results[tk]["params"] = exec_params  # merged threshold + execution
                    results[tk]["stats"]["pnl"] = exec_result.get("pnl", 0)
                    print(f"pool=${exec_params['active_pool']} "
                          f"bullets={exec_params['active_bullets_max']} "
                          f"P/L=${exec_result.get('pnl', 0):.2f} [{time.time()-t0:.0f}s]", flush=True)
                else:
                    print(f"no improvement [{time.time()-t0:.0f}s]", flush=True)

    # Write results
    output = {
        "_meta": {
            "source": "support_parameter_sweeper.py",
            "updated": date.today().isoformat(),
            "threshold_combos": threshold_combos,
            "execution_combos": execution_combos,
            "tickers_swept": len(tickers),
            "profitable": len(results),
        }
    }
    for tk, r in results.items():
        output[tk] = {
            "params": r["params"],
            "stats": r["stats"],
            "features": r.get("features"),
            "cross_validation": r.get("cross_validation"),
        }

    if not args.dry_run and args.stage != "level":
        with open(RESULTS_PATH, "w") as f:
            json.dump(output, f, indent=2, default=str)
        print(f"\nResults saved to {RESULTS_PATH}")

    # Stage 3: Level filter sweep
    if args.stage == "level":
        if not RESULTS_PATH.exists():
            print("*Stage 1+2 results not found. Run --stage both first.*")
            return
        with open(RESULTS_PATH) as f:
            prior = json.load(f)

        # Pre-filter: warn about skipped tickers
        for tk in tickers:
            if not tk.startswith("_") and tk not in prior:
                print(f"  {tk}... *skipped (not in prior sweep results)*", flush=True)

        level_tickers = [tk for tk in tickers if tk in prior and not tk.startswith("_")]
        print(f"\nStage 3: Level filter sweep on {len(level_tickers)} tickers...")
        level_output = {}

        if args.workers > 1 and len(level_tickers) > 1:
            worker_args = [(tk, prior[tk]["params"],
                            {k: prior[tk]["params"][k] for k in
                             ("active_pool", "reserve_pool", "active_bullets_max", "reserve_bullets_max")
                             if k in prior[tk]["params"]},
                            args.months)
                           for tk in level_tickers]
            with Pool(processes=min(args.workers, len(worker_args))) as pool:
                for tk, result in pool.map(_sweep_levels_worker, worker_args):
                    if result:
                        level_output[tk] = result
                        lp = result["level_params"]
                        print(f"  {tk}: hr={lp['min_hold_rate']} tf={lp['min_touch_freq']} "
                              f"zone={lp['zone_filter']} composite=${result['stats']['composite']:.1f}/mo",
                              flush=True)
                    else:
                        print(f"  {tk}: no improvement", flush=True)
        else:
            for tk in level_tickers:
                print(f"  {tk}...", end=" ", flush=True)
                t0 = time.time()
                best_params, best_result, composite, periods = sweep_levels(
                    tk, prior[tk]["params"],
                    {k: prior[tk]["params"][k] for k in
                     ("active_pool", "reserve_pool", "active_bullets_max", "reserve_bullets_max")
                     if k in prior[tk]["params"]},
                    args.months)
                if best_params:
                    level_output[tk] = {
                        "level_params": best_params,
                        "stats": {
                            "composite": round(composite, 2) if composite else 0,
                            "pnl": best_result.get("pnl", 0) if best_result else 0,
                            "trades": best_result.get("sells", 0) if best_result else 0,
                        },
                        "periods": periods,
                    }
                    print(f"hr={best_params['min_hold_rate']} tf={best_params['min_touch_freq']} "
                          f"zone={best_params['zone_filter']} composite=${composite:.1f}/mo "
                          f"[{time.time()-t0:.0f}s]",
                          flush=True)
                else:
                    print(f"no improvement [{time.time()-t0:.0f}s]", flush=True)

        if level_output and not args.dry_run:
            with open(LEVEL_RESULTS_PATH, "w") as f:
                json.dump(level_output, f, indent=2)
            print(f"\nLevel filter results written to {LEVEL_RESULTS_PATH}")

    # Summary
    elapsed = time.time() - start
    print(f"\n{'='*60}")
    if args.stage == "level":
        print(f"| Ticker | HoldRate | TouchFreq | SkipDormant | Zone | $/mo | Trades |")
        print(f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for tk in sorted(level_output.keys(),
                         key=lambda t: level_output[t]["stats"]["composite"], reverse=True):
            lp = level_output[tk]["level_params"]
            ls = level_output[tk]["stats"]
            print(f"| {tk} | {lp['min_hold_rate']} | {lp['min_touch_freq']} | "
                  f"{lp['skip_dormant']} | {lp['zone_filter']} | "
                  f"${ls['composite']:.1f} | {ls['trades']} |")
    else:
        print(f"| Ticker | Sell% | Cat% | Pool | Bullets | P/L | WR | Trades |")
        print(f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for tk in sorted(results.keys(),
                         key=lambda t: results[t]["stats"]["pnl"], reverse=True):
            r = results[tk]
            p = r["params"]
            s = r["stats"]
            print(f"| {tk} | {p['sell_default']}% | {p['cat_hard_stop']}% | "
                  f"${p.get('active_pool', 300)} | {p.get('active_bullets_max', 5)} | "
                  f"${s['pnl']:.2f} | {s['win_rate']}% | {s['trades']} |")

    print(f"\nTotal time: {elapsed:.0f}s ({elapsed/60:.1f} min)")


if __name__ == "__main__":
    main()
