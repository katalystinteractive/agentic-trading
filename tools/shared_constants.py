"""Shared constants used across multiple tools.

Centralized here to avoid silent divergence when values are tuned.
"""

# Order matching tolerance — 0.5% (used by portfolio_manager, bullet_recommender,
# morning_gatherer cross_reference_fills)
MATCH_TOLERANCE = 0.005
