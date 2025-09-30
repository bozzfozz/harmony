"""Music matching logic used by Harmony."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, Mapping, Optional

from app.config import MatchingConfig, load_matching_config
from app.logging import get_logger
from app.integrations.base import TrackCandidate
from app.integrations.contracts import ProviderTrack
from app.services.library_service import LibraryAlbum, LibraryService, LibraryTrack
from app.utils.text_normalization import (
    clean_album_title,
    clean_track_title,
    expand_artist_aliases,
    extract_editions,
    generate_album_variants,
    generate_track_variants,
    normalize_unicode,
)

logger = get_logger(__name__)


@dataclass(slots=True)
class MatchResult:
    candidate: LibraryTrack | LibraryAlbum | None
    score: float
    path: str


class MusicMatchingEngine:
    """Provides fuzzy matching utilities across Spotify and Soulseek."""

    def __init__(
        self,
        *,
        library_service: LibraryService | None = None,
        config: MatchingConfig | None = None,
    ) -> None:
        self.library = library_service or LibraryService()
        self.config = config or load_matching_config()
        self._last_completion_label: str | None = None
        self._last_track_path: str | None = None
        self._last_album_path: str | None = None

    # ------------------------------------------------------------------
    # Common helpers

    @staticmethod
    def _normalise(value: Optional[str]) -> str:
        return normalize_unicode(value or "")

    @staticmethod
    def _ratio(left: str, right: str) -> float:
        if not left or not right:
            return 0.0
        return SequenceMatcher(None, left, right).ratio()

    def _artist_similarity(self, query_artist: str, candidate_artist: str) -> float:
        query_aliases = expand_artist_aliases(query_artist)
        candidate_aliases = expand_artist_aliases(candidate_artist)
        if not query_aliases or not candidate_aliases:
            return 0.0
        best = 0.0
        for query in query_aliases:
            for candidate in candidate_aliases:
                best = max(best, self._ratio(query, candidate))
        return best

    def _track_title_similarity(self, query: str, candidate: str) -> float:
        raw = self._ratio(self._normalise(query), self._normalise(candidate))
        cleaned_query = clean_track_title(query) or query
        cleaned_candidate = clean_track_title(candidate) or candidate
        cleaned = self._ratio(self._normalise(cleaned_query), self._normalise(cleaned_candidate))
        return max(raw, cleaned)

    def _album_title_similarity(self, query: str, candidate: str) -> float:
        raw = self._ratio(self._normalise(query), self._normalise(candidate))
        cleaned_query = clean_album_title(query) or query
        cleaned_candidate = clean_album_title(candidate) or candidate
        cleaned = self._ratio(self._normalise(cleaned_query), self._normalise(cleaned_candidate))
        return max(raw, cleaned)

    def _penalise_artist(self, score: float, artist_similarity: float) -> float:
        if artist_similarity < self.config.min_artist_similarity:
            return score * 0.5
        return score

    @staticmethod
    def _clamp(score: float) -> float:
        return max(0.0, min(score, 1.0))

    def _log_result(self, entity: str, result: MatchResult, candidates: int) -> None:
        logger.info(
            "%s matching pipeline completed",  # pragma: no cover - logging side effect
            entity,
            extra={
                "event": f"match.{entity}",
                "best_score": result.score,
                "path": result.path,
                "candidates": candidates,
            },
        )

    # ------------------------------------------------------------------
    # Track matching

    def _score_track(self, query_title: str, query_artist: str, candidate: LibraryTrack) -> float:
        title_similarity = self._track_title_similarity(query_title, candidate.title)
        artist_similarity = self._artist_similarity(query_artist, candidate.artist)
        score = (title_similarity * 0.5) + (artist_similarity * 0.5)
        return self._clamp(self._penalise_artist(score, artist_similarity))

    def _score_track_candidates(
        self,
        title: str,
        artist: str,
        candidates: Iterable[LibraryTrack],
    ) -> MatchResult:
        best_candidate: LibraryTrack | None = None
        best_score = 0.0
        for candidate in candidates:
            score = self._score_track(title, artist, candidate)
            if score > best_score:
                best_candidate = candidate
                best_score = score
        return MatchResult(best_candidate, round(best_score, 4), "")

    def match_track(self, title: str, artist: str) -> tuple[LibraryTrack | None, float]:
        """Resolve a track candidate using the staged search pipeline."""

        if not title:
            return None, 0.0

        title_variants = generate_track_variants(title)
        artist_variants = [artist] if artist else []
        artist_variants.extend(expand_artist_aliases(artist))
        best = MatchResult(None, 0.0, "like")
        candidate_counter = 0

        for path, search in (
            ("like", self.library.search_tracks_like),
            ("normalized", self.library.search_tracks_like_normalized),
        ):
            candidates = search(
                title_variants, artist_variants, limit=self.config.fuzzy_max_candidates
            )
            candidate_counter += len(candidates)
            result = self._score_track_candidates(title, artist, candidates)
            result.path = path
            if result.score > best.score:
                best = result
            if best.score >= 0.92:
                break

        if best.score < 0.92:
            fuzzy_title = clean_track_title(title) or title
            candidates = self.library.search_tracks_fuzzy(
                fuzzy_title,
                artist,
                limit=self.config.fuzzy_max_candidates,
            )
            candidate_counter += len(candidates)
            result = self._score_track_candidates(title, artist, candidates)
            result.path = "fuzzy"
            if result.score > best.score:
                best = result

        self._log_result("track", best, candidate_counter)
        self._last_track_path = best.path
        return best.candidate, best.score

    # ------------------------------------------------------------------
    # Album matching

    def _edition_adjustment(self, query_editions: set[str], candidate_editions: set[str]) -> float:
        if not query_editions and not candidate_editions:
            return 0.0
        if query_editions and candidate_editions:
            if query_editions & candidate_editions:
                return 0.08
            return -0.18
        if query_editions and not candidate_editions:
            return -0.08
        return -0.05

    def _track_count_adjustment(
        self,
        expected: Optional[int],
        candidate: Optional[int],
        *,
        edition_mismatch: bool = False,
    ) -> float:
        if not expected or not candidate:
            return 0.0
        if expected <= 0 or candidate <= 0:
            return 0.0
        ratio = candidate / expected
        if ratio >= 1.05:
            bonus = 0.08
        elif ratio >= self.config.complete_threshold:
            bonus = 0.05
        elif ratio >= self.config.nearly_threshold:
            bonus = 0.02
        else:
            return -min(0.15, (1.0 - ratio) * 0.3)
        if edition_mismatch and bonus > 0:
            return 0.0
        return bonus

    def _score_album(
        self,
        title: str,
        artist: str,
        candidate: LibraryAlbum,
        expected_tracks: Optional[int],
    ) -> float:
        title_similarity = self._album_title_similarity(title, candidate.title)
        artist_similarity = self._artist_similarity(artist, candidate.artist)
        query_editions: set[str] = set()
        candidate_editions: set[str] = set()
        if self.config.edition_aware:
            query_editions = extract_editions(title)
            candidate_editions = extract_editions(candidate.title)

        score = (title_similarity * 0.6) + (artist_similarity * 0.4)
        score = self._penalise_artist(score, artist_similarity)

        if self.config.edition_aware:
            score += self._edition_adjustment(query_editions, candidate_editions)

        edition_mismatch = False
        if self.config.edition_aware:
            edition_mismatch = bool(
                (query_editions or candidate_editions) and not (query_editions & candidate_editions)
            )

        score += self._track_count_adjustment(
            expected_tracks or candidate.track_count,
            candidate.track_count,
            edition_mismatch=edition_mismatch,
        )
        return self._clamp(score)

    def _score_album_candidates(
        self,
        title: str,
        artist: str,
        candidates: Iterable[LibraryAlbum],
        expected_tracks: Optional[int],
    ) -> MatchResult:
        best_candidate: LibraryAlbum | None = None
        best_score = 0.0
        for candidate in candidates:
            score = self._score_album(title, artist, candidate, expected_tracks)
            if score > best_score:
                best_candidate = candidate
                best_score = score
        return MatchResult(best_candidate, round(best_score, 4), "")

    def match_album(
        self,
        title: str,
        artist: str,
        expected_tracks: Optional[int] | None = None,
    ) -> tuple[LibraryAlbum | None, float]:
        """Resolve an album candidate considering edition metadata."""

        if not title:
            return None, 0.0

        title_variants = generate_album_variants(title)
        artist_variants = [artist] if artist else []
        artist_variants.extend(expand_artist_aliases(artist))
        best = MatchResult(None, 0.0, "like")
        candidate_counter = 0

        for path, search in (
            ("like", self.library.search_albums_like),
            ("normalized", self.library.search_albums_like_normalized),
        ):
            candidates = search(
                title_variants, artist_variants, limit=self.config.fuzzy_max_candidates
            )
            candidate_counter += len(candidates)
            result = self._score_album_candidates(title, artist, candidates, expected_tracks)
            result.path = path
            if result.score > best.score:
                best = result
            if best.score >= 0.9:
                break

        if best.score < 0.9:
            fuzzy_title = clean_album_title(title) or title
            candidates = self.library.search_albums_fuzzy(
                fuzzy_title,
                artist,
                limit=self.config.fuzzy_max_candidates,
            )
            candidate_counter += len(candidates)
            result = self._score_album_candidates(title, artist, candidates, expected_tracks)
            result.path = "fuzzy"
            if result.score > best.score:
                best = result

        self._log_result("album", best, candidate_counter)
        self._last_album_path = best.path
        return best.candidate, best.score

    # ------------------------------------------------------------------
    # Completion helpers

    def album_completion(self, album_id: int) -> tuple[int, int, bool]:
        album = self.library.get_album(album_id)
        if album is None:
            self._last_completion_label = "missing"
            return 0, 0, False

        owned = max(0, album.owned_tracks if album.owned_tracks is not None else album.track_count)
        expected = max(owned, album.track_count)
        ratio = (owned / expected) if expected else 0.0

        if ratio >= self.config.complete_threshold:
            self._last_completion_label = "complete"
            return owned, expected, True
        if ratio >= self.config.nearly_threshold:
            self._last_completion_label = "nearly"
        else:
            self._last_completion_label = "incomplete"
        return owned, expected, False

    @property
    def last_completion_label(self) -> str | None:
        return self._last_completion_label

    @property
    def last_track_path(self) -> str | None:
        return self._last_track_path

    @property
    def last_album_path(self) -> str | None:
        return self._last_album_path

    # ------------------------------------------------------------------
    # Legacy helpers preserved for compatibility

    def compute_relevance_score(self, query: str, candidate: Dict[str, Any]) -> float:
        """Return a lightweight similarity score for arbitrary music items."""

        normalised_query = self._normalise(query)
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

        title_score = self._ratio(self._normalise(query), self._normalise(title))
        album_score = self._ratio(self._normalise(query), self._normalise(album))
        artist_score = 0.0
        for artist in artists:
            artist_score = max(
                artist_score, self._ratio(self._normalise(query), self._normalise(artist))
            )

        composite_terms = [title or "", album or "", " ".join(artists)]
        composite_target = " ".join(term for term in composite_terms if term)
        composite_score = self._ratio(self._normalise(query), self._normalise(composite_target))

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

        normalised_title = self._normalise(title)
        normalised_album = self._normalise(album)
        if normalised_title and normalised_title == normalised_query:
            score += 0.1
        elif normalised_album and normalised_album == normalised_query:
            score += 0.05

        return round(min(score, 1.0), 4)

    def calculate_slskd_match_confidence(
        self,
        spotify_track: ProviderTrack | Mapping[str, Any],
        soulseek_entry: TrackCandidate | Mapping[str, Any],
    ) -> float:
        """Return a confidence score comparing Spotify and Soulseek payloads."""

        def _first_artist_from_mapping(payload: Mapping[str, Any]) -> str:
            artists_value = payload.get("artists")
            if isinstance(artists_value, list) and artists_value:
                first = artists_value[0]
                if isinstance(first, Mapping):
                    return str(first.get("name") or first.get("artist") or "")
                return str(first or "")
            if isinstance(artists_value, Mapping):
                return str(artists_value.get("name") or "")
            return str(payload.get("artist") or "")

        track_name: str
        track_artist: str
        if isinstance(spotify_track, ProviderTrack):
            track_name = spotify_track.name
            if spotify_track.artists:
                track_artist = spotify_track.artists[0].name
            else:
                track_artist = ""
                metadata_artists = spotify_track.metadata.get("artists")
                if isinstance(metadata_artists, (list, tuple)) and metadata_artists:
                    track_artist = str(metadata_artists[0])
        elif isinstance(spotify_track, Mapping):
            track_name = str(spotify_track.get("name") or "")
            track_artist = _first_artist_from_mapping(spotify_track)
        else:
            track_name = str(getattr(spotify_track, "name", "") or "")
            track_artist = str(getattr(spotify_track, "artist", "") or "")

        if isinstance(soulseek_entry, TrackCandidate):
            candidate_title_raw = soulseek_entry.metadata.get("filename")
            if not candidate_title_raw:
                candidate_title_raw = soulseek_entry.download_uri or soulseek_entry.title
            candidate_username = soulseek_entry.username or ""
            candidate_artist = soulseek_entry.artist or ""
            candidate_bitrate = soulseek_entry.bitrate_kbps or 0
            candidate_metadata = soulseek_entry.metadata
        else:
            candidate_mapping: Mapping[str, Any]
            if isinstance(soulseek_entry, Mapping):
                candidate_mapping = soulseek_entry
            else:
                candidate_mapping = {}
            candidate_title_raw = (
                candidate_mapping.get("filename")
                or candidate_mapping.get("title")
                or candidate_mapping.get("name")
                or getattr(soulseek_entry, "filename", None)
                or getattr(soulseek_entry, "title", None)
                or ""
            )
            candidate_username = str(
                candidate_mapping.get("username")
                or candidate_mapping.get("user")
                or getattr(soulseek_entry, "username", "")
            )
            candidate_artist = str(
                candidate_mapping.get("artist")
                or getattr(soulseek_entry, "artist", "")
            )
            bitrate_value = (
                candidate_mapping.get("bitrate")
                or candidate_mapping.get("bitrate_kbps")
                or getattr(soulseek_entry, "bitrate_kbps", None)
            )
            candidate_bitrate = int(bitrate_value or 0)
            candidate_metadata = candidate_mapping.get("metadata")
            if not isinstance(candidate_metadata, Mapping):
                candidate_metadata = {}

        candidate_title_text = str(candidate_title_raw or "")
        normalized_track_title = self._normalise(track_name)
        normalized_candidate_title = self._normalise(candidate_title_text)
        alternate_title = ""
        if " - " in candidate_title_text:
            alternate_title = candidate_title_text.split(" - ", 1)[1]
        elif isinstance(candidate_metadata, Mapping):
            filename = candidate_metadata.get("filename")
            if filename and " - " in str(filename):
                alternate_title = str(filename).split(" - ", 1)[1]
        title_score = max(
            self._ratio(normalized_track_title, normalized_candidate_title),
            self._ratio(normalized_track_title, self._normalise(alternate_title)),
        )

        candidate_artist_name = candidate_artist
        if not candidate_artist_name and isinstance(candidate_metadata, Mapping):
            artists_meta = candidate_metadata.get("artists")
            if isinstance(artists_meta, list) and artists_meta:
                candidate_artist_name = str(artists_meta[0])

        artist_score = self._ratio(
            self._normalise(track_artist),
            self._normalise(candidate_username or candidate_artist_name),
        )
        bitrate_score = 1.0 if candidate_bitrate >= 256 else 0.5
        return round((title_score * 0.6) + (artist_score * 0.2) + (bitrate_score * 0.2), 4)
