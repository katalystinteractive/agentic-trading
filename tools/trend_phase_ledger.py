#!/usr/bin/env python3
"""Run the deterministic snapshot-to-ledger phase with status tracking."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from trend_contracts import (
    atomic_write_json,
    build_run_status,
    copy_to_run_history,
    issue_dicts,
    load_validated_trend_json,
    phase_entry,
    status_from_output_dir,
    utc_now,
)
from trend_critic import build_critic_patches
from trend_ledger import build_trend_ledger, render_ledger_md
from trend_validator import findings_artifact, validate_trend_ledger_records


def run_ledger_phase(as_of_date: str, snapshot_path: Path, output_dir: Path) -> tuple[int, list[Path]]:
    run_id, _ = status_from_output_dir(output_dir, as_of_date)
    snapshot = load_validated_trend_json(snapshot_path, "daily-market-snapshot")
    if snapshot["as_of_date"] != as_of_date:
        raise ValueError("snapshot as_of_date mismatch")
    started = utc_now()
    ledger = build_trend_ledger(snapshot)
    ledger_path = atomic_write_json(output_dir / "trend-ledger.json", ledger)
    ledger_md_path = (output_dir / "trend-ledger.md")
    from trend_contracts import atomic_write_text

    atomic_write_text(ledger_md_path, render_ledger_md(ledger))
    issues = validate_trend_ledger_records(ledger)
    findings = findings_artifact(as_of_date=as_of_date, issues=issues, source_artifact="trend-ledger")
    findings_path = atomic_write_json(output_dir / "validation-findings.json", findings)
    patches = build_critic_patches(findings)
    patches_path = atomic_write_json(output_dir / "critic-patches.json", patches)
    finished = utc_now()
    if issues:
        errors = issue_dicts(issues)
        status = build_run_status(
            as_of_date=as_of_date,
            run_id=run_id,
            run_status="nonconverged",
            generated_at=finished,
            phase_statuses=[
                phase_entry("snapshot", "completed", started_at=snapshot["generated_at"], finished_at=started,
                            output_artifacts=[snapshot_path.name]),
                phase_entry("ledger", "nonconverged", started_at=started, finished_at=finished,
                            input_artifacts=[snapshot_path.name],
                            output_artifacts=[ledger_path.name, findings_path.name, patches_path.name],
                            errors=errors),
                phase_entry("actions", "skipped", started_at=None, finished_at=finished),
                phase_entry("report", "skipped", started_at=None, finished_at=finished),
            ],
        )
        status_path = atomic_write_json(output_dir / "run-status.json", status)
        paths = [ledger_path, ledger_md_path, findings_path, patches_path, status_path]
        copy_to_run_history(output_dir, as_of_date, run_id, paths)
        return 1, paths

    status = build_run_status(
        as_of_date=as_of_date,
        run_id=run_id,
        run_status="running",
        generated_at=finished,
        phase_statuses=[
            phase_entry("snapshot", "completed", started_at=snapshot["generated_at"], finished_at=started,
                        output_artifacts=[snapshot_path.name]),
            phase_entry("ledger", "completed", started_at=started, finished_at=finished,
                        input_artifacts=[snapshot_path.name],
                        output_artifacts=[ledger_path.name, ledger_md_path.name, findings_path.name, patches_path.name]),
            phase_entry("actions", "running", started_at=finished, finished_at=None,
                        input_artifacts=[ledger_path.name]),
            phase_entry("report", "skipped", started_at=None, finished_at=finished),
        ],
    )
    status_path = atomic_write_json(output_dir / "run-status.json", status)
    paths = [ledger_path, ledger_md_path, findings_path, patches_path, status_path]
    copy_to_run_history(output_dir, as_of_date, run_id, paths)
    return 0, paths


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run V2 trend ledger phase")
    parser.add_argument("--as-of", required=True, dest="as_of_date")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        code, paths = run_ledger_phase(args.as_of_date, args.snapshot, args.output_dir)
        print(f"Wrote ledger phase artifacts to {args.output_dir} ({len(paths)} files)")
        return code
    except ValueError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"trend phase ledger failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

