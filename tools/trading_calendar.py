#!/usr/bin/env python3
"""
Trading Calendar — Lightweight US market trading day utilities.

Stdlib only. Hardcoded US market holidays for 2025–2027.

Usage:
    from trading_calendar import is_trading_day, last_trading_day, as_of_date_label
"""

from datetime import date, datetime, timedelta

import pytz

ET = pytz.timezone("US/Eastern")

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


# ---------------------------------------------------------------------------
# Market hours, early closes, and phase detection
# ---------------------------------------------------------------------------

MARKET_OPEN_ET = (9, 30)
MARKET_CLOSE_ET = (16, 0)

_EARLY_CLOSES = {
    date(2025, 11, 28): (13, 0),  # Day after Thanksgiving
    date(2025, 12, 24): (13, 0),  # Christmas Eve
    date(2026, 11, 27): (13, 0),
    date(2026, 12, 24): (13, 0),
    date(2027, 11, 26): (13, 0),
    date(2027, 12, 24): (13, 0),
}

# Expected market phases per evaluator --phase argument
VALID_PHASES_FOR_MARKET = {
    "first_hour": ("FIRST_HOUR", "CONFIRMATION"),
    "decision": ("CONFIRMATION", "REGULAR"),
    "eod_check": ("REGULAR",),
}


def market_close_time(d=None):
    """Return (hour, minute) close time for given day (handles early closes)."""
    d = d or date.today()
    return _EARLY_CLOSES.get(d, MARKET_CLOSE_ET)


def get_market_phase():
    """Return current market phase based on ET time.

    Returns: CLOSED, PRE_MARKET, FIRST_HOUR, CONFIRMATION, REGULAR, AFTER_HOURS
    """
    now = datetime.now(ET)
    d = now.date()
    if not is_trading_day(d):
        return "CLOSED"
    h, m = now.hour, now.minute
    close_h, close_m = market_close_time(d)
    if h < 9 or (h == 9 and m < 30):
        return "PRE_MARKET"
    elif (h == 9 and m >= 30) or (h == 10 and m < 30):
        return "FIRST_HOUR"
    elif h == 10 and m >= 30:
        return "CONFIRMATION"
    elif h < close_h or (h == close_h and m < close_m):
        return "REGULAR"
    else:
        return "AFTER_HOURS"


def market_time_to_utc_hour(et_hour, et_minute=0):
    """Convert ET time to UTC fractional hour (handles EDT/EST automatically)."""
    now_et = datetime.now(ET)
    market_time = now_et.replace(hour=et_hour, minute=et_minute, second=0, microsecond=0)
    market_utc = market_time.astimezone(pytz.utc)
    return market_utc.hour + market_utc.minute / 60
