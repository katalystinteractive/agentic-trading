# Phase 1: Foundation — Measure What We Have
*Status: Not Started | Depends on: Nothing | Enables: All other phases*

## Goal
Know how the system is actually performing before optimizing it. Every optimization in Phases 2-5 requires baseline metrics that don't exist today.

**Key constraint:** Phase 1 is 100% mechanical — ZERO qualitative/LLM work. Every output is deterministic from input data.

## Deliverable
`python3 tools/pnl_dashboard.py` — single command gives full performance picture: realized P/L, cycle analytics, per-ticker ranking, benchmark comparison, capital utilization.

## Gaps Addressed

| # | Gap | Impact | Effort |
| :--- | :--- | :--- | :--- |
| 7.6 | Trade history normalization (structured JSON) | Medium | Medium |
| 7.1 | Aggregated P/L dashboard | High | Low |
| 7.2 | Cycle-level analytics | High | Medium |
| 7.5 | Per-ticker profitability ranking | High | Medium |
| 8.1 | Post-sell continuation tracking | High | Low |
| 7.3 | Benchmark comparison (SPY/QQQ) | Medium | Low |
| 7.4 | Capital utilization metric | Medium | Low |

### Existing Infrastructure (do NOT rebuild)

| Asset | Location | Reuse How |
| :--- | :--- | :--- |
| `trade_history.json` | Root | Flat BUY/SELL ledger, auto-populated by `portfolio_manager.py _record_trade()`. Source data for cycle grouper. |
| `portfolio.json` | Root | Positions, pending_orders, capital config, watchlist. Source for utilization + open position health. |
| `portfolio_status.py` | `tools/` | `fetch_prices(tickers)` returns `{ticker: {price, day_low, day_high, stale, last_trade_date}}`. Reuse for live prices — do NOT re-implement yfinance fetching. |
| `market_pulse.py` | `tools/` | SPY/QQQ/IWM + VIX 3-month data. Reference for benchmark fetch pattern. |
| `trading_calendar.py` | `tools/` | `is_trading_day(d)`, `last_trading_day(d)`, `as_of_date_label(d)`. Reuse for trading day counting. |
| `cooldown.json` | Root | Root key `"cooldowns"` → list of `{ticker, sold_date, reeval_date, cooldown_days, note}`. |

## Detailed Requirements

### 1A. Trade History Backfill (Gap 7.6)

**Problem:** Trade data lives in unstructured narrative `memory.md` files across 20+ tickers. Example:
```
- **2026-03-02:** BUY 6 shares @ $9.66 (Bullet 1 filled). Cost: $57.96.
- **2026-03-02:** SELL 6 shares @ $10.425 (full exit). Revenue: $62.55. **Profit: +$4.59 (+7.9%).**
```
Cannot be queried, aggregated, or analyzed programmatically.

**Solution:** One-time backfill tool `tools/trade_history_backfill.py` that extracts
historical trades from `tickers/*/memory.md` files predating the `trade_history.json`
auto-recording system. NOT the ongoing recording mechanism — `portfolio_manager.py
_record_trade()` handles that.

1. Parse all `tickers/*/memory.md` files using multi-pattern extraction.
   Five format patterns, tried in order per line:

   **Pattern A — Standard:** `r'(?:\*\*)?(\d{4}-\d{2}-\d{2}):?(?:\*\*)?\s+(BUY|SELL)\s+(\d+)\s+(?:shares?\s+)?@\s+\$?([\d.]+)'`
   Example: `**2026-02-23:** BUY 3 shares @ $17.33`
   Also matches: `- 2026-03-05: BUY 16 @ $3.81` (BBAI, no bold, no "shares") and `**2026-03-06:** SELL 2 @ $53.45` (TEM, no "shares")

   **Pattern B — "Bullet N filled at":** `r'\*\*(\d{4}-\d{2}-\d{2}):\*\*\s+Bullet\s+\d+\s+filled\s+at\s+\$?([\d.]+)\s+\((\d+)\s+shares?'`
   Implicit side = BUY. Example: `**2026-02-23:** Bullet 1 filled at $31.30 (3 shares)`

   **Pattern C — "Sold":** `r'\*\*(\d{4}-\d{2}-\d{2}):\*\*\s+Sold\s+(\d+)\s+shares?\s+@\s+\$?([\d.]+)'`
   Implicit side = SELL. Example: `**2026-02-27:** Sold 3 shares @ $33.40`

   **Pattern D — Multi-trade line:** When a line yields more than one match from the date-free
   trade regex (below), use Pattern D instead of Pattern A. Detection: apply `re.findall`
   with the date-free regex and check `len(matches) > 1`. Do NOT use keyword substring
   search (`"SELL" in line`) — this would false-positive on words like "SELL-off".
   `r'(BUY|SELL)\s+(\d+)\s+(?:shares?\s+)?@\s+\$?([\d.]+)'`
   Use Pattern D findall results exclusively for this line, attaching the date extracted
   by Pattern A to each match.
   Example: `**2026-03-03:** BUY 3 @ $17.16 (B1). BUY 3 @ $16.92 (B2).`
   yields two BUY records both dated 2026-03-03.

   **Pattern E — Table format:** `r'\|\s*(\S+)\s*\|\s*(BUY|SELL)\s*\|\s*(\d+)\s*\|\s*\$?([\d.]+)'`
   Matches rows in markdown tables (e.g., IONQ, USAR, INTC memory.md). Date column may
   contain "Pre-YYYY" — parse as YYYY-01-01 and set `"pre_strategy": true`.

   Order: try Patterns B, C, E first (specific), then A/D (general). Each line may yield
   0, 1, or N records (Pattern D).
2. Produce records matching `_record_trade()` schema: `{ticker, side, date, shares, price, note}`.
   Set `avg_cost_before`, `avg_cost_after`, `total_shares_after` to `null` (cannot be
   reconstructed reliably for backfilled records).
   **`id` assignment:** Read existing `trade_history.json`, find `max(t["id"] for t in trades)`,
   assign backfilled records sequential ids starting at `max_id + 1`. If no existing trades,
   start at 1.
3. Add `"backfilled": true` flag to distinguish from auto-recorded trades.
4. **Deduplication:** Before inserting, check if a trade with matching `(ticker, side, date,
   shares)` exists in `trade_history.json` AND `abs(existing.price - parsed.price) < 0.01`.
   The 4 non-price fields are sufficient for identity; price tolerance handles text-to-float
   rounding (e.g., "$31.30" → 31.3 vs recorded 31.30). Skip if match found.
5. **Validation:** For each SELL in memory.md that states a profit % (regex:
   `r'[+-]?([\d.]+)%'`), compute `(sell_price - entry_avg) / entry_avg * 100` where
   `entry_avg` comes from all BUYs for the same ticker since the last SELL that brought
   shares to 0 (i.e., same-cycle BUYs). If no preceding BUY exists (orphaned SELL), skip
   validation for that SELL and add to `parse_warnings[]`:
   `"{TICKER}: cannot validate SELL profit — no preceding BUYs found"`.
   If discrepancy > 0.5 percentage points, add to `parse_warnings[]`:
   `"CLSK: memory.md states +7.9% but computed +7.6% for 2026-03-02 SELL"`.
6. **Pre-strategy flag:** If `portfolio.json` position note or `tickers/<TICKER>/identity.md`
   contains "pre-strategy", flag all trades for that ticker as `"pre_strategy": true`.

**CLI:** `python3 tools/trade_history_backfill.py [--dry-run]`
- `--dry-run`: Print what would be added without writing.
- Output: markdown table of added trades + warnings.

**Missing file handling:** If `tickers/<TICKER>/memory.md` does not exist, skip that ticker
with a note: `"Skipped {ticker}: no memory.md"`. Do not raise an error.

---

### 1B. Cycle Grouper (Gap 7.2)

**Problem:** `trade_history.json` is a flat ledger of individual BUY/SELL events. Analytics
require grouping these into complete buy→sell cycles.

**Solution:** New tool `tools/cycle_grouper.py` that reads `trade_history.json` and groups
records into completed trade cycles.

**Mechanical cycle definition:**
- **Start:** First BUY record for a ticker where either (a) no prior trade exists for this
  ticker, or (b) the immediately preceding trade has `total_shares_after == 0` (or `null`
  with running count at 0 — see "Backfilled records" below).
- **End (full close):** A SELL record where `total_shares_after == 0` (or `null` with running
  count reaching 0). Closes the cycle.
- **Partial sell:** A SELL where `total_shares_after > 0` is a sub-event within the open
  cycle — does NOT close it.
- **Still open:** If the last trade for a ticker has `total_shares_after > 0`, the cycle
  has `"status": "open"`.
- **Backfilled records** (null `total_shares_after`): Sort all records by `(ticker, date, id)`
  first, then walk in order maintaining running share count. A SELL bringing the running
  count to 0 = cycle end. Sorting is required because backfilled records may be inserted
  out of chronological order.
- **Orphaned SELL:** If the first trade for a ticker (in date order) is a SELL with no
  preceding BUY, emit warning: `"WARNING: {ticker} has orphaned SELL (id={id}, date={date})
  with no preceding BUY — skipping from cycle formation. Resolve via backfill."` Skip this
  SELL from cycle formation entirely. Add to `parse_warnings[]`. Known case: LUNR SELL id=9
  in production `trade_history.json`.
- **Phantom open cycle validation:** After grouping, for any cycle with `status: "open"`,
  cross-check against `portfolio.json positions[ticker]["shares"]`. If shares == 0 but cycle
  is open, emit warning: `"WARNING: {ticker} cycle {cycle_id} is open but portfolio.json
  shows 0 shares — likely missing SELL record."` Add to `parse_warnings[]`.

**Cycle fields (all computed mechanically):**

| Field | Formula |
| :--- | :--- |
| `cycle_id` | `"{TICKER}-{N}"` — sequential per ticker |
| `status` | `"closed"` or `"open"` |
| `pre_strategy` | `true` if any entry BUY has `"pre_strategy": true` |
| `entry_shares` | `sum(e.shares for e in entries)` |
| `entry_avg` | `sum(e.shares * e.price for e in entries) / sum(e.shares for e in entries)` |
| `exit_shares` | `sum(x.shares for x in exits)` |
| `exit_avg` | `sum(x.shares * x.price for x in exits) / sum(x.shares for x in exits)` |
| `profit_pct` | `(exit_avg - entry_avg) / entry_avg * 100` |
| `profit_dollar` | `(exit_avg - entry_avg) * exit_shares` |
| `cycle_days` | `(last_exit_date - first_entry_date).days` (calendar days) |
| `trading_days` | Count of `is_trading_day()` days between first entry and last exit (inclusive) |
| `bullets_used` | `len(entries)` |
| `zones_used` | `list(set(e.get("zone") for e in entries if e.get("zone")))` — preserves active/reserve segmentation from trade_history.json |

**Output:** Writes `cycle_history.json`:
`{"cycles": [...], "parse_warnings": [...], "last_updated": "YYYY-MM-DD"}`

**CLI:** `python3 tools/cycle_grouper.py [--ticker CLSK]`
- `--ticker`: Filter output to cycles for the specified ticker only. Still processes all
  trades internally (to maintain correct running share counts), but only writes cycles
  matching the filter to output. When omitted, outputs all tickers.

**Merge strategy:** When `cycle_history.json` already exists, cycle_grouper reads it first.
For each cycle_id present in both old and new data, preserve any `post_sell_tracking`
sub-object from the old version. Only overwrite the cycle-level fields the grouper owns
(entry_avg, exit_avg, profit_pct, etc.). New cycles get no `post_sell_tracking` (added
later by post_sell_tracker.py). This prevents re-runs from destroying accumulated tracking data.

---

### 2. P/L Dashboard (Gaps 7.1, 7.2, 7.5)

**Problem:** No single view of system performance. Cannot answer basic questions: total profit, win rate, best ticker, worst ticker.

**Solution:** New tool `tools/pnl_dashboard.py` that reads `cycle_history.json` + `portfolio.json` and outputs all 6 tables below.

**Data freshness header:** `pnl_dashboard.py` must output as its first line:
`# P/L Dashboard — {as_of_date_label(today)}`
using `trading_calendar.as_of_date_label()`.

**Output:** Writes `pnl_dashboard.md` to project root AND prints to stdout (matching
`portfolio_status.py` convention).

**CLI:** `python3 tools/pnl_dashboard.py [--period week|month|ytd|all] [--ticker CLSK]`
- `--period`: Filters Tables 1-2 and 5 to the specified period only (instead of showing all
  periods). Tables 3, 4, and 6 are unaffected (they are snapshot-based, not period-based).
  Default: show all periods.
- `--ticker`: Filters Tables 1-3 to cycles for the specified ticker. Table 4 filters to that
  ticker's open position (if any). Tables 5-6 are unaffected (benchmark and utilization are
  portfolio-wide). Default: all tickers.

#### Table 1: Summary

**Zero-cycle guard:** If `len(closed_cycles) == 0`, display `--` for Win Rate, Avg
Profit/Cycle, Avg Cycle Duration, Profit Margin on Turnover, and Return on Pool Capital.
Skip division entirely.

| Metric | Formula |
| :--- | :--- |
| Total Realized Profit ($) | `sum(c.profit_dollar for c in closed_cycles)` |
| Total Realized Cycles | `len(closed_cycles)` |
| Win Rate | `len([c for c in closed_cycles if c.profit_pct > 0.0]) / len(closed_cycles) * 100`. Win = strictly `> 0.0`. Zero-profit = loss. |
| Avg Profit/Cycle (%) | `mean(c.profit_pct for c in closed_cycles)` |
| Avg Profit/Cycle ($) | `mean(c.profit_dollar for c in closed_cycles)` |
| Avg Cycle Duration | `mean(c.cycle_days for c in closed_cycles)` calendar days |
| Total Capital Turnover | `sum(c.entry_avg * c.entry_shares for c in closed_cycles)` — cumulative, counts recycled capital each cycle |
| Profit Margin on Turnover | `total_realized_profit / total_capital_turnover * 100` — measures margin per dollar deployed (double-counts recycled capital by design; useful for comparing efficiency across tickers) |
| Return on Pool Capital | `total_realized_profit / (len(portfolio["watchlist"]) * capital["per_stock_total"]) * 100` — measures return on actual capital allocated from portfolio.json. Note: pre-strategy tickers (IONQ, USAR) are included in watchlist count; their $600 pool is nominal. This makes the metric conservative — acceptable, do not exclude them. |
| Unrealized P/L ($) | `sum((current_price - pos.avg_cost) * pos.shares for open positions)`. Fetch via `portfolio_status.fetch_prices()`. |
| Net P/L ($) | `total_realized_profit + unrealized_pnl` |

#### Table 2: Period Breakdown

| Period | Cycles | Win Rate | Profit ($) | Avg/Cycle (%) |
| :--- | :--- | :--- | :--- | :--- |
| This Week | ... | ... | ... | ... |
| This Month | ... | ... | ... | ... |
| Last 30 Days | ... | ... | ... | ... |
| YTD | ... | ... | ... | ... |
| All Time | ... | ... | ... | ... |

**Period definitions (mechanical):**

| Period | Filter predicate |
| :--- | :--- |
| This Week | `last_exit >= Monday of current ISO week` where Monday = `today - timedelta(days=today.weekday())`. `today = date.today()` (calendar day, not last trading day — cycle exit dates are calendar dates, so the filter should use calendar boundaries). |
| This Month | `last_exit.year == today.year AND last_exit.month == today.month` |
| Last 30 Days | `last_exit >= today - timedelta(days=30)` |
| YTD | `last_exit.year == today.year` |
| All Time | All closed cycles |

#### Table 3: Per-Ticker Ranking

| Rank | Ticker | Cycles | Win% | Avg Profit | Total $ | Simple Ann. | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |

**Sort order:** Rank by `Total $` descending (highest realized dollar profit first). Tickers
with 0 completed cycles sort to the bottom, ordered alphabetically.

**Annualized return:** `total_profit_pct_for_ticker * (365 / observation_days)` where
`observation_days = (today - first_entry_date).days` for that ticker's first cycle entry.
Label as "Simple Ann." (not compound, not risk-adjusted).
Guards: if `observation_days < 30`, display "N/A (< 30d data)". If 0 completed cycles,
display "N/A". This avoids the naive `avg_profit_pct * (365 / avg_cycle_days)` formula
which assumes zero idle time between cycles.

`total_profit_pct_for_ticker = sum(c.profit_dollar for c in ticker_closed_cycles) / sum(c.entry_avg * c.entry_shares for c in ticker_closed_cycles) * 100`
This is the dollar-weighted aggregate return — consistent with Profit Margin on Turnover
methodology. Not the sum of individual cycle profit_pct values (which would ignore position
size differences between cycles).

**Status label rules** (deterministic, first match wins):

| Priority | Status | Rule |
| :--- | :--- | :--- |
| 1 | No Cycles | 0 completed cycles AND open position exists |
| 2 | Trapped | Open position AND (`unrealized_pnl_pct <= -15.0` OR `days_held >= 60`) |
| 3 | Underwater | Open position AND `unrealized_pnl_pct < 0.0` |
| 4 | Active | Open position AND `unrealized_pnl_pct >= 0.0` |
| 5 | Cooldown | No open position AND ticker in `cooldown.json` with `reeval_date > today` |
| 6 | Re-entry | No open position AND ≥ 1 completed cycle |
| 7 | Watching | No position, 0 completed cycles |

Formulas:
- `unrealized_pnl_pct = (current_price - avg_cost) / avg_cost * 100`
- `entry_date`: Read from `portfolio.json positions[ticker]["entry_date"]`. If absent, fall
  back to earliest BUY date in `cycle_history.json` for the ticker's current open cycle.
  If neither exists, use `"unknown"` and display "N/A" for days_held.
- `days_held = (today - date.fromisoformat(entry_date)).days`
- For `entry_date` starting with "pre-", parse as `2026-01-01` and append "(est)" to output.

#### Table 4: Open Position Health

| Ticker | Shares | Avg Cost | Current | P/L | Days Held | Bullets | Time Stop |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |

**Time Stop rule:** `"REVIEW"` if `days_held >= 60`, `"OK"` otherwise. The 60-day threshold
comes from strategy.md exit protocol ("8 weeks ~ 60 days").

**Bullets column:** Display raw `bullets_used` from portfolio.json as-is (may be int like `5`
or string like `"5 active + R1"`). Do not reformat.

**Filter:** Only include tickers where `portfolio.json positions[ticker]["shares"] > 0`.
Tickers with no open position do not appear in the Open Position Health table.

#### Table 5: Benchmark Comparison (Gap 7.3)

**Not a separate tool** — included within `pnl_dashboard.py`.

**Data source:** `yf.Ticker("SPY").history(period="1y")` (and QQQ). Single fetch, compute
returns for same periods as Table 2.

**Formulas:**
- Benchmark return: `(close_end - close_start) / close_start * 100` where `close_start` is
  closing price on first trading day of the period, `close_end` is most recent close.
- Strategy return: `sum(c.profit_dollar for period) / sum(c.entry_avg * c.entry_shares for period) * 100`.
  Return on deployed capital for cycles completed within that period. If no cycles, show "N/A".
- **Column label:** "Excess Return" (not "Alpha" — this is simple excess return, not risk-adjusted).

**Period start dates:** Same as Table 2 period definitions. For "All Time", start = earliest
`first_entry` date across all cycles.

| Benchmark | Period | Benchmark Return | Strategy Return | Excess Return |
| :--- | :--- | :--- | :--- | :--- |

#### Table 6: Capital Utilization (Gap 7.4)

**Not a separate tool** — included within `pnl_dashboard.py`.

**Formulas (all read from portfolio.json):**

| Category | Formula |
| :--- | :--- |
| Ticker count | `len(portfolio["watchlist"])` — read from portfolio.json, never hardcode |
| Total pool | `ticker_count * capital["per_stock_total"]` |
| Active positions (at cost) | `sum(pos["shares"] * pos["avg_cost"] for pos in positions.values() if pos["shares"] > 0)` |
| Pending buy orders | `sum(order["price"] * order["shares"] for all BUY orders without "filled" key)` — limit price × shares = max commitment. Exclude filled orders (those with `"filled"` key). |
| Available (idle) | `total_pool - active_positions - pending_buy_orders` — can be negative if over-allocated |
| Utilization rate | `(active_positions + pending_buy_orders) / total_pool * 100` |

---

### 3. Post-Sell Continuation Tracking (Gap 8.1)

**Problem:** When we sell CLSK at $10.24, we don't know if it went to $10.80 afterward. We can't measure how much money we're leaving on the table.

**Solution:** New tool `tools/post_sell_tracker.py` that reads `cycle_history.json` and updates closed cycles with post-sell price tracking data.

**Mechanical definitions:**

- **Tracking window:** 5 trading days after sell date. Count using
  `trading_calendar.is_trading_day()`. Day 1 = first trading day AFTER sell date.
- **Data source:** `yfinance history(period="10d")` — covers weekends/holidays in window.
- **`peak_after_sell`:** Highest **daily close** (not intraday high) during the 5-trading-day
  window. Rationale: intraday highs are not realistically capturable; close prices represent
  achievable exits.
- **`trough_after_sell`:** Lowest daily close during the window.
- **`money_left_on_table_pct`:** `max(0, (peak_after_sell - sell_price) / sell_price * 100)`.
  Clamped to 0 — if price only fell after sell, money left = 0.
- **`close_5d_after`:** Closing price on the 5th trading day after sell.
- **`close_5d_pct`:** `(close_5d_after - sell_price) / sell_price * 100`.
- **`tracking_complete`:** `true` once 5 trading days have elapsed since sell date.

**Output schema per cycle:**
```json
{
  "post_sell_tracking": {
    "sell_price": 10.24,
    "sell_date": "2026-03-13",
    "peak_after_sell": 10.80,
    "peak_date": "2026-03-14",
    "trough_after_sell": 9.50,
    "money_left_on_table_pct": 5.5,
    "close_5d_after": 9.76,
    "close_5d_pct": -4.7,
    "tracking_complete": true
  }
}
```

**CLI:** `python3 tools/post_sell_tracker.py [--backfill]`
- Default: Updates cycles where `tracking_complete` is false or missing.
- `--backfill`: Also fills tracking for historical sells (skip with warning if yfinance
  lacks data that far back).

**File ownership:** `post_sell_tracker.py` reads and updates `cycle_history.json`, adding
`post_sell_tracking` fields to closed cycles. It does NOT read or write `trade_history.json`
— that file is a flat ledger maintained exclusively by `portfolio_manager.py _record_trade()`.

**This data feeds Phase 4** (gap 8.2 — adaptive sell targets).

---

## Implementation Order

1. `tools/trade_history_backfill.py` — one-time memory.md parser [no deps]
2. `tools/cycle_grouper.py` — groups flat trades into cycles [depends on: trade_history.json]
3. `tools/pnl_dashboard.py` — all 6 tables [depends on: cycle_history.json]
   - Tables 1-4: Summary, Period Breakdown, Per-Ticker Ranking, Open Position Health
   - Table 5: Benchmark (fetches SPY/QQQ via yfinance)
   - Table 6: Capital Utilization (reads portfolio.json)
4. `tools/post_sell_tracker.py` — daily continuation tracking [depends on: cycle_history.json]
5. Integration: add `post_sell_tracker.py` to `morning_gatherer.py` parallel tool list

## Success Criteria

- [ ] `cycle_grouper.py` groups all trades with 0 unexpected unmatched SELL records (orphaned SELLs emitted as warnings, not failures)
- [ ] `pnl_dashboard.py` produces all 6 tables with no "N/A" for tickers with completed cycles
- [ ] Every status label assignment traces to a specific threshold rule
- [ ] `post_sell_tracker.py --backfill` fills tracking for all sells older than 5 trading days
- [ ] Benchmark excess returns match manual SPY/QQQ calculations within 0.1% rounding tolerance
- [ ] Capital utilization total equals `len(watchlist) * per_stock_total` from portfolio.json
- [ ] All formulas are explicit in the spec — no "calculate X" without the math
- [ ] Zero LLM/qualitative work — every output is deterministic from input data
- [ ] Win Rate uses strictly `> 0.0` (not `>= 0`)
- [ ] Annualized return labeled "Simple Ann." with `observation_days < 30` guard (display "N/A (< 30d data)")
- [ ] Benchmark column labeled "Excess Return" (not "Alpha")
- [ ] Post-sell tracking uses daily close (not intraday high) with clamped `money_left >= 0`
- [ ] `trade_history_backfill.py` deduplicates against existing `trade_history.json` records
- [ ] Backfilled records flagged with `"backfilled": true`, pre-strategy with `"pre_strategy": true`
