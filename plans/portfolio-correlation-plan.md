# Implementation Plan: Portfolio-Level Risk & Sector Concentration

**Date**: 2026-04-11
**Source**: `plans/portfolio-correlation-analysis.md` (verified, v2)

---

## Context

Per-ticker simulations work but ignore portfolio-level risk: sector concentration (46% broad Technology), capital adequacy (no total budget limit), and correlated drawdowns (crypto/quantum/nuclear clusters). This plan adds 4 deliverables that surface actionable risk data in the daily analyzer.

---

## Deliverable 1: Portfolio Stress Test Tool

**File**: `tools/portfolio_stress_test.py` (NEW, ~200 lines)

### Purpose
Simulate sector-correlated shocks on current portfolio. Answer: "If crypto drops 15%, how many bullets fire and do I have enough capital?"

### Architecture
```
CLI: python3 tools/portfolio_stress_test.py [--shock-pct 15] [--workers 8] [--json]

1. Load portfolio.json (positions + pending BUY orders)
2. Group tickers by fine sector (from sector_registry.py FINE_SECTOR_MAP)
3. For each sector with ≥2 active tickers:
   a. Simulate shock: current_price * (1 - shock_pct/100)
   b. Count which pending BUYs would fill at shocked price
   c. Compute capital needed: sum(fill_shares * fill_price) for all fills
   d. Compare against available pools: sum(active_pool - deployed) per ticker
   e. Flag deficit: capital_needed > capital_available
4. Run historical validation: 4-period (12/6/3/1 month) lookback
   - For each period, find actual max sector drawdown from yfinance data
   - Count how many times pending orders WOULD have filled
   - Compute historical fill rate and capital adequacy per period
5. Composite score: weighted by min(events, 5)/5 significance (same as multi_period_scorer)
6. Write data/portfolio_stress_results.json
7. Print markdown summary
```

### Historical Validation (4-period, 8 workers)
```python
PERIODS = [12, 6, 3, 1]  # months

def stress_test_period(sector_tickers, pending_orders, months, shock_pct):
    """For a given period, find actual correlated drawdown events using ticker prices.

    Uses individual ticker prices (NOT sector ETFs — fine sectors like Crypto/Quantum
    have no ETF proxy). Groups tickers by fine sector, finds days where ALL tickers
    in the sector dropped simultaneously, measures how many pending orders would fill.
    """
    # Download price data for all tickers in the sector group
    # For each day, compute sector-group drawdown = avg drawdown across group tickers
    # Find days where group drawdown > shock_pct/2 from rolling 20-day high
    # On those days, check which pending orders would have filled (day_low <= order_price)
    # Return: {events, fills, capital_needed, capital_available, deficit}
```

Use `ThreadPoolExecutor(max_workers=8)` to run sectors × periods in parallel.

**Note:** Individual ticker prices are used instead of sector ETFs because fine sectors (Crypto, Quantum, Nuclear, etc.) have no ETF proxy. This is more accurate for our niche sectors.

### Output Format
```markdown
## Portfolio Stress Test — 2026-04-11

### Sector Concentration
| Sector | Tickers | Positions | Pending BUYs | Deployed | Pool Remaining |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Crypto | CIFR, CLSK, APLD | 3 | 7 | $1,200 | $600 |
| Quantum | IONQ, RGTI | 2 | 4 | $800 | $400 |

### Shock Scenarios (15% sector drop)
| Sector | Fills Triggered | Capital Needed | Available | Surplus/Deficit |
| :--- | :--- | :--- | :--- | :--- |
| Crypto | 5 of 7 | $450 | $600 | +$150 ✅ |
| Quantum | 3 of 4 | $380 | $400 | +$20 ⚠️ |

### Historical Validation (actual sector drawdowns)
| Period | Sector | Max Drawdown | Would-Fill Events | Avg Deficit |
| :--- | :--- | :--- | :--- | :--- |
| 3mo | Crypto | -22% | 2 events | -$180 |
| 1mo | Quantum | -18% | 1 event | $0 |
```

### Output File
`data/portfolio_stress_results.json` — own file, no contamination of existing sweep data.

**~200 lines.**

---

## Deliverable 2: Sector Diversity in watchlist_fitness.py

**File**: `tools/watchlist_fitness.py` (MODIFY)

### Current scoring (100 pts, 7 components)
```
Swing=15, Consistency=15, LevelCount=10, HoldRate=10,
OrderHygiene=20, CycleEfficiency=20, TouchFrequency=10
```

### New scoring (100 pts, 8 components)
Reallocate 5 pts from OrderHygiene (20→15) and 5 pts from CycleEfficiency (20→15) to create a new 10-pt sector diversity component:

```
Swing=15, Consistency=15, LevelCount=10, HoldRate=10,
OrderHygiene=15, CycleEfficiency=15, TouchFrequency=10,
SectorDiversity=10  ← NEW
```

### Sector Diversity Scoring Logic
```python
MAX_SECTOR_DIVERSITY = 10

def score_sector_diversity_fitness(ticker, portfolio):
    """Score sector diversity for watchlist fitness.

    Uses fine sector from FINE_SECTOR_MAP.
    Counts how many OTHER active tickers share the same fine sector.
    """
    from sector_registry import get_sector
    ticker_sector = get_sector(ticker)

    # Count same-sector tickers in positions + watchlist
    positions = set(portfolio.get("positions", {}).keys())
    watchlist = set(portfolio.get("watchlist", []))
    active = (positions | watchlist) - {ticker}

    same_sector = sum(1 for t in active if get_sector(t) == ticker_sector)

    # Diminishing returns (tighter than surgical_filter — fitness is stricter)
    if same_sector == 0:
        return MAX_SECTOR_DIVERSITY      # 10 — unique sector
    elif same_sector <= 2:
        return 8                          # mild penalty
    elif same_sector <= 4:
        return 5                          # moderate
    else:
        return 2                          # heavy — 5+ in same sector
```

### REMOVE Verdict Enhancement
When fitness verdict is REMOVE, add sector reason if applicable:
```python
if same_sector >= 4:
    actions.append(f"Sector overweight: {same_sector + 1} tickers in {ticker_sector}")
```

### Assert Guard Update
```python
assert (SWING_POINTS + CONSISTENCY_POINTS + LEVEL_COUNT_POINTS + HOLD_RATE_POINTS +
        ORDER_HYGIENE_POINTS + CYCLE_EFFICIENCY_POINTS + TOUCH_FREQUENCY_POINTS +
        MAX_SECTOR_DIVERSITY) == 100
```

**~25 lines changed.**

---

## Deliverable 3: Concentration Limit in surgical_filter.py

**File**: `tools/surgical_filter.py` (MODIFY)

### Change
```python
SECTOR_CONCENTRATION_LIMIT = 4  # was 999 (disabled)
```

This means any fine sector with ≥4 existing tickers gets a hard gate: new candidates in that sector are flagged in output but not blocked (informational gate, same as KPI gates 6-9).

### Scoring — No Change
The existing `score_sector_diversity()` function (10/100 pts, diminishing returns) remains unchanged. The concentration limit adds a visible WARNING in the screening output when a candidate would be the 5th+ ticker in a sector.

**~1 line changed + ~5 lines for gate warning output.**

---

## Deliverable 4: Capital Adequacy & Sector Risk in daily_analyzer.py

**File**: `tools/daily_analyzer.py` (MODIFY)

### New Section: Portfolio Risk (after Part 7 reconciliation)

```python
def print_portfolio_risk():
    """Part 8: Portfolio Risk — sector concentration + capital adequacy."""

    # 1. Load portfolio
    with open(PORTFOLIO_PATH) as f:
        portfolio = json.load(f)

    positions = portfolio.get("positions", {})
    pending = portfolio.get("pending_orders", {})
    capital = portfolio.get("capital", {})

    # 2. Capital Adequacy
    total_deployed = sum(
        p["shares"] * p["avg_cost"]
        for p in positions.values()
        if p.get("shares", 0) > 0
    )
    total_pending = sum(
        o["price"] * o.get("shares", 0)
        for tk_orders in pending.values()
        for o in tk_orders
        if o.get("type") == "BUY" and o.get("placed") and not o.get("filled")
    )
    worst_case = total_deployed + total_pending
    per_stock = capital.get("per_stock_total", 600)
    n_tracked = len(set(portfolio.get("watchlist", [])) | set(positions.keys()))
    total_budget = n_tracked * per_stock

    print("## Part 8: Portfolio Risk\n")
    print("### Capital Adequacy")
    print(f"| Metric | Amount |")
    print(f"| :--- | :--- |")
    print(f"| Deployed | ${total_deployed:,.0f} |")
    print(f"| Pending BUYs | ${total_pending:,.0f} |")
    print(f"| Worst Case (all fill) | ${worst_case:,.0f} |")
    print(f"| Total Budget ({n_tracked} × ${per_stock}) | ${total_budget:,.0f} |")
    surplus = total_budget - worst_case
    status = "✅" if surplus > 0 else "⚠️ DEFICIT"
    print(f"| Surplus/Deficit | ${surplus:,.0f} {status} |")

    # 3. Sector Concentration
    from sector_registry import get_sector
    sector_counts = {}
    for tk in set(list(positions.keys()) + portfolio.get("watchlist", [])):
        sec = get_sector(tk)
        sector_counts.setdefault(sec, []).append(tk)

    concentrated = {s: tks for s, tks in sector_counts.items() if len(tks) >= 3}
    if concentrated:
        print("\n### Sector Concentration")
        print("| Sector | Count | Tickers |")
        print("| :--- | :--- | :--- |")
        for sec, tks in sorted(concentrated.items(), key=lambda x: -len(x[1])):
            flag = " ⚠️" if len(tks) >= 5 else ""
            print(f"| {sec}{flag} | {len(tks)} | {', '.join(sorted(tks))} |")

    # 4. Stress Test Summary (if results exist)
    stress_path = Path(__file__).resolve().parent.parent / "data" / "portfolio_stress_results.json"
    if stress_path.exists():
        try:
            with open(stress_path) as f:
                stress = json.load(f)
            deficits = [s for s in stress.get("scenarios", []) if s.get("deficit", 0) > 0]
            if deficits:
                print("\n### Stress Test Warnings")
                for d in deficits:
                    print(f"- **{d['sector']}**: {d['shock_pct']}% drop → "
                          f"${d['capital_needed']:,.0f} needed, "
                          f"${d['available']:,.0f} available → "
                          f"**${d['deficit']:,.0f} deficit**")
        except (json.JSONDecodeError, KeyError):
            pass
```

**~60 lines.**

---

## Files Modified/Created

| File | Action | Lines | Why |
| :--- | :--- | :--- | :--- |
| `tools/portfolio_stress_test.py` | NEW | ~200 | Sector shock simulation |
| `tools/watchlist_fitness.py` | MODIFY | ~25 | Sector diversity scoring |
| `tools/surgical_filter.py` | MODIFY | ~6 | Lower concentration limit |
| `tools/daily_analyzer.py` | MODIFY | ~60 | Portfolio risk section |
| `data/portfolio_stress_results.json` | NEW (output) | — | Stress test results |
| **Total** | | **~291** | |

---

## Implementation Order

1. Deliverable 3: surgical_filter concentration limit (1 line, immediate)
2. Deliverable 2: watchlist_fitness sector diversity (25 lines, score rebalance)
3. Deliverable 4: daily_analyzer portfolio risk section (60 lines)
4. Deliverable 1: portfolio_stress_test.py (200 lines, most complex)
5. Tests
6. System graph update

---

## Verification

1. **Concentration limit**: `python3 -c "from surgical_filter import SECTOR_CONCENTRATION_LIMIT; print(SECTOR_CONCENTRATION_LIMIT)"` → `4`
2. **Fitness scoring**: `python3 -m pytest tests/ -v` — assert guard catches point total ≠ 100
3. **Capital adequacy**: `python3 tools/daily_analyzer.py` — Part 8 shows deployed/pending/surplus
4. **Stress test**: `python3 tools/portfolio_stress_test.py --shock-pct 15` — shows sector scenarios
5. **Stress test output**: `cat data/portfolio_stress_results.json | python3 -m json.tool` — valid JSON
6. **No contamination**: `ls -la data/support_sweep_results.json` — timestamp unchanged
7. **Tests pass**: `python3 -m pytest tests/ -v`
