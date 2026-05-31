#!/usr/bin/env python3
"""Build recommendation-only monitoring actions from a trend ledger."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from trend_contracts import (
    ACTION_ADD_TO_CANDIDATE_POOL,
    ACTION_MONITOR,
    ACTION_PROMOTE_TO_SIMULATION,
    SCHEMA_VERSION,
    atomic_write_json,
    atomic_write_text,
    build_run_status,
    copy_to_run_history,
    load_validated_trend_json,
    phase_entry,
    status_from_output_dir,
    utc_now,
)


def _action_for_score(score: float | None) -> tuple[str, str]:
    if score is None:
        return ACTION_MONITOR, "insufficient evidence"
    if score >= 75:
        return ACTION_PROMOTE_TO_SIMULATION, "recent edge score >= 75"
    if score >= 60:
        return ACTION_ADD_TO_CANDIDATE_POOL, "recent edge score >= 60"
    return ACTION_MONITOR, "recent edge score below promotion threshold"


def build_monitoring_actions(ledger: dict[str, Any]) -> dict[str, Any]:
    actions = []
    for idx, record in enumerate(ledger.get("records", [])):
        metrics = record.get("metrics", {})
        score = metrics.get("recent_edge_score") if isinstance(metrics, dict) else None
        action, rationale = _action_for_score(score)
        actions.append({
            "ticker": record.get("ticker"),
            "action": action,
            "write_effect": "none",
            "rationale": rationale,
            "score": score,
            "trend_state": record.get("trend_state"),
            "source_refs": record.get("source_refs", []),
            "ledger_pointer": f"/records/{idx}",
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "monitoring-actions",
        "as_of_date": ledger["as_of_date"],
        "generated_at": utc_now(),
        "actions": actions,
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
        status = build_run_status(
            as_of_date=args.as_of_date,
            run_id=run_id,
            run_status="running",
            generated_at=finished,
            phase_statuses=[
                phase_entry("snapshot", "completed", started_at=ledger["generated_at"], finished_at=started),
                phase_entry("ledger", "completed", started_at=ledger["generated_at"], finished_at=started,
                            output_artifacts=[args.ledger.name]),
                phase_entry("actions", "completed", started_at=started, finished_at=finished,
                            input_artifacts=[args.ledger.name],
                            output_artifacts=[path.name for path in paths]),
                phase_entry("report", "running", started_at=finished, finished_at=None,
                            input_artifacts=[args.ledger.name, paths[0].name]),
            ],
        )
        status_path = atomic_write_json(args.output_dir / "run-status.json", status)
        copy_to_run_history(args.output_dir, args.as_of_date, run_id, paths + [status_path])
        print(f"Wrote {len(actions['actions'])} recommendation-only actions to {paths[0]}")
        return 0
    except Exception as exc:
        print(f"trend action planner failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

