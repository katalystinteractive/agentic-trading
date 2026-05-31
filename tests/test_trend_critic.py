from trend_critic import build_critic_patches
from trend_contracts import validate_critic_patches


def test_critic_patches_are_recommendation_only():
    findings = {
        "as_of_date": "2026-05-31",
        "findings": [{
            "id": "VF-1",
            "finding_category": "UNSUPPORTED_SOURCE_CLAIM",
            "artifact": "trend-ledger",
            "path": "/records/0/source_refs",
            "message": "must include at least one source ref",
            "severity": "error",
            "record_id": "TRD-1",
            "source_refs": [],
        }],
    }

    patches = build_critic_patches(findings)

    assert patches["artifact_type"] == "critic-patches"
    assert patches["patches"][0]["write_effect"] == "none"
    assert patches["patches"][0]["operation"] == "mark_needs_data"
    assert patches["patches"][0]["finding_id"] == "VF-1"
    assert "unrepaired_findings" in patches
    # the artifact is schema-valid
    assert validate_critic_patches(patches) == []


def test_unmappable_finding_goes_to_unrepaired():
    findings = {"as_of_date": "2026-05-31", "findings": [
        {"id": "VF-9", "finding_category": "MISSING_REQUIRED_TREND", "message": "x",
         "artifact": "trend-ledger", "path": "/metrics", "source_refs": []},
    ]}
    patches = build_critic_patches(findings)
    assert patches["patches"] == []
    assert patches["unrepaired_findings"][0]["finding_id"] == "VF-9"
