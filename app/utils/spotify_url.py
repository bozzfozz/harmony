"""Utilities for working with Spotify URLs and URIs."""

from __future__ import annotations

from typing import Final
from urllib.parse import urlparse

_PLAYLIST_URI_PREFIX: Final[str] = "spotify:playlist:"
_USER_URI_PREFIX: Final[str] = "spotify:user:"
_ALLOWED_HOST: Final[str] = "open.spotify.com"


def parse_playlist_id(
    url_or_uri: str | None,
    *,
    allow_user_urls: bool = False,
) -> str | None:
    """Extract a playlist identifier from a Spotify URL or URI.

    Args:
        url_or_uri: Raw input provided by the user. Supports Spotify playlist
            share URLs (``https://open.spotify.com/playlist/{id}``) and Spotify
            URIs (``spotify:playlist:{id}``). When ``allow_user_urls`` is set to
            ``True`` the legacy ``/user/{user_id}/playlist/{id}`` URL and
            ``spotify:user:{user_id}:playlist:{id}`` URI formats are also
            accepted. Query parameters and fragments are ignored. Returns
            ``None`` when the input does not represent a playlist link or when
            the identifier contains invalid characters.
    """

    if not url_or_uri:
        return None
    candidate = url_or_uri.strip()
    if not candidate:
        return None

    lowered = candidate.lower()

    if lowered.startswith(_PLAYLIST_URI_PREFIX):
        playlist_id = candidate[len(_PLAYLIST_URI_PREFIX) :]
        return playlist_id if playlist_id.isalnum() else None

    if allow_user_urls and lowered.startswith(_USER_URI_PREFIX):
        parts = candidate.split(":")
        if len(parts) < 5:
            return None
        if parts[3].lower() != "playlist":
            return None
        playlist_id = parts[4]
        return playlist_id if playlist_id.isalnum() else None

    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"}:
        return None
    host = parsed.hostname
    if host is None or host.lower() != _ALLOWED_HOST:
        return None

    segments = [segment for segment in parsed.path.split("/") if segment]
    if segments and segments[0].lower().startswith("intl-"):
        segments = segments[1:]
    if len(segments) >= 2 and segments[0].lower() == "playlist":
        playlist_id = segments[1].split("?")[0].split("#")[0]
        return playlist_id if playlist_id.isalnum() else None

    if allow_user_urls and len(segments) >= 4 and segments[0].lower() == "user":
        if segments[2].lower() != "playlist":
            return None
        playlist_id = segments[3].split("?")[0].split("#")[0]
        return playlist_id if playlist_id.isalnum() else None

    return None
