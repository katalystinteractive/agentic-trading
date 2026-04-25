import re

from bullet_recommender import build_zone_labels
from daily_analyzer import _extract_label_from_note, truncate_note
from deep_dive_pre_analyst import _parse_bullet_plan_table
from graph_builder import _extract_label
from shared_utils import parse_bullet_label


def _level(buy_at, zone="Active", score=0):
    return {
        "recommended_buy": buy_at,
        "zone": zone,
        "support_score": score,
        "gap_pct": 0,
    }


def test_fill_sequence_labels_follow_buy_price_not_score_order():
    levels = [
        _level(419.52, score=99),
        _level(445.93, score=20),
        _level(440.00, score=50),
        _level(300.00, zone="Reserve", score=80),
    ]

    assert build_zone_labels(levels, active_radius=20.0) == ["F3", "F1", "F2", "R1"]


def test_new_and_legacy_order_labels_remain_parseable():
    assert parse_bullet_label("F1 — $445.93 HVN+PA, 22% hold, Half tier") == "F1"
    assert parse_bullet_label("A1 — $383.01 HVN+PA, 15% hold, Half tier") == "F1"
    assert parse_bullet_label("Bullet 2 — $440.00 HVN+PA, 25% hold") == "F2"
    assert _extract_label("F2 — $440.00 HVN+PA, 25% hold") == "F2"
    assert _extract_label_from_note("F3 — $419.52 HVN+PA, 46% hold") == "F3"


def test_truncate_note_accepts_fill_sequence_notes():
    note = "F1 — $445.93 HVN+PA, 22% hold, Half tier, wick-adjusted"

    assert truncate_note(note) == "F1 — $445.93 HVN+PA, 22% hold, Half"


def test_deep_dive_parser_accepts_fill_seq_header():
    section = """
### Suggested Bullet Plan
| Fill Seq | Zone | Level | Buy At | Hold% | Tier | Alloc | Shares | ~Cost |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | Active | $442.25 | $445.93 | 22% | Half | baseline 0.90x | 0.1 | $44.59 |
"""

    rows = _parse_bullet_plan_table(section)

    assert rows[0]["num"] == 1
    assert rows[0]["zone"] == "Active"
    assert rows[0]["buy_at"] == 445.93


def test_upper_fill_detection_regex_covers_new_and_legacy_labels():
    pattern = re.compile(r"\b(F[1-9]|A[1-5]|B[1-5]|R[1-3])\b")

    assert pattern.search("F1 — $445.93").group(1) in ("F1", "F2", "A1", "A2")
    assert pattern.search("A2 — $440.00").group(1) in ("F1", "F2", "A1", "A2")
    assert pattern.search("F3 — $419.52").group(1) not in ("F1", "F2", "A1", "A2")
