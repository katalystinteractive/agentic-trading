"""Surgical Candidate Screener — batch swing screen + deep wick analysis.

Collects ALL data upfront so workflow agents can evaluate without network calls.
Stage 1: Batch swing screen ~150 tickers through surgical gates.
Stage 2: Deep wick analysis on top 20 passers.
Stage 3: Build screening_data.md with all results + portfolio context.

Usage:
    python3 tools/surgical_screener.py
"""
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
from wick_offset_analyzer import (
    fetch_history, compute_monthly_swing, compute_swing_consistency,
    analyze_stock,
)

ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = ROOT / "portfolio.json"
OUTPUT_PATH = ROOT / "screening_data.md"

# --- Surgical gates ---
MIN_SWING_PCT = 10.0
MIN_CONSISTENCY_PCT = 80.0
MIN_PRICE = 3.0
MAX_PRICE = 60.0
MIN_AVG_VOL = 500_000

# --- Sector mapping for the ~150-ticker universe ---
SECTOR_MAP = {
    # Tech / Software / AI
    "PLTR": "Tech", "HOOD": "Fintech", "RKLB": "Space", "SMCI": "AI/Infra",
    "PATH": "Tech", "NET": "Tech", "DDOG": "Tech", "MDB": "Tech",
    "SQ": "Fintech", "PINS": "Tech", "SNAP": "Tech", "ROKU": "Tech",
    "ABNB": "Tech", "DASH": "Tech", "LYFT": "Tech", "UBER": "Tech",
    "AFRM": "Fintech", "UPST": "Fintech", "LMND": "Fintech", "OPEN": "Tech",
    "RDFN": "Tech", "BBAI": "AI", "AI": "AI",
    "OKTA": "Tech", "ZS": "Tech", "CRWD": "Tech", "SNOW": "Tech", "SHOP": "Tech",
    # Space / Quantum / Frontier
    "JOBY": "Space", "LILM": "Space", "ASTS": "Space", "RDW": "Space",
    "LUNR": "Space", "OKLO": "Nuclear", "SMR": "Nuclear", "NNE": "Nuclear",
    "RGTI": "Quantum", "QBTS": "Quantum",
    # Crypto-adjacent
    "COIN": "Crypto", "RIOT": "Crypto", "MARA": "Crypto", "HUT": "Crypto",
    "BITF": "Crypto", "CLSK": "Crypto", "MSTR": "Crypto",
    # Energy / Solar / Nuclear
    "FSLR": "Solar", "ENPH": "Solar", "RUN": "Solar", "NOVA": "Solar",
    "OXY": "Energy", "DVN": "Energy", "MRO": "Energy", "HAL": "Energy",
    "SLB": "Energy", "CTRA": "Energy", "EQT": "Energy", "RRC": "Energy",
    "VST": "Energy", "CEG": "Nuclear",
    # EV / Clean Energy
    "PLUG": "EV/Clean", "BE": "EV/Clean", "BLNK": "EV/Clean", "CHPT": "EV/Clean",
    "QS": "EV/Clean", "RIVN": "EV/Clean", "LCID": "EV/Clean", "NKLA": "EV/Clean",
    "GOEV": "EV/Clean", "WKHS": "EV/Clean",
    # Biotech / Health
    "MRNA": "Biotech", "BNTX": "Biotech", "NVAX": "Biotech", "DNA": "Biotech",
    "BEAM": "Biotech", "CRSP": "Biotech", "EDIT": "Biotech", "NTLA": "Biotech",
    "PACB": "Biotech", "HIMS": "Health", "DOCS": "Health", "EXAS": "Health",
    # Materials / Mining / Steel
    "FCX": "Materials", "NEM": "Materials", "GOLD": "Materials", "AA": "Materials",
    "X": "Steel", "NUE": "Steel", "STLD": "Steel", "MP": "Materials", "TMC": "Materials",
    # Finance / Fintech
    "PYPL": "Fintech", "ALLY": "Finance", "LC": "Fintech",
    # Retail / Consumer
    "CHWY": "Retail", "DKS": "Retail", "CROX": "Retail", "ETSY": "Retail",
    "W": "Retail", "GME": "Retail", "AMC": "Retail", "BB": "Tech",
    # China ADR
    "BABA": "China ADR", "JD": "China ADR", "PDD": "China ADR", "NIO": "China ADR",
    "XPEV": "China ADR", "LI": "China ADR", "BIDU": "China ADR", "FUTU": "China ADR",
    # Defense / Industrial
    "KTOS": "Defense", "AVAV": "Defense", "IREN": "Crypto",
    # Misc volatile
    "CLOV": "Health", "TTWO": "Gaming", "EA": "Gaming", "WOLF": "Tech",
    "ON": "Semi", "MRVL": "Semi", "ARM": "Semi",
    "SWAV": "Health", "TEM": "AI", "RXRX": "Biotech", "SOUN": "AI",
    "NNOX": "Health", "VLD": "Tech", "PSNY": "EV/Clean",
    "LAZR": "Tech", "OUST": "Tech", "LIDR": "Tech", "TOST": "Tech",
    "GRAB": "Tech", "SE": "Tech", "CPNG": "Retail",
    "DUOL": "Tech", "MNDY": "Tech", "GLBE": "Tech", "CAVA": "Retail",
    "CART": "Retail", "DLO": "Fintech",
    # REITs
    "AGNC": "REIT", "NLY": "REIT", "MPW": "REIT",
    # Telecom / Media
    "PARA": "Media", "WBD": "Media",
    # Additional volatile mid-caps
    "BILL": "Tech", "GTLB": "Tech", "CFLT": "Tech", "ESTC": "Tech",
    "ZI": "Tech", "BRZE": "Tech",
    "APP": "Tech", "PUBM": "Tech", "MGNI": "Tech", "TTD": "Tech",
    "CELH": "Consumer", "MNST": "Consumer",
    "DKNG": "Gaming", "PENN": "Gaming", "RSI": "Gaming", "GENI": "Gaming",
}


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
                volume = data["Volume"][ticker].dropna()
            else:
                close = data["Close"].dropna()
                high = data["High"].dropna()
                low = data["Low"].dropna()
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


def deep_wick_analysis(passers, top_n=20):
    """Run full wick offset analysis on top N candidates."""
    candidates = passers[:top_n]
    print(f"\n[Stage 2] Deep wick analysis on top {len(candidates)} candidates...")

    results = {}
    for i, p in enumerate(candidates, 1):
        ticker = p["ticker"]
        print(f"  [{i}/{len(candidates)}] {ticker}...", end=" ", flush=True)
        try:
            report = analyze_stock(ticker)
            if report:
                results[ticker] = report
                print("OK")
            else:
                print("no data")
        except Exception as e:
            print(f"ERROR: {e}")

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


def build_screening_report(screen_results, wick_results, portfolio_ctx):
    """Build and write screening_data.md with all collected data."""
    lines = []
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    lines.append(f"# Surgical Candidate Screening Data")
    lines.append(f"*Generated: {now}*")
    lines.append("")

    # Section 1: Screening Summary
    lines.append("## 1. Gate Passers — All Candidates")
    lines.append(f"*{len(screen_results)} tickers passed all surgical gates "
                 f"(10%+ swing, 80%+ consistency, $3-$60, 500K+ vol)*")
    lines.append("")
    lines.append("| # | Ticker | Swing% | Consistency% | Price | Avg Vol | Sector |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for i, r in enumerate(screen_results, 1):
        vol_str = f"{r['avg_vol']/1e6:.1f}M"
        lines.append(f"| {i} | {r['ticker']} | {r['median_swing']}% "
                     f"| {r['consistency']}% | ${r['price']:.2f} | {vol_str} | {r['sector']} |")
    lines.append("")

    # Section 2: Deep Wick Analysis
    top_n = min(20, len(screen_results))
    lines.append(f"## 2. Deep Wick Analysis — Top {top_n} Candidates")
    lines.append("")
    for ticker in [r["ticker"] for r in screen_results[:top_n]]:
        if ticker in wick_results:
            lines.append(f"### {ticker}")
            lines.append(wick_results[ticker])
            lines.append("")
            lines.append("---")
            lines.append("")
        else:
            lines.append(f"### {ticker}")
            lines.append(f"*Wick analysis failed or returned no data for {ticker}.*")
            lines.append("")

    # Section 3: Portfolio Context
    lines.append("## 3. Portfolio Context")
    lines.append("")
    lines.append("### Current Positions")
    if portfolio_ctx["position_tickers"]:
        lines.append(f"**Active:** {', '.join(portfolio_ctx['position_tickers'])}")
    else:
        lines.append("*No active positions.*")
    lines.append("")

    lines.append("### Watchlist")
    if portfolio_ctx["watchlist"]:
        lines.append(f"**Watching:** {', '.join(portfolio_ctx['watchlist'])}")
    else:
        lines.append("*Empty watchlist.*")
    lines.append("")

    lines.append("### Sectors Already Held")
    if portfolio_ctx["sectors"]:
        lines.append("| Sector | Tickers |")
        lines.append("| :--- | :--- |")
        for sector, tickers in sorted(portfolio_ctx["sectors"].items()):
            lines.append(f"| {sector} | {', '.join(sorted(tickers))} |")
    else:
        lines.append("*No sector data.*")
    lines.append("")

    report = "\n".join(lines)
    OUTPUT_PATH.write_text(report + "\n")
    print(f"\n[Stage 3] Wrote {OUTPUT_PATH.name} ({len(screen_results)} passers, "
          f"{len(wick_results)} wick analyses)")
    return report


def run_screener():
    """Full pipeline: screen -> wick analysis -> write report."""
    print("=" * 60)
    print("  Surgical Candidate Screener")
    print("=" * 60)

    screen_results = batch_swing_screen()
    if not screen_results:
        print("*No tickers passed surgical gates.*")
        return

    wick_results = deep_wick_analysis(screen_results, top_n=20)
    portfolio_ctx = get_portfolio_context()
    build_screening_report(screen_results, wick_results, portfolio_ctx)

    print("\nDone. Agents can now evaluate screening_data.md.")


if __name__ == "__main__":
    run_screener()
