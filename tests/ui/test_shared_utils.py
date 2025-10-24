"""Tests for shared UI utilities."""

from __future__ import annotations

from typing import Mapping
from unittest.mock import Mock

import pytest

from app.ui.routes.shared import _extract_download_refresh_params, _parse_form_body


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
