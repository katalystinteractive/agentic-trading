"""Weekly watchlist tournament — simulation-driven ticker ranking.

Ranks all swept tickers by best-of composite $/mo across 4 sweep types
(support, resistance, bounce, entry). Flags watchlist swaps with safety
gates. Produces markdown report + JSON + optional email.

Usage:
    python3 tools/watchlist_tournament.py              # full run with email
    python3 tools/watchlist_tournament.py --dry-run     # report only, no writes
    python3 tools/watchlist_tournament.py --top 25      # custom target size
    python3 tools/watchlist_tournament.py --no-email    # skip email
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import date, datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent))

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"
RESULTS_PATH = _ROOT / "data" / "tournament_results.json"

SWEEP_FILES = {
    "dip": _ROOT / "data" / "sweep_results.json",
    "support": _ROOT / "data" / "support_sweep_results.json",
    "resistance": _ROOT / "data" / "resistance_sweep_results.json",
    "bounce": _ROOT / "data" / "bounce_sweep_results.json",
    "entry": _ROOT / "data" / "entry_sweep_results.json",
}

PROTECTION_WEEKS = 4
BEAT_MARGIN = 0.20  # 20% beat margin for competitive swaps
MAX_WEEKLY_SWAPS = 3


# ---------------------------------------------------------------------------
# Sweep loading
# ---------------------------------------------------------------------------

_sweep_cache = {}  # {path_str: {"mtime": float, "data": dict}}


def _load_sweep(path):
    """Load a sweep result file with mtime caching. Returns {ticker: stats}."""
    ps = str(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    cached = _sweep_cache.get(ps)
    if cached and cached["mtime"] == mtime:
        return cached["data"]
    try:
        with open(path) as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    data = {k: v for k, v in raw.items() if not k.startswith("_")}
    _sweep_cache[ps] = {"mtime": mtime, "data": data}
    return data


def load_all_sweeps(portfolio=None):
    """Load all 4 sweep files. Filter to tracked + top challengers.

    Returns {ticker: {sweep_type: composite}}.
    """
    all_data = {}
    for sweep_type, path in SWEEP_FILES.items():
        data = _load_sweep(path)
        for ticker, entry in data.items():
            composite = entry.get("stats", {}).get("composite", 0)
            if ticker not in all_data:
                all_data[ticker] = {}
            all_data[ticker][sweep_type] = composite

    if not portfolio:
        return all_data

    # Filter: all tracked + top N challengers by best composite
    tracked = set(portfolio.get("watchlist", [])) | set(portfolio.get("positions", {}).keys())
    untracked = {tk: max(comps.values()) for tk, comps in all_data.items() if tk not in tracked}
    n_challengers = max(len([tk for tk in tracked if tk in all_data]) // 2, 10)
    top_challengers = set(tk for tk, _ in sorted(untracked.items(), key=lambda x: x[1], reverse=True)[:n_challengers])

    return {tk: comps for tk, comps in all_data.items()
            if tk in tracked or tk in top_challengers}


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def compute_rankings(all_sweeps):
    """Rank tickers by best-of composite across sweep types.

    Returns sorted list of dicts:
    [{ticker, score, best_strategy, strategy_type, active_levels, composites}, ...]
    """
    from shared_utils import get_strategy_type

    rankings = []
    for ticker, composites in all_sweeps.items():
        if not composites:
            continue
        best_strategy = max(composites, key=composites.get)
        score = composites[best_strategy]
        strategy_type, active_levels = get_strategy_type(ticker)
        rankings.append({
            "ticker": ticker,
            "score": round(score, 2),
            "best_strategy": best_strategy,
            "strategy_type": strategy_type,
            "active_levels": active_levels,
            "composites": {k: round(v, 2) for k, v in composites.items()},
        })
    rankings.sort(key=lambda x: x["score"], reverse=True)
    for i, r in enumerate(rankings):
        r["rank"] = i + 1
    return rankings


def classify_tickers(rankings, portfolio):
    """Tag each ticker with its current status."""
    positions = portfolio.get("positions", {})
    watchlist = set(portfolio.get("watchlist", []))
    for r in rankings:
        tk = r["ticker"]
        shares = positions.get(tk, {}).get("shares", 0)
        if shares > 0:
            r["status"] = "position"
        elif tk in watchlist or tk in positions:
            r["status"] = "watchlist"
        else:
            r["status"] = "candidate"


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------

def load_metadata():
    """Load watchlist_metadata + swap_history from tournament results.

    Seeds existing watchlist tickers with added_date='2026-01-01' if missing.
    """
    meta = {"watchlist_metadata": {}, "swap_history": []}
    if RESULTS_PATH.exists():
        try:
            with open(RESULTS_PATH) as f:
                existing = json.load(f)
            meta["watchlist_metadata"] = existing.get("watchlist_metadata", {})
            meta["swap_history"] = existing.get("swap_history", [])
        except (OSError, json.JSONDecodeError):
            pass

    # Seed existing watchlist tickers
    try:
        with open(PORTFOLIO_PATH) as f:
            portfolio = json.load(f)
        for tk in portfolio.get("watchlist", []):
            if tk not in meta["watchlist_metadata"]:
                meta["watchlist_metadata"][tk] = {"added_date": "2026-01-01"}
        for tk in portfolio.get("positions", {}):
            if tk not in meta["watchlist_metadata"]:
                meta["watchlist_metadata"][tk] = {"added_date": "2026-01-01"}
    except (OSError, json.JSONDecodeError):
        pass

    return meta


# ---------------------------------------------------------------------------
# Safety gates
# ---------------------------------------------------------------------------

def apply_safety_gates(rankings, portfolio, metadata, top_n=30):
    """Apply safety gates to tournament rankings.

    Returns dict of actions:
      onboard: tickers to add to watchlist + onboard
      drop: tickers to remove from watchlist (no position)
      wind_down: tickers with positions to set winding_down flag
      challenge: [{challenger, incumbent, margin}] competitive swaps
      protected: tickers within 4-week protection window
      confirmed: tickers staying in top-N
    """
    actions = {
        "onboard": [], "drop": [], "wind_down": [],
        "challenge": [], "protected": [], "confirmed": [],
    }

    positions = portfolio.get("positions", {})
    watchlist = set(portfolio.get("watchlist", []))
    tracked = watchlist | set(positions.keys())
    wl_meta = metadata.get("watchlist_metadata", {})
    swap_history = metadata.get("swap_history", [])

    # Count recent competitive swaps (this week)
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()[:10]
    recent_swaps = sum(1 for s in swap_history
                       if s.get("date", "") >= week_ago
                       and s.get("type") == "competitive")

    top_set = set()
    below_cutoff = []

    for r in rankings:
        if r["rank"] <= top_n:
            top_set.add(r["ticker"])
        else:
            below_cutoff.append(r)

    # --- Process tickers BELOW cutoff that are tracked ---
    for r in below_cutoff:
        tk = r["ticker"]
        if tk not in tracked:
            continue  # candidate below cutoff — no action

        shares = positions.get(tk, {}).get("shares", 0)
        if shares > 0:
            actions["wind_down"].append(tk)
            continue

        # Check 4-week protection
        added = wl_meta.get(tk, {}).get("added_date", "2026-01-01")
        try:
            added_dt = datetime.fromisoformat(added)
        except (ValueError, TypeError):
            added_dt = datetime(2026, 1, 1)
        if datetime.now() - added_dt < timedelta(weeks=PROTECTION_WEEKS):
            actions["protected"].append(tk)
            continue

        actions["drop"].append(tk)

    # --- Determine vacated slots and fill with candidates ---
    # Vacated slots = tickers leaving (drop + wind_down from below-cutoff processing)
    leaving = actions["drop"] + actions["wind_down"]
    slots_available = len(leaving)

    # Tracked tickers IN top-N are confirmed
    for r in rankings:
        if r["rank"] > top_n:
            break
        if r["ticker"] in tracked:
            actions["confirmed"].append(r["ticker"])

    # Candidates IN top-N, ranked by score (already sorted)
    candidates_in_top = [r for r in rankings
                         if r["rank"] <= top_n and r["ticker"] not in tracked]

    # Build replacement pool: leaving tickers sorted worst-first
    leaving_scores = {}
    for r in rankings:
        if r["ticker"] in leaving:
            leaving_scores[r["ticker"]] = r["score"]
    # Add zero-data tickers (TMC, SMCI) that aren't in rankings
    for tk in leaving:
        if tk not in leaving_scores:
            leaving_scores[tk] = 0
    replaceable = sorted(leaving_scores.items(), key=lambda x: x[1])

    # Fill slots: match best candidate → worst departing ticker
    for candidate_r in candidates_in_top:
        if recent_swaps >= MAX_WEEKLY_SWAPS:
            break
        if not replaceable:
            break
        if candidate_r["score"] <= 0:
            continue

        # Compare against the ticker being replaced (worst remaining)
        replace_tk, replace_score = replaceable[0]
        if replace_score <= 0:
            margin = float("inf")
        else:
            margin = (candidate_r["score"] - replace_score) / replace_score
        if margin < BEAT_MARGIN:
            continue  # doesn't beat the departing ticker by enough

        challenge = {
            "challenger": candidate_r["ticker"],
            "incumbent": replace_tk,
            "margin_pct": round(margin * 100, 1),
            "challenger_score": candidate_r["score"],
            "incumbent_score": replace_score,
        }
        if candidate_r.get("strategy_type") == "daily_range":
            challenge["note"] = "daily_range — use dip entry, not surgical bullets"
        actions["challenge"].append(challenge)
        recent_swaps += 1
        replaceable.pop(0)  # slot filled

    # --- Emergency drops: tracked tickers with zero sweep data ---
    all_swept = set(r["ticker"] for r in rankings)
    for tk in tracked:
        if tk in all_swept:
            continue
        shares = positions.get(tk, {}).get("shares", 0)
        if shares > 0:
            if tk not in actions["wind_down"]:
                actions["wind_down"].append(tk)
        else:
            if tk not in actions["drop"]:
                actions["drop"].append(tk)

    # Challenged incumbents are already in drop/wind_down — just remove from confirmed
    displaced = {c["incumbent"] for c in actions["challenge"]}
    actions["confirmed"] = [tk for tk in actions["confirmed"] if tk not in displaced]

    return actions


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def build_report(rankings, actions, top_n):
    """Build markdown tournament report."""
    today = date.today().isoformat()
    lines = [
        f"## Watchlist Tournament — {today}",
        "",
        f"*{len(rankings)} tickers ranked | Target: top {top_n}*",
        "",
        "### Power Rankings",
        "| Rank | Ticker | Score | Best Strategy | Type | Status | Action |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    action_map = {}
    for tk in actions["onboard"]:
        action_map[tk] = "ONBOARD"
    for tk in actions["drop"]:
        action_map[tk] = "DROP"
    for tk in actions["wind_down"]:
        action_map[tk] = "WIND DOWN"
    for c in actions["challenge"]:
        action_map[c["challenger"]] = f"CHALLENGE (vs {c['incumbent']}, +{c['margin_pct']}%)"
    for tk in actions["protected"]:
        action_map[tk] = "PROTECTED (<4wk)"
    for tk in actions["confirmed"]:
        action_map[tk] = "✓"

    for r in rankings:
        action = action_map.get(r["ticker"], "—")
        separator = "---" if r["rank"] == top_n else ""
        st_label = r.get("strategy_type", "surgical")[:3].upper()
        lines.append(
            f"| {r['rank']} | {r['ticker']} | ${r['score']:.1f} | "
            f"{r['best_strategy']} | {st_label} | {r['status']} | {action} |"
        )
        if separator:
            lines.append(f"| --- | --- | --- | --- | --- | --- | *cutoff* |")

    # Actions summary
    lines.extend(["", "### Recommended Actions"])
    total_actions = (len(actions["onboard"]) + len(actions["drop"])
                     + len(actions["wind_down"]) + len(actions["challenge"]))
    if total_actions == 0:
        lines.append("*No changes recommended this week.*")
    else:
        for tk in actions["onboard"]:
            lines.append(f"- **ONBOARD**: {tk}")
        for c in actions["challenge"]:
            note = c.get("note", "")
            note_str = f" *[{note}]*" if note else ""
            lines.append(
                f"- **CHALLENGE**: {c['challenger']} to replace "
                f"{c['incumbent']} (+{c['margin_pct']}%){note_str}")
        for tk in actions["wind_down"]:
            lines.append(f"- **WIND DOWN**: {tk} (active position — no new bullets)")
        for tk in actions["drop"]:
            lines.append(f"- **DROP**: {tk} (no active position)")
        for tk in actions["protected"]:
            lines.append(f"- **PROTECTED**: {tk} (added <4 weeks ago)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Save results
# ---------------------------------------------------------------------------

def save_results(rankings, actions, metadata):
    """Write tournament results to data/tournament_results.json (atomic)."""
    output = {
        "_meta": {
            "last_run": date.today().isoformat(),
            "tickers_ranked": len(rankings),
        },
        "rankings": rankings,
        "actions": actions,
        "watchlist_metadata": metadata.get("watchlist_metadata", {}),
        "swap_history": metadata.get("swap_history", []),
    }

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = RESULTS_PATH.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(output, f, indent=2)
    tmp.rename(RESULTS_PATH)


def execute_actions(actions, portfolio, metadata, rankings=None):
    """Auto-execute tournament actions on portfolio.json."""
    changed = False

    # Set winding_down on positions
    for tk in actions["wind_down"]:
        if tk in portfolio.get("positions", {}):
            portfolio["positions"][tk]["winding_down"] = True
            changed = True

    # Drop tickers with no position
    watchlist = portfolio.get("watchlist", [])
    positions = portfolio.get("positions", {})
    for tk in actions["drop"]:
        if tk in watchlist:
            watchlist.remove(tk)
            changed = True
        # Clean up zero-share position entry
        if tk in positions and positions[tk].get("shares", 0) == 0:
            del positions[tk]
            changed = True
        # Clean up pending orders
        if tk in portfolio.get("pending_orders", {}):
            del portfolio["pending_orders"][tk]
            changed = True
        # Clean up metadata
        metadata["watchlist_metadata"].pop(tk, None)

    # Remove challenged incumbents (if no active position → drop; if position → wind_down)
    positions = portfolio.get("positions", {})
    for c in actions["challenge"]:
        inc = c["incumbent"]
        inc_shares = positions.get(inc, {}).get("shares", 0)
        if inc_shares > 0:
            positions[inc]["winding_down"] = True
            changed = True
        else:
            if inc in watchlist:
                watchlist.remove(inc)
                changed = True
            metadata["watchlist_metadata"].pop(inc, None)

    # Record swaps in history
    today = date.today().isoformat()
    for c in actions["challenge"]:
        metadata["swap_history"].append({
            "date": today,
            "in": c["challenger"],
            "out": c["incumbent"],
            "type": "competitive",
        })
    for tk in actions["drop"]:
        metadata["swap_history"].append({
            "date": today,
            "in": None,
            "out": tk,
            "type": "drop",
        })

    # Onboard new tickers
    onboard_list = actions["onboard"] + [c["challenger"] for c in actions["challenge"]]
    if onboard_list:
        # Build strategy type map from rankings
        strategy_types = {}
        if rankings:
            strategy_types = {r["ticker"]: r.get("strategy_type", "surgical")
                              for r in rankings}
        try:
            from batch_onboard import batch_onboard, run_post_onboard_sweeps
            results = batch_onboard(onboard_list, dry_run=False, max_workers=6)
            for r in results:
                if r["status"] == "ok":
                    if r["ticker"] not in watchlist:
                        watchlist.append(r["ticker"])
                    metadata["watchlist_metadata"][r["ticker"]] = {
                        "added_date": today,
                    }
                    changed = True
                else:
                    print(f"  *Onboard failed for {r['ticker']}: {r.get('errors', [])}*")
        except Exception as e:
            print(f"  *Batch onboard error: {e}*")

    if changed:
        portfolio["watchlist"] = sorted(watchlist)
        tmp = PORTFOLIO_PATH.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(portfolio, f, indent=2)
        tmp.rename(PORTFOLIO_PATH)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Weekly Watchlist Tournament")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report only — no writes, no email")
    parser.add_argument("--top", type=int, default=30,
                        help="Target watchlist size (default: 30)")
    parser.add_argument("--no-email", action="store_true",
                        help="Skip email notification")
    args = parser.parse_args()

    # Idempotency: skip if already ran today with fresh sweep data
    if RESULTS_PATH.exists() and not args.dry_run:
        try:
            with open(RESULTS_PATH) as f:
                prior = json.load(f)
            if prior.get("_meta", {}).get("last_run") == date.today().isoformat():
                all_fresh = all(
                    p.exists() and date.fromtimestamp(p.stat().st_mtime) == date.today()
                    for p in SWEEP_FILES.values() if p.exists()
                )
                if all_fresh:
                    print("*Tournament already ran today with fresh data — skipping.*")
                    return
        except (OSError, json.JSONDecodeError):
            pass

    # Load data
    try:
        with open(PORTFOLIO_PATH) as f:
            portfolio = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"*Cannot load portfolio: {e}*")
        return

    all_sweeps = load_all_sweeps(portfolio)
    if not all_sweeps:
        print("*No sweep data available — cannot run tournament.*")
        return

    metadata = load_metadata()

    # Rank
    rankings = compute_rankings(all_sweeps)
    classify_tickers(rankings, portfolio)

    # Apply gates
    actions = apply_safety_gates(rankings, portfolio, metadata, args.top)

    # Report
    report = build_report(rankings, actions, args.top)
    print(report)

    if args.dry_run:
        return

    # Save results
    save_results(rankings, actions, metadata)

    # Execute actions
    total_actions = (len(actions["onboard"]) + len(actions["drop"])
                     + len(actions["wind_down"]) + len(actions["challenge"]))
    if total_actions > 0:
        execute_actions(actions, portfolio, metadata, rankings)
        save_results(rankings, actions, metadata)  # re-save with updated metadata

    # Email
    if not args.no_email:
        try:
            from notify import send_summary_email
            n_actions = total_actions
            subject = (f"Watchlist Tournament — {n_actions} action{'s' if n_actions != 1 else ''}"
                       if n_actions > 0
                       else "Watchlist Tournament — no changes")
            send_summary_email(subject, report)
        except Exception as e:
            print(f"*Email failed: {e}*")


if __name__ == "__main__":
    main()
