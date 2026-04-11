"""Portfolio stress test — sector-correlated shock scenarios on current portfolio.

Simulates what happens when an entire sector drops X% simultaneously.
Reports which pending orders would fill, capital needed, and surplus/deficit.

Includes 4-period historical validation: finds actual correlated drawdown events
in 12/6/3/1 month lookback windows using individual ticker prices.

Usage:
    python3 tools/portfolio_stress_test.py                     # default 15% shock
    python3 tools/portfolio_stress_test.py --shock-pct 20       # custom shock
    python3 tools/portfolio_stress_test.py --workers 8 --json   # parallel + JSON output
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).resolve().parent))

import warnings
warnings.filterwarnings("ignore")
import yfinance as yf

from sector_registry import get_sector
from shared_utils import get_ticker_pool

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"
OUTPUT_PATH = _ROOT / "data" / "portfolio_stress_results.json"

PERIODS = [12, 6, 3, 1]  # months for historical validation
SIGNIFICANCE_THRESHOLD = 5  # from multi_period_scorer convention


def load_portfolio():
    with open(PORTFOLIO_PATH) as f:
        return json.load(f)


def group_by_sector(portfolio):
    """Group active tickers by fine sector. Returns {sector: [ticker_info]}."""
    positions = portfolio.get("positions", {})
    watchlist = set(portfolio.get("watchlist", []))
    pending = portfolio.get("pending_orders", {})
    tracked = set(positions.keys()) | watchlist

    sectors = {}
    for tk in sorted(tracked):
        pos = positions.get(tk, {})
        if pos.get("winding_down"):
            continue

        sec = get_sector(tk)
        if not sec or sec == "Unknown":
            continue

        # Collect pending BUYs
        tk_buys = [
            o for o in pending.get(tk, [])
            if o.get("type") == "BUY" and o.get("placed") and not o.get("filled")
        ]
        pool = get_ticker_pool(tk)
        deployed = pos.get("shares", 0) * pos.get("avg_cost", 0)
        pool_remaining = pool.get("active_pool", 300) - deployed

        sectors.setdefault(sec, []).append({
            "ticker": tk,
            "shares": pos.get("shares", 0),
            "avg_cost": pos.get("avg_cost", 0),
            "deployed": round(deployed, 2),
            "pool_remaining": round(max(pool_remaining, 0), 2),
            "pending_buys": tk_buys,
        })

    return sectors


def simulate_shock(sector, tickers_info, shock_pct, current_prices):
    """Simulate a sector shock and count fills + capital needed."""
    fills = []
    total_needed = 0
    total_available = 0

    for ti in tickers_info:
        tk = ti["ticker"]
        price = current_prices.get(tk)
        if price is None:
            continue

        shocked_price = price * (1 - shock_pct / 100)
        total_available += ti["pool_remaining"]

        for order in ti["pending_buys"]:
            if shocked_price <= order["price"]:
                cost = order["price"] * order.get("shares", 0)
                fills.append({
                    "ticker": tk,
                    "order_price": order["price"],
                    "shares": order.get("shares", 0),
                    "cost": round(cost, 2),
                })
                total_needed += cost

    deficit = max(total_needed - total_available, 0)
    return {
        "sector": sector,
        "shock_pct": shock_pct,
        "tickers": len(tickers_info),
        "pending_buys": sum(len(ti["pending_buys"]) for ti in tickers_info),
        "fills_triggered": len(fills),
        "capital_needed": round(total_needed, 2),
        "available": round(total_available, 2),
        "deficit": round(deficit, 2),
        "fills": fills,
    }


def historical_validation_sector(sector, tickers_info, months, shock_pct):
    """Find actual correlated drawdown events for a sector in a given period.

    Uses individual ticker prices (not sector ETFs) because fine sectors
    like Crypto/Quantum/Nuclear have no ETF proxy.
    """
    tickers = [ti["ticker"] for ti in tickers_info]
    if len(tickers) < 2:
        return {"months": months, "events": 0, "note": "< 2 tickers"}

    try:
        data = yf.download(tickers, period=f"{months}mo", progress=False, threads=True)
        if data.empty:
            return {"months": months, "events": 0, "note": "no data"}

        close = data["Close"] if len(tickers) > 1 else data[["Close"]].rename(
            columns={"Close": tickers[0]})
        if hasattr(close.columns, "levels"):
            pass  # multi-ticker already has ticker columns

        # Compute rolling 20-day high and drawdown per ticker
        rolling_high = close.rolling(20, min_periods=1).max()
        drawdown = (close - rolling_high) / rolling_high * 100

        # A correlated event = day where AVERAGE sector drawdown exceeds threshold
        threshold = -shock_pct / 2  # half the shock for "stress event"
        avg_dd = drawdown.mean(axis=1)
        stress_days = avg_dd[avg_dd <= threshold]

        return {
            "months": months,
            "events": len(stress_days),
            "worst_dd": round(float(avg_dd.min()), 1) if len(avg_dd) > 0 else 0,
            "threshold": threshold,
        }
    except Exception as e:
        return {"months": months, "events": 0, "note": str(e)}


def run_historical_validation(sectors, shock_pct, workers=4):
    """Run historical validation across all sectors × periods using parallel workers."""
    tasks = []
    for sec, tickers_info in sectors.items():
        if len(tickers_info) < 2:
            continue
        for months in PERIODS:
            tasks.append((sec, tickers_info, months, shock_pct))

    results = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(historical_validation_sector, *t): (t[0], t[2])
            for t in tasks
        }
        for future in as_completed(futures):
            sec, months = futures[future]
            try:
                result = future.result()
                results.setdefault(sec, {})[months] = result
            except Exception:
                results.setdefault(sec, {})[months] = {"months": months, "events": 0}

    return results


def fetch_current_prices(tickers):
    """Batch fetch current prices."""
    if not tickers:
        return {}
    try:
        data = yf.download(tickers, period="1d", progress=False, threads=True)
        if data.empty:
            return {}
        prices = {}
        for tk in tickers:
            try:
                if len(tickers) == 1:
                    prices[tk] = float(data["Close"].iloc[-1])
                else:
                    prices[tk] = float(data["Close"][tk].iloc[-1])
            except (KeyError, IndexError):
                continue
        return prices
    except Exception:
        return {}


def print_report(scenarios, historical, shock_pct):
    """Print markdown stress test report."""
    print(f"## Portfolio Stress Test — {datetime.now().strftime('%Y-%m-%d')}\n")
    print(f"**Shock scenario:** {shock_pct}% sector drop\n")

    # Sector concentration
    print("### Sector Concentration\n")
    print("| Sector | Tickers | Pending BUYs | Capital Needed | Available | Status |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- |")
    for s in sorted(scenarios, key=lambda x: -x["deficit"]):
        if s["tickers"] < 2:
            continue
        status = f"⚠️ -${s['deficit']:,.0f}" if s["deficit"] > 0 else "✅"
        print(f"| {s['sector']} | {s['tickers']} | {s['pending_buys']} | "
              f"${s['capital_needed']:,.0f} | ${s['available']:,.0f} | {status} |")

    # Deficits
    deficits = [s for s in scenarios if s["deficit"] > 0]
    if deficits:
        print("\n### Deficit Details\n")
        for d in deficits:
            print(f"**{d['sector']}** — {d['fills_triggered']} of {d['pending_buys']} "
                  f"orders fill, need ${d['capital_needed']:,.0f} but only "
                  f"${d['available']:,.0f} available")
            for f in d["fills"]:
                print(f"  - {f['ticker']} BUY {f['shares']} @ ${f['order_price']:.2f} "
                      f"(${f['cost']:.2f})")

    # Historical validation
    if historical:
        print("\n### Historical Validation\n")
        print("| Sector | Period | Stress Events | Worst Drawdown |")
        print("| :--- | :--- | :--- | :--- |")
        for sec in sorted(historical.keys()):
            for months in PERIODS:
                h = historical[sec].get(months, {})
                events = h.get("events", 0)
                worst = h.get("worst_dd", "N/A")
                worst_str = f"{worst}%" if isinstance(worst, (int, float)) else worst
                print(f"| {sec} | {months}mo | {events} | {worst_str} |")

    total_deficit = sum(s["deficit"] for s in scenarios)
    if total_deficit > 0:
        print(f"\n**Total portfolio deficit in {shock_pct}% scenario: "
              f"${total_deficit:,.0f}**")
    else:
        print(f"\n**All sectors adequately funded for {shock_pct}% shock ✅**")


def main():
    parser = argparse.ArgumentParser(description="Portfolio Stress Test")
    parser.add_argument("--shock-pct", type=float, default=15.0,
                        help="Sector shock percentage (default: 15)")
    parser.add_argument("--workers", type=int, default=4,
                        help="Parallel workers for historical validation (default: 4)")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Output JSON instead of markdown")
    parser.add_argument("--no-historical", action="store_true",
                        help="Skip historical validation (faster)")
    args = parser.parse_args()

    portfolio = load_portfolio()
    sectors = group_by_sector(portfolio)

    # Fetch current prices for all tracked tickers
    all_tickers = [ti["ticker"] for tis in sectors.values() for ti in tis]
    prices = fetch_current_prices(all_tickers)

    # Run shock scenarios per sector
    scenarios = []
    for sec, tickers_info in sorted(sectors.items()):
        if len(tickers_info) < 2:
            continue
        result = simulate_shock(sec, tickers_info, args.shock_pct, prices)
        scenarios.append(result)

    # Historical validation
    historical = {}
    if not args.no_historical:
        historical = run_historical_validation(sectors, args.shock_pct, args.workers)

    # Write results (own file — no contamination)
    output = {
        "_meta": {
            "source": "portfolio_stress_test.py",
            "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "shock_pct": args.shock_pct,
            "sectors_tested": len(scenarios),
        },
        "scenarios": scenarios,
        "historical": {sec: {str(m): v for m, v in periods.items()}
                       for sec, periods in historical.items()},
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    if args.json_output:
        print(json.dumps(output, indent=2))
    else:
        print_report(scenarios, historical, args.shock_pct)


if __name__ == "__main__":
    main()
