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


# ---------------------------------------------------------------------------
# Hold rate quality scoring (surgical_filter)
# ---------------------------------------------------------------------------

from surgical_filter import score_hold_quality, MAX_HOLD_QUALITY


class TestScoreHoldQuality:
    """Test score_hold_quality from surgical_filter."""

    def _wick(self, active_levels):
        """Build minimal wick_data with active bullet levels."""
        return {"bullet_plan": {"active": active_levels, "reserve": []}}

    def _level(self, decayed_hr):
        return {"decayed_hold_rate": decayed_hr, "hold_rate": decayed_hr}

    def test_no_reliable_levels(self):
        wick = self._wick([self._level(30), self._level(40)])
        assert score_hold_quality(wick) == 0

    def test_one_reliable(self):
        wick = self._wick([self._level(50), self._level(30)])
        assert score_hold_quality(wick) == 2  # 1 reliable, no floor

    def test_two_reliable(self):
        wick = self._wick([self._level(50), self._level(55)])
        assert score_hold_quality(wick) == 5  # 2 reliable, no floor

    def test_three_reliable(self):
        wick = self._wick([self._level(50), self._level(55), self._level(52)])
        assert score_hold_quality(wick) == 7

    def test_four_reliable(self):
        wick = self._wick([self._level(50), self._level(55), self._level(52), self._level(51)])
        assert score_hold_quality(wick) == 9

    def test_floor_bonus(self):
        wick = self._wick([self._level(60)])
        assert score_hold_quality(wick) == 2 + 6  # 1 reliable + floor

    def test_max_score(self):
        wick = self._wick([self._level(70), self._level(65), self._level(60), self._level(55)])
        assert score_hold_quality(wick) == 15  # 9 + 6 = 15 = MAX

    def test_empty_active(self):
        wick = self._wick([])
        assert score_hold_quality(wick) == 0

    def test_fallback_to_hold_rate(self):
        """When decayed_hold_rate missing, falls back to hold_rate."""
        wick = self._wick([{"hold_rate": 55}])
        assert score_hold_quality(wick) == 2  # 1 reliable, no floor

    def test_floor_at_boundary(self):
        wick = self._wick([self._level(59)])  # below 60% floor threshold
        assert score_hold_quality(wick) == 2  # reliable but no floor bonus

    def test_reliable_at_boundary(self):
        wick = self._wick([self._level(49)])  # below 50% reliable threshold
        assert score_hold_quality(wick) == 0


# ---------------------------------------------------------------------------
# Touch frequency scoring (surgical_filter)
# ---------------------------------------------------------------------------

from surgical_filter import score_touch_frequency, MAX_TOUCH_FREQUENCY


class TestScoreTouchFrequency:
    """Test score_touch_frequency from surgical_filter."""

    def _wick(self, active_freqs):
        """Build minimal wick_data with active levels having given frequencies."""
        levels = [{"zone": "Active", "monthly_touch_freq": f} for f in active_freqs]
        return {"levels": levels, "bullet_plan": {"active": [], "reserve": []}}

    def test_high_frequency(self):
        assert score_touch_frequency(self._wick([3.0, 1.0])) == MAX_TOUCH_FREQUENCY  # 15

    def test_medium_frequency(self):
        assert score_touch_frequency(self._wick([2.0])) == 12

    def test_moderate_frequency(self):
        assert score_touch_frequency(self._wick([1.0, 0.5])) == 8

    def test_low_frequency(self):
        assert score_touch_frequency(self._wick([0.5])) == 4

    def test_zero_frequency(self):
        assert score_touch_frequency(self._wick([0.0, 0.3])) == 0

    def test_no_active_levels(self):
        assert score_touch_frequency({"levels": [], "bullet_plan": {"active": [], "reserve": []}}) == 0

    def test_only_buffer_levels(self):
        wick = {"levels": [{"zone": "Buffer", "monthly_touch_freq": 5.0}],
                "bullet_plan": {"active": [], "reserve": []}}
        assert score_touch_frequency(wick) == 0  # Buffer levels ignored

    def test_max_constant(self):
        assert MAX_TOUCH_FREQUENCY == 15


# ---------------------------------------------------------------------------
# Touch frequency scoring (watchlist_fitness)
# ---------------------------------------------------------------------------

from watchlist_fitness import _score_touch_frequency, TOUCH_FREQUENCY_POINTS


class TestWatchlistTouchFrequency:
    """Test _score_touch_frequency from watchlist_fitness (0-10 scale)."""

    def _data(self, active_freqs):
        return {"levels": [{"zone": "Active", "monthly_touch_freq": f} for f in active_freqs]}

    def test_high_frequency(self):
        pts, freq = _score_touch_frequency(self._data([3.0]))
        assert pts == TOUCH_FREQUENCY_POINTS  # 10
        assert freq == 3.0

    def test_medium_frequency(self):
        pts, _ = _score_touch_frequency(self._data([2.0]))
        assert pts == 8

    def test_moderate_frequency(self):
        pts, _ = _score_touch_frequency(self._data([1.0]))
        assert pts == 5

    def test_low_frequency(self):
        pts, _ = _score_touch_frequency(self._data([0.5]))
        assert pts == 3

    def test_zero_frequency(self):
        pts, _ = _score_touch_frequency(self._data([0.3]))
        assert pts == 0

    def test_no_active_levels(self):
        pts, freq = _score_touch_frequency({"levels": []})
        assert pts == 0
        assert freq == 0

    def test_max_constant(self):
        assert TOUCH_FREQUENCY_POINTS == 10


# ---------------------------------------------------------------------------
# Hold rate quality scoring (watchlist_fitness)
# ---------------------------------------------------------------------------

from watchlist_fitness import _score_hold_rate, HOLD_RATE_POINTS


class TestFitnessHoldRate:
    """Test _score_hold_rate from watchlist_fitness."""

    def _level(self, zone, tier, decayed_hr):
        return {"zone": zone, "effective_tier": tier, "decayed_hold_rate": decayed_hr}

    def test_no_active_levels(self):
        assert _score_hold_rate([]) == 0

    def test_skip_tiers_excluded(self):
        levels = [self._level("Active", "Skip", 60)]
        assert _score_hold_rate(levels) == 0

    def test_non_active_zones_excluded(self):
        levels = [self._level("Buffer", "Full", 60)]
        assert _score_hold_rate(levels) == 0

    def test_one_reliable(self):
        levels = [self._level("Active", "Full", 55)]
        assert _score_hold_rate(levels) == 2

    def test_two_reliable(self):
        levels = [self._level("Active", "Full", 55), self._level("Active", "Std", 52)]
        assert _score_hold_rate(levels) == 4

    def test_three_reliable_plus_floor(self):
        levels = [
            self._level("Active", "Full", 65),
            self._level("Active", "Std", 55),
            self._level("Active", "Half", 50),
        ]
        assert _score_hold_rate(levels) == 6 + 4  # 3 reliable + floor = 10 = max

    def test_max_is_hold_rate_points(self):
        assert HOLD_RATE_POINTS == 10


# ---------------------------------------------------------------------------
# Sector diversity scoring (diminishing-returns curve)
# ---------------------------------------------------------------------------

from surgical_filter import score_sector_diversity, MAX_SECTOR_DIVERSITY


class TestScoreSectorDiversity:
    """Test diminishing-returns sector diversity scoring."""

    def _ctx(self, sector, count):
        """Build portfolio_ctx with `count` existing tickers in `sector`."""
        return {"sectors": {sector: [f"TK{i}" for i in range(count)]}}

    def test_new_sector(self):
        assert score_sector_diversity("NEW", "Biotech", self._ctx("Biotech", 0)) == 10

    def test_second_ticker(self):
        assert score_sector_diversity("NEW", "Crypto", self._ctx("Crypto", 1)) == 8

    def test_third_ticker(self):
        assert score_sector_diversity("NEW", "Crypto", self._ctx("Crypto", 2)) == 8

    def test_fourth_ticker(self):
        assert score_sector_diversity("NEW", "Tech", self._ctx("Tech", 3)) == 6

    def test_sixth_ticker(self):
        assert score_sector_diversity("NEW", "Tech", self._ctx("Tech", 5)) == 6

    def test_seventh_ticker(self):
        assert score_sector_diversity("NEW", "Health", self._ctx("Health", 6)) == 4

    def test_sixteenth_ticker(self):
        assert score_sector_diversity("NEW", "Health", self._ctx("Health", 15)) == 4

    def test_seventeenth_ticker(self):
        assert score_sector_diversity("NEW", "Health", self._ctx("Health", 16)) == 2

    def test_fiftieth_ticker(self):
        assert score_sector_diversity("NEW", "Health", self._ctx("Health", 49)) == 2

    def test_unknown_sector(self):
        assert score_sector_diversity("NEW", "Unknown", {}) == MAX_SECTOR_DIVERSITY

    def test_none_sector(self):
        assert score_sector_diversity("NEW", None, {}) == MAX_SECTOR_DIVERSITY

    def test_empty_sector(self):
        assert score_sector_diversity("NEW", "", {}) == MAX_SECTOR_DIVERSITY

    def test_never_exceeds_max(self):
        """All branches return <= MAX_SECTOR_DIVERSITY."""
        ctx = self._ctx("X", 0)
        for count in range(0, 100):
            ctx = self._ctx("X", count)
            score = score_sector_diversity("NEW", "X", ctx)
            assert score <= MAX_SECTOR_DIVERSITY, f"count={count} returned {score}"
            assert score >= 0, f"count={count} returned negative {score}"

    def test_never_returns_zero(self):
        """Minimum score is 2, never 0."""
        for count in [16, 50, 100, 500]:
            ctx = self._ctx("X", count)
            assert score_sector_diversity("NEW", "X", ctx) >= 2

    def test_max_is_ten(self):
        assert MAX_SECTOR_DIVERSITY == 10


# ---------------------------------------------------------------------------
# Touch frequency metric
# ---------------------------------------------------------------------------

class TestMonthlyTouchFreq:
    """Test monthly_touch_freq computation logic."""

    def test_basic_computation(self):
        """6 recent approaches in 90 days = 2.0/month."""
        assert round(6 / 3.0, 1) == 2.0

    def test_zero_approaches(self):
        assert round(0 / 3.0, 1) == 0.0

    def test_high_frequency(self):
        """24 approaches in 90 days = 8.0/month."""
        assert round(24 / 3.0, 1) == 8.0

    def test_single_approach(self):
        assert round(1 / 3.0, 1) == 0.3


# ---------------------------------------------------------------------------
# Daily range computation
# ---------------------------------------------------------------------------

class TestDailyRange:
    """Test daily range computation logic."""

    def test_range_formula(self):
        """(High - Low) / Low * 100."""
        high, low = 10.5, 10.0
        assert round((high - low) / low * 100, 1) == 5.0

    def test_days_above_3pct(self):
        """Count days with range >= 3%."""
        ranges = [2.0, 3.0, 4.0, 1.5, 5.0, 2.8, 3.1]
        above = sum(1 for r in ranges if r >= 3.0)
        pct = round(above / len(ranges) * 100, 1)
        assert above == 4
        assert pct == 57.1

    def test_all_above(self):
        ranges = [5.0, 6.0, 7.0]
        assert sum(1 for r in ranges if r >= 3.0) == 3

    def test_none_above(self):
        ranges = [1.0, 2.0, 2.5]
        assert sum(1 for r in ranges if r >= 3.0) == 0


# ---------------------------------------------------------------------------
# Dual exit zone detection
# ---------------------------------------------------------------------------

class TestZoneDetection:
    """Test zone label extraction for dual exit routing."""

    def test_a1_is_upper(self):
        import re
        note = "A1 — $15.26 PA, 22% hold, Half^"
        match = re.search(r'\b(A[1-5]|B[1-5]|R[1-3])\b', note)
        assert match is not None
        assert match.group(1) == "A1"
        assert match.group(1) in ("A1", "A2")

    def test_a2_is_upper(self):
        import re
        note = "A2 — $14.12 PA, 60% hold, Full^"
        match = re.search(r'\b(A[1-5]|B[1-5]|R[1-3])\b', note)
        assert match.group(1) == "A2"
        assert match.group(1) in ("A1", "A2")

    def test_b3_is_lower(self):
        import re
        note = "B3 — $10.18 PA, 67% hold, Full"
        match = re.search(r'\b(A[1-5]|B[1-5]|R[1-3])\b', note)
        assert match.group(1) == "B3"
        assert match.group(1) not in ("A1", "A2")

    def test_r1_is_reserve(self):
        import re
        note = "R1 — $8.26 PA, 33% hold, Std"
        match = re.search(r'\b(A[1-5]|B[1-5]|R[1-3])\b', note)
        assert match.group(1) == "R1"
        assert match.group(1) not in ("A1", "A2")

    def test_no_zone_in_note(self):
        import re
        note = "Bullet 1 — some old format note"
        match = re.search(r'\b(A[1-5]|B[1-5]|R[1-3])\b', note)
        assert match is None

    def test_same_day_price(self):
        """Fill price * 1.03 = same-day exit target."""
        fill = 18.18
        target = round(fill * 1.03, 2)
        assert target == 18.73


# ---------------------------------------------------------------------------
# Daily range scoring (parallel score)
# ---------------------------------------------------------------------------

from surgical_filter import score_daily_range


class TestScoreDailyRange:
    """Test daily range viability scoring."""

    def _passer(self, dr=0, days_3=0, recovery=0, ltc=0, swing=0):
        return {
            "median_daily_range": dr,
            "days_above_3pct": days_3,
            "dip_recovery_ratio": recovery,
            "median_low_to_close": ltc,
            "median_swing": swing,
        }

    def test_high_score(self):
        """Strong daily range profile = ~90."""
        p = self._passer(dr=7, days_3=95, recovery=75, ltc=4, swing=25)
        score = score_daily_range(p)
        assert score >= 85

    def test_low_score(self):
        """Weak daily range profile."""
        p = self._passer(dr=1.5, days_3=40, recovery=15, ltc=1, swing=8)
        assert score_daily_range(p) <= 10

    def test_ar_profile(self):
        """AR-like: 3.5% range, 73% days, moderate recovery."""
        p = self._passer(dr=3.5, days_3=73, recovery=55, ltc=2.0, swing=18)
        score = score_daily_range(p)
        assert 40 <= score <= 70  # mid-range

    def test_zero_data(self):
        assert score_daily_range(self._passer()) == 0

    def test_high_range_low_recovery(self):
        """Big swings but doesn't recover = penalized."""
        p = self._passer(dr=8, days_3=95, recovery=15, ltc=1, swing=30)
        score = score_daily_range(p)
        # Range + consistency maxed (50), but recovery low (6), swing good (15)
        assert score <= 75  # recovery drags it down

    def test_max_theoretical(self):
        """Perfect on all criteria = 90 (sector added separately)."""
        p = self._passer(dr=10, days_3=100, recovery=80, ltc=5, swing=30)
        assert score_daily_range(p) == 90  # 25 + 25 + 25 + 15

    def test_recovery_bonus(self):
        """Low-to-close >= 3% adds +5 bonus."""
        p_no_bonus = self._passer(dr=5, days_3=85, recovery=60, ltc=2.5, swing=15)
        p_with_bonus = self._passer(dr=5, days_3=85, recovery=60, ltc=3.5, swing=15)
        assert score_daily_range(p_with_bonus) > score_daily_range(p_no_bonus)


class TestStrategyType:
    """Test strategy type classification."""

    def test_support_wins(self):
        """When support score > daily range, strategy = support."""
        support_total = 75
        daily_range_total = 50
        strategy = "daily_range" if daily_range_total > support_total else "support"
        assert strategy == "support"

    def test_daily_range_wins(self):
        """When daily range > support, strategy = daily_range."""
        support_total = 30
        daily_range_total = 65
        strategy = "daily_range" if daily_range_total > support_total else "support"
        assert strategy == "daily_range"

    def test_effective_score_is_max(self):
        """Effective score = max of both."""
        assert max(75, 50) == 75
        assert max(30, 65) == 65

    def test_tie_goes_to_support(self):
        """Equal scores → support (strict >)."""
        strategy = "daily_range" if 50 > 50 else "support"
        assert strategy == "support"


# ---------------------------------------------------------------------------
# Optimal combo and daily range zone detection
# ---------------------------------------------------------------------------

from daily_range_analyzer import _find_optimal_combo


class TestFindOptimalCombo:
    """Test _find_optimal_combo for daily fluctuation entry selection."""

    def test_ar_profile(self):
        """AR-like: shallow dip, moderate range → optimal around +2-2.5%."""
        import numpy as np
        # Simulate 60 days: 1.5% median dip, 3.5% range
        np.random.seed(42)
        close_to_low = np.random.uniform(0.5, 2.5, 60)
        low_to_high = np.random.uniform(2.0, 5.0, 60)
        result = _find_optimal_combo(close_to_low, low_to_high, 43.0)
        assert result is not None
        assert result["target_pct"] >= 1.5
        assert result["fill_rate"] >= 50
        assert result["win_rate"] >= 60

    def test_stim_profile(self):
        """STIM-like: deep dip, wide range → optimal at +3%."""
        import numpy as np
        np.random.seed(42)
        close_to_low = np.random.uniform(2.0, 7.0, 60)
        low_to_high = np.random.uniform(5.0, 15.0, 60)
        result = _find_optimal_combo(close_to_low, low_to_high, 1.46)
        assert result is not None
        assert result["target_pct"] >= 2.5
        assert result["win_rate"] >= 60

    def test_no_viable(self):
        """Low range, no viable combo → returns None."""
        import numpy as np
        close_to_low = np.array([0.1, 0.2, 0.3, 0.1, 0.2] * 12)
        low_to_high = np.array([0.5, 0.6, 0.4, 0.3, 0.5] * 12)
        result = _find_optimal_combo(close_to_low, low_to_high, 10.0)
        assert result is None


class TestDailyRangeZoneDetection:
    """Test zone detection for daily-range order notes."""

    def test_dip_buy_detected(self):
        import re
        note = "Dip Buy — close-0.5%, daily-range"
        is_daily_range = "dip-buy" in note.lower() or "daily-range" in note.lower()
        assert is_daily_range is True

    def test_standard_note_not_detected(self):
        import re
        note = "A1 — $15.26 PA, 22% hold, Half^"
        is_daily_range = "dip-buy" in note.lower() or "daily-range" in note.lower()
        assert is_daily_range is False

    def test_empty_note(self):
        note = ""
        is_daily_range = "dip-buy" in note.lower() or "daily-range" in note.lower()
        assert is_daily_range is False
