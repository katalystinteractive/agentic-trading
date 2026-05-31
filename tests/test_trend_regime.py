"""Risk-off gate live-regime fetch (trend_sources.get_market_regime)."""
import pytest

import trend_sources as ts


def _raw(direction, vix):
    pd = pytest.importorskip("pandas")
    idx = pd.date_range("2026-01-01", periods=60, freq="D")

    def frame(start, step):
        closes = [start + step * i for i in range(60)]
        return pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                             "Close": closes, "Volume": [1] * 60}, index=idx)
    rising = ("SPY", "QQQ", "IWM")
    frames = {}
    for s in rising:
        frames[s] = frame(100.0, 1.0 if direction == "up" else -1.0)
    frames["^VIX"] = frame(vix, 0.0)
    return pd.concat(frames, axis=1)


def test_regime_risk_on():
    out = ts.get_market_regime(downloader=lambda t, **kw: _raw("up", 15.0))
    assert out == "Risk-On"


def test_regime_risk_off():
    out = ts.get_market_regime(downloader=lambda t, **kw: _raw("down", 30.0))
    assert out == "Risk-Off"


def test_regime_none_on_failure():
    def boom(t, **kw):
        raise RuntimeError("offline")
    assert ts.get_market_regime(downloader=boom) is None
