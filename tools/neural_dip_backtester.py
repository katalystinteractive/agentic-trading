"""Neural Dip Backtester — replay historical 5-min data through neural evaluation.

Downloads 5-min bars for ALL tickers, replays day-by-day through the same
build_first_hour_graph() + build_decision_graph() functions used live.
Computes P/L per trade and aggregate stats.

Usage:
    python3 tools/neural_dip_backtester.py                  # 60-day replay
    python3 tools/neural_dip_backtester.py --days 30         # 30-day replay
    python3 tools/neural_dip_backtester.py --cached           # reuse cached 5-min data
    python3 tools/neural_dip_backtester.py --json             # output JSON results
"""
import sys
import json
import time
import argparse
import pickle
from pathlib import Path
from datetime import date, timedelta
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import yfinance as yf

from neural_dip_evaluator import (
    build_first_hour_graph, build_decision_graph,
    DIP_CONFIG, _extract_col, _load_profiles, _load_weights,
)
from trading_calendar import is_trading_day, market_time_to_utc_hour

_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = _ROOT / "data" / "backtest"
INTRADAY_CACHE = CACHE_DIR / "intraday_5min_cache.pkl"
DAILY_CACHE = CACHE_DIR / "daily_backtest_cache.pkl"


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def download_intraday(tickers, days=60, interval="5m"):
    """Download intraday bars for all tickers. Cache to pickle.

    Supports 5m (60-day max) and 1h (730-day max) intervals.
    """
    max_days = 730 if interval == "1h" else 60
    days = min(days, max_days)
    cache_path = CACHE_DIR / f"intraday_{interval.replace('m','min')}_{days}d.pkl"

    print(f"Downloading {days}-day {interval} data for {len(tickers)} tickers...")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    data = yf.download(tickers, period=f"{days}d", interval=interval, progress=False)
    if data.empty:
        print("*Error: no intraday data returned.*")
        return None

    data.to_pickle(str(cache_path))
    bars = len(data)
    print(f"Cached {bars} bars to {cache_path}")
    return data


def download_daily(tickers, days=90):
    """Download daily OHLCV for regime + historical range computation per day."""
    print(f"Downloading {days}-day daily data for regime/range context...")

    data = yf.download(tickers, period=f"{days}d", interval="1d", progress=False)
    if data.empty:
        print("*Error: no daily data returned.*")
        return None

    data.to_pickle(str(DAILY_CACHE))
    print(f"Cached daily data to {DAILY_CACHE}")
    return data


def load_cached(path):
    """Load cached pickle data."""
    if path.exists():
        return pickle.load(open(path, "rb"))
    return None


# ---------------------------------------------------------------------------
# Per-day context computation (prevents look-ahead bias)
# ---------------------------------------------------------------------------

def compute_regime_for_day(daily_data, day, tickers):
    """Compute regime for a specific day using only prior data (no look-ahead)."""
    try:
        # Simple VIX-based regime (matching daily_analyzer logic)
        # Use ^VIX if available, otherwise default Neutral
        vix_data = yf.download("^VIX", start=(day - timedelta(days=10)).isoformat(),
                               end=day.isoformat(), interval="1d", progress=False)
        if vix_data.empty or len(vix_data) < 1:
            return "Neutral"
        vix = float(vix_data["Close"].iloc[-1])
        if vix >= 25:
            return "Risk-Off"
        elif vix <= 15:
            return "Risk-On"
        return "Neutral"
    except Exception:
        return "Neutral"


def compute_ranges_for_day(daily_data, tickers, day, lookback=21):
    """Compute historical range/recovery stats using data BEFORE this day."""
    n = len(tickers)
    result = {}
    cfg = DIP_CONFIG

    try:
        prior = daily_data[daily_data.index.date < day]
        if len(prior) < lookback:
            prior = daily_data  # not enough prior data, use all
        else:
            prior = prior.iloc[-lookback:]
    except Exception:
        return {tk: {"range_pct": 0, "recovery_pct": 0, "viable": False}
                for tk in tickers}

    for tk in tickers:
        try:
            highs = _extract_col(prior, "High", tk, n).values
            lows = _extract_col(prior, "Low", tk, n).values
            if len(highs) < 5:
                result[tk] = {"range_pct": 0, "recovery_pct": 0, "viable": False}
                continue
            daily_range = (highs - lows) / lows * 100
            med_range = round(float(np.median(daily_range)), 1)
            low_to_high = (highs - lows) / lows * 100
            recovery_days = int((low_to_high >= 3.0).sum())
            recovery_pct = round(recovery_days / len(low_to_high) * 100)
            result[tk] = {
                "range_pct": med_range,
                "recovery_pct": recovery_pct,
                "viable": (med_range >= cfg["range_threshold_pct"]
                           and recovery_pct >= cfg["recovery_threshold_pct"]),
            }
        except Exception:
            result[tk] = {"range_pct": 0, "recovery_pct": 0, "viable": False}

    return result


# ---------------------------------------------------------------------------
# Day replay
# ---------------------------------------------------------------------------

def replay_day(day, day_bars, tickers, static, hist_ranges, regime, n_tickers,
               profiles=None, weights=None):
    """Replay one trading day through the neural evaluation phases.

    Returns dict with: day, signal, buys [{ticker, entry, pnl, exit_reason}]
    """
    if len(day_bars) < 12:
        return {"day": str(day), "signal": "INSUFFICIENT_DATA", "buys": []}

    # Phase 2: First-hour graph (bars 0-12 = first hour of 5-min data)
    fh_bars = day_bars.iloc[:12]
    try:
        _, fh_state = build_first_hour_graph(
            tickers, fh_bars, static, hist_ranges, regime, profiles, weights)
    except Exception as e:
        return {"day": str(day), "signal": f"FH_ERROR: {e}", "buys": []}

    if not fh_state.get("breadth_dip"):
        return {"day": str(day), "signal": "NO_DIP", "buys": []}

    # Phase 3: Decision graph (bars up to ~18 = 90 min of data)
    decision_bars = day_bars.iloc[:min(18, len(day_bars))]
    try:
        decision_graph, top, budget = build_decision_graph(
            tickers, decision_bars, fh_state, static, hist_ranges, regime,
            profiles, weights)
    except Exception as e:
        return {"day": str(day), "signal": f"DECISION_ERROR: {e}", "buys": []}

    # Check BUY_DIP neurons — check node value directly (no signal diffing in backtest)
    buy_tickers = []
    for name, node in decision_graph.nodes.items():
        if name.endswith(":buy_dip") and node.is_report and node.value:
            buy_tickers.append(name.split(":")[0])

    if not buy_tickers:
        # Check if signal was confirmed but no candidates passed
        sc = decision_graph.nodes.get("signal_confirmed")
        if sc and sc.value:
            return {"day": str(day), "signal": "NO_CANDIDATES", "buys": []}
        return {"day": str(day), "signal": "NOT_CONFIRMED", "buys": []}

    # Compute P/L for each buy using remaining bars (after decision time)
    remaining = day_bars.iloc[18:] if len(day_bars) > 18 else None
    buys = []

    for tk in buy_tickers:
        candidate = next((c for c in top if c["ticker"] == tk), None)
        if not candidate:
            continue

        entry = candidate["entry"]
        target = candidate["target"]
        stop = candidate["stop"]

        if entry <= 0:
            continue

        if remaining is not None and len(remaining) > 0:
            try:
                tk_high = _extract_col(remaining, "High", tk, n_tickers)
                tk_low = _extract_col(remaining, "Low", tk, n_tickers)
                tk_close = _extract_col(remaining, "Close", tk, n_tickers)

                day_high = float(tk_high.max()) if len(tk_high) > 0 else entry
                day_low = float(tk_low.min()) if len(tk_low) > 0 else entry
                eod = float(tk_close.iloc[-1]) if len(tk_close) > 0 else entry

                # Stop checked first (conservative)
                if day_low <= stop:
                    pnl = stop - entry
                    exit_reason = "STOP"
                elif day_high >= target:
                    pnl = target - entry
                    exit_reason = "TARGET"
                else:
                    pnl = eod - entry
                    exit_reason = "EOD_CUT"
            except Exception:
                pnl = 0
                exit_reason = "DATA_ERROR"
        else:
            pnl = 0
            exit_reason = "NO_REMAINING_DATA"

        buys.append({
            "ticker": tk,
            "entry": round(entry, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl / entry * 100, 2) if entry > 0 else 0,
            "exit_reason": exit_reason,
        })

    return {"day": str(day), "signal": "CONFIRMED", "buys": buys}


# ---------------------------------------------------------------------------
# Main backtest loop
# ---------------------------------------------------------------------------

def backtest_neural_dip(tickers, days=60, use_cached=False, profiles=None,
                        weights=None, interval="5m"):
    """Replay historical intraday data through neural evaluation phases.

    Supports 5m (60-day max) and 1h (730-day max) intervals.
    """
    if profiles is None:
        profiles = _load_profiles()
    if weights is None:
        weights = _load_weights()

    max_days = 730 if interval == "1h" else 60
    days = min(days, max_days)
    cache_path = CACHE_DIR / f"intraday_{interval.replace('m','min')}_{days}d.pkl"

    # Load or download intraday data
    if use_cached and cache_path.exists():
        print(f"Loading cached {interval} data from {cache_path}...")
        intraday = load_cached(cache_path)
    else:
        intraday = download_intraday(tickers, days, interval=interval)

    if intraday is None or intraday.empty:
        print("*No intraday data available. Cannot backtest.*")
        return []

    # Load or download daily data (for per-day regime/range context)
    if use_cached and DAILY_CACHE.exists():
        print(f"Loading cached daily data from {DAILY_CACHE}...")
        daily = load_cached(DAILY_CACHE)
    else:
        daily = download_daily(tickers, days + 30)

    if daily is None:
        daily = intraday  # fallback: use intraday for ranges (less accurate)

    # Get trading days from intraday data
    all_dates = sorted(set(intraday.index.date))
    trading_days = [d for d in all_dates if is_trading_day(d)]
    n = len(tickers)

    print(f"\nReplaying {len(trading_days)} trading days...")
    print(f"Tickers: {len(tickers)}")
    print()

    results = []
    for i, day in enumerate(trading_days):
        day_bars = intraday[intraday.index.date == day]

        # Per-day context (no look-ahead bias)
        regime = compute_regime_for_day(daily, day, tickers)
        hist_ranges = compute_ranges_for_day(daily, tickers, day)

        # Static neurons: UNKNOWN for all (no graph_state history for backtest)
        static = {tk: {"verdict": ["UNKNOWN"], "catastrophic": None,
                       "dip_viable": "UNKNOWN", "earnings_gate": "CLEAR"}
                  for tk in tickers}

        result = replay_day(day, day_bars, tickers, static, hist_ranges, regime, n,
                            profiles, weights)
        results.append(result)

        # Progress
        signal = result["signal"]
        n_buys = len(result["buys"])
        day_pnl = sum(b["pnl"] for b in result["buys"])
        marker = ""
        if signal == "CONFIRMED" and n_buys > 0:
            marker = f" → {n_buys} buys, P/L ${day_pnl:.2f}"
        if (i + 1) % 10 == 0 or signal == "CONFIRMED":
            print(f"  [{i+1}/{len(trading_days)}] {day} {signal}{marker}")

    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_summary(results, tickers):
    """Print backtest summary statistics."""
    total_days = len(results)
    signal_days = sum(1 for r in results if r["signal"] == "CONFIRMED")
    no_dip_days = sum(1 for r in results if r["signal"] == "NO_DIP")
    no_cand_days = sum(1 for r in results if r["signal"] == "NO_CANDIDATES")

    all_buys = [b for r in results for b in r["buys"]]
    wins = [b for b in all_buys if b["pnl"] > 0]
    losses = [b for b in all_buys if b["pnl"] < 0]
    total_pnl = sum(b["pnl"] for b in all_buys)

    # Exit reason breakdown
    exits = defaultdict(int)
    for b in all_buys:
        exits[b["exit_reason"]] += 1

    # Per-ticker breakdown
    ticker_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
    for b in all_buys:
        ts = ticker_stats[b["ticker"]]
        ts["trades"] += 1
        if b["pnl"] > 0:
            ts["wins"] += 1
        ts["pnl"] += b["pnl"]

    print(f"\n{'='*60}")
    print(f"Neural Dip Backtest Summary")
    print(f"{'='*60}\n")

    print(f"| Metric | Value |")
    print(f"| :--- | :--- |")
    print(f"| Trading days | {total_days} |")
    print(f"| Signal CONFIRMED days | {signal_days} ({round(signal_days/total_days*100) if total_days else 0}%) |")
    print(f"| NO_DIP days | {no_dip_days} |")
    print(f"| NO_CANDIDATES days | {no_cand_days} |")
    print(f"| Total trades | {len(all_buys)} |")
    print(f"| Wins | {len(wins)} |")
    print(f"| Losses | {len(losses)} |")
    print(f"| Win rate | {round(len(wins)/len(all_buys)*100, 1) if all_buys else 0}% |")
    print(f"| Total P/L | ${total_pnl:.2f} |")
    print(f"| Avg P/L per trade | ${total_pnl/len(all_buys):.2f} |" if all_buys else "")

    if exits:
        print(f"\n### Exit Reasons\n")
        print(f"| Reason | Count |")
        print(f"| :--- | :--- |")
        for reason, count in sorted(exits.items()):
            print(f"| {reason} | {count} |")

    if ticker_stats:
        print(f"\n### Per-Ticker Breakdown\n")
        print(f"| Ticker | Trades | Wins | Win% | P/L |")
        print(f"| :--- | :--- | :--- | :--- | :--- |")
        for tk in sorted(ticker_stats.keys()):
            ts = ticker_stats[tk]
            wr = round(ts["wins"] / ts["trades"] * 100) if ts["trades"] else 0
            print(f"| {tk} | {ts['trades']} | {ts['wins']} | {wr}% | ${ts['pnl']:.2f} |")

    # Sharpe ratio
    if len(all_buys) > 1:
        pnl_array = np.array([b["pnl"] for b in all_buys])
        mean_pnl = float(np.mean(pnl_array))
        std_pnl = float(np.std(pnl_array, ddof=1))
        if std_pnl > 0:
            sharpe = mean_pnl / std_pnl * np.sqrt(252)
            print(f"\n| Sharpe ratio (annualized) | {sharpe:.2f} |")

    print(f"\n{'='*60}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Neural Dip Backtester")
    parser.add_argument("--days", type=int, default=60,
                        help="Number of days to backtest (max 60 for 5m, 730 for 1h)")
    parser.add_argument("--interval", choices=["5m", "1h"], default="5m",
                        help="Bar interval: 5m (60-day max) or 1h (730-day max)")
    parser.add_argument("--cached", action="store_true",
                        help="Use cached intraday data instead of downloading")
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")
    args = parser.parse_args()

    max_days = 730 if args.interval == "1h" else 60
    days = min(args.days, max_days)

    # Load tickers from portfolio
    try:
        from neural_dip_evaluator import _load_portfolio, _get_dip_candidates
        portfolio = _load_portfolio()
        tickers = _get_dip_candidates(portfolio)
    except Exception as e:
        print(f"*Error loading portfolio: {e}*")
        return

    if not tickers:
        print("No tickers to backtest.")
        return

    print(f"Neural Dip Backtester — {days} days, {args.interval} bars, {len(tickers)} tickers")

    results = backtest_neural_dip(tickers, days, use_cached=args.cached,
                                  interval=args.interval)

    if not results:
        print("No results.")
        return

    if args.json:
        out_path = CACHE_DIR / "neural_dip_backtest_results.json"
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nJSON results saved to {out_path}")
    else:
        print_summary(results, tickers)


if __name__ == "__main__":
    main()
