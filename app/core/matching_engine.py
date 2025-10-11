"""Pure matching logic operating on provider DTOs."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping, Sequence

from app.config import MatchingConfig, load_matching_config

from .errors import InvalidInputError
from .types import MatchResult, MatchScore, ProviderTrackDTO, ensure_track_dto

_DEFAULT_MATCHING_CONFIG = load_matching_config()


_TRACK_COUNT_META_KEYS = (
    "total_tracks",
    "track_count",
    "tracks_count",
    "total_track_count",
    "num_tracks",
    "number_of_tracks",
    "album_total_tracks",
)


@dataclass(slots=True, frozen=True)
class _QueryParts:
    raw: str
    title: str
    artists: tuple[str, ...]
    edition_tags: tuple[str, ...]


def _strip_accents(value: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch)
    )


def _normalize_text(value: str) -> str:
    if not value:
        return ""
    normalised = unicodedata.normalize("NFKC", value)
    normalised = _strip_accents(normalised).casefold()
    return " ".join(normalised.split())


def _ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _parse_query(query: str) -> _QueryParts:
    raw = (query or "").strip()
    if not raw:
        raise InvalidInputError("Query must not be empty.")
    working = raw
    for separator in (" – ", " — "):
        if separator in working:
            working = working.replace(separator, " - ")
    artists: list[str] = []
    title = working
    if " - " in working:
        prefix, suffix = working.split(" - ", 1)
        if prefix.strip() and suffix.strip():
            artists.append(prefix.strip())
            title = suffix.strip()
    edition_tags = _extract_edition_tags(title)
    return _QueryParts(raw=raw, title=title, artists=tuple(artists), edition_tags=edition_tags)


_EDITION_PATTERN = re.compile(
    r"\b(anniversary|collector|deluxe|expanded|live|remaster(?:ed|d)?|special|super|ultimate)\b",
    re.IGNORECASE,
)


def _extract_edition_tags(text: str) -> tuple[str, ...]:
    if not text:
        return ()
    return tuple(sorted({match.group(0).lower() for match in _EDITION_PATTERN.finditer(text)}))


def _candidate_artist_names(track: ProviderTrackDTO) -> tuple[str, ...]:
    names: list[str] = []
    for artist in track.artists:
        names.append(_normalize_text(artist.name))
        for alias in artist.aliases:
            names.append(_normalize_text(alias))
    username = track.metadata.get("username")
    if isinstance(username, str):
        names.append(_normalize_text(username))
    seen: set[str] = set()
    deduped: list[str] = []
    for name in names:
        if not name:
            continue
        if name in seen:
            continue
        seen.add(name)
        deduped.append(name)
    return tuple(deduped)


def _artist_similarity(query_artists: Sequence[str], track: ProviderTrackDTO) -> float:
    if not query_artists:
        return 1.0 if track.artists else 0.5
    candidates = _candidate_artist_names(track)
    if not candidates:
        return 0.0
    best = 0.0
    for artist in query_artists:
        normalised = _normalize_text(artist)
        if not normalised:
            continue
        for candidate in candidates:
            best = max(best, _ratio(normalised, candidate))
    return best


def _album_similarity(query: _QueryParts, track: ProviderTrackDTO) -> float:
    if track.album is None:
        return 0.0
    return _ratio(_normalize_text(query.title), _normalize_text(track.album.title))


def _edition_bonus(query_tags: set[str], track_tags: set[str]) -> float:
    if not query_tags:
        return 0.0
    if not track_tags:
        return -0.05
    overlap = query_tags & track_tags
    if overlap:
        return min(0.1, 0.05 + 0.02 * (len(overlap) - 1))
    return -0.08


def _extract_year_from_text(text: str) -> int | None:
    if not text:
        return None
    match = re.search(r"(19|20)\d{2}", text)
    if match:
        return int(match.group(0))
    return None


def _score_candidate(
    query: _QueryParts,
    track: ProviderTrackDTO,
    *,
    min_artist_sim: float,
    edition_aware: bool,
) -> MatchScore:
    normalised_query_title = _normalize_text(query.title)
    title_score = _ratio(normalised_query_title, _normalize_text(track.title))
    artist_score = _artist_similarity(query.artists, track)
    album_score = _album_similarity(query, track)
    penalty = 0.0
    if query.artists and artist_score < min_artist_sim:
        penalty = min(0.4, (min_artist_sim - artist_score) * 0.75)
    bonus = 0.0
    if edition_aware:
        bonus += _edition_bonus(set(query.edition_tags), set(track.combined_edition_tags))
    query_year = _extract_year_from_text(query.raw)
    track_year = track.year
    if query_year is not None and track_year is not None:
        delta = abs(track_year - query_year)
        if delta == 0:
            bonus += 0.02
        elif delta <= 1:
            bonus += 0.01
        elif delta > 5:
            penalty += 0.05
    return MatchScore(
        title=title_score,
        artist=artist_score,
        album=album_score,
        bonus=bonus,
        penalty=penalty,
    )


def _confidence_label(score: float, *, complete: float, nearly: float) -> str:
    if score >= complete:
        return "complete"
    if score >= nearly:
        return "nearly"
    return "incomplete"


def _sort_key(result: MatchResult, total: float) -> tuple[Any, ...]:
    track = result.track
    return (
        -total,
        _normalize_text(track.title),
        track.source,
        track.source_id or "",
    )


def rank_candidates(
    query: str,
    candidates: Sequence[Any],
    *,
    min_artist_sim: float = _DEFAULT_MATCHING_CONFIG.min_artist_similarity,
    complete_thr: float = _DEFAULT_MATCHING_CONFIG.complete_threshold,
    nearly_thr: float = _DEFAULT_MATCHING_CONFIG.nearly_threshold,
    fuzzy_max: int = _DEFAULT_MATCHING_CONFIG.fuzzy_max_candidates,
    edition_aware: bool = _DEFAULT_MATCHING_CONFIG.edition_aware,
) -> list[MatchResult]:
    """Score and rank track candidates for the supplied query."""

    parsed_query = _parse_query(query)
    track_candidates = [ensure_track_dto(candidate) for candidate in candidates]
    enriched: list[tuple[MatchResult, float]] = []
    for track in track_candidates:
        score = _score_candidate(
            parsed_query,
            track,
            min_artist_sim=min_artist_sim,
            edition_aware=edition_aware,
        )
        total = score.total
        confidence = _confidence_label(total, complete=complete_thr, nearly=nearly_thr)
        enriched.append((MatchResult(track=track, score=score, confidence=confidence), total))
    enriched.sort(key=lambda item: _sort_key(item[0], item[1]))
    limit = len(enriched)
    if fuzzy_max >= 0:
        limit = min(limit, fuzzy_max)
    return [result for result, _ in enriched[:limit]]


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _album_total_tracks_from_dto(track: ProviderTrackDTO) -> int | None:
    album = track.album
    if not album:
        return None
    primary = _as_int(album.total_tracks)
    if primary is not None:
        return primary
    for key in _TRACK_COUNT_META_KEYS:
        if key in album.metadata:
            total = _as_int(album.metadata.get(key))
            if total is not None:
                return total
    return None


def _album_total_tracks_from_metadata(metadata: Mapping[str, Any]) -> int | None:
    for key in _TRACK_COUNT_META_KEYS:
        if key in metadata:
            total = _as_int(metadata.get(key))
            if total is not None:
                return total
    return None


def _track_identity_for_completion(track: ProviderTrackDTO) -> tuple[Any, ...]:
    metadata = track.metadata
    disc_candidates = (
        metadata.get("disc_number"),
        metadata.get("discnumber"),
        metadata.get("disc_no"),
        metadata.get("disc"),
    )
    track_candidates = (
        metadata.get("track_number"),
        metadata.get("tracknumber"),
        metadata.get("track"),
        metadata.get("number"),
        metadata.get("position"),
    )
    disc_number = None
    for candidate in disc_candidates:
        disc_number = _as_int(candidate)
        if disc_number is not None:
            break
    track_number = None
    for candidate in track_candidates:
        track_number = _as_int(candidate)
        if track_number is not None:
            break
    if track_number is not None:
        return (disc_number or 1, track_number)
    if track.source_id:
        return (track.source, track.source_id)
    return (
        _normalize_text(track.title),
        tuple(_normalize_text(artist.name) for artist in track.artists),
    )


def calculate_album_completion(
    matched_tracks: Iterable[Any],
    *,
    expected_total_tracks: int | None = None,
    complete_thr: float = _DEFAULT_MATCHING_CONFIG.complete_threshold,
    nearly_thr: float = _DEFAULT_MATCHING_CONFIG.nearly_threshold,
) -> tuple[float, str]:
    """Return album completion ratio and label for a collection of tracks."""

    tracks = [ensure_track_dto(track) for track in matched_tracks]
    if expected_total_tracks is None:
        totals: list[int] = []
        for track in tracks:
            total = _album_total_tracks_from_dto(track)
            if total is None:
                total = _album_total_tracks_from_metadata(track.metadata)
            if total is not None:
                totals.append(total)
        if totals:
            expected_total_tracks = max(totals)

    unique_tracks = {_track_identity_for_completion(track) for track in tracks}
    matched_count = len(unique_tracks)

    if expected_total_tracks is None or expected_total_tracks <= 0:
        ratio = 1.0 if matched_count else 0.0
    else:
        ratio = matched_count / expected_total_tracks
    ratio = max(0.0, min(1.0, round(ratio, 4)))
    label = _confidence_label(ratio, complete=complete_thr, nearly=nearly_thr)
    return ratio, label


def calculate_slskd_match_confidence(spotify_track: Any, soulseek_entry: Any) -> float:
    """Return a confidence score between a Spotify track and a Soulseek candidate."""

    track = ensure_track_dto(spotify_track, default_source="spotify")
    candidate = ensure_track_dto(soulseek_entry, default_source="slskd")
    title_score = _ratio(_normalize_text(track.title), _normalize_text(candidate.title))
    artist_score = 0.0
    primary_artist = track.primary_artist
    if primary_artist:
        for name in _candidate_artist_names(candidate) or (_normalize_text(primary_artist),):
            artist_score = max(artist_score, _ratio(_normalize_text(primary_artist), name))
    else:
        artist_score = 0.5
    bitrate_value = _as_int(
        candidate.metadata.get("bitrate_kbps") or candidate.metadata.get("bitrate")
    )
    if bitrate_value is None:
        bitrate_score = 0.3
    elif bitrate_value >= 256:
        bitrate_score = 1.0
    elif bitrate_value >= 192:
        bitrate_score = 0.7
    else:
        bitrate_score = 0.4
    album_bonus = 0.0
    spotify_total = _album_total_tracks_from_dto(track)
    soulseek_total = _album_total_tracks_from_dto(candidate)
    if spotify_total is not None and soulseek_total is not None:
        diff = abs(spotify_total - soulseek_total)
        if diff <= 1:
            album_bonus = 0.05
        else:
            album_bonus = -0.02 * min(diff, 10)
    result = (title_score * 0.6) + (artist_score * 0.25) + (bitrate_score * 0.15)
    adjusted = result + album_bonus
    return max(0.0, min(1.0, round(adjusted, 4)))


def _ensure_iterable(obj: Any) -> Iterable[Any]:
    if obj is None:
        return ()
    if isinstance(obj, (list, tuple)):
        return obj
    return (obj,)


def compute_relevance_score(query: str, candidate: Mapping[str, Any]) -> float:
    """Return a lightweight similarity score for arbitrary music items."""

    normalised_query = _normalize_text(query)
    if not normalised_query:
        return 0.0
    title = _normalize_text(str(candidate.get("title", "")))
    album = _normalize_text(str(candidate.get("album", "")))
    artist_entries = _ensure_iterable(candidate.get("artists"))
    artists = [
        _normalize_text(str(entry)) for entry in artist_entries if _normalize_text(str(entry))
    ]
    title_score = _ratio(normalised_query, title)
    album_score = _ratio(normalised_query, album)
    artist_score = max((_ratio(normalised_query, artist) for artist in artists), default=0.0)
    composite_terms = " ".join(filter(None, [title, album, " ".join(artists)]))
    composite_score = _ratio(normalised_query, composite_terms)
    type_hint = str(candidate.get("type") or "").lower()
    if type_hint == "track":
        weights = (0.55, 0.25, 0.15, 0.05)
    elif type_hint == "album":
        weights = (0.35, 0.15, 0.4, 0.1)
    elif type_hint == "artist":
        weights = (0.2, 0.6, 0.1, 0.1)
    else:
        weights = (0.4, 0.3, 0.2, 0.1)
    score = (
        (title_score * weights[0])
        + (artist_score * weights[1])
        + (album_score * weights[2])
        + (composite_score * weights[3])
    )
    if title and title == normalised_query:
        score += 0.05
    elif album and album == normalised_query:
        score += 0.03
    return max(0.0, min(1.0, round(score, 4)))


class MusicMatchingEngine:
    """Wrapper exposing the pure matching utilities with injected configuration."""

    def __init__(self, *, config: MatchingConfig | None = None) -> None:
        self._config = config or load_matching_config()

    @property
    def config(self) -> MatchingConfig:
        return self._config

    def rank_candidates(self, query: str, candidates: Sequence[Any]) -> list[MatchResult]:
        return rank_candidates(
            query,
            candidates,
            min_artist_sim=self._config.min_artist_similarity,
            complete_thr=self._config.complete_threshold,
            nearly_thr=self._config.nearly_threshold,
            fuzzy_max=self._config.fuzzy_max_candidates,
            edition_aware=self._config.edition_aware,
        )

    def calculate_album_completion(
        self,
        matched_tracks: Iterable[Any],
        *,
        expected_total_tracks: int | None = None,
    ) -> tuple[float, str]:
        return calculate_album_completion(
            matched_tracks,
            expected_total_tracks=expected_total_tracks,
            complete_thr=self._config.complete_threshold,
            nearly_thr=self._config.nearly_threshold,
        )

    @staticmethod
    def compute_relevance_score(query: str, candidate: Mapping[str, Any]) -> float:
        return compute_relevance_score(query, candidate)

    @staticmethod
    def calculate_slskd_match_confidence(spotify_track: Any, soulseek_entry: Any) -> float:
        return calculate_slskd_match_confidence(spotify_track, soulseek_entry)


__all__ = [
    "MusicMatchingEngine",
    "calculate_album_completion",
    "calculate_slskd_match_confidence",
    "compute_relevance_score",
    "rank_candidates",
]
