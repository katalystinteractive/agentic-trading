#!/usr/bin/env python3
"""Produce deterministic critic patches for V2 trend validation findings."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from trend_contracts import SCHEMA_VERSION, atomic_write_json, load_json, utc_now


def _operation_for(finding: dict[str, Any]) -> str | None:
    """Map a finding to a locked critic operation (spec §1315), or None if unrepairable."""
    category = finding.get("finding_category", "")
    path = str(finding.get("path", finding.get("field_path", "")))
    if category == "DUPLICATE_OR_FRAGMENTED_TREND":
        return "merge_duplicate"
    if category == "STRATEGY_GATE_CONFLICT":
        return "append_blocked_reason"
    if category == "STALE_SOURCE_ARTIFACT":
        return "downgrade_readiness"
    if category in ("DATA_PROVIDER_GAP", "INSUFFICIENT_RECENT_EDGE", "UNSUPPORTED_SOURCE_CLAIM"):
        return "mark_needs_data"
    if "recent_edge_score_inputs" in path:
        return "replace"
    return None


def build_critic_patches(findings: dict[str, Any]) -> dict[str, Any]:
    patches = []
    unrepaired: list[dict[str, Any]] = []
    for idx, finding in enumerate(findings.get("findings", [])):
        if not isinstance(finding, dict):
            continue
        finding_id = finding.get("id") or f"VF-{idx + 1}"
        operation = _operation_for(finding)
        if operation is None:
            unrepaired.append({"finding_id": finding_id, "reason": "no deterministic remediation"})
            continue
        patches.append({
            "id": f"patch-{idx + 1}",
            "finding_id": finding_id,
            "record_id": finding.get("record_id"),
            "artifact": finding.get("artifact"),
            "path": str(finding.get("path", finding.get("field_path", ""))),
            "operation": operation,
            "write_effect": "none",
            "applied": False,
            "rationale": str(finding.get("message", "")),
            "source_refs": finding.get("source_refs", []),
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "critic-patches",
        "as_of_date": findings.get("as_of_date"),
        "generated_at": utc_now(),
        "patches": patches,
        "unrepaired_findings": unrepaired,
    }


def write_critic_patches(findings: dict[str, Any], output_dir: Path) -> Path:
    return atomic_write_json(output_dir / "critic-patches.json", build_critic_patches(findings))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build V2 critic patches")
    parser.add_argument("--findings", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        findings = load_json(args.findings)
        patches = build_critic_patches(findings)
        write_critic_patches(findings, args.output_dir)
        print(f"Critic patches: {len(patches['patches'])}")
        return 0
    except Exception as exc:
        print(f"trend critic failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

