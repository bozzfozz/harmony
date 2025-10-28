"""Tests for download utility helpers."""

from __future__ import annotations

import pytest

from app.errors import ValidationAppError
from app.utils.downloads import resolve_status_filter


@pytest.mark.parametrize(
    "value",
    [None, 0, 1.5, [], {}, object()],
)
def test_resolve_status_filter_rejects_non_string(value: object) -> None:
    with pytest.raises(ValidationAppError):
        resolve_status_filter(value)


def test_resolve_status_filter_accepts_valid_string() -> None:
    assert resolve_status_filter(" Running \t") == {"running", "downloading"}
