"""Unit tests for src/storage/db.py — SQLite active_trades persistence."""

import pytest
from src.storage.db import init_db, load_active_trades, save_all_active_trades


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "state.db")


class TestInitDb:
    @pytest.mark.asyncio
    async def test_creates_table(self, db_path):
        await init_db(db_path)
        # Verify we can load (empty) from the created table
        trades = await load_active_trades(db_path)
        assert trades == []

    @pytest.mark.asyncio
    async def test_idempotent(self, db_path):
        # Calling init twice must not raise or drop data
        await init_db(db_path)
        await save_all_active_trades(db_path, [{"asset": "BTC", "amount": 0.1}])
        await init_db(db_path)
        trades = await load_active_trades(db_path)
        assert len(trades) == 1


class TestSaveAndLoad:
    @pytest.mark.asyncio
    async def test_roundtrip_single_trade(self, db_path):
        await init_db(db_path)
        trade = {"asset": "BTC", "is_long": True, "amount": 0.5, "entry_price": 50000.0}
        await save_all_active_trades(db_path, [trade])
        loaded = await load_active_trades(db_path)
        assert len(loaded) == 1
        assert loaded[0]["asset"] == "BTC"
        assert loaded[0]["amount"] == 0.5

    @pytest.mark.asyncio
    async def test_roundtrip_multiple_trades(self, db_path):
        await init_db(db_path)
        trades = [
            {"asset": "BTC", "amount": 0.1},
            {"asset": "ETH", "amount": 2.0},
        ]
        await save_all_active_trades(db_path, trades)
        loaded = await load_active_trades(db_path)
        assert len(loaded) == 2
        assets = {t["asset"] for t in loaded}
        assert assets == {"BTC", "ETH"}

    @pytest.mark.asyncio
    async def test_save_overwrites_previous(self, db_path):
        await init_db(db_path)
        await save_all_active_trades(db_path, [{"asset": "BTC", "amount": 0.1}])
        await save_all_active_trades(db_path, [{"asset": "ETH", "amount": 5.0}])
        loaded = await load_active_trades(db_path)
        assert len(loaded) == 1
        assert loaded[0]["asset"] == "ETH"

    @pytest.mark.asyncio
    async def test_save_empty_clears_table(self, db_path):
        await init_db(db_path)
        await save_all_active_trades(db_path, [{"asset": "BTC", "amount": 0.1}])
        await save_all_active_trades(db_path, [])
        loaded = await load_active_trades(db_path)
        assert loaded == []

    @pytest.mark.asyncio
    async def test_preserves_all_fields(self, db_path):
        await init_db(db_path)
        trade = {
            "asset": "SOL",
            "is_long": False,
            "amount": 10.0,
            "entry_price": 150.0,
            "tp_oid": "12345",
            "sl_oid": "67890",
            "exit_plan": "sell at 160",
            "opened_at": "2026-04-27T00:00:00+00:00",
        }
        await save_all_active_trades(db_path, [trade])
        loaded = await load_active_trades(db_path)
        assert loaded[0] == trade


class TestLoadFromMissingDb:
    @pytest.mark.asyncio
    async def test_returns_empty_list_for_nonexistent_file(self, tmp_path):
        result = await load_active_trades(str(tmp_path / "nonexistent.db"))
        assert result == []
