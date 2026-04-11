"""Daily Analyzer — consolidated session tool.

Processes fills/sells in batch, shows consolidated placed orders with
position summaries and sell targets, analyzes per-ticker performance,
recommends new deployments, evaluates watchlist fitness, screens for
new candidates, and reconciles broker state.

Usage:
    python3 tools/daily_analyzer.py --fills "CIFR:14.18:8" --sells "LUNR:18.89:2"
    python3 tools/daily_analyzer.py --fills "CIFR:14.18:8:2026-03-26" --sells "LUNR:18.89:2:2026-03-27"
    python3 tools/daily_analyzer.py                   # full flow: Parts 1-7 (~7-14 min)
    python3 tools/daily_analyzer.py --no-deploy       # Parts 1-2, 7 only (quick)
    python3 tools/daily_analyzer.py --no-perf         # Parts 1-2, 4-7 (skip perf analysis)
    python3 tools/daily_analyzer.py --no-fitness      # Parts 1-4, 7 only
    python3 tools/daily_analyzer.py --no-screen       # Parts 1-5, 7 only (skip screening)
    python3 tools/daily_analyzer.py --no-recon        # Parts 1-6 only (skip reconciliation)
"""
import sys
import json
import re
import argparse
import subprocess
from pathlib import Path
from datetime import date, datetime

_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent
COOLDOWN_PATH = _ROOT / "cooldown.json"
FITNESS_JSON_PATH = _ROOT / "watchlist-fitness.json"
SHORTLIST_JSON_PATH = _ROOT / "candidate_shortlist.json"
CANDIDATES_JSON_PATH = _ROOT / "data" / "candidates.json"
UNIVERSE_CACHE_PATH = _ROOT / "data" / "universe_screen_cache.json"
REMOVAL_SCORE_THRESHOLD = 50
CANDIDATE_SCORE_THRESHOLD = 80
GRAPH_STATE_PATH = _ROOT / "data" / "graph_state.json"

sys.path.insert(0, str(TOOLS_DIR))
from portfolio_manager import _load, cmd_fill, cmd_sell, parse_bullets_used
from shared_utils import is_active_buy as _is_active_buy, is_active_sell as _is_active_sell
from shared_utils import compute_days_held, compute_time_stop


# ---------------------------------------------------------------------------
# Shared infrastructure
# ---------------------------------------------------------------------------

def _fetch_position_prices(tickers):
    """Batch-fetch live prices for position tickers. Returns {ticker: price}."""
    import yfinance as yf
    if not tickers:
        return {}
    try:
        data = yf.download(list(tickers), period="5d", progress=False)
        prices = {}
        for t in tickers:
            try:
                col = data["Close"][t] if len(tickers) > 1 else data["Close"]
                val = col.dropna().iloc[-1]
                prices[t] = round(float(val), 2)
            except (KeyError, IndexError):
                pass
        return prices
    except Exception:
        return {}


def print_market_regime():
    """Part 0: Fetch and display market regime. Returns (regime, vix, vix_5d_pct)."""
    vix_5d_pct = None
    try:
        from shared_regime import fetch_regime_detail
        detail = fetch_regime_detail()
        regime = detail["regime"]
        vix = detail["vix"]
        # Compute VIX 5-day change for entry gate CAUTION rule
        try:
            import yfinance as yf
            vix_hist = yf.download("^VIX", period="10d", progress=False)
            if not vix_hist.empty:
                vc = vix_hist["Close"]
                if hasattr(vc, "columns"):
                    vc = vc.iloc[:, 0]
                if len(vc) >= 5:
                    vix_5d_pct = round((float(vc.iloc[-1]) - float(vc.iloc[-5])) / float(vc.iloc[-5]) * 100, 1)
        except Exception:
            pass
    except Exception as e:
        print(f"*Warning: Market regime fetch failed ({e}), defaulting to Neutral*\n")
        regime = "Neutral"
        vix = None

    print("## Market Regime\n")
    print("| Field | Value |")
    print("| :--- | :--- |")
    print(f"| Regime | **{regime}** |")
    if vix is not None:
        print(f"| VIX | {vix:.1f} |")

    if regime == "Risk-Off":
        print("\n*Risk-Off modifiers active: time stops +14d, sell upgrades suppressed, deployment cautioned*")
        # Load regime exit sweep results for active positions
        try:
            _re_path = Path(__file__).resolve().parent.parent / "data" / "regime_exit_sweep_results.json"
            if _re_path.exists():
                with open(_re_path) as _f:
                    _re_data = json.load(_f)
                _data = _load()
                _positions = _data.get("positions", {})
                _exits = []
                for tk, pos in _positions.items():
                    if pos.get("shares", 0) <= 0 or pos.get("winding_down"):
                        continue
                    _re = _re_data.get(tk, {}).get("regime_exit_params", {})
                    if _re.get("regime_exit_pct", 0) > 0:
                        shares = pos["shares"]
                        exit_shares = max(1, round(shares * _re["regime_exit_pct"] / 100))
                        _exits.append((tk, exit_shares, shares, _re["regime_exit_pct"],
                                       _re.get("regime_exit_hold_days", 0)))
                if _exits:
                    print("\n### Regime Exit Recommendations")
                    print("| Ticker | Sell Shares | Of Total | Exit % | After Days |")
                    print("| :--- | :--- | :--- | :--- | :--- |")
                    for tk, exit_sh, total, pct, hold in _exits:
                        print(f"| {tk} | {exit_sh} | {total} | {pct}% | {hold}d |")
                    print()
        except Exception:
            pass
    elif regime == "Risk-On":
        print("\n*Risk-On: standard rules, full deployment*")
    print()
    return regime, vix, vix_5d_pct


# ---------------------------------------------------------------------------
# Batch technical data + Verdict / Gate / Projection sections
# ---------------------------------------------------------------------------

def _fetch_technical_data(tickers):
    """Batch fetch 3-month daily data and compute RSI/MACD per ticker.
    Returns: {ticker: {rsi: float, macd_vs_signal: str, histogram: float}}
    """
    import yfinance as yf
    try:
        from technical_scanner import calc_rsi, calc_macd
    except ImportError:
        return {}

    if not tickers:
        return {}

    result = {}
    try:
        hist = yf.download(tickers, period="3mo", interval="1d", progress=False)
        if hist.empty:
            return {}
        multi = len(tickers) > 1
        for tk in tickers:
            try:
                if multi:
                    close = hist["Close"][tk].dropna()
                else:
                    close = hist["Close"].dropna()
                    if hasattr(close, "columns"):
                        close = close.iloc[:, 0]
                if len(close) < 35:
                    result[tk] = {"rsi": None, "macd_vs_signal": None, "histogram": None}
                    continue

                rsi_series = calc_rsi(close)
                rsi_val = float(rsi_series.iloc[-1]) if len(rsi_series) > 0 else None

                macd_line, signal_line, hist_series = calc_macd(close)
                if len(macd_line) > 0 and len(signal_line) > 0:
                    macd_vs = "above" if float(macd_line.iloc[-1]) > float(signal_line.iloc[-1]) else "below"
                    hist_val = float(hist_series.iloc[-1]) if len(hist_series) > 0 else None
                else:
                    macd_vs = None
                    hist_val = None

                result[tk] = {"rsi": round(rsi_val, 1) if rsi_val is not None else None,
                             "macd_vs_signal": macd_vs,
                             "histogram": round(hist_val, 3) if hist_val is not None else None}
            except Exception:
                result[tk] = {"rsi": None, "macd_vs_signal": None, "histogram": None}
    except Exception:
        pass
    return result


def print_position_verdicts(live_prices, regime, vix, vix_5d_pct):
    """Print per-position verdict table using deterministic rules."""
    from shared_utils import classify_momentum, compute_verdict, compute_days_held, is_recovery_position
    from earnings_gate import check_earnings_gate

    data = _load()
    positions = data.get("positions", {})
    active = {tk: p for tk, p in positions.items() if p.get("shares", 0) > 0}
    if not active:
        return {}

    # Batch fetch technical data
    tech = _fetch_technical_data(list(active.keys()))

    print("\n## Position Verdicts\n")
    print("| Ticker | P/L% | Time | Earnings | Momentum | Verdict | Rule |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")

    verdicts_data = {}
    for tk in sorted(active.keys()):
        pos = active[tk]
        price = live_prices.get(tk)
        if not price:
            print(f"| {tk} | ? | ? | ? | ? | REVIEW | No price data |")
            verdicts_data[tk] = {"verdict": "REVIEW", "rule": "No price data",
                                 "pl_pct": 0, "time_status": "?",
                                 "earnings_gate": "?", "momentum": "?"}
            continue

        avg_cost = pos.get("avg_cost", 0)
        pl_pct = round((price - avg_cost) / avg_cost * 100, 1) if avg_cost > 0 else 0

        # Time stop
        days, day_str, is_pre = compute_days_held(pos.get("entry_date", ""), None)
        from shared_utils import compute_time_stop
        time_status = compute_time_stop(days, is_pre, regime)

        # Earnings gate
        try:
            gate = check_earnings_gate(tk)
            eg_status = gate["status"]
        except Exception:
            eg_status = "CLEAR"

        # Momentum
        td = tech.get(tk, {})
        momentum = classify_momentum(td.get("rsi"), td.get("macd_vs_signal"), td.get("histogram"))

        # Verdict
        verdict, rule, detail = compute_verdict(
            avg_cost, price, pos.get("entry_date", ""), pos.get("note", ""),
            eg_status, momentum, regime)

        verdicts_data[tk] = {"verdict": verdict, "rule": rule, "pl_pct": pl_pct,
                             "time_status": time_status, "earnings_gate": eg_status,
                             "momentum": momentum}

        # Format
        pl_str = f"{pl_pct:+.1f}%"
        time_str = f"{day_str} {time_status}" if not is_pre else f"pre {time_status}"
        v_style = f"**{verdict}**" if verdict in ("EXIT", "REDUCE", "REVIEW") else verdict

        print(f"| {tk} | {pl_str} | {time_str} | {eg_status} | {momentum} | {v_style} | {rule} |")

    return verdicts_data


def print_entry_gates(regime, vix, vix_5d_pct, live_prices):
    """Print per-order entry gate table (market + earnings combined)."""
    from shared_utils import compute_entry_gate
    from earnings_gate import check_earnings_gate

    data = _load()
    pending = data.get("pending_orders", {})
    positions = data.get("positions", {})
    watchlist = set(data.get("watchlist", []))

    has_orders = False
    rows = []

    for tk, orders in sorted(pending.items()):
        active_buys = [o for o in orders if o.get("type") == "BUY"
                       and o.get("placed") and not o.get("filled")]
        if not active_buys:
            continue

        is_wl = tk not in positions or positions[tk].get("shares", 0) == 0
        current = live_prices.get(tk)

        try:
            gate = check_earnings_gate(tk)
            eg_status = gate["status"]
        except Exception:
            eg_status = "CLEAR"

        for order in active_buys:
            o_price = order.get("price", 0)
            note = order.get("note", "")
            # Extract label (A1, A2, B1, etc.) from note
            import re
            label_match = re.search(r'\b(A[1-5]|B[1-5]|R[1-3])\b', note)
            label = label_match.group() if label_match else "?"

            if current and current > 0:
                market_gate, earn_gate, combined = compute_entry_gate(
                    regime, vix, vix_5d_pct, eg_status, o_price, current, is_wl)
            else:
                market_gate, earn_gate, combined = "?", "?", "?"

            rows.append((tk, label, o_price, market_gate, earn_gate, combined))
            has_orders = True

    if not has_orders:
        return {}

    print("\n## Entry Gates\n")
    print("| Ticker | Order | Price | Market | Earnings | Combined |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- |")
    gates_data = {}
    for tk, label, price, mg, eg, cg in rows:
        cg_style = f"**{cg}**" if cg in ("PAUSE", "REVIEW") else cg
        print(f"| {tk} | {label} | ${price:.2f} | {mg} | {eg} | {cg_style} |")
        key = f"{tk}:{label}:{price:.2f}"
        gates_data[key] = {"market": mg, "earnings": eg, "combined": cg}

    return gates_data


def print_sell_projections():
    """Print what-if sell scenario tables for positions with pending buys."""
    from shared_utils import compute_sell_scenarios, is_active_buy

    data = _load()
    positions = data.get("positions", {})
    pending = data.get("pending_orders", {})

    shown = False
    for tk in sorted(positions.keys()):
        pos = positions[tk]
        shares = pos.get("shares", 0)
        avg_cost = pos.get("avg_cost", 0)
        if shares <= 0 or avg_cost <= 0:
            continue

        # Get pending BUY orders
        tk_orders = pending.get(tk, [])
        active_buys = [{"price": o["price"], "shares": o.get("shares", 1)}
                       for o in tk_orders if is_active_buy(o)]
        if not active_buys:
            continue

        scenarios = compute_sell_scenarios(shares, avg_cost, active_buys)
        if len(scenarios) <= 1:
            continue

        if not shown:
            print("\n## Sell Projections\n")
            shown = True

        print(f"### {tk} ({shares} sh @ ${avg_cost:.2f})")
        print("| Scenario | Shares | Avg Cost | Sell 6% | P/L$ |")
        print("| :--- | :--- | :--- | :--- | :--- |")
        for s in scenarios:
            print(f"| {s['scenario']} | {s['total_shares']} | ${s['new_avg']:.2f} "
                  f"| ${s['sell_price']:.2f} | ${s['pl_dollars']:.2f} |")
        print()


# ---------------------------------------------------------------------------
# Catastrophic drawdown constants
# ---------------------------------------------------------------------------
CATASTROPHIC_WARNING = 15.0
CATASTROPHIC_HARD_STOP = 25.0
CATASTROPHIC_EXIT_REVIEW = 40.0


def print_catastrophic_alerts(prices):
    """Alert on positions with severe drawdown from avg cost."""
    data = _load()
    positions = data.get("positions", {})

    alerts = []
    for ticker, pos in sorted(positions.items()):
        shares = pos.get("shares", 0)
        avg = pos.get("avg_cost", 0)
        if shares <= 0 or avg <= 0:
            continue
        price = prices.get(ticker)
        if price is None:
            continue
        drawdown = round((price - avg) / avg * 100, 1)
        if drawdown <= -CATASTROPHIC_WARNING:
            if drawdown <= -CATASTROPHIC_EXIT_REVIEW:
                severity = "EXIT REVIEW"
            elif drawdown <= -CATASTROPHIC_HARD_STOP:
                severity = "HARD STOP"
            else:
                severity = "WARNING"
            alerts.append((ticker, avg, price, drawdown, severity))

    alerts_dict = {t: {"avg_cost": a, "price": p, "drawdown": d, "severity": s}
                   for t, a, p, d, s in alerts}

    if not alerts:
        return set(), {}

    print("\n## Catastrophic Drawdown Alerts")
    print("| Ticker | Avg Cost | Price | Drawdown | Severity | Action |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- |")
    for ticker, avg, price, dd, sev in alerts:
        action = {
            "WARNING": "Check news before any action",
            "HARD STOP": "Pause all pending BUYs — do NOT average down",
            "EXIT REVIEW": "Recommend exit regardless of time stop",
        }[sev]
        print(f"| **{ticker}** | ${avg:.2f} | ${price:.2f} | {dd:.1f}% | **{sev}** | {action} |")

    paused = {t for t, _, _, _, s in alerts if s in ("HARD STOP", "EXIT REVIEW")}
    return paused, alerts_dict


def print_position_age_monitor(prices, regime="Neutral"):
    """Print position age table with time stop status."""
    data = _load()
    positions = data.get("positions", {})
    today = date.today()

    rows = []
    for ticker, pos in sorted(positions.items()):
        shares = pos.get("shares", 0)
        if shares <= 0:
            continue
        avg = pos.get("avg_cost", 0)
        entry = pos.get("entry_date", "")
        days, display, is_pre = compute_days_held(entry, today)
        status = compute_time_stop(days, is_pre, regime)
        price = prices.get(ticker, avg)
        pnl = round((price - avg) / avg * 100, 1) if avg > 0 else 0
        note = ""
        if is_pre:
            note = "Pre-strategy"
        elif status == "EXCEEDED":
            note = "Run exit-review workflow"
        elif status == "APPROACHING":
            note = "Plan exit strategy"
        rows.append((ticker, display, status, avg, pnl, note))

    age_data = {tk: {"days": d, "status": s, "avg_cost": a, "pnl_pct": p}
                for tk, d, s, a, p, _ in rows}

    if not rows:
        return age_data

    flagged = [r for r in rows if r[2] in ("EXCEEDED", "APPROACHING")]
    if not flagged and regime != "Risk-Off":
        return age_data

    print("\n## Position Age Monitor")
    if regime == "Risk-Off":
        print("*Risk-Off: time stops extended +14 days (APPROACHING >=59d, EXCEEDED >74d)*\n")
    print("| Ticker | Age | Status | Avg Cost | P/L% | Note |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- |")
    for ticker, display, status, avg, pnl, note in rows:
        marker = "**" if status in ("EXCEEDED", "APPROACHING") else ""
        print(f"| {marker}{ticker}{marker} | {display}d | {marker}{status}{marker} | ${avg:.2f} | {pnl:+.1f}% | {note} |")

    return age_data


def print_exit_strategy_summary():
    """Show exit strategy recommendation per active position — fetches fresh data."""
    import yfinance as yf
    import numpy as np

    data = _load()
    positions = data.get("positions", {})

    active_tickers = [tk for tk, pos in positions.items() if pos.get("shares", 0) > 0]
    if not active_tickers:
        return

    try:
        hist = yf.download(active_tickers, period="3mo", interval="1d", progress=False)
    except Exception:
        return

    if hist.empty:
        return

    rows = []
    for tk in sorted(active_tickers):
        try:
            if len(active_tickers) > 1:
                h = hist["High"][tk].dropna()
                l = hist["Low"][tk].dropna()
            else:
                h = hist["High"].dropna()
                l = hist["Low"].dropna()

            if len(h) < 10:
                continue

            daily_ranges = ((h - l) / l * 100).values
            med_range = float(np.median(daily_ranges[-21:]))
            days_3 = round(sum(1 for r in daily_ranges[-63:] if r >= 3.0) / min(63, len(daily_ranges)) * 100, 1)

            exit_type = "Same-Day 3%" if days_3 >= 60 else "Patient 6%+"
            rows.append((tk, med_range, days_3, exit_type))
        except Exception:
            continue

    if not rows:
        return

    print("\n## Exit Strategy by Ticker")
    print("| Ticker | Daily Range | Pct>=3% | Exit Type |")
    print("| :--- | :--- | :--- | :--- |")
    for ticker, rng, days, etype in rows:
        print(f"| {ticker} | {rng:.1f}% | {days:.0f}% | {etype} |")


def print_unfilled_same_day_exits():
    """Surface same-day exit orders that didn't fill."""
    data = _load()
    pending = data.get("pending_orders", {})

    unfilled = []
    for ticker, orders in pending.items():
        for o in orders:
            if o.get("type") == "SELL" and "same-day-exit" in o.get("note", "").lower():
                unfilled.append((ticker, o["price"], o["shares"]))

    if not unfilled:
        return

    print("\n## Unfilled Same-Day Exits")
    print("*These same-day exit orders are still pending.*\n")
    print("| Ticker | Price | Shares | Action |")
    print("| :--- | :--- | :--- | :--- |")
    for ticker, price, shares in unfilled:
        print(f"| {ticker} | ${price:.2f} | {shares} | Cancel or Hold? |")


def print_pdt_status():
    """Show pattern day trade count from same-day-exit pending sells."""
    data = _load()
    pending = data.get("pending_orders", {})
    same_day_count = sum(
        1 for orders in pending.values()
        for o in orders
        if o.get("type") == "SELL" and "same-day-exit" in o.get("note", "").lower()
    )
    if same_day_count > 0:
        print(f"\n*PDT Status: {same_day_count} same-day exit(s) pending — track against 3/5-day limit*")


def print_daily_fluctuation_watchlist(regime="Neutral", graph=None):
    """Show daily dip watchlist with today's actionable prices."""
    import yfinance as yf
    import numpy as np

    data = _load()
    positions = data.get("positions", {})
    pending = data.get("pending_orders", {})
    watchlist = data.get("watchlist", [])

    # All tickers we're tracking
    candidates = set()
    for tk, pos in positions.items():
        if pos.get("shares", 0) > 0:
            candidates.add(tk)
    for tk in watchlist:
        if any(o.get("type") == "BUY" for o in pending.get(tk, [])):
            candidates.add(tk)

    if not candidates:
        return

    blocked_dip = []  # tickers blocked by graph (catastrophic/verdict)

    # Batch fetch 1-month daily data for all candidates
    try:
        tickers_list = sorted(candidates)
        hist = yf.download(tickers_list, period="1mo", interval="1d", progress=False)
    except Exception:
        return

    if hist.empty:
        return

    rows = []
    for tk in sorted(candidates):
        try:
            if len(tickers_list) > 1:
                o = hist["Open"][tk].dropna()
                h = hist["High"][tk].dropna()
                l = hist["Low"][tk].dropna()
                c = hist["Close"][tk].dropna()
            else:
                o = hist["Open"].dropna()
                h = hist["High"].dropna()
                l = hist["Low"].dropna()
                c = hist["Close"].dropna()

            if len(o) < 10:
                continue

            ov = o.values
            hv = h.values
            lv = l.values
            cv = c.values

            # Daily range
            daily_range = (hv - lv) / lv * 100
            med_range = float(np.median(daily_range))

            # First-hour dip proxy: open-to-low as % of open
            open_to_low = (ov - lv) / ov * 100
            med_dip = float(np.median(open_to_low))
            dip_days = sum(1 for d in open_to_low if d > 1.0)
            dip_pct = round(dip_days / len(open_to_low) * 100)

            # Recovery: low-to-high as % of low
            low_to_high = (hv - lv) / lv * 100
            recovery_2 = round(sum(1 for r in low_to_high if r >= 2) / len(low_to_high) * 100)
            recovery_3 = round(sum(1 for r in low_to_high if r >= 3) / len(low_to_high) * 100)

            # Today's open (last row = today if market open, yesterday if closed)
            today_open = float(ov[-1])

            # Actionable prices
            buy_at = round(today_open * (1 - 0.01), 2)  # open - 1%
            sell_3 = round(buy_at * 1.04, 2)

            # Only show tickers with decent daily range and recovery
            if med_range < 3.0 or recovery_2 < 60:
                continue

            # Graph-based dip viability (when simulation data available)
            dip_status = None
            if graph is not None:
                dip_node = graph.nodes.get(f"{tk}:dip_viable")
                if dip_node and dip_node.value:
                    dip_status = dip_node.value
                    if dip_status == "BLOCKED":
                        blocked_dip.append(tk)
                        continue
                    elif dip_status == "NO":
                        continue

            rows.append((tk, today_open, buy_at, sell_3, med_range, dip_pct, recovery_2, recovery_3, dip_status))
        except Exception:
            continue

    if not rows:
        return

    print("\n## Daily Dip Watchlist")

    if regime == "Risk-Off":
        print("**WARNING: Risk-Off regime — dips are likely to keep dipping. Daily plays are HIGH RISK today.**")
        print("*Consider skipping daily dip plays entirely or using half-size positions.*\n")
    else:
        print("*Optimized rules: $100/ticker, top 5 dippers only, sell +3%, stop -3%, cut at EOD.*")
        print("*Wait for 10:30 AM confirmation before buying. Run dip_signal_checker.py at ~10:30.*\n")

    # Earnings gate check
    gated_tickers = set()
    try:
        from earnings_gate import check_earnings_gate
        for tk, *_ in rows:
            gate = check_earnings_gate(tk)
            if gate["blocked"]:
                gated_tickers.add(tk)
    except Exception:
        pass

    print("| Ticker | Open | Buy (-1%) | Sell +4% | Stop -3% | Range | Dip Days | +3% Win |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    shown = 0
    for row in rows:
        tk, today_open, buy, s3, rng, dip_d, rec2, rec3 = row[:8]
        dip_status = row[8] if len(row) > 8 else None
        if tk in gated_tickers:
            print(f"| ~~{tk}~~ | — | — | — | — | — | — | EARNINGS GATE |")
        else:
            stop = round(buy * 0.97, 2)
            print(f"| {tk} | ${today_open:.2f} | ${buy:.2f} | ${s3:.2f} | ${stop:.2f} | {rng:.1f}% | {dip_d}% | {rec3}% |")
            shown += 1

    print(f"\n*{shown} eligible tickers ({len(gated_tickers)} earnings-gated). Top 5 at signal. PDT: each = 1 day trade.*")
    print("*Run `python3 tools/dip_signal_checker.py` at ~10:30 AM ET for buy/no-buy confirmation.*")


# ---------------------------------------------------------------------------
# Part 1 — Process fills and sells
# ---------------------------------------------------------------------------

def parse_specs(spec_string):
    """Parse 'TICKER:PRICE:SHARES[:DATE],...' → (list of tuples, parse_error_count).

    Each item is TICKER:PRICE:SHARES or TICKER:PRICE:SHARES:YYYY-MM-DD.
    If date is omitted, defaults to last trading day.
    Returns list of (ticker, price, shares, trade_date_str).
    """
    if not spec_string:
        return [], 0

    from trading_calendar import last_trading_day
    default_date = last_trading_day().isoformat()

    results = []
    errors = 0
    for item in spec_string.split(","):
        item = item.strip()
        if not item:
            continue
        parts = item.split(":")
        if len(parts) not in (3, 4):
            print(f"*Error: bad spec '{item}' — expected TICKER:PRICE:SHARES or TICKER:PRICE:SHARES:DATE*")
            errors += 1
            continue
        ticker = parts[0].strip().upper()
        try:
            price = float(parts[1].strip())
            shares = int(parts[2].strip())
        except ValueError:
            print(f"*Error: bad spec '{item}' — price/shares not numeric*")
            errors += 1
            continue
        if shares <= 0:
            print(f"*Error: bad spec '{item}' — shares must be positive*")
            errors += 1
            continue
        trade_date = default_date
        if len(parts) == 4:
            d = parts[3].strip()
            # Validate date format YYYY-MM-DD
            import re as _re
            if _re.match(r'^\d{4}-\d{2}-\d{2}$', d):
                trade_date = d
            else:
                print(f"*Error: bad date '{d}' in '{item}' — expected YYYY-MM-DD*")
                errors += 1
                continue
        results.append((ticker, price, shares, trade_date))
    return results, errors


def process_transactions(fills, sells, parse_errors=0):
    """Call cmd_fill/cmd_sell for each spec with sys.exit trap."""
    if not fills and not sells and not parse_errors:
        return

    ok, fail = 0, parse_errors

    # Suppress sell_target auto-output during batch fills
    import sell_target_calculator
    _orig_analyze = sell_target_calculator.analyze_ticker
    sell_target_calculator.analyze_ticker = lambda *a, **kw: None

    for ticker, price, shares, trade_date in fills:
        args = argparse.Namespace(ticker=ticker, price=price, shares=shares,
                                  trade_date=trade_date)
        try:
            data = _load()
            cmd_fill(data, args)
            ok += 1
            print()
        except SystemExit:
            print(f"*Error: failed to process fill {ticker}:{price}:{shares}*")
            fail += 1
            print()
        except Exception as e:
            print(f"*Error: fill {ticker}:{price}:{shares} — {e}*")
            fail += 1
            print()

    # Restore sell_target_calculator
    sell_target_calculator.analyze_ticker = _orig_analyze

    for ticker, price, shares, trade_date in sells:
        args = argparse.Namespace(ticker=ticker, price=price, shares=shares,
                                  trade_date=trade_date)
        try:
            data = _load()
            cmd_sell(data, args)
            ok += 1
            print()
        except SystemExit:
            print(f"*Error: failed to process sell {ticker}:{price}:{shares}*")
            fail += 1
            print()
        except Exception as e:
            print(f"*Error: sell {ticker}:{price}:{shares} — {e}*")
            fail += 1
            print()

    summary = f"**Processed {ok} transaction(s)**"
    if fail:
        summary += f", **{fail} failed**"
    print(summary)
    print()


# ---------------------------------------------------------------------------
# Part 2 — Consolidated placed orders table
# ---------------------------------------------------------------------------

def truncate_note(note, max_len=45):
    """Extract label + tier from order note."""
    if not note:
        return ""
    m = re.match(
        r'((?:A\d|B\d|R\d|Bullet \d|Reserve \d).*?,\s*(?:Full|Std|Half|Skip)[\^v]?)',
        note,
    )
    if m:
        return m.group(1)
    return note[:max_len] + ("..." if len(note) > max_len else "")


def print_consolidated_orders():
    """Build and print Part 2 table from portfolio.json."""
    data = _load()
    positions = data.get("positions", {})
    pending = data.get("pending_orders", {})

    # Collect tickers to show: has shares OR has active placed orders
    tickers_to_show = set()
    for ticker, pos in positions.items():
        if pos.get("shares", 0) > 0:
            tickers_to_show.add(ticker)
    for ticker, orders in pending.items():
        for o in orders:
            if (_is_active_buy(o) or _is_active_sell(o)):
                tickers_to_show.add(ticker)
                break

    if not tickers_to_show:
        print("*No active positions or placed orders.*")
        return

    today = date.today().isoformat()
    print(f"## Placed Orders & Positions — {today} ({len(tickers_to_show)} tickers)")
    print()
    print("| Ticker | Type | Price | Shares | Note |")
    print("| :--- | :--- | :--- | :--- | :--- |")

    first_ticker = True
    for ticker in sorted(tickers_to_show):
        if not first_ticker:
            print("| — | — | — | — | — |")
        first_ticker = False

        orders = pending.get(ticker, [])
        pos = positions.get(ticker, {})
        shares = pos.get("shares", 0)
        avg_cost = pos.get("avg_cost", 0)

        # BUY rows (price descending — highest first)
        active_buys = [o for o in orders if _is_active_buy(o)]
        active_buys.sort(key=lambda o: o["price"], reverse=True)
        for o in active_buys:
            note = truncate_note(o.get("note", ""))
            print(f"| {ticker} | BUY | ${o['price']:.2f} | {o['shares']} | {note} |")

        # Position summary (only if shares > 0)
        if shares > 0:
            bu_raw = pos.get("bullets_used", 0)
            bu = parse_bullets_used(bu_raw, pos.get("note", ""))
            parts = []
            if bu["active"]:
                parts.append(f"{bu['active']}A")
            if bu["reserve"]:
                parts.append(f"R{bu['reserve']}")
            if bu["pre_strategy"]:
                parts.append("pre")
            bu_label = "+".join(parts) + " used" if parts else "0 used"
            print(
                f"| **{ticker}** | **Position** | **${avg_cost:.2f} avg** "
                f"| **{shares} sh** | **{bu_label}** |"
            )

        # SELL rows — priority: placed SELL orders → target_exit → math fallback
        sell_rows_printed = 0
        for o in orders:
            if _is_active_sell(o):
                pnl = round((o["price"] - avg_cost) / avg_cost * 100, 1) if avg_cost > 0 else 0
                sign = "+" if pnl >= 0 else ""
                print(
                    f"| **{ticker}** | **SELL** | **${o['price']:.2f}** "
                    f"| **{o['shares']}** | **{sign}{pnl}%** |"
                )
                sell_rows_printed += 1

        if sell_rows_printed == 0 and shares > 0:
            target = pos.get("target_exit")
            if target:
                pnl = round((target - avg_cost) / avg_cost * 100, 1) if avg_cost > 0 else 0
                sign = "+" if pnl >= 0 else ""
                print(
                    f"| **{ticker}** | **SELL** | **${target:.2f}** "
                    f"| **{shares}** | **target {sign}{pnl}%** |"
                )
            else:
                fallback = round(avg_cost * 1.06, 2)
                print(
                    f"| **{ticker}** | **SELL** | **${fallback:.2f}** "
                    f"| **{shares}** | **math 6.0%** |"
                )

    print()


def print_tier_summary():
    """Print a compact tier one-liner from watchlist_manager.py."""
    try:
        result = subprocess.run(
            [sys.executable, str(TOOLS_DIR / "watchlist_manager.py"), "--json", "status"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return
        totals = json.loads(result.stdout).get("totals", {})
    except Exception:
        return
    parts = []
    for tier in ("ACTIVE", "ENGAGED", "SCOUTING", "CANDIDATE"):
        count = totals.get(tier, 0)
        if count:
            parts.append(f"{count} {tier}")
    if parts:
        print(f"*Tiers: {' | '.join(parts)}*")
        print()


# ---------------------------------------------------------------------------
# Part 3 — Ticker Performance Analysis
# ---------------------------------------------------------------------------

def run_ticker_perf_analysis():
    """Run ticker_perf_analyzer.py, display results."""
    print("## Part 3 — Ticker Performance Analysis")
    print()
    try:
        result = subprocess.run(
            [sys.executable, str(TOOLS_DIR / "ticker_perf_analyzer.py"), "--json"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            print(f"*Error: ticker_perf_analyzer.py failed: {result.stderr.strip() or 'unknown'}*")
            return
    except subprocess.TimeoutExpired:
        print("*Error: ticker_perf_analyzer.py timed out (300s)*")
        return
    except Exception as e:
        print(f"*Error: {e}*")
        return

    if result.stdout.strip():
        # Strip the subprocess's own header (we already printed the Part 3 version)
        lines = result.stdout.strip().split("\n")
        if lines and lines[0].startswith("## "):
            lines = lines[1:]
        output = "\n".join(lines).strip()
        if output:
            print(output)
        print()


# ---------------------------------------------------------------------------
# Part 4 — Deployment recommendations
# ---------------------------------------------------------------------------

def find_deployment_tickers():
    """Identify tickers needing new limit orders (no active placed buys, not on cooldown)."""
    data = _load()
    positions = data.get("positions", {})
    pending = data.get("pending_orders", {})
    watchlist = data.get("watchlist", [])

    # Union of watchlist + position tickers
    all_tickers = set(watchlist) | set(positions.keys())

    # Load cooldowns
    cooldown_tickers = {}  # ticker → reeval_date
    if COOLDOWN_PATH.exists():
        try:
            with open(COOLDOWN_PATH, "r", encoding="utf-8") as f:
                cd = json.load(f)
            today = date.today().isoformat()
            for entry in cd.get("cooldowns", []):
                if entry.get("reeval_date", "") > today:
                    cooldown_tickers[entry["ticker"]] = entry["reeval_date"]
        except (json.JSONDecodeError, KeyError):
            pass

    result = []
    skipped_cooldown = []
    for ticker in sorted(all_tickers):
        orders = pending.get(ticker, [])
        pos = positions.get(ticker, {})
        if pos.get("winding_down"):
            continue  # Skip winding-down positions — no new bullets
        shares = pos.get("shares", 0)

        # Skip dead entries: no shares and no pending orders at all
        if shares == 0 and not orders:
            continue

        # Check active coverage
        has_active_buy = any(_is_active_buy(o) for o in orders)
        if has_active_buy:
            continue

        # Cooldown check — only for tickers that would otherwise need deployment
        if ticker in cooldown_tickers:
            skipped_cooldown.append(
                f"{ticker} (until {cooldown_tickers[ticker]})"
            )
            continue

        result.append(ticker)

    if skipped_cooldown:
        print(f"*Cooldown: {', '.join(skipped_cooldown)}*")
        print()

    return result


def print_deployment_recs(tickers, paused=None):
    """Run bullet_recommender per ticker via subprocess."""
    if not tickers:
        print("*All tickers have active placed orders — no deployment needed.*")
        return

    # Pre-check earnings gates
    earnings_gated = {}
    try:
        from earnings_gate import check_earnings_gate
        for tk in tickers:
            gate = check_earnings_gate(tk)
            if gate["blocked"]:
                earnings_gated[tk] = gate["reason"]
    except Exception:
        pass

    print(f"## Part 4 — Deployment Recommendations ({len(tickers)} tickers)")
    if earnings_gated:
        gated_str = ", ".join(earnings_gated.keys())
        print(f"\n*Earnings gate active for: {gated_str}*")
    print()

    for ticker in tickers:
        if paused and ticker in paused:
            print(f"### {ticker}\n")
            print("*PAUSED: Catastrophic drawdown — review before deploying*\n")
            continue
        print(f"### {ticker}")
        print()
        try:
            result = subprocess.run(
                [sys.executable, str(TOOLS_DIR / "bullet_recommender.py"), ticker],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0 and result.stdout.strip():
                print(result.stdout.strip())
            else:
                if result.stdout.strip():
                    print(result.stdout.strip())
                    print()
                err = result.stderr.strip() if result.stderr.strip() else "unknown error"
                print(f"*Error running bullet_recommender for {ticker}: {err}*")
        except subprocess.TimeoutExpired:
            print(f"*Error: bullet_recommender timed out for {ticker}*")
        except Exception as e:
            print(f"*Error: {e}*")
        print()


# ---------------------------------------------------------------------------
# Part 5 — Watchlist Fitness Check
# ---------------------------------------------------------------------------

def run_watchlist_fitness():
    """Run watchlist_fitness.py, print summary, flag removal candidates."""
    print("## Part 5 — Watchlist Fitness Check")
    print()
    try:
        result = subprocess.run(
            [sys.executable, str(TOOLS_DIR / "watchlist_fitness.py"), "--summary-only"],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            print(f"*Error: watchlist_fitness.py failed: {result.stderr.strip() or 'unknown'}*")
            return
    except subprocess.TimeoutExpired:
        print("*Error: watchlist_fitness.py timed out (180s)*")
        return
    except Exception as e:
        print(f"*Error: {e}*")
        return

    if result.stdout.strip():
        print(result.stdout.strip())
        print()

    # Read JSON
    try:
        with open(FITNESS_JSON_PATH) as f:
            fitness_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"*Error reading {FITNESS_JSON_PATH.name}: {e}*")
        return

    all_tickers = fitness_data.get("tickers", [])
    print(f"*Evaluated {len(all_tickers)} tickers.*")
    print()

    # Cross-reference portfolio.json for removal check
    data = _load()
    positions = data.get("positions", {})
    pending = data.get("pending_orders", {})

    removal = []
    for entry in all_tickers:
        ticker = entry.get("ticker", "")
        score = entry.get("fitness_score")
        if score is None or score >= REMOVAL_SCORE_THRESHOLD:
            continue
        if positions.get(ticker, {}).get("shares", 0) > 0:
            continue
        if any(_is_active_buy(o) for o in pending.get(ticker, [])):
            continue
        removal.append(entry)

    if removal:
        removal.sort(key=lambda e: e["fitness_score"])
        print(f"### Removal Candidates ({len(removal)} tickers)")
        print()
        print("| Ticker | Score | Verdict | Note |")
        print("| :--- | :--- | :--- | :--- |")
        for entry in removal:
            r_ticker = entry.get("ticker", "")
            note = (entry.get("verdict_note") or "").replace("|", "-")
            if len(note) > 60:
                note = note[:60] + "..."
            verdict = (entry.get("verdict") or "").replace("|", "-")
            print(f"| {r_ticker} | {entry['fitness_score']} | {verdict} | {note} |")
        print()
    else:
        print("*No removal candidates — all tickers score >= 50 or have active positions/orders.*")
        print()


# ---------------------------------------------------------------------------
# Part 6 — New Candidate Screening
# ---------------------------------------------------------------------------

def run_candidate_screening(wide_screen=False):
    """Run screener → filter → print new strong candidates not already tracked."""
    print("## Part 6 — New Candidate Screening")
    print()

    # Build screener args
    screener_args = [sys.executable, str(TOOLS_DIR / "surgical_screener.py")]
    if wide_screen:
        if UNIVERSE_CACHE_PATH.exists():
            screener_args.append("--universe")
            print("*Running wide screener (dynamic universe)...*")
        else:
            print("*Universe cache not found — using default 160-ticker universe. "
                  "Run: python3 tools/universe_screener.py to enable wide screening.*")
    else:
        print("*Running screener (~3-5 min)...*")
    print()

    # Step A: Screener
    try:
        result = subprocess.run(
            screener_args,
            capture_output=True, text=True, timeout=420,
        )
        if result.returncode != 0:
            print(f"*Error: surgical_screener.py failed: {result.stderr.strip() or 'unknown'}*")
            return
    except subprocess.TimeoutExpired:
        print("*Error: surgical_screener.py timed out (420s)*")
        return
    except Exception as e:
        print(f"*Error: {e}*")
        return

    # Step B: Filter (only runs if screener succeeded)
    try:
        result = subprocess.run(
            [sys.executable, str(TOOLS_DIR / "surgical_filter.py")],
            capture_output=True, text=True, timeout=180,
        )
        if result.returncode != 0:
            print(f"*Error: surgical_filter.py failed: {result.stderr.strip() or 'unknown'}*")
            return
    except subprocess.TimeoutExpired:
        print("*Error: surgical_filter.py timed out (180s)*")
        return
    except Exception as e:
        print(f"*Error: {e}*")
        return

    if result.stdout.strip():
        print(result.stdout.strip())
        print()
    else:
        print("*Filter completed.*")
        print()

    # Read shortlist JSON
    try:
        with open(SHORTLIST_JSON_PATH) as f:
            shortlist_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"*Error reading {SHORTLIST_JSON_PATH.name}: {e}*")
        return

    # Build tracked set from portfolio.json
    data = _load()
    tracked = set(data.get("watchlist", [])) | set(data.get("positions", {}).keys())

    shortlist = shortlist_data.get("shortlist", [])
    print(f"*Shortlisted {len(shortlist)} tickers.*")
    print()

    new_candidates = []
    already_tracked = []
    for entry in shortlist:
        ticker = entry.get("ticker", "")
        score = entry.get("total_score", 0)
        if score < CANDIDATE_SCORE_THRESHOLD:
            continue
        if ticker in tracked:
            already_tracked.append((ticker, score))
        else:
            new_candidates.append(entry)

    if new_candidates:
        new_candidates.sort(key=lambda e: e.get("total_score", 0), reverse=True)
        print(f"### New Candidates ({len(new_candidates)} tickers, score >= {CANDIDATE_SCORE_THRESHOLD}, not tracked)")
        print()
        print("| Ticker | Score | Sector | Swing | Top Strength |")
        print("| :--- | :--- | :--- | :--- | :--- |")
        for entry in new_candidates:
            c_ticker = entry.get("ticker", "")
            c_score = entry.get("total_score", 0)
            passer = entry.get("passer") or {}
            sector = (passer.get("sector") or "—").replace("|", "-")
            swing = passer.get("median_swing")
            swing_str = f"{swing:.1f}%" if swing is not None else "—"

            # Top Strength from cycle timing
            ct = passer.get("cycle_timing") or {}
            if "total_cycles" in ct and "immediate_fill_pct" in ct:
                strength = f"{ct['total_cycles']} cycles, {ct['immediate_fill_pct']:.0f}% fill"
            else:
                flags = entry.get("flags", [])
                if flags:
                    s = str(flags[0]).replace("|", "-")
                    strength = s[:40] + ("..." if len(s) > 40 else "")
                else:
                    strength = "—"

            print(f"| {c_ticker} | {c_score} | {sector} | {swing_str} | {strength} |")
        print()
    else:
        print(f"*No new candidates scoring >= {CANDIDATE_SCORE_THRESHOLD} outside current watchlist.*")
        print()

    if already_tracked:
        already_tracked.sort(key=lambda x: x[1], reverse=True)
        labels = ", ".join(f"{t} ({s})" for t, s in already_tracked)
        print(f"*Already tracked: {labels}*")
        print()

    _persist_candidates([e["ticker"] for e in new_candidates])


def _persist_candidates(tickers):
    """Auto-add screening candidates to data/candidates.json for cross-session tracking."""
    added_count = 0

    # Step 1: Add new tickers (skip if empty)
    if tickers:
        try:
            result = subprocess.run(
                [sys.executable, str(TOOLS_DIR / "candidate_tracker.py"), "add"] + tickers,
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and result.stdout:
                m = re.search(r"Added (\d+)", result.stdout)
                if m:
                    added_count = int(m.group(1))
        except Exception:
            pass

    # Step 2: Age-out stale entries
    try:
        subprocess.run(
            [sys.executable, str(TOOLS_DIR / "candidate_tracker.py"), "age-out"],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        pass

    # Step 3: Report pool size
    try:
        with open(CANDIDATES_JSON_PATH) as f:
            pool = json.load(f).get("candidates", [])
        msg = f"*Candidate pool: {len(pool)} tickers"
        if added_count:
            msg += f" ({added_count} new added)"
        msg += "*"
        print(msg)
        print()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Graph-driven infrastructure (replaces manual state/diff/dashboard)
# ---------------------------------------------------------------------------

def _extract_label_from_note(note):
    """Parse A1/B2/R3 from order note. Returns '?' if not found."""
    m = re.search(r'\b(A[1-5]|B[1-5]|R[1-3])\b', note or "")
    return m.group() if m else "?"


def _get_active_tickers(portfolio):
    """Return sorted list of tickers with positions or active BUY orders."""
    positions = portfolio.get("positions", {})
    pending = portfolio.get("pending_orders", {})
    tickers = set()
    for tk, pos in positions.items():
        if pos.get("shares", 0) > 0:
            tickers.add(tk)
    for tk, orders in pending.items():
        if any(_is_active_buy(o) for o in orders):
            tickers.add(tk)
    return sorted(tickers)


def _batch_earnings(tickers):
    """Call check_earnings_gate() per ticker. Returns {ticker: gate_dict}."""
    from earnings_gate import check_earnings_gate
    result = {}
    for tk in tickers:
        try:
            result[tk] = check_earnings_gate(tk)
        except Exception:
            result[tk] = {"status": "CLEAR"}
    return result


def _run_recon_for_graph(portfolio, tickers):
    """Run reconciliation per ticker, returning {ticker: recon_dict} without printing."""
    try:
        from broker_reconciliation import (
            reconcile_ticker, _load_profiles, _load_trade_history_buys, _get_bullet_ctx
        )
        from wick_offset_analyzer import load_capital_config
    except ImportError:
        return {}

    try:
        profiles = _load_profiles()
        trade_buys = _load_trade_history_buys()
    except Exception:
        return {}

    positions = portfolio.get("positions", {})
    pending = portfolio.get("pending_orders", {})
    result = {}
    for tk in tickers:
        pos = positions.get(tk)
        orders = pending.get(tk, [])
        try:
            cap = load_capital_config(tk)
            bullet_ctx = _get_bullet_ctx(tk, portfolio, cap)
        except Exception:
            bullet_ctx = None
        recon = reconcile_ticker(tk, pos, orders, bullet_ctx,
                                 trade_buys.get(tk, []), profiles)
        result[tk] = recon
    return result


def _load_graph_state():
    """Load previous graph state. Returns {} on first run."""
    if not GRAPH_STATE_PATH.exists():
        return {}
    try:
        with open(GRAPH_STATE_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _write_graph_state(state):
    """Persist graph state for next run's diff."""
    try:
        with open(GRAPH_STATE_PATH, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except OSError:
        pass


def print_action_dashboard_from_signals(signals, graph):
    """Print prioritized action dashboard from graph signals.

    Groups activated report node signals into 6 buckets:
    URGENT, PLACE, ADJUST, CANCEL, CHANGED, REVIEW
    Each row uses signal.flat_reason() — composable chain from leaf to report.
    """
    urgent = []
    place = []
    adjust = []
    cancel = []
    changed = []
    review = []

    for name, node in graph.get_activated_reports():
        val = node.value
        reason = ""
        node_path = ""
        if node.signals:
            reason = node.signals[0].flat_reason()
            node_path = node.signals[0].node_path_str()

        # Categorize by report node type
        if ":catastrophic_alert" in name:
            if val in ("HARD_STOP", "EXIT_REVIEW"):
                tk = name.split(":")[0]
                # Get drawdown from the drawdown node
                dd_node = graph.nodes.get(f"{tk}:drawdown")
                dd = dd_node.value if dd_node else "?"
                action_str = ("Pause all pending BUYs" if val == "HARD_STOP"
                              else "Recommend exit regardless of time stop")
                full_reason = f"{node_path} {reason}" if node_path else reason
                urgent.append((tk, val, f"{dd:.1f}%" if isinstance(dd, (int, float)) else "?", action_str, full_reason))

        elif ":sell_order_action" in name or ":buy_order_action" in name:
            if isinstance(val, list):
                for a in val:
                    if not isinstance(a, dict):
                        continue
                    # Prepend node path to action reason
                    if node_path and "node_path" not in a:
                        a = dict(a)  # don't mutate original
                        a["reason"] = f"{node_path} {a.get('reason', '')}"
                    action = a.get("action", "")
                    if action == "PLACE":
                        place.append(a)
                    elif "ADJUST" in action:
                        adjust.append(a)
                    elif "CANCEL" in action:
                        cancel.append(a)

        elif name == "regime_change":
            if reason:
                full_reason = f"{node_path} {reason}" if node_path else reason
                changed.append(("---", "Regime", str(node.prev_value or "?"),
                                str(val), full_reason))

        elif ":verdict_alert" in name:
            if isinstance(val, tuple) and isinstance(node.prev_value, tuple):
                if val[0] != node.prev_value[0]:
                    tk = name.split(":")[0]
                    full_reason = f"{node_path} {reason}" if node_path else reason
                    changed.append((tk, "Verdict", node.prev_value[0],
                                    val[0], full_reason))

        elif ":gate_alert" in name:
            if isinstance(val, tuple) and isinstance(node.prev_value, tuple):
                if val[2] != node.prev_value[2]:
                    tk = name.split(":")[0]
                    full_reason = f"{node_path} {reason}" if node_path else reason
                    changed.append((tk, "Gate", node.prev_value[2],
                                    val[2], full_reason))

        elif ":review" in name:
            if val and isinstance(val, tuple):
                tk = name.split(":")[0]
                review.append((tk, val[1], f"P/L {val[0]}, {val[2]}"))

    has_content = urgent or place or adjust or cancel or changed or review

    print("\n## ACTION DASHBOARD\n")

    if not has_content:
        print("*All clear — no actions needed.*\n")
        return

    if urgent:
        print("### URGENT\n")
        print("| Ticker | Severity | Drawdown | Action | Reason |")
        print("| :--- | :--- | :--- | :--- | :--- |")
        for tk, sev, dd, act, reason in urgent:
            print(f"| **{tk}** | **{sev}** | {dd} | {act} | {reason} |")
        print()

    if place:
        print("### PLACE These Orders\n")
        print("| Side | Ticker | Price | Shares | Reason |")
        print("| :--- | :--- | :--- | :--- | :--- |")
        for a in sorted(place, key=lambda x: x.get("ticker", "")):
            print(f"| {a['side']} | {a['ticker']} | ${a['rec_price']:.2f} | "
                  f"{a['rec_shares']} | {a['reason']} |")
        print()

    if adjust:
        print("### ADJUST These Orders\n")
        print("| Side | Ticker | Current | Recommended | Reason |")
        print("| :--- | :--- | :--- | :--- | :--- |")
        for a in sorted(adjust, key=lambda x: x.get("ticker", "")):
            curr = f"${a['broker_price']:.2f}/{a['broker_shares']}sh"
            rec = f"${a['rec_price']:.2f}/{a['rec_shares']}sh"
            print(f"| {a['side']} | {a['ticker']} | {curr} | {rec} | {a['reason']} |")
        print()

    if cancel:
        print("### CANCEL These Orders\n")
        print("| Side | Ticker | Price | Reason |")
        print("| :--- | :--- | :--- | :--- |")
        for a in sorted(cancel, key=lambda x: x.get("ticker", "")):
            print(f"| {a['side']} | {a['ticker']} | ${a['broker_price']:.2f} | {a['reason']} |")
        print()

    if changed:
        print("### CHANGED Since Last Run\n")
        print("| Ticker | What | Previous | Current | Reason |")
        print("| :--- | :--- | :--- | :--- | :--- |")
        for tk, field, prev, curr, reason in changed:
            print(f"| {tk} | {field} | {prev} | {curr} | {reason} |")
        print()

    if review:
        print("### REVIEW (Human Decision Needed)\n")
        print("| Ticker | Rule | Situation |")
        print("| :--- | :--- | :--- |")
        for tk, rule, situation in review:
            print(f"| {tk} | {rule} | {situation} |")
        print()


def print_detail_sections(graph, regime):
    """Print all detail sections reading values from graph nodes.

    Output format is IDENTICAL to the pre-graph tables.
    """
    from broker_reconciliation import format_ticker_report, format_action_summary

    # Part 2: Consolidated orders + tier summary (unchanged — reads portfolio directly)
    print_consolidated_orders()
    print_tier_summary()

    # Position Age Monitor — read from graph nodes
    active_positions = sorted(
        name.split(":")[0] for name in graph.nodes
        if name.endswith(":shares") and graph.nodes[name].value and graph.nodes[name].value > 0)

    if active_positions:
        age_rows = []
        for tk in active_positions:
            dh = graph.nodes.get(f"{tk}:days_held")
            ts = graph.nodes.get(f"{tk}:time_status")
            avg_node = graph.nodes.get(f"{tk}:avg_cost")
            pl_node = graph.nodes.get(f"{tk}:pl_pct")
            if dh and dh.value:
                days, display, is_pre = dh.value
                status = ts.value if ts else "?"
                avg = avg_node.value if avg_node else 0
                pnl = pl_node.value if pl_node else 0
                note = ""
                if is_pre:
                    note = "Pre-strategy"
                age_rows.append((tk, display, status, avg, pnl or 0, note))

        flagged = [r for r in age_rows if r[2] in ("EXCEEDED", "APPROACHING")]
        if flagged or regime == "Risk-Off":
            print("\n## Position Age Monitor")
            if regime == "Risk-Off":
                print("*Risk-Off: time stops extended +14 days (APPROACHING >=59d, EXCEEDED >74d)*\n")
            print("| Ticker | Age | Status | Avg Cost | P/L% | Note |")
            print("| :--- | :--- | :--- | :--- | :--- | :--- |")
            for ticker, display, status, avg, pnl, note in age_rows:
                marker = "**" if status in ("EXCEEDED", "APPROACHING") else ""
                print(f"| {marker}{ticker}{marker} | {display}d | {marker}{status}{marker} | ${avg:.2f} | {pnl:+.1f}% | {note} |")

    # Pool Allocations — read from graph nodes
    pool_rows = []
    for tk in sorted(graph.nodes):
        if tk.endswith(":pool"):
            ticker = tk.split(":")[0]
            pool = graph.nodes[tk].value
            if isinstance(pool, dict) and pool.get("source") == "multi-period-scorer":
                pool_rows.append((ticker, pool))
    if pool_rows:
        print("\n## Pool Allocations (simulation-backed)\n")
        print("| Ticker | Composite | Active | Reserve | Total | Source |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for tk, p in sorted(pool_rows, key=lambda x: x[1].get("composite") or 0, reverse=True):
            comp = f"${p.get('composite', 0):.1f}/mo" if p.get("composite") is not None else "—"
            print(f"| {tk} | {comp} | ${p.get('active_pool', 300)} | ${p.get('reserve_pool', 300)} | ${p.get('total_pool', 600)} | {p['source']} |")

    # Catastrophic Drawdown Alerts — read from graph nodes
    alerts = []
    for tk in active_positions:
        cat = graph.nodes.get(f"{tk}:catastrophic")
        if cat and cat.value:
            avg = graph.nodes.get(f"{tk}:avg_cost")
            price = graph.nodes.get(f"{tk}:price")
            dd = graph.nodes.get(f"{tk}:drawdown")
            alerts.append((tk,
                           avg.value if avg else 0,
                           price.value if price else 0,
                           dd.value if dd else 0,
                           cat.value))
    if alerts:
        print("\n## Catastrophic Drawdown Alerts")
        print("| Ticker | Avg Cost | Price | Drawdown | Severity | Action |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for ticker, avg, price, dd, sev in alerts:
            action = {
                "WARNING": "Check news before any action",
                "HARD_STOP": "Pause all pending BUYs — do NOT average down",
                "EXIT_REVIEW": "Recommend exit regardless of time stop",
            }.get(sev, "Review")
            print(f"| **{ticker}** | ${avg:.2f} | ${price:.2f} | {dd:.1f}% | **{sev}** | {action} |")

    # Position Verdicts — read from graph nodes
    verdict_rows = []
    for tk in active_positions:
        v = graph.nodes.get(f"{tk}:verdict")
        eg = graph.nodes.get(f"{tk}:earnings_gate")
        mom = graph.nodes.get(f"{tk}:momentum")
        pl = graph.nodes.get(f"{tk}:pl_pct")
        dh = graph.nodes.get(f"{tk}:days_held")
        ts = graph.nodes.get(f"{tk}:time_status")
        if v and v.value and isinstance(v.value, tuple):
            verdict, rule, detail = v.value
            pl_pct = pl.value if pl else 0
            days_held_val = dh.value if dh else (None, "?", False)
            time_status = ts.value if ts else "?"
            is_pre = days_held_val[2] if days_held_val else False
            day_str = days_held_val[1] if days_held_val else "?"
            time_str = f"{day_str} {time_status}" if not is_pre else f"pre {time_status}"
            eg_status = eg.value if eg else "?"
            momentum = mom.value if mom else "?"
            pl_str = f"{pl_pct:+.1f}%" if isinstance(pl_pct, (int, float)) else "?"
            v_style = f"**{verdict}**" if verdict in ("EXIT", "REDUCE", "REVIEW") else verdict
            verdict_rows.append((tk, pl_str, time_str, eg_status, momentum, v_style, rule))

    if verdict_rows:
        print("\n## Position Verdicts\n")
        print("| Ticker | P/L% | Time | Earnings | Momentum | Verdict | Rule |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for row in verdict_rows:
            print(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]} | {row[4]} | {row[5]} | {row[6]} |")

    # Entry Gates — read from graph nodes
    gate_rows = []
    for name, node in sorted(graph.nodes.items()):
        if ":order_" in name and name.endswith(":entry_gate"):
            parts = name.split(":")
            tk = parts[0]
            if isinstance(node.value, tuple) and len(node.value) == 3:
                mg, eg, cg = node.value
                # Find the order price from the compute closure
                idx = int(parts[1].replace("order_", ""))
                pending = graph.nodes.get("live_prices")  # won't work, need portfolio
                # Get order info from portfolio
                portfolio_data = _load()
                orders = portfolio_data.get("pending_orders", {}).get(tk, [])
                active_buys = [o for o in orders if o.get("type") == "BUY"
                               and o.get("placed") and not o.get("filled")]
                if idx < len(active_buys):
                    order = active_buys[idx]
                    label = _extract_label_from_note(order.get("note", ""))
                    gate_rows.append((tk, label, order["price"], mg, eg, cg))

    if gate_rows:
        print("\n## Entry Gates\n")
        print("| Ticker | Order | Price | Market | Earnings | Combined |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for tk, label, price, mg, eg, cg in gate_rows:
            cg_style = f"**{cg}**" if cg in ("PAUSE", "REVIEW") else cg
            print(f"| {tk} | {label} | ${price:.2f} | {mg} | {eg} | {cg_style} |")

    # Sell Projections, Exit Strategy, Same-Day Exits, PDT, Dip Watchlist — UNCHANGED
    try:
        print_sell_projections()
    except Exception as e:
        print(f"\n*Sell projections unavailable: {e}*\n")
    print_exit_strategy_summary()
    print_unfilled_same_day_exits()
    print_pdt_status()
    print_daily_fluctuation_watchlist(regime=regime, graph=graph)

    # Broker Reconciliation — read from graph nodes
    recon_tickers = sorted(
        name.split(":")[0] for name in graph.nodes
        if name.endswith(":recon") and graph.nodes[name].value)
    if recon_tickers:
        print(f"\n## Part 7 — Broker Reconciliation ({len(recon_tickers)} tickers)\n")
        all_recons = []
        for tk in recon_tickers:
            recon = graph.nodes[f"{tk}:recon"].value
            if recon:
                all_recons.append(recon)
                print(format_ticker_report(recon))
        if all_recons:
            print(format_action_summary(all_recons))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _print_neural_sections(portfolio):
    """Print neural network profile sections — both strategies side by side."""
    _ROOT = Path(__file__).resolve().parent.parent

    # Load neural support profiles
    ns_profiles = {}
    try:
        ns_path = _ROOT / "data" / "neural_support_candidates.json"
        if ns_path.exists():
            with open(ns_path) as f:
                ns_data = json.load(f)
            ns_profiles = {c["ticker"]: c for c in ns_data.get("candidates", [])}
    except (json.JSONDecodeError, OSError):
        pass

    # Load neural dip profiles
    dip_profiles = {}
    try:
        dp_path = _ROOT / "data" / "ticker_profiles.json"
        if dp_path.exists():
            with open(dp_path) as f:
                dp_data = json.load(f)
            dip_profiles = {k: v for k, v in dp_data.items() if not k.startswith("_")}
    except (json.JSONDecodeError, OSError):
        pass

    if not ns_profiles and not dip_profiles:
        return

    positions = portfolio.get("positions", {})

    # === Active Positions — Neural vs Default ===
    pos_with_neural = [(tk, pos) for tk, pos in positions.items()
                       if tk in ns_profiles or tk in dip_profiles]
    if pos_with_neural:
        print("\n## Neural Profiles — Active Positions\n")
        print("| Ticker | Avg | Neural Sell | Default Sell | Pool | Bullets | Cat Stop | Tier Full/Std |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for tk, pos in sorted(pos_with_neural):
            avg = pos.get("avg_cost", 0)
            ns = ns_profiles.get(tk, {}).get("params", {})
            neural_sell_pct = ns.get("sell_default")
            neural_sell = f"${avg * (1 + neural_sell_pct/100):.2f} ({neural_sell_pct}%)" if neural_sell_pct else "—"
            default_sell = f"${avg * 1.06:.2f} (6%)"
            neural_pool = f"${ns.get('active_pool', 300)}" if ns else "$300"
            neural_bullets = ns.get("active_bullets_max", 5) if ns else 5
            cat_stop = ns.get("cat_hard_stop")
            cat_str = f"{cat_stop}% | 25%" if cat_stop else "25% | 25%"
            tier_full = ns.get("tier_full")
            tier_std = ns.get("tier_std")
            tier_str = f"{tier_full}%/{tier_std}% | 50%/30%" if tier_full else "50%/30% | 50%/30%"
            print(f"| {tk} | ${avg:.2f} | {neural_sell} | {default_sell} | "
                  f"{neural_pool} | {neural_bullets} | {cat_str} | {tier_str} |")

    # === Neural Support Opportunities (from evaluator cache) ===
    eval_path = _ROOT / "data" / "support_eval_latest.json"
    if eval_path.exists():
        try:
            with open(eval_path) as f:
                eval_data = json.load(f)
            opps = [o for o in eval_data.get("opportunities", [])
                    if not o.get("already_ordered")]
            if opps:
                print(f"\n## Neural Support Opportunities ({eval_data.get('date', '?')})\n")
                print("| Ticker | Price | Support | Distance | Shares | Pool | Sell% | Hold% |")
                print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
                for o in opps[:10]:  # top 10
                    print(f"| {o['ticker']} | ${o['price']:.2f} | ${o['support']:.2f} | "
                          f"{o['distance_pct']}% | {o['shares']} | ${o['pool']} | "
                          f"{o['sell_target_pct']}% | {o.get('hold_rate', 0):.0f}% |")
        except (json.JSONDecodeError, OSError):
            pass

    # === Neural Dip Profiles ===
    watchlist = set(portfolio.get("watchlist", []))
    dip_watchlist = {tk: p for tk, p in dip_profiles.items()
                     if tk in watchlist or tk in positions}
    if dip_watchlist:
        print("\n## Neural Dip Profiles\n")
        print("| Ticker | Dip Thresh | Target | Stop | Breadth | Confidence |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for tk in sorted(dip_watchlist.keys()):
            p = dip_watchlist[tk]
            conf = p.get("confidence", "—")
            breadth = p.get("breadth_threshold")
            breadth_str = f"{breadth:.0%}" if breadth else "—"
            print(f"| {tk} | {p.get('dip_threshold', '?')}% | "
                  f"{p.get('target_pct', '?')}% | {p.get('stop_pct', '?')}% | "
                  f"{breadth_str} | {conf} |")


def print_portfolio_risk(portfolio):
    """Part 8: Portfolio Risk — sector concentration + capital adequacy."""
    positions = portfolio.get("positions", {})
    pending = portfolio.get("pending_orders", {})
    capital = portfolio.get("capital", {})

    # Capital Adequacy
    total_deployed = sum(
        p.get("shares", 0) * p.get("avg_cost", 0)
        for p in positions.values()
        if p.get("shares", 0) > 0 and not p.get("winding_down")
    )
    total_pending = sum(
        o["price"] * o.get("shares", 0)
        for tk_orders in pending.values()
        for o in tk_orders
        if o.get("type") == "BUY" and o.get("placed") and not o.get("filled")
    )
    worst_case = total_deployed + total_pending
    per_stock = capital.get("per_stock_total", 600)
    tracked = set(portfolio.get("watchlist", [])) | set(
        tk for tk, p in positions.items() if p.get("shares", 0) > 0
    )
    n_tracked = len(tracked)
    total_budget = n_tracked * per_stock

    print(f"\n## Part 8 — Portfolio Risk\n")
    print("### Capital Adequacy\n")
    print("| Metric | Amount |")
    print("| :--- | :--- |")
    print(f"| Deployed | ${total_deployed:,.0f} |")
    print(f"| Pending BUYs | ${total_pending:,.0f} |")
    print(f"| Worst Case (all fill) | ${worst_case:,.0f} |")
    print(f"| Budget ({n_tracked} × ${per_stock}) | ${total_budget:,.0f} |")
    surplus = total_budget - worst_case
    status = "✅" if surplus > 0 else "⚠️ DEFICIT"
    print(f"| Surplus/Deficit | ${surplus:+,.0f} {status} |")

    # Sector Concentration
    try:
        from sector_registry import get_sector
        sector_counts = {}
        for tk in tracked:
            sec = get_sector(tk)
            sector_counts.setdefault(sec, []).append(tk)

        concentrated = {s: tks for s, tks in sector_counts.items() if len(tks) >= 3}
        if concentrated:
            print("\n### Sector Concentration\n")
            print("| Sector | Count | Tickers |")
            print("| :--- | :--- | :--- |")
            for sec, tks in sorted(concentrated.items(), key=lambda x: -len(x[1])):
                flag = " ⚠️" if len(tks) >= 5 else ""
                print(f"| {sec}{flag} | {len(tks)} | {', '.join(sorted(tks))} |")
    except ImportError:
        pass

    # Stress Test Summary (if results exist)
    stress_path = _ROOT / "data" / "portfolio_stress_results.json"
    if stress_path.exists():
        try:
            with open(stress_path) as f:
                stress = json.load(f)
            deficits = [s for s in stress.get("scenarios", []) if s.get("deficit", 0) > 0]
            if deficits:
                print("\n### Stress Test Warnings\n")
                for d in deficits:
                    print(f"- **{d['sector']}**: {d['shock_pct']}% drop → "
                          f"${d['capital_needed']:,.0f} needed, "
                          f"${d['available']:,.0f} available → "
                          f"**${d['deficit']:,.0f} deficit**")
        except (json.JSONDecodeError, KeyError):
            pass
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Daily Analyzer — consolidated session tool",
    )
    parser.add_argument(
        "--fills", type=str, default="",
        help='Comma-separated fill specs: "TICKER:PRICE:SHARES,..."',
    )
    parser.add_argument(
        "--sells", type=str, default="",
        help='Comma-separated sell specs: "TICKER:PRICE:SHARES,..."',
    )
    parser.add_argument(
        "--no-deploy", action="store_true",
        help="Skip Parts 3-6 (perf analysis, deployment, fitness, screening)",
    )
    parser.add_argument(
        "--no-recon", action="store_true",
        help="Skip Part 7 (broker reconciliation)",
    )
    parser.add_argument(
        "--no-perf", action="store_true",
        help="Skip Part 3 (performance analysis)",
    )
    parser.add_argument(
        "--no-fitness", action="store_true",
        help="Skip Parts 5-6 (fitness check and screening)",
    )
    parser.add_argument(
        "--no-screen", action="store_true",
        help="Skip Part 6 (new candidate screening)",
    )
    parser.add_argument(
        "--wide-screen", action="store_true",
        help="Use dynamic universe for screening (requires universe_screener.py cache)",
    )
    args = parser.parse_args()

    fills, fill_parse_err = parse_specs(args.fills)
    sells, sell_parse_err = parse_specs(args.sells)
    parse_errors = fill_parse_err + sell_parse_err

    # Part 0: Market Regime (prints immediately — before graph)
    regime, vix, vix_5d_pct = print_market_regime()

    # Part 1: Process transactions (prints immediately — before graph)
    if fills or sells or parse_errors:
        print("## Part 1 — Processing Transactions")
        print()
        process_transactions(fills, sells, parse_errors)

    # Phase A: Fetch all leaf data (batch where possible)
    portfolio = _load()
    active_tickers = _get_active_tickers(portfolio)
    live_prices = _fetch_position_prices(active_tickers)
    tech_data = _fetch_technical_data(active_tickers)
    earnings_data = _batch_earnings(active_tickers)

    # Phase A2: Pre-compute reconciliation (expensive — wick fetches happen here)
    recon_data = {}
    if not args.no_recon:
        recon_data = _run_recon_for_graph(portfolio, active_tickers)

    # Phase B: Build graph, load prev state, resolve, propagate signals
    from graph_builder import build_daily_graph, get_state_for_persistence
    prev_state = _load_graph_state()
    graph = build_daily_graph(portfolio, live_prices, regime, vix, vix_5d_pct,
                              tech_data, earnings_data, recon_data)
    graph.load_prev_state(prev_state)

    try:
        graph.resolve()
        signals = graph.propagate_signals()
    except Exception as e:
        print(f"\n*Graph resolve failed: {e}. Running in status-only mode.*\n")
        print_consolidated_orders()
        print_tier_summary()
        return

    # Phase C: Dashboard FIRST (from signals), then detail sections (from graph.nodes)
    print_action_dashboard_from_signals(signals, graph)
    print_detail_sections(graph, regime)

    # Phase C2: Neural profile sections (supplement graph with learned params)
    _print_neural_sections(portfolio)

    # Phase C3: Neural order adjustment recommendations
    try:
        from neural_order_adjuster import compute_and_print_adjustments
        compute_and_print_adjustments(portfolio)
    except ImportError:
        pass

    # Parts 3-6: Subprocesses (unchanged, outside graph)
    if not args.no_deploy and not args.no_perf:
        if regime != "Risk-Off":
            run_ticker_perf_analysis()
        else:
            print("## Part 3 — Ticker Performance Analysis\n")
            print("*Suppressed: Risk-Off regime — sell target upgrades paused*\n")

    if not args.no_deploy:
        if regime == "Risk-Off":
            print("*CAUTION: Risk-Off regime — consider half-sizing or pausing watchlist entries*\n")
        deploy_tickers = find_deployment_tickers()
        # Get paused tickers from graph catastrophic nodes
        paused = set()
        for tk in active_tickers:
            cat = graph.nodes.get(f"{tk}:catastrophic")
            if cat and cat.value in ("HARD_STOP", "EXIT_REVIEW"):
                paused.add(tk)
        print_deployment_recs(deploy_tickers, paused=paused)

    if not args.no_deploy and not args.no_fitness:
        run_watchlist_fitness()

    if not args.no_deploy and not args.no_fitness and not args.no_screen:
        run_candidate_screening(wide_screen=args.wide_screen)

    # Part 8: Portfolio Risk
    if not args.no_deploy:
        print_portfolio_risk(portfolio)

    # Phase D: Persist canonical state
    state = get_state_for_persistence(graph, active_tickers,
                                       portfolio.get("pending_orders", {}))
    _write_graph_state(state)


if __name__ == "__main__":
    main()
