# Analysis: Notification System Upgrade

**Date**: 2026-03-31 (Tuesday)
**Purpose**: Two upgrades — (1) dip evaluator sends "nothing to report" emails at both time checks, (2) new 5-minute price proximity monitor sends alerts when price approaches placed limit orders.

---

## Part 1: Dip Evaluator "Nothing to Report" Emails

### Current State (FACT — verified)

**FACT**: `neural_dip_evaluator.py` runs at two cron times:
- 17:30 local (10:30 AM ET) — `--phase first_hour` (breadth check)
- 18:00 local (11:00 AM ET) — `--phase decision` (buy/no-buy)

**FACT**: Emails are only sent when the `BUY_DIP` neuron fires (line 803-807). If no dip signal → no email. The user gets zero notification that the check ran.

**FACT**: `send_dip_alert()` in `notify.py` (line 22) is designed for positive alerts only. `send_summary_email()` (line 94) is generic and can send any subject/body.

### Proposed Fix

After each phase completes with no actionable signals, call `send_summary_email()` with a "nothing to report" message:

**Phase 1 (first_hour)**: After breadth evaluation, if no tickers qualify:
```
Subject: "Dip Check 10:30 — No Signal"
Body: "Breadth: X/Y tickers dipped (Z%). Threshold: 50%. No dip signal today.
       Regime: {regime}, VIX: {vix}"
```

**Phase 2 (decision)**: After decision evaluation, if no BUY signals:
```
Subject: "Dip Check 11:00 — No Buys"
Body: "Breadth confirmed: X dipped, Y bounced. No tickers passed all gates.
       [optional: list of tickers that came close but failed a gate]"
```

**Phase 3 (eod_check)**: After end-of-day check, if no unfilled same-day exits:
```
Subject: "Dip EOD 3:45 — No Unfilled Exits"
Body: "No same-day dip exits were left unfilled today."
```

**Integration point**: All three phases have the data available. Phase 1 has breadth/dip counts in scope. Phase 2's bounce count lives inside the decision graph state — extract it from the graph or from the `fh_state` cache. Phase 3 simply checks unfilled sell orders.

---

## Part 2: 5-Minute Price Proximity Monitor

### Requirements

1. Check every 5 minutes during market hours (9:30 AM - 4:00 PM ET, Mon-Fri)
2. Load all placed limit orders from `portfolio.json`
3. Fetch live prices for tickers with placed orders
4. Alert when price is within 2% of a limit order (APPROACHING) or 1% of a limit order (IMMINENT)
5. Suppress duplicate alerts — alert once per threshold crossing, suppress until price moves away

### Current Infrastructure (FACT — verified)

**FACT**: `portfolio.json` pending orders have `placed: true/false` flag. Only `placed: true` orders are live on the broker.

**FACT**: `notify.py::send_summary_email(subject, body)` can send any email. No new email function needed.

**FACT**: No existing tool monitors prices in real-time against pending orders. The closest is `neural_support_evaluator.py` which checks at 8:30 AM only (not continuous).

**FACT**: `trading_calendar.py` has `get_market_phase()` (returns CLOSED/PRE_MARKET/FIRST_HOUR/CONFIRMATION/REGULAR/AFTER_HOURS) and `is_trading_day(d)`. No `is_market_open()` function exists. The proximity monitor should use `get_market_phase()` — if result is `"CLOSED"` or `"PRE_MARKET"` or `"AFTER_HOURS"`, exit early.

### Proposed New Tool: `tools/order_proximity_monitor.py`

**Core logic**:
1. Load `portfolio.json` → extract all `placed: true` orders
2. Fetch live prices via yfinance (batch download for efficiency)
3. For each order, compute `distance_pct = abs(price - order_price) / order_price * 100`
4. For BUY orders: alert when price is ABOVE the buy price and within threshold (approaching from above)
5. For SELL orders: alert when price is BELOW the sell price and within threshold (approaching from below)
6. Load suppression state from `data/proximity_alerts_state.json`
7. Only send alert if this (ticker, order_price, threshold_level) hasn't been alerted since last reset
8. Save updated suppression state

**Suppression logic**:
```python
state = {
    "BBAI:BUY:3.31": {"level": "APPROACHING", "alerted_at": "2026-03-31T10:35:00"},
    "CIFR:SELL:15.80": {"level": "IMMINENT", "alerted_at": "2026-03-31T14:20:00"},
}
```
- Alert fires when crossing INTO a threshold (e.g., distance drops from 3% to 1.8% → APPROACHING)
- Alert fires again when crossing to tighter threshold (e.g., 1.8% → 0.9% → IMMINENT)
- Suppressed if already alerted at same or tighter level
- Reset when price moves BACK beyond the outer threshold (>2%) — removes from state

**Email format** (plain-text aligned — `send_summary_email` sends `plain_text_content` only, no HTML):
```
Subject: "APPROACHING: BBAI BUY @ $3.31 — price $3.37 (1.8%)"
Body:
  BBAI   BUY   $3.31  →  $3.37   1.8%  APPROACHING
  CIFR   SELL  $15.80 →  $15.50  1.9%  APPROACHING

[If multiple alerts in same check, batch into one email]
```

Plain-text aligned columns (no markdown tables — they render as raw `|` in email). Use fixed-width spacing or simple `→` arrows.

**Batch email**: If multiple tickers trigger in the same 5-minute check, send ONE email with all alerts in a table, not separate emails per ticker.

**Same-ticker BUY + SELL**: A ticker can have both a placed BUY and a placed SELL (e.g., NU has BUY @ $13.41 and SELL @ $16.75). The monitor checks each order independently — the same ticker may appear twice in one alert email (once approaching its BUY, once approaching its SELL). The suppression key format `"TICKER:SIDE:PRICE"` handles this naturally.

### Cron Schedule

```cron
# Price proximity monitor — every 5 min during market hours (Mon-Fri)
# Market hours: 9:30 AM - 4:00 PM ET = 16:30 - 23:00 local (ET+7)
*/5 16-22 * * 1-5 cd /Users/kamenkamenov/agentic-trading && python3 tools/order_proximity_monitor.py >> data/proximity_monitor.log 2>&1
```

**Note**: Cron can't express "start at :30" for the first hour. Options:
- Run every 5 min from 16:00-23:00 (adds 30 min of pre-market checks — harmless, yfinance returns last close)
- Have the script itself check if market is open and exit early if not

The script-level market hours check is cleaner — run every 5 min 16:00-23:00 and let the script skip non-market times.

### Data Freshness

**FACT**: yfinance `download(period="1d", interval="5m")` returns intraday data during market hours (codebase uses `interval="5m"` consistently — no `"1m"` usage). For the current price, `hist["Close"].iloc[-1]` gives the latest 5-minute bar. At 5-minute polling intervals, this resolution is sufficient.

**Alternative**: `yf.Ticker(tk).fast_info["lastPrice"]` is faster for single price lookups but less reliable. Batch download with `yf.download(tickers, period="1d", interval="5m")` is more efficient for 15+ tickers.

### Error Handling

The proximity monitor runs every 5 minutes in production. yfinance failures (network, rate limits, stale data) must not crash the script or produce phantom alerts.

**Required**: Wrap the yfinance download in `try/except`. On failure:
- Log the error to stderr
- Skip the entire check cycle (do not compare stale prices against thresholds)
- Do NOT clear suppression state (preserve it for next successful run)
- If 3+ consecutive failures, send a single "monitoring degraded" email alert

### State Cleanup

Suppression state in `data/proximity_alerts_state.json` can accumulate stale entries over weekends/holidays. On startup:
- Remove entries older than 24 hours (covers overnight + weekend gap)
- This ensures Monday's first run starts fresh without stale Friday alerts

---

## Part 3: Files

| File | Action | Est. Lines |
| :--- | :--- | :--- |
| `tools/neural_dip_evaluator.py` | Add "nothing to report" email after all 3 phases (first_hour, decision, eod_check) | ~25 |
| `tools/order_proximity_monitor.py` | **NEW** — price proximity checker with suppression, error handling, state cleanup | ~140 |
| `cron_neural_trading.txt` | Add proximity monitor cron entry, no changes to dip entries | ~2 |
| **Total** | | **~167** |

**NOT modified**: `notify.py` (existing `send_summary_email` with plain text is sufficient — no HTML needed), `portfolio_manager.py`, `daily_analyzer.py`.

---

## Part 4: Open Questions (Resolved)

1. **Approaching threshold**: 2% APPROACHING, 1% IMMINENT — agreed
2. **Repeat suppression**: Alert once per threshold crossing, suppress until price moves beyond 2% — agreed
3. **Existing support notification**: Keep as-is (separate daily summary at 8:30 AM) — agreed
4. **Dip "nothing to report"**: All 3 phases (10:30 AM, 11:00 AM, 3:45 PM) send email even when empty — agreed
