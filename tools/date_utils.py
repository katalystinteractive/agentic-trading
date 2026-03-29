"""Date utilities — deterministic date/day-of-week helpers.

Call these instead of guessing what day it is. Every date claim
in the system must come from this module, not from LLM inference.

Usage:
    python3 tools/date_utils.py                # print today's info
    python3 tools/date_utils.py --ago 2        # 2 days ago
    python3 tools/date_utils.py --last-trading  # last trading day
"""
import sys
from datetime import date, datetime, timedelta

import pytz

ET = pytz.timezone("US/Eastern")
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def today_info():
    """Return dict with today's date, day name, and whether markets are open."""
    d = date.today()
    dow = d.weekday()  # 0=Mon, 6=Sun
    return {
        "date": d.isoformat(),
        "day": DAY_NAMES[dow],
        "weekday_num": dow,
        "is_weekday": dow < 5,
        "is_trading_day": dow < 5,  # holidays not tracked yet
    }


def days_ago(n):
    """Return date info for N days ago."""
    d = date.today() - timedelta(days=n)
    dow = d.weekday()
    return {
        "date": d.isoformat(),
        "day": DAY_NAMES[dow],
        "weekday_num": dow,
        "is_weekday": dow < 5,
        "is_trading_day": dow < 5,
    }


def last_trading_day():
    """Return the most recent trading day (today if weekday, else last Friday)."""
    d = date.today()
    dow = d.weekday()
    if dow == 5:       # Saturday → Friday
        d -= timedelta(days=1)
    elif dow == 6:     # Sunday → Friday
        d -= timedelta(days=2)
    return {
        "date": d.isoformat(),
        "day": DAY_NAMES[d.weekday()],
        "weekday_num": d.weekday(),
        "is_weekday": True,
        "is_trading_day": True,
    }


def next_trading_day():
    """Return the next trading day (today if weekday, else Monday)."""
    d = date.today()
    dow = d.weekday()
    if dow == 5:       # Saturday → Monday
        d += timedelta(days=2)
    elif dow == 6:     # Sunday → Monday
        d += timedelta(days=1)
    return {
        "date": d.isoformat(),
        "day": DAY_NAMES[d.weekday()],
        "weekday_num": d.weekday(),
    }


def now_local():
    """Return current local date and time (user's timezone)."""
    now = datetime.now()
    return {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "day": DAY_NAMES[now.weekday()],
        "timezone": "local",
    }


def now_market():
    """Return current date and time in US Eastern (market timezone)."""
    now = datetime.now(ET)
    return {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "day": DAY_NAMES[now.weekday()],
        "timezone": "ET",
    }


def format_summary():
    """Human-readable summary: local time, market time, dates."""
    t = today_info()
    lt = last_trading_day()
    nt = next_trading_day()
    local = now_local()
    market = now_market()
    lines = [
        f"Your time:          {local['day']}, {local['date']} {local['time']}",
        f"Market time (ET):   {market['day']}, {market['date']} {market['time']}",
        f"Markets open today: {'Yes' if t['is_trading_day'] else 'No'}",
        f"Last trading day:   {lt['day']}, {lt['date']}",
        f"Next trading day:   {nt['day']}, {nt['date']}",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    if "--ago" in sys.argv:
        idx = sys.argv.index("--ago")
        n = int(sys.argv[idx + 1])
        info = days_ago(n)
        print(f"{n} days ago: {info['day']}, {info['date']} "
              f"({'trading day' if info['is_trading_day'] else 'weekend'})")
    elif "--last-trading" in sys.argv:
        info = last_trading_day()
        print(f"Last trading day: {info['day']}, {info['date']}")
    elif "--next-trading" in sys.argv:
        info = next_trading_day()
        print(f"Next trading day: {info['day']}, {info['date']}")
    else:
        print(format_summary())
