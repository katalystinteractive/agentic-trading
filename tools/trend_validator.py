#!/usr/bin/env python3
"""Validate V2 trend-monitoring artifacts without mutating them."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from trend_contracts import (
    SCHEMA_VERSION,
    TrendValidationIssue,
    atomic_write_json,
    issue_dicts,
    load_json,
    source_ref,
    utc_now,
    validate_artifact,
)


def validate_trend_ledger_records(ledger: dict[str, Any]) -> list[TrendValidationIssue]:
    issues = validate_artifact(ledger, "trend-ledger")
    for idx, record in enumerate(ledger.get("records", []) if isinstance(ledger.get("records"), list) else []):
        if not isinstance(record, dict):
            continue
        metrics = record.get("metrics")
        if not isinstance(metrics, dict):
            continue
        score = metrics.get("recent_edge_score")
        inputs = metrics.get("recent_edge_score_inputs")
        if score is not None and isinstance(inputs, list):
            for input_idx, item in enumerate(inputs):
                if not isinstance(item, dict):
                    issues.append(TrendValidationIssue(
                        "trend-ledger",
                        f"/records/{idx}/metrics/recent_edge_score_inputs/{input_idx}",
                        "score input must be an object",
                    ))
                    continue
                for field in ["component", "source_field", "raw_value", "normalized_value", "weight", "missing"]:
                    if field not in item:
                        issues.append(TrendValidationIssue(
                            "trend-ledger",
                            f"/records/{idx}/metrics/recent_edge_score_inputs/{input_idx}/{field}",
                            "missing required score input field",
                        ))
                normalized = item.get("normalized_value")
                if normalized is not None and (
                    not isinstance(normalized, (int, float))
                    or isinstance(normalized, bool)
                    or normalized < 0
                    or normalized > 100
                ):
                    issues.append(TrendValidationIssue(
                        "trend-ledger",
                        f"/records/{idx}/metrics/recent_edge_score_inputs/{input_idx}/normalized_value",
                        "must be null or 0..100",
                    ))
    return issues


def findings_artifact(
    *,
    as_of_date: str,
    issues: list[TrendValidationIssue],
    source_artifact: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "validation-findings",
        "as_of_date": as_of_date,
        "generated_at": utc_now(),
        "findings": [
            {
                **issue.__dict__,
                "source_refs": [
                    source_ref(
                        artifact=source_artifact,
                        json_pointer=issue.path or "/",
                        value=issue.message,
                        as_of_date=as_of_date,
                        freshness="fresh",
                        claim_field="validation_issue",
                    )
                ],
            }
            for issue in issues
        ],
    }


def write_findings(
    *,
    ledger: dict[str, Any],
    issues: list[TrendValidationIssue],
    output_dir: Path,
) -> Path:
    path = output_dir / "validation-findings.json"
    return atomic_write_json(path, findings_artifact(
        as_of_date=ledger["as_of_date"],
        issues=issues,
        source_artifact="trend-ledger",
    ))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a V2 trend ledger")
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        ledger = load_json(args.ledger)
        issues = validate_trend_ledger_records(ledger)
        write_findings(ledger=ledger, issues=issues, output_dir=args.output_dir)
        print(f"Validation findings: {len(issues)}")
        return 1 if issues else 0
    except Exception as exc:
        print(f"trend validation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

