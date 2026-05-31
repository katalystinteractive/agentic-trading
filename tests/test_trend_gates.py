"""M5 — strategy gates (§12), cache-window (§5.13), critic operations (§5.7)."""
from trend_validator import apply_strategy_gates
from trend_critic import build_critic_patches
from trend_contracts import validate_critic_patches


def _rec(ticker="ALFA", **m):
    base = {"price": 24.5, "avg_volume": 1_800_000, "sector": "Tech", "broad_sector": "Technology"}
    base.update(m)
    return {"ticker": ticker, "id": f"TRD-{ticker}", "trend_category": "SUPPORT_RETEST",
            "readiness": "accepted", "priority_tier": "P1", "trend_status": "new",
            "metrics": base, "source_refs": []}


def _ledger(records):
    return {"as_of_date": "2026-05-31", "records": records}


def test_hard_gate_earnings_blocks():
    rec = _rec(earnings_blocked=True)
    findings = apply_strategy_gates(_ledger([rec]))
    assert rec["readiness"] == "blocked"
    assert rec["trend_status"] == "blocked"
    f = findings[0]
    assert f["finding_category"] == "STRATEGY_GATE_CONFLICT"
    assert f["blocks_readiness"] is True


def test_hard_gate_low_liquidity_and_price_band():
    low = _rec("LOWV", avg_volume=100_000)
    apply_strategy_gates(_ledger([low]))
    assert low["readiness"] == "blocked"
    pricey = _rec("HIGHP", price=120.0)
    apply_strategy_gates(_ledger([pricey]))
    assert pricey["readiness"] == "blocked"


def test_soft_riskoff_downgrades_accepted():
    rec = _rec()
    findings = apply_strategy_gates(_ledger([rec]), market_regime="Risk-Off")
    assert rec["readiness"] == "monitor_only"     # downgraded, not blocked
    assert rec["priority_tier"] == "P2"           # P1 demoted
    assert any(f["severity"] == "warning" for f in findings)


def test_cache_window_stale_support_downgrades():
    rec = _rec()
    rec["source_refs"] = [{"artifact": "support_eval", "json_pointer": "/0", "freshness": "stale"}]
    findings = apply_strategy_gates(_ledger([rec]))
    assert rec["readiness"] == "monitor_only"
    assert any(f["finding_category"] == "STALE_SOURCE_ARTIFACT" for f in findings)


def test_overlap_sets_human_action_required():
    rec = _rec(portfolio_overlap=True)
    apply_strategy_gates(_ledger([rec]))
    assert rec["human_action_required"] is True


def test_critic_maps_to_locked_operations_and_validates():
    findings = {
        "schema_version": 1, "artifact_type": "validation-findings", "as_of_date": "2026-05-31",
        "findings": [
            {"id": "VF-1", "finding_category": "STRATEGY_GATE_CONFLICT", "message": "earnings",
             "record_id": "TRD-1", "artifact": "trend-ledger", "path": "/metrics", "source_refs": []},
            {"id": "VF-2", "finding_category": "DUPLICATE_OR_FRAGMENTED_TREND", "message": "dup",
             "record_id": "TRD-2", "artifact": "trend-ledger", "path": "/metrics", "source_refs": []},
            {"id": "VF-3", "finding_category": "MISSING_REQUIRED_TREND", "message": "missing",
             "record_id": "TRD-3", "artifact": "trend-ledger", "path": "/metrics", "source_refs": []},
        ],
    }
    patches = build_critic_patches(findings)
    ops = {p["finding_id"]: p["operation"] for p in patches["patches"]}
    assert ops["VF-1"] == "append_blocked_reason"
    assert ops["VF-2"] == "merge_duplicate"
    assert {u["finding_id"] for u in patches["unrepaired_findings"]} == {"VF-3"}
    assert validate_critic_patches(patches) == []
