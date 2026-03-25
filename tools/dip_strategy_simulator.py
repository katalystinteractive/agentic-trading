"""Dip Strategy Simulator — backtest the daily fluctuation strategy on historical data.

Replays historical intraday data day by day using the two-step confirmation:
1. First hour breadth: 50%+ tickers dipping >1% from open?
2. Second hour bounce: 50%+ recovering?
3. If confirmed: buy top 5 dipped+bouncing tickers at ~10:30 AM price
4. Sell at +3%, stop at -3%, or cut at EOD (1-day max hold)

Usage:
    python3 tools/dip_strategy_simulator.py                          # last 3 months
    python3 tools/dip_strategy_simulator.py --start 2026-01-01       # from date to now
    python3 tools/dip_strategy_simulator.py --start 2026-01-01 --end 2026-03-01
    python3 tools/dip_strategy_simulator.py --interval 30m           # 30-min bars (longer history)
    python3 tools/dip_strategy_simulator.py --budget 150             # $150 per ticker per trade
"""
import sys
import json
import argparse
from datetime import datetime, timedelta, date
from pathlib import Path
from collections import defaultdict

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"

# Strategy parameters
DEFAULT_BUDGET = 100        # $ per ticker per trade
DIP_THRESHOLD = 1.0         # % dip from open to qualify
BOUNCE_THRESHOLD = 0.3      # % bounce in 2nd hour to confirm
BREADTH_RATIO = 0.5         # 50% of tickers must dip for signal (was 70%)
BOUNCE_RATIO = 0.5          # 50% must bounce for confirmation (was 70%)
SELL_TARGET_PCT = 3.0       # +3% from entry
MAX_HOLD_DAYS = 1           # cut at EOD if target not hit (was 3)
STOP_LOSS_PCT = -3.0        # cut losses at -3% (was -5%)
MAX_TICKERS_PER_SIGNAL = 5  # only buy top 5 dippers (was unlimited)


def _load_watchlist():
    """Get watchlist tickers from portfolio.json."""
    with open(PORTFOLIO_PATH) as f:
        data = json.load(f)
    return sorted(data.get("watchlist", []))


def _fetch_intraday(tickers, start, end, interval="5m"):
    """Fetch intraday data for simulation period."""
    import yfinance as yf

    # yfinance limits: 5m = ~60 days, 30m = ~6 months, 1h = ~2 years
    print(f"Fetching {interval} data for {len(tickers)} tickers...")

    if start and end:
        hist = yf.download(tickers, start=start, end=end, interval=interval, progress=False)
    elif start:
        hist = yf.download(tickers, start=start, interval=interval, progress=False)
    else:
        period = "60d" if interval == "5m" else "6mo"
        hist = yf.download(tickers, period=period, interval=interval, progress=False)

    if hist.empty:
        print("*Error: no data returned.*")
        return None

    # Normalize to UTC
    import pytz
    if hist.index.tz is None:
        hist.index = hist.index.tz_localize("UTC")
    else:
        hist.index = hist.index.tz_convert("UTC")

    print(f"  Data: {hist.index[0].date()} to {hist.index[-1].date()}, {len(hist)} bars")
    return hist


def _get_utc_offset(sample_date):
    """Get UTC offset for ET on a given date (handles EDT/EST)."""
    import pytz
    et = pytz.timezone("US/Eastern")
    dt = datetime(sample_date.year, sample_date.month, sample_date.day, 12, 0, tzinfo=pytz.utc)
    et_time = dt.astimezone(et)
    offset_hours = et_time.utcoffset().total_seconds() / 3600  # -4 for EDT, -5 for EST
    return -offset_hours  # positive: hours to ADD to ET to get UTC


def simulate(hist, tickers, budget=DEFAULT_BUDGET, interval="5m"):
    """Run the daily dip simulation on historical data."""
    import numpy as np

    multi = len(tickers) > 1
    dates = sorted(set(hist.index.date))
    bars_per_hour = 12 if interval == "5m" else (2 if interval == "30m" else 1)

    trades = []           # completed trades
    open_positions = []   # currently held positions
    daily_log = []        # per-day summary

    for day_idx, d in enumerate(dates):
        day_data = hist[hist.index.date == d]
        if len(day_data) < bars_per_hour * 2:  # need at least 2 hours of data
            continue

        # Determine UTC offset for this day
        utc_offset = _get_utc_offset(d)
        fh_end_utc = 10.5 + utc_offset    # 10:30 ET in UTC
        sh_end_utc = 11.0 + utc_offset    # 11:00 ET in UTC
        market_close_utc = 16.0 + utc_offset  # 4:00 PM ET in UTC

        # --- Check existing positions for exit ---
        still_open = []
        for pos in open_positions:
            tk = pos["ticker"]
            entry = pos["entry_price"]
            target = entry * (1 + SELL_TARGET_PCT / 100)
            stop = entry * (1 + STOP_LOSS_PCT / 100)
            days_held = (d - pos["entry_date"]).days

            try:
                if multi:
                    day_high = float(day_data["High"][tk].max())
                    day_low = float(day_data["Low"][tk].min())
                    day_close = float(day_data["Close"][tk].dropna().iloc[-1])
                else:
                    day_high = float(day_data["High"].max())
                    day_low = float(day_data["Low"].min())
                    day_close = float(day_data["Close"].dropna().iloc[-1])
            except (KeyError, IndexError):
                still_open.append(pos)
                continue

            if np.isnan(day_high) or np.isnan(day_close):
                still_open.append(pos)
                continue

            # Check exit conditions
            if day_high >= target:
                # Target hit — sell at target
                pnl_pct = SELL_TARGET_PCT
                pnl_dollars = pos["shares"] * entry * SELL_TARGET_PCT / 100
                trades.append({
                    "ticker": tk, "entry_date": pos["entry_date"], "exit_date": d,
                    "entry_price": round(entry, 2), "exit_price": round(target, 2),
                    "shares": pos["shares"], "pnl_pct": round(pnl_pct, 2),
                    "pnl_dollars": round(pnl_dollars, 2), "exit_reason": "TARGET",
                    "days_held": days_held,
                })
            elif day_low <= stop:
                # Stop loss hit
                pnl_pct = STOP_LOSS_PCT
                pnl_dollars = pos["shares"] * entry * STOP_LOSS_PCT / 100
                trades.append({
                    "ticker": tk, "entry_date": pos["entry_date"], "exit_date": d,
                    "entry_price": round(entry, 2), "exit_price": round(stop, 2),
                    "shares": pos["shares"], "pnl_pct": round(pnl_pct, 2),
                    "pnl_dollars": round(pnl_dollars, 2), "exit_reason": "STOP_LOSS",
                    "days_held": days_held,
                })
            elif days_held >= MAX_HOLD_DAYS:
                # Max hold — cut at close
                pnl_pct = round((day_close - entry) / entry * 100, 2)
                pnl_dollars = round(pos["shares"] * (day_close - entry), 2)
                trades.append({
                    "ticker": tk, "entry_date": pos["entry_date"], "exit_date": d,
                    "entry_price": round(entry, 2), "exit_price": round(day_close, 2),
                    "shares": pos["shares"], "pnl_pct": pnl_pct,
                    "pnl_dollars": pnl_dollars, "exit_reason": "MAX_HOLD",
                    "days_held": days_held,
                })
            else:
                still_open.append(pos)

        open_positions = still_open

        # --- Two-step signal check for new entries ---
        ticker_stats = []
        for tk in tickers:
            try:
                if multi:
                    tk_o = day_data["Open"][tk].dropna()
                    tk_c = day_data["Close"][tk].dropna()
                    tk_l = day_data["Low"][tk].dropna()
                else:
                    tk_o = day_data["Open"].dropna()
                    tk_c = day_data["Close"].dropna()
                    tk_l = day_data["Low"].dropna()

                if len(tk_o) < 3:
                    continue

                today_open = float(tk_o.iloc[0])
                if np.isnan(today_open) or today_open <= 0:
                    continue

                # First hour bars (before 10:30 ET)
                fh_mask = tk_c.index.hour + tk_c.index.minute / 60 < fh_end_utc
                fh_bars = tk_c[fh_mask]
                if len(fh_bars) == 0:
                    continue
                fh_close = float(fh_bars.iloc[-1])
                fh_low = float(tk_l[fh_mask].min())
                fh_move = (fh_close - today_open) / today_open * 100

                # Second hour bars (10:30-11:00 ET)
                sh_mask = (tk_c.index.hour + tk_c.index.minute / 60 >= fh_end_utc) & \
                          (tk_c.index.hour + tk_c.index.minute / 60 < sh_end_utc)
                sh_bars = tk_c[sh_mask]
                if len(sh_bars) > 0:
                    sh_close = float(sh_bars.iloc[-1])
                    sh_move = (sh_close - fh_close) / fh_close * 100
                else:
                    sh_close = fh_close
                    sh_move = 0.0

                # Current price at ~10:30-11:00
                confirmation_bars = tk_c[tk_c.index.hour + tk_c.index.minute / 60 <= sh_end_utc]
                current_price = float(confirmation_bars.iloc[-1]) if len(confirmation_bars) > 0 else fh_close

                dipped = fh_move < -DIP_THRESHOLD
                bouncing = sh_move > BOUNCE_THRESHOLD
                below_open = current_price < today_open

                dip_from_open = round((today_open - current_price) / today_open * 100, 1)
                ticker_stats.append({
                    "ticker": tk, "open": today_open, "fh_move": fh_move,
                    "sh_move": sh_move, "current": current_price,
                    "dipped": dipped, "bouncing": bouncing, "below_open": below_open,
                    "fh_low": fh_low, "dip_from_open": dip_from_open,
                })
            except Exception:
                continue

        # Breadth check
        total = len(ticker_stats)
        if total == 0:
            daily_log.append({"date": d, "signal": "NO_DATA", "entries": 0, "exits": len(trades)})
            continue

        dipped_count = sum(1 for t in ticker_stats if t["dipped"])
        bouncing_count = sum(1 for t in ticker_stats if t["bouncing"])

        if dipped_count >= total * BREADTH_RATIO and bouncing_count >= total * BOUNCE_RATIO:
            signal = "CONFIRMED"
        elif dipped_count >= total * BREADTH_RATIO and bouncing_count < total * 0.3:
            signal = "STAY_OUT"
        elif dipped_count < total * 0.3:
            signal = "NO_DIP"
        else:
            signal = "MIXED"

        # --- Execute entries on CONFIRMED signal ---
        day_entries = 0
        if signal == "CONFIRMED":
            buys = [t for t in ticker_stats if t["dipped"] and t["bouncing"] and t["below_open"]]
            # Don't buy if already holding this ticker
            held_tickers = {p["ticker"] for p in open_positions}
            buys = [b for b in buys if b["ticker"] not in held_tickers]
            # Sort by largest dip (most opportunity) and take top N
            buys.sort(key=lambda x: x["dip_from_open"], reverse=True)
            buys = buys[:MAX_TICKERS_PER_SIGNAL]

            for b in buys:
                shares = max(1, int(budget / b["current"]))
                open_positions.append({
                    "ticker": b["ticker"],
                    "entry_date": d,
                    "entry_price": b["current"],
                    "shares": shares,
                })
                day_entries += 1

        day_exits = sum(1 for t in trades if t["exit_date"] == d)
        daily_log.append({
            "date": d, "signal": signal, "entries": day_entries, "exits": day_exits,
            "dipped": dipped_count, "bouncing": bouncing_count, "total": total,
            "open_positions": len(open_positions),
        })

    # Force-close any remaining positions at last day's close
    last_date = dates[-1]
    last_day = hist[hist.index.date == last_date]
    for pos in open_positions:
        tk = pos["ticker"]
        try:
            if multi:
                close_price = float(last_day["Close"][tk].dropna().iloc[-1])
            else:
                close_price = float(last_day["Close"].dropna().iloc[-1])
            pnl_pct = round((close_price - pos["entry_price"]) / pos["entry_price"] * 100, 2)
            pnl_dollars = round(pos["shares"] * (close_price - pos["entry_price"]), 2)
        except Exception:
            close_price = pos["entry_price"]
            pnl_pct = 0.0
            pnl_dollars = 0.0

        trades.append({
            "ticker": tk, "entry_date": pos["entry_date"], "exit_date": last_date,
            "entry_price": round(pos["entry_price"], 2), "exit_price": round(close_price, 2),
            "shares": pos["shares"], "pnl_pct": pnl_pct,
            "pnl_dollars": pnl_dollars, "exit_reason": "SIM_END",
            "days_held": (last_date - pos["entry_date"]).days,
        })

    return trades, daily_log


def print_results(trades, daily_log, budget):
    """Print simulation results."""
    import numpy as np

    if not trades:
        print("\n*No trades executed during simulation period.*")
        return

    # --- Trade Log ---
    print("\n## Trade Log")
    print("| # | Ticker | Entry Date | Entry | Exit Date | Exit | Shares | P/L% | P/L$ | Days | Reason |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for i, t in enumerate(trades, 1):
        pnl_sign = "+" if t["pnl_pct"] >= 0 else ""
        print(f"| {i} | {t['ticker']} | {t['entry_date']} | ${t['entry_price']:.2f} "
              f"| {t['exit_date']} | ${t['exit_price']:.2f} | {t['shares']} "
              f"| {pnl_sign}{t['pnl_pct']:.1f}% | ${t['pnl_dollars']:.2f} "
              f"| {t['days_held']}d | {t['exit_reason']} |")

    # --- Summary Stats ---
    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    total_pnl = sum(t["pnl_dollars"] for t in trades)
    avg_pnl = np.mean([t["pnl_pct"] for t in trades])
    avg_hold = np.mean([t["days_held"] for t in trades])
    win_rate = len(wins) / len(trades) * 100 if trades else 0

    print(f"\n## Summary")
    print(f"| Metric | Value |")
    print(f"| :--- | :--- |")
    print(f"| Total trades | {len(trades)} |")
    print(f"| Wins | {len(wins)} ({win_rate:.0f}%) |")
    print(f"| Losses | {len(losses)} ({100 - win_rate:.0f}%) |")
    print(f"| Total P/L | ${total_pnl:.2f} |")
    print(f"| Avg P/L per trade | {avg_pnl:+.1f}% |")
    print(f"| Avg hold time | {avg_hold:.1f} days |")
    if wins:
        print(f"| Avg win | +{np.mean([t['pnl_pct'] for t in wins]):.1f}% (${np.mean([t['pnl_dollars'] for t in wins]):.2f}) |")
    if losses:
        print(f"| Avg loss | {np.mean([t['pnl_pct'] for t in losses]):.1f}% (${np.mean([t['pnl_dollars'] for t in losses]):.2f}) |")
    print(f"| Best trade | {max(trades, key=lambda t: t['pnl_pct'])['ticker']} +{max(trades, key=lambda t: t['pnl_pct'])['pnl_pct']:.1f}% |")
    print(f"| Worst trade | {min(trades, key=lambda t: t['pnl_pct'])['ticker']} {min(trades, key=lambda t: t['pnl_pct'])['pnl_pct']:.1f}% |")
    print(f"| Budget per trade | ${budget} |")

    # --- Exit Reason Breakdown ---
    reasons = defaultdict(list)
    for t in trades:
        reasons[t["exit_reason"]].append(t)

    print(f"\n## Exit Reasons")
    print(f"| Reason | Count | Avg P/L% | Total P/L$ |")
    print(f"| :--- | :--- | :--- | :--- |")
    for reason in ["TARGET", "STOP_LOSS", "MAX_HOLD", "SIM_END"]:
        if reason in reasons:
            r_trades = reasons[reason]
            r_avg = np.mean([t["pnl_pct"] for t in r_trades])
            r_total = sum(t["pnl_dollars"] for t in r_trades)
            print(f"| {reason} | {len(r_trades)} | {r_avg:+.1f}% | ${r_total:.2f} |")

    # --- Daily Signal Distribution ---
    signals = defaultdict(int)
    for d in daily_log:
        signals[d["signal"]] += 1

    print(f"\n## Signal Distribution")
    print(f"| Signal | Days | % |")
    print(f"| :--- | :--- | :--- |")
    total_days = len(daily_log)
    for sig in ["CONFIRMED", "STAY_OUT", "NO_DIP", "MIXED", "NO_DATA"]:
        if sig in signals:
            print(f"| {sig} | {signals[sig]} | {signals[sig] / total_days * 100:.0f}% |")

    # --- Monthly Breakdown ---
    monthly = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
    for t in trades:
        key = t["exit_date"].strftime("%Y-%m") if isinstance(t["exit_date"], date) else str(t["exit_date"])[:7]
        monthly[key]["trades"] += 1
        monthly[key]["pnl"] += t["pnl_dollars"]
        if t["pnl_pct"] > 0:
            monthly[key]["wins"] += 1

    print(f"\n## Monthly Breakdown")
    print(f"| Month | Trades | Wins | Win% | P/L$ |")
    print(f"| :--- | :--- | :--- | :--- | :--- |")
    for month in sorted(monthly):
        m = monthly[month]
        wr = m["wins"] / m["trades"] * 100 if m["trades"] > 0 else 0
        print(f"| {month} | {m['trades']} | {m['wins']} | {wr:.0f}% | ${m['pnl']:.2f} |")

    # --- Per-Ticker Breakdown ---
    ticker_stats = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
    for t in trades:
        tk = t["ticker"]
        ticker_stats[tk]["trades"] += 1
        ticker_stats[tk]["pnl"] += t["pnl_dollars"]
        if t["pnl_pct"] > 0:
            ticker_stats[tk]["wins"] += 1

    print(f"\n## Per-Ticker Performance")
    print(f"| Ticker | Trades | Wins | Win% | Total P/L$ |")
    print(f"| :--- | :--- | :--- | :--- | :--- |")
    for tk in sorted(ticker_stats, key=lambda k: ticker_stats[k]["pnl"], reverse=True):
        s = ticker_stats[tk]
        wr = s["wins"] / s["trades"] * 100 if s["trades"] > 0 else 0
        print(f"| {tk} | {s['trades']} | {s['wins']} | {wr:.0f}% | ${s['pnl']:.2f} |")

    # --- Comparison: Daily Dip vs Just Hold ---
    print(f"\n## Comparison")
    print(f"| Strategy | Total P/L$ | Trades | Avg P/L% |")
    print(f"| :--- | :--- | :--- | :--- |")
    print(f"| Daily Dip (this sim) | ${total_pnl:.2f} | {len(trades)} | {avg_pnl:+.1f}% |")
    # Estimate buy-and-hold: $100 per ticker at start, sell at end
    # (rough — uses first and last available close)
    print(f"| *Buy & Hold comparison requires daily close data — run with --compare flag* | | | |")


def main():
    parser = argparse.ArgumentParser(description="Dip Strategy Simulator")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--interval", type=str, default="5m",
                        choices=["5m", "15m", "30m", "1h"],
                        help="Bar interval (default: 5m, max ~60 days)")
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET,
                        help=f"Budget per ticker per trade (default: ${DEFAULT_BUDGET})")
    parser.add_argument("--tickers", nargs="*", type=str.upper,
                        help="Specific tickers (default: watchlist)")
    args = parser.parse_args()

    tickers = args.tickers or _load_watchlist()
    if not tickers:
        print("*No tickers to simulate.*")
        return

    print(f"## Dip Strategy Simulation")
    print(f"*Budget: ${args.budget}/ticker | Target: +{SELL_TARGET_PCT}% | "
          f"Stop: {STOP_LOSS_PCT}% | Max hold: {MAX_HOLD_DAYS}d*")
    print(f"*Tickers: {len(tickers)} | Interval: {args.interval}*\n")

    hist = _fetch_intraday(tickers, args.start, args.end, args.interval)
    if hist is None:
        return

    trades, daily_log = simulate(hist, tickers, budget=args.budget, interval=args.interval)
    print_results(trades, daily_log, args.budget)


if __name__ == "__main__":
    main()
