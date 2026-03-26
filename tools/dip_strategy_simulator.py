"""Dip Strategy Simulator — backtest the daily fluctuation strategy on historical data.

Replays historical intraday data day by day using the two-step confirmation:
1. First hour breadth: 50%+ tickers dipping >1% from open?
2. Second hour bounce: 50%+ recovering?
3. If confirmed: buy top 5 dipped+bouncing tickers at ~10:30 AM price
4. Sell at +3%, stop at -3%, or cut at EOD (1-day max hold)

All parameters tunable via CLI flags or DipSimConfig from backtest_config.py.

Usage:
    python3 tools/dip_strategy_simulator.py                          # defaults
    python3 tools/dip_strategy_simulator.py --interval 30m           # 6-month backtest
    python3 tools/dip_strategy_simulator.py --sell-target 4 --stop-loss -2  # tune exits
    python3 tools/dip_strategy_simulator.py --vix-threshold 20       # filter Risk-Off days
    python3 tools/dip_strategy_simulator.py --sweep --sweep-params "sell_target_pct=2:1:5"
"""
import sys
import json
from datetime import datetime, timedelta, date
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_config import DipSimConfig, build_dip_argparse, args_to_dip_config, parse_sweep_spec, apply_sweep_overrides

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"

# Legacy constants kept for reference — actual values come from DipSimConfig
DEFAULT_BUDGET = 100
DIP_THRESHOLD = 1.0
BOUNCE_THRESHOLD = 0.3
BREADTH_RATIO = 0.5
BOUNCE_RATIO = 0.5
SELL_TARGET_PCT = 3.0
MAX_HOLD_DAYS = 1
STOP_LOSS_PCT = -3.0
MAX_TICKERS_PER_SIGNAL = 5


def _load_watchlist():
    """Get watchlist tickers from portfolio.json."""
    with open(PORTFOLIO_PATH) as f:
        data = json.load(f)
    return sorted(data.get("watchlist", []))


def _fetch_vix_history(start, end):
    """Fetch daily VIX closes for regime filtering."""
    import yfinance as yf
    try:
        kwargs = {"progress": False}
        if start and end:
            kwargs.update(start=start, end=end)
        elif start:
            kwargs["start"] = start
        else:
            kwargs["period"] = "6mo"
        vix = yf.download("^VIX", **kwargs)
        if vix.empty:
            return None
        close = vix["Close"]
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
        result = {}
        for dt, val in close.items():
            result[str(dt.date())] = round(float(val), 2)
        print(f"  VIX data: {len(result)} days")
        return result
    except Exception as e:
        print(f"  *VIX fetch failed: {e} — proceeding without regime filter*")
        return None


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


def simulate(hist, tickers, config=None, budget=None, interval=None, vix_history=None):
    """Run the daily dip simulation on historical data.

    Args:
        hist: DataFrame with intraday OHLCV data (UTC-normalized)
        tickers: list of ticker symbols
        config: DipSimConfig (preferred). If None, uses defaults.
        budget: legacy parameter (overridden by config.budget if config provided)
        interval: legacy parameter (overridden by config.interval if config provided)
        vix_history: optional dict {date_str: vix_close} for regime filtering

    Returns:
        (trades, daily_log, equity_curve, pdt_log)
    """
    import numpy as np

    if config is None:
        config = DipSimConfig()
    if budget is not None and config.budget == 100.0:
        config.budget = budget
    if interval is not None and config.interval == "5m":
        config.interval = interval

    cfg = config  # shorthand

    multi = len(tickers) > 1
    dates = sorted(set(hist.index.date))
    bars_per_hour = 12 if cfg.interval == "5m" else (2 if cfg.interval == "30m" else 1)

    trades = []           # completed trades
    open_positions = []   # currently held positions
    daily_log = []        # per-day summary
    equity_curve = []     # daily cumulative P/L
    pdt_log = []          # PDT violation tracking
    cumulative_pnl = 0.0
    dip_pool = cfg.budget * cfg.max_tickers_per_signal * 2  # total pool for dip strategy

    for day_idx, d in enumerate(dates):
        day_data = hist[hist.index.date == d]
        if len(day_data) < bars_per_hour * 2:  # need at least 2 hours of data
            continue

        # Determine UTC offset for this day
        utc_offset = _get_utc_offset(d)
        fh_end_utc = cfg.fh_end_et + utc_offset
        sh_end_utc = cfg.sh_end_et + utc_offset
        market_close_utc = 16.0 + utc_offset

        # VIX regime check
        day_regime = "Neutral"
        if vix_history:
            day_vix = vix_history.get(str(d))
            if day_vix is not None and day_vix >= cfg.vix_risk_off:
                day_regime = "Risk-Off"

        # --- Check existing positions for exit ---
        still_open = []
        for pos in open_positions:
            tk = pos["ticker"]
            entry = pos["entry_price"]
            target = entry * (1 + cfg.sell_target_pct / 100)
            stop = entry * (1 + cfg.stop_loss_pct / 100)
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

            # Check exit conditions — when both target and stop could trigger
            # on the same day, check stop first (conservative: assume adverse move
            # happens before favorable move to avoid optimistic bias)
            if day_low <= stop:
                # Stop loss hit
                pnl_pct = cfg.stop_loss_pct
                pnl_dollars = pos["shares"] * entry * cfg.stop_loss_pct / 100
                trades.append({
                    "ticker": tk, "entry_date": pos["entry_date"], "exit_date": d,
                    "entry_price": round(entry, 2), "exit_price": round(stop, 2),
                    "shares": pos["shares"], "pnl_pct": round(pnl_pct, 2),
                    "pnl_dollars": round(pnl_dollars, 2), "exit_reason": "STOP_LOSS",
                    "days_held": days_held,
                })
                if cfg.compound:
                    dip_pool += pos["shares"] * stop  # return capital (reduced by loss)
            elif day_high >= target:
                # Target hit — sell at target
                pnl_pct = cfg.sell_target_pct
                pnl_dollars = pos["shares"] * entry * cfg.sell_target_pct / 100
                trades.append({
                    "ticker": tk, "entry_date": pos["entry_date"], "exit_date": d,
                    "entry_price": round(entry, 2), "exit_price": round(target, 2),
                    "shares": pos["shares"], "pnl_pct": round(pnl_pct, 2),
                    "pnl_dollars": round(pnl_dollars, 2), "exit_reason": "TARGET",
                    "days_held": days_held,
                })
                if cfg.compound:
                    dip_pool += pos["shares"] * target  # return capital + profit
            elif days_held >= cfg.max_hold_days:
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
                if cfg.compound:
                    dip_pool += pos["shares"] * day_close  # return at close price
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

                dipped = fh_move < -cfg.dip_threshold
                bouncing = sh_move > cfg.bounce_threshold
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

        if dipped_count >= total * cfg.breadth_ratio and bouncing_count >= total * cfg.bounce_ratio:
            signal = "CONFIRMED"
        elif dipped_count >= total * cfg.breadth_ratio and bouncing_count < total * 0.3:
            signal = "STAY_OUT"
        elif dipped_count < total * 0.3:
            signal = "NO_DIP"
        else:
            signal = "MIXED"

        # --- Execute entries on CONFIRMED or MIXED signal ---
        day_entries = 0
        day_capital_used = 0.0
        skip_reason = None

        # Regime gate
        if day_regime == "Risk-Off" and signal in ("CONFIRMED", "MIXED"):
            if cfg.risk_off_action == "skip":
                signal = "RISK_OFF_SKIP"
                skip_reason = "Risk-Off regime (VIX >= {:.0f})".format(cfg.vix_risk_off)

        # PDT gate
        if signal in ("CONFIRMED", "MIXED") and cfg.account_size < 25000:
            recent_day_trades = sum(1 for t in trades
                                   if t["entry_date"] == t["exit_date"]
                                   and (d - t["exit_date"]).days <= cfg.pdt_window)
            if recent_day_trades >= cfg.pdt_limit:
                pdt_log.append({"date": str(d), "trades_in_window": recent_day_trades,
                                "action": "SKIPPED — PDT limit reached"})
                signal = "PDT_BLOCKED"

        if signal in ("CONFIRMED", "MIXED"):
            buys = [t for t in ticker_stats if t["dipped"] and t["bouncing"] and t["below_open"]]
            # Don't buy if already holding this ticker
            held_tickers = {p["ticker"] for p in open_positions}
            buys = [b for b in buys if b["ticker"] not in held_tickers]
            # Ranking: by dip (default) or by recovery strength
            if cfg.rank_method == "recovery":
                buys.sort(key=lambda x: x["sh_move"], reverse=True)
            else:
                buys.sort(key=lambda x: x["dip_from_open"], reverse=True)
            buys = buys[:cfg.max_tickers_per_signal]

            # Per-trade budget: if compounding, derive from current pool size
            if cfg.compound:
                effective_budget = max(1, dip_pool / (cfg.max_tickers_per_signal * 2))
            else:
                effective_budget = cfg.budget
            if day_regime == "Risk-Off" and cfg.risk_off_action == "half":
                effective_budget = effective_budget / 2

            for b in buys:
                if day_capital_used + effective_budget > cfg.total_daily_cap:
                    break
                if cfg.compound and dip_pool < effective_budget:
                    break  # not enough in pool
                # Apply entry slippage (buy slightly higher)
                entry_price = b["current"] * (1 + cfg.entry_slippage_pct / 100)
                shares = max(1, int(effective_budget / entry_price))
                cost = shares * entry_price
                open_positions.append({
                    "ticker": b["ticker"],
                    "entry_date": d,
                    "entry_price": entry_price,
                    "shares": shares,
                })
                day_entries += 1
                day_capital_used += cost
                if cfg.compound:
                    dip_pool -= cost  # capital leaves the pool

        day_exits = sum(1 for t in trades if t["exit_date"] == d)
        day_pnl = sum(t["pnl_dollars"] for t in trades if t["exit_date"] == d)
        cumulative_pnl += day_pnl
        daily_log.append({
            "date": d, "signal": signal, "entries": day_entries, "exits": day_exits,
            "dipped": dipped_count, "bouncing": bouncing_count, "total": total,
            "open_positions": len(open_positions), "regime": day_regime,
        })
        equity_curve.append({
            "date": str(d), "cumulative_pnl": round(cumulative_pnl, 2),
            "day_pnl": round(day_pnl, 2), "positions": len(open_positions),
            "regime": day_regime,
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

    return trades, daily_log, equity_curve, pdt_log


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


def _run_workflow_mode(cfg):
    """Workflow mode: read sim-data.json, run simulation, write JSON outputs."""
    out_dir = Path(cfg.output_dir)
    sim_data_path = out_dir / "sim-data.json"

    if not sim_data_path.exists():
        print(f"*Error: {sim_data_path} not found — run data collector first*")
        sys.exit(1)

    with open(sim_data_path) as f:
        sim_data = json.load(f)

    # Override config from sim-data
    saved_cfg = sim_data.get("config", {})
    cfg = DipSimConfig.from_dict(saved_cfg)

    tickers = sim_data.get("tickers_eligible", [])
    if not tickers:
        print("*No eligible tickers in sim-data.json*")
        sys.exit(1)

    vix_history = sim_data.get("vix_history")

    print(f"Workflow mode: {len(tickers)} tickers, interval={cfg.interval}")
    hist = _fetch_intraday(tickers, cfg.start, cfg.end, cfg.interval)
    if hist is None:
        sys.exit(1)

    trades, daily_log, equity_curve, pdt_log = simulate(
        hist, tickers, config=cfg, vix_history=vix_history)

    # Serialize dates in trades/daily_log
    def _serialize(obj):
        if isinstance(obj, date):
            return str(obj)
        return obj

    trades_out = [{k: _serialize(v) for k, v in t.items()} for t in trades]
    log_out = [{k: _serialize(v) for k, v in d.items()} for d in daily_log]

    # Write outputs
    with open(out_dir / "trades-raw.json", "w") as f:
        json.dump(trades_out, f, indent=2)
    with open(out_dir / "daily-log.json", "w") as f:
        json.dump(log_out, f, indent=2)
    with open(out_dir / "equity-curve-raw.json", "w") as f:
        json.dump(equity_curve, f, indent=2)
    with open(out_dir / "pdt-log.json", "w") as f:
        json.dump(pdt_log, f, indent=2)

    print(f"Wrote {len(trades)} trades to {out_dir}/")
    print(f"Signals: {sum(1 for d in daily_log if d.get('signal') == 'CONFIRMED')} CONFIRMED, "
          f"{sum(1 for d in daily_log if d.get('signal') == 'MIXED')} MIXED")


def main():
    parser = build_dip_argparse()
    args = parser.parse_args()
    cfg = args_to_dip_config(args)

    # Workflow mode: read config from sim-data.json, write JSON outputs
    if cfg.workflow_mode:
        _run_workflow_mode(cfg)
        return

    tickers = cfg.tickers or _load_watchlist()
    if not tickers:
        print("*No tickers to simulate.*")
        return

    # Fetch VIX history for regime filtering
    vix_history = None
    if cfg.vix_risk_off < 9999:
        vix_history = _fetch_vix_history(cfg.start, cfg.end)

    print(f"## Dip Strategy Simulation")
    print(f"*Budget: ${cfg.budget}/ticker | Target: +{cfg.sell_target_pct}% | "
          f"Stop: {cfg.stop_loss_pct}% | Max hold: {cfg.max_hold_days}d*")
    non_defaults = []
    if cfg.dip_threshold != 1.0:
        non_defaults.append(f"dip>{cfg.dip_threshold}%")
    if cfg.breadth_ratio != 0.5:
        non_defaults.append(f"breadth={cfg.breadth_ratio:.0%}")
    if cfg.vix_risk_off < 9999:
        non_defaults.append(f"VIX>{cfg.vix_risk_off}={cfg.risk_off_action}")
    if cfg.entry_slippage_pct > 0:
        non_defaults.append(f"slippage={cfg.entry_slippage_pct}%")
    nd_str = f" | Overrides: {', '.join(non_defaults)}" if non_defaults else ""
    print(f"*Tickers: {len(tickers)} | Interval: {cfg.interval}{nd_str}*\n")

    hist = _fetch_intraday(tickers, cfg.start, cfg.end, cfg.interval)
    if hist is None:
        return

    # Sweep mode
    if cfg.sweep and cfg.sweep_params:
        combos = parse_sweep_spec(cfg.sweep_params)
        print(f"## Parameter Sweep: {len(combos)} combinations\n")
        sweep_results = []
        for i, overrides in enumerate(combos, 1):
            variant = apply_sweep_overrides(cfg, overrides)
            t, dl, ec, pl = simulate(hist, tickers, config=variant, vix_history=vix_history)
            if t:
                import numpy as np
                wins = sum(1 for x in t if x["pnl_pct"] > 0)
                total_pnl = sum(x["pnl_dollars"] for x in t)
                win_rate = wins / len(t) * 100
                avg_pnl = np.mean([x["pnl_pct"] for x in t])
                win_sum = sum(x["pnl_dollars"] for x in t if x["pnl_dollars"] > 0)
                loss_sum = abs(sum(x["pnl_dollars"] for x in t if x["pnl_dollars"] < 0))
                pf = win_sum / loss_sum if loss_sum > 0 else float("inf")
                sweep_results.append({
                    "overrides": overrides, "trades": len(t), "wins": wins,
                    "win_rate": round(win_rate, 1), "total_pnl": round(total_pnl, 2),
                    "avg_pnl": round(avg_pnl, 2), "profit_factor": round(pf, 2),
                })
            print(f"  [{i}/{len(combos)}] {overrides} → {len(t)} trades, ${sum(x['pnl_dollars'] for x in t):.2f}")

        # Print sweep summary
        sweep_results.sort(key=lambda x: x["total_pnl"], reverse=True)
        print(f"\n## Sweep Results (sorted by P/L)")
        print(f"| # | Overrides | Trades | Win% | P/L$ | PF |")
        print(f"| :--- | :--- | :--- | :--- | :--- | :--- |")
        for i, r in enumerate(sweep_results, 1):
            ov = ", ".join(f"{k}={v}" for k, v in r["overrides"].items())
            print(f"| {i} | {ov} | {r['trades']} | {r['win_rate']}% | ${r['total_pnl']:.2f} | {r['profit_factor']} |")
        return

    # Single run
    trades, daily_log, equity_curve, pdt_log = simulate(
        hist, tickers, config=cfg, vix_history=vix_history)
    print_results(trades, daily_log, cfg.budget)

    # Equity curve summary
    if equity_curve:
        max_dd = min((e["cumulative_pnl"] for e in equity_curve), default=0)
        peak = max((e["cumulative_pnl"] for e in equity_curve), default=0)
        print(f"\n## Equity Curve")
        print(f"| Metric | Value |")
        print(f"| :--- | :--- |")
        print(f"| Final P/L | ${equity_curve[-1]['cumulative_pnl']:.2f} |")
        print(f"| Peak P/L | ${peak:.2f} |")
        print(f"| Max Drawdown | ${max_dd:.2f} |")
        riskoff_days = sum(1 for e in equity_curve if e["regime"] == "Risk-Off")
        print(f"| Risk-Off days | {riskoff_days}/{len(equity_curve)} |")

    # PDT log
    if pdt_log:
        print(f"\n## PDT Violations")
        print(f"| Date | Trades in Window | Action |")
        print(f"| :--- | :--- | :--- |")
        for p in pdt_log:
            print(f"| {p['date']} | {p['trades_in_window']} | {p['action']} |")


if __name__ == "__main__":
    main()
