#!/usr/bin/env python3
"""Produce deterministic critic patches for V2 trend validation findings."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from trend_contracts import SCHEMA_VERSION, atomic_write_json, load_json, utc_now


def build_critic_patches(findings: dict[str, Any]) -> dict[str, Any]:
    patches = []
    for idx, finding in enumerate(findings.get("findings", [])):
        if not isinstance(finding, dict):
            continue
        path = str(finding.get("path", ""))
        message = str(finding.get("message", ""))
        if "source ref" in message or path.endswith("/source_refs"):
            action = "reject_record_until_source_ref_added"
        elif "recent_edge_score_inputs" in path:
            action = "recompute_recent_edge_score_inputs"
        else:
            action = "manual_review_required"
        patches.append({
            "id": f"patch-{idx + 1}",
            "artifact": finding.get("artifact"),
            "path": path,
            "action": action,
            "write_effect": "none",
            "rationale": message,
            "source_refs": finding.get("source_refs", []),
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "critic-patches",
        "as_of_date": findings.get("as_of_date"),
        "generated_at": utc_now(),
        "patches": patches,
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

