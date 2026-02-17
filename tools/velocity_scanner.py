"""Velocity Signal Scanner — scores a single ticker for quick-strike entry."""

import json
import sys
from pathlib import Path

import yfinance as yf
import pandas as pd

from technical_scanner import calc_rsi, calc_macd, calc_bollinger, calc_stochastic, calc_atr

ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO = ROOT / "portfolio.json"


def score_velocity_signal(ticker_symbol):
    """Score a single ticker on the 100-point velocity scale.

    Returns a dict with all signal components, trade setup, and verdict.
    Returns None on data error.
    """
    try:
        df = yf.download(ticker_symbol, period="3mo", interval="1d", progress=False)
        if df.empty:
            return None
    except Exception:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    current_price = float(close.iloc[-1])

    # --- Indicators ---
    rsi_series = calc_rsi(close)
    rsi_val = float(rsi_series.iloc[-1])

    _, _, histogram = calc_macd(close)
    hist_val = float(histogram.iloc[-1])

    _, _, bb_lower = calc_bollinger(close)
    bb_lower_val = float(bb_lower.iloc[-1])

    stoch_k, _ = calc_stochastic(high, low, close)
    stoch_k_val = float(stoch_k.iloc[-1])

    atr_val = float(calc_atr(high, low, close).iloc[-1])
    atr_pct = (atr_val / current_price) * 100

    # Volume check
    avg_volume = float(df["Volume"].tail(20).mean())

    # --- Scoring ---
    total = 0
    components = []

    # RSI(14) Oversold: 30 pts if < 35
    rsi_pts = 30 if rsi_val < 35 else 0
    total += rsi_pts
    components.append({
        "name": "RSI(14)",
        "value": f"{rsi_val:.1f}",
        "threshold": "< 35",
        "points": rsi_pts,
        "max": 30,
    })

    # MACD Bullish Cross: 25 pts if histogram just turned positive (fresh cross)
    macd_pts = 0
    prev_hist = float(histogram.iloc[-2]) if len(histogram) >= 2 else 0
    if hist_val > 0 and prev_hist <= 0:
        macd_pts = 25
    total += macd_pts
    macd_label = f"Bullish Cross ({hist_val:+.3f})" if macd_pts > 0 else (
        f"Bullish ({hist_val:+.3f})" if hist_val > 0 else f"Bearish ({hist_val:+.3f})"
    )
    components.append({
        "name": "MACD Cross",
        "value": macd_label,
        "threshold": "Cross up",
        "points": macd_pts,
        "max": 25,
    })

    # Bollinger Lower Pierce: 25 pts if price <= lower band
    boll_pts = 25 if current_price <= bb_lower_val else 0
    total += boll_pts
    boll_label = "Below lower" if current_price <= bb_lower_val else "Inside bands"
    components.append({
        "name": "Bollinger",
        "value": boll_label,
        "threshold": "Touch/break",
        "points": boll_pts,
        "max": 25,
    })

    # Stochastic Oversold: 10 pts if %K < 20
    stoch_pts = 10 if stoch_k_val < 20 else 0
    total += stoch_pts
    components.append({
        "name": "Stochastic %K",
        "value": f"{stoch_k_val:.1f}",
        "threshold": "< 20",
        "points": stoch_pts,
        "max": 10,
    })

    # RSI 3-Day Trend: 10 pts if RSI rising for 3 consecutive days from oversold
    rsi_trend_pts = 0
    if len(rsi_series) >= 4:
        r = rsi_series.iloc[-4:]
        if float(r.iloc[0]) < 40 and float(r.iloc[1]) > float(r.iloc[0]) and float(r.iloc[2]) > float(r.iloc[1]) and float(r.iloc[3]) > float(r.iloc[2]):
            rsi_trend_pts = 10
    total += rsi_trend_pts
    trend_label = "Rising" if rsi_trend_pts > 0 else "Flat/Falling"
    components.append({
        "name": "RSI 3-Day Trend",
        "value": trend_label,
        "threshold": "3-day up",
        "points": rsi_trend_pts,
        "max": 10,
    })

    # --- Verdict ---
    # Overlap check done early so it can block the verdict
    portfolio = json.loads(PORTFOLIO.read_text())
    surgical_tickers = set(portfolio.get("positions", {}).keys()) | \
                       set(portfolio.get("pending_orders", {}).keys()) | \
                       set(portfolio.get("watchlist", []))
    overlap = ticker_symbol in surgical_tickers

    if overlap:
        verdict = "BLOCKED — OVERLAP"
    elif total >= 70:
        verdict = "STRONG BUY" if total >= 85 else "BUY"
    elif total >= 50:
        verdict = "WATCH"
    else:
        verdict = "NO SIGNAL"

    # --- Trade Setup ---
    vel_cap = portfolio.get("velocity_capital", {})
    per_trade = vel_cap.get("per_trade_size", 175)
    target_pct = vel_cap.get("target_pct", 4.5)
    stop_pct = vel_cap.get("stop_loss_pct", 3.0)

    shares = int(per_trade / current_price) if current_price > 0 else 0
    target_price = round(current_price * (1 + target_pct / 100), 2)
    stop_price = round(current_price * (1 - stop_pct / 100), 2)
    risk = current_price - stop_price
    reward = target_price - current_price
    rr_ratio = round(reward / risk, 1) if risk > 0 else 0.0

    return {
        "ticker": ticker_symbol,
        "price": current_price,
        "date": df.index[-1].strftime("%Y-%m-%d"),
        "score": total,
        "verdict": verdict,
        "components": components,
        "rsi": rsi_val,
        "macd_hist": hist_val,
        "stoch_k": stoch_k_val,
        "atr_pct": atr_pct,
        "avg_volume": avg_volume,
        "target_price": target_price,
        "stop_price": stop_price,
        "shares": shares,
        "rr_ratio": rr_ratio,
        "overlap": overlap,
    }


def format_report(result):
    """Format a velocity signal result as a markdown report."""
    if result is None:
        return ""

    t = result["ticker"]
    lines = []
    lines.append(f"\n## Velocity Signal: {t}")
    lines.append(f"**Price: ${result['price']:.2f}** | Date: {result['date']}")

    # Signal Score table
    lines.append("\n### Signal Score")
    lines.append("| Component | Value | Threshold | Points |")
    lines.append("| :--- | :--- | :--- | :--- |")
    for c in result["components"]:
        lines.append(f"| {c['name']} | {c['value']} | {c['threshold']} | {c['points']}/{c['max']} |")
    lines.append(f"| **Total** | | | **{result['score']}/100** |")

    # Trade Setup table (suppressed for blocked tickers)
    if not result.get("overlap"):
        lines.append("\n### Trade Setup")
        lines.append("| Metric | Value |")
        lines.append("| :--- | :--- |")
        lines.append(f"| Entry Price | ${result['price']:.2f} |")
        lines.append(f"| Target (+4.5%) | ${result['target_price']:.2f} |")
        lines.append(f"| Stop (-3%) | ${result['stop_price']:.2f} |")
        lines.append(f"| ATR% | {result['atr_pct']:.1f}% |")
        lines.append(f"| Avg Volume | {result['avg_volume']:,.0f} |")
        lines.append(f"| Shares (~$175) | {result['shares']} |")
        lines.append(f"| Risk/Reward | {result['rr_ratio']}:1 |")

    # Selection criteria flags
    flags = []
    if result.get("overlap"):
        flags.append("OVERLAP: Ticker is in the Surgical stock pool — cannot trade in both strategies")
    if result["atr_pct"] < 2.5:
        flags.append("ATR% below 2.5% minimum")
    if result["avg_volume"] < 2_000_000:
        flags.append("Avg volume below 2M minimum")
    if not (5 <= result["price"] <= 80):
        flags.append(f"Price ${result['price']:.2f} outside $5-$80 range")

    if flags:
        lines.append("\n### Selection Flags")
        for f in flags:
            lines.append(f"- {f}")

    lines.append(f"\n### Verdict: **{result['verdict']}**")

    return "\n".join(lines)


def cache_signal(result):
    """Write signal report to agents/<TICKER>/velocity_signal.md"""
    if result is None:
        return
    ticker = result["ticker"]
    agent_dir = ROOT / "agents" / ticker
    agent_dir.mkdir(parents=True, exist_ok=True)
    report = format_report(result)
    (agent_dir / "velocity_signal.md").write_text(report.lstrip("\n") + "\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 velocity_scanner.py <TICKER>")
        sys.exit(1)

    ticker = sys.argv[1].upper()
    result = score_velocity_signal(ticker)
    if result:
        report = format_report(result)
        print(report)
        cache_signal(result)
