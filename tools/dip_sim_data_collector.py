"""Dip Simulator Data Collector — Phase 1 of dip-sim-workflow.

Downloads all data needed for the simulation upfront:
1. Intraday OHLCV data for all tickers
2. VIX daily history for regime classification
3. Earnings dates per ticker (best-effort)
4. Eligibility pre-screen (daily range + recovery rate)
5. Buy-and-hold baseline for comparison

Usage:
    python3 tools/dip_sim_data_collector.py                    # defaults from portfolio watchlist
    python3 tools/dip_sim_data_collector.py --tickers LUNR CIFR CLSK --interval 1h
"""
import sys
import json
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_config import DipSimConfig, build_dip_argparse, args_to_dip_config

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"


def _load_watchlist():
    with open(PORTFOLIO_PATH) as f:
        data = json.load(f)
    return sorted(data.get("watchlist", []))


def collect_data(cfg):
    """Collect all data needed for simulation. Returns result dict."""
    import yfinance as yf
    import numpy as np

    tickers = cfg.tickers or _load_watchlist()
    if not tickers:
        return {"error": "No tickers to simulate"}

    result = {
        "generated": datetime.now().isoformat(),
        "config": json.loads(cfg.to_json()),
        "tickers_requested": tickers,
        "tickers_eligible": [],
        "tickers_excluded": {},
        "vix_history": {},
        "earnings_dates": {},
        "buy_hold_baseline": {},
        "data_range": {},
    }

    # --- 1. VIX history ---
    print("Fetching VIX history...")
    try:
        kwargs = {"progress": False}
        if cfg.start and cfg.end:
            kwargs.update(start=cfg.start, end=cfg.end)
        elif cfg.start:
            kwargs["start"] = cfg.start
        else:
            kwargs["period"] = "6mo"
        vix = yf.download("^VIX", **kwargs)
        if not vix.empty:
            close = vix["Close"]
            if hasattr(close, "columns"):
                close = close.iloc[:, 0]
            for dt, val in close.items():
                result["vix_history"][str(dt.date())] = round(float(val), 2)
            print(f"  VIX: {len(result['vix_history'])} days")
    except Exception as e:
        print(f"  *VIX fetch failed: {e}*")

    # --- 2. Eligibility pre-screen (daily data) ---
    print("Screening eligibility (daily data)...")
    try:
        daily = yf.download(tickers, period="3mo", interval="1d", progress=False)
        if not daily.empty:
            multi = len(tickers) > 1
            for tk in tickers:
                try:
                    if multi:
                        h = daily["High"][tk].dropna()
                        l = daily["Low"][tk].dropna()
                        c = daily["Close"][tk].dropna()
                    else:
                        h = daily["High"].dropna()
                        l = daily["Low"].dropna()
                        c = daily["Close"].dropna()

                    if len(h) < 21:
                        result["tickers_excluded"][tk] = "Insufficient daily data"
                        continue

                    # Daily range
                    daily_range = ((h - l) / l * 100).tail(21)
                    med_range = float(np.median(daily_range))

                    # Recovery rate: % of days where (high-low)/low >= 2%
                    low_to_high = ((h - l) / l * 100).tail(63)
                    recovery_2 = float((low_to_high >= 2).sum() / len(low_to_high) * 100)

                    if med_range < cfg.min_daily_range:
                        result["tickers_excluded"][tk] = f"daily_range {med_range:.1f}% < {cfg.min_daily_range}%"
                        continue
                    if recovery_2 < cfg.min_recovery_rate:
                        result["tickers_excluded"][tk] = f"recovery {recovery_2:.0f}% < {cfg.min_recovery_rate}%"
                        continue

                    result["tickers_eligible"].append(tk)

                    # Buy-and-hold baseline
                    start_price = float(c.iloc[0])
                    end_price = float(c.iloc[-1])
                    return_pct = round((end_price - start_price) / start_price * 100, 2)
                    result["buy_hold_baseline"][tk] = {
                        "start_price": round(start_price, 2),
                        "end_price": round(end_price, 2),
                        "return_pct": return_pct,
                    }
                except Exception:
                    result["tickers_excluded"][tk] = "Data extraction error"
                    continue

            print(f"  Eligible: {len(result['tickers_eligible'])}/{len(tickers)} tickers")
            if result["tickers_excluded"]:
                print(f"  Excluded: {', '.join(f'{k} ({v})' for k, v in result['tickers_excluded'].items())}")
    except Exception as e:
        print(f"  *Daily data fetch failed: {e} — using all tickers*")
        result["tickers_eligible"] = tickers

    # --- 3. Earnings dates (best-effort) ---
    print("Fetching earnings dates...")
    for tk in result["tickers_eligible"]:
        try:
            ticker_obj = yf.Ticker(tk)
            cal = ticker_obj.calendar
            if cal is not None and hasattr(cal, "get"):
                ed = cal.get("Earnings Date")
                if ed is not None:
                    if isinstance(ed, list) and ed:
                        result["earnings_dates"][tk] = str(ed[0].date()) if hasattr(ed[0], "date") else str(ed[0])
                    elif hasattr(ed, "date"):
                        result["earnings_dates"][tk] = str(ed.date())
            elif cal is not None and hasattr(cal, "iloc"):
                # Some yfinance versions return DataFrame
                result["earnings_dates"][tk] = None
        except Exception:
            result["earnings_dates"][tk] = None
    earns_found = sum(1 for v in result["earnings_dates"].values() if v)
    print(f"  Earnings dates found: {earns_found}/{len(result['tickers_eligible'])}")

    # --- 4. Data range info ---
    result["data_range"] = {
        "interval": cfg.interval,
        "start": cfg.start or "auto",
        "end": cfg.end or "today",
        "eligible_tickers": len(result["tickers_eligible"]),
    }

    return result


def main():
    parser = build_dip_argparse()
    args = parser.parse_args()
    cfg = args_to_dip_config(args)

    result = collect_data(cfg)

    # Write output
    out_dir = Path(cfg.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "sim-data.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\nWrote {out_path} ({len(result['tickers_eligible'])} eligible tickers)")


if __name__ == "__main__":
    main()
