"""Utility helpers for normalising search data and computing scores."""

from __future__ import annotations

from typing import Iterable, Optional, Sequence
import unicodedata


def normalize_text(value: str | None) -> str:
    """Return a lowercase, accent-free representation of *value*."""

    if not value:
        return ""
    text = unicodedata.normalize("NFKD", value)
    without_accents = "".join(char for char in text if not unicodedata.combining(char))
    return without_accents.casefold().strip()


def normalize_genres(genres: Iterable[str | None]) -> list[str]:
    """Return a list of unique, trimmed genres preserving input order."""

    result: list[str] = []
    seen: set[str] = set()
    for genre in genres:
        if not genre:
            continue
        cleaned = str(genre).strip()
        if not cleaned:
            continue
        if cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def clamp_score(value: float) -> float:
    """Clamp *value* to the inclusive range [0.0, 1.0]."""

    return max(0.0, min(1.0, value))


def boost_for_format(audio_format: Optional[str]) -> float:
    """Return the score boost associated with *audio_format*."""

    if not audio_format:
        return 0.0
    upper = audio_format.upper()
    if upper == "FLAC":
        return 0.15
    if upper == "ALAC":
        return 0.12
    if upper in {"AAC", "OGG"}:
        return 0.03
    return 0.0


def boost_for_bitrate(bitrate: Optional[int]) -> float:
    """Return the score boost derived from the given *bitrate*."""

    if bitrate is None:
        return 0.0
    if bitrate >= 1000:
        return 0.1
    if bitrate >= 320:
        return 0.05
    if bitrate >= 256:
        return 0.02
    return 0.0


def year_distance_bonus(
    year: Optional[int], year_from: Optional[int], year_to: Optional[int]
) -> float:
    """Return a small bonus when *year* falls into the requested interval."""

    if year is None:
        return 0.0
    if year_from is not None and year < year_from:
        return 0.0
    if year_to is not None and year > year_to:
        return 0.0
    return 0.05 if year_from is not None or year_to is not None else 0.0


def format_priority_index(audio_format: Optional[str], priority: Sequence[str]) -> int:
    """Return the stable index for *audio_format* based on *priority* order."""

    if not priority:
        return 0
    if not audio_format:
        return len(priority)
    upper = audio_format.upper()
    for index, value in enumerate(priority):
        if upper == value:
            return index
    return len(priority)


def bitrate_penalty(bitrate: Optional[int]) -> float:
    """Return a small penalty for missing or very low bitrate."""

    if bitrate is None:
        return 0.02
    if bitrate < 192:
        return 0.05
    return 0.0


def score_weighted_sum(values: Sequence[float]) -> float:
    """Return the sum of score contributions rounded to four decimals."""

    return round(sum(values), 4)


def harmonic_mean(values: Sequence[float]) -> float:
    """Return the harmonic mean of *values* (ignoring zero entries)."""

    filtered = [value for value in values if value > 0]
    if not filtered:
        return 0.0
    denominator = sum(1 / value for value in filtered)
    if denominator == 0:
        return 0.0
    return len(filtered) / denominator
