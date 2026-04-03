"""Weekly re-optimization pipeline — automated neural network maintenance.

Orchestrates the full learning cycle:
  1. Download latest 60-day 5-min data
  2. Run parameter sweep with cross-validation
  3. Re-cluster tickers by behavioral features
  4. Train synapse weights from trade outcomes
  5. Check for overfitting / divergence
  6. Email summary

Designed for cron execution (Saturday mornings) or manual runs.

Usage:
    python3 tools/weekly_reoptimize.py                  # full pipeline
    python3 tools/weekly_reoptimize.py --skip-download   # use cached data
    python3 tools/weekly_reoptimize.py --dry-run          # no writes, no email
    python3 tools/weekly_reoptimize.py --no-email         # skip email notification

Cron:
    0 6 * * 6 cd /Users/kamenkamenov/agentic-trading && python3 tools/weekly_reoptimize.py >> data/reoptimize.log 2>&1
"""
import sys
import json
import argparse
import subprocess
import time
from pathlib import Path
from datetime import datetime, date

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
PROFILES_PATH = _ROOT / "data" / "ticker_profiles.json"
WEIGHTS_PATH = _ROOT / "data" / "synapse_weights.json"
SWEEP_RESULTS_PATH = _ROOT / "data" / "sweep_results.json"
REOPT_HISTORY_PATH = _ROOT / "data" / "reoptimize_history.json"

# Strategy-specific tool paths
STRATEGY_TOOLS = {
    "dip": {
        "sweeper": "tools/parameter_sweeper.py",
        "sweeper_args": ["--split"],
        "clusterer": "tools/ticker_clusterer.py",
        "sweep_results": _ROOT / "data" / "sweep_results.json",
    },
    "support": {
        "sweeper": "tools/support_parameter_sweeper.py",
        "sweeper_args": ["--split"],
        "clusterer": "tools/ticker_clusterer.py",
        "sweep_results": _ROOT / "data" / "support_sweep_results.json",
    },
}


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def step_watchlist_sweep():
    """Sweep support params for ALL watchlist + position tickers."""
    print("=" * 60)
    print("STEP: Watchlist Support Sweep")
    print("=" * 60)

    cmd = [sys.executable, "tools/neural_watchlist_sweeper.py", "--workers", "4"]
    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_ROOT))
    elapsed = time.time() - t0

    print(result.stdout)
    if result.stderr:
        for line in result.stderr.split("\n"):
            if "FutureWarning" not in line and "float(ser" not in line and line.strip():
                print(f"  stderr: {line}")

    success = result.returncode == 0
    print(f"  Watchlist sweep {'completed' if success else 'FAILED'} in {elapsed:.0f}s\n")
    return success, elapsed


def step_sweep(use_cached=False, strategy="dip"):
    """Step 1-2: Download data + parameter sweep with cross-validation."""
    tools = STRATEGY_TOOLS[strategy]
    print("=" * 60)
    print(f"STEP 1: Parameter Sweep + Cross-Validation ({strategy})")
    print("=" * 60)

    cmd = [sys.executable, tools["sweeper"]] + tools["sweeper_args"]
    if use_cached:
        cmd.append("--cached")

    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_ROOT))
    elapsed = time.time() - t0

    print(result.stdout)
    if result.stderr:
        # Filter yfinance warnings
        for line in result.stderr.split("\n"):
            if "FutureWarning" not in line and "float(ser" not in line and line.strip():
                print(f"  stderr: {line}")

    success = result.returncode == 0 and tools["sweep_results"].exists()
    print(f"  Sweep {'completed' if success else 'FAILED'} in {elapsed:.0f}s\n")
    return success, elapsed


def step_cluster():
    """Step 3: Re-cluster tickers by behavioral features."""
    print("=" * 60)
    print("STEP 2: Behavioral Clustering")
    print("=" * 60)

    cmd = [sys.executable, "tools/ticker_clusterer.py"]
    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_ROOT))
    elapsed = time.time() - t0

    print(result.stdout)
    if result.returncode != 0:
        print(f"  Clustering FAILED\n")
        if result.stderr:
            print(f"  stderr: {result.stderr[:500]}")
        return False, elapsed, {}

    # Parse cluster info from profiles
    cluster_info = {}
    if PROFILES_PATH.exists():
        with open(PROFILES_PATH) as f:
            profiles = json.load(f)
        meta = profiles.get("_meta", {})
        cluster_info = {
            "n_clusters": meta.get("clusters", 0),
            "silhouette": meta.get("silhouette_score", 0),
        }

    print(f"  Clustering completed in {elapsed:.0f}s\n")
    return True, elapsed, cluster_info


def step_train_weights(epochs=3, learning_rate=0.01):
    """Step 4: Train synapse weights from sweep trade outcomes."""
    print("=" * 60)
    print("STEP 3: Synapse Weight Training")
    print("=" * 60)

    cmd = [sys.executable, "tools/weight_learner.py",
           "--epochs", str(epochs), "--learning-rate", str(learning_rate)]
    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_ROOT))
    elapsed = time.time() - t0

    print(result.stdout)
    if result.returncode != 0:
        print(f"  Weight training FAILED\n")
        return False, elapsed, {}

    # Parse weight stats
    weight_stats = {}
    if WEIGHTS_PATH.exists():
        with open(WEIGHTS_PATH) as f:
            data = json.load(f)
        stats = data.get("_meta", {}).get("stats", {})
        weights = data.get("weights", {})
        all_w = [w for gate in weights.values() for w in gate.values()]
        weight_stats = {
            "total_synapses": len(all_w),
            "mean_weight": round(float(np.mean(all_w)), 4) if all_w else 1.0,
            "min_weight": round(min(all_w), 4) if all_w else 1.0,
            "max_weight": round(max(all_w), 4) if all_w else 1.0,
            "trades_trained": stats.get("total_trades", 0),
        }

    print(f"  Weight training completed in {elapsed:.0f}s\n")
    return True, elapsed, weight_stats


def step_check_overfitting():
    """Step 5: Check cross-validation results for overfitting signals."""
    print("=" * 60)
    print("STEP 4: Overfitting Check")
    print("=" * 60)

    if not SWEEP_RESULTS_PATH.exists():
        print("  No sweep results to check.\n")
        return []

    with open(SWEEP_RESULTS_PATH) as f:
        sweep = json.load(f)

    overfit_flags = []
    for tk, result in sorted(sweep.items()):
        if tk.startswith("_"):
            continue
        cv = result.get("cross_validation")
        stats = result.get("stats", {})
        if not cv or cv.get("trades", 0) == 0:
            continue

        train_pnl = stats.get("total_pnl", 0)
        val_pnl = cv.get("pnl", 0)

        if train_pnl > 0 and val_pnl < 0:
            overfit_flags.append({
                "ticker": tk,
                "train_pnl": train_pnl,
                "val_pnl": val_pnl,
                "train_trades": stats.get("trades", 0),
                "val_trades": cv.get("trades", 0),
            })
            print(f"  ⚠ {tk}: OVERFIT — train P/L=${train_pnl:.2f} "
                  f"but validation P/L=${val_pnl:.2f}")

    if not overfit_flags:
        print("  No overfitting signals detected.")
    print(f"  Flagged: {len(overfit_flags)} tickers\n")
    return overfit_flags


def step_check_confidence():
    """Check for low-confidence and confidence-drop tickers."""
    if not PROFILES_PATH.exists():
        return [], []

    with open(PROFILES_PATH) as f:
        profiles = json.load(f)

    low_conf = []
    for tk, profile in sorted(profiles.items()):
        if tk.startswith("_"):
            continue
        conf = profile.get("confidence", 100)
        if conf < 40:
            low_conf.append((tk, conf))

    # Check for confidence drops vs previous run
    drops = []
    if REOPT_HISTORY_PATH.exists():
        with open(REOPT_HISTORY_PATH) as f:
            history = json.load(f)
        prev_run = history.get("runs", [{}])[-1] if history.get("runs") else {}
        prev_conf = prev_run.get("confidence_scores", {})
        for tk, profile in profiles.items():
            if tk.startswith("_"):
                continue
            curr = profile.get("confidence", 0)
            prev = prev_conf.get(tk, curr)
            if prev - curr > 10:
                drops.append((tk, prev, curr))

    return low_conf, drops


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def build_summary(sweep_ok, cluster_ok, weights_ok, cluster_info,
                  weight_stats, overfit_flags, low_conf, conf_drops,
                  timings):
    """Build human-readable summary for email + log."""
    lines = [
        f"Weekly Re-optimization — {date.today().isoformat()}",
        f"{'=' * 50}",
        "",
        "Pipeline Status:",
        f"  Sweep:      {'OK' if sweep_ok else 'FAILED'} ({timings.get('sweep', 0):.0f}s)",
        f"  Clustering: {'OK' if cluster_ok else 'FAILED'} ({timings.get('cluster', 0):.0f}s)",
        f"  Weights:    {'OK' if weights_ok else 'FAILED'} ({timings.get('weights', 0):.0f}s)",
        "",
    ]

    if cluster_info:
        lines.append(f"Clusters: {cluster_info.get('n_clusters', '?')} "
                     f"(silhouette={cluster_info.get('silhouette', '?')})")

    if weight_stats:
        lines.append(f"Synapses: {weight_stats.get('total_synapses', 0)} "
                     f"(mean={weight_stats.get('mean_weight', 1.0):.4f}, "
                     f"range=[{weight_stats.get('min_weight', 1.0):.4f}, "
                     f"{weight_stats.get('max_weight', 1.0):.4f}])")
        lines.append(f"Trained on: {weight_stats.get('trades_trained', 0)} trades")

    if overfit_flags:
        lines.append(f"\nOverfitting flags ({len(overfit_flags)}):")
        for f in overfit_flags:
            lines.append(f"  {f['ticker']}: train=${f['train_pnl']:.2f} "
                        f"val=${f['val_pnl']:.2f}")

    if low_conf:
        lines.append(f"\nLow confidence (<40): {', '.join(tk for tk, _ in low_conf)}")

    if conf_drops:
        lines.append(f"\nConfidence drops (>10pt):")
        for tk, prev, curr in conf_drops:
            lines.append(f"  {tk}: {prev:.0f} → {curr:.0f}")

    if not overfit_flags and not low_conf and not conf_drops:
        lines.append("\nNo issues detected.")

    return "\n".join(lines)


def save_history(summary, cluster_info, weight_stats, overfit_flags):
    """Append run to reoptimize_history.json for trend tracking."""
    history = {"runs": []}
    if REOPT_HISTORY_PATH.exists():
        try:
            with open(REOPT_HISTORY_PATH) as f:
                history = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # Read current confidence scores
    conf_scores = {}
    if PROFILES_PATH.exists():
        with open(PROFILES_PATH) as f:
            profiles = json.load(f)
        for tk, p in profiles.items():
            if not tk.startswith("_"):
                conf_scores[tk] = p.get("confidence", 0)

    run = {
        "date": date.today().isoformat(),
        "clusters": cluster_info.get("n_clusters", 0),
        "silhouette": cluster_info.get("silhouette", 0),
        "synapses": weight_stats.get("total_synapses", 0),
        "mean_weight": weight_stats.get("mean_weight", 1.0),
        "overfit_count": len(overfit_flags),
        "confidence_scores": conf_scores,
    }

    history["runs"].append(run)
    # Keep last 52 runs (1 year of weekly)
    history["runs"] = history["runs"][-52:]

    with open(REOPT_HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)


# ---------------------------------------------------------------------------
# Candidate sweep + Tournament
# ---------------------------------------------------------------------------

def step_candidate_sweep():
    """Sweep top 15 universe-screening passers (Stage 1 only) for tournament."""
    print("=" * 60)
    print("STEP 6: Candidate Sweep (Stage 1)")
    print("=" * 60)

    cache_path = _ROOT / "data" / "universe_screen_cache.json"
    if not cache_path.exists():
        print("  Universe screen cache not found — skipping")
        return False, 0, 0

    try:
        with open(cache_path) as f:
            cache = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"  *Cache load error: {e}*")
        return False, 0, 0

    # Get tracked tickers to exclude
    try:
        with open(_ROOT / "portfolio.json") as f:
            portfolio = json.load(f)
    except (OSError, json.JSONDecodeError):
        portfolio = {}
    tracked = (set(portfolio.get("watchlist", []))
               | set(portfolio.get("positions", {}).keys()))

    passers = [t["ticker"] for t in cache.get("passers", [])
               if t["ticker"] not in tracked][:15]

    if not passers:
        print("  No new candidates to sweep")
        return True, 0, 0

    print(f"  Sweeping {len(passers)} candidates...")
    t0 = time.time()

    from concurrent.futures import ThreadPoolExecutor

    def sweep_one(tk):
        result = subprocess.run(
            [sys.executable, "tools/support_parameter_sweeper.py",
             "--ticker", tk, "--stage", "threshold"],
            capture_output=True, text=True, cwd=str(_ROOT))
        return tk, result.returncode == 0

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(sweep_one, passers))

    swept = sum(1 for _, ok in results if ok)
    failed = [tk for tk, ok in results if not ok]
    elapsed = time.time() - t0
    print(f"  Swept: {swept}/{len(passers)} in {elapsed:.0f}s")
    if failed:
        print(f"  Failed: {', '.join(failed)}")
    return True, elapsed, swept


def step_tournament(dry_run=False, no_email=False):
    """Run watchlist tournament ranking."""
    print("=" * 60)
    print("STEP 7: Watchlist Tournament")
    print("=" * 60)

    cmd = [sys.executable, "tools/watchlist_tournament.py"]
    if dry_run:
        cmd.append("--dry-run")
    if no_email:
        cmd.append("--no-email")

    t0 = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_ROOT))
    elapsed = time.time() - t0

    if result.stdout:
        print(result.stdout)
    if result.returncode != 0 and result.stderr:
        for line in result.stderr.split("\n"):
            if line.strip():
                print(f"  stderr: {line}")

    success = result.returncode == 0
    print(f"  Tournament {'completed' if success else 'FAILED'} in {elapsed:.0f}s\n")
    return success, elapsed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Weekly Re-optimization Pipeline")
    parser.add_argument("--skip-download", action="store_true",
                        help="Use cached intraday data (skip yfinance download)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run pipeline but don't write profiles/weights")
    parser.add_argument("--no-email", action="store_true",
                        help="Skip email notification")
    parser.add_argument("--epochs", type=int, default=3,
                        help="Weight training epochs (default: 3)")
    parser.add_argument("--learning-rate", type=float, default=0.01,
                        help="Weight learning rate (default: 0.01)")
    parser.add_argument("--strategy", choices=["dip", "support"], default="dip",
                        help="Strategy module to optimize (default: dip)")
    args = parser.parse_args()

    start = time.time()
    print(f"\nWeekly Re-optimization Pipeline — {date.today().isoformat()} ({args.strategy})")
    print(f"Started at {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'=' * 60}\n")

    timings = {}

    # Step 1-2: Sweep with cross-validation
    sweep_ok, t = step_sweep(use_cached=args.skip_download, strategy=args.strategy)
    timings["sweep"] = t
    if not sweep_ok:
        print("*Sweep failed. Aborting pipeline.*")
        return

    # Step 2b: Watchlist sweep (ensures every tracked ticker has a neural profile)
    wl_ok, wl_t = step_watchlist_sweep()
    timings["watchlist_sweep"] = wl_t

    # Step 3: Cluster
    cluster_ok, t, cluster_info = step_cluster()
    timings["cluster"] = t

    # Step 4: Train weights
    weights_ok, t, weight_stats = step_train_weights(
        epochs=args.epochs, learning_rate=args.learning_rate)
    timings["weights"] = t

    # Step 5: Overfitting check
    overfit_flags = step_check_overfitting()
    low_conf, conf_drops = step_check_confidence()

    # Step 6: Candidate sweep (Stage 1 only for tournament ranking)
    cand_ok, cand_t, n_swept = step_candidate_sweep()
    timings["candidate_sweep"] = cand_t
    if n_swept > 0:
        print(f"  Candidate sweep: {n_swept} tickers in {cand_t:.0f}s")

    # Step 7: Tournament
    if not args.dry_run:
        tour_ok, tour_t = step_tournament(no_email=args.no_email)
    else:
        tour_ok, tour_t = step_tournament(dry_run=True, no_email=True)
    timings["tournament"] = tour_t

    # Build summary
    total_time = time.time() - start
    summary = build_summary(sweep_ok, cluster_ok, weights_ok, cluster_info,
                           weight_stats, overfit_flags, low_conf, conf_drops,
                           timings)

    print(f"\n{'=' * 60}")
    print(summary)
    print(f"\nTotal pipeline time: {total_time:.0f}s")
    print(f"{'=' * 60}")

    # Save history
    if not args.dry_run:
        save_history(summary, cluster_info, weight_stats, overfit_flags)
        print(f"\nHistory saved to {REOPT_HISTORY_PATH}")

    # Email
    if not args.no_email and not args.dry_run:
        try:
            from notify import send_summary_email
            send_summary_email(
                subject=f"Neural Re-optimization — {date.today().isoformat()}",
                body=summary + f"\n\nPipeline time: {total_time:.0f}s")
        except Exception as e:
            print(f"*Email failed: {e}*")


if __name__ == "__main__":
    main()
