"""Utility classes and helpers for matching music metadata across services."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, List, Optional

from app.utils.logging_config import get_logger


logger = get_logger("matching_engine")


_FEATURE_PATTERN = re.compile(r"\bfeat(?:\.|uring)?\s+[^\-()]*", re.IGNORECASE)
_REMIX_PATTERN = re.compile(r"\bremaster(?:ed)?\b", re.IGNORECASE)
_SPECIAL_EDITION_PATTERN = re.compile(r"\bspecial\s+edition\b", re.IGNORECASE)
_PAREN_CONTENT_PATTERN = re.compile(r"\([^)]*\)")
_SEPARATORS_PATTERN = re.compile(r"[^a-z0-9]+")


@dataclass
class SpotifyTrack:
    id: str
    name: str
    artists: List[str]
    album: str | None = None
    duration_ms: int | None = None


@dataclass
class PlexTrackInfo:
    id: str
    title: str
    artist: str
    album: str | None = None
    duration_ms: int | None = None


@dataclass
class SoulseekTrackResult:
    id: str | None
    title: str
    artist: str | None
    filename: str
    duration_ms: int | None = None
    bitrate: int | None = None


class MusicMatchingEngine:
    """Determine the best Plex or Soulseek match for a Spotify track."""

    def _normalise(self, value: str | None) -> str:
        if not value:
            return ""

        text = value.lower()
        text = _PAREN_CONTENT_PATTERN.sub(" ", text)
        text = _FEATURE_PATTERN.sub(" ", text)
        text = _REMIX_PATTERN.sub(" ", text)
        text = _SPECIAL_EDITION_PATTERN.sub(" ", text)
        text = _SEPARATORS_PATTERN.sub(" ", text)
        return " ".join(text.split())

    def _ratio(self, left: str | None, right: str | None) -> float:
        normalised_left = self._normalise(left)
        normalised_right = self._normalise(right)
        if not normalised_left or not normalised_right:
            return 0.0
        return SequenceMatcher(None, normalised_left, normalised_right).ratio()

    def calculate_match_confidence(self, spotify_track: SpotifyTrack, plex_track: PlexTrackInfo) -> float:
        """Return a weighted similarity score between Spotify and Plex tracks."""

        title_score = self._ratio(spotify_track.name, plex_track.title)
        artist_score = self._ratio(" ".join(spotify_track.artists), plex_track.artist)
        album_score = self._ratio(spotify_track.album, plex_track.album)

        duration_score = 0.0
        if spotify_track.duration_ms and plex_track.duration_ms:
            delta = abs(spotify_track.duration_ms - plex_track.duration_ms)
            max_duration = max(spotify_track.duration_ms, plex_track.duration_ms)
            duration_score = 1.0 - (delta / max_duration)
            duration_score = max(duration_score, 0.0)

        confidence = (title_score * 0.6) + (artist_score * 0.3) + (album_score * 0.05) + (duration_score * 0.05)
        logger.debug(
            "Match confidence calculated: title=%.3f artist=%.3f album=%.3f duration=%.3f -> %.3f",
            title_score,
            artist_score,
            album_score,
            duration_score,
            confidence,
        )
        return confidence

    def find_best_match(self, spotify_track: SpotifyTrack, plex_tracks: Iterable[PlexTrackInfo]) -> dict[str, object]:
        """Return the Plex track with the highest confidence."""

        best_track: Optional[PlexTrackInfo] = None
        best_confidence = 0.0
        for candidate in plex_tracks:
            confidence = self.calculate_match_confidence(spotify_track, candidate)
            if confidence > best_confidence:
                best_track = candidate
                best_confidence = confidence

        matched = best_track is not None and best_confidence >= 0.5
        logger.info(
            "Best Plex match for %s: track=%s confidence=%.3f", spotify_track.id, getattr(best_track, "id", None), best_confidence
        )
        return {
            "track": best_track,
            "confidence": best_confidence,
            "matched": matched,
        }

    def calculate_slskd_match_confidence(
        self, spotify_track: SpotifyTrack, slskd_track: SoulseekTrackResult
    ) -> float:
        """Return similarity score for Soulseek results."""

        title_score = self._ratio(spotify_track.name, slskd_track.title or slskd_track.filename)
        artist_score = self._ratio(" ".join(spotify_track.artists), slskd_track.artist)

        duration_score = 0.0
        if spotify_track.duration_ms and slskd_track.duration_ms:
            delta = abs(spotify_track.duration_ms - slskd_track.duration_ms)
            max_duration = max(spotify_track.duration_ms, slskd_track.duration_ms)
            duration_score = 1.0 - (delta / max_duration)
            duration_score = max(duration_score, 0.0)

        confidence = (title_score * 0.7) + (artist_score * 0.25) + (duration_score * 0.05)
        logger.debug(
            "Soulseek confidence: title=%.3f artist=%.3f duration=%.3f -> %.3f",
            title_score,
            artist_score,
            duration_score,
            confidence,
        )
        return confidence


__all__ = ["MusicMatchingEngine", "SpotifyTrack", "PlexTrackInfo", "SoulseekTrackResult"]

