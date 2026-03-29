# Requirements Analysis: Neural Dip Evaluator

**Date**: 2026-03-29 (Sunday)
**Purpose**: Go through every requirement for the neural dip evaluator. For each: what exists, what needs building, what design decisions must be answered.

---

## Requirement 1: Data Feed ✅ CLEARED

yfinance 5-min bars, batch download for all 27 tickers in ~2 seconds. `dip_signal_checker.py` proves this works during market hours. Near real-time (0-2 second delay on completed bars).

**No work needed.**

---

## Requirement 2: Graph Engine Extensions

### What exists:
- `resolve()` — resolves ALL nodes in one pass. Works, tested.
- `propagate_signals()` — diffs current vs prev state.
- `load_prev_state()` — loads previous run's values.

### What doesn't exist:
- `resolve_phase()` — resolve only nodes tagged for a specific phase
- `inject_prices()` — update leaf node values after graph is built
- Phase tagging on nodes

### Design decision:

**The simplest approach that doesn't break existing code**: Don't modify `graph_engine.py` at all.

Instead, build **separate graphs per phase** in the neural evaluator:

```python
# Phase 1: Pre-session graph (static neurons only)
pre_graph = build_pre_session_graph(portfolio, graph_state)
pre_graph.resolve()

# Phase 2: First-hour graph (injects 10:30 prices into leaf nodes)
fh_graph = build_first_hour_graph(portfolio, prices_10_30, pre_graph.get_state())
fh_graph.resolve()

# Phase 3: Decision graph (injects 11:00 prices + breadth/bounce results)
decision_graph = build_decision_graph(portfolio, prices_11_00, fh_graph.get_state())
decision_graph.resolve()
```

Each phase builds a fresh graph with different leaf values. The previous phase's state feeds as `prev_state` to the next phase for signal propagation. **Zero changes to graph_engine.py. All 93 existing tests pass unchanged.**

**Tradeoff**: Builds 3 graphs instead of 1. But each graph is small (~50-100 nodes for the dip strategy, not 429 for the full daily analyzer). Resolution is <10ms per graph.

---

## Requirement 3: Market Calendar Awareness

### What exists:
- `trading_calendar.py` — `is_trading_day()`, `last_trading_day()`, `as_of_date_label()`
- Holiday list covers 2025-2027 (30 holidays)

### What doesn't exist:
- Early close handling (day before Thanksgiving — market closes at 1 PM ET)
- Market hours constants (9:30 AM, 4:00 PM ET)

### What needs building:
Add to `trading_calendar.py`:

```python
MARKET_OPEN_ET = (9, 30)   # 9:30 AM ET
MARKET_CLOSE_ET = (16, 0)  # 4:00 PM ET

_EARLY_CLOSES = {
    date(2025, 11, 28): (13, 0),  # Day after Thanksgiving
    date(2025, 12, 24): (13, 0),  # Christmas Eve
    date(2026, 11, 27): (13, 0),
    date(2026, 12, 24): (13, 0),
    date(2027, 11, 26): (13, 0),
    date(2027, 12, 24): (13, 0),
}

def market_close_time(d=None):
    """Return close time for given day (handles early closes)."""
    d = d or date.today()
    return _EARLY_CLOSES.get(d, MARKET_CLOSE_ET)
```

**Effort**: ~15 lines added to existing file.

### How the evaluator uses it:
```python
if not is_trading_day():
    print("Market closed today. Skipping.")
    sys.exit(0)
```

First line of the evaluator. Cron fires Monday-Friday, evaluator exits immediately on holidays.

---

## Requirement 4: Timezone Handling

### What exists:
`dip_signal_checker.py` has complete timezone handling:
- `pytz.timezone("US/Eastern")` for ET
- `_market_time_to_utc_hour(et_hour, et_minute)` — converts ET to UTC, handles EDT/EST automatically
- `_get_market_phase()` — detects PRE_MARKET, FIRST_HOUR, CONFIRMATION, etc.

### What needs building:
**Nothing new.** Extract these functions into a shared module (or just import from `dip_signal_checker`).

### Design decision:
**Extract to `trading_calendar.py`** (where they logically belong) or create `tools/market_time.py`. The functions are 25 lines total:

```python
# In trading_calendar.py (add to existing file):
import pytz
ET = pytz.timezone("US/Eastern")

def get_market_phase():
    """Return current market phase: PRE_MARKET, FIRST_HOUR, CONFIRMATION, etc."""
    now = datetime.now(ET)
    h, m = now.hour, now.minute
    if not is_trading_day():
        return "CLOSED"
    if h < 9 or (h == 9 and m < 30):
        return "PRE_MARKET"
    elif (h == 9 and m >= 30) or (h == 10 and m < 30):
        return "FIRST_HOUR"
    elif h == 10 and m >= 30:
        return "CONFIRMATION"
    elif h < 16:
        return "REGULAR"
    else:
        return "AFTER_HOURS"
```

**Cron timezone**: The evaluator checks its own phase regardless of what timezone cron runs in. If cron fires at 14:30 UTC (= 10:30 ET), the evaluator calls `get_market_phase()` → "CONFIRMATION" → proceeds. If cron fires at wrong time, evaluator detects wrong phase and exits.

**Effort**: ~25 lines, added to existing file.

---

## Requirement 5: Static Neuron Data Source

### What exists:
- `graph_state.json` — written by daily analyzer, contains regime, verdicts, catastrophic, dip_viable per ticker
- `portfolio.json` — positions, pending orders, capital
- `earnings_gate.py` — check earnings proximity

### Design decision — can the evaluator work WITHOUT daily analyzer having run?

**YES, with a degraded mode.** The evaluator can compute most static neurons from live data:

| Neuron | From graph_state.json | Fallback (no daily analyzer) |
| :--- | :--- | :--- |
| REGIME | regime field | Compute from VIX + indices (same as daily analyzer) — adds ~5s |
| NOT_CATASTROPHIC | catastrophic field | Compute from avg_cost vs live price — simple arithmetic |
| EARNINGS_CLEAR | earnings_gate field | Call `check_earnings_gate(ticker)` directly — adds ~5s for 27 tickers |
| DIP_VIABLE | dip_viable field | "UNKNOWN" — can't simulate without multi-period data |
| VERDICT | verdict field | "UNKNOWN" — can't compute full verdict without technical data |
| HISTORICAL_RANGE | Not in graph_state | Always compute fresh from 1-month yfinance data |

**Strategy**: Try graph_state.json first. If missing or stale (>24 hours old), compute what we can, mark the rest UNKNOWN. UNKNOWN neurons don't block — they just don't provide the simulation-backed gate. The hardcoded thresholds (range ≥ 3%, recovery ≥ 60%) still apply as fallback.

**Effort**: ~30 lines for the fallback logic.

---

## Requirement 6: Notification Engine (SendGrid)

### What exists:
Nothing. No email integration, no .env pattern, no notification mechanism in the codebase.

### What needs building:
```python
# tools/notify.py (~40 lines)
import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

def send_dip_alert(ticker, entry_price, target, stop, reason_chain,
                   regime, budget, recipient=None):
    """Send email notification when BUY_DIP neuron fires."""
    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        print("*Warning: SENDGRID_API_KEY not set. Skipping email.*")
        return False

    recipient = recipient or os.environ.get("ALERT_EMAIL")
    if not recipient:
        print("*Warning: ALERT_EMAIL not set. Skipping email.*")
        return False

    subject = f"DIP ALERT: BUY {ticker} at ${entry_price:.2f}"
    body = f"""
Ticker: {ticker}
Entry:  ${entry_price:.2f}
Target: ${target:.2f} (+4%)
Stop:   ${stop:.2f} (-3%)
Budget: ${budget:.0f}
Regime: {regime}

REASON CHAIN:
{reason_chain}

-- Sent by Neural Dip Evaluator at {datetime.now().strftime('%H:%M:%S ET')}
"""
    message = Mail(
        from_email="alerts@yourdomain.com",
        to_emails=recipient,
        subject=subject,
        plain_text_content=body)

    try:
        sg = SendGridAPIClient(api_key)
        sg.send(message)
        return True
    except Exception as e:
        print(f"*Warning: email send failed: {e}*")
        return False
```

### Setup needed from you:
1. SendGrid account (free tier: 100 emails/day)
2. API key → set as `SENDGRID_API_KEY` environment variable
3. Your email → set as `ALERT_EMAIL` environment variable
4. Verified sender email in SendGrid

**Effort**: ~40 lines. Standard integration.

---

## Requirement 7: Scheduling

### What needs building:
4 cron entries. The evaluator handles phase detection internally — cron just triggers it.

```bash
# In crontab (adjust timezone for your server):
# Pre-session check (9:00 AM ET)
0 9 * * 1-5 cd /Users/kamenkamenov/agentic-trading && python3 tools/neural_dip_evaluator.py --phase pre_session 2>&1 >> logs/neural_dip.log

# First-hour breadth (10:30 AM ET)
30 10 * * 1-5 cd /Users/kamenkamenov/agentic-trading && python3 tools/neural_dip_evaluator.py --phase first_hour 2>&1 >> logs/neural_dip.log

# Decision time (11:00 AM ET)
0 11 * * 1-5 cd /Users/kamenkamenov/agentic-trading && python3 tools/neural_dip_evaluator.py --phase decision 2>&1 >> logs/neural_dip.log

# EOD exit check (3:45 PM ET)
45 15 * * 1-5 cd /Users/kamenkamenov/agentic-trading && python3 tools/neural_dip_evaluator.py --phase eod_check 2>&1 >> logs/neural_dip.log
```

**Holiday handling**: The evaluator's first line is `if not is_trading_day(): sys.exit(0)`. Cron fires on all weekdays, evaluator exits silently on holidays.

**Timezone**: If your machine is in ET, the cron times above are correct. If not, adjust. The evaluator double-checks by calling `get_market_phase()`.

**Logging**: Append to `logs/neural_dip.log` so you can review what happened.

**Effort**: 4 lines in crontab. Create `logs/` directory.

---

## Requirement 8: Intraday Backtesting

### What exists:
- `dip_strategy_simulator.py` — backtests with 5-min bars, but doesn't test the neural firing sequence
- yfinance 60-day lookback for 5-min data

### What needs building:
A replay script that feeds historical 5-min bars through the neural evaluator's 3-phase sequence and checks if BUY_DIP would have fired, and what the P/L would have been.

```python
# tools/neural_dip_backtester.py (~150 lines)
for each trading day in last 60 days:
    # Phase 1: pre-session (use that day's portfolio state)
    # Phase 2: first-hour (feed 9:30-10:30 bars)
    # Phase 3: decision (feed 10:30-11:00 bars)
    # Record: did BUY_DIP fire? For which tickers? What was actual P/L by EOD?
```

**Limitation**: 60-day lookback only. For longer backtesting, fall back to the daily OHLCV dip side-channel we already built in the surgical simulator.

**Effort**: ~150 lines. Reuses the neural evaluator's graph-building functions.

---

## Requirement 9: Error Handling

### What exists:
- `try/except` with silent `continue` in dip_signal_checker
- Empty dict fallback in daily_analyzer's yfinance fetcher

### What needs building:
Structured error handling for the neural evaluator:

```python
def fetch_intraday(tickers, retries=1):
    """Fetch 5-min bars with retry on failure."""
    for attempt in range(retries + 1):
        try:
            data = yf.download(tickers, period="1d", interval="5m", progress=False)
            if data.empty:
                if attempt < retries:
                    time.sleep(3)
                    continue
                return None
            return data
        except Exception as e:
            if attempt < retries:
                time.sleep(3)
                continue
            log(f"yfinance failed after {retries + 1} attempts: {e}")
            return None
```

**Strategy**: 1 retry with 3-second delay. If both fail, skip this phase and log. Don't crash — the next cron trigger (30 min later) will try again.

**Effort**: ~20 lines.

---

## Requirement 10: Testing

### What needs building:
Test analysis and test plan (following the mandatory process: analysis → plan → implement → verify).

**Test categories needed**:
- Neuron firing logic (AND-gates, threshold comparisons)
- Phase sequencing (pre-session → first-hour → decision)
- Breadth aggregation (50% threshold across N tickers)
- Reason chain composition (firing path traces)
- Market calendar checks (holiday, weekend, early close)
- Timezone handling (ET conversion, phase detection)
- Error recovery (yfinance down, missing graph_state)
- Backtesting accuracy (neural model vs dip_signal_checker on same data)

**Effort**: Requires its own analysis → plan → implement cycle. Estimate ~80-100 test cases.

---

## Summary: All 10 Requirements

| # | Requirement | Status | Effort | Blocked? |
| :--- | :--- | :--- | :--- | :--- |
| 1 | Data feed (yfinance 5-min) | ✅ CLEARED | 0 | NO |
| 2 | Graph engine extensions | Build separate graphs per phase (no engine changes) | ~0 new lines | NO |
| 3 | Market calendar | Add early closes + market hours constants | ~15 lines | NO |
| 4 | Timezone handling | Extract from dip_signal_checker to shared module | ~25 lines | NO |
| 5 | Static neuron data | graph_state.json + fallback to live computation | ~30 lines | NO |
| 6 | SendGrid notifications | New `tools/notify.py` | ~40 lines | NEED API key |
| 7 | Cron scheduling | 4 crontab entries + logs directory | 4 lines | NO |
| 8 | Intraday backtesting | New `tools/neural_dip_backtester.py` | ~150 lines | NO |
| 9 | Error handling | Retry + fallback pattern | ~20 lines | NO |
| 10 | Testing | Requires own analysis→plan→implement cycle | ~100 test cases | NO |

**Total new code (excluding tests)**: ~280 lines across 3-4 files + the core neural evaluator (~350-450 lines).

**Grand total**: ~630-730 lines of production code + ~200 lines of tests.

---

## Design Decisions Summary

| # | Decision | Recommendation | Rationale |
| :--- | :--- | :--- | :--- |
| 1 | Graph engine changes? | NO — build separate graphs per phase | Don't break 93 passing tests |
| 2 | Signal carryover between phases? | YES — prev phase state = next phase prev_state | Enables cross-phase reason chains |
| 3 | Fallback when no graph_state? | Compute what we can, mark rest UNKNOWN | Don't block on missing daily analyzer |
| 4 | Threshold configurability? | YES — read from config dict, not hardcoded | Easy to tune from backtesting |
| 5 | Cron timezone? | Evaluator checks its own phase regardless of cron tz | Self-correcting |
| 6 | Holiday handling? | `is_trading_day()` check at evaluator start | Exit immediately, don't waste API calls |
| 7 | Retry strategy? | 1 retry, 3-second delay, then skip | Don't block; next cron trigger retries |
| 8 | SendGrid config? | Environment variables (SENDGRID_API_KEY, ALERT_EMAIL) | Standard pattern, .env file |
| 9 | Early close handling? | Add to trading_calendar.py | Shared by all tools |
| 10 | UNKNOWN neuron semantics? | UNKNOWN = pass-through (don't block, don't confirm) | Conservative: hardcoded thresholds still apply as fallback |
| 11 | Pre-session phase purpose? | DROP — daily analyzer already covers this | Reduce to 3 cron entries (10:30, 11:00, 15:45) |

---

## Verification Findings (Post-Verification)

### Critical Gaps Fixed

**1. Backtesting requires ALL tickers' 5-min data for breadth computation**

The initial analysis assumed breadth could be computed from per-ticker data. Wrong — breadth is a CROSS-TICKER aggregation ("did ≥50% of tickers dip?"). The backtester must:
- Download 5-min bars for ALL 27 tickers for ALL 60 days
- yfinance batch download handles this: `yf.download(all_27, period="60d", interval="5m")` — one call, returns ~126K data points
- Cache locally to avoid re-downloading: save to `data/backtest/intraday_5min_cache.pkl`
- Replay day-by-day, computing breadth per timestamp across all tickers

**Effort revised**: 150 → 200 lines (add caching + cross-ticker aggregation logic).

**2. UNKNOWN neuron semantics defined**

When a static neuron (DIP_VIABLE, VERDICT) returns UNKNOWN:
- **UNKNOWN = pass-through** — the neuron neither confirms nor blocks
- The hardcoded fallback thresholds (range ≥ 3%, recovery ≥ 60%) still apply
- BUY_DIP CAN fire with UNKNOWN neurons, but the reason chain notes "DIP_VIABLE: UNKNOWN (no simulation data)"
- This matches current behavior: the dip watchlist works today without graph_state.json

**3. SendGrid response validation**

Updated `send_dip_alert()` to check response status:
```python
response = sg.send(message)
if response.status_code not in (200, 202):
    print(f"*Warning: SendGrid returned {response.status_code}*")
    return False
```
Also: `from_email` must be an environment variable, not hardcoded. Add `SENDGRID_FROM_EMAIL` to .env.

### Moderate Gaps Fixed

**4. Timezone functions are private (_underscore prefix)**

`_market_time_to_utc_hour()` and `_get_market_phase()` in dip_signal_checker.py start with underscore (private). Solution: add public wrapper functions to `trading_calendar.py` that call the same logic. Don't refactor dip_signal_checker — it still works as-is.

**5. Pre-session phase dropped**

The 9:00 AM pre-session phase is redundant — the daily analyzer runs at session start and computes regime, verdicts, catastrophic. The neural evaluator reads these from graph_state.json.

Revised cron schedule: **3 entries, not 4**:
- 10:30 AM ET — first-hour breadth
- 11:00 AM ET — second-hour bounce + decision
- 3:45 PM ET — EOD exit check

**6. Partial yfinance data handling**

Updated error pattern to detect missing tickers:
```python
data = yf.download(tickers, period="1d", interval="5m")
if len(tickers) > 1:
    available = [tk for tk in tickers if tk in data["Close"].columns]
    missing = [tk for tk in tickers if tk not in available]
    if missing:
        log(f"Missing tickers: {missing}")
```

### Minor Gaps Fixed

**7. Node count corrected**: 50-100 per phase → 222 nodes (8 per ticker × 27 + 6 market). Still <10ms resolution.

**8. macOS sleep risk documented**: If Mac sleeps at 10:30 AM, cron misses. Mitigation: use `caffeinate` during market hours, or run on a server.

### Updated Totals

| Aspect | Initial | Corrected |
| :--- | :--- | :--- |
| Cron entries | 4 | **3** (pre-session dropped) |
| Nodes per phase | 50-100 | **~222** |
| Backtester lines | 150 | **200** (add caching + cross-ticker) |
| Grand total code | 630-730 | **680-780** |
| Dependencies to add | sendgrid | **sendgrid, python-dotenv** |
| .env variables needed | 2 (API_KEY, EMAIL) | **3** (+ SENDGRID_FROM_EMAIL) |
