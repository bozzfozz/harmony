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
    async def get_download_status(self) -> dict[str, str]:
        return {"status": "ok"}

    async def close(self) -> None:
        return None


class _FailingSoulseek:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def get_download_status(self) -> dict[str, str]:
        raise self._error

    async def close(self) -> None:
        return None


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

    def _build_health_client() -> _HealthySoulseek:
        return _HealthySoulseek()

    monkeypatch.setattr(service, "_build_soulseek_health_client", _build_health_client)

    status = service.get_status()

    assert status.free_available is True
    assert status.authenticated is True
    assert status.pro_available is True
    assert status.status == "connected"


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
