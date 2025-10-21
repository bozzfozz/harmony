from __future__ import annotations

import asyncio
from collections.abc import Mapping
from types import SimpleNamespace

import pytest

from app.integrations.health import IntegrationHealth, ProviderHealth
from app.schemas import StatusResponse
from app.ui.context import build_soulseek_user_directory_context
from app.ui.services.soulseek import (
    SoulseekUiService,
    SoulseekUserDirectoryListing,
)


class _StubRegistry:
    def __init__(self) -> None:
        self.initialised = False

    def initialise(self) -> None:
        self.initialised = True

    def track_providers(self) -> dict[str, object]:
        return {}


def _make_service(
    *,
    soulseek_overrides: dict[str, object] | None = None,
    security_overrides: dict[str, object] | None = None,
) -> SoulseekUiService:
    base_soulseek = {
        "base_url": "https://slskd.example",
        "api_key": "token",
        "timeout_ms": 8_000,
        "retry_max": 3,
        "retry_backoff_base_ms": 250,
        "retry_jitter_pct": 20.0,
        "preferred_formats": ("flac", "mp3"),
        "max_results": 50,
    }
    base_security = {
        "profile": "default",
        "require_auth": True,
        "rate_limiting_enabled": True,
    }
    if soulseek_overrides:
        base_soulseek.update(soulseek_overrides)
    if security_overrides:
        base_security.update(security_overrides)

    config = SimpleNamespace(
        soulseek=SimpleNamespace(**base_soulseek),
        security=SimpleNamespace(**base_security),
    )
    registry = _StubRegistry()
    return SoulseekUiService(
        request=SimpleNamespace(),
        config=config,
        soulseek_client=SimpleNamespace(),
        registry=registry,
    )


def test_suggested_tasks_reflects_healthy_configuration() -> None:
    service = _make_service()
    status = StatusResponse(status="ok")
    health = IntegrationHealth(
        overall="ok",
        providers=(ProviderHealth(provider="soulseek", status="ok", details={}),),
    )

    tasks = service.suggested_tasks(status=status, health=health)

    assert len(tasks) == 10
    assert all(task.completed for task in tasks)


def test_suggested_tasks_marks_daemon_completed_for_connected_status() -> None:
    service = _make_service()
    status = StatusResponse(status="connected")
    health = IntegrationHealth(
        overall="ok",
        providers=(ProviderHealth(provider="soulseek", status="ok", details={}),),
    )

    tasks = service.suggested_tasks(status=status, health=health)

    daemon_task = next(task for task in tasks if task.identifier == "daemon")
    assert daemon_task.completed is True


def test_suggested_tasks_flags_gaps_and_limits_count() -> None:
    service = _make_service(
        soulseek_overrides={
            "api_key": "",
            "preferred_formats": (),
            "retry_max": 1,
            "retry_jitter_pct": 0.0,
            "timeout_ms": 12_000,
            "max_results": 200,
        },
        security_overrides={
            "require_auth": False,
            "rate_limiting_enabled": False,
        },
    )
    status = StatusResponse(status="down")
    health = IntegrationHealth(
        overall="down",
        providers=(ProviderHealth(provider="soulseek", status="down", details={}),),
    )

    tasks = service.suggested_tasks(status=status, health=health, limit=5)

    assert len(tasks) == 5
    flags = {
        task.identifier: task.completed
        for task in service.suggested_tasks(status=status, health=health)
    }
    assert flags["daemon"] is False
    assert flags["providers"] is False
    assert flags["api-key"] is False
    assert flags["preferred-formats"] is False
    assert flags["retry-policy"] is False
    assert flags["retry-jitter"] is False
    assert flags["timeout"] is False
    assert flags["max-results"] is False
    assert flags["require-auth"] is False
    assert flags["rate-limiting"] is False


def test_extract_files_preserves_zero_size_and_renders_zero_bytes() -> None:
    payload = {
        "files": [
            {
                "name": "silence.flac",
                "path": "Music/silence.flac",
                "size": 0,
            }
        ]
    }

    files = SoulseekUiService._extract_files(payload)

    assert files
    assert files[0].size_bytes == 0

    listing = SoulseekUserDirectoryListing(
        username="alice",
        current_path="Music",
        parent_path=None,
        directories=(),
        files=files,
    )

    class _DummyRequest:
        def url_for(self, name: str, **kwargs: object) -> str:
            raise RuntimeError("no routes")

    context = build_soulseek_user_directory_context(
        _DummyRequest(),
        username="alice",
        path="Music",
        listing=listing,
        status=None,
        browsing_status=None,
    )

    sizes = tuple(file.size for file in context["files"])
    assert "0 B" in sizes


def test_user_directory_context_marks_listing_present_even_when_empty() -> None:
    listing = SoulseekUserDirectoryListing(
        username="alice",
        current_path="Music/Albums",
        parent_path="Music",
        directories=(),
        files=(),
    )

    class _DummyRequest:
        def url_for(self, name: str, **kwargs: object) -> str:
            raise RuntimeError("no routes")

    context = build_soulseek_user_directory_context(
        _DummyRequest(),
        username="alice",
        path="Music/Albums",
        listing=listing,
        status=None,
        browsing_status=None,
    )

    assert context["has_listing"] is True
    assert context["parent_path"] == "Music"
    assert context["parent_url"] == "/ui/soulseek/user/directory?username=alice&path=Music"
    assert context["directories"] == ()
    assert context["files"] == ()


@pytest.mark.asyncio
async def test_user_directory_trims_provided_path(monkeypatch) -> None:
    recorded: dict[str, object] = {}

    async def _fake_user_directory(*, username: str, path: str, client: object) -> Mapping[str, object]:
        recorded["username"] = username
        recorded["path"] = path
        return {
            "path": path,
            "directories": (),
            "files": (),
        }

    async def _unexpected_browse(**_: object) -> Mapping[str, object]:
        raise AssertionError("browse should not be invoked when path is provided")

    monkeypatch.setattr(
        "app.ui.services.soulseek.soulseek_user_directory",
        _fake_user_directory,
    )
    monkeypatch.setattr(
        "app.ui.services.soulseek.soulseek_user_browse",
        _unexpected_browse,
    )
    service = _make_service()

    listing = await service.user_directory(username=" alice ", path="  Music/Albums  ")

    assert recorded["username"] == "alice"
    assert recorded["path"] == "Music/Albums"
    assert listing.current_path == "Music/Albums"


def test_extract_directories_handles_mapping_payloads() -> None:
    payload = {
        "directories": {
            "music": {
                "name": "Music",
                "path": "Music",
            },
            "samples": {
                "path": "Music/Samples",
            },
        }
    }

    directories = SoulseekUiService._extract_directories(payload)

    assert len(directories) == 2
    names = {entry.name for entry in directories}
    paths = {entry.path for entry in directories}
    assert names == {"Music", "Samples"}
    assert paths == {"Music", "Music/Samples"}


def test_extract_files_handles_mapping_payloads() -> None:
    payload = {
        "files": {
            "silence": {
                "name": "silence.flac",
                "path": "Music/silence.flac",
                "size": 0,
            },
            "noise": {
                "filename": "noise.mp3",
                "size_bytes": 512,
            },
        }
    }

    files = SoulseekUiService._extract_files(payload)

    assert len(files) == 2
    names = {entry.name for entry in files}
    sizes = {entry.size_bytes for entry in files}
    assert names == {"silence.flac", "noise.mp3"}
    assert sizes == {0, 512}


@pytest.mark.asyncio
async def test_user_status_preserves_zero_values(monkeypatch) -> None:
    async def _fake_user_status(*, username: str, client: object) -> Mapping[str, object]:
        assert username == "alice"
        return {
            "state": "Online",
            "status_message": " ",
            "shared_count": 0,
            "avg_speed": 0,
        }

    monkeypatch.setattr(
        "app.ui.services.soulseek.soulseek_user_status",
        _fake_user_status,
    )
    service = _make_service()

    result = await service.user_status(username="alice")

    assert result.state == "online"
    assert result.shared_files == 0
    assert result.average_speed_bps == 0.0


@pytest.mark.asyncio
async def test_user_browsing_status_preserves_zero_values(monkeypatch) -> None:
    async def _fake_browsing_status(
        *,
        username: str,
        client: object,
    ) -> Mapping[str, object]:
        assert username == "alice"
        return {
            "state": "Queued",
            "percent": 0,
            "position": 0,
            "queue_size": 0,
        }

    monkeypatch.setattr(
        "app.ui.services.soulseek.soulseek_user_browsing_status",
        _fake_browsing_status,
    )
    service = _make_service()

    result = await service.user_browsing_status(username="alice")

    assert result.state == "queued"
    assert result.progress == 0.0
    assert result.queue_position == 0
    assert result.queue_length == 0


@pytest.mark.asyncio
async def test_user_profile_requests_address_and_info_concurrently(monkeypatch) -> None:
    address_started = asyncio.Event()
    info_started = asyncio.Event()

    async def _fake_user_address(*, username: str, client: object) -> Mapping[str, object]:
        assert username == "alice"
        address_started.set()
        await asyncio.wait_for(info_started.wait(), timeout=0.2)
        return {"city": "Test"}

    async def _fake_user_info(*, username: str, client: object) -> Mapping[str, object]:
        assert username == "alice"
        info_started.set()
        await asyncio.wait_for(address_started.wait(), timeout=0.2)
        return {"bio": "Hello"}

    monkeypatch.setattr(
        "app.ui.services.soulseek.soulseek_user_address",
        _fake_user_address,
    )
    monkeypatch.setattr(
        "app.ui.services.soulseek.soulseek_user_info",
        _fake_user_info,
    )
    service = _make_service()

    profile = await service.user_profile(username=" alice ")

    assert address_started.is_set() is True
    assert info_started.is_set() is True
    assert profile.username == "alice"
    assert profile.address == {"city": "Test"}
    assert profile.info == {"bio": "Hello"}
