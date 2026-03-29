"""Neural Dip Evaluator — event-driven decision network for daily dip trades.

Builds per-phase dependency graphs with explicit neurons for every gate.
Cascades through 6 layers: Environment → Market-wide → Per-ticker → Gate → Portfolio → Decision.

Usage:
    python3 tools/neural_dip_evaluator.py --phase first_hour     # 10:30 AM breadth check
    python3 tools/neural_dip_evaluator.py --phase decision        # 11:00 AM buy/no-buy
    python3 tools/neural_dip_evaluator.py --phase eod_check       # 3:45 PM unfilled exits
    python3 tools/neural_dip_evaluator.py --phase decision --dry-run  # no email
"""
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import date, datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yfinance as yf
from graph_engine import DependencyGraph
from trading_calendar import (
    is_trading_day, get_market_phase, market_time_to_utc_hour,
    ET, VALID_PHASES_FOR_MARKET,
)

_ROOT = Path(__file__).resolve().parent.parent
GRAPH_STATE_PATH = _ROOT / "data" / "graph_state.json"
FH_CACHE_PATH = _ROOT / "data" / "neural_fh_cache.json"
HIST_CACHE_PATH = _ROOT / "data" / "neural_hist_ranges_cache.json"

# ---------------------------------------------------------------------------
# Configuration — all thresholds in one place (from plan v2 Section 3.0)
# ---------------------------------------------------------------------------

DIP_CONFIG = {
    "dip_threshold_pct": 1.0,
    "bounce_threshold_pct": 0.3,
    "breadth_threshold": 0.50,
    "range_threshold_pct": 3.0,
    "recovery_threshold_pct": 60.0,
    "budget_normal": 100,
    "budget_risk_off": 50,
    "max_tickers": 5,
    "pdt_limit": 3,
    "capital_min": 100,
}

# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_intraday(tickers, retries=1):
    """Fetch 5-min bars for all tickers. 1 retry, 3s delay."""
    for attempt in range(retries + 1):
        try:
            data = yf.download(tickers, period="1d", interval="5m",
                               progress=False)
            if data.empty:
                if attempt < retries:
                    time.sleep(3)
                    continue
                return None
            if len(tickers) > 1:
                try:
                    available = set(data["Close"].columns)
                    missing = [tk for tk in tickers if tk not in available]
                    if missing:
                        print(f"*Warning: missing tickers: {missing}*")
                except Exception:
                    pass
            return data
        except Exception as e:
            if attempt < retries:
                time.sleep(3)
                continue
            print(f"*Warning: yfinance failed: {e}*")
            return None
    return None


# ---------------------------------------------------------------------------
# Price extraction helpers
# ---------------------------------------------------------------------------

def _extract_col(data, col, tk, n_tickers):
    """Extract column from yfinance MultiIndex DataFrame."""
    if n_tickers > 1:
        return data[(col, tk)].dropna()
    return data[col].dropna()


def _extract_open(data, tk, n_tickers):
    """First bar's open = today's open."""
    try:
        col = _extract_col(data, "Open", tk, n_tickers)
        return round(float(col.iloc[0]), 2) if len(col) > 0 else None
    except (KeyError, IndexError):
        return None


def _extract_price_at(data, tk, et_hour, et_minute, n_tickers):
    """Price at specific ET time (finds closest bar)."""
    try:
        utc_target = market_time_to_utc_hour(et_hour, et_minute)
        col = _extract_col(data, "Close", tk, n_tickers)
        for idx in col.index:
            bar_hour = idx.hour + idx.minute / 60
            if bar_hour >= utc_target:
                return round(float(col.loc[idx]), 2)
        return round(float(col.iloc[-1]), 2) if len(col) > 0 else None
    except (KeyError, IndexError):
        return None


def _extract_first_hour_low(data, tk, n_tickers):
    """Lowest price between 9:30-10:30 ET."""
    try:
        fh_start = market_time_to_utc_hour(9, 30)
        fh_end = market_time_to_utc_hour(10, 30)
        col = _extract_col(data, "Low", tk, n_tickers)
        mask = [(idx.hour + idx.minute / 60 >= fh_start and
                 idx.hour + idx.minute / 60 < fh_end) for idx in col.index]
        fh_bars = col[mask]
        return round(float(fh_bars.min()), 2) if len(fh_bars) > 0 else None
    except (KeyError, IndexError):
        return None


def _extract_latest(data, tk, n_tickers):
    """Most recent bar's close."""
    try:
        col = _extract_col(data, "Close", tk, n_tickers)
        return round(float(col.iloc[-1]), 2) if len(col) > 0 else None
    except (KeyError, IndexError):
        return None


# ---------------------------------------------------------------------------
# Static context (graph_state.json + fallback)
# ---------------------------------------------------------------------------

def load_static_context(tickers):
    """Load regime, verdicts, catastrophic from graph_state.json.
    Falls back to live computation if missing/stale."""
    state = {}
    if GRAPH_STATE_PATH.exists():
        try:
            with open(GRAPH_STATE_PATH) as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    regime = state.get("regime")
    vix = state.get("vix")
    tickers_state = state.get("tickers", {})

    # Fallback: compute regime from live data if missing
    if regime is None:
        try:
            from shared_regime import fetch_regime_detail
            info = fetch_regime_detail()
            regime = info.get("regime", "Neutral")
            vix = info.get("vix")
        except Exception:
            regime = "Neutral"

    static = {}
    for tk in tickers:
        ts = tickers_state.get(tk, {})
        catastrophic = ts.get("catastrophic")
        verdict = ts.get("verdict", ["UNKNOWN"])
        dip_viable = ts.get("dip_viable", "UNKNOWN")
        earnings_gate = ts.get("earnings_gate")

        # Fallback: compute earnings if missing
        if earnings_gate is None:
            try:
                from earnings_gate import check_earnings_gate
                gate = check_earnings_gate(tk)
                earnings_gate = gate.get("status", "CLEAR")
            except Exception:
                earnings_gate = "CLEAR"

        static[tk] = {
            "verdict": verdict,
            "catastrophic": catastrophic,
            "dip_viable": dip_viable,
            "earnings_gate": earnings_gate,
        }

    return regime, vix, static


# ---------------------------------------------------------------------------
# Historical range computation (with caching)
# ---------------------------------------------------------------------------

def compute_historical_ranges(tickers):
    """Compute 1-month range + recovery stats per ticker.
    Cached to disk (4-hour TTL) to avoid re-downloading across phases.
    """
    # Check cache
    if HIST_CACHE_PATH.exists():
        cache_age = time.time() - HIST_CACHE_PATH.stat().st_mtime
        if cache_age < 14400:  # <4 hours
            try:
                with open(HIST_CACHE_PATH) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

    # Compute fresh
    result = {}
    try:
        data = yf.download(tickers, period="1mo", interval="1d", progress=False)
    except Exception:
        result = {tk: {"range_pct": 0, "recovery_pct": 0, "viable": False}
                  for tk in tickers}
        return result

    n = len(tickers)
    for tk in tickers:
        try:
            highs = _extract_col(data, "High", tk, n).values
            lows = _extract_col(data, "Low", tk, n).values
            if len(highs) < 5 or len(lows) < 5:
                result[tk] = {"range_pct": 0, "recovery_pct": 0, "viable": False}
                continue
            daily_range = (highs - lows) / lows * 100
            med_range = float(round(float(daily_range.mean()), 1))
            low_to_high = (highs - lows) / lows * 100
            recovery_days = int((low_to_high >= 3.0).sum())
            recovery_pct = round(recovery_days / len(low_to_high) * 100)
            cfg = DIP_CONFIG
            result[tk] = {
                "range_pct": med_range,
                "recovery_pct": recovery_pct,
                "viable": (med_range >= cfg["range_threshold_pct"]
                           and recovery_pct >= cfg["recovery_threshold_pct"]),
            }
        except Exception:
            result[tk] = {"range_pct": 0, "recovery_pct": 0, "viable": False}

    # Save cache
    try:
        HIST_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(HIST_CACHE_PATH, "w") as f:
            json.dump(result, f, indent=2)
    except OSError:
        pass

    return result


# ---------------------------------------------------------------------------
# Graph builders (per plan v2 Section 3.4-3.5)
# ---------------------------------------------------------------------------

def build_first_hour_graph(tickers, prices, static, hist_ranges, regime):
    """Build first-hour graph: per-ticker dip detection + breadth aggregation.
    All static neurons are explicit graph nodes with reason_fn.
    """
    graph = DependencyGraph()
    cfg = DIP_CONFIG
    n = len(tickers)

    graph.add_node("regime", compute=lambda _: regime,
        reason_fn=lambda old, new, _: f"Regime: {new}")

    dip_count = 0
    for tk in tickers:
        o = _extract_open(prices, tk, n)
        c = _extract_price_at(prices, tk, 10, 30, n)
        dip_pct = round((o - c) / o * 100, 1) if o and c and o > 0 else 0
        dipped = dip_pct >= cfg["dip_threshold_pct"]
        if dipped:
            dip_count += 1

        st = static.get(tk, {})
        hr = hist_ranges.get(tk, {})
        cat = st.get("catastrophic")
        verdict = st.get("verdict", ["UNKNOWN"])
        v0 = verdict[0] if isinstance(verdict, list) else verdict
        eg = st.get("earnings_gate", "CLEAR")
        viable = st.get("dip_viable", "UNKNOWN")

        # Layer 3: ALL neurons as graph nodes
        graph.add_node(f"{tk}:dipped", compute=lambda _, d=dipped: d,
            reason_fn=lambda old, new, _, pct=dip_pct:
                f"Dipped {pct:.1f}%" if new else f"No dip ({pct:.1f}%)")
        graph.add_node(f"{tk}:dip_viable", compute=lambda _, v=viable: v in ("YES", "CAUTION", "UNKNOWN"),
            reason_fn=lambda old, new, _, v=viable: f"DIP_VIABLE={v}")
        graph.add_node(f"{tk}:not_catastrophic", compute=lambda _, c=cat: c not in ("HARD_STOP", "EXIT_REVIEW"),
            reason_fn=lambda old, new, _, c=cat: "Clear" if new else f"BLOCKED:{c}")
        graph.add_node(f"{tk}:not_exit", compute=lambda _, v=v0: v not in ("EXIT", "REDUCE"),
            reason_fn=lambda old, new, _, v=v0: "Clear" if new else f"BLOCKED:verdict={v}")
        graph.add_node(f"{tk}:earnings_clear", compute=lambda _, e=eg: e not in ("BLOCKED", "FALLING_KNIFE"),
            reason_fn=lambda old, new, _, e=eg: "Clear" if new else f"BLOCKED:earnings={e}")
        graph.add_node(f"{tk}:historical_range", compute=lambda _, h=hr: h.get("viable", False),
            reason_fn=lambda old, new, _, h=hr:
                f"Range {h.get('range_pct',0)}% rec {h.get('recovery_pct',0)}%" if new
                else f"BLOCKED:range={h.get('range_pct',0)}%")

    # Layer 2: Breadth
    breadth_ratio = dip_count / n if n > 0 else 0
    graph.add_node("breadth_dip",
        compute=lambda _: breadth_ratio >= cfg["breadth_threshold"],
        reason_fn=lambda old, new, _:
            f"Breadth {dip_count}/{n}={breadth_ratio:.0%} {'FIRED' if new else 'NOT FIRED'}")

    graph.resolve()

    # Build state dict with extra per-ticker data for decision phase
    fh_state = graph.get_state()
    for tk in tickers:
        fh_state[f"{tk}:first_hour_low"] = _extract_first_hour_low(prices, tk, n)
        o = _extract_open(prices, tk, n)
        c = _extract_price_at(prices, tk, 10, 30, n)
        fh_state[f"{tk}:dip_pct"] = round((o - c) / o * 100, 1) if o and c and o > 0 else 0

    return graph, fh_state


def build_decision_graph(tickers, prices_11, fh_state, static, hist_ranges, regime):
    """Build decision graph: bounce + CANDIDATE AND-gate + RANKER + BUY_DIP.
    All neurons explicit with reason_fn for full trace.
    """
    graph = DependencyGraph()
    cfg = DIP_CONFIG
    n = len(tickers)

    breadth_dip_fired = fh_state.get("breadth_dip", False)

    bounce_count = 0
    candidates = []

    for tk in tickers:
        fh_low = fh_state.get(f"{tk}:first_hour_low")
        current = _extract_latest(prices_11, tk, n)
        bounce_pct = round((current - fh_low) / fh_low * 100, 1) if fh_low and current and fh_low > 0 else 0
        bounced = bounce_pct >= cfg["bounce_threshold_pct"]
        if bounced:
            bounce_count += 1

        dipped = fh_state.get(f"{tk}:dipped", False)
        st = static.get(tk, {})
        hr = hist_ranges.get(tk, {})
        cat = st.get("catastrophic")
        verdict = st.get("verdict", ["UNKNOWN"])
        v0 = verdict[0] if isinstance(verdict, list) else verdict
        eg = st.get("earnings_gate", "CLEAR")
        viable = st.get("dip_viable", "UNKNOWN")

        # Layer 3: All neurons
        graph.add_node(f"{tk}:dipped", compute=lambda _, d=dipped: d,
            reason_fn=lambda old, new, _: "Dipped" if new else "No dip")
        graph.add_node(f"{tk}:bounced", compute=lambda _, b=bounced: b,
            reason_fn=lambda old, new, _, pct=bounce_pct:
                f"Bounced {pct:.1f}%" if new else f"No bounce ({pct:.1f}%)")
        graph.add_node(f"{tk}:dip_viable", compute=lambda _, v=viable: v in ("YES", "CAUTION", "UNKNOWN"),
            reason_fn=lambda old, new, _, v=viable: f"DIP_VIABLE={v}")
        graph.add_node(f"{tk}:not_catastrophic", compute=lambda _, c=cat: c not in ("HARD_STOP", "EXIT_REVIEW"),
            reason_fn=lambda old, new, _, c=cat: "Clear" if new else f"BLOCKED:{c}")
        graph.add_node(f"{tk}:not_exit", compute=lambda _, v=v0: v not in ("EXIT", "REDUCE"),
            reason_fn=lambda old, new, _, v=v0: "Clear" if new else f"BLOCKED:verdict={v}")
        graph.add_node(f"{tk}:earnings_clear", compute=lambda _, e=eg: e not in ("BLOCKED", "FALLING_KNIFE"),
            reason_fn=lambda old, new, _, e=eg: "Clear" if new else f"BLOCKED:earnings={e}")
        graph.add_node(f"{tk}:historical_range", compute=lambda _, h=hr: h.get("viable", False),
            reason_fn=lambda old, new, _, h=hr: "Range OK" if new else f"BLOCKED:range")

        # Layer 4: CANDIDATE — AND gate
        is_candidate = all([dipped, bounced,
                            viable in ("YES", "CAUTION", "UNKNOWN"),
                            cat not in ("HARD_STOP", "EXIT_REVIEW"),
                            v0 not in ("EXIT", "REDUCE"),
                            eg not in ("BLOCKED", "FALLING_KNIFE"),
                            hr.get("viable", False)])

        graph.add_node(f"{tk}:candidate", compute=lambda _, c=is_candidate: c,
            depends_on=[f"{tk}:dipped", f"{tk}:bounced", f"{tk}:dip_viable",
                        f"{tk}:not_catastrophic", f"{tk}:not_exit",
                        f"{tk}:earnings_clear", f"{tk}:historical_range"],
            reason_fn=lambda old, new, _:
                "ALL 7 gates passed" if new else "Blocked — see child neurons")

        if is_candidate:
            dip_pct = fh_state.get(f"{tk}:dip_pct", 0)
            candidates.append({
                "ticker": tk, "dip_pct": dip_pct,
                "entry": round(current, 2) if current else 0,
                "target": round(current * 1.04, 2) if current else 0,
                "stop": round(current * 0.97, 2) if current else 0,
            })

    # Layer 2: Breadth bounce + signal confirmed
    breadth_bounce_ratio = bounce_count / n if n > 0 else 0
    breadth_bounce_fired = breadth_bounce_ratio >= cfg["breadth_threshold"]
    signal_confirmed = breadth_dip_fired and breadth_bounce_fired

    graph.add_node("breadth_bounce", compute=lambda _: breadth_bounce_fired,
        reason_fn=lambda old, new, _:
            f"Bounce {bounce_count}/{n}={breadth_bounce_ratio:.0%} {'FIRED' if new else 'NOT FIRED'}")
    graph.add_node("signal_confirmed", compute=lambda _: signal_confirmed,
        depends_on=["breadth_bounce"],
        reason_fn=lambda old, new, _:
            "CONFIRMED" if new else "NOT CONFIRMED")

    # Layer 5: Portfolio constraints
    pdt_count = _count_pdt_trades()
    pdt_ok = pdt_count < cfg["pdt_limit"]
    capital = _get_dip_capital()
    capital_ok = capital >= cfg["capital_min"]

    graph.add_node("pdt_available", compute=lambda _: pdt_ok,
        reason_fn=lambda old, new, _: f"PDT {pdt_count}/{cfg['pdt_limit']}")
    graph.add_node("capital_available", compute=lambda _: capital_ok,
        reason_fn=lambda old, new, _: f"Capital ${capital:.0f}")

    # Rank candidates
    candidates.sort(key=lambda c: c["dip_pct"], reverse=True)
    top = candidates[:cfg["max_tickers"]]

    # Layer 6: Terminal BUY_DIP neurons
    budget = cfg["budget_normal"] if regime != "Risk-Off" else cfg["budget_risk_off"]

    for c in top:
        tk = c["ticker"]
        graph.add_node(f"{tk}:buy_dip",
            compute=lambda _, conf=signal_confirmed, pdt=pdt_ok, cap=capital_ok: conf and pdt and cap,
            depends_on=["signal_confirmed", "pdt_available", "capital_available", f"{tk}:candidate"],
            is_report=True,
            reason_fn=lambda old, new, _: "BUY" if new else "NO ACTION")

    # NO_ACTION neuron
    no_buys = not (signal_confirmed and pdt_ok and capital_ok and top)
    graph.add_node("no_action", compute=lambda _: no_buys, is_report=True,
        reason_fn=lambda old, new, _: "No dip play today" if new else "")

    graph.resolve()
    return graph, top, budget


# ---------------------------------------------------------------------------
# Portfolio helpers
# ---------------------------------------------------------------------------

def _load_portfolio():
    with open(_ROOT / "portfolio.json") as f:
        return json.load(f)


def _get_dip_candidates(portfolio):
    """Tickers eligible for dip evaluation: positions + watchlist with pending buys."""
    positions = portfolio.get("positions", {})
    watchlist = portfolio.get("watchlist", [])
    pending = portfolio.get("pending_orders", {})
    tickers = set()
    for tk, pos in positions.items():
        if pos.get("shares", 0) > 0:
            tickers.add(tk)
    for tk in watchlist:
        if any(o.get("type") == "BUY" for o in pending.get(tk, [])):
            tickers.add(tk)
    return sorted(tickers)


def _count_pdt_trades():
    """Count same-day exits in last 5 trading days."""
    try:
        with open(_ROOT / "trade_history.json") as f:
            trades = json.load(f).get("trades", [])
        cutoff = (date.today() - timedelta(days=7)).isoformat()
        return sum(1 for t in trades
                   if t.get("date", "") >= cutoff
                   and t.get("exit_reason") == "SAME_DAY_EXIT")
    except Exception:
        return 0


def _get_dip_capital():
    """Return available dip budget."""
    try:
        portfolio = _load_portfolio()
        return portfolio.get("capital", {}).get("dip_pool", 500)
    except Exception:
        return 500


# ---------------------------------------------------------------------------
# Phase evaluation functions
# ---------------------------------------------------------------------------

def evaluate_first_hour(tickers, static, hist_ranges, regime):
    """10:30 AM: First-hour breadth check. Cache results for decision phase."""
    prices = fetch_intraday(tickers)
    if prices is None:
        print("*yfinance unavailable. Skipping first_hour.*")
        return

    graph, fh_state = build_first_hour_graph(tickers, prices, static, hist_ranges, regime)

    # Cache for decision phase
    try:
        FH_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(FH_CACHE_PATH, "w") as f:
            json.dump(fh_state, f, default=str)
    except OSError as e:
        print(f"*Warning: failed to cache first-hour state: {e}*")

    dip_count = sum(1 for tk in tickers if fh_state.get(f"{tk}:dipped"))
    breadth = fh_state.get("breadth_dip", False)
    print(f"First-hour: {dip_count}/{len(tickers)} dipped. "
          f"Breadth {'FIRED' if breadth else 'NOT FIRED'}.")


def evaluate_decision(tickers, static, hist_ranges, regime, dry_run=False):
    """11:00 AM: Full decision — load first-hour cache + bounce + decide."""
    # Load cached first-hour state
    fh_state = {}
    if FH_CACHE_PATH.exists():
        try:
            with open(FH_CACHE_PATH) as f:
                fh_state = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    if not fh_state:
        # Fallback: compute first-hour from current data
        print("*No first-hour cache. Computing from current data.*")
        prices = fetch_intraday(tickers)
        if prices is None:
            print("*yfinance unavailable. Skipping.*")
            return
        _, fh_state = build_first_hour_graph(tickers, prices, static, hist_ranges, regime)

    if not fh_state.get("breadth_dip"):
        print("Breadth dip NOT FIRED. No dip play today.")
        return

    # Fetch 11:00 prices
    prices_11 = fetch_intraday(tickers)
    if prices_11 is None:
        print("*yfinance unavailable at decision time. Skipping.*")
        return

    decision_graph, top, budget = build_decision_graph(
        tickers, prices_11, fh_state, static, hist_ranges, regime)

    # Check fired BUY_DIP neurons
    activated = decision_graph.get_activated_reports()
    buy_signals = [(name, node) for name, node in activated
                   if name.endswith(":buy_dip") and node.value]

    if not buy_signals:
        print("No dip play today — signal or candidates blocked.")
        # Show why each ticker was blocked
        for tk in tickers:
            cand = decision_graph.nodes.get(f"{tk}:candidate")
            if cand and not cand.value:
                blocked = []
                for dep_name in (cand.depends_on or []):
                    dep = decision_graph.nodes.get(dep_name)
                    if dep and not dep.value and dep.reason_fn:
                        blocked.append(dep.reason_fn(None, dep.value, []))
                if blocked:
                    print(f"  {tk}: {', '.join(blocked)}")
        return

    # Output buy signals
    print(f"\n## Neural Dip Evaluator — {len(buy_signals)} BUY signal(s)\n")
    for name, node in buy_signals:
        tk = name.split(":")[0]
        candidate = next((c for c in top if c["ticker"] == tk), None)
        if not candidate:
            continue

        reason = node.signals[0].flat_reason() if node.signals else "No chain"
        node_path = node.signals[0].node_path_str() if node.signals else ""

        print(f"### {tk}: BUY at ${candidate['entry']:.2f}")
        print(f"- Target: ${candidate['target']:.2f} (+4%)")
        print(f"- Stop: ${candidate['stop']:.2f} (-3%)")
        print(f"- Budget: ${budget}")
        print(f"- Regime: {regime}")
        print(f"- Path: {node_path}")
        print(f"- Reason: {reason}")
        print()

        if not dry_run:
            from notify import send_dip_alert
            send_dip_alert(tk, candidate["entry"], candidate["target"],
                          candidate["stop"], f"{node_path}\n{reason}",
                          regime, budget)


def evaluate_eod(tickers):
    """3:45 PM: Check for unfilled same-day dip sells."""
    try:
        portfolio = _load_portfolio()
    except Exception:
        print("*Cannot load portfolio for EOD check.*")
        return

    pending = portfolio.get("pending_orders", {})
    unfilled = []
    for tk in tickers:
        for order in pending.get(tk, []):
            if (order.get("type") == "SELL" and
                    "same-day" in order.get("note", "").lower()):
                unfilled.append((tk, order["price"], order.get("shares", 0)))

    if unfilled:
        print(f"\n## EOD Check — {len(unfilled)} unfilled same-day exit(s)\n")
        for tk, price, shares in unfilled:
            print(f"- {tk}: SELL @ ${price:.2f} x {shares} — consider manual close or hold")
    else:
        print("EOD: No unfilled same-day exits.")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Neural Dip Evaluator")
    parser.add_argument("--phase", choices=["first_hour", "decision", "eod_check"],
                        default="decision")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print results but don't send email")
    args = parser.parse_args()

    # Gate: trading day
    if not is_trading_day():
        print(f"Market closed ({date.today()}). Skipping.")
        return

    # Gate: market phase validation
    actual_phase = get_market_phase()
    valid = VALID_PHASES_FOR_MARKET.get(args.phase, ())
    if actual_phase not in valid and actual_phase != "CLOSED":
        print(f"*Phase mismatch: requested {args.phase}, market is {actual_phase}. "
              f"Expected: {valid}. Proceeding anyway.*")

    # Load context
    portfolio = _load_portfolio()
    tickers = _get_dip_candidates(portfolio)
    if not tickers:
        print("No dip candidates (no positions or watchlist tickers).")
        return

    regime, vix, static = load_static_context(tickers)
    hist_ranges = compute_historical_ranges(tickers)

    print(f"Neural Dip Evaluator — {args.phase} | {len(tickers)} tickers | "
          f"Regime: {regime} | {datetime.now(ET).strftime('%H:%M ET')}")

    if args.phase == "first_hour":
        evaluate_first_hour(tickers, static, hist_ranges, regime)
    elif args.phase == "decision":
        evaluate_decision(tickers, static, hist_ranges, regime, args.dry_run)
    elif args.phase == "eod_check":
        evaluate_eod(tickers)


if __name__ == "__main__":
    main()
