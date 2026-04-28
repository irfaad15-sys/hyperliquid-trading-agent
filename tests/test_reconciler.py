"""Unit tests for src/loop/reconciler.py."""

import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.loop.reconciler import reconcile_active_trades, fetch_fills


class TestReconcileActiveTrades:
    def test_trade_with_live_position_kept(self, tmp_path):
        diary = str(tmp_path / "diary.jsonl")
        active_trades = [{"asset": "BTC", "opened_at": "2026-01-01"}]
        state = {"positions": [{"coin": "BTC", "szi": "0.1"}]}
        reconcile_active_trades(active_trades, state, [], diary)
        assert len(active_trades) == 1

    def test_trade_with_open_order_kept(self, tmp_path):
        diary = str(tmp_path / "diary.jsonl")
        active_trades = [{"asset": "ETH", "opened_at": "2026-01-01"}]
        state = {"positions": []}
        open_orders = [{"coin": "ETH"}]
        reconcile_active_trades(active_trades, state, open_orders, diary)
        assert len(active_trades) == 1

    def test_stale_trade_removed(self, tmp_path):
        diary = str(tmp_path / "diary.jsonl")
        active_trades = [{"asset": "SOL", "opened_at": "2026-01-01"}]
        state = {"positions": []}
        reconcile_active_trades(active_trades, state, [], diary)
        assert len(active_trades) == 0

    def test_stale_trade_writes_diary_entry(self, tmp_path):
        diary = str(tmp_path / "diary.jsonl")
        active_trades = [{"asset": "SOL", "opened_at": "2026-01-01"}]
        state = {"positions": []}
        reconcile_active_trades(active_trades, state, [], diary)
        with open(diary) as f:
            entry = json.loads(f.read())
        assert entry["action"] == "reconcile_close"
        assert entry["asset"] == "SOL"

    def test_empty_state_positions_safe(self, tmp_path):
        diary = str(tmp_path / "diary.jsonl")
        active_trades = []
        state = {}  # no 'positions' key at all
        reconcile_active_trades(active_trades, state, [], diary)
        assert active_trades == []


class TestFetchFills:
    @pytest.mark.asyncio
    async def test_returns_formatted_fills(self):
        mock_api = MagicMock()
        mock_api.get_recent_fills = AsyncMock(return_value=[
            {"coin": "BTC", "isBuy": True, "sz": "0.01", "px": "50000", "time": "1700000000000"},
        ])
        result = await fetch_fills(mock_api)
        assert len(result) == 1
        assert result[0]["coin"] == "BTC"
        assert result[0]["is_buy"] is True
        assert result[0]["size"] == 0.01
        assert result[0]["price"] == 50000.0

    @pytest.mark.asyncio
    async def test_api_error_returns_empty_list(self):
        mock_api = MagicMock()
        mock_api.get_recent_fills = AsyncMock(side_effect=Exception("network error"))
        result = await fetch_fills(mock_api)
        assert result == []

    @pytest.mark.asyncio
    async def test_limits_to_20_most_recent(self):
        fills = [{"coin": "BTC", "isBuy": True, "sz": "0.01", "px": "50000", "time": "1700000000000"}] * 30
        mock_api = MagicMock()
        mock_api.get_recent_fills = AsyncMock(return_value=fills)
        result = await fetch_fills(mock_api)
        assert len(result) == 20
