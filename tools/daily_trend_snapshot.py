#!/usr/bin/env python3
"""Build a deterministic daily market snapshot for V2 trend monitoring."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from trend_contracts import (
    SCHEMA_VERSION,
    atomic_write_json,
    atomic_write_text,
    build_run_status,
    copy_to_run_history,
    load_json,
    load_validated_trend_json,
    new_run_id,
    phase_entry,
    source_ref,
    status_from_output_dir,
    utc_now,
)


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DEFAULT_OUTPUT_DIR = DATA_DIR / "trend_monitoring"


LOCAL_SOURCE_FILES = {
    "universe_screen": DATA_DIR / "universe_screen_cache.json",
    "support_eval": DATA_DIR / "support_eval_latest.json",
    "watchlist_fitness": ROOT / "watchlist-fitness.json",
    "candidate_pool": DATA_DIR / "candidates.json",
}


def _load_fixture(fixture_dir: Path) -> dict[str, Any]:
    path = fixture_dir / "snapshot_sources.json"
    if not path.exists():
        raise FileNotFoundError(f"fixture file not found: {path}")
    data = load_json(path)
    if not isinstance(data, dict):
        raise ValueError("snapshot_sources.json root must be an object")
    return data


def _load_local_sources() -> dict[str, Any]:
    sources: dict[str, Any] = {}
    for name, path in LOCAL_SOURCE_FILES.items():
        if path.exists():
            try:
                sources[name] = load_json(path)
            except json.JSONDecodeError:
                sources[name] = {"_error": f"invalid JSON in {path}"}
    return sources


def _records_from_universe(source_name: str, source: dict[str, Any], as_of_date: str) -> list[dict[str, Any]]:
    passers = source.get("passers", [])
    if not isinstance(passers, list):
        return []
    generated = source.get("generated") or source.get("as_of_date") or as_of_date
    records: list[dict[str, Any]] = []
    for idx, item in enumerate(passers):
        if not isinstance(item, dict) or not item.get("ticker"):
            continue
        ticker = str(item["ticker"]).upper()
        metrics = {
            "price": item.get("price"),
            "avg_volume": item.get("avg_vol", item.get("avg_volume")),
            "median_swing": item.get("median_swing"),
            "consistency": item.get("consistency"),
            "freshness": item.get("freshness", "fresh"),
        }
        refs = [
            source_ref(
                artifact=source_name,
                json_pointer=f"/passers/{idx}",
                value=item,
                as_of_date=str(generated)[:10] if generated else as_of_date,
                freshness=str(metrics["freshness"]),
                claim_field="universe_pass",
            )
        ]
        records.append({"ticker": ticker, "metrics": metrics, "source_refs": refs})
    return records


def _merge_metric(
    records: dict[str, dict[str, Any]],
    ticker: str,
    *,
    artifact: str,
    pointer: str,
    value: dict[str, Any],
    as_of_date: str | None,
    field_map: dict[str, str],
) -> None:
    if ticker not in records:
        records[ticker] = {
            "ticker": ticker,
            "metrics": {},
            "source_refs": [],
        }
    rec = records[ticker]
    for source_field, target_field in field_map.items():
        if source_field in value:
            rec["metrics"][target_field] = value[source_field]
    rec["source_refs"].append(source_ref(
        artifact=artifact,
        json_pointer=pointer,
        value=value,
        as_of_date=as_of_date,
        freshness=str(value.get("freshness", "unknown")),
        claim_field=",".join(field_map.values()),
    ))


def build_snapshot(as_of_date: str, sources: dict[str, Any]) -> dict[str, Any]:
    records: dict[str, dict[str, Any]] = {}
    universe = sources.get("universe_screen")
    if isinstance(universe, dict):
        for record in _records_from_universe("universe_screen", universe, as_of_date):
            records[record["ticker"]] = record

    support = sources.get("support_eval")
    support_items = support.get("levels", []) if isinstance(support, dict) else []
    if isinstance(support_items, list):
        for idx, item in enumerate(support_items):
            if isinstance(item, dict) and item.get("ticker"):
                _merge_metric(
                    records,
                    str(item["ticker"]).upper(),
                    artifact="support_eval",
                    pointer=f"/levels/{idx}",
                    value=item,
                    as_of_date=item.get("as_of_date") or as_of_date,
                    field_map={"level": "support_level", "support_level": "support_level"},
                )

    watchlist = sources.get("watchlist_fitness")
    watch_items = watchlist.get("records", watchlist.get("tickers", [])) if isinstance(watchlist, dict) else []
    if isinstance(watch_items, list):
        for idx, item in enumerate(watch_items):
            if isinstance(item, dict) and item.get("ticker"):
                _merge_metric(
                    records,
                    str(item["ticker"]).upper(),
                    artifact="watchlist_fitness",
                    pointer=f"/records/{idx}",
                    value=item,
                    as_of_date=item.get("as_of_date") or as_of_date,
                    field_map={
                        "fitness_delta_pct": "watchlist_fitness_delta_pct",
                        "post_signal_return_pct": "post_signal_return_pct",
                    },
                )

    candidates = sources.get("candidate_pool")
    candidate_items = candidates.get("candidates", []) if isinstance(candidates, dict) else []
    if isinstance(candidate_items, list):
        for idx, item in enumerate(candidate_items):
            if isinstance(item, dict) and item.get("ticker"):
                _merge_metric(
                    records,
                    str(item["ticker"]).upper(),
                    artifact="candidate_pool",
                    pointer=f"/candidates/{idx}",
                    value=item,
                    as_of_date=item.get("added") or as_of_date,
                    field_map={"fitness_delta_pct": "candidate_fitness_delta_pct"},
                )

    simulation = sources.get("simulation_validation")
    sim_items = simulation.get("records", []) if isinstance(simulation, dict) else []
    if isinstance(sim_items, list):
        for idx, item in enumerate(sim_items):
            if isinstance(item, dict) and item.get("ticker"):
                _merge_metric(
                    records,
                    str(item["ticker"]).upper(),
                    artifact="simulation_validation",
                    pointer=f"/records/{idx}",
                    value=item,
                    as_of_date=item.get("as_of_date") or as_of_date,
                    field_map={"return_pct": "simulation_validation_return_pct"},
                )

    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "daily-market-snapshot",
        "as_of_date": as_of_date,
        "generated_at": utc_now(),
        "source_artifacts": sorted(sources.keys()),
        "records": sorted(records.values(), key=lambda item: item["ticker"]),
    }


def render_snapshot_md(snapshot: dict[str, Any]) -> str:
    lines = [
        f"# Daily Market Snapshot - {snapshot['as_of_date']}",
        "",
        "| Ticker | Price | Avg Volume | Source Refs |",
        "| :--- | ---: | ---: | ---: |",
    ]
    for record in snapshot.get("records", []):
        metrics = record.get("metrics", {})
        lines.append(
            f"| {record.get('ticker')} | {metrics.get('price', '')} | "
            f"{metrics.get('avg_volume', '')} | {len(record.get('source_refs', []))} |"
        )
    return "\n".join(lines) + "\n"


def write_snapshot_artifacts(snapshot: dict[str, Any], output_dir: Path, run_id: str) -> list[Path]:
    json_path = atomic_write_json(output_dir / "daily-market-snapshot.json", snapshot)
    md_path = atomic_write_text(output_dir / "daily-market-snapshot.md", render_snapshot_md(snapshot))
    now = utc_now()
    status = build_run_status(
        as_of_date=snapshot["as_of_date"],
        run_id=run_id,
        run_status="running",
        generated_at=now,
        phase_statuses=[
            phase_entry(
                "snapshot",
                "completed",
                started_at=snapshot["generated_at"],
                finished_at=now,
                output_artifacts=[json_path.name, md_path.name],
            ),
            phase_entry("ledger", "running", started_at=now, finished_at=None, input_artifacts=[json_path.name]),
            phase_entry("actions", "skipped", started_at=None, finished_at=now),
            phase_entry("report", "skipped", started_at=None, finished_at=now),
        ],
    )
    status_path = atomic_write_json(output_dir / "run-status.json", status)
    copy_to_run_history(output_dir, snapshot["as_of_date"], run_id, [json_path, md_path, status_path])
    return [json_path, md_path, status_path]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build V2 daily trend snapshot")
    parser.add_argument("--as-of", required=True, dest="as_of_date")
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        output_dir = args.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        run_id, _ = status_from_output_dir(output_dir, args.as_of_date)
        if args.fixture:
            sources = _load_fixture(args.fixture)
        else:
            sources = _load_local_sources()
        snapshot = build_snapshot(args.as_of_date, sources)
        paths = write_snapshot_artifacts(snapshot, output_dir, run_id)
        load_validated_trend_json(output_dir / "daily-market-snapshot.json", "daily-market-snapshot")
        print(f"Wrote snapshot with {len(snapshot['records'])} records to {paths[0]}")
        return 0
    except (argparse.ArgumentError, FileNotFoundError, ValueError) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"snapshot failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

