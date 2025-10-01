"""Utility functions for normalising provider payloads into DTOs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.integrations.base import TrackCandidate
from app.integrations.contracts import ProviderAlbum, ProviderArtist, ProviderTrack


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned.lstrip("-+").isdigit():
            try:
                return int(cleaned)
            except ValueError:
                return None
    return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _extract_mapping(obj: Any) -> Mapping[str, Any] | None:
    if isinstance(obj, Mapping):
        return obj
    return None


def _iter_sequence(obj: Any) -> Iterable[Any]:
    if isinstance(obj, (list, tuple)):
        return obj
    if obj is None:
        return ()
    return (obj,)


def normalize_spotify_track(
    payload: Mapping[str, Any] | Any, *, provider: str = "spotify"
) -> ProviderTrack:
    """Convert a Spotify track payload into :class:`ProviderTrack`."""

    def _get(value: Any, key: str, default: Any = None) -> Any:
        mapping = _extract_mapping(value)
        if mapping is not None:
            return mapping.get(key, default)
        return getattr(value, key, default)

    name = _coerce_str(_get(payload, "name")) or ""
    duration_ms = _coerce_int(_get(payload, "duration_ms"))
    isrc = _coerce_str(_get(payload, "isrc"))
    metadata: dict[str, Any] = {}

    track_id = _coerce_str(_get(payload, "id"))
    if track_id:
        metadata["id"] = track_id
    if duration_ms is not None:
        metadata["duration_ms"] = duration_ms

    external_ids = _get(payload, "external_ids")
    external_mapping = _extract_mapping(external_ids)
    if external_mapping:
        isrc_value = _coerce_str(external_mapping.get("isrc"))
        if isrc_value:
            isrc = isrc_value
            metadata.setdefault("isrc", isrc_value)

    artist_entries: list[ProviderArtist] = []
    aggregated_genres: set[str] = set()
    artists = _get(payload, "artists", ())
    for entry in _iter_sequence(artists):
        artist_name = _coerce_str(_get(entry, "name")) or ""
        artist_id = _coerce_str(_get(entry, "id"))
        artist_metadata: dict[str, Any] = {}
        genres = _get(entry, "genres")
        if genres:
            genre_list = [str(item) for item in _iter_sequence(genres) if _coerce_str(item)]
            if genre_list:
                artist_metadata["genres"] = tuple(genre_list)
                aggregated_genres.update(genre_list)
        popularity = _get(entry, "popularity")
        if popularity is not None:
            popularity_value = _coerce_int(popularity)
            if popularity_value is not None:
                artist_metadata["popularity"] = popularity_value
        artist_entries.append(
            ProviderArtist(name=artist_name, id=artist_id, metadata=artist_metadata)
        )

    album_payload = _get(payload, "album")
    album: ProviderAlbum | None = None
    if album_payload:
        album_name = _coerce_str(_get(album_payload, "name")) or ""
        album_id = _coerce_str(_get(album_payload, "id"))
        album_metadata: dict[str, Any] = {}
        release_year = _coerce_int(_get(album_payload, "release_year"))
        if release_year is not None:
            album_metadata["release_year"] = release_year
        total_tracks = _coerce_int(_get(album_payload, "total_tracks"))
        if total_tracks is not None:
            album_metadata["total_tracks"] = total_tracks
        release_date = _coerce_str(_get(album_payload, "release_date"))
        if release_date:
            album_metadata["release_date"] = release_date
        album_artists_payload = _get(album_payload, "artists", ())
        album_artists: list[ProviderArtist] = []
        for entry in _iter_sequence(album_artists_payload):
            album_artist_name = _coerce_str(_get(entry, "name")) or ""
            album_artist_id = _coerce_str(_get(entry, "id"))
            album_artist_metadata: dict[str, Any] = {}
            genres = _get(entry, "genres")
            if genres:
                genre_list = [str(item) for item in _iter_sequence(genres) if _coerce_str(item)]
                if genre_list:
                    album_artist_metadata["genres"] = tuple(genre_list)
            album_artists.append(
                ProviderArtist(
                    name=album_artist_name,
                    id=album_artist_id,
                    metadata=album_artist_metadata,
                )
            )
        album = ProviderAlbum(
            name=album_name,
            id=album_id,
            artists=tuple(album_artists),
            metadata=album_metadata,
        )

    genres = _get(payload, "genres")
    if genres:
        metadata["genres"] = tuple(
            str(item) for item in _iter_sequence(genres) if _coerce_str(item)
        )
    if aggregated_genres and "genres" not in metadata:
        metadata["genres"] = tuple(sorted(aggregated_genres))

    return ProviderTrack(
        name=name,
        provider=provider,
        artists=tuple(artist_entries),
        album=album,
        duration_ms=duration_ms,
        isrc=isrc,
        candidates=tuple(),
        metadata=metadata,
    )


def normalize_slskd_candidate(
    payload: Mapping[str, Any] | TrackCandidate,
    *,
    source: str = "slskd",
) -> TrackCandidate:
    """Convert a Soulseek entry into :class:`TrackCandidate`."""

    if isinstance(payload, TrackCandidate):
        if payload.source == source:
            return payload
        return TrackCandidate(
            title=payload.title,
            artist=payload.artist,
            format=payload.format,
            bitrate_kbps=payload.bitrate_kbps,
            size_bytes=payload.size_bytes,
            seeders=payload.seeders,
            username=payload.username,
            availability=payload.availability,
            source=source,
            download_uri=payload.download_uri,
            metadata=payload.metadata,
        )

    title = (
        _coerce_str(payload.get("title"))
        or _coerce_str(payload.get("name"))
        or _coerce_str(payload.get("filename"))
        or "Unknown Track"
    )
    artist = _coerce_str(payload.get("artist")) or _coerce_str(payload.get("uploader"))
    format_name = _coerce_str(payload.get("format"))
    if format_name:
        format_name = format_name.upper()
    bitrate = _coerce_int(payload.get("bitrate") or payload.get("bitrate_kbps"))
    if bitrate is not None and bitrate <= 0:
        bitrate = None
    size = _coerce_int(payload.get("size") or payload.get("size_bytes") or payload.get("filesize"))
    if size is not None and size < 0:
        size = None
    seeders = _coerce_int(
        payload.get("seeders")
        or payload.get("user_count")
        or payload.get("users")
        or payload.get("availability")
        or payload.get("count")
    )
    username = _coerce_str(payload.get("username") or payload.get("user"))
    availability = _coerce_float(
        payload.get("availability")
        or payload.get("availability_score")
        or payload.get("estimated_availability")
    )
    download_uri = _coerce_str(
        payload.get("download_uri")
        or payload.get("magnet")
        or payload.get("magnet_uri")
        or payload.get("path")
        or payload.get("filename")
    )

    metadata: dict[str, Any] = {}
    identifier = payload.get("id") or payload.get("track_id")
    if identifier is not None:
        metadata["id"] = identifier
    score = _coerce_float(payload.get("score"))
    if score is not None:
        metadata["score"] = score
    bitrate_mode = _coerce_str(payload.get("bitrate_mode") or payload.get("encoding"))
    if bitrate_mode:
        metadata["bitrate_mode"] = bitrate_mode
    year = _coerce_int(payload.get("year"))
    if year is not None:
        metadata["year"] = year
    genres_field = payload.get("genres")
    if isinstance(genres_field, (list, tuple)):
        genres = [str(item) for item in genres_field if _coerce_str(item)]
        if genres:
            metadata["genres"] = genres
    genre = _coerce_str(payload.get("genre"))
    if genre:
        metadata["genre"] = genre
    album = _coerce_str(payload.get("album"))
    if album:
        metadata["album"] = album
    filename = _coerce_str(payload.get("filename"))
    if filename:
        metadata["filename"] = filename
    artists = payload.get("artists")
    if isinstance(artists, list):
        names: list[str] = []
        for entry in artists:
            if isinstance(entry, Mapping):
                name = _coerce_str(entry.get("name"))
            else:
                name = _coerce_str(entry)
            if name:
                names.append(name)
        if names:
            metadata["artists"] = names
    if artist:
        metadata.setdefault("artists", []).append(artist)

    return TrackCandidate(
        title=title,
        artist=artist,
        format=format_name,
        bitrate_kbps=bitrate,
        size_bytes=size,
        seeders=seeders,
        username=username,
        availability=availability,
        source=source,
        download_uri=download_uri,
        metadata=metadata,
    )


def normalize_slskd_track(
    payload: Mapping[str, Any] | TrackCandidate,
    *,
    provider: str = "slskd",
) -> ProviderTrack:
    """Convert a Soulseek entry into :class:`ProviderTrack`."""

    candidate = normalize_slskd_candidate(payload, source=provider)
    metadata = dict(candidate.metadata or {})

    artist_names: list[str] = []
    if candidate.artist:
        artist_names.append(candidate.artist)
    for item in _iter_sequence(metadata.get("artists")):
        name = _coerce_str(item)
        if name and name not in artist_names:
            artist_names.append(name)
    provider_artists = tuple(ProviderArtist(name=name) for name in artist_names if name)

    album_name = _coerce_str(metadata.get("album"))
    album = None
    if album_name:
        album = ProviderAlbum(name=album_name, id=None, artists=tuple())

    track_metadata: dict[str, Any] = {}
    for key in ("genre", "genres", "year", "id", "score", "bitrate_mode"):
        if key in metadata and metadata[key] is not None:
            track_metadata[key] = metadata[key]

    return ProviderTrack(
        name=candidate.title,
        provider=provider,
        artists=provider_artists,
        album=album,
        duration_ms=None,
        isrc=None,
        candidates=(candidate,),
        metadata=track_metadata,
    )


__all__ = [
    "normalize_slskd_candidate",
    "normalize_slskd_track",
    "normalize_spotify_track",
]
