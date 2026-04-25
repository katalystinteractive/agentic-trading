from datetime import date

import watchlist_tournament as tournament


def _ranking(ticker, rank, score=1.0):
    return {
        "ticker": ticker,
        "rank": rank,
        "score": score,
        "best_strategy": "support",
        "strategy_type": "surgical",
        "active_levels": 1,
        "composites": {"support": score},
    }


def test_recent_active_position_is_protected_from_first_wind_down():
    portfolio = {
        "watchlist": ["ASML"],
        "positions": {
            "ASML": {
                "shares": 0.2,
                "entry_date": date.today().isoformat(),
            },
        },
    }
    metadata = {
        "watchlist_metadata": {
            "ASML": {"added_date": date.today().isoformat()},
        },
        "swap_history": [],
    }
    rankings = [_ranking("WINNER", 1, 100.0), _ranking("ASML", 31, 8.1)]

    actions = tournament.apply_safety_gates(rankings, portfolio, metadata, top_n=1)

    assert actions["wind_down"] == []
    assert actions["monitor"] == []
    assert actions["protected"] == ["ASML"]
    assert metadata["watchlist_metadata"]["ASML"]["below_cutoff_streak"] == 1
    assert "protection window" in actions["reasons"]["ASML"]


def test_mature_active_position_monitors_before_wind_down():
    portfolio = {
        "watchlist": ["OLD"],
        "positions": {
            "OLD": {
                "shares": 1.0,
                "entry_date": "2026-01-01",
            },
        },
    }
    metadata = {
        "watchlist_metadata": {
            "OLD": {"added_date": "2026-01-01"},
        },
        "swap_history": [],
    }
    rankings = [_ranking("WINNER", 1, 100.0), _ranking("OLD", 31, 4.0)]

    actions = tournament.apply_safety_gates(rankings, portfolio, metadata, top_n=1)

    assert actions["wind_down"] == []
    assert actions["monitor"] == ["OLD"]
    assert metadata["watchlist_metadata"]["OLD"]["below_cutoff_streak"] == 1
    assert "needs 2 consecutive" in actions["reasons"]["OLD"]


def test_mature_active_position_winds_down_after_confirmed_bad_run():
    portfolio = {
        "watchlist": ["OLD"],
        "positions": {
            "OLD": {
                "shares": 1.0,
                "entry_date": "2026-01-01",
            },
        },
    }
    metadata = {
        "watchlist_metadata": {
            "OLD": {
                "added_date": "2026-01-01",
                "below_cutoff_streak": 1,
            },
        },
        "swap_history": [],
    }
    rankings = [_ranking("WINNER", 1, 100.0), _ranking("OLD", 31, 4.0)]

    actions = tournament.apply_safety_gates(rankings, portfolio, metadata, top_n=1)

    assert actions["monitor"] == []
    assert actions["wind_down"] == ["OLD"]
    assert metadata["watchlist_metadata"]["OLD"]["below_cutoff_streak"] == 2
    assert "confirmed by 2 consecutive" in actions["reasons"]["OLD"]


def test_same_day_force_rerun_does_not_increment_bad_run_twice():
    portfolio = {
        "watchlist": ["OLD"],
        "positions": {
            "OLD": {
                "shares": 1.0,
                "entry_date": "2026-01-01",
            },
        },
    }
    metadata = {
        "watchlist_metadata": {
            "OLD": {
                "added_date": "2026-01-01",
                "below_cutoff_streak": 1,
                "below_cutoff_last_seen": date.today().isoformat(),
            },
        },
        "swap_history": [],
    }
    rankings = [_ranking("WINNER", 1, 100.0), _ranking("OLD", 31, 4.0)]

    actions = tournament.apply_safety_gates(rankings, portfolio, metadata, top_n=1)

    assert actions["wind_down"] == []
    assert actions["monitor"] == ["OLD"]
    assert metadata["watchlist_metadata"]["OLD"]["below_cutoff_streak"] == 1


def test_execute_actions_clears_stale_wind_down_for_protected_position(monkeypatch, tmp_path):
    monkeypatch.setattr(tournament, "PORTFOLIO_PATH", tmp_path / "portfolio.json")
    portfolio = {
        "watchlist": ["ASML"],
        "positions": {
            "ASML": {
                "shares": 0.2,
                "winding_down": True,
            },
        },
    }
    actions = {
        "wind_down": [],
        "drop": [],
        "challenge": [],
        "onboard": [],
        "protected": ["ASML"],
        "monitor": [],
        "confirmed": [],
    }
    metadata = {"watchlist_metadata": {}, "swap_history": []}

    tournament.execute_actions(actions, portfolio, metadata)

    assert "winding_down" not in portfolio["positions"]["ASML"]


def test_score_diagnostics_explain_material_regression():
    rankings = [_ranking("ASML", 181, 8.1)]
    actions = {
        "onboard": [],
        "drop": [],
        "wind_down": [],
        "monitor": ["ASML"],
        "protected": [],
        "confirmed": [],
        "challenge": [],
        "reasons": {"ASML": "rank 181 below top-30 cutoff"},
    }
    metadata = {
        "previous_rankings": {
            "ASML": {
                "ticker": "ASML",
                "rank": 1,
                "score": 30.1,
                "best_strategy": "support",
                "composites": {"support": 30.1},
            },
        },
    }

    diagnostics = tournament.build_score_diagnostics(rankings, actions, metadata)

    assert diagnostics["ASML"]["previous_score"] == 30.1
    assert diagnostics["ASML"]["score_delta"] == -22.0
    assert diagnostics["ASML"]["action"] == "monitor"
    assert diagnostics["ASML"]["reason"] == "rank 181 below top-30 cutoff"
