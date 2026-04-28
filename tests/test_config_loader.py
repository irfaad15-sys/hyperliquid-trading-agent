"""Unit tests for src/config_loader.py helper functions."""

import os
import pytest
from src.config_loader import _get_bool, _get_int, _get_list, _get_env


class TestGetBool:
    def test_truthy_values(self, monkeypatch):
        for val in ("1", "true", "True", "TRUE", "yes", "on"):
            monkeypatch.setenv("TEST_BOOL", val)
            assert _get_bool("TEST_BOOL") is True, f"expected True for {val!r}"

    def test_falsy_values(self, monkeypatch):
        for val in ("0", "false", "False", "no", "off", ""):
            monkeypatch.setenv("TEST_BOOL", val)
            assert _get_bool("TEST_BOOL") is False, f"expected False for {val!r}"

    def test_missing_returns_default(self, monkeypatch):
        monkeypatch.delenv("TEST_BOOL", raising=False)
        assert _get_bool("TEST_BOOL") is False
        assert _get_bool("TEST_BOOL", default=True) is True


class TestGetInt:
    def test_valid_integer(self, monkeypatch):
        monkeypatch.setenv("TEST_INT", "42")
        assert _get_int("TEST_INT") == 42

    def test_missing_returns_default(self, monkeypatch):
        monkeypatch.delenv("TEST_INT", raising=False)
        assert _get_int("TEST_INT", default=7) == 7

    def test_empty_string_returns_default(self, monkeypatch):
        monkeypatch.setenv("TEST_INT", "")
        assert _get_int("TEST_INT", default=99) == 99

    def test_invalid_value_raises(self, monkeypatch):
        monkeypatch.setenv("TEST_INT", "not_a_number")
        with pytest.raises(RuntimeError, match="Invalid integer"):
            _get_int("TEST_INT")


class TestGetList:
    def test_space_separated_is_single_item(self, monkeypatch):
        # _get_list splits on commas only; space-separated is one item
        monkeypatch.setenv("TEST_LIST", "BTC ETH SOL")
        assert _get_list("TEST_LIST") == ["BTC ETH SOL"]

    def test_comma_separated(self, monkeypatch):
        monkeypatch.setenv("TEST_LIST", "BTC,ETH,SOL")
        assert _get_list("TEST_LIST") == ["BTC", "ETH", "SOL"]

    def test_json_array(self, monkeypatch):
        monkeypatch.setenv("TEST_LIST", '["BTC", "ETH"]')
        assert _get_list("TEST_LIST") == ["BTC", "ETH"]

    def test_missing_returns_default(self, monkeypatch):
        monkeypatch.delenv("TEST_LIST", raising=False)
        assert _get_list("TEST_LIST", default=["X"]) == ["X"]

    def test_empty_returns_default(self, monkeypatch):
        monkeypatch.setenv("TEST_LIST", "")
        assert _get_list("TEST_LIST", default=["X"]) == ["X"]


class TestGetEnv:
    def test_returns_value(self, monkeypatch):
        monkeypatch.setenv("TEST_VAR", "hello")
        assert _get_env("TEST_VAR") == "hello"

    def test_returns_default_when_missing(self, monkeypatch):
        monkeypatch.delenv("TEST_VAR", raising=False)
        assert _get_env("TEST_VAR", default="default_val") == "default_val"

    def test_required_missing_raises(self, monkeypatch):
        monkeypatch.delenv("TEST_VAR", raising=False)
        with pytest.raises(RuntimeError, match="Missing required environment variable"):
            _get_env("TEST_VAR", required=True)

    def test_required_empty_raises(self, monkeypatch):
        monkeypatch.setenv("TEST_VAR", "")
        with pytest.raises(RuntimeError, match="Missing required environment variable"):
            _get_env("TEST_VAR", required=True)
