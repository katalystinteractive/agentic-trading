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
from artifact_promoter import promote_candidate, snapshot_incumbent
from model_complexity_gate import is_live_decision_artifact, live_decision_reason

_ROOT = Path(__file__).resolve().parent.parent
PROFILES_PATH = _ROOT / "data" / "ticker_profiles.json"
WEIGHTS_PATH = _ROOT / "data" / "synapse_weights.json"
SWEEP_RESULTS_PATH = _ROOT / "data" / "sweep_results.json"
REOPT_HISTORY_PATH = _ROOT / "data" / "reoptimize_history.json"
PROMOTED_ARTIFACTS = [
    _ROOT / "data" / "probability_calibration.json",
    _ROOT / "data" / "sweep_results.json",
    _ROOT / "data" / "support_sweep_results.json",
    _ROOT / "data" / "ticker_profiles.json",
    _ROOT / "data" / "synapse_weights.json",
]
_PROMOTION_RUN_ID = datetime.now().strftime("%Y%m%d-%H%M%S")
_INCUMBENT_SNAPSHOTS: dict[str, Path | None] = {}

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
    """Sweep support params for Tier 2 pool — threshold + execution + slippage in
    one process via `--stage all`, eliminating the redundant data load that the
    previous standalone `--stage slippage` process incurred.

    Uses --tickers-file if available (built by Tier 1 pre-screen + tracked),
    otherwise falls back to default pool (collected data directory).
    """
    cmd = [sys.executable, "tools/support_parameter_sweeper.py",
           "--stage", "all", "--workers", "8"]
    _tier2_file = _ROOT / "data" / ".tier2_pool.json"
    if _tier2_file.exists():
        cmd.extend(["--tickers-file", str(_tier2_file)])
    support_path = _ROOT / "data" / "support_sweep_results.json"
    _snapshot_artifacts([support_path])
    ok, elapsed = _run_sweep_step("2", "Support Sweep (Stage 1+2+slippage)", cmd)
    if ok:
        decisions = _promote_artifacts([support_path])
        ok = all(d.approved for d in decisions)
    return ok, elapsed


def _snapshot_artifacts(paths=None):
    """Snapshot incumbent artifacts before a pipeline step can overwrite them."""
    for path in paths or PROMOTED_ARTIFACTS:
        key = str(path)
        if key not in _INCUMBENT_SNAPSHOTS:
            _INCUMBENT_SNAPSHOTS[key] = snapshot_incumbent(
                path, run_id=_PROMOTION_RUN_ID)


def _promote_artifacts(paths, min_margin=0.02, allow_stale=False):
    """Promote or restore generated artifacts before downstream consumers run."""
    decisions = []
    for path in paths:
        if not path.exists():
            continue
        incumbent = _INCUMBENT_SNAPSHOTS.get(str(path))
        decision = promote_candidate(
            path,
            path,
            incumbent_path=incumbent,
            min_margin=min_margin,
            allow_stale=allow_stale,
        )
        decisions.append(decision)
        status = "PROMOTED" if decision.approved else "REJECTED"
        print(f"  {status}: {path.name} — {decision.reason}", flush=True)
    return decisions


def step_model_complexity_gate(paths=None):
    """Ensure black-box/advisory model outputs cannot affect live consumers."""
    print("=" * 60)
    print("STEP 0.8: Model Complexity Gate")
    print("=" * 60)

    checked = 0
    blocked = []
    for path in paths or PROMOTED_ARTIFACTS:
        if not path.exists():
            continue
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            blocked.append(f"{path.name}: unreadable ({exc})")
            continue
        checked += 1
        if not is_live_decision_artifact(data):
            blocked.append(f"{path.name}: {live_decision_reason(data)}")

    if blocked:
        for line in blocked:
            print(f"  BLOCKED: {line}", flush=True)
        print(f"  Model complexity gate FAILED ({len(blocked)} blocked)\n", flush=True)
        return False, {"checked": checked, "blocked": blocked}

    print(f"  Model complexity gate passed ({checked} live artifacts checked)\n",
          flush=True)
    return True, {"checked": checked, "blocked": []}


def step_sweep(use_cached=False, strategy="dip"):
    """Step 1-2: Download data + parameter sweep with cross-validation."""
    tools = STRATEGY_TOOLS[strategy]
    print("=" * 60)
    print(f"STEP 1: Parameter Sweep + Cross-Validation ({strategy})")
    print("=" * 60)

    cmd = [sys.executable, tools["sweeper"]] + tools["sweeper_args"]
    if use_cached:
        cmd.append("--cached")

    sys.stdout.flush()
    t0 = time.time()
    _snapshot_artifacts([tools["sweep_results"]])
    result = subprocess.run(cmd, cwd=str(_ROOT))
    elapsed = time.time() - t0

    success = result.returncode == 0 and tools["sweep_results"].exists()
    if success:
        decisions = _promote_artifacts([tools["sweep_results"]])
        success = all(d.approved for d in decisions)
    print(f"  Sweep {'completed' if success else 'FAILED'} in {elapsed:.0f}s\n", flush=True)
    return success, elapsed


def step_cluster():
    """Step 3: Re-cluster tickers by behavioral features."""
    print("=" * 60)
    print("STEP 2: Behavioral Clustering")
    print("=" * 60)

    cmd = [sys.executable, "tools/ticker_clusterer.py"]
    sys.stdout.flush()
    t0 = time.time()
    _snapshot_artifacts([PROFILES_PATH])
    result = subprocess.run(cmd, cwd=str(_ROOT))
    elapsed = time.time() - t0

    if result.returncode != 0:
        print(f"  Clustering FAILED\n", flush=True)
        return False, elapsed, {}
    decisions = _promote_artifacts([PROFILES_PATH])
    if not all(d.approved for d in decisions):
        print(f"  Clustering artifact promotion FAILED\n", flush=True)
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
    sys.stdout.flush()
    t0 = time.time()
    _snapshot_artifacts([WEIGHTS_PATH])
    result = subprocess.run(cmd, cwd=str(_ROOT))
    elapsed = time.time() - t0

    if result.returncode != 0:
        print(f"  Weight training FAILED\n", flush=True)
        return False, elapsed, {}
    decisions = _promote_artifacts([WEIGHTS_PATH])
    if not all(d.approved for d in decisions):
        print(f"  Weight artifact promotion FAILED\n", flush=True)
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


def step_probability_calibration(dry_run=False):
    """Build calibrated probability buckets for expected-edge scoring."""
    print("=" * 60)
    print("STEP 0.75: Probability Calibration")
    print("=" * 60)

    cmd = [sys.executable, "tools/probability_calibrator.py"]
    if dry_run:
        cmd.append("--dry-run")

    sys.stdout.flush()
    t0 = time.time()
    calibration_path = _ROOT / "data" / "probability_calibration.json"
    _snapshot_artifacts([calibration_path])
    result = subprocess.run(cmd, cwd=str(_ROOT))
    elapsed = time.time() - t0
    success = result.returncode == 0
    if success and not dry_run:
        decisions = _promote_artifacts([calibration_path])
        success = all(d.approved for d in decisions)
    print(f"  Probability calibration {'completed' if success else 'FAILED'} "
          f"in {elapsed:.0f}s\n", flush=True)
    return success, elapsed


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
    print("STEP 11: Watchlist Tournament")
    print("=" * 60)

    cmd = [sys.executable, "tools/watchlist_tournament.py"]
    if dry_run:
        cmd.append("--dry-run")
    if no_email:
        cmd.append("--no-email")

    sys.stdout.flush()
    t0 = time.time()
    result = subprocess.run(cmd, cwd=str(_ROOT))
    elapsed = time.time() - t0

    success = result.returncode == 0
    print(f"  Tournament {'completed' if success else 'FAILED'} in {elapsed:.0f}s\n", flush=True)
    return success, elapsed


# ---------------------------------------------------------------------------
# Surgical sweep steps (consolidated from standalone cron entries)
# ---------------------------------------------------------------------------

def _run_sweep_step(step_num, name, cmd):
    """Run a sweep step with full logging. Returns (success, elapsed)."""
    print("=" * 60)
    print(f"STEP {step_num}: {name}")
    print(f"  Started: {time.strftime('%H:%M:%S')}")
    print("=" * 60, flush=True)

    sys.stdout.flush()
    t0 = time.time()
    result = subprocess.run(cmd, cwd=str(_ROOT))
    elapsed = time.time() - t0

    success = result.returncode == 0
    status = "completed" if success else f"FAILED (exit code {result.returncode})"
    print(f"  {name} {status} in {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"  Finished: {time.strftime('%H:%M:%S')}\n", flush=True)
    return success, elapsed


def _profitable_tier2_args():
    """Return --tickers-file args pointing at the profitable-at-support subset,
    falling back to full Tier 2 pool if the filtered file is missing or empty.

    Used by downstream sweepers (STEP 7/8/9/10) to skip tickers that had zero
    trades at the support stage — they have no activity to optimize.
    """
    _profitable = _ROOT / "data" / ".profitable_tier2_pool.json"
    _fallback = _ROOT / "data" / ".tier2_pool.json"
    if _profitable.exists():
        try:
            with open(_profitable) as _f:
                _pool = json.load(_f)
            if _pool and len(_pool) >= 10:  # sanity: at least 10 tickers
                return ["--tickers-file", str(_profitable)]
        except (json.JSONDecodeError, OSError):
            pass
    return ["--tickers-file", str(_fallback)] if _fallback.exists() else []


def _build_profitable_tier2_pool():
    """After support sweep completes, build the profitable-tier2 pool:
    filter out tickers with zero support trades (they won't benefit from
    resistance/bounce/entry optimization either).
    """
    _results_path = _ROOT / "data" / "support_sweep_results.json"
    _tier2_path = _ROOT / "data" / ".tier2_pool.json"
    _profitable_path = _ROOT / "data" / ".profitable_tier2_pool.json"

    if not _results_path.exists() or not _tier2_path.exists():
        return

    try:
        with open(_results_path) as _f:
            _results = json.load(_f)
        with open(_tier2_path) as _f:
            _tier2 = json.load(_f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  *Profitable pool build skipped: {e}*", flush=True)
        return

    _profitable = []
    for _tk in _tier2:
        _entry = _results.get(_tk)
        if not isinstance(_entry, dict):
            continue
        _trades = (_entry.get("stats") or {}).get("trades", 0)
        if _trades > 0:
            _profitable.append(_tk)

    # Safety rail: if filter drops >70% of pool, something's off — use full pool
    if len(_profitable) < len(_tier2) * 0.30:
        print(f"  *Profitable pool only {len(_profitable)}/{len(_tier2)} tickers — "
              f"keeping full pool for downstream sweeps*", flush=True)
        return

    with open(_profitable_path, "w") as _f:
        json.dump(_profitable, _f)
    print(f"  Profitable Tier 2 pool: {len(_profitable)}/{len(_tier2)} tickers "
          f"(filtered zero-trade)", flush=True)


def step_resistance_sweep():
    """Step 7: Resistance parameter sweep."""
    return _run_sweep_step(7, "Resistance Sweep",
        [sys.executable, "tools/resistance_parameter_sweeper.py",
         "--workers", "8"] + _profitable_tier2_args())


def step_bounce_sweep():
    """Step 8: Bounce parameter sweep."""
    return _run_sweep_step(8, "Bounce Sweep",
        [sys.executable, "tools/bounce_parameter_sweeper.py",
         "--workers", "8"] + _profitable_tier2_args())


def step_entry_sweep():
    """Step 9: Entry parameter sweep."""
    return _run_sweep_step(9, "Entry Sweep",
        [sys.executable, "tools/entry_parameter_sweeper.py",
         "--workers", "8"] + _profitable_tier2_args())


def step_slippage_sweep():
    """Step 10: Slippage + pullback sweep."""
    return _run_sweep_step(10, "Slippage Sweep",
        [sys.executable, "tools/support_parameter_sweeper.py",
         "--stage", "slippage", "--workers", "8"] + _profitable_tier2_args())


def step_regime_exit_sweep():
    """Step 10b: Regime exit parameter sweep."""
    return _run_sweep_step("10b", "Regime Exit Sweep",
        [sys.executable, "tools/support_parameter_sweeper.py",
         "--stage", "regime_exit", "--workers", "8"] + _profitable_tier2_args())


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

    # Run-once guard: prevent double execution on same day
    _guard_path = _ROOT / "data" / ".reoptimize_guard"
    if _guard_path.exists() and not args.dry_run:
        try:
            guard_date = _guard_path.read_text().strip()
            if guard_date == date.today().isoformat():
                print(f"*Weekly reoptimize already ran today ({guard_date}). Skipping.*")
                return
        except Exception:
            pass
    if not args.dry_run:
        _guard_path.parent.mkdir(parents=True, exist_ok=True)
        _guard_path.write_text(date.today().isoformat())

    start = time.time()
    print(f"\nWeekly Re-optimization Pipeline — {date.today().isoformat()} ({args.strategy})")
    print(f"Started at {datetime.now().strftime('%H:%M:%S')}")
    print(f"{'=' * 60}\n")

    timings = {}

    # Clean up stale tier2 pool from previous run
    _stale_tier2 = _ROOT / "data" / ".tier2_pool.json"
    if _stale_tier2.exists():
        _stale_tier2.unlink()

    # Step 0: Refresh wick analysis for all tracked tickers
    print("=" * 60)
    print("STEP 0: Wick Analysis Refresh")
    print(f"  Started: {time.strftime('%H:%M:%S')}")
    print("=" * 60, flush=True)
    t0_wick = time.time()
    try:
        import warnings as _w
        _w.filterwarnings("ignore")
        import yfinance as yf

        _portfolio_path = _ROOT / "portfolio.json"
        with open(_portfolio_path) as _f:
            _port = json.load(_f)
        _tracked = sorted(set(_port.get("watchlist", [])) | set(_port.get("positions", {}).keys()))
        _tracked = [tk for tk in _tracked if not _port.get("positions", {}).get(tk, {}).get("winding_down")]

        sys.path.insert(0, str(_ROOT / "tools"))
        from wick_offset_analyzer import analyze_stock_data, _format_stock_report, _write_cache, load_capital_config

        _refreshed = 0
        _failed = 0
        _before_snapshot_buffer = {}  # ticker -> data dict for bullet drift snapshot
        for tk in _tracked:
            try:
                hist = yf.download(tk, period="13mo", progress=False)
                if hist.empty:
                    _failed += 1
                    continue
                if hasattr(hist.columns, "levels"):
                    hist.columns = hist.columns.get_level_values(0)
                _cap = load_capital_config(tk)
                data, err = analyze_stock_data(tk, hist, capital_config=_cap)
                if data:
                    _before_snapshot_buffer[tk] = data
                    report = _format_stock_report(tk, data)
                    _write_cache(tk, "wick_analysis.md", report)
                    _refreshed += 1
                else:
                    _failed += 1
            except Exception:
                _failed += 1
        _wick_elapsed = time.time() - t0_wick
        print(f"  Refreshed: {_refreshed}/{len(_tracked)} tickers ({_failed} failed)")
        print(f"  Wick refresh completed in {_wick_elapsed:.0f}s ({_wick_elapsed/60:.1f} min)")
        print(f"  Finished: {time.strftime('%H:%M:%S')}\n", flush=True)
        timings["wick_refresh"] = _wick_elapsed

        # Capture before-snapshot for bullet drift reporter
        try:
            from bullet_drift_report import write_before_snapshot
            write_before_snapshot(
                _tracked,
                _port.get("pending_orders", {}),
                _before_snapshot_buffer,
            )
            print("  Bullet drift snapshot captured.\n", flush=True)
        except Exception as _snap_exc:
            print(f"  *Bullet drift snapshot FAILED (non-fatal): {_snap_exc}*\n",
                  flush=True)
    except Exception as e:
        print(f"  *Wick refresh FAILED: {e}*\n", flush=True)
        timings["wick_refresh"] = time.time() - t0_wick

    # Step 0.5: Tier 1 — Pre-screen entire universe
    print("=" * 60)
    print("STEP 0.5: Universe Pre-Screen (Tier 1)")
    print(f"  Started: {time.strftime('%H:%M:%S')}")
    print("=" * 60, flush=True)
    t0_prescreen = time.time()
    # Use cached results if fresh (<24h), otherwise re-run
    _prescreen_path = _ROOT / "data" / "universe_prescreen_results.json"
    _ps_fresh = False
    if _prescreen_path.exists():
        import os as _os
        _ps_age = (time.time() - _os.path.getmtime(_prescreen_path)) / 3600
        _ps_fresh = _ps_age < 24
    _ps_cmd = [sys.executable, "tools/universe_prescreener.py", "--workers", "8"]
    if _ps_fresh:
        _ps_cmd.append("--cached")
        print(f"  Using cached pre-screen results ({_ps_age:.1f}h old)", flush=True)
    try:
        sys.stdout.flush()
        _ps_result = subprocess.run(
            _ps_cmd,
            cwd=str(_ROOT), timeout=14400,
        )
        if _ps_result.returncode != 0:
            print(f"  *Pre-screen failed (exit {_ps_result.returncode})*", file=sys.stderr, flush=True)
        else:
            _prescreen_path = _ROOT / "data" / "universe_prescreen_results.json"
            if _prescreen_path.exists():
                with open(_prescreen_path) as _f:
                    _ps = json.load(_f)
                print(f"  Pre-screened: {len(_ps.get('rankings', []))} tickers with signal")
    except subprocess.TimeoutExpired:
        print("  *Pre-screen timed out (4 hours)*", file=sys.stderr)
    except Exception as e:
        print(f"  *Pre-screen error: {e}*", file=sys.stderr)
    _prescreen_elapsed = time.time() - t0_prescreen
    print(f"  Completed in {_prescreen_elapsed:.0f}s ({_prescreen_elapsed/60:.1f} min)")
    print(f"  Finished: {time.strftime('%H:%M:%S')}\n", flush=True)
    timings["prescreen"] = _prescreen_elapsed

    # Build Tier 2 pool: tracked tickers + top pre-screen candidates
    _tier2_pool = list(_tracked)
    _prescreen_path = _ROOT / "data" / "universe_prescreen_results.json"
    if _prescreen_path.exists():
        try:
            with open(_prescreen_path) as _f:
                _ps = json.load(_f)
            _tracked_set = set(_tracked)
            for r in _ps.get("rankings", []):
                if len(_tier2_pool) >= 200:
                    break
                if r["ticker"] not in _tracked_set:
                    _tier2_pool.append(r["ticker"])
        except (json.JSONDecodeError, KeyError):
            pass
    _tier2_file = _ROOT / "data" / ".tier2_pool.json"
    with open(_tier2_file, "w") as _f:
        json.dump(_tier2_pool, _f)
    print(f"  Tier 2 pool: {len(_tier2_pool)} tickers "
          f"({len(_tracked)} tracked + {len(_tier2_pool) - len(_tracked)} challengers)\n",
          flush=True)

    # Step 0.75: Calibrate probabilities from prior promoted artifacts before
    # sweep scoring reads them. Non-fatal: scorer fails closed to raw probabilities.
    calib_ok, calib_t = step_probability_calibration(dry_run=args.dry_run)
    timings["probability_calibration"] = calib_t

    gate_ok, gate_report = step_model_complexity_gate()
    timings["model_complexity_gate"] = 0
    if not gate_ok:
        print("*Model complexity gate failed. Aborting before live artifacts can be consumed.*")
        return

    # Step 1-2: Sweep with cross-validation
    # Auto-reuse 5-min intraday cache if <7 days old (eliminates redundant re-download)
    _cache_pkl = _ROOT / "data" / "backtest" / "intraday_5min_60d.pkl"
    _cache_fresh = _cache_pkl.exists() and (
        (time.time() - _cache_pkl.stat().st_mtime) / 3600 < 168
    )
    if _cache_fresh and not args.skip_download:
        print(f"  Auto-reusing intraday cache "
              f"({(time.time() - _cache_pkl.stat().st_mtime) / 3600:.1f}h old)", flush=True)
    sweep_ok, t = step_sweep(
        use_cached=(args.skip_download or _cache_fresh),
        strategy=args.strategy,
    )
    timings["sweep"] = t
    if not sweep_ok:
        print("*Sweep failed. Aborting pipeline.*")
        return

    # Step 2b: Watchlist sweep (ensures every tracked ticker has a neural profile)
    wl_ok, wl_t = step_watchlist_sweep()
    timings["watchlist_sweep"] = wl_t

    # Build profitable-tier2 pool for downstream sweepers (STEP 7/8/9/10/10b)
    # to skip zero-trade tickers
    _build_profitable_tier2_pool()

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

    # Step 6: Skipped — pre-screener (Step 0.5) covers all universe passers
    # and Step 2 sweeps the top 200. The old 15-ticker candidate sweep is redundant.
    timings["candidate_sweep"] = 0

    # Steps 7-10: Surgical sweeps (each independent, continue on failure)
    print(f"\n{'='*60}")
    print(f"SURGICAL SWEEPS — Starting 4 sweep stages at {time.strftime('%H:%M:%S')}")
    print(f"{'='*60}\n", flush=True)
    sweep_failures = []
    for step_name, step_fn in [
        ("resistance", step_resistance_sweep),
        ("bounce", step_bounce_sweep),
        ("entry", step_entry_sweep),
        # slippage is now folded into STEP 2 via --stage all (Fix D)
        ("regime_exit", step_regime_exit_sweep),
    ]:
        try:
            ok, t = step_fn()
            timings[step_name] = t
            if not ok:
                sweep_failures.append(step_name)
                print(f"  *** {step_name} FAILED — continuing to next sweep ***\n",
                      flush=True)
        except Exception as e:
            print(f"  *** {step_name} EXCEPTION: {e} ***\n", flush=True)
            sweep_failures.append(step_name)
            timings[step_name] = 0

    if sweep_failures:
        print(f"\n  WARNING: {len(sweep_failures)} sweep(s) failed: "
              f"{', '.join(sweep_failures)}")
    else:
        print(f"\n  All 4 surgical sweeps completed successfully.")

    # Step 11: Tournament (all sweep data now complete)
    if not args.dry_run:
        tour_ok, tour_t = step_tournament(no_email=args.no_email)
    else:
        tour_ok, tour_t = step_tournament(dry_run=True, no_email=True)
    timings["tournament"] = tour_t

    # Step 12: Bullet drift report
    print("=" * 60)
    print("STEP 12: Bullet Drift Report")
    print(f"  Started: {time.strftime('%H:%M:%S')}")
    print("=" * 60, flush=True)
    t_drift = time.time()
    try:
        from bullet_drift_report import generate_drift_report
        drift = generate_drift_report(dry_run=args.dry_run)
        drift_status = drift.get("status", "OK")
        drift_elapsed = time.time() - t_drift
        drift_tickers = len(drift.get("tickers", {}))
        print(f"  Status: {drift_status} ({drift_tickers} tickers)")
        print(f"  Drift report completed in {drift_elapsed:.1f}s")
        print(f"  Finished: {time.strftime('%H:%M:%S')}\n", flush=True)
        timings["drift_report"] = drift_elapsed
    except Exception as _drift_exc:
        print(f"  *Drift report FAILED (non-fatal): {_drift_exc}*\n", flush=True)
        timings["drift_report"] = time.time() - t_drift

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
