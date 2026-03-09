#!/usr/bin/env python3
"""
Trading Calendar — Lightweight US market trading day utilities.

Stdlib only. Hardcoded US market holidays for 2025–2027.

Usage:
    from trading_calendar import is_trading_day, last_trading_day, as_of_date_label
"""

from datetime import date, timedelta

# US market holidays (observed dates) — NYSE/NASDAQ
_HOLIDAYS = {
    # 2025
    date(2025, 1, 1),   # New Year's Day
    date(2025, 1, 20),  # MLK Day
    date(2025, 2, 17),  # Presidents' Day
    date(2025, 4, 18),  # Good Friday
    date(2025, 5, 26),  # Memorial Day
    date(2025, 6, 19),  # Juneteenth
    date(2025, 7, 4),   # Independence Day
    date(2025, 9, 1),   # Labor Day
    date(2025, 11, 27), # Thanksgiving
    date(2025, 12, 25), # Christmas
    # 2026
    date(2026, 1, 1),   # New Year's Day
    date(2026, 1, 19),  # MLK Day
    date(2026, 2, 16),  # Presidents' Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 6, 19),  # Juneteenth
    date(2026, 7, 3),   # Independence Day (observed, July 4 = Saturday)
    date(2026, 9, 7),   # Labor Day
    date(2026, 11, 26), # Thanksgiving
    date(2026, 12, 25), # Christmas
    # 2027
    date(2027, 1, 1),   # New Year's Day
    date(2027, 1, 18),  # MLK Day
    date(2027, 2, 15),  # Presidents' Day
    date(2027, 3, 26),  # Good Friday
    date(2027, 5, 31),  # Memorial Day
    date(2027, 6, 18),  # Juneteenth (observed, June 19 = Saturday)
    date(2027, 7, 5),   # Independence Day (observed, July 4 = Sunday)
    date(2027, 9, 6),   # Labor Day
    date(2027, 11, 25), # Thanksgiving
    date(2027, 12, 24), # Christmas (observed, Dec 25 = Saturday)
}

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def is_trading_day(d=None):
    """Return True if d (default: today) is a US market trading day."""
    if d is None:
        d = date.today()
    return d.weekday() < 5 and d not in _HOLIDAYS


def last_trading_day(d=None):
    """Return the most recent trading day on or before d (default: today)."""
    if d is None:
        d = date.today()
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def as_of_date_label(d=None):
    """Return a human-readable data freshness label.

    Examples:
        On a trading day: "2026-03-06 close"
        On a weekend:     "2026-03-06 close (data from Friday)"
    """
    if d is None:
        d = date.today()
    ltd = last_trading_day(d)
    label = f"{ltd.isoformat()} close"
    if ltd != d:
        label += f" (data from {_DAY_NAMES[ltd.weekday()]})"
    return label
