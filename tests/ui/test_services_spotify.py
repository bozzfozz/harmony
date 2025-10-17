"""Unit tests for :mod:`app.ui.services.spotify`."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Mapping
from unittest.mock import Mock

from starlette.requests import Request

from app.ui.services.spotify import SpotifyUiService


class _StubOAuthService:
    def __init__(self, payload: Mapping[str, object]) -> None:
        self._payload = payload

    def health(self) -> Mapping[str, object]:
        return self._payload


def _make_request() -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "path": "/ui/spotify",
        "headers": [],
    }
    return Request(scope)


def test_oauth_health_hides_redirect_when_manual_disabled() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    oauth = _StubOAuthService(
        {
            "manual_enabled": False,
            "redirect_uri": "https://example/callback",
            "public_host_hint": "https://public.example",
            "active_transactions": 2,
            "ttl_seconds": 120,
        }
    )
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=Mock(),
        oauth_service=oauth,
        db_session=Mock(),
    )

    health = service.oauth_health()

    assert health.manual_enabled is False
    assert health.redirect_uri is None
    assert health.public_host_hint == "https://public.example"
    assert health.active_transactions == 2
    assert health.ttl_seconds == 120


def test_oauth_health_keeps_redirect_when_manual_enabled() -> None:
    request = _make_request()
    config = SimpleNamespace(spotify=SimpleNamespace(backfill_max_items=None))
    oauth = _StubOAuthService(
        {
            "manual_enabled": True,
            "redirect_uri": "https://example/callback",
            "public_host_hint": None,
            "active_transactions": None,
            "ttl_seconds": None,
        }
    )
    service = SpotifyUiService(
        request=request,
        config=config,
        spotify_service=Mock(),
        oauth_service=oauth,
        db_session=Mock(),
    )

    health = service.oauth_health()

    assert health.manual_enabled is True
    assert health.redirect_uri == "https://example/callback"
    assert health.public_host_hint is None
    assert health.active_transactions == 0
    assert health.ttl_seconds == 0
