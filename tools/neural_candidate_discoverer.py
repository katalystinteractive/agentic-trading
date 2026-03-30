"""Neural Candidate Discoverer — scan universe through neural dip strategy.

Applies the neural network (level-firing observers, subscription gates,
learned weights) to the full universe of pre-screened tickers to discover
the top 30 same-day dip-buy candidates ranked by out-of-sample P/L.

Pipeline:
  1. Load universe passers (~1,500 tickers)
  2. Download 60-day 5-min intraday data (chunked)
  3. Two-pass signal computation (arithmetic breadth first, graph second)
  4. Parameter sweep per ticker (600 combos including breadth)
  5. Cross-validation: train on first 2/3, validate on last 1/3
  6. Rank by validation P/L, apply gates
  7. Cluster top candidates
  8. Output top 30

Usage:
    python3 tools/neural_candidate_discoverer.py                    # full run
    python3 tools/neural_candidate_discoverer.py --cached           # use cached data
    python3 tools/neural_candidate_discoverer.py --top 50           # top 50 output
    python3 tools/neural_candidate_discoverer.py --chunk-size 300   # download chunk size
    python3 tools/neural_candidate_discoverer.py --dry-run          # no file writes
"""
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, date

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import yfinance as yf

from neural_dip_evaluator import _extract_open, _extract_price_at, DIP_CONFIG
from parameter_sweeper import (
    precompute_signals, sweep_ticker, evaluate_params,
    _extract_features, SWEEP_BREADTH, SWEEP_DIP_THRESHOLDS,
    SWEEP_TARGETS, SWEEP_STOPS,
)
from neural_dip_backtester import (
    download_daily, load_cached, compute_ranges_for_day,
    CACHE_DIR, DAILY_CACHE,
)
from trading_calendar import is_trading_day

_ROOT = Path(__file__).resolve().parent.parent
UNIVERSE_CACHE = _ROOT / "data" / "universe_screen_cache.json"
INTRADAY_CACHE = CACHE_DIR / "universe_intraday_cache.pkl"
RESULTS_PATH = _ROOT / "data" / "neural_candidates.json"
RESULTS_MD = _ROOT / "data" / "neural_candidates.md"


# ---------------------------------------------------------------------------
# Stage 0: Universe loading
# ---------------------------------------------------------------------------

def load_universe_passers(min_swing=10, min_vol=500_000):
    """Load universe screen passers, apply gates."""
    if not UNIVERSE_CACHE.exists():
        print("*No universe cache. Run: python3 tools/universe_screener.py*")
        return []

    cache_age = (datetime.now() -
                 datetime.fromtimestamp(UNIVERSE_CACHE.stat().st_mtime)).days
    if cache_age > 7:
        print(f"*Warning: universe cache is {cache_age} days old (>7). "
              f"Consider: python3 tools/universe_screener.py --refresh*")

    with open(UNIVERSE_CACHE) as f:
        cache = json.load(f)

    passers = cache.get("passers", [])
    filtered = [
        p for p in passers
        if p.get("median_swing", 0) >= min_swing
        and p.get("avg_vol", 0) >= min_vol
    ]
    return filtered


def load_excluded_tickers():
    """Load tickers already in portfolio/watchlist."""
    try:
        with open(_ROOT / "portfolio.json") as f:
            portfolio = json.load(f)
        excluded = set(portfolio.get("watchlist", []))
        excluded.update(portfolio.get("positions", {}).keys())
        return excluded
    except Exception:
        return set()


# ---------------------------------------------------------------------------
# Stage 2: Chunked data download
# ---------------------------------------------------------------------------

def download_universe_intraday(tickers, chunk_size=300, delay=5,
                               use_cached=False):
    """Download 60-day 5-min data for universe tickers in chunks."""
    if use_cached and INTRADAY_CACHE.exists():
        print(f"Loading cached universe intraday data...")
        return load_cached(INTRADAY_CACHE)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    n_chunks = (len(tickers) + chunk_size - 1) // chunk_size
    print(f"Downloading 60-day 5-min data for {len(tickers)} tickers "
          f"in {n_chunks} chunks of {chunk_size}...")

    import pandas as pd
    all_data = []
    for i in range(0, len(tickers), chunk_size):
        chunk = tickers[i:i + chunk_size]
        chunk_num = i // chunk_size + 1
        print(f"  Chunk {chunk_num}/{n_chunks} ({len(chunk)} tickers)...",
              end=" ", flush=True)
        try:
            data = yf.download(chunk, period="60d", interval="5m",
                               progress=False)
            if not data.empty:
                all_data.append(data)
                print(f"{len(data)} bars", flush=True)
            else:
                print("empty", flush=True)
        except Exception as e:
            print(f"error: {e}", flush=True)

        if i + chunk_size < len(tickers):
            time.sleep(delay)

    if not all_data:
        print("*No intraday data downloaded.*")
        return None

    # Concatenate chunks
    if len(all_data) == 1:
        combined = all_data[0]
    else:
        combined = pd.concat(all_data, axis=1)

    # Cache
    import pickle
    with open(INTRADAY_CACHE, "wb") as f:
        pickle.dump(combined, f)
    print(f"Cached to {INTRADAY_CACHE}")

    return combined


# ---------------------------------------------------------------------------
# Stage 3: Two-pass signal computation
# ---------------------------------------------------------------------------

def compute_raw_breadth(tickers, trading_days, intraday, dip_thresh):
    """Pass 1: Arithmetic-only breadth computation. No graph."""
    n = len(tickers)
    breadth_per_day = {}

    for day in trading_days:
        day_bars = intraday[intraday.index.date == day]
        if len(day_bars) < 12:
            continue

        fh_bars = day_bars.iloc[:12]
        dip_count = 0
        for tk in tickers:
            try:
                o = _extract_open(fh_bars, tk, n)
                c = _extract_price_at(fh_bars, tk, 10, 30, n)
                dip_pct = round((o - c) / o * 100, 1) if o and c and o > 0 else 0
                if dip_pct >= dip_thresh:
                    dip_count += 1
            except Exception:
                continue

        breadth_per_day[day] = round(dip_count / n, 3) if n > 0 else 0

    return breadth_per_day


# ---------------------------------------------------------------------------
# Stage 5-6: Ranking and gating
# ---------------------------------------------------------------------------

def rank_and_gate(results, min_val_trades=5):
    """Rank by validation P/L, apply gates."""
    ranked = []
    for tk, r in results.items():
        cv = r.get("cross_validation")
        stats = r.get("stats", {})
        params = r.get("params")
        if not params:
            continue

        # Must have validation data
        if not cv or cv.get("trades", 0) < min_val_trades:
            continue

        # Positive validation P/L
        val_pnl = cv.get("pnl", 0)
        if val_pnl <= 0:
            continue

        # Overfitting check: positive train but negative validation
        train_pnl = stats.get("total_pnl", 0)
        if train_pnl > 0 and val_pnl < 0:
            continue

        ranked.append({
            "ticker": tk,
            "val_pnl": val_pnl,
            "train_pnl": train_pnl,
            "val_trades": cv.get("trades", 0),
            "val_win_rate": cv.get("win_rate", 0),
            "train_trades": stats.get("trades", 0),
            "train_win_rate": stats.get("win_rate", 0),
            "params": params,
            "features": r.get("features"),
        })

    ranked.sort(key=lambda x: x["val_pnl"], reverse=True)
    return ranked


# ---------------------------------------------------------------------------
# Stage 8: Output
# ---------------------------------------------------------------------------

def write_results(ranked, top_n, meta):
    """Write neural_candidates.json and .md."""
    output = {
        "_meta": {
            "source": "neural_candidate_discoverer.py",
            "updated": date.today().isoformat(),
            **meta,
            "top_n": top_n,
        },
        "candidates": ranked[:top_n],
    }

    with open(RESULTS_PATH, "w") as f:
        json.dump(output, f, indent=2, default=str)

    # Markdown table
    lines = [
        f"# Neural Candidate Discovery — {date.today().isoformat()}\n",
        f"*Universe: {meta.get('universe_passers', '?')} passers, "
        f"{meta.get('tickers_swept', '?')} swept, "
        f"{meta.get('passed_gates', '?')} passed gates*\n",
        f"| # | Ticker | Val P/L | Val Trades | Val WR | Train P/L | "
        f"Dip | Target | Stop | Breadth |",
        f"| :--- | :--- | :--- | :--- | :--- | :--- | "
        f":--- | :--- | :--- | :--- |",
    ]
    for i, c in enumerate(ranked[:top_n], 1):
        p = c["params"]
        lines.append(
            f"| {i} | {c['ticker']} | ${c['val_pnl']:.2f} | "
            f"{c['val_trades']} | {c['val_win_rate']}% | "
            f"${c['train_pnl']:.2f} | "
            f"{p['dip_threshold']}% | {p['target_pct']}% | "
            f"{p['stop_pct']}% | {p.get('breadth_threshold', 0.5):.0%} |"
        )

    with open(RESULTS_MD, "w") as f:
        f.write("\n".join(lines) + "\n")

    return RESULTS_PATH, RESULTS_MD


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Neural Candidate Discoverer")
    parser.add_argument("--top", type=int, default=30,
                        help="Number of top candidates to output (default: 30)")
    parser.add_argument("--cached", action="store_true",
                        help="Use cached intraday data")
    parser.add_argument("--chunk-size", type=int, default=300,
                        help="yfinance download chunk size (default: 300)")
    parser.add_argument("--min-swing", type=float, default=10,
                        help="Minimum median swing %% (default: 10)")
    parser.add_argument("--min-vol", type=float, default=500_000,
                        help="Minimum average volume (default: 500K)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't write output files")
    args = parser.parse_args()

    start = time.time()
    print(f"Neural Candidate Discoverer — {date.today().isoformat()}")
    print(f"{'=' * 60}\n")

    # Stage 0-1: Load universe
    passers = load_universe_passers(args.min_swing, args.min_vol)
    if not passers:
        return
    excluded = load_excluded_tickers()
    candidates = [p for p in passers if p["ticker"] not in excluded]
    tickers = [c["ticker"] for c in candidates]
    n = len(tickers)

    print(f"Universe: {len(passers)} passers, {len(excluded)} excluded, "
          f"{n} to sweep")
    combos = (len(SWEEP_TARGETS) * len(SWEEP_STOPS) *
              len(SWEEP_DIP_THRESHOLDS) * len(SWEEP_BREADTH))
    print(f"Sweep grid: {combos} combos/ticker\n")

    # Stage 2: Download data
    intraday = download_universe_intraday(
        tickers, chunk_size=args.chunk_size, use_cached=args.cached)
    if intraday is None or intraday.empty:
        print("*No intraday data. Aborting.*")
        return

    # Download daily for range computation
    if args.cached and DAILY_CACHE.exists():
        daily = load_cached(DAILY_CACHE)
    else:
        daily = download_daily(tickers, 90)
    if daily is None:
        daily = intraday

    all_dates = sorted(set(intraday.index.date))
    trading_days = [d for d in all_dates if is_trading_day(d)]
    print(f"Trading days: {len(trading_days)}\n")

    # Stage 3: Two-pass signal computation
    # Pass 1: Quick breadth check (arithmetic only)
    min_breadth = min(SWEEP_BREADTH)
    print(f"Pass 1: Computing raw breadth (min threshold={min_breadth:.0%})...")
    # Use smallest dip_threshold for max signal days
    breadth = compute_raw_breadth(
        tickers, trading_days, intraday, min(SWEEP_DIP_THRESHOLDS))
    signal_days = [d for d, b in breadth.items() if b >= min_breadth]
    print(f"  {len(signal_days)}/{len(trading_days)} days pass "
          f"breadth >= {min_breadth:.0%}\n")

    if not signal_days:
        print("*No signal days at minimum breadth threshold. No candidates.*")
        return

    # Pass 2: Full graph-based signal computation (only on signal days)
    print(f"Pass 2: Pre-computing signals on {len(signal_days)} signal days...")
    signals = precompute_signals(tickers, signal_days, intraday, daily, n)

    # Determine train/validate split
    all_signal_day_strs = sorted(set(
        ds for thresh_signals in signals.values()
        for ds in thresh_signals.keys()
    ))
    if len(all_signal_day_strs) >= 6:
        split_idx = len(all_signal_day_strs) * 2 // 3
        train_days = set(all_signal_day_strs[:split_idx])
        val_days = set(all_signal_day_strs[split_idx:])
    else:
        train_days = None
        val_days = None
    if train_days:
        print(f"Cross-validation: train={len(train_days)} days, "
              f"validate={len(val_days)} days\n")

    # Stage 4: Sweep each ticker
    print(f"Sweeping {n} tickers...")
    results = {}
    for i, tk in enumerate(tickers):
        params, stats, trades, features = sweep_ticker(
            tk, signals, day_filter=train_days)

        if params:
            cv = None
            if val_days:
                cv = evaluate_params(tk, params, signals, day_filter=val_days)

            results[tk] = {
                "params": params, "stats": stats,
                "trades": trades, "features": features,
                "cross_validation": cv,
            }

        if (i + 1) % 100 == 0:
            print(f"  [{i+1}/{n}] swept...", flush=True)

    with_params = len(results)
    print(f"\n{with_params}/{n} tickers had profitable combos")

    # Stage 5-6: Rank and gate
    ranked = rank_and_gate(results)
    print(f"{len(ranked)} passed validation gates\n")

    if not ranked:
        print("*No candidates passed all gates.*")
        return

    # Stage 7: Cluster top candidates (if enough)
    if len(ranked) >= 3:
        try:
            from ticker_clusterer import (
                build_feature_matrix, find_optimal_clusters,
                compute_cluster_profiles,
            )
            from sklearn.preprocessing import StandardScaler

            cluster_tickers = [r["ticker"] for r in ranked[:50]]
            cluster_data = {r["ticker"]: {
                "params": r["params"],
                "stats": {"total_pnl": r["train_pnl"],
                          "trades": r["train_trades"],
                          "win_rate": r["train_win_rate"]},
                "features": r["features"],
            } for r in ranked[:50]}

            _, X, _ = build_feature_matrix(cluster_data)
            if len(X) >= 3:
                scaler = StandardScaler()
                X_scaled = scaler.fit_transform(X)
                n_clusters, silhouette, labels = find_optimal_clusters(X_scaled)
                for i, r in enumerate(ranked[:50]):
                    if i < len(labels):
                        r["cluster"] = int(labels[i])
                print(f"Clustered top {min(50, len(ranked))} into "
                      f"{n_clusters} clusters (silhouette={silhouette})")
        except Exception as e:
            print(f"*Clustering skipped: {e}*")

    # Stage 8: Output
    meta = {
        "universe_passers": len(passers),
        "excluded": len(excluded),
        "tickers_swept": n,
        "with_params": with_params,
        "passed_gates": len(ranked),
        "trading_days": len(trading_days),
        "signal_days": len(signal_days),
        "combos_per_ticker": combos,
    }

    # Print top results
    print(f"\n{'=' * 60}")
    print(f"Top {min(args.top, len(ranked))} Neural Dip Candidates")
    print(f"{'=' * 60}\n")
    print(f"| # | Ticker | Val P/L | VTrades | VWR | Train P/L | "
          f"Dip | Tgt | Stop | Breadth |")
    print(f"| :--- | :--- | :--- | :--- | :--- | :--- | "
          f":--- | :--- | :--- | :--- |")
    for i, c in enumerate(ranked[:args.top], 1):
        p = c["params"]
        print(f"| {i} | {c['ticker']} | ${c['val_pnl']:.2f} | "
              f"{c['val_trades']} | {c['val_win_rate']}% | "
              f"${c['train_pnl']:.2f} | "
              f"{p['dip_threshold']}% | {p['target_pct']}% | "
              f"{p['stop_pct']}% | {p.get('breadth_threshold', 0.5):.0%} |")

    if not args.dry_run:
        jp, mp = write_results(ranked, args.top, meta)
        print(f"\nResults: {jp}")
        print(f"Report:  {mp}")

    elapsed = time.time() - start
    print(f"\nTotal time: {elapsed:.0f}s ({elapsed/60:.1f} min)")


if __name__ == "__main__":
    main()
