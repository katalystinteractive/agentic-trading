# Auto-Fill Detection → Order Cascade — Analysis

**Date**: 2026-04-11 (v2 — verified)
**Task**: When proximity monitor detects FILLED?, auto-record the fill and cascade next actions.

---

## Current State

Fill detection happens in 3 places, all producing alerts only:

| Detector | Mechanism | Output | Frequency |
| :--- | :--- | :--- | :--- |
| `order_proximity_monitor.py` | `current_price <= order_price` (5-min close) | Email "FILLED?" | Every 5 min (market hours) |
| `portfolio_status.py` | `day_low <= order_price` | Markdown "**FILLED?**" | On-demand |
| `status_pre_analyst.py` | Parses portfolio_status output (two modes: 10-col status read, 9-col day_low/day_high derivation) | Fill alert section | Workflow-driven |

**Key distinction:** The proximity monitor uses the latest 5-minute candle close, NOT day_low. This is a stronger fill signal — if a 5-min bar closes at or below the order price, the stock sustained that level (not just a brief wick). The other two detectors use day_low which captures any intraday touch.

**The gap:** All 3 detect fills but NONE record them. User must manually run `cmd_fill()` or `daily_analyzer --fills` before cascade actions (sell targets, next bullet) can fire.

---

## What cmd_fill() Does (portfolio_manager.py:224-372)

When a fill IS recorded, cmd_fill triggers:
1. Position update (shares, avg_cost, fill_prices array)
2. Pending order removal (matched by price within 0.5% tolerance, with 2% fallback for market slippage)
3. Bullets_used increment (active vs reserve zone tracking)
4. Trade history ledger entry (trade_history.json)
5. **Auto-cascade: sell_target_calculator.analyze_ticker()** — immediate sell targets
6. **Auto-cascade: same-day exit advisory** — for upper-zone (A1/A2) or daily-range fills
7. **Auto-cascade: knowledge_store.store_fill()** — pattern logging

**Note on tolerance:** The 2% fallback is important for auto-fill because the monitor passes `current_price` (not the exact limit order price). If the fill happened at a slightly different price, the fallback ensures the pending order gets matched.

---

## Critical Implementation Constraints

### 1. FILLED? vs PLACE_NOW — Must filter by alert level

The proximity monitor distinguishes two alert types at `distance <= 0`:
- **FILLED?** — for placed orders (live limit orders at broker). Auto-fill is valid.
- **PLACE_NOW** — for monitored/unplaced levels (no broker order exists). Auto-fill MUST NOT trigger.

The `_is_monitored` flag (from `load_monitored_levels()`) determines which type. Auto-fill logic MUST check `level == "FILLED?"` explicitly. Defense-in-depth: monitored levels have `shares: 0`, and `cmd_fill` rejects `shares <= 0`, providing a secondary guard.

### 2. VIX Gate — Must exempt fill detection

The VIX gate (lines 201-204) skips orders entirely when VIX exceeds the ticker's learned threshold:
```python
if _vix_gate > 0 and _vix_now > _vix_gate:
    continue  # VIX too high — skips ALL alerts including FILLED?
```

This creates false negatives: a placed order fills at the broker (the broker ignores VIX), but the monitor never detects it because the VIX gate `continue` fires before distance is computed. The auto-fill implementation must exempt `distance <= 0` checks from the VIX gate, or move the VIX gate to apply only to APPROACHING/IMMINENT levels.

---

## False Positive Risk Assessment

**Question:** Can `current_price <= order_price` (5-min close) WITHOUT the limit order actually filling?

**Analysis:**
- The proximity monitor checks the latest 5-minute candle close, not day_low. This means the stock SUSTAINED a price at or below the order for a full 5-minute bar
- For our tickers ($3-60 price range, >500K daily volume), a sustained 5-min close at/below the limit price makes fill near-certain
- This is actually a STRONGER fill indicator than day_low — a brief wick might not sustain long enough for a fill, but a 5-min close at the price means sustained trading at that level
- Edge case: broker-side issues (order expired, insufficient funds, order rejected). Can't detect from price data alone
- Edge case: order placed outside market hours then cancelled before open. Proximity monitor only runs during market hours

**Conclusion:** False positive rate is negligible for our ticker universe. The 5-minute close mechanism is more conservative than day_low, reducing false positives further.

**Reversal cost if wrong:** `cmd_sell` reverses the position math but does NOT: (a) remove the phantom BUY entry from trade_history.json, (b) remove the knowledge_store entry, (c) undo sell target recalculations. These artifacts are benign (trade history shows the reversal sequence) but the user should be aware that a false fill leaves residual records.

---

## Design Decision: Auto-Record vs Pending Confirmation

| Approach | Pros | Cons |
| :--- | :--- | :--- |
| Auto-record immediately | Zero manual work, instant cascade | Rare false fill requires manual reversal |
| Pending confirmation | No false fills | Adds manual step, defeats purpose |
| Auto-record with flag | Best of both, auditable | Slightly more complex |

**Choice:** Auto-record with `"auto_detected": true` flag in trade_history. If wrong, user reverses with cmd_sell. The flag provides audit trail.

---

## Cascade Email Content

Current FILLED? email: `"FILLED?: CIFR BUY @ $14.18 -> $14.05 -0.92%"`

Proposed consolidated email after auto-fill:

```
FILL RECORDED: CIFR BUY 8 shares @ $14.18

Position: 30 shares @ $15.22 avg
Deployed: $456.60 / $600.00 pool (76%)

Sell Target: $16.13 (Standard, 6.0%)

Next Bullet: A4 @ $13.85 (3 shares)
Action: Place limit BUY 3 CIFR @ $13.85
```

**Runtime dependencies** (read-only, no modification needed):
- `sell_target_calculator.py` — sell target computation (already triggered by cmd_fill)
- `bullet_recommender.py` — next bullet recommendation (invoked from monitor, output captured for email)

---

## Implementation Scope

### In scope:
1. Auto-record fill in `order_proximity_monitor.py` when `level == "FILLED?"` (NOT PLACE_NOW)
2. Exempt fill detection from VIX gate (move gate to APPROACHING/IMMINENT only)
3. Capture sell targets and next bullet info for email
4. Send consolidated "FILL RECORDED + Next Action" email
5. Flag auto-detected fills in trade_history for audit
6. Dry-run mode for testing

### Out of scope:
- Changing how cmd_fill works (already handles everything)
- Modifying portfolio_status.py or status workflows (they remain read-only)
- Auto-placing the next limit order (user must place manually)
- SELL order fill detection — lower priority because: (a) no "next bullet" cascade needed, (b) fewer SELL orders in flight at any time, (c) SELL fills are less time-sensitive since they reduce position rather than add to it

---

## Files to Modify

| File | Change | Why |
| :--- | :--- | :--- |
| `tools/order_proximity_monitor.py` | Auto-fill on FILLED? (not PLACE_NOW), VIX gate exemption, cascade email, dry-run flag | Core feature |
| `tools/portfolio_manager.py` | Add `auto_detected` flag passthrough to trade_history | Audit trail |
| `tools/notify.py` | Add `send_fill_cascade_alert()` | Consolidated email |

**Runtime dependencies** (no modification): `bullet_recommender.py`, `sell_target_calculator.py`

**Lines changed estimate:** ~80-100 lines across 3 files.

---

## Risks and Mitigations

| Risk | Mitigation |
| :--- | :--- |
| PLACE_NOW mistaken for FILLED? | Explicit `level == "FILLED?"` check + shares>0 defense-in-depth |
| VIX gate hiding real fills | Exempt distance<=0 from VIX gate |
| False fill on 5-min close anomaly | `auto_detected` flag in trade_history; cmd_sell for reversal |
| Double-recording (monitor runs every 5 min) | cmd_fill removes matched pending order; next run finds no order. 5-min cron interval makes overlap near-impossible but add PID/lock guard |
| cmd_fill failure mid-cascade | Wrap in try/except, send error email instead |
| Residual artifacts from false fill reversal | trade_history and knowledge_store entries remain after cmd_sell — benign, shows full sequence |

---

## Testing Plan

1. **Unit tests**: Test FILLED?-only filter (mock alerts with FILLED? and PLACE_NOW, verify only FILLED? triggers auto-fill)
2. **VIX exemption test**: Mock high-VIX scenario, verify FILLED? still fires
3. **Dry-run mode**: `--auto-fill-dry-run` flag that logs what WOULD be recorded without calling cmd_fill. Validates detection without modifying portfolio.json
4. **Staged rollout**: Week 1 = dry-run only (email shows "WOULD RECORD: ..."). Week 2 = live with auto_detected flag. Validates against actual broker fills
