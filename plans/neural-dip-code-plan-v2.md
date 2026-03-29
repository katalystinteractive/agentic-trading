# Code Plan v2: Neural Dip Evaluator (Revised)

**Date**: 2026-03-29 (Sunday)
**Supersedes**: `plans/neural-dip-code-plan.md` (v1 — 17 gaps found in verification)
**Source**: `plans/neural-requirements-analysis.md` (verified requirements)
**Reference**: `plans/neural-graph-analysis.md` (6-layer neural design)

This plan addresses all 17 gaps found in v1 verification. Key changes:
- All Layer 3 static neurons are explicit graph nodes (not inline checks)
- HISTORICAL_RANGE neuron implemented
- All referenced functions defined
- Backtester complete (not skeleton)
- Config dict for thresholds
- Phase validation (cron phase matches market time)
- First-hour state cached to disk between phases
- NO_ACTION neuron with blocked-ticker reasons

---

## Phase 1: Shared Infrastructure (~55 lines)

### 1.1 `trading_calendar.py` additions (~55 lines)

Add to existing file:

```python
import pytz
from datetime import datetime

ET = pytz.timezone("US/Eastern")
MARKET_OPEN_ET = (9, 30)
MARKET_CLOSE_ET = (16, 0)

_EARLY_CLOSES = {
    date(2025, 11, 28): (13, 0),  # Day after Thanksgiving
    date(2025, 12, 24): (13, 0),  # Christmas Eve
    date(2026, 11, 27): (13, 0),
    date(2026, 12, 24): (13, 0),
    date(2027, 11, 26): (13, 0),
    date(2027, 12, 24): (13, 0),
}

def market_close_time(d=None):
    """Return (hour, minute) close time for given day."""
    d = d or date.today()
    return _EARLY_CLOSES.get(d, MARKET_CLOSE_ET)

def get_market_phase():
    """Return current market phase based on ET time.
    Returns: CLOSED, PRE_MARKET, FIRST_HOUR, CONFIRMATION, REGULAR, AFTER_HOURS
    """
    now = datetime.now(ET)
    d = now.date()
    if not is_trading_day(d):
        return "CLOSED"
    h, m = now.hour, now.minute
    close_h, close_m = market_close_time(d)
    if h < 9 or (h == 9 and m < 30):
        return "PRE_MARKET"
    elif (h == 9 and m >= 30) or (h == 10 and m < 30):
        return "FIRST_HOUR"
    elif h == 10 and m >= 30:
        return "CONFIRMATION"
    elif h < close_h or (h == close_h and m < close_m):
        return "REGULAR"
    else:
        return "AFTER_HOURS"

def market_time_to_utc_hour(et_hour, et_minute=0):
    """Convert ET time to UTC fractional hour (handles EDT/EST)."""
    now_et = datetime.now(ET)
    market_time = now_et.replace(hour=et_hour, minute=et_minute, second=0)
    market_utc = market_time.astimezone(pytz.utc)
    return market_utc.hour + market_utc.minute / 60

# Expected phases per evaluator --phase argument
VALID_PHASES_FOR_MARKET = {
    "first_hour": ("FIRST_HOUR", "CONFIRMATION"),  # 10:30 may land in either
    "decision": ("CONFIRMATION", "REGULAR"),
    "eod_check": ("REGULAR",),
}
```

---

## Phase 2: Notification Engine (~45 lines)

### 2.1 `tools/notify.py` (NEW)

Same as v1 plan with the verification fix: check response.status_code, read all 3 env vars, handle missing gracefully. Also add a `--test` mode.

```python
"""Email notification for neural dip evaluator."""
import os
from datetime import datetime

def send_dip_alert(ticker, entry_price, target, stop, reason_chain,
                   regime, budget):
    """Send email when BUY_DIP neuron fires. Returns True on success."""
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
    except ImportError:
        print("*Warning: sendgrid not installed. pip install sendgrid*")
        return False

    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.environ.get("SENDGRID_API_KEY")
    recipient = os.environ.get("ALERT_EMAIL")
    sender = os.environ.get("SENDGRID_FROM_EMAIL")

    if not all([api_key, recipient, sender]):
        missing = [v for v, val in [("SENDGRID_API_KEY", api_key),
                   ("ALERT_EMAIL", recipient), ("SENDGRID_FROM_EMAIL", sender)]
                   if not val]
        print(f"*Warning: missing env vars: {missing}. Skipping email.*")
        return False

    subject = f"DIP ALERT: BUY {ticker} at ${entry_price:.2f}"
    body = (f"Ticker: {ticker}\n"
            f"Entry:  ${entry_price:.2f}\n"
            f"Target: ${target:.2f} (+4%)\n"
            f"Stop:   ${stop:.2f} (-3%)\n"
            f"Budget: ${budget:.0f}\n"
            f"Regime: {regime}\n\n"
            f"REASON CHAIN:\n{reason_chain}\n\n"
            f"-- Neural Dip Evaluator at "
            f"{datetime.now().strftime('%H:%M:%S ET %Y-%m-%d')}")

    message = Mail(from_email=sender, to_emails=recipient,
                   subject=subject, plain_text_content=body)
    try:
        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        if response.status_code not in (200, 202):
            print(f"*Warning: SendGrid returned {response.status_code}*")
            return False
        print(f"Email sent to {recipient}: {subject}")
        return True
    except Exception as e:
        print(f"*Warning: email send failed: {e}*")
        return False


if __name__ == "__main__":
    # Test mode: send a test email
    success = send_dip_alert("TEST", 10.00, 10.40, 9.70,
                             "This is a test firing chain", "Neutral", 100)
    print(f"Test email: {'sent' if success else 'FAILED'}")
```

---

## Phase 3: Core Neural Dip Evaluator (~500 lines)

### 3.0 Configuration (not hardcoded)

```python
# At module top — ensure tools/ is in path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

DIP_CONFIG = {
    "dip_threshold_pct": 1.0,        # min first-hour dip from open
    "bounce_threshold_pct": 0.3,     # min second-hour bounce
    "breadth_threshold": 0.50,       # min fraction of tickers dipped/bounced
    "range_threshold_pct": 3.0,      # min daily range (historical)
    "recovery_threshold_pct": 60.0,  # min recovery rate (historical)
    "budget_normal": 100,            # $ per trade in non-Risk-Off
    "budget_risk_off": 50,           # $ per trade in Risk-Off
    "max_tickers": 5,                # top N candidates
    "pdt_limit": 3,                  # max day trades per 5-day window
    "capital_min": 100,              # min dip budget to proceed
}
```

### 3.1 Data Fetching (with retry + partial detection)

```python
def fetch_intraday(tickers, retries=1):
    """Fetch 5-min bars for all tickers. 1 retry, 3s delay."""
    for attempt in range(retries + 1):
        try:
            data = yf.download(tickers, period="1d", interval="5m", progress=False)
            if data.empty:
                if attempt < retries:
                    time.sleep(3)
                    continue
                return None
            # Detect partial data
            if len(tickers) > 1:
                available = set(data["Close"].columns)
                missing = [tk for tk in tickers if tk not in available]
                if missing:
                    print(f"*Warning: missing tickers: {missing}*")
            return data
        except Exception as e:
            if attempt < retries:
                time.sleep(3)
                continue
            print(f"*Warning: yfinance failed: {e}*")
            return None
    return None
```

### 3.2 Static Context Loading (with fallback computation)

```python
def load_static_context(tickers):
    """Load static neurons from graph_state.json. Fallback to live computation."""
    from dotenv import load_dotenv
    load_dotenv()

    state = {}
    if GRAPH_STATE_PATH.exists():
        try:
            with open(GRAPH_STATE_PATH) as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    regime = state.get("regime", None)
    vix = state.get("vix")
    tickers_state = state.get("tickers", {})

    # Fallback: compute regime from live data if missing
    if regime is None:
        try:
            from shared_regime import fetch_regime_detail
            regime_info = fetch_regime_detail()
            regime = regime_info.get("regime", "Neutral")
            vix = regime_info.get("vix")
        except Exception:
            regime = "Neutral"

    # Per-ticker static neurons
    static = {}
    for tk in tickers:
        ts = tickers_state.get(tk, {})
        catastrophic = ts.get("catastrophic")
        verdict = ts.get("verdict", ["UNKNOWN"])
        dip_viable = ts.get("dip_viable", "UNKNOWN")
        earnings_gate = ts.get("earnings_gate")

        # Fallback: compute earnings gate if missing
        if earnings_gate is None:
            try:
                from earnings_gate import check_earnings_gate
                gate = check_earnings_gate(tk)
                earnings_gate = gate.get("status", "CLEAR")
            except Exception:
                earnings_gate = "CLEAR"

        # Fallback: compute catastrophic from live price if missing
        if catastrophic is None and ts.get("avg_cost") and ts.get("avg_cost") > 0:
            pl_pct = ts.get("pl_pct", 0)
            if pl_pct and pl_pct <= -25:
                catastrophic = "HARD_STOP"
            elif pl_pct and pl_pct <= -15:
                catastrophic = "WARNING"

        static[tk] = {
            "verdict": verdict,
            "catastrophic": catastrophic,
            "dip_viable": dip_viable,
            "earnings_gate": earnings_gate,
        }

    return regime, vix, static
```

### 3.3 Historical Range Computation

```python
def compute_historical_ranges(tickers):
    """Compute 1-month range and recovery stats per ticker.
    Returns {ticker: {range_pct, recovery_pct, viable}}.
    """
    try:
        data = yf.download(tickers, period="1mo", interval="1d", progress=False)
    except Exception:
        return {tk: {"range_pct": 0, "recovery_pct": 0, "viable": False}
                for tk in tickers}

    result = {}
    for tk in tickers:
        try:
            if len(tickers) > 1:
                highs = data[("High", tk)].dropna()
                lows = data[("Low", tk)].dropna()
                closes = data[("Close", tk)].dropna()
            else:
                highs = data["High"].dropna()
                lows = data["Low"].dropna()
                closes = data["Close"].dropna()

            daily_range = ((highs - lows) / lows * 100)
            med_range = float(daily_range.median())
            low_to_high = ((highs - lows) / lows * 100)
            recovery_days = int((low_to_high >= 3.0).sum())
            recovery_pct = round(recovery_days / len(low_to_high) * 100) if len(low_to_high) > 0 else 0

            result[tk] = {
                "range_pct": round(med_range, 1),
                "recovery_pct": recovery_pct,
                "viable": med_range >= DIP_CONFIG["range_threshold_pct"]
                          and recovery_pct >= DIP_CONFIG["recovery_threshold_pct"],
            }
        except Exception:
            result[tk] = {"range_pct": 0, "recovery_pct": 0, "viable": False}

    return result
```

### 3.4 First-Hour Graph (10:30 AM) — ALL neurons as graph nodes

```python
def build_first_hour_graph(tickers, prices_data, static, hist_ranges, regime):
    """Build first-hour graph with explicit neurons for every gate.

    Neurons per ticker (all as graph nodes with reason_fn):
      {tk}:open, {tk}:price_10_30, {tk}:dipped,
      {tk}:dip_viable, {tk}:not_catastrophic, {tk}:earnings_clear,
      {tk}:historical_range

    Market-wide:
      regime, breadth_dip
    """
    graph = DependencyGraph()
    cfg = DIP_CONFIG

    graph.add_node("regime", compute=lambda _: regime,
        reason_fn=lambda old, new, _: f"Regime: {new}")

    dip_count = 0
    for tk in tickers:
        o = _extract_open(prices_data, tk)
        c = _extract_price_at(prices_data, tk, "10:30")
        dip_pct = round((o - c) / o * 100, 1) if o and c and o > 0 else 0
        dipped = dip_pct >= cfg["dip_threshold_pct"]
        if dipped:
            dip_count += 1

        st = static.get(tk, {})
        hr = hist_ranges.get(tk, {})

        # Layer 3: ALL static neurons as explicit graph nodes
        graph.add_node(f"{tk}:open", compute=lambda _, v=o: v)
        graph.add_node(f"{tk}:price_10_30", compute=lambda _, v=c: v)
        graph.add_node(f"{tk}:dip_pct", compute=lambda _, v=dip_pct: v)

        graph.add_node(f"{tk}:dipped",
            compute=lambda _, d=dipped: d,
            depends_on=[f"{tk}:dip_pct"],
            reason_fn=lambda old, new, _, pct=dip_pct:
                f"Dipped {pct:.1f}% from open" if new else f"No dip ({pct:.1f}%)")

        graph.add_node(f"{tk}:dip_viable",
            compute=lambda _, v=st.get("dip_viable", "UNKNOWN"): v,
            reason_fn=lambda old, new, _:
                f"DIP_VIABLE: {new}")

        cat = st.get("catastrophic")
        graph.add_node(f"{tk}:not_catastrophic",
            compute=lambda _, c=cat: c not in ("HARD_STOP", "EXIT_REVIEW"),
            reason_fn=lambda old, new, _, c=cat:
                "Clear" if new else f"BLOCKED: {c}")

        verdict = st.get("verdict", ["UNKNOWN"])
        v0 = verdict[0] if isinstance(verdict, list) else verdict
        graph.add_node(f"{tk}:not_exit",
            compute=lambda _, v=v0: v not in ("EXIT", "REDUCE"),
            reason_fn=lambda old, new, _, v=v0:
                "Clear" if new else f"BLOCKED: verdict={v}")

        eg = st.get("earnings_gate", "CLEAR")
        graph.add_node(f"{tk}:earnings_clear",
            compute=lambda _, e=eg: e not in ("BLOCKED", "FALLING_KNIFE"),
            reason_fn=lambda old, new, _, e=eg:
                "Clear" if new else f"BLOCKED: earnings={e}")

        graph.add_node(f"{tk}:historical_range",
            compute=lambda _, h=hr: h.get("viable", False),
            reason_fn=lambda old, new, _, h=hr:
                f"Range {h.get('range_pct',0)}%, recovery {h.get('recovery_pct',0)}%"
                if new else f"BLOCKED: range {h.get('range_pct',0)}%")

    # Layer 2: Breadth
    breadth_ratio = dip_count / len(tickers) if tickers else 0
    graph.add_node("breadth_dip",
        compute=lambda _: breadth_ratio >= cfg["breadth_threshold"],
        reason_fn=lambda old, new, _:
            f"Breadth: {dip_count}/{len(tickers)} = {breadth_ratio:.0%}"
            + (" FIRED" if new else " NOT FIRED"))

    graph.resolve()

    # Save first-hour low per ticker for bounce detection
    fh_state = graph.get_state()
    for tk in tickers:
        fh_state[f"{tk}:first_hour_low"] = _extract_first_hour_low(prices_data, tk)
        fh_state[f"{tk}:dip_pct"] = _extract_dip_pct(prices_data, tk)

    return graph, fh_state
```

### 3.5 Decision Graph (11:00 AM) — CANDIDATE AND-gate + RANKER + BUY_DIP

```python
def build_decision_graph(tickers, prices_11, fh_state, static, hist_ranges, regime):
    """Build decision graph with all neurons explicit.

    Per-ticker: bounced, candidate (AND gate of 7 inputs)
    Market: breadth_bounce, signal_confirmed
    Portfolio: pdt_available, capital_available
    Terminal: {tk}:buy_dip (report nodes)
    """
    graph = DependencyGraph()
    cfg = DIP_CONFIG

    breadth_dip_fired = fh_state.get("breadth_dip", False)

    bounce_count = 0
    candidates = []

    for tk in tickers:
        fh_low = fh_state.get(f"{tk}:first_hour_low")
        current = _extract_latest_price(prices_11, tk)
        bounce_pct = round((current - fh_low) / fh_low * 100, 1) if fh_low and current and fh_low > 0 else 0
        bounced = bounce_pct >= cfg["bounce_threshold_pct"]
        if bounced:
            bounce_count += 1

        dipped = fh_state.get(f"{tk}:dipped", False)
        st = static.get(tk, {})
        hr = hist_ranges.get(tk, {})

        # All Layer 3 neurons as graph nodes (for reason chain)
        graph.add_node(f"{tk}:dipped", compute=lambda _, d=dipped: d,
            reason_fn=lambda old, new, _: "Dipped" if new else "No dip")
        graph.add_node(f"{tk}:bounced", compute=lambda _, b=bounced: b,
            reason_fn=lambda old, new, _, pct=bounce_pct:
                f"Bounced {pct:.1f}%" if new else f"No bounce ({pct:.1f}%)")

        cat = st.get("catastrophic")
        viable = st.get("dip_viable", "UNKNOWN")
        verdict = st.get("verdict", ["UNKNOWN"])
        v0 = verdict[0] if isinstance(verdict, list) else verdict
        eg = st.get("earnings_gate", "CLEAR")

        graph.add_node(f"{tk}:dip_viable", compute=lambda _, v=viable: v in ("YES", "CAUTION", "UNKNOWN"),
            reason_fn=lambda old, new, _, v=viable: f"DIP_VIABLE={v}")
        graph.add_node(f"{tk}:not_catastrophic", compute=lambda _, c=cat: c not in ("HARD_STOP", "EXIT_REVIEW"),
            reason_fn=lambda old, new, _, c=cat: "Clear" if new else f"BLOCKED:{c}")
        graph.add_node(f"{tk}:not_exit", compute=lambda _, v=v0: v not in ("EXIT", "REDUCE"),
            reason_fn=lambda old, new, _, v=v0: "Clear" if new else f"BLOCKED:verdict={v}")
        graph.add_node(f"{tk}:earnings_clear", compute=lambda _, e=eg: e not in ("BLOCKED", "FALLING_KNIFE"),
            reason_fn=lambda old, new, _, e=eg: "Clear" if new else f"BLOCKED:earnings={e}")
        graph.add_node(f"{tk}:historical_range", compute=lambda _, h=hr: h.get("viable", False),
            reason_fn=lambda old, new, _, h=hr: f"Range OK" if new else f"BLOCKED:range={h.get('range_pct',0)}%")

        # Layer 4: CANDIDATE — AND gate (all 7 must be True)
        is_candidate = all([dipped, bounced,
                            viable in ("YES", "CAUTION", "UNKNOWN"),
                            cat not in ("HARD_STOP", "EXIT_REVIEW"),
                            v0 not in ("EXIT", "REDUCE"),
                            eg not in ("BLOCKED", "FALLING_KNIFE"),
                            hr.get("viable", False)])

        graph.add_node(f"{tk}:candidate",
            compute=lambda _, c=is_candidate: c,
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
    breadth_bounce_ratio = bounce_count / len(tickers) if tickers else 0
    breadth_bounce_fired = breadth_bounce_ratio >= cfg["breadth_threshold"]
    signal_confirmed = breadth_dip_fired and breadth_bounce_fired

    graph.add_node("breadth_bounce", compute=lambda _: breadth_bounce_fired,
        reason_fn=lambda old, new, _:
            f"Bounce breadth: {bounce_count}/{len(tickers)} = {breadth_bounce_ratio:.0%}")
    graph.add_node("signal_confirmed",
        compute=lambda _: signal_confirmed,
        depends_on=["breadth_bounce"],
        reason_fn=lambda old, new, _:
            "CONFIRMED (dip + bounce breadth met)" if new else "NOT CONFIRMED")

    # Layer 5: Portfolio constraints
    pdt_count = _count_pdt_trades()
    pdt_ok = pdt_count < cfg["pdt_limit"]
    capital = _get_dip_capital()
    capital_ok = capital >= cfg["capital_min"]

    graph.add_node("pdt_available", compute=lambda _: pdt_ok,
        reason_fn=lambda old, new, _: f"PDT: {pdt_count}/{cfg['pdt_limit']} used" if new else f"PDT BLOCKED: {pdt_count} used")
    graph.add_node("capital_available", compute=lambda _: capital_ok,
        reason_fn=lambda old, new, _: f"Capital: ${capital:.0f}" if new else f"BLOCKED: ${capital:.0f} < ${cfg['capital_min']}")

    # Rank candidates by dip size, take top N
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

    # NO_ACTION neuron — fires when NO buy_dip fired
    no_buys = not (signal_confirmed and pdt_ok and capital_ok and top)
    graph.add_node("no_action", compute=lambda _: no_buys, is_report=True,
        reason_fn=lambda old, new, _: "No dip play today" if new else "")

    graph.resolve()
    return graph, top, budget
```

### 3.6 Helper Functions

```python
def _load_portfolio():
    """Load portfolio.json."""
    with open(_ROOT / "portfolio.json") as f:
        return json.load(f)

def _get_dip_candidates(portfolio):
    """Return sorted list of tickers eligible for dip evaluation."""
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
        same_day = [t for t in trades
                    if t.get("date", "") >= cutoff
                    and t.get("exit_reason") == "SAME_DAY_EXIT"]
        return len(same_day)
    except Exception:
        return 0

def _get_dip_capital():
    """Return available dip budget (separate from support-level pools)."""
    try:
        portfolio = _load_portfolio()
        capital = portfolio.get("capital", {})
        return capital.get("dip_pool", 500)  # default $500 daily dip budget
    except Exception:
        return 500

def _extract_col(data, col, tk, tickers_count):
    """Extract a column from yfinance MultiIndex DataFrame."""
    if tickers_count > 1:
        return data[(col, tk)].dropna()
    else:
        return data[col].dropna()

def _extract_open(data, tk, tickers_count=1):
    """Extract today's open price from 5-min data (first bar's open)."""
    try:
        col = _extract_col(data, "Open", tk, tickers_count)
        return round(float(col.iloc[0]), 2) if len(col) > 0 else None
    except (KeyError, IndexError):
        return None

def _extract_price_at(data, tk, et_hour, et_minute, tickers_count=1):
    """Extract price at specific ET time from 5-min bars."""
    try:
        utc_hour = market_time_to_utc_hour(et_hour, et_minute)
        col = _extract_col(data, "Close", tk, tickers_count)
        # Find bar closest to target UTC hour
        for idx in col.index:
            bar_hour = idx.hour + idx.minute / 60
            if bar_hour >= utc_hour:
                return round(float(col.loc[idx]), 2)
        # If past target, return last available
        return round(float(col.iloc[-1]), 2) if len(col) > 0 else None
    except (KeyError, IndexError):
        return None

def _extract_first_hour_low(data, tk, tickers_count=1):
    """Extract lowest price in first hour (9:30-10:30 ET)."""
    try:
        fh_start = market_time_to_utc_hour(9, 30)
        fh_end = market_time_to_utc_hour(10, 30)
        col = _extract_col(data, "Low", tk, tickers_count)
        fh_bars = col[(col.index.hour + col.index.minute / 60 >= fh_start) &
                      (col.index.hour + col.index.minute / 60 < fh_end)]
        return round(float(fh_bars.min()), 2) if len(fh_bars) > 0 else None
    except (KeyError, IndexError):
        return None

def _extract_latest_price(data, tk, tickers_count=1):
    """Extract most recent bar's close."""
    try:
        col = _extract_col(data, "Close", tk, tickers_count)
        return round(float(col.iloc[-1]), 2) if len(col) > 0 else None
    except (KeyError, IndexError):
        return None

def _extract_dip_pct(data, tk, tickers_count=1):
    """Compute dip % from open to latest close."""
    o = _extract_open(data, tk, tickers_count)
    c = _extract_latest_price(data, tk, tickers_count)
    if o and c and o > 0:
        return round((o - c) / o * 100, 1)
    return 0
```

### 3.7 Phase Evaluation Functions

```python
def evaluate_first_hour(tickers, static, hist_ranges, regime):
    """10:30 AM: Evaluate first-hour breadth. Cache results for decision phase."""
    prices = fetch_intraday(tickers)
    if prices is None:
        print("*yfinance unavailable. Skipping first_hour.*")
        return

    graph, fh_state = build_first_hour_graph(tickers, prices, static, hist_ranges, regime)

    # Cache first-hour state for decision phase
    cache_path = _ROOT / "data" / "neural_fh_cache.json"
    with open(cache_path, "w") as f:
        json.dump(fh_state, f, default=str)

    breadth = fh_state.get("breadth_dip", False)
    dip_count = sum(1 for tk in tickers if fh_state.get(f"{tk}:dipped"))
    print(f"First-hour breadth: {dip_count}/{len(tickers)} dipped. "
          f"{'FIRED' if breadth else 'NOT FIRED'}")


def evaluate_decision(tickers, static, hist_ranges, regime, dry_run=False):
    """11:00 AM: Full decision — load first-hour cache + bounce + decide."""
    # Load cached first-hour state
    cache_path = _ROOT / "data" / "neural_fh_cache.json"
    if cache_path.exists():
        with open(cache_path) as f:
            fh_state = json.load(f)
    else:
        # Fallback: compute first-hour from current data
        print("*No first-hour cache. Computing from current data.*")
        prices = fetch_intraday(tickers)
        if prices is None:
            print("*yfinance unavailable. Skipping.*")
            return
        _, fh_state = build_first_hour_graph(tickers, prices, static, hist_ranges, regime)

    if not fh_state.get("breadth_dip"):
        print("Breadth dip: NOT FIRED. No dip play today.")
        return

    # Fetch 11:00 prices
    prices_11 = fetch_intraday(tickers)
    if prices_11 is None:
        print("*yfinance unavailable at 11:00. Skipping.*")
        return

    decision_graph, top, budget = build_decision_graph(
        tickers, prices_11, fh_state, static, hist_ranges, regime)

    # Check fired BUY_DIP neurons
    activated = decision_graph.get_activated_reports()
    buy_signals = [(name, node) for name, node in activated
                   if name.endswith(":buy_dip") and node.value]

    if not buy_signals:
        # Show why NO_ACTION fired
        no_action = decision_graph.nodes.get("no_action")
        reason = "Unknown"
        if no_action and no_action.signals:
            reason = no_action.signals[0].flat_reason()
        print(f"No dip play today. Reason: {reason}")
        # Show blocked tickers
        for tk in tickers:
            cand = decision_graph.nodes.get(f"{tk}:candidate")
            if cand and not cand.value:
                blocked_reasons = []
                for dep in cand.depends_on:
                    dep_node = decision_graph.nodes.get(dep)
                    if dep_node and not dep_node.value:
                        r = dep_node.reason_fn(None, dep_node.value, []) if dep_node.reason_fn else dep
                        blocked_reasons.append(r)
                if blocked_reasons:
                    print(f"  {tk}: {', '.join(blocked_reasons)}")
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
            # notify.py is in same tools/ directory — sys.path already set at module top
            from notify import send_dip_alert
            send_dip_alert(tk, candidate["entry"], candidate["target"],
                          candidate["stop"], f"{node_path}\n{reason}", regime, budget)


def evaluate_eod(tickers):
    """3:45 PM: Check for unfilled dip sells."""
    portfolio = _load_portfolio()
    pending = portfolio.get("pending_orders", {})
    unfilled = []
    for tk in tickers:
        for order in pending.get(tk, []):
            if order.get("type") == "SELL" and "same-day-exit" in order.get("note", "").lower():
                unfilled.append((tk, order["price"], order.get("shares", 0)))
    if unfilled:
        print(f"\n## EOD Check — {len(unfilled)} unfilled same-day exit(s)\n")
        for tk, price, shares in unfilled:
            print(f"- {tk}: SELL @ ${price:.2f} × {shares} — consider manual close or hold")
    else:
        print("EOD: No unfilled same-day exits.")
```

### 3.8 Main Entry Point

```python
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

    # Gate: market phase matches requested phase
    actual_phase = get_market_phase()
    valid_phases = VALID_PHASES_FOR_MARKET.get(args.phase, ())
    if actual_phase not in valid_phases and actual_phase != "CLOSED":
        print(f"Phase mismatch: requested {args.phase}, market is {actual_phase}. "
              f"Expected: {valid_phases}. Proceeding anyway (may use stale data).")

    # Load context
    portfolio = _load_portfolio()
    tickers = _get_dip_candidates(portfolio)
    regime, vix, static = load_static_context(tickers)
    hist_ranges = compute_historical_ranges(tickers)

    # Cache historical ranges to avoid re-downloading across phases
    hist_cache_path = _ROOT / "data" / "neural_hist_ranges_cache.json"
    if hist_cache_path.exists():
        cache_age = time.time() - hist_cache_path.stat().st_mtime
        if cache_age < 14400:  # <4 hours old = reuse
            with open(hist_cache_path) as f:
                hist_ranges = json.load(f)
        else:
            hist_ranges = compute_historical_ranges(tickers)
            with open(hist_cache_path, "w") as f:
                json.dump(hist_ranges, f, indent=2)
    else:
        hist_ranges = compute_historical_ranges(tickers)
        with open(hist_cache_path, "w") as f:
            json.dump(hist_ranges, f, indent=2)

    print(f"Neural Dip Evaluator — {args.phase} | {len(tickers)} tickers | Regime: {regime}")

    if args.phase == "first_hour":
        evaluate_first_hour(tickers, static, hist_ranges, regime)
    elif args.phase == "decision":
        evaluate_decision(tickers, static, hist_ranges, regime, args.dry_run)
    elif args.phase == "eod_check":
        evaluate_eod(tickers)
```

---

## Phase 4: Cron Scheduling (3 entries)

```bash
# Neural Dip Evaluator — market hours ET
# Adjust times if server is not in ET timezone

# 10:30 AM ET — First-hour breadth
30 10 * * 1-5 cd /Users/kamenkamenov/agentic-trading && python3 tools/neural_dip_evaluator.py --phase first_hour >> logs/neural_dip.log 2>&1

# 11:00 AM ET — Decision (+ email if BUY fires)
0 11 * * 1-5 cd /Users/kamenkamenov/agentic-trading && python3 tools/neural_dip_evaluator.py --phase decision >> logs/neural_dip.log 2>&1

# 3:45 PM ET — EOD unfilled dip sells check
45 15 * * 1-5 cd /Users/kamenkamenov/agentic-trading && python3 tools/neural_dip_evaluator.py --phase eod_check >> logs/neural_dip.log 2>&1
```

Create logs directory: `mkdir -p logs && echo "logs/" >> .gitignore`

---

## Phase 5: Intraday Backtester (~200 lines)

### 5.1 `tools/neural_dip_backtester.py` (NEW)

```python
def backtest_neural_dip(tickers, days=60):
    """Replay historical 5-min data through neural evaluation phases."""
    # Download ALL tickers in one batch
    all_data = yf.download(tickers, period=f"{days}d", interval="5m", progress=False)

    # Cache locally
    cache_path = _ROOT / "data" / "backtest" / "intraday_5min_cache.pkl"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    all_data.to_pickle(cache_path)

    # Get trading days in the data
    trading_days = sorted(set(all_data.index.date))

    # Pre-compute per-day context from daily OHLCV (regime, ranges)
    daily_data = yf.download(tickers, period=f"{days + 30}d", interval="1d", progress=False)

    results = []
    for day in trading_days:
        day_bars = all_data[all_data.index.date == day]
        if len(day_bars) < 12:  # need at least 1 hour of data
            continue

        # Per-day context: compute regime + ranges using data BEFORE this day
        # (prevents look-ahead bias — only use what was known at that time)
        prior_daily = daily_data[daily_data.index.date < day]
        regime = _compute_regime_for_day(prior_daily, day)  # VIX + index 50-SMA
        hist_ranges = _compute_ranges_for_day(prior_daily, tickers, lookback=21)

        # Static neurons: use "UNKNOWN" for all (no graph_state history)
        # This tests the neural model without simulation-backed data
        static = {tk: {"verdict": ["UNKNOWN"], "catastrophic": None,
                       "dip_viable": "UNKNOWN", "earnings_gate": "CLEAR"}
                  for tk in tickers}

        # Simulate first-hour (bars 0-12 = 9:30-10:30)
        fh_bars = day_bars.iloc[:12]
        # Simulate decision (bars 12-18 = 10:30-11:00)
        decision_bars = day_bars.iloc[:18]
        # EOD close for P/L
        eod_close = day_bars.iloc[-1]

        # Build first-hour graph from fh_bars
        _, fh_state = build_first_hour_graph(tickers, fh_bars, static, hist_ranges, regime)

        if not fh_state.get("breadth_dip"):
            results.append({"day": str(day), "signal": "NO_DIP", "buys": []})
            continue

        # Build decision graph from decision_bars
        decision_graph, top, budget = build_decision_graph(
            tickers, decision_bars, fh_state, static, hist_ranges, regime)

        # Check BUY_DIP
        buy_tickers = [name.split(":")[0]
                       for name, node in decision_graph.get_activated_reports()
                       if name.endswith(":buy_dip") and node.value]

        # Compute P/L for each buy
        day_result = {"day": str(day), "signal": "CONFIRMED" if buy_tickers else "NO_CANDIDATES", "buys": []}
        for tk in buy_tickers:
            candidate = next((c for c in top if c["ticker"] == tk), None)
            if not candidate:
                continue
            entry = candidate["entry"]
            target = candidate["target"]
            stop = candidate["stop"]

            # Check if target or stop hit during the day
            remaining_bars = day_bars.iloc[18:]  # after 11:00
            if len(remaining_bars) > 0:
                day_high = float(remaining_bars[("High", tk)].max()) if len(tickers) > 1 else float(remaining_bars["High"].max())
                day_low = float(remaining_bars[("Low", tk)].min()) if len(tickers) > 1 else float(remaining_bars["Low"].min())
                eod = float(remaining_bars[("Close", tk)].iloc[-1]) if len(tickers) > 1 else float(remaining_bars["Close"].iloc[-1])

                if day_low <= stop:
                    pnl = stop - entry
                    exit_reason = "STOP"
                elif day_high >= target:
                    pnl = target - entry
                    exit_reason = "TARGET"
                else:
                    pnl = eod - entry
                    exit_reason = "EOD_CUT"
            else:
                pnl = 0
                exit_reason = "NO_DATA"

            day_result["buys"].append({
                "ticker": tk, "entry": entry, "pnl": round(pnl, 2),
                "exit_reason": exit_reason,
            })

        results.append(day_result)

    # Summary
    total_days = len(results)
    signal_days = sum(1 for r in results if r["signal"] == "CONFIRMED")
    all_buys = [b for r in results for b in r["buys"]]
    wins = sum(1 for b in all_buys if b["pnl"] > 0)
    total_pnl = sum(b["pnl"] for b in all_buys)

    print(f"\n## Neural Dip Backtest — {days} days\n")
    print(f"Trading days: {total_days}")
    print(f"Signal days: {signal_days}")
    print(f"Total trades: {len(all_buys)}")
    print(f"Wins: {wins} ({wins/len(all_buys)*100:.0f}%)" if all_buys else "No trades")
    print(f"Total P/L: ${total_pnl:.2f}")

    return results
```

---

## Files Modified / Created

| File | Action | Lines |
| :--- | :--- | :--- |
| `tools/trading_calendar.py` | MODIFY — market phase, timezone, early closes | ~55 |
| `tools/notify.py` | NEW — SendGrid email | ~45 |
| `tools/neural_dip_evaluator.py` | NEW — core evaluator | ~500 |
| `tools/neural_dip_backtester.py` | NEW — 60-day replay | ~200 |
| `.gitignore` | MODIFY — add logs/ | 1 |
| `tools/graph_engine.py` | NO CHANGES | 0 |
| `tools/graph_builder.py` | NO CHANGES | 0 |
| `tools/daily_analyzer.py` | NO CHANGES | 0 |
| **Total** | | **~800** |

---

## Gaps from v1 Addressed

| Gap # | Description | How Fixed in v2 |
| :--- | :--- | :--- |
| 1 | Static Layer 3 neurons not as graph nodes | ALL neurons explicit: dip_viable, not_catastrophic, not_exit, earnings_clear, historical_range |
| 2 | Thresholds hardcoded | DIP_CONFIG dict at module level |
| 3 | HISTORICAL_RANGE missing | compute_historical_ranges() function |
| 4 | Fallback for missing graph_state | load_static_context() computes regime + earnings from live data |
| 5 | First-hour data not cached | Cached to data/neural_fh_cache.json between phases |
| 6 | Reason chain incomplete | All neurons have reason_fn, traces through graph |
| 7 | CANDIDATE depends_on not linked to BUY_DIP | Explicit depends_on chain: Layer 3 → CANDIDATE → BUY_DIP |
| 8 | Phase routing incomplete | evaluate_first_hour, evaluate_decision, evaluate_eod all defined |
| 9 | NO_ACTION neuron missing | Explicit no_action node + blocked ticker reasons printed |
| 10 | Backtester skeleton | Complete: download, cache, replay, P/L, summary |
| 11 | Regime sizing | Uses DIP_CONFIG budget_normal/budget_risk_off |
| 12 | UNKNOWN semantics | UNKNOWN treated as pass-through in dip_viable check |
| 13 | Phase validation | VALID_PHASES_FOR_MARKET dict + mismatch warning |
| 14 | Missing functions | All 7 defined: _load_portfolio, _get_dip_candidates, _count_pdt_trades, _get_dip_capital, evaluate_first_hour, evaluate_decision, evaluate_eod |
| 15 | evaluate_first_hour undefined | Fully implemented with fh_cache write |
| 16 | evaluate_eod undefined | Fully implemented — checks unfilled same-day exits |
| 17 | Test plan | Acknowledged — requires own analysis → plan → implement cycle (Phase 6) |

---

## Verification

1. [ ] `python3 tools/trading_calendar.py` — get_market_phase() returns "CLOSED" on Sunday
2. [ ] `python3 tools/notify.py` — test email arrives at kamen@katalyst.digital
3. [ ] `python3 tools/neural_dip_evaluator.py --phase decision --dry-run` — exits "Market closed" on weekend
4. [ ] `python3 tools/neural_dip_backtester.py --days 10` — shows trade summary
5. [ ] `python3 -m pytest tests/test_graph.py -v` — all 93 existing tests pass
6. [ ] Monday 10:30 AM: cron fires first_hour, logs to neural_dip.log
7. [ ] Monday 11:00 AM: cron fires decision, email arrives if BUY fires
8. [ ] Graph reason chains show every neuron (dipped, bounced, dip_viable, not_catastrophic, etc.)

---

## Implementation Order

1. **Phase 1** (trading_calendar.py) — test with `get_market_phase()`
2. **Phase 2** (notify.py) — test with `python3 tools/notify.py`
3. **Phase 3** (neural_dip_evaluator.py) — test with `--dry-run`
4. **Phase 4** (cron) — install Monday morning
5. **Phase 5** (backtester) — validate against historical data
6. **Phase 6** (tests) — separate analysis → plan → implement cycle
