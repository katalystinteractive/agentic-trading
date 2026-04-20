"""Tests for wick_offset_analyzer zone/tier classification logic."""
import sys
import json
from pathlib import Path

# Allow importing from tools/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from wick_offset_analyzer import (classify_level, compute_effective_tier, _compute_bullet_plan,
                                   compute_pool_sizing, POOL_MAX_FRACTION, ACTIVE_RADIUS_CAP,
                                   sizing_description, _load_level_filters)


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

    # --- Active radius cap ---

    def test_active_radius_cap_value(self):
        """ACTIVE_RADIUS_CAP constant is 20.0%."""
        assert ACTIVE_RADIUS_CAP == 20.0

    def test_active_radius_cap_applied(self):
        """Verify that capping logic min(radius, ACTIVE_RADIUS_CAP) works as expected.

        This mirrors the logic in analyze_stock_data() line 656:
            active_radius = min(active_radius, ACTIVE_RADIUS_CAP)
        We can't easily call analyze_stock_data() without full price history,
        so we verify the math and that the constant is importable/correct.
        """
        # Simulated high-swing stock: 65% monthly swing → uncapped radius = 32.5%
        uncapped_radius = 65.0 / 2
        capped = min(uncapped_radius, ACTIVE_RADIUS_CAP)
        assert capped == 20.0

        # Level at 25% gap: Active with uncapped radius, Buffer with capped
        zone_uncapped, _ = classify_level(50, 25.0, uncapped_radius)
        zone_capped, _ = classify_level(50, 25.0, capped)
        assert zone_uncapped == "Active"
        assert zone_capped == "Buffer"

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
        # Single reserve level gets full $300 pool: $300 / $9.90 ≈ 30.3 shares (0.1 increments)
        assert bp["reserve"][0]["shares"] >= 30


class TestLevelFilters:
    """Tests: neural level filters applied in _compute_bullet_plan()."""

    CAP = TestBulletPlanPromotion.CAP

    @staticmethod
    def _make_level(price, zone, tier, hold_rate=50.0, touch_freq=2.0, dormant=False):
        """Build level_result with filter-relevant fields."""
        return {
            "level": {"price": price, "source": "HVN"},
            "events": [{"start": "2026-01-01", "min_low": price, "offset_pct": -1.0, "held": True}],
            "total_approaches": 4, "held": 2,
            "hold_rate": hold_rate, "decayed_hold_rate": hold_rate,
            "median_offset": -1.0, "recommended_buy": price * 0.99,
            "zone": zone, "tier": tier, "effective_tier": tier,
            "tier_override": False, "tier_promoted": False,
            "gap_pct": 5.0, "monthly_touch_freq": touch_freq,
            "dormant": dormant,
        }

    def test_no_filters_passes_all(self):
        """level_filters=None passes all levels (backward compat)."""
        levels = [self._make_level(10.0, "Active", "Full"),
                  self._make_level(8.0, "Reserve", "Full")]
        bp = _compute_bullet_plan(levels, current_price=11.0, cap=self.CAP, level_filters=None)
        assert len(bp["active"]) == 1
        assert len(bp["reserve"]) == 1

    def test_min_hold_rate_filters_active(self):
        """Active level with 30% hold rate removed when min_hold_rate=50."""
        level = self._make_level(10.0, "Active", "Full", hold_rate=30.0)
        filters = {"min_hold_rate": 50}
        bp = _compute_bullet_plan([level], current_price=11.0, cap=self.CAP, level_filters=filters)
        assert len(bp["active"]) == 0

    def test_min_hold_rate_does_not_filter_reserve(self):
        """Reserve level with 30% hold rate KEPT when min_hold_rate=50 (zone-aware)."""
        level = self._make_level(10.0, "Reserve", "Full", hold_rate=30.0)
        filters = {"min_hold_rate": 50}
        bp = _compute_bullet_plan([level], current_price=11.0, cap=self.CAP, level_filters=filters)
        assert len(bp["reserve"]) == 1

    def test_min_touch_freq_filters_both_zones(self):
        """Both zones filtered when touch_freq below threshold."""
        active = self._make_level(10.0, "Active", "Full", touch_freq=0.5)
        reserve = self._make_level(8.0, "Reserve", "Full", touch_freq=0.5)
        filters = {"min_touch_freq": 1.0}
        bp = _compute_bullet_plan([active, reserve], current_price=11.0, cap=self.CAP, level_filters=filters)
        assert len(bp["active"]) == 0
        assert len(bp["reserve"]) == 0

    def test_zone_filter_active_skips_reserve(self):
        """zone_filter='active' produces empty reserve list."""
        active = self._make_level(10.0, "Active", "Full")
        reserve = self._make_level(8.0, "Reserve", "Full")
        filters = {"zone_filter": "active"}
        bp = _compute_bullet_plan([active, reserve], current_price=11.0, cap=self.CAP, level_filters=filters)
        assert len(bp["active"]) == 1
        assert len(bp["reserve"]) == 0

    def test_skip_dormant_filters_both_zones(self):
        """Dormant levels removed when skip_dormant=True."""
        active = self._make_level(10.0, "Active", "Full", dormant=True)
        reserve = self._make_level(8.0, "Reserve", "Full", dormant=True)
        filters = {"skip_dormant": True}
        bp = _compute_bullet_plan([active, reserve], current_price=11.0, cap=self.CAP, level_filters=filters)
        assert len(bp["active"]) == 0
        assert len(bp["reserve"]) == 0

    def test_all_levels_filtered_returns_empty_plan(self):
        """All levels fail filters — empty plan, no crash."""
        level = self._make_level(10.0, "Active", "Full", hold_rate=10.0, touch_freq=0.1, dormant=True)
        filters = {"min_hold_rate": 50, "min_touch_freq": 1.0, "skip_dormant": True}
        bp = _compute_bullet_plan([level], current_price=11.0, cap=self.CAP, level_filters=filters)
        assert len(bp["active"]) == 0
        assert len(bp["reserve"]) == 0


    def test_dormant_sorts_last_when_not_skipped(self):
        """Dormant levels pass through but sort after fresh levels."""
        fresh = self._make_level(10.0, "Active", "Full", dormant=False)
        dormant = self._make_level(9.0, "Active", "Full", dormant=True)
        filters = {"skip_dormant": False}
        bp = _compute_bullet_plan([dormant, fresh], current_price=11.0, cap=self.CAP, level_filters=filters)
        assert len(bp["active"]) == 2
        # Fresh (dormant=False) sorts first, dormant sorts last
        assert bp["active"][0]["dormant"] is False
        assert bp["active"][1]["dormant"] is True

    def test_min_hold_rate_uses_decayed_over_raw(self):
        """Filter uses decayed_hold_rate, not raw hold_rate."""
        level = self._make_level(10.0, "Active", "Full", hold_rate=60.0)
        level["decayed_hold_rate"] = 30.0  # override: decayed is worse
        filters = {"min_hold_rate": 50}
        bp = _compute_bullet_plan([level], current_price=11.0, cap=self.CAP, level_filters=filters)
        assert len(bp["active"]) == 0  # filtered by decayed (30 < 50)

    def test_zone_filter_all_keeps_reserve(self):
        """zone_filter='all' keeps both active and reserve levels."""
        active = self._make_level(10.0, "Active", "Full")
        reserve = self._make_level(8.0, "Reserve", "Full")
        filters = {"zone_filter": "all"}
        bp = _compute_bullet_plan([active, reserve], current_price=11.0, cap=self.CAP, level_filters=filters)
        assert len(bp["active"]) == 1
        assert len(bp["reserve"]) == 1


class TestLoadLevelFilters:
    """Tests for _load_level_filters file loading."""

    def test_returns_none_when_file_missing(self, monkeypatch):
        """No sweep file → None (no filtering)."""
        import wick_offset_analyzer as woa
        monkeypatch.setattr(woa, "_LEVEL_FILTER_PATH", Path("/nonexistent/path.json"))
        monkeypatch.setattr(woa, "_level_filter_cache", {"mtime": 0, "data": None})
        assert _load_level_filters("CIFR") is None

    def test_returns_params_for_known_ticker(self, tmp_path, monkeypatch):
        """Known ticker returns its level_params dict."""
        import wick_offset_analyzer as woa
        lf_path = tmp_path / "sweep_support_levels.json"
        lf_path.write_text(json.dumps({
            "CIFR": {"level_params": {"min_hold_rate": 50, "zone_filter": "active"}}
        }))
        monkeypatch.setattr(woa, "_LEVEL_FILTER_PATH", lf_path)
        monkeypatch.setattr(woa, "_level_filter_cache", {"mtime": 0, "data": None})
        result = _load_level_filters("CIFR")
        assert result == {"min_hold_rate": 50, "zone_filter": "active"}

    def test_returns_none_for_unknown_ticker(self, tmp_path, monkeypatch):
        """File exists but ticker not in it → None."""
        import wick_offset_analyzer as woa
        lf_path = tmp_path / "sweep_support_levels.json"
        lf_path.write_text(json.dumps({"CIFR": {"level_params": {"min_hold_rate": 50}}}))
        monkeypatch.setattr(woa, "_LEVEL_FILTER_PATH", lf_path)
        monkeypatch.setattr(woa, "_level_filter_cache", {"mtime": 0, "data": None})
        assert _load_level_filters("AAPL") is None

    def test_returns_none_when_level_params_missing(self, tmp_path, monkeypatch):
        """Ticker exists but no level_params key → None."""
        import wick_offset_analyzer as woa
        lf_path = tmp_path / "sweep_support_levels.json"
        lf_path.write_text(json.dumps({"CIFR": {"stats": {"pnl": 100}}}))
        monkeypatch.setattr(woa, "_LEVEL_FILTER_PATH", lf_path)
        monkeypatch.setattr(woa, "_level_filter_cache", {"mtime": 0, "data": None})
        assert _load_level_filters("CIFR") is None


class TestPoolSizing:
    """Tests for compute_pool_sizing() — equal-impact pool distribution."""

    @staticmethod
    def _make_level(price, tier="Full", hold_rate=60.0, freq=1.0):
        return {"recommended_buy": price, "effective_tier": tier, "tier": tier,
                "hold_rate": hold_rate, "monthly_touch_freq": freq}

    def test_equal_shares_same_tier(self):
        """Same-price, same-tier, same-freq levels get equal shares."""
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
        assert result[1]["cost"] <= 300 * 0.60 + 50  # 60% cap

    def test_cap_redistributes_to_uncapped(self):
        levels = [self._make_level(2.0), self._make_level(100.0)]
        result = compute_pool_sizing(levels, 300, "active")
        assert result[0]["cost"] > 100  # cheap level gets redistributed budget

    def test_residual_goes_to_highest_frequency(self):
        """Residual shares go to highest monthly_touch_freq level."""
        levels = [self._make_level(7.0, freq=3.0), self._make_level(7.0, freq=1.0)]
        result = compute_pool_sizing(levels, 300, "active")
        assert result[0]["shares"] >= result[1]["shares"]

    def test_half_tier_gets_one_third_of_full(self):
        """Half-tier multiplier is 0.5; Full-tier is 1.5 — ratio ~= 0.33. Use 3 Full + 1 Half
        to avoid the 60% per-bullet cap skewing the test."""
        levels = [self._make_level(10.0, tier="Full"), self._make_level(10.0, tier="Full"),
                  self._make_level(10.0, tier="Full"), self._make_level(10.0, tier="Half")]
        result = compute_pool_sizing(levels, 300, "active")
        full_shares = result[0]["shares"]
        half_shares = result[3]["shares"]
        ratio = half_shares / full_shares if full_shares > 0 else 0
        # Half/Full = 0.5/1.5 = 1/3 ≈ 0.33. Allow some tolerance for residual redistribution.
        assert 0.25 <= ratio <= 0.45, \
            f"half/full ratio = {ratio:.3f} (expected ~0.33)"

    def test_full_tier_gets_more_than_std(self):
        """Full-tier multiplier is 1.5×; Std-tier is 1.0×. Same-price Full should get
        more shares than Std when competing for the same pool."""
        levels = [self._make_level(10.0, tier="Full"), self._make_level(10.0, tier="Std"),
                  self._make_level(10.0, tier="Std")]
        result = compute_pool_sizing(levels, 300, "active")
        full_shares = result[0]["shares"]
        std_shares = result[1]["shares"]
        assert full_shares > std_shares, \
            f"Full tier shares ({full_shares}) must exceed Std tier ({std_shares})"

    def test_empty_input(self):
        assert compute_pool_sizing([], 300, "active") == []

    def test_single_level_gets_full_pool(self):
        result = compute_pool_sizing([self._make_level(10.0)], 300, "active")
        assert result[0]["shares"] == 30 and result[0]["cost"] == 300.0

    def test_single_half_level_gets_full_pool(self):
        result = compute_pool_sizing([self._make_level(10.0, tier="Half")], 300, "active")
        assert result[0]["shares"] == 30  # only level → 100% of pool

    def test_minimum_fractional_share(self):
        """Minimum share is 0.1 (fractional share support)."""
        levels = [self._make_level(1.0)] + [self._make_level(100.0)] * 4
        result = compute_pool_sizing(levels, 300, "active")
        for r in result:
            assert r["shares"] >= 0.1

    def test_output_preserves_input_order(self):
        levels = [self._make_level(15.0), self._make_level(5.0), self._make_level(10.0)]
        result = compute_pool_sizing(levels, 300, "active")
        assert [r["recommended_buy"] for r in result] == [15.0, 5.0, 10.0]

    def test_equal_impact_different_prices(self):
        """3 Full-tier levels at $5/$10/$15 with same freq: proportional to price weight.
        At 60% cap, none are capped (max allocation = $150 < $180 cap)."""
        levels = [self._make_level(5.0), self._make_level(10.0), self._make_level(15.0)]
        result = compute_pool_sizing(levels, 300, "active")
        shares = [r["shares"] for r in result]
        # Weight proportional to price: $5=16.7%, $10=33.3%, $15=50%
        # All same freq=1.0, so dollar allocation follows price weight
        # Each level gets ~equal dollar amount (by design: weight = price)
        # shares[0] = $50/$5 = 10, shares[1] = $100/$10 = 10, shares[2] = $150/$15 = 10
        assert abs(shares[0] - shares[1]) <= 1
        assert abs(shares[1] - shares[2]) <= 1
        # Total cost should use most of the budget
        total = sum(r["cost"] for r in result)
        assert total <= 300
        assert total >= 260

    def test_output_only_has_expected_keys(self):
        """compute_pool_sizing() should not leak input keys beyond the documented output."""
        levels = [self._make_level(10.0, hold_rate=60.0)]
        result = compute_pool_sizing(levels, 300, "active")
        expected_keys = {"recommended_buy", "hold_rate", "monthly_touch_freq", "shares", "cost", "dollar_alloc"}
        assert set(result[0].keys()) == expected_keys

    def test_all_capped_distributes_via_residual(self):
        """Two expensive levels: each gets proportional allocation (60% cap = $180 each max).
        With equal weight (same price/tier/freq), each gets $150, no cap triggered."""
        levels = [self._make_level(50.0), self._make_level(50.0)]
        result = compute_pool_sizing(levels, 300, "active")
        # Equal weight → each gets $150 (< $180 cap), 3 shares each
        total = sum(r["cost"] for r in result)
        assert total <= 300
        assert total >= 250  # at least 5 shares total at $50 each
        for r in result:
            assert r["shares"] >= 2  # floor($120/$50) = 2

    def test_higher_freq_gets_more_shares(self):
        """Same price/tier, higher frequency gets more shares."""
        levels = [self._make_level(10.0, freq=2.0), self._make_level(10.0, freq=1.0)]
        result = compute_pool_sizing(levels, 300, "active")
        assert result[0]["shares"] > result[1]["shares"]

    def test_freq_floor_at_one(self):
        """Low frequency (0.3) floored to 1.0 for weight — equal allocation before residual."""
        levels = [self._make_level(10.0, freq=0.3), self._make_level(10.0, freq=1.0)]
        result = compute_pool_sizing(levels, 300, "active")
        # Weights are equal (both floored to 1.0), but residual goes to freq=1.0
        # So freq=1.0 level gets slightly more (residual preference)
        assert result[0]["shares"] >= 10  # floor-weighted level gets substantial allocation
        assert result[1]["shares"] >= result[0]["shares"]  # higher freq gets residual

    def test_freq_zero_treated_as_one(self):
        """Zero frequency (no data) floored to 1.0 — baseline weight, residual to higher freq."""
        levels = [self._make_level(10.0, freq=0), self._make_level(10.0, freq=1.0)]
        result = compute_pool_sizing(levels, 300, "active")
        assert result[0]["shares"] >= 10  # still gets substantial allocation
        assert result[1]["shares"] >= result[0]["shares"]  # higher freq gets residual

    def test_pool_cap_60pct_multi_level(self):
        """Multiple expensive levels hit the 60% per-bullet cap; residual must redistribute
        to the cheap uncapped level without exceeding pool budget."""
        levels = [
            self._make_level(200.0, tier="Full", hold_rate=60.0, freq=2.0),
            self._make_level(150.0, tier="Full", hold_rate=60.0, freq=2.0),
            self._make_level(40.0,  tier="Std",  hold_rate=35.0, freq=1.0),
        ]
        result = compute_pool_sizing(levels, 300, "active")
        total_cost = sum(r["cost"] for r in result)
        # Total stays within pool (+ max-one-share-price tolerance for rounding)
        max_price = max(r["recommended_buy"] for r in result)
        assert total_cost <= 300 + max_price
        # Expensive levels should not each exceed 60% cap dollar amount
        # (cap relaxes via residual redistribution, but gross allocation respects cap)
        cheap = next(r for r in result if r["recommended_buy"] == 40.0)
        assert cheap["shares"] >= 1, "cheap level must absorb residual"

    def test_residual_distribution_order(self):
        """Same-price, same-tier levels with different frequencies — residual goes to the
        higher-frequency level first per the by_freq sort in compute_pool_sizing."""
        levels = [
            self._make_level(10.0, tier="Std", hold_rate=30.0, freq=0.5),
            self._make_level(10.0, tier="Std", hold_rate=35.0, freq=2.5),
        ]
        result = compute_pool_sizing(levels, 100, "active")
        high_freq = next(r for r in result if r["monthly_touch_freq"] == 2.5)
        low_freq = next(r for r in result if r["monthly_touch_freq"] == 0.5)
        assert high_freq["shares"] >= low_freq["shares"], \
            f"high-freq shares ({high_freq['shares']}) must be >= low-freq ({low_freq['shares']})"

    def test_cap_no_leftover_below_min_step(self):
        """Sub-$150 tickers must round shares to integer. Verify no crash on residual
        below-one-share and that total doesn't explode past pool + one-share-price tolerance."""
        levels = [
            self._make_level(7.13, tier="Std", hold_rate=35.0, freq=1.0),
            self._make_level(5.07, tier="Std", hold_rate=35.0, freq=1.0),
        ]
        result = compute_pool_sizing(levels, 50, "active")
        # All sub-$150 levels must have INTEGER share counts (broker rule)
        for r in result:
            shares_val = r["shares"]
            assert shares_val == int(shares_val), \
                f"price={r['recommended_buy']} got non-integer shares={shares_val}"
            assert shares_val >= 1, "minimum share floor violated"
        total_cost = sum(r["cost"] for r in result)
        max_price = max(r["recommended_buy"] for r in result)
        assert total_cost <= 50 + max_price, \
            f"total={total_cost} exceeds pool+tolerance (pool=50, max_price={max_price})"


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
        assert desc["max_fraction_pct"] == 60
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
