"""Surgical Mean-Reversion Backtest Engine — Phase 2 of backtest-surgical-workflow.

Replays each trading day sequentially, maintaining simulated portfolio state.
Uses ONLY past data for level discovery (no look-ahead bias).

Core loop for each day:
1. Classify regime (from precomputed VIX + index data)
2. Check exits (profit target, time stop, catastrophic stop)
3. Check fills (limit order vs day's low)
4. Recompute levels (weekly/monthly — wick analysis with time-sliced data)
5. Record equity snapshot

Usage:
    python3 tools/backtest_engine.py --data-dir data/backtest/latest
    python3 tools/backtest_engine.py --data-dir data/backtest/latest --sell-default 8 --time-stop-days 45
"""
import sys
import json
import pickle
import math
from datetime import datetime, timedelta, date
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_config import SurgicalSimConfig

_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Position:
    ticker: str
    shares: int
    avg_cost: float
    entry_date: str
    fills: list = field(default_factory=list)     # [{date, price, shares, zone}]
    bullets_used: int = 0
    sell_target_pct: float = 6.0
    zones_used: list = field(default_factory=list)


@dataclass
class PendingOrder:
    ticker: str
    price: float
    shares: int
    zone: str
    tier: str
    placed_date: str


@dataclass
class StockCapital:
    active_remaining: float
    reserve_remaining: float
    active_bullets: int = 0
    reserve_bullets: int = 0


def load_collected_data(data_dir):
    """Load Phase 1 output."""
    p = Path(data_dir)

    with open(p / "price_data.pkl", "rb") as f:
        price_data = pickle.load(f)

    with open(p / "regime_data.json") as f:
        regime_data = json.load(f)

    with open(p / "config.json") as f:
        config_meta = json.load(f)

    return price_data, regime_data, config_meta


def _build_hist_dataframe(tk_data):
    """Convert dict of Series to DataFrame for wick analyzer."""
    df = pd.DataFrame({
        "Open": tk_data["Open"],
        "High": tk_data["High"],
        "Low": tk_data["Low"],
        "Close": tk_data["Close"],
        "Volume": tk_data["Volume"],
    })
    return df


def _compute_sell_target(cfg, completed_cycles_for_ticker):
    """Determine sell target % based on cycle history within the simulation."""
    cycles = completed_cycles_for_ticker
    if not cycles:
        return cfg.sell_default

    n = len(cycles)
    durations = [c["duration_days"] for c in cycles]
    median_dur = float(np.median(durations))

    # Exceptional check first
    if (n >= cfg.exceptional_min_cycles and
            median_dur <= cfg.exceptional_max_median_days):
        return cfg.sell_exceptional

    # Fast cycler check
    if (n >= cfg.fast_cycler_min_cycles and
            median_dur <= cfg.fast_cycler_max_median_days):
        return cfg.sell_fast_cycler

    return cfg.sell_default


def run_simulation(price_data, regime_data, cfg):
    """Execute the surgical mean-reversion backtest.

    Returns: (trades, cycles, equity_curve)
    """
    from wick_offset_analyzer import analyze_stock_data, WickConfig, ACTIVE_RADIUS_CAP, POOL_MAX_FRACTION
    import wick_offset_analyzer as woa

    # Patch module constants from config
    woa.ACTIVE_RADIUS_CAP = cfg.active_radius_cap
    woa.POOL_MAX_FRACTION = cfg.pool_max_fraction

    wick_config = cfg.to_wick_config()
    capital_config = cfg.to_capital_config()

    tickers = list(price_data.keys())

    # Parse date range
    # Find common trading days across all tickers
    all_dates = set()
    for tk in tickers:
        for dt in price_data[tk]["Close"].index:
            all_dates.add(dt.date() if hasattr(dt, "date") else dt)
    all_dates = sorted(all_dates)

    # Determine sim start (after warmup)
    if cfg.start:
        sim_start = datetime.strptime(cfg.start, "%Y-%m-%d").date()
    else:
        # Start after 13 months warmup
        warmup_idx = min(cfg.wick_lookback_months * 21, len(all_dates) - 1)
        sim_start = all_dates[warmup_idx]

    sim_end = datetime.strptime(cfg.end, "%Y-%m-%d").date() if cfg.end else all_dates[-1]
    sim_dates = [d for d in all_dates if sim_start <= d <= sim_end]

    print(f"Sim dates: {sim_dates[0]} to {sim_dates[-1]} ({len(sim_dates)} trading days)")
    print(f"Tickers: {len(tickers)}")

    # State
    positions = {}           # ticker -> Position
    pending_orders = {}      # ticker -> [PendingOrder]
    stock_capital = {}       # ticker -> StockCapital
    trades = []              # completed trades
    completed_cycles = defaultdict(list)  # ticker -> [cycle_dicts]
    equity_curve = []
    cached_levels = {}       # ticker -> {date, levels, bullet_plan}

    # Initialize capital pools
    for tk in tickers:
        stock_capital[tk] = StockCapital(
            active_remaining=cfg.active_pool,
            reserve_remaining=cfg.reserve_pool,
        )
        pending_orders[tk] = []

    # Determine recompute schedule
    recompute_interval = {"daily": 1, "weekly": 5, "monthly": 21}.get(cfg.recompute_levels, 5)
    days_since_recompute = {tk: recompute_interval for tk in tickers}  # force initial compute

    # --- DAILY REPLAY ---
    for day_idx, d in enumerate(sim_dates):
        d_str = str(d)

        # 1. REGIME
        regime_info = regime_data.get(d_str, {"regime": "Neutral", "vix": None})
        regime = regime_info["regime"]

        # 2. CHECK EXITS
        for tk in list(positions.keys()):
            pos = positions[tk]
            tk_data = price_data.get(tk)
            if tk_data is None:
                continue

            # Get today's OHLC
            try:
                if d in tk_data["High"].index:
                    day_high = float(tk_data["High"].loc[d])
                    day_low = float(tk_data["Low"].loc[d])
                    day_close = float(tk_data["Close"].loc[d])
                elif hasattr(tk_data["High"].index[0], "date"):
                    mask = tk_data["High"].index.date == d
                    if not mask.any():
                        continue
                    day_high = float(tk_data["High"][mask].iloc[0])
                    day_low = float(tk_data["Low"][mask].iloc[0])
                    day_close = float(tk_data["Close"][mask].iloc[0])
                else:
                    continue
            except (KeyError, IndexError):
                continue

            entry_date = datetime.strptime(pos.entry_date, "%Y-%m-%d").date()
            days_held = (d - entry_date).days
            drawdown_pct = (day_low - pos.avg_cost) / pos.avg_cost * 100

            # a. Catastrophic stop
            if drawdown_pct <= -cfg.cat_exit:
                pnl_pct = (day_close - pos.avg_cost) / pos.avg_cost * 100
                pnl_dollars = pos.shares * (day_close - pos.avg_cost)
                trades.append({
                    "ticker": tk, "side": "SELL", "date": d_str,
                    "price": round(day_close, 2), "shares": pos.shares,
                    "pnl_pct": round(pnl_pct, 2), "pnl_dollars": round(pnl_dollars, 2),
                    "exit_reason": "CATASTROPHIC_EXIT", "days_held": days_held,
                    "avg_cost": round(pos.avg_cost, 2), "regime": regime,
                })
                # Return capital
                stock_capital[tk].active_remaining = cfg.active_pool
                stock_capital[tk].reserve_remaining = cfg.reserve_pool
                stock_capital[tk].active_bullets = 0
                stock_capital[tk].reserve_bullets = 0
                del positions[tk]
                pending_orders[tk] = []
                continue

            # b. Time stop
            time_limit = cfg.time_stop_days
            if regime == "Risk-Off":
                time_limit += cfg.time_stop_riskoff_ext
            if days_held > time_limit:
                pnl_pct = (day_close - pos.avg_cost) / pos.avg_cost * 100
                pnl_dollars = pos.shares * (day_close - pos.avg_cost)
                trades.append({
                    "ticker": tk, "side": "SELL", "date": d_str,
                    "price": round(day_close, 2), "shares": pos.shares,
                    "pnl_pct": round(pnl_pct, 2), "pnl_dollars": round(pnl_dollars, 2),
                    "exit_reason": "TIME_STOP", "days_held": days_held,
                    "avg_cost": round(pos.avg_cost, 2), "regime": regime,
                })
                completed_cycles[tk].append({
                    "entry_date": pos.entry_date, "exit_date": d_str,
                    "avg_cost": pos.avg_cost, "exit_price": day_close,
                    "pnl_pct": round(pnl_pct, 2), "duration_days": days_held,
                    "bullets_used": pos.bullets_used, "zones": pos.zones_used,
                })
                stock_capital[tk].active_remaining = cfg.active_pool
                stock_capital[tk].reserve_remaining = cfg.reserve_pool
                stock_capital[tk].active_bullets = 0
                stock_capital[tk].reserve_bullets = 0
                del positions[tk]
                pending_orders[tk] = []
                continue

            # c. Profit target (check stop first if conservative)
            sell_target = _compute_sell_target(cfg, completed_cycles.get(tk, []))
            if regime == "Risk-Off" and cfg.riskoff_suppress_upgrades:
                sell_target = cfg.sell_default
            target_price = pos.avg_cost * (1 + sell_target / 100)

            if cfg.conservative_exit_order and drawdown_pct <= -cfg.cat_warning:
                # Don't sell at target during significant drawdown
                pass
            elif day_high >= target_price:
                pnl_pct = sell_target
                pnl_dollars = pos.shares * pos.avg_cost * sell_target / 100
                trades.append({
                    "ticker": tk, "side": "SELL", "date": d_str,
                    "price": round(target_price, 2), "shares": pos.shares,
                    "pnl_pct": round(pnl_pct, 2), "pnl_dollars": round(pnl_dollars, 2),
                    "exit_reason": "PROFIT_TARGET", "days_held": days_held,
                    "avg_cost": round(pos.avg_cost, 2), "regime": regime,
                    "sell_tier": f"{sell_target}%",
                })
                completed_cycles[tk].append({
                    "entry_date": pos.entry_date, "exit_date": d_str,
                    "avg_cost": pos.avg_cost, "exit_price": target_price,
                    "pnl_pct": round(pnl_pct, 2), "duration_days": days_held,
                    "bullets_used": pos.bullets_used, "zones": pos.zones_used,
                })
                stock_capital[tk].active_remaining = cfg.active_pool
                stock_capital[tk].reserve_remaining = cfg.reserve_pool
                stock_capital[tk].active_bullets = 0
                stock_capital[tk].reserve_bullets = 0
                del positions[tk]
                pending_orders[tk] = []
                continue

        # 3. CHECK FILLS for pending limit buys
        for tk in tickers:
            if tk not in price_data:
                continue
            tk_data = price_data[tk]
            try:
                if d in tk_data["Low"].index:
                    day_low = float(tk_data["Low"].loc[d])
                    day_close = float(tk_data["Close"].loc[d])
                elif hasattr(tk_data["Low"].index[0], "date"):
                    mask = tk_data["Low"].index.date == d
                    if not mask.any():
                        continue
                    day_low = float(tk_data["Low"][mask].iloc[0])
                    day_close = float(tk_data["Close"][mask].iloc[0])
                else:
                    continue
            except (KeyError, IndexError):
                continue

            filled = []
            for i, order in enumerate(pending_orders.get(tk, [])):
                # Regime gate
                if regime == "Risk-Off":
                    current = day_close
                    pct_below = (current - order.price) / current * 100
                    if pct_below < 15:  # within 15% of current — pause
                        continue

                if day_low <= order.price:
                    filled.append(i)
                    fill_price = order.price

                    # Update position
                    if tk in positions:
                        pos = positions[tk]
                        total_cost = pos.shares * pos.avg_cost + order.shares * fill_price
                        pos.shares += order.shares
                        pos.avg_cost = total_cost / pos.shares
                        pos.fills.append({"date": d_str, "price": fill_price,
                                         "shares": order.shares, "zone": order.zone})
                        pos.bullets_used += 1
                        if order.zone not in pos.zones_used:
                            pos.zones_used.append(order.zone)
                    else:
                        positions[tk] = Position(
                            ticker=tk, shares=order.shares, avg_cost=fill_price,
                            entry_date=d_str,
                            fills=[{"date": d_str, "price": fill_price,
                                   "shares": order.shares, "zone": order.zone}],
                            bullets_used=1, zones_used=[order.zone],
                        )

                    # Deduct from pool
                    cap = stock_capital[tk]
                    cost = order.shares * fill_price
                    if order.zone in ("Active", "Buffer"):
                        cap.active_remaining -= cost
                        cap.active_bullets += 1
                    else:
                        cap.reserve_remaining -= cost
                        cap.reserve_bullets += 1

                    trades.append({
                        "ticker": tk, "side": "BUY", "date": d_str,
                        "price": round(fill_price, 2), "shares": order.shares,
                        "zone": order.zone, "tier": order.tier,
                        "avg_cost": round(positions[tk].avg_cost, 2),
                        "regime": regime,
                    })

                    # Same-day exit check
                    if cfg.same_day_exit and order.zone == "Active":
                        try:
                            if d in tk_data["High"].index:
                                dh = float(tk_data["High"].loc[d])
                            else:
                                mask = tk_data["High"].index.date == d
                                dh = float(tk_data["High"][mask].iloc[0]) if mask.any() else 0
                            sde_target = fill_price * (1 + cfg.same_day_exit_pct / 100)
                            if dh >= sde_target:
                                pos = positions[tk]
                                sde_pnl = cfg.same_day_exit_pct
                                sde_dollars = pos.shares * fill_price * sde_pnl / 100
                                trades.append({
                                    "ticker": tk, "side": "SELL", "date": d_str,
                                    "price": round(sde_target, 2), "shares": pos.shares,
                                    "pnl_pct": round(sde_pnl, 2),
                                    "pnl_dollars": round(sde_dollars, 2),
                                    "exit_reason": "SAME_DAY_EXIT",
                                    "days_held": 0, "avg_cost": round(pos.avg_cost, 2),
                                    "regime": regime,
                                })
                                completed_cycles[tk].append({
                                    "entry_date": d_str, "exit_date": d_str,
                                    "avg_cost": pos.avg_cost, "exit_price": sde_target,
                                    "pnl_pct": round(sde_pnl, 2), "duration_days": 0,
                                    "bullets_used": pos.bullets_used,
                                    "zones": pos.zones_used,
                                })
                                stock_capital[tk].active_remaining = cfg.active_pool
                                stock_capital[tk].reserve_remaining = cfg.reserve_pool
                                stock_capital[tk].active_bullets = 0
                                stock_capital[tk].reserve_bullets = 0
                                del positions[tk]
                                break
                        except Exception:
                            pass

            # Remove filled orders (reverse to preserve indices)
            for i in sorted(filled, reverse=True):
                pending_orders[tk].pop(i)

        # 4. RECOMPUTE LEVELS (if recompute day)
        for tk in tickers:
            days_since_recompute[tk] += 1
            if days_since_recompute[tk] < recompute_interval:
                continue
            days_since_recompute[tk] = 0

            tk_data = price_data.get(tk)
            if tk_data is None:
                continue

            # Slice hist to current date (NO LOOK-AHEAD)
            full_df = _build_hist_dataframe(tk_data)
            if hasattr(full_df.index[0], "date"):
                mask = full_df.index.date <= d
            else:
                mask = full_df.index <= pd.Timestamp(d)
            hist_slice = full_df[mask]

            if len(hist_slice) < 60:
                continue

            try:
                wick_result, err = analyze_stock_data(
                    tk, hist=hist_slice, config=wick_config,
                    capital_config=capital_config)
                if wick_result is None:
                    continue

                bp = wick_result.get("bullet_plan", {})
                active_bullets = bp.get("active", [])
                reserve_bullets = bp.get("reserve", [])

                cached_levels[tk] = {
                    "date": d_str,
                    "active": active_bullets,
                    "reserve": reserve_bullets,
                }

                # Place new pending orders for levels not already covered
                cap = stock_capital[tk]
                existing_prices = {round(o.price, 2) for o in pending_orders.get(tk, [])}

                for bullet in active_bullets:
                    buy_at = bullet.get("buy_at")
                    if buy_at is None or round(buy_at, 2) in existing_prices:
                        continue
                    tier = bullet.get("effective_tier", bullet.get("tier", "Skip"))
                    if tier == "Skip":
                        continue
                    hr = bullet.get("decayed_hold_rate", bullet.get("hold_rate", 0))
                    if hr < cfg.min_hold_rate:
                        continue
                    if cap.active_bullets >= cfg.active_bullets_max:
                        break
                    shares = bullet.get("shares", 1)
                    if tk not in positions:  # only place if no position or averaging down
                        pass  # place regardless
                    pending_orders.setdefault(tk, []).append(PendingOrder(
                        ticker=tk, price=buy_at, shares=shares,
                        zone="Active", tier=tier, placed_date=d_str,
                    ))

                for bullet in reserve_bullets:
                    buy_at = bullet.get("buy_at")
                    if buy_at is None or round(buy_at, 2) in existing_prices:
                        continue
                    tier = bullet.get("effective_tier", bullet.get("tier", "Skip"))
                    if tier == "Skip":
                        continue
                    if cap.reserve_bullets >= cfg.reserve_bullets_max:
                        break
                    shares = bullet.get("shares", 1)
                    pending_orders.setdefault(tk, []).append(PendingOrder(
                        ticker=tk, price=buy_at, shares=shares,
                        zone="Reserve", tier=tier, placed_date=d_str,
                    ))

            except Exception as e:
                if day_idx == 0:
                    print(f"  Wick analysis failed for {tk}: {e}")

        # 5. EQUITY SNAPSHOT
        portfolio_value = 0
        unrealized_pnl = 0
        for tk, pos in positions.items():
            try:
                tk_data = price_data[tk]
                if d in tk_data["Close"].index:
                    close = float(tk_data["Close"].loc[d])
                elif hasattr(tk_data["Close"].index[0], "date"):
                    mask = tk_data["Close"].index.date == d
                    close = float(tk_data["Close"][mask].iloc[0]) if mask.any() else pos.avg_cost
                else:
                    close = pos.avg_cost
                portfolio_value += pos.shares * close
                unrealized_pnl += pos.shares * (close - pos.avg_cost)
            except Exception:
                portfolio_value += pos.shares * pos.avg_cost

        realized_pnl = sum(t["pnl_dollars"] for t in trades
                          if t.get("side") == "SELL" and t.get("pnl_dollars"))

        equity_curve.append({
            "date": d_str,
            "realized_pnl": round(realized_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "total_pnl": round(realized_pnl + unrealized_pnl, 2),
            "positions": len(positions),
            "pending_orders": sum(len(v) for v in pending_orders.values()),
            "regime": regime,
        })

        # Progress
        if day_idx % 50 == 0 and day_idx > 0:
            print(f"  Day {day_idx}/{len(sim_dates)}: {len(positions)} positions, "
                  f"{len(trades)} trades, regime={regime}")

    # Force-close remaining positions at sim end
    last_date = sim_dates[-1]
    for tk in list(positions.keys()):
        pos = positions[tk]
        try:
            tk_data = price_data[tk]
            if last_date in tk_data["Close"].index:
                close = float(tk_data["Close"].loc[last_date])
            elif hasattr(tk_data["Close"].index[0], "date"):
                mask = tk_data["Close"].index.date == last_date
                close = float(tk_data["Close"][mask].iloc[0]) if mask.any() else pos.avg_cost
            else:
                close = pos.avg_cost
        except Exception:
            close = pos.avg_cost

        pnl_pct = (close - pos.avg_cost) / pos.avg_cost * 100
        pnl_dollars = pos.shares * (close - pos.avg_cost)
        entry_date = datetime.strptime(pos.entry_date, "%Y-%m-%d").date()
        days_held = (last_date - entry_date).days

        trades.append({
            "ticker": tk, "side": "SELL", "date": str(last_date),
            "price": round(close, 2), "shares": pos.shares,
            "pnl_pct": round(pnl_pct, 2), "pnl_dollars": round(pnl_dollars, 2),
            "exit_reason": "SIM_END", "days_held": days_held,
            "avg_cost": round(pos.avg_cost, 2), "regime": regime_data.get(str(last_date), {}).get("regime", "Neutral"),
        })

    # Flatten cycles
    all_cycles = []
    for tk, cycles in completed_cycles.items():
        for c in cycles:
            c["ticker"] = tk
            all_cycles.append(c)

    sell_trades = [t for t in trades if t.get("side") == "SELL"]
    buy_trades = [t for t in trades if t.get("side") == "BUY"]
    print(f"\nSimulation complete: {len(buy_trades)} buys, {len(sell_trades)} sells, "
          f"{len(all_cycles)} cycles")

    return trades, all_cycles, equity_curve


def save_results(trades, cycles, equity_curve, output_dir):
    """Save simulation results."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    with open(out / "trades.json", "w") as f:
        json.dump(trades, f, indent=2, default=str)

    with open(out / "cycles.json", "w") as f:
        json.dump(cycles, f, indent=2, default=str)

    with open(out / "equity_curve.json", "w") as f:
        json.dump(equity_curve, f, indent=2, default=str)

    print(f"Saved results to {out}/")


def main():
    import argparse
    p = argparse.ArgumentParser(description="Surgical Mean-Reversion Backtest Engine")
    p.add_argument("--data-dir", required=True, help="Phase 1 output directory")
    p.add_argument("--sell-default", type=float, default=6.0)
    p.add_argument("--sell-fast-cycler", type=float, default=8.0)
    p.add_argument("--sell-exceptional", type=float, default=10.0)
    p.add_argument("--time-stop-days", type=int, default=60)
    p.add_argument("--time-stop-riskoff-ext", type=int, default=14)
    p.add_argument("--cat-warning", type=float, default=15.0)
    p.add_argument("--cat-hard-stop", type=float, default=25.0)
    p.add_argument("--cat-exit", type=float, default=40.0)
    p.add_argument("--active-pool", type=float, default=300.0)
    p.add_argument("--reserve-pool", type=float, default=300.0)
    p.add_argument("--active-bullets-max", type=int, default=5)
    p.add_argument("--reserve-bullets-max", type=int, default=3)
    p.add_argument("--active-radius-cap", type=float, default=20.0)
    p.add_argument("--recompute-levels", default="weekly",
                   choices=["daily", "weekly", "monthly"])
    p.add_argument("--same-day-exit", action="store_true", default=True)
    p.add_argument("--same-day-exit-pct", type=float, default=3.0)
    p.add_argument("--min-hold-rate", type=int, default=15)
    p.add_argument("--start", type=str, default="")
    p.add_argument("--end", type=str, default="")
    args = p.parse_args()

    price_data, regime_data, config_meta = load_collected_data(args.data_dir)
    saved_cfg = config_meta.get("config", {})

    cfg = SurgicalSimConfig.from_dict(saved_cfg)
    # Override with CLI args
    for k, v in vars(args).items():
        if k == "data_dir":
            continue
        if hasattr(cfg, k):
            setattr(cfg, k, v)
    cfg.output_dir = args.data_dir

    trades, cycles, equity_curve = run_simulation(price_data, regime_data, cfg)
    save_results(trades, cycles, equity_curve, args.data_dir)


if __name__ == "__main__":
    main()
