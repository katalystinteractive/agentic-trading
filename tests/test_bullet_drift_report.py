"""Tests for bullet_drift_report — drift classification + inference + schema guard."""
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import bullet_drift_report as bdr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _order(price, shares=1, note="A1 — $11.56 HVN+PA, 50% hold, Half tier, wick-adjusted"):
    return {"type": "BUY", "price": price, "shares": shares, "note": note,
            "filled": False}


def _level(support, source="HVN+PA", recommended_buy=None, tier="Half",
           effective_tier=None, hold_rate=50, zone="Active", merged_from=None):
    return {
        "support_price": support,
        "source": source,
        "recommended_buy": recommended_buy if recommended_buy is not None else support * 1.005,
        "tier": tier,
        "effective_tier": effective_tier or tier,
        "hold_rate": hold_rate,
        "zone": zone,
        "merged_from": merged_from or [],
    }


def _plan(support, buy_at, tier="Half", shares=1, zone="Active"):
    return {"support_price": support, "buy_at": buy_at, "tier": tier,
            "shares": shares, "zone": zone}


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


class TestClassifyDrift:
    def test_unchanged(self):
        order = _order(price=10.00, note="A1 — $9.95 PA, 50% hold, Half tier")
        lvl = _level(support=9.95, recommended_buy=10.00, tier="Half", effective_tier="Half")
        plan = _plan(9.95, 10.00, tier="Half", shares=3)
        row = bdr._classify_drift(order, lvl, plan)
        assert row["action"] == "UNCHANGED"

    def test_move_small_drift(self):
        # 1% drift → MOVE
        order = _order(price=10.00, note="A1 — $9.95 PA, 50% hold, Half tier")
        lvl = _level(support=9.95, recommended_buy=10.10, tier="Half", effective_tier="Half")
        plan = _plan(9.95, 10.10, tier="Half", shares=3)
        row = bdr._classify_drift(order, lvl, plan)
        assert row["action"] == "MOVE"
        assert row["new_price"] == 10.10
        assert abs(row["delta_pct"] - 1.0) < 0.05

    def test_move_boundary_just_under_5pct(self):
        order = _order(price=10.00, note="A1 — $9.95 PA, 50% hold, Half tier")
        lvl = _level(support=9.95, recommended_buy=10.49, tier="Half", effective_tier="Half")
        plan = _plan(9.95, 10.49, tier="Half", shares=3)
        row = bdr._classify_drift(order, lvl, plan)
        assert row["action"] == "MOVE"

    def test_cancel_over_drift_tolerance(self):
        # 5.5% drift → CANCEL
        order = _order(price=10.00, note="A1 — $9.95 PA, 50% hold, Half tier")
        lvl = _level(support=9.95, recommended_buy=10.55, tier="Half", effective_tier="Half")
        plan = _plan(9.95, 10.55, tier="Half", shares=3)
        row = bdr._classify_drift(order, lvl, plan)
        assert row["action"] == "CANCEL"
        assert "drifted" in row["reason"]

    def test_cancel_skip_tier(self):
        order = _order(price=10.00, note="A1 — $9.95 PA, 50% hold, Half tier")
        lvl = _level(support=9.95, recommended_buy=10.00, tier="Skip", effective_tier="Skip")
        row = bdr._classify_drift(order, lvl, None)
        assert row["action"] == "CANCEL"
        assert "Skip" in row["reason"]

    def test_resize_tier_changed(self):
        # Same price, Full → Half
        order = _order(price=10.00, note="A1 — $9.95 PA, 50% hold, Full tier")
        lvl = _level(support=9.95, recommended_buy=10.00, tier="Half", effective_tier="Half")
        plan = _plan(9.95, 10.00, tier="Half", shares=1)
        row = bdr._classify_drift(order, lvl, plan)
        assert row["action"] == "RESIZE"
        assert row["tier_before"] == "Full"
        assert row["tier_after"] == "Half"


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


class TestMatching:
    def test_note_support_parsed(self):
        assert bdr._parse_note_support("A1 — $11.56 HVN+PA, 50% hold, Half tier") == 11.56
        assert bdr._parse_note_support("B2 — $124.75 PA, 30% hold, Std tier") == 124.75

    def test_note_unparseable_returns_none(self):
        assert bdr._parse_note_support("") is None
        assert bdr._parse_note_support("manual entry") is None
        assert bdr._parse_note_support(None) is None

    def test_tier_parse(self):
        assert bdr._tier_from_order_note("A1 — $11.56, Full tier, wick") == "Full"
        assert bdr._tier_from_order_note("B1 — $9.50 PA, 30% hold, Std tier") == "Std"
        assert bdr._tier_from_order_note("manual entry") is None

    def test_fuzzy_match_within_tolerance(self):
        levels = [_level(support=10.00), _level(support=12.00), _level(support=15.00)]
        # 10.00 * (1 + 0.004) = 10.04 → matches 10.00 (within 0.5%)
        match = bdr._find_level_by_support(levels, 10.04)
        assert match is not None
        assert match["support_price"] == 10.00

    def test_no_fuzzy_match_outside_tolerance(self):
        levels = [_level(support=10.00)]
        # 10.00 * (1 + 0.01) = 10.10 → outside 0.5%
        match = bdr._find_level_by_support(levels, 10.10)
        assert match is None

    def test_merged_from_fallback(self):
        # Target was absorbed into a larger level via merged_from
        lvl = _level(support=12.00, merged_from=[{"price": 11.56, "source": "HVN+PA"}])
        match = bdr._find_level_by_support([lvl], 11.56, check_merged_from=True)
        assert match is not None
        assert match["support_price"] == 12.00

    def test_tie_break_by_hold_rate(self):
        levels = [
            _level(support=10.00, hold_rate=30, recommended_buy=10.00),
            _level(support=10.02, hold_rate=70, recommended_buy=10.02),  # within 0.5%
        ]
        match = bdr._find_level_by_support(levels, 10.00)
        assert match is not None
        assert match["hold_rate"] == 70


# ---------------------------------------------------------------------------
# Missing-order inference
# ---------------------------------------------------------------------------


class TestMissingOrder:
    def test_filled_within_window(self):
        now = time.time()
        snap_ts = now - 3600
        report_ts = now
        order = {"ticker": "ABC", "price": 10.00, "shares": 3,
                 "note": "A1 — $9.95 PA, 50% hold, Half tier"}
        trade_date = bdr.datetime.fromtimestamp(snap_ts + 1800).strftime("%Y-%m-%d")
        trades = [{"ticker": "ABC", "side": "BUY", "date": trade_date, "price": 10.01}]
        row = bdr._classify_missing("ABC", order, trades, snap_ts, report_ts)
        assert row["action"] == "FILLED"
        assert row["fill_price"] == 10.01

    def test_cancelled_no_matching_trade(self):
        now = time.time()
        order = {"ticker": "ABC", "price": 10.00, "shares": 3, "note": ""}
        trades = []
        row = bdr._classify_missing("ABC", order, trades, now - 100, now)
        assert row["action"] == "CANCELLED"

    def test_trade_outside_window_becomes_cancelled(self):
        now = time.time()
        snap_ts = now - 60  # 1 min ago
        # Trade dated YESTERDAY (way before snapshot)
        yesterday = bdr.datetime.fromtimestamp(now - 86400 * 2).strftime("%Y-%m-%d")
        order = {"ticker": "ABC", "price": 10.00, "shares": 3, "note": ""}
        trades = [{"ticker": "ABC", "side": "BUY", "date": yesterday, "price": 10.00}]
        row = bdr._classify_missing("ABC", order, trades, snap_ts, now)
        assert row["action"] == "CANCELLED"

    def test_wrong_side_not_matched(self):
        now = time.time()
        today = bdr.datetime.fromtimestamp(now - 100).strftime("%Y-%m-%d")
        order = {"ticker": "ABC", "price": 10.00, "shares": 3, "note": ""}
        trades = [{"ticker": "ABC", "side": "SELL", "date": today, "price": 10.00}]
        row = bdr._classify_missing("ABC", order, trades, now - 86400, now)
        assert row["action"] == "CANCELLED"

    def test_malformed_trade_date_not_matched(self):
        now = time.time()
        order = {"ticker": "ABC", "price": 10.00, "shares": 3, "note": ""}
        trades = [{"ticker": "ABC", "side": "BUY", "date": "not-a-date", "price": 10.00}]
        row = bdr._classify_missing("ABC", order, trades, now - 86400, now)
        assert row["action"] == "CANCELLED"

    def test_price_outside_tolerance_not_matched(self):
        now = time.time()
        today = bdr.datetime.fromtimestamp(now - 100).strftime("%Y-%m-%d")
        order = {"ticker": "ABC", "price": 10.00, "shares": 3, "note": ""}
        trades = [{"ticker": "ABC", "side": "BUY", "date": today, "price": 10.20}]
        row = bdr._classify_missing("ABC", order, trades, now - 86400, now)
        assert row["action"] == "CANCELLED"


# ---------------------------------------------------------------------------
# Schema guard
# ---------------------------------------------------------------------------


class TestSchemaGuard:
    def test_reader_raises_on_version_mismatch(self, tmp_path):
        snap = tmp_path / "snap.json"
        snap.write_text(json.dumps({"schema_version": 99, "tickers": {}}))
        with pytest.raises(ValueError, match="schema_version"):
            bdr.generate_drift_report(dry_run=True, snapshot_path=snap)

    def test_no_snapshot_returns_status(self, tmp_path):
        missing = tmp_path / "missing.json"
        result = bdr.generate_drift_report(dry_run=True, snapshot_path=missing)
        assert result["status"] == "NO_SNAPSHOT"


# ---------------------------------------------------------------------------
# Ticker sets
# ---------------------------------------------------------------------------


class TestTickerSets:
    def test_orphan_passes_through(self, tmp_path, monkeypatch):
        snap = tmp_path / "snap.json"
        snap.write_text(json.dumps({
            "schema_version": 1,
            "snapshot_ts": time.time() - 60,
            "tickers": {
                "ORPH": {
                    "status": "ORPHAN",
                    "reason": "ticker not in tracked set",
                    "pending_orders": [{"type": "BUY", "price": 5.0, "shares": 1,
                                        "note": "A1 — $4.95 PA, 50% hold, Half tier",
                                        "filled": False}],
                }
            }
        }))
        report = bdr.generate_drift_report(dry_run=True, snapshot_path=snap)
        assert report["tickers"]["ORPH"]["status"] == "ORPHAN"
        assert report["tickers"]["ORPH"]["orders"][0]["action"] == "ORPHAN"

    def test_wick_missing_passes_through(self, tmp_path):
        snap = tmp_path / "snap.json"
        snap.write_text(json.dumps({
            "schema_version": 1,
            "snapshot_ts": time.time() - 60,
            "tickers": {
                "MISS": {
                    "status": "WICK_MISSING",
                    "reason": "data_cache missing",
                    "pending_orders": [{"type": "BUY", "price": 5.0, "shares": 1,
                                        "note": "", "filled": False}],
                }
            }
        }))
        report = bdr.generate_drift_report(dry_run=True, snapshot_path=snap)
        assert report["tickers"]["MISS"]["status"] == "WICK_MISSING"


# ---------------------------------------------------------------------------
# Snapshot capture
# ---------------------------------------------------------------------------


class TestSnapshotCapture:
    def test_all_filled_orders_filter_out(self, tmp_path):
        snap_path = tmp_path / "snap.json"
        pending = {"XYZ": [{"type": "BUY", "price": 10.0, "shares": 1,
                            "note": "", "filled": True}]}
        bdr.write_before_snapshot(tracked_tickers=["XYZ"],
                                   pending_orders_all=pending,
                                   data_cache={}, snapshot_path=snap_path)
        data = json.loads(snap_path.read_text())
        assert "XYZ" not in data["tickers"]

    def test_orphan_when_not_tracked(self, tmp_path):
        snap_path = tmp_path / "snap.json"
        pending = {"ORPH": [{"type": "BUY", "price": 5.0, "shares": 1,
                              "note": "A1 — $4.95 PA, 50% hold, Half tier",
                              "filled": False}]}
        bdr.write_before_snapshot(tracked_tickers=[],
                                   pending_orders_all=pending,
                                   data_cache={}, snapshot_path=snap_path)
        data = json.loads(snap_path.read_text())
        assert data["tickers"]["ORPH"]["status"] == "ORPHAN"

    def test_ok_ticker_includes_levels_and_plan(self, tmp_path):
        snap_path = tmp_path / "snap.json"
        pending = {"ABC": [{"type": "BUY", "price": 10.0, "shares": 1,
                             "note": "A1 — $9.95 PA, 50% hold, Half tier",
                             "filled": False}]}
        data_cache = {
            "ABC": {
                "current_price": 10.50,
                "levels": [_level(support=9.95, hold_rate=50)],
                "bullet_plan": {"active": [_plan(9.95, 10.00)], "reserve": []},
            }
        }
        bdr.write_before_snapshot(tracked_tickers=["ABC"],
                                   pending_orders_all=pending,
                                   data_cache=data_cache,
                                   snapshot_path=snap_path)
        data = json.loads(snap_path.read_text())
        assert data["tickers"]["ABC"]["status"] == "OK"
        assert len(data["tickers"]["ABC"]["levels"]) == 1
        assert len(data["tickers"]["ABC"]["bullet_plan"]) == 1


# ---------------------------------------------------------------------------
# Archive pruning
# ---------------------------------------------------------------------------


class TestArchive:
    def test_prune_old_files(self, tmp_path, monkeypatch):
        archive = tmp_path / "arch"
        archive.mkdir()
        old = archive / "2025-01-01.json"
        old.write_text("{}")
        recent = archive / "2026-04-20.json"
        recent.write_text("{}")
        # Set old file mtime to ~60 days ago
        old_t = time.time() - 60 * 86400
        import os
        os.utime(old, (old_t, old_t))
        monkeypatch.setattr(bdr, "ARCHIVE_DIR", archive)
        bdr._prune_archive()
        assert not old.exists()
        assert recent.exists()

    def test_keep_recent_files(self, tmp_path, monkeypatch):
        archive = tmp_path / "arch"
        archive.mkdir()
        recent = archive / "2026-04-20.json"
        recent.write_text("{}")
        # 14-day-old file — within 28-day retention
        t = time.time() - 14 * 86400
        import os
        os.utime(recent, (t, t))
        monkeypatch.setattr(bdr, "ARCHIVE_DIR", archive)
        bdr._prune_archive()
        assert recent.exists()


# ---------------------------------------------------------------------------
# Broker command rendering
# ---------------------------------------------------------------------------


class TestBrokerCmd:
    def test_move_command(self):
        o = {"action": "MOVE", "old_price": 10.00, "new_price": 10.20,
             "old_shares": 3, "new_shares": 3}
        cmd = bdr._order_to_broker_cmd("ABC", o)
        assert "Cancel ABC BUY 3 @ $10.0" in cmd
        assert "Place ABC BUY 3 @ $10.2" in cmd

    def test_cancel_command(self):
        o = {"action": "CANCEL", "old_price": 10.00, "old_shares": 3,
             "reason": "drift > 5%"}
        cmd = bdr._order_to_broker_cmd("ABC", o)
        assert "Cancel ABC BUY 3 @ $10.0" in cmd

    def test_resize_with_tier_suffix(self):
        o = {"action": "RESIZE", "old_price": 10.00, "old_shares": 3,
             "new_shares": 1, "tier_before": "Full", "tier_after": "Half"}
        cmd = bdr._order_to_broker_cmd("ABC", o)
        assert "3 → 1" in cmd
        assert "tier Full→Half" in cmd

    def test_resize_tier_before_none_uses_question_mark(self):
        o = {"action": "RESIZE", "old_price": 10.00, "old_shares": 3,
             "new_shares": 1, "tier_before": None, "tier_after": "Half"}
        cmd = bdr._order_to_broker_cmd("ABC", o)
        assert "tier ?→Half" in cmd
        assert "None" not in cmd

    def test_unchanged_returns_none(self):
        assert bdr._order_to_broker_cmd("ABC", {"action": "UNCHANGED"}) is None

    def test_filled_returns_none(self):
        assert bdr._order_to_broker_cmd("ABC", {"action": "FILLED"}) is None

    def test_add_optional(self):
        o = {"action": "ADD", "new_price": 11.00, "new_shares": 2}
        cmd = bdr._order_to_broker_cmd("ABC", o)
        assert "optional ADD" in cmd
        assert "11.0" in cmd
