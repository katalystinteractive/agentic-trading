#!/usr/bin/env python3
"""Build the deterministic trend ledger from a daily snapshot."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from trend_contracts import (
    SCHEMA_VERSION,
    atomic_write_json,
    atomic_write_text,
    copy_to_run_history,
    load_validated_trend_json,
    new_run_id,
    utc_now,
)
from trend_extractor import enrich_snapshot_record


def build_trend_ledger(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "trend-ledger",
        "as_of_date": snapshot["as_of_date"],
        "generated_at": utc_now(),
        "source_snapshot": "daily-market-snapshot.json",
        "records": [enrich_snapshot_record(record) for record in snapshot.get("records", [])],
    }


def render_ledger_md(ledger: dict[str, Any]) -> str:
    lines = [
        f"# Trend Ledger - {ledger['as_of_date']}",
        "",
        "| Ticker | State | Recent Edge | Evidence |",
        "| :--- | :--- | ---: | ---: |",
    ]
    for record in ledger.get("records", []):
        metrics = record.get("metrics", {})
        score = metrics.get("recent_edge_score")
        score_text = "" if score is None else str(score)
        lines.append(
            f"| {record.get('ticker')} | {record.get('trend_state')} | "
            f"{score_text} | {len(record.get('source_refs', []))} |"
        )
    return "\n".join(lines) + "\n"


def write_ledger_artifacts(ledger: dict[str, Any], output_dir: Path, run_id: str) -> list[Path]:
    json_path = atomic_write_json(output_dir / "trend-ledger.json", ledger)
    md_path = atomic_write_text(output_dir / "trend-ledger.md", render_ledger_md(ledger))
    copy_to_run_history(output_dir, ledger["as_of_date"], run_id, [json_path, md_path])
    return [json_path, md_path]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build V2 trend ledger")
    parser.add_argument("--as-of", required=True, dest="as_of_date")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        snapshot = load_validated_trend_json(args.snapshot, "daily-market-snapshot")
        if snapshot["as_of_date"] != args.as_of_date:
            print("configuration error: snapshot as_of_date mismatch", file=sys.stderr)
            return 2
        ledger = build_trend_ledger(snapshot)
        paths = write_ledger_artifacts(ledger, args.output_dir, new_run_id())
        load_validated_trend_json(paths[0], "trend-ledger")
        print(f"Wrote trend ledger with {len(ledger['records'])} records to {paths[0]}")
        return 0
    except Exception as exc:
        print(f"trend ledger failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

