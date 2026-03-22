"""Tests for wick_offset_analyzer zone/tier classification logic."""
import sys
from pathlib import Path

# Allow importing from tools/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from wick_offset_analyzer import classify_level, compute_effective_tier, _compute_bullet_plan, compute_pool_sizing, POOL_MAX_FRACTION, sizing_description


class TestClassifyLevel:
    """Zone and tier boundary tests for classify_level()."""

    # --- Zone classification ---

    def test_active_when_gap_below_radius(self):
        zone, _ = classify_level(hold_rate=50, gap_pct=10.0, active_radius=20.0)
        assert zone == "Active"

    def test_active_when_gap_equals_radius(self):
        zone, _ = classify_level(hold_rate=50, gap_pct=20.0, active_radius=20.0)
        assert zone == "Active"

    def test_buffer_when_gap_above_radius(self):
        zone, _ = classify_level(hold_rate=50, gap_pct=20.01, active_radius=20.0)
        assert zone == "Buffer"

    def test_buffer_at_exact_double_radius(self):
        zone, _ = classify_level(hold_rate=50, gap_pct=40.0, active_radius=20.0)
        assert zone == "Buffer"

    def test_reserve_when_gap_above_double_radius(self):
        zone, _ = classify_level(hold_rate=50, gap_pct=40.01, active_radius=20.0)
        assert zone == "Reserve"

    def test_zone_boundary_matches_price_formula(self):
        """gap_pct <= active_radius ⟺ lvl_price >= current × (1 - active_radius/100)."""
        current_price = 24.60
        active_radius = 20.0  # capped radius (production max)

        # Level just inside active zone: floor = 24.60 * 0.80 = 19.68
        lvl_inside = 19.70  # above floor of 19.68
        gap_inside = ((current_price - lvl_inside) / current_price) * 100
        zone, _ = classify_level(50, gap_inside, active_radius)
        assert zone == "Active"
        assert lvl_inside >= current_price * (1 - active_radius / 100)

        # Level just outside active zone
        lvl_outside = 19.60  # below floor of 19.68
        gap_outside = ((current_price - lvl_outside) / current_price) * 100
        zone, _ = classify_level(50, gap_outside, active_radius)
        assert zone == "Buffer"
        assert lvl_outside < current_price * (1 - active_radius / 100)

    def test_nne_18_81_is_buffer_with_capped_radius(self):
        """NNE $18.81 at gap ~23.5% is Buffer with capped 20% radius."""
        current_price = 24.60
        lvl_price = 18.81
        active_radius = 20.0  # capped radius (production max)
        gap_pct = ((current_price - lvl_price) / current_price) * 100
        zone, tier = classify_level(67, gap_pct, active_radius, approaches=3)
        assert zone == "Buffer"  # gap 23.5% > 20% radius
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

    CAP = {
        "active_pool": 300, "reserve_pool": 300,
        "active_bullets_max": 5, "reserve_bullets_max": 3,
    }

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
        level = self._make_level_result(
            price=10.0, hold_rate=12.0, zone="Active",
            raw_tier="Skip", effective_tier="Half", tier_promoted=True,
            recommended_buy=9.90,
        )
        bp = _compute_bullet_plan([level], current_price=11.0, cap=self.CAP)
        assert len(bp["active"]) == 1
        assert bp["active"][0]["tier"] == "Half"
        assert bp["active"][0]["raw_tier"] == "Skip"
        assert bp["active"][0]["tier_promoted"] is True

    def test_unpromoted_skip_excluded_from_bullet_plan(self):
        """A raw Skip level that stays Skip should NOT appear in bullets."""
        level = self._make_level_result(
            price=10.0, hold_rate=12.0, zone="Active",
            raw_tier="Skip", effective_tier="Skip", tier_promoted=False,
            recommended_buy=9.90,
        )
        bp = _compute_bullet_plan([level], current_price=11.0, cap=self.CAP)
        assert len(bp["active"]) == 0

    def test_half_promoted_to_std_gets_full_sizing_in_reserve(self):
        """A Half→Std promoted level in reserve zone should qualify (Std is in Full/Std filter)."""
        level = self._make_level_result(
            price=10.0, hold_rate=25.0, zone="Reserve",
            raw_tier="Half", effective_tier="Std", tier_promoted=True,
            recommended_buy=9.90,
        )
        bp = _compute_bullet_plan([level], current_price=11.0, cap=self.CAP)
        assert len(bp["reserve"]) == 1
        assert bp["reserve"][0]["tier"] == "Std"
        # Single reserve level gets full $300 pool: $300 / $9.90 = 30 shares
        assert bp["reserve"][0]["shares"] == 30


class TestPoolSizing:
    """Tests for compute_pool_sizing() — equal-impact pool distribution."""

    @staticmethod
    def _make_level(price, tier="Full", hold_rate=60.0):
        return {"recommended_buy": price, "effective_tier": tier, "tier": tier, "hold_rate": hold_rate}

    def test_equal_shares_same_tier(self):
        """Same-price, same-tier levels get equal shares (no cap interference)."""
        levels = [self._make_level(10.0), self._make_level(10.0), self._make_level(10.0)]
        result = compute_pool_sizing(levels, 300, "active")
        shares = [r["shares"] for r in result]
        assert max(shares) - min(shares) <= 1

    def test_total_cost_near_budget(self):
        levels = [self._make_level(5.0), self._make_level(10.0), self._make_level(15.0)]
        result = compute_pool_sizing(levels, 300, "active")
        total = sum(r["cost"] for r in result)
        assert total <= 300
        assert total >= 300 - sum(r["recommended_buy"] for r in result)

    def test_cap_limits_expensive_level(self):
        levels = [self._make_level(5.0), self._make_level(50.0)]
        result = compute_pool_sizing(levels, 300, "active")
        assert result[1]["cost"] <= 300 * 0.40 + 50

    def test_cap_redistributes_to_uncapped(self):
        levels = [self._make_level(2.0), self._make_level(100.0)]
        result = compute_pool_sizing(levels, 300, "active")
        assert result[0]["cost"] > 100  # cheap level gets redistributed budget

    def test_residual_goes_to_highest_hold_rate(self):
        levels = [self._make_level(7.0, hold_rate=80.0), self._make_level(7.0, hold_rate=30.0)]
        result = compute_pool_sizing(levels, 300, "active")
        assert result[0]["shares"] >= result[1]["shares"]

    def test_half_tier_gets_half_shares(self):
        """Half-tier gets ~half the shares of Full-tier. Use 3 Full + 1 Half to avoid cap."""
        levels = [self._make_level(10.0, tier="Full"), self._make_level(10.0, tier="Full"),
                  self._make_level(10.0, tier="Full"), self._make_level(10.0, tier="Half")]
        result = compute_pool_sizing(levels, 300, "active")
        full_shares = result[0]["shares"]
        half_shares = result[3]["shares"]
        ratio = half_shares / full_shares if full_shares > 0 else 0
        assert 0.4 <= ratio <= 0.6

    def test_empty_input(self):
        assert compute_pool_sizing([], 300, "active") == []

    def test_single_level_gets_full_pool(self):
        result = compute_pool_sizing([self._make_level(10.0)], 300, "active")
        assert result[0]["shares"] == 30 and result[0]["cost"] == 300.0

    def test_single_half_level_gets_full_pool(self):
        result = compute_pool_sizing([self._make_level(10.0, tier="Half")], 300, "active")
        assert result[0]["shares"] == 30  # only level → 100% of pool

    def test_minimum_one_share(self):
        levels = [self._make_level(1.0)] + [self._make_level(100.0)] * 4
        result = compute_pool_sizing(levels, 300, "active")
        for r in result:
            assert r["shares"] >= 1

    def test_output_preserves_input_order(self):
        levels = [self._make_level(15.0), self._make_level(5.0), self._make_level(10.0)]
        result = compute_pool_sizing(levels, 300, "active")
        assert [r["recommended_buy"] for r in result] == [15.0, 5.0, 10.0]

    def test_equal_impact_different_prices(self):
        """3 Full-tier levels at $5/$10/$15: uncapped levels get equal shares.
        $15 hits 40% cap ($120 → 8 shares), $5/$10 share the rest equally (~12 shares each)."""
        levels = [self._make_level(5.0), self._make_level(10.0), self._make_level(15.0)]
        result = compute_pool_sizing(levels, 300, "active")
        shares = [r["shares"] for r in result]
        # $5 and $10 are uncapped → equal shares
        assert abs(shares[0] - shares[1]) <= 1
        # $15 is capped at POOL_MAX_FRACTION of pool
        expected_capped = int(300 * POOL_MAX_FRACTION / 15.0)
        assert shares[2] == expected_capped
        # Total cost should use most of the budget
        total = sum(r["cost"] for r in result)
        assert total <= 300
        assert total >= 260

    def test_output_only_has_expected_keys(self):
        """compute_pool_sizing() should not leak input keys beyond the documented output."""
        levels = [self._make_level(10.0, hold_rate=60.0)]
        result = compute_pool_sizing(levels, 300, "active")
        expected_keys = {"recommended_buy", "hold_rate", "shares", "cost", "dollar_alloc"}
        assert set(result[0].keys()) == expected_keys

    def test_all_capped_distributes_via_residual(self):
        """When all levels exceed 40% cap, residual redistribution handles the overflow."""
        levels = [self._make_level(50.0), self._make_level(50.0)]
        result = compute_pool_sizing(levels, 300, "active")
        # Each capped at 40% = $120, total capped = $240.
        # Residual: $300 - $240 = $60 → 1 extra share to highest hold_rate (tied, first wins)
        total = sum(r["cost"] for r in result)
        assert total <= 300
        assert total >= 250  # at least 5 shares total at $50 each
        for r in result:
            assert r["shares"] >= 2  # floor($120/$50) = 2


class TestSizingDescription:
    """Tests for sizing_description() — centralized sizing strings."""

    def test_returns_all_expected_keys(self):
        desc = sizing_description()
        expected = {"method", "active_pool", "reserve_pool", "active_max", "reserve_max",
                    "tier_weights", "max_fraction_pct", "one_liner", "capital_note",
                    "tier_rules", "verification_note"}
        assert set(desc.keys()) == expected

    def test_values_match_constants(self):
        custom = {"active_pool": 300, "reserve_pool": 300,
                  "active_bullets_max": 5, "reserve_bullets_max": 3}
        desc = sizing_description(cap=custom)
        assert desc["active_pool"] == 300
        assert desc["reserve_pool"] == 300
        assert desc["max_fraction_pct"] == 40
        assert desc["tier_weights"]["Half"] == 0.5

    def test_one_liner_contains_pool_amounts(self):
        custom = {"active_pool": 300, "reserve_pool": 300,
                  "active_bullets_max": 5, "reserve_bullets_max": 3}
        desc = sizing_description(cap=custom)
        assert "$300" in desc["one_liner"]
        assert "equal impact" in desc["one_liner"]

    def test_custom_cap_override(self):
        custom = {"active_pool": 500, "reserve_pool": 200,
                  "active_bullets_max": 7, "reserve_bullets_max": 2}
        desc = sizing_description(cap=custom)
        assert desc["active_pool"] == 500
        assert "$500" in desc["one_liner"]
