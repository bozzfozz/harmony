from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, Optional

from app.core.plex_client import PlexTrackInfo
from app.core.spotify_client import Track


@dataclass
class MatchResult:
    plex_track: PlexTrackInfo
    score: float


class MusicMatchingEngine:
    """Naive matching engine comparing Spotify and Plex tracks."""

    def score(self, spotify_track: Track, plex_track: PlexTrackInfo) -> float:
        title_ratio = SequenceMatcher(None, spotify_track.title.lower(), plex_track.title.lower()).ratio()
        artist_ratio = SequenceMatcher(None, spotify_track.artist.lower(), plex_track.artist.lower()).ratio()
        album_ratio = SequenceMatcher(None, (spotify_track.album or "").lower(), (plex_track.album or "").lower()).ratio()
        return (title_ratio * 0.5) + (artist_ratio * 0.4) + (album_ratio * 0.1)

    def find_best_match(self, spotify_track: Track, plex_candidates: Iterable[PlexTrackInfo]) -> Optional[MatchResult]:
        best_result: Optional[MatchResult] = None
        for candidate in plex_candidates:
            current_score = self.score(spotify_track, candidate)
            if not best_result or current_score > best_result.score:
                best_result = MatchResult(plex_track=candidate, score=current_score)
        return best_result
