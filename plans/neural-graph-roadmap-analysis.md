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
| Neural dip evaluator | Graph engine needs extensions (resolve_phase, inject_prices) | **YES** — ~50-100 lines of engine changes |
| Pre-session static neurons | Daily analyzer must have run (graph_state.json exists) | **YES** — with fallback for missing state |
| First-hour breadth (10:30 AM) | Must be run during market hours | **YES** (code can be written + tested on weekends with historical data) |
| Second-hour bounce (11:00 AM) | Must be run during market hours | **YES** (same) |
| SendGrid notifications | SendGrid API key + account setup | **YES** (once you provide API key) |
| Cron scheduling | Machine on during market hours + timezone config | **YES** — must handle ET timezone + market holidays |
| Intraday backtesting | Nothing — 60 days of 5-min data available via yfinance | **YES** |
| Broker API integration | N/A — you said manual | **NOT NEEDED** |
| Paid data providers | N/A — yfinance is sufficient | **NOT NEEDED** |

**Core concept is buildable.** No hard blockers. But operational details (timezone, holidays, error handling, graph engine extensions) add significant work.

---

## 6. Revised Assessment (Post-Verification)

The honest assessment said "premature without real-time data feeds." That was wrong — yfinance delivers near real-time 5-min bars during market hours. `dip_signal_checker.py` proves this works.

However, the initial roadmap was too optimistic about effort:

| Aspect | Initial Claim | Verified Reality |
| :--- | :--- | :--- |
| Core evaluator | ~200 lines | **350-450 lines** (timezone, holiday checks, error handling, 20+ reason functions) |
| Graph engine changes | None needed | **50-100 lines** (resolve_phase, inject_prices, temporal gating) |
| Total new code | ~400 lines | **600-750 lines** production-grade |
| Batch yfinance calls | 2-3 per session | **3-4 per session** (pre-session doesn't call yfinance, but EOD check does) |
| Dependencies | None | **3 dependencies** — daily analyzer must run first, SendGrid key, cron timezone config |

**Revised verdict**: Buildable with existing tools, but it's a multi-phase project, not a weekend spike. The architecture is sound, the data source works, and no paid services are needed. The effort is ~2x what was initially claimed.

---

## 7. Honest Risks (Updated)

| Risk | Likelihood | Mitigation |
| :--- | :--- | :--- |
| yfinance gets rate-limited during market hours | LOW — batch calls are 3-4 per session | Exponential backoff, already used in screener |
| yfinance API changes or breaks | MEDIUM — unofficial API | Pin version, have fallback to daily OHLCV |
| Cron fires on market holiday | HIGH — cron doesn't know calendar | Check `is_trading_day()` at evaluator start, exit early |
| Cron timezone mismatch | HIGH — server may not be in ET | Use explicit ET timezone in cron entry or in evaluator code |
| yfinance down at 10:30 AM | LOW — brief outages possible | Retry once after 2-minute wait. If still down, skip this session with logged warning |
| Daily analyzer didn't run | MEDIUM — user may forget | Fallback: compute static neurons from portfolio.json directly, skip graph_state.json |
| Neural model produces false BUY signals | LOW — same gates as existing dip checker | Backtesting against 60 days validates accuracy |
| Intraday catastrophic not re-checked | MEDIUM — HARD_STOP computed at 9 AM, price drops by 10:30 | Re-compute drawdown from live prices at each phase, not just graph_state.json |
| SendGrid rate limit | LOW — free tier 100/day, we send ~5/day | Monitor usage, upgrade if needed ($19.95/month) |
