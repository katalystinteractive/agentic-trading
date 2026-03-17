"""Shared constants used across multiple tools.

Centralized here to avoid silent divergence when values are tuned.
"""

# Order matching tolerance — 0.5% (used by portfolio_manager, bullet_recommender,
# morning_gatherer cross_reference_fills)
MATCH_TOLERANCE = 0.005

# Exit multipliers (used by range_reset_analyzer, range_uplift_analyzer,
# sell_target_calculator)
EXIT_CONSERVATIVE = 1.045        # 4.5% conservative exit
EXIT_STANDARD = 1.06             # 6% standard exit
EXIT_AGGRESSIVE = 1.075          # 7.5% aggressive exit

# Range analysis thresholds (used by range_reset_analyzer, range_uplift_analyzer)
SWING_MIN = 20.0                 # % — minimum 20d range swing
MIN_HOLD_RATE = 15.0             # % — below this = dead zone, no order
