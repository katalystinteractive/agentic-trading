import json
from datetime import date

import artifact_promoter as promoter


def _meta(source, execution_mode):
    return {
        "schema_version": 1,
        "source": source,
        "execution_mode": execution_mode,
        "updated": date.today().isoformat(),
    }


def _write_sweep(path, ticker, score, trades=5):
    path.write_text(json.dumps({
        "_meta": {
            **_meta("parameter_sweeper.py", "intraday_5min_neural_replay"),
            "tickers_swept": 1,
        },
        ticker: {
            "params": {"dip_threshold": 1.0},
            "stats": {
                "trades": trades,
                "edge_adjusted_composite": score,
                "composite": score,
            },
            "features": {"trade_count": trades},
            "trades": [],
        },
    }))


def test_promotes_candidate_that_beats_incumbent(tmp_path, monkeypatch):
    monkeypatch.setattr(promoter, "REPORTS_DIR", tmp_path / "reports")
    live = tmp_path / "sweep_results.json"
    incumbent = tmp_path / "incumbent" / "sweep_results.json"
    candidate = tmp_path / "candidate" / "sweep_results.json"
    incumbent.parent.mkdir()
    candidate.parent.mkdir()
    _write_sweep(incumbent, "AAA", 10)
    _write_sweep(candidate, "AAA", 20)

    decision = promoter.promote_candidate(candidate, live, incumbent)

    assert decision.approved
    assert decision.decision == "promoted"
    assert json.loads(live.read_text())["AAA"]["stats"]["edge_adjusted_composite"] == 20


def test_rejects_candidate_below_incumbent_and_restores_live(tmp_path, monkeypatch):
    monkeypatch.setattr(promoter, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(promoter, "REJECTED_DIR", tmp_path / "rejected")
    live = tmp_path / "sweep_results.json"
    incumbent = tmp_path / "incumbent" / "sweep_results.json"
    incumbent.parent.mkdir()
    _write_sweep(incumbent, "AAA", 100)
    _write_sweep(live, "AAA", 10)

    decision = promoter.promote_candidate(live, live, incumbent, min_margin=0.02)

    assert not decision.approved
    assert decision.decision == "rejected"
    restored = json.loads(live.read_text())
    assert restored["AAA"]["stats"]["edge_adjusted_composite"] == 100
    assert list((tmp_path / "rejected").glob("*-sweep_results.json"))


def test_validation_failure_restores_incumbent(tmp_path, monkeypatch):
    monkeypatch.setattr(promoter, "REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(promoter, "REJECTED_DIR", tmp_path / "rejected")
    live = tmp_path / "sweep_results.json"
    incumbent = tmp_path / "incumbent" / "sweep_results.json"
    incumbent.parent.mkdir()
    _write_sweep(incumbent, "AAA", 100)
    live.write_text(json.dumps({"_meta": {"source": "wrong"}}))

    decision = promoter.promote_candidate(live, live, incumbent)

    assert not decision.approved
    assert "validation failed" in decision.reason
    assert json.loads(live.read_text())["AAA"]["stats"]["edge_adjusted_composite"] == 100


def test_snapshot_incumbent_copies_live_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(promoter, "INCUMBENT_DIR", tmp_path / "incumbents")
    live = tmp_path / "sweep_results.json"
    _write_sweep(live, "AAA", 10)

    snap = promoter.snapshot_incumbent(live, run_id="run-1")

    assert snap is not None
    assert snap.exists()
    assert json.loads(snap.read_text())["AAA"]["stats"]["edge_adjusted_composite"] == 10
