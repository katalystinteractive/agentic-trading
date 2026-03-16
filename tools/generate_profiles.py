#!/usr/bin/env python3
"""
Generate Profiles — Consolidates Phase 4 cached data into ticker_profiles.json.

CLI: python3 tools/generate_profiles.py
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

import yfinance as yf
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shared_wick import parse_wick_active_supports
from shared_utils import load_json, parse_entry_date

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO = PROJECT_ROOT / "portfolio.json"
OUTPUT = PROJECT_ROOT / "ticker_profiles.json"


def compute_abandon_flags(ticker, pos, current_price, today, portfolio):
    """Compute abandon flags for a position. Returns list of triggered criteria."""
    flags = []
    avg_cost = pos.get("avg_cost", 0)
    shares = pos.get("shares", 0)
    if not isinstance(shares, int) or shares <= 0 or avg_cost <= 0:
        return flags
    if current_price >= avg_cost:
        return flags  # not underwater

    # C1: all active supports broke
    supports = parse_wick_active_supports(ticker)
    if len(supports) >= 2 and all(current_price < s for s in supports):
        flags.append("C1")

    # C2: days stuck > 30
    entry, _ = parse_entry_date(pos.get("entry_date", ""))
    if entry and (today - entry).days > 30:
        flags.append("C2")

    # C3: loss > 20% and reserves can't rescue
    loss_pct = (current_price - avg_cost) / avg_cost * 100
    if loss_pct <= -20:
        reserves = []
        for o in portfolio.get("pending_orders", {}).get(ticker, []):
            if o.get("type", "").upper() == "BUY" and not o.get("filled"):
                note = o.get("note", "").lower()
                if "reserve" in note or re.search(r'\br\d', note):
                    reserves.append(o)
        total_cost = shares * avg_cost + sum(r.get("shares", 0) * r.get("price", 0) for r in reserves)
        total_shares = shares + sum(r.get("shares", 0) for r in reserves)
        if total_shares > 0:
            new_avg = total_cost / total_shares
            rescue_gap = (new_avg - current_price) / current_price * 100
            if rescue_gap > 15:
                flags.append("C3")

    return flags


def main():
    portfolio = load_json(PORTFOLIO)
    positions = portfolio.get("positions", {})
    today = date.today()
    # Collect all tickers from positions and watchlist
    all_tickers = set(positions.keys())
    all_tickers.update(portfolio.get("watchlist", []))
    for t in portfolio.get("pending_orders", {}).keys():
        all_tickers.add(t)

    profiles = {}
    for ticker in sorted(all_tickers):
        pos = positions.get(ticker, {})

        # Pullback profile cache
        pp_path = PROJECT_ROOT / "tickers" / ticker / "pullback_profile.json"
        pp = load_json(pp_path)

        # Cycle timing cache
        ct_path = PROJECT_ROOT / "tickers" / ticker / "cycle_timing.json"
        ct = load_json(ct_path)

        # Extract fields
        avg_depth = pp.get("avg_depth_pct") if pp else None
        b1_rate = None
        if pp and pp.get("bullet_fill_rates"):
            b1_rate = pp["bullet_fill_rates"][0].get("fill_rate_pct")

        median_fill_days = ct.get("statistics", {}).get("median_deep") if ct else None
        current_phase = pp.get("current_phase") if pp else None

        # Abandon flags (only for active underwater positions)
        shares = pos.get("shares", 0)
        if isinstance(shares, int) and shares > 0:
            # Fetch current price directly (F5 fix: no fragile inference)
            current_price = None
            try:
                df = yf.download(ticker, period="5d", auto_adjust=True, progress=False)
                if not df.empty:
                    close = df["Close"]
                    if isinstance(close, pd.DataFrame):
                        close = close.iloc[:, 0]
                    current_price = float(close.iloc[-1])
            except Exception:
                pass
            flags = compute_abandon_flags(ticker, pos, current_price, today, portfolio) if current_price else []
        else:
            flags = []

        profiles[ticker] = {
            "optimal_target_pct": None,
            "optimal_bullet_count": None,
            "avg_pullback_depth_pct": avg_depth,
            "b1_fill_rate_pct": b1_rate,
            "median_fill_days": median_fill_days,
            "capital_velocity_per_day": None,
            "reserve_utilization_pct": None,
            "abandon_threshold_pct": None,
            "abandon_flags": flags,
            "deployment_status": None,
            "current_phase": current_phase,
            "last_updated": today.isoformat(),
        }

    # Add schema documentation
    output = {
        "_schema": {
            "phase4_native": ["avg_pullback_depth_pct", "b1_fill_rate_pct", "median_fill_days", "abandon_flags", "current_phase"],
            "blocked_phase1": ["capital_velocity_per_day", "reserve_utilization_pct", "optimal_target_pct"],
            "blocked_phase2": ["optimal_bullet_count", "abandon_threshold_pct"],
            "phase5_only": ["deployment_status"],
        },
        **profiles,
    }

    with open(OUTPUT, "w") as f:
        json.dump(output, f, indent=2)

    print(f"### Ticker Profiles Generated")
    print(f"")
    print(f"| Metric | Value |")
    print(f"| :--- | :--- |")
    print(f"| Tickers profiled | {len(profiles)} |")
    with_pullback = sum(1 for p in profiles.values() if p["avg_pullback_depth_pct"] is not None)
    with_cycle = sum(1 for p in profiles.values() if p["median_fill_days"] is not None)
    with_flags = sum(1 for p in profiles.values() if p["abandon_flags"])
    print(f"| With pullback data | {with_pullback} |")
    print(f"| With cycle timing | {with_cycle} |")
    print(f"| With abandon flags | {with_flags} |")
    print(f"| Output | ticker_profiles.json |")

    if with_flags:
        print(f"")
        print(f"**Flagged tickers:** {', '.join(t for t, p in profiles.items() if p['abandon_flags'])}")


if __name__ == "__main__":
    main()
