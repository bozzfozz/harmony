from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.config import load_config
from app.services.spotify_domain_service import SpotifyDomainService


class _StubSpotifyClient:
    def __init__(self, authenticated: bool) -> None:
        self._authenticated = authenticated

    def is_authenticated(self) -> bool:
        return self._authenticated


class _StubSoulseekClient:
    async def close(self) -> None:  # pragma: no cover - interface shim
        return None


class _HealthySoulseek:
    def __init__(self) -> None:
        self.closed = False

    async def get_download_status(self) -> dict[str, str]:
        return {"status": "ok"}

    async def close(self) -> None:
        self.closed = True


class _FailingSoulseek:
    def __init__(self, error: Exception) -> None:
        self._error = error
        self.closed = False

    async def get_download_status(self) -> dict[str, str]:
        raise self._error

    async def close(self) -> None:
        self.closed = True


def _make_service(*, authenticated: bool = True) -> SpotifyDomainService:
    config = load_config()
    spotify_client = _StubSpotifyClient(authenticated)
    soulseek_client = _StubSoulseekClient()
    return SpotifyDomainService(
        config=config,
        spotify_client=spotify_client,
        soulseek_client=soulseek_client,
        app_state=SimpleNamespace(),
    )


def test_get_status_reports_free_available_when_health_check_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _make_service(authenticated=True)

    clients: list[_HealthySoulseek] = []

    def _build_health_client() -> _HealthySoulseek:
        client = _HealthySoulseek()
        clients.append(client)
        return client

    monkeypatch.setattr(service, "_build_soulseek_health_client", _build_health_client)

    status = service.get_status()

    assert status.free_available is True
    assert status.authenticated is True
    assert status.pro_available is True
    assert status.status == "connected"
    assert len(clients) == 1
    assert clients[0].closed is True


def test_get_status_free_unavailable_without_api_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    service = _make_service(authenticated=False)
    service._config.soulseek.api_key = ""
    health_probe = Mock()
    monkeypatch.setattr(service, "_perform_free_healthcheck", health_probe)

    caplog.set_level("WARNING")
    status = service.get_status()

    assert status.free_available is False
    assert status.pro_available is True
    assert status.authenticated is False
    assert status.status == "unauthenticated"
    assert not health_probe.called
    assert any(record.reason == "missing_api_key" for record in caplog.records)


def test_get_status_logs_error_when_health_check_fails(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    service = _make_service(authenticated=True)

    def _build_health_client() -> _FailingSoulseek:
        return _FailingSoulseek(RuntimeError("probe failed"))

    monkeypatch.setattr(service, "_build_soulseek_health_client", _build_health_client)

    caplog.set_level("ERROR")
    status = service.get_status()

    assert status.free_available is False
    assert any(record.reason == "healthcheck_failed" for record in caplog.records)


@pytest.mark.asyncio
async def test_get_status_health_check_runs_with_active_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _make_service(authenticated=True)

    clients: list[_HealthySoulseek] = []

    def _build_health_client() -> _HealthySoulseek:
        client = _HealthySoulseek()
        clients.append(client)
        return client

    monkeypatch.setattr(service, "_build_soulseek_health_client", _build_health_client)

    status = service.get_status()

    assert status.free_available is True
    assert len(clients) == 1
    assert clients[0].closed is True


@pytest.mark.asyncio
async def test_get_status_health_check_failure_with_active_loop(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    service = _make_service(authenticated=True)

    clients: list[_FailingSoulseek] = []

    def _build_health_client() -> _FailingSoulseek:
        client = _FailingSoulseek(RuntimeError("probe failed"))
        clients.append(client)
        return client

    monkeypatch.setattr(service, "_build_soulseek_health_client", _build_health_client)

    caplog.set_level("ERROR")
    status = service.get_status()

    assert status.free_available is False
    assert len(clients) == 1
    assert clients[0].closed is True
    assert any(record.reason == "healthcheck_failed" for record in caplog.records)


def test_get_status_reuses_cached_free_health_result(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _make_service(authenticated=True)

    call_count = 0

    class _CountingSoulseek(_HealthySoulseek):
        async def get_download_status(self) -> dict[str, str]:
            nonlocal call_count
            call_count += 1
            return await super().get_download_status()

    def _build_health_client() -> _CountingSoulseek:
        return _CountingSoulseek()

    monkeypatch.setattr(service, "_build_soulseek_health_client", _build_health_client)

    timeline = iter([0.0, 30.0, 61.0, 120.0])
    last_value = 120.0

    def _fake_monotonic() -> float:
        nonlocal last_value
        try:
            last_value = next(timeline)
        except StopIteration:
            pass
        return last_value

    monkeypatch.setattr("app.services.spotify_domain_service.monotonic", _fake_monotonic)

    first = service.get_status()
    second = service.get_status()
    third = service.get_status()

    assert call_count == 2
    assert first.free_available is True
    assert second.free_available is True
    assert third.free_available is True
