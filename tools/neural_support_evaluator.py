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
import argparse
from pathlib import Path
from datetime import date, datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yfinance as yf
from neural_artifact_validator import ArtifactValidationError, load_validated_json
from shared_utils import compute_position_allocation, compute_support_level_score
from wick_offset_analyzer import analyze_stock_data

_ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_PATH = _ROOT / "data" / "neural_support_candidates.json"
PORTFOLIO_PATH = _ROOT / "portfolio.json"
EVAL_CACHE_PATH = _ROOT / "data" / "support_eval_latest.json"
DEFAULT_PROXIMITY = 5.0  # % distance from support to trigger alert
EVAL_CACHE_SCHEMA_VERSION = 1


def load_candidates():
    """Load neural support candidate profiles."""
    if not CANDIDATES_PATH.exists():
        print("*No neural support candidates. Run neural_support_discoverer.py first.*")
        return []
    try:
        data = load_validated_json(CANDIDATES_PATH)
    except ArtifactValidationError as e:
        print(f"*Warning: {e}. Skipping neural support candidates.*")
        return []
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


def _parse_source_date(value):
    """Parse analyzer last_date into a date, returning None if malformed."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _is_structured_analysis_fresh(data, max_age_days=7):
    """Check that analyzer output is recent enough for live support scanning."""
    source_date = _parse_source_date(data.get("last_date"))
    if source_date is None:
        return False
    age = (date.today() - source_date).days
    return 0 <= age <= max_age_days


def _levels_from_structured_analysis(ticker, data):
    """Extract scanner levels from wick analyzer structured bullet_plan output."""
    plan = data.get("bullet_plan") or {}
    levels = []
    for zone in ("active", "reserve"):
        for item in plan.get(zone, []) or []:
            buy_at = item.get("buy_at")
            if not isinstance(buy_at, (int, float)) or buy_at <= 0:
                continue
            levels.append({
                "ticker": ticker,
                "raw_support": item.get("support_price"),
                "hold_rate": item.get("decayed_hold_rate", item.get("hold_rate", 0)),
                "buy_at": float(buy_at),
                "zone": item.get("zone", zone.title()),
                "tier": item.get("tier"),
                "source": "wick_offset_analyzer.analyze_stock_data",
                "last_date": data.get("last_date"),
                "current_price": data.get("current_price"),
                "monthly_touch_freq": item.get("monthly_touch_freq", 0),
                "dormant": item.get("dormant", False),
                "support_score": item.get("support_score"),
                "support_expected_edge_pct": item.get("support_expected_edge_pct"),
                "support_score_components": item.get("support_score_components", {}),
            })
    return levels


def load_support_levels(ticker, max_age_days=7):
    """Load wick-adjusted buy levels from structured analyzer output.

    Markdown reports are operator-facing only. Live support scanning uses
    wick_offset_analyzer.analyze_stock_data() so levels are schema-bearing,
    recomputed, and freshness checked instead of parsed from cached prose.
    """
    data, error = analyze_stock_data(ticker)
    if data is None:
        print(error or f"*Support analysis unavailable for {ticker}*")
        return []
    if not _is_structured_analysis_fresh(data, max_age_days=max_age_days):
        print(f"*Support analysis stale for {ticker}: last_date={data.get('last_date')}*")
        return []
    return _levels_from_structured_analysis(ticker, data)


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
        stats = c.get("stats", {})
        features = c.get("features") or {}
        pool = params.get("active_pool", 300)
        bullets = params.get("active_bullets_max", 5)
        sell_pct = params.get("sell_default", 6.0)
        score = stats if isinstance(stats, dict) else {}

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
                base_dollars = pool / max(1, bullets)
                allocation = compute_position_allocation(
                    base_dollars,
                    buy_at,
                    features={
                        **features,
                        "hold_rate": level.get("hold_rate", 0),
                        "monthly_touch_freq": level.get("monthly_touch_freq", 0),
                        "distance_pct": distance_pct,
                        "proximity_pct": proximity_pct,
                        "target_pct": sell_pct,
                        "stop_pct": 3.0,
                    },
                    score=score,
                    max_dollars=pool * 0.60,
                )
                shares = allocation["shares"]
                level_score = compute_support_level_score(
                    {
                        **level,
                        "distance_pct": distance_pct,
                        "target_pct": sell_pct,
                        "stop_pct": 3.0,
                    },
                    current_price=price,
                    proximity_pct=proximity_pct,
                    target_pct=sell_pct,
                    stop_pct=3.0,
                    allocated_dollars=allocation["allocated_dollars"],
                    pool_budget=pool,
                )

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
                    "allocated_dollars": allocation["allocated_dollars"],
                    "allocation_multiplier": allocation["allocation_multiplier"],
                    "allocation_action": allocation["allocation_action"],
                    "allocation_reason": allocation["allocation_reason"],
                    **level_score,
                    "pool": pool,
                    "sell_target_pct": sell_pct,
                    "hold_rate": level.get("hold_rate", 0),
                    "zone": level.get("zone"),
                    "tier": level.get("tier"),
                    "support_source": level.get("source"),
                    "support_last_date": level.get("last_date"),
                    "already_ordered": already_ordered,
                })

    opportunities.sort(key=lambda x: (-x.get("support_score", 0), x["distance_pct"]))
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
        print(f"| Ticker | Score | Edge | Price | Support | Distance | Alloc | Shares | Pool | Sell% | Hold% |")
        print(f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for o in actionable:
            print(f"| {o['ticker']} | {o.get('support_score', 0):.1f} | "
                  f"{o.get('support_expected_edge_pct', 0):+.1f}% | "
                  f"${o['price']:.2f} | ${o['support']:.2f} | "
                  f"{o['distance_pct']}% | {o.get('allocation_action', 'baseline')} "
                  f"{o.get('allocation_multiplier', 1.0):.2f}x | {o['shares']} | ${o['pool']} | "
                  f"{o['sell_target_pct']}% | {o['hold_rate']:.0f}% |")
    else:
        print("No tickers near support levels today.")

    if already:
        print(f"\n## Already Ordered ({len(already)})\n")
        for o in already:
            print(f"  {o['ticker']}: ${o['support']:.2f} (order already placed)")

    # Cache for daily_analyzer
    cache = {
        "schema_version": EVAL_CACHE_SCHEMA_VERSION,
        "date": date.today().isoformat(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "neural_support_evaluator.py",
        "support_source": "wick_offset_analyzer.analyze_stock_data",
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
            from expected_edge import score_graph_candidate
            from prediction_ledger import artifact_versions, record_prediction

            versions = artifact_versions({
                "neural_support_candidates": CANDIDATES_PATH,
                "support_sweep_results": _ROOT / "data" / "support_sweep_results.json",
                "probability_calibration": _ROOT / "data" / "probability_calibration.json",
            })
            for o in actionable:
                p_target = max(0.0, min(1.0, o.get("hold_rate", 0) / 100.0))
                score = score_graph_candidate(
                    "support",
                    params={"sell_default": o.get("sell_target_pct", 0), "cat_hard_stop": 3.0},
                    stats={"composite": p_target * 100},
                    features={
                        "target_hit_rate": p_target,
                        "stop_hit_rate": max(0.0, 1.0 - p_target),
                        "trade_count": 1,
                    },
                )
                record_prediction(
                    "support",
                    o["ticker"],
                    {
                        "date": date.today().isoformat(),
                        "price": o["price"],
                        "support": o["support"],
                        "shares": o["shares"],
                        "allocated_dollars": o.get("allocated_dollars"),
                        "allocation_multiplier": o.get("allocation_multiplier"),
                        "allocation_action": o.get("allocation_action"),
                        "support_score": o.get("support_score"),
                        "support_expected_edge_pct": o.get("support_expected_edge_pct"),
                        "pool": o["pool"],
                        "sell_target_pct": o["sell_target_pct"],
                        "distance_pct": o["distance_pct"],
                        "hold_rate": o["hold_rate"],
                        "zone": o.get("zone"),
                        "tier": o.get("tier"),
                    },
                    features={
                        "proximity_pct": args.proximity,
                        "support_source": o.get("support_source"),
                        "support_last_date": o.get("support_last_date"),
                        "allocation_reason": o.get("allocation_reason"),
                        "support_score_components": o.get("support_score_components", {}),
                    },
                    score=score,
                    artifact_versions=versions,
                    reason=o.get("support_source", ""),
                )
        except Exception as e:
            print(f"*Warning: prediction ledger write failed: {e}*")

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
