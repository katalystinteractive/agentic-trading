#!/usr/bin/env python3
"""Universe Screener — dynamic screener scanning full US stock universe.

Applies the same surgical gates (price, volume, swing, consistency) as
surgical_screener.py but against ~4000 tickers from data/us_universe.json.

Results cached to data/universe_screen_cache.json (7-day validity).

Usage:
    python3 tools/universe_screener.py              # full scan (~5-10 min)
    python3 tools/universe_screener.py --cached     # use cache only
    python3 tools/universe_screener.py --refresh    # force re-download universe list first
    python3 tools/universe_screener.py --json       # JSON output to stdout
"""
import argparse
import datetime
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sector_registry import get_sector

_UNIVERSE_PATH = _ROOT / "data" / "us_universe.json"
_CACHE_PATH = _ROOT / "data" / "universe_screen_cache.json"
_PARTIAL_PATH = _ROOT / "data" / "universe_screen_partial.json"

# Surgical gates (same as surgical_screener.py)
MIN_SWING_PCT = 10.0
MIN_CONSISTENCY_PCT = 80.0
MIN_PRICE = 3.0
MAX_PRICE = 60.0
MIN_AVG_VOL = 500_000

CHUNK_SIZE = 500
CHUNK_PAUSE = 3.0  # seconds between chunks
MAX_RETRIES = 3
CACHE_VALIDITY_DAYS = 7


def _load_universe():
    """Load ticker list from data/us_universe.json."""
    try:
        data = json.loads(_UNIVERSE_PATH.read_text())
        return data.get("tickers", [])
    except (FileNotFoundError, json.JSONDecodeError):
        # Fallback to bounce_screener.TICKERS
        try:
            from bounce_screener import TICKERS
            print(f"Warning: {_UNIVERSE_PATH} not found — using bounce_screener ({len(TICKERS)} tickers)")
            return list(TICKERS)
        except ImportError:
            print(f"*Error: No universe file and bounce_screener not available*")
            return []


def _load_cache():
    """Load cached results if still valid."""
    try:
        data = json.loads(_CACHE_PATH.read_text())
        generated = datetime.datetime.fromisoformat(data["generated"])
        age_days = (datetime.datetime.now() - generated).days
        if age_days <= CACHE_VALIDITY_DAYS:
            return data
        print(f"Cache is {age_days} days old (>{CACHE_VALIDITY_DAYS}) — will re-scan")
        return None
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None


def _load_partial():
    """Load partial results from interrupted scan."""
    try:
        data = json.loads(_PARTIAL_PATH.read_text())
        return data.get("passers", []), data.get("completed_chunks", 0)
    except (FileNotFoundError, json.JSONDecodeError):
        return [], 0


def _save_partial(passers, completed_chunks):
    """Save partial results for resume after failure."""
    _PARTIAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "completed_chunks": completed_chunks,
        "passers": passers,
    }
    _PARTIAL_PATH.write_text(json.dumps(data, indent=2, default=float) + "\n")


def _screen_chunk(tickers):
    """Screen a chunk of tickers through surgical gates. Returns list of passer dicts."""
    if not tickers:
        return []

    try:
        data = yf.download(tickers, period="400d", interval="1d",
                           progress=False, threads=True)
    except Exception as e:
        print(f"    *Chunk download error: {e}*")
        return None

    if data.empty:
        return []

    passers = []
    now = datetime.datetime.now()
    multi = isinstance(data.columns, pd.MultiIndex) and len(tickers) > 1

    for ticker in tickers:
        try:
            if multi:
                close = data["Close"][ticker].dropna()
                high = data["High"][ticker].dropna()
                low = data["Low"][ticker].dropna()
                volume = data["Volume"][ticker].dropna()
            else:
                close = data["Close"].dropna()
                high = data["High"].dropna()
                low = data["Low"].dropna()
                volume = data["Volume"].dropna()

            if len(close) < 60:
                continue

            price = float(close.iloc[-1])
            avg_vol = float(volume.tail(20).mean())

            if not (MIN_PRICE <= price <= MAX_PRICE):
                continue
            if avg_vol < MIN_AVG_VOL:
                continue

            # Monthly swing
            df = pd.DataFrame({"High": high, "Low": low, "Close": close})
            monthly = df.resample("ME").agg({"High": "max", "Low": "min"}).dropna()
            if len(monthly) > 0 and monthly.index[-1].month == now.month and monthly.index[-1].year == now.year:
                monthly = monthly.iloc[:-1]
            if len(monthly) < 3:
                continue

            swings = ((monthly["High"] - monthly["Low"]) / monthly["Low"] * 100).values
            median_swing = float(np.median(swings))
            above_thresh = sum(1 for s in swings if s >= MIN_SWING_PCT)
            consistency = round(above_thresh / len(swings) * 100, 1)

            if median_swing < MIN_SWING_PCT:
                continue
            if consistency < MIN_CONSISTENCY_PCT:
                continue

            passers.append({
                "ticker": ticker,
                "median_swing": round(median_swing, 1),
                "consistency": consistency,
                "price": round(price, 2),
                "avg_vol": avg_vol,
                "sector": get_sector(ticker),
            })
        except Exception:
            continue

    return passers


def full_scan(tickers):
    """Run full universe scan in chunks with retry + checkpointing."""
    # Check for partial results to resume
    partial_passers, completed_chunks = _load_partial()
    if partial_passers:
        print(f"  Resuming from partial: {len(partial_passers)} passers, {completed_chunks} chunks done")

    chunks = [tickers[i:i + CHUNK_SIZE] for i in range(0, len(tickers), CHUNK_SIZE)]
    total_chunks = len(chunks)
    all_passers = list(partial_passers)
    consecutive_failures = 0

    for i, chunk in enumerate(chunks):
        if i < completed_chunks:
            continue  # skip already-completed chunks

        print(f"  Chunk {i + 1}/{total_chunks} ({len(chunk)} tickers)...", end=" ", flush=True)

        # Retry with exponential backoff
        chunk_passers = None
        for attempt in range(MAX_RETRIES):
            chunk_passers = _screen_chunk(chunk)
            if chunk_passers is not None:
                break
            wait = 2 ** attempt
            print(f"retry in {wait}s...", end=" ", flush=True)
            time.sleep(wait)

        if chunk_passers is None:
            consecutive_failures += 1
            print(f"FAILED (consecutive: {consecutive_failures})")
            if consecutive_failures >= 3:
                print(f"  Circuit breaker: 3 consecutive failures — using partial results")
                break
            continue

        consecutive_failures = 0
        all_passers.extend(chunk_passers)
        print(f"{len(chunk_passers)} passed")

        # Checkpoint
        _save_partial(all_passers, i + 1)

        # Pause between chunks to avoid rate limiting
        if i < total_chunks - 1:
            time.sleep(CHUNK_PAUSE)

    # Sort by swing magnitude descending
    all_passers.sort(key=lambda x: x["median_swing"], reverse=True)

    # Clean up partial file on success
    _PARTIAL_PATH.unlink(missing_ok=True)

    return all_passers


def write_cache(passers):
    """Write scan results to cache file."""
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "gates": {
            "min_swing_pct": MIN_SWING_PCT,
            "min_consistency_pct": MIN_CONSISTENCY_PCT,
            "min_price": MIN_PRICE,
            "max_price": MAX_PRICE,
            "min_avg_vol": MIN_AVG_VOL,
        },
        "total_passers": len(passers),
        "passers": passers,
    }
    _CACHE_PATH.write_text(json.dumps(output, indent=2, default=float) + "\n")
    return output


def format_markdown(passers):
    """Format passers as a markdown table."""
    lines = []
    lines.append("# Universe Screening Results")
    lines.append(f"*Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    lines.append(f"*{len(passers)} tickers passed surgical gates*")
    lines.append("")
    lines.append("| # | Ticker | Sector | Price | Swing% | Consistency% | Avg Vol |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for i, p in enumerate(passers, 1):
        lines.append(
            f"| {i} | {p['ticker']} | {p['sector']} | ${p['price']:.2f} "
            f"| {p['median_swing']}% | {p['consistency']}% "
            f"| {p['avg_vol']:,.0f} |"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Universe Screener — scan US stocks through surgical gates")
    parser.add_argument("--cached", action="store_true", help="Use cached results only")
    parser.add_argument("--refresh", action="store_true", help="Force re-download universe list first")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    args = parser.parse_args()

    t0 = time.monotonic()

    # --cached: use cache only
    if args.cached:
        cache = _load_cache()
        if cache is None:
            print("*Error: No valid cache — run without --cached first*")
            sys.exit(1)
        passers = cache["passers"]
        print(f"Using cached results: {len(passers)} passers "
              f"(generated {cache['generated']})")
        if args.json:
            print(json.dumps(cache, indent=2, default=float))
        else:
            print(format_markdown(passers))
        return

    # --refresh: update universe list first
    if args.refresh:
        from refresh_universe import refresh
        refresh()

    # Load universe
    universe = _load_universe()
    if not universe:
        print("*Error: No universe tickers available*")
        sys.exit(1)

    print(f"Universe Screener")
    print(f"=" * 50)
    print(f"Universe: {len(universe)} tickers")
    print(f"Gates: price ${MIN_PRICE}-${MAX_PRICE}, vol >={MIN_AVG_VOL:,}, "
          f"swing >={MIN_SWING_PCT}%, consistency >={MIN_CONSISTENCY_PCT}%")
    print()

    # Run scan
    passers = full_scan(universe)
    elapsed = time.monotonic() - t0

    # Write cache
    cache = write_cache(passers)

    print(f"\n{'=' * 50}")
    print(f"Passed: {len(passers)} / {len(universe)} ({len(passers)/len(universe)*100:.1f}%)")
    print(f"Elapsed: {elapsed:.0f}s")
    print(f"Cache: {_CACHE_PATH}")

    # Output
    if args.json:
        print(json.dumps(cache, indent=2, default=float))
    else:
        print()
        print(format_markdown(passers))


if __name__ == "__main__":
    main()
