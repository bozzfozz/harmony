"""Tests for shared UI utilities."""

from __future__ import annotations

from typing import Mapping
from unittest.mock import Mock

import pytest

from app.ui.routes.shared import _extract_download_refresh_params


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
