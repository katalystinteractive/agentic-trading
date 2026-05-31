from trend_critic import build_critic_patches


def test_critic_patches_are_recommendation_only():
    findings = {
        "as_of_date": "2026-05-31",
        "findings": [{
            "artifact": "trend-ledger",
            "path": "/records/0/source_refs",
            "message": "must include at least one source ref",
            "severity": "ERROR",
            "source_refs": [],
        }],
    }

    patches = build_critic_patches(findings)

    assert patches["artifact_type"] == "critic-patches"
    assert patches["patches"][0]["write_effect"] == "none"
    assert patches["patches"][0]["action"] == "reject_record_until_source_ref_added"

