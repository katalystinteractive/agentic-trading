"""M1 — keyed snapshot, live-fetch sourcing, and the §5.8 support-bug regression."""
import json
from pathlib import Path

import pytest

from daily_trend_snapshot import build_snapshot
from trend_contracts import validate_artifact
from trend_extractor import compute_recent_edge_score

FIX = Path(__file__).resolve().parent / "fixtures" / "trend_monitoring" / "snapshot_sources_v2.json"


def _fake_ohlcv():
    pd = pytest.importorskip("pandas")
    idx = pd.date_range("2026-04-01", periods=40, freq="D")

    def frame(base):
        return pd.DataFrame(
            {
                "Open": [base] * 40,
                "High": [base * 1.03] * 40,
                "Low": [base * 0.97] * 40,
                "Close": [base * 0.99] + [base] * 39,
                "Volume": [1_000_000] * 40,
            },
            index=idx,
        )

    # ALFA + BETA have data; GAMMA is intentionally absent -> provider failure.
    raw = pd.concat({"ALFA": frame(24.5), "BETA": frame(11.25)}, axis=1)
    return lambda tickers, **kw: raw


@pytest.fixture
def offline(monkeypatch):
    import trend_sources as ts
    monkeypatch.setattr(ts, "get_sector", lambda t: {"sector": "Tech", "broad_sector": "Technology"})
    monkeypatch.setattr(ts, "get_earnings_status",
                        lambda t, d=None: {"earnings_status": "CLEAR", "earnings_blocked": False, "days_to_earnings": 40})
    monkeypatch.setattr(ts, "compute_overlaps",
                        lambda t: {"portfolio_overlap": False, "candidate_overlap": False, "watchlist_overlap": False})
    return ts


def _build(offline):
    sources = json.loads(FIX.read_text())
    return build_snapshot("2026-05-31", sources, downloader=_fake_ohlcv(), live=True)


def test_snapshot_is_keyed_by_ticker_and_validates(offline):
    snap = _build(offline)
    assert isinstance(snap["tickers"], dict)
    assert "ALFA" in snap["tickers"]
    assert validate_artifact(snap, "daily-market-snapshot") == []


def test_support_component_populated_from_opportunities(offline):
    # §5.8 regression: real shape uses `opportunities` + scalar `support`.
    snap = _build(offline)
    alfa = snap["tickers"]["ALFA"]
    assert alfa["metrics"]["support_level"]["support"] == 23.4
    score, inputs = compute_recent_edge_score(alfa)
    support_input = next(i for i in inputs if i["component"] == "support")
    assert support_input["missing"] is False
    assert score is not None


def test_live_fields_and_provider_failures(offline):
    snap = _build(offline)
    alfa = snap["tickers"]["ALFA"]
    assert "atr" in alfa["metrics"] and "daily_change_pct" in alfa["metrics"]
    assert alfa["metrics"]["sector"] == "Tech"
    # GAMMA had no price data -> recorded as a provider failure, not a crash.
    failed = {f["ticker"] for f in snap["provider_failures"]}
    assert "GAMMA" in failed


def test_cache_status_ages_sources(offline):
    snap = _build(offline)
    arts = {c["artifact"]: c for c in snap["cache_status"]}
    assert "support_eval" in arts
    assert arts["support_eval"]["age_trading_days"] is not None
