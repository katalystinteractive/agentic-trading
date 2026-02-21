"""Tests for wick_offset_analyzer zone/tier classification logic."""
import sys
from pathlib import Path

# Allow importing from tools/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from wick_offset_analyzer import classify_level


class TestClassifyLevel:
    """Zone and tier boundary tests for classify_level()."""

    # --- Zone classification ---

    def test_active_when_gap_below_radius(self):
        zone, _ = classify_level(hold_rate=50, gap_pct=10.0, active_radius=20.0)
        assert zone == "Active"

    def test_active_when_gap_equals_radius(self):
        zone, _ = classify_level(hold_rate=50, gap_pct=20.0, active_radius=20.0)
        assert zone == "Active"

    def test_reserve_when_gap_above_radius(self):
        zone, _ = classify_level(hold_rate=50, gap_pct=20.01, active_radius=20.0)
        assert zone == "Reserve"

    def test_zone_boundary_matches_price_formula(self):
        """gap_pct <= active_radius ⟺ lvl_price >= current × (1 - active_radius/100)."""
        current_price = 24.60
        active_radius = 30.6  # NNE's actual value

        # Level just inside active zone
        lvl_inside = 17.10  # above floor of 17.07
        gap_inside = ((current_price - lvl_inside) / current_price) * 100
        zone, _ = classify_level(50, gap_inside, active_radius)
        assert zone == "Active"
        assert lvl_inside >= current_price * (1 - active_radius / 100)

        # Level just outside active zone
        lvl_outside = 17.00  # below floor of 17.07
        gap_outside = ((current_price - lvl_outside) / current_price) * 100
        zone, _ = classify_level(50, gap_outside, active_radius)
        assert zone == "Reserve"
        assert lvl_outside < current_price * (1 - active_radius / 100)

    def test_nne_18_81_is_active(self):
        """Regression test: NNE $18.81 was misclassified as Reserve before the fix."""
        current_price = 24.60
        lvl_price = 18.81
        active_radius = 30.6
        gap_pct = ((current_price - lvl_price) / current_price) * 100
        zone, tier = classify_level(67, gap_pct, active_radius, approaches=3)
        assert zone == "Active"
        assert tier == "Full"

    # --- Tier classification ---

    def test_tier_full(self):
        _, tier = classify_level(hold_rate=50, gap_pct=5.0, active_radius=20.0, approaches=3)
        assert tier == "Full"

    def test_tier_full_boundary(self):
        _, tier = classify_level(hold_rate=75, gap_pct=5.0, active_radius=20.0, approaches=5)
        assert tier == "Full"

    def test_tier_std(self):
        _, tier = classify_level(hold_rate=30, gap_pct=5.0, active_radius=20.0, approaches=3)
        assert tier == "Std"

    def test_tier_std_upper(self):
        _, tier = classify_level(hold_rate=49, gap_pct=5.0, active_radius=20.0, approaches=4)
        assert tier == "Std"

    def test_tier_half(self):
        _, tier = classify_level(hold_rate=15, gap_pct=5.0, active_radius=20.0)
        assert tier == "Half"

    def test_tier_skip(self):
        _, tier = classify_level(hold_rate=14, gap_pct=5.0, active_radius=20.0)
        assert tier == "Skip"

    def test_tier_skip_zero(self):
        _, tier = classify_level(hold_rate=0, gap_pct=5.0, active_radius=20.0)
        assert tier == "Skip"

    # --- Confidence gate ---

    def test_confidence_gate_full_demoted_with_few_approaches(self):
        _, tier = classify_level(hold_rate=60, gap_pct=5.0, active_radius=20.0, approaches=2)
        assert tier == "Half"

    def test_confidence_gate_std_demoted_with_few_approaches(self):
        _, tier = classify_level(hold_rate=35, gap_pct=5.0, active_radius=20.0, approaches=1)
        assert tier == "Half"

    def test_confidence_gate_full_preserved_with_enough_approaches(self):
        _, tier = classify_level(hold_rate=60, gap_pct=5.0, active_radius=20.0, approaches=3)
        assert tier == "Full"

    def test_confidence_gate_half_not_affected(self):
        """Half tier is not demoted further by low approaches."""
        _, tier = classify_level(hold_rate=20, gap_pct=5.0, active_radius=20.0, approaches=1)
        assert tier == "Half"

    def test_confidence_gate_skip_not_affected(self):
        _, tier = classify_level(hold_rate=5, gap_pct=5.0, active_radius=20.0, approaches=1)
        assert tier == "Skip"
