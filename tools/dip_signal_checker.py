"""Dip Signal Checker — run at ~10:30 AM ET for buy/no-buy confirmation.

Two-step signal:
1. First hour breadth: how many tickers dipped >1% from open?
2. Second hour confirmation: how many are bouncing back?

If breadth dip + bounce confirmed -> show buy recommendations with current prices.
If no confirmation -> show STAY OUT warning.

Usage:
    python3 tools/dip_signal_checker.py              # all watchlist tickers
    python3 tools/dip_signal_checker.py LUNR CIFR AR  # specific tickers
"""
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

import pytz

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"
ET = pytz.timezone("US/Eastern")


def _market_time_to_utc_hour(et_hour, et_minute=0):
    """Convert ET time to UTC fractional hour for today, handling EDT/EST automatically."""
    now_et = datetime.now(ET)
    market_time = now_et.replace(hour=et_hour, minute=et_minute, second=0, microsecond=0)
    market_utc = market_time.astimezone(pytz.utc)
    return market_utc.hour + market_utc.minute / 60


def _get_market_phase():
    """Determine current market phase in Eastern Time."""
    now = datetime.now(pytz.timezone("US/Eastern"))
    h, m = now.hour, now.minute

    if h < 9 or (h == 9 and m < 30):
        return "PRE_MARKET", now
    elif (h == 9 and m >= 30) or (h == 10 and m < 30):
        return "FIRST_HOUR", now
    elif h == 10 and m >= 30:
        return "CONFIRMATION", now
    elif h < 14:
        return "MIDDAY", now
    elif h < 16:
        return "AFTERNOON", now
    else:
        return "AFTER_HOURS", now


def _load_candidates():
    """Get candidate tickers from portfolio.json (same logic as daily dip watchlist)."""
    with open(PORTFOLIO_PATH) as f:
        data = json.load(f)

    positions = data.get("positions", {})
    pending = data.get("pending_orders", {})
    watchlist = data.get("watchlist", [])

    candidates = set()
    for tk, pos in positions.items():
        if pos.get("shares", 0) > 0:
            candidates.add(tk)
    for tk in watchlist:
        if any(o.get("type") == "BUY" for o in pending.get(tk, [])):
            candidates.add(tk)

    return sorted(candidates)


def check_signal(tickers):
    """Fetch intraday data and compute dip signal."""
    import yfinance as yf

    hist = yf.download(tickers, period="1d", interval="5m", progress=False)
    if hist.empty:
        return None, "No intraday data available."

    # Normalize index to UTC (yfinance may return ET or UTC depending on version)
    if hist.index.tz is None:
        hist.index = hist.index.tz_localize("UTC")
    else:
        hist.index = hist.index.tz_convert("UTC")

    # Compute UTC hour thresholds dynamically (handles EDT/EST)
    fh_end_utc = _market_time_to_utc_hour(10, 30)  # 10:30 ET → UTC
    sh_end_utc = _market_time_to_utc_hour(11, 0)   # 11:00 ET → UTC

    multi = len(tickers) > 1
    results = []

    for tk in tickers:
        try:
            if multi:
                o = hist["Open"][tk].dropna()
                h = hist["High"][tk].dropna()
                l = hist["Low"][tk].dropna()
                c = hist["Close"][tk].dropna()
            else:
                o = hist["Open"].dropna()
                h = hist["High"].dropna()
                l = hist["Low"].dropna()
                c = hist["Close"].dropna()

            if len(o) < 3:
                continue

            today_open = float(o.iloc[0])

            # First hour: bars where UTC hour < 14.5 (before 10:30 ET)
            fh_mask = o.index.hour + o.index.minute / 60 < fh_end_utc
            first_hour = c[fh_mask]
            fh_low_series = l[fh_mask]

            if len(first_hour) == 0:
                continue

            fh_close = float(first_hour.iloc[-1])
            fh_low = float(fh_low_series.min())
            fh_move = (fh_close - today_open) / today_open * 100

            # Second hour: bars between 14:30 and 15:00 UTC (10:30-11:00 ET)
            sh_mask = (c.index.hour + c.index.minute / 60 >= fh_end_utc) & \
                      (c.index.hour + c.index.minute / 60 < sh_end_utc)
            second_hour = c[sh_mask]

            if len(second_hour) > 0:
                sh_close = float(second_hour.iloc[-1])
                sh_move = (sh_close - fh_close) / fh_close * 100
            else:
                sh_close = fh_close
                sh_move = 0.0

            # Current price (last available bar)
            current = float(c.iloc[-1])

            dipped = fh_move < -1.0
            bouncing = sh_move > 0.3
            below_open = current < today_open
            dip_from_open = (today_open - current) / today_open * 100

            results.append({
                "ticker": tk,
                "open": today_open,
                "fh_low": fh_low,
                "fh_close": fh_close,
                "fh_move": round(fh_move, 1),
                "sh_close": sh_close,
                "sh_move": round(sh_move, 1),
                "current": current,
                "dipped": dipped,
                "bouncing": bouncing,
                "below_open": below_open,
                "dip_from_open": round(dip_from_open, 1),
            })
        except Exception:
            continue

    return results, None


def print_signal(results, phase, now_et):
    """Print the dip signal report."""
    time_str = now_et.strftime("%I:%M %p ET")

    print(f"## Dip Signal Check ({time_str})\n")

    if not results:
        print("*No data available.*")
        return

    total = len(results)
    dipped_count = sum(1 for r in results if r["dipped"])
    bouncing_count = sum(1 for r in results if r["bouncing"])

    print(f"**Breadth:** {dipped_count}/{total} tickers dipped >1% in first hour")
    print(f"**Bounce:** {bouncing_count}/{total} recovering in second hour")

    # Determine signal (50% thresholds — optimized from backtesting)
    if dipped_count >= total * 0.5 and bouncing_count >= total * 0.5:
        signal = "CONFIRMED — BUY THE DIP (top 5 dippers)"
    elif dipped_count >= total * 0.5 and bouncing_count < total * 0.3:
        signal = "STAY OUT — selling continuing, dips not recovering"
    elif dipped_count < total * 0.3:
        signal = "NO DIP — tickers are up, no dip play today"
    else:
        signal = "MIXED — use judgment, not all tickers aligned"

    print(f"**Signal:** {signal}\n")

    # Phase-specific notes
    if phase == "FIRST_HOUR":
        print("*First hour still in progress — second-hour confirmation not available yet.*")
        print("*Check back at 10:30 AM ET for full signal.*\n")
    elif phase == "MIDDAY":
        print("*Late for first-hour dip play. Data reflects morning action.*\n")
    elif phase == "AFTERNOON":
        print("*Late in session. Consider selling stuck positions instead of new entries.*\n")

    # Buy recommendations (only for CONFIRMED signal)
    if "CONFIRMED" in signal or "MIXED" in signal:
        # Filter: dipped + bouncing + still below open
        buys = [r for r in results if r["dipped"] and r["bouncing"] and r["below_open"]]
        buys.sort(key=lambda x: x["dip_from_open"], reverse=True)  # biggest dip first
        top_buys = buys[:5]  # top 5 only (optimized from backtesting)

        if top_buys:
            print("### Buy Recommendations (Top 5)")
            print("*$100/ticker. Sell at +4%. Stop at -3%. Cut at EOD if neither hit.*\n")
            print("| # | Ticker | Open | 1st-Hr Low | Current | Dip% | Bounce | Sell +4% | Stop -3% |")
            print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            for i, r in enumerate(top_buys, 1):
                sell_4 = round(r["current"] * 1.04, 2)
                stop_3 = round(r["current"] * 0.97, 2)
                print(f"| {i} | {r['ticker']} | ${r['open']:.2f} | ${r['fh_low']:.2f} "
                      f"| ${r['current']:.2f} | -{r['dip_from_open']:.1f}% "
                      f"| +{r['sh_move']:.1f}% | ${sell_4:.2f} | ${stop_3:.2f} |")
            skipped = len(buys) - len(top_buys)
            if skipped > 0:
                print(f"\n*{skipped} more qualified but not in top 5.*")
            print(f"\n*Rules: sell at +4%, stop at -3%, cut at EOD. PDT: each = 1 day trade.*")
        else:
            print("*No tickers meet all criteria (dipped + bouncing + below open).*")

    elif "STAY OUT" in signal:
        print("*No buy recommendations. Dips are not recovering.*")
        print("*Check again at 11:30 AM if situation changes.*")

    elif "NO DIP" in signal:
        print("*No dip to buy. Tickers are trading above open.*")


def main():
    parser = argparse.ArgumentParser(description="Dip Signal Checker")
    parser.add_argument("tickers", nargs="*", type=str.upper,
                        help="Specific tickers (default: all watchlist)")
    args = parser.parse_args()

    phase, now_et = _get_market_phase()

    if phase == "PRE_MARKET":
        print("## Dip Signal Check\n")
        print("*Market not open. Run after 10:30 AM ET for confirmation signal.*")
        return

    if phase == "AFTER_HOURS":
        print("## Dip Signal Check\n")
        print("*Market closed. Run tomorrow morning after 10:30 AM ET.*")
        return

    # Get tickers
    if args.tickers:
        tickers = args.tickers
    else:
        tickers = _load_candidates()

    if not tickers:
        print("*No tickers to check.*")
        return

    results, error = check_signal(tickers)
    if error:
        print(f"*Error: {error}*")
        return

    print_signal(results, phase, now_et)


if __name__ == "__main__":
    main()
