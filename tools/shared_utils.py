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


def score_cycle_efficiency(cycle_timing, max_points=20):
    """Score cycle efficiency (0-max_points).

    Sub-components:
    - Cycle count (0-6): 0 cycles=0, 1-4=2, 5-9=4, 10+=6
    - Immediate fill rate (0-6): <50%=0, 50-79%=2, 80-99%=4, 100%=6
    - Median deep speed (0-5): >15d=0, 8-15d=2, 3-7d=3, 1-2d=5
    - Consistency bonus (0-3): 10+ cycles AND 100% fill AND median_deep<=2 = 3

    Used by surgical_filter.py and watchlist_fitness.py.
    """
    if cycle_timing is None:
        return 0

    pts = 0
    total = cycle_timing.get("total_cycles", 0)
    fill_pct = cycle_timing.get("immediate_fill_pct", 0)
    median_deep = cycle_timing.get("median_deep")

    # Cycle count (0-6)
    if total >= 10:
        pts += 6
    elif total >= 5:
        pts += 4
    elif total >= 1:
        pts += 2

    # Immediate fill rate (0-6)
    if fill_pct >= 100:
        pts += 6
    elif fill_pct >= 80:
        pts += 4
    elif fill_pct >= 50:
        pts += 2

    # Median deep speed (0-5)
    if median_deep is not None:
        if median_deep <= 2:
            pts += 5
        elif median_deep <= 7:
            pts += 3
        elif median_deep <= 15:
            pts += 2

    # Consistency bonus (0-3)
    if total >= 10 and fill_pct >= 100 and median_deep is not None and median_deep <= 2:
        pts += 3

    return min(pts, max_points)


# ---------------------------------------------------------------------------
# Order filter helpers (used by daily_analyzer, broker_reconciliation)
# ---------------------------------------------------------------------------

def is_active_buy(order):
    """Unfilled, placed BUY order."""
    return (order.get("type") == "BUY"
            and order.get("placed", False)
            and "filled" not in order)


def is_active_sell(order):
    """Unfilled, placed SELL order."""
    return (order.get("type") == "SELL"
            and order.get("placed", False)
            and "filled" not in order)


# ---------------------------------------------------------------------------
# Time stop constants & functions
# ---------------------------------------------------------------------------
TIME_STOP_EXCEEDED_DAYS = 60
TIME_STOP_APPROACHING_DAYS = 45


def compute_days_held(entry_date_str, as_of_date=None):
    """Compute days held from entry_date relative to as_of_date.

    Returns (days_int, display_str, is_pre_strategy).
    as_of_date defaults to date.today() if not provided.
    """
    from datetime import date, datetime as dt
    if as_of_date is None:
        as_of_date = date.today()
    if entry_date_str.startswith("pre-"):
        return None, f">{TIME_STOP_EXCEEDED_DAYS}d (pre-strategy)", True
    try:
        entry = dt.strptime(entry_date_str, "%Y-%m-%d").date()
        days = (as_of_date - entry).days
        return days, str(days), False
    except ValueError:
        return None, "Unknown", False


def compute_time_stop(days_held, is_pre_strategy, regime="Neutral"):
    """Compute time stop status. Risk-Off extends thresholds by 14 days."""
    exceeded = TIME_STOP_EXCEEDED_DAYS + (14 if regime == "Risk-Off" else 0)
    approaching = TIME_STOP_APPROACHING_DAYS + (14 if regime == "Risk-Off" else 0)
    if is_pre_strategy:
        return "EXCEEDED"
    if days_held is None:
        return "Unknown"
    if days_held > exceeded:
        return "EXCEEDED"
    if days_held >= approaching:
        return "APPROACHING"
    return "WITHIN"
