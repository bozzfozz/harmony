"""Tests for shared UI utilities."""

from __future__ import annotations

from typing import Mapping
from unittest.mock import Mock

import pytest

from fastapi import Request, status

from app.ui.routes.shared import (
    _extract_download_refresh_params,
    _parse_form_body,
    _render_alert_fragment,
)


def _make_request() -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "headers": [],
        "client": ("testclient", 1234),
        "server": ("testserver", 80),
    }
    return Request(scope)


@pytest.mark.parametrize(
    "values, query_params, expected",
    [
        (
            {"limit": "250", "offset": "-10", "scope": "active"},
            {},
            (100, 0, False),
        ),
        (
            {},
            {"limit": "5", "offset": "10", "scope": "all"},
            (5, 10, True),
        ),
        (
            {"limit": "abc", "offset": ""},
            {"limit": "NaN", "offset": "12.5", "all": "true"},
            (20, 0, True),
        ),
    ],
)
def test_extract_download_refresh_params(values: Mapping[str, str], query_params: Mapping[str, str], expected: tuple[int, int, bool]) -> None:
    request = Mock()
    request.query_params = query_params

    result = _extract_download_refresh_params(request, values)

    assert result == expected


def test_parse_form_body_decodes_utf8_and_percent_encoded() -> None:
    raw = "name=J%C3%B6rg&message=Ol%C3%A1+Mundo&note=%20Hello%20World%20".encode("utf-8")

    result = _parse_form_body(raw)

    assert result == {
        "name": "Jörg",
        "message": "Olá Mundo",
        "note": "Hello World",
    }


def test_parse_form_body_prefers_first_value_and_trims_whitespace() -> None:
    raw = b"choice=%20first%20&choice=second&empty=%20%20&flag=%09%0A"

    result = _parse_form_body(raw)

    assert set(result) == {"choice", "empty", "flag"}
    assert result["choice"] == "first"
    assert result["empty"] == ""
    assert result["flag"] == ""


def test_parse_form_body_invalid_bytes_returns_empty_dict() -> None:
    raw = b"\xff\xfe\xfd"

    result = _parse_form_body(raw)

    assert result == {}


@pytest.mark.asyncio
async def test_render_alert_fragment_includes_retry_metadata() -> None:
    request = _make_request()

    response = _render_alert_fragment(
        request,
        "Please retry",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        retry_url="/fragments/retry",
        retry_target="#fragment",
        retry_label_key="downloads.retry",
    )

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.template.name.endswith("partials/async_error.j2")

    body = response.body.decode("utf-8")

    assert "Please retry" in body
    assert 'hx-get="/fragments/retry"' in body
    assert 'hx-target="#fragment"' in body
    assert "Retry download" in body


@pytest.mark.asyncio
async def test_render_alert_fragment_defaults_to_async_error_template() -> None:
    request = _make_request()

    response = _render_alert_fragment(request, "")

    assert response.template.name.endswith("partials/async_error.j2")
    assert response.context["alerts"][0].text == "An unexpected error occurred."
    assert response.context["retry_url"] is None
    assert response.context["retry_target"] is None
    assert response.context["retry_label_key"] == "fragments.retry"

    body = response.body.decode("utf-8")
    assert "An unexpected error occurred." in body
