"""Daily Range Analyzer — entry/exit for oscillation tickers.

For tickers with no viable support levels but good daily range.
Computes entry at previous close minus median dip, exit at +2% or +3%.

Usage:
    python3 tools/daily_range_analyzer.py AR
    python3 tools/daily_range_analyzer.py AR ARM NU
"""
import sys
import argparse
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def analyze_daily_range(ticker):
    """Compute daily range metrics and entry/exit recommendation."""
    import yfinance as yf
    import numpy as np

    hist = yf.download(ticker, period="3mo", interval="1d", progress=False)
    if hist.empty or len(hist) < 21:
        return {"ticker": ticker, "viable": False, "error": "Insufficient data"}

    # Use close-to-low for entry computation (consistent reference price)
    close_shifted = hist["Close"].shift(1)  # previous day's close
    close_to_low = ((close_shifted - hist["Low"]) / close_shifted * 100).dropna().values
    low_to_close = ((hist["Close"] - hist["Low"]) / hist["Low"] * 100).values
    daily_range = ((hist["High"] - hist["Low"]) / hist["Low"] * 100).values

    last_close = float(hist["Close"].iloc[-1])
    last_date = hist.index[-1].strftime("%Y-%m-%d")

    med_dip = float(np.median(close_to_low[-21:])) if len(close_to_low) >= 21 else float(np.median(close_to_low))
    med_recovery = float(np.median(low_to_close[-21:]))
    med_range = float(np.median(daily_range[-21:]))

    entry_price = round(last_close * (1 - med_dip / 100), 2)

    # Win rates at different targets
    win_2pct = round(float((low_to_close >= 2).sum() / len(low_to_close) * 100))
    win_3pct = round(float((low_to_close >= 3).sum() / len(low_to_close) * 100))

    # Determine best target
    if win_3pct >= 60:
        target_pct = 3.0
    elif win_2pct >= 60:
        target_pct = 2.0
    else:
        target_pct = None

    exit_price = round(entry_price * (1 + target_pct / 100), 2) if target_pct else None

    return {
        "ticker": ticker,
        "last_close": last_close,
        "last_date": last_date,
        "med_daily_range": round(med_range, 1),
        "med_dip_pct": round(med_dip, 2),
        "med_recovery_pct": round(med_recovery, 2),
        "entry_price": entry_price,
        "target_pct": target_pct,
        "exit_price": exit_price,
        "win_rate_2pct": win_2pct,
        "win_rate_3pct": win_3pct,
        "viable": target_pct is not None,
    }


def print_daily_range(result):
    """Print markdown output for a daily range analysis."""
    r = result
    if not r.get("viable") and r.get("error"):
        print(f"*Error: {r['error']}*")
        return

    print(f"## Daily Range Entry: {r['ticker']}")
    print(f"*Generated: {r.get('last_date', '?')} | Daily range oscillation strategy*\n")

    print("| Metric | Value |")
    print("| :--- | :--- |")
    print(f"| Last Close | ${r['last_close']:.2f} |")
    print(f"| Median Daily Range | {r['med_daily_range']:.1f}% |")
    print(f"| Median Dip (Close to Low) | {r['med_dip_pct']:.1f}% |")
    print(f"| Median Recovery (Low to Close) | {r['med_recovery_pct']:.1f}% |")
    print()

    print("| Entry | Price | Target | Win Rate |")
    print("| :--- | :--- | :--- | :--- |")
    if r["viable"]:
        print(f"| Dip Buy (-{r['med_dip_pct']:.1f}%) | ${r['entry_price']:.2f} "
              f"| ${r['exit_price']:.2f} (+{r['target_pct']:.0f}%) "
              f"| {r['win_rate_2pct'] if r['target_pct'] == 2 else r['win_rate_3pct']}% |")
    else:
        print(f"| — | — | — | Not viable (2% win rate: {r.get('win_rate_2pct', 0)}%) |")

    print(f"\n*PDT: Same-day round trip = 1 day trade (3/5-day limit at <$25K)*")


def main():
    parser = argparse.ArgumentParser(description="Daily Range Analyzer")
    parser.add_argument("tickers", nargs="+", type=str.upper, help="Ticker symbols")
    args = parser.parse_args()

    for ticker in args.tickers:
        result = analyze_daily_range(ticker)
        print_daily_range(result)
        if ticker != args.tickers[-1]:
            print("\n---\n")


if __name__ == "__main__":
    main()
