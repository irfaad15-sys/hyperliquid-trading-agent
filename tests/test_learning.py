"""Unit tests for src/loop/learning.py (C3 post-trade learning)."""

import json
import os
import pytest
from src.loop.learning import load_recent_outcomes


def _write_diary(path, entries):
    with open(path, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


class TestLoadRecentOutcomes:
    def test_returns_last_n_trade_entries(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LEARNING_WINDOW", "3")
        diary = tmp_path / "diary.jsonl"
        _write_diary(diary, [
            {"action": "buy", "asset": "BTC", "entry_price": 50000, "rationale": "bullish"},
            {"action": "hold", "asset": "ETH"},  # skipped — not a trade outcome
            {"action": "sell", "asset": "ETH", "entry_price": 2000, "rationale": "overbought"},
            {"action": "risk_force_close", "asset": "SOL", "pnl": -50, "loss_pct": 22},
            {"action": "buy", "asset": "BTC", "entry_price": 51000, "rationale": "breakout"},
        ])
        result = load_recent_outcomes(str(diary))
        assert len(result) == 3
        assert result[0]["asset"] == "ETH"  # chronological order
        assert result[1]["action"] == "risk_force_close"
        assert result[2]["asset"] == "BTC"

    def test_returns_empty_when_window_is_zero(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LEARNING_WINDOW", "0")
        diary = tmp_path / "diary.jsonl"
        _write_diary(diary, [{"action": "buy", "asset": "BTC"}])
        assert load_recent_outcomes(str(diary)) == []

    def test_returns_empty_for_missing_diary(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LEARNING_WINDOW", "5")
        result = load_recent_outcomes(str(tmp_path / "nonexistent.jsonl"))
        assert result == []

    def test_skips_hold_and_reconcile_entries(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LEARNING_WINDOW", "5")
        diary = tmp_path / "diary.jsonl"
        _write_diary(diary, [
            {"action": "hold", "asset": "BTC"},
            {"action": "reconcile_close", "asset": "ETH"},
            {"action": "risk_blocked", "asset": "SOL"},
        ])
        assert load_recent_outcomes(str(diary)) == []

    def test_outcome_fields_mapped_correctly(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LEARNING_WINDOW", "5")
        diary = tmp_path / "diary.jsonl"
        _write_diary(diary, [{
            "action": "buy",
            "asset": "BTC",
            "timestamp": "2026-01-01T00:00:00Z",
            "entry_price": 50000,
            "allocation_usd": 100,
            "filled": True,
            "rationale": "bullish momentum",
        }])
        result = load_recent_outcomes(str(diary))
        assert len(result) == 1
        r = result[0]
        assert r["action"] == "buy"
        assert r["asset"] == "BTC"
        assert r["entry_price"] == 50000
        assert r["allocation_usd"] == 100
        assert r["filled"] is True
        assert r["rationale"] == "bullish momentum"

    def test_handles_malformed_diary_lines(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LEARNING_WINDOW", "5")
        diary = tmp_path / "diary.jsonl"
        with open(diary, "w") as f:
            f.write("not valid json\n")
            f.write(json.dumps({"action": "buy", "asset": "BTC"}) + "\n")
        result = load_recent_outcomes(str(diary))
        assert len(result) == 1
        assert result[0]["asset"] == "BTC"
