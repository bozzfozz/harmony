"""Music matching logic used by Harmony."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, Optional


class MusicMatchingEngine:
    """Provides fuzzy matching utilities across Spotify and Soulseek."""

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

    def compute_relevance_score(self, query: str, candidate: Dict[str, Any]) -> float:
        """Return a lightweight similarity score for arbitrary music items."""

        normalised_query = self._normalize(query)
        if not normalised_query:
            return 0.0

        title = candidate.get("title")
        album = candidate.get("album")
        artists_raw = candidate.get("artists")
        if isinstance(artists_raw, str):
            artists: list[str] = [artists_raw]
        elif isinstance(artists_raw, Iterable):
            artists = [str(entry) for entry in artists_raw if entry]
        else:
            artists = []

        title_score = self._ratio(query, title)
        album_score = self._ratio(query, album)
        artist_score = 0.0
        for artist in artists:
            artist_score = max(artist_score, self._ratio(query, artist))

        composite_terms = [title or "", album or "", " ".join(artists)]
        composite_target = " ".join(term for term in composite_terms if term)
        composite_score = self._ratio(query, composite_target)

        type_hint = str(candidate.get("type") or "").lower()
        if type_hint == "track":
            weights = (0.55, 0.25, 0.15, 0.05)
        elif type_hint == "album":
            weights = (0.35, 0.15, 0.4, 0.1)
        elif type_hint == "artist":
            weights = (0.15, 0.65, 0.1, 0.1)
        else:
            weights = (0.4, 0.3, 0.2, 0.1)

        score = (
            (title_score * weights[0])
            + (artist_score * weights[1])
            + (album_score * weights[2])
            + (composite_score * weights[3])
        )

        normalised_title = self._normalize(title)
        normalised_album = self._normalize(album)
        if normalised_title and normalised_title == normalised_query:
            score += 0.1
        elif normalised_album and normalised_album == normalised_query:
            score += 0.05

        return round(min(score, 1.0), 4)

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
