from types import SimpleNamespace

import pytest

import weekly_reoptimize as weekly


def test_step_sweep_continues_when_rejected_candidate_leaves_valid_live_artifact(
        monkeypatch, tmp_path):
    sweep_path = tmp_path / "sweep_results.json"
    sweep_path.write_text('{"_meta": {"source": "test"}}\n')
    promoted = []

    monkeypatch.setattr(weekly, "STRATEGY_TOOLS", {
        "dip": {
            "sweeper": "tools/parameter_sweeper.py",
            "sweeper_args": ["--split"],
            "clusterer": "tools/ticker_clusterer.py",
            "sweep_results": sweep_path,
        },
    })
    monkeypatch.setattr(weekly, "_snapshot_artifacts", lambda paths=None: None)
    monkeypatch.setattr(
        weekly.subprocess,
        "run",
        lambda cmd, cwd=None: SimpleNamespace(returncode=0),
    )

    def fake_promote(paths, min_margin=0.02, allow_stale=False):
        promoted.extend(paths)
        return [SimpleNamespace(approved=False, decision="rejected")]

    monkeypatch.setattr(weekly, "_promote_artifacts", fake_promote)
    monkeypatch.setattr(
        weekly,
        "load_validated_json",
        lambda path, allow_stale=False: {"restored": True},
    )

    ok, _elapsed = weekly.step_sweep(use_cached=True, strategy="dip")

    assert ok is True
    assert promoted == [sweep_path]


def test_step_sweep_fails_when_live_artifact_is_unavailable_after_promotion(
        monkeypatch, tmp_path):
    sweep_path = tmp_path / "sweep_results.json"
    sweep_path.write_text('{"_meta": {"source": "test"}}\n')

    monkeypatch.setattr(weekly, "STRATEGY_TOOLS", {
        "dip": {
            "sweeper": "tools/parameter_sweeper.py",
            "sweeper_args": ["--split"],
            "clusterer": "tools/ticker_clusterer.py",
            "sweep_results": sweep_path,
        },
    })
    monkeypatch.setattr(weekly, "_snapshot_artifacts", lambda paths=None: None)
    monkeypatch.setattr(
        weekly.subprocess,
        "run",
        lambda cmd, cwd=None: SimpleNamespace(returncode=0),
    )
    monkeypatch.setattr(
        weekly,
        "_promote_artifacts",
        lambda paths, min_margin=0.02, allow_stale=False: [
            SimpleNamespace(approved=False, decision="rejected"),
        ],
    )
    monkeypatch.setattr(
        weekly,
        "load_validated_json",
        lambda path, allow_stale=False: (_ for _ in ()).throw(ValueError("bad")),
    )

    ok, _elapsed = weekly.step_sweep(use_cached=True, strategy="dip")

    assert ok is False


def test_step_sweep_does_not_promote_failed_sweeper(monkeypatch, tmp_path):
    sweep_path = tmp_path / "sweep_results.json"
    sweep_path.write_text('{"_meta": {"source": "test"}}\n')

    monkeypatch.setattr(weekly, "STRATEGY_TOOLS", {
        "dip": {
            "sweeper": "tools/parameter_sweeper.py",
            "sweeper_args": ["--split"],
            "clusterer": "tools/ticker_clusterer.py",
            "sweep_results": sweep_path,
        },
    })
    monkeypatch.setattr(weekly, "_snapshot_artifacts", lambda paths=None: None)
    monkeypatch.setattr(
        weekly.subprocess,
        "run",
        lambda cmd, cwd=None: SimpleNamespace(returncode=1),
    )
    monkeypatch.setattr(
        weekly,
        "_promote_artifacts",
        lambda *args, **kwargs: pytest.fail("failed sweeper should not promote"),
    )

    ok, _elapsed = weekly.step_sweep(use_cached=True, strategy="dip")

    assert ok is False


def test_watchlist_sweep_continues_when_rejected_candidate_leaves_valid_live_artifact(
        monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    support_path = data_dir / "support_sweep_results.json"
    support_path.write_text('{"_meta": {"source": "test"}}\n')

    monkeypatch.setattr(weekly, "_ROOT", tmp_path)
    monkeypatch.setattr(weekly, "_snapshot_artifacts", lambda paths=None: None)
    monkeypatch.setattr(weekly, "_run_sweep_step", lambda step, name, cmd: (True, 1.0))
    monkeypatch.setattr(
        weekly,
        "_promote_artifacts",
        lambda paths, min_margin=0.02, allow_stale=False: [
            SimpleNamespace(approved=False, decision="rejected"),
        ],
    )
    monkeypatch.setattr(
        weekly,
        "load_validated_json",
        lambda path, allow_stale=False: {"restored": True},
    )

    ok, elapsed = weekly.step_watchlist_sweep()

    assert ok is True
    assert elapsed == 1.0
