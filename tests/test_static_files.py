"""Tests for the ImmutableStaticFiles path normalization helper."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

from app.main import ImmutableStaticFiles


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("css/app.css", "css/app.css"),
    ],
)
def test_normalize_path_allows_safe_relative_paths(path: str, expected: str) -> None:
    """Safe relative paths should be preserved after normalization."""

    assert ImmutableStaticFiles._normalize_path(path) == expected


@pytest.mark.parametrize(
    "path",
    [
        "../secret",
        r"C:\\tmp",
        "",
    ],
)
def test_normalize_path_rejects_unsafe_paths(path: str) -> None:
    """Unsafe or malformed paths should be rejected."""

    assert ImmutableStaticFiles._normalize_path(path) is None


@pytest.mark.asyncio
async def test_get_response_adds_cache_control_header(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Successful responses should receive the immutable cache header."""

    static_files = ImmutableStaticFiles(directory=tmp_path)
    cached_response = Response(status_code=200)
    observed: dict[str, Any] = {}

    async def fake_get_response(
        self: StaticFiles, path: str, scope: dict[str, Any]
    ) -> Response:
        observed["path"] = path
        observed["scope"] = scope
        return cached_response

    monkeypatch.setattr(StaticFiles, "get_response", fake_get_response)

    scope = {"type": "http"}
    response = await static_files.get_response("css/app.css", scope)

    assert response is cached_response
    assert response.headers["Cache-Control"] == ImmutableStaticFiles.cache_control_header
    assert observed["path"] == "css/app.css"
    assert observed["scope"] is scope


@pytest.mark.asyncio
async def test_get_response_does_not_add_cache_header_on_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Error responses should not be decorated with cache headers."""

    static_files = ImmutableStaticFiles(directory=tmp_path)
    error_response = Response(status_code=404)

    async def fake_get_response(
        self: StaticFiles, path: str, scope: dict[str, Any]
    ) -> Response:
        return error_response

    monkeypatch.setattr(StaticFiles, "get_response", fake_get_response)

    response = await static_files.get_response("missing.css", {"type": "http"})

    assert response is error_response
    assert "Cache-Control" not in response.headers
