# Implementation Plan: Auto-Fill Detection → Order Cascade

**Date**: 2026-04-11
**Source**: `plans/auto-fill-detection-analysis.md` (verified, v2)

---

## Context

The proximity monitor detects FILLED? alerts every 5 minutes but only sends emails. The user must manually record fills via `cmd_fill()`. This plan adds auto-recording when FILLED? is detected, cascading sell targets and next-bullet recommendations in a consolidated email.

---

## Step 1: Exempt fill detection from VIX gate

**File**: `tools/order_proximity_monitor.py`
**Location**: Lines 200-204 (VIX gate)

### Current code:
```python
if side == "BUY" and _vix_now is not None:
    _vix_gate = _entry_data.get(tk, {}).get("params", {}).get("per_ticker_vix_gate", 0)
    if _vix_gate > 0 and _vix_now > _vix_gate:
        continue  # VIX too high for this ticker
```

### New code:
Move VIX gate to apply only to APPROACHING/IMMINENT alerts, not FILLED?. Compute distance FIRST, then apply VIX gate only if `distance > 0`:

```python
# Distance calculation — positive means price is approaching but hasn't crossed
if side == "BUY":
    distance = (current_price - order_price) / order_price * 100
else:  # SELL
    distance = (order_price - current_price) / order_price * 100

# VIX gate: suppress BUY APPROACH/IMMINENT alerts when VIX exceeds threshold
# BUT: never suppress FILLED? — a placed order fills regardless of VIX
if distance > 0 and side == "BUY" and _vix_now is not None:
    _vix_gate = _entry_data.get(tk, {}).get("params", {}).get("per_ticker_vix_gate", 0)
    if _vix_gate > 0 and _vix_now > _vix_gate:
        continue
```

This requires moving the distance calculation (currently at lines 207-210) ABOVE the VIX gate. The existing distance calc at lines 207-210 gets removed (it's now above the gate).

**~8 lines changed.**

---

## Step 2: Add auto-fill handler function

**File**: `tools/order_proximity_monitor.py`
**Location**: After `load_monitored_levels()` function (after line ~141)

### New function:
```python
def auto_record_fill(ticker, price, shares, dry_run=False):
    """Auto-record a detected fill via portfolio_manager cmd_fill.

    Returns (success: bool, summary: str) tuple.
    summary contains position update + sell targets for email.
    """
    if shares <= 0:
        return False, f"*{ticker}: shares={shares}, skipping auto-fill*"

    if dry_run:
        return True, f"[DRY RUN] Would record: {ticker} BUY {shares} @ ${price:.2f}"

    import argparse
    from portfolio_manager import cmd_fill

    # Construct args namespace matching cmd_fill(data, args) interface
    args = argparse.Namespace(
        ticker=ticker,
        price=price,
        shares=shares,
        trade_date=None,  # defaults to last trading day inside cmd_fill
        auto_detected=True,  # flag for trade_history audit trail
    )

    # Load fresh portfolio data
    with open(PORTFOLIO_PATH) as f:
        data = json.load(f)

    # Capture cmd_fill output (it prints markdown)
    import io, contextlib
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            cmd_fill(data, args)
        return True, buf.getvalue()
    except SystemExit:
        return False, f"*{ticker}: cmd_fill rejected fill @ ${price:.2f}*"
    except Exception as e:
        return False, f"*{ticker}: auto-fill error: {e}*"
```

**~30 lines.**

---

## Step 3: Add next-bullet lookup function

**File**: `tools/order_proximity_monitor.py`
**Location**: After `auto_record_fill()`

### New function:
```python
def get_next_bullet(ticker):
    """Get next bullet recommendation for email cascade.

    Uses bullet_recommender.run_recommend() which returns a structured ctx dict
    with ctx["recommendation"] = {level, shares, cost, pool, label} or None.
    Returns dict {level, price, shares} or None if no next bullet.
    """
    try:
        import io, contextlib
        from bullet_recommender import run_recommend
        from wick_offset_analyzer import analyze_stock_data, load_capital_config

        # Load required data (same pattern as bullet_recommender main())
        with open(PORTFOLIO_PATH) as f:
            portfolio = json.load(f)
        cap = load_capital_config(ticker)
        data, err = analyze_stock_data(ticker, capital_config=cap)
        if data is None:
            return None

        # Suppress stdout (run_recommend prints the full report)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ctx = run_recommend(ticker, "any", data, portfolio, cap)

        if not ctx or not ctx.get("recommendation"):
            return None
        rec = ctx["recommendation"]
        return {
            "level": rec["label"],
            "price": rec["level"]["recommended_buy"],
            "shares": rec["shares"],
        }
    except Exception:
        return None
```

**Key:** `run_recommend(ticker, type_filter, data, portfolio)` returns a rich `ctx` dict.
`ctx["recommendation"]` is `{level, shares, cost, pool, label}` where `level["recommended_buy"]`
is the buy price. The function prints to stdout (suppressed via redirect), so the caller
gets structured data without parsing text.

**~30 lines.**

---

## Step 4: Mark fills in compute_alerts, handle in main()

**File**: `tools/order_proximity_monitor.py`

### Architecture decision:
`compute_alerts()` identifies fills and writes them to `state["_auto_fills"]` (matching existing convention: `_failures`, `_degraded_alerted` are already stored in state). `main()` reads `state["_auto_fills"]` after the call and handles cmd_fill invocation where `args` (including dry_run) is in scope.

### 4a. Inside `compute_alerts()` — mark fills in state

**Location**: After escalation check (after line ~238), when a new FILLED? alert is confirmed:

```python
# Mark fill for auto-recording (handled by main() where args is in scope)
if level == "FILLED?" and not o.get("monitored"):
    state.setdefault("_auto_fills", []).append({
        "ticker": tk,
        "price": order_price,
        "shares": o.get("shares", 0),
    })
```

**~5 lines inside compute_alerts.**

### 4b. Inside `main()` — process marked fills

**Location**: After `compute_alerts()` returns, before email sending:

```python
# Auto-record detected fills
_auto_fills_raw = state.pop("_auto_fills", [])
_auto_fill_results = []
for af in _auto_fills_raw:
    success, summary = auto_record_fill(
        af["ticker"], af["price"], af["shares"],
        dry_run=args.auto_fill_dry_run if hasattr(args, 'auto_fill_dry_run') else False,
    )
    next_bullet = get_next_bullet(af["ticker"]) if success else None
    _auto_fill_results.append({
        **af,
        "success": success,
        "summary": summary,
        "next_bullet": next_bullet,
    })
```

This keeps `compute_alerts()` signature unchanged (`orders, prices, state` → returns `alerts`). The `state` dict is already passed by reference and mutated in place, so no return value change needed.

**~15 lines in main().**

---

## Step 5: Add consolidated cascade email

**File**: `tools/notify.py`
**Location**: After existing `send_summary_email()` function

### New function:
```python
def send_fill_cascade_alert(auto_fills):
    """Send consolidated email for auto-detected fills with cascade info.

    auto_fills: list of dicts with ticker, price, shares, success, summary, next_bullet
    """
    if not auto_fills:
        return

    successful = [f for f in auto_fills if f["success"]]
    failed = [f for f in auto_fills if not f["success"]]

    lines = []
    for f in successful:
        lines.append(f"FILL RECORDED: {f['ticker']} BUY {f['shares']} @ ${f['price']:.2f}")
        lines.append("")
        if f["summary"]:
            # Include position update + sell targets from cmd_fill output
            lines.append(f["summary"].strip())
            lines.append("")
        nb = f.get("next_bullet")
        if nb:
            lines.append(f"Next Bullet: {nb['level']} @ ${nb['price']:.2f} ({nb['shares']} shares)")
            lines.append(f"Action: Place limit BUY {nb['shares']} {f['ticker']} @ ${nb['price']:.2f}")
            lines.append("")
        lines.append("---")
        lines.append("")

    for f in failed:
        lines.append(f"FILL FAILED: {f['summary']}")
        lines.append("")

    body = "\n".join(lines)

    if len(successful) == 1:
        f = successful[0]
        subject = f"FILL: {f['ticker']} BUY {f['shares']} @ ${f['price']:.2f}"
    elif successful:
        tickers = ", ".join(f["ticker"] for f in successful)
        subject = f"FILLS: {tickers}"
    else:
        subject = "FILL ERRORS"

    send_summary_email(subject, body)
```

**~35 lines.**

---

## Step 6: Add auto_detected flag to trade_history

**File**: `tools/portfolio_manager.py`
**Location**: Line ~321 (trade history recording in cmd_fill)

### Current code (approximate):
```python
record = {
    "ticker": ticker,
    "action": "BUY",
    "date": trade_date,
    "shares": shares,
    "price": price,
    ...
}
```

### Change:
Add `auto_detected` field from args:
```python
if getattr(args, "auto_detected", False):
    record["auto_detected"] = True
```

Also update the argparse Namespace construction in `auto_record_fill()` (Step 2) to include `auto_detected=True`.

**~3 lines.**

---

## Step 7: Add --auto-fill-dry-run CLI flag

**File**: `tools/order_proximity_monitor.py`
**Location**: argparse setup in `main()`

```python
parser.add_argument("--auto-fill-dry-run", action="store_true",
                    help="Log what would be auto-filled without recording")
```

Pass to compute_alerts or make accessible globally.

**~2 lines.**

---

## Step 8: Update cascade email in main()

**File**: `tools/order_proximity_monitor.py`
**Location**: In `main()`, after `compute_alerts()` returns

Send cascade email for auto-fills separately from regular proximity alerts:

```python
if _auto_fill_results:
    from notify import send_fill_cascade_alert
    send_fill_cascade_alert(_auto_fill_results)
```

Regular APPROACHING/IMMINENT alerts still use the existing `send_summary_email()` path.

**~4 lines.**

---

## Files Modified

| File | Change | Lines |
| :--- | :--- | :--- |
| `tools/order_proximity_monitor.py` | VIX gate exemption, auto_record_fill(), get_next_bullet(), state-based fill marking, main() fill processing, dry-run flag, cascade email call | ~85 |
| `tools/portfolio_manager.py` | `auto_detected` flag in trade history record | ~3 |
| `tools/notify.py` | `send_fill_cascade_alert()` function | ~35 |
| **Total** | | **~118** |

---

## Implementation Order

1. Step 1: VIX gate restructure (prerequisite — fills must not be suppressed)
2. Step 6: auto_detected flag in portfolio_manager (small, independent)
3. Step 5: Cascade email in notify.py (independent)
4. Step 2: auto_record_fill() function
5. Step 3: get_next_bullet() function
6. Step 4: Wire into compute_alerts
7. Step 7: CLI dry-run flag
8. Step 8: Cascade email in main()
9. Tests

---

## Verification

1. **VIX gate exemption**: Manually test with mock VIX > threshold, verify FILLED? still fires
2. **PLACE_NOW filter**: Run with monitored levels at distance<=0, verify NO auto-fill triggers
3. **Auto-fill recording**: Mock a FILLED? alert, verify portfolio.json updated, trade_history entry has `auto_detected: true`
4. **Cascade email**: Verify email contains position summary + sell targets + next bullet
5. **Dry-run mode**: `python3 tools/order_proximity_monitor.py --auto-fill-dry-run` — verify no portfolio.json changes, log shows "Would record"
6. **Double-recording prevention**: Run monitor twice quickly, verify only one fill recorded
7. **Tests pass**: `python3 -m pytest tests/ -v`
