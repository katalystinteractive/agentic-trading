#!/usr/bin/env python3
"""
Loss Evaluator — Break-even estimates, abandon criteria (C1-C4),
redeployment ROI, capital trap alerts, and reserve effectiveness.

Gaps addressed: 6.1, 6.2, 6.3, 6.4, 4.4

CLI: python3 tools/loss_evaluator.py
     Evaluates all underwater active positions (shares > 0, current < avg_cost).
"""

import json
import re
import statistics
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from technical_scanner import calc_atr
from shared_wick import parse_wick_active_supports, parse_wick_active_levels

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO = PROJECT_ROOT / "portfolio.json"
TRADE_HISTORY = PROJECT_ROOT / "trade_history.json"
OUTPUT_FILE = PROJECT_ROOT / "loss-evaluator-flags.md"


def load_json(path):
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def parse_entry_date(entry_date_str):
    """Parse entry_date, handling 'pre-' prefix dates.
    Returns (date_obj, is_pre_strategy)."""
    if not entry_date_str:
        return None, False
    if entry_date_str.startswith("pre-"):
        rest = entry_date_str[4:]
        # Try "pre-2026-02-12"
        try:
            return datetime.strptime(rest, "%Y-%m-%d").date(), True
        except ValueError:
            pass
        # Try "pre-2026"
        try:
            year = int(rest)
            return date(year, 1, 1), True
        except ValueError:
            pass
        return None, True
    try:
        return datetime.strptime(entry_date_str, "%Y-%m-%d").date(), False
    except ValueError:
        return None, False


def get_portfolio_median_pnl(trade_history):
    """Compute portfolio median PnL from SELL records.
    Fallback 6.0% if <3 records."""
    sells = [t for t in trade_history.get("trades", [])
             if t.get("side") == "SELL" and t.get("pnl_pct") is not None]
    pnls = [t["pnl_pct"] for t in sells]
    if len(pnls) < 3:
        return 6.0
    return statistics.median(pnls)


def get_reserve_orders(ticker, portfolio):
    """Get unfilled reserve BUY orders for a ticker."""
    reserves = []
    for o in portfolio.get("pending_orders", {}).get(ticker, []):
        if o.get("type", "").upper() != "BUY":
            continue
        if o.get("filled"):
            continue
        note = o.get("note", "").lower()
        if "reserve" in note or re.search(r'\br\d', note):
            reserves.append({
                "price": o.get("price", 0),
                "shares": o.get("shares", 0),
            })
    return reserves


def get_pending_buys(ticker, portfolio):
    """Get all unfilled BUY orders for a ticker (for reserve effectiveness calc)."""
    buys = []
    for o in portfolio.get("pending_orders", {}).get(ticker, []):
        if o.get("type", "").upper() != "BUY":
            continue
        if o.get("filled"):
            continue
        buys.append({
            "price": o.get("price", 0),
            "shares": o.get("shares", 0),
        })
    return buys


# --- Criterion Functions ---

def check_c1(ticker, current_price):
    """C1: All active supports broke.
    Triggered = current_price below ALL active support prices.
    Requires >= 2 active supports to evaluate."""
    supports = parse_wick_active_supports(ticker)
    if len(supports) < 2:
        return False, f"{len(supports)} active support(s) — insufficient"
    if all(current_price < s for s in supports):
        return True, f"Below all {len(supports)} active supports (lowest: ${min(supports):.2f})"
    held = [s for s in supports if current_price >= s]
    return False, f"Holding above {len(held)}/{len(supports)} supports"


def check_c2(entry_date_str, today, threshold=30):
    """C2: Days stuck > threshold."""
    entry, is_pre = parse_entry_date(entry_date_str)
    if entry is None:
        return False, "Unknown entry date"
    days = (today - entry).days
    if days > threshold:
        suffix = " (pre-strategy)" if is_pre else ""
        return True, f"{days} days stuck{suffix}"
    return False, f"{days} days (< {threshold})"


def check_c3(avg_cost, current_price, shares, pending_reserves, threshold_loss=20, threshold_rescue=15):
    """C3: Loss > 20% AND reserves can't rescue to within 15%."""
    loss_pct = (current_price - avg_cost) / avg_cost * 100
    if loss_pct > -threshold_loss:
        return False, loss_pct, None

    # Simulate filling all reserves
    total_cost = shares * avg_cost
    total_shares = shares
    for r in pending_reserves:
        total_cost += r["shares"] * r["price"]
        total_shares += r["shares"]
    new_avg = total_cost / total_shares if total_shares > 0 else avg_cost

    rescue_gap = (new_avg - current_price) / current_price * 100
    if rescue_gap > threshold_rescue:
        return True, loss_pct, new_avg
    return False, loss_pct, new_avg


def check_c4(capital_at_risk, portfolio_median_pnl, median_fill_days, est_breakeven_days):
    """C4: Redeployment ROI exceeds hold ROI by 50%.

    Only triggers when est_breakeven_days <= 30 (recovery window exists).
    When est_breakeven_days > 30: C2 already covers, C4 does NOT trigger.
    """
    if median_fill_days is None or est_breakeven_days is None:
        return False, 0, 0

    cycle_days_est = max(median_fill_days + 3, 1)
    redeploy_roi_30d = capital_at_risk * (portfolio_median_pnl / 100) * (30 / cycle_days_est)

    if est_breakeven_days > 30:
        return False, redeploy_roi_30d, 0

    hold_roi_30d = capital_at_risk * (30 - est_breakeven_days) / 30 * portfolio_median_pnl / 100
    if hold_roi_30d <= 0:
        return False, redeploy_roi_30d, hold_roi_30d

    ratio = redeploy_roi_30d / hold_roi_30d
    triggered = ratio > 1.5
    return triggered, redeploy_roi_30d, hold_roi_30d


def estimate_breakeven(ticker, avg_cost, current_price, atr):
    """Estimate break-even time: distance / (ATR * recovery_factor).
    Returns (display_str, numeric_days)."""
    if pd.isna(atr) or atr <= 0:
        return "N/A", None

    distance = avg_cost - current_price
    if distance <= 0:
        return "0 days", 0

    # Get best active support hold rate for recovery factor
    levels = parse_wick_active_levels(ticker)
    below_levels = [lv for lv in levels if lv["price"] <= current_price]

    best_rate = 0
    for lv in below_levels:
        m = re.search(r'(\d+)', lv["hold_rate"])
        rate = int(m.group(1)) if m else 0
        if rate > best_rate:
            best_rate = rate

    if not below_levels:
        return "30+ days", 31

    if best_rate >= 60:
        recovery_factor = 0.8
    elif best_rate >= 40:
        recovery_factor = 0.5
    else:
        recovery_factor = 0.3

    daily_recovery = atr * recovery_factor
    if daily_recovery <= 0:
        return "30+ days", 31

    est_days = distance / daily_recovery
    est_days = min(est_days, 60)  # cap at 60
    est_str = f"{est_days:.0f} days" if est_days <= 30 else "30+ days"
    return est_str, round(est_days, 1)


def compute_reserve_effectiveness(avg_cost, shares, pending_buys, current_price):
    """Compute effectiveness of deploying all pending BUYs.
    Returns dict with new_avg, new_shares, distance_pct, improvement_pct, verdict."""
    if not pending_buys:
        return None

    total_cost = shares * avg_cost
    total_shares = shares
    for b in pending_buys:
        total_cost += b["shares"] * b["price"]
        total_shares += b["shares"]

    new_avg = total_cost / total_shares if total_shares > 0 else avg_cost
    distance_pct = (new_avg - current_price) / current_price * 100 if current_price > 0 else 0
    improvement_pct = (avg_cost - new_avg) / avg_cost * 100

    if distance_pct < 8:
        verdict = "DEPLOY"
    elif distance_pct < 15:
        verdict = "MARGINAL"
    else:
        verdict = "CUT LOSSES"

    return {
        "new_avg": round(new_avg, 2),
        "new_shares": total_shares,
        "distance_pct": round(distance_pct, 1),
        "improvement_pct": round(improvement_pct, 1),
        "verdict": verdict,
    }


def main():
    portfolio = load_json(PORTFOLIO)
    trade_hist = load_json(TRADE_HISTORY)
    today = date.today()
    positions = portfolio.get("positions", {})
    portfolio_median_pnl = get_portfolio_median_pnl(trade_hist)

    # Find underwater active positions
    underwater = []
    for ticker, pos in positions.items():
        shares = pos.get("shares", 0)
        if not isinstance(shares, int) or shares <= 0:
            continue

        try:
            df = yf.download(ticker, period="5d", auto_adjust=True, progress=False)
            if df.empty:
                continue
            close = df["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            current = float(close.iloc[-1])
        except Exception as e:
            print(f"*Error fetching {ticker}: {e}*")
            continue

        avg_cost = pos.get("avg_cost", 0)
        if current >= avg_cost:
            continue  # not underwater

        # Compute ATR
        try:
            df_atr = yf.download(ticker, period="1mo", auto_adjust=True, progress=False)
            if not df_atr.empty:
                atr_series = calc_atr(df_atr["High"], df_atr["Low"], df_atr["Close"])
                if isinstance(atr_series, pd.DataFrame):
                    atr_series = atr_series.iloc[:, 0]
                atr_val = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else None
            else:
                atr_val = None
        except Exception:
            atr_val = None

        underwater.append({
            "ticker": ticker,
            "pos": pos,
            "current": current,
            "avg_cost": avg_cost,
            "shares": shares,
            "atr": atr_val,
        })

    # --- Block 1: Break-Even Estimates ---
    print("### Break-Even Estimates")
    print("| Ticker | Avg Cost | Current | Loss | Nearest Support | Hold Rate | Est Break-Even |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    breakeven_data = {}
    if not underwater:
        print("| — | — | — | No underwater positions | — | — | — |")
    else:
        for u in underwater:
            ticker = u["ticker"]
            loss_pct = (u["current"] - u["avg_cost"]) / u["avg_cost"] * 100
            atr = u["atr"] if u["atr"] is not None else float("nan")

            be_str, be_days = estimate_breakeven(ticker, u["avg_cost"], u["current"], atr)
            breakeven_data[ticker] = (be_str, be_days)

            # Nearest support
            levels = parse_wick_active_levels(ticker)
            below = [lv for lv in levels if lv["price"] <= u["current"]]
            if below:
                nearest = max(below, key=lambda x: x["price"])
                nearest_str = f"${nearest['price']:.2f}"
                hold_str = nearest["hold_rate"]
            else:
                nearest_str = "None"
                hold_str = "—"

            print(f"| {ticker} | ${u['avg_cost']:.2f} | ${u['current']:.2f} | {loss_pct:.1f}% | {nearest_str} | {hold_str} | {be_str} |")

    # --- Block 2: Abandon Criteria Flags ---
    print("")
    print("### Loss Evaluator Flags")
    print("| Ticker | Days Stuck | Loss % | Triggers | Redeploy ROI (30d) | Est Break-Even | Verdict | LLM Check |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    flag_lines = []
    if not underwater:
        line = "| — | — | — | None | — | — | — | — |"
        print(line)
        flag_lines.append(line)
    else:
        for u in underwater:
            ticker = u["ticker"]
            entry_date_str = u["pos"].get("entry_date", "")
            loss_pct = (u["current"] - u["avg_cost"]) / u["avg_cost"] * 100

            # C1
            c1_triggered, c1_detail = check_c1(ticker, u["current"])
            # C2
            c2_triggered, c2_detail = check_c2(entry_date_str, today)
            # C3
            reserves = get_reserve_orders(ticker, portfolio)
            c3_triggered, c3_loss, c3_new_avg = check_c3(
                u["avg_cost"], u["current"], u["shares"], reserves)
            # C4
            be_str, be_days = breakeven_data.get(ticker, ("N/A", None))
            cycle_timing_path = PROJECT_ROOT / "tickers" / ticker / "cycle_timing.json"
            ct = load_json(cycle_timing_path)
            median_fill_days = ct.get("statistics", {}).get("median_deep")
            capital_at_risk = u["shares"] * u["avg_cost"]
            c4_triggered, redeploy_roi, hold_roi = check_c4(
                capital_at_risk, portfolio_median_pnl, median_fill_days, be_days)

            # Days stuck display
            entry, is_pre = parse_entry_date(entry_date_str)
            if entry:
                days_stuck = (today - entry).days
                days_str = f"{days_stuck}" + (" (pre)" if is_pre else "")
            else:
                days_str = "?"

            # Triggers list
            triggers = []
            if c1_triggered:
                triggers.append("C1")
            if c2_triggered:
                triggers.append("C2")
            if c3_triggered:
                triggers.append("C3")
            if c4_triggered:
                triggers.append("C4")
            trigger_str = ", ".join(triggers) if triggers else "None"

            # Verdict (first-match-wins)
            if len(triggers) >= 2 or c1_triggered:
                verdict = "ABANDON_CANDIDATE"
            elif len(triggers) == 1:
                verdict = "REVIEW"
            else:
                verdict = "HOLD"

            # LLM check column
            llm_checks = []
            if c1_triggered:
                llm_checks.append("Verify support structure")
            if verdict == "ABANDON_CANDIDATE":
                llm_checks.append("Confirm thesis broken")
            llm_str = "; ".join(llm_checks) if llm_checks else "—"

            redeploy_str = f"${redeploy_roi:.0f}" if redeploy_roi else "—"
            be_display = be_str

            line = f"| {ticker} | {days_str} | {loss_pct:.1f}% | {trigger_str} | {redeploy_str} | {be_display} | {verdict} | {llm_str} |"
            print(line)
            flag_lines.append(line)

    # --- Block 3: Reserve Effectiveness ---
    print("")
    print("### Reserve Effectiveness")
    print("| Ticker | Current Shares | Current Avg | With Reserves | New Avg | Distance | Improvement | Verdict |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    has_reserve_rows = False
    for u in underwater:
        ticker = u["ticker"]
        pending_buys = get_pending_buys(ticker, portfolio)
        if not pending_buys:
            continue
        eff = compute_reserve_effectiveness(
            u["avg_cost"], u["shares"], pending_buys, u["current"])
        if eff is None:
            continue
        has_reserve_rows = True
        print(f"| {ticker} | {u['shares']} | ${u['avg_cost']:.2f} | {eff['new_shares']} | ${eff['new_avg']:.2f} | {eff['distance_pct']:.1f}% | {eff['improvement_pct']:.1f}% | {eff['verdict']} |")

    if not has_reserve_rows:
        print("| — | — | — | — | — | No reserves pending | — | — |")

    # --- Block 4: Capital Trap Summary ---
    print("")
    print("### Capital Trap Alert")
    print("| Ticker | Days Stuck | Loss | Est Recovery | Redeploy Recovery | Verdict |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- |")

    has_trap = False
    for u in underwater:
        ticker = u["ticker"]
        entry_date_str = u["pos"].get("entry_date", "")
        entry, is_pre = parse_entry_date(entry_date_str)
        days = (today - entry).days if entry else 0
        loss_pct = (u["current"] - u["avg_cost"]) / u["avg_cost"] * 100
        be_str, be_days = breakeven_data.get(ticker, ("N/A", None))

        # Only show if days > 20 or loss > 15%
        if days <= 20 and loss_pct > -15:
            continue
        has_trap = True

        cycle_timing_path = PROJECT_ROOT / "tickers" / ticker / "cycle_timing.json"
        ct = load_json(cycle_timing_path)
        median_fill_days = ct.get("statistics", {}).get("median_deep")
        if median_fill_days is not None:
            cycle_est = median_fill_days + 3
            redeploy_str = f"~{cycle_est} days/cycle"
        else:
            redeploy_str = "No cycle data"

        # Use the worst verdict from Block 2
        # Re-derive since we need it
        c1_triggered, _ = check_c1(ticker, u["current"])
        c2_triggered, _ = check_c2(entry_date_str, today)
        reserves = get_reserve_orders(ticker, portfolio)
        c3_triggered, _, _ = check_c3(u["avg_cost"], u["current"], u["shares"], reserves)
        capital_at_risk = u["shares"] * u["avg_cost"]
        c4_triggered, _, _ = check_c4(capital_at_risk, portfolio_median_pnl, median_fill_days, be_days)
        n_triggers = sum([c1_triggered, c2_triggered, c3_triggered, c4_triggered])
        if n_triggers >= 2 or c1_triggered:
            verdict = "ABANDON_CANDIDATE"
        elif n_triggers == 1:
            verdict = "REVIEW"
        else:
            verdict = "HOLD"

        print(f"| {ticker} | {days} | {loss_pct:.1f}% | {be_str} | {redeploy_str} | {verdict} |")

    if not has_trap:
        print("| — | — | — | No capital traps detected | — | — |")

    # Write Block 2 to file for workflow handoff
    with open(OUTPUT_FILE, "w") as f:
        f.write("### Loss Evaluator Flags\n")
        f.write("| Ticker | Days Stuck | Loss % | Triggers | Redeploy ROI (30d) | Est Break-Even | Verdict | LLM Check |\n")
        f.write("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n")
        for line in flag_lines:
            f.write(line + "\n")


if __name__ == "__main__":
    main()
