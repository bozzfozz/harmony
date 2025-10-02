"""Regression tests for Spotify FREE playlist link parsing."""

from __future__ import annotations

import pytest

from app.utils.spotify_free import _normalise_playlist_link


@pytest.mark.parametrize(
    "link",
    [
        "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
        "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M",
    ],
)
def test_normalise_playlist_link_accepts_direct_playlist_links(link: str) -> None:
    playlist_id, reason = _normalise_playlist_link(link, allow_user_urls=False)

    assert playlist_id == "37i9dQZF1DXcBWIGoYBM5M"
    assert reason is None


def test_normalise_playlist_link_accepts_user_playlist_url_when_allowed() -> None:
    playlist_id, reason = _normalise_playlist_link(
        "https://open.spotify.com/user/spotify/playlist/37i9dQZF1DXcBWIGoYBM5M",
        allow_user_urls=True,
    )

    assert playlist_id == "37i9dQZF1DXcBWIGoYBM5M"
    assert reason is None


def test_normalise_playlist_link_accepts_user_playlist_uri_when_allowed() -> None:
    playlist_id, reason = _normalise_playlist_link(
        "spotify:user:spotify:playlist:37i9dQZF1DXcBWIGoYBM5M",
        allow_user_urls=True,
    )

    assert playlist_id == "37i9dQZF1DXcBWIGoYBM5M"
    assert reason is None


@pytest.mark.parametrize(
    "link",
    [
        "https://open.spotify.com/user/spotify/playlist/37i9dQZF1DXcBWIGoYBM5M",
        "spotify:user:spotify:playlist:37i9dQZF1DXcBWIGoYBM5M",
    ],
)
def test_normalise_playlist_link_rejects_user_links_when_disallowed(link: str) -> None:
    playlist_id, reason = _normalise_playlist_link(link, allow_user_urls=False)

    assert playlist_id is None
    assert reason == "NOT_A_PLAYLIST_URL"
