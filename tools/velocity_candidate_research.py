"""Advisory NUAI-like velocity candidate research from local artifacts.

This tool is intentionally read-only with respect to live decision artifacts. It
mines existing sweep/cycle outputs and writes a separate advisory report.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent

EVIDENCE_SOURCES = ("support", "support_levels", "resistance", "bounce", "regime_exit")
PERIODS = ("12", "6", "3", "1")


def default_paths(root: Path = ROOT) -> dict[str, Path]:
    """Return default repo-local input and output paths."""
    return {
        "support": root / "data" / "support_sweep_results.json",
        "support_levels": root / "data" / "sweep_support_levels.json",
        "resistance": root / "data" / "resistance_sweep_results.json",
        "bounce": root / "data" / "bounce_sweep_results.json",
        "regime_exit": root / "data" / "regime_exit_sweep_results.json",
        "entry": root / "data" / "entry_sweep_results.json",
        "tournament": root / "data" / "tournament_results.json",
        "portfolio": root / "portfolio.json",
        "tickers_dir": root / "tickers",
        "output_json": root / "data" / "velocity_candidate_research.json",
        "output_md": root / "data" / "velocity_candidate_research.md",
    }


def load_json_artifact(path: Path) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Load a JSON object and return (data, input_status_or_warning)."""
    status = {"path": _rel(path), "status": "ok"}
    try:
        with path.open() as f:
            data = json.load(f)
    except FileNotFoundError:
        status["status"] = "missing"
        return None, status
    except json.JSONDecodeError as exc:
        status.update({"status": "invalid_json", "error": str(exc)})
        return None, status
    except OSError as exc:
        status.update({"status": "read_error", "error": str(exc)})
        return None, status

    if not isinstance(data, dict):
        status.update({"status": "invalid_shape", "error": "root must be an object"})
        return None, status
    return data, status


def normalize_strategy_entry(
    ticker: str,
    strategy: str,
    entry: dict[str, Any],
    source_file: str | Path,
) -> dict[str, Any]:
    """Normalize one strategy artifact entry to the scanner's common shape."""
    warnings: list[str] = []
    stats_key, periods_key = _keys_for_strategy(strategy, entry)
    raw_stats = entry.get(stats_key, {}) if isinstance(entry, dict) else {}
    raw_periods = entry.get(periods_key, {}) if isinstance(entry, dict) else {}

    stats = _normalize_stats(raw_stats, warnings, f"{ticker}.{strategy}.stats")
    periods = {
        period: _normalize_period(
            raw_periods.get(period, raw_periods.get(int(period), {}))
            if isinstance(raw_periods, dict)
            else {},
            warnings,
            f"{ticker}.{strategy}.periods.{period}",
        )
        for period in PERIODS
    }

    winner_context = {}
    if strategy == "resistance" and isinstance(entry.get("vs_flat"), dict):
        winner_context = {"vs_flat": entry["vs_flat"]}
    elif strategy == "bounce" and isinstance(entry.get("vs_others"), dict):
        winner_context = {"vs_others": entry["vs_others"]}

    return {
        "ticker": ticker,
        "strategy": strategy,
        "source_file": _rel(Path(source_file)),
        "stats": stats,
        "periods": periods,
        "winner_context": winner_context,
        "warnings": warnings,
    }


def load_strategy_entries(
    paths: dict[str, Path],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Load and normalize all evidence sources.

    Entry sweep is probed for input status only and is never consumed as evidence.
    """
    entries: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    input_status: dict[str, dict[str, Any]] = {}

    for strategy in EVIDENCE_SOURCES:
        path = paths[strategy]
        data, status = load_json_artifact(path)
        input_status[f"{strategy}_sweep_results"] = status or {
            "path": _rel(path),
            "status": "unknown",
        }
        if status and status.get("status") != "ok":
            warnings.append(status)
            continue
        for ticker, entry in (data or {}).items():
            if str(ticker).startswith("_") or not isinstance(entry, dict):
                continue
            entries.append(normalize_strategy_entry(ticker, strategy, entry, path))

    entry_path = paths.get("entry")
    if entry_path is not None:
        _, entry_status = load_json_artifact(entry_path)
        if entry_status:
            input_status["entry_sweep_results"] = entry_status
            if entry_status.get("status") != "ok":
                warnings.append(entry_status)
            else:
                input_status["entry_sweep_results"]["status"] = "ignored"
                input_status["entry_sweep_results"]["reason"] = "excluded from advisory scanner v1"

    return entries, warnings, input_status


def load_cycle_timing(ticker: str, tickers_dir: Path) -> dict[str, Any]:
    data, _ = load_json_artifact(tickers_dir / ticker / "cycle_timing.json")
    return data or {}


def compute_cycle_amplitude(cycle_timing: dict[str, Any]) -> dict[str, Any]:
    """Compute median support-to-resistance rebound percentage from cycles."""
    rebounds = []
    for cycle in cycle_timing.get("cycles", []) or []:
        if not isinstance(cycle, dict):
            continue
        resistance = _num(cycle.get("resistance_price"))
        first = _num(cycle.get("first_touch_price"))
        deep = _num(cycle.get("deep_touch_price"))
        touch = first if first > 0 else deep
        if resistance > 0 and touch > 0 and resistance > touch:
            rebounds.append((resistance - touch) / touch * 100.0)

    if not rebounds:
        return {"median_cycle_rebound_pct": None, "sample_size": 0}
    return {
        "median_cycle_rebound_pct": round(statistics.median(rebounds), 1),
        "sample_size": len(rebounds),
    }


def load_tournament_context(path: Path) -> dict[str, dict[str, Any]]:
    data, _ = load_json_artifact(path)
    rankings = {}
    for item in (data or {}).get("rankings", []) or []:
        if not isinstance(item, dict) or not item.get("ticker"):
            continue
        rankings[str(item["ticker"])] = {
            "rank": item.get("rank"),
            "score": item.get("score"),
            "best_strategy": item.get("best_strategy"),
            "status": item.get("status"),
        }
    return rankings


def load_portfolio_context(path: Path) -> dict[str, Any]:
    data, _ = load_json_artifact(path)
    portfolio = data or {}
    positions = portfolio.get("positions", {}) if isinstance(portfolio.get("positions"), dict) else {}
    pending = portfolio.get("pending_orders", {}) if isinstance(portfolio.get("pending_orders"), dict) else {}
    watchlist = set(portfolio.get("watchlist", []) or [])
    velocity_watchlist = set(portfolio.get("velocity_watchlist", []) or [])
    return {
        "positions": positions,
        "pending_orders": pending,
        "watchlist": watchlist,
        "velocity_watchlist": velocity_watchlist,
    }


def score_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    """Attach score components, final score, confidence, and profile labels."""
    best = candidate["best_entry"]
    recent = _recent_evidence(best)
    cycle = candidate.get("cycle_timing", {})
    amp = candidate.get("cycle_amplitude", {})
    tournament_rank = candidate.get("tournament_rank")

    win = max(recent.get("win_rate_1m", 0), recent.get("win_rate_3m", 0))
    recent_profitability = min(35.0, (win / 100.0) * 25.0 + min(max(recent.get("pnl", 0), 0), 50) / 50 * 10)

    stats = cycle.get("statistics", {}) if isinstance(cycle.get("statistics"), dict) else {}
    cycle_cadence = 0.0
    if _num(stats.get("total_cycles")) >= 5:
        cycle_cadence += 8
    median_first = _num(stats.get("median_first"), default=999)
    if median_first <= 2:
        cycle_cadence += 9
    if _num(stats.get("immediate_fill_pct")) >= 80:
        cycle_cadence += 8

    trade_frequency = min(15.0, _num(recent.get("trades_1m")) * 2.5 + _num(recent.get("trades_3m")) * 0.75)

    rebound = amp.get("median_cycle_rebound_pct")
    if rebound is None:
        cycle_amplitude = 0.0
    elif rebound >= 7:
        cycle_amplitude = 10.0
    elif rebound >= 5:
        cycle_amplitude = 7.0
    else:
        cycle_amplitude = 0.0

    active_strategies = sum(1 for e in candidate["entries"] if _has_recent_gate(e))
    multi_strategy = min(10.0, max(0, active_strategies - 1) * 5.0)

    underweight = 0.0
    if tournament_rank is None:
        underweight = 8.0
    elif tournament_rank > 30:
        underweight = 10.0

    components = {
        "recent_profitability": round(recent_profitability, 1),
        "cycle_cadence": round(cycle_cadence, 1),
        "trade_frequency": round(trade_frequency, 1),
        "cycle_amplitude": round(cycle_amplitude, 1),
        "multi_strategy": round(multi_strategy, 1),
        "underweight_opportunity": round(underweight, 1),
    }
    raw = sum(components.values())
    score = round(min(100.0, raw / 105.0 * 100.0), 1)

    confidence = _confidence(score, cycle, rebound, recent)
    profile = "nuai_like_velocity" if confidence in {"high", "medium"} else "velocity_review"
    return {
        **candidate,
        "score": score,
        "profile": profile,
        "confidence": confidence,
        "score_components": components,
        "recent_evidence": {
            "trades_1m": recent.get("trades_1m", 0),
            "win_rate_1m": recent.get("win_rate_1m", 0),
            "pnl_1m": recent.get("pnl_1m", 0),
            "trades_3m": recent.get("trades_3m", 0),
            "win_rate_3m": recent.get("win_rate_3m", 0),
            "pnl_3m": recent.get("pnl_3m", 0),
        },
    }


def build_rankings(
    normalized_entries: list[dict[str, Any]],
    cycle_map: dict[str, dict[str, Any]],
    tournament_context: dict[str, dict[str, Any]],
    portfolio_context: dict[str, Any],
    include_low_confidence: bool = False,
    min_score: float = 0,
    top: int = 50,
) -> dict[str, list[dict[str, Any]]]:
    """Build categorized candidate output buckets."""
    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for entry in normalized_entries:
        by_ticker.setdefault(entry["ticker"], []).append(entry)

    rankings = []
    review = []
    stale = []
    excluded = []

    for ticker, entries in sorted(by_ticker.items()):
        status = _portfolio_status(ticker, portfolio_context)
        if status == "winding_down_excluded":
            excluded.append({"ticker": ticker, "reason": status, "status": "position"})
            continue

        if _is_stale_history(entries):
            stale.append(_stale_entry(ticker, entries, tournament_context.get(ticker)))
            continue

        eligible = [e for e in entries if _has_recent_gate(e)]
        if not eligible:
            continue

        best = max(eligible, key=_recent_score)
        cycle = cycle_map.get(ticker, {})
        amp = compute_cycle_amplitude(cycle)
        candidate = {
            "ticker": ticker,
            "status": status,
            "tournament_rank": (tournament_context.get(ticker) or {}).get("rank"),
            "best_strategy": best["strategy"],
            "best_entry": best,
            "entries": entries,
            "cycle_timing": cycle,
            "cycle_amplitude": amp,
            "warnings": _candidate_warnings(entries, cycle, amp),
        }
        scored = score_candidate(candidate)

        if _low_amplitude_review(scored):
            scored["reason"] = "low_amplitude_review"
            review.append(_public_candidate(scored))
            continue

        if scored["score"] >= min_score and (include_low_confidence or scored["confidence"] != "low"):
            rankings.append(_public_candidate(scored))
        else:
            scored["reason"] = "low_confidence_review"
            review.append(_public_candidate(scored))

    rankings.sort(key=lambda r: r["score"], reverse=True)
    review.sort(key=lambda r: r.get("score", 0), reverse=True)
    return {
        "rankings": rankings[:top],
        "needs_manual_review": review,
        "stale_history": stale,
        "excluded": excluded,
    }


def build_report(
    root: Path = ROOT,
    paths: dict[str, Path] | None = None,
    options: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int]:
    """Build the advisory report and return (report, exit_code)."""
    paths = paths or default_paths(root)
    options = options or {}
    entries, input_warnings, input_status = load_strategy_entries(paths)
    valid_evidence = [
        key for key in EVIDENCE_SOURCES
        if input_status.get(f"{key}_sweep_results", {}).get("status") == "ok"
    ]
    if not valid_evidence:
        report = _empty_report(input_status, input_warnings)
        return report, 1

    tickers = sorted({entry["ticker"] for entry in entries})
    cycle_map = {ticker: load_cycle_timing(ticker, paths["tickers_dir"]) for ticker in tickers}
    tournament = load_tournament_context(paths["tournament"])
    portfolio = load_portfolio_context(paths["portfolio"])

    buckets = build_rankings(
        entries,
        cycle_map,
        tournament,
        portfolio,
        include_low_confidence=bool(options.get("include_low_confidence", False)),
        min_score=float(options.get("min_score", 0)),
        top=int(options.get("top", 50)),
    )
    report = {
        "_meta": {
            "schema_version": 1,
            "source": "velocity_candidate_research.py",
            "model_family": "advisory_research",
            "execution_mode": "offline_artifact_research",
            "live_decision_status": "advisory_only",
            "generated": datetime.now().isoformat(timespec="seconds"),
            "inputs": input_status,
        },
        "summary": {
            "total_tickers_scanned": len(tickers),
            "candidates_passing_gates": len(buckets["rankings"]),
            "high_confidence": sum(1 for r in buckets["rankings"] if r["confidence"] == "high"),
            "tracked_candidates": sum(1 for r in buckets["rankings"] if r["status"] in {"position", "watchlist"}),
            "untracked_candidates": sum(1 for r in buckets["rankings"] if r["status"] == "untracked"),
            "malformed_or_skipped_inputs": sum(1 for w in input_warnings if w.get("status") != "missing"),
        },
        **buckets,
        "skipped_inputs": input_warnings,
        "warnings": [w for w in input_warnings],
    }
    return report, 0


def format_markdown(report: dict[str, Any]) -> str:
    """Format an advisory markdown report."""
    meta = report.get("_meta", {})
    summary = report.get("summary", {})
    lines = [
        "# Velocity Candidate Research",
        "",
        f"Generated: {meta.get('generated', 'unknown')}",
        "",
        "**Advisory only.** This report is for candidate review and does not modify portfolio, tournament, bullet, or deployment decisions.",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| :--- | :--- |",
    ]
    for key in (
        "total_tickers_scanned",
        "candidates_passing_gates",
        "high_confidence",
        "tracked_candidates",
        "untracked_candidates",
        "malformed_or_skipped_inputs",
    ):
        lines.append(f"| {key.replace('_', ' ').title()} | {summary.get(key, 0)} |")

    _append_candidate_section(lines, "High Confidence", [
        r for r in report.get("rankings", []) if r.get("confidence") == "high"
    ])
    _append_candidate_section(lines, "Rankings", [
        r for r in report.get("rankings", []) if r.get("confidence") != "high"
    ])
    _append_candidate_section(lines, "Needs Manual Review", report.get("needs_manual_review", []))

    lines.append("")
    lines.append("## Stale 12m Only")
    stale = report.get("stale_history", [])
    if stale:
        lines.append("")
        lines.append("| Ticker | Best Strategy | 12m Trades | 12m Win | Reason |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for item in stale:
            ctx = item.get("stability_context", {})
            lines.append(
                f"| {item['ticker']} | {item.get('best_strategy', '')} | "
                f"{ctx.get('trades_12m', 0)} | {_fmt_pct(ctx.get('win_rate_12m', 0))} | "
                f"{item.get('reason', '')} |"
            )
    else:
        lines.append("\nNo stale-history candidates.")

    lines.append("")
    lines.append("## Skipped or Invalid Inputs")
    skipped = report.get("skipped_inputs", [])
    if skipped:
        lines.append("")
        lines.append("| Path | Status | Detail |")
        lines.append("| :--- | :--- | :--- |")
        for item in skipped:
            lines.append(f"| {item.get('path', '')} | {item.get('status', '')} | {item.get('error', item.get('reason', ''))} |")
    else:
        lines.append("\nNo skipped or invalid inputs.")

    return "\n".join(lines).rstrip() + "\n"


def write_outputs(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2) + "\n")
    md_path.write_text(format_markdown(report))


def run_research(
    root: Path = ROOT,
    paths: dict[str, Path] | None = None,
    output_json: Path | None = None,
    output_md: Path | None = None,
    stdout_only: bool = False,
    options: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int]:
    """Run the scanner with injectable paths for tests."""
    paths = paths or default_paths(root)
    report, exit_code = build_report(root=root, paths=paths, options=options)
    if not stdout_only:
        write_outputs(
            report,
            output_json or paths["output_json"],
            output_md or paths["output_md"],
        )
    return report, exit_code


def _keys_for_strategy(strategy: str, entry: dict[str, Any]) -> tuple[str, str]:
    if strategy == "support" and "slippage_stats" in entry:
        return "slippage_stats", "slippage_periods"
    if strategy == "regime_exit":
        return "regime_exit_stats", "regime_exit_periods"
    return "stats", "periods"


def _normalize_stats(raw: Any, warnings: list[str], label: str) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "composite": _field_num(raw, "composite", warnings, label),
        "pnl": _field_num(raw, "pnl", warnings, label),
        "trades": int(_field_num(raw, "trades", warnings, label)),
        "win_rate": _field_num(raw, "win_rate", warnings, label),
    }


def _normalize_period(raw: Any, warnings: list[str], label: str) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "pnl": _field_num(raw, "pnl", warnings, label),
        "cycles": int(_field_num(raw, "cycles", warnings, label)),
        "trades": int(_field_num(raw, "trades", warnings, label)),
        "win_rate": _field_num(raw, "win_rate", warnings, label),
    }


def _field_num(raw: dict[str, Any], field: str, warnings: list[str], label: str) -> float:
    value = raw.get(field, 0)
    try:
        return float(value)
    except (TypeError, ValueError):
        warnings.append(f"{label}.{field} malformed; coerced to 0")
        return 0.0


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _recent_evidence(entry: dict[str, Any]) -> dict[str, float]:
    p1 = entry.get("periods", {}).get("1", {})
    p3 = entry.get("periods", {}).get("3", {})
    primary = p1 if _num(p1.get("trades")) >= 2 else p3
    return {
        "trades_1m": int(_num(p1.get("trades"))),
        "win_rate_1m": _num(p1.get("win_rate")),
        "pnl_1m": round(_num(p1.get("pnl")), 2),
        "trades_3m": int(_num(p3.get("trades"))),
        "win_rate_3m": _num(p3.get("win_rate")),
        "pnl_3m": round(_num(p3.get("pnl")), 2),
        "pnl": _num(primary.get("pnl")),
    }


def _has_recent_gate(entry: dict[str, Any]) -> bool:
    p1 = entry.get("periods", {}).get("1", {})
    p3 = entry.get("periods", {}).get("3", {})
    one_ok = _num(p1.get("trades")) >= 2 and _num(p1.get("win_rate")) >= 75 and _num(p1.get("pnl")) > 0
    three_ok = _num(p3.get("trades")) >= 4 and _num(p3.get("win_rate")) >= 75 and _num(p3.get("pnl")) > 0
    return one_ok or three_ok


def _recent_score(entry: dict[str, Any]) -> float:
    ev = _recent_evidence(entry)
    return (
        ev["pnl_1m"] * 2
        + ev["pnl_3m"]
        + ev["trades_1m"] * 5
        + ev["trades_3m"] * 2
        + max(ev["win_rate_1m"], ev["win_rate_3m"])
    )


def _is_stale_history(entries: list[dict[str, Any]]) -> bool:
    has_strong_12 = False
    has_recent = False
    for entry in entries:
        p12 = entry.get("periods", {}).get("12", {})
        if _num(p12.get("trades")) >= 10 and _num(p12.get("win_rate")) >= 75 and _num(p12.get("pnl")) > 0:
            has_strong_12 = True
        if _num(entry.get("periods", {}).get("1", {}).get("trades")) > 0 or _num(entry.get("periods", {}).get("3", {}).get("trades")) > 0:
            has_recent = True
    return has_strong_12 and not has_recent


def _stale_entry(
    ticker: str,
    entries: list[dict[str, Any]],
    tournament: dict[str, Any] | None,
) -> dict[str, Any]:
    best = max(entries, key=lambda e: _num(e.get("periods", {}).get("12", {}).get("pnl")))
    p12 = best.get("periods", {}).get("12", {})
    return {
        "ticker": ticker,
        "reason": "stale_history",
        "best_strategy": best["strategy"],
        "tournament_rank": (tournament or {}).get("rank"),
        "recent_evidence": {
            "trades_1m": int(_num(best.get("periods", {}).get("1", {}).get("trades"))),
            "trades_3m": int(_num(best.get("periods", {}).get("3", {}).get("trades"))),
        },
        "stability_context": {
            "trades_12m": int(_num(p12.get("trades"))),
            "win_rate_12m": _num(p12.get("win_rate")),
            "pnl_12m": round(_num(p12.get("pnl")), 2),
        },
    }


def _portfolio_status(ticker: str, portfolio: dict[str, Any]) -> str:
    pos = portfolio.get("positions", {}).get(ticker)
    if isinstance(pos, dict):
        if pos.get("winding_down"):
            return "winding_down_excluded"
        if _num(pos.get("shares")) > 0:
            return "position"
    if ticker in portfolio.get("pending_orders", {}):
        return "pending"
    if ticker in portfolio.get("watchlist", set()):
        return "watchlist"
    if ticker in portfolio.get("velocity_watchlist", set()):
        return "velocity_watchlist"
    return "untracked"


def _confidence(
    score: float,
    cycle: dict[str, Any],
    rebound: float | None,
    recent: dict[str, Any],
) -> str:
    stats = cycle.get("statistics", {}) if isinstance(cycle.get("statistics"), dict) else {}
    cycle_ok = (
        _num(stats.get("total_cycles")) >= 5
        and _num(stats.get("median_first"), 999) <= 2
        and _num(stats.get("immediate_fill_pct")) >= 80
    )
    amplitude_ok = rebound is not None and rebound >= 7
    missing_amp_exception = (
        rebound is None
        and (
            recent["trades_1m"] >= 4 and recent["win_rate_1m"] >= 85 and recent["pnl_1m"] > 0
            or recent["trades_3m"] >= 10 and recent["win_rate_3m"] >= 85 and recent["pnl_3m"] > 0
        )
    )
    if score >= 70 and cycle_ok and (amplitude_ok or missing_amp_exception):
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def _low_amplitude_review(candidate: dict[str, Any]) -> bool:
    rebound = candidate.get("cycle_amplitude", {}).get("median_cycle_rebound_pct")
    if rebound is None or rebound >= 5:
        return False
    recent = candidate.get("recent_evidence", {})
    exception = (
        recent.get("trades_1m", 0) >= 6
        and recent.get("win_rate_1m", 0) >= 90
        and recent.get("pnl_1m", 0) > 0
    ) or (
        recent.get("trades_3m", 0) >= 15
        and recent.get("win_rate_3m", 0) >= 90
        and recent.get("pnl_3m", 0) > 0
    )
    return not exception


def _candidate_warnings(
    entries: list[dict[str, Any]],
    cycle: dict[str, Any],
    amp: dict[str, Any],
) -> list[str]:
    warnings = [w for entry in entries for w in entry.get("warnings", [])]
    if not cycle:
        warnings.append("cycle_timing_missing")
    if amp.get("median_cycle_rebound_pct") is None:
        warnings.append("cycle_amplitude_missing")
    elif amp.get("median_cycle_rebound_pct", 0) < 5:
        warnings.append("median_cycle_rebound_pct below 5")
    return warnings


def _public_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    cycle_stats = candidate.get("cycle_timing", {}).get("statistics", {})
    cycle_amp = candidate.get("cycle_amplitude", {})
    return {
        "ticker": candidate["ticker"],
        "score": candidate.get("score"),
        "profile": candidate.get("profile"),
        "confidence": candidate.get("confidence"),
        "status": candidate.get("status"),
        "reason": candidate.get("reason"),
        "tournament_rank": candidate.get("tournament_rank"),
        "best_strategy": candidate.get("best_strategy"),
        "recent_evidence": candidate.get("recent_evidence", {}),
        "cycle_timing": {
            "total_cycles": cycle_stats.get("total_cycles"),
            "median_first": cycle_stats.get("median_first"),
            "median_deep": cycle_stats.get("median_deep"),
            "immediate_fill_pct": cycle_stats.get("immediate_fill_pct"),
            "median_cycle_rebound_pct": cycle_amp.get("median_cycle_rebound_pct"),
        },
        "score_components": candidate.get("score_components", {}),
        "warnings": candidate.get("warnings", []),
    }


def _append_candidate_section(lines: list[str], title: str, rows: list[dict[str, Any]]) -> None:
    lines.append("")
    lines.append(f"## {title}")
    if not rows:
        lines.append(f"\nNo {title.lower()} candidates.")
        return
    lines.append("")
    lines.append("| Rank | Ticker | Score | Conf | Status | Tourn | Strategy | 1m | 3m | First | Fill | Rebound | Why |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for idx, row in enumerate(rows, 1):
        recent = row.get("recent_evidence", {})
        cycle = row.get("cycle_timing", {})
        why = row.get("reason") or row.get("profile", "")
        lines.append(
            f"| {idx} | {row.get('ticker', '')} | {row.get('score', '')} | "
            f"{row.get('confidence', '')} | {row.get('status', '')} | "
            f"{row.get('tournament_rank') or ''} | {row.get('best_strategy', '')} | "
            f"{recent.get('trades_1m', 0)} / {_fmt_pct(recent.get('win_rate_1m', 0))} / ${recent.get('pnl_1m', 0):.2f} | "
            f"{recent.get('trades_3m', 0)} / {_fmt_pct(recent.get('win_rate_3m', 0))} / ${recent.get('pnl_3m', 0):.2f} | "
            f"{cycle.get('median_first') if cycle.get('median_first') is not None else ''} | "
            f"{_fmt_pct(cycle.get('immediate_fill_pct'))} | "
            f"{_fmt_pct(cycle.get('median_cycle_rebound_pct'))} | {why} |"
        )


def _empty_report(
    input_status: dict[str, dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "_meta": {
            "schema_version": 1,
            "source": "velocity_candidate_research.py",
            "model_family": "advisory_research",
            "execution_mode": "offline_artifact_research",
            "live_decision_status": "advisory_only",
            "generated": datetime.now().isoformat(timespec="seconds"),
            "inputs": input_status,
        },
        "summary": {
            "total_tickers_scanned": 0,
            "candidates_passing_gates": 0,
            "high_confidence": 0,
            "tracked_candidates": 0,
            "untracked_candidates": 0,
            "malformed_or_skipped_inputs": len(warnings),
        },
        "rankings": [],
        "needs_manual_review": [],
        "stale_history": [],
        "excluded": [],
        "skipped_inputs": warnings,
        "warnings": warnings,
    }


def _fmt_pct(value: Any) -> str:
    if value is None or value == "":
        return ""
    return f"{_num(value):.1f}%"


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except (OSError, ValueError):
        return str(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Advisory velocity candidate research")
    parser.add_argument("--top", type=int, default=50)
    parser.add_argument("--min-score", type=float, default=0)
    parser.add_argument("--include-low-confidence", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_stdout")
    parser.add_argument("--stdout-only", action="store_true")
    args = parser.parse_args(argv)

    report, exit_code = run_research(
        options={
            "top": args.top,
            "min_score": args.min_score,
            "include_low_confidence": args.include_low_confidence,
        },
        stdout_only=args.stdout_only,
    )
    if args.json_stdout:
        print(json.dumps(report, indent=2))
    else:
        print(format_markdown(report), end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
