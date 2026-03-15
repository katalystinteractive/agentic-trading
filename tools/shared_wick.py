"""Shared wick/cycle utilities for Capital Intelligence tools.

Extracted from cycle_phase_detector.py and cooldown_evaluator.py to avoid
cross-tool imports and circular dependencies.
"""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_wick_active_supports(ticker):
    """Parse active support levels from wick_analysis.md.
    Returns list of float support prices (raw Support column, not Buy At)."""
    wick_path = PROJECT_ROOT / "tickers" / ticker / "wick_analysis.md"
    if not wick_path.exists():
        return []
    text = wick_path.read_text(encoding="utf-8")
    supports = []
    in_table = False
    headers = []
    for line in text.split("\n"):
        if "Support Levels" in line and "Buy Recommendations" in line:
            in_table = True
            continue
        if in_table and line.strip().startswith("|"):
            parts = [p.strip() for p in line.split("|")]
            parts = [p for p in parts if p]
            if not headers:
                if "Zone" in parts or "Level" in parts:
                    headers = parts
                continue
            if parts[0].startswith(":") or parts[0].startswith("-"):
                continue
            if len(parts) < len(headers):
                continue
            col_map = {h: i for i, h in enumerate(headers)}
            zone_idx = col_map.get("Zone")
            support_idx = col_map.get("Support") if "Support" in col_map else col_map.get("Level")
            if zone_idx is None or support_idx is None:
                continue
            zone = parts[zone_idx].strip()
            if zone != "Active":
                continue
            price_str = parts[support_idx].replace("$", "").replace(",", "").strip()
            try:
                supports.append(float(price_str))
            except ValueError:
                pass
        elif in_table and not line.strip().startswith("|") and line.strip():
            break
    return supports


def parse_wick_active_levels(ticker):
    """Parse active support levels and their tiers from wick_analysis.md.
    Returns list of dicts: {price, tier, hold_rate}.
    NOTE: hold_rate is a STRING ("50%" or "N/A"), not numeric."""
    wick_path = PROJECT_ROOT / "tickers" / ticker / "wick_analysis.md"
    if not wick_path.exists():
        return []
    text = wick_path.read_text(encoding="utf-8")
    levels = []
    in_table = False
    headers = []
    for line in text.split("\n"):
        if "Support Levels" in line and "Buy Recommendations" in line:
            in_table = True
            continue
        if in_table and line.strip().startswith("|"):
            parts = [p.strip() for p in line.split("|")]
            parts = [p for p in parts if p]
            if not headers:
                if "Zone" in parts or "Level" in parts:
                    headers = parts
                continue
            if parts[0].startswith(":") or parts[0].startswith("-"):
                continue
            if len(parts) < len(headers):
                continue
            col_map = {h: i for i, h in enumerate(headers)}
            zone_idx = col_map.get("Zone")
            support_idx = col_map.get("Support") if "Support" in col_map else col_map.get("Level")
            tier_idx = col_map.get("Tier")
            decayed_idx = col_map.get("Decayed")
            if zone_idx is None or support_idx is None:
                continue
            if parts[zone_idx].strip() != "Active":
                continue
            price_str = parts[support_idx].replace("$", "").replace(",", "").strip()
            try:
                price = float(price_str)
            except ValueError:
                continue
            tier = parts[tier_idx].strip() if tier_idx is not None and tier_idx < len(parts) else "Unknown"
            hold_rate = "N/A"
            if decayed_idx is not None and decayed_idx < len(parts):
                m = re.search(r'(\d+)%', parts[decayed_idx])
                if m:
                    hold_rate = f"{m.group(1)}%"
            levels.append({"price": price, "tier": tier, "hold_rate": hold_rate})
        elif in_table and not line.strip().startswith("|") and line.strip():
            break
    return levels


def find_local_highs(values, window=10):
    """Find local highs from values array. Returns list of (index, value) tuples."""
    result = []
    for i in range(window, len(values) - window):
        if values[i] == max(values[i - window:i + window + 1]):
            result.append((i, values[i]))
    return result


def find_local_lows(values, window=10):
    """Find local lows from values array. Returns list of (index, value) tuples."""
    result = []
    for i in range(window, len(values) - window):
        if values[i] == min(values[i - window:i + window + 1]):
            result.append((i, values[i]))
    return result
