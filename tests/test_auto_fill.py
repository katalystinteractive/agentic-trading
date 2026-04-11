"""Tests for auto-fill detection in order_proximity_monitor."""
import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from order_proximity_monitor import compute_alerts, auto_record_fill


class TestComputeAlertsFillMarking:
    """Test that compute_alerts marks fills in state for placed orders only."""

    def _make_order(self, ticker="CIFR", price=14.18, shares=8, monitored=False):
        o = {"ticker": ticker, "side": "BUY", "price": price, "shares": shares}
        if monitored:
            o["monitored"] = True
        return o

    @patch("order_proximity_monitor._load_entry_sweep", return_value={})
    @patch("order_proximity_monitor.yf")
    def test_filled_placed_order_marks_auto_fill(self, mock_yf, mock_sweep):
        """FILLED? on placed order should append to state['_auto_fills']."""
        mock_yf.download.return_value = MagicMock(empty=True)  # VIX fetch
        orders = [self._make_order(price=14.18)]
        prices = {"CIFR": 14.00}  # below order → FILLED?
        state = {}

        alerts = compute_alerts(orders, prices, state)

        assert len(alerts) == 1
        assert alerts[0]["level"] == "FILLED?"
        assert "_auto_fills" in state
        assert len(state["_auto_fills"]) == 1
        assert state["_auto_fills"][0]["ticker"] == "CIFR"
        assert state["_auto_fills"][0]["price"] == 14.18
        assert state["_auto_fills"][0]["shares"] == 8

    @patch("order_proximity_monitor._load_entry_sweep", return_value={})
    @patch("order_proximity_monitor.yf")
    def test_place_now_monitored_no_auto_fill(self, mock_yf, mock_sweep):
        """PLACE_NOW on monitored level should NOT append to state['_auto_fills']."""
        mock_yf.download.return_value = MagicMock(empty=True)
        orders = [self._make_order(price=14.18, shares=0, monitored=True)]
        prices = {"CIFR": 14.00}  # below → PLACE_NOW (not FILLED?)
        state = {}

        alerts = compute_alerts(orders, prices, state)

        assert len(alerts) == 1
        assert alerts[0]["level"] == "PLACE_NOW"
        assert "_auto_fills" not in state

    @patch("order_proximity_monitor._load_entry_sweep", return_value={})
    @patch("order_proximity_monitor.yf")
    def test_approaching_no_auto_fill(self, mock_yf, mock_sweep):
        """APPROACHING alerts should NOT trigger auto-fill."""
        mock_yf.download.return_value = MagicMock(empty=True)
        orders = [self._make_order(price=14.18)]
        prices = {"CIFR": 14.40}  # 1.6% above → APPROACHING
        state = {}

        alerts = compute_alerts(orders, prices, state)

        assert len(alerts) == 1
        assert alerts[0]["level"] == "APPROACHING"
        assert "_auto_fills" not in state

    @patch("order_proximity_monitor._load_entry_sweep", return_value={})
    @patch("order_proximity_monitor.yf")
    def test_suppressed_filled_no_double_auto_fill(self, mock_yf, mock_sweep):
        """A FILLED? that's already been alerted should NOT re-append to _auto_fills."""
        mock_yf.download.return_value = MagicMock(empty=True)
        orders = [self._make_order(price=14.18)]
        prices = {"CIFR": 14.00}
        # Pre-existing state: already alerted at FILLED? level
        state = {"CIFR:BUY:14.18": {"level": "FILLED?", "alerted_at": "2026-04-11T10:00:00"}}

        alerts = compute_alerts(orders, prices, state)

        assert len(alerts) == 0  # suppressed
        assert "_auto_fills" not in state


    @patch("order_proximity_monitor._load_entry_sweep", return_value={})
    @patch("order_proximity_monitor.yf")
    def test_sell_order_no_auto_fill(self, mock_yf, mock_sweep):
        """SELL orders at FILLED? should NOT trigger auto-fill (uses cmd_sell, not cmd_fill)."""
        mock_yf.download.return_value = MagicMock(empty=True)
        orders = [{"ticker": "CIFR", "side": "SELL", "price": 16.00, "shares": 8}]
        prices = {"CIFR": 16.50}  # above sell price → FILLED? for SELL
        state = {}

        alerts = compute_alerts(orders, prices, state)

        assert len(alerts) == 1
        assert alerts[0]["level"] == "FILLED?"
        assert "_auto_fills" not in state  # SELL fills must not trigger auto-fill


class TestVixGateExemption:
    """Test that VIX gate does NOT suppress FILLED? alerts."""

    @patch("order_proximity_monitor._load_entry_sweep")
    @patch("order_proximity_monitor.yf")
    def test_vix_gate_exempts_filled(self, mock_yf, mock_sweep):
        """High VIX should suppress APPROACHING but NOT FILLED?."""
        import pandas as pd
        import numpy as np

        # Mock VIX download: _vd["Close"]["^VIX"].iloc[-1] → 35.0
        vix_data = pd.DataFrame(
            {"Close": [35.0]},
            index=pd.DatetimeIndex(["2026-04-11"]),
        )
        vix_data.columns = pd.MultiIndex.from_tuples([("Close", "^VIX")])
        mock_yf.download.return_value = vix_data

        mock_sweep.return_value = {
            "CIFR": {"params": {"per_ticker_vix_gate": 25}},
            "APLD": {"params": {"per_ticker_vix_gate": 25}},
        }

        orders = [
            {"ticker": "CIFR", "side": "BUY", "price": 14.18, "shares": 8},      # price below → FILLED?
            {"ticker": "APLD", "side": "BUY", "price": 30.00, "shares": 5},       # price above → APPROACHING
        ]
        prices = {"CIFR": 14.00, "APLD": 30.40}  # CIFR below, APLD ~1.3% above
        state = {}

        alerts = compute_alerts(orders, prices, state)

        # CIFR should alert (FILLED? exempt from VIX gate)
        cifr_alerts = [a for a in alerts if a["ticker"] == "CIFR"]
        assert len(cifr_alerts) == 1
        assert cifr_alerts[0]["level"] == "FILLED?"

        # APLD should be suppressed (APPROACHING, VIX too high)
        apld_alerts = [a for a in alerts if a["ticker"] == "APLD"]
        assert len(apld_alerts) == 0


class TestAutoRecordFill:
    """Test auto_record_fill function."""

    def test_dry_run_does_not_mutate(self):
        """Dry run should return success but not call cmd_fill."""
        success, summary = auto_record_fill("CIFR", 14.18, 8, dry_run=True)
        assert success is True
        assert "DRY RUN" in summary

    def test_zero_shares_rejected(self):
        """Zero shares should be rejected without calling cmd_fill."""
        success, summary = auto_record_fill("CIFR", 14.18, 0, dry_run=False)
        assert success is False
        assert "shares=0" in summary
