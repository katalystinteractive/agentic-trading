"""Tests for swing compression detection across screener, filter, and fitness."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from surgical_filter import score_swing, COMPRESSION_THRESHOLD, COMPRESSION_PENALTY
from watchlist_fitness import _score_swing, SWING_POINTS


# ---------------------------------------------------------------------------
# surgical_filter.score_swing — compression penalty
# ---------------------------------------------------------------------------

class TestFilterScoreSwing:
    def test_no_compression(self):
        """No penalty when compression_ratio >= threshold."""
        passer = {"median_swing": 25.0, "compression_ratio": 1.0}
        assert score_swing(passer) == 10  # full points, no penalty

    def test_with_compression(self):
        """Penalty applied when compression_ratio < threshold."""
        passer = {"median_swing": 25.0, "compression_ratio": 0.50}
        assert score_swing(passer) == 10 - COMPRESSION_PENALTY  # 7

    def test_floor_zero(self):
        """Penalty can't push score below zero."""
        # median_swing=11 → base ~1 pt, minus 3 → clamped to 0
        passer = {"median_swing": 11.0, "compression_ratio": 0.40}
        assert score_swing(passer) == 0

    def test_at_boundary_no_penalty(self):
        """Exactly at threshold → no penalty (strict less-than)."""
        passer = {"median_swing": 25.0, "compression_ratio": 0.65}
        assert score_swing(passer) == 10

    def test_just_below_boundary(self):
        """Just below threshold → penalty applied."""
        passer = {"median_swing": 25.0, "compression_ratio": 0.64}
        assert score_swing(passer) == 10 - COMPRESSION_PENALTY

    def test_missing_compression_ratio(self):
        """Backward compat: no compression_ratio key → default 1.0, no penalty."""
        passer = {"median_swing": 25.0}
        assert score_swing(passer) == 10

    def test_low_swing_no_compression_effect(self):
        """Swing below floor → 0 pts regardless of compression."""
        passer = {"median_swing": 8.0, "compression_ratio": 0.40}
        assert score_swing(passer) == 0


# ---------------------------------------------------------------------------
# watchlist_fitness._score_swing — compression penalty
# ---------------------------------------------------------------------------

class TestFitnessScoreSwing:
    def test_no_compression(self):
        """Full points when no compression."""
        assert _score_swing(20.0, compression_ratio=1.0) == SWING_POINTS  # 15

    def test_with_compression(self):
        """Penalty applied when compressed."""
        assert _score_swing(20.0, compression_ratio=0.50) == SWING_POINTS - COMPRESSION_PENALTY  # 12

    def test_at_boundary_no_penalty(self):
        """Exactly at threshold → no penalty."""
        assert _score_swing(20.0, compression_ratio=0.65) == SWING_POINTS  # 15

    def test_partial_swing_with_compression(self):
        """Swing 10-15% (partial credit) + compression penalty."""
        # Base = 10, minus 3 = 7
        assert _score_swing(12.0, compression_ratio=0.50) == 10 - COMPRESSION_PENALTY  # 7

    def test_none_swing(self):
        """None swing → 0 regardless of compression."""
        assert _score_swing(None, compression_ratio=0.50) == 0

    def test_default_no_compression(self):
        """Default compression_ratio=1.0 when not provided."""
        assert _score_swing(20.0) == SWING_POINTS  # 15


# ---------------------------------------------------------------------------
# Compression ratio computation (unit logic)
# ---------------------------------------------------------------------------

class TestCompressionRatio:
    def test_stable_swings(self):
        """Stable monthly swings → ratio near 1.0."""
        import numpy as np
        swings = np.array([20, 22, 18, 21, 20, 22, 19, 21, 20, 22, 18, 21])
        median_swing = float(np.median(swings))
        recent_swing = float(np.median(swings[-4:]))
        ratio = recent_swing / median_swing
        assert 0.9 <= ratio <= 1.1

    def test_severe_compression(self):
        """Decaying swings → ratio well below threshold."""
        import numpy as np
        swings = np.array([40, 38, 42, 35, 30, 25, 20, 15, 12, 11, 10, 10])
        median_swing = float(np.median(swings))
        recent_swing = float(np.median(swings[-4:]))
        ratio = recent_swing / median_swing
        assert ratio < COMPRESSION_THRESHOLD

    def test_short_swings_fallback(self):
        """Less than 4 months → fallback to median_swing (ratio = 1.0)."""
        import numpy as np
        swings = np.array([20, 25, 30])
        median_swing = float(np.median(swings))
        recent_swing = float(np.median(swings[-4:])) if len(swings) >= 4 else median_swing
        ratio = recent_swing / median_swing if median_swing > 0 else 1.0
        assert ratio == 1.0
