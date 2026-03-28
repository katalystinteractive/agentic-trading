"""Post-Simulation Validator — mechanical portfolio-level checks on sim-proven candidates.

Replaces LLM qualitative review with deterministic checks:
1. Sector concentration — flag if adding this ticker would create extreme imbalance
2. Earnings blackout — check earnings gate
3. Price correlation — does this ticker move with ones we already hold?
4. Liquidity — can we fill at wick-adjusted levels?

Reports findings for human decision — does NOT re-rank or reject.
Simulation P/L ranking is authoritative. This only flags portfolio-level risks.

Usage:
    python3 tools/post_sim_validator.py                       # validates sim-ranked results
    python3 tools/post_sim_validator.py --tickers PLTR HOOD   # specific tickers
"""
import sys
import json
from datetime import datetime
from pathlib import Path
from collections import defaultdict

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = _ROOT / "data" / "backtest" / "sim-ranked"


def _load_portfolio():
    with open(_ROOT / "portfolio.json") as f:
        return json.load(f)


def _get_sector(ticker):
    """Get fine-grained sector for a ticker."""
    try:
        from sector_registry import get_sector
        return get_sector(ticker)
    except Exception:
        pass
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        industry = info.get("industry", "")
        sector = info.get("sector", "Unknown")
        return industry if industry else sector
    except Exception:
        return "Unknown"


def check_sector_concentration(candidate_tickers, portfolio):
    """Check sector balance if candidates are added to current watchlist.

    At 200 tickers across ~30 fine sectors, average is ~7 per sector.
    Flag if any fine sector would exceed 2x the average after adding candidates.
    """
    watchlist = set(portfolio.get("watchlist", []))
    positions = set(portfolio.get("positions", {}).keys())
    current_tickers = watchlist | positions

    # Count current sectors
    sector_counts = defaultdict(list)
    for tk in current_tickers:
        sector = _get_sector(tk)
        sector_counts[sector].append(tk)

    results = []
    for tk in candidate_tickers:
        sector = _get_sector(tk)
        existing = sector_counts.get(sector, [])
        total_after = len(existing) + 1
        total_tickers = len(current_tickers) + 1
        n_sectors = max(len(sector_counts), 1)
        avg_per_sector = total_tickers / n_sectors

        # Flag if this sector would be >2x the average concentration
        flag = total_after > avg_per_sector * 2 and total_after > 3

        results.append({
            "ticker": tk,
            "sector": sector,
            "existing_in_sector": existing,
            "count_after": total_after,
            "avg_per_sector": round(avg_per_sector, 1),
            "flag": flag,
            "note": f"{total_after} in {sector} (avg {avg_per_sector:.1f}/sector)"
                    + (f" — HIGH CONCENTRATION" if flag else ""),
        })

    return results


def check_earnings(candidate_tickers):
    """Check earnings blackout for each candidate."""
    try:
        from earnings_gate import check_earnings_gate
        results = []
        for tk in candidate_tickers:
            gate = check_earnings_gate(tk)
            results.append({
                "ticker": tk,
                "status": gate["status"],
                "blocked": gate["blocked"],
                "reason": gate["reason"],
                "earnings_date": gate.get("earnings_date"),
            })
        return results
    except Exception as e:
        return [{"ticker": tk, "status": "ERROR", "blocked": False,
                 "reason": f"Earnings check failed: {e}"} for tk in candidate_tickers]


def check_correlation(candidate_tickers, portfolio, threshold=0.75):
    """Check price correlation between candidates and existing watchlist.

    Flag pairs with >75% daily return correlation (move together too closely).
    """
    import yfinance as yf
    import warnings
    warnings.filterwarnings("ignore")

    watchlist = list(set(portfolio.get("watchlist", [])))
    if not watchlist or not candidate_tickers:
        return []

    all_tickers = list(set(candidate_tickers + watchlist))

    try:
        hist = yf.download(all_tickers, period="3mo", interval="1d", progress=False)
        if hist.empty:
            return []

        # Compute daily returns
        close = hist["Close"]
        if hasattr(close, "columns") and len(close.columns) > 1:
            returns = close.pct_change().dropna()
        else:
            return []  # single ticker, no correlation possible

        results = []
        for tk in candidate_tickers:
            if tk not in returns.columns:
                continue
            high_corr = []
            for wt in watchlist:
                if wt not in returns.columns or wt == tk:
                    continue
                corr = returns[tk].corr(returns[wt])
                if not np.isnan(corr) and corr >= threshold:
                    high_corr.append((wt, round(corr, 2)))

            high_corr.sort(key=lambda x: x[1], reverse=True)
            results.append({
                "ticker": tk,
                "high_correlations": high_corr[:3],  # top 3 correlated
                "flag": len(high_corr) > 0,
                "note": f"Correlated with {', '.join(f'{w}({c})' for w, c in high_corr[:3])}"
                        if high_corr else "No high correlations",
            })

        return results
    except Exception as e:
        return [{"ticker": tk, "high_correlations": [], "flag": False,
                 "note": f"Correlation check failed: {e}"} for tk in candidate_tickers]


def check_liquidity(candidate_tickers, min_dollar_vol=500_000):
    """Check if tickers have enough volume for our $300 pool sizes."""
    import yfinance as yf
    import warnings
    warnings.filterwarnings("ignore")

    results = []
    for tk in candidate_tickers:
        try:
            hist = yf.Ticker(tk).history(period="1mo")
            if hist.empty:
                results.append({"ticker": tk, "flag": True, "note": "No data"})
                continue
            avg_vol = float(hist["Volume"].tail(20).mean())
            price = float(hist["Close"].iloc[-1])
            dollar_vol = avg_vol * price
            flag = dollar_vol < min_dollar_vol
            results.append({
                "ticker": tk,
                "avg_volume": int(avg_vol),
                "price": round(price, 2),
                "dollar_volume": int(dollar_vol),
                "flag": flag,
                "note": f"${dollar_vol/1e6:.1f}M/day" + (" — LOW LIQUIDITY" if flag else ""),
            })
        except Exception:
            results.append({"ticker": tk, "flag": True, "note": "Liquidity check failed"})

    return results


def validate(candidate_tickers):
    """Run all portfolio-level validations. Returns structured report."""
    portfolio = _load_portfolio()

    print(f"## Post-Simulation Validator\n")
    print(f"*Checking {len(candidate_tickers)} simulation-proven candidates*")
    print(f"*These checks are portfolio-level — they do NOT override simulation rankings*\n")

    # 1. Sector concentration
    print("### 1. Sector Concentration\n")
    sectors = check_sector_concentration(candidate_tickers, portfolio)
    print("| Ticker | Sector | In Sector After | Avg/Sector | Flag |")
    print("| :--- | :--- | :--- | :--- | :--- |")
    for s in sectors:
        flag = "**HIGH**" if s["flag"] else "ok"
        existing = ", ".join(s["existing_in_sector"]) if s["existing_in_sector"] else "none"
        print(f"| {s['ticker']} | {s['sector']} | {s['count_after']} ({existing}) | {s['avg_per_sector']} | {flag} |")

    # 2. Earnings blackout
    print("\n### 2. Earnings Blackout\n")
    earnings = check_earnings(candidate_tickers)
    print("| Ticker | Status | Detail |")
    print("| :--- | :--- | :--- |")
    for e in earnings:
        status = f"**{e['status']}**" if e["blocked"] else e["status"]
        print(f"| {e['ticker']} | {status} | {e['reason']} |")

    # 3. Price correlation
    print("\n### 3. Price Correlation with Watchlist (>75%)\n")
    correlations = check_correlation(candidate_tickers, portfolio)
    print("| Ticker | Correlated With | Flag |")
    print("| :--- | :--- | :--- |")
    for c in correlations:
        flag = "**YES**" if c["flag"] else "ok"
        print(f"| {c['ticker']} | {c['note']} | {flag} |")

    # 4. Liquidity
    print("\n### 4. Liquidity\n")
    liquidity = check_liquidity(candidate_tickers)
    print("| Ticker | Price | Avg Volume | $/Day | Flag |")
    print("| :--- | :--- | :--- | :--- | :--- |")
    for l in liquidity:
        flag = "**LOW**" if l["flag"] else "ok"
        print(f"| {l['ticker']} | ${l.get('price', '?')} | {l.get('avg_volume', '?'):,} | {l.get('note', '?')} | {flag} |")

    # Summary
    any_flags = (
        sum(1 for s in sectors if s["flag"]) +
        sum(1 for e in earnings if e["blocked"]) +
        sum(1 for c in correlations if c["flag"]) +
        sum(1 for l in liquidity if l["flag"])
    )

    print(f"\n### Summary\n")
    print(f"**{any_flags} flags across {len(candidate_tickers)} candidates**")
    if any_flags == 0:
        print(f"All candidates clear — ready for onboarding based on simulation ranking.")
    else:
        print(f"Flagged items require human review before onboarding.")
        print(f"Flags are informational — they do NOT override simulation P/L ranking.")

    return {
        "sectors": sectors,
        "earnings": earnings,
        "correlations": correlations,
        "liquidity": liquidity,
        "total_flags": any_flags,
    }


def main():
    import argparse
    p = argparse.ArgumentParser(description="Post-Simulation Validator")
    p.add_argument("--tickers", nargs="*", type=str.upper)
    args = p.parse_args()

    if args.tickers:
        tickers = args.tickers
    else:
        # Load from sim-ranked results
        results_path = RESULTS_DIR / "sim-ranked-results.json"
        if not results_path.exists():
            print("*No sim-ranked results found. Run sim_ranked_screener.py first.*")
            sys.exit(1)
        with open(results_path) as f:
            data = json.load(f)
        tickers = data.get("passed", [])
        if not tickers:
            tickers = [r["ticker"] for r in data.get("results", []) if r.get("passed")]

    if not tickers:
        print("*No candidates to validate.*")
        sys.exit(1)

    report = validate(tickers)

    # Save
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "validation-report.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
