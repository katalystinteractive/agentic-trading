"""Tests for multi_period_scorer — focus on compute_composite recency weighting."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from multi_period_scorer import compute_composite, PERIODS, RECENCY_WEIGHTS


def _r(pnl, cycles):
    """Minimal shape of a simulation result accepted by compute_composite."""
    return {"pnl": pnl, "cycles": cycles}


class TestRecencyWeighting:
    """Verify RECENCY_WEIGHTS = {12:1, 6:2, 3:3, 1:4} tilts composite toward recent periods."""

    def test_recent_strong_ticker_scores_higher_than_old_strong(self):
        """Mirror-image rate profiles:
          Ticker A (strengthening) — rate rises over time: 5, 5, 10, 15 for 12/6/3/1mo
          Ticker B (decaying)     — rate falls over time: 15, 10, 5, 5 for 12/6/3/1mo
        Equal cycle counts so significance weight is 1.0 for each period. Under pure
        cycle-based weighting both composites would be equal (mean = 8.75). With
        recency weights 1:2:3:4, the 1mo rate dominates → A > B."""
        with patch("multi_period_scorer._get_period_risk_off_pct", return_value=0):
            # Ticker A — strengthening (recent rates higher)
            a = {12: _r(60, 5), 6: _r(30, 5), 3: _r(30, 5), 1: _r(15, 5)}
            composite_a, _ = compute_composite(a)
            # Ticker B — decaying (older rates higher)
            b = {12: _r(180, 5), 6: _r(60, 5), 3: _r(15, 5), 1: _r(5, 5)}
            composite_b, _ = compute_composite(b)
        # Rates: A = [5, 5, 10, 15]; B = [15, 10, 5, 5]. Un-weighted mean = 8.75 for both.
        # With recency 1:2:3:4: A = (5+10+30+60)/10 = 10.5; B = (15+20+15+20)/10 = 7.0
        assert composite_a > composite_b, \
            f"Strengthening ticker should score higher than decaying: a={composite_a} b={composite_b}"

    def test_recency_weights_constant_shape(self):
        """RECENCY_WEIGHTS must cover all PERIODS and be monotonic (shorter = higher)."""
        assert set(RECENCY_WEIGHTS.keys()) == set(PERIODS)
        # Shorter periods get higher weights
        assert RECENCY_WEIGHTS[1] > RECENCY_WEIGHTS[3]
        assert RECENCY_WEIGHTS[3] > RECENCY_WEIGHTS[6]
        assert RECENCY_WEIGHTS[6] > RECENCY_WEIGHTS[12]

    def test_regime_override_still_works(self):
        """When 1mo has 3+ cycles and risk_off_pct >= 30, the resilience bonus (Step 3)
        can push 1mo weight above the base significance weight. Recency multiplier is
        then applied on top. Verify the chain still yields a sensible composite."""
        with patch("multi_period_scorer._get_period_risk_off_pct", return_value=50):
            # 1mo cycled 5× during Risk-Off — resilience bonus
            results = {12: _r(60, 5), 6: _r(30, 5), 3: _r(15, 5), 1: _r(5, 5)}
            composite, details = compute_composite(results)
        # The composite should be positive and reflect the 1mo-heavy weighting
        assert composite > 0
        # Details should show weight w1 > w12 due to both resilience + recency
        assert details["w1"] >= details["w12"]

    def test_zero_cycles_all_periods_safe(self):
        """Degenerate case: no cycles anywhere. Should not crash; composite = 0."""
        with patch("multi_period_scorer._get_period_risk_off_pct", return_value=0):
            results = {12: _r(0, 0), 6: _r(0, 0), 3: _r(0, 0), 1: _r(0, 0)}
            composite, _ = compute_composite(results)
        assert composite == 0

    def test_uniform_performance_positive_composite(self):
        """Ticker with equal rate across all periods — composite should approximate
        the rate (since weighted average of identical rates = that rate)."""
        with patch("multi_period_scorer._get_period_risk_off_pct", return_value=0):
            # rate = 5/mo in all periods
            results = {12: _r(60, 5), 6: _r(30, 5), 3: _r(15, 5), 1: _r(5, 5)}
            composite, _ = compute_composite(results)
        # Each period has rate=5/mo; weighted average should be ~5 regardless of recency weights
        assert 4.5 <= composite <= 5.5, f"expected ~5.0, got {composite}"
