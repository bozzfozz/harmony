"""Tests for :mod:`app.core.soulseek_client` covering retries, rate limits and payload normalisation."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import SoulseekConfig
from app.core.soulseek_client import SoulseekClient, SoulseekClientError


def _make_client(config: SoulseekConfig | None = None) -> SoulseekClient:
    cfg = config or SoulseekConfig(
        base_url="https://slskd.local",
        api_key=None,
        timeout_ms=1000,
        retry_max=2,
        retry_backoff_base_ms=1,
        retry_jitter_pct=0,
        preferred_formats=(),
        max_results=5,
    )
    session = MagicMock()
    session.closed = False
    client = SoulseekClient(cfg, session=session)
    client._respect_rate_limit = AsyncMock()  # type: ignore[method-assign]
    return client


def _response(
    *, status: int, headers: dict[str, str] | None = None, body: str = ""
) -> SimpleNamespace:
    resp_headers = headers or {}
    response = SimpleNamespace(status=status, headers=resp_headers)

    async def _text() -> str:
        return body

    response.text = _text  # type: ignore[assignment]
    return response


def _context_manager(response: SimpleNamespace) -> AsyncMock:
    context = AsyncMock()
    context.__aenter__.return_value = response
    context.__aexit__.return_value = False
    return context


@pytest.mark.asyncio
async def test_search_payload_uses_config_defaults() -> None:
    config = SoulseekConfig(
        base_url="https://slskd.local",
        api_key=None,
        timeout_ms=1000,
        retry_max=2,
        retry_backoff_base_ms=1,
        retry_jitter_pct=0,
        preferred_formats=("flac", "alac"),
        max_results=7,
    )
    client = _make_client(config)
    request_mock = AsyncMock(return_value={})
    client._request = request_mock  # type: ignore[method-assign]

    await client.search("query")

    request_mock.assert_awaited_once()
    payload = request_mock.await_args.kwargs["json"]
    assert payload["preferredFormats"] == ["flac", "alac"]
    assert payload["maxResults"] == 7


@pytest.mark.asyncio
async def test_search_payload_respects_overrides() -> None:
    config = SoulseekConfig(
        base_url="https://slskd.local",
        api_key=None,
        timeout_ms=1000,
        retry_max=2,
        retry_backoff_base_ms=1,
        retry_jitter_pct=0,
        preferred_formats=("flac",),
        max_results=8,
    )
    client = _make_client(config)
    request_mock = AsyncMock(return_value={})
    client._request = request_mock  # type: ignore[method-assign]

    await client.search(
        "query",
        format_priority=("mp3", "aac"),
        max_results=3,
    )

    request_mock.assert_awaited_once()
    payload = request_mock.await_args.kwargs["json"]
    assert payload["preferredFormats"] == ["mp3", "aac"]
    assert payload["maxResults"] == 3


@pytest.mark.asyncio
async def test_should_retry_matrix() -> None:
    client = _make_client()
    cases = [
        (SoulseekClientError("network"), True),
        (SoulseekClientError("server", status_code=500), True),
        (SoulseekClientError("timeout", status_code=408), True),
        (SoulseekClientError("rate", status_code=429), True),
        (SoulseekClientError("missing", status_code=404), False),
        (SoulseekClientError("ok", status_code=200), False),
    ]

    for error, expected in cases:
        assert client._should_retry(error) is expected


@pytest.mark.asyncio
async def test_request_returns_json_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client()
    session = client._session
    assert session is not None
    response = _response(
        status=200, headers={"Content-Type": "application/json"}, body='{"ok": true}'
    )
    session.request = MagicMock(return_value=_context_manager(response))
    monkeypatch.setattr("app.utils.retry.asyncio.sleep", AsyncMock())

    result = await client._request("GET", "status")

    assert result == {"ok": True}
    assert session.request.call_count == 1


@pytest.mark.asyncio
async def test_request_raises_client_error_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client()
    session = client._session
    assert session is not None
    response = _response(
        status=404,
        headers={"Content-Type": "application/json"},
        body='{"detail": "missing"}',
    )
    session.request = MagicMock(return_value=_context_manager(response))
    monkeypatch.setattr("app.utils.retry.asyncio.sleep", AsyncMock())

    with pytest.raises(SoulseekClientError) as excinfo:
        await client._request("GET", "missing")

    error = excinfo.value
    assert error.status_code == 404
    assert error.payload == {"detail": "missing"}
    assert session.request.call_count == 1


@pytest.mark.asyncio
async def test_request_retries_on_server_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client()
    session = client._session
    assert session is not None
    first = _context_manager(
        _response(
            status=503, headers={"Content-Type": "application/json"}, body='{"error": "upstream"}'
        )
    )
    second = _context_manager(
        _response(
            status=500, headers={"Content-Type": "application/json"}, body='{"error": "still"}'
        )
    )
    final = _context_manager(
        _response(status=200, headers={"Content-Type": "application/json"}, body='{"done": true}')
    )
    session.request = MagicMock(side_effect=[first, second, final])
    monkeypatch.setattr("app.utils.retry.asyncio.sleep", AsyncMock())

    result = await client._request("GET", "unstable")

    assert result == {"done": True}
    assert session.request.call_count == 3


@pytest.mark.asyncio
async def test_request_timeout_converts_to_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    config = SoulseekConfig(
        base_url="https://slskd.local",
        api_key=None,
        timeout_ms=250,
        retry_max=1,
        retry_backoff_base_ms=1,
        retry_jitter_pct=0,
        preferred_formats=(),
        max_results=5,
    )
    client = _make_client(config)
    session = client._session
    assert session is not None
    session.request = MagicMock(side_effect=asyncio.TimeoutError)
    sleep_mock = AsyncMock()
    monkeypatch.setattr("app.utils.retry.asyncio.sleep", sleep_mock)

    with pytest.raises(SoulseekClientError) as excinfo:
        await client._request("GET", "slow")

    error = excinfo.value
    assert error.status_code == 408
    assert "timed out" in str(error)
    assert session.request.call_count == 2
    assert sleep_mock.await_count == 1


@pytest.mark.asyncio
async def test_request_returns_plain_text_response(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client()
    session = client._session
    assert session is not None
    response = _response(status=200, headers={"Content-Type": "text/plain"}, body="ok")
    session.request = MagicMock(return_value=_context_manager(response))
    monkeypatch.setattr("app.utils.retry.asyncio.sleep", AsyncMock())

    result = await client._request("GET", "text")

    assert result == "ok"
    assert session.request.call_count == 1


@pytest.mark.asyncio
async def test_respect_rate_limit_enforces_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client()
    client._respect_rate_limit = SoulseekClient._respect_rate_limit.__get__(client, SoulseekClient)  # type: ignore[method-assign]
    client.RATE_LIMIT_COUNT = 3
    client.RATE_LIMIT_WINDOW = 10.0
    client._timestamps = deque(maxlen=client.RATE_LIMIT_COUNT)

    sleep_mock = AsyncMock()
    monkeypatch.setattr("app.core.soulseek_client.asyncio.sleep", sleep_mock)

    times: Iterator[float] = iter([0.0, 0.0, 1.0, 1.0, 2.0, 2.0, 3.0, 10.0])

    def fake_monotonic() -> float:
        return next(times)

    monkeypatch.setattr("app.core.soulseek_client.time", SimpleNamespace(monotonic=fake_monotonic))

    await client._respect_rate_limit()
    await client._respect_rate_limit()
    await client._respect_rate_limit()
    await client._respect_rate_limit()

    sleep_mock.assert_awaited_once()
    sleep_args = sleep_mock.await_args[0][0]
    assert pytest.approx(sleep_args, rel=1e-6) == 7.0
    assert list(client._timestamps) == [1.0, 2.0, 10.0]


def test_normalise_search_results_mixed_payloads() -> None:
    client = _make_client()
    payload = {
        "results": [
            {
                "username": " user1 ",
                "files": [
                    {
                        "id": "1",
                        "filename": "Track.FLAC",
                        "artist": ["Artist A"],
                        "bitrate": None,
                        "format": None,
                        "size": "2048",
                    },
                    {
                        "token": "2",
                        "path": "folder/Track320.mp3",
                        "artists": "Artist B",
                        "bitrate": "320",
                        "extension": "mp3",
                        "size": 1024,
                    },
                ],
            },
            {
                "username": "user2",
                "files": {
                    "entry": {
                        "path": "Song.wav",
                        "bitrate": None,
                        "format": None,
                        "size": 512,
                    }
                },
            },
        ]
    }

    results = client.normalise_search_results(payload)

    assert len(results) == 3
    first, second, third = results
    assert first["bitrate"] == 1000
    assert first["format"] == "flac"
    assert first["artists"] == ["Artist A"]
    assert first["extra"]["username"] == "user1"
    assert second["bitrate"] == 320
    assert second["format"] == "mp3"
    assert second["artists"] == ["Artist B"]
    assert third["format"] == "wav"
    assert third["bitrate"] == 1000


def test_normalise_search_results_applies_limits() -> None:
    config = SoulseekConfig(
        base_url="https://slskd.local",
        api_key=None,
        timeout_ms=1000,
        retry_max=2,
        retry_backoff_base_ms=1,
        retry_jitter_pct=0,
        preferred_formats=(),
        max_results=2,
    )
    client = _make_client(config)
    payload = {
        "results": [
            {
                "username": "user",
                "files": [
                    {
                        "id": str(index),
                        "filename": f"Track{index}.mp3",
                        "bitrate": 320,
                        "format": "mp3",
                    }
                    for index in range(5)
                ],
            }
        ]
    }

    default_limited = client.normalise_search_results(payload)
    assert len(default_limited) == 2

    override_limited = client.normalise_search_results(payload, limit=3)
    assert len(override_limited) == 3


def test_normalise_search_results_zero_limit_returns_empty() -> None:
    client = _make_client()
    payload = {
        "results": [
            {
                "username": "user",
                "files": [{"id": "1", "filename": "Track1.mp3", "bitrate": 320, "format": "mp3"}],
            }
        ]
    }

    assert client.normalise_search_results(payload, limit=0) == []


def test_normalise_file_infers_metadata() -> None:
    client = _make_client()
    file_info: dict[str, Any] = {
        "token": 42,
        "filename": "Album - Track ALAC",
        "album": "Album",
        "artists": ["Artist"],
        "bitrate": None,
        "duration": "300000",
        "year": "2020",
        "genre": ["Rock"],
        "size": "4096",
        "availability": "free",
    }

    normalised = client._normalise_file("listener", file_info)

    assert normalised["id"] == "42"
    assert normalised["bitrate"] == 1000
    assert normalised["format"] == "alac"
    assert normalised["duration_ms"] == 300000
    assert normalised["year"] == 2020
    assert normalised["genres"] == ["Rock"]
    assert normalised["extra"] == {
        "username": "listener",
        "path": "Album - Track ALAC",
        "size": 4096,
        "availability": "free",
    }
