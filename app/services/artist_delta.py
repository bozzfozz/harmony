"""Helpers for computing artist release deltas from provider payloads."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from app.core import ProviderAlbumDTO, ProviderTrackDTO, ensure_album_dto, ensure_track_dto


@dataclass(frozen=True)
class AlbumRelease:
    """Normalized representation of an album release used for delta calculation."""

    album: ProviderAlbumDTO
    release_date: datetime | None
    etag: str | None = None
    raw: Mapping[str, Any] | None = None

    @property
    def album_id(self) -> str | None:
        return self.album.source_id

    @property
    def source(self) -> str:
        return self.album.source

    @staticmethod
    def _coerce_mapping(payload: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
        if payload is None:
            return None
        return dict(payload)

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any] | None,
        *,
        source: str = "unknown",
    ) -> AlbumRelease | None:
        """Return an :class:`AlbumRelease` from a raw provider mapping."""

        if not isinstance(payload, Mapping):
            return None
        album_id_raw = payload.get("id") or payload.get("album_id")
        if album_id_raw in (None, ""):
            return None
        album_id = str(album_id_raw).strip()
        if not album_id:
            return None
        release_date = parse_release_date(
            payload.get("release_date"), payload.get("release_date_precision")
        )
        metadata: dict[str, Any] = {}
        for key in ("release_date", "release_date_precision", "album_type"):
            value = payload.get(key)
            if value is not None:
                metadata[key] = value
        if release_date is not None:
            metadata.setdefault("release_year", release_date.year)
        album_payload: dict[str, Any] = {
            "id": album_id,
            "name": payload.get("name"),
            "artists": payload.get("artists"),
            "total_tracks": payload.get("total_tracks"),
            "metadata": metadata,
            "source": source,
        }
        if release_date is not None:
            album_payload["year"] = release_date.year
        album = ensure_album_dto(album_payload, default_source=source)
        etag = _optional_str(payload.get("etag"))
        return cls(album=album, release_date=release_date, etag=etag, raw=cls._coerce_mapping(payload))


@dataclass(frozen=True)
class ArtistKnownRelease:
    """Persisted state describing a processed track."""

    track_id: str
    etag: str | None = None
    fetched_at: datetime | None = None


@dataclass(frozen=True)
class ArtistTrackCandidate:
    """Track candidate used to compute the delta for an artist."""

    track: ProviderTrackDTO
    release: AlbumRelease
    raw_track: Mapping[str, Any] | None = None

    @property
    def track_id(self) -> str | None:
        return self.track.source_id

    @property
    def release_date(self) -> datetime | None:
        return self.release.release_date

    @property
    def raw_album(self) -> Mapping[str, Any] | None:
        return self.release.raw

    @property
    def cache_key(self) -> str:
        album = self.track.album
        album_id = album.source_id if album else ""
        artists = "|".join(artist.name for artist in self.track.artists)
        release_date = self.release_date.isoformat() if self.release_date else ""
        duration = str(self.track.duration_ms or "")
        payload = "\n".join(
            [
                self.track.source or "",
                self.track.source_id or "",
                album_id or "",
                self.track.title,
                artists,
                release_date,
                duration,
            ]
        )
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
        return f"artist-track:{digest}"

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any] | None,
        release: AlbumRelease,
        *,
        source: str | None = None,
    ) -> ArtistTrackCandidate | None:
        """Return a candidate built from a provider mapping."""

        if not isinstance(payload, Mapping):
            return None
        track_id_raw = payload.get("id") or payload.get("track_id")
        if track_id_raw in (None, ""):
            return None
        track_id = str(track_id_raw).strip()
        if not track_id:
            return None
        metadata: dict[str, Any] = {}
        for key in ("disc_number", "track_number", "explicit", "external_ids", "isrc"):
            value = payload.get(key)
            if value is not None and key not in metadata:
                metadata[key] = value
        track_payload: dict[str, Any] = {
            "id": track_id,
            "name": payload.get("name") or payload.get("title"),
            "artists": payload.get("artists"),
            "duration_ms": payload.get("duration_ms") or payload.get("duration"),
            "album": release.album,
            "metadata": metadata,
            "source": source or release.source,
        }
        track = ensure_track_dto(track_payload, default_source=source or release.source)
        return cls(track=track, release=release, raw_track=dict(payload))


@dataclass(frozen=True)
class ArtistCacheHint:
    """Metadata describing the combined cache characteristics of a delta result."""

    etag: str
    latest_release_at: datetime | None
    release_count: int


@dataclass(frozen=True)
class ArtistDelta:
    """Delta between provider releases and persisted state."""

    new: tuple[ArtistTrackCandidate, ...]
    updated: tuple[ArtistTrackCandidate, ...]
    cache_hint: ArtistCacheHint | None


KnownReleasesInput = (
    Mapping[str, ArtistKnownRelease | str | None] | Iterable[str] | Iterable[ArtistKnownRelease]
)


def parse_release_date(value: Any, precision: Any) -> datetime | None:
    """Return a parsed release date using the provided precision."""

    if not value:
        return None
    precision_value = str(precision or "day").lower()
    text = str(value).strip()
    if not text:
        return None
    try:
        if precision_value == "day":
            return datetime.strptime(text, "%Y-%m-%d")
        if precision_value == "month":
            return datetime.strptime(text, "%Y-%m")
        if precision_value == "year":
            return datetime.strptime(text, "%Y")
    except ValueError:
        return None
    return None


def filter_new_releases(
    releases: Sequence[AlbumRelease], *, last_checked: datetime | None
) -> tuple[AlbumRelease, ...]:
    """Return releases that are newer than the provided timestamp."""

    return tuple(release for release in releases if _is_release_new(release, last_checked))


def build_artist_delta(
    candidates: Sequence[ArtistTrackCandidate],
    known_releases: KnownReleasesInput,
    *,
    last_checked: datetime | None,
) -> ArtistDelta:
    """Return the delta describing new and updated track candidates."""

    normalised_known = _normalise_known_releases(known_releases)
    deduped: dict[str, ArtistTrackCandidate] = {}
    for candidate in candidates:
        track_id = candidate.track_id
        if not track_id:
            continue
        if track_id not in deduped:
            deduped[track_id] = candidate
    considered = [
        candidate
        for candidate in deduped.values()
        if _is_release_new(candidate.release, last_checked)
    ]
    new_candidates: list[ArtistTrackCandidate] = []
    updated_candidates: list[ArtistTrackCandidate] = []
    for candidate in considered:
        track_id = candidate.track_id
        if not track_id:
            continue
        known = normalised_known.get(track_id)
        if known is None:
            new_candidates.append(candidate)
            continue
        if known.etag and known.etag != candidate.cache_key:
            updated_candidates.append(candidate)
    cache_hint = _build_cache_hint(considered)
    return ArtistDelta(
        new=tuple(new_candidates),
        updated=tuple(updated_candidates),
        cache_hint=cache_hint,
    )


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _is_release_new(release: AlbumRelease | ArtistTrackCandidate, last_checked: datetime | None) -> bool:
    release_date = release.release_date if isinstance(release, ArtistTrackCandidate) else release.release_date
    if last_checked is None:
        return True
    if release_date is None:
        return False
    return release_date > last_checked


def _normalise_known_releases(
    entries: KnownReleasesInput,
) -> dict[str, ArtistKnownRelease]:
    mapping: dict[str, ArtistKnownRelease] = {}
    if isinstance(entries, Mapping):
        for key, value in entries.items():
            track_id = _optional_str(key)
            if not track_id:
                continue
            if isinstance(value, ArtistKnownRelease):
                mapping[track_id] = value
            elif isinstance(value, str):
                mapping[track_id] = ArtistKnownRelease(
                    track_id=track_id, etag=_optional_str(value)
                )
            else:
                mapping[track_id] = ArtistKnownRelease(track_id=track_id, etag=None)
        return mapping

    for entry in entries:
        if isinstance(entry, ArtistKnownRelease):
            track_id = _optional_str(entry.track_id)
            if track_id:
                mapping[track_id] = entry
            continue
        track_id = _optional_str(entry)
        if track_id:
            mapping[track_id] = ArtistKnownRelease(track_id=track_id, etag=None)
    return mapping


def _build_cache_hint(
    candidates: Sequence[ArtistTrackCandidate],
) -> ArtistCacheHint | None:
    if not candidates:
        return None
    parts: list[str] = []
    latest: datetime | None = None
    for candidate in candidates:
        key = candidate.cache_key
        parts.append(key)
        release_date = candidate.release_date
        if release_date is not None and (latest is None or release_date > latest):
            latest = release_date
    if not parts:
        return None
    digest = hashlib.sha1("|".join(sorted(parts)).encode("utf-8")).hexdigest()
    etag = f'"artist-delta:{digest}:{len(parts)}"'
    return ArtistCacheHint(etag=etag, latest_release_at=latest, release_count=len(parts))


__all__ = [
    "AlbumRelease",
    "ArtistCacheHint",
    "ArtistDelta",
    "ArtistKnownRelease",
    "ArtistTrackCandidate",
    "build_artist_delta",
    "filter_new_releases",
    "parse_release_date",
]
