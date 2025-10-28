"""Tests for settings store counter helpers."""

from __future__ import annotations

from uuid import uuid4

from app.utils.settings_store import delete_setting, increment_counter, write_setting


def _unique_key() -> str:
    return f"tests.settings_store.{uuid4()}"


def test_increment_counter_amount_zero_returns_existing_value_for_numeric_string() -> None:
    key = _unique_key()
    try:
        write_setting(key, "  42  ")

        result = increment_counter(key, amount=0)

        assert result == 42
    finally:
        delete_setting(key)


def test_increment_counter_amount_zero_preserves_negative_values() -> None:
    key = _unique_key()
    try:
        write_setting(key, " -5 ")

        result = increment_counter(key, amount=0)

        assert result == -5
    finally:
        delete_setting(key)


def test_increment_counter_amount_zero_falls_back_for_invalid_values() -> None:
    key = _unique_key()
    try:
        write_setting(key, "not-a-number")

        result = increment_counter(key, amount=0)

        assert result == 0
    finally:
        delete_setting(key)
