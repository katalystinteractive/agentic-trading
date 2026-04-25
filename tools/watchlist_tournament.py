"""Weekly watchlist tournament — simulation-driven ticker ranking.

Ranks all swept tickers by best-of composite $/mo across 4 sweep types
(support, resistance, bounce, entry). Flags watchlist swaps with safety
gates. Produces markdown report + JSON + optional email.

Usage:
    python3 tools/watchlist_tournament.py              # full run with email
    python3 tools/watchlist_tournament.py --dry-run     # report only, no writes
    python3 tools/watchlist_tournament.py --top 25      # custom target size
    python3 tools/watchlist_tournament.py --no-email    # skip email
    python3 tools/watchlist_tournament.py --force       # bypass same-day skip
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import date, datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent))

from model_complexity_gate import filter_live_decision_entries, live_decision_reason

_ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = _ROOT / "portfolio.json"
RESULTS_PATH = _ROOT / "data" / "tournament_results.json"

SWEEP_FILES = {
    "dip": _ROOT / "data" / "sweep_results.json",
    "support": _ROOT / "data" / "support_sweep_results.json",
    "resistance": _ROOT / "data" / "resistance_sweep_results.json",
    "bounce": _ROOT / "data" / "bounce_sweep_results.json",
    "entry": _ROOT / "data" / "entry_sweep_results.json",
    "regime_exit": _ROOT / "data" / "regime_exit_sweep_results.json",
}

PROTECTION_WEEKS = 4
BEAT_MARGIN = 0.20  # 20% beat margin for competitive swaps
MAX_WEEKLY_SWAPS = 3
WIND_DOWN_CONFIRM_RUNS = 2
DIAGNOSTIC_DROP_PCT = 50.0


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
    try:
        data = filter_live_decision_entries(
            raw, path=path, consumer="watchlist_tournament")
    except ValueError:
        print(f"*Ignoring {path.name}: {live_decision_reason(raw)}*")
        data = {}
    _sweep_cache[ps] = {"mtime": mtime, "data": data}
    return data


def _ranking_value(entry):
    """Return tournament score from a sweep entry.

    New artifacts can provide edge_adjusted_composite. Older artifacts keep using
    composite so existing runs remain readable.
    """
    stats = entry.get("stats", {}) if isinstance(entry, dict) else {}
    value = stats.get("edge_adjusted_composite")
    if value is None:
        value = stats.get("composite", 0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_iso_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _active_protection_start(ticker, position, watchlist_meta):
    """Return the newest lifecycle date that should protect an active position."""
    dates = []
    added_dt = _parse_iso_date(watchlist_meta.get(ticker, {}).get("added_date"))
    entry_dt = _parse_iso_date(position.get("entry_date"))
    if added_dt:
        dates.append(added_dt)
    if entry_dt:
        dates.append(entry_dt)
    return max(dates) if dates else None


def _is_recent_active_position(ticker, position, watchlist_meta, now=None):
    start = _active_protection_start(ticker, position, watchlist_meta)
    if not start:
        return False
    now = now or datetime.now()
    return now - start < timedelta(weeks=PROTECTION_WEEKS)


def _below_cutoff_streak(watchlist_meta, ticker):
    try:
        return int(watchlist_meta.get(ticker, {}).get("below_cutoff_streak", 0))
    except (TypeError, ValueError):
        return 0


def load_all_sweeps(portfolio=None):
    """Load all sweep files. Filter to tracked + top challengers.

    Returns {ticker: {sweep_type: tournament_score}}.
    """
    all_data = {}
    for sweep_type, path in SWEEP_FILES.items():
        data = _load_sweep(path)
        for ticker, entry in data.items():
            composite = _ranking_value(entry)
            if ticker not in all_data:
                all_data[ticker] = {}
            all_data[ticker][sweep_type] = composite

    # Supplement with universe pre-screen results (own file, no contamination)
    _prescreen_path = Path(__file__).resolve().parent.parent / "data" / "universe_prescreen_results.json"
    if _prescreen_path.exists():
        try:
            with open(_prescreen_path) as f:
                ps = json.load(f)
            for r in ps.get("rankings", []):
                tk = r["ticker"]
                if tk not in all_data:
                    all_data[tk] = {"prescreen": r["composite"]}
        except (json.JSONDecodeError, KeyError):
            pass

    if not portfolio:
        return all_data

    # Filter: all tracked + all tickers from Tier 2 pool (if available)
    tracked = set(portfolio.get("watchlist", [])) | set(portfolio.get("positions", {}).keys())
    _tier2_path = Path(__file__).resolve().parent.parent / "data" / ".tier2_pool.json"
    if _tier2_path.exists():
        try:
            with open(_tier2_path) as f:
                _tier2 = set(json.load(f))
            # Include all tracked + all Tier 2 pool tickers that have sweep data
            return {tk: comps for tk, comps in all_data.items()
                    if tk in tracked or tk in _tier2}
        except (OSError, json.JSONDecodeError):
            pass

    # Fallback: old formula if no tier2 pool
    untracked = {tk: max(comps.values()) for tk, comps in all_data.items() if tk not in tracked}
    n_challengers = max(len([tk for tk in tracked if tk in all_data]) // 2, 10)
    top_challengers = set(tk for tk, _ in sorted(untracked.items(), key=lambda x: x[1], reverse=True)[:n_challengers])

    return {tk: comps for tk, comps in all_data.items()
            if tk in tracked or tk in top_challengers}


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def compute_rankings(all_sweeps):
    """Rank tickers by best-of tournament score across sweep types.

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
            meta["previous_rankings"] = {
                r.get("ticker"): r
                for r in existing.get("rankings", [])
                if r.get("ticker")
            }
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
      monitor: active positions below cutoff but not confirmed for wind-down yet
      challenge: [{challenger, incumbent, margin}] competitive swaps
      protected: tickers within 4-week protection window
      confirmed: tickers staying in top-N
    """
    actions = {
        "onboard": [], "drop": [], "wind_down": [], "monitor": [],
        "challenge": [], "protected": [], "confirmed": [], "reasons": {},
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

    below_cutoff = []

    for r in rankings:
        if r["rank"] <= top_n:
            if r["ticker"] in tracked:
                meta = wl_meta.setdefault(r["ticker"], {})
                meta["below_cutoff_streak"] = 0
                meta.pop("below_cutoff_last_seen", None)
        else:
            below_cutoff.append(r)

    def _handle_active_exit_candidate(tk, reason):
        pos = positions.get(tk, {})
        meta = wl_meta.setdefault(tk, {})
        today = date.today().isoformat()
        prior_streak = _below_cutoff_streak(wl_meta, tk)
        if meta.get("below_cutoff_last_seen") == today:
            streak = max(prior_streak, 1)
        else:
            streak = prior_streak + 1
        meta["below_cutoff_streak"] = streak
        meta["below_cutoff_last_seen"] = today

        if _is_recent_active_position(tk, pos, wl_meta):
            actions["protected"].append(tk)
            actions["reasons"][tk] = (
                f"active position inside {PROTECTION_WEEKS}-week protection window; "
                f"{reason}; below-cutoff streak {streak}/{WIND_DOWN_CONFIRM_RUNS}"
            )
            return

        if streak < WIND_DOWN_CONFIRM_RUNS:
            actions["monitor"].append(tk)
            actions["reasons"][tk] = (
                f"{reason}; needs {WIND_DOWN_CONFIRM_RUNS} consecutive bad tournament "
                f"runs before wind-down; streak {streak}/{WIND_DOWN_CONFIRM_RUNS}"
            )
            return

        actions["wind_down"].append(tk)
        actions["reasons"][tk] = (
            f"{reason}; confirmed by {streak} consecutive bad tournament runs"
        )

    # --- Process tickers BELOW cutoff that are tracked ---
    for r in below_cutoff:
        tk = r["ticker"]
        if tk not in tracked:
            continue  # candidate below cutoff — no action

        shares = positions.get(tk, {}).get("shares", 0)
        if shares > 0:
            _handle_active_exit_candidate(
                tk,
                f"rank {r['rank']} below top-{top_n} cutoff with score {r['score']}",
            )
            continue

        # Check 4-week protection
        added = wl_meta.get(tk, {}).get("added_date", "2026-01-01")
        added_dt = _parse_iso_date(added) or datetime(2026, 1, 1)
        if datetime.now() - added_dt < timedelta(weeks=PROTECTION_WEEKS):
            actions["protected"].append(tk)
            actions["reasons"][tk] = (
                f"watchlist ticker inside {PROTECTION_WEEKS}-week protection window"
            )
            continue

        actions["drop"].append(tk)
        actions["reasons"][tk] = f"rank {r['rank']} below top-{top_n} cutoff"

    # --- Determine vacated slots and fill with candidates ---
    # Vacated slots = tickers leaving (drop + wind_down from below-cutoff processing)
    leaving = actions["drop"] + actions["wind_down"]

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
            if (tk not in actions["wind_down"] and tk not in actions["protected"]
                    and tk not in actions["monitor"]):
                _handle_active_exit_candidate(tk, "missing from all live sweep artifacts")
        else:
            if tk not in actions["drop"]:
                actions["drop"].append(tk)
                actions["reasons"][tk] = "missing from all live sweep artifacts"

    # Challenged incumbents are already in drop/wind_down — just remove from confirmed
    displaced = {c["incumbent"] for c in actions["challenge"]}
    actions["confirmed"] = [tk for tk in actions["confirmed"] if tk not in displaced]

    return actions


def build_score_diagnostics(rankings, actions, metadata):
    """Explain material score/rank changes and action reasons."""
    previous = metadata.get("previous_rankings", {})
    reasons = actions.get("reasons", {})
    action_by_ticker = {}
    for action_name in ("onboard", "drop", "wind_down", "monitor", "protected"):
        for tk in actions.get(action_name, []):
            action_by_ticker[tk] = action_name
    for challenge in actions.get("challenge", []):
        action_by_ticker[challenge["challenger"]] = "challenge"
        action_by_ticker[challenge["incumbent"]] = "challenged_out"

    diagnostics = {}
    for r in rankings:
        tk = r["ticker"]
        prior = previous.get(tk, {})
        prior_score = prior.get("score")
        score_delta = None
        score_delta_pct = None
        if isinstance(prior_score, (int, float)):
            score_delta = round(r["score"] - prior_score, 2)
            if prior_score:
                score_delta_pct = round((score_delta / prior_score) * 100, 1)

        material_drop = (
            score_delta_pct is not None
            and score_delta_pct <= -DIAGNOSTIC_DROP_PCT
        )
        if tk not in action_by_ticker and not material_drop:
            continue

        diagnostics[tk] = {
            "rank": r["rank"],
            "score": r["score"],
            "best_strategy": r.get("best_strategy"),
            "composites": r.get("composites", {}),
            "previous_rank": prior.get("rank"),
            "previous_score": prior_score,
            "previous_best_strategy": prior.get("best_strategy"),
            "previous_composites": prior.get("composites", {}),
            "score_delta": score_delta,
            "score_delta_pct": score_delta_pct,
            "action": action_by_ticker.get(tk, "score_drop"),
            "reason": reasons.get(tk, ""),
        }

    return diagnostics


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def build_report(rankings, actions, top_n, score_diagnostics=None):
    """Build markdown tournament report."""
    score_diagnostics = score_diagnostics or {}
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
    for tk in actions.get("monitor", []):
        action_map[tk] = "MONITOR"
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
                     + len(actions["wind_down"]) + len(actions.get("monitor", []))
                     + len(actions["protected"])
                     + len(actions["challenge"]))
    if total_actions == 0:
        lines.append("*No changes recommended this week.*")
    else:
        for tk in actions["onboard"]:
            lines.append(f"- **ONBOARD**: {tk}")
            lines.append(f"  → Run: `python3 tools/bullet_recommender.py {tk}` for entry levels")
        for c in actions["challenge"]:
            note = c.get("note", "")
            note_str = f" *[{note}]*" if note else ""
            lines.append(
                f"- **CHALLENGE**: {c['challenger']} to replace "
                f"{c['incumbent']} (+{c['margin_pct']}%){note_str}")
            lines.append(f"  → Run: `python3 tools/bullet_recommender.py {c['challenger']}` for entry levels")
        for tk in actions["wind_down"]:
            reason = actions.get("reasons", {}).get(tk, "")
            suffix = f" — {reason}" if reason else ""
            lines.append(f"- **WIND DOWN**: {tk} (active position — no new bullets){suffix}")
        for tk in actions.get("monitor", []):
            reason = actions.get("reasons", {}).get(tk, "")
            suffix = f" — {reason}" if reason else ""
            lines.append(f"- **MONITOR**: {tk} (active position — wind-down not confirmed){suffix}")
        for tk in actions["drop"]:
            reason = actions.get("reasons", {}).get(tk, "")
            suffix = f" — {reason}" if reason else ""
            lines.append(f"- **DROP**: {tk} (no active position){suffix}")
        for tk in actions["protected"]:
            reason = actions.get("reasons", {}).get(tk, "")
            suffix = f" — {reason}" if reason else ""
            lines.append(f"- **PROTECTED**: {tk} (protected from churn){suffix}")

    if score_diagnostics:
        lines.extend([
            "",
            "### Score Diagnostics",
            "| Ticker | Action | Score | Previous | Δ | Rank | Previous Rank | Reason |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ])
        action_order = {
            "wind_down": 0,
            "monitor": 1,
            "protected": 2,
            "challenged_out": 3,
            "drop": 4,
            "challenge": 5,
            "onboard": 6,
            "score_drop": 7,
            "confirmed": 8,
        }
        rows = sorted(
            score_diagnostics.items(),
            key=lambda item: (action_order.get(item[1].get("action"), 99), item[0]),
        )
        for tk, d in rows[:40]:
            prev_score = d["previous_score"]
            prev_score_s = f"${prev_score:.1f}" if isinstance(prev_score, (int, float)) else "—"
            delta = d["score_delta"]
            if isinstance(delta, (int, float)):
                delta_s = f"{delta:+.1f}"
                if d["score_delta_pct"] is not None:
                    delta_s += f" ({d['score_delta_pct']:+.1f}%)"
            else:
                delta_s = "—"
            prev_rank = d["previous_rank"] if d["previous_rank"] is not None else "—"
            reason = str(d.get("reason", "")).replace("|", "/")
            lines.append(
                f"| {tk} | {d['action']} | ${d['score']:.1f} | {prev_score_s} | "
                f"{delta_s} | {d['rank']} | {prev_rank} | {reason} |"
            )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Save results
# ---------------------------------------------------------------------------

def save_results(rankings, actions, metadata, score_diagnostics=None):
    """Write tournament results to data/tournament_results.json (atomic)."""
    output = {
        "_meta": {
            "last_run": date.today().isoformat(),
            "tickers_ranked": len(rankings),
        },
        "rankings": rankings,
        "actions": actions,
        "score_diagnostics": score_diagnostics or {},
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

    # Clear stale wind-down flags when the new guard says to keep monitoring.
    keep_active = (
        set(actions.get("protected", []))
        | set(actions.get("monitor", []))
        | set(actions.get("confirmed", []))
    )
    for tk in keep_active:
        pos = portfolio.get("positions", {}).get(tk)
        if pos and pos.pop("winding_down", None) is not None:
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
            # Run all simulation sweeps for successfully onboarded tickers
            successful = [r["ticker"] for r in results if r["status"] == "ok"]
            if successful:
                run_post_onboard_sweeps(successful, strategy_types=strategy_types)
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
    parser.add_argument("--force", action="store_true",
                        help="Run even if today's tournament result already exists")
    args = parser.parse_args()

    # Idempotency: skip if already ran today with fresh sweep data
    if RESULTS_PATH.exists() and not args.dry_run and not args.force:
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
    score_diagnostics = build_score_diagnostics(rankings, actions, metadata)

    # Report
    report = build_report(rankings, actions, args.top, score_diagnostics)
    print(report)

    if args.dry_run:
        return

    # Save results
    save_results(rankings, actions, metadata, score_diagnostics)

    # Execute actions
    total_actions = (len(actions["onboard"]) + len(actions["drop"])
                     + len(actions["wind_down"]) + len(actions.get("monitor", []))
                     + len(actions["protected"])
                     + len(actions["challenge"]))
    if total_actions > 0:
        execute_actions(actions, portfolio, metadata, rankings)
        save_results(rankings, actions, metadata, score_diagnostics)  # re-save with updated metadata

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
