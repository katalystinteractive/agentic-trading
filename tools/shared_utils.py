"""Shared utilities for Capital Intelligence tools."""

import re


def parse_bullet_label(note):
    """Parse bullet label from order note. Returns e.g. 'B1', 'R2', 'B2+3', 'B?'."""
    if not note:
        return "B?"
    # Take text before em dash
    prefix = note.split("\u2014")[0].split("—")[0].strip()
    # "Bullets N+M"
    m = re.match(r"Bullets?\s+(\d+\+\d+)", prefix, re.IGNORECASE)
    if m:
        return f"B{m.group(1)}"
    # "BN reserve" → RN
    m = re.match(r"B(\d+)\s+reserve", prefix, re.IGNORECASE)
    if m:
        return f"R{m.group(1)}"
    # "Reserve N"
    m = re.match(r"Reserve\s+(\d+)", prefix, re.IGNORECASE)
    if m:
        return f"R{m.group(1)}"
    # "Bullet N"
    m = re.match(r"Bullet\s+(\d+)", prefix, re.IGNORECASE)
    if m:
        return f"B{m.group(1)}"
    return "B?"
