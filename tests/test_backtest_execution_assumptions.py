import pandas as pd

from backtest_config import SurgicalSimConfig
from backtest_engine import build_execution_stress_report, run_simulation


def _price_data_with_same_day_touch():
    dates = pd.bdate_range("2026-01-01", periods=68)
    open_ = [12.0] * len(dates)
    high = [12.2] * len(dates)
    low = [11.8] * len(dates)
    close = [12.0] * len(dates)
    volume = [1_000_000] * len(dates)

    # Sim day 1 places the order after fill checks.
    open_[-3], high[-3], low[-3], close[-3] = 12.0, 12.2, 11.7, 12.0
    # Sim day 2 touches both the buy limit and same-day target.
    open_[-2], high[-2], low[-2], close[-2] = 11.0, 11.0, 10.0, 10.5
    # Sim day 3 allows the conservative path to exit on the next bar.
    open_[-1], high[-1], low[-1], close[-1] = 10.7, 11.0, 10.3, 10.8

    return {
        "TEST": {
            "Open": pd.Series(open_, index=dates),
            "High": pd.Series(high, index=dates),
            "Low": pd.Series(low, index=dates),
            "Close": pd.Series(close, index=dates),
            "Volume": pd.Series(volume, index=dates),
        }
    }, dates


def _regime_data(dates):
    return {
        str(d.date()): {"regime": "Neutral", "vix": 18}
        for d in dates
    }


def _stub_wick(monkeypatch):
    import wick_offset_analyzer

    def fake_analyze_stock_data(*_args, **_kwargs):
        return {
            "bullet_plan": {
                "active": [{
                    "buy_at": 10.0,
                    "support_price": 10.0,
                    "shares": 10,
                    "effective_tier": "Full",
                    "decayed_hold_rate": 100,
                    "zone": "Active",
                }],
                "reserve": [],
            }
        }, None

    monkeypatch.setattr(wick_offset_analyzer, "analyze_stock_data", fake_analyze_stock_data)


def _cfg(dates, mode):
    return SurgicalSimConfig(
        tickers=["TEST"],
        start=str(dates[-3].date()),
        end=str(dates[-1].date()),
        recompute_levels="weekly",
        same_day_exit=True,
        same_day_exit_mode=mode,
        same_day_exit_pct=4.0,
        sell_default=4.0,
        min_hold_rate=15,
    )


def test_optimistic_mode_allows_same_day_exit_when_low_and_high_touch(monkeypatch):
    _stub_wick(monkeypatch)
    price_data, dates = _price_data_with_same_day_touch()

    trades, cycles, _equity, _dip = run_simulation(
        price_data, _regime_data(dates), _cfg(dates, "optimistic"), quiet=True)

    sells = [t for t in trades if t.get("side") == "SELL"]
    assert sells[0]["exit_reason"] == "SAME_DAY_EXIT"
    assert sells[0]["date"] == str(dates[-2].date())
    assert cycles[0]["duration_days"] == 0


def test_conservative_mode_disallows_same_day_exit_on_daily_bar(monkeypatch):
    _stub_wick(monkeypatch)
    price_data, dates = _price_data_with_same_day_touch()

    trades, cycles, _equity, _dip = run_simulation(
        price_data, _regime_data(dates), _cfg(dates, "conservative"), quiet=True)

    sells = [t for t in trades if t.get("side") == "SELL"]
    assert all(t["exit_reason"] != "SAME_DAY_EXIT" for t in sells)
    assert sells[0]["exit_reason"] == "PROFIT_TARGET"
    assert sells[0]["date"] == str(dates[-1].date())
    assert cycles[0]["duration_days"] > 0


def test_execution_costs_report_gross_net_and_fees(monkeypatch):
    _stub_wick(monkeypatch)
    price_data, dates = _price_data_with_same_day_touch()
    cfg = _cfg(dates, "optimistic")
    cfg.entry_spread_pct = 1.0
    cfg.exit_spread_pct = 1.0
    cfg.fee_per_trade = 1.0
    cfg.fee_per_share = 0.01

    trades, _cycles, _equity, _dip = run_simulation(
        price_data, _regime_data(dates), cfg, quiet=True)

    buy = next(t for t in trades if t.get("side") == "BUY")
    sell = next(t for t in trades if t.get("side") == "SELL")
    assert buy["fees"] == 1.1
    assert sell["fees"] == 2.2
    assert sell["gross_pnl_dollars"] > sell["pnl_dollars"]


def test_execution_stress_report_compares_same_day_modes(monkeypatch):
    _stub_wick(monkeypatch)
    price_data, dates = _price_data_with_same_day_touch()

    report = build_execution_stress_report(
        price_data, _regime_data(dates), _cfg(dates, "optimistic"))

    assert report["optimistic"]["same_day_exits"] == 1
    assert report["conservative"]["same_day_exits"] == 0
    assert report["no_same_day_exit"]["same_day_exits"] == 0
    assert report["conservative"]["avg_hold_days"] > report["optimistic"]["avg_hold_days"]
