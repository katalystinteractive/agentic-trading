"""Live prediction ledger for graph-policy recommendations and outcomes."""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = ROOT / "data" / "prediction_ledger.json"
SCHEMA_VERSION = 1


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _today():
    return date.today().isoformat()


def _resolve_path(path: Path | None) -> Path:
    return Path(path) if path is not None else LEDGER_PATH


def _load(path: Path | None = None) -> dict[str, Any]:
    path = _resolve_path(path)
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "predictions": []}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"schema_version": SCHEMA_VERSION, "predictions": []}
    if not isinstance(data, dict):
        return {"schema_version": SCHEMA_VERSION, "predictions": []}
    predictions = data.get("predictions")
    if not isinstance(predictions, list):
        predictions = []
    return {"schema_version": SCHEMA_VERSION, "predictions": predictions}


def _write(data: dict[str, Any], path: Path | None = None) -> None:
    path = _resolve_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2, default=str) + "\n")
    tmp.replace(path)


def _next_id(predictions: list[dict[str, Any]]) -> int:
    ids = [p.get("id", 0) for p in predictions if isinstance(p.get("id"), int)]
    return max(ids, default=0) + 1


def _dedupe_key(strategy: str, ticker: str, recommendation: dict[str, Any],
                decision_date: str) -> str:
    level = (
        recommendation.get("entry")
        or recommendation.get("support")
        or recommendation.get("price")
        or recommendation.get("buy_at")
        or ""
    )
    return f"{decision_date}:{strategy}:{ticker}:{level}"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None


def _score_bucket(score: dict[str, Any]) -> str:
    value = score.get("expected_edge_pct")
    if value is None:
        value = score.get("expected_edge")
        if isinstance(value, (int, float)):
            value *= 100
    if not isinstance(value, (int, float)):
        return "unknown"
    if value < 0:
        return "<0%"
    if value < 2:
        return "0-2%"
    if value < 5:
        return "2-5%"
    return "5%+"


def _artifact_bucket(artifact_versions: dict[str, Any]) -> str:
    if not artifact_versions:
        return "unknown"
    parts = []
    for name in sorted(artifact_versions):
        version = artifact_versions.get(name)
        if isinstance(version, dict):
            marker = version.get("mtime") or version.get("updated") or version.get("version")
        else:
            marker = version
        parts.append(f"{name}:{marker}")
    return "|".join(parts)[:240] or "unknown"


def artifact_versions(paths: dict[str, Path | str]) -> dict[str, Any]:
    """Return lightweight version markers for artifacts used in a prediction."""
    versions = {}
    for name, raw_path in paths.items():
        path = Path(raw_path)
        if not path.exists():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        versions[name] = {
            "path": str(path),
            "mtime": round(stat.st_mtime, 3),
            "size": stat.st_size,
        }
    return versions


def record_prediction(strategy: str, ticker: str, recommendation: dict[str, Any],
                      *, features: dict[str, Any] | None = None,
                      score: dict[str, Any] | None = None,
                      artifact_versions: dict[str, Any] | None = None,
                      reason: str | None = None,
                      path: Path | None = None) -> dict[str, Any]:
    """Append or update an open prediction for a live recommendation."""
    ticker = ticker.upper()
    decision_date = recommendation.get("date") or _today()
    key = recommendation.get("prediction_key") or _dedupe_key(
        strategy, ticker, recommendation, decision_date)
    data = _load(path)
    predictions = data["predictions"]

    existing = next((p for p in predictions if p.get("prediction_key") == key), None)
    if existing is None:
        existing = {
            "id": _next_id(predictions),
            "prediction_key": key,
            "created_at": _now(),
            "status": "open",
        }
        predictions.append(existing)

    existing.update({
        "updated_at": _now(),
        "decision_date": decision_date,
        "strategy": strategy,
        "ticker": ticker,
        "recommendation": recommendation,
        "features": features or {},
        "score": score or {},
        "artifact_versions": artifact_versions or {},
        "reason": reason or "",
    })
    _write(data, path)
    return existing


def _open_predictions(predictions: list[dict[str, Any]], ticker: str,
                      statuses: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        p for p in predictions
        if p.get("ticker") == ticker and p.get("status") in statuses
    ]


def link_fill(ticker: str, price: float, shares: float, fill_date: str | None = None,
              *, path: Path | None = None) -> dict[str, Any] | None:
    """Link a fill to the latest open prediction for a ticker."""
    ticker = ticker.upper()
    data = _load(path)
    matches = _open_predictions(data["predictions"], ticker, ("open",))
    if not matches:
        return None
    pred = sorted(matches, key=lambda p: p.get("created_at", ""))[-1]
    rec = pred.get("recommendation") or {}
    expected = rec.get("entry") or rec.get("support") or rec.get("price")
    directionally_correct = None
    if isinstance(expected, (int, float)) and expected > 0:
        directionally_correct = abs(float(price) - float(expected)) / float(expected) <= 0.03
    pred["status"] = "filled"
    pred["fill"] = {
        "date": fill_date or _today(),
        "linked_at": _now(),
        "price": round(float(price), 4),
        "shares": shares,
        "directionally_correct": directionally_correct,
    }
    pred["updated_at"] = _now()
    _write(data, path)
    return pred


def link_sell(ticker: str, price: float, shares: float, sell_date: str | None = None,
              pnl_pct: float | None = None, exit_reason: str | None = None,
              *, path: Path | None = None) -> dict[str, Any] | None:
    """Link a sell/exit to the latest filled prediction for a ticker."""
    ticker = ticker.upper()
    data = _load(path)
    matches = _open_predictions(data["predictions"], ticker, ("filled",))
    if not matches:
        return None
    pred = sorted(matches, key=lambda p: p.get("fill", {}).get("linked_at", ""))[-1]
    fill = pred.get("fill") or {}
    fill_price = fill.get("price")
    realized_pct = pnl_pct
    if realized_pct is None and isinstance(fill_price, (int, float)) and fill_price > 0:
        realized_pct = round((float(price) - float(fill_price)) / float(fill_price) * 100, 2)
    fill_dt = _parse_date(fill.get("date"))
    sell_dt = _parse_date(sell_date or _today())
    hold_days = (sell_dt - fill_dt).days if fill_dt and sell_dt else None
    pred["status"] = "closed"
    pred["outcome"] = {
        "date": sell_date or _today(),
        "linked_at": _now(),
        "price": round(float(price), 4),
        "shares": shares,
        "hold_days": hold_days,
        "exit_reason": exit_reason or "",
        "pnl_pct": realized_pct,
        "profitable": realized_pct is not None and realized_pct > 0,
    }
    pred["updated_at"] = _now()
    _write(data, path)
    return pred


def _group_summary(predictions: list[dict[str, Any]], key_fn) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for pred in predictions:
        groups.setdefault(str(key_fn(pred) or "unknown"), []).append(pred)
    summary = {}
    for key, rows in sorted(groups.items()):
        closed = [p for p in rows if p.get("status") == "closed"]
        pnl_values = [
            (p.get("outcome") or {}).get("pnl_pct")
            for p in closed
            if isinstance((p.get("outcome") or {}).get("pnl_pct"), (int, float))
        ]
        profitable = sum(1 for p in closed if (p.get("outcome") or {}).get("profitable"))
        expected = [
            (p.get("score") or {}).get("expected_edge_pct")
            for p in rows
            if isinstance((p.get("score") or {}).get("expected_edge_pct"), (int, float))
        ]
        summary[key] = {
            "total": len(rows),
            "closed": len(closed),
            "win_rate": round(profitable / len(closed) * 100, 1) if closed else 0,
            "avg_pnl_pct": round(sum(pnl_values) / len(pnl_values), 2) if pnl_values else 0,
            "avg_expected_edge_pct": round(sum(expected) / len(expected), 2) if expected else 0,
        }
    return summary


def summarize_predictions(path: Path | None = None) -> dict[str, Any]:
    data = _load(path)
    predictions = [p for p in data.get("predictions", []) if isinstance(p, dict)]
    open_count = sum(1 for p in predictions if p.get("status") == "open")
    filled_count = sum(1 for p in predictions if p.get("status") == "filled")
    closed = [p for p in predictions if p.get("status") == "closed"]
    profitable = sum(1 for p in closed if (p.get("outcome") or {}).get("profitable"))
    pnl_values = [
        (p.get("outcome") or {}).get("pnl_pct")
        for p in closed
        if isinstance((p.get("outcome") or {}).get("pnl_pct"), (int, float))
    ]
    avg_pnl = round(sum(pnl_values) / len(pnl_values), 2) if pnl_values else 0
    return {
        "total": len(predictions),
        "open": open_count,
        "filled": filled_count,
        "closed": len(closed),
        "profitable_closed": profitable,
        "win_rate": round(profitable / len(closed) * 100, 1) if closed else 0,
        "avg_pnl_pct": avg_pnl,
        "by_strategy": _group_summary(predictions, lambda p: p.get("strategy")),
        "by_ticker": _group_summary(predictions, lambda p: p.get("ticker")),
        "by_regime": _group_summary(
            predictions,
            lambda p: (p.get("recommendation") or {}).get("regime")
            or (p.get("features") or {}).get("regime"),
        ),
        "by_score_bucket": _group_summary(
            predictions,
            lambda p: _score_bucket(p.get("score") or {}),
        ),
        "by_artifact_version": _group_summary(
            predictions,
            lambda p: _artifact_bucket(p.get("artifact_versions") or {}),
        ),
    }


def print_summary(path: Path | None = None) -> None:
    summary = summarize_predictions(path)
    print("## Prediction Ledger")
    print()
    print("| Total | Open | Filled | Closed | Win% | Avg P/L% |")
    print("| :--- | :--- | :--- | :--- | :--- | :--- |")
    print(
        f"| {summary['total']} | {summary['open']} | {summary['filled']} | "
        f"{summary['closed']} | {summary['win_rate']}% | {summary['avg_pnl_pct']}% |"
    )
    print()
