"""Helpers for computing artist release deltas from provider payloads."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Sequence, Tuple

from app.core import (ProviderAlbumDTO, ProviderTrackDTO, ensure_album_dto,
                      ensure_track_dto)
from app.services.artist_dao import ArtistReleaseRow, ArtistReleaseUpsertDTO


@dataclass(slots=True, frozen=True)
class ReleaseSnapshot:
    """Minimal view of a persisted release used for delta calculations."""

    id: int
    artist_key: str
    source: str
    source_id: str | None
    title: str
    release_date: date | None
    release_type: str | None
    total_tracks: int | None
    metadata: Mapping[str, object]
    version: str | None
    etag: str | None
    updated_at: datetime | None
    inactive_at: datetime | None
    inactive_reason: str | None

    @classmethod
    def from_row(cls, row: ArtistReleaseRow) -> "ReleaseSnapshot":
        return cls(
            id=row.id,
            artist_key=row.artist_key,
            source=row.source,
            source_id=row.source_id,
            title=row.title,
            release_date=row.release_date,
            release_type=row.release_type,
            total_tracks=row.total_tracks,
            metadata=dict(row.metadata),
            version=row.version,
            etag=row.etag,
            updated_at=row.updated_at,
            inactive_at=row.inactive_at,
            inactive_reason=row.inactive_reason,
        )


@dataclass(slots=True, frozen=True)
class ReleaseUpdate:
    before: ReleaseSnapshot
    after: ArtistReleaseUpsertDTO


@dataclass(slots=True, frozen=True)
class ReleaseDelta:
    added: Tuple[ArtistReleaseUpsertDTO, ...]
    updated: Tuple[ReleaseUpdate, ...]
    removed: Tuple[ReleaseSnapshot, ...]


@dataclass(slots=True, frozen=True)
class AliasDelta:
    added: Tuple[str, ...]
    removed: Tuple[str, ...]


@dataclass(slots=True, frozen=True)
class TrackDelta:
    added: Tuple[Any, ...] = ()
    updated: Tuple[Any, ...] = ()
    removed: Tuple[Any, ...] = ()


@dataclass(slots=True, frozen=True)
class ReleaseDeltaSummary:
    title: str
    source: str | None
    source_id: str | None
    release_date: str | None
    release_type: str | None

    @classmethod
    def from_dto(cls, dto: ArtistReleaseUpsertDTO) -> "ReleaseDeltaSummary":
        return cls(
            title=dto.title,
            source=dto.source,
            source_id=dto.source_id,
            release_date=_format_release_date(dto.release_date),
            release_type=dto.release_type,
        )

    @classmethod
    def from_snapshot(cls, snapshot: ReleaseSnapshot) -> "ReleaseDeltaSummary":
        return cls(
            title=snapshot.title,
            source=snapshot.source,
            source_id=snapshot.source_id,
            release_date=_format_release_date(snapshot.release_date),
            release_type=snapshot.release_type,
        )

    def to_dict(self) -> dict[str, str | None]:
        return {
            "title": self.title,
            "source": self.source,
            "source_id": self.source_id,
            "release_date": self.release_date,
            "release_type": self.release_type,
        }


@dataclass(slots=True, frozen=True)
class DeltaSummaryView:
    added: Tuple[ReleaseDeltaSummary, ...]
    updated: Tuple[ReleaseDeltaSummary, ...]
    removed: Tuple[ReleaseDeltaSummary, ...]
    alias_added: Tuple[str, ...]
    alias_removed: Tuple[str, ...]
    added_count: int
    updated_count: int
    removed_count: int
    alias_added_count: int
    alias_removed_count: int


@dataclass(slots=True, frozen=True)
class ArtistLocalState:
    releases: Tuple[ReleaseSnapshot, ...] = ()
    aliases: Tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class ArtistRemoteState:
    releases: Tuple[ArtistReleaseUpsertDTO, ...] = ()
    aliases: Tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class DeltaResult:
    releases: ReleaseDelta
    aliases: AliasDelta
    tracks: TrackDelta = field(default_factory=TrackDelta)


def determine_delta(local: ArtistLocalState, remote: ArtistRemoteState) -> DeltaResult:
    """Return the delta between the persisted artist state and provider payloads."""

    release_index: dict[Tuple[str, ...], list[ReleaseSnapshot]] = {}
    for snapshot in local.releases:
        key = _release_identity_from_snapshot(snapshot)
        bucket = release_index.setdefault(key, [])
        bucket.append(snapshot)
    for bucket in release_index.values():
        bucket.sort(
            key=lambda item: (item.inactive_at is not None, item.updated_at or datetime.min)
        )

    added: list[ArtistReleaseUpsertDTO] = []
    updated: list[ReleaseUpdate] = []
    seen_remote: set[Tuple[str, ...]] = set()

    for dto in remote.releases:
        identity = _release_identity_from_dto(dto)
        if identity in seen_remote:
            continue
        seen_remote.add(identity)
        candidates = release_index.get(identity)
        snapshot = candidates.pop(0) if candidates else None
        if candidates is not None and not candidates:
            release_index.pop(identity, None)
        if snapshot is None:
            added.append(dto)
            continue
        if _requires_release_update(snapshot, dto):
            updated.append(ReleaseUpdate(before=snapshot, after=dto))

    removed: list[ReleaseSnapshot] = []
    for remaining in release_index.values():
        for snapshot in remaining:
            if snapshot.inactive_at is None:
                removed.append(snapshot)

    alias_delta = _determine_alias_delta(local.aliases, remote.aliases)

    return DeltaResult(
        releases=ReleaseDelta(
            added=tuple(added),
            updated=tuple(updated),
            removed=tuple(removed),
        ),
        aliases=alias_delta,
        tracks=TrackDelta(),
    )


def summarise_delta(delta: DeltaResult, *, limit: int = 20) -> DeltaSummaryView:
    """Return a condensed summary for presentation layers."""

    preview_limit = int(limit)
    if preview_limit > 0:
        added_candidates = delta.releases.added[:preview_limit]
        updated_candidates = delta.releases.updated[:preview_limit]
        removed_candidates = delta.releases.removed[:preview_limit]
        alias_added_candidates = delta.aliases.added[:preview_limit]
        alias_removed_candidates = delta.aliases.removed[:preview_limit]
    else:
        added_candidates = delta.releases.added
        updated_candidates = delta.releases.updated
        removed_candidates = delta.releases.removed
        alias_added_candidates = delta.aliases.added
        alias_removed_candidates = delta.aliases.removed

    added_preview = tuple(ReleaseDeltaSummary.from_dto(dto) for dto in added_candidates)
    updated_preview = tuple(
        ReleaseDeltaSummary.from_dto(change.after) for change in updated_candidates
    )
    removed_preview = tuple(
        ReleaseDeltaSummary.from_snapshot(snapshot) for snapshot in removed_candidates
    )
    alias_added_preview = tuple(alias_added_candidates)
    alias_removed_preview = tuple(alias_removed_candidates)

    return DeltaSummaryView(
        added=added_preview,
        updated=updated_preview,
        removed=removed_preview,
        alias_added=alias_added_preview,
        alias_removed=alias_removed_preview,
        added_count=len(delta.releases.added),
        updated_count=len(delta.releases.updated),
        removed_count=len(delta.releases.removed),
        alias_added_count=len(delta.aliases.added),
        alias_removed_count=len(delta.aliases.removed),
    )


def _format_release_date(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _determine_alias_delta(
    local_aliases: Sequence[str], remote_aliases: Sequence[str]
) -> AliasDelta:
    local_map = _alias_map(local_aliases)
    remote_map = _alias_map(remote_aliases)
    added_keys = remote_map.keys() - local_map.keys()
    removed_keys = local_map.keys() - remote_map.keys()
    added = tuple(remote_map[key] for key in sorted(added_keys))
    removed = tuple(local_map[key] for key in sorted(removed_keys))
    return AliasDelta(added=added, removed=removed)


def _alias_map(values: Sequence[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        mapping[text.casefold()] = text
    return mapping


def _requires_release_update(snapshot: ReleaseSnapshot, dto: ArtistReleaseUpsertDTO) -> bool:
    if snapshot.inactive_at is not None:
        return True
    return _release_fingerprint_from_snapshot(snapshot) != _release_fingerprint_from_dto(dto)


def _release_identity_from_snapshot(snapshot: ReleaseSnapshot) -> Tuple[str, ...]:
    source = _clean_source(snapshot.source)
    source_id = _clean_optional(snapshot.source_id)
    if source_id:
        return ("id", source, source_id)
    return (
        "composite",
        source,
        _clean_text(snapshot.title).casefold(),
        _normalised_date(snapshot.release_date),
        _clean_text(snapshot.release_type).casefold(),
    )


def _release_identity_from_dto(dto: ArtistReleaseUpsertDTO) -> Tuple[str, ...]:
    source = _clean_source(dto.source)
    source_id = _clean_optional(dto.source_id)
    if source_id:
        return ("id", source, source_id)
    return (
        "composite",
        source,
        _clean_text(dto.title).casefold(),
        _normalised_date(dto.release_date),
        _clean_text(dto.release_type).casefold(),
    )


def _release_fingerprint_from_snapshot(snapshot: ReleaseSnapshot) -> Tuple[str, ...]:
    return (
        _clean_text(snapshot.title).casefold(),
        _normalised_date(snapshot.release_date),
        _clean_text(snapshot.release_type).casefold(),
        str(snapshot.total_tracks or ""),
        _hash_mapping(snapshot.metadata),
    )


def _release_fingerprint_from_dto(dto: ArtistReleaseUpsertDTO) -> Tuple[str, ...]:
    return (
        _clean_text(dto.title).casefold(),
        _normalised_date(dto.release_date),
        _clean_text(dto.release_type).casefold(),
        str(dto.total_tracks or ""),
        _hash_mapping(dto.metadata),
    )


def _normalised_date(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = _clean_text(value)
    if not text:
        return ""
    if len(text) == 4 and text.isdigit():
        return text
    if len(text) == 7 and text[:4].isdigit():
        return text
    return text


def _clean_source(value: object | None) -> str:
    text = _clean_text(value)
    return text.casefold() or "unknown"


def _clean_optional(value: object | None) -> str | None:
    text = _clean_text(value)
    return text or None


def _clean_text(value: object | None) -> str:
    if value in (None, ""):
        return ""
    return str(value).strip()


def _hash_mapping(mapping: Mapping[str, object] | None) -> str:
    if not mapping:
        return ""
    try:
        payload = json.dumps(mapping, sort_keys=True, default=str, separators=(",", ":"))
    except TypeError:
        payload = json.dumps({key: str(value) for key, value in mapping.items()}, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


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
        return cls(
            album=album, release_date=release_date, etag=etag, raw=cls._coerce_mapping(payload)
        )


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


def _is_release_new(
    release: AlbumRelease | ArtistTrackCandidate, last_checked: datetime | None
) -> bool:
    release_date = (
        release.release_date if isinstance(release, ArtistTrackCandidate) else release.release_date
    )
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
                mapping[track_id] = ArtistKnownRelease(track_id=track_id, etag=_optional_str(value))
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
    "AliasDelta",
    "AlbumRelease",
    "ArtistCacheHint",
    "ArtistLocalState",
    "ArtistDelta",
    "ArtistKnownRelease",
    "ArtistTrackCandidate",
    "ArtistRemoteState",
    "DeltaResult",
    "DeltaSummaryView",
    "ReleaseDelta",
    "ReleaseDeltaSummary",
    "ReleaseSnapshot",
    "ReleaseUpdate",
    "TrackDelta",
    "build_artist_delta",
    "determine_delta",
    "summarise_delta",
    "filter_new_releases",
    "parse_release_date",
]
