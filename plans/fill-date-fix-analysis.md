# Analysis: Fill Date Recording Fix

**Date**: 2026-03-31 (Tuesday)
**Purpose**: Two issues — (1) `portfolio_manager.py` fill/sell commands have no `--trade-date` CLI arg despite the functions expecting one, (2) 5 buy fills and 1 sell from yesterday got recorded with today's date.

---

## Issue 1: Missing `--trade-date` argparse wiring (FACT — verified)

**FACT**: `cmd_fill()` at line 228 reads `getattr(args, "trade_date", None) or TODAY`. `cmd_sell()` at line 379 does the same. Both functions are ready to accept a trade date.

**FACT**: The argparse setup at lines 731-734 (fill) and 737-740 (sell) does NOT include `--trade-date`:
```python
fill_p = subparsers.add_parser("fill")
fill_p.add_argument("ticker")
fill_p.add_argument("--price", type=float, required=True)
fill_p.add_argument("--shares", type=int, required=True)
# NO --trade-date
```

**FACT**: Same missing arg for `sell_p` at lines 737-740.

**Fix**: Add `--trade-date` to both `fill_p` and `sell_p` argparse definitions. The attribute name must be `trade_date` (with underscore) to match the `getattr` calls.

```python
fill_p.add_argument("--trade-date", type=str, default=None, dest="trade_date")
sell_p.add_argument("--trade-date", type=str, default=None, dest="trade_date")
```

**~2 lines added.**

---

## Issue 2: Wrong dates in trade_history.json (FACT — verified)

**FACT**: 5 buy fills from 2026-03-30 and 1 sell from today (2026-03-31) were all recorded with date `2026-03-31`:

| Trade | Actual Date | Recorded Date |
| :--- | :--- | :--- |
| RDW BUY 6@7.89 | 2026-03-30 | 2026-03-31 |
| CIFR BUY 4@13.27 | 2026-03-30 | 2026-03-31 |
| CIFR BUY 3@13.09 | 2026-03-30 | 2026-03-31 |
| STIM BUY 95@1.26 | 2026-03-30 | 2026-03-31 |
| RDW BUY 6@7.53 | 2026-03-30 | 2026-03-31 |
| STIM SELL 95@1.35 | 2026-03-31 | 2026-03-31 (correct) |

**FACT**: The STIM sell date is correct (today). Only the 5 buys need date correction.

**FACT**: `portfolio.json` positions are NOT affected for RDW and CIFR — their `entry_date` reflects the original position open date, not the fill date. STIM position is already closed (shares=0).

**Fix**: Update the last 5 BUY entries in `trade_history.json` to change date from `2026-03-31` to `2026-03-30`. The SELL entry stays as-is.

**~5 lines changed in trade_history.json.**

**FACT**: STIM's `entry_date` in portfolio.json is `2026-03-31` but should be `2026-03-30` (the fill opened the position yesterday). However, since STIM is now closed (shares=0), this has no practical impact.

---

## Files

| File | Change | Lines |
| :--- | :--- | :--- |
| `tools/portfolio_manager.py` | Add `--trade-date` to fill and sell argparse | ~2 |
| `trade_history.json` | Fix 5 buy dates from 2026-03-31 to 2026-03-30 | ~5 |
| **Total** | | **~7** |
