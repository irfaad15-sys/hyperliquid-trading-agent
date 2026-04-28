"""Coverage-gap tests for utils, dashboard, state_builder, reconciler, and kelly."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.utils.formatting import format_number, format_size
from src.utils.prompt_utils import json_default, safe_float, round_or_none, round_series
from src.loop.dashboard import build_dashboard
from src.loop.state_builder import build_account_state
from src.loop.reconciler import reconcile_active_trades, fetch_fills
from src.intelligence.kelly import kelly_fraction, kelly_size_usd, _parse_trade_returns


# ---------------------------------------------------------------------------
# src/utils/formatting.py
# ---------------------------------------------------------------------------

class TestFormatNumber:
    def test_rounds_float(self):
        assert format_number(3.14159, 2) == 3.14

    def test_rounds_string_number(self):
        assert format_number("2.71828", 3) == 2.718

    def test_returns_raw_on_non_numeric(self):
        assert format_number("abc") == "abc"

    def test_default_decimals_is_2(self):
        assert format_number(1.9999) == 2.0

    def test_none_returns_none(self):
        assert format_number(None) is None


class TestFormatSize:
    def test_uses_6_decimal_places(self):
        assert format_size(0.1234567) == 0.123457

    def test_integer_input(self):
        assert format_size(5) == 5.0


# ---------------------------------------------------------------------------
# src/utils/prompt_utils.py
# ---------------------------------------------------------------------------

class TestJsonDefault:
    def test_datetime_serialized(self):
        from datetime import datetime, timezone
        dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert "2026-01-01" in json_default(dt)

    def test_set_converted_to_list(self):
        result = json_default({1, 2, 3})
        assert isinstance(result, list)
        assert set(result) == {1, 2, 3}

    def test_unknown_type_returns_str(self):
        class Foo:
            def __str__(self): return "foo"
        assert json_default(Foo()) == "foo"


class TestSafeFloat:
    def test_converts_string(self):
        assert safe_float("3.14") == 3.14

    def test_returns_none_for_none(self):
        assert safe_float(None) is None

    def test_returns_none_for_text(self):
        assert safe_float("abc") is None


class TestRoundSeries:
    def test_rounds_each_element(self):
        assert round_series([1.111, 2.222], 2) == [1.11, 2.22]

    def test_empty_returns_empty(self):
        assert round_series([]) == []

    def test_none_input_returns_empty(self):
        assert round_series(None) == []

    def test_non_numeric_becomes_none(self):
        result = round_series(["abc", 1.5])
        assert result[0] is None
        assert result[1] == 1.5


# ---------------------------------------------------------------------------
# src/loop/dashboard.py  (line 17 — the return dict)
# ---------------------------------------------------------------------------

class TestBuildDashboard:
    def test_returns_all_keys(self):
        d = build_dashboard(
            total_return_pct=5.5,
            balance=1000.0,
            account_value=1055.0,
            sharpe=1.2,
            positions=[],
            active_trades=[],
            open_orders=[],
            recent_diary=[],
            recent_fills=[],
        )
        assert d["total_return_pct"] == 5.5
        assert d["balance"] == 1000.0
        assert d["account_value"] == 1055.0
        assert d["sharpe_ratio"] == 1.2

    def test_active_trades_formatted(self):
        trades = [{"asset": "BTC", "is_long": True, "amount": 0.1,
                   "entry_price": 50000, "tp_oid": "1", "sl_oid": "2",
                   "exit_plan": "sell at 55k", "opened_at": "2026-01-01"}]
        d = build_dashboard(0, 1000, 1000, 0, [], trades, [], [], [])
        assert d["active_trades"][0]["asset"] == "BTC"
        assert d["active_trades"][0]["amount"] == 0.1


# ---------------------------------------------------------------------------
# src/loop/state_builder.py  (line 37 — exception path for price fetch)
# ---------------------------------------------------------------------------

class TestBuildAccountState:
    @pytest.mark.asyncio
    async def test_price_fetch_exception_returns_none(self):
        api = MagicMock()
        api.get_current_price = AsyncMock(side_effect=RuntimeError("timeout"))
        raw = {
            "balance": 1000.0,
            "total_value": 1000.0,
            "positions": [{"coin": "BTC", "szi": "0.1", "entryPx": "50000", "pnl": 0}],
        }
        balance, total_value, positions = await build_account_state(raw, api)
        assert positions[0]["current_price"] is None

    @pytest.mark.asyncio
    async def test_no_positions_returns_empty_list(self):
        api = MagicMock()
        raw = {"balance": 500.0, "total_value": 500.0, "positions": []}
        _, _, positions = await build_account_state(raw, api)
        assert positions == []

    @pytest.mark.asyncio
    async def test_coin_none_returns_none_price(self):
        api = MagicMock()
        api.get_current_price = AsyncMock(return_value=999.0)
        raw = {
            "balance": 1000.0,
            "positions": [{"coin": None, "szi": "1", "entryPx": "100", "pnl": 0}],
        }
        _, _, positions = await build_account_state(raw, api)
        assert positions[0]["current_price"] is None


# ---------------------------------------------------------------------------
# src/loop/reconciler.py  — missing branches
# ---------------------------------------------------------------------------

class TestReconcileActiveTrades:
    def test_removes_stale_trade_with_no_position_or_order(self, tmp_path):
        diary = str(tmp_path / "diary.jsonl")
        trades = [{"asset": "BTC", "opened_at": "2026-01-01"}]
        state = {"positions": []}
        reconcile_active_trades(trades, state, [], diary)
        assert trades == []
        with open(diary) as f:
            entry = json.loads(f.read())
        assert entry["action"] == "reconcile_close"

    def test_keeps_trade_that_has_open_order(self, tmp_path):
        diary = str(tmp_path / "diary.jsonl")
        trades = [{"asset": "ETH", "opened_at": "2026-01-01"}]
        state = {"positions": []}
        orders = [{"coin": "ETH"}]
        reconcile_active_trades(trades, state, orders, diary)
        assert len(trades) == 1

    def test_keeps_trade_with_live_position(self, tmp_path):
        diary = str(tmp_path / "diary.jsonl")
        trades = [{"asset": "SOL", "opened_at": "2026-01-01"}]
        state = {"positions": [{"coin": "SOL", "szi": "5.0"}]}
        reconcile_active_trades(trades, state, [], diary)
        assert len(trades) == 1

    def test_handles_bad_szi_gracefully(self, tmp_path):
        diary = str(tmp_path / "diary.jsonl")
        trades = [{"asset": "BTC"}]
        state = {"positions": [{"coin": "BTC", "szi": "bad_value"}]}
        reconcile_active_trades(trades, state, [], diary)
        # Should not crash — bad szi is skipped, trade gets reconciled
        assert isinstance(trades, list)


class TestFetchFills:
    @pytest.mark.asyncio
    async def test_formats_fills_correctly(self):
        api = MagicMock()
        api.get_recent_fills = AsyncMock(return_value=[
            {"coin": "BTC", "isBuy": True, "sz": "0.1", "px": "50000",
             "time": "1700000000000"},
        ])
        result = await fetch_fills(api)
        assert len(result) == 1
        assert result[0]["coin"] == "BTC"
        assert result[0]["is_buy"] is True

    @pytest.mark.asyncio
    async def test_returns_empty_on_api_error(self):
        api = MagicMock()
        api.get_recent_fills = AsyncMock(side_effect=RuntimeError("network"))
        result = await fetch_fills(api)
        assert result == []

    @pytest.mark.asyncio
    async def test_handles_unix_seconds_timestamp(self):
        api = MagicMock()
        api.get_recent_fills = AsyncMock(return_value=[
            {"coin": "ETH", "isBuy": False, "sz": "1", "px": "2000",
             "time": "1700000000"},  # seconds not ms
        ])
        result = await fetch_fills(api)
        assert result[0]["timestamp"] is not None

    @pytest.mark.asyncio
    async def test_limits_to_20_fills(self):
        api = MagicMock()
        api.get_recent_fills = AsyncMock(return_value=[
            {"coin": "BTC", "isBuy": True, "sz": "0.1", "px": "50000", "time": "1700000000000"}
            for _ in range(50)
        ])
        result = await fetch_fills(api)
        assert len(result) == 20


# ---------------------------------------------------------------------------
# src/intelligence/kelly.py — short trade pairing and edge cases
# ---------------------------------------------------------------------------

class TestKellyShortTrades:
    def _write_diary(self, path, entries):
        with open(path, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def test_short_trade_win_counted(self, tmp_path):
        diary = tmp_path / "diary.jsonl"
        # Open short at 50000, close at 45000 → 10% gain
        entries = [
            {"action": "sell", "asset": "BTC", "is_long": False, "entry_price": 50000},
            {"action": "buy",  "asset": "BTC", "is_long": False, "entry_price": 45000},
        ]
        self._write_diary(diary, entries)
        returns = _parse_trade_returns(str(diary), window=10)
        assert len(returns) == 1
        assert returns[0] == pytest.approx(10.0)

    def test_short_trade_loss_counted(self, tmp_path):
        diary = tmp_path / "diary.jsonl"
        # Open short at 50000, close at 55000 → 10% loss
        entries = [
            {"action": "sell", "asset": "BTC", "is_long": False, "entry_price": 50000},
            {"action": "buy",  "asset": "BTC", "is_long": False, "entry_price": 55000},
        ]
        self._write_diary(diary, entries)
        returns = _parse_trade_returns(str(diary), window=10)
        assert len(returns) == 1
        assert returns[0] == pytest.approx(-10.0)

    def test_mixed_long_and_short_both_counted(self, tmp_path):
        diary = tmp_path / "diary.jsonl"
        entries = [
            # Long win: buy 50k, sell 55k → +10%
            {"action": "buy",  "asset": "BTC", "is_long": True,  "entry_price": 50000},
            {"action": "sell", "asset": "BTC", "is_long": True,  "entry_price": 55000},
            # Short win: sell 50k, buy 45k → +10%
            {"action": "sell", "asset": "ETH", "is_long": False, "entry_price": 50000},
            {"action": "buy",  "asset": "ETH", "is_long": False, "entry_price": 45000},
        ]
        self._write_diary(diary, entries)
        returns = _parse_trade_returns(str(diary), window=10)
        assert len(returns) == 2
        assert all(r == pytest.approx(10.0) for r in returns)

    def test_legacy_entries_without_is_long_treated_as_long(self, tmp_path):
        diary = tmp_path / "diary.jsonl"
        # No is_long field — should default to long pairing
        entries = [
            {"action": "buy",  "asset": "BTC", "entry_price": 50000},
            {"action": "sell", "asset": "BTC", "entry_price": 55000},
        ]
        self._write_diary(diary, entries)
        returns = _parse_trade_returns(str(diary), window=10)
        assert len(returns) == 1
        assert returns[0] == pytest.approx(10.0)

    def test_kelly_fraction_100pct_win_rate(self):
        # win_rate=1.0 with avg_win>0, avg_loss=0.01 fallback → should return positive
        f = kelly_fraction(1.0, 10.0, 0.01)
        assert f > 0


# ---------------------------------------------------------------------------
# src/backtest/simulated_api.py — naked short (no position) path
# ---------------------------------------------------------------------------

class TestSimulatedAPINakedShort:
    @pytest.mark.asyncio
    async def test_sell_without_position_rejected(self):
        from src.backtest.simulated_api import SimulatedAPI
        sim = SimulatedAPI(
            ohlcv={"BTC": [{"t": 0, "o": 50000, "h": 50000, "l": 50000, "c": 50000, "v": 1}]},
            initial_balance=10000,
        )
        result = sim._fill_order("BTC", 0.1, is_buy=False)
        # Should reject (status != ok) not add phantom balance
        assert result.get("status") == "rejected"
        state = await sim.get_user_state()
        assert state["balance"] == pytest.approx(10000.0)

    def test_is_simulation_flag(self):
        from src.backtest.simulated_api import SimulatedAPI
        sim = SimulatedAPI(ohlcv={}, initial_balance=1000)
        assert sim.is_simulation is True


# ---------------------------------------------------------------------------
# src/storage/db.py — error path (lines 48-49)
# ---------------------------------------------------------------------------

class TestStorageErrorPath:
    @pytest.mark.asyncio
    async def test_save_handles_bad_db_path_gracefully(self):
        from src.storage.db import save_all_active_trades
        # Should log warning and not raise
        await save_all_active_trades("/nonexistent_dir/state.db", [{"asset": "BTC"}])
