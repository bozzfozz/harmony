"""Domain DTOs and helpers used by the pure matching engine."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, MutableMapping
from dataclasses import dataclass, field
import math
import re
from types import MappingProxyType
from typing import Any

from .errors import InvalidInputError

_EDITION_KEYWORDS = {
    "anniversary",
    "collector",
    "deluxe",
    "expanded",
    "live",
    "remaster",
    "remastered",
    "remasterd",
    "special",
    "super",
    "ultimate",
}
_EDITION_REGEX = re.compile(r"\b(" + "|".join(sorted(_EDITION_KEYWORDS)) + r")\b", re.IGNORECASE)


_TRACK_COUNT_META_KEYS = (
    "total_tracks",
    "track_count",
    "tracks_count",
    "total_track_count",
    "num_tracks",
    "number_of_tracks",
    "album_total_tracks",
)


def extract_edition_tags(text: str) -> tuple[str, ...]:
    """Return edition markers contained in ``text``."""

    if not text:
        return ()
    matches = {match.group(0).lower() for match in _EDITION_REGEX.finditer(text)}
    return tuple(sorted(matches))


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    text = str(value).strip()
    return text or None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int | float) and not isinstance(value, bool):
        result = int(value)
        return result
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _iter_sequence(obj: Any) -> Iterable[Any]:
    if obj is None:
        return ()
    if isinstance(obj, list | tuple):
        return obj
    return (obj,)


def _normalise_aliases(aliases: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for alias in aliases:
        text = _coerce_str(alias)
        if not text:
            continue
        lowered = text.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(text)
    return tuple(result)


def _freeze_mapping(
    mapping: Mapping[str, Any] | MutableMapping[str, Any] | None,
) -> Mapping[str, Any]:
    if not mapping:
        return MappingProxyType({})
    normalised: dict[str, Any] = {}
    for key, value in mapping.items():
        text_key = _coerce_str(key)
        if text_key is None:
            continue
        normalised[text_key] = value
    return MappingProxyType(normalised)


def _collect_edition_tags(*sources: Iterable[str]) -> tuple[str, ...]:
    collected: set[str] = set()
    for source in sources:
        for tag in source:
            text = _coerce_str(tag)
            if not text:
                continue
            collected.add(text.lower())
    return tuple(sorted(collected))


def _clamp_unit(value: float) -> float:
    if math.isnan(value):
        return 0.0
    return max(0.0, min(1.0, value))


def _clamp_signed(value: float) -> float:
    if math.isnan(value):
        return 0.0
    return max(-1.0, min(1.0, value))


@dataclass(slots=True, frozen=True)
class ProviderArtistDTO:
    """Normalized representation of an artist used by the matching engine."""

    name: str
    source: str
    source_id: str | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)
    popularity: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        name = _coerce_str(self.name)
        if not name:
            raise InvalidInputError("Artist name must not be empty.")
        source = _coerce_str(self.source) or "unknown"
        source_id = _coerce_str(self.source_id)
        aliases = _normalise_aliases(self.aliases)
        popularity = _coerce_int(self.popularity)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "aliases", aliases)
        object.__setattr__(self, "popularity", popularity)
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(slots=True, frozen=True)
class ProviderAlbumDTO:
    """Normalized representation of an album used by the matching engine."""

    title: str
    source: str
    source_id: str | None = None
    artists: tuple[ProviderArtistDTO, ...] = field(default_factory=tuple)
    year: int | None = None
    total_tracks: int | None = None
    edition_tags: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        title = _coerce_str(self.title)
        if not title:
            raise InvalidInputError("Album title must not be empty.")
        source = _coerce_str(self.source) or "unknown"
        source_id = _coerce_str(self.source_id)
        year = _coerce_int(self.year)
        if year is not None and year <= 0:
            year = None
        total_tracks = _coerce_int(self.total_tracks)
        if total_tracks is not None and total_tracks <= 0:
            total_tracks = None
        artists = tuple(self.artists)
        edition_tags = _collect_edition_tags(self.edition_tags, extract_edition_tags(title))
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "artists", artists)
        object.__setattr__(self, "year", year)
        object.__setattr__(self, "total_tracks", total_tracks)
        object.__setattr__(self, "edition_tags", edition_tags)
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))


@dataclass(slots=True, frozen=True)
class ProviderTrackDTO:
    """Normalized representation of a track exposed to the core domain."""

    title: str
    artists: tuple[ProviderArtistDTO, ...] = field(default_factory=tuple)
    album: ProviderAlbumDTO | None = None
    duration_ms: int | None = None
    source: str = "unknown"
    source_id: str | None = None
    popularity: int | None = None
    year: int | None = None
    edition_tags: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        title = _coerce_str(self.title)
        if not title:
            raise InvalidInputError("Track title must not be empty.")
        source = _coerce_str(self.source) or "unknown"
        source_id = _coerce_str(self.source_id)
        duration = _coerce_int(self.duration_ms)
        if duration is not None and duration < 0:
            duration = None
        popularity = _coerce_int(self.popularity)
        if popularity is not None and popularity < 0:
            popularity = None
        year = _coerce_int(self.year)
        if year is not None and year <= 0:
            year = None
        artists = tuple(self.artists)
        edition_tags = list(self.edition_tags)
        edition_tags.extend(extract_edition_tags(title))
        if self.album is not None:
            edition_tags.extend(self.album.edition_tags)
            if year is None and self.album.year is not None:
                year = self.album.year
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "artists", artists)
        object.__setattr__(self, "album", self.album)
        object.__setattr__(self, "duration_ms", duration)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "popularity", popularity)
        object.__setattr__(self, "year", year)
        object.__setattr__(self, "edition_tags", _collect_edition_tags(edition_tags))
        object.__setattr__(self, "metadata", _freeze_mapping(self.metadata))

    @property
    def primary_artist(self) -> str | None:
        return self.artists[0].name if self.artists else None

    @property
    def combined_edition_tags(self) -> tuple[str, ...]:
        return self.edition_tags


@dataclass(slots=True, frozen=True)
class MatchScore:
    """Score components used to rank track candidates."""

    title: float
    artist: float
    album: float
    bonus: float = 0.0
    penalty: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", _clamp_unit(self.title))
        object.__setattr__(self, "artist", _clamp_unit(self.artist))
        object.__setattr__(self, "album", _clamp_unit(self.album))
        object.__setattr__(self, "bonus", _clamp_signed(self.bonus))
        penalty = _clamp_unit(self.penalty)
        object.__setattr__(self, "penalty", penalty)

    @property
    def total(self) -> float:
        base = (self.title * 0.6) + (self.artist * 0.3) + (self.album * 0.1)
        adjusted = base + self.bonus - self.penalty
        return max(0.0, min(1.0, round(adjusted, 4)))


@dataclass(slots=True, frozen=True)
class MatchResult:
    """Result returned by :func:`app.core.matching_engine.rank_candidates`."""

    track: ProviderTrackDTO
    score: MatchScore
    confidence: str

    def __post_init__(self) -> None:
        confidence = (self.confidence or "").strip().lower()
        if confidence not in {"complete", "nearly", "incomplete"}:
            raise InvalidInputError("Unsupported confidence label")
        object.__setattr__(self, "confidence", confidence)

    @property
    def is_confident(self) -> bool:
        return self.confidence in {"complete", "nearly"}


def ensure_artist_dto(payload: Any, *, default_source: str | None = None) -> ProviderArtistDTO:
    if isinstance(payload, ProviderArtistDTO):
        return payload
    mapping: Mapping[str, Any] | None = payload if isinstance(payload, Mapping) else None
    metadata: Mapping[str, Any] | None = None
    if mapping is not None:
        name = mapping.get("name") or mapping.get("title")
        source = mapping.get("source") or mapping.get("provider") or default_source
        source_id = mapping.get("source_id") or mapping.get("id")
        aliases = mapping.get("aliases") or mapping.get("aka")
        popularity = mapping.get("popularity")
        metadata = mapping.get("metadata") if isinstance(mapping.get("metadata"), Mapping) else None
    else:
        name = getattr(payload, "name", None)
        source = getattr(payload, "source", None) or default_source
        source_id = getattr(payload, "source_id", None) or getattr(payload, "id", None)
        aliases = getattr(payload, "aliases", None)
        popularity = getattr(payload, "popularity", None)
        metadata = (
            getattr(payload, "metadata", None)
            if isinstance(getattr(payload, "metadata", None), Mapping)
            else None
        )
    alias_iterable = _iter_sequence(aliases)
    return ProviderArtistDTO(
        name=_coerce_str(name) or "",
        source=_coerce_str(source) or default_source or "unknown",
        source_id=_coerce_str(source_id),
        aliases=_normalise_aliases(alias_iterable),
        popularity=_coerce_int(popularity),
        metadata=metadata or {},
    )


def _extract_total_tracks_from_metadata(
    metadata: Mapping[str, Any] | None,
) -> int | None:
    if not metadata:
        return None
    for key in _TRACK_COUNT_META_KEYS:
        value = metadata.get(key)
        total = _coerce_int(value)
        if total is not None:
            return total
    return None


def ensure_album_dto(payload: Any, *, default_source: str | None = None) -> ProviderAlbumDTO:
    if isinstance(payload, ProviderAlbumDTO):
        return payload
    mapping: Mapping[str, Any] | None = payload if isinstance(payload, Mapping) else None
    if mapping is not None:
        title = mapping.get("title") or mapping.get("name")
        source = mapping.get("source") or mapping.get("provider") or default_source
        source_id = mapping.get("source_id") or mapping.get("id")
        artists = mapping.get("artists")
        year = mapping.get("year") or mapping.get("release_year")
        total_tracks = mapping.get("total_tracks")
        edition_tags = mapping.get("edition_tags") or mapping.get("editions")
        metadata = mapping.get("metadata") if isinstance(mapping.get("metadata"), Mapping) else None
    else:
        title = getattr(payload, "title", None) or getattr(payload, "name", None)
        source = (
            getattr(payload, "source", None) or getattr(payload, "provider", None) or default_source
        )
        source_id = getattr(payload, "source_id", None) or getattr(payload, "id", None)
        artists = getattr(payload, "artists", None)
        year = getattr(payload, "year", None) or getattr(payload, "release_year", None)
        total_tracks = getattr(payload, "total_tracks", None)
        edition_tags = getattr(payload, "edition_tags", None) or getattr(payload, "editions", None)
        metadata = (
            getattr(payload, "metadata", None)
            if isinstance(getattr(payload, "metadata", None), Mapping)
            else None
        )
    if total_tracks is None:
        total_tracks = _extract_total_tracks_from_metadata(metadata)
    artist_entries = tuple(
        ensure_artist_dto(entry, default_source=_coerce_str(source) or default_source or "unknown")
        for entry in _iter_sequence(artists)
    )
    edition_iterable = _iter_sequence(edition_tags)
    return ProviderAlbumDTO(
        title=_coerce_str(title) or "",
        source=_coerce_str(source) or default_source or "unknown",
        source_id=_coerce_str(source_id),
        artists=artist_entries,
        year=_coerce_int(year),
        total_tracks=_coerce_int(total_tracks),
        edition_tags=_collect_edition_tags(
            edition_iterable, extract_edition_tags(_coerce_str(title) or "")
        ),
        metadata=metadata or {},
    )


def ensure_track_dto(payload: Any, *, default_source: str | None = None) -> ProviderTrackDTO:
    if isinstance(payload, ProviderTrackDTO):
        return payload
    mapping: Mapping[str, Any] | None = payload if isinstance(payload, Mapping) else None
    metadata_source: Mapping[str, Any] | None = None
    if mapping is not None:
        title = mapping.get("title") or mapping.get("name")
        source = mapping.get("source") or mapping.get("provider") or default_source
        source_id = mapping.get("source_id") or mapping.get("id") or mapping.get("track_id")
        artists = mapping.get("artists")
        album = mapping.get("album")
        duration = mapping.get("duration_ms") or mapping.get("duration")
        popularity = mapping.get("popularity")
        year = mapping.get("year") or mapping.get("release_year")
        edition_tags = mapping.get("edition_tags") or mapping.get("editions")
        metadata_source = (
            mapping.get("metadata") if isinstance(mapping.get("metadata"), Mapping) else None
        )
    else:
        title = getattr(payload, "title", None) or getattr(payload, "name", None)
        source = (
            getattr(payload, "source", None) or getattr(payload, "provider", None) or default_source
        )
        source_id = (
            getattr(payload, "source_id", None)
            or getattr(payload, "id", None)
            or getattr(payload, "track_id", None)
        )
        artists = getattr(payload, "artists", None)
        album = getattr(payload, "album", None)
        duration = getattr(payload, "duration_ms", None) or getattr(payload, "duration", None)
        popularity = getattr(payload, "popularity", None)
        year = getattr(payload, "year", None) or getattr(payload, "release_year", None)
        edition_tags = getattr(payload, "edition_tags", None) or getattr(payload, "editions", None)
        metadata_source = (
            getattr(payload, "metadata", None)
            if isinstance(getattr(payload, "metadata", None), Mapping)
            else None
        )
    # Fallback artist fields commonly present on candidates
    if not artists:
        artist_name = mapping.get("artist") if mapping else getattr(payload, "artist", None)
        username = mapping.get("username") if mapping else getattr(payload, "username", None)
        artists = (
            [
                ProviderArtistDTO(
                    name=_coerce_str(artist_name) or "",
                    source=_coerce_str(source) or default_source or "unknown",
                )
            ]
            if _coerce_str(artist_name)
            else []
        )
        if _coerce_str(username):
            artists.append(
                ProviderArtistDTO(
                    name=_coerce_str(username) or "",
                    source=_coerce_str(source) or default_source or "unknown",
                    aliases=_normalise_aliases((_coerce_str(artist_name),)),
                )
            )
    artist_entries: tuple[ProviderArtistDTO, ...] = tuple(
        ensure_artist_dto(entry, default_source=_coerce_str(source) or default_source or "unknown")
        for entry in _iter_sequence(artists)
    )
    album_entry = (
        ensure_album_dto(album, default_source=_coerce_str(source) or default_source or "unknown")
        if album
        else None
    )
    metadata = dict(metadata_source or {})
    for key in ("bitrate", "bitrate_kbps", "format", "username", "download_uri"):
        value = mapping.get(key) if mapping else getattr(payload, key, None)
        if value is not None and key not in metadata:
            metadata[key] = value
    return ProviderTrackDTO(
        title=_coerce_str(title) or "",
        artists=artist_entries,
        album=album_entry,
        duration_ms=_coerce_int(duration),
        source=_coerce_str(source) or default_source or "unknown",
        source_id=_coerce_str(source_id),
        popularity=_coerce_int(popularity),
        year=_coerce_int(year),
        edition_tags=_collect_edition_tags(_iter_sequence(edition_tags)),
        metadata=metadata,
    )


__all__ = [
    "MatchResult",
    "MatchScore",
    "ProviderAlbumDTO",
    "ProviderArtistDTO",
    "ProviderTrackDTO",
    "ensure_album_dto",
    "ensure_artist_dto",
    "ensure_track_dto",
    "extract_edition_tags",
]
