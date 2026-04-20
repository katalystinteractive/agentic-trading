"""Multi-Period Composite Scorer — 4-period simulation-based ticker ranking.

Runs simulations at 12mo, 6mo, 3mo, 1mo windows. Combines into a single
composite $/month score. Allocates capital proportionally — no arbitrary
tiers or thresholds.

Composite = 20% × 12mo_rate + 30% × 6mo_rate + 30% × 3mo_rate + 20% × 1mo_rate
1-month: regime-adjusted (stalled tickers during Risk-Off use 3mo rate)

Capital allocation: each ticker gets pool = total_budget × (composite / sum_composites)
Higher composite = bigger pool. Sum always equals total budget.

Usage:
    python3 tools/multi_period_scorer.py                            # all watchlist
    python3 tools/multi_period_scorer.py --tickers LUNR CIFR CLSK   # specific
    python3 tools/multi_period_scorer.py --budget 18000             # custom total
"""
import sys
import json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = _ROOT / "data" / "backtest" / "multi-period"

# Periods to simulate (months)
PERIODS = [12, 6, 3, 1]

# Significance threshold: minimum cycles for a period to be statistically meaningful
SIGNIFICANCE_THRESHOLD = 5

# Recency weights: shorter periods weighted higher so the composite favors tickers
# whose patterns are active in the current regime, not relics of 12-month-old behavior.
# Linear 1:2:3:4 for 12:6:3:1mo gives 1mo 4× the influence of 12mo.
# Without this, the tournament ranked tickers on 12-month averages even when the
# recent pattern had decayed — leading to placements at stale levels that never hit.
RECENCY_WEIGHTS = {12: 1, 6: 2, 3: 3, 1: 4}


def _get_period_risk_off_pct(months):
    """Compute % of Risk-Off days in the last N months.
    Uses VIX > 25 AND majority of SPY/QQQ/IWM below 50-SMA.
    Returns 0-100 float.
    """
    import yfinance as yf
    import warnings
    warnings.filterwarnings("ignore")
    from datetime import datetime, timedelta
    import numpy as np

    end = datetime.now()
    start = end - timedelta(days=months * 30 + 10)  # buffer

    try:
        tickers_to_dl = ["^VIX", "SPY", "QQQ", "IWM"]
        data = yf.download(tickers_to_dl, start=start.strftime("%Y-%m-%d"),
                          progress=False)
        if data.empty:
            return 0

        close = data["Close"]
        vix = close["^VIX"].dropna()

        # Count Risk-Off days in the last N months
        cutoff = end - timedelta(days=months * 30)
        risk_off = 0
        total = 0

        for dt in vix.index:
            if dt.to_pydatetime().replace(tzinfo=None) < cutoff:
                continue
            v = float(vix.loc[dt])
            if v <= 25:
                total += 1
                continue

            # VIX > 25 — check indices
            below_count = 0
            for idx in ["SPY", "QQQ", "IWM"]:
                if idx not in close.columns:
                    continue
                idx_close = close[idx].dropna()
                sma50 = idx_close.rolling(50).mean()
                if dt in idx_close.index and dt in sma50.index:
                    c = float(idx_close.loc[dt])
                    s = float(sma50.loc[dt])
                    if not np.isnan(s) and c < s:
                        below_count += 1

            total += 1
            if below_count >= 2:  # majority below
                risk_off += 1

        return round(risk_off / total * 100, 1) if total > 0 else 0
    except Exception:
        return 0


def _load_watchlist():
    with open(_ROOT / "portfolio.json") as f:
        data = json.load(f)
    return sorted(data.get("watchlist", []))


def _simulate_ticker(ticker, months):
    """Run simulation for a single ticker at a given period. Returns metrics."""
    from candidate_sim_gate import simulate_candidate
    try:
        result = simulate_candidate(ticker, months=months)
        return result
    except Exception as e:
        return {"ticker": ticker, "pnl": 0, "win_rate": 0, "sharpe": 0,
                "cycles": 0, "buys": 0, "sells": 0, "sde_rate": 0,
                "avg_hold": 0, "catastrophic": 0, "error": str(e)}


def compute_composite(results_by_period):
    """Compute composite $/month score from multi-period results.

    Weights are determined by CYCLE COUNT (statistical significance), not fixed
    percentages. A period with 30 cycles gets more weight than one with 2 cycles.
    This is data-driven: more data = more confidence = more weight.

    Formula:
        weight_i = min(cycles_i, SIGNIFICANCE_THRESHOLD) / SIGNIFICANCE_THRESHOLD
        composite = sum(weight_i * rate_i) / sum(weight_i)

    Special handling:
        - 1-month with zero cycles during Risk-Off: excluded (weight=0), not penalized
        - 1-month with cycles during Risk-Off: BONUS weight (resilience signal)
        - Minimum 1 period must have weight > 0

    Args:
        results_by_period: {12: result, 6: result, 3: result, 1: result}

    Returns:
        composite_score ($/month), details dict
    """
    import numpy as np

    # Step 1: compute monthly rate and cycle count per period
    period_data = {}
    for months, result in results_by_period.items():
        pnl = result.get("pnl", 0)
        cycles = result.get("cycles", 0)
        rate = pnl / months if months > 0 else pnl  # $/month
        period_data[months] = {"rate": rate, "cycles": cycles}

    # Step 2: compute significance-based weight per period
    # weight = min(cycles, threshold) / threshold → 0.0 to 1.0
    weights = {}
    for months, pd in period_data.items():
        sig = min(pd["cycles"], SIGNIFICANCE_THRESHOLD) / SIGNIFICANCE_THRESHOLD
        weights[months] = sig

    # Step 3: regime-aware weight adjustment for 1-month period
    # Query actual market regime for the 1-month window to determine
    # whether zero cycles is expected (Risk-Off) or a failure (Risk-On/Neutral)
    cycles_1mo = period_data.get(1, {}).get("cycles", 0)
    regime_adjusted = False
    risk_off_pct = _get_period_risk_off_pct(1)  # % of days that were Risk-Off

    if cycles_1mo == 0:
        if risk_off_pct >= 30:
            # Risk-Off dominant — zero cycles is expected, don't penalize
            weights[1] = 0
            regime_adjusted = True
        else:
            # Market was favorable but ticker didn't cycle — penalize
            # Keep the significance weight (which is 0 for 0 cycles),
            # but set a small negative penalty weight to drag composite
            weights[1] = 0  # still 0 from significance, but NOT regime-adjusted
    elif cycles_1mo >= 3 and risk_off_pct >= 30:
        # Cycled 3+ times during Risk-Off — resilience bonus
        # Bonus scales with both cycle count and Risk-Off severity
        sig = min(cycles_1mo, SIGNIFICANCE_THRESHOLD) / SIGNIFICANCE_THRESHOLD
        resilience = 1.0 + (risk_off_pct / 100) * sig
        weights[1] = min(resilience, 2.0)  # cap at 2x
    elif cycles_1mo >= 3:
        # Cycled 3+ times during normal market — full weight
        weights[1] = 1.0

    # Step 3.5: apply recency multiplier. Shorter periods get more influence so
    # the composite reflects current-regime behavior, not 12-month averages.
    # Multiplies AFTER significance + regime adjustments so both signals persist.
    for months in weights:
        weights[months] *= RECENCY_WEIGHTS.get(months, 1)

    # Step 4: compute weighted composite
    total_weight = sum(weights.values())
    if total_weight == 0:
        total_weight = 1  # safety: at least 1 period

    composite = sum(
        weights[m] * period_data[m]["rate"]
        for m in period_data
    ) / total_weight

    # Step 5: build details
    details = {}
    for months in sorted(period_data.keys()):
        pd = period_data[months]
        details[f"r{months}"] = round(pd["rate"], 1)
        details[f"w{months}"] = round(weights[months], 2)
        details[f"c{months}"] = pd["cycles"]

    details["regime_adjusted"] = regime_adjusted
    details["risk_off_pct_1mo"] = risk_off_pct
    details["total_weight"] = round(total_weight, 2)

    return round(composite, 1), details


def allocate_capital(composites, total_budget):
    """Proportional capital allocation based on composite scores.

    Each ticker gets: pool = total_budget × (score / sum_scores)
    Minimum pool: $100 (floor to prevent zero allocation)
    """
    total_score = sum(max(s, 0.1) for s in composites.values())  # floor at 0.1
    allocations = {}
    for tk, score in composites.items():
        weight = max(score, 0.1) / total_score
        total_pool = max(100, round(total_budget * weight))
        active = total_pool // 2
        reserve = total_pool - active
        allocations[tk] = {
            "total_pool": total_pool,
            "active_pool": active,
            "reserve_pool": reserve,
            "weight": round(weight * 100, 1),
        }
    return allocations


def main():
    import argparse
    p = argparse.ArgumentParser(description="Multi-Period Composite Scorer")
    p.add_argument("--tickers", nargs="*", type=str.upper)
    p.add_argument("--budget", type=float, default=None,
                   help="Total budget (default: n_tickers × $600)")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    tickers = args.tickers or _load_watchlist()
    if not tickers:
        print("*No tickers*")
        sys.exit(1)

    total_budget = args.budget or len(tickers) * 600

    print(f"## Multi-Period Composite Scorer\n")
    print(f"*{len(tickers)} tickers | Periods: 12mo, 6mo, 3mo, 1mo*")
    print(f"*Weights: per-ticker, based on cycle count (significance threshold: {SIGNIFICANCE_THRESHOLD} cycles)*")
    print(f"*Total budget: ${total_budget:,.0f} | Proportional allocation*\n")

    # Run simulations for all periods
    all_results = {}  # {ticker: {period: result}}
    for months in PERIODS:
        print(f"### Simulating {months}-month window...")
        for i, tk in enumerate(tickers, 1):
            print(f"  [{i}/{len(tickers)}] {tk}...", end=" ", flush=True)
            result = _simulate_ticker(tk, months)
            all_results.setdefault(tk, {})[months] = result
            pnl = result.get("pnl", 0)
            cycles = result.get("cycles", 0)
            print(f"${pnl:.0f} ({cycles} cycles)")
        print()

    # Compute composites
    composites = {}
    details = {}
    for tk in tickers:
        comp, det = compute_composite(all_results[tk])
        composites[tk] = comp
        details[tk] = det

    # Allocate capital
    alloc = allocate_capital(composites, total_budget)

    # Compute composite dip KPIs per ticker (weighted across periods)
    for tk in tickers:
        dip_composite = None
        weighted_win = 0
        weighted_pnl = 0
        total_w = 0
        for months in PERIODS:
            result = all_results.get(tk, {}).get(months, {})
            dk = result.get("dip_kpis")
            if dk and dk.get("dip_trades", 0) > 0:
                w = details.get(tk, {}).get(f"w{months}", 0)
                if w > 0:
                    weighted_win += dk["dip_win_rate_pct"] * w
                    weighted_pnl += dk["dip_pnl"] * w
                    total_w += w
        if total_w > 0:
            # Use 12-month regime breakdown as the most representative
            regime_data_12 = all_results.get(tk, {}).get(12, {}).get("dip_kpis", {})
            dip_composite = {
                "dip_win_rate": round(weighted_win / total_w, 1),
                "dip_pnl_weighted": round(weighted_pnl / total_w, 2),
                "by_regime": regime_data_12.get("by_regime", {}) if regime_data_12 else {},
            }
        if tk in alloc:
            alloc[tk]["dip_kpis"] = dip_composite

    # Sort by composite
    ranked = sorted(composites.items(), key=lambda x: x[1], reverse=True)

    # Output
    print("## Composite Rankings & Capital Allocation\n")
    print("*Weights are per-ticker based on cycle count (statistical significance)*")
    print(f"*Significance threshold: {SIGNIFICANCE_THRESHOLD} cycles = full weight*\n")
    print("| # | Ticker | 12mo (w) | 6mo (w) | 3mo (w) | 1mo (w) | Composite | Pool | Active | Reserve |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for i, (tk, comp) in enumerate(ranked, 1):
        d = details[tk]
        a = alloc[tk]
        adj = "*" if d.get("regime_adjusted") else ""
        r12 = f"${d.get('r12',0)} ({d.get('w12',0):.0%})"
        r6 = f"${d.get('r6',0)} ({d.get('w6',0):.0%})"
        r3 = f"${d.get('r3',0)} ({d.get('w3',0):.0%})"
        r1 = f"${d.get('r1',0)}{adj} ({d.get('w1',0):.0%})"
        print(f"| {i} | **{tk}** | {r12} | {r6} | {r3} | {r1} | **${comp}** | "
              f"${a['total_pool']} | ${a['active_pool']} | ${a['reserve_pool']} |")

    print(f"\n*Total allocated: ${sum(a['total_pool'] for a in alloc.values()):,}*")

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output = {
        "generated": datetime.now().isoformat(),
        "tickers": tickers,
        "total_budget": total_budget,
        "weights": {"12mo": W_12MO, "6mo": W_6MO, "3mo": W_3MO, "1mo": W_1MO},
        "composites": composites,
        "details": details,
        "allocations": alloc,
        "rankings": [tk for tk, _ in ranked],
        "simulations": {
            tk: {str(m): {k: v for k, v in r.items() if k != "error"}
                 for m, r in periods.items()}
            for tk, periods in all_results.items()
        },
    }
    out_path = RESULTS_DIR / "multi-period-results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
