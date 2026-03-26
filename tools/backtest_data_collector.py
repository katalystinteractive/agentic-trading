"""Surgical Backtest Data Collector — Phase 1 of backtest-surgical-workflow.

Downloads ALL historical data upfront for look-ahead-bias-free simulation:
1. Daily OHLCV for each ticker (13-month warmup + simulation window)
2. VIX daily for regime classification
3. SPY/QQQ/IWM daily + 50-SMA for regime computation
4. Earnings dates (best-effort)

Usage:
    python3 tools/backtest_data_collector.py --tickers LUNR CIFR CLSK --start 2025-06-01
    python3 tools/backtest_data_collector.py --start 2025-01-01 --end 2026-03-01
"""
import sys
import json
import pickle
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_config import SurgicalSimConfig

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"
REGIME_INDICES = ["SPY", "QQQ", "IWM"]


def _load_watchlist():
    with open(PORTFOLIO_PATH) as f:
        data = json.load(f)
    return sorted(data.get("watchlist", []))


def collect_data(cfg):
    """Download and cache all data for surgical backtest."""
    import yfinance as yf

    tickers = cfg.tickers or _load_watchlist()
    if not tickers:
        print("*Error: No tickers*")
        sys.exit(1)

    # Compute date range with warmup
    if cfg.end:
        end_date = datetime.strptime(cfg.end, "%Y-%m-%d")
    else:
        end_date = datetime.now()

    if cfg.start:
        sim_start = datetime.strptime(cfg.start, "%Y-%m-%d")
    else:
        sim_start = end_date - timedelta(days=365)

    # Warmup: 13 months before sim start for wick analysis + 70 days for 50-SMA
    warmup_days = cfg.wick_lookback_months * 30 + 70
    data_start = sim_start - timedelta(days=warmup_days)

    start_str = data_start.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    sim_start_str = sim_start.strftime("%Y-%m-%d")

    print(f"Date range: data from {start_str}, sim from {sim_start_str}, end {end_str}")
    print(f"Tickers: {len(tickers)}")

    # --- 1. Ticker OHLCV (daily bars) ---
    print(f"\nFetching daily data for {len(tickers)} tickers...")
    price_data = {}
    try:
        all_tickers = tickers + REGIME_INDICES + ["^VIX"]
        hist = yf.download(all_tickers, start=start_str, end=end_str,
                          auto_adjust=True, progress=False)

        if hist.empty:
            print("*Error: No data returned from yfinance*")
            sys.exit(1)

        multi = len(all_tickers) > 1

        for tk in tickers:
            try:
                if multi:
                    tk_data = {
                        "Open": hist["Open"][tk].dropna(),
                        "High": hist["High"][tk].dropna(),
                        "Low": hist["Low"][tk].dropna(),
                        "Close": hist["Close"][tk].dropna(),
                        "Volume": hist["Volume"][tk].dropna(),
                    }
                else:
                    tk_data = {
                        "Open": hist["Open"].dropna(),
                        "High": hist["High"].dropna(),
                        "Low": hist["Low"].dropna(),
                        "Close": hist["Close"].dropna(),
                        "Volume": hist["Volume"].dropna(),
                    }
                if len(tk_data["Close"]) >= 60:
                    price_data[tk] = tk_data
                    print(f"  {tk}: {len(tk_data['Close'])} days")
                else:
                    print(f"  {tk}: insufficient data ({len(tk_data['Close'])} days)")
            except Exception as e:
                print(f"  {tk}: error — {e}")

        # --- 2. Regime data (VIX + indices) ---
        print(f"\nComputing regime history...")
        regime_data = {}
        try:
            vix_close = hist["Close"]["^VIX"].dropna() if multi else hist["Close"].dropna()
            index_data = {}
            for idx in REGIME_INDICES:
                if multi:
                    idx_close = hist["Close"][idx].dropna()
                else:
                    idx_close = hist["Close"].dropna()
                # Compute 50-SMA
                sma50 = idx_close.rolling(window=50, min_periods=50).mean()
                index_data[idx] = {"close": idx_close, "sma50": sma50}

            # For each trading day, classify regime
            dates_in_range = vix_close.index
            for dt in dates_in_range:
                dt_date = dt.date() if hasattr(dt, "date") else dt
                if str(dt_date) < sim_start_str:
                    continue  # only store regime for sim window

                vix_val = float(vix_close.loc[dt]) if dt in vix_close.index else None
                if vix_val is None:
                    continue

                above_count = 0
                total_indices = 0
                for idx in REGIME_INDICES:
                    if dt in index_data[idx]["close"].index and dt in index_data[idx]["sma50"].index:
                        close = float(index_data[idx]["close"].loc[dt])
                        sma = float(index_data[idx]["sma50"].loc[dt])
                        if not np.isnan(sma):
                            total_indices += 1
                            if close > sma:
                                above_count += 1

                # Classify
                if total_indices == 0:
                    regime = "Neutral"
                elif vix_val < cfg.vix_risk_on and above_count > total_indices / 2:
                    regime = "Risk-On"
                elif vix_val > cfg.vix_risk_off and above_count <= total_indices / 2:
                    regime = "Risk-Off"
                else:
                    regime = "Neutral"

                regime_data[str(dt_date)] = {
                    "regime": regime,
                    "vix": round(vix_val, 2),
                    "indices_above_50sma": above_count,
                    "indices_total": total_indices,
                }

            print(f"  Regime days: {len(regime_data)}")
            regime_counts = {}
            for rd in regime_data.values():
                r = rd["regime"]
                regime_counts[r] = regime_counts.get(r, 0) + 1
            for r, c in sorted(regime_counts.items()):
                print(f"    {r}: {c} days ({c / len(regime_data) * 100:.0f}%)")

        except Exception as e:
            print(f"  *Regime computation failed: {e}*")

    except Exception as e:
        print(f"*Error downloading data: {e}*")
        sys.exit(1)

    # --- 3. Earnings dates (best-effort) ---
    print(f"\nFetching earnings dates...")
    earnings_dates = {}
    for tk in tickers:
        try:
            cal = yf.Ticker(tk).calendar
            if cal is not None and hasattr(cal, "get"):
                ed = cal.get("Earnings Date")
                if ed and isinstance(ed, list) and ed:
                    earnings_dates[tk] = str(ed[0].date()) if hasattr(ed[0], "date") else str(ed[0])
        except Exception:
            pass
    earns_found = sum(1 for v in earnings_dates.values() if v)
    print(f"  Found: {earns_found}/{len(tickers)}")

    return {
        "price_data": price_data,
        "regime_data": regime_data,
        "earnings_dates": earnings_dates,
        "config": json.loads(cfg.to_json()),
        "tickers": list(price_data.keys()),
        "date_range": {
            "data_start": start_str,
            "sim_start": sim_start_str,
            "end": end_str,
            "warmup_days": warmup_days,
        },
        "generated": datetime.now().isoformat(),
    }


def save_data(data, output_dir):
    """Save collected data to output directory."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Price data as pickle (preserves pandas Series)
    with open(out / "price_data.pkl", "wb") as f:
        pickle.dump(data["price_data"], f)

    # Regime data as JSON
    with open(out / "regime_data.json", "w") as f:
        json.dump(data["regime_data"], f, indent=2)

    # Config snapshot for reproducibility
    config_out = {
        "config": data["config"],
        "tickers": data["tickers"],
        "date_range": data["date_range"],
        "earnings_dates": data["earnings_dates"],
        "generated": data["generated"],
    }
    with open(out / "config.json", "w") as f:
        json.dump(config_out, f, indent=2)

    print(f"\nSaved to {out}/:")
    print(f"  price_data.pkl ({len(data['price_data'])} tickers)")
    print(f"  regime_data.json ({len(data['regime_data'])} days)")
    print(f"  config.json")


def main():
    import argparse
    p = argparse.ArgumentParser(description="Surgical Backtest Data Collector")
    p.add_argument("--tickers", nargs="*", type=str.upper)
    p.add_argument("--start", type=str, default="")
    p.add_argument("--end", type=str, default="")
    p.add_argument("--output-dir", default="data/backtest/latest")
    p.add_argument("--wick-lookback-months", type=int, default=13)
    p.add_argument("--vix-risk-on", type=float, default=20.0)
    p.add_argument("--vix-risk-off", type=float, default=25.0)
    args = p.parse_args()

    cfg = SurgicalSimConfig(
        tickers=args.tickers or [],
        start=args.start,
        end=args.end,
        output_dir=args.output_dir,
        wick_lookback_months=args.wick_lookback_months,
        vix_risk_on=args.vix_risk_on,
        vix_risk_off=args.vix_risk_off,
    )

    data = collect_data(cfg)
    save_data(data, args.output_dir)


if __name__ == "__main__":
    main()
