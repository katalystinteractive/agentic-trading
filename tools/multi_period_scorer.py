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

# Composite weights
W_12MO = 0.20
W_6MO = 0.30
W_3MO = 0.30
W_1MO = 0.20

# Periods to simulate (months)
PERIODS = [12, 6, 3, 1]


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

    Args:
        results_by_period: {12: result, 6: result, 3: result, 1: result}

    Returns:
        composite_score ($/month), details dict
    """
    rates = {}
    for months, result in results_by_period.items():
        pnl = result.get("pnl", 0)
        rates[months] = pnl / months if months > 0 else pnl

    # Regime adjustment: if 1mo has zero cycles, use 3mo monthly rate
    r1 = rates.get(1, 0)
    r3 = rates.get(3, 0)
    cycles_1mo = results_by_period.get(1, {}).get("cycles", 0)
    regime_adjusted = False
    if r1 == 0 and cycles_1mo == 0 and r3 > 0:
        r1 = r3 / 3
        regime_adjusted = True

    composite = (
        W_12MO * rates.get(12, 0) / 10 * 10 +   # normalize: 12mo P/L / 10 = monthly rate
        W_6MO * rates.get(6, 0) +
        W_3MO * rates.get(3, 0) +
        W_1MO * r1
    )

    # Correct: rates are already $/month for 6mo, 3mo, 1mo
    # But 12mo P/L is total, so rate = P/L / 10
    r12 = rates.get(12, 0)
    r6 = rates.get(6, 0)

    composite = W_12MO * r12 + W_6MO * r6 + W_3MO * (r3 / 3) + W_1MO * r1

    return round(composite, 1), {
        "r12": round(r12, 1),
        "r6": round(r6, 1),
        "r3": round(r3 / 3, 1),
        "r1": round(r1, 1),
        "regime_adjusted": regime_adjusted,
        "cycles_1mo": cycles_1mo,
    }


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
    print(f"*Weights: 12mo={W_12MO:.0%}, 6mo={W_6MO:.0%}, 3mo={W_3MO:.0%}, 1mo={W_1MO:.0%}*")
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

    # Sort by composite
    ranked = sorted(composites.items(), key=lambda x: x[1], reverse=True)

    # Output
    print("## Composite Rankings & Capital Allocation\n")
    print("| # | Ticker | 12mo$/mo | 6mo$/mo | 3mo$/mo | 1mo$/mo | Composite | Pool | Active | Reserve |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for i, (tk, comp) in enumerate(ranked, 1):
        d = details[tk]
        a = alloc[tk]
        adj = " (adj)" if d["regime_adjusted"] else ""
        print(f"| {i} | **{tk}** | ${d['r12']} | ${d['r6']} | ${d['r3']} | "
              f"${d['r1']}{adj} | **${comp}** | ${a['total_pool']} | "
              f"${a['active_pool']} | ${a['reserve_pool']} |")

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
