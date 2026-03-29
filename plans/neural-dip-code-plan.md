# Code Plan: Neural Dip Evaluator

**Date**: 2026-03-29 (Sunday)
**Source**: `plans/neural-requirements-analysis.md` (verified, 373 lines)
**Goal**: Build a neural firing evaluator for daily dip same-day-profit decisions. 3 phases (first-hour, decision, EOD), graph-driven, with email notifications.

---

## Context

The daily dip strategy currently uses hardcoded thresholds (range ≥ 3%, recovery ≥ 60%) and a manual `dip_signal_checker.py` run at ~10:30 AM. This plan replaces it with:
1. A neural evaluator that builds per-phase graphs with temporal awareness
2. Cron-triggered at 10:30, 11:00, and 15:45 ET
3. Email alert via SendGrid when BUY_DIP neuron fires
4. Full reason chain tracing every neuron that fired or blocked

---

## Phase 1: Shared Infrastructure (~40 lines)

### 1.1 Add market phase + timezone to `trading_calendar.py`

**File**: `tools/trading_calendar.py` (add to existing, ~40 lines)

```python
import pytz
from datetime import datetime

ET = pytz.timezone("US/Eastern")
MARKET_OPEN_ET = (9, 30)
MARKET_CLOSE_ET = (16, 0)

_EARLY_CLOSES = {
    date(2025, 11, 28): (13, 0),
    date(2025, 12, 24): (13, 0),
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
    """Return current market phase based on ET time."""
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
    market_time = now_et.replace(hour=et_hour, minute=et_minute, second=0, microsecond=0)
    market_utc = market_time.astimezone(pytz.utc)
    return market_utc.hour + market_utc.minute / 60
```

---

## Phase 2: Notification Engine (~40 lines)

### 2.1 Create `tools/notify.py`

**File**: `tools/notify.py` (NEW, ~40 lines)

```python
"""Email notification for neural dip evaluator alerts."""
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
        return True
    except Exception as e:
        print(f"*Warning: email send failed: {e}*")
        return False
```

---

## Phase 3: Core Neural Dip Evaluator (~400 lines)

### 3.1 Create `tools/neural_dip_evaluator.py`

**File**: `tools/neural_dip_evaluator.py` (NEW)

**Structure**:
```
Imports + constants                          (~20 lines)
fetch_intraday() — yfinance with retry       (~25 lines)
load_static_context() — graph_state fallback (~40 lines)
build_first_hour_graph() — Phase 2 neurons   (~80 lines)
build_decision_graph() — Phase 3 neurons     (~100 lines)
evaluate_first_hour() — 10:30 AM logic       (~40 lines)
evaluate_decision() — 11:00 AM logic         (~50 lines)
evaluate_eod() — 3:45 PM logic               (~20 lines)
print_results() — output formatting          (~30 lines)
main() — arg parsing + phase routing         (~30 lines)
```

### 3.2 Data Fetching

```python
import time
import yfinance as yf

def fetch_intraday(tickers, retries=1):
    """Fetch 5-min bars for all tickers. Retry once on failure."""
    for attempt in range(retries + 1):
        try:
            data = yf.download(tickers, period="1d", interval="5m",
                               progress=False)
            if data.empty:
                if attempt < retries:
                    time.sleep(3)
                    continue
                return None

            # Check for partial data (some tickers missing)
            if len(tickers) > 1:
                available = [tk for tk in tickers
                             if tk in data["Close"].columns]
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

### 3.3 Static Context Loading

```python
def load_static_context():
    """Load regime, verdicts, catastrophic from graph_state.json.
    Falls back to live computation if missing/stale."""
    state = {}
    if GRAPH_STATE_PATH.exists():
        try:
            with open(GRAPH_STATE_PATH) as f:
                state = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    regime = state.get("regime", "Neutral")
    vix = state.get("vix")
    tickers_state = state.get("tickers", {})

    # Extract per-ticker static neurons
    static = {}
    for tk, ts in tickers_state.items():
        static[tk] = {
            "verdict": ts.get("verdict", ["UNKNOWN"]),
            "catastrophic": ts.get("catastrophic"),
            "dip_viable": ts.get("dip_viable", "UNKNOWN"),
            "earnings_gate": ts.get("earnings_gate", "CLEAR"),
        }

    return regime, vix, static
```

### 3.4 First-Hour Graph (10:30 AM)

Builds a graph with per-ticker dip detection + breadth aggregation.

```python
def build_first_hour_graph(tickers, prices_data, static_context, regime):
    """Build first-hour evaluation graph.

    Per-ticker neurons:
      {tk}:open — today's open price
      {tk}:current — price at 10:30
      {tk}:dipped — (open - current) / open > 1%
      {tk}:not_catastrophic — static check
      {tk}:earnings_clear — static check
      {tk}:dip_viable — from simulation
      {tk}:historical_range — from 1-month stats (pre-computed)

    Market-wide neurons:
      breadth_dip — count(dipped) / total >= 50%
    """
    graph = DependencyGraph()

    # Extract open and 10:30 prices from intraday data
    opens = {}
    currents = {}
    for tk in tickers:
        # ... extract from prices_data MultiIndex DataFrame

    # Per-ticker neurons
    dip_count = 0
    for tk in tickers:
        o = opens.get(tk)
        c = currents.get(tk)
        dip_pct = (o - c) / o * 100 if o and c and o > 0 else 0
        dipped = dip_pct >= 1.0
        if dipped:
            dip_count += 1

        graph.add_node(f"{tk}:dipped", compute=lambda _, d=dipped: d,
            reason_fn=lambda old, new, _: f"Dipped {dip_pct:.1f}%" if new else "")
        # ... static neurons from context

    # Breadth neuron
    breadth_ratio = dip_count / len(tickers) if tickers else 0
    breadth_fired = breadth_ratio >= 0.50
    graph.add_node("breadth_dip",
        compute=lambda _: breadth_fired,
        reason_fn=lambda old, new, _:
            f"Breadth {dip_count}/{len(tickers)} = {breadth_ratio:.0%}")

    graph.resolve()
    return graph
```

### 3.5 Decision Graph (11:00 AM)

Builds on first-hour results, adds bounce detection + CANDIDATE AND-gates + RANKER.

```python
def build_decision_graph(tickers, prices_11, fh_state, static_context, regime):
    """Build decision graph.

    Per-ticker neurons:
      {tk}:bounced — recovering >0.3% from first-hour low
      {tk}:candidate — AND gate: dipped AND bounced AND viable AND clear

    Market-wide:
      breadth_bounce — count(bounced) / total >= 50%
      signal_confirmed — breadth_dip (from fh) AND breadth_bounce

    Portfolio:
      pdt_available — day_trade_count < 3
      capital_available — dip budget > $100

    Terminal:
      {tk}:buy_dip — fires when: candidate AND signal_confirmed AND pdt AND capital
    """
    graph = DependencyGraph()

    # Carry forward first-hour state
    breadth_dip_fired = fh_state.get("breadth_dip", False)

    # Per-ticker bounce detection
    bounce_count = 0
    candidates = []
    for tk in tickers:
        fh_low = fh_state.get(f"{tk}:first_hour_low")
        current_11 = prices_11.get(tk)
        bounce_pct = (current_11 - fh_low) / fh_low * 100 if fh_low and current_11 else 0
        bounced = bounce_pct >= 0.3
        if bounced:
            bounce_count += 1

        dipped = fh_state.get(f"{tk}:dipped", False)
        viable = static_context.get(tk, {}).get("dip_viable") in ("YES", "CAUTION", "UNKNOWN")
        catastrophic = static_context.get(tk, {}).get("catastrophic")
        not_blocked = catastrophic not in ("HARD_STOP", "EXIT_REVIEW")
        verdict = static_context.get(tk, {}).get("verdict", ["UNKNOWN"])
        not_exit = verdict[0] not in ("EXIT", "REDUCE") if isinstance(verdict, list) else True
        earnings = static_context.get(tk, {}).get("earnings_gate", "CLEAR")
        earnings_clear = earnings not in ("BLOCKED", "FALLING_KNIFE")

        # AND gate: ALL must be true
        is_candidate = (dipped and bounced and viable and not_blocked
                       and not_exit and earnings_clear)

        if is_candidate:
            candidates.append({
                "ticker": tk,
                "dip_pct": fh_state.get(f"{tk}:dip_pct", 0),
                "entry": current_11,
                "target": round(current_11 * 1.04, 2),
                "stop": round(current_11 * 0.97, 2),
            })

        # Add nodes for reason chain
        graph.add_node(f"{tk}:candidate",
            compute=lambda _, c=is_candidate: c,
            reason_fn=lambda old, new, _: "ALL gates passed" if new else "Blocked")

    # Breadth bounce
    breadth_bounce_ratio = bounce_count / len(tickers) if tickers else 0
    breadth_bounce_fired = breadth_bounce_ratio >= 0.50
    signal_confirmed = breadth_dip_fired and breadth_bounce_fired

    graph.add_node("breadth_bounce",
        compute=lambda _: breadth_bounce_fired,
        reason_fn=lambda old, new, _:
            f"Bounce {bounce_count}/{len(tickers)} = {breadth_bounce_ratio:.0%}")
    graph.add_node("signal_confirmed",
        compute=lambda _: signal_confirmed,
        depends_on=["breadth_bounce"],
        reason_fn=lambda old, new, _:
            "CONFIRMED" if new else "NOT CONFIRMED")

    # PDT + capital
    pdt_count = _count_pdt_trades()
    pdt_ok = pdt_count < 3
    capital_ok = _check_dip_capital() >= 100
    graph.add_node("pdt_available", compute=lambda _: pdt_ok)
    graph.add_node("capital_available", compute=lambda _: capital_ok)

    # Rank candidates
    candidates.sort(key=lambda c: c["dip_pct"], reverse=True)
    top_5 = candidates[:5]

    # Terminal BUY_DIP neurons
    budget = 100 if regime != "Risk-Off" else 50
    for c in top_5:
        tk = c["ticker"]
        graph.add_node(f"{tk}:buy_dip",
            compute=lambda _, confirmed=signal_confirmed, pdt=pdt_ok, cap=capital_ok:
                confirmed and pdt and cap,
            depends_on=["signal_confirmed", "pdt_available", "capital_available",
                        f"{tk}:candidate"],
            is_report=True,
            reason_fn=lambda old, new, _: "BUY" if new else "NO ACTION")

    graph.resolve()
    return graph, top_5, budget
```

### 3.6 Phase Routing (main)

```python
def main():
    parser = argparse.ArgumentParser(description="Neural Dip Evaluator")
    parser.add_argument("--phase", choices=["first_hour", "decision", "eod_check"],
                        default="decision")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print results but don't send email")
    args = parser.parse_args()

    # Gate: trading day check
    if not is_trading_day():
        print(f"Market closed today ({date.today()}). Skipping.")
        return

    # Gate: market phase check
    phase = get_market_phase()
    if phase in ("CLOSED", "PRE_MARKET", "AFTER_HOURS"):
        print(f"Market phase: {phase}. Not in evaluation window.")
        return

    # Load context
    portfolio = _load_portfolio()
    tickers = _get_dip_candidates(portfolio)
    regime, vix, static = load_static_context()

    if args.phase == "first_hour":
        evaluate_first_hour(tickers, static, regime)
    elif args.phase == "decision":
        evaluate_decision(tickers, static, regime, args.dry_run)
    elif args.phase == "eod_check":
        evaluate_eod(tickers)
```

### 3.7 Decision Evaluation (11:00 AM)

```python
def evaluate_decision(tickers, static, regime, dry_run=False):
    """Full evaluation: first-hour + decision phase in sequence."""
    # Phase 2: First-hour breadth
    prices = fetch_intraday(tickers)
    if prices is None:
        print("*yfinance unavailable. Skipping.*")
        return

    fh_graph = build_first_hour_graph(tickers, prices, static, regime)
    fh_state = fh_graph.get_state()

    if not fh_state.get("breadth_dip"):
        print("Breadth dip: NOT FIRED. No dip play today.")
        return

    # Phase 3: Decision
    # Re-fetch latest prices (may have changed in 30 minutes)
    prices_11 = fetch_intraday(tickers)
    if prices_11 is None:
        prices_11 = prices  # fallback to 10:30 data

    decision_graph, top_5, budget = build_decision_graph(
        tickers, prices_11, fh_state, static, regime)

    # Check which BUY_DIP neurons fired
    activated = decision_graph.get_activated_reports()
    buy_signals = [(name, node) for name, node in activated
                   if name.endswith(":buy_dip") and node.value]

    if not buy_signals:
        print("Signal confirmed but no candidates passed all gates.")
        return

    # Output results
    print(f"\n## Neural Dip Evaluator — {len(buy_signals)} BUY signal(s)\n")
    for name, node in buy_signals:
        tk = name.split(":")[0]
        candidate = next((c for c in top_5 if c["ticker"] == tk), None)
        if not candidate:
            continue

        reason = node.signals[0].flat_reason() if node.signals else "No chain"
        print(f"### {tk}: BUY at ${candidate['entry']:.2f}")
        print(f"- Target: ${candidate['target']:.2f} (+4%)")
        print(f"- Stop: ${candidate['stop']:.2f} (-3%)")
        print(f"- Budget: ${budget}")
        print(f"- Regime: {regime}")
        print(f"- Reason: {reason}")
        print()

        # Send email notification
        if not dry_run:
            from notify import send_dip_alert
            send_dip_alert(tk, candidate["entry"], candidate["target"],
                          candidate["stop"], reason, regime, budget)
```

---

## Phase 4: Cron Scheduling (~3 entries)

### 4.1 Crontab entries

```bash
# Neural Dip Evaluator — runs during market hours only
# Times are in ET (adjust if server is different timezone)

# 10:30 AM ET — First-hour breadth check
30 10 * * 1-5 cd /Users/kamenkamenov/agentic-trading && python3 tools/neural_dip_evaluator.py --phase first_hour >> logs/neural_dip.log 2>&1

# 11:00 AM ET — Decision (breadth + bounce + candidate gates + email)
0 11 * * 1-5 cd /Users/kamenkamenov/agentic-trading && python3 tools/neural_dip_evaluator.py --phase decision >> logs/neural_dip.log 2>&1

# 3:45 PM ET — EOD check for unfilled dip sells
45 15 * * 1-5 cd /Users/kamenkamenov/agentic-trading && python3 tools/neural_dip_evaluator.py --phase eod_check >> logs/neural_dip.log 2>&1
```

### 4.2 Create logs directory

```bash
mkdir -p logs
echo "logs/" >> .gitignore
```

---

## Phase 5: Intraday Backtester (~200 lines)

### 5.1 Create `tools/neural_dip_backtester.py`

**File**: `tools/neural_dip_backtester.py` (NEW)

**Purpose**: Replay 60 days of 5-min data through the neural evaluator's 2-phase sequence and compare against actual P/L.

```python
def backtest_neural_dip(tickers, days=60):
    """Replay historical 5-min data through neural phases."""
    # Download ALL tickers' 5-min data in one batch
    all_data = yf.download(tickers, period=f"{days}d", interval="5m",
                           progress=False)

    # Cache locally
    cache_path = _ROOT / "data" / "backtest" / "intraday_5min_cache.pkl"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    all_data.to_pickle(cache_path)

    # Group bars by trading day
    results = []
    for day in trading_days:
        day_bars = all_data[all_data.index.date == day]

        # Extract 10:30 bars and 11:00 bars
        # Build first-hour graph from 10:30 data
        # Build decision graph from 11:00 data
        # Record: did BUY_DIP fire? For which tickers?
        # Check actual EOD close: what was P/L?

    # Summary
    print(f"Days evaluated: {len(results)}")
    print(f"BUY signals: {sum(1 for r in results if r['buy_fired'])}")
    print(f"Win rate: ...")
    print(f"Total P/L: ...")
```

**Key design**: Uses the SAME `build_first_hour_graph()` and `build_decision_graph()` functions as the live evaluator. Tests the exact same logic.

---

## Files Modified / Created

| File | Action | Lines |
| :--- | :--- | :--- |
| `tools/trading_calendar.py` | MODIFY — add market phase, timezone, early closes | ~40 |
| `tools/notify.py` | NEW — SendGrid email notification | ~40 |
| `tools/neural_dip_evaluator.py` | NEW — core evaluator with 3-phase routing | ~400 |
| `tools/neural_dip_backtester.py` | NEW — replay 60 days of 5-min data | ~200 |
| `.gitignore` | MODIFY — add logs/ | 1 |
| `tools/graph_engine.py` | NO CHANGES | 0 |
| `tools/graph_builder.py` | NO CHANGES | 0 |
| `tools/daily_analyzer.py` | NO CHANGES | 0 |
| **Total** | | **~680** |

---

## Dependencies to Install

```bash
pip install sendgrid python-dotenv
```

---

## Verification

After implementation:

1. [ ] `python3 tools/neural_dip_evaluator.py --phase decision --dry-run` — runs without error on weekend (exits with "Market closed")
2. [ ] `python3 tools/neural_dip_evaluator.py --phase first_hour --dry-run` — same
3. [ ] `python3 tools/notify.py` (with test function) — sends test email to your inbox
4. [ ] `python3 tools/neural_dip_backtester.py --days 10` — replays 10 days, shows results
5. [ ] `python3 -m pytest tests/test_graph.py -v` — all 93 existing tests still pass
6. [ ] `python3 tools/graph_builder.py --test` — self-test passes (no engine changes)
7. [ ] `python3 tools/trading_calendar.py` — verify get_market_phase() returns correct phase
8. [ ] On Monday at 11:00 AM ET — cron triggers evaluator, email arrives if BUY fires

---

## Implementation Order

1. **Phase 1** (trading_calendar.py) — shared infrastructure, testable immediately
2. **Phase 2** (notify.py) — SendGrid integration, test with a real email
3. **Phase 3** (neural_dip_evaluator.py) — core logic, test with --dry-run
4. **Phase 4** (cron) — 3 entries, test on Monday market open
5. **Phase 5** (backtester) — validate against historical data

Each phase is independently testable. Phase 3 depends on Phase 1+2 being done.
