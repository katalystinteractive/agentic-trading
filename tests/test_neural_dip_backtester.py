from types import SimpleNamespace

import pandas as pd

import neural_dip_backtester as ndb
import neural_dip_evaluator as nde


def _day_bars():
    index = pd.date_range("2026-04-25 13:30", periods=24, freq="5min", tz="UTC")
    return pd.DataFrame({
        "Open": [100.0] * len(index),
        "High": [101.0] * 18 + [105.0] * 6,
        "Low": [99.0] * len(index),
        "Close": [100.0] * len(index),
    }, index=index)


def _parity_day_bars():
    index = pd.date_range("2026-04-25 13:30", periods=24, freq="5min", tz="UTC")
    close = [95.0] * 12 + [96.0, 96.2, 96.4, 96.6, 96.8, 97.0] + [101.0] * 6
    return pd.DataFrame({
        "Open": [100.0] * len(index),
        "High": [100.0] * 18 + [105.0] * 6,
        "Low": [95.0] * 18 + [96.0] * 6,
        "Close": close,
    }, index=index)


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


def _patch_first_hour(monkeypatch, fh_state):
    monkeypatch.setattr(
        ndb,
        "build_first_hour_graph",
        lambda *_args, **_kwargs: (None, fh_state),
    )


def _patch_confirmed_buy(monkeypatch):
    graph = SimpleNamespace(nodes={
        "AAA:buy_dip": SimpleNamespace(is_report=True, value=True),
    })
    top = [{
        "ticker": "AAA",
        "entry": 100.0,
        "target": 104.0,
        "stop": 97.0,
    }]

    monkeypatch.setattr(
        ndb,
        "build_decision_graph",
        lambda *_args, **_kwargs: (graph, top, 100),
    )


def test_replay_day_uses_current_breadth_dip_gate_key(monkeypatch):
    _patch_first_hour(monkeypatch, {"breadth_dip_gate": True})
    _patch_confirmed_buy(monkeypatch)

    result = ndb.replay_day(
        "2026-04-25", _day_bars(), ["AAA"], {}, {}, "Neutral", 1)

    assert result["signal"] == "CONFIRMED"
    assert result["buys"] == [{
        "ticker": "AAA",
        "entry": 100.0,
        "pnl": 4.0,
        "pnl_pct": 4.0,
        "exit_reason": "TARGET",
    }]


def test_replay_day_does_not_accept_legacy_breadth_dip_key(monkeypatch):
    _patch_first_hour(monkeypatch, {"breadth_dip": True})

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("decision graph should not run without breadth_dip_gate")

    monkeypatch.setattr(ndb, "build_decision_graph", fail_if_called)

    result = ndb.replay_day(
        "2026-04-25", _day_bars(), ["AAA"], {}, {}, "Neutral", 1)

    assert result == {"day": "2026-04-25", "signal": "NO_DIP", "buys": []}


def test_replay_day_matches_live_graph_builders_on_same_synthetic_state(monkeypatch):
    monkeypatch.setattr(nde, "_count_pdt_trades", lambda: 0)
    monkeypatch.setattr(nde, "_get_dip_capital", lambda: 500)
    day_bars = _parity_day_bars()
    tickers = ["AAA"]
    static = _static_context()
    hist_ranges = _historical_ranges()

    _fh_graph, fh_state = nde.build_first_hour_graph(
        tickers, day_bars.iloc[:12], static, hist_ranges, "Neutral", {}, {})
    decision_graph, _top, _budget = nde.build_decision_graph(
        tickers, day_bars.iloc[:18], fh_state, static, hist_ranges,
        "Neutral", {}, {})
    decision_graph.propagate_signals()
    live_buy_tickers = [
        name.split(":")[0]
        for name, node in decision_graph.get_activated_reports()
        if name.endswith(":buy_dip") and node.value
    ]

    replay = ndb.replay_day(
        "2026-04-25", day_bars, tickers, static, hist_ranges, "Neutral", 1,
        profiles={}, weights={})

    assert live_buy_tickers == ["AAA"]
    assert replay["signal"] == "CONFIRMED"
    assert [buy["ticker"] for buy in replay["buys"]] == live_buy_tickers
