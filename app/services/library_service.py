"""In-memory helper service for matching engine database lookups."""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Iterable, Sequence

from app.utils.text_normalization import normalize_unicode


@dataclass(slots=True)
class LibraryTrack:
    """Simplified representation of a track stored in the library."""

    id: int
    title: str
    artist: str
    album: str | None = None
    normalized_title: str | None = None
    normalized_artist: str | None = None

    def normalised_title(self) -> str:
        if self.normalized_title is None:
            self.normalized_title = normalize_unicode(self.title)
        return self.normalized_title

    def normalised_artist(self) -> str:
        if self.normalized_artist is None:
            self.normalized_artist = normalize_unicode(self.artist)
        return self.normalized_artist


@dataclass(slots=True)
class LibraryAlbum:
    """Simplified representation of an album stored in the library."""

    id: int
    title: str
    artist: str
    track_count: int
    owned_tracks: int | None = None
    normalized_title: str | None = None
    normalized_artist: str | None = None

    def normalised_title(self) -> str:
        if self.normalized_title is None:
            self.normalized_title = normalize_unicode(self.title)
        return self.normalized_title

    def normalised_artist(self) -> str:
        if self.normalized_artist is None:
            self.normalized_artist = normalize_unicode(self.artist)
        return self.normalized_artist


@dataclass(slots=True)
class LibraryService:
    """Provide minimal querying capabilities for the matching engine."""

    tracks: list[LibraryTrack] = field(default_factory=list)
    albums: list[LibraryAlbum] = field(default_factory=list)

    def add_tracks(self, entries: Iterable[LibraryTrack]) -> None:
        self.tracks.extend(entries)

    def add_albums(self, entries: Iterable[LibraryAlbum]) -> None:
        self.albums.extend(entries)

    def get_album(self, album_id: int) -> LibraryAlbum | None:
        for album in self.albums:
            if album.id == album_id:
                return album
        return None

    @staticmethod
    def _like_match(haystack: str, needles: Iterable[str]) -> bool:
        haystack_lower = haystack.lower()
        return any(needle and needle.lower() in haystack_lower for needle in needles)

    def search_tracks_like(
        self, title_variants: Sequence[str], artist_variants: Sequence[str], *, limit: int = 20
    ) -> list[LibraryTrack]:
        matches: list[LibraryTrack] = []
        for track in self.tracks:
            if not self._like_match(track.title, title_variants):
                continue
            if artist_variants and not self._like_match(track.artist, artist_variants):
                continue
            matches.append(track)
            if len(matches) >= limit:
                break
        return matches

    def search_tracks_like_normalized(
        self, title_variants: Sequence[str], artist_variants: Sequence[str], *, limit: int = 20
    ) -> list[LibraryTrack]:
        normalized_titles = [normalize_unicode(title) for title in title_variants if title]
        normalized_artists = [normalize_unicode(artist) for artist in artist_variants if artist]
        matches: list[LibraryTrack] = []
        for track in self.tracks:
            if normalized_titles and not self._like_match(
                track.normalised_title(), normalized_titles
            ):
                continue
            if normalized_artists and not self._like_match(
                track.normalised_artist(), normalized_artists
            ):
                continue
            matches.append(track)
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
    ) -> list[LibraryTrack]:
        target_title = normalize_unicode(title)
        target_artist = normalize_unicode(artist)
        scored: list[tuple[float, LibraryTrack]] = []
        for track in self.tracks:
            title_score = SequenceMatcher(None, target_title, track.normalised_title()).ratio()
            artist_score = SequenceMatcher(None, target_artist, track.normalised_artist()).ratio()
            composite = (title_score * 0.7) + (artist_score * 0.3)
            if composite >= min_score:
                scored.append((composite, track))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [track for _, track in scored[:limit]]

    def search_albums_like(
        self, title_variants: Sequence[str], artist_variants: Sequence[str], *, limit: int = 20
    ) -> list[LibraryAlbum]:
        matches: list[LibraryAlbum] = []
        for album in self.albums:
            if not self._like_match(album.title, title_variants):
                continue
            if artist_variants and not self._like_match(album.artist, artist_variants):
                continue
            matches.append(album)
            if len(matches) >= limit:
                break
        return matches

    def search_albums_like_normalized(
        self, title_variants: Sequence[str], artist_variants: Sequence[str], *, limit: int = 20
    ) -> list[LibraryAlbum]:
        normalized_titles = [normalize_unicode(title) for title in title_variants if title]
        normalized_artists = [normalize_unicode(artist) for artist in artist_variants if artist]
        matches: list[LibraryAlbum] = []
        for album in self.albums:
            if normalized_titles and not self._like_match(
                album.normalised_title(), normalized_titles
            ):
                continue
            if normalized_artists and not self._like_match(
                album.normalised_artist(), normalized_artists
            ):
                continue
            matches.append(album)
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
    ) -> list[LibraryAlbum]:
        target_title = normalize_unicode(title)
        target_artist = normalize_unicode(artist)
        scored: list[tuple[float, LibraryAlbum]] = []
        for album in self.albums:
            title_score = SequenceMatcher(None, target_title, album.normalised_title()).ratio()
            artist_score = SequenceMatcher(None, target_artist, album.normalised_artist()).ratio()
            composite = (title_score * 0.65) + (artist_score * 0.35)
            if composite >= min_score:
                scored.append((composite, album))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [album for _, album in scored[:limit]]
