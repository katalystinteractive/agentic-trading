"""Shared utilities for Capital Intelligence tools."""

import json
import math
import re
import statistics
from datetime import date, datetime
from pathlib import Path
from neural_artifact_validator import ArtifactValidationError, load_validated_json


def load_json(path):
    """Load a JSON file. Returns empty dict if file doesn't exist."""
    if isinstance(path, str):
        path = Path(path)
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Pool allocation gatekeeper — SINGLE source of truth for pool sizes
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
_MULTI_PERIOD_PATH = _ROOT / "data" / "backtest" / "multi-period" / "multi-period-results.json"
_PORTFOLIO_PATH = _ROOT / "portfolio.json"

# Default fallback pools (from portfolio.json capital section)
_DEFAULT_ACTIVE = 300
_DEFAULT_RESERVE = 300


_mp_cache = {"data": None, "mtime": 0}  # file-level cache for multi-period data


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value, low, high):
    return max(low, min(high, value))


def _probability(value):
    value = _as_float(value)
    if value > 1:
        value /= 100.0
    return _clamp(value, 0.0, 1.0)


def _round_broker_shares(shares, price):
    if price >= 150:
        return max(0.1, round(shares * 10) / 10)
    return max(1, int(round(shares)))


def compute_allocation_signal(features=None, score=None):
    """Return risk-adjusted allocation multiplier and explanation fields.

    This is the shared capital-sizing contract used by bullet plans, live
    support alerts, dip recommendations, and order adjustment reports.
    """
    features = features or {}
    score = score or {}
    components = score.get("edge_components") or {}

    expected_edge_pct = _as_float(
        score.get("expected_edge_pct", features.get("expected_edge_pct")),
        default=None,
    )
    if expected_edge_pct is None:
        hold_rate = _probability(features.get("hold_rate"))
        target_pct = _as_float(features.get("target_pct"), 6.0)
        stop_pct = abs(_as_float(features.get("stop_pct"), 3.0))
        expected_edge_pct = hold_rate * target_pct - (1.0 - hold_rate) * stop_pct

    confidence = components.get("confidence")
    if confidence is None:
        trades = _as_float(features.get("trade_count"))
        approaches = _as_float(features.get("approaches"))
        confidence = _clamp(math.sqrt(max(trades, approaches, 1.0) / 8.0), 0.2, 1.0)
    confidence = _clamp(_as_float(confidence), 0.0, 1.0)

    stop_risk = components.get("p_stop")
    if stop_risk is None:
        stop_risk = features.get("stop_hit_rate")
    stop_risk = _probability(stop_risk)

    fill_likelihood = features.get("fill_likelihood")
    if fill_likelihood is None:
        distance_pct = _as_float(features.get("distance_pct"))
        proximity_pct = max(0.1, _as_float(features.get("proximity_pct"), 5.0))
        touch_freq = _as_float(features.get("monthly_touch_freq"), 1.0)
        distance_factor = _clamp(1.0 - max(0.0, distance_pct) / proximity_pct, 0.25, 1.0)
        freq_factor = _clamp(touch_freq / 2.0, 0.35, 1.0)
        fill_likelihood = distance_factor * freq_factor
    fill_likelihood = _clamp(_as_float(fill_likelihood), 0.0, 1.0)

    hold_days = _as_float(features.get("median_hold_days"))
    hold_penalty = _clamp(hold_days / 90.0, 0.0, 0.35)
    dormant_penalty = 0.45 if features.get("dormant") else 0.0

    edge_factor = _clamp(1.0 + expected_edge_pct / 10.0, 0.35, 1.75)
    confidence_factor = 0.45 + confidence * 0.55
    fill_factor = 0.65 + fill_likelihood * 0.35
    risk_factor = _clamp(1.0 - stop_risk * 0.55 - hold_penalty - dormant_penalty, 0.25, 1.0)
    multiplier = _clamp(edge_factor * confidence_factor * fill_factor * risk_factor, 0.15, 1.75)

    reasons = []
    reasons.append(f"edge {expected_edge_pct:+.1f}%")
    reasons.append(f"confidence {confidence:.0%}")
    reasons.append(f"fill {fill_likelihood:.0%}")
    if stop_risk:
        reasons.append(f"stop risk {stop_risk:.0%}")
    if hold_penalty:
        reasons.append(f"hold penalty {hold_penalty:.0%}")
    if dormant_penalty:
        reasons.append("dormant penalty")
    if multiplier >= 1.15:
        action = "increased"
    elif multiplier <= 0.85:
        action = "reduced"
    else:
        action = "baseline"
    return {
        "allocation_multiplier": round(multiplier, 3),
        "allocation_action": action,
        "allocation_reason": "; ".join(reasons),
        "expected_edge_pct": round(expected_edge_pct, 3),
        "confidence": round(confidence, 3),
        "fill_likelihood": round(fill_likelihood, 3),
        "stop_risk": round(stop_risk, 3),
    }


def compute_position_allocation(base_dollars, price, features=None, score=None,
                                min_dollars=0.0, max_dollars=None):
    """Size one candidate from a base dollar amount and risk/edge signal."""
    price = _as_float(price)
    base_dollars = max(0.0, _as_float(base_dollars))
    signal = compute_allocation_signal(features=features, score=score)
    dollars = base_dollars * signal["allocation_multiplier"]
    if max_dollars is not None:
        dollars = min(dollars, _as_float(max_dollars))
    dollars = max(_as_float(min_dollars), dollars)
    if price <= 0 or dollars <= 0:
        shares = 0
        cost = 0.0
    else:
        shares = _round_broker_shares(dollars / price, price)
        cost = round(shares * price, 2)
    return {
        **signal,
        "base_dollars": round(base_dollars, 2),
        "allocated_dollars": round(dollars, 2),
        "shares": shares,
        "cost": cost,
    }


def compute_support_level_score(level, *, current_price=None, proximity_pct=5.0,
                                target_pct=6.0, stop_pct=3.0,
                                allocated_dollars=None, pool_budget=None):
    """Score one support level by expected recovery quality, not just distance."""
    level = level or {}
    buy_at = _as_float(
        level.get("buy_at", level.get("recommended_buy", level.get("support")))
    )
    price = _as_float(current_price, level.get("current_price", 0))
    if price <= 0:
        price = _as_float(level.get("price"), buy_at)
    distance_pct = level.get("distance_pct")
    if distance_pct is None and buy_at > 0 and price > 0:
        distance_pct = (price - buy_at) / buy_at * 100
    distance_pct = max(0.0, _as_float(distance_pct))

    hold_rate = _probability(level.get("decayed_hold_rate", level.get("hold_rate", 0)))
    raw_hold_rate = _probability(level.get("hold_rate", hold_rate))
    recent_hold = level.get("recent_hold_pct")
    recent_hold_rate = _probability(recent_hold) if recent_hold is not None else hold_rate
    monthly_touch_freq = _as_float(level.get("monthly_touch_freq"))
    recent_approaches = _as_float(level.get("recent_approaches"))
    approaches = _as_float(level.get("approaches", level.get("total_approaches")))

    tier = level.get("effective_tier", level.get("tier", "Std"))
    tier_bonus = {"Full": 6.0, "Std": 2.5, "Half": -5.0}.get(tier, -10.0)
    zone = level.get("zone", "Active")
    zone_bonus = {"Active": 3.0, "Reserve": -2.0, "Buffer": -6.0}.get(zone, -4.0)
    trend = level.get("trend", "")
    trend_bonus = {"Improving": 4.0, "Stable": 0.0, "Deteriorating": -8.0}.get(trend, 0.0)

    p_target = _clamp((hold_rate * 0.65) + (recent_hold_rate * 0.25) + (raw_hold_rate * 0.10), 0.0, 1.0)
    p_break = _clamp(1.0 - p_target, 0.0, 1.0)
    fill_likelihood = _clamp(
        (1.0 - distance_pct / max(0.1, proximity_pct)) * 0.65
        + _clamp(monthly_touch_freq / 2.0, 0.0, 1.0) * 0.35,
        0.0,
        1.0,
    )
    expected_edge_pct = p_target * _as_float(target_pct, 6.0) - p_break * abs(_as_float(stop_pct, 3.0))

    dormant_penalty = 18.0 if level.get("dormant") else 0.0
    low_frequency_penalty = max(0.0, 1.0 - monthly_touch_freq) * 5.0
    confidence_penalty = max(0.0, 3.0 - max(approaches, recent_approaches)) * 2.0
    distance_penalty = min(12.0, distance_pct * 1.6)
    capital_lock_penalty = 0.0
    if allocated_dollars is not None and pool_budget:
        capital_lock_penalty = min(8.0, _as_float(allocated_dollars) / max(1.0, _as_float(pool_budget)) * 8.0)

    score = (
        50.0
        + expected_edge_pct * 5.0
        + fill_likelihood * 10.0
        + tier_bonus
        + zone_bonus
        + trend_bonus
        - dormant_penalty
        - low_frequency_penalty
        - confidence_penalty
        - distance_penalty
        - capital_lock_penalty
    )
    score = _clamp(score, 0.0, 100.0)
    return {
        "support_score": round(score, 1),
        "support_expected_edge_pct": round(expected_edge_pct, 3),
        "support_score_components": {
            "p_target": round(p_target, 3),
            "p_break": round(p_break, 3),
            "fill_likelihood": round(fill_likelihood, 3),
            "distance_pct": round(distance_pct, 3),
            "tier_bonus": round(tier_bonus, 3),
            "zone_bonus": round(zone_bonus, 3),
            "trend_bonus": round(trend_bonus, 3),
            "dormant_penalty": round(dormant_penalty, 3),
            "low_frequency_penalty": round(low_frequency_penalty, 3),
            "confidence_penalty": round(confidence_penalty, 3),
            "capital_lock_penalty": round(capital_lock_penalty, 3),
        },
    }


def _load_mp_data():
    """Load multi-period data with file-modification-time caching.
    Returns the parsed JSON dict or None if file doesn't exist.
    """
    try:
        if not _MULTI_PERIOD_PATH.exists():
            return None
        mtime = _MULTI_PERIOD_PATH.stat().st_mtime
        if _mp_cache["data"] is not None and _mp_cache["mtime"] == mtime:
            return _mp_cache["data"]
        with open(_MULTI_PERIOD_PATH) as f:
            data = json.load(f)
        _mp_cache["data"] = data
        _mp_cache["mtime"] = mtime
        return data
    except (json.JSONDecodeError, OSError):
        return None


def get_ticker_pool(ticker):
    """Get the allocated pool size for a ticker.

    Priority:
    1. multi-period-results.json (simulation-backed allocation)
    2. neural_support_candidates.json (per-ticker learned pool sizing)
    3. portfolio.json capital section (static default)
    4. hardcoded $300/$300

    This function is the ONLY way to look up pool sizes.
    multi-period-results.json is written ONLY by multi_period_scorer.py.
    No agent can modify pool allocations.

    Returns: {active_pool: float, reserve_pool: float, source: str}
    """
    # Load bullet counts from support sweep (most authoritative for active_bullets_max)
    _ss_bullets = {}
    try:
        _ss_path = Path(__file__).resolve().parent.parent / "data" / "support_sweep_results.json"
        if _ss_path.exists():
            _ss = load_validated_json(_ss_path)
            _ss_entry = _ss.get(ticker, {}).get("params", {})
            if _ss_entry.get("active_bullets_max") is not None:
                _ss_bullets = {
                    "active_bullets_max": _ss_entry["active_bullets_max"],
                    "reserve_bullets_max": _ss_entry.get("reserve_bullets_max"),
                }
    except (FileNotFoundError, json.JSONDecodeError, ArtifactValidationError):
        pass

    # Try simulation-backed allocation first (cached read)
    mp_data = _load_mp_data()
    if mp_data is not None:
        alloc = mp_data.get("allocations", {}).get(ticker)
        if alloc:
            result = {
                "active_pool": alloc.get("active_pool", _DEFAULT_ACTIVE),
                "reserve_pool": alloc.get("reserve_pool", _DEFAULT_RESERVE),
                "total_pool": alloc.get("total_pool", _DEFAULT_ACTIVE + _DEFAULT_RESERVE),
                "active_bullets_max": alloc.get("active_bullets_max"),
                "reserve_bullets_max": alloc.get("reserve_bullets_max"),
                "source": "multi-period-scorer",
                "composite": mp_data.get("composites", {}).get(ticker),
            }
            # Supplement bullet counts from support sweep if multi-period has None
            if result["active_bullets_max"] is None and _ss_bullets:
                result["active_bullets_max"] = _ss_bullets["active_bullets_max"]
                result["reserve_bullets_max"] = result["reserve_bullets_max"] or _ss_bullets.get("reserve_bullets_max")
            return result

    # Check neural watchlist profiles (guaranteed for every tracked ticker)
    try:
        wl_path = Path(__file__).resolve().parent.parent / "data" / "neural_watchlist_profiles.json"
        if wl_path.exists():
            wl_data = load_validated_json(wl_path)
            for c in wl_data.get("candidates", []):
                if c["ticker"] == ticker:
                    params = c.get("params", {})
                    ap = params.get("active_pool", _DEFAULT_ACTIVE)
                    rp = params.get("reserve_pool", _DEFAULT_RESERVE)
                    return {
                        "active_pool": ap,
                        "reserve_pool": rp,
                        "total_pool": ap + rp,
                        "active_bullets_max": params.get("active_bullets_max"),
                        "reserve_bullets_max": params.get("reserve_bullets_max"),
                        "source": "neural_watchlist",
                        "composite": None,
                    }
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ArtifactValidationError):
        pass

    # Check neural support candidates (candidate discovery fallback)
    try:
        ns_path = Path(__file__).resolve().parent.parent / "data" / "neural_support_candidates.json"
        if ns_path.exists():
            ns_data = load_validated_json(ns_path)
            for c in ns_data.get("candidates", []):
                if c["ticker"] == ticker:
                    params = c.get("params", {})
                    ap = params.get("active_pool", _DEFAULT_ACTIVE)
                    rp = params.get("reserve_pool", _DEFAULT_RESERVE)
                    return {
                        "active_pool": ap,
                        "reserve_pool": rp,
                        "total_pool": ap + rp,
                        "active_bullets_max": params.get("active_bullets_max"),
                        "reserve_bullets_max": params.get("reserve_bullets_max"),
                        "source": "neural_support",
                        "composite": None,
                    }
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ArtifactValidationError):
        pass

    # Fallback to portfolio.json static defaults
    try:
        with open(_PORTFOLIO_PATH) as f:
            portfolio = json.load(f)
        cap = portfolio.get("capital", {})
        return {
            "active_pool": cap.get("active_pool", _DEFAULT_ACTIVE),
            "reserve_pool": cap.get("reserve_pool", _DEFAULT_RESERVE),
            "total_pool": cap.get("active_pool", _DEFAULT_ACTIVE) + cap.get("reserve_pool", _DEFAULT_RESERVE),
            "active_bullets_max": cap.get("active_bullets_max"),
            "reserve_bullets_max": cap.get("reserve_bullets_max"),
            "source": "portfolio.json (default)",
            "composite": None,
        }
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "active_pool": _DEFAULT_ACTIVE,
            "reserve_pool": _DEFAULT_RESERVE,
            "total_pool": _DEFAULT_ACTIVE + _DEFAULT_RESERVE,
            "active_bullets_max": None,
            "reserve_bullets_max": None,
            "source": "hardcoded fallback",
            "composite": None,
        }


def get_all_ticker_pools(tickers):
    """Get pool allocations for multiple tickers. Single file read.
    Returns: {ticker: pool_dict}
    """
    return {tk: get_ticker_pool(tk) for tk in tickers}


def get_strategy_type(ticker, min_active_levels=3):
    """Classify ticker as 'surgical' or 'daily_range' based on active level count.

    Reads cached wick_analysis.md (fast, no yfinance call).
    Returns: (strategy_type, active_count)
      - 'surgical': ≥3 active levels with valid tier
      - 'daily_range': 1-2 active levels (insufficient for bullet stacking)
      - 'unknown': no wick data available (file missing or empty)
    """
    from shared_wick import parse_wick_active_levels
    levels = parse_wick_active_levels(ticker)
    active_count = len([l for l in levels if l["tier"] not in ("Skip", "")])
    if active_count == 0 and not levels:
        return "unknown", 0
    strategy_type = "surgical" if active_count >= min_active_levels else "daily_range"
    return strategy_type, active_count


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
    """Parse bullet label from order note.

    New notes use F1/F2 for fill sequence. Legacy notes may still use A/B/R or
    Bullet/Reserve prefixes; keep accepting those so current portfolio data
    remains readable.
    """
    if not note:
        return "F?"
    # Take text before em dash
    prefix = note.split("\u2014")[0].split("—")[0].strip()
    # "BN reserve" → RN
    m = re.match(r"B(\d+)\s+reserve", prefix, re.IGNORECASE)
    if m:
        return f"R{m.group(1)}"
    m = re.match(r"F(\d+)", prefix, re.IGNORECASE)
    if m:
        return f"F{m.group(1)}"
    # Legacy A/B active labels normalize to F fill sequence.
    m = re.match(r"[AB](\d+)", prefix, re.IGNORECASE)
    if m:
        return f"F{m.group(1)}"
    m = re.match(r"R(\d+)", prefix, re.IGNORECASE)
    if m:
        return f"R{m.group(1)}"
    # "Bullets N+M"
    m = re.match(r"Bullets?\s+(\d+\+\d+)", prefix, re.IGNORECASE)
    if m:
        return f"F{m.group(1)}"
    # "Reserve N"
    m = re.match(r"Reserve\s+(\d+)", prefix, re.IGNORECASE)
    if m:
        return f"R{m.group(1)}"
    # "Bullet N"
    m = re.match(r"Bullet\s+(\d+)", prefix, re.IGNORECASE)
    if m:
        return f"F{m.group(1)}"
    return "F?"


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
    result = {
        "total_cycles": stats.get("total_cycles", 0),
        "median_deep": stats.get("median_deep"),
        "median_first": stats.get("median_first"),
        "max_deep": stats.get("max_deep"),
        "immediate_fill_pct": stats.get("immediate_fill_pct", 0),
        "stale": False,
    }

    # Freshness check: flag if data is > 14 days old
    last_date = ct.get("last_date")
    if last_date:
        try:
            from datetime import datetime, date
            ct_date = datetime.strptime(last_date[:10], "%Y-%m-%d").date()
            age = (date.today() - ct_date).days
            if age > 14:
                result["stale"] = True
        except (ValueError, TypeError):
            pass

    return result


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


# ---------------------------------------------------------------------------
# Momentum classification (from morning_verifier.py:364-395)
# ---------------------------------------------------------------------------

def classify_momentum(rsi, macd_vs_signal, histogram):
    """Deterministic momentum classification from RSI + MACD.

    Args:
        rsi: RSI value (float) or None
        macd_vs_signal: "above" or "below" or None
        histogram: MACD histogram value (float) or None

    Returns: 'Bullish' | 'Bearish' | 'Neutral' | 'SKIPPED'
    """
    if rsi is None or macd_vs_signal is None:
        return "SKIPPED"

    # Bearish: RSI < 40 unconditionally, or bearish MACD confluence
    if rsi < 40:
        return "Bearish"
    if macd_vs_signal == "below" and histogram is not None and histogram < 0 and rsi <= 50:
        return "Bearish"

    # Bullish: RSI > 50 AND MACD above signal
    if rsi > 50 and macd_vs_signal == "above":
        return "Bullish"

    # Conflicting: RSI > 50 but MACD bearish
    if rsi > 50 and macd_vs_signal == "below":
        return "SKIPPED"

    return "Neutral"


# ---------------------------------------------------------------------------
# Recovery position classification (from exit_review_pre_analyst.py:375-396)
# ---------------------------------------------------------------------------

RECOVERY_KEYWORDS = ["recovery", "pre-strategy", "underwater", "pre-"]


def is_recovery_position(note, entry_date=None, pl_pct=None):
    """Deterministic recovery classification from portfolio.json fields.

    Args:
        note: position note string from portfolio.json
        entry_date: entry_date string (if starts with 'pre-' → recovery)
        pl_pct: current P/L % (if > 0, reclassify as NOT recovery)

    Returns: bool
    """
    if pl_pct is not None and pl_pct > 0:
        return False  # profitable = not recovery regardless of note

    note_lower = (note or "").lower()
    for kw in RECOVERY_KEYWORDS:
        if kw in note_lower:
            return True

    if entry_date and str(entry_date).startswith("pre-"):
        return True

    return False


# ---------------------------------------------------------------------------
# Verdict engine — 13 mechanizable rules + 3 REVIEW (from morning_verifier.py:755-932)
# ---------------------------------------------------------------------------

def compute_verdict(avg_cost, current_price, entry_date, note,
                    earnings_gate_status, momentum_label, regime,
                    as_of_date=None):
    """First-match-wins verdict engine for active positions.

    Args:
        avg_cost: position average cost
        current_price: live price
        entry_date: entry date string from portfolio.json
        note: position note string
        earnings_gate_status: from earnings_gate.py — 'CLEAR', 'APPROACHING', 'BLOCKED', 'FALLING_KNIFE'
        momentum_label: from classify_momentum() — 'Bullish', 'Bearish', 'Neutral', 'SKIPPED'
        regime: from shared_regime — 'Risk-On', 'Neutral', 'Risk-Off'
        as_of_date: reference date (default: today)

    Returns: (verdict, rule, detail)
        verdict: 'EXIT' | 'REDUCE' | 'HOLD' | 'MONITOR' | 'REVIEW'
        rule: rule identifier (e.g., 'R1', 'R11')
        detail: human-readable explanation
    """
    from datetime import date as date_type

    if as_of_date is None:
        as_of_date = date_type.today()

    # Compute P/L %
    pl_pct = (current_price - avg_cost) / avg_cost * 100 if avg_cost > 0 else 0

    # Compute time stop
    days_held, _, is_pre = compute_days_held(str(entry_date), as_of_date)
    time_status = compute_time_stop(days_held, is_pre, regime)

    # Compute recovery
    recovery = is_recovery_position(note, str(entry_date), pl_pct)

    # Earnings gate
    is_gated = earnings_gate_status in ("BLOCKED", "FALLING_KNIFE")
    is_approaching = earnings_gate_status == "APPROACHING"

    # Momentum
    bearish = momentum_label == "Bearish"

    # --- RULES (first match wins) ---

    # Rules 1-5: GATED positions
    if is_gated:
        if not recovery and pl_pct > 0:
            return ("REDUCE", "R1", f"GATED + profitable ({pl_pct:+.1f}%) → take profit before event")
        if not recovery and pl_pct <= 0:
            return ("HOLD", "R2", f"GATED + underwater ({pl_pct:+.1f}%) → hold through event")
        # Recovery + GATED: rules 3-5 (Rule 3 needs thesis = REVIEW)
        if recovery:
            return ("REVIEW", "R3", f"Recovery + GATED — needs thesis evaluation (P/L {pl_pct:+.1f}%)")

    # Rules 6-6a: Profit targets
    if pl_pct >= 12:
        return ("REDUCE", "R6a", f"P/L {pl_pct:+.1f}% ≥ 12% — take partial profit")
    if 10 <= pl_pct < 12:
        return ("HOLD", "R6", f"P/L {pl_pct:+.1f}% at target (10-12%) — hold for full target")
    if 7 <= pl_pct < 10:
        return ("HOLD", "R7", f"P/L {pl_pct:+.1f}% approaching target (7-10%)")

    # Rules 8-10: Recovery positions (non-GATED)
    if recovery and not is_gated:
        return ("REVIEW", "R8-10", f"Recovery position ({pl_pct:+.1f}%) — needs momentum/thesis analysis")

    # Rules 11-16: Time stop + momentum
    if time_status == "EXCEEDED":
        if bearish and not is_approaching:
            return ("EXIT", "R11", f"Time EXCEEDED + bearish momentum + earnings CLEAR")
        if is_approaching:
            return ("REDUCE", "R13", f"Time EXCEEDED + earnings APPROACHING — reduce before event")
        if not bearish:
            return ("HOLD", "R14", f"Time EXCEEDED but momentum not bearish ({momentum_label})")

    if time_status == "APPROACHING":
        return ("MONITOR", "R15", f"Time APPROACHING ({days_held}d) — monitor for exit trigger")

    # Rule 16: Time WITHIN
    return ("MONITOR", "R16", f"Time WITHIN ({days_held}d) — on track")


# ---------------------------------------------------------------------------
# Entry gate logic (from morning_verifier.py:1085-1191)
# ---------------------------------------------------------------------------

GATE_PRIORITY = {"ACTIVE": 0, "CAUTION": 1, "REVIEW": 2, "PAUSE": 3}


def compute_entry_gate(regime, vix, vix_5d_pct, earnings_gate_status,
                       order_price, current_price, is_watchlist=False):
    """Combined market + earnings gate per pending order.

    Args:
        regime: from shared_regime — 'Risk-On', 'Neutral', 'Risk-Off'
        vix: current VIX value (float) or None
        vix_5d_pct: 5-day VIX change % (float) or None
        earnings_gate_status: from earnings_gate.py
        order_price: limit order price
        current_price: live price
        is_watchlist: True if ticker is watchlist-only (no position)

    Returns: (market_gate, earnings_gate, combined_gate)
    """
    # Market gate
    if regime == "Risk-On":
        market_gate = "ACTIVE"
    elif regime == "Risk-Off":
        if is_watchlist:
            market_gate = "PAUSE"
        else:
            # Active position: REVIEW unless order is deep (>15% below)
            pct_below = (current_price - order_price) / current_price * 100
            market_gate = "ACTIVE" if pct_below > 15 else "REVIEW"
    else:  # Neutral
        if vix is not None and 20 <= vix <= 25 and vix_5d_pct is not None and vix_5d_pct > 0:
            market_gate = "CAUTION"
        else:
            market_gate = "ACTIVE"

    # Earnings gate mapping
    eg_map = {
        "CLEAR": "ACTIVE",
        "APPROACHING": "REVIEW",
        "BLOCKED": "PAUSE",
        "FALLING_KNIFE": "PAUSE",
    }
    earnings_mapped = eg_map.get(earnings_gate_status, "ACTIVE")

    # Combined = worst of both
    m_pri = GATE_PRIORITY.get(market_gate, 0)
    e_pri = GATE_PRIORITY.get(earnings_mapped, 0)
    if m_pri >= e_pri:
        combined = market_gate
    else:
        combined = earnings_mapped

    return market_gate, earnings_mapped, combined


# ---------------------------------------------------------------------------
# Projected sell scenarios
# ---------------------------------------------------------------------------

def compute_sell_scenarios(shares, avg_cost, pending_buys, sell_target_pct=6.0):
    """What-if table: current position + each pending fill scenario.

    Args:
        shares: current position shares (int)
        avg_cost: current average cost (float)
        pending_buys: list of {price: float, shares: int} from portfolio.json
        sell_target_pct: exit target % (default 6.0)

    Returns: list of dicts, one per scenario:
        {scenario, total_shares, new_avg, sell_price, pl_pct, pl_dollars}
    """
    scenarios = []

    # Current position
    if shares > 0:
        sell_price = round(avg_cost * (1 + sell_target_pct / 100), 2)
        pl_dollars = round(shares * (sell_price - avg_cost), 2)
        scenarios.append({
            "scenario": "Current",
            "total_shares": shares,
            "new_avg": round(avg_cost, 2),
            "sell_price": sell_price,
            "pl_pct": round(sell_target_pct, 1),
            "pl_dollars": pl_dollars,
        })

    # What-if for each pending fill (cumulative)
    running_shares = shares
    running_cost = shares * avg_cost

    for i, order in enumerate(pending_buys, 1):
        o_price = order.get("price", 0)
        o_shares = order.get("shares", 0)
        if o_price <= 0 or o_shares <= 0:
            continue

        running_shares += o_shares
        running_cost += o_shares * o_price
        new_avg = running_cost / running_shares
        sell_price = round(new_avg * (1 + sell_target_pct / 100), 2)
        pl_dollars = round(running_shares * (sell_price - new_avg), 2)

        scenarios.append({
            "scenario": f"+Fill #{i} (${o_price:.2f}×{o_shares})",
            "total_shares": running_shares,
            "new_avg": round(new_avg, 2),
            "sell_price": sell_price,
            "pl_pct": round(sell_target_pct, 1),
            "pl_dollars": pl_dollars,
        })

    return scenarios
