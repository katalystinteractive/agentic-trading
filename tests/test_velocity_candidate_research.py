import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import velocity_candidate_research as research
from model_complexity_gate import is_live_decision_artifact
from weekly_reoptimize import PROMOTED_ARTIFACTS


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _paths(tmp_path):
    return {
        "support": tmp_path / "data" / "support_sweep_results.json",
        "support_levels": tmp_path / "data" / "sweep_support_levels.json",
        "resistance": tmp_path / "data" / "resistance_sweep_results.json",
        "bounce": tmp_path / "data" / "bounce_sweep_results.json",
        "regime_exit": tmp_path / "data" / "regime_exit_sweep_results.json",
        "entry": tmp_path / "data" / "entry_sweep_results.json",
        "tournament": tmp_path / "data" / "tournament_results.json",
        "portfolio": tmp_path / "portfolio.json",
        "tickers_dir": tmp_path / "tickers",
        "output_json": tmp_path / "data" / "velocity_candidate_research.json",
        "output_md": tmp_path / "data" / "velocity_candidate_research.md",
    }


def _periods(one_trades=0, one_win=0, one_pnl=0, three_trades=0, three_win=0,
             three_pnl=0, twelve_trades=0, twelve_win=0, twelve_pnl=0):
    return {
        "12": {"pnl": twelve_pnl, "cycles": twelve_trades, "trades": twelve_trades, "win_rate": twelve_win},
        "6": {"pnl": 0, "cycles": 0, "trades": 0, "win_rate": 0},
        "3": {"pnl": three_pnl, "cycles": three_trades, "trades": three_trades, "win_rate": three_win},
        "1": {"pnl": one_pnl, "cycles": one_trades, "trades": one_trades, "win_rate": one_win},
    }


def _cycle_payload(rebound=True):
    cycles = []
    if rebound:
        cycles = [{
            "resistance_price": 10.0,
            "first_touch_price": 9.0,
            "deep_touch_price": 8.8,
        }]
    return {
        "statistics": {
            "total_cycles": 6,
            "median_first": 1,
            "median_deep": 1,
            "immediate_fill_pct": 100.0,
        },
        "cycles": cycles,
    }


def test_normalizes_support_slippage_schema():
    entry = {
        "slippage_stats": {"composite": 21.2, "pnl": 10, "trades": 2},
        "slippage_periods": _periods(one_trades=2, one_win=100, one_pnl=10),
    }

    result = research.normalize_strategy_entry("AAA", "support", entry, "support.json")

    assert result["stats"]["composite"] == 21.2
    assert result["periods"]["1"]["trades"] == 2


def test_normalizes_support_regular_schema():
    entry = {
        "stats": {"composite": 27.4, "pnl": 45.63, "trades": 6},
        "periods": _periods(three_trades=6, three_win=90, three_pnl=30),
    }

    result = research.normalize_strategy_entry("AAA", "support", entry, "support.json")

    assert result["stats"]["composite"] == 27.4
    assert result["periods"]["3"]["win_rate"] == 90


def test_support_falls_back_when_slippage_periods_missing():
    entry = {
        "slippage_stats": {"composite": 99, "pnl": 0, "trades": 0},
        "stats": {"composite": 27.4, "pnl": 45.63, "trades": 6},
        "periods": _periods(one_trades=2, one_win=100, one_pnl=20),
    }

    result = research.normalize_strategy_entry("AAA", "support", entry, "support.json")

    assert result["stats"]["composite"] == 27.4
    assert result["periods"]["1"]["trades"] == 2


def test_normalizes_resistance_bounce_and_regime_exit_schemas():
    resistance = research.normalize_strategy_entry(
        "AAA",
        "resistance",
        {"stats": {"composite": 1}, "periods": {}, "vs_flat": {"winner": "resistance"}},
        "resistance.json",
    )
    bounce = research.normalize_strategy_entry(
        "AAA",
        "bounce",
        {"stats": {"composite": 2}, "periods": {}, "vs_others": {"winner": "bounce"}},
        "bounce.json",
    )
    regime = research.normalize_strategy_entry(
        "AAA",
        "regime_exit",
        {"regime_exit_stats": {"composite": 3}, "regime_exit_periods": {}},
        "regime.json",
    )

    assert resistance["stats"]["composite"] == 1
    assert resistance["winner_context"]["vs_flat"]["winner"] == "resistance"
    assert bounce["stats"]["composite"] == 2
    assert bounce["winner_context"]["vs_others"]["winner"] == "bounce"
    assert regime["stats"]["composite"] == 3


def test_run_research_warns_on_malformed_entry_without_failing(tmp_path):
    paths = _paths(tmp_path)
    _write_json(paths["support_levels"], {
        "VCAND": {
            "stats": {"composite": 30, "pnl": 50, "trades": 6},
            "periods": _periods(one_trades=4, one_win=100, one_pnl=20, three_trades=10, three_win=90, three_pnl=45),
        }
    })
    paths["entry"].parent.mkdir(parents=True, exist_ok=True)
    paths["entry"].write_text('{"bad": true}\n{"extra": true}\n')
    _write_json(paths["portfolio"], {"positions": {}, "watchlist": [], "velocity_watchlist": []})
    _write_json(paths["tournament"], {"rankings": []})
    _write_json(paths["tickers_dir"] / "VCAND" / "cycle_timing.json", _cycle_payload())

    report, exit_code = research.run_research(tmp_path, paths=paths, stdout_only=True)

    assert exit_code == 0
    assert report["rankings"][0]["ticker"] == "VCAND"
    assert report["_meta"]["inputs"]["entry_sweep_results"]["status"] == "invalid_json"
    assert any(w["status"] == "invalid_json" for w in report["warnings"])


def test_nuai_like_fixture_ranks_high_with_recent_evidence_and_amplitude(tmp_path):
    paths = _paths(tmp_path)
    _write_json(paths["support_levels"], {
        "VCAND": {
            "stats": {"composite": 30, "pnl": 50, "trades": 6},
            "periods": _periods(one_trades=6, one_win=100, one_pnl=40, three_trades=16, three_win=94, three_pnl=58),
        }
    })
    _write_json(paths["portfolio"], {"positions": {}, "watchlist": [], "velocity_watchlist": []})
    _write_json(paths["tournament"], {"rankings": [{"ticker": "VCAND", "rank": 115}]})
    _write_json(paths["tickers_dir"] / "VCAND" / "cycle_timing.json", _cycle_payload())

    report, exit_code = research.run_research(tmp_path, paths=paths, stdout_only=True)

    assert exit_code == 0
    top = report["rankings"][0]
    assert top["ticker"] == "VCAND"
    assert top["confidence"] == "high"
    assert top["cycle_timing"]["median_cycle_rebound_pct"] >= 7


def test_stale_twelve_month_only_candidate_is_not_primary(tmp_path):
    paths = _paths(tmp_path)
    _write_json(paths["resistance"], {
        "OLDX": {
            "stats": {"composite": 50, "pnl": 300, "trades": 40},
            "periods": _periods(twelve_trades=40, twelve_win=95, twelve_pnl=300),
        }
    })
    _write_json(paths["portfolio"], {"positions": {}, "watchlist": [], "velocity_watchlist": []})
    _write_json(paths["tournament"], {"rankings": []})

    report, exit_code = research.run_research(tmp_path, paths=paths, stdout_only=True)

    assert exit_code == 0
    assert report["rankings"] == []
    assert report["stale_history"][0]["ticker"] == "OLDX"


def test_stale_history_reports_strategy_that_met_stale_gate(tmp_path):
    paths = _paths(tmp_path)
    _write_json(paths["resistance"], {
        "OLDX": {
            "stats": {"composite": 50, "pnl": 300, "trades": 1},
            "periods": _periods(twelve_trades=1, twelve_win=20, twelve_pnl=1000),
        }
    })
    _write_json(paths["bounce"], {
        "OLDX": {
            "stats": {"composite": 20, "pnl": 300, "trades": 40},
            "periods": _periods(twelve_trades=40, twelve_win=95, twelve_pnl=300),
        }
    })
    _write_json(paths["portfolio"], {"positions": {}, "watchlist": [], "velocity_watchlist": []})
    _write_json(paths["tournament"], {"rankings": []})

    report, exit_code = research.run_research(tmp_path, paths=paths, stdout_only=True)

    assert exit_code == 0
    assert report["stale_history"][0]["ticker"] == "OLDX"
    assert report["stale_history"][0]["best_strategy"] == "bounce"
    assert report["stale_history"][0]["stability_context"]["trades_12m"] == 40


def test_missing_cycle_timing_lowers_confidence_but_does_not_crash(tmp_path):
    paths = _paths(tmp_path)
    _write_json(paths["support_levels"], {
        "MISS": {
            "stats": {"composite": 30, "pnl": 50, "trades": 6},
            "periods": _periods(one_trades=2, one_win=100, one_pnl=20),
        }
    })
    _write_json(paths["portfolio"], {"positions": {}, "watchlist": [], "velocity_watchlist": []})
    _write_json(paths["tournament"], {"rankings": []})

    report, exit_code = research.run_research(tmp_path, paths=paths, stdout_only=True, options={"include_low_confidence": True})

    assert exit_code == 0
    assert report["rankings"][0]["ticker"] == "MISS"
    assert report["rankings"][0]["confidence"] != "high"
    assert "cycle_timing_missing" in report["rankings"][0]["warnings"]


def test_low_amplitude_goes_to_manual_review(tmp_path):
    paths = _paths(tmp_path)
    _write_json(paths["support_levels"], {
        "LOWA": {
            "stats": {"composite": 30, "pnl": 50, "trades": 6},
            "periods": _periods(one_trades=2, one_win=80, one_pnl=10),
        }
    })
    low_amp = _cycle_payload()
    low_amp["cycles"][0]["resistance_price"] = 10.2
    low_amp["cycles"][0]["first_touch_price"] = 10.0
    _write_json(paths["tickers_dir"] / "LOWA" / "cycle_timing.json", low_amp)
    _write_json(paths["portfolio"], {"positions": {}, "watchlist": [], "velocity_watchlist": []})
    _write_json(paths["tournament"], {"rankings": []})

    report, exit_code = research.run_research(tmp_path, paths=paths, stdout_only=True)

    assert exit_code == 0
    assert report["rankings"] == []
    assert report["needs_manual_review"][0]["reason"] == "low_amplitude_review"


def test_scanner_does_not_write_portfolio_or_tournament(tmp_path):
    paths = _paths(tmp_path)
    _write_json(paths["support_levels"], {
        "VCAND": {
            "stats": {"composite": 30, "pnl": 50, "trades": 6},
            "periods": _periods(one_trades=4, one_win=100, one_pnl=20),
        }
    })
    _write_json(paths["portfolio"], {"positions": {}, "watchlist": [], "velocity_watchlist": []})
    _write_json(paths["tournament"], {"rankings": []})
    before_portfolio = paths["portfolio"].read_text()
    before_tournament = paths["tournament"].read_text()

    report, exit_code = research.run_research(tmp_path, paths=paths)

    assert exit_code == 0
    assert paths["portfolio"].read_text() == before_portfolio
    assert paths["tournament"].read_text() == before_tournament
    assert paths["output_json"].exists()
    assert paths["output_md"].exists()


def test_missing_context_artifacts_are_reported_as_warnings(tmp_path):
    paths = _paths(tmp_path)
    _write_json(paths["support_levels"], {
        "VCAND": {
            "stats": {"composite": 30, "pnl": 50, "trades": 6},
            "periods": _periods(one_trades=4, one_win=100, one_pnl=20),
        }
    })

    report, exit_code = research.run_research(tmp_path, paths=paths, stdout_only=True)

    assert exit_code == 0
    assert report["_meta"]["inputs"]["portfolio"]["status"] == "missing"
    assert report["_meta"]["inputs"]["tournament_results"]["status"] == "missing"
    warning_paths = {warning["path"] for warning in report["warnings"]}
    assert str(paths["portfolio"]) in warning_paths
    assert str(paths["tournament"]) in warning_paths


def test_output_is_not_promoted_or_live_decision_eligible(tmp_path):
    paths = _paths(tmp_path)
    _write_json(paths["support_levels"], {
        "VCAND": {
            "stats": {"composite": 30, "pnl": 50, "trades": 6},
            "periods": _periods(one_trades=4, one_win=100, one_pnl=20),
        }
    })
    _write_json(paths["portfolio"], {"positions": {}, "watchlist": [], "velocity_watchlist": []})
    _write_json(paths["tournament"], {"rankings": []})

    report, _ = research.run_research(tmp_path, paths=paths, stdout_only=True)

    promoted_names = {path.name for path in PROMOTED_ARTIFACTS}
    assert "velocity_candidate_research.json" not in promoted_names
    assert is_live_decision_artifact(report) is False


def test_markdown_is_advisory_and_avoids_imperative_trading_language(tmp_path):
    paths = _paths(tmp_path)
    _write_json(paths["support_levels"], {
        "VCAND": {
            "stats": {"composite": 30, "pnl": 50, "trades": 6},
            "periods": _periods(one_trades=4, one_win=100, one_pnl=20),
        }
    })
    _write_json(paths["portfolio"], {"positions": {}, "watchlist": [], "velocity_watchlist": []})
    _write_json(paths["tournament"], {"rankings": []})

    report, _ = research.run_research(tmp_path, paths=paths, stdout_only=True)
    md = research.format_markdown(report)

    assert "Advisory only" in md
    lowered = md.lower()
    assert "buy now" not in lowered
    assert "add to watchlist" not in lowered


def test_stdout_only_skips_output_writes(tmp_path):
    paths = _paths(tmp_path)
    _write_json(paths["support_levels"], {
        "VCAND": {
            "stats": {"composite": 30, "pnl": 50, "trades": 6},
            "periods": _periods(one_trades=4, one_win=100, one_pnl=20),
        }
    })
    _write_json(paths["portfolio"], {"positions": {}, "watchlist": [], "velocity_watchlist": []})
    _write_json(paths["tournament"], {"rankings": []})

    _, exit_code = research.run_research(tmp_path, paths=paths, stdout_only=True)

    assert exit_code == 0
    assert not paths["output_json"].exists()
    assert not paths["output_md"].exists()


def test_no_valid_evidence_artifact_returns_exit_one(tmp_path):
    paths = _paths(tmp_path)
    _write_json(paths["portfolio"], {"positions": {}, "watchlist": [], "velocity_watchlist": []})
    _write_json(paths["tournament"], {"rankings": []})

    report, exit_code = research.run_research(tmp_path, paths=paths, stdout_only=True)

    assert exit_code == 1
    assert report["rankings"] == []
