import json

import pandas as pd

import neural_dip_evaluator as nde


def _prices(latest_close=96.5):
    index = pd.date_range("2026-04-25 15:00", periods=3, freq="5min", tz="UTC")
    return pd.DataFrame({
        "Open": [96.0, 96.1, 96.2],
        "High": [96.2, 96.3, latest_close],
        "Low": [95.8, 95.9, 96.0],
        "Close": [96.0, 96.2, latest_close],
    }, index=index)


def _first_hour_state():
    return {
        "breadth_dip_gate": True,
        "AAA:first_hour_low": 95.0,
        "AAA:dip_pct": 5.0,
    }


def _static_context():
    return {
        "AAA": {
            "catastrophic": None,
            "verdict": ["MONITOR"],
            "earnings_gate": "CLEAR",
            "dip_viable": "YES",
        }
    }


def _historical_ranges():
    return {
        "AAA": {
            "range_pct": 4.0,
            "recovery_pct": 75,
            "viable": True,
        }
    }


def _patch_live_dependencies(monkeypatch, tmp_path, prices):
    cache_path = tmp_path / "neural_fh_cache.json"
    cache_path.write_text(json.dumps(_first_hour_state()))

    monkeypatch.setattr(nde, "FH_CACHE_PATH", cache_path)
    monkeypatch.setattr(nde, "fetch_intraday", lambda _tickers: prices)
    monkeypatch.setattr(nde, "_load_profiles", lambda: {})
    monkeypatch.setattr(nde, "_load_weights", lambda _regime: {})
    monkeypatch.setattr(nde, "_count_pdt_trades", lambda: 0)
    monkeypatch.setattr(nde, "_get_dip_capital", lambda: 500)


def test_evaluate_decision_propagates_signals_before_reading_reports(
        monkeypatch, tmp_path, capsys):
    _patch_live_dependencies(monkeypatch, tmp_path, _prices())

    nde.evaluate_decision(
        ["AAA"], _static_context(), _historical_ranges(), "Neutral",
        dry_run=True)

    out = capsys.readouterr().out
    assert "1 BUY signal(s)" in out
    assert "### AAA: BUY at $96.50" in out
    assert "No dip play today" not in out


def test_evaluate_decision_still_reports_no_buy_when_signal_not_confirmed(
        monkeypatch, tmp_path, capsys):
    _patch_live_dependencies(monkeypatch, tmp_path, _prices(latest_close=95.1))

    nde.evaluate_decision(
        ["AAA"], _static_context(), _historical_ranges(), "Neutral",
        dry_run=True)

    out = capsys.readouterr().out
    assert "No dip play today" in out
    assert "### AAA: BUY" not in out
