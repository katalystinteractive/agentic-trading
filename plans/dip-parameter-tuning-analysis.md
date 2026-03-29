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

## 8. Per-Ticker Dip Profile — Full Portfolio Scan

Simulated every ticker: buy at open-1% when dip occurs, sell at +4% or stop -3% or cut at EOD. 3-month daily data.

| Ticker | Price | Range | Dip Days | Rec≥4% | Sim Trades | Win% | Sim P/L | Verdict |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| **OKLO** | $50.23 | 7.7% | 92% | 97% | 57 | 39% | **+$10.00** | STRONG |
| **AR** | $45.15 | 3.5% | 65% | 31% | 40 | 5% | **+$5.87** | UNUSUAL — low range but profitable |
| **IONQ** | $27.51 | 7.5% | 92% | 95% | 57 | 33% | **+$3.29** | MODERATE |
| **CLSK** | $8.66 | 7.5% | 92% | 100% | 57 | 44% | **+$2.52** | MODERATE |
| **NNE** | $20.29 | 7.8% | 94% | 98% | 58 | 40% | **+$2.45** | MODERATE |
| **NU** | $13.60 | 3.4% | 73% | 27% | 45 | 4% | **+$2.22** | UNUSUAL — low range but profitable |
| **RGTI** | $13.32 | 7.1% | 89% | 95% | 55 | 36% | **+$1.51** | MODERATE |
| **CLF** | $8.11 | 5.3% | 74% | 71% | 46 | 22% | **+$0.56** | MARGINAL |
| **ACHR** | $5.09 | 6.0% | 89% | 85% | 55 | 27% | **+$0.44** | MARGINAL |
| BBAI | $3.14 | 6.7% | 84% | 100% | 52 | 33% | -$0.16 | BREAKEVEN |
| RDW | $8.16 | 10.2% | 92% | 100% | 57 | 44% | -$0.58 | BREAKEVEN |
| LUNR | $17.52 | 10.7% | 81% | 100% | 50 | 42% | -$0.61 | BREAKEVEN |
| TMC | $4.27 | 7.7% | 90% | 92% | 56 | 32% | -$0.85 | LOSER |
| RUN | $12.60 | 6.9% | 65% | 92% | 40 | 32% | -$1.82 | LOSER |
| OUST | $17.66 | 7.5% | 82% | 97% | 51 | 31% | -$2.18 | LOSER |
| CIFR | $13.74 | 9.0% | 90% | 97% | 56 | 38% | -$2.38 | LOSER |
| APLD | $23.76 | 7.9% | 84% | 98% | 52 | 33% | -$5.03 | LOSER |
| USAR | $15.42 | 8.9% | 87% | 100% | 54 | 24% | -$10.85 | BAD |
| TEM | $42.62 | 5.2% | 79% | 81% | 49 | 22% | -$11.37 | BAD |
| ARM | $144.13 | 4.5% | 63% | 61% | 39 | 13% | -$12.36 | BAD |
| NVDA | $167.52 | 2.5% | 55% | 16% | 34 | 6% | -$17.47 | BAD |

### Key Finding: Range Does NOT Predict Profitability

**This contradicts the earlier hypothesis.** The data shows:

- Average range of **profitable** tickers: 6.2%
- Average range of **unprofitable** tickers: 7.3%

**Unprofitable tickers have HIGHER range on average.** LUNR (10.7%, $-0.61), RDW (10.2%, $-0.58), CIFR (9.0%, $-2.38), USAR (8.9%, $-10.85) — all high-range, all losing.

Meanwhile AR (3.5%, +$5.87) and NU (3.4%, +$2.22) are LOW range but PROFITABLE. And OKLO (7.7%, +$10.00) is the best performer — not the highest range.

**The range threshold hypothesis from Section 4 was WRONG.** Raising min_daily_range from 3% to 8% would eliminate profitable tickers (OKLO, CLSK, NNE, RGTI) while keeping losers (USAR 8.9%, CIFR 9.0%).

---

## 9. What Actually Separates Winners from Losers?

### 9.1 Ticker-Specific Patterns

Each ticker has its own dip-recovery personality:

**OKLO (+$10.00)**: 7.7% range, 39% win rate — but wins are large because the stock tends to dip deeply (giving better entries) and recover strongly on winning days.

**AR (+$5.87)**: Only 3.5% range, 5% win rate — wins almost never. But when the dip-buy triggers and AR recovers, the EOD cut produces tiny gains consistently. Very few stops hit (AR doesn't crash after dipping — it dips and goes flat).

**LUNR ($-0.61)**: 10.7% range, 42% win rate — high range means BOTH targets and stops get hit easily. The 42% win rate at 4%/3% risk-reward = near breakeven. LUNR is a coin flip, not a sure thing.

**USAR ($-10.85)**: 8.9% range, 24% win rate — dips deeply but does NOT recover same-day. Persistent downtrend.

**NVDA ($-17.47)**: 2.5% range, 6% win rate — simply doesn't move enough intraday for the dip strategy. Dips rarely hit entry, and when they do, recovery is insufficient.

### 9.2 The Real Predictors

Looking at the data, the actual predictors of same-day dip profitability appear to be:

1. **Win rate > 30%**: All profitable tickers have ≥22% simulated win rate, most have ≥33%. Below ~30%, the 4%/3% risk-reward can't overcome the losses.

2. **Price behavior after dip**: Some tickers dip and mean-revert (OKLO, CLSK). Others dip and keep falling (USAR, ARM). This is a BEHAVIORAL trait, not a range metric.

3. **Not a pure range filter**: AR (3.5% range) is profitable because it dips rarely but recovers when it does. USAR (8.9% range) is a disaster because it dips often and never recovers.

### 9.3 Market-Specific Patterns

The 6-month backtest showed monthly variation:
- **Nov 2025**: 100% win rate — bull market, all dips recover
- **Oct, Dec 2025, Mar 2026**: 20-40% win rate — choppy/bearish
- **Feb 2026**: 60% — transitional

**Market regime is a stronger predictor than ticker selection.** In a bull market, EVERY ticker's dip play works. In bearish/choppy markets, only a few with structural mean-reversion properties survive.

---

## 10. Revised Hypothesis

The original hypothesis was: "raise the range threshold to filter out losers."

**New hypothesis**: The dip strategy needs **two layers of filtering**:

**Layer 1: Ticker qualification (static, computed once):**
Not based on range alone. Based on **simulated same-day dip win rate** over a rolling window. If a ticker's 30-day simulated dip win rate is below 30%, exclude it from the dip watchlist entirely.

This is exactly what the `dip_kpis` from the surgical simulation side-channel provides — per-ticker, per-regime dip win rate backed by actual backtest data.

**Layer 2: Market regime (dynamic, checked daily):**
In Risk-Off (VIX > 25), reduce position size or skip entirely. The November 100% win rate vs March 40% proves that market regime matters more than ticker selection.

**Layer 3: Per-ticker parameters (optional optimization):**
Different tickers may benefit from different target/stop ratios:
- OKLO: 4%/3% works (39% win rate × 1.33 ratio > 1.0)
- LUNR: Needs tighter target (3%/3% = needs 50% win rate, currently at 42% — still marginal)
- AR: Needs different entry (rarely dips 1% — lower threshold to 0.5%?)

---

## 11. Verification Findings — What I Got Wrong

### Win Rate Filter is INVALID (Test 1 REJECTED)

The proposal to filter tickers by `dip_win_rate ≥ 30%` was tested against the Section 8 data:

- **62% false positive rate**: 8 of 13 tickers with ≥30% win rate LOSE money (LUNR 42% win -$0.61, RDW 44% win -$0.58, CIFR 38% win -$2.38, etc.)
- **44% false negative rate**: 4 of 9 profitable tickers have <30% win rate (AR 5% win +$5.87, NU 4% win +$2.22)
- **Overall accuracy: 43%** — worse than random

**Win rate does NOT predict P/L.** The reason: EOD cuts. Most "losses" aren't full -3% stops — they're tiny EOD cuts (-0.5% to -1.5%). A ticker can have 5% win rate but still profit because 90% of its trades exit at EOD with tiny losses while 5% hit the +4% target.

### Regime Claim is Confounded

The November 100% win rate came from a 3-ticker/3%-target run. The March 40% came from a 21-ticker/4%-target run. Can't compare across different tickers AND different parameters AND different market conditions. Need per-regime breakdown of the SAME ticker set with SAME parameters.

### LUNR 69% vs 42% is Unverified

The analysis assumes the standalone dip simulator used 3% target. This hasn't been confirmed against the actual simulator config. The `backtest_config.py` default is 4%, not 3%.

---

## 12. Revised Test Plan

### ~~Test 1~~: REJECTED — win rate filter is invalid

### Test 2: Per-Regime Breakdown (prerequisite for regime gating)
Before testing regime gating, first MEASURE per-regime results for the 21-ticker 4%-target scan:
- Split the 3-month daily data by VIX regime
- Compute per-ticker dip P/L in Risk-On vs Neutral vs Risk-Off
- See if the same tickers profit/lose across ALL regimes or only specific ones

### Test 3: Per-Ticker Parameter Sweeps
For the top 5 profitable tickers (OKLO, AR, IONQ, CLSK, NNE), sweep:
- Target: 2%, 3%, 4%, 5%
- Stop: -2%, -3%, -4%
- Dip threshold: 0.5%, 1.0%, 1.5%, 2.0%

Find each ticker's optimal parameters. If they cluster around a common optimum, use that. If they diverge, per-ticker configs are needed.

### Test 4: LUNR at 3% vs 4% Target
Quick A/B:
- A: LUNR with 3% target, 3% stop
- B: LUNR with 4% target, 3% stop

Verify whether the 69% win rate was from 3% target. If so, test ALL tickers at 3% to see if the portfolio improves.

### Test 5: AR Trade Distribution (NEW)
Extract AR's actual trade-by-trade results to understand HOW it profits at 5% win rate:
- How many hit target (+4%)?
- How many hit stop (-3%)?
- How many EOD cuts? Average P/L of EOD cuts?
- Is the profit from rare large wins + many tiny flat exits?

### Test 6: Cross-Regime Stability (NEW)
For USAR (-$10.85, worst performer): was it always a loser or only in the recent Risk-Off period?
- Run USAR's dip simulation on just the November 2025 data (bull market)
- If USAR profits in November, the "behavioral trait" claim is wrong — it's regime-dependent
- If USAR still loses in November, the trait is real

---

## 13. What We'd Learn

1. **Test 2**: Are winners/losers consistent across regimes, or does everything flip in bull markets?
2. **Test 3**: Do tickers cluster around one optimal config, or does each need its own?
3. **Test 4**: Is 3% target universally better than 4%?
4. **Test 5**: What mechanism makes low-win-rate tickers profitable? (EOD cut distribution)
5. **Test 6**: Is USAR a structural loser or just a bear-market loser?

These answers determine whether we need:
- A single tuned config (if tickers cluster)
- Per-ticker configs (if they diverge)
- Regime gating (if winners/losers flip by regime)
- A completely different qualification metric (if win rate is useless)

---

## 14. Test Results (Executed 2026-03-29)

### Test 2 Results: Per-Regime Breakdown

Days by regime: Neutral=44, Risk-Off=11, Risk-On=7

| Regime | Days | Trades | Win% | P/L | Profitable Tickers |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Risk-On | 7 | 115 | 34% | -$1.01 | 13/21 |
| Neutral | 44 | 751 | 30% | -$21.77 | 10/21 |
| Risk-Off | 11 | 194 | 26% | -$14.00 | 8/21 |

**Finding**: Regime effect is REAL but MODEST. Risk-On is only marginally better (34% vs 26%). All regimes lose money overall. Skipping Risk-Off would save -$14 but the strategy still loses -$22.78 in the other regimes.

**Surprise**: Some tickers REVERSE by regime — ARM loses in Risk-On (-$5.09) but profits in Risk-Off (+$3.02). NNE loses in Risk-On (-$3.14) but profits in Risk-Off (+$2.69). This means regime gating would HURT these tickers.

### Test 3 Results: Per-Ticker Optimal Parameters

| Ticker | Current Config | Current P/L | Optimal Config | Optimal P/L | Improvement |
| :--- | :--- | :--- | :--- | :--- | :--- |
| OKLO | 4%/-3%/1.0% dip | +$10.00 | **5%/-3%/1.0%** | **+$19.83** | +$9.83 |
| AR | 4%/-3%/1.0% | +$5.87 | **2%/-4%/2.0%** | **+$13.38** | +$7.51 |
| IONQ | 4%/-3%/1.0% | +$3.29 | **4%/-3%/2.0%** | **+$14.14** | +$10.85 |
| CLSK | 4%/-3%/1.0% | +$2.52 | **3.5%/-3%/2.0%** | **+$5.88** | +$3.36 |
| NNE | 4%/-3%/1.0% | +$2.45 | **3.5%/-4%/1.5%** | **+$9.06** | +$6.61 |

**Finding**: Parameters DIVERGE significantly. No single config works for all.
- OKLO wants HIGH target (5%) — big swinger, benefits from letting winners run
- AR wants LOW target (2%) + TIGHT stop (-4%) + HIGH dip threshold (2%) — profits from EOD cuts, not targets
- IONQ wants DEEPER dip entry (2%) — filtering out shallow dips improves win rate from 33% to 50%
- CLSK/NNE want MODERATE target (3.5%) — middle ground between target hits and EOD cuts

**Total: current +$24.13 → optimal +$62.29. That's +$38.16 improvement (+158%) from per-ticker tuning.**

### Test 4 Results: LUNR Target Sweep

| Target | Trades | Wins | Stops | Cuts | Win% | P/L |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2.0% | 50 | 23 | 27 | 0 | 46% | -$6.87 |
| 3.0% | 50 | 22 | 27 | 1 | 44% | -$3.74 |
| 3.5% | 50 | 22 | 27 | 1 | 44% | -$1.81 |
| 4.0% | 50 | 21 | 27 | 2 | 42% | -$0.61 |
| **5.0%** | **50** | **20** | **27** | **3** | **40%** | **+$2.37** |

**Finding**: LUNR has a FIXED 27 stops regardless of target (the stop at -3% is always hit on the same days). Only the win payoff changes. **5% target is the only profitable config** because $5 per win × 20 wins = $100, vs $3 per stop × 27 stops = $81.

The 69% win rate from the standalone simulator was likely from a different market window or different parameters entirely.

### Test 5 Results: AR Trade Distribution

| Exit Type | Count | Avg P/L | Mechanism |
| :--- | :--- | :--- | :--- |
| TARGET (+4%) | 2 | +$1.35 | Rare large wins |
| STOP (-3%) | 6 | -$1.05 | Infrequent stops |
| EOD_CUT | 32 | **+$0.30** | **The profit engine** |

Of 32 EOD cuts: 23 positive (avg +$0.52), 9 negative (avg -$0.28).

**Finding**: AR profits from a completely different mechanism than other tickers. It dips slightly from open, sits flat or drifts up slightly, and closes near or above the entry price. The +4% target and -3% stop are almost irrelevant — 80% of trades exit at close with a small profit.

**AR needs its own strategy**: 2% target / -4% stop / 2% dip threshold = +$13.38 (vs +$5.87 current). The tight target catches the small-but-reliable close-above-entry pattern.

### Test 6 Results: USAR Cross-Regime

| Regime | Days | Trades | Win% | P/L |
| :--- | :--- | :--- | :--- | :--- |
| Risk-On | 7 | 6 | 50% | +$1.03 |
| Neutral | 44 | 37 | 22% | -$8.96 |
| Risk-Off | 11 | 11 | 18% | -$2.92 |

**Finding**: USAR is REGIME-DEPENDENT, not structural. 50% win rate in Risk-On (+$1.03) vs 22% in Neutral (-$8.96). The "behavioral trait" claim was WRONG for USAR — it's a bull-market dipper that crashes in other regimes.

### Bonus: 3% vs 4% Target (All 21 Tickers)

| Target | Trades | Win% | P/L | Profitable Tickers |
| :--- | :--- | :--- | :--- | :--- |
| 3.0% | 1060 | 39% | **-$52.99** | 9/21 |
| 4.0% | 1060 | 30% | **-$36.80** | 9/21 |

**Finding**: 4% target is BETTER than 3% across all tickers. The 3% "optimization" from the earlier sweep was wrong. Higher target = fewer wins but each win covers more stops.

---

## 15. Conclusions from Tests

1. **No single config works.** Per-ticker parameters yield +$38 improvement over a uniform config.

2. **Three distinct ticker behaviors identified**:
   - **Big swingers** (OKLO, LUNR): Need high targets (5%) to let winners run. Stops are constant regardless.
   - **EOD drifters** (AR, NU): Profit from small positive EOD cuts, not target hits. Need low targets (2%) and tight stops.
   - **Moderate recoverers** (CLSK, NNE, IONQ): Need moderate targets (3.5-4%) and deeper dip entries (1.5-2%).

3. **Regime gating is NOT clearly beneficial.** Some tickers reverse by regime (ARM, NNE profit in Risk-Off but lose in Risk-On). A blanket regime skip would help some tickers and hurt others.

4. **The dip threshold matters more than expected.** Raising from 1.0% to 2.0% dramatically improved IONQ (33%→50% win rate, +$3.29→+$14.14) and CLSK (+$2.52→+$5.88). Deeper dips = stronger bounces.

5. **3% target is worse than 4% globally.** The earlier "optimization" was incorrect or regime-specific.
