# Analysis: Daily Dip Strategy Parameter Tuning

**Date**: 2026-03-29 (Sunday, 1:45 PM local / 6:45 AM ET)
**Purpose**: Determine which parameters to tune, using LUNR as the reference ticker, to make the same-day dip strategy profitable.

---

## 1. The Problem

The 6-month neural dip backtest produced:
- 70 trades, 47% win rate, $0.10 total P/L (breakeven)
- 11 stops hit vs 3 targets in the recent 30-day window

But the standalone dip simulator showed LUNR at **69% win rate, +$14.28 P/L** over the same period while CLSK (-$28.83) and CIFR (-$33.76) destroyed the portfolio.

**LUNR works. The strategy parameters don't work for most tickers.** The question: can we tune parameters so the strategy is profitable across the portfolio, or should we be more selective about WHICH tickers qualify?

---

## 2. LUNR: Why It Works

| Metric | LUNR | CLSK | CIFR | Threshold |
| :--- | :--- | :--- | :--- | :--- |
| Median daily range | **10.7%** | 7.6% | 7.8% | ≥ 3% (current gate) |
| Days with 3%+ swing | **100%** | 100% | 100% | ≥ 60% (current gate) |
| Dip sim win rate | **69%** | 14% | 13% | N/A |
| Dip sim P/L | **+$14.28** | -$28.83 | -$33.76 | N/A |
| Same-day exit rate | 9/13 (69%) | Low | Low | N/A |

**LUNR's edge**: 10.7% median daily range means the stock swings enough to hit a 3% target AND recover from a 1% dip on the same day. With 10.7% range, a 3% move is only 28% of the daily range — high probability.

**CLSK/CIFR fail because**: Even though they pass the 3% range gate, their actual dip-recovery pattern doesn't align. They dip and keep falling, or bounce insufficiently.

---

## 3. Current Parameters and Their Effects

### 3.1 Sell Target: 3% vs 4%

**History**: The backtest config comment says `# optimized from 3% via backtest sweep` — meaning 4% was BETTER in a prior sweep. But the recent simulator used 3%.

**LUNR at 3% target**: 69% win rate (9/13 hit target)
**LUNR at 4% target**: Need to estimate. With 10.7% median range, a 4% move is 37% of the range — still very achievable. Likely 55-65% win rate, but higher P/L per win ($4 vs $3 on $100 trade).

**Key tradeoff**: Higher target = fewer wins but more profit per win. Lower target = more wins but smaller edge over stops.

**Risk/reward at 3%/3% stop**: 1:1 ratio. Need >50% win rate to profit.
**Risk/reward at 4%/3% stop**: 1.33:1 ratio. Need only >43% win rate to profit.

**Evidence says**: 4% target is better MATHEMATICALLY (favorable risk/reward) but only works for tickers with enough daily range to actually hit it.

### 3.2 Stop Loss: -3%

**Current**: -3% hard stop.

**LUNR data**: Only 1 stop hit in 9 same-day trades (11%). The stop is rarely triggered for LUNR because its bounces are strong.

**CLSK/CIFR data**: Stops hit 12-14 times each. The stop is the primary loss mechanism.

**Question**: Is -3% too tight for high-volatility stocks? Or is it correct and the problem is stock selection?

**Answer from LUNR**: -3% is fine for LUNR (11% stop rate). The problem is CLSK/CIFR getting selected at all.

### 3.3 Breadth Threshold: 50%

**Current**: 50% of tickers must dip >1% from open.

**6-month data**: Only 14 of 125 days (11%) passed this threshold. Of those, the bounce threshold further filtered to a subset.

**Problem**: 50% breadth means we only trade on days when MORE THAN HALF the watchlist is dipping. This is a severe market-wide selloff filter. It excludes single-stock dips that could be profitable (LUNR dips alone while the market is flat).

**LUNR insight**: LUNR dips on many more days than just the breadth-confirmed ones. Its 10.7% range means it dips >1% from open on roughly 60-70% of trading days — but the breadth gate blocks most of those because the REST of the portfolio isn't dipping simultaneously.

### 3.4 Minimum Daily Range: 3%

**Current**: Ticker must have median daily range ≥ 3%.

**LUNR**: 10.7% — passes easily.
**CLSK**: 7.6% — passes.
**CIFR**: 7.8% — passes.

**Problem**: All three pass the 3% gate, but only LUNR is profitable. The gate is too loose — it lets in tickers that swing enough to trigger entries but not enough to hit targets reliably.

**Evidence**: LUNR at 10.7% has 69% win rate. CLSK at 7.6% has 14%. The cutoff for profitability appears to be around 8-10% median range, not 3%.

### 3.5 Dip Threshold: 1%

**Current**: Ticker must dip >1% from open to qualify.

**LUNR**: With 10.7% median range, a 1% dip is only 9% of the daily range — very common. This means LUNR qualifies on most days.

**Question**: Should this be higher (e.g., 2%) to filter out shallow dips that don't lead to strong recoveries?

**LUNR data**: All 13 LUNR trades had >1% dip. Many had 2-3%+ dips. Raising to 2% would reduce entries but might improve win rate by ensuring deeper dips (stronger bounce potential).

### 3.6 Bounce Threshold: 0.3%

**Current**: Ticker must bounce >0.3% in second hour to confirm recovery.

**Problem**: 0.3% is tiny. Almost any noise in the second hour produces a 0.3% move. This gate barely filters anything.

**LUNR data**: LUNR always bounces >0.3% when it dips — its volatility guarantees this. But so do CLSK and CIFR, which then fail to sustain the bounce.

**Consider raising to 1.0%**: A 1% bounce in the second hour indicates genuine buying pressure, not noise.

---

## 4. Root Cause: Two Separate Problems

### Problem A: Ticker Selection (which tickers qualify)

The 3% range gate lets in tickers that shouldn't be playing the dip strategy. LUNR works because 10.7% range gives it room to dip, bounce, and hit target. CLSK/CIFR at 7-8% don't have enough range for reliable same-day exits.

**Fix**: Raise `min_daily_range` from 3% to a higher threshold. Evidence suggests 8-10% is where same-day profitability kicks in.

### Problem B: Signal Quality (which days to trade)

The 50% breadth gate is a market-wide filter that's too selective (11% of days) AND doesn't correlate with per-ticker success. LUNR can profitably dip on days when breadth is only 20-30%, but the gate blocks those trades.

**Two approaches**:
- **Keep breadth but lower to 30%**: More signal days, but risk of false positives
- **Drop breadth, use per-ticker gates only**: Each ticker's own dip pattern determines entry, not cross-ticker breadth. This is a fundamental strategy change.

---

## 5. What Parameters to Test

Based on the evidence, here are the parameters worth sweeping:

### Tier 1: High Impact (change the outcome)

| Parameter | Current | Test Values | Why |
| :--- | :--- | :--- | :--- |
| min_daily_range | 3% | **6%, 8%, 10%** | Filter out tickers like CLSK/CIFR that pass at 3% but lose money |
| sell_target_pct | 3% (or 4%) | **3%, 3.5%, 4%, 5%** | Risk/reward ratio. 4%/3% stop = 1.33:1 ratio |
| breadth_threshold | 50% | **30%, 40%, 50%, DISABLED** | 50% is too selective. Per-ticker may be enough |

### Tier 2: Medium Impact (refine quality)

| Parameter | Current | Test Values | Why |
| :--- | :--- | :--- | :--- |
| dip_threshold_pct | 1.0% | **1.0%, 1.5%, 2.0%** | Deeper dip = stronger bounce potential |
| bounce_threshold_pct | 0.3% | **0.3%, 0.5%, 1.0%** | Current is noise-level. 1.0% = real buying pressure |
| stop_loss_pct | -3% | **-2%, -3%, -4%** | Tighter stop = less loss per trade but more triggers |

### Tier 3: Low Impact (operational)

| Parameter | Current | Test Values | Why |
| :--- | :--- | :--- | :--- |
| max_tickers | 5 | **3, 5** | Fewer tickers = concentrate on best dippers |
| budget | $100 | **$50, $100** | Risk management per trade |

---

## 6. The LUNR-Derived Parameter Set

If we optimize for "what works for LUNR" and apply that filter to all tickers:

```python
LUNR_OPTIMIZED_CONFIG = {
    "dip_threshold_pct": 1.5,         # Deeper dip entry
    "bounce_threshold_pct": 1.0,       # Real bounce, not noise
    "breadth_threshold": 0.30,         # Lower breadth (more signal days)
    "range_threshold_pct": 8.0,        # Only high-swing tickers
    "recovery_threshold_pct": 80.0,    # Only reliable recoverers
    "sell_target_pct": 4.0,            # 4% target (1.33:1 risk/reward vs 3% stop)
    "stop_loss_pct": -3.0,             # Keep stop tight
    "budget_normal": 100,
    "budget_risk_off": 50,
    "max_tickers": 5,
}
```

**What this changes**:
- Only tickers with ≥8% median daily range qualify (filters out CLSK 7.6%, keeps LUNR 10.7%)
- Requires 80% recovery rate (filters out inconsistent bouncers)
- 30% breadth (more trading days, less selective)
- 1.5% dip + 1.0% bounce (real moves, not noise)
- 4% target with 3% stop (1.33:1 favorable risk/reward)

**Which tickers would pass at 8% range?** From the portfolio:
- LUNR: 10.7% ✓
- CIFR: 7.8% ✗ (barely fails)
- CLSK: 7.6% ✗
- RDW: 9.5% ✓
- STIM: 9.8% ✓
- ACHR: 6.0% ✗
- RGTI: 6.4% ✗

Only ~3-5 tickers would qualify with an 8% range gate vs the current 15+ at 3%.

---

## 7. Recommended Approach

### Option A: Sweep All Parameters (Scientific)
Run the backtester with a parameter grid across Tier 1 + Tier 2 parameters. ~72 combinations (3×4×4 × 3×3×3). Each runs over 125 trading days. Report the best combination by Sharpe ratio.

**Pro**: Data-driven answer.
**Con**: 72 × 125 days = ~9,000 day-replays. At ~2 seconds per day = ~5 hours runtime.

### Option B: Test LUNR-Optimized Config Only (Fast)
Run the backtester once with the LUNR-derived parameters above and compare against current config.

**Pro**: Fast (2 minutes). Clear A/B comparison.
**Con**: May not be the global optimum.

### Option C: Two-Stage (Pragmatic)
1. First: test LUNR-optimized config vs current config (2 minutes)
2. If LUNR-optimized is better: sweep around those values (narrower grid, ~20 combinations)

**Recommendation**: Option C — validate the hypothesis fast, then refine.

---

## 8. What We'd Learn

After the sweep, we'll know:
1. **Does raising min_daily_range from 3% to 8% eliminate the losers?** (CLSK, CIFR)
2. **Does lowering breadth from 50% to 30% produce more signal days without more false positives?**
3. **Is 4% target better than 3% for high-swing tickers?**
4. **Does requiring 1% bounce (vs 0.3%) filter out fake recoveries?**

Each answer is backed by 125 days of real data, not guessing.
