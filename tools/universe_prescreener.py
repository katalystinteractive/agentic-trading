"""Universe pre-screener — Stage 1 sweep across all universe passers.

Batch-downloads price data for ALL tickers in ~2 minutes (500-ticker chunks),
then runs threshold sweep (30 combos x 4 periods) per ticker with 8 workers.

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
import pickle
from pathlib import Path
from datetime import datetime, timedelta
from multiprocessing import Pool

sys.path.insert(0, str(Path(__file__).resolve().parent))

import warnings
warnings.filterwarnings("ignore")
import numpy as np
import yfinance as yf

from support_parameter_sweeper import (
    _simulate_with_config, THRESHOLD_GRID, SWEEP_PERIODS,
)
from multi_period_scorer import compute_composite
from backtest_data_collector import REGIME_INDICES

_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = _ROOT / "data" / "universe_screen_cache.json"
OUTPUT_PATH = _ROOT / "data" / "universe_prescreen_results.json"
BATCH_CACHE_DIR = _ROOT / "data" / "prescreen_cache"

CHUNK_SIZE = 500
CHUNK_PAUSE = 3.0  # seconds between yfinance chunks


def load_universe_tickers():
    """Load ticker symbols from universe screening cache."""
    if not CACHE_PATH.exists():
        print("*No universe cache. Run universe_screener.py first.*", file=sys.stderr)
        return []
    with open(CACHE_PATH) as f:
        cache = json.load(f)
    return [p["ticker"] for p in cache.get("passers", [])]


def batch_download(tickers, months=12):
    """Batch-download price data for all tickers in chunks.

    Downloads ~500 tickers per yfinance call (~30s each).
    Returns {ticker: DataFrame} dict with OHLCV data.
    """
    warmup_days = 13 * 30 + 70  # 13 months wick lookback + 50-SMA warmup
    end_date = datetime.now()
    sim_start = end_date - timedelta(days=months * 30)
    data_start = sim_start - timedelta(days=warmup_days)

    start_str = data_start.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    # Check cache
    BATCH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = BATCH_CACHE_DIR / "batch_prices.pkl"
    if cache_file.exists():
        import os
        age_hours = (time.time() - os.path.getmtime(cache_file)) / 3600
        if age_hours < 24:
            print(f"  Using cached batch data ({age_hours:.1f}h old)")
            with open(cache_file, "rb") as f:
                return pickle.load(f)

    all_prices = {}
    chunks = [tickers[i:i + CHUNK_SIZE] for i in range(0, len(tickers), CHUNK_SIZE)]

    print(f"  Downloading {len(tickers)} tickers in {len(chunks)} chunks "
          f"({start_str} to {end_str})...")

    for ci, chunk in enumerate(chunks):
        t0 = time.time()
        try:
            hist = yf.download(chunk, start=start_str, end=end_str,
                               auto_adjust=True, progress=False, threads=True)
            if hist.empty:
                print(f"    Chunk {ci + 1}/{len(chunks)}: empty", flush=True)
                continue

            # Extract per-ticker DataFrames
            if len(chunk) == 1:
                tk = chunk[0]
                if not hist.empty and len(hist) > 20:
                    all_prices[tk] = hist
            else:
                for tk in chunk:
                    try:
                        tk_df = hist.xs(tk, level=1, axis=1) if hasattr(hist.columns, "levels") else hist
                        if len(tk_df.dropna()) > 20:
                            all_prices[tk] = tk_df
                    except (KeyError, TypeError):
                        continue

            elapsed = time.time() - t0
            print(f"    Chunk {ci + 1}/{len(chunks)}: {len(chunk)} tickers, "
                  f"{elapsed:.1f}s, {len(all_prices)} total", flush=True)
        except Exception as e:
            print(f"    Chunk {ci + 1}/{len(chunks)}: FAILED ({e})", flush=True)

        if ci < len(chunks) - 1:
            time.sleep(CHUNK_PAUSE)

    # Download regime data (VIX + indices) once
    try:
        regime_tickers = REGIME_INDICES + ["^VIX"]
        regime_hist = yf.download(regime_tickers, start=start_str, end=end_str,
                                  auto_adjust=True, progress=False)
        all_prices["_regime_hist"] = regime_hist
    except Exception:
        pass

    # Cache for 24 hours
    with open(cache_file, "wb") as f:
        pickle.dump(all_prices, f)

    print(f"  Downloaded: {len(all_prices)} tickers with data")
    return all_prices


def build_regime_data(regime_hist):
    """Build regime classification from VIX + index data.

    Matches backtest_data_collector's inline logic: VIX thresholds (20/30)
    combined with indices above/below 50-SMA for 3-state classification.
    """
    regime = {}
    try:
        multi = hasattr(regime_hist.columns, "levels")
        vix = regime_hist["Close"]["^VIX"].dropna() if multi else regime_hist["Close"].dropna()

        # Build 50-SMA for regime indices
        index_data = {}
        for idx in REGIME_INDICES:
            try:
                idx_close = regime_hist["Close"][idx].dropna() if multi else None
                if idx_close is not None and len(idx_close) > 50:
                    index_data[idx] = {
                        "close": idx_close,
                        "sma50": idx_close.rolling(window=50, min_periods=50).mean(),
                    }
            except (KeyError, TypeError):
                continue

        for dt in vix.index:
            vix_val = float(vix.loc[dt])
            dt_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)

            above_count = 0
            total_indices = 0
            for idx, idata in index_data.items():
                if dt in idata["close"].index and dt in idata["sma50"].index:
                    close = float(idata["close"].loc[dt])
                    sma = float(idata["sma50"].loc[dt])
                    if not np.isnan(sma):
                        total_indices += 1
                        if close > sma:
                            above_count += 1

            if total_indices == 0:
                r = "Neutral"
            elif vix_val < 20 and above_count > total_indices / 2:
                r = "Risk-On"
            elif vix_val > 30 and above_count <= total_indices / 2:
                r = "Risk-Off"
            else:
                r = "Neutral"

            regime[dt_str] = {"regime": r, "vix": round(vix_val, 2)}
    except Exception:
        pass
    return regime


def build_price_data_for_ticker(ticker, ticker_df):
    """Convert a single-ticker DataFrame into the format run_simulation expects.

    Returns {ticker: {"Open": Series, "High": Series, ...}}
    """
    return {ticker: {
        "Open": ticker_df["Open"] if "Open" in ticker_df else ticker_df.iloc[:, 0],
        "High": ticker_df["High"] if "High" in ticker_df else ticker_df.iloc[:, 1],
        "Low": ticker_df["Low"] if "Low" in ticker_df else ticker_df.iloc[:, 2],
        "Close": ticker_df["Close"] if "Close" in ticker_df else ticker_df.iloc[:, 3],
        "Volume": ticker_df["Volume"] if "Volume" in ticker_df else ticker_df.iloc[:, 4],
    }}


def prescreen_ticker_with_data(ticker, price_data, regime_data):
    """Run Stage 1 (30 combos x 4 periods) using pre-fetched data.

    No yfinance calls — all data passed in.
    Returns dict with ticker, composite, best_params, or None.
    """
    try:
        results_by_period = {}
        for months in SWEEP_PERIODS:
            wick_cache = {}
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
                        price_data=price_data, regime_data=regime_data,
                        wick_cache=wick_cache,
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

        best_12mo = results_by_period.get(12, {})
        return {
            "ticker": ticker,
            "composite": round(composite, 2),
            "best_params": best_12mo.get("params"),
            "sells_12mo": best_12mo.get("sells", 0),
            "win_rate_12mo": best_12mo.get("win_rate", 0),
        }
    except Exception:
        return None


# Module-level globals for multiprocessing workers
_WORKER_PRICES = None
_WORKER_REGIME = None


def _init_worker(cache_path):
    """Initialize worker process: load batch price data from shared cache."""
    global _WORKER_PRICES, _WORKER_REGIME
    with open(cache_path, "rb") as f:
        all_data = pickle.load(f)
    regime_hist = all_data.pop("_regime_hist", None)
    _WORKER_PRICES = all_data
    _WORKER_REGIME = build_regime_data(regime_hist) if regime_hist is not None else {}


def _worker_prescreen(ticker):
    """Worker function: prescreen a single ticker using process-local data."""
    if ticker not in _WORKER_PRICES:
        return None
    pd = build_price_data_for_ticker(ticker, _WORKER_PRICES[ticker])
    return prescreen_ticker_with_data(ticker, pd, _WORKER_REGIME)


# Minimum Active-zone support levels required for a ticker to enter the Tier 2 pool.
# Tickers with fewer Active-zone levels can't support a surgical bullet ladder
# (bullet_recommender rejects them as "insufficient for surgical bullet stacking"
# anyway). Gating here saves downstream onboarding time (~22 min/ticker).
MIN_SUPPORT_LEVELS_FOR_TIER2 = 3


def _worker_density_check(ticker):
    """Worker: count Active-zone support levels for a ticker using cached price data.

    Counts Active-zone specifically (NOT any-zone). This matches
    bullet_recommender's actual rejection criterion — it rejects tickers with
    <3 Active-zone levels as "insufficient for surgical bullet stacking."
    Counting all-zones lets tickers with lots of Reserve levels but thin Active
    structure slip through the gate, defeating the purpose.

    Returns (ticker, active_level_count). Count is 0 on any failure; caller
    treats failures the same as thin tickers (excluded from Tier 2).
    """
    if ticker not in _WORKER_PRICES:
        return ticker, 0
    try:
        from wick_offset_analyzer import analyze_stock_data
        hist = _WORKER_PRICES[ticker]
        # Flatten multi-column if yfinance returned a MultiIndex
        if hasattr(hist.columns, "levels"):
            hist = hist.copy()
            hist.columns = hist.columns.get_level_values(0)
        data, err = analyze_stock_data(ticker, hist)
        if err or not data:
            return ticker, 0
        # Match bullet_recommender's exact rejection criterion
        # (tools/bullet_recommender.py:336-339). Count levels that satisfy ALL:
        #   - recommended_buy is not None and < current_price
        #   - zone == "Active" (strict — NOT zone_promoted Buffer)
        #   - effective_tier not in {"Skip", ""}
        current_price = data.get("current_price")
        if not current_price:
            return ticker, 0
        active_count = 0
        for lvl in data.get("levels", []):
            rb = lvl.get("recommended_buy")
            if rb is None or rb >= current_price:
                continue
            if lvl.get("zone") != "Active":
                continue
            tier = lvl.get("effective_tier") or lvl.get("tier") or ""
            if tier in ("Skip", ""):
                continue
            active_count += 1
        return ticker, active_count
    except Exception:
        return ticker, 0


def apply_density_gate(rankings, cache_path, min_levels=MIN_SUPPORT_LEVELS_FOR_TIER2, workers=8):
    """Filter rankings to tickers with >= min_levels raw support levels.

    Uses the same multiprocessing Pool infrastructure as run_prescreen — each
    worker reuses its process-local price cache (no per-ticker yfinance calls).

    Returns (filtered_rankings, level_counts_dict). Each passing ranking entry
    gets a new `level_count` field for downstream visibility.
    """
    if not rankings:
        return rankings, {}

    tickers = [r["ticker"] for r in rankings]
    total = len(tickers)
    print(f"Phase 2.5: Support-level-density gate (min {min_levels} levels)")
    t0 = time.time()

    level_counts = {}
    with Pool(processes=workers, initializer=_init_worker,
              initargs=(str(cache_path),)) as pool:
        for i, (ticker, count) in enumerate(
            pool.imap_unordered(_worker_density_check, tickers), 1,
        ):
            level_counts[ticker] = count
            if i % 100 == 0:
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                eta = (total - i) / rate if rate > 0 else 0
                print(f"  Progress: {i}/{total} ({rate:.1f}/s, ETA {eta:.0f}s)",
                      flush=True)

    filtered = [r for r in rankings if level_counts.get(r["ticker"], 0) >= min_levels]
    gated_out = total - len(filtered)
    elapsed = time.time() - t0
    print(f"  Density gate: {gated_out} gated out (<{min_levels} levels), "
          f"{len(filtered)} kept. {elapsed:.0f}s ({elapsed/60:.1f} min)",
          flush=True)

    # Attach level_count to each passing ranking for downstream visibility
    for r in filtered:
        r["level_count"] = level_counts.get(r["ticker"], 0)

    return filtered, level_counts


def run_prescreen(tickers, cache_path, workers=8):
    """Pre-screen all tickers using multiprocessing Pool.

    Each worker loads the batch cache once via _init_worker, then
    processes tickers from the shared pool. True process-level parallelism.
    """
    total = len(tickers)
    results = []
    failed = 0

    t0 = time.time()
    with Pool(processes=workers, initializer=_init_worker,
              initargs=(str(cache_path),)) as pool:
        for i, r in enumerate(pool.imap_unordered(_worker_prescreen, tickers), 1):
            if i % 100 == 0:
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                eta = (total - i) / rate if rate > 0 else 0
                print(f"  Progress: {i}/{total} ({rate:.1f}/s, "
                      f"ETA {eta:.0f}s)", flush=True)
            if r:
                results.append(r)
            else:
                failed += 1

    elapsed = time.time() - t0
    print(f"  Simulations: {len(results)} with signal, "
          f"{failed} failed/no-signal, {elapsed:.0f}s ({elapsed/60:.1f} min)")

    return sorted(results, key=lambda x: -x["composite"])


def save_results(rankings, total_screened):
    """Save pre-screen results to own file (no contamination)."""
    output = {
        "_meta": {
            "source": "universe_prescreener.py",
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "tickers_screened": total_screened,
            "tickers_with_signal": len(rankings),
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
              f"{meta.get('tickers_with_signal', '?')} tickers with signal")
        print_top(rankings, args.top)
        return

    tickers = load_universe_tickers()
    if not tickers:
        return

    print(f"Pre-screening {len(tickers)} universe passers "
          f"with {args.workers} workers...")
    print(f"Grid: {len(THRESHOLD_GRID['sell_default'])} sell x "
          f"{len(THRESHOLD_GRID['cat_hard_stop'])} stop x "
          f"{len(SWEEP_PERIODS)} periods = "
          f"{len(THRESHOLD_GRID['sell_default']) * len(THRESHOLD_GRID['cat_hard_stop']) * len(SWEEP_PERIODS)} "
          f"sims/ticker\n")

    # Phase 1: Batch download ALL data (~2 min)
    print("Phase 1: Batch data download")
    t0 = time.time()
    all_prices = batch_download(tickers)
    download_time = time.time() - t0
    print(f"  Download completed in {download_time:.0f}s ({download_time/60:.1f} min)\n")

    # Phase 1.5: Export per-ticker data to candidate-gate format
    # so downstream pipeline steps (_collect_once) find cached data and skip re-downloading
    print("Phase 1.5: Exporting per-ticker data for pipeline reuse")
    t0_export = time.time()
    _gate_dir = _ROOT / "data" / "backtest" / "candidate-gate"
    _gate_dir.mkdir(parents=True, exist_ok=True)
    regime_hist = all_prices.get("_regime_hist")
    regime_data_export = build_regime_data(regime_hist) if regime_hist is not None else {}
    _exported = 0
    for tk in all_prices:
        if tk.startswith("_"):
            continue
        tk_dir = _gate_dir / tk
        price_pkl = tk_dir / "price_data.pkl"
        # Skip if already fresh (<24h)
        if price_pkl.exists():
            try:
                import os
                if (time.time() - os.path.getmtime(price_pkl)) / 3600 < 24:
                    continue
            except OSError:
                pass
        tk_dir.mkdir(parents=True, exist_ok=True)
        try:
            tk_price_data = build_price_data_for_ticker(tk, all_prices[tk])
            with open(price_pkl, "wb") as f:
                pickle.dump(tk_price_data, f)
            with open(tk_dir / "regime_data.json", "w") as f:
                json.dump(regime_data_export, f)
            with open(tk_dir / "config.json", "w") as f:
                json.dump({"tickers": [tk], "earnings_dates": {}}, f)
            _exported += 1
        except Exception:
            pass
    print(f"  Exported {_exported} tickers to candidate-gate "
          f"({time.time() - t0_export:.0f}s)\n")

    # Retention cap: remove candidate-gate subdirs older than 90 days.
    # historical_trade_trainer.py consumes this directory; 90 days ≈ 13 weekly runs.
    _KEEP_AGE_DAYS = 90
    _cutoff = time.time() - _KEEP_AGE_DAYS * 86400
    _pruned = 0
    import shutil
    for _d in _gate_dir.iterdir():
        if _d.is_dir() and _d.stat().st_mtime < _cutoff:
            try:
                shutil.rmtree(_d)
                _pruned += 1
            except OSError:
                pass
    if _pruned:
        print(f"  Pruned {_pruned} candidate-gate dirs older than {_KEEP_AGE_DAYS} days\n")

    # Phase 2: Run simulations using multiprocessing (each worker loads cache)
    print("Phase 2: Threshold sweep simulations")
    ticker_list = [tk for tk in all_prices if not tk.startswith("_")]
    cache_path = BATCH_CACHE_DIR / "batch_prices.pkl"
    rankings = run_prescreen(ticker_list, cache_path, workers=args.workers)
    # Phase 2.5: support-level-density gate — drop tickers that can't support
    # a surgical bullet ladder. Uses the same cached price data, so no new
    # yfinance round-trips. ~3-7 min wall-clock for 1,585 tickers at 8 workers.
    rankings, _level_counts = apply_density_gate(
        rankings, cache_path, workers=args.workers,
    )
    save_results(rankings, len(tickers))
    print_top(rankings, args.top)


if __name__ == "__main__":
    main()
