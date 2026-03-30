# Analysis: Neural Order Adjustment Tool

**Date**: 2026-03-29 (Sunday, 11:09 PM local / 4:09 PM ET)
**Purpose**: Build a tool that computes specific sell and buy order adjustments based on neural profiles. The tool reads portfolio.json pending orders, compares against neural-learned parameters, and outputs a concrete action table — no LLM interpretation.

**Honesty note**: Every claim labeled FACT (verified) or PROPOSED.

---

## 1. What the Tool Must Do

Produce two tables:

**Sell Adjustments**: For each pending SELL order, compare current sell price against the neural-optimized sell target. Show the delta and action (RAISE/LOWER/OK).

**Buy Adjustments**: For each pending BUY order, compare current share count against neural-optimized pool/bullet sizing. Show the delta and action (+N shares/-N shares/OK).

Both tables must account for:
- Pending limit orders that exist in portfolio.json
- Current position data (avg_cost, shares, bullets_used)
- Neural profiles from `neural_support_candidates.json`
- Tickers WITHOUT neural profiles (show as "no neural profile" — don't skip)

---

## 2. Data Sources (FACT — verified)

### 2.1 Portfolio pending orders

**FACT**: `portfolio.json` has `pending_orders` keyed by ticker, each containing a list of order dicts:

```json
"pending_orders": {
    "NU": [
        {"type": "BUY", "price": 13.03, "shares": 9, "note": "..."},
        {"type": "SELL", "price": 16.75, "shares": 15, "note": "..."},
        {"type": "SELL", "price": 17.14, "shares": 15, "note": "..."}
    ]
}
```

Fields: `type` (BUY/SELL), `price`, `shares`, optional `note`.

### 2.2 Positions

**FACT**: `portfolio.json` has `positions` keyed by ticker:

```json
"positions": {
    "NU": {
        "shares": 30,
        "avg_cost": 15.85,
        "bullets_used": 6,
        "target_exit": 16.75,
        ...
    }
}
```

### 2.3 Neural support profiles

**FACT**: `data/neural_support_candidates.json` has `candidates` array, each with `params`:

```json
{
    "ticker": "NU",
    "params": {
        "sell_default": 10.0,
        "cat_hard_stop": 15,
        "active_pool": 300,
        "reserve_pool": 200,
        "active_bullets_max": 5,
        "reserve_bullets_max": 2,
        "tier_full": 40,
        "tier_std": 20
    }
}
```

### 2.4 What multi-period-scorer provides (FACT)

**FACT**: `get_ticker_pool()` in `shared_utils.py` has a priority chain: multi-period → neural → portfolio.json → hardcoded $300. For tickers WITH multi-period allocations, the pool is simulation-backed (e.g., NNE=$407). This takes priority over neural.

The adjuster should use the SAME priority chain — call `get_ticker_pool()` and `load_capital_config()` rather than reading neural profiles directly. This ensures the adjustment recommendations match what the daily analyzer actually computes.

---

## 3. Sell Adjustment Logic

For each ticker with a position AND pending SELL order(s):

```
current_sell_price = order["price"]
current_sell_pct = (current_sell_price - avg_cost) / avg_cost * 100

# Get the sell target the system would compute
# (uses same priority: target_exit > optimized/neural > 6.0%)
from broker_reconciliation import compute_recommended_sell, _load_profiles
profiles = _load_profiles()
recommended_sell, source = compute_recommended_sell(ticker, avg_cost, pos, profiles)

diff = recommended_sell - current_sell_price
if abs(diff) < 0.05:
    action = "OK"
elif diff > 0:
    action = f"RAISE +${diff:.2f}"
else:
    action = f"LOWER ${diff:.2f}"
```

**Key**: Use `compute_recommended_sell()` which respects the full priority chain (target_exit > optimized > neural > 6.0%). Don't bypass it by reading neural profiles directly — that would produce recommendations inconsistent with what the daily analyzer shows.

---

## 4. Buy Adjustment Logic

For each ticker with pending BUY order(s):

```
current_shares = order["shares"]
buy_price = order["price"]

# Get the pool/bullet config the system would use
# (uses same priority: multi-period > neural > portfolio.json > $300)
from wick_offset_analyzer import load_capital_config
cap = load_capital_config(ticker)
neural_pool = cap["active_pool"]
neural_bullets = cap["active_bullets_max"]
recommended_shares = max(1, int(neural_pool / neural_bullets / buy_price))

diff = recommended_shares - current_shares
if diff == 0:
    action = "OK"
elif diff > 0:
    action = f"+{diff} shares"
else:
    action = f"{diff} shares"
```

**Key**: Use `load_capital_config(ticker)` which now has the neural tier integrated. Don't read neural profiles directly.

---

## 5. Edge Cases

### 5.1 Tickers without neural profiles
Show in the table with source="default" and current values. Don't skip them — the user needs to see every pending order.

### 5.2 Tickers with target_exit set manually
`compute_recommended_sell()` returns `target_exit` as highest priority. If the current sell order matches `target_exit`, the action is "OK" even if neural says something different. This is correct — manual overrides win.

### 5.3 Multiple SELL orders for same ticker
Each order gets its own row. Some tickers have tiered sells (e.g., NNE has $25.44 and $26.02). Each is compared against the recommended sell independently.

### 5.4 BUY orders for tickers not in positions
Watchlist tickers (AR, ARM, etc.) have BUY orders but no position. The adjuster should still compute recommended shares from `load_capital_config(ticker)`.

### 5.5 Tickers with multi-period pool (higher priority than neural)
For tickers like NNE ($407 pool from multi-period), the pool is NOT $300 neural default. `load_capital_config()` returns the multi-period value. The adjuster inherits this correctly.

---

## 6. Output Format

### 6.1 Sell Adjustments Table

```
## Sell Order Adjustments (N changes needed)

| Ticker | Shares | Current Sell | Current % | Recommended Sell | Rec % | Source | Action |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| NU | 15 | $16.75 | 5.7% | $17.44 | 10.0% | neural_support | RAISE +$0.69 |
| NU | 15 | $17.14 | 8.1% | $17.44 | 10.0% | neural_support | RAISE +$0.30 |
| ACHR | 92 | $6.92 | 6.0% | $6.92 | 6.0% | standard | OK |
```

### 6.2 Buy Adjustments Table

```
## Buy Order Adjustments (N changes needed)

| Ticker | Buy Price | Current Shares | Rec Shares | Pool | Bullets | Source | Action |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| RDW | $7.89 | 6 | 9 | $500 | 7 | neural_support | +3 shares |
| BBAI | $3.71 | 78 | 16 | $363 | 5 | multi-period-scorer | -62 shares |
| NVDA | $174.60 | 1 | 1 | $300 | 5 | default | OK |
```

### 6.3 Summary

```
Sell adjustments: 2 RAISE, 0 LOWER, 12 OK
Buy adjustments: 15 resize, 15 OK
```

---

## 7. Multi-Period Simulation Alignment

### 7.1 Current gap (FACT)

**FACT**: The existing system runs simulations across 4 time periods (12mo, 6mo, 3mo, 1mo) via `multi_period_scorer.py`, computing a weighted composite $/month score per ticker. This drives pool allocations — NNE gets $407 because its composite is $23.7/mo.

**FACT**: The neural support sweeper (`support_parameter_sweeper.py`) currently runs a SINGLE 10-month simulation per combo. It does NOT use multi-period scoring. This means:
- Neural optimal params are tuned on one time window
- No verification that params work across different market conditions
- No regime-aware weighting (1-month Risk-Off handling)
- Inconsistent with how pool allocations are computed

### 7.2 What must change (PROPOSED)

The support sweeper should sweep each parameter combo across 4 periods (12mo, 6mo, 3mo, 1mo), compute a weighted composite P/L, and rank by COMPOSITE — not by single-period P/L.

```
For each ticker:
  For each param combo (sell_default, cat_hard_stop):
    Run simulation at 12 months → P/L_12, cycles_12
    Run simulation at 6 months  → P/L_6, cycles_6
    Run simulation at 3 months  → P/L_3, cycles_3
    Run simulation at 1 month   → P/L_1, cycles_1
    composite = compute_composite({12: result_12, 6: result_6, ...})

  Best combo = highest composite $/month (not highest single-period P/L)
```

**FACT**: `compute_composite()` already exists in `multi_period_scorer.py` (line 112) and handles:
- Significance-based weighting (more cycles = more weight)
- Risk-Off regime adjustment for 1-month period
- Edge case handling (zero cycles, insufficient data)

The support sweeper can import and call `compute_composite()` directly.

### 7.3 Runtime impact (ESTIMATE)

Current: 30 combos × 1 simulation = 30 simulations per ticker (~9s with wick cache)
With multi-period: 30 combos × 4 periods = 120 simulations per ticker (~36s with wick cache)

At 68 tickers with 8 workers: ~36s × 68 / 8 = ~5 minutes. Feasible.

### 7.4 Profile output with multi-period data

The neural support profile should include per-period breakdown:

```json
{
  "CIFR": {
    "params": {"sell_default": 10.0, "cat_hard_stop": 15, ...},
    "composite": 23.5,
    "periods": {
      "12": {"pnl": 495.77, "cycles": 40, "rate": 41.3},
      "6": {"pnl": 280.20, "cycles": 25, "rate": 46.7},
      "3": {"pnl": 120.10, "cycles": 12, "rate": 40.0},
      "1": {"pnl": 35.50, "cycles": 4, "rate": 35.5}
    }
  }
}
```

---

## 8. Reason Chain — Neural Firing Path in Adjustment Table

### 8.1 Current gap

The adjustment table currently shows: "RAISE +$0.69" — but doesn't show WHY the neural network recommends 10% instead of 6%. The user needs to see the decision path.

### 8.2 What the reason chain must include (PROPOSED)

For each adjustment, trace the path through the priority chain and show which neural finding drove the recommendation:

**Sell adjustment reason chain:**
```
NU: RAISE from $16.75 (5.7%) to $17.44 (10.0%)
  Path: target_exit=None → ticker_profiles.json=None → neural_support(10.0%)
  Neural evidence:
    12mo: $346.94 P/L, 15 sells, 100% WR at sell_default=10.0%
    6mo:  $180.20 P/L, 8 sells, 100% WR
    3mo:  $85.10 P/L, 4 sells, 100% WR
    1mo:  $25.30 P/L, 2 sells, 100% WR
    Composite: $23.1/mo
  vs current 6.0%:
    12mo: $247.90 P/L (lower — more frequent exits but smaller gains)
```

**Buy adjustment reason chain:**
```
RDW: +3 shares (6 → 9) at $7.89
  Path: multi-period-scorer=None for bullets → neural_support(pool=$500, bullets=7)
  Neural evidence:
    Optimal pool=$500 discovered by execution sweep (Stage 2)
    $500 pool with 7 bullets → $9/bullet at $7.89
    vs current $300 pool / 5 bullets → $6/bullet
    P/L improvement: $833 (neural) vs $404 (default) = +$429
```

### 8.3 Data sources for reason chain

**FACT**: `compute_recommended_sell()` in `broker_reconciliation.py` returns a `(price, source)` tuple where `source` is a string like `"neural_support 10.0%"` or `"target_exit"` or `"standard 6.0%"`. This already traces which priority level was used.

**FACT**: `get_ticker_pool()` in `shared_utils.py` returns a dict with `"source"` field (`"neural_support"`, `"multi-period-scorer"`, `"portfolio.json (default)"`). This traces the pool source.

**PROPOSED**: The adjuster should also load the neural support candidate's stats (P/L, trades, win rate) to show the evidence behind the recommendation. This data is in `neural_support_candidates.json` under each candidate's `pnl`, `win_rate`, `trades` fields.

### 8.4 Reason chain in output format

```
## Sell Order Adjustments (2 changes needed)

| Ticker | Shares | Current | Recommended | Action | Reason |
| :--- | :--- | :--- | :--- | :--- | :--- |
| NU | 15 | $16.75 (5.7%) | $17.44 (10.0%) | RAISE +$0.69 | neural_support: 10% optimal, $347 P/L, 100% WR, composite $23.1/mo |
| NU | 15 | $17.14 (8.1%) | $17.44 (10.0%) | RAISE +$0.30 | neural_support: same profile |
```

```
## Buy Order Adjustments (3 changes needed)

| Ticker | Price | Current | Recommended | Action | Reason |
| :--- | :--- | :--- | :--- | :--- | :--- |
| RDW | $7.89 | 6 sh | 9 sh | +3 sh | neural_support: pool=$500/7 bullets (P/L $833, +$429 vs default) |
| BBAI | $3.71 | 78 sh | 16 sh | -62 sh | multi-period: pool=$363/5 bullets (over-allocated from old sizing) |
```

---

## 9. Integration with Daily Analyzer

The tool should be callable from daily_analyzer.py as an additional section, OR run standalone:

```bash
python3 tools/neural_order_adjuster.py              # full report with reason chains
python3 tools/neural_order_adjuster.py --sells-only  # sells only
python3 tools/neural_order_adjuster.py --buys-only   # buys only
```

The daily analyzer calls it inline and includes the output in the report after the Neural Profiles section.

---

## 10. Files

| File | Action | Lines |
| :--- | :--- | :--- |
| `tools/neural_order_adjuster.py` | NEW — adjustment tables with reason chains | ~200 |
| `tools/support_parameter_sweeper.py` | MODIFY — add multi-period sweep (12/6/3/1mo), import `compute_composite` | ~40 |
| `tools/daily_analyzer.py` | MODIFY — call adjuster inline, add section to report | ~10 |

**NOT modified**: `shared_utils.py`, `broker_reconciliation.py`, `wick_offset_analyzer.py`, `graph_builder.py`, `multi_period_scorer.py` (compute_composite imported, not modified)

---

## 11. Implementation Order

1. First: Update `support_parameter_sweeper.py` to run multi-period simulations and use `compute_composite()` for ranking. This changes the neural support profiles to include per-period data.
2. Second: Build `neural_order_adjuster.py` that reads the multi-period profiles, computes adjustments, and outputs tables with reason chains showing the neural firing path + per-period evidence.
3. Third: Wire into `daily_analyzer.py` as an inline section.
