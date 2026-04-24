"""Neural Order Adjuster — compute sell and buy order adjustments with reason chains.

Compares ALL pending orders against neural-optimized parameters using the SAME
computation functions as the daily analyzer (compute_recommended_sell,
load_capital_config). Reason chains trace the priority path + per-period evidence.

Usage:
    python3 tools/neural_order_adjuster.py              # full report
    python3 tools/neural_order_adjuster.py --sells-only
    python3 tools/neural_order_adjuster.py --buys-only
"""
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from broker_reconciliation import (compute_recommended_sell, _load_profiles,
                                    _load_resistance_profiles, _load_bounce_profiles)
from neural_artifact_validator import ArtifactValidationError, load_validated_json
from shared_utils import compute_position_allocation, get_ticker_pool
from wick_offset_analyzer import load_capital_config

_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_portfolio():
    with open(_ROOT / "portfolio.json") as f:
        return json.load(f)


def _load_neural_candidates():
    """Load neural support candidates for reason chain evidence."""
    try:
        data = load_validated_json(_ROOT / "data" / "neural_support_candidates.json")
        return {c["ticker"]: c for c in data.get("candidates", [])}
    except (FileNotFoundError, json.JSONDecodeError, ArtifactValidationError):
        return {}


# ---------------------------------------------------------------------------
# Reason chain builders
# ---------------------------------------------------------------------------

def _build_sell_reason(ticker, source, rec_price, avg_cost, ns_candidates):
    """Full reason chain: priority path + per-period evidence + vs-default."""
    parts = [f"Source: {source}"]

    # Per-period evidence when neural
    candidate = ns_candidates.get(ticker)
    if candidate and "neural" in str(source):
        periods = candidate.get("periods")
        if periods:
            period_parts = []
            for months in [12, 6, 3, 1]:
                p = periods.get(str(months)) or periods.get(months, {})
                if p and p.get("pnl"):
                    period_parts.append(
                        f"{months}mo: ${p['pnl']:.0f}/{p.get('cycles', 0)}cyc/"
                        f"{p.get('win_rate', 0):.0f}%WR")
            if period_parts:
                parts.append(" | ".join(period_parts))
        composite = candidate.get("composite")
        if composite:
            parts.append(f"Composite: ${composite:.1f}/mo")

    # vs-default comparison
    if avg_cost > 0:
        default_sell = round(avg_cost * 1.06, 2)
        if abs(rec_price - default_sell) > 0.05:
            diff = rec_price - default_sell
            parts.append(f"vs 6%: ${default_sell:.2f} ({'+' if diff > 0 else ''}${diff:.2f})")

    return " | ".join(parts)


def _build_buy_reason(ticker, pool, bullets, rec_shares, current_shares,
                      buy_price, pool_source, ns_candidates, allocation=None):
    """Full reason chain: pool source + sizing math + evidence + vs-default."""
    parts = []

    # Pool source + sizing math
    per_bullet = round(pool / bullets, 0) if bullets > 0 else pool
    parts.append(f"${pool}/{bullets}b=${per_bullet:.0f}/bullet ({pool_source})")
    parts.append(f"${per_bullet:.0f}/${buy_price:.2f}={rec_shares}sh")
    if allocation:
        parts.append(
            f"alloc {allocation.get('allocation_action', 'baseline')} "
            f"{allocation.get('allocation_multiplier', 1.0):.2f}x: "
            f"{allocation.get('allocation_reason', '')}"
        )

    # Neural evidence
    candidate = ns_candidates.get(ticker)
    if candidate:
        composite = candidate.get("composite")
        if composite:
            parts.append(f"Composite: ${composite:.1f}/mo")
        else:
            pnl = candidate.get("pnl", 0)
            wr = candidate.get("win_rate", 0)
            if pnl:
                parts.append(f"P/L: ${pnl:.0f} ({wr:.0f}%WR)")

    # vs-default comparison
    default_shares = max(1, int(300 / 5 / buy_price))
    if rec_shares != default_shares:
        parts.append(f"vs $300/5b={default_shares}sh")

    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Adjustment computation
# ---------------------------------------------------------------------------

def compute_sell_adjustments(portfolio, ns_candidates):
    """Compare ALL pending SELL orders against recommended sell targets."""
    positions = portfolio.get("positions", {})
    pending = portfolio.get("pending_orders", {})
    profiles = _load_profiles()
    _res_profiles = _load_resistance_profiles()
    _bounce_profiles = _load_bounce_profiles()
    adjustments = []

    for tk in sorted(pending.keys()):
        orders = pending[tk]
        # Only active limit orders: placed=True AND not filled
        sell_orders = [o for o in orders
                       if o.get("type", "").upper() == "SELL"
                       and o.get("placed") is True
                       and not o.get("filled")]
        if not sell_orders:
            continue

        pos = positions.get(tk, {})
        avg = pos.get("avg_cost", 0)
        if avg <= 0:
            continue

        # Fetch hist for resistance/bounce sell targets
        _hist = None
        if (_res_profiles.get(tk, {}).get("vs_flat", {}).get("winner") == "resistance" or
                _bounce_profiles.get(tk, {}).get("vs_others", {}).get("winner") == "bounce"):
            try:
                import yfinance as yf
                import warnings
                warnings.filterwarnings("ignore")
                _hdf = yf.download(tk, period="13mo", progress=False)
                if not _hdf.empty:
                    _hist = _hdf
            except Exception:
                pass

        rec_sell, source = compute_recommended_sell(tk, avg, pos, profiles, hist=_hist)

        for o in sell_orders:
            current_price = o.get("price", 0)
            current_shares = o.get("shares", 0)
            current_pct = round((current_price - avg) / avg * 100, 1)
            rec_pct = round((rec_sell - avg) / avg * 100, 1) if rec_sell > 0 else 0
            diff = round(rec_sell - current_price, 2)

            if abs(diff) < 0.05:
                action = "OK"
            elif diff > 0:
                action = f"RAISE +${diff:.2f}"
            else:
                action = f"LOWER ${diff:.2f}"

            reason = _build_sell_reason(tk, source, rec_sell, avg, ns_candidates)

            adjustments.append({
                "ticker": tk,
                "shares": current_shares,
                "current_price": current_price,
                "current_pct": current_pct,
                "rec_price": rec_sell,
                "rec_pct": rec_pct,
                "source": source,
                "diff": diff,
                "action": action,
                "reason": reason,
            })

    return adjustments


def compute_buy_adjustments(portfolio, ns_candidates):
    """Compare ALL pending BUY orders against neural pool/bullet sizing."""
    pending = portfolio.get("pending_orders", {})
    adjustments = []

    for tk in sorted(pending.keys()):
        orders = pending[tk]
        # Only active limit orders: placed=True AND not filled
        buy_orders = [o for o in orders
                      if o.get("type", "").upper() == "BUY"
                      and o.get("placed") is True
                      and not o.get("filled")]
        if not buy_orders:
            continue

        cap = load_capital_config(tk)
        pool = cap["active_pool"]
        bullets = cap["active_bullets_max"]
        pool_info = get_ticker_pool(tk)
        pool_source = pool_info.get("source", "default")

        for o in buy_orders:
            buy_price = o.get("price", 0)
            current_shares = o.get("shares", 0)
            if buy_price <= 0:
                continue

            candidate = ns_candidates.get(tk, {})
            allocation = compute_position_allocation(
                pool / max(1, bullets),
                buy_price,
                features=candidate.get("features") or {},
                score=candidate.get("stats") or {},
                max_dollars=pool * 0.60,
            )
            rec_shares = allocation["shares"]
            diff = rec_shares - current_shares

            if diff == 0:
                action = "OK"
            elif diff > 0:
                action = f"+{diff} sh"
            else:
                action = f"{diff} sh"

            reason = _build_buy_reason(tk, pool, bullets, rec_shares, current_shares,
                                       buy_price, pool_source, ns_candidates,
                                       allocation=allocation)

            adjustments.append({
                "ticker": tk,
                "buy_price": buy_price,
                "current_shares": current_shares,
                "rec_shares": rec_shares,
                "pool": pool,
                "bullets": bullets,
                "allocated_dollars": allocation["allocated_dollars"],
                "allocation_multiplier": allocation["allocation_multiplier"],
                "allocation_action": allocation["allocation_action"],
                "allocation_reason": allocation["allocation_reason"],
                "pool_source": pool_source,
                "diff": diff,
                "action": action,
                "reason": reason,
            })

    return adjustments


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_sell_adjustments(adjustments):
    """Print sell adjustment table with reason chains."""
    changes = [a for a in adjustments if a["action"] != "OK"]
    ok = [a for a in adjustments if a["action"] == "OK"]

    print(f"## Sell Order Adjustments ({len(changes)} changes, {len(ok)} OK)\n")
    print(f"| Ticker | Shares | Current Sell | Rec Sell | Action | Reason |")
    print(f"| :--- | :--- | :--- | :--- | :--- | :--- |")
    for a in adjustments:
        bold = "**" if a["action"] != "OK" else ""
        print(f"| {a['ticker']} | {a['shares']} | "
              f"${a['current_price']:.2f} ({a['current_pct']}%) | "
              f"${a['rec_price']:.2f} ({a['rec_pct']}%) | "
              f"{bold}{a['action']}{bold} | {a['reason']} |")
    print()


def print_buy_adjustments(adjustments):
    """Print buy adjustment table with reason chains."""
    changes = [a for a in adjustments if a["action"] != "OK"]
    ok = [a for a in adjustments if a["action"] == "OK"]

    print(f"## Buy Order Adjustments ({len(changes)} changes, {len(ok)} OK)\n")
    print(f"| Ticker | Price | Current | Rec | Alloc | Action | Reason |")
    print(f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for a in adjustments:
        bold = "**" if a["action"] != "OK" else ""
        print(f"| {a['ticker']} | ${a['buy_price']:.2f} | "
              f"{a['current_shares']} sh | {a['rec_shares']} sh | "
              f"{a.get('allocation_action', 'baseline')} {a.get('allocation_multiplier', 1.0):.2f}x | "
              f"{bold}{a['action']}{bold} | {a['reason']} |")
    print()


def compute_and_print_adjustments(portfolio=None):
    """Callable from daily_analyzer for inline report section."""
    if portfolio is None:
        portfolio = _load_portfolio()
    ns_candidates = _load_neural_candidates()

    sell_adj = compute_sell_adjustments(portfolio, ns_candidates)
    buy_adj = compute_buy_adjustments(portfolio, ns_candidates)

    if sell_adj:
        print_sell_adjustments(sell_adj)
    if buy_adj:
        print_buy_adjustments(buy_adj)

    # Summary
    sell_changes = sum(1 for a in sell_adj if a["action"] != "OK")
    buy_changes = sum(1 for a in buy_adj if a["action"] != "OK")
    print(f"*Sells: {sell_changes} changes, {len(sell_adj) - sell_changes} OK | "
          f"Buys: {buy_changes} changes, {len(buy_adj) - buy_changes} OK*")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Neural Order Adjuster")
    parser.add_argument("--sells-only", action="store_true")
    parser.add_argument("--buys-only", action="store_true")
    args = parser.parse_args()

    portfolio = _load_portfolio()
    ns_candidates = _load_neural_candidates()

    print(f"## Neural Order Adjustment Report\n")
    print(f"*Neural profiles: {len(ns_candidates)} tickers*\n")

    if not args.buys_only:
        sell_adj = compute_sell_adjustments(portfolio, ns_candidates)
        print_sell_adjustments(sell_adj)

    if not args.sells_only:
        buy_adj = compute_buy_adjustments(portfolio, ns_candidates)
        print_buy_adjustments(buy_adj)


if __name__ == "__main__":
    main()
