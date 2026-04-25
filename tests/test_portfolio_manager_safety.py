import json
import sys
import types

import pytest

import portfolio_manager as pm
import prediction_ledger as pl


def _valid_portfolio():
    return {
        "last_updated": "2026-04-23",
        "positions": {
            "ABC": {
                "shares": 1,
                "avg_cost": 10.0,
                "bullets_used": 1,
                "entry_date": "2026-04-23",
                "target_exit": None,
                "fill_prices": [10.0],
                "note": "",
            }
        },
        "pending_orders": {
            "ABC": [
                {"type": "BUY", "price": 9.5, "shares": 1, "note": "A1", "placed": True}
            ]
        },
        "watchlist": ["ABC"],
    }


def _patch_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(pm, "PORTFOLIO_PATH", tmp_path / "portfolio.json")
    monkeypatch.setattr(pm, "TRADE_HISTORY_PATH", tmp_path / "trade_history.json")
    monkeypatch.setattr(pm, "LOCK_PATH", tmp_path / ".portfolio.lock")
    monkeypatch.setattr(pm, "TODAY", "2026-04-24")
    monkeypatch.setattr(pm, "_timestamp", lambda: "20260424_120000")
    pm._LOCK_DEPTH = 0


def test_save_uses_timestamped_backup_and_atomic_json(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    pm.PORTFOLIO_PATH.write_text(json.dumps(_valid_portfolio()))

    updated = _valid_portfolio()
    updated["positions"]["ABC"]["shares"] = 2

    pm._save(updated)

    saved = json.loads(pm.PORTFOLIO_PATH.read_text())
    assert saved["last_updated"] == "2026-04-24"
    assert saved["positions"]["ABC"]["shares"] == 2
    assert (tmp_path / "portfolio.json.bak.20260424_120000").exists()
    assert not list(tmp_path.glob(".portfolio.json.tmp.*"))


def test_save_rejects_invalid_portfolio_without_overwriting(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    original = _valid_portfolio()
    pm.PORTFOLIO_PATH.write_text(json.dumps(original))

    invalid = _valid_portfolio()
    invalid["pending_orders"]["ABC"][0]["type"] = "HOLD"

    with pytest.raises(pm.StateValidationError):
        pm._save(invalid)

    assert json.loads(pm.PORTFOLIO_PATH.read_text()) == original


def test_record_trade_recovers_corrupt_history(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    pm.TRADE_HISTORY_PATH.write_text("{not valid json")

    pm._record_trade({
        "ticker": "ABC",
        "side": "BUY",
        "date": "2026-04-24",
        "shares": 1,
        "price": 10.0,
    })

    history = json.loads(pm.TRADE_HISTORY_PATH.read_text())
    assert history["trades"][0]["id"] == 1
    assert history["trades"][0]["ticker"] == "ABC"
    assert (tmp_path / "trade_history.json.corrupt.20260424_120000").exists()


def test_load_validates_portfolio_shape(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    pm.PORTFOLIO_PATH.write_text(json.dumps({"positions": [], "pending_orders": {}, "watchlist": []}))

    with pytest.raises(pm.StateValidationError):
        pm._load()


def test_order_repairs_shell_expanded_high_price_note(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    data = {"positions": {}, "pending_orders": {}, "watchlist": []}
    args = types.SimpleNamespace(
        ticker="ABNB",
        type="BUY",
        price=131.39,
        shares=1,
        note="A1 — 29.23 HVN+PA, 21% hold, Std tier",
        placed=True,
    )

    pm.cmd_order(data, args)

    order = json.loads(pm.PORTFOLIO_PATH.read_text())["pending_orders"]["ABNB"][0]
    assert order["note"] == "A1 — $129.23 HVN+PA, 21% hold, Std tier"


def test_order_keeps_legitimate_low_price_note_for_low_price_order():
    note = "A1 — 29.23 HVN+PA, 21% hold, Std tier"

    assert pm._repair_shell_expanded_note_price(note, 31.00) == note


def _stub_post_trade_modules(monkeypatch):
    sell_targets = types.ModuleType("sell_target_calculator")
    sell_targets.analyze_ticker = lambda *args, **kwargs: None
    knowledge = types.ModuleType("knowledge_store")
    knowledge.store_fill = lambda *args, **kwargs: None
    knowledge.store_sell = lambda *args, **kwargs: None
    knowledge.store_partial_sell = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "sell_target_calculator", sell_targets)
    monkeypatch.setitem(sys.modules, "knowledge_store", knowledge)


def test_record_fill_loads_fresh_state_instead_of_using_stale_caller_data(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(pl, "LEDGER_PATH", tmp_path / "prediction_ledger.json")
    _stub_post_trade_modules(monkeypatch)
    pm.PORTFOLIO_PATH.write_text(json.dumps(_valid_portfolio()))
    pl.record_prediction(
        "support",
        "ABC",
        {"date": "2026-04-24", "support": 11.0},
    )

    stale = pm._load()
    assert stale["positions"]["ABC"]["shares"] == 1

    fresh = _valid_portfolio()
    fresh["positions"]["ABC"]["shares"] = 2
    fresh["positions"]["ABC"]["avg_cost"] = 10.0
    pm.PORTFOLIO_PATH.write_text(json.dumps(fresh))

    args = types.SimpleNamespace(ticker="ABC", price=11.0, shares=1, trade_date="2026-04-24")
    pm.record_fill(args)

    saved = json.loads(pm.PORTFOLIO_PATH.read_text())
    assert saved["positions"]["ABC"]["shares"] == 3
    assert saved["positions"]["ABC"]["avg_cost"] == 10.33
    ledger = pl.summarize_predictions()
    assert ledger["filled"] == 1


def test_record_sell_loads_fresh_state_instead_of_using_stale_caller_data(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(pl, "LEDGER_PATH", tmp_path / "prediction_ledger.json")
    _stub_post_trade_modules(monkeypatch)
    pl.record_prediction(
        "support",
        "ABC",
        {"date": "2026-04-24", "support": 10.0},
    )
    pl.link_fill("ABC", 10.0, 1, "2026-04-24")
    portfolio = _valid_portfolio()
    portfolio["positions"]["ABC"]["shares"] = 3
    portfolio["positions"]["ABC"]["avg_cost"] = 10.0
    pm.PORTFOLIO_PATH.write_text(json.dumps(portfolio))

    stale = pm._load()
    assert stale["positions"]["ABC"]["shares"] == 3

    fresh = _valid_portfolio()
    fresh["positions"]["ABC"]["shares"] = 4
    fresh["positions"]["ABC"]["avg_cost"] = 10.0
    pm.PORTFOLIO_PATH.write_text(json.dumps(fresh))

    args = types.SimpleNamespace(ticker="ABC", price=11.0, shares=1, trade_date="2026-04-24")
    pm.record_sell(args)

    saved = json.loads(pm.PORTFOLIO_PATH.read_text())
    assert saved["positions"]["ABC"]["shares"] == 3
    ledger = pl.summarize_predictions()
    assert ledger["closed"] == 1
