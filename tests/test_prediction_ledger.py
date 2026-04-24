from datetime import date

import prediction_ledger as ledger


def test_prediction_lifecycle_links_fill_and_sell(tmp_path):
    path = tmp_path / "prediction_ledger.json"

    pred = ledger.record_prediction(
        "support",
        "abc",
        {
            "date": "2026-04-24",
            "support": 10.0,
            "price": 10.1,
            "regime": "Neutral",
        },
        features={"proximity_pct": 5},
        score={"expected_edge_pct": 4.2},
        artifact_versions={"support_sweep_results": {"mtime": 123}},
        reason="wick_offset_analyzer",
        path=path,
    )

    assert pred["status"] == "open"
    assert pred["ticker"] == "ABC"

    filled = ledger.link_fill("ABC", 10.05, 3, "2026-04-25", path=path)
    assert filled["status"] == "filled"
    assert filled["fill"]["directionally_correct"] is True

    closed = ledger.link_sell(
        "ABC", 11.0, 3, "2026-04-28", pnl_pct=9.5,
        exit_reason="Target", path=path)
    assert closed["status"] == "closed"
    assert closed["outcome"]["hold_days"] == 3
    assert closed["outcome"]["profitable"] is True

    summary = ledger.summarize_predictions(path)
    assert summary["total"] == 1
    assert summary["closed"] == 1
    assert summary["win_rate"] == 100.0
    assert summary["by_strategy"]["support"]["avg_pnl_pct"] == 9.5
    assert summary["by_regime"]["Neutral"]["closed"] == 1
    assert summary["by_score_bucket"]["2-5%"]["avg_expected_edge_pct"] == 4.2


def test_record_prediction_dedupes_same_day_strategy_ticker_level(tmp_path):
    path = tmp_path / "prediction_ledger.json"

    first = ledger.record_prediction(
        "dip", "XYZ", {"date": date.today().isoformat(), "entry": 20.0},
        path=path)
    second = ledger.record_prediction(
        "dip", "XYZ", {"date": date.today().isoformat(), "entry": 20.0, "budget": 50},
        path=path)

    summary = ledger.summarize_predictions(path)
    assert first["id"] == second["id"]
    assert summary["total"] == 1
    assert second["recommendation"]["budget"] == 50
