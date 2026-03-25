"""Surgical Candidate Screener — batch swing screen + deep wick analysis.

Collects ALL data upfront so workflow agents can evaluate without network calls.
Stage 1: Batch swing screen ~150 tickers through surgical gates.
Stage 2: Deep wick analysis on top 20 passers (or 50 with --expanded).
Stage 3: Build screening_data.json with all results + portfolio context.

Usage:
    python3 tools/surgical_screener.py                      # default (150 tickers, top 20 wick)
    python3 tools/surgical_screener.py --universe           # use dynamic universe passers
    python3 tools/surgical_screener.py --expanded           # top 50 wick analysis
    python3 tools/surgical_screener.py --universe --expanded # both
"""
import argparse
import json
import sys
import datetime
import numpy as np
import yfinance as yf
import pandas as pd
from pathlib import Path

# Same-directory imports (our convention)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bounce_screener import TICKERS, get_excluded_tickers
from wick_offset_analyzer import analyze_stock_data, load_capital_config
from shared_utils import load_cycle_timing
from cycle_timing_analyzer import analyze_ticker as _analyze_cycle_timing

ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = ROOT / "portfolio.json"
OUTPUT_PATH = ROOT / "screening_data.json"

# --- Surgical gates ---
MIN_SWING_PCT = 10.0
MIN_CONSISTENCY_PCT = 80.0
MIN_PRICE = 3.0
MAX_PRICE = 60.0
MIN_AVG_VOL = 500_000

# Sector mapping — centralized in sector_registry.py
from sector_registry import FINE_SECTOR_MAP as SECTOR_MAP


def batch_swing_screen():
    """Screen ~150 tickers through surgical gates using batch download."""
    excluded = get_excluded_tickers()
    unique = list(dict.fromkeys(t for t in TICKERS if t not in excluded))
    print(f"[Stage 1] Screening {len(unique)} tickers (excluded {len(excluded)} portfolio tickers)...")

    # Batch download 400 days
    try:
        data = yf.download(unique, period="400d", interval="1d", progress=False, threads=True)
    except Exception as e:
        print(f"*Error in batch download: {e}*")
        return []

    passers = []
    gate_stats = {"price": 0, "volume": 0, "swing": 0, "consistency": 0, "data": 0}

    for ticker in unique:
        try:
            # Extract per-ticker data
            if isinstance(data.columns, pd.MultiIndex):
                close = data["Close"][ticker].dropna()
                high = data["High"][ticker].dropna()
                low = data["Low"][ticker].dropna()
                open_prices = data["Open"][ticker].dropna()
                volume = data["Volume"][ticker].dropna()
            else:
                close = data["Close"].dropna()
                high = data["High"].dropna()
                low = data["Low"].dropna()
                open_prices = data["Open"].dropna()
                volume = data["Volume"].dropna()

            if len(close) < 60:
                gate_stats["data"] += 1
                continue

            price = float(close.iloc[-1])
            avg_vol = float(volume.tail(20).mean())

            # Price gate
            if not (MIN_PRICE <= price <= MAX_PRICE):
                gate_stats["price"] += 1
                continue

            # Volume gate
            if avg_vol < MIN_AVG_VOL:
                gate_stats["volume"] += 1
                continue

            # Monthly swing — build from the batch data
            df = pd.DataFrame({"High": high, "Low": low, "Close": close})
            monthly = df.resample("ME").agg({"High": "max", "Low": "min"})
            monthly = monthly.dropna()
            # Drop incomplete current month
            now = datetime.datetime.now()
            if len(monthly) > 0 and monthly.index[-1].month == now.month and monthly.index[-1].year == now.year:
                monthly = monthly.iloc[:-1]
            if len(monthly) < 3:
                gate_stats["data"] += 1
                continue

            swings = ((monthly["High"] - monthly["Low"]) / monthly["Low"] * 100).values
            median_swing = float(np.median(swings))
            above_thresh = sum(1 for s in swings if s >= MIN_SWING_PCT)
            consistency = round(above_thresh / len(swings) * 100, 1)
            recent_swing = float(np.median(swings[-4:])) if len(swings) >= 4 else median_swing
            compression_ratio = round(recent_swing / median_swing, 2) if median_swing > 0 else 1.0

            # Daily range metrics
            daily_ranges = ((high - low) / low * 100).values
            median_daily_range = float(np.median(daily_ranges[-21:])) if len(daily_ranges) >= 21 else float(np.median(daily_ranges))
            days_above_3pct = round(sum(1 for d in daily_ranges[-63:] if d >= 3.0) / min(63, len(daily_ranges)) * 100, 1) if len(daily_ranges) > 0 else 0

            # Dip-recovery metrics (for daily range strategy)
            open_to_low_pct = ((open_prices - low) / open_prices * 100).values
            low_to_close_pct = ((close - low) / low * 100).values
            median_open_to_low = round(float(np.median(open_to_low_pct[-21:])), 2) if len(open_to_low_pct) >= 21 else round(float(np.median(open_to_low_pct)), 2)
            median_low_to_close = round(float(np.median(low_to_close_pct[-21:])), 2) if len(low_to_close_pct) >= 21 else round(float(np.median(low_to_close_pct)), 2)
            dip_days = [(otl, ltc) for otl, ltc in zip(open_to_low_pct[-63:], low_to_close_pct[-63:]) if otl > 1.0]
            dip_recovery_ratio = round(sum(1 for _, ltc in dip_days if ltc > 1.5) / max(len(dip_days), 1) * 100, 1)

            # Swing gate
            if median_swing < MIN_SWING_PCT:
                gate_stats["swing"] += 1
                continue

            # Consistency gate
            if consistency < MIN_CONSISTENCY_PCT:
                gate_stats["consistency"] += 1
                continue

            sector = SECTOR_MAP.get(ticker, "Unknown")

            passers.append({
                "ticker": ticker,
                "median_swing": round(median_swing, 1),
                "recent_swing": round(recent_swing, 1),
                "compression_ratio": compression_ratio,
                "median_daily_range": round(median_daily_range, 1),
                "days_above_3pct": days_above_3pct,
                "median_open_to_low": median_open_to_low,
                "median_low_to_close": median_low_to_close,
                "dip_recovery_ratio": dip_recovery_ratio,
                "consistency": consistency,
                "price": round(price, 2),
                "avg_vol": avg_vol,
                "sector": sector,
            })

        except Exception:
            gate_stats["data"] += 1
            continue

    # Sort by swing magnitude descending
    passers.sort(key=lambda x: x["median_swing"], reverse=True)

    print(f"  Passed: {len(passers)} | Filtered: price={gate_stats['price']}, "
          f"vol={gate_stats['volume']}, swing={gate_stats['swing']}, "
          f"consistency={gate_stats['consistency']}, data={gate_stats['data']}")

    return passers


def _analyze_one_wick(ticker):
    """Analyze a single ticker for wick data. Thread-safe wrapper."""
    try:
        data, error = analyze_stock_data(ticker)
        if data:
            return ticker, data, None
        return ticker, None, error
    except Exception as e:
        return ticker, None, str(e)


def deep_wick_analysis(passers, top_n=20, max_workers=6):
    """Run full wick offset analysis on top N candidates. Returns structured dicts.

    Uses ThreadPoolExecutor for parallel analysis when top_n > 20.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    candidates = passers[:top_n]
    print(f"\n[Stage 2] Deep wick analysis on top {len(candidates)} candidates "
          f"({max_workers} workers)...")

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_analyze_one_wick, p["ticker"]): p["ticker"]
                   for p in candidates}
        done = 0
        for future in as_completed(futures):
            done += 1
            ticker, data, error = future.result()
            if data:
                results[ticker] = data
                print(f"  [{done}/{len(candidates)}] {ticker}... OK")
            else:
                msg = f"no data ({error})" if error else "no data"
                print(f"  [{done}/{len(candidates)}] {ticker}... {msg}")

    print(f"  Completed: {len(results)}/{len(candidates)}")
    return results


def get_portfolio_context():
    """Read portfolio.json and extract context for sector overlap analysis."""
    try:
        portfolio = json.loads(PORTFOLIO_PATH.read_text())
    except Exception:
        return {"position_tickers": [], "watchlist": [], "sectors": {}}

    position_tickers = list(portfolio.get("positions", {}).keys())
    watchlist = portfolio.get("watchlist", [])
    pending_tickers = list(portfolio.get("pending_orders", {}).keys())

    # Map current portfolio tickers to sectors
    all_held = set(position_tickers + watchlist + pending_tickers)
    sectors = {}
    for t in all_held:
        s = SECTOR_MAP.get(t, "Unknown")
        sectors.setdefault(s, []).append(t)

    return {
        "position_tickers": position_tickers,
        "watchlist": watchlist,
        "pending_tickers": pending_tickers,
        "sectors": sectors,
    }


def gather_cycle_timing(screen_results, wick_tickers):
    """Gather cycle timing data for screening passers.

    For each ticker with wick analysis (top 20):
    1. Try to load cached cycle_timing.json (fast path).
    2. If no cache, run full cycle timing analysis on-the-fly from historical data.
    3. Save computed results to tickers/<TICKER>/cycle_timing.json for future runs.

    Args:
        screen_results: All Stage 1 passers.
        wick_tickers: Set of tickers that passed Stage 2 (have wick analysis).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    ct_data = {}
    need_compute = []

    # Fast path: load cached data
    for p in screen_results:
        ticker = p["ticker"]
        if ticker not in wick_tickers:
            continue  # only compute for tickers with wick analysis
        ct = load_cycle_timing(ticker)
        if ct is not None:
            ct_data[ticker] = ct
        else:
            need_compute.append(ticker)

    if not need_compute:
        print(f"[Cycle Timing] All {len(ct_data)} tickers loaded from cache")
        return ct_data

    print(f"[Cycle Timing] {len(ct_data)} cached, computing {len(need_compute)} on-the-fly: "
          f"{', '.join(need_compute)}")

    # Compute cycle timing in parallel for uncached tickers
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_analyze_cycle_timing, t): t
                   for t in need_compute}
        for future in as_completed(futures):
            ticker, result, err = future.result()
            if err:
                print(f"  {ticker}: {err}")
                continue
            if result is None:
                continue

            # Extract statistics for scoring
            stats = result.get("statistics")
            if stats and stats.get("total_cycles", 0) > 0:
                ct_data[ticker] = {
                    "total_cycles": stats.get("total_cycles", 0),
                    "median_deep": stats.get("median_deep"),
                    "median_first": stats.get("median_first"),
                    "max_deep": stats.get("max_deep"),
                    "immediate_fill_pct": stats.get("immediate_fill_pct", 0),
                }

            # Save full result to disk for future runs
            ticker_dir = ROOT / "tickers" / ticker
            ticker_dir.mkdir(parents=True, exist_ok=True)
            json_path = ticker_dir / "cycle_timing.json"
            json_path.write_text(
                json.dumps(result, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            print(f"  {ticker}: {stats.get('total_cycles', 0)} cycles → saved")

    print(f"[Cycle Timing] Total: {len(ct_data)} tickers with cycle data")
    return ct_data


def build_screening_json(screen_results, wick_results, portfolio_ctx):
    """Build and write screening_data.json."""
    cycle_timings = gather_cycle_timing(screen_results, set(wick_results.keys()))
    output = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "gates": {
            "min_swing_pct": MIN_SWING_PCT,
            "min_consistency_pct": MIN_CONSISTENCY_PCT,
            "min_price": MIN_PRICE,
            "max_price": MAX_PRICE,
            "min_avg_vol": MIN_AVG_VOL,
        },
        "total_passers": len(screen_results),
        "passers": screen_results,
        "wick_analyses": wick_results,
        "cycle_timings": cycle_timings,
        "portfolio_context": portfolio_ctx,
        "capital_config": load_capital_config(),
    }
    # default=float as safety net for any stray numpy types in batch_swing_screen() output
    OUTPUT_PATH.write_text(json.dumps(output, indent=2, default=float) + "\n")
    print(f"\n[Stage 3] Wrote {OUTPUT_PATH.name} ({len(screen_results)} passers, "
          f"{len(wick_results)} wick analyses)")
    # Clean up stale markdown file
    stale_md = ROOT / "screening_data.md"
    stale_md.unlink(missing_ok=True)
    return output


def _load_universe_passers():
    """Load pre-screened passers from universe_screener cache."""
    cache_path = ROOT / "data" / "universe_screen_cache.json"
    try:
        data = json.loads(cache_path.read_text())
        passers = data.get("passers", [])
        print(f"  Loaded {len(passers)} passers from universe cache "
              f"(generated {data.get('generated', '?')})")
        return passers
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"  *Error loading universe cache: {e}*")
        print(f"  Run: python3 tools/universe_screener.py first")
        return None


def run_screener(use_universe=False, expanded=False):
    """Full pipeline: screen -> wick analysis -> write JSON.

    Args:
        use_universe: If True, load passers from universe_screen_cache.json
                      instead of running batch_swing_screen().
        expanded: If True, run wick analysis on top 50 (vs default 20).
    """
    top_n = 50 if expanded else 20

    print("=" * 60)
    print("  Surgical Candidate Screener")
    if use_universe:
        print("  Mode: Dynamic Universe")
    if expanded:
        print(f"  Expanded: top {top_n} wick analysis")
    print("=" * 60)

    if use_universe:
        screen_results = _load_universe_passers()
        if screen_results is None:
            return
    else:
        screen_results = batch_swing_screen()

    if not screen_results:
        print("*No tickers passed surgical gates.*")
        return

    workers = 6 if top_n > 20 else 4
    wick_results = deep_wick_analysis(screen_results, top_n=top_n, max_workers=workers)
    portfolio_ctx = get_portfolio_context()
    build_screening_json(screen_results, wick_results, portfolio_ctx)

    print("\nDone. Run surgical_filter.py next.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Surgical Candidate Screener")
    parser.add_argument("--universe", action="store_true",
                        help="Use dynamic universe passers from universe_screen_cache.json")
    parser.add_argument("--expanded", action="store_true",
                        help="Run wick analysis on top 50 candidates (vs default 20)")
    args = parser.parse_args()
    run_screener(use_universe=args.universe, expanded=args.expanded)
