"""Unit tests for src/risk_manager.py — all safety guards."""

import pytest
from src.risk_manager import RiskManager


@pytest.fixture
def rm():
    """RiskManager with predictable defaults (reads from env via CONFIG)."""
    return RiskManager()


class TestCheckPositionSize:
    def test_within_limit(self, rm):
        ok, reason = rm.check_position_size(alloc_usd=10, account_value=1000)
        assert ok is True
        assert reason == ""

    def test_over_limit(self, rm):
        # max_position_pct default is 20 → max = 200 on a $1000 account
        ok, reason = rm.check_position_size(alloc_usd=300, account_value=1000)
        assert ok is False
        assert "exceeds" in reason

    def test_zero_account_value(self, rm):
        ok, reason = rm.check_position_size(alloc_usd=10, account_value=0)
        assert ok is False


class TestCheckLeverage:
    def test_normal_leverage(self, rm):
        ok, reason = rm.check_leverage(alloc_usd=100, balance=1000)
        assert ok is True

    def test_excessive_leverage(self, rm):
        # default max_leverage=10; 10001/1000 = 10.001x
        ok, reason = rm.check_leverage(alloc_usd=10001, balance=1000)
        assert ok is False
        assert "leverage" in reason.lower()

    def test_zero_balance(self, rm):
        ok, reason = rm.check_leverage(alloc_usd=100, balance=0)
        assert ok is False


class TestCheckDailyDrawdown:
    def test_no_drawdown_allowed(self, rm):
        ok, _ = rm.check_daily_drawdown(account_value=1000)
        assert ok is True

    def test_circuit_breaker_triggers(self, rm):
        # daily_loss_circuit_breaker_pct default = 25
        rm.check_daily_drawdown(account_value=1000)   # sets daily_high = 1000
        ok, reason = rm.check_daily_drawdown(account_value=700)  # 30% drawdown
        assert ok is False
        assert "circuit breaker" in reason.lower()

    def test_circuit_breaker_stays_active(self, rm):
        rm.check_daily_drawdown(account_value=1000)
        rm.check_daily_drawdown(account_value=700)   # triggers
        ok, reason = rm.check_daily_drawdown(account_value=900)  # recovery, still blocked
        assert ok is False


class TestCheckConcurrentPositions:
    def test_under_limit(self, rm):
        ok, _ = rm.check_concurrent_positions(current_count=0)
        assert ok is True

    def test_at_limit(self, rm):
        # default max_concurrent_positions=10
        ok, reason = rm.check_concurrent_positions(current_count=10)
        assert ok is False
        assert "max concurrent" in reason.lower()


class TestCheckBalanceReserve:
    def test_balance_above_reserve(self, rm):
        # min_balance_reserve_pct=10 → min = 100 on 1000 initial account value
        ok, _ = rm.check_balance_reserve(account_value=900, initial_account_value=1000)
        assert ok is True

    def test_balance_below_reserve(self, rm):
        ok, reason = rm.check_balance_reserve(account_value=50, initial_account_value=1000)
        assert ok is False
        assert "reserve" in reason.lower()

    def test_zero_initial_balance_skips_check(self, rm):
        ok, _ = rm.check_balance_reserve(account_value=0, initial_account_value=0)
        assert ok is True


class TestEnforceStopLoss:
    def test_existing_sl_unchanged(self, rm):
        result = rm.enforce_stop_loss(sl_price=95.0, entry_price=100.0, is_buy=True)
        assert result == 95.0

    def test_auto_sl_long(self, rm):
        # mandatory_sl_pct=5 → SL = 100 - 5 = 95
        result = rm.enforce_stop_loss(sl_price=None, entry_price=100.0, is_buy=True)
        assert result == 95.0

    def test_auto_sl_short(self, rm):
        # SL above entry for shorts: 100 + 5 = 105
        result = rm.enforce_stop_loss(sl_price=None, entry_price=100.0, is_buy=False)
        assert result == 105.0


class TestCheckLosingPositions:
    def test_no_losses(self, rm):
        positions = [{"coin": "BTC", "szi": "0.1", "entryPx": "50000", "pnl": "100"}]
        result = rm.check_losing_positions(positions)
        assert result == []

    def test_loss_below_threshold(self, rm):
        # max_loss_per_position_pct=20; notional=5000, pnl=-500 → 10% loss
        positions = [{"coin": "BTC", "szi": "0.1", "entryPx": "50000", "pnl": "-500"}]
        result = rm.check_losing_positions(positions)
        assert result == []

    def test_loss_at_threshold_triggers_close(self, rm):
        # 20% loss: notional=5000, pnl=-1000
        positions = [{"coin": "BTC", "szi": "0.1", "entryPx": "50000", "pnl": "-1000"}]
        result = rm.check_losing_positions(positions)
        assert len(result) == 1
        assert result[0]["coin"] == "BTC"
        assert result[0]["is_long"] is True

    def test_skips_zero_size_positions(self, rm):
        positions = [{"coin": "BTC", "szi": "0", "entryPx": "50000", "pnl": "-9999"}]
        result = rm.check_losing_positions(positions)
        assert result == []


class TestValidateTrade:
    def _state(self, balance=1000, total_value=1000, positions=None):
        return {"balance": balance, "total_value": total_value, "positions": positions or []}

    def test_hold_always_allowed(self, rm):
        trade = {"action": "hold"}
        ok, reason, _ = rm.validate_trade(trade, self._state(), 1000)
        assert ok is True

    def test_zero_allocation_blocked(self, rm):
        trade = {"action": "buy", "allocation_usd": 0}
        ok, reason, _ = rm.validate_trade(trade, self._state(), 1000)
        assert ok is False

    def test_normal_buy_allowed_and_sl_auto_set(self, rm):
        trade = {
            "action": "buy",
            "allocation_usd": 50,
            "current_price": 100.0,
            "sl_price": None,
        }
        ok, reason, adjusted = rm.validate_trade(trade, self._state(), 1000)
        assert ok is True
        assert adjusted["sl_price"] is not None
        assert adjusted["sl_price"] < 100.0  # SL below entry for longs

    def test_below_minimum_order_bumped_to_11(self, rm):
        trade = {"action": "buy", "allocation_usd": 5, "current_price": 100.0}
        ok, _, adjusted = rm.validate_trade(trade, self._state(), 1000)
        assert ok is True
        assert adjusted["allocation_usd"] >= 11.0
