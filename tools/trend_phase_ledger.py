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
    update_phase_status,
    utc_now,
)
from trend_critic import build_critic_patches
from trend_ledger import build_trend_ledger, render_ledger_md
from trend_validator import apply_strategy_gates, findings_artifact, validate_trend_ledger_records


def run_ledger_phase(as_of_date: str, snapshot_path: Path, output_dir: Path,
                     *, market_regime: str | None = None) -> tuple[int, list[Path]]:
    run_id, _ = status_from_output_dir(output_dir, as_of_date)
    snapshot = load_validated_trend_json(snapshot_path, "daily-market-snapshot")
    if snapshot["as_of_date"] != as_of_date:
        raise ValueError("snapshot as_of_date mismatch")
    started = utc_now()
    prior_ledger = None
    prior_path = output_dir / "trend-ledger.json"
    if prior_path.exists():
        try:
            prior_ledger = load_validated_trend_json(prior_path, "trend-ledger")
        except Exception:
            prior_ledger = None
    ledger = build_trend_ledger(snapshot, prior_ledger=prior_ledger, run_id=run_id)
    gate_findings = apply_strategy_gates(ledger, market_regime=market_regime)  # mutates readiness in place (§12)
    ledger_path = atomic_write_json(output_dir / "trend-ledger.json", ledger)
    ledger_md_path = (output_dir / "trend-ledger.md")
    from trend_contracts import atomic_write_text

    atomic_write_text(ledger_md_path, render_ledger_md(ledger))
    issues = validate_trend_ledger_records(ledger)
    findings = findings_artifact(as_of_date=as_of_date, issues=issues,
                                 source_artifact="trend-ledger", extra=gate_findings)
    findings_path = atomic_write_json(output_dir / "validation-findings.json", findings)
    patches = build_critic_patches(findings)
    patches_path = atomic_write_json(output_dir / "critic-patches.json", patches)
    finished = utc_now()
    if issues:
        errors = issue_dicts(issues)
        update_phase_status(
            output_dir,
            as_of_date=as_of_date,
            run_id=run_id,
            phase="ledger",
            status="nonconverged",
            started_at=started,
            finished_at=finished,
            input_artifacts=[snapshot_path.name],
            output_artifacts=[ledger_path.name, findings_path.name, patches_path.name],
            errors=errors,
        )
        status_path = output_dir / "run-status.json"
        paths = [ledger_path, ledger_md_path, findings_path, patches_path, status_path]
        copy_to_run_history(output_dir, as_of_date, run_id, paths)
        return 1, paths

    update_phase_status(
        output_dir,
        as_of_date=as_of_date,
        run_id=run_id,
        phase="ledger",
        status="completed",
        started_at=started,
        finished_at=finished,
        input_artifacts=[snapshot_path.name],
        output_artifacts=[ledger_path.name, ledger_md_path.name, findings_path.name, patches_path.name],
    )
    status_path = output_dir / "run-status.json"
    paths = [ledger_path, ledger_md_path, findings_path, patches_path, status_path]
    copy_to_run_history(output_dir, as_of_date, run_id, paths)
    return 0, paths


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run V2 trend ledger phase")
    parser.add_argument("--as-of", required=True, dest="as_of_date")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--with-regime", action="store_true",
                        help="fetch live market regime for the risk-off gate (network)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        market_regime = None
        if args.with_regime:
            import trend_sources
            market_regime = trend_sources.get_market_regime()
        code, paths = run_ledger_phase(args.as_of_date, args.snapshot, args.output_dir,
                                       market_regime=market_regime)
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

