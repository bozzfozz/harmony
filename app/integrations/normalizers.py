"""Utility functions for normalising provider payloads into DTOs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from app.integrations.base import TrackCandidate
from app.integrations.contracts import (
    ProviderAlbum,
    ProviderAlbumDetails,
    ProviderArtist,
    ProviderRelease,
    ProviderTrack,
)

_TRACK_COUNT_KEYS = (
    "total_tracks",
    "track_count",
    "tracks_count",
    "total_track_count",
    "num_tracks",
    "number_of_tracks",
    "album_total_tracks",
)


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


def _get_field(obj: Any, key: str, default: Any = None) -> Any:
    mapping = _extract_mapping(obj)
    if mapping is not None:
        return mapping.get(key, default)
    return getattr(obj, key, default)


def _collect_image_urls(source: Any) -> tuple[str, ...]:
    urls: list[str] = []
    for entry in _iter_sequence(source):
        if isinstance(entry, Mapping):
            candidate = _coerce_str(entry.get("url") or entry.get("href"))
        else:
            candidate = _coerce_str(entry)
        if candidate and candidate not in urls:
            urls.append(candidate)
    return tuple(urls)


def _collect_track_count_metadata(source: Any) -> dict[str, int]:
    mapping = _extract_mapping(source)
    metadata_mapping = None
    if mapping is not None:
        metadata_mapping = _extract_mapping(mapping.get("metadata"))
    counts: dict[str, int] = {}
    for key in _TRACK_COUNT_KEYS:
        raw = None
        if mapping is not None and key in mapping:
            raw = mapping.get(key)
        elif metadata_mapping is not None and key in metadata_mapping:
            raw = metadata_mapping.get(key)
        elif mapping is None:
            raw = getattr(source, key, None)
            if raw is None:
                metadata_attr = getattr(source, "metadata", None)
                if isinstance(metadata_attr, Mapping):
                    raw = metadata_attr.get(key)
                elif metadata_attr is not None:
                    raw = getattr(metadata_attr, key, None)
        value = _coerce_int(raw)
        if value is not None:
            counts[key] = value
    if "total_tracks" not in counts:
        for key in _TRACK_COUNT_KEYS:
            if key in counts:
                counts["total_tracks"] = counts[key]
                break
    return counts


def normalize_spotify_track(
    payload: Mapping[str, Any] | Any,
    *,
    provider: str = "spotify",
    album_payload: Mapping[str, Any] | Any | None = None,
) -> ProviderTrack:
    """Convert a Spotify track payload into :class:`ProviderTrack`."""

    def _get(value: Any, key: str, default: Any = None) -> Any:
        return _get_field(value, key, default)

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
        genres_field = _get(entry, "genres")
        genre_list = [str(item) for item in _iter_sequence(genres_field) if _coerce_str(item)]
        if genre_list:
            artist_metadata["genres"] = tuple(genre_list)
            aggregated_genres.update(genre_list)
        popularity_value = _coerce_int(_get(entry, "popularity"))
        if popularity_value is not None:
            artist_metadata["popularity"] = popularity_value
        images = _collect_image_urls(_get(entry, "images"))
        artist_entries.append(
            ProviderArtist(
                source=provider,
                name=artist_name,
                source_id=artist_id,
                popularity=popularity_value,
                genres=tuple(genre_list),
                images=images,
                metadata=artist_metadata,
            )
        )

    album_payload = album_payload or _get(payload, "album")
    album: ProviderAlbum | None = None
    if album_payload:
        album_name = _coerce_str(_get(album_payload, "name")) or ""
        album_id = _coerce_str(_get(album_payload, "id"))
        album_metadata: dict[str, Any] = {}
        track_counts = _collect_track_count_metadata(album_payload)
        if track_counts:
            album_metadata.update(track_counts)
        release_year = _coerce_int(_get(album_payload, "release_year"))
        if release_year is not None:
            album_metadata["release_year"] = release_year
        release_date = _coerce_str(_get(album_payload, "release_date"))
        if release_date:
            album_metadata["release_date"] = release_date
        total_tracks = _coerce_int(_get(album_payload, "total_tracks"))
        if total_tracks is not None and "total_tracks" not in album_metadata:
            album_metadata["total_tracks"] = total_tracks
        album_artists_payload = _get(album_payload, "artists", ())
        album_artists: list[ProviderArtist] = []
        for entry in _iter_sequence(album_artists_payload):
            album_artist_name = _coerce_str(_get(entry, "name")) or ""
            album_artist_id = _coerce_str(_get(entry, "id"))
            album_artist_metadata: dict[str, Any] = {}
            genres = _get(entry, "genres")
            genre_list = [str(item) for item in _iter_sequence(genres) if _coerce_str(item)]
            if genre_list:
                album_artist_metadata["genres"] = tuple(genre_list)
            album_artists.append(
                ProviderArtist(
                    source=provider,
                    name=album_artist_name,
                    source_id=album_artist_id,
                    genres=tuple(genre_list),
                    images=_collect_image_urls(_get(entry, "images")),
                    metadata=album_artist_metadata,
                )
            )
        album_images = _collect_image_urls(_get(album_payload, "images"))
        album_total = album_metadata.get("total_tracks")
        album = ProviderAlbum(
            name=album_name,
            id=album_id,
            artists=tuple(album_artists),
            metadata=album_metadata,
            release_date=release_date,
            total_tracks=_coerce_int(album_total) if album_total is not None else total_tracks,
            images=album_images,
        )

    genres = _get(payload, "genres")
    if genres:
        metadata["genres"] = tuple(
            str(item) for item in _iter_sequence(genres) if _coerce_str(item)
        )
    if aggregated_genres and "genres" not in metadata:
        metadata["genres"] = tuple(sorted(aggregated_genres))

    popularity_score = _coerce_float(_get(payload, "popularity"))

    return ProviderTrack(
        name=name,
        provider=provider,
        id=track_id,
        artists=tuple(artist_entries),
        album=album,
        duration_ms=duration_ms,
        isrc=isrc,
        score=popularity_score,
        candidates=tuple(),
        metadata=metadata,
    )


def from_spotify_artist(payload: Mapping[str, Any] | Any) -> ProviderArtist:
    """Convert a Spotify artist payload into :class:`ProviderArtist`."""

    name = _coerce_str(_get_field(payload, "name")) or ""
    if not name:
        raise ValueError("Spotify artist payload missing 'name'")

    source_id = _coerce_str(_get_field(payload, "id"))
    popularity = _coerce_int(_get_field(payload, "popularity"))
    genres = tuple(
        str(item) for item in _iter_sequence(_get_field(payload, "genres")) if _coerce_str(item)
    )
    images = _collect_image_urls(_get_field(payload, "images"))

    metadata: dict[str, Any] = {}
    followers = _extract_mapping(_get_field(payload, "followers"))
    if followers:
        total = _coerce_int(followers.get("total"))
        if total is not None:
            metadata["followers"] = total
    external_urls = _extract_mapping(_get_field(payload, "external_urls"))
    if external_urls:
        metadata["external_urls"] = dict(external_urls)
    uri = _coerce_str(_get_field(payload, "uri"))
    if uri:
        metadata["uri"] = uri
    metadata_payload = _extract_mapping(_get_field(payload, "metadata"))
    if metadata_payload:
        for key, value in metadata_payload.items():
            if key not in metadata:
                metadata[key] = value

    return ProviderArtist(
        source="spotify",
        name=name,
        source_id=source_id,
        popularity=popularity,
        genres=genres,
        images=images,
        metadata=metadata,
    )


def _ensure_spotify_track(
    entry: Any,
    *,
    provider: str,
    album_payload: Mapping[str, Any] | Any | None,
) -> ProviderTrack:
    if isinstance(entry, ProviderTrack):
        if entry.provider == provider:
            return entry
        return ProviderTrack(
            name=entry.name,
            provider=provider,
            id=entry.id,
            artists=entry.artists,
            album=entry.album,
            duration_ms=entry.duration_ms,
            isrc=entry.isrc,
            score=entry.score,
            candidates=entry.candidates,
            metadata=entry.metadata,
        )
    return normalize_spotify_track(entry, provider=provider, album_payload=album_payload)


def from_spotify_album_details(
    payload: Mapping[str, Any] | Any,
    *,
    tracks: Iterable[Any] = (),
    provider: str = "spotify",
) -> ProviderAlbumDetails:
    """Convert Spotify album payloads into :class:`ProviderAlbumDetails`."""

    mapping = _extract_mapping(payload)
    if mapping is None:
        raise ValueError("Spotify album payload must be a mapping")

    name = _coerce_str(mapping.get("name")) or ""
    if not name:
        raise ValueError("Spotify album payload missing 'name'")

    source_id = _coerce_str(mapping.get("id"))
    release_date = _coerce_str(mapping.get("release_date"))
    total_tracks = _coerce_int(mapping.get("total_tracks"))
    images = _collect_image_urls(mapping.get("images"))

    album_artists: list[ProviderArtist] = []
    for entry in _iter_sequence(mapping.get("artists")):
        try:
            album_artists.append(from_spotify_artist(entry))
        except ValueError:
            continue

    album_metadata: dict[str, Any] = {}
    track_counts = _collect_track_count_metadata(mapping)
    if track_counts:
        album_metadata.update(track_counts)
    label = _coerce_str(mapping.get("label"))
    if label:
        album_metadata["label"] = label
    popularity = _coerce_int(mapping.get("popularity"))
    if popularity is not None:
        album_metadata["popularity"] = popularity
    metadata_payload = _extract_mapping(mapping.get("metadata"))
    if metadata_payload:
        for key, value in metadata_payload.items():
            if key not in album_metadata:
                album_metadata[key] = value

    normalized_tracks = [
        _ensure_spotify_track(entry, provider=provider, album_payload=mapping) for entry in tracks
    ]

    effective_total_tracks = total_tracks
    if effective_total_tracks is None and album_metadata.get("total_tracks") is not None:
        try:
            effective_total_tracks = int(album_metadata["total_tracks"])
        except (TypeError, ValueError):
            effective_total_tracks = None
    if effective_total_tracks is None and normalized_tracks:
        effective_total_tracks = len(normalized_tracks)

    album = ProviderAlbum(
        name=name,
        id=source_id,
        artists=tuple(album_artists),
        metadata=album_metadata,
        release_date=release_date,
        total_tracks=effective_total_tracks,
        images=images,
    )

    detail_metadata: dict[str, Any] = {}
    available_markets = mapping.get("available_markets")
    if isinstance(available_markets, list):
        markets = [str(item) for item in available_markets if _coerce_str(item)]
        if markets:
            detail_metadata["available_markets"] = markets

    return ProviderAlbumDetails(
        source=provider,
        album=album,
        tracks=tuple(normalized_tracks),
        metadata=detail_metadata,
    )


def from_spotify_release(
    payload: Mapping[str, Any] | Any, artist_id: str | None
) -> ProviderRelease:
    """Convert a Spotify album payload into :class:`ProviderRelease`."""

    title = _coerce_str(_get_field(payload, "name")) or ""
    source_id = _coerce_str(_get_field(payload, "id"))
    release_date = _coerce_str(_get_field(payload, "release_date"))
    release_type = _coerce_str(_get_field(payload, "album_type") or _get_field(payload, "type"))
    total_tracks = _coerce_int(_get_field(payload, "total_tracks"))
    version = _coerce_str(
        _get_field(payload, "version")
        or _get_field(payload, "album_group")
        or _get_field(payload, "release_version")
    )
    updated_at = _coerce_str(
        _get_field(payload, "updated_at") or _get_field(payload, "modified_at")
    )

    metadata: dict[str, Any] = {}
    precision = _coerce_str(_get_field(payload, "release_date_precision"))
    if precision:
        metadata["release_date_precision"] = precision
    markets = _get_field(payload, "available_markets")
    if isinstance(markets, list):
        metadata["available_markets"] = [str(item) for item in markets if _coerce_str(item)]
    metadata_payload = _extract_mapping(_get_field(payload, "metadata"))
    if metadata_payload:
        for key, value in metadata_payload.items():
            if key not in metadata:
                metadata[key] = value

    return ProviderRelease(
        source="spotify",
        source_id=source_id,
        artist_source_id=artist_id,
        title=title,
        release_date=release_date,
        type=release_type,
        total_tracks=total_tracks,
        version=version,
        updated_at=updated_at,
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
    for key in _TRACK_COUNT_KEYS:
        value = payload.get(key)
        count = _coerce_int(value)
        if count is not None:
            metadata[key] = count
    payload_metadata = payload.get("metadata")
    if isinstance(payload_metadata, Mapping):
        for key in _TRACK_COUNT_KEYS:
            if key in metadata:
                continue
            count = _coerce_int(payload_metadata.get(key))
            if count is not None:
                metadata[key] = count
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


def from_slskd_artist(payload: Mapping[str, Any] | Any) -> ProviderArtist:
    """Convert a slskd artist payload into :class:`ProviderArtist`."""

    mapping = _extract_mapping(payload)
    if mapping is None:
        raise ValueError("slskd artist payload must be a mapping")

    name = _coerce_str(mapping.get("name")) or ""
    if not name:
        raise ValueError("slskd artist payload missing 'name'")

    source_id = _coerce_str(mapping.get("id") or mapping.get("artist_id"))
    popularity = _coerce_int(mapping.get("popularity"))
    genres_field = mapping.get("genres")
    genres = [str(item) for item in _iter_sequence(genres_field) if _coerce_str(item)]
    if not genres:
        genre = _coerce_str(mapping.get("genre"))
        if genre:
            genres.append(genre)
    images = _collect_image_urls(mapping.get("images") or mapping.get("image"))

    metadata = dict(mapping.get("metadata")) if isinstance(mapping.get("metadata"), Mapping) else {}
    aliases = [str(item) for item in _iter_sequence(mapping.get("aliases")) if _coerce_str(item)]
    if aliases and "aliases" not in metadata:
        metadata["aliases"] = aliases

    return ProviderArtist(
        source="slskd",
        name=name,
        source_id=source_id,
        popularity=popularity,
        genres=tuple(genres),
        images=images,
        metadata=metadata,
    )


def from_slskd_release(payload: Mapping[str, Any] | Any, artist_id: str | None) -> ProviderRelease:
    """Convert a slskd release payload into :class:`ProviderRelease`."""

    mapping = _extract_mapping(payload)
    if mapping is None:
        raise ValueError("slskd release payload must be a mapping")

    title = _coerce_str(mapping.get("title")) or _coerce_str(mapping.get("name")) or ""
    source_id = _coerce_str(mapping.get("id") or mapping.get("release_id"))
    release_date = _coerce_str(mapping.get("release_date") or mapping.get("date"))
    release_type = _coerce_str(mapping.get("type") or mapping.get("release_type"))
    total_tracks = _coerce_int(mapping.get("total_tracks") or mapping.get("track_count"))
    version = _coerce_str(mapping.get("version") or mapping.get("edition"))
    updated_at = _coerce_str(mapping.get("updated_at") or mapping.get("modified_at"))

    metadata = dict(mapping.get("metadata")) if isinstance(mapping.get("metadata"), Mapping) else {}
    for key in ("catalog_number", "catalogue_number", "catno"):
        value = mapping.get(key)
        if value is not None and key not in metadata:
            metadata[key] = value

    return ProviderRelease(
        source="slskd",
        source_id=source_id,
        artist_source_id=artist_id,
        title=title,
        release_date=release_date,
        type=release_type,
        total_tracks=total_tracks,
        version=version,
        updated_at=updated_at,
        metadata=metadata,
    )


def _ensure_slskd_track(entry: Any, *, provider: str) -> ProviderTrack:
    if isinstance(entry, ProviderTrack):
        if entry.provider == provider:
            return entry
        return ProviderTrack(
            name=entry.name,
            provider=provider,
            id=entry.id,
            artists=entry.artists,
            album=entry.album,
            duration_ms=entry.duration_ms,
            isrc=entry.isrc,
            score=entry.score,
            candidates=entry.candidates,
            metadata=entry.metadata,
        )
    return normalize_slskd_track(entry, provider=provider)


def from_slskd_album_details(
    payload: Mapping[str, Any] | Any,
    *,
    tracks: Iterable[Any] = (),
    provider: str = "slskd",
) -> ProviderAlbumDetails:
    """Convert slskd album payloads into :class:`ProviderAlbumDetails`."""

    mapping = _extract_mapping(payload)
    if mapping is None:
        raise ValueError("slskd album payload must be a mapping")

    name = _coerce_str(mapping.get("title") or mapping.get("name")) or ""
    if not name:
        raise ValueError("slskd album payload missing 'name'")

    source_id = _coerce_str(mapping.get("id") or mapping.get("album_id"))
    release_date = _coerce_str(
        mapping.get("release_date") or mapping.get("date") or mapping.get("year")
    )
    total_tracks = _coerce_int(mapping.get("total_tracks") or mapping.get("track_count"))
    images = _collect_image_urls(mapping.get("images") or mapping.get("image"))

    normalized_tracks = [_ensure_slskd_track(entry, provider=provider) for entry in tracks]

    if total_tracks is None and normalized_tracks:
        total_tracks = len(normalized_tracks)

    metadata = dict(mapping.get("metadata")) if isinstance(mapping.get("metadata"), Mapping) else {}
    for key in ("catalog_number", "catalogue_number", "catno"):
        if key in mapping and key not in metadata:
            metadata[key] = mapping[key]

    seen_artists: dict[str, ProviderArtist] = {}
    for track in normalized_tracks:
        for artist in track.artists:
            key = artist.name.lower() if artist.name else ""
            if key and key not in seen_artists:
                seen_artists[key] = artist

    album_artists = tuple(seen_artists.values())

    album = ProviderAlbum(
        name=name,
        id=source_id,
        artists=album_artists,
        metadata=metadata,
        release_date=release_date,
        total_tracks=total_tracks,
        images=images,
    )

    extra_metadata: dict[str, Any] = {}
    aliases = [str(item) for item in _iter_sequence(mapping.get("aliases")) if _coerce_str(item)]
    if aliases:
        extra_metadata["aliases"] = aliases

    if mapping.get("genre") and "genre" not in metadata:
        extra_metadata["genre"] = str(mapping.get("genre"))

    return ProviderAlbumDetails(
        source=provider,
        album=album,
        tracks=tuple(normalized_tracks),
        metadata=extra_metadata,
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
    provider_artists = tuple(
        ProviderArtist(source=provider, name=name) for name in artist_names if name
    )

    album_name = _coerce_str(metadata.get("album"))
    album = None
    if album_name:
        album_metadata = {
            key: metadata[key] for key in _TRACK_COUNT_KEYS if metadata.get(key) is not None
        }
        release_date = _coerce_str(metadata.get("release_date"))
        if not release_date:
            year_value = metadata.get("year")
            release_date = _coerce_str(year_value) if year_value is not None else None
        total_tracks = _coerce_int(album_metadata.get("total_tracks"))
        album = ProviderAlbum(
            name=album_name,
            id=None,
            artists=tuple(),
            metadata=album_metadata,
            release_date=release_date,
            total_tracks=total_tracks,
        )

    track_metadata: dict[str, Any] = {}
    for key in ("genre", "genres", "year", "id", "score", "bitrate_mode") + _TRACK_COUNT_KEYS:
        if key in metadata and metadata[key] is not None:
            track_metadata[key] = metadata[key]

    track_id = _coerce_str(metadata.get("id"))
    score = _coerce_float(metadata.get("score"))

    return ProviderTrack(
        name=candidate.title,
        provider=provider,
        id=track_id,
        artists=provider_artists,
        album=album,
        duration_ms=None,
        isrc=None,
        score=score,
        candidates=(candidate,),
        metadata=track_metadata,
    )


__all__ = [
    "from_slskd_artist",
    "from_slskd_album_details",
    "from_slskd_release",
    "from_spotify_artist",
    "from_spotify_album_details",
    "from_spotify_release",
    "normalize_slskd_candidate",
    "normalize_slskd_track",
    "normalize_spotify_track",
]
