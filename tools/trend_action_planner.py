#!/usr/bin/env python3
"""Build recommendation-only monitoring actions from a trend ledger."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from trend_contracts import (
    MAX_HIGH_PRIORITY_REFRESHES,
    MAX_MONITORED_TICKERS,
    MAX_REVIEW_ACTIONS,
    MONITORING_ONLY_CATEGORIES,
    NEXT_WORKFLOW,
    SCHEMA_VERSION,
    WATCHLIST_REVIEW_DELTA_PCT,
    atomic_write_json,
    atomic_write_text,
    build_run_status,
    copy_to_run_history,
    load_validated_trend_json,
    phase_entry,
    status_from_output_dir,
    update_phase_status,
    utc_now,
)

_PRIO = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}


def _intended_action(rec: dict[str, Any]) -> str:
    """§11.2 action-category selection from readiness/priority/transition/category."""
    readiness = rec.get("readiness")
    tier = rec.get("priority_tier")
    status = rec.get("trend_status")
    cat = rec.get("trend_category")
    metrics = rec.get("metrics") or {}
    monitoring_only = rec.get("monitoring_only_category") or cat in MONITORING_ONLY_CATEGORIES
    if status in ("stale", "retired"):
        return "COOLDOWN_OR_DROP"
    delta = metrics.get("watchlist_fitness_delta_pct")
    if metrics.get("watchlist_overlap") and isinstance(delta, (int, float)) and delta <= WATCHLIST_REVIEW_DELTA_PCT:
        return "RECOMMEND_WATCHLIST_REVIEW"
    if readiness in ("blocked", "needs_data"):
        return "WATCH_DAILY"
    if readiness == "accepted" and tier == "P1":
        if monitoring_only:
            return "WATCH_INTRADAY"
        return "PROMOTE_TO_DEEP_DIVE" if cat == "EVENT_DRIVEN_SETUP" else "PROMOTE_TO_SIMULATION"
    if readiness == "accepted" and tier == "P2":
        return "WATCH_DAILY" if monitoring_only else "ADD_TO_CANDIDATE_POOL"
    if readiness == "monitor_only":
        return "WATCH_INTRADAY" if rec.get("monitoring_cadence") == "intraday" else "WATCH_DAILY"
    return "NO_CHANGE"


def _score(rec: dict[str, Any]) -> float:
    s = (rec.get("metrics") or {}).get("recent_edge_score")
    return s if isinstance(s, (int, float)) else -1.0


def build_monitoring_actions(ledger: dict[str, Any]) -> dict[str, Any]:
    records = ledger.get("records", []) if isinstance(ledger.get("records"), list) else []
    # §6.2 G2: quotas count distinct tickers; rank each ticker by its best record.
    best: dict[Any, dict[str, Any]] = {}
    for rec in records:
        t = rec.get("ticker")
        if t is None:
            continue
        if t not in best or _score(rec) > _score(best[t]):
            best[t] = rec
    ranked = sorted(best.values(), key=lambda r: (-_score(r), _PRIO.get(r.get("priority_tier"), 3), str(r.get("ticker"))))
    monitored = ranked[:MAX_MONITORED_TICKERS]
    refresh = [r for r in monitored if r.get("source_quality") == "fresh"][:MAX_HIGH_PRIORITY_REFRESHES]
    refresh_tickers = {r.get("ticker") for r in refresh}
    review = [r for r in refresh if r.get("human_action_required")][:MAX_REVIEW_ACTIONS]
    review_tickers = {r.get("ticker") for r in review}

    actions: list[dict[str, Any]] = []
    deferred_review = 0
    deferred_refresh = 0
    for i, rec in enumerate(monitored):
        t = rec.get("ticker")
        action = _intended_action(rec)
        deferred = False
        promote_like = action in ("PROMOTE_TO_SIMULATION", "PROMOTE_TO_DEEP_DIVE",
                                   "ADD_TO_CANDIDATE_POOL", "WATCH_INTRADAY")
        if t not in refresh_tickers:
            # §6.2 G3: monitored-but-not-top-75 caps action at WATCH_DAILY.
            if promote_like:
                action = "WATCH_DAILY"
                deferred = True
                deferred_refresh += 1
        elif t not in review_tickers:
            # top-75 not top-30: promote/review assigned but flagged deferred (not surfaced).
            if action in ("PROMOTE_TO_SIMULATION", "PROMOTE_TO_DEEP_DIVE", "RECOMMEND_WATCHLIST_REVIEW"):
                deferred = True
                deferred_review += 1
        score = _score(rec)
        actions.append({
            "id": f"ACT-{i + 1}",
            "trend_id": rec.get("id"),
            "ticker": t,
            "action": action,
            "action_category": action,
            "priority_tier": rec.get("priority_tier"),
            "reason": f"{rec.get('trend_category')} / {rec.get('readiness')} / {rec.get('trend_status')}",
            "next_workflow": NEXT_WORKFLOW.get(action, "none"),
            "human_approval_required": bool(rec.get("human_action_required")),
            "write_effect": "none",
            "deferred": deferred,
            "score": score if score >= 0 else None,
            "source_refs": rec.get("source_refs", []),
            "expires_after": ledger["as_of_date"],
        })

    by_action: dict[str, int] = {}
    for a in actions:
        by_action[a["action"]] = by_action.get(a["action"], 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "monitoring-actions",
        "as_of_date": ledger["as_of_date"],
        "generated_at": utc_now(),
        "actions": actions,
        "summary": {"by_action_category": by_action},
        "quotas": {
            "max_monitored_tickers": MAX_MONITORED_TICKERS,
            "max_high_priority_refreshes": MAX_HIGH_PRIORITY_REFRESHES,
            "max_review_actions": MAX_REVIEW_ACTIONS,
            "used_monitored_tickers": len(monitored),
            "used_high_priority_refreshes": len(refresh),
            "used_review_actions": len(review),
            "deferred_review": deferred_review,
            "deferred_refresh": deferred_refresh,
            "excluded_overflow": max(0, len(ranked) - len(monitored)),
        },
    }


def render_actions_md(actions: dict[str, Any]) -> str:
    lines = [
        f"# Monitoring Actions - {actions['as_of_date']}",
        "",
        "| Ticker | Action | Score | Write Effect |",
        "| :--- | :--- | ---: | :--- |",
    ]
    for action in actions.get("actions", []):
        score = action.get("score")
        score_text = "" if score is None else str(score)
        lines.append(
            f"| {action.get('ticker')} | {action.get('action')} | "
            f"{score_text} | {action.get('write_effect')} |"
        )
    return "\n".join(lines) + "\n"


def write_action_artifacts(actions: dict[str, Any], output_dir: Path, run_id: str) -> list[Path]:
    json_path = atomic_write_json(output_dir / "monitoring-actions.json", actions)
    md_path = atomic_write_text(output_dir / "monitoring-actions.md", render_actions_md(actions))
    return [json_path, md_path]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build V2 monitoring actions")
    parser.add_argument("--as-of", required=True, dest="as_of_date")
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        ledger = load_validated_trend_json(args.ledger, "trend-ledger")
        if ledger["as_of_date"] != args.as_of_date:
            print("configuration error: ledger as_of_date mismatch", file=sys.stderr)
            return 2
        run_id, _ = status_from_output_dir(args.output_dir, args.as_of_date)
        started = utc_now()
        actions = build_monitoring_actions(ledger)
        paths = write_action_artifacts(actions, args.output_dir, run_id)
        finished = utc_now()
        update_phase_status(
            args.output_dir,
            as_of_date=args.as_of_date,
            run_id=run_id,
            phase="actions",
            status="completed",
            started_at=started,
            finished_at=finished,
            input_artifacts=[args.ledger.name],
            output_artifacts=[path.name for path in paths],
        )
        status_path = args.output_dir / "run-status.json"
        copy_to_run_history(args.output_dir, args.as_of_date, run_id, paths + [status_path])
        print(f"Wrote {len(actions['actions'])} recommendation-only actions to {paths[0]}")
        return 0
    except Exception as exc:
        print(f"trend action planner failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

