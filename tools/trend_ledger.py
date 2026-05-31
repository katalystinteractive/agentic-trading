#!/usr/bin/env python3
"""Build the deterministic trend ledger from a daily snapshot."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from trend_contracts import (
    ABSENT_AGE_OUT_DAYS,
    COOLDOWN_DAYS,
    SCHEMA_VERSION,
    atomic_write_json,
    atomic_write_text,
    build_run_id,
    copy_to_run_history,
    load_validated_trend_json,
    new_run_id,
    short_hash,
    utc_now,
)
from trend_extractor import enrich_snapshot_record

_PRIO_RANK = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}


def _norm_anchor(value: Any) -> str:
    return str(value).lower().replace(" ", "")


def build_stable_key(rec: dict[str, Any], as_of_date: str) -> str:
    """Deterministic identity key (brief §6.7): ticker:category:anchor."""
    ticker = str(rec.get("ticker", "")).upper()
    cat = rec.get("trend_category", "DORMANT_OR_NO_ACTION")
    m = rec.get("metrics", {}) if isinstance(rec.get("metrics"), dict) else {}
    if cat in ("SUPPORT_RETEST", "MEAN_REVERSION_PULLBACK"):
        sl = m.get("support_level") if isinstance(m.get("support_level"), dict) else {}
        lvl = sl.get("support", sl.get("buy_at")) if sl else None
        anchor = f"support_{float(lvl):.2f}" if lvl is not None else "support_na"
    elif cat in ("VOLATILITY_EXPANSION", "BREAKOUT_ACCELERATION"):
        band = m.get("atr_pct")
        anchor = f"range_{float(band):.2f}" if band is not None else "range_na"
    elif cat == "RELATIVE_STRENGTH_ROTATION":
        anchor = f"sector_{_norm_anchor(m.get('sector') or 'na')}"
    elif cat == "EVENT_DRIVEN_SETUP":
        anchor = f"event_{as_of_date}"
    else:
        anchor = "dormant"
    return f"{ticker}:{cat}:{anchor}"


def _transition(rec: dict[str, Any], prior: dict[str, Any] | None) -> str:
    if rec.get("readiness") == "blocked":
        return "blocked"
    if rec.get("source_quality") == "stale":
        return "stale"
    if prior is None:
        return "new"
    pr = _PRIO_RANK.get(prior.get("priority_tier", "P4"), 3)
    cur = _PRIO_RANK.get(rec.get("priority_tier", "P4"), 3)
    if cur < pr:
        return "upgraded"
    if cur > pr:
        return "downgraded"
    return "persisting"


def _merge_duplicate(keep: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    """Keep the higher recent_edge_score, union source_refs (brief §5.14/§11.8)."""
    ks = keep.get("metrics", {}).get("recent_edge_score")
    os_ = other.get("metrics", {}).get("recent_edge_score")
    winner, loser = (keep, other) if (ks or -1) >= (os_ or -1) else (other, keep)
    refs = list(winner.get("source_refs") or [])
    seen = {(r.get("artifact"), r.get("json_pointer")) for r in refs}
    for r in loser.get("source_refs") or []:
        if (r.get("artifact"), r.get("json_pointer")) not in seen:
            refs.append(r)
    winner["source_refs"] = refs
    return winner


def build_trend_ledger(
    snapshot: dict[str, Any],
    *,
    prior_ledger: dict[str, Any] | None = None,
    run_id: str | None = None,
    now=None,
) -> dict[str, Any]:
    as_of = snapshot["as_of_date"]
    enriched = [enrich_snapshot_record(r) for r in snapshot.get("records", [])]

    # 1. stable_key + same-day duplicate merge.
    by_key: dict[str, dict[str, Any]] = {}
    duplicate_keys: list[str] = []
    for rec in enriched:
        key = build_stable_key(rec, as_of)
        rec["stable_key"] = key
        if key in by_key:
            by_key[key] = _merge_duplicate(by_key[key], rec)
            by_key[key]["stable_key"] = key
            duplicate_keys.append(key)
        else:
            by_key[key] = rec

    # 2. prior-ledger index for cross-run identity/transitions.
    prior_index: dict[str, dict[str, Any]] = {}
    prior_run_id = None
    if prior_ledger:
        prior_run_id = prior_ledger.get("run_id")
        for pr in prior_ledger.get("records", []):
            if isinstance(pr, dict) and pr.get("stable_key"):
                prior_index[pr["stable_key"]] = pr

    transitions: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for key, rec in sorted(by_key.items()):
        prior = prior_index.get(key)
        rec["id"] = (prior or {}).get("id") or f"TRD-{short_hash(key)[:6]}"
        rec["first_seen"] = (prior or {}).get("first_seen") or as_of
        rec["last_seen"] = as_of
        rec["last_updated"] = as_of
        status = _transition(rec, prior)
        stale_streak = ((prior or {}).get("stale_streak", 0) + 1) if status == "stale" else 0
        if stale_streak >= COOLDOWN_DAYS:
            status = "retired"
        rec["stale_streak"] = stale_streak
        rec["absent_streak"] = 0
        rec["trend_status"] = status
        rec.setdefault("patch_history", [])
        records.append(rec)
        transitions.append({"stable_key": key, "ticker": rec.get("ticker"), "transition": status})

    # 3. absent records (in prior, not in snapshot) -> stale -> retired -> dropped.
    for key, pr in sorted(prior_index.items()):
        if key in by_key or pr.get("trend_status") == "retired":
            continue
        absent_streak = pr.get("absent_streak", 0) + 1
        status = "retired" if absent_streak >= ABSENT_AGE_OUT_DAYS else "stale"
        carry = dict(pr)
        carry.update({"absent_streak": absent_streak, "last_updated": as_of, "trend_status": status})
        records.append(carry)
        transitions.append({"stable_key": key, "ticker": pr.get("ticker"), "transition": status})

    records.sort(key=lambda r: r.get("stable_key", ""))
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "trend-ledger",
        "as_of_date": as_of,
        "generated_at": utc_now(now),
        "run_id": run_id or build_run_id(as_of, snapshot, now=now),
        "prior_ledger_run_id": prior_run_id,
        "source_snapshot": "daily-market-snapshot.json",
        "records": records,
        "transitions": transitions,
        "summary": _ledger_summary(records, transitions, duplicate_keys),
    }


def _ledger_summary(records, transitions, duplicate_keys) -> dict[str, Any]:
    by_readiness: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_transition: dict[str, int] = {}
    for r in records:
        by_readiness[r.get("readiness", "unknown")] = by_readiness.get(r.get("readiness", "unknown"), 0) + 1
        by_category[r.get("trend_category", "unknown")] = by_category.get(r.get("trend_category", "unknown"), 0) + 1
    for t in transitions:
        by_transition[t["transition"]] = by_transition.get(t["transition"], 0) + 1
    return {
        "record_count": len(records),
        "by_readiness": by_readiness,
        "by_category": by_category,
        "by_transition": by_transition,
        "duplicate_merged_keys": sorted(set(duplicate_keys)),
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

