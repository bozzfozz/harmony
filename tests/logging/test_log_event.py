from __future__ import annotations

from unittest.mock import Mock

import pytest

from app.logging_events import log_event, now_ms


def test_log_event_emits_expected_extra_fields() -> None:
    logger = Mock()

    log_event(
        logger,
        "cache.hit",
        component="cache",
        status="ok",
        entity_id="key-1",
        meta={"nested": {"value": 1}},
    )

    logger.info.assert_called_once()
    args, kwargs = logger.info.call_args
    assert args == ("cache.hit",)
    assert kwargs["extra"] == {
        "event": "cache.hit",
        "component": "cache",
        "status": "ok",
        "entity_id": "key-1",
        "meta": {"nested": {"value": 1}},
    }


def test_log_event_rejects_empty_event() -> None:
    logger = Mock()

    with pytest.raises(ValueError):
        log_event(logger, "")


def test_log_event_rejects_invalid_meta_type() -> None:
    logger = Mock()

    with pytest.raises(TypeError):
        log_event(logger, "sample", component="x", status="ok", meta="oops")


def test_now_ms_returns_positive_integer() -> None:
    value = now_ms()
    assert isinstance(value, int)
    assert value > 0
