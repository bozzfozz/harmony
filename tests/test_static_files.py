"""Tests for the ImmutableStaticFiles path normalization helper."""

import pytest

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
