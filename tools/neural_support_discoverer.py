"""Neural Support Candidate Discoverer — find top 30 support strategy tickers.

Runs support_parameter_sweeper on tickers that have collected simulation data,
ranks by P/L, applies gates, clusters, outputs top 30 with complete profiles.

Usage:
    python3 tools/neural_support_discoverer.py                     # full run
    python3 tools/neural_support_discoverer.py --top 50             # top 50
    python3 tools/neural_support_discoverer.py --split              # cross-validate
    python3 tools/neural_support_discoverer.py --workers 4          # parallel
    python3 tools/neural_support_discoverer.py --dry-run            # no writes
"""
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

from support_parameter_sweeper import (
    sweep_threshold, sweep_execution, extract_support_features,
    _collect_once, _simulate_with_config, GATE_RESULTS_DIR,
)

_ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = _ROOT / "data" / "neural_support_candidates.json"
RESULTS_MD = _ROOT / "data" / "neural_support_candidates.md"
DIP_RESULTS = _ROOT / "data" / "neural_candidates.json"

# Support strategy feature columns for clustering
SUPPORT_FEATURE_COLS = [
    "target_hit_rate",
    "stop_hit_rate",
    "mean_pnl_pct",
    "trade_count",
    "median_hold_days",
    "avg_bullets_per_cycle",
    "pool_efficiency",
    "cycle_count",
]


def get_available_tickers():
    """Find tickers that have collected simulation data."""
    available = []
    for d in GATE_RESULTS_DIR.iterdir():
        if d.is_dir() and (d / "price_data.pkl").exists():
            available.append(d.name)
    return sorted(available)


def rank_and_gate(results, min_trades=3):
    """Rank by P/L, apply gates."""
    ranked = []
    for tk, r in results.items():
        stats = r.get("stats", {})
        params = r.get("params")
        if not params:
            continue
        if stats.get("trades", 0) < min_trades:
            continue
        if stats.get("pnl", 0) <= 0:
            continue
        # Check cross-validation if available
        cv = r.get("cross_validation")
        overfit = False
        if cv and cv.get("trades", 0) > 0:
            if stats["pnl"] > 0 and cv["pnl"] < 0:
                overfit = True

        ranked.append({
            "ticker": tk,
            "pnl": stats["pnl"],
            "composite": stats.get("composite", 0),
            "win_rate": stats.get("win_rate", 0),
            "trades": stats.get("trades", 0),
            "cycles": stats.get("cycles", 0),
            "sharpe": stats.get("sharpe", 0),
            "params": params,
            "features": r.get("features"),
            "periods": r.get("periods"),
            "cross_validation": cv,
            "overfit": overfit,
        })

    # Sort by composite $/month (multi-period weighted, not single-period P/L)
    ranked.sort(key=lambda x: x.get("composite", 0), reverse=True)
    return ranked


def compare_with_dip():
    """Load dip candidates and find overlap."""
    if not DIP_RESULTS.exists():
        return set()
    with open(DIP_RESULTS) as f:
        dip = json.load(f)
    return {c["ticker"] for c in dip.get("candidates", [])}


def write_results(ranked, top_n, meta):
    """Write results to JSON and markdown."""
    output = {
        "_meta": {
            "source": "neural_support_discoverer.py",
            "updated": date.today().isoformat(),
            **meta,
        },
        "candidates": ranked[:top_n],
    }

    with open(RESULTS_PATH, "w") as f:
        json.dump(output, f, indent=2, default=str)

    # Markdown
    lines = [
        f"# Neural Support Candidate Discovery — {date.today().isoformat()}\n",
        f"*Tickers swept: {meta.get('tickers_swept', '?')}, "
        f"passed gates: {meta.get('passed_gates', '?')}*\n",
        f"| # | Ticker | P/L | WR | Trades | Cycles | Sell% | Cat% | "
        f"Pool | Bullets | Dip? |",
        f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | "
        f":--- | :--- | :--- |",
    ]

    dip_tickers = compare_with_dip()
    for i, c in enumerate(ranked[:top_n], 1):
        p = c["params"]
        in_dip = "YES" if c["ticker"] in dip_tickers else ""
        lines.append(
            f"| {i} | {c['ticker']} | ${c['pnl']:.2f} | "
            f"{c['win_rate']}% | {c['trades']} | {c['cycles']} | "
            f"{p['sell_default']}% | {p['cat_hard_stop']}% | "
            f"${p.get('active_pool', 300)} | {p.get('active_bullets_max', 5)} | "
            f"{in_dip} |"
        )

    with open(RESULTS_MD, "w") as f:
        f.write("\n".join(lines) + "\n")

    return RESULTS_PATH, RESULTS_MD


def main():
    parser = argparse.ArgumentParser(description="Neural Support Candidate Discoverer")
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--months", type=int, default=10)
    parser.add_argument("--split", action="store_true",
                        help="Cross-validate: train 7mo, validate 3mo")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--exec-top", type=int, default=10,
                        help="Run execution sweep on top N from threshold sweep")
    args = parser.parse_args()

    start = time.time()
    print(f"Neural Support Candidate Discoverer — {date.today().isoformat()}")
    print(f"{'='*60}\n")

    # Find tickers with data
    available = get_available_tickers()
    print(f"Tickers with collected data: {len(available)}")

    if not available:
        print("*No tickers with collected data. Run candidate_sim_gate.py first.*")
        return

    # Stage 1: Threshold sweep
    train_months = args.months
    if args.split:
        train_months = int(args.months * 0.7)
        print(f"Cross-validation: train={train_months}mo, validate={args.months - train_months}mo")

    print(f"\nStage 1: Threshold sweep on {len(available)} tickers "
          f"({args.workers} workers)...")
    results = {}

    if args.workers > 1 and len(available) > 1:
        # Parallel sweep across tickers
        from multiprocessing import Pool as ProcessPool
        from support_parameter_sweeper import _sweep_threshold_worker

        worker_args = [(tk, train_months) for tk in available]
        with ProcessPool(processes=min(args.workers, len(available))) as pool:
            for tk, result_data in pool.map(_sweep_threshold_worker, worker_args):
                if result_data:
                    results[tk] = result_data
                    s = result_data["stats"]
                    p = result_data["params"]
                    print(f"  {tk}: P/L=${s['pnl']:.2f} ({s['trades']}t) "
                          f"sell={p['sell_default']}%", flush=True)
                else:
                    print(f"  {tk}: no profitable combo", flush=True)
    else:
        # Sequential fallback
        for i, tk in enumerate(available):
            print(f"  [{i+1}/{len(available)}] {tk}...", end=" ", flush=True)
            try:
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
                        "periods": periods,
                    }
                    s = results[tk]["stats"]
                    print(f"P/L=${s['pnl']:.2f} ({s['trades']}t) "
                          f"composite=${composite:.1f}/mo "
                          f"sell={params['sell_default']}%", flush=True)
                else:
                    print("no profitable combo", flush=True)
            except Exception as e:
                print(f"error: {e}", flush=True)

    print(f"\n{len(results)}/{len(available)} profitable")

    # Cross-validation
    if args.split:
        val_months = args.months - train_months
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
                data_dir = str(GATE_RESULTS_DIR / tk)
                val_result = _simulate_with_config(tk, val_months, overrides, data_dir)
                results[tk]["cross_validation"] = {
                    "pnl": val_result.get("pnl", 0),
                    "trades": val_result.get("sells", 0),
                    "win_rate": val_result.get("win_rate", 0),
                }
            except Exception:
                results[tk]["cross_validation"] = {"pnl": 0, "trades": 0}

    # Stage 2: Execution sweep on top N
    ranked_for_exec = sorted(results.items(),
                             key=lambda x: x[1]["stats"]["pnl"], reverse=True)
    exec_tickers = [tk for tk, r in ranked_for_exec[:args.exec_top]
                    if r["stats"]["pnl"] > 0]

    if exec_tickers:
        print(f"\nStage 2: Execution sweep on top {len(exec_tickers)} tickers...")
        for tk in exec_tickers:
            print(f"  {tk}...", end=" ", flush=True)
            try:
                params, result = sweep_execution(tk, results[tk]["params"], train_months)
                if params:
                    results[tk]["params"] = params
                    results[tk]["stats"]["pnl"] = result.get("pnl", 0)
                    print(f"pool=${params.get('active_pool', 300)} "
                          f"bullets={params.get('active_bullets_max', 5)} "
                          f"P/L=${result.get('pnl', 0):.2f}", flush=True)
                else:
                    print("no improvement", flush=True)
            except Exception as e:
                print(f"error: {e}", flush=True)

    # Rank and gate
    ranked = rank_and_gate(results)
    overfit = [r for r in ranked if r.get("overfit")]

    # Cluster if enough candidates
    if len(ranked) >= 3:
        try:
            from ticker_clusterer import (
                build_feature_matrix, find_optimal_clusters,
            )
            from sklearn.preprocessing import StandardScaler

            cluster_data = {r["ticker"]: {"features": r["features"]}
                           for r in ranked[:50] if r.get("features")}
            _, X, _ = build_feature_matrix(cluster_data, SUPPORT_FEATURE_COLS)
            if len(X) >= 3:
                scaler = StandardScaler()
                X_scaled = scaler.fit_transform(X)
                n_clusters, silhouette, labels = find_optimal_clusters(X_scaled)
                for i, r in enumerate(ranked[:50]):
                    if i < len(labels):
                        r["cluster"] = int(labels[i])
                print(f"\nClustered into {n_clusters} groups (silhouette={silhouette})")
        except Exception as e:
            print(f"*Clustering skipped: {e}*")

    # Output
    meta = {
        "tickers_swept": len(available),
        "profitable": len(results),
        "passed_gates": len(ranked),
        "overfit_flagged": len(overfit),
    }

    print(f"\n{'='*60}")
    print(f"Top {min(args.top, len(ranked))} Neural Support Candidates")
    print(f"{'='*60}\n")

    dip_tickers = compare_with_dip()
    print(f"| # | Ticker | P/L | WR | Trades | Cycles | Sell% | Cat% | "
          f"Pool | Bullets | Dip? |")
    print(f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | "
          f":--- | :--- | :--- |")
    for i, c in enumerate(ranked[:args.top], 1):
        p = c["params"]
        in_dip = "YES" if c["ticker"] in dip_tickers else ""
        print(f"| {i} | {c['ticker']} | ${c['pnl']:.2f} | "
              f"{c['win_rate']}% | {c['trades']} | {c['cycles']} | "
              f"{p['sell_default']}% | {p['cat_hard_stop']}% | "
              f"${p.get('active_pool', 300)} | {p.get('active_bullets_max', 5)} | "
              f"{in_dip} |")

    if dip_tickers:
        overlap = {c["ticker"] for c in ranked[:args.top]} & dip_tickers
        if overlap:
            print(f"\n**In BOTH dip + support top 30:** {', '.join(sorted(overlap))}")

    if not args.dry_run:
        jp, mp = write_results(ranked, args.top, meta)
        print(f"\nResults: {jp}")
        print(f"Report:  {mp}")

    elapsed = time.time() - start
    print(f"\nTotal time: {elapsed:.0f}s ({elapsed/60:.1f} min)")


if __name__ == "__main__":
    main()
