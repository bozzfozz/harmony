from __future__ import annotations

import pytest

from app.config import _normalise_public_base


@pytest.mark.parametrize(
    ("raw", "api_base", "expected"),
    [
        (None, "/api/v1", "/api/v1/oauth"),
        ("", "/api/v1", "/api/v1/oauth"),
        ("/custom/oauth", "/api/v1", "/custom/oauth"),
        ("oauth", "/api/v1", "/oauth"),
        ("/", "/api/v1", "/"),
        (
            "https://harmony.example.com/api/v1/oauth",
            "/api/v1",
            "https://harmony.example.com/api/v1/oauth",
        ),
        (
            "https://harmony.example.com/api/v1/oauth/",
            "/api/v1",
            "https://harmony.example.com/api/v1/oauth",
        ),
        ("https://harmony.example.com", "/api/v1", "https://harmony.example.com"),
        ("https://harmony.example.com/", "", "https://harmony.example.com"),
        ("https://harmony.example.com/path?foo=bar", "", "https://harmony.example.com/path"),
        ("https:///broken/path", "", "/broken/path"),
        ("   https://harmony.example.com/base   ", "", "https://harmony.example.com/base"),
        (None, "", "/oauth"),
    ],
)
def test_normalise_public_base(raw: str | None, api_base: str, expected: str) -> None:
    assert _normalise_public_base(raw, api_base_path=api_base) == expected
