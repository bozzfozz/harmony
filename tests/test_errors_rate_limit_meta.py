"""Tests for rate limit metadata extraction helpers."""

from __future__ import annotations

import pytest

from app.errors import rate_limit_meta


@pytest.mark.parametrize(
    "header_name",
    ["Retry-After", "retry-after", "RETRY-AFTER"],
)
def test_rate_limit_meta_accepts_case_insensitive_headers(header_name: str) -> None:
    meta, headers = rate_limit_meta({header_name: "5"})

    assert meta == {"retry_after_ms": 5000}
    assert headers == {"Retry-After": "5"}


def test_rate_limit_meta_returns_empty_when_header_missing() -> None:
    meta, headers = rate_limit_meta({})

    assert meta is None
    assert headers == {}
