#!/usr/bin/env python3
"""
Fill Probability — Computes fill probability, distance dashboard, opportunity cost,
and stale order alerts for all unfilled pending BUY orders.

Gaps addressed: 5.5, 2.2, 2.5, 5.1, 5.6

CLI: python3 tools/fill_probability.py
"""

import json
import math
import re
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from technical_scanner import calc_atr

try:
    from market_context_pre_analyst import classify_regime
except ImportError as e:
    print(f"*Warning: classify_regime import failed ({e}), using Neutral regime*")
    def classify_regime(indices, vix):
        return {"regime": "Neutral", "indices_above": 0, "indices_total": 0,
                "vix_value": None, "reasoning": "Import fallback"}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO = PROJECT_ROOT / "portfolio.json"
TRADE_HISTORY = PROJECT_ROOT / "trade_history.json"


def load_json(path):
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def parse_bullet_label(note):
    """Parse bullet label from order note. Returns e.g. 'B1', 'R2', 'B2+3', 'B?'."""
    if not note:
        return "B?"
    # Take text before em dash
    prefix = note.split("\u2014")[0].split("—")[0].strip()
    # "Bullets N+M"
    m = re.match(r"Bullets?\s+(\d+\+\d+)", prefix, re.IGNORECASE)
    if m:
        return f"B{m.group(1)}"
    # "BN reserve" → RN
    m = re.match(r"B(\d+)\s+reserve", prefix, re.IGNORECASE)
    if m:
        return f"R{m.group(1)}"
    # "Reserve N"
    m = re.match(r"Reserve\s+(\d+)", prefix, re.IGNORECASE)
    if m:
        return f"R{m.group(1)}"
    # "Bullet N"
    m = re.match(r"Bullet\s+(\d+)", prefix, re.IGNORECASE)
    if m:
        return f"B{m.group(1)}"
    return "B?"


def fetch_regime():
    """Fetch market regime using classify_regime. Returns regime string."""
    try:
        indices = []
        for sym in ["SPY", "QQQ", "IWM"]:
            try:
                df = yf.download(sym, period="6mo", auto_adjust=True, progress=False)
                close = df["Close"]
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                sma50 = close.rolling(50).mean().iloc[-1]
                current = close.iloc[-1]
                vs_50sma = "Above 50-SMA" if current >= sma50 else "Below 50-SMA"
                indices.append({"vs_50sma": vs_50sma})
            except Exception:
                print(f"*Warning: Failed to fetch {sym} for regime, skipping*")
        vix_df = yf.download("^VIX", period="5d", auto_adjust=True, progress=False)
        vix_close = vix_df["Close"]
        if isinstance(vix_close, pd.DataFrame):
            vix_close = vix_close.iloc[:, 0]
        vix_val = float(vix_close.iloc[-1])
        result = classify_regime(indices, {"value": vix_val})
        return result["regime"]
    except Exception as e:
        print(f"*Warning: Regime fetch failed ({e}), using Neutral*")
        return "Neutral"


def get_unfilled_buys(portfolio):
    """Get all unfilled BUY orders from portfolio.json."""
    orders = []
    pending = portfolio.get("pending_orders", {})
    for ticker, ticker_orders in pending.items():
        for o in ticker_orders:
            if o.get("type", "").upper() != "BUY":
                continue
            if o.get("filled"):
                continue
            orders.append({
                "ticker": ticker,
                "price": o.get("price", 0),
                "shares": o.get("shares", 0),
                "note": o.get("note", ""),
                "placed": o.get("placed", False),
                "label": parse_bullet_label(o.get("note", "")),
            })
    return orders


def compute_fill_probability(order_price, current_price, df, atr, regime):
    """Compute fill probability for horizons [5, 10, 30].
    Returns dict of {5: prob, 10: prob, 30: prob}.
    """
    dist_pct = (order_price - current_price) / current_price
    # Already fillable
    if dist_pct >= 0:
        return {5: 0.99, 10: 0.99, 30: 0.99}

    abs_dist = abs(dist_pct)

    # Historical frequency — 30-day base rate from recent 30 trading days
    recent = df.tail(30)
    if len(recent) == 0:
        return {5: 0.01, 10: 0.01, 30: 0.01}

    threshold = order_price * 1.005
    total_weight = 0.0
    weighted_hits = 0.0
    lows = recent["Low"]
    if isinstance(lows, pd.DataFrame):
        lows = lows.iloc[:, 0]
    for i, (idx, low_val) in enumerate(lows.items()):
        days_ago = len(recent) - 1 - i
        weight = math.exp(-days_ago * math.log(2) / 30)
        total_weight += weight
        if low_val <= threshold:
            weighted_hits += weight

    base_rate_30d = weighted_hits / total_weight if total_weight > 0 else 0.0

    # Approach velocity (3-day ROC)
    close = df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    if len(close) >= 4:
        roc = (float(close.iloc[-1]) - float(close.iloc[-4])) / float(close.iloc[-4])
    else:
        roc = 0.0
    if roc < -0.005:
        velocity_adj = 1.15
    elif roc > 0.005:
        velocity_adj = 0.90
    else:
        velocity_adj = 1.0

    # ATR ratio modifier
    if pd.isna(atr) or atr <= 0:
        atr_mod = 1.0
        atr_ratio = 1.5
    else:
        atr_ratio = abs(current_price - order_price) / atr
        if atr_ratio < 1.0:
            atr_mod = 1.2
        elif atr_ratio > 3.0:
            atr_mod = 0.7
        else:
            atr_mod = 1.0

    # Regime modifier
    if pd.isna(atr) or atr <= 0:
        regime_mod = 1.0
    elif regime == "Risk-Off" and atr_ratio > 2:
        regime_mod = 1.3
    elif regime == "Risk-On" and atr_ratio > 2:
        regime_mod = 0.8
    else:
        regime_mod = 1.0

    probs = {}
    for h in [5, 10, 30]:
        hist_prob = min(1.0, 1 - (1 - base_rate_30d) ** (h / 30))
        prob = hist_prob * velocity_adj * atr_mod * regime_mod
        probs[h] = max(0.01, min(0.99, prob))

    return probs


def parse_placed_date(note):
    """Extract placed date from note field. Returns date or None."""
    m = re.search(r'\(?\s*placed\s+(\d{4}-\d{2}-\d{2})', note, re.IGNORECASE)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").date()
        except ValueError:
            pass
    return None


def main():
    portfolio = load_json(PORTFOLIO)
    trade_hist = load_json(TRADE_HISTORY)

    orders = get_unfilled_buys(portfolio)
    today = date.today()

    # Get expected profit pct from trade history
    sell_records = [t for t in trade_hist.get("trades", []) if t.get("side") == "SELL" and t.get("pnl_pct")]
    # Per-ticker sell pnl
    ticker_pnls = {}
    for t in sell_records:
        ticker_pnls.setdefault(t["ticker"], []).append(t["pnl_pct"])
    all_pnls = [t["pnl_pct"] for t in sell_records]
    if all_pnls:
        portfolio_median_pnl = sorted(all_pnls)[len(all_pnls) // 2]
    else:
        portfolio_median_pnl = 6.0

    if not orders:
        # Empty output with headers
        print("### Fill Probability")
        print("| Ticker | Order | Price | Distance | Fill Prob (5d) | Fill Prob (10d) | Fill Prob (30d) |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        print("| — | — | — | No pending orders | — | — | — |")
        print("")
        print("### Nearest Fills")
        print("| Ticker | Order | Price | Current | Distance | Fill Prob (5d) | Status |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        print("| — | — | — | — | No pending orders | — | — |")
        print("")
        print("### Opportunity Cost Analysis")
        print("| Ticker | Order | Capital | Fill Prob (30d) | EV (30d) | Best Alt EV | Delta | Verdict |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        print("| — | — | — | — | No pending orders | — | — | — |")
        return

    # Fetch regime once
    regime = fetch_regime()

    # Group orders by ticker
    tickers = sorted(set(o["ticker"] for o in orders))

    # Fetch data per ticker
    ticker_data = {}
    for ticker in tickers:
        try:
            df = yf.download(ticker, period="6mo", auto_adjust=True, progress=False)
            if df.empty:
                print(f"*Error fetching {ticker}: empty data*")
                continue
            close = df["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            current = float(close.iloc[-1])
            atr_series = calc_atr(df["High"], df["Low"], df["Close"])
            if isinstance(atr_series, pd.DataFrame):
                atr_series = atr_series.iloc[:, 0]
            atr_val = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else None
            ticker_data[ticker] = {
                "df": df,
                "current": current,
                "atr": atr_val,
            }
        except Exception as e:
            print(f"*Error fetching {ticker}: {e}*")

    # Compute probabilities for all orders
    results = []
    for o in orders:
        ticker = o["ticker"]
        if ticker not in ticker_data:
            continue
        td = ticker_data[ticker]
        current = td["current"]
        atr = td["atr"] if td["atr"] is not None else float("nan")
        probs = compute_fill_probability(o["price"], current, td["df"], atr, regime)
        dist_pct = (o["price"] - current) / current * 100
        capital = o["shares"] * o["price"]

        # Expected profit
        tpnls = ticker_pnls.get(ticker, [])
        if len(tpnls) >= 3:
            exp_profit_pct = sorted(tpnls)[len(tpnls) // 2]
        else:
            exp_profit_pct = portfolio_median_pnl

        ev_30d = probs[30] * capital * exp_profit_pct / 100

        # Stale detection
        stale = False
        placed_date = parse_placed_date(o["note"])
        if placed_date and (today - placed_date).days >= 14 and td["atr"] is not None:
            # Check if any day low within 2*ATR during order's lifetime
            df = td["df"]
            try:
                post_place = df[df.index >= pd.Timestamp(placed_date)]
                lows = post_place["Low"]
                if isinstance(lows, pd.DataFrame):
                    lows = lows.iloc[:, 0]
                approached = any(abs(low - o["price"]) <= 2 * td["atr"] for low in lows)
                if not approached:
                    stale = True
            except Exception:
                pass

        results.append({
            **o,
            "current": current,
            "dist_pct": dist_pct,
            "probs": probs,
            "capital": capital,
            "ev_30d": ev_30d,
            "exp_profit_pct": exp_profit_pct,
            "stale": stale,
        })

    # --- Block 1: Fill Probability Table ---
    print("### Fill Probability")
    print("| Ticker | Order | Price | Distance | Fill Prob (5d) | Fill Prob (10d) | Fill Prob (30d) |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    # Sort: ticker alpha, then price descending
    sorted_results = sorted(results, key=lambda r: (r["ticker"], -r["price"]))
    for r in sorted_results:
        print(f"| {r['ticker']} | {r['label']} | ${r['price']:.2f} | {r['dist_pct']:+.1f}% | {r['probs'][5]:.0%} | {r['probs'][10]:.0%} | {r['probs'][30]:.0%} |")

    # --- Block 2: Nearest Fills Dashboard ---
    print("")
    print("### Nearest Fills")
    print("| Ticker | Order | Price | Current | Distance | Fill Prob (5d) | Status |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    # One row per ticker: nearest unfilled BUY (highest price = closest to current)
    nearest = {}
    for r in results:
        t = r["ticker"]
        if t not in nearest or r["price"] > nearest[t]["price"]:
            nearest[t] = r
    nearest_sorted = sorted(nearest.values(), key=lambda r: abs(r["dist_pct"]))
    for r in nearest_sorted:
        abs_dist = abs(r["dist_pct"])
        if abs_dist < 0.5:
            status = "At level"
        elif abs_dist < 1.5:
            status = "Imminent"
        elif abs_dist < 5:
            status = "Approaching"
        elif abs_dist < 10:
            status = "Near"
        else:
            status = "Distant"
        print(f"| {r['ticker']} | {r['label']} | ${r['price']:.2f} | ${r['current']:.2f} | {r['dist_pct']:+.1f}% | {r['probs'][5]:.0%} | {status} |")

    # --- Block 3: Opportunity Cost + Stale Alerts ---
    print("")
    print("### Opportunity Cost Analysis")
    print("| Ticker | Order | Capital | Fill Prob (30d) | EV (30d) | Best Alt EV | Delta | Verdict |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    # Compute best alternative EV per ticker (best B1-equivalent EV from OTHER tickers)
    # Use nearest (highest-priced unfilled) per ticker as the "B1 equivalent"
    ticker_best_ev = {}
    for t, r in nearest.items():
        ticker_best_ev[t] = r["ev_30d"]

    only_one_ticker = len(ticker_best_ev) <= 1

    for r in sorted_results:
        label = r["label"]
        is_b1_b2 = label in ("B1", "B2")

        if only_one_ticker:
            best_alt_ev = 0.0
        else:
            best_alt_ev = max(ev for t, ev in ticker_best_ev.items() if t != r["ticker"]) if len(ticker_best_ev) > 1 else 0.0

        # Verdict precedence
        if is_b1_b2:
            verdict = "KEEP"
        elif only_one_ticker:
            verdict = "KEEP"
        elif r["ev_30d"] == 0 and best_alt_ev > 0:
            verdict = "REDEPLOY"
        elif r["ev_30d"] > 0:
            ratio = best_alt_ev / r["ev_30d"]
            if ratio >= 3.0:
                verdict = "REDEPLOY"
            elif ratio >= 1.5:
                verdict = "REVIEW"
            else:
                verdict = "KEEP"
        else:
            verdict = "KEEP"

        # Stale detection append
        if r["stale"]:
            verdict += " [STALE]"

        delta = best_alt_ev - r["ev_30d"]
        print(f"| {r['ticker']} | {label} | ${r['capital']:.0f} | {r['probs'][30]:.0%} | ${r['ev_30d']:.2f} | ${best_alt_ev:.2f} | ${delta:+.2f} | {verdict} |")


if __name__ == "__main__":
    main()
