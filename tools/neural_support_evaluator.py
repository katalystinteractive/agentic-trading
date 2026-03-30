"""Neural Support Evaluator — daily pre-market support level scanner.

Checks which neural support candidates are near wick-adjusted buy levels.
Uses per-ticker neural profiles (pool, bullets, sell target) instead of
fixed defaults. Emails actionable opportunities.

Usage:
    python3 tools/neural_support_evaluator.py                 # scan + email
    python3 tools/neural_support_evaluator.py --no-email       # scan only, print report
    python3 tools/neural_support_evaluator.py --proximity 5    # 5% proximity threshold
"""
import sys
import json
import re
import argparse
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yfinance as yf

_ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_PATH = _ROOT / "data" / "neural_support_candidates.json"
PORTFOLIO_PATH = _ROOT / "portfolio.json"
EVAL_CACHE_PATH = _ROOT / "data" / "support_eval_latest.json"
DEFAULT_PROXIMITY = 5.0  # % distance from support to trigger alert


def load_candidates():
    """Load neural support candidate profiles."""
    if not CANDIDATES_PATH.exists():
        print("*No neural support candidates. Run neural_support_discoverer.py first.*")
        return []
    with open(CANDIDATES_PATH) as f:
        data = json.load(f)
    return data.get("candidates", [])


def load_portfolio():
    """Load current positions and pending orders."""
    try:
        with open(PORTFOLIO_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def fetch_prices(tickers):
    """Batch fetch current prices via yfinance."""
    if not tickers:
        return {}
    try:
        data = yf.download(tickers, period="1d", interval="1d", progress=False)
        if data.empty:
            return {}
        prices = {}
        if len(tickers) == 1:
            prices[tickers[0]] = float(data["Close"].iloc[-1])
        else:
            for tk in tickers:
                try:
                    col = data["Close"][tk] if tk in data["Close"].columns else None
                    if col is not None and not col.empty:
                        prices[tk] = float(col.iloc[-1])
                except Exception:
                    continue
        return prices
    except Exception:
        return {}


def load_support_levels(ticker):
    """Load wick-adjusted buy levels from cached wick analysis.

    Parses the 'Buy At' column from the wick analysis markdown table.
    Returns list of dicts with 'buy_at', 'raw_support', 'hold_rate'.
    Returns [] if no wick analysis file exists.
    """
    wick_path = _ROOT / "tickers" / ticker / "wick_analysis.md"
    if not wick_path.exists():
        return []

    try:
        content = wick_path.read_text()
    except OSError:
        return []

    levels = []
    # Parse markdown table rows — format has 13 columns:
    # | Support | Source | Approaches | Held | Freq/mo | Hold Rate | Median Offset | Buy At | Zone | Tier | Decayed | Trend | Fresh |
    # Column indices: Support=0, Hold Rate=5, Buy At=7
    header_found = False
    for line in content.split("\n"):
        if not line.startswith("|"):
            continue
        if "Support" in line and "Buy At" in line:
            header_found = True
            continue
        if "---" in line:
            continue
        if not header_found:
            continue
        cols = [c.strip() for c in line.split("|")[1:-1]]
        if len(cols) < 8:
            continue
        try:
            raw_support = float(cols[0].replace("$", "").replace(",", ""))
            hold_rate_str = cols[5].replace("%", "").strip()
            hold_rate = float(hold_rate_str) if hold_rate_str else 0
            buy_at_str = cols[7].replace("$", "").replace(",", "").strip()
            if "N/A" in buy_at_str or not buy_at_str:
                continue  # skip levels with no buy recommendation
            buy_at = float(buy_at_str)
            levels.append({
                "raw_support": raw_support,
                "hold_rate": hold_rate,
                "buy_at": buy_at,
            })
        except (ValueError, IndexError):
            continue

    return levels


def scan_opportunities(candidates, prices, portfolio, proximity_pct):
    """Find tickers near support levels using neural profiles."""
    positions = portfolio.get("positions", {})
    pending = portfolio.get("pending_orders", {})
    opportunities = []

    for c in candidates:
        tk = c["ticker"]
        price = prices.get(tk)
        if not price:
            continue

        params = c.get("params", {})
        pool = params.get("active_pool", 300)
        bullets = params.get("active_bullets_max", 5)
        sell_pct = params.get("sell_default", 6.0)

        # Load support levels
        levels = load_support_levels(tk)
        if not levels:
            continue

        # Check each level
        for level in levels:
            buy_at = level["buy_at"]
            if buy_at <= 0:
                continue

            # Distance: how far price is above the buy level
            distance_pct = (price - buy_at) / buy_at * 100
            if 0 <= distance_pct <= proximity_pct:
                shares = max(1, int(pool / bullets / buy_at))

                # Check if already have a pending order near this level
                tk_orders = pending.get(tk, [])
                already_ordered = any(
                    abs(o.get("price", 0) - buy_at) / buy_at < 0.02
                    for o in tk_orders if o.get("type", "").upper() == "BUY"
                )

                opportunities.append({
                    "ticker": tk,
                    "price": round(price, 2),
                    "support": round(buy_at, 2),
                    "distance_pct": round(distance_pct, 1),
                    "shares": shares,
                    "pool": pool,
                    "sell_target_pct": sell_pct,
                    "hold_rate": level.get("hold_rate", 0),
                    "already_ordered": already_ordered,
                })

    # Sort by distance (closest first)
    opportunities.sort(key=lambda x: x["distance_pct"])
    return opportunities


def main():
    parser = argparse.ArgumentParser(description="Neural Support Evaluator")
    parser.add_argument("--no-email", action="store_true",
                        help="Print report only, don't send email")
    parser.add_argument("--proximity", type=float, default=DEFAULT_PROXIMITY,
                        help=f"Proximity threshold %% (default: {DEFAULT_PROXIMITY})")
    args = parser.parse_args()

    print(f"Neural Support Evaluator — {date.today().isoformat()}")
    print(f"Proximity threshold: {args.proximity}%\n")

    # Load data
    candidates = load_candidates()
    if not candidates:
        return

    portfolio = load_portfolio()
    tickers = [c["ticker"] for c in candidates]

    print(f"Candidates: {len(candidates)}")
    prices = fetch_prices(tickers)
    print(f"Prices fetched: {len(prices)}/{len(tickers)}\n")

    # Scan
    opportunities = scan_opportunities(candidates, prices, portfolio, args.proximity)

    # Report
    actionable = [o for o in opportunities if not o["already_ordered"]]
    already = [o for o in opportunities if o["already_ordered"]]

    if actionable:
        print(f"## Actionable Opportunities ({len(actionable)})\n")
        print(f"| Ticker | Price | Support | Distance | Shares | Pool | Sell% | Hold% |")
        print(f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for o in actionable:
            print(f"| {o['ticker']} | ${o['price']:.2f} | ${o['support']:.2f} | "
                  f"{o['distance_pct']}% | {o['shares']} | ${o['pool']} | "
                  f"{o['sell_target_pct']}% | {o['hold_rate']:.0f}% |")
    else:
        print("No tickers near support levels today.")

    if already:
        print(f"\n## Already Ordered ({len(already)})\n")
        for o in already:
            print(f"  {o['ticker']}: ${o['support']:.2f} (order already placed)")

    # Cache for daily_analyzer
    cache = {
        "date": date.today().isoformat(),
        "proximity_pct": args.proximity,
        "opportunities": opportunities,
    }
    try:
        with open(EVAL_CACHE_PATH, "w") as f:
            json.dump(cache, f, indent=2)
    except OSError:
        pass

    # Email
    if actionable and not args.no_email:
        try:
            from notify import send_support_alert
            send_support_alert(actionable)
        except Exception as e:
            print(f"*Email failed: {e}*")

    print(f"\nScanned {len(candidates)} candidates, "
          f"{len(opportunities)} near support, "
          f"{len(actionable)} actionable")


if __name__ == "__main__":
    main()
