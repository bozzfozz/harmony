"""Tests for Spotify URL parsing helpers."""

from __future__ import annotations

import pytest

from app.utils.spotify_url import parse_playlist_id


@pytest.mark.parametrize(
    "raw,allow_user,expected",
    [
        ("https://open.spotify.com:443/playlist/abc123", False, "abc123"),
        (
            "https://open.spotify.com:8443/playlist/abc123?si=foo",
            False,
            "abc123",
        ),
        ("https://example.com:443/playlist/abc123", False, None),
        (
            "https://open.spotify.com:8080/user/someone/playlist/def456",
            True,
            "def456",
        ),
    ],
)
def test_parse_playlist_id_accepts_urls_with_ports(
    raw: str, allow_user: bool, expected: str | None
) -> None:
    """Ensure playlist IDs are extracted when the host matches despite ports."""

    assert parse_playlist_id(raw, allow_user_urls=allow_user) == expected
