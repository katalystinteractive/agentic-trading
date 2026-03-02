"""Tests for wick_offset_analyzer zone/tier classification logic."""
import sys
from pathlib import Path

# Allow importing from tools/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from wick_offset_analyzer import classify_level, compute_effective_tier, _compute_bullet_plan


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


class TestEffectiveTier:
    """Tests for compute_effective_tier() — promotion floor and demotion logic."""

    # --- Same tier (no change) ---

    def test_same_tier_full(self):
        eff, promoted = compute_effective_tier("Full", "Full")
        assert eff == "Full"
        assert promoted is False

    def test_same_tier_skip(self):
        eff, promoted = compute_effective_tier("Skip", "Skip")
        assert eff == "Skip"
        assert promoted is False

    # --- Demotion (unrestricted) ---

    def test_demotion_one_step(self):
        eff, promoted = compute_effective_tier("Full", "Std")
        assert eff == "Std"
        assert promoted is False

    def test_demotion_two_steps(self):
        eff, promoted = compute_effective_tier("Full", "Half")
        assert eff == "Half"
        assert promoted is False

    def test_demotion_three_steps(self):
        eff, promoted = compute_effective_tier("Full", "Skip")
        assert eff == "Skip"
        assert promoted is False

    def test_demotion_std_to_skip(self):
        eff, promoted = compute_effective_tier("Std", "Skip")
        assert eff == "Skip"
        assert promoted is False

    # --- Promotion (one step allowed) ---

    def test_promotion_one_step_skip_to_half(self):
        eff, promoted = compute_effective_tier("Skip", "Half")
        assert eff == "Half"
        assert promoted is True

    def test_promotion_one_step_half_to_std(self):
        eff, promoted = compute_effective_tier("Half", "Std")
        assert eff == "Std"
        assert promoted is True

    def test_promotion_one_step_std_to_full(self):
        eff, promoted = compute_effective_tier("Std", "Full")
        assert eff == "Full"
        assert promoted is True

    # --- Promotion floor (max +1 above raw) ---

    def test_floor_skip_to_full_capped_at_half(self):
        eff, promoted = compute_effective_tier("Skip", "Full")
        assert eff == "Half"
        assert promoted is True

    def test_floor_skip_to_std_capped_at_half(self):
        eff, promoted = compute_effective_tier("Skip", "Std")
        assert eff == "Half"
        assert promoted is True

    def test_floor_half_to_full_capped_at_std(self):
        eff, promoted = compute_effective_tier("Half", "Full")
        assert eff == "Std"
        assert promoted is True

    # --- Confidence gate interaction ---

    def test_confidence_gate_blocks_promotion(self):
        """Raw Full + 2 approaches → gated to Half; decayed Full + 2 approaches → also Half.
        compute_effective_tier(Half, Half) = Half, no promotion."""
        # Simulate: raw hold rate qualifies for Full, but only 2 approaches
        _, raw_tier = classify_level(hold_rate=60, gap_pct=5.0, active_radius=20.0, approaches=2)
        assert raw_tier == "Half"  # gated from Full

        # Decayed hold rate also qualifies for Full, same 2 approaches
        _, decayed_tier = classify_level(hold_rate=65, gap_pct=5.0, active_radius=20.0, approaches=2)
        assert decayed_tier == "Half"  # gated from Full

        # Both gated to Half → no promotion possible
        eff, promoted = compute_effective_tier(raw_tier, decayed_tier)
        assert eff == "Half"
        assert promoted is False


class TestBulletPlanPromotion:
    """Integration tests: promoted levels flow through _compute_bullet_plan()."""

    @staticmethod
    def _make_level_result(price, hold_rate, zone, raw_tier, effective_tier, tier_promoted,
                           recommended_buy=None):
        """Build a minimal level_result dict matching analyze_stock_data() output."""
        if recommended_buy is None:
            recommended_buy = price * 0.99
        return {
            "level": {"price": price, "source": "HVN"},
            "events": [{"start": "2026-01-01", "min_low": price, "offset_pct": -1.0, "held": True}],
            "total_approaches": 4,
            "held": 2,
            "hold_rate": hold_rate,
            "median_offset": -1.0,
            "recommended_buy": recommended_buy,
            "decayed_hold_rate": 50.0,
            "zone": zone,
            "tier": raw_tier,
            "effective_tier": effective_tier,
            "tier_override": raw_tier != effective_tier,
            "tier_promoted": tier_promoted,
            "gap_pct": 5.0,
        }

    def test_skip_promoted_to_half_enters_active_bullet_plan(self):
        """A raw Skip level promoted to Half should appear in active bullets."""
        cap = {
            "active_pool": 300, "reserve_pool": 300,
            "active_bullets_max": 5, "reserve_bullets_max": 3,
            "active_bullet_full": 60, "active_bullet_half": 30,
            "reserve_bullet_size": 100,
        }
        # Raw Skip (12% hold rate) but decayed to Half via promotion
        level = self._make_level_result(
            price=10.0, hold_rate=12.0, zone="Active",
            raw_tier="Skip", effective_tier="Half", tier_promoted=True,
            recommended_buy=9.90,
        )
        bp = _compute_bullet_plan([level], current_price=11.0, cap=cap)
        assert len(bp["active"]) == 1
        assert bp["active"][0]["tier"] == "Half"
        assert bp["active"][0]["raw_tier"] == "Skip"
        assert bp["active"][0]["tier_promoted"] is True

    def test_unpromoted_skip_excluded_from_bullet_plan(self):
        """A raw Skip level that stays Skip should NOT appear in bullets."""
        cap = {
            "active_pool": 300, "reserve_pool": 300,
            "active_bullets_max": 5, "reserve_bullets_max": 3,
            "active_bullet_full": 60, "active_bullet_half": 30,
            "reserve_bullet_size": 100,
        }
        level = self._make_level_result(
            price=10.0, hold_rate=12.0, zone="Active",
            raw_tier="Skip", effective_tier="Skip", tier_promoted=False,
            recommended_buy=9.90,
        )
        bp = _compute_bullet_plan([level], current_price=11.0, cap=cap)
        assert len(bp["active"]) == 0

    def test_half_promoted_to_std_gets_full_sizing_in_reserve(self):
        """A Half→Std promoted level in reserve zone should qualify (Std is in Full/Std filter)."""
        cap = {
            "active_pool": 300, "reserve_pool": 300,
            "active_bullets_max": 5, "reserve_bullets_max": 3,
            "active_bullet_full": 60, "active_bullet_half": 30,
            "reserve_bullet_size": 100,
        }
        level = self._make_level_result(
            price=10.0, hold_rate=25.0, zone="Reserve",
            raw_tier="Half", effective_tier="Std", tier_promoted=True,
            recommended_buy=9.90,
        )
        bp = _compute_bullet_plan([level], current_price=11.0, cap=cap)
        assert len(bp["reserve"]) == 1
        assert bp["reserve"][0]["tier"] == "Std"
        # Std in reserve gets reserve_bullet_size ($100), not Half ($30)
        assert bp["reserve"][0]["shares"] == 10  # $100 / $9.90 = 10
