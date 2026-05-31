#!/usr/bin/env python3
"""Render a deterministic V2 trend-monitoring report."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from trend_action_planner import build_monitoring_actions
from trend_contracts import (
    atomic_write_json,
    atomic_write_text,
    build_run_status,
    copy_to_run_history,
    load_json,
    load_validated_trend_json,
    phase_entry,
    status_from_output_dir,
    update_phase_status,
    utc_now,
)


def render_report(ledger: dict[str, Any], actions: dict[str, Any]) -> str:
    action_by_ticker = {
        action.get("ticker"): action
        for action in actions.get("actions", [])
        if isinstance(action, dict)
    }
    lines = [
        f"# Daily Trend Report - {ledger['as_of_date']}",
        "",
        "| Ticker | Category | Readiness | Tier | Score | Action |",
        "| :--- | :--- | :--- | :--- | ---: | :--- |",
    ]
    for record in ledger.get("records", []):
        ticker = record.get("ticker")
        metrics = record.get("metrics", {}) if isinstance(record.get("metrics"), dict) else {}
        action = action_by_ticker.get(ticker, {})
        score = metrics.get("recent_edge_score")
        lines.append(
            f"| {ticker} | {record.get('trend_category', record.get('trend_state', ''))} | "
            f"{record.get('readiness', '')} | {record.get('priority_tier', '')} | "
            f"{'' if score is None else score} | {action.get('action', 'NO_CHANGE')} |"
        )
    summary = ledger.get("summary") or {}
    quotas = actions.get("quotas") or {}
    lines.append("")
    if summary:
        lines.append(
            f"Summary: {summary.get('record_count', len(ledger.get('records', [])))} records; "
            f"transitions {summary.get('by_transition', {})}."
        )
    if quotas:
        lines.append(
            f"Quotas: monitored {quotas.get('used_monitored_tickers')}/{quotas.get('max_monitored_tickers')}, "
            f"refresh {quotas.get('used_high_priority_refreshes')}/{quotas.get('max_high_priority_refreshes')}, "
            f"review {quotas.get('used_review_actions')}/{quotas.get('max_review_actions')}."
        )
    lines.extend([
        "",
        "All recommendations are read-only. No portfolio, trade, watchlist, or candidate files were modified.",
        "",
    ])
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render V2 trend report")
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
        actions_path = args.output_dir / "monitoring-actions.json"
        if actions_path.exists():
            actions = load_json(actions_path)
        else:
            actions = build_monitoring_actions(ledger)
            atomic_write_json(actions_path, actions)
        run_id, _ = status_from_output_dir(args.output_dir, args.as_of_date)
        started = utc_now()
        report_path = atomic_write_text(args.output_dir / "daily-trend-report.md", render_report(ledger, actions))
        finished = utc_now()
        update_phase_status(
            args.output_dir,
            as_of_date=args.as_of_date,
            run_id=run_id,
            phase="report",
            status="completed",
            started_at=started,
            finished_at=finished,
            input_artifacts=[args.ledger.name, actions_path.name],
            output_artifacts=[report_path.name],
        )
        status_path = args.output_dir / "run-status.json"
        copy_to_run_history(args.output_dir, args.as_of_date, run_id, [report_path, actions_path, status_path])
        print(f"Wrote trend report to {report_path}")
        return 0
    except Exception as exc:
        print(f"trend reporter failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

