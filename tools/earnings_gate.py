"""Earnings Gate — blocks buy orders within 7 days before and 3 days after earnings.

Returns gate status for a ticker:
- BLOCKED: within blackout window (7d before through 3d after)
- FALLING_KNIFE: post-settling but price >5% below pre-earnings close
- APPROACHING: 8-14 days before earnings (warning, not blocked)
- CLEAR: no earnings concern

Usage:
    from earnings_gate import check_earnings_gate
    gate = check_earnings_gate("ACHR")
    if gate["blocked"]:
        print(f"EARNINGS GATE: {gate['reason']}")
"""
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# Gate parameters
PRE_EARNINGS_DAYS = 7    # block 7 days before earnings
POST_EARNINGS_DAYS = 3   # block 3 days after earnings
APPROACHING_DAYS = 14    # warning zone
FALLING_KNIFE_PCT = 5.0  # >5% below pre-earnings close = falling knife


def _fetch_earnings_date(ticker):
    """Fetch next and most recent earnings date from yfinance."""
    import yfinance as yf
    try:
        t = yf.Ticker(ticker)
        ed = t.earnings_dates
        if ed is None or ed.empty:
            return None, None

        now = datetime.now()
        future = []
        past = []

        for dt in ed.index:
            earn_dt = dt.to_pydatetime().replace(tzinfo=None)
            if earn_dt.date() >= now.date():
                future.append(earn_dt.date())
            else:
                past.append(earn_dt.date())

        next_earn = min(future) if future else None
        last_earn = max(past) if past else None
        return next_earn, last_earn
    except Exception:
        return None, None


def _get_pre_earnings_close(ticker, earnings_date):
    """Get the closing price on the day before earnings."""
    import yfinance as yf
    try:
        start = earnings_date - timedelta(days=5)
        end = earnings_date
        hist = yf.Ticker(ticker).history(start=str(start), end=str(end))
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def _get_current_price(ticker):
    """Get current/latest price."""
    import yfinance as yf
    try:
        hist = yf.Ticker(ticker).history(period="2d")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def check_earnings_gate(ticker, as_of_date=None):
    """Check earnings gate status for a ticker.

    Args:
        ticker: stock symbol
        as_of_date: date to check (default: today)

    Returns dict:
        blocked: bool — True if orders should be blocked
        status: str — BLOCKED, FALLING_KNIFE, APPROACHING, CLEAR
        reason: str — human-readable explanation
        earnings_date: str or None — the relevant earnings date
        days_to_earnings: int or None — days until next earnings
        days_since_earnings: int or None — days since last earnings
    """
    today = as_of_date or date.today()
    next_earn, last_earn = _fetch_earnings_date(ticker)

    result = {
        "blocked": False,
        "status": "CLEAR",
        "reason": "No earnings concern",
        "earnings_date": None,
        "days_to_earnings": None,
        "days_since_earnings": None,
    }

    # Check pre-earnings gate (next earnings)
    if next_earn:
        days_to = (next_earn - today).days
        result["earnings_date"] = str(next_earn)
        result["days_to_earnings"] = days_to

        if days_to <= 0:
            # Earnings is today — blocked
            result["blocked"] = True
            result["status"] = "BLOCKED"
            result["reason"] = f"Earnings TODAY ({next_earn})"
            return result

        if days_to <= PRE_EARNINGS_DAYS:
            result["blocked"] = True
            result["status"] = "BLOCKED"
            result["reason"] = f"Earnings in {days_to}d ({next_earn}) — within {PRE_EARNINGS_DAYS}d blackout"
            return result

        if days_to <= APPROACHING_DAYS:
            result["status"] = "APPROACHING"
            result["reason"] = f"Earnings in {days_to}d ({next_earn}) — approaching blackout"
            return result

    # Check post-earnings gate (last earnings)
    if last_earn:
        days_since = (today - last_earn).days
        result["days_since_earnings"] = days_since
        result["earnings_date"] = result["earnings_date"] or str(last_earn)

        if days_since <= POST_EARNINGS_DAYS:
            result["blocked"] = True
            result["status"] = "BLOCKED"
            result["reason"] = f"Earnings {days_since}d ago ({last_earn}) — within {POST_EARNINGS_DAYS}d settling"
            return result

        # Falling knife check: post-settling but still falling
        if days_since <= POST_EARNINGS_DAYS + 7:  # check for 10 days after earnings
            pre_close = _get_pre_earnings_close(ticker, last_earn)
            current = _get_current_price(ticker)
            if pre_close and current:
                drop_pct = (pre_close - current) / pre_close * 100
                if drop_pct >= FALLING_KNIFE_PCT:
                    result["blocked"] = True
                    result["status"] = "FALLING_KNIFE"
                    result["reason"] = (
                        f"Post-earnings falling knife: -{drop_pct:.1f}% from "
                        f"pre-earnings ${pre_close:.2f} → ${current:.2f}. "
                        f"Earnings was {last_earn} ({days_since}d ago)"
                    )
                    return result

    return result


def check_earnings_gate_batch(tickers, as_of_date=None):
    """Check earnings gate for multiple tickers. Returns {ticker: gate_result}."""
    results = {}
    for tk in tickers:
        results[tk] = check_earnings_gate(tk, as_of_date)
    return results


def format_gate_warning(gate):
    """Format gate result as a markdown warning string."""
    if gate["status"] == "CLEAR":
        return ""
    if gate["status"] == "BLOCKED":
        return f"**EARNINGS GATE — BLOCKED:** {gate['reason']}"
    if gate["status"] == "FALLING_KNIFE":
        return f"**FALLING KNIFE WARNING:** {gate['reason']}"
    if gate["status"] == "APPROACHING":
        return f"*Earnings approaching: {gate['reason']}*"
    return ""


if __name__ == "__main__":
    """CLI: check earnings gate for one or more tickers."""
    tickers = [t.upper() for t in sys.argv[1:]] if len(sys.argv) > 1 else []
    if not tickers:
        print("Usage: python3 tools/earnings_gate.py ACHR LUNR CIFR")
        sys.exit(1)

    print("## Earnings Gate Check\n")
    print("| Ticker | Status | Earnings | Days | Detail |")
    print("| :--- | :--- | :--- | :--- | :--- |")
    for tk in tickers:
        g = check_earnings_gate(tk)
        days = g["days_to_earnings"] if g["days_to_earnings"] is not None else f"-{g['days_since_earnings']}d ago" if g["days_since_earnings"] else "?"
        print(f"| {tk} | **{g['status']}** | {g['earnings_date'] or '?'} | {days} | {g['reason']} |")
