"""Unit tests for src/loop/state_builder.py."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.loop.state_builder import build_account_state


def _mock_hyperliquid(price=50000.0):
    api = MagicMock()
    api.get_current_price = AsyncMock(return_value=price)
    return api


class TestBuildAccountState:
    @pytest.mark.asyncio
    async def test_returns_balance_from_state(self):
        state = {"balance": 1000.0, "total_value": 1000.0, "positions": []}
        balance, total_value, positions = await build_account_state(state, _mock_hyperliquid())
        assert balance == 1000.0

    @pytest.mark.asyncio
    async def test_total_value_uses_api_field_when_present(self):
        state = {"balance": 900.0, "total_value": 950.0, "positions": []}
        _, total_value, _ = await build_account_state(state, _mock_hyperliquid())
        assert total_value == 950.0

    @pytest.mark.asyncio
    async def test_total_value_computed_from_balance_and_pnl_when_missing(self):
        state = {
            "balance": 900.0,
            "positions": [{"coin": "BTC", "szi": "0.1", "entryPx": "50000", "pnl": 100.0}],
        }
        _, total_value, _ = await build_account_state(state, _mock_hyperliquid())
        assert total_value == 1000.0  # 900 + 100

    @pytest.mark.asyncio
    async def test_positions_enriched_with_current_price(self):
        state = {
            "balance": 1000.0,
            "positions": [{"coin": "BTC", "szi": "0.1", "entryPx": "48000", "pnl": 200.0}],
        }
        _, _, positions = await build_account_state(state, _mock_hyperliquid(price=50000.0))
        assert len(positions) == 1
        assert positions[0]["symbol"] == "BTC"
        assert positions[0]["current_price"] == 50000.0
        assert positions[0]["entry_price"] == 48000.0

    @pytest.mark.asyncio
    async def test_no_positions_returns_empty_list(self):
        state = {"balance": 1000.0, "total_value": 1000.0, "positions": []}
        _, _, positions = await build_account_state(state, _mock_hyperliquid())
        assert positions == []

    @pytest.mark.asyncio
    async def test_missing_positions_key_safe(self):
        state = {"balance": 1000.0, "total_value": 1000.0}
        balance, total_value, positions = await build_account_state(state, _mock_hyperliquid())
        assert positions == []
        assert balance == 1000.0

    @pytest.mark.asyncio
    async def test_zero_balance_triggers_no_crash(self):
        state = {"balance": 0.0, "total_value": 0.0, "positions": []}
        balance, total_value, positions = await build_account_state(state, _mock_hyperliquid())
        assert balance == 0.0
