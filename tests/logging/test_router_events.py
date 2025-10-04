"""Snapshot tests for router logging events."""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

from app import logging_events
from app.middleware import request_logging


def _load_module(name: str):
    module = sys.modules.get(name)
    if module is None:
        module = importlib.import_module(name)
    return module


download_router_module = _load_module("app.routers.download_router")
metadata_router_module = _load_module("app.routers.metadata_router")
soulseek_router_module = _load_module("app.routers.soulseek_router")
sync_router_module = _load_module("app.routers.sync_router")


class _StubDownloadService:
    def list_downloads(
        self,
        *,
        include_all: bool,
        status_filter: str | None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        assert include_all is True
        assert status_filter == "queued"
        assert limit == 5
        assert offset == 2
        return []


def _first_record(caplog, event: str):
    for record in caplog.records:
        if record.message == event:
            return record
    raise AssertionError(f"event {event!r} not found in logs")


def test_download_router_list_emits_structured_event(caplog, monkeypatch) -> None:
    monkeypatch.setattr(download_router_module.logger, "disabled", False)
    service = _StubDownloadService()

    with caplog.at_level("INFO", logger="app.routers.download_router"):
        response = download_router_module.list_downloads(
            limit=5,
            offset=2,
            all=True,
            status_filter="queued",
            service=service,
        )

    assert response.downloads == []

    record = _first_record(caplog, "api.download.list")
    assert record.event == "api.download.list"
    assert record.component == "router.download"
    assert record.status == "requested"
    assert record.entity_id is None
    assert record.include_all is True
    assert record.status_filter == "queued"
    assert record.limit == 5
    assert record.offset == 2


class _StubMetadataUpdateWorker:
    def __init__(self) -> None:
        self.started = False

    async def start(self) -> dict[str, str]:
        self.started = True
        return {"status": "running"}


@pytest.mark.asyncio
async def test_metadata_router_logs_start_event(caplog, monkeypatch) -> None:
    monkeypatch.setattr(metadata_router_module.logger, "disabled", False)

    worker = _StubMetadataUpdateWorker()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(metadata_update_worker=worker))
    )

    with caplog.at_level("INFO", logger="app.routers.metadata_router"):
        payload = await metadata_router_module.start_metadata_update(request)

    assert worker.started is True
    assert payload["status"] == "running"

    record = _first_record(caplog, "api.metadata.request")
    assert record.component == "router.metadata"
    assert record.status == "accepted"
    assert record.action == "update"


class _FailingSoulseekClient:
    async def get_download_status(self) -> None:  # pragma: no cover - behaviour mocked
        raise RuntimeError("daemon unavailable")


@pytest.mark.asyncio
async def test_soulseek_status_failure_logs_error_event(caplog, monkeypatch) -> None:
    monkeypatch.setattr(soulseek_router_module.logger, "disabled", False)
    with caplog.at_level("INFO", logger="app.routers.soulseek_router"):
        response = await soulseek_router_module.soulseek_status(client=_FailingSoulseekClient())

    assert response.status == "disconnected"

    record = _first_record(caplog, "api.soulseek.status")
    assert record.component == "router.soulseek"
    assert record.status == "error"
    assert record.error == "daemon unavailable"


@pytest.mark.asyncio
async def test_sync_router_missing_credentials_logs_blocked_event(
    caplog, monkeypatch
) -> None:
    monkeypatch.setattr(sync_router_module.logger, "disabled", False)
    async def fake_missing_credentials(session_runner):  # pragma: no cover - simple stub
        return {"spotify": ("token",)}

    monkeypatch.setattr(
        sync_router_module, "_missing_credentials", fake_missing_credentials
    )
    monkeypatch.setattr(
        sync_router_module, "record_activity", lambda *args, **kwargs: None
    )

    with caplog.at_level("INFO", logger="app.routers.sync_router"):
        with pytest.raises(HTTPException):
            await sync_router_module.trigger_manual_sync(
                request=object(), session_runner=None
            )

    record = _first_record(caplog, "api.sync.trigger")
    assert record.component == "router.sync"
    assert record.status == "blocked"
    assert record.entity_id is None
    assert record.meta == {"missing": {"spotify": ["token"]}}


def test_request_logging_shim_uses_single_log_event_instance() -> None:
    assert request_logging.log_event is logging_events.log_event
