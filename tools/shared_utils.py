"""Shared utilities for Capital Intelligence tools."""

import json
import re
import statistics
from datetime import date, datetime
from pathlib import Path


def load_json(path):
    """Load a JSON file. Returns empty dict if file doesn't exist."""
    if isinstance(path, str):
        path = Path(path)
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def parse_entry_date(entry_date_str):
    """Parse entry_date, handling 'pre-' prefix dates.
    Returns (date_obj, is_pre_strategy)."""
    if not entry_date_str:
        return None, False
    if entry_date_str.startswith("pre-"):
        rest = entry_date_str[4:]
        try:
            return datetime.strptime(rest, "%Y-%m-%d").date(), True
        except ValueError:
            pass
        try:
            year = int(rest)
            return date(year, 1, 1), True
        except ValueError:
            pass
        return None, True
    try:
        return datetime.strptime(entry_date_str, "%Y-%m-%d").date(), False
    except ValueError:
        return None, False


def get_portfolio_median_pnl(trade_history):
    """Compute portfolio median PnL from SELL records.
    Fallback 6.0% if <3 records."""
    sells = [t for t in trade_history.get("trades", [])
             if t.get("side") == "SELL" and t.get("pnl_pct") is not None]
    pnls = [t["pnl_pct"] for t in sells]
    if len(pnls) < 3:
        return 6.0
    return statistics.median(pnls)


def parse_bullet_label(note):
    """Parse bullet label from order note. Returns e.g. 'B1', 'R2', 'B2+3', 'B?'."""
    if not note:
        return "B?"
    # Take text before em dash
    prefix = note.split("\u2014")[0].split("—")[0].strip()
    # "Bullets N+M"
    m = re.match(r"Bullets?\s+(\d+\+\d+)", prefix, re.IGNORECASE)
    if m:
        return f"B{m.group(1)}"
    # "BN reserve" → RN
    m = re.match(r"B(\d+)\s+reserve", prefix, re.IGNORECASE)
    if m:
        return f"R{m.group(1)}"
    # "Reserve N"
    m = re.match(r"Reserve\s+(\d+)", prefix, re.IGNORECASE)
    if m:
        return f"R{m.group(1)}"
    # "Bullet N"
    m = re.match(r"Bullet\s+(\d+)", prefix, re.IGNORECASE)
    if m:
        return f"B{m.group(1)}"
    return "B?"


def load_cycle_timing(ticker, project_root=None):
    """Load cycle_timing.json for a ticker. Returns stats dict or None.

    Returns: {"total_cycles": int, "median_deep": int, "immediate_fill_pct": float,
              "median_first": int, "max_deep": int} or None if no data.
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent
    ct = load_json(project_root / "tickers" / ticker / "cycle_timing.json")
    if not ct:
        return None
    stats = ct.get("statistics")
    if not stats:
        return None
    return {
        "total_cycles": stats.get("total_cycles", 0),
        "median_deep": stats.get("median_deep"),
        "median_first": stats.get("median_first"),
        "max_deep": stats.get("max_deep"),
        "immediate_fill_pct": stats.get("immediate_fill_pct", 0),
    }
