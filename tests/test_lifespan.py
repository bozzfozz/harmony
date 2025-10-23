from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest

import app.main as app_main
from app.main import app, override_lifespan_hooks


def test_soulseek_client_closed_on_shutdown(monkeypatch) -> None:
    close_mock = AsyncMock()
    registry = SimpleNamespace(shutdown=AsyncMock())
    stop_workers = AsyncMock()

    monkeypatch.setattr(app_main, "_should_start_workers", lambda config=None: False)

    with override_lifespan_hooks(
        configure_application=lambda config: None,
        register_ui_session_metrics=lambda: None,
        get_soulseek_client=lambda: SimpleNamespace(close=close_mock),
        get_provider_registry=lambda: registry,
        stop_workers=stop_workers,
    ):
        with TestClient(app):
            pass

    assert close_mock.await_count == 1
    assert registry.shutdown.await_count == 1
    assert stop_workers.await_count == 1


def test_worker_initialization_failure_triggers_shutdown(monkeypatch) -> None:
    start_workers = AsyncMock(side_effect=RuntimeError("boom"))
    stop_workers = AsyncMock()
    close_mock = AsyncMock()
    registry_shutdown = AsyncMock()

    monkeypatch.setattr(app_main, "_should_start_workers", lambda config=None: True)

    with override_lifespan_hooks(
        configure_application=lambda config: None,
        register_ui_session_metrics=lambda: None,
        start_workers=start_workers,
        stop_workers=stop_workers,
        get_soulseek_client=lambda: SimpleNamespace(close=close_mock),
        get_provider_registry=lambda: SimpleNamespace(shutdown=registry_shutdown),
    ):
        with pytest.raises(RuntimeError):
            with TestClient(app):
                pass

    assert start_workers.await_count == 1
    assert stop_workers.await_count == 1
    assert close_mock.await_count == 1
    assert registry_shutdown.await_count == 1


def test_shutdown_order(monkeypatch) -> None:
    events: list[str] = []

    async def close_async() -> None:
        events.append("soulseek.close")

    class DummyRegistry:
        async def shutdown(self) -> None:
            events.append("registry.shutdown")

    async def stop_stub(app: Any) -> None:
        events.append("stop.workers")

    monkeypatch.setattr(app_main, "_should_start_workers", lambda config=None: False)

    with override_lifespan_hooks(
        configure_application=lambda config: None,
        register_ui_session_metrics=lambda: None,
        get_soulseek_client=lambda: SimpleNamespace(close=close_async),
        get_provider_registry=lambda: DummyRegistry(),
        stop_workers=stop_stub,
    ):
        with TestClient(app):
            pass

    assert events == [
        "soulseek.close",
        "registry.shutdown",
        "stop.workers",
    ]


def test_lifespan_idempotent_restart(monkeypatch) -> None:
    monkeypatch.setattr(app_main, "_should_start_workers", lambda config=None: True)

    start_calls: list[int] = []
    stop_calls: list[int] = []
    close_calls = AsyncMock()
    registry_shutdown = AsyncMock()

    async def start_stub(
        app: Any, config: Any, enable_artwork: bool, enable_lyrics: bool
    ) -> dict[str, bool]:
        marker = len(start_calls) + 1
        start_calls.append(marker)
        app.state.custom_marker = marker
        return {"started": True}

    async def stop_stub(app: Any) -> None:
        stop_calls.append(getattr(app.state, "custom_marker", None))
        if hasattr(app.state, "custom_marker"):
            delattr(app.state, "custom_marker")

    def get_client() -> SimpleNamespace:
        return SimpleNamespace(close=close_calls)

    def get_registry() -> SimpleNamespace:
        return SimpleNamespace(shutdown=registry_shutdown)

    with override_lifespan_hooks(
        configure_application=lambda config: None,
        register_ui_session_metrics=lambda: None,
        start_workers=start_stub,
        stop_workers=stop_stub,
        get_soulseek_client=get_client,
        get_provider_registry=get_registry,
    ):
        for _ in range(2):
            with TestClient(app):
                pass

    assert start_calls == [1, 2]
    assert stop_calls == [1, 2]
    assert close_calls.await_count == 2
    assert registry_shutdown.await_count == 2
    assert not hasattr(app.state, "custom_marker")
