# Implementation Plan: Neural Network Live Integration

**Date**: 2026-03-29
**Source analysis**: `plans/neural-live-integration-analysis.md` (verified, all issues resolved)
**Goal**: Both strategies (dip + support) running automatically via cron, neural profiles driving all trading parameters, email notifications for every actionable signal.

---

## Scope

| Step | What | Files | Type |
| :--- | :--- | :--- | :--- |
| 1 | Fix notify.py +4% bug | `notify.py` | MODIFY |
| 2 | Build neural support evaluator | `neural_support_evaluator.py` | NEW |
| 3 | Add neural profile loading to daily analyzer | `daily_analyzer.py` | MODIFY |
| 4 | Add neural sell target override to sell_target_calculator | `sell_target_calculator.py` | MODIFY |
| 5 | Set up cron schedule | crontab | NEW |
| 6 | Test end-to-end | — | VERIFY |

**Frozen files**: `neural_dip_evaluator.py`, `parameter_sweeper.py`, `neural_candidate_discoverer.py`, `support_parameter_sweeper.py`, `graph_engine.py`, `graph_builder.py`, `backtest_engine.py`, `data/neural_candidates.json`, `data/sweep_results.json`

**Deferred**: Dip-to-support bridge at EOD (analysis Section 3.7) — when a dip buy doesn't hit same-day target, check if the ticker has a support profile and recommend HOLD instead of CUT. Deferred until basic integration works.

---

## Step 0: Prerequisite — Generate Wick Analysis for Support Candidates

**FACT** (verified): Most neural support candidates (including top-ranked APP, MSTR) lack `tickers/<TICKER>/wick_analysis.md` files. The support evaluator depends on wick-adjusted support levels to recommend buy prices.

**Without this step**: The evaluator silently produces zero alerts for most candidates.

```bash
# Run wick analysis for all 30 neural support candidates
python3 -c "
import json
with open('data/neural_support_candidates.json') as f:
    candidates = [c['ticker'] for c in json.load(f)['candidates']]
print(' '.join(candidates))
" | xargs -n1 python3 tools/wick_offset_analyzer.py
```

Alternatively, use `batch_onboard.py --from-file` to onboard all 30 candidates (creates identity.md, memory.md, runs wick analysis + cycle timing).

This is a one-time step. The weekly re-optimization pipeline should auto-refresh wick analysis for all active candidates going forward.

---

## Step 1: Fix notify.py +4% Bug

**FACT** (verified): Line 52 of `notify.py` hardcodes `(+4%)` regardless of actual target:
```python
f"Target: ${target:.2f} (+4%)\n"
```

**Fix**: Compute actual percentage from target and entry_price:

```python
target_pct = round((target - entry_price) / entry_price * 100, 1)
f"Target: ${target:.2f} (+{target_pct}%)\n"
```

Also fix stop line (line 53) similarly:
```python
stop_pct = round((stop - entry_price) / entry_price * 100, 1)
f"Stop:   ${stop:.2f} ({stop_pct}%)\n"
```

**Lines changed**: ~5

---

## Step 2: Build Neural Support Evaluator

**New file**: `tools/neural_support_evaluator.py` (~150 lines)

### 2.1 Purpose

Daily pre-market scan: check which neural support candidates are near buy levels. Email actionable opportunities.

### 2.2 Logic

```python
"""Neural Support Evaluator — daily support level scanner.

Usage:
    python3 tools/neural_support_evaluator.py              # scan + email
    python3 tools/neural_support_evaluator.py --no-email   # scan only
    python3 tools/neural_support_evaluator.py --proximity 5 # wider proximity %
"""

def main():
    # 1. Load neural support profiles
    with open("data/neural_support_candidates.json") as f:
        candidates = json.load(f)["candidates"]

    # 2. Load portfolio (exclude tickers already fully positioned)
    portfolio = _load_portfolio()
    positions = portfolio.get("positions", {})

    # 3. Get live prices
    tickers = [c["ticker"] for c in candidates]
    prices = _fetch_prices(tickers)  # yfinance batch

    # 4. For each candidate, check support proximity
    opportunities = []
    for c in candidates:
        tk = c["ticker"]
        price = prices.get(tk)
        if not price:
            continue

        profile = c["params"]
        # Load wick analysis for support levels
        levels = _load_support_levels(tk)  # from tickers/<tk>/wick_analysis.md cache
        if not levels:
            continue

        for level in levels:
            distance_pct = (price - level["buy_at"]) / level["buy_at"] * 100
            if 0 <= distance_pct <= proximity_threshold:
                pool = profile.get("active_pool", 300)
                bullets = profile.get("active_bullets_max", 5)
                shares = int(pool / bullets / price)
                opportunities.append({
                    "ticker": tk,
                    "price": price,
                    "support": level["buy_at"],
                    "distance_pct": round(distance_pct, 1),
                    "shares": shares,
                    "pool": pool,
                    "sell_target_pct": profile.get("sell_default", 6.0),
                })

    # 5. Email if opportunities found
    if opportunities and not args.no_email:
        send_support_alert_batch(opportunities)

    # 6. Write cache for daily_analyzer to read
    with open("data/support_eval_latest.json", "w") as f:
        json.dump({"date": today, "opportunities": opportunities}, f)
```

### 2.3 Support level loading

**FACT** (verified): Most neural support candidates lack `wick_analysis.md`. The evaluator must handle missing files gracefully:

```python
def _load_support_levels(ticker):
    """Load wick-adjusted support levels. Returns [] if not available."""
    wick_path = _ROOT / "tickers" / ticker / "wick_analysis.md"
    if not wick_path.exists():
        return []
    # Parse the Buy At column from the wick analysis table
    ...
```

Tickers without wick analysis get skipped (no alert). The weekly pipeline should auto-generate wick analysis for new candidates.

### 2.4 Add `send_support_alert()` to notify.py

```python
def send_support_alert(opportunities):
    """Send email listing support buy opportunities."""
    if not opportunities:
        return False
    lines = [f"{len(opportunities)} tickers near support levels:\n"]
    for opp in opportunities:
        lines.append(f"{opp['ticker']}: ${opp['price']:.2f}, "
                     f"support at ${opp['support']:.2f} ({opp['distance_pct']}% away)")
        lines.append(f"  Neural: sell at +{opp['sell_target_pct']}%, "
                     f"${opp['pool']} pool, {opp['shares']} shares")
        lines.append(f"  Action: Place limit buy at ${opp['support']:.2f}\n")
    body = "\n".join(lines)
    return send_summary_email(
        f"Morning Support Scan — {date.today().isoformat()}", body)
```

**Lines**: ~25 in notify.py

---

## Step 3: Add Neural Profile Loading to Daily Analyzer

### 3.1 Load profiles at startup

**Where**: After market regime computation in `main()`, before position analysis.

```python
# Load neural profiles for both strategies
_neural_support = {}
_neural_dip = {}
try:
    with open(_ROOT / "data" / "neural_support_candidates.json") as f:
        _ns = json.load(f)
    _neural_support = {c["ticker"]: c for c in _ns.get("candidates", [])}
except (FileNotFoundError, json.JSONDecodeError):
    pass
try:
    from neural_dip_evaluator import _load_profiles
    _neural_dip = _load_profiles()
except Exception:
    pass
```

### 3.2 Helper functions

```python
def _get_neural_sell_target(ticker, avg_cost):
    """Neural sell target if profile exists, else None (use default)."""
    profile = _neural_support.get(ticker)
    if profile and "params" in profile:
        pct = profile["params"].get("sell_default")
        if pct:
            return round(avg_cost * (1 + pct / 100), 2)
    return None

def _get_neural_pool(ticker):
    """Neural pool size if profile exists, else None."""
    profile = _neural_support.get(ticker)
    if profile and "params" in profile:
        return profile["params"].get("active_pool")
    return None

def _get_neural_bullets(ticker):
    """Neural bullet count if profile exists, else None."""
    profile = _neural_support.get(ticker)
    if profile and "params" in profile:
        return profile["params"].get("active_bullets_max")
    return None

def _get_neural_cat_stop(ticker):
    """Neural catastrophic stop % if profile exists, else None."""
    profile = _neural_support.get(ticker)
    if profile and "params" in profile:
        return profile["params"].get("cat_hard_stop")
    return None

def _get_neural_tier(ticker):
    """Neural tier thresholds if profile exists, else (None, None)."""
    profile = _neural_support.get(ticker)
    if profile and "params" in profile:
        return (profile["params"].get("tier_full"),
                profile["params"].get("tier_std"))
    return None, None
```

### 3.3 Use neural targets in position table

**Where**: In the consolidated orders / position table, after computing the default sell target.

```python
# Existing: default sell target
default_target = round(avg_cost * 1.06, 2)

# NEW: show BOTH neural and default side by side for comparison
neural_target = _get_neural_sell_target(tk, avg_cost)
neural_cat = _get_neural_cat_stop(tk)
neural_tf, neural_ts = _get_neural_tier(tk)

if neural_target:
    n_pct = _neural_support[tk]["params"]["sell_default"]
    display_target = f"${neural_target:.2f} (neural {n_pct}%) | ${default_target:.2f} (default 6%)"
else:
    display_target = f"${default_target:.2f} (default 6%)"

# Same pattern for catastrophic stop and tier thresholds
if neural_cat:
    display_cat = f"{neural_cat}% (neural) | 25% (default)"
# If neural tier thresholds exist:
if neural_tf:
    display_tier = f"Full≥{neural_tf}%/Std≥{neural_ts}% (neural) | 50%/30% (default)"
```

### 3.4 Add neural sections to report output

**After existing position tables, add:**

```python
# === Neural Support Opportunities ===
eval_path = _ROOT / "data" / "support_eval_latest.json"
if eval_path.exists():
    with open(eval_path) as f:
        eval_data = json.load(f)
    opps = eval_data.get("opportunities", [])
    if opps:
        print("\n## Neural Support Opportunities\n")
        print("| Ticker | Price | Support | Distance | Shares | Pool | Sell% |")
        print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for o in opps:
            print(f"| {o['ticker']} | ${o['price']:.2f} | ${o['support']:.2f} | "
                  f"{o['distance_pct']}% | {o['shares']} | ${o['pool']} | "
                  f"{o['sell_target_pct']}% |")

# === Neural Dip Status ===
# Show per-ticker dip profiles for watchlist tickers
if _neural_dip:
    print("\n## Neural Dip Profiles\n")
    print("| Ticker | Dip Threshold | Target | Stop | Breadth |")
    print("| :--- | :--- | :--- | :--- | :--- |")
    for tk in sorted(_neural_dip.keys()):
        p = _neural_dip[tk]
        print(f"| {tk} | {p.get('dip_threshold', '?')}% | "
              f"{p.get('target_pct', '?')}% | {p.get('stop_pct', '?')}% | "
              f"{p.get('breadth_threshold', '?'):.0%} |")
```

**Lines changed in daily_analyzer.py**: ~80

---

## Step 4: Neural Sell Target Override in sell_target_calculator.py

**FACT** (verified): `sell_target_calculator.py` already has override infrastructure:
- `_load_profile(ticker)` loads from `ticker_profiles.json` (line 496)
- `custom_pct` from `profile["optimal_target_pct"]` adds an "optimized" target (line 497-499)
- `_compute_math_prices(avg_cost, custom_pct=None)` accepts custom percentage (line 81)

**Change**: Add a second profile source — check `neural_support_candidates.json` if `ticker_profiles.json` doesn't have an optimized target:

```python
def _load_profile(ticker):
    """Load per-ticker profile. Check neural support candidates as fallback."""
    # Existing: check ticker_profiles.json
    ...existing logic...

    # NEW: if no optimal_target_pct, check neural support candidates
    if not profile.get("optimal_target_pct"):
        try:
            with open(_ROOT / "data" / "neural_support_candidates.json") as f:
                ns = json.load(f)
            for c in ns.get("candidates", []):
                if c["ticker"] == ticker:
                    profile["optimal_target_pct"] = c["params"]["sell_default"]
                    profile["optimal_source"] = "neural_support"
                    break
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    return profile
```

**Backward compat**: If no neural profile exists, falls back to existing 4.5%/6.0%/7.5% tiers.

**Lines changed**: ~15

---

## Step 5: Cron Schedule

### 5.1 Cron entries

```cron
# === Neural Trading System — Automated Schedule ===
# Times in local (EET/EEST), +7hr offset from ET

# Morning support scan (8:30 AM ET = 15:30 local)
30 15 * * 1-5 cd /Users/kamenkamenov/agentic-trading && python3 tools/neural_support_evaluator.py >> data/support_eval.log 2>&1

# Dip: first-hour breadth (10:30 AM ET = 17:30 local)
30 17 * * 1-5 cd /Users/kamenkamenov/agentic-trading && python3 tools/neural_dip_evaluator.py --phase first_hour >> data/dip_eval.log 2>&1

# Dip: decision + email (11:00 AM ET = 18:00 local)
0 18 * * 1-5 cd /Users/kamenkamenov/agentic-trading && python3 tools/neural_dip_evaluator.py --phase decision >> data/dip_eval.log 2>&1

# Dip: EOD check (3:45 PM ET = 22:45 local)
45 22 * * 1-5 cd /Users/kamenkamenov/agentic-trading && python3 tools/neural_dip_evaluator.py --phase eod_check >> data/dip_eval.log 2>&1

# Weekly re-optimization (Saturday 6 AM local)
0 6 * * 6 cd /Users/kamenkamenov/agentic-trading && python3 tools/weekly_reoptimize.py >> data/reoptimize.log 2>&1
```

### 5.2 Installation

```bash
# Add to crontab (preserves existing entries)
crontab -l > /tmp/cron_backup.txt
cat >> /tmp/cron_backup.txt << 'EOF'
# Neural Trading System entries here
EOF
crontab /tmp/cron_backup.txt
```

### 5.3 DST note

US and EU DST transitions differ by ~2 weeks in March and November. During these gaps, the +7hr offset becomes +6hr, causing cron entries to fire 1 hour late. User should manually adjust cron times during these transition periods, or consider a timezone-aware scheduler.

---

## Step 6: End-to-End Test

### 6.1 Test neural support evaluator

```bash
python3 tools/neural_support_evaluator.py --no-email
# Verify: lists opportunities for tickers with wick_analysis.md
# Verify: skips tickers without wick data
# Verify: uses neural pool/bullets/sell_target from profiles
```

### 6.2 Test daily analyzer with neural profiles

```bash
python3 tools/daily_analyzer.py
# Verify: "Neural Support Opportunities" section appears
# Verify: "Neural Dip Profiles" section appears
# Verify: sell targets show neural % where profiles exist
# Verify: default 6% shown where no profile exists
```

### 6.3 Test notify.py fix

```bash
python3 -c "from tools.notify import send_dip_alert; send_dip_alert('TEST', 10.0, 10.50, 9.70, 'test', 'Neutral', 100)"
# Verify: email shows "+5.0%" (computed) not "+4%" (hardcoded)
```

### 6.4 Test cron (dry run)

```bash
# Verify cron entry parses correctly
crontab -l | grep "neural"
# Manually run each job once to verify
python3 tools/neural_support_evaluator.py --no-email
python3 tools/neural_dip_evaluator.py --phase first_hour --dry-run
```

---

## Files Summary

| File | Action | Lines | Backward compat |
| :--- | :--- | :--- | :--- |
| `tools/notify.py` | Fix +4% bug + add `send_support_alert()` | ~30 | `send_dip_alert()` unchanged |
| `tools/neural_support_evaluator.py` | NEW — daily support scanner | ~150 | N/A |
| `tools/daily_analyzer.py` | Load neural profiles, add neural sections | ~80 | Falls back to defaults when no profile |
| `tools/sell_target_calculator.py` | Add neural profile as second source | ~15 | Default tiers if no neural profile |
| crontab | 5 new entries | 5 lines | Preserves existing entries |
| **Total** | | **~275 lines** | |

**Frozen (zero modifications)**: `graph_engine.py`, `graph_builder.py`, `neural_dip_evaluator.py`, `parameter_sweeper.py`, `neural_candidate_discoverer.py`, `support_parameter_sweeper.py`, `backtest_engine.py`, `data/neural_candidates.json`, `data/sweep_results.json`
