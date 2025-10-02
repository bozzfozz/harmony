"""In-memory helper service for matching engine database lookups."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, Sequence

from app.schemas.errors import ApiError, ErrorCode
from app.schemas.provider import ProviderAlbum, ProviderTrack
from app.services.errors import ServiceError
from app.utils.text_normalization import normalize_unicode


def _artist_names(track: ProviderTrack) -> list[str]:
    return [artist.name for artist in track.artists if artist.name]


def _album_artist_names(album: ProviderAlbum) -> list[str]:
    return [artist.name for artist in album.artists if artist.name]


def _ensure_positive_limit(limit: int, *, message: str) -> None:
    if limit <= 0:
        raise ServiceError(
            ApiError.from_components(
                code=ErrorCode.VALIDATION_ERROR,
                message=message,
            )
        )


@dataclass(slots=True)
class _TrackEntry:
    track: ProviderTrack
    normalized_title: str
    normalized_artists: tuple[str, ...]


@dataclass(slots=True)
class _AlbumEntry:
    album: ProviderAlbum
    normalized_title: str
    normalized_artists: tuple[str, ...]


class LibraryService:
    """Provide minimal querying capabilities for the matching engine."""

    def __init__(self) -> None:
        self._tracks: list[_TrackEntry] = []
        self._albums: list[_AlbumEntry] = []

    def add_tracks(self, entries: Iterable[ProviderTrack | dict]) -> None:
        for entry in entries:
            track = ProviderTrack.model_validate(entry)
            self._tracks.append(
                _TrackEntry(
                    track=track,
                    normalized_title=normalize_unicode(track.name),
                    normalized_artists=tuple(
                        normalize_unicode(name) for name in _artist_names(track)
                    ),
                )
            )

    def add_albums(self, entries: Iterable[ProviderAlbum | dict]) -> None:
        for entry in entries:
            album = ProviderAlbum.model_validate(entry)
            self._albums.append(
                _AlbumEntry(
                    album=album,
                    normalized_title=normalize_unicode(album.name),
                    normalized_artists=tuple(
                        normalize_unicode(name) for name in _album_artist_names(album)
                    ),
                )
            )

    def get_album(self, album_id: int) -> ProviderAlbum | None:
        for entry in self._albums:
            if entry.album.id == album_id:
                return entry.album
        return None

    @staticmethod
    def _like_match(haystack: str | None, needles: Iterable[str]) -> bool:
        if not haystack:
            return False
        haystack_lower = haystack.lower()
        return any(needle and needle.lower() in haystack_lower for needle in needles)

    def search_tracks_like(
        self, title_variants: Sequence[str], artist_variants: Sequence[str], *, limit: int = 20
    ) -> list[ProviderTrack]:
        _ensure_positive_limit(limit, message="limit must be greater than zero.")
        matches: list[ProviderTrack] = []
        for entry in self._tracks:
            if not self._like_match(entry.track.name, title_variants):
                continue
            if artist_variants and not any(
                self._like_match(name, artist_variants) for name in _artist_names(entry.track)
            ):
                continue
            matches.append(entry.track)
            if len(matches) >= limit:
                break
        return matches

    def search_tracks_like_normalized(
        self, title_variants: Sequence[str], artist_variants: Sequence[str], *, limit: int = 20
    ) -> list[ProviderTrack]:
        _ensure_positive_limit(limit, message="limit must be greater than zero.")
        normalized_titles = [normalize_unicode(title) for title in title_variants if title]
        normalized_artists = [normalize_unicode(artist) for artist in artist_variants if artist]
        matches: list[ProviderTrack] = []
        for entry in self._tracks:
            if normalized_titles and not self._like_match(
                entry.normalized_title, normalized_titles
            ):
                continue
            if normalized_artists and not any(
                self._like_match(name, normalized_artists) for name in entry.normalized_artists
            ):
                continue
            matches.append(entry.track)
            if len(matches) >= limit:
                break
        return matches

    def search_tracks_fuzzy(
        self,
        title: str,
        artist: str,
        *,
        limit: int = 50,
        min_score: float = 0.4,
    ) -> list[ProviderTrack]:
        _ensure_positive_limit(limit, message="limit must be greater than zero.")
        target_title = normalize_unicode(title)
        target_artist = normalize_unicode(artist)
        scored: list[tuple[float, ProviderTrack]] = []
        for entry in self._tracks:
            title_score = SequenceMatcher(None, target_title, entry.normalized_title).ratio()
            artist_score = 0.0
            if entry.normalized_artists:
                artist_score = max(
                    SequenceMatcher(None, target_artist, artist).ratio()
                    for artist in entry.normalized_artists
                )
            composite = (title_score * 0.7) + (artist_score * 0.3)
            if composite >= min_score:
                scored.append((composite, entry.track))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [track for _, track in scored[:limit]]

    def search_albums_like(
        self, title_variants: Sequence[str], artist_variants: Sequence[str], *, limit: int = 20
    ) -> list[ProviderAlbum]:
        _ensure_positive_limit(limit, message="limit must be greater than zero.")
        matches: list[ProviderAlbum] = []
        for entry in self._albums:
            if not self._like_match(entry.album.name, title_variants):
                continue
            if artist_variants and not any(
                self._like_match(name, artist_variants) for name in _album_artist_names(entry.album)
            ):
                continue
            matches.append(entry.album)
            if len(matches) >= limit:
                break
        return matches

    def search_albums_like_normalized(
        self, title_variants: Sequence[str], artist_variants: Sequence[str], *, limit: int = 20
    ) -> list[ProviderAlbum]:
        _ensure_positive_limit(limit, message="limit must be greater than zero.")
        normalized_titles = [normalize_unicode(title) for title in title_variants if title]
        normalized_artists = [normalize_unicode(artist) for artist in artist_variants if artist]
        matches: list[ProviderAlbum] = []
        for entry in self._albums:
            if normalized_titles and not self._like_match(
                entry.normalized_title, normalized_titles
            ):
                continue
            if normalized_artists and not any(
                self._like_match(name, normalized_artists) for name in entry.normalized_artists
            ):
                continue
            matches.append(entry.album)
            if len(matches) >= limit:
                break
        return matches

    def search_albums_fuzzy(
        self,
        title: str,
        artist: str,
        *,
        limit: int = 50,
        min_score: float = 0.45,
    ) -> list[ProviderAlbum]:
        _ensure_positive_limit(limit, message="limit must be greater than zero.")
        target_title = normalize_unicode(title)
        target_artist = normalize_unicode(artist)
        scored: list[tuple[float, ProviderAlbum]] = []
        for entry in self._albums:
            title_score = SequenceMatcher(None, target_title, entry.normalized_title).ratio()
            artist_score = 0.0
            if entry.normalized_artists:
                artist_score = max(
                    SequenceMatcher(None, target_artist, artist).ratio()
                    for artist in entry.normalized_artists
                )
            composite = (title_score * 0.65) + (artist_score * 0.35)
            if composite >= min_score:
                scored.append((composite, entry.album))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [album for _, album in scored[:limit]]
