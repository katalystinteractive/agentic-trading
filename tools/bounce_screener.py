"""Bounce Screener — scan 150+ tickers, filter by criteria, run bounce analysis.

Quick-screens by price/volume/ATR using daily data, then runs full hourly
bounce analysis on qualifying tickers. Outputs ranked results.

Usage:
    python3 tools/bounce_screener.py
"""
import json
import sys
import time
from pathlib import Path

import yfinance as yf
import pandas as pd
import numpy as np

# Import analyze_stock from bounce_analyzer (same directory)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bounce_analyzer import analyze_stock

ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO = ROOT / "portfolio.json"

# --- Screening criteria ---
MIN_PRICE = 3
MAX_PRICE = 60
MIN_AVG_VOLUME = 1_000_000
MIN_ATR_PCT = 2.0

# --- Ticker universe (150+ diverse, liquid, volatile stocks) ---
TICKERS = [
    # Tech / Software / AI
    "PLTR", "HOOD", "RKLB", "SMCI", "PATH", "NET", "DDOG", "MDB",
    "SQ", "PINS", "SNAP", "ROKU", "ABNB", "DASH", "LYFT", "UBER",
    "AFRM", "UPST", "LMND", "OPEN", "RDFN", "BBAI", "AI",
    "OKTA", "ZS", "CRWD", "SNOW", "SHOP",
    # Space / Quantum / Frontier
    "JOBY", "LILM", "ASTS", "RDW", "LUNR", "OKLO", "SMR", "NNE",
    "RGTI", "QBTS",
    # Crypto-adjacent
    "COIN", "RIOT", "MARA", "HUT", "BITF", "CLSK", "MSTR",
    # Energy / Solar / Nuclear
    "FSLR", "ENPH", "RUN", "NOVA", "OXY", "DVN", "MRO", "HAL",
    "SLB", "CTRA", "EQT", "RRC", "VST", "CEG",
    # EV / Clean Energy
    "PLUG", "BE", "BLNK", "CHPT", "QS", "RIVN", "LCID", "NKLA",
    "GOEV", "WKHS",
    # Biotech / Health
    "MRNA", "BNTX", "NVAX", "DNA", "BEAM", "CRSP", "EDIT", "NTLA",
    "PACB", "HIMS", "DOCS", "EXAS",
    # Materials / Mining / Steel
    "FCX", "NEM", "GOLD", "AA", "X", "NUE", "STLD", "MP",
    "TMC",
    # Finance / Fintech
    "PYPL", "ALLY", "LC", "OPEN", "AFRM",
    # Retail / Consumer
    "CHWY", "DKS", "CROX", "ETSY", "W", "GME", "AMC", "BB",
    # China ADR
    "BABA", "JD", "PDD", "NIO", "XPEV", "LI", "BIDU", "FUTU",
    # Defense / Industrial
    "KTOS", "AVAV", "IREN",
    # Misc volatile
    "CLOV", "TTWO", "EA", "WOLF", "ON", "MRVL", "ARM",
    "SWAV", "TEM", "RXRX", "SOUN", "NNOX", "VLD", "PSNY",
    "LAZR", "OUST", "LIDR", "TOST", "GRAB", "SE", "CPNG",
    "DUOL", "MNDY", "GLBE", "CAVA", "CART", "DLO",
    # REITs / Real Estate (volatile ones)
    "AGNC", "NLY", "MPW",
    # Telecom / Media
    "PARA", "WBD",
    # Additional volatile mid-caps
    "BILL", "GTLB", "CFLT", "ESTC", "ZI", "BRZE",
    "APP", "PUBM", "MGNI", "TTD", "CELH", "MNST",
    "DKNG", "PENN", "RSI", "GENI",
]


def get_excluded_tickers():
    """Get all tickers in Surgical + Velocity + Bounce pools."""
    try:
        portfolio = json.loads(PORTFOLIO.read_text())
    except Exception:
        return set()
    excluded = set()
    # Surgical
    excluded.update(portfolio.get("positions", {}).keys())
    excluded.update(portfolio.get("pending_orders", {}).keys())
    excluded.update(portfolio.get("watchlist", []))
    # Velocity
    excluded.update(portfolio.get("velocity_positions", {}).keys())
    excluded.update(portfolio.get("velocity_pending", {}).keys())
    excluded.update(portfolio.get("velocity_watchlist", []))
    # Bounce
    excluded.update(portfolio.get("bounce_positions", {}).keys())
    excluded.update(portfolio.get("bounce_pending", {}).keys())
    excluded.update(portfolio.get("bounce_watchlist", []))
    return excluded


def quick_screen(tickers, excluded):
    """Batch download daily data and filter by price/volume/ATR."""
    # Remove excluded and duplicates
    unique = list(dict.fromkeys(t for t in tickers if t not in excluded))
    print(f"Screening {len(unique)} tickers (excluded {len(excluded)} portfolio tickers)...")

    # Batch download (much faster than individual)
    try:
        data = yf.download(unique, period="1mo", interval="1d", progress=False, threads=True)
    except Exception as e:
        print(f"*Error in batch download: {e}*")
        return []

    qualified = []
    disqualified_reasons = {"price": 0, "volume": 0, "atr": 0, "data": 0}

    for ticker in unique:
        try:
            if isinstance(data.columns, pd.MultiIndex):
                close = data["Close"][ticker].dropna()
                high = data["High"][ticker].dropna()
                low = data["Low"][ticker].dropna()
                volume = data["Volume"][ticker].dropna()
            else:
                close = data["Close"].dropna()
                high = data["High"].dropna()
                low = data["Low"].dropna()
                volume = data["Volume"].dropna()

            if len(close) < 10:
                disqualified_reasons["data"] += 1
                continue

            price = float(close.iloc[-1])
            avg_vol = float(volume.tail(20).mean())

            # ATR%
            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs()
            ], axis=1).max(axis=1)
            atr = float(tr.tail(14).mean())
            atr_pct = (atr / price) * 100 if price > 0 else 0

            if not (MIN_PRICE <= price <= MAX_PRICE):
                disqualified_reasons["price"] += 1
                continue
            if avg_vol < MIN_AVG_VOLUME:
                disqualified_reasons["volume"] += 1
                continue
            if atr_pct < MIN_ATR_PCT:
                disqualified_reasons["atr"] += 1
                continue

            qualified.append({
                "ticker": ticker,
                "price": price,
                "avg_volume": avg_vol,
                "atr_pct": atr_pct,
            })
        except Exception:
            disqualified_reasons["data"] += 1
            continue

    print(f"Qualified: {len(qualified)} | Disqualified: price={disqualified_reasons['price']}, "
          f"volume={disqualified_reasons['volume']}, ATR={disqualified_reasons['atr']}, "
          f"data={disqualified_reasons['data']}")
    return qualified


def run_screener():
    excluded = get_excluded_tickers()
    qualified = quick_screen(TICKERS, excluded)

    if not qualified:
        print("*No tickers passed screening.*")
        return

    # Sort by ATR% descending (most volatile first — better bounce candidates)
    qualified.sort(key=lambda x: x["atr_pct"], reverse=True)

    print(f"\n## Phase 1: Quick Screen Results ({len(qualified)} qualified)")
    print("| # | Ticker | Price | Avg Vol | ATR% |")
    print("| :--- | :--- | :--- | :--- | :--- |")
    for i, q in enumerate(qualified, 1):
        print(f"| {i} | {q['ticker']} | ${q['price']:.2f} | {q['avg_volume']/1e6:.1f}M | {q['atr_pct']:.1f}% |")

    # Phase 2: Full bounce analysis on each qualified ticker
    print(f"\n## Phase 2: Bounce Analysis ({len(qualified)} tickers)")
    print("Running hourly analysis — this takes ~5-10 seconds per ticker...\n")

    all_levels = []
    analyzed = 0
    failed = 0

    for i, q in enumerate(qualified, 1):
        ticker = q["ticker"]
        print(f"[{i}/{len(qualified)}] Analyzing {ticker}...", end=" ", flush=True)
        start = time.time()

        try:
            report, json_data = analyze_stock(ticker)
            elapsed = time.time() - start

            if json_data and json_data.get("levels"):
                actionable = [l for l in json_data["levels"]
                              if l.get("verdict") in ("STRONG BOUNCE", "BOUNCE")]
                print(f"{len(json_data['levels'])} levels, {len(actionable)} actionable ({elapsed:.1f}s)")
                for lvl in json_data["levels"]:
                    lvl["_ticker"] = ticker
                    lvl["_price"] = q["price"]
                    lvl["_atr_pct"] = q["atr_pct"]
                    all_levels.append(lvl)
                analyzed += 1
            else:
                print(f"no levels ({elapsed:.1f}s)")
                analyzed += 1
        except Exception as e:
            elapsed = time.time() - start
            print(f"ERROR: {e} ({elapsed:.1f}s)")
            failed += 1

    # Phase 3: Rank results
    print(f"\n## Phase 3: Ranked Results")
    print(f"Analyzed: {analyzed} | Failed: {failed} | Total levels: {len(all_levels)}")

    # Filter to actionable only
    actionable_verdicts = {"STRONG BOUNCE", "BOUNCE"}
    actionable = [l for l in all_levels if l.get("verdict") in actionable_verdicts]

    # Sort: STRONG BOUNCE first, then by bounce_3d_median descending
    verdict_order = {"STRONG BOUNCE": 0, "BOUNCE": 1}
    actionable.sort(key=lambda x: (
        verdict_order.get(x["verdict"], 9),
        -(x.get("bounce_3d_median") or 0),
    ))

    if actionable:
        print(f"\n### Actionable Levels ({len(actionable)} across all tickers)")
        print("| # | Ticker | Price | Level | Source | Hold% | Bounce 3D | >= 4.5% | Buy At | Sell At | Stop | R/R | Verdict | ATR% |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for i, lvl in enumerate(actionable, 1):
            hr = f"{lvl.get('hold_rate', 0):.0%}"
            b3 = f"+{lvl['bounce_3d_median']:.1f}%" if lvl.get("bounce_3d_median") is not None else "N/A"
            p45 = f"{lvl.get('pct_above_4_5', 0):.0%}"
            buy = f"${lvl['buy_at']:.2f}" if lvl.get("buy_at") else "N/A"
            sell = f"${lvl['sell_at']:.2f}" if lvl.get("sell_at") else "N/A"
            stop = f"${lvl['stop']:.2f}" if lvl.get("stop") else "N/A"
            shares = lvl.get("shares", "?")
            # Compute R/R if we have the data
            if lvl.get("sell_at") and lvl.get("buy_at") and lvl.get("stop"):
                risk = lvl["buy_at"] - lvl["stop"]
                reward = lvl["sell_at"] - lvl["buy_at"]
                rr = f"{reward/risk:.1f}:1" if risk > 0 else "N/A"
            else:
                rr = "N/A"
            print(
                f"| {i} | {lvl['_ticker']} | ${lvl['_price']:.2f} | ${lvl.get('price', 0):.2f} "
                f"| {lvl.get('source', '?')} | {hr} | {b3} | {p45} | {buy} "
                f"| {sell} | {stop} | {rr} | {lvl['verdict']} | {lvl['_atr_pct']:.1f}% |"
            )

        # Top 10 summary
        top10 = actionable[:10]
        print(f"\n### Top 10 Best Bounce Candidates")
        print("| # | Ticker | Buy At | Sell At | Bounce 3D | Hold% | >= 4.5% | Verdict |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for i, lvl in enumerate(top10, 1):
            hr = f"{lvl.get('hold_rate', 0):.0%}"
            b3 = f"+{lvl['bounce_3d_median']:.1f}%" if lvl.get("bounce_3d_median") is not None else "N/A"
            p45 = f"{lvl.get('pct_above_4_5', 0):.0%}"
            buy = f"${lvl['buy_at']:.2f}" if lvl.get("buy_at") else "N/A"
            sell = f"${lvl['sell_at']:.2f}" if lvl.get("sell_at") else "N/A"
            print(f"| {i} | {lvl['_ticker']} | {buy} | {sell} | {b3} | {hr} | {p45} | {lvl['verdict']} |")
    else:
        print("\n*No actionable levels found across all tickers.*")

    # Also show all WEAK levels with high bounce potential (might be close to upgrading)
    almost = [l for l in all_levels
              if l.get("verdict") == "WEAK"
              and (l.get("bounce_3d_median") or 0) >= 4.5
              and (l.get("hold_rate") or 0) >= 0.35]
    if almost:
        print(f"\n### Near-Miss Levels (WEAK but close to BOUNCE threshold)")
        print("| Ticker | Level | Hold% | Bounce 3D | >= 4.5% | Verdict |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for lvl in almost[:10]:
            hr = f"{lvl.get('hold_rate', 0):.0%}"
            b3 = f"+{lvl['bounce_3d_median']:.1f}%" if lvl.get("bounce_3d_median") is not None else "N/A"
            p45 = f"{lvl.get('pct_above_4_5', 0):.0%}"
            print(f"| {lvl['_ticker']} | ${lvl.get('price', 0):.2f} | {hr} | {b3} | {p45} | {lvl['verdict']} |")


if __name__ == "__main__":
    run_screener()
