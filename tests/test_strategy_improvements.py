"""Tests for strategy improvements: time stops, catastrophic alerts, sell target tiers."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from shared_utils import (
    compute_days_held, compute_time_stop,
    TIME_STOP_EXCEEDED_DAYS, TIME_STOP_APPROACHING_DAYS,
)


# ---------------------------------------------------------------------------
# compute_days_held
# ---------------------------------------------------------------------------

class TestComputeDaysHeld:
    def test_normal_date(self):
        days, display, is_pre = compute_days_held("2026-03-01", date(2026, 3, 24))
        assert days == 23
        assert display == "23"
        assert is_pre is False

    def test_pre_strategy(self):
        days, display, is_pre = compute_days_held("pre-2025-12-01", date(2026, 3, 24))
        assert days is None
        assert "pre-strategy" in display
        assert is_pre is True

    def test_invalid_date(self):
        days, display, is_pre = compute_days_held("not-a-date", date(2026, 3, 24))
        assert days is None
        assert display == "Unknown"
        assert is_pre is False

    def test_same_day(self):
        days, _, _ = compute_days_held("2026-03-24", date(2026, 3, 24))
        assert days == 0

    def test_defaults_to_today(self):
        """Without as_of_date, uses date.today()."""
        days, _, _ = compute_days_held("2020-01-01")
        assert days > 2000  # definitely more than 5 years ago


# ---------------------------------------------------------------------------
# compute_time_stop
# ---------------------------------------------------------------------------

class TestComputeTimeStop:
    def test_within(self):
        assert compute_time_stop(30, False) == "WITHIN"

    def test_approaching(self):
        assert compute_time_stop(45, False) == "APPROACHING"

    def test_approaching_boundary(self):
        assert compute_time_stop(44, False) == "WITHIN"

    def test_exceeded(self):
        assert compute_time_stop(61, False) == "EXCEEDED"

    def test_exceeded_boundary(self):
        assert compute_time_stop(60, False) == "APPROACHING"

    def test_pre_strategy_always_exceeded(self):
        assert compute_time_stop(None, True) == "EXCEEDED"
        assert compute_time_stop(10, True) == "EXCEEDED"

    def test_none_days(self):
        assert compute_time_stop(None, False) == "Unknown"

    def test_risk_off_extends_thresholds(self):
        # At 58 days, normally APPROACHING. With Risk-Off (+14), should be WITHIN
        assert compute_time_stop(58, False, regime="Risk-Off") == "WITHIN"
        # At 61 days with Risk-Off: 45+14=59 approaching threshold, 61>=59
        assert compute_time_stop(61, False, regime="Risk-Off") == "APPROACHING"
        # At 75 days with Risk-Off: 60+14=74 exceeded threshold
        assert compute_time_stop(75, False, regime="Risk-Off") == "EXCEEDED"

    def test_risk_off_boundary(self):
        # Exactly at extended exceeded (74): should be APPROACHING (> not >=)
        assert compute_time_stop(74, False, regime="Risk-Off") == "APPROACHING"
        # At 75: exceeded
        assert compute_time_stop(75, False, regime="Risk-Off") == "EXCEEDED"

    def test_neutral_regime_default(self):
        """Default regime is Neutral — standard thresholds."""
        assert compute_time_stop(61, False) == "EXCEEDED"
        assert compute_time_stop(61, False, regime="Neutral") == "EXCEEDED"

    def test_risk_on_same_as_neutral(self):
        assert compute_time_stop(61, False, regime="Risk-On") == "EXCEEDED"

    def test_constants(self):
        assert TIME_STOP_EXCEEDED_DAYS == 60
        assert TIME_STOP_APPROACHING_DAYS == 45


# ---------------------------------------------------------------------------
# Catastrophic drawdown thresholds (unit logic)
# ---------------------------------------------------------------------------

class TestCatastrophicThresholds:
    """Test the threshold logic used in daily_analyzer.print_catastrophic_alerts."""

    WARNING = 15.0
    HARD_STOP = 25.0
    EXIT_REVIEW = 40.0

    def _classify(self, drawdown_pct):
        """Mirror the daily_analyzer classification logic."""
        if drawdown_pct <= -self.EXIT_REVIEW:
            return "EXIT REVIEW"
        elif drawdown_pct <= -self.HARD_STOP:
            return "HARD STOP"
        elif drawdown_pct <= -self.WARNING:
            return "WARNING"
        return None

    def test_no_alert(self):
        assert self._classify(-10.0) is None
        assert self._classify(-14.9) is None
        assert self._classify(5.0) is None

    def test_warning(self):
        assert self._classify(-15.0) == "WARNING"
        assert self._classify(-20.0) == "WARNING"
        assert self._classify(-24.9) == "WARNING"

    def test_hard_stop(self):
        assert self._classify(-25.0) == "HARD STOP"
        assert self._classify(-30.0) == "HARD STOP"
        assert self._classify(-39.9) == "HARD STOP"

    def test_exit_review(self):
        assert self._classify(-40.0) == "EXIT REVIEW"
        assert self._classify(-50.0) == "EXIT REVIEW"

    def test_boundary_15(self):
        assert self._classify(-14.9) is None
        assert self._classify(-15.0) == "WARNING"

    def test_boundary_25(self):
        assert self._classify(-24.9) == "WARNING"
        assert self._classify(-25.0) == "HARD STOP"

    def test_boundary_40(self):
        assert self._classify(-39.9) == "HARD STOP"
        assert self._classify(-40.0) == "EXIT REVIEW"


# ---------------------------------------------------------------------------
# Sell target tier logic (unit)
# ---------------------------------------------------------------------------

class TestSellTargetTiers:
    """Test the graduated tier classification from ticker_perf_analyzer."""

    FAST_MIN_CYCLES = 3
    FAST_MAX_DAYS = 3
    FAST_TARGET = 8.0

    EXCEPTIONAL_MIN_CYCLES = 5
    EXCEPTIONAL_MAX_DAYS = 2
    EXCEPTIONAL_MIN_CAPTURE = 50
    EXCEPTIONAL_TARGET = 10.0

    def _classify(self, cycles, median_days, capture):
        if (cycles >= self.EXCEPTIONAL_MIN_CYCLES
                and median_days is not None
                and median_days <= self.EXCEPTIONAL_MAX_DAYS
                and capture is not None
                and capture >= self.EXCEPTIONAL_MIN_CAPTURE):
            return self.EXCEPTIONAL_TARGET
        if (cycles >= self.FAST_MIN_CYCLES
                and median_days is not None
                and median_days <= self.FAST_MAX_DAYS):
            return self.FAST_TARGET
        return 6.0

    def test_default(self):
        assert self._classify(2, 5, 40) == 6.0

    def test_fast_cycler(self):
        assert self._classify(3, 3, 40) == 8.0

    def test_fast_cycler_boundary(self):
        assert self._classify(3, 4, 40) == 6.0  # median too slow
        assert self._classify(2, 3, 40) == 6.0  # not enough cycles

    def test_exceptional(self):
        assert self._classify(5, 2, 50) == 10.0

    def test_exceptional_boundary(self):
        assert self._classify(5, 2, 49) == 8.0   # capture too low → falls to fast
        assert self._classify(5, 3, 50) == 8.0   # median too slow → falls to fast
        assert self._classify(4, 2, 50) == 8.0   # not enough cycles → falls to fast

    def test_none_median_days(self):
        assert self._classify(5, None, 50) == 6.0  # no duration data → default

    def test_none_capture(self):
        # Exceptional requires capture >= 50, but None capture should fall to fast
        assert self._classify(5, 2, None) == 8.0  # has cycles+speed, no capture → fast
