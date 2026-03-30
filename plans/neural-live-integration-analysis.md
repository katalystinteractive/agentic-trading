# Analysis: Neural Network Live Integration — Both Strategies Running Automatically

**Date**: 2026-03-29 (Sunday, 9:54 PM local / 2:54 PM ET)
**Purpose**: Design how the neural network integrates into the live trading system so both strategies (same-day dip + support-based) run automatically and notify the user to take action.

**Honesty note**: Every claim labeled FACT (verified), ESTIMATE, or PROPOSED.

---

## 1. What Exists Today (FACT — verified against code)

### 1.1 Current automation: NONE

**FACT**: There are no cron jobs, no launchd agents, no scheduled tasks. Everything is manual — the user runs commands by hand.

**FACT**: The current daily flow is:
1. User manually runs `python3 tools/daily_analyzer.py` (morning briefing)
2. User manually runs `python3 tools/neural_dip_evaluator.py --phase first_hour` at 10:30 AM
3. User manually runs `python3 tools/neural_dip_evaluator.py --phase decision` at 11:00 AM
4. If BUY_DIP fires, email goes to user → user manually places order in broker
5. User manually runs `--phase eod_check` at 3:45 PM

### 1.2 Two separate decision systems

**FACT**: Two independent graph systems exist:
- **Daily graph** (`graph_builder.py`) — position state, verdict, reconciliation. Used by `daily_analyzer.py`.
- **Neural graph** (`neural_dip_evaluator.py`) — intraday dip detection, 6-layer network. Separate from daily graph.

These don't communicate. The daily graph has a `{tk}:dip_viable` node but it's a static check, not connected to the neural network.

### 1.3 Notification infrastructure

**FACT**: `notify.py` has two functions:
- `send_dip_alert(ticker, entry, target, stop, reason_chain, regime, budget)` — fires when BUY_DIP neuron activates
- `send_summary_email(subject, body)` — generic notification (added in Phase 5)

Both use SendGrid. Requires `SENDGRID_API_KEY`, `ALERT_EMAIL`, `SENDGRID_FROM_EMAIL` env vars.

### 1.4 Neural profiles exist for both strategies

**FACT**: The neural network has produced:
- `data/ticker_profiles.json` — dip strategy profiles (19 tickers with per-ticker dip/target/stop/breadth thresholds)
- `data/synapse_weights.json` — learned synapse weights (40 connections)
- `data/neural_support_candidates.json` — support strategy top 30 (with per-ticker sell target, stop, pool, bullets)

### 1.5 What the user currently does NOT get notified about

**FACT**: The support strategy has NO live evaluation component. The neural support discoverer finds optimal parameters via backtest, but there's no code that:
- Monitors live prices against support levels
- Fires a notification when a support level is approaching
- Recommends "place a buy order for CIFR at $X with Y shares"

The dip strategy HAS live evaluation (neural_dip_evaluator.py phases), but the support strategy is backtest-only.

---

## 2. What the Integrated System Needs

### 2.1 Two operating modes, one notification channel

```
MODE 1: Same-Day Dip (intraday, 3 phases)
  10:30 AM → first_hour: breadth check, cache state
  11:00 AM → decision: bounce check, fire BUY_DIP, email alert
  3:45 PM  → eod_check: unfilled same-day exits

MODE 2: Support Strategy (daily, 1 phase)
  Pre-market or 9:00 AM → support_eval: check which tickers are near
  support levels, recommend orders, email alert

SHARED:
  notify.py → email channel for both modes
  portfolio.json → single source of truth for positions/orders
  Weekly re-optimization → updates profiles for both strategies
```

### 2.2 What "support strategy live evaluation" means

The support strategy doesn't need intraday phases like the dip strategy. It needs a daily check:

1. Load neural support profiles (`data/neural_support_candidates.json`)
2. For each ticker in the top 30 (or user's watchlist):
   - Get current price (yfinance)
   - Get wick-adjusted support levels (from cached wick analysis)
   - Check: is price within X% of a support level?
   - Check: does the neural profile say this ticker should use $500 pool / 3 bullets?
3. If a buy opportunity exists:
   - Compute order: price, shares, pool allocation per neural profile
   - Email: "SUPPORT BUY: CIFR at $X, Y shares, $500 pool, target sell at +10%"

This is similar to what `bullet_recommender.py` does, but with neural-optimized parameters instead of fixed defaults.

### 2.3 What needs to be automated via cron

| Time (ET) | Job | Tool | Strategy |
| :--- | :--- | :--- | :--- |
| 8:30 AM | Daily briefing + support evaluation | `daily_analyzer.py` + support evaluator | Both |
| 10:30 AM | First-hour breadth check | `neural_dip_evaluator.py --phase first_hour` | Dip |
| 11:00 AM | Dip decision + email | `neural_dip_evaluator.py --phase decision` | Dip |
| 3:45 PM | EOD check | `neural_dip_evaluator.py --phase eod_check` | Dip |
| Saturday 6 AM | Weekly re-optimization | `weekly_reoptimize.py` | Both |

---

## 3. What Must Be Built

### 3.1 New: Support strategy live evaluator (PROPOSED)

**New file: `tools/neural_support_evaluator.py`**

Purpose: Daily pre-market check — which tickers from the neural support candidates are near buy levels?

```
Input:
  - data/neural_support_candidates.json (top 30 with learned profiles)
  - portfolio.json (current positions/orders)
  - Live prices (yfinance)
  - Wick analysis data (tickers/<TICKER>/wick_analysis.md or cached)

Output:
  - Email alert listing actionable opportunities
  - Console report for daily_analyzer integration

Logic:
  For each neural support candidate not already in portfolio:
    price = yfinance current price
    support_levels = from wick analysis cache
    neural_profile = from neural_support_candidates.json

    For each support level:
      distance = (price - level) / level * 100
      if distance < proximity_threshold:
        # NOTE: 3% is a proposed starting value. The existing codebase uses
        # approach_proximity_pct = 8.0 in wick_offset_analyzer.py (line 102)
        # and backtest_config.py (line 152) for level approach detection.
        # 3% is tighter (alert only when very close). Should be tunable.
        shares = neural_profile.active_pool / neural_profile.active_bullets_max / price
        ALERT: "BUY {ticker} at ${level}, {shares} shares, pool=${pool}"
```

### 3.2 New: Unified notification for both strategies (PROPOSED)

Extend `notify.py` with a `send_support_alert()` function:

```python
def send_support_alert(ticker, level, shares, pool, sell_target_pct, reason):
    """Email when price approaches a neural-optimized support level."""
    subject = f"SUPPORT ALERT: BUY {ticker} near ${level:.2f}"
    body = f"""Ticker: {ticker}
Support Level: ${level:.2f}
Shares: {shares}
Pool: ${pool}
Sell Target: {sell_target_pct}%
...
"""
```

### 3.3 New: Cron schedule (PROPOSED)

```cron
# === Neural Trading System — Automated Schedule ===

# Daily briefing + support evaluation (8:30 AM ET = 15:30 local, +7hr offset)
30 15 * * 1-5 cd /Users/kamenkamenov/agentic-trading && python3 tools/neural_support_evaluator.py >> data/support_eval.log 2>&1

# Dip strategy: first-hour breadth (10:30 AM ET = 17:30 local)
30 17 * * 1-5 cd /Users/kamenkamenov/agentic-trading && python3 tools/neural_dip_evaluator.py --phase first_hour >> data/dip_eval.log 2>&1

# Dip strategy: decision + email (11:00 AM ET = 18:00 local)
0 18 * * 1-5 cd /Users/kamenkamenov/agentic-trading && python3 tools/neural_dip_evaluator.py --phase decision >> data/dip_eval.log 2>&1

# Dip strategy: EOD check (3:45 PM ET = 22:45 local)
45 22 * * 1-5 cd /Users/kamenkamenov/agentic-trading && python3 tools/neural_dip_evaluator.py --phase eod_check >> data/dip_eval.log 2>&1

# Weekly re-optimization (Saturday 6 AM local)
0 6 * * 6 cd /Users/kamenkamenov/agentic-trading && python3 tools/weekly_reoptimize.py >> data/reoptimize.log 2>&1
```

**NOTE**: Times above assume +7hr ET-to-local offset (verified: 9:54 PM local = 2:54 PM ET on 2026-03-29). Both EET and ET shift for DST, keeping the offset at +7 most of the year. HOWEVER, US DST starts second Sunday of March while EU DST starts last Sunday of March — there's a ~2-week gap each spring/fall where the offset becomes +6hr. During these gaps, cron entries would fire 1 hour late relative to US market time. Consider using a timezone-aware scheduler or manually adjusting cron during transition weeks. `date_utils.py` shows local time is ~7 hours ahead of ET.

### 3.4 Replace hardcoded defaults with neural profiles in daily analyzer (PROPOSED)

**FACT**: The daily analyzer currently uses hardcoded defaults throughout:

| Decision | Current source | Hardcoded value | Neural replacement |
| :--- | :--- | :--- | :--- |
| Sell target | `sell_target_calculator.py` or `"math 6.0%"` fallback (line 872) | Fixed 4.5%/6.0%/7.5% tiers | Per-ticker `sell_default` from `neural_support_candidates.json` |
| Verdict thresholds | `shared_utils.py::compute_verdict()` (called at daily_analyzer line 212) | Fixed catastrophic levels | Per-ticker `cat_hard_stop` from neural profile |
| Pool sizing | `wick_offset_analyzer.py` default `active_pool=300` (line 75), flows through `shared_utils.get_ticker_pool()` and `graph_builder.py` | $300 per ticker | Per-ticker `active_pool` from neural profile ($200-$750) |
| Bullet count | Fixed from `bullet_recommender.py` | 5 active + 3 reserve | Per-ticker `active_bullets_max` from neural profile (3-7) |
| Tier thresholds | `wick_offset_analyzer.py::WickConfig` (lines 95-97), applied by `classify_level()` (line 291) | Fixed 50%/30%/15% | Per-ticker `tier_full`/`tier_std` from neural profile |
| Dip thresholds | `DIP_CONFIG` in `neural_dip_evaluator.py` | Global 1.0% dip | Per-ticker `dip_threshold` from `ticker_profiles.json` (already done in Phase 1) |

**The integration point**: When the daily analyzer computes sell targets, order recommendations, or verdicts, it should check if a neural profile exists for that ticker and use the learned parameters instead of the hardcoded defaults.

```python
# PROPOSED: in daily_analyzer.py, load neural profiles at startup
support_profiles = _load_neural_support_profiles()  # from neural_support_candidates.json
dip_profiles = _load_profiles()  # from ticker_profiles.json (already exists)

# When computing sell target for a position:
def get_neural_sell_target(ticker, avg_cost):
    profile = support_profiles.get(ticker)
    if profile:
        return avg_cost * (1 + profile["params"]["sell_default"] / 100)
    return avg_cost * 1.06  # fallback to 6.0% default

# When computing pool for new order:
def get_neural_pool(ticker):
    profile = support_profiles.get(ticker)
    if profile:
        return profile["params"].get("active_pool", 300)
    return 300  # fallback
```

**This is the core change**: the daily analyzer stops being a hardcoded system and becomes a neural-driven system that uses per-ticker learned parameters for every decision.

### 3.5 Display neural data in daily report (PROPOSED)

Add sections to the daily analyzer output showing neural-optimized parameters:

```
## Active Positions — Neural Profiles

| Ticker | Current | Avg | P/L | Neural Sell% | Neural Pool | Neural Bullets | Default Sell% |
| CIFR   | $9.20   | $8.85 | +4% | 10.0%       | $500        | 3             | 6.0%          |
| IONQ   | $44.00  | $44.43| -1% | 8.0%        | $300        | 5             | 6.0%          |
| LUNR   | $7.10   | $6.90 | +3% | 10.0%       | $300        | 5             | 6.0%          |

## Neural Support Opportunities (approaching buy levels)

| Ticker | Price | Support | Distance | Shares | Pool | Sell% |
| CIFR   | $9.20 | $8.85   | 3.8%     | 56     | $500 | 10%   |

## Neural Dip Status (from today's evaluation)

| Ticker | Dip% | Gate | Breadth | Status |
| CLSK   | 2.3% | >=2.0% ACTIVATED | 23% >= 10% | CANDIDATE |
```

### 3.6 How both strategies flow through the daily run (PROPOSED)

**Morning daily run flow:**

```
1. Load neural profiles
   - data/ticker_profiles.json (dip strategy, 19 tickers)
   - data/neural_support_candidates.json (support strategy, 30 tickers)
   - data/synapse_weights.json (learned weights)

2. Market regime (existing)
   - VIX, regime classification

3. Position analysis (MODIFIED — use neural sell targets)
   - For each position: neural sell_target% if profile exists, else default 6%
   - Verdict: use neural cat_hard_stop% if profile exists, else default
   - Show BOTH: "Neural: sell at +10%" vs "Default: sell at +6%"

4. Order reconciliation (MODIFIED — use neural pool/bullets)
   - Pending buy orders: recommend shares from neural pool/bullets
   - Pending sell orders: target from neural sell_target%

5. Support opportunity scan (NEW)
   - Run neural_support_evaluator inline or read its cached output
   - Show tickers approaching neural-optimized support levels

6. Dip strategy status (existing, uses Phase 1-3 neural profiles)
   - Shows dip_viable, neural thresholds per ticker
   - At 10:30/11:00 AM: first_hour + decision phases fire automatically via cron

7. Candidate discovery status (NEW)
   - Last run date + summary from neural_candidates.json / neural_support_candidates.json
   - How many candidates in each strategy's top 30
```

### 3.7 Bridge: dip-to-support handoff at EOD (PROPOSED — deferred)

When a same-day dip buy doesn't hit its target by EOD, the system could check if the ticker has a support strategy neural profile:
- If yes: "HOLD — neural support profile says sell at +10%, not same-day cut"
- If no: "CUT — no support profile, close at EOD"

This requires `evaluate_eod()` in `neural_dip_evaluator.py` to load support profiles. Currently `evaluate_eod()` only lists unfilled exits with no hold-vs-cut logic. Adding this intelligence is a separate change — deferred until the basic integration works.

---

## 4. What Changes vs What Doesn't

### 4.1 Modified (backward-compatible)

| Component | Change | Backward compat |
| :--- | :--- | :--- |
| `daily_analyzer.py` | Load neural profiles, use per-ticker sell/pool/bullets, add neural sections to report | Falls back to hardcoded defaults when no profile exists |
| `sell_target_calculator.py` | Accept optional neural sell target override | Default=None uses existing 4.5%/6.0%/7.5% |
| `notify.py` | Add `send_support_alert()`, fix "+4%" bug | Existing `send_dip_alert()` unchanged |

### 4.2 NOT changed

| Component | Why unchanged |
| :--- | :--- |
| `graph_engine.py` | Strategy-agnostic infrastructure |
| `neural_dip_evaluator.py` | Already has live phases with neural profiles — just needs cron |
| `parameter_sweeper.py` | Dip sweep — frozen baseline |
| `neural_candidate_discoverer.py` | Dip discovery — frozen baseline |
| `support_parameter_sweeper.py` | Runs during weekly re-optimization, not live |
| `backtest_engine.py` | Simulation tool, not live |
| `graph_builder.py` | Daily graph nodes (sell_target, pool, verdict) keep their existing defaults. Neural overrides are applied DOWNSTREAM in the daily analyzer report — the graph computes the baseline, the report shows "Default: 6.0% / Neural: 10.0%" side by side. This avoids modifying graph_builder.py while still surfacing neural recommendations. If the user acts on the neural recommendation, the position's `target_exit` in portfolio.json is updated, and the graph picks it up on the next run. |

---

## 5. Notification Flow

### 5.1 What the user receives

**Morning (8:30 AM ET):**
```
Subject: Morning Support Scan — 2026-03-30

2 tickers near support levels:

CIFR: $9.20, support at $8.85 (3.8% away)
  Neural profile: sell at +10%, $500 pool, 3 bullets
  Action: Place limit buy at $8.85 for 56 shares

LUNR: $7.10, support at $6.90 (2.9% away)
  Neural profile: sell at +10%, $300 pool, 5 bullets
  Action: Place limit buy at $6.90 for 43 shares
```

**11:00 AM ET (if dip fires):**
```
Subject: DIP ALERT: BUY CLSK at $8.66

Ticker: CLSK
Entry: $8.66
Target: $9.01 (+4%)     ← BUG: notify.py line 52 hardcodes "(+4%)"
Stop: $8.40 (-3%)           regardless of actual per-ticker target.
Budget: $100                Must fix to compute from actual target/entry.
Regime: Neutral

REASON CHAIN:
DIP_LEVEL=2.3% → DIP_GATE(>=2.0%) ACTIVATED → BOUNCE_LEVEL=1.1% → ...
```

**3:45 PM ET (PROPOSED — this intelligence does NOT exist yet):**
```
Subject: EOD Dip Check — 2026-03-30

CLSK: bought at $8.66, current $8.80 (+1.6%)
  Same-day target not hit.
  NOTE: Current evaluate_eod() only lists unfilled exits.
  It has NO hold-vs-cut decision logic.
  PROPOSED: Add dip-to-support bridge that checks neural support
  profile for hold parameters.
```

### 5.2 Decision authority

**The neural network RECOMMENDS. The user DECIDES.** No automated order placement. Every alert requires manual broker action. This is by design — real money, human in the loop.

---

## 6. Implementation Steps

0. **Prerequisite: Wick analysis for support candidates** — Most neural support candidates (including top-ranked APP, MSTR) lack `tickers/<TICKER>/wick_analysis.md` files. The support evaluator depends on wick-adjusted support levels. Must run `wick_offset_analyzer.py` for all 30 candidates before the evaluator can work. This can be automated as part of the weekly re-optimization pipeline or run once during onboarding via `batch_onboard.py`.
1. **`tools/neural_support_evaluator.py`** (~150 lines) — Daily support level scanner with email alerts
2. **`tools/notify.py`** — Add `send_support_alert()` + fix hardcoded "+4%" bug (line 52: compute actual target % from target/entry ratio) (~25 lines)
3. **`tools/daily_analyzer.py`** — Load neural profiles at startup, use per-ticker sell targets/pools/bullets instead of hardcoded defaults. Add neural support opportunities + dip status sections to report (~80 lines)
4. **`tools/sell_target_calculator.py`** — Accept optional neural profile override for per-ticker sell target % instead of fixed 4.5%/6.0%/7.5% (~15 lines, backward compat via default=None)
5. **Cron entries** — 5 jobs (morning support, 3 dip phases, weekly reopt). Times use +7hr ET-to-local offset.

**Total: ~270 lines new/modified code + cron setup**

---

## 7. Open Questions

1. **User's timezone** — Cron times must be in local time. The user appears to be ~7 hours ahead of ET (EET/EEST). Must confirm exact offset.

2. **Broker API** — Currently no broker integration. Everything is email → manual order. Should broker API (e.g., Schwab/Alpaca) be explored for automated order placement?

3. **Support level freshness** — The support evaluator needs wick analysis data. This is computed by `wick_offset_analyzer.py` and cached. How often should it refresh? Daily? Weekly?

4. **Dip-to-support bridge** — When a same-day dip buy doesn't hit its target by EOD, should the system automatically switch to support strategy hold parameters? This adds complexity but could improve P/L.

5. **Multiple email alerts** — On active days, the user could get 3-4 emails (morning support, dip alert, EOD check, weekly summary). Is this acceptable or should alerts be consolidated?
