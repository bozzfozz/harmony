from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, Iterable, Optional, Tuple

from app.core.plex_client import PlexTrackInfo
from app.core.spotify_client import Album, Track


MATCH_THRESHOLD = 0.7
ALBUM_MATCH_THRESHOLD = 0.6


@dataclass
class MatchResult:
    plex_track: Optional[PlexTrackInfo]
    confidence: float
    match_type: str
    is_match: bool


class MusicMatchingEngine:
    """Naive matching engine comparing Spotify and Plex tracks."""

    def _score_track(self, spotify_track: Track, plex_track: PlexTrackInfo) -> float:
        title_ratio = SequenceMatcher(None, spotify_track.title.lower(), plex_track.title.lower()).ratio()
        artist_ratio = SequenceMatcher(None, spotify_track.artist.lower(), plex_track.artist.lower()).ratio()
        album_ratio = SequenceMatcher(None, (spotify_track.album or "").lower(), (plex_track.album or "").lower()).ratio()
        return (title_ratio * 0.5) + (artist_ratio * 0.4) + (album_ratio * 0.1)

    def _match_type(self, spotify_track: Track, plex_track: Optional[PlexTrackInfo], score: float) -> str:
        if plex_track is None:
            return "no_match"

        if (
            spotify_track.title.lower() == plex_track.title.lower()
            and spotify_track.artist.lower() == plex_track.artist.lower()
        ):
            return "exact"

        if spotify_track.artist.lower() == plex_track.artist.lower():
            if spotify_track.album and plex_track.album and spotify_track.album.lower() == plex_track.album.lower():
                return "artist_album"
            return "artist"

        if spotify_track.album and plex_track.album and spotify_track.album.lower() == plex_track.album.lower():
            return "album"

        return "fuzzy" if score >= MATCH_THRESHOLD else "low_confidence"

    def find_best_match(self, spotify_track: Track, plex_candidates: Iterable[PlexTrackInfo]) -> MatchResult:
        best_track: Optional[PlexTrackInfo] = None
        best_score = 0.0
        for candidate in plex_candidates:
            current_score = self._score_track(spotify_track, candidate)
            if current_score > best_score:
                best_score = current_score
                best_track = candidate

        match_type = self._match_type(spotify_track, best_track, best_score)
        return MatchResult(
            plex_track=best_track,
            confidence=best_score,
            match_type=match_type,
            is_match=best_track is not None and best_score >= MATCH_THRESHOLD,
        )

    def _score_album(self, spotify_album: Album, plex_album: Dict[str, object]) -> float:
        title_ratio = SequenceMatcher(None, spotify_album.title.lower(), str(plex_album.get("title", "")).lower()).ratio()
        artist_ratio = SequenceMatcher(None, spotify_album.artist.lower(), str(plex_album.get("artist", "")).lower()).ratio()
        return (title_ratio * 0.6) + (artist_ratio * 0.4)

    def find_best_album_match(
        self, spotify_album: Album, plex_albums: Iterable[Dict[str, object]]
    ) -> Tuple[Optional[Dict[str, object]], float]:
        best_album: Optional[Dict[str, object]] = None
        best_score = 0.0
        for candidate in plex_albums:
            current_score = self._score_album(spotify_album, candidate)
            if current_score > best_score:
                best_score = current_score
                best_album = candidate

        if best_score < ALBUM_MATCH_THRESHOLD:
            return None, best_score

        return best_album, best_score
