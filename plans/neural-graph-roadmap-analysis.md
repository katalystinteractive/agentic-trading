# Analysis: Neural Graph Roadmap — What We Need to Build

**Date**: 2026-03-29 (Sunday)
**Purpose**: Define every prerequisite for the neural firing network and determine what's buildable now vs what's blocked.

---

## 1. Key Finding: yfinance IS Sufficient

The honest assessment assumed we need paid real-time data providers. **That's wrong.** Research shows:

- yfinance delivers **near real-time** (0-2 second delay), NOT 15-20 minute delayed
- **5-minute bars** available with 60-day lookback
- **Batch download**: all 27 tickers in one call, ~2 seconds
- `dip_signal_checker.py` already uses yfinance 5-min bars during market hours — it works

**The neural model needs 3 data points per ticker over 1.5 hours** (open, 10:30, 11:00). That's 2-3 yfinance batch calls. No streaming, no paid provider, no websockets.

This removes the biggest blocker. The infrastructure needed is simpler than assumed.

---

## 2. What We Actually Need to Build

### Prerequisite 1: Persistent Process (Scheduler)
**What**: A process that runs during market hours and triggers neural evaluation at specific times.
**NOT needed**: A daemon running 24/7. Just a scheduler that fires at:
- 9:00 AM ET — pre-session evaluation (static neurons)
- 10:30 AM ET — first-hour breadth evaluation
- 11:00 AM ET — second-hour bounce + decision
- 3:45 PM ET — EOD exit check for unfilled dip sells

**Options**:
- **Cron jobs**: 4 crontab entries calling the neural evaluator at fixed times. Simplest. Works on any machine.
- **Python scheduler**: `schedule` library or `APScheduler` running in a single Python process during market hours.
- **Manual**: You run the evaluator at 10:30 AM yourself (same as current `dip_signal_checker.py` workflow).

**Recommendation**: Start with cron. 4 entries. No new infrastructure.

### Prerequisite 2: Notification Engine (SendGrid Email)
**What**: When a BUY_DIP neuron fires, send you an email with the ticker, entry price, target, stop, and the full firing reason chain.
**You said**: "We can start with SendGrid emails, and I will place these myself."

**Implementation**:
- SendGrid Python SDK (`pip install sendgrid`)
- Single function: `send_dip_alert(ticker, entry, target, stop, reason_chain, regime)`
- Called from the terminal BUY_DIP neuron when it fires
- Email format: plain text or simple HTML with the action + reason chain

**Effort**: ~30 lines. Standard SendGrid integration.

### Prerequisite 3: Neural Graph Engine
**What**: The event-driven firing engine that replaces or extends graph_engine.py for temporal decisions.

**Key insight from research**: We don't need a complex event-driven engine. The dip strategy has exactly **4 evaluation points** (9:00, 10:30, 11:00, 3:45). That's 4 calls to a resolve function, not continuous event streaming.

**Simplified architecture**: Instead of a full neural firing engine with state machines and event loops, we can use the **phased resolution approach** (Approach C from neural-graph-analysis.md):

```python
# Phase 1: Pre-session (9:00 AM) — static neurons
graph = build_dip_neural_graph(portfolio, regime, earnings, dip_kpis)
graph.resolve_phase("pre_session")
# Evaluates: MARKET_OPEN, DIP_VIABLE, NOT_CATASTROPHIC, EARNINGS_CLEAR, HISTORICAL_RANGE

# Phase 2: First hour (10:30 AM) — breadth evaluation
prices_10_30 = yf.download(tickers, period="1d", interval="5m")
graph.inject_prices(prices_10_30)
graph.resolve_phase("first_hour")
# Evaluates: TICKER_DIPPED per ticker, BREADTH_DIP aggregate

# Phase 3: Second hour (11:00 AM) — bounce + decision
prices_11_00 = yf.download(tickers, period="1d", interval="5m")
graph.inject_prices(prices_11_00)
graph.resolve_phase("second_hour")
# Evaluates: TICKER_BOUNCED, BREADTH_BOUNCE, SIGNAL_CONFIRMED
# Evaluates: CANDIDATE (AND gate), RANKER, BUY_DIP

# If BUY_DIP fired → send email notification
```

This uses the existing graph engine with a `resolve_phase()` method that only evaluates neurons tagged for that phase. No event loops, no state machines, no continuous polling.

### Prerequisite 4: Intraday Price Injection
**What**: A function that fetches 5-min bars and injects them into graph nodes.

**Implementation**: Already exists — `dip_signal_checker.py` does exactly this. Extract the yfinance fetch into a reusable function.

### Prerequisite 5: Historical Intraday Backtesting
**What**: Test the neural model against the last 60 days of 5-min data.

**Implementation**: Already partially exists — `dip_strategy_simulator.py` backtests with 5-min bars. Extend to test the neural firing sequence (pre-session → first-hour → second-hour → decision) against historical data.

**Limitation**: 60-day lookback is the max for 5-min bars via yfinance. For longer backtesting, fall back to daily OHLCV approximation (which we already built in the simulation side-channel).

---

## 3. Roadmap — Build Order

### Phase 1: Neural Dip Evaluator (standalone script)
**What**: `tools/neural_dip_evaluator.py` — a script that runs the 4-phase neural evaluation.
**Inputs**: portfolio.json, yfinance 5-min bars, graph nodes (dip_viable, catastrophic, verdict)
**Output**: JSON result with fired/unfired neurons and reason chain. If BUY_DIP fired, includes: ticker, entry, target, stop, full firing path.
**Run manually**: `python3 tools/neural_dip_evaluator.py` at 10:30 or 11:00 AM.
**No cron, no email** — just the core decision logic. You read the output.
**Effort**: ~200 lines. Uses existing graph_engine for resolution, existing yfinance patterns for data.

### Phase 2: SendGrid Email Notifications
**What**: When the evaluator produces a BUY_DIP decision, send email.
**Inputs**: evaluator output
**Output**: email to your inbox with ticker, price, action, reason chain
**Effort**: ~50 lines. SendGrid SDK + email template.
**Config**: SendGrid API key in .env, recipient email in settings.

### Phase 3: Cron Scheduling
**What**: 4 crontab entries that call the evaluator at fixed times during market hours.
**Entries**:
```
00 09 * * 1-5  cd /path/to/agentic-trading && python3 tools/neural_dip_evaluator.py --phase pre_session
30 10 * * 1-5  cd /path/to/agentic-trading && python3 tools/neural_dip_evaluator.py --phase first_hour
00 11 * * 1-5  cd /path/to/agentic-trading && python3 tools/neural_dip_evaluator.py --phase decision
45 15 * * 1-5  cd /path/to/agentic-trading && python3 tools/neural_dip_evaluator.py --phase eod_check
```
**Effort**: 4 lines in crontab. The evaluator handles phase routing internally.

### Phase 4: Intraday Backtesting
**What**: Replay 60 days of 5-min data through the neural evaluator to validate firing accuracy.
**Inputs**: historical 5-min bars (yfinance, 60-day lookback)
**Output**: per-day results — did the neural model fire correctly? What would the P/L have been?
**Comparison**: compare neural model decisions against the existing `dip_strategy_simulator.py` results.
**Effort**: ~150 lines. Replay loop + comparison logic.

### Phase 5: Extend to Other Strategies
**What**: Apply the neural firing pattern to support-level entries, exit decisions, risk management.
**When**: After Phase 1-4 prove the pattern works for dip decisions.
**Effort**: TBD — depends on which strategies benefit from temporal awareness.

---

## 4. What Stays the Same

- **Daily analyzer** — keeps running as-is. The snapshot graph produces the dashboard, action items, broker reconciliation. Nothing changes.
- **Bullet recommender** — still produces support-level orders. Not affected.
- **Portfolio manager** — you still record fills/sells manually.
- **dip_signal_checker.py** — still works. The neural evaluator can replace it eventually, but it's not deleted until the neural model is proven.

The neural model runs **alongside** the existing system, not instead of it. It adds temporal decision-making for the dip strategy without touching anything else.

---

## 5. What's Blocked vs What's Buildable Now

| Component | Blocked By | Buildable Now? |
| :--- | :--- | :--- |
| Neural dip evaluator | Nothing — uses existing graph engine + yfinance | **YES** |
| Pre-session static neurons | Nothing — same as current graph nodes | **YES** |
| First-hour breadth (10:30 AM) | Must be run during market hours | **YES** (code can be written + tested on weekends with historical data) |
| Second-hour bounce (11:00 AM) | Must be run during market hours | **YES** (same) |
| SendGrid notifications | SendGrid API key needed | **YES** (once you provide API key) |
| Cron scheduling | Machine that's on during market hours | **YES** (your dev machine or any server) |
| Intraday backtesting | Nothing — 60 days of 5-min data available via yfinance | **YES** |
| Broker API integration | N/A — you said manual | **NOT NEEDED** |
| Paid data providers | N/A — yfinance is sufficient | **NOT NEEDED** |

**Nothing is blocked.** Every component is buildable with what we have.

---

## 6. Revised Assessment

The honest assessment said "the neural model is premature without real-time data feeds." That was based on the assumption that yfinance couldn't deliver intraday data during market hours. **That assumption was wrong.**

yfinance delivers near real-time 5-min bars. `dip_signal_checker.py` already proves this works. The neural model needs 2-3 batch calls at fixed times, not continuous streaming.

**Revised verdict**: The neural model is buildable NOW with:
- Existing graph engine (phased resolution, not event loops)
- Existing yfinance patterns (batch 5-min bars)
- Cron for scheduling (4 entries)
- SendGrid for notifications (30 lines)
- ~200 lines for the core neural evaluator

The total new code is ~400 lines. No new infrastructure, no paid services (beyond SendGrid which is free tier for low volume), no persistent daemon.

---

## 7. Honest Risks

| Risk | Likelihood | Mitigation |
| :--- | :--- | :--- |
| yfinance gets rate-limited during market hours | LOW — batch calls are 2-3 per session | Exponential backoff, already used in screener |
| yfinance API changes or breaks | MEDIUM — it's an unofficial API | Pin version, have fallback to daily OHLCV |
| Cron doesn't fire (machine asleep/off) | MEDIUM — depends on your machine | Use a cloud VPS for $5/month, or just run manually |
| Neural model produces false BUY signals | LOW — same gates as existing dip checker | Backtesting against 60 days validates accuracy |
| Email notification delayed | LOW — SendGrid is reliable | Add timestamp to email body so you know when signal fired |
