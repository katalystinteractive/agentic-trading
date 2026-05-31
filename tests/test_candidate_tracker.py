import json
import types

import candidate_tracker as ct


def _patch_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(ct, "_CANDIDATES", tmp_path / "candidates.json")
    monkeypatch.setattr(ct, "_UNIVERSE_CACHE", tmp_path / "universe_screen_cache.json")
    monkeypatch.setattr(ct, "_PORTFOLIO", tmp_path / "portfolio.json")
    ct._CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    ct._CANDIDATES.write_text(json.dumps({
        "candidates": [{"ticker": "DUP", "added": "2026-05-01"}],
        "last_updated": "before",
    }))
    ct._PORTFOLIO.write_text(json.dumps({
        "positions": {"POS": {}},
        "watchlist": ["WATCH"],
        "pending_orders": {"PEND": []},
    }))


def test_add_skips_duplicates_portfolio_watchlist_and_pending(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    args = types.SimpleNamespace(tickers=["DUP", "POS", "WATCH", "PEND", "NEW"], dry_run=False)

    ct.cmd_add(args)

    data = json.loads(ct._CANDIDATES.read_text())
    tickers = [item["ticker"] for item in data["candidates"]]
    assert tickers == ["DUP", "NEW"]


def test_add_dry_run_does_not_mutate_candidates(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    before = ct._CANDIDATES.read_text()
    args = types.SimpleNamespace(tickers=["NEW"], dry_run=True)

    ct.cmd_add(args)

    assert ct._CANDIDATES.read_text() == before


def test_import_screening_dry_run_does_not_mutate_candidates(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    ct._UNIVERSE_CACHE.write_text(json.dumps({
        "passers": [{"ticker": "IMP", "median_swing": 11.0, "price": 10.0}]
    }))
    before = ct._CANDIDATES.read_text()

    ct.cmd_import_screening(types.SimpleNamespace(dry_run=True))

    assert ct._CANDIDATES.read_text() == before


def test_age_out_dry_run_does_not_mutate_candidates(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    ct._CANDIDATES.write_text(json.dumps({
        "candidates": [{"ticker": "OLD", "added": "2000-01-01"}],
        "last_updated": "before",
    }))
    before = ct._CANDIDATES.read_text()

    ct.cmd_age_out(types.SimpleNamespace(dry_run=True))

    assert ct._CANDIDATES.read_text() == before
