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

    def _extract_album_artist(self, album: Dict[str, str]) -> Optional[str]:
        artists = album.get("artists")
        if isinstance(artists, list) and artists:
            primary_artist = artists[0]
            if isinstance(primary_artist, dict):
                return primary_artist.get("name")
            return str(primary_artist)
        return album.get("artist") or album.get("grandparentTitle")

    def _album_track_count(self, album: Dict[str, str]) -> Optional[int]:
        for key in ("total_tracks", "trackCount", "leafCount", "childCount", "track_count"):
            value = album.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
        tracks = album.get("tracks")
        if isinstance(tracks, dict):
            items = tracks.get("items")
            if isinstance(items, list):
                return len(items)
        if isinstance(tracks, list):
            return len(tracks)
        return None

    def _album_year(self, album: Dict[str, str]) -> Optional[int]:
        for key in ("year", "release_year"):
            value = album.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)
        release_date = album.get("release_date")
        if isinstance(release_date, str) and release_date:
            if len(release_date) >= 4 and release_date[:4].isdigit():
                return int(release_date[:4])
        originally_available_at = album.get("originallyAvailableAt")
        if isinstance(originally_available_at, str) and originally_available_at:
            if originally_available_at[:4].isdigit():
                return int(originally_available_at[:4])
        return None

    def calculate_album_confidence(
        self, spotify_album: Dict[str, str], plex_album: Dict[str, str]
    ) -> float:
        """Calculate similarity score between Spotify and Plex albums."""

        name_score = self._ratio(spotify_album.get("name"), plex_album.get("title"))
        spotify_artist = self._extract_album_artist(spotify_album)
        plex_artist = self._extract_album_artist(plex_album) or plex_album.get("parentTitle")
        artist_score = self._ratio(spotify_artist, plex_artist)

        spotify_tracks = self._album_track_count(spotify_album)
        plex_tracks = self._album_track_count(plex_album)
        track_count_score = 0.0
        if spotify_tracks and plex_tracks:
            diff = abs(spotify_tracks - plex_tracks)
            max_count = max(spotify_tracks, plex_tracks)
            track_count_score = 1.0 - min(diff / max_count, 1)

        spotify_year = self._album_year(spotify_album)
        plex_year = self._album_year(plex_album)
        year_score = 0.0
        if spotify_year and plex_year:
            year_score = 1.0 if spotify_year == plex_year else 0.0

        score = (name_score * 0.4) + (artist_score * 0.4) + (track_count_score * 0.1) + (year_score * 0.1)
        return round(score, 4)

    def find_best_album_match(
        self, spotify_album: Dict[str, str], plex_albums: Iterable[Dict[str, str]]
    ) -> Tuple[Optional[Dict[str, str]], float]:
        """Find the highest scoring Plex album for the given Spotify album."""

        best_match: Optional[Dict[str, str]] = None
        best_score = 0.0
        for candidate in plex_albums:
            score = self.calculate_album_confidence(spotify_album, candidate)
            if score > best_score:
                best_score = score
                best_match = candidate
        return best_match, best_score
