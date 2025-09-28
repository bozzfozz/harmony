"""Spotify implementation of the :class:`MusicProvider` interface."""

from __future__ import annotations

from typing import Iterable, List

from app.core.spotify_client import SpotifyClient
from app.integrations.base import Album, Artist, MusicProvider, Playlist, ProviderError, Track


def _extract_artists(payload: List[dict]) -> tuple[Artist, ...]:
    artists: list[Artist] = []
    for entry in payload or []:
        if not isinstance(entry, dict):
            continue
        artist_id = str(entry.get("id") or "")
        if not artist_id:
            continue
        artists.append(
            Artist(
                id=artist_id,
                name=str(entry.get("name") or ""),
                genres=tuple(entry.get("genres") or ()),
                popularity=entry.get("popularity"),
            )
        )
    return tuple(artists)


def _normalise_track(payload: dict) -> Track:
    album_payload = payload.get("album") if isinstance(payload, dict) else None
    album: Album | None = None
    if isinstance(album_payload, dict):
        album_artists_payload = album_payload.get("artists")
        album_artists: tuple[Artist, ...] = ()
        if isinstance(album_artists_payload, list):
            album_artists = _extract_artists(album_artists_payload)
        album = Album(
            id=str(album_payload.get("id") or ""),
            name=str(album_payload.get("name") or ""),
            artists=album_artists,
            release_year=None,
            total_tracks=album_payload.get("total_tracks"),
        )
    artists_payload = payload.get("artists") if isinstance(payload, dict) else None
    artists: tuple[Artist, ...] = ()
    if isinstance(artists_payload, list):
        artists = _extract_artists(artists_payload)
    external_ids = payload.get("external_ids") if isinstance(payload, dict) else {}
    isrc = None
    if isinstance(external_ids, dict):
        raw_isrc = external_ids.get("isrc")
        if raw_isrc:
            isrc = str(raw_isrc)
    return Track(
        id=str(payload.get("id") or ""),
        name=str(payload.get("name") or ""),
        artists=artists,
        album=album,
        duration_ms=payload.get("duration_ms"),
        isrc=isrc,
    )


class SpotifyAdapter(MusicProvider):
    """Adapter using :class:`SpotifyClient` for integration flows."""

    name = "spotify"

    def __init__(self, *, client: SpotifyClient, timeout_ms: int) -> None:
        self._client = client
        self._timeout_ms = timeout_ms

    def search_tracks(self, query: str, limit: int = 20) -> Iterable[Track]:
        try:
            payload = self._client.search_tracks(query, limit=limit)
        except Exception as exc:  # pragma: no cover - network errors mocked in tests
            raise ProviderError(self.name, str(exc)) from exc
        items = []
        if isinstance(payload, dict):
            tracks_payload = payload.get("tracks")
            if isinstance(tracks_payload, dict):
                items = tracks_payload.get("items") or []
        for raw in items or []:
            if isinstance(raw, dict):
                yield _normalise_track(raw)

    def get_artist(self, artist_id: str) -> Artist:
        try:
            payload = self._client._execute(self._client._client.artist, artist_id)  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - network errors mocked in tests
            raise ProviderError(self.name, str(exc)) from exc
        return Artist(
            id=str(payload.get("id") or artist_id),
            name=str(payload.get("name") or ""),
            genres=tuple(payload.get("genres") or ()),
            popularity=payload.get("popularity"),
        )

    def get_album(self, album_id: str) -> Album:
        try:
            payload = self._client.get_album_details(album_id)
        except Exception as exc:  # pragma: no cover - network errors mocked in tests
            raise ProviderError(self.name, str(exc)) from exc
        artists_payload = payload.get("artists") if isinstance(payload, dict) else []
        artists = _extract_artists(artists_payload if isinstance(artists_payload, list) else [])
        release_date = payload.get("release_date") if isinstance(payload, dict) else None
        year = None
        if isinstance(release_date, str) and release_date[:4].isdigit():
            year = int(release_date[:4])
        return Album(
            id=str(payload.get("id") or album_id),
            name=str(payload.get("name") or ""),
            artists=artists,
            release_year=year,
            total_tracks=payload.get("total_tracks"),
        )

    def get_artist_top_tracks(self, artist_id: str, limit: int = 10) -> Iterable[Track]:
        try:
            payload = self._client._execute(  # type: ignore[attr-defined]
                self._client._client.artist_top_tracks, artist_id
            )
        except Exception as exc:  # pragma: no cover - network errors mocked in tests
            raise ProviderError(self.name, str(exc)) from exc
        tracks = payload.get("tracks") if isinstance(payload, dict) else []
        for raw in (tracks or [])[:limit]:
            if isinstance(raw, dict):
                yield _normalise_track(raw)

    def get_playlist(self, playlist_id: str) -> Playlist:
        try:
            payload = self._client._execute(self._client._client.playlist, playlist_id)  # type: ignore[attr-defined]
        except Exception as exc:  # pragma: no cover - network errors mocked in tests
            raise ProviderError(self.name, str(exc)) from exc
        tracks_payload = payload.get("tracks") if isinstance(payload, dict) else {}
        track_items = tracks_payload.get("items") if isinstance(tracks_payload, dict) else []
        tracks: list[Track] = []
        for entry in track_items or []:
            if not isinstance(entry, dict):
                continue
            track_payload = entry.get("track") if isinstance(entry.get("track"), dict) else entry
            if isinstance(track_payload, dict):
                tracks.append(_normalise_track(track_payload))
        owner_payload = payload.get("owner") if isinstance(payload, dict) else None
        owner = None
        if isinstance(owner_payload, dict):
            owner = str(owner_payload.get("display_name") or owner_payload.get("id") or "")
        return Playlist(
            id=str(payload.get("id") or playlist_id),
            name=str(payload.get("name") or ""),
            owner=owner,
            description=payload.get("description") if isinstance(payload, dict) else None,
            tracks=tuple(tracks),
        )
