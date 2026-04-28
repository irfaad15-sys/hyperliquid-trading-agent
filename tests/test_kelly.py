"""Unit tests for src/intelligence/kelly.py — Kelly criterion position sizing."""

import json
import pytest
from src.intelligence.kelly import kelly_fraction, kelly_size_usd


class TestKellyFraction:
    def test_50_50_equal_win_loss(self):
        # p=0.5, b=1 → f = (0.5*1 - 0.5)/1 = 0 — breakeven, bet nothing
        assert kelly_fraction(0.5, 1.0, 1.0) == pytest.approx(0.0)

    def test_60_pct_win_rate_equal_payoff(self):
        # p=0.6, b=1 → f = (0.6 - 0.4)/1 = 0.2
        assert kelly_fraction(0.6, 1.0, 1.0) == pytest.approx(0.2)

    def test_higher_win_ratio_increases_fraction(self):
        # b=2 (wins twice the loss), p=0.5 → f = (0.5*2 - 0.5)/2 = 0.25
        assert kelly_fraction(0.5, 2.0, 1.0) == pytest.approx(0.25)

    def test_zero_win_rate_returns_zero(self):
        assert kelly_fraction(0.0, 5.0, 1.0) == 0.0

    def test_negative_kelly_clamped_to_zero(self):
        # p=0.3, b=1 → (0.3 - 0.7) = -0.4 → clamped to 0
        assert kelly_fraction(0.3, 1.0, 1.0) == 0.0

    def test_zero_avg_loss_returns_zero(self):
        assert kelly_fraction(0.6, 2.0, 0.0) == 0.0

    def test_result_capped_at_one(self):
        # Extreme win rate / ratio shouldn't exceed 1
        assert kelly_fraction(0.99, 100.0, 0.01) <= 1.0


class TestKellySizeUsd:
    def _write_diary(self, path, entries):
        with open(path, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def _trade_pair(self, asset, entry_px, exit_px):
        return [
            {"action": "buy", "asset": asset, "entry_price": entry_px},
            {"action": "sell", "asset": asset, "entry_price": exit_px},
        ]

    def test_returns_none_when_insufficient_history(self, tmp_path):
        diary = tmp_path / "diary.jsonl"
        # Only 5 trade pairs — below min_trades=10
        entries = []
        for i in range(5):
            entries.extend(self._trade_pair("BTC", 50000, 51000))
        self._write_diary(diary, entries)
        result = kelly_size_usd(str(diary), balance=1000, max_position_usd=500)
        assert result is None

    def test_returns_none_for_missing_diary(self, tmp_path):
        result = kelly_size_usd(str(tmp_path / "nonexistent.jsonl"), balance=1000, max_position_usd=500)
        assert result is None

    def test_positive_kelly_on_winning_history(self, tmp_path):
        diary = tmp_path / "diary.jsonl"
        entries = []
        # 15 wins (10% gain each), 5 losses (5% each) — win_rate=0.75, avg_win=10, avg_loss=5
        for _ in range(15):
            entries.extend(self._trade_pair("BTC", 50000, 55000))   # +10%
        for _ in range(5):
            entries.extend(self._trade_pair("ETH", 2000, 1900))     # -5%
        self._write_diary(diary, entries)
        result = kelly_size_usd(str(diary), balance=10000, max_position_usd=5000)
        assert result is not None
        assert result > 0
        assert result <= 5000  # capped at max

    def test_capped_at_max_position_usd(self, tmp_path):
        diary = tmp_path / "diary.jsonl"
        entries = []
        # Very profitable history — Kelly would suggest large bet
        for _ in range(20):
            entries.extend(self._trade_pair("BTC", 1000, 2000))  # +100% wins
        self._write_diary(diary, entries)
        result = kelly_size_usd(str(diary), balance=100000, max_position_usd=200, min_trades=10)
        assert result is not None
        assert result <= 200

    def test_zero_kelly_on_losing_history(self, tmp_path):
        diary = tmp_path / "diary.jsonl"
        entries = []
        # All losses — Kelly should be 0, returns None or 0
        for _ in range(15):
            entries.extend(self._trade_pair("BTC", 50000, 45000))
        self._write_diary(diary, entries)
        result = kelly_size_usd(str(diary), balance=10000, max_position_usd=5000)
        # Kelly fraction is 0 for all losses → size=0 → should return 0 or None
        assert result is None or result == pytest.approx(0.0)

    def test_risk_force_close_counted_as_loss(self, tmp_path):
        diary = tmp_path / "diary.jsonl"
        entries = []
        for _ in range(12):
            entries.extend(self._trade_pair("BTC", 50000, 55000))  # wins
        for _ in range(3):
            entries.append({"action": "risk_force_close", "asset": "ETH", "loss_pct": 20})
        self._write_diary(diary, entries)
        result = kelly_size_usd(str(diary), balance=10000, max_position_usd=5000)
        assert result is not None
        assert result <= 5000

    def test_custom_window_limits_lookback(self, tmp_path):
        diary = tmp_path / "diary.jsonl"
        entries = []
        # 5 old losses then 20 recent wins — window=20 should see mostly wins
        for _ in range(5):
            entries.extend(self._trade_pair("BTC", 50000, 40000))
        for _ in range(20):
            entries.extend(self._trade_pair("BTC", 50000, 60000))
        self._write_diary(diary, entries)
        result_wide = kelly_size_usd(str(diary), balance=10000, max_position_usd=5000, window=50)
        result_narrow = kelly_size_usd(str(diary), balance=10000, max_position_usd=5000, window=20)
        # Narrower window (recent only) should be more bullish than wide window
        assert result_narrow is not None
        assert result_wide is not None
        assert result_narrow >= result_wide
