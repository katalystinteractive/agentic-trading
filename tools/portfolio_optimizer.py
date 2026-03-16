#!/usr/bin/env python3
"""
Portfolio Optimizer — Cross-portfolio EV/day ranking + capital reallocation.

Gaps addressed: 5.2 (cross-portfolio optimization), 2.5 (enhanced distance-to-fill)

CLI: python3 tools/portfolio_optimizer.py
"""

import statistics
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared_utils import load_json, parse_bullet_label, get_portfolio_median_pnl
from fill_probability import compute_fill_probability
from technical_scanner import calc_atr
from shared_regime import fetch_regime_detail
from market_context_gatherer import SECTOR_MAP

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO = PROJECT_ROOT / "portfolio.json"
TRADE_HISTORY = PROJECT_ROOT / "trade_history.json"

# Constants
MAX_PER_TICKER = 600
MIN_ACTIVE_BULLETS = 2
MAX_SECTOR_PCT = 0.40
DEFAULT_CYCLE_DAYS = 15
EV_RATIO_THRESHOLD = 2.0


def is_never_redeploy(label):
    """B1 and B2 orders (including compounds like B1+2) are never redeployed."""
    return label.startswith(("B1", "B2"))


def get_cycle_days_estimate(ticker):
    """Read cycle_timing.json, return median_deep + 3 or DEFAULT_CYCLE_DAYS."""
    ct_path = PROJECT_ROOT / "tickers" / ticker / "cycle_timing.json"
    ct = load_json(ct_path)
    if not ct:
        return DEFAULT_CYCLE_DAYS
    median_deep = ct.get("statistics", {}).get("median_deep")
    if median_deep is None:
        return DEFAULT_CYCLE_DAYS
    return median_deep + 3


def compute_ev_per_dollar_per_day(fill_prob_30d, exp_profit_pct, cycle_days_est):
    """Pure arithmetic EV formula."""
    return (fill_prob_30d * exp_profit_pct / 100) / max(cycle_days_est, 1)


def get_current_phase(ticker):
    """Read pullback_profile.json for current_phase."""
    pp_path = PROJECT_ROOT / "tickers" / ticker / "pullback_profile.json"
    pp = load_json(pp_path)
    if not pp:
        return "Unknown"
    return pp.get("current_phase", "Unknown") or "Unknown"


def get_ticker_exp_profit(ticker, trade_hist, portfolio_median):
    """Per-ticker median PnL if 3+ sells, else portfolio median."""
    sells = [t for t in trade_hist.get("trades", [])
             if t.get("side") == "SELL" and t.get("ticker") == ticker
             and t.get("pnl_pct") is not None]
    if len(sells) >= 3:
        return statistics.median([t["pnl_pct"] for t in sells])
    return portfolio_median


def rank_orders(orders_with_ev):
    """Sort by ev_per_dollar_per_day descending, assign priority."""
    orders_with_ev.sort(key=lambda o: o["ev_per_day"], reverse=True)
    for i, o in enumerate(orders_with_ev, 1):
        o["priority"] = i
    return orders_with_ev


def check_reallocation_constraints(from_order, to_order, portfolio):
    """Validates reallocation: never-redeploy, min bullets, max per-ticker, sector cap."""
    if is_never_redeploy(from_order["label"]):
        return False

    pending = portfolio.get("pending_orders", {})

    # Source ticker must keep MIN_ACTIVE_BULLETS unfilled BUY orders
    source_buys = [o for o in pending.get(from_order["ticker"], [])
                   if o.get("type", "").upper() == "BUY" and not o.get("filled")]
    if len(source_buys) <= MIN_ACTIVE_BULLETS:
        return False

    # Target ticker must not exceed MAX_PER_TICKER after absorbing from_order's capital
    positions = portfolio.get("positions", {})
    target_pos = positions.get(to_order["ticker"], {})
    target_deployed = target_pos.get("shares", 0) * target_pos.get("avg_cost", 0)
    target_pending = sum(o.get("shares", 0) * o.get("price", 0)
                         for o in pending.get(to_order["ticker"], [])
                         if o.get("type", "").upper() == "BUY" and not o.get("filled"))
    if target_deployed + target_pending + from_order["capital"] > MAX_PER_TICKER:
        return False

    # Sector cap check
    target_sector = SECTOR_MAP.get(to_order["ticker"], "Unknown")
    if target_sector != "Unknown":
        sector_deployed = 0
        total_deployed = 0
        for t, pos in positions.items():
            if pos.get("shares", 0) > 0:
                amt = pos["shares"] * pos.get("avg_cost", 0)
                total_deployed += amt
                if SECTOR_MAP.get(t, "Unknown") == target_sector:
                    sector_deployed += amt
        if total_deployed > 0 and (sector_deployed + from_order["capital"]) / total_deployed > MAX_SECTOR_PCT:
            return False

    return True


def find_reallocation_opportunities(ranked, portfolio):
    """Compare bottom-quartile vs top-quartile. Return recommendations."""
    if len(ranked) < 4:
        return []

    q_size = max(1, len(ranked) // 4)
    top_q = ranked[:q_size]
    bottom_q = ranked[-q_size:]

    opportunities = []
    for bottom in bottom_q:
        for top in top_q:
            if bottom["ticker"] == top["ticker"]:
                continue
            if top["ev_per_day"] == 0:
                continue
            if bottom["ev_per_day"] == 0:
                ev_ratio = float("inf")
            else:
                ev_ratio = top["ev_per_day"] / bottom["ev_per_day"]
            if ev_ratio >= EV_RATIO_THRESHOLD:
                if check_reallocation_constraints(bottom, top, portfolio):
                    ev_gain_month = (top["ev_per_day"] - bottom["ev_per_day"]) * bottom["capital"] * 30
                    opportunities.append({
                        "from_ticker": bottom["ticker"],
                        "from_label": bottom["label"],
                        "from_ev": bottom["ev_per_day"],
                        "to_ticker": top["ticker"],
                        "to_label": top["label"],
                        "to_ev": top["ev_per_day"],
                        "amount": bottom["capital"],
                        "ev_gain_month": ev_gain_month,
                        "ev_ratio": ev_ratio,
                    })

    # Sort by EV gain descending, deduplicate from-orders
    opportunities.sort(key=lambda o: o["ev_gain_month"], reverse=True)
    seen_from = set()
    deduped = []
    for opp in opportunities:
        key = (opp["from_ticker"], opp["from_label"])
        if key not in seen_from:
            seen_from.add(key)
            deduped.append(opp)
    return deduped


def get_action_label(prob_5d, ev_per_day, ranked):
    """Determine action label for an order."""
    if prob_5d > 0.80:
        return "Ready to fill"
    if prob_5d > 0.50:
        return "Monitor closely"
    # Bottom quartile check
    if ranked:
        q_size = max(1, len(ranked) // 4)
        bottom_evs = [r["ev_per_day"] for r in ranked[-q_size:]]
        if bottom_evs and ev_per_day <= max(bottom_evs):
            return "Low EV — review"
    return "—"


def main():
    portfolio = load_json(PORTFOLIO)
    if not portfolio:
        print("*Error: portfolio.json not found*")
        sys.exit(1)

    trade_hist = load_json(TRADE_HISTORY)
    portfolio_median_pnl = get_portfolio_median_pnl(trade_hist)

    regime_detail = fetch_regime_detail()
    regime = regime_detail["regime"]

    pending = portfolio.get("pending_orders", {})

    # Collect all unfilled BUY orders
    all_orders = []
    for ticker, orders in pending.items():
        for o in orders:
            if o.get("type", "").upper() != "BUY" or o.get("filled"):
                continue
            label = parse_bullet_label(o.get("note", ""))
            all_orders.append({
                "ticker": ticker,
                "price": o["price"],
                "shares": o.get("shares", 0),
                "label": label,
                "note": o.get("note", ""),
                "capital": o.get("shares", 0) * o["price"],
            })

    if not all_orders:
        print("### Portfolio Fill Priority")
        print("*No unfilled BUY orders.*")
        return

    # Fetch market data per unique ticker
    tickers = sorted(set(o["ticker"] for o in all_orders))
    ticker_data = {}  # {ticker: {"df": df, "current": float, "atr": float}}

    for ticker in tickers:
        try:
            df = yf.download(ticker, period="6mo", auto_adjust=True, progress=False)
            if df.empty:
                continue
            close = df["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            current = float(close.iloc[-1])
            atr_series = calc_atr(df["High"], df["Low"], df["Close"])
            if isinstance(atr_series, pd.DataFrame):
                atr_series = atr_series.iloc[:, 0]
            atr_val = float(atr_series.iloc[-1])
            if pd.isna(atr_val) or atr_val <= 0:
                atr_val = current * 0.03  # fallback 3%
            ticker_data[ticker] = {"df": df, "current": current, "atr": atr_val}
        except Exception as e:
            print(f"*Warning: Failed to fetch {ticker}: {e}*", file=sys.stderr)

    # Pre-compute per-ticker data (avoid re-reading JSON / re-filtering per order)
    ticker_cycle_days = {t: get_cycle_days_estimate(t) for t in tickers}
    ticker_phase = {t: get_current_phase(t) for t in tickers}
    ticker_exp_profit = {t: get_ticker_exp_profit(t, trade_hist, portfolio_median_pnl) for t in tickers}

    # Compute EV per order
    orders_with_ev = []
    for o in all_orders:
        td = ticker_data.get(o["ticker"])
        if not td:
            continue

        probs = compute_fill_probability(o["price"], td["current"], td["df"], td["atr"], regime)
        prob_30 = probs[30]
        prob_5 = probs[5]

        exp_profit = ticker_exp_profit.get(o["ticker"], portfolio_median_pnl)
        cycle_days = ticker_cycle_days.get(o["ticker"], DEFAULT_CYCLE_DAYS)
        ev_per_day = compute_ev_per_dollar_per_day(prob_30, exp_profit, cycle_days)
        phase = ticker_phase.get(o["ticker"], "Unknown")

        orders_with_ev.append({
            **o,
            "current": td["current"],
            "prob_5d": prob_5,
            "prob_30d": prob_30,
            "exp_profit": exp_profit,
            "cycle_days": cycle_days,
            "ev_per_day": ev_per_day,
            "phase": phase,
        })

    # Rank
    ranked = rank_orders(orders_with_ev)

    # Find reallocation opportunities
    reallocations = find_reallocation_opportunities(ranked, portfolio)

    # Output Block 1: Portfolio Fill Priority
    print("### Portfolio Fill Priority")
    print("| Priority | Ticker | Order | Fill Prob (5d) | EV/Day | Capital | Phase | Action |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for o in ranked:
        action = get_action_label(o["prob_5d"], o["ev_per_day"], ranked)
        print(f"| {o['priority']} | {o['ticker']} | {o['label']} ${o['price']:.2f} "
              f"| {o['prob_5d']:.0%} | {o['ev_per_day']:.4f} | ${o['capital']:.0f} "
              f"| {o['phase']} | {action} |")

    # Output Block 2: Capital Optimization
    print("")
    print("### Portfolio Capital Optimization")
    if reallocations:
        print("| Action | From | To | Amount | EV Gain/Month |")
        print("| :--- | :--- | :--- | :--- | :--- |")
        for r in reallocations:
            print(f"| Redeploy | {r['from_ticker']} {r['from_label']} (EV {r['from_ev']:.4f}) "
                  f"| {r['to_ticker']} {r['to_label']} (EV {r['to_ev']:.4f}) "
                  f"| ${r['amount']:.0f} | ${r['ev_gain_month']:.2f} |")
    else:
        print("*No reallocation opportunities exceed threshold.*")


if __name__ == "__main__":
    main()
