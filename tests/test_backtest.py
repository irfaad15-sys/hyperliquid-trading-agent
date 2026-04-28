"""Unit tests for src/backtest/ — SimulatedAPI and report computation."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.backtest.simulated_api import SimulatedAPI
from src.backtest.runner import _compute_report, load_ohlcv_csv


def _candles(prices: list[float]) -> list[dict]:
    return [{"t": i * 60000, "o": p, "h": p, "l": p, "c": p, "v": 1000.0}
            for i, p in enumerate(prices)]


class TestSimulatedAPI:
    @pytest.mark.asyncio
    async def test_initial_balance_in_user_state(self):
        sim = SimulatedAPI(ohlcv={"BTC": _candles([50000])}, initial_balance=5000)
        state = await sim.get_user_state()
        assert state["balance"] == 5000.0

    @pytest.mark.asyncio
    async def test_buy_reduces_balance(self):
        sim = SimulatedAPI(ohlcv={"BTC": _candles([50000, 51000])}, initial_balance=10000)
        await sim.place_buy_order("BTC", 0.1)  # cost = 5000
        state = await sim.get_user_state()
        assert state["balance"] == pytest.approx(5000.0)

    @pytest.mark.asyncio
    async def test_sell_after_buy_books_profit(self):
        prices = [50000, 55000]
        sim = SimulatedAPI(ohlcv={"BTC": _candles(prices)}, initial_balance=10000)
        await sim.place_buy_order("BTC", 0.1)   # buy at 50000, cost=5000
        sim.advance()                            # price moves to 55000
        await sim.place_sell_order("BTC", 0.1)  # sell at 55000, proceeds=5500+500 pnl
        state = await sim.get_user_state()
        assert state["balance"] == pytest.approx(10500.0)

    @pytest.mark.asyncio
    async def test_get_candles_returns_up_to_limit(self):
        sim = SimulatedAPI(ohlcv={"BTC": _candles([1, 2, 3, 4, 5])}, initial_balance=1000)
        sim._cursor["BTC"] = 4  # at end
        candles = await sim.get_candles("BTC", "5m", 3)
        assert len(candles) == 3
        assert candles[-1]["c"] == 5

    def test_is_done_after_advancing_past_end(self):
        sim = SimulatedAPI(ohlcv={"BTC": _candles([1, 2])}, initial_balance=1000)
        assert sim.is_done() is False
        sim.advance()
        assert sim.is_done() is True

    @pytest.mark.asyncio
    async def test_fills_recorded(self):
        sim = SimulatedAPI(ohlcv={"BTC": _candles([50000])}, initial_balance=10000)
        await sim.place_buy_order("BTC", 0.1)
        fills = await sim.get_recent_fills()
        assert len(fills) == 1
        assert fills[0]["coin"] == "BTC"
        assert fills[0]["isBuy"] is True


class TestComputeReport:
    def test_no_fills_returns_zero_metrics(self):
        report = _compute_report(10000, 10000, [])
        assert report["total_trades"] == 0
        assert report["total_return_pct"] == 0.0

    def test_positive_return_computed(self):
        report = _compute_report(initial_balance=10000, final_balance=11000, fills=[])
        assert report["total_return_pct"] == pytest.approx(10.0)

    def test_negative_return_computed(self):
        report = _compute_report(initial_balance=10000, final_balance=9000, fills=[])
        assert report["total_return_pct"] == pytest.approx(-10.0)

    def test_win_rate_computed_from_paired_fills(self):
        fills = [
            {"coin": "BTC", "isBuy": True,  "px": "50000", "sz": "0.1"},
            {"coin": "BTC", "isBuy": False, "px": "55000", "sz": "0.1"},  # win
            {"coin": "ETH", "isBuy": True,  "px": "2000",  "sz": "1"},
            {"coin": "ETH", "isBuy": False, "px": "1800",  "sz": "1"},  # loss
        ]
        report = _compute_report(10000, 10300, fills)
        assert report["win_rate_pct"] == pytest.approx(50.0)
        assert report["total_trades"] == 4


class TestLoadOhlcvCsv:
    def test_loads_csv_correctly(self, tmp_path):
        csv_file = tmp_path / "btc.csv"
        csv_file.write_text(
            "timestamp,open,high,low,close,volume\n"
            "1700000000000,50000,51000,49000,50500,100\n"
            "1700060000000,50500,52000,50000,51000,120\n"
        )
        candles = load_ohlcv_csv(str(csv_file), "BTC")
        assert len(candles) == 2
        assert candles[0]["c"] == 50500.0
        assert candles[1]["o"] == 50500.0

    def test_skips_malformed_rows(self, tmp_path):
        csv_file = tmp_path / "btc.csv"
        csv_file.write_text(
            "timestamp,open,high,low,close,volume\n"
            "bad_row,notanumber,x,x,x,x\n"
            "1700000000000,50000,51000,49000,50500,100\n"
        )
        candles = load_ohlcv_csv(str(csv_file), "BTC")
        assert len(candles) == 1
