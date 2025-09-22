"""Music matching logic used by Harmony."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Dict, Iterable, Optional, Tuple


class MusicMatchingEngine:
    """Provides fuzzy matching utilities across Spotify, Plex and Soulseek."""

    def _normalize(self, value: Optional[str]) -> str:
        if not value:
            return ""
        normalized = unicodedata.normalize("NFKD", value)
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        normalized = re.sub(r"[^a-z0-9]+", " ", normalized.lower())
        return normalized.strip()

    def _ratio(self, a: Optional[str], b: Optional[str]) -> float:
        na, nb = self._normalize(a), self._normalize(b)
        if not na or not nb:
            return 0.0
        return SequenceMatcher(None, na, nb).ratio()

    def calculate_match_confidence(self, spotify_track: Dict[str, str], plex_track: Dict[str, str]) -> float:
        title_score = self._ratio(spotify_track.get("name"), plex_track.get("title"))
        artist_score = self._ratio(
            (spotify_track.get("artists") or [{}])[0].get("name") if isinstance(spotify_track.get("artists"), list) else spotify_track.get("artist"),
            plex_track.get("artist") or plex_track.get("grandparentTitle"),
        )
        album_score = self._ratio(
            (spotify_track.get("album") or {}).get("name") if isinstance(spotify_track.get("album"), dict) else spotify_track.get("album"),
            plex_track.get("album") or plex_track.get("parentTitle"),
        )
        duration_spotify = spotify_track.get("duration_ms")
        duration_plex = plex_track.get("duration")
        duration_score = 0.0
        if duration_spotify and duration_plex:
            duration_score = 1.0 - min(abs(duration_spotify - duration_plex) / max(duration_spotify, duration_plex), 1)

        return round((title_score * 0.5) + (artist_score * 0.3) + (album_score * 0.15) + (duration_score * 0.05), 4)

    def find_best_match(
        self, spotify_track: Dict[str, str], plex_candidates: Iterable[Dict[str, str]]
    ) -> Tuple[Optional[Dict[str, str]], float]:
        best_match: Optional[Dict[str, str]] = None
        best_score = 0.0
        for candidate in plex_candidates:
            score = self.calculate_match_confidence(spotify_track, candidate)
            if score > best_score:
                best_score = score
                best_match = candidate
        return best_match, best_score

    def calculate_slskd_match_confidence(
        self, spotify_track: Dict[str, str], soulseek_entry: Dict[str, str]
    ) -> float:
        title_score = self._ratio(spotify_track.get("name"), soulseek_entry.get("filename"))
        artist = (
            (spotify_track.get("artists") or [{}])[0].get("name")
            if isinstance(spotify_track.get("artists"), list)
            else spotify_track.get("artist")
        )
        artist_score = self._ratio(artist, soulseek_entry.get("username"))
        bitrate_score = 1.0 if soulseek_entry.get("bitrate", 0) >= 256 else 0.5
        return round((title_score * 0.6) + (artist_score * 0.2) + (bitrate_score * 0.2), 4)
