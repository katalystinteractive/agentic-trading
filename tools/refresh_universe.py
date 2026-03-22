#!/usr/bin/env python3
"""Refresh Universe — download US-listed ticker universe from NASDAQ FTP.

Generates data/us_universe.json with all US-listed common stock tickers.
Persists on disk — only overwrites if a larger list is successfully fetched.

Usage:
    python3 tools/refresh_universe.py              # normal refresh
    python3 tools/refresh_universe.py --bootstrap   # initial bootstrap (same logic, explicit intent)
"""
import argparse
import json
import sys
import time
from io import StringIO
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_OUTPUT = _ROOT / "data" / "us_universe.json"


def _fetch_nasdaq_ftp():
    """Fetch ticker lists from NASDAQ FTP (nasdaqlisted.txt + otherlisted.txt).

    Returns set of ticker symbols or raises on failure.
    """
    import urllib.request

    tickers = set()
    urls = [
        "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
        "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
    ]

    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                text = resp.read().decode("utf-8")
        except Exception as e:
            print(f"  Warning: Failed to fetch {url}: {e}")
            continue

        for line in text.strip().split("\n")[1:]:  # skip header
            if "|" not in line:
                continue
            parts = line.split("|")
            symbol = parts[0].strip()
            # Filter out test entries, empty, non-alpha
            if not symbol or not symbol.isalpha() or len(symbol) > 5:
                continue
            # nasdaqlisted.txt: col 6 = Test Issue (Y/N)
            if len(parts) > 6 and parts[6].strip() == "Y":
                continue
            # otherlisted.txt: col 5 = Test Issue
            if len(parts) > 5 and parts[5].strip() == "Y":
                continue
            tickers.add(symbol)

    return tickers


def _fetch_screener_api():
    """Fallback: fetch tickers from NASDAQ screener API."""
    import urllib.request

    url = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=10000&offset=0"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        rows = data.get("data", {}).get("table", {}).get("rows", [])
        tickers = set()
        for row in rows:
            symbol = row.get("symbol", "").strip()
            if symbol and symbol.isalpha() and len(symbol) <= 5:
                tickers.add(symbol)
        return tickers
    except Exception as e:
        print(f"  Warning: Screener API fallback failed: {e}")
        return set()


def _seed_from_bounce_screener():
    """Last-resort fallback: use bounce_screener.TICKERS."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from bounce_screener import TICKERS
        return set(TICKERS)
    except ImportError:
        return set()


def _load_existing():
    """Load existing universe file, return set of tickers."""
    try:
        data = json.loads(_OUTPUT.read_text())
        return set(data.get("tickers", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def refresh(force=False):
    """Fetch universe and write to data/us_universe.json.

    Only overwrites if new list is larger than existing (safety guard).
    Pass force=True to overwrite regardless.
    """
    existing = _load_existing()
    print(f"Existing universe: {len(existing)} tickers")

    # Try NASDAQ FTP first
    print("Fetching from NASDAQ FTP...")
    tickers = _fetch_nasdaq_ftp()
    source = "nasdaq_ftp"

    if len(tickers) < 500:
        print(f"  FTP returned only {len(tickers)} — trying screener API fallback...")
        api_tickers = _fetch_screener_api()
        if len(api_tickers) > len(tickers):
            tickers = api_tickers
            source = "screener_api"

    if len(tickers) < 100:
        print(f"  Only {len(tickers)} tickers — using bounce_screener seed as last resort...")
        seed = _seed_from_bounce_screener()
        if len(seed) > len(tickers):
            tickers = seed
            source = "bounce_screener_seed"

    print(f"Fetched {len(tickers)} tickers via {source}")

    # Safety: don't overwrite with a smaller list unless forced
    if not force and len(tickers) < len(existing):
        print(f"  New list ({len(tickers)}) is smaller than existing ({len(existing)}) — skipping.")
        print("  Use --force to overwrite.")
        return existing

    # Write
    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": source,
        "count": len(tickers),
        "tickers": sorted(tickers),
    }
    _OUTPUT.write_text(json.dumps(output, indent=2) + "\n")
    print(f"Wrote {_OUTPUT} ({len(tickers)} tickers)")
    return tickers


def main():
    parser = argparse.ArgumentParser(description="Refresh US ticker universe")
    parser.add_argument("--bootstrap", action="store_true",
                        help="Initial bootstrap (same as normal refresh)")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite even if new list is smaller")
    args = parser.parse_args()

    refresh(force=args.force)


if __name__ == "__main__":
    main()
