#!/usr/bin/env python3
"""Validate V2 trend-monitoring artifacts without mutating them."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from trend_contracts import (
    GATE_MIN_AVG_VOLUME,
    GATE_MIN_LADDER_LEVELS,
    GATE_PRICE_MAX,
    GATE_PRICE_MIN,
    GATE_SECTOR_CONCENTRATION_MAX,
    SCHEMA_VERSION,
    TrendValidationIssue,
    atomic_write_json,
    issue_dicts,
    load_json,
    source_ref,
    utc_now,
    validate_artifact,
)

_DEFENSIVE_SECTORS = {"Cons Defensive", "Utilities", "Healthcare"}


def _gate_finding(seq, rec, message, *, blocks, severity="error",
                  category="STRATEGY_GATE_CONFLICT", field_path="/metrics", repairable=False):
    return {
        "id": f"VF-{seq}",
        "record_id": rec.get("id"),
        "ticker": rec.get("ticker"),
        "finding_category": category,
        "severity": severity,
        "field_path": field_path,
        "message": message,
        "source_refs": rec.get("source_refs", []),
        "repairable": repairable,
        "blocks_readiness": blocks,
        # legacy fields kept so validate_validation_findings still passes
        "artifact": "trend-ledger",
        "path": field_path,
    }


def _has_stale_support(rec):
    for r in rec.get("source_refs", []) or []:
        if r.get("artifact") == "support_eval" and r.get("freshness") in ("stale", "weekly_context"):
            return True
    return False


def apply_strategy_gates(ledger: dict[str, Any], *, market_regime: str | None = None) -> list[dict[str, Any]]:
    """Evaluate strategy gates (brief §12) + cache-window (§5.13); mutate readiness in place.

    Hard gates -> readiness=blocked; soft gates -> downgrade accepted to monitor_only and
    demote P1->P2; overlap -> human_action_required. Returns finding dicts.
    """
    records = ledger.get("records", []) if isinstance(ledger.get("records"), list) else []
    findings: list[dict[str, Any]] = []
    seq = 0
    # Concentration: count high-priority records per (broad) sector.
    sector_hi: dict[Any, int] = {}
    for r in records:
        if r.get("priority_tier") in ("P1", "P2"):
            m = r.get("metrics") or {}
            s = m.get("broad_sector") or m.get("sector")
            sector_hi[s] = sector_hi.get(s, 0) + 1

    for rec in records:
        m = rec.get("metrics") or {}
        blocked = False
        downgrade = False
        if m.get("earnings_blocked"):
            seq += 1
            findings.append(_gate_finding(seq, rec, "earnings blackout", blocks=True))
            blocked = True
        av = m.get("avg_volume")
        if isinstance(av, (int, float)) and av < GATE_MIN_AVG_VOLUME:
            seq += 1
            findings.append(_gate_finding(seq, rec, f"avg_volume {av} below {GATE_MIN_AVG_VOLUME}", blocks=True))
            blocked = True
        price = m.get("price")
        if isinstance(price, (int, float)) and (price < GATE_PRICE_MIN or price > GATE_PRICE_MAX):
            seq += 1
            findings.append(_gate_finding(seq, rec, f"price {price} outside ${GATE_PRICE_MIN}-${GATE_PRICE_MAX}", blocks=True))
            blocked = True
        levels = m.get("active_zone_levels")
        if rec.get("trend_category") == "SUPPORT_RETEST" and isinstance(levels, (int, float)) and levels < GATE_MIN_LADDER_LEVELS:
            seq += 1
            findings.append(_gate_finding(seq, rec, "insufficient support ladder depth", blocks=True))
            blocked = True
        if _has_stale_support(rec):
            seq += 1
            findings.append(_gate_finding(seq, rec, "support evidence outside freshness window",
                                          blocks=False, category="STALE_SOURCE_ARTIFACT",
                                          field_path="/source_refs"))
            downgrade = True
        sector = m.get("broad_sector") or m.get("sector")
        if market_regime == "Risk-Off" and sector not in _DEFENSIVE_SECTORS:
            seq += 1
            findings.append(_gate_finding(seq, rec, "risk-off regime, non-defensive sector",
                                          blocks=False, severity="warning"))
            downgrade = True
        if rec.get("priority_tier") in ("P1", "P2") and sector_hi.get(sector, 0) > GATE_SECTOR_CONCENTRATION_MAX:
            seq += 1
            findings.append(_gate_finding(seq, rec,
                                          f"sector concentration {sector_hi.get(sector)} > {GATE_SECTOR_CONCENTRATION_MAX}",
                                          blocks=False, severity="warning"))
            downgrade = True
        if m.get("portfolio_overlap"):
            rec["human_action_required"] = True
        if blocked:
            rec["readiness"] = "blocked"
            rec["trend_status"] = "blocked"
        elif downgrade:
            if rec.get("readiness") == "accepted":
                rec["readiness"] = "monitor_only"
            if rec.get("priority_tier") == "P1":
                rec["priority_tier"] = "P2"
    return findings


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
    extra: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    findings = [
        {
            **issue.__dict__,
            "finding_category": "UNSUPPORTED_SOURCE_CLAIM",
            "blocks_readiness": issue.severity == "ERROR",
            "source_refs": [
                source_ref(
                    artifact=source_artifact,
                    json_pointer=issue.path or "/",
                    value=issue.message,
                    as_of_date=as_of_date,
                    freshness="same_day",
                    claim_field=issue.path or "/",
                )
            ],
        }
        for issue in issues
    ]
    if extra:
        findings.extend(extra)
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "validation-findings",
        "as_of_date": as_of_date,
        "generated_at": utc_now(),
        "findings": findings,
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

