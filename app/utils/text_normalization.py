"""Utilities for normalising music metadata and generating title variants."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Iterable

try:  # pragma: no cover - optional dependency
    from unidecode import unidecode
except ImportError:  # pragma: no cover - fallback path
    unidecode = None  # type: ignore[assignment]


ARTIST_ALIASES: dict[str, set[str]] = {
    "beyonce": {"beyonce", "beyoncé"},
    "korn": {"korn", "koЯn", "koRn"},
    "avicii": {"avicii", "tim berg"},
    "sigur ros": {"sigur ros", "sigur rós", 'sigur r"os'},
}
"""Normalised artist aliases keyed by their simplified form."""


_QUOTES_TRANSLATION = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "«": '"',
        "»": '"',
        "‹": '"',
        "›": '"',
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "′": "'",
        "‵": "'",
    }
)

_EDITION_KEYWORDS = {
    "anniversary",
    "collector",
    "deluxe",
    "expanded",
    "live",
    "remaster",
    "remastered",
    "remasterd",
    "special",
    "super",
    "ultimate",
}

_EDITION_REGEX = re.compile(
    r"\b(" + "|".join(sorted(_EDITION_KEYWORDS)) + r")\b",
    flags=re.IGNORECASE,
)

_FEAT_PATTERN = re.compile(
    r"\s*(?:[\[(]\s*(?:feat\.?|featuring|ft\.?|with)[^\]\)]*[\])]|[-–—]\s*(?:feat\.?|featuring|ft\.?|with)\s.+$)",
    flags=re.IGNORECASE,
)

_EXPLICIT_PATTERN = re.compile(r"\b(?:explicit|clean)\b", re.IGNORECASE)

_PAREN_TO_DASH = re.compile(r"\(([^)]+)\)")
_DASH_TO_PAREN = re.compile(r"\s+-\s+([^-(]+)")


def normalize_quotes(value: str) -> str:
    """Return the provided string with smart quotes converted to ASCII ones."""

    if not value:
        return ""
    return value.translate(_QUOTES_TRANSLATION)


def _strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("ascii", "ignore").decode("ascii")


def normalize_unicode(value: str) -> str:
    """Return a lowercase ASCII representation of the supplied value."""

    if not value:
        return ""

    normalised = unicodedata.normalize("NFKC", value)
    normalised = normalize_quotes(normalised)
    if unidecode is not None:
        normalised = unidecode(normalised)
    else:  # pragma: no cover - executed only when unidecode is absent
        normalised = _strip_accents(normalised)
    normalised = normalised.replace("ß", "ss")
    return normalised.lower().strip()


def _compact_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def clean_track_title(title: str) -> str:
    """Remove common noise from track titles without touching remix markers."""

    if not title:
        return ""

    working = normalize_quotes(title)
    working = _FEAT_PATTERN.sub("", working)
    working = _EXPLICIT_PATTERN.sub("", working)
    working = re.sub(
        r"\s*[-–—]\s*(?:explicit|clean)\b", "", working, flags=re.IGNORECASE
    )
    working = re.sub(r"\s*\(explicit\)|\s*\(clean\)", "", working, flags=re.IGNORECASE)
    working = re.sub(r"\s{2,}", " ", working)
    return working.strip(" -")


def clean_album_title(title: str) -> str:
    """Remove edition noise (deluxe/remaster/anniversary) from album titles."""

    if not title:
        return ""
    working = normalize_quotes(title)
    extended_keywords = set(_EDITION_KEYWORDS)
    extended_keywords.add("edition")
    keyword_pattern = "|".join(sorted(extended_keywords))
    bracket_regex = re.compile(
        rf"\s*[\[(][^)\]]*(?:{keyword_pattern})[^)\]]*[\])]",
        flags=re.IGNORECASE,
    )
    dash_regex = re.compile(
        rf"\s*[-–—]\s*(?:{keyword_pattern})(?:\s+edition|\s+version|\s+remaster(?:ed)?)?",
        flags=re.IGNORECASE,
    )
    word_regex = re.compile(rf"\b(?:{keyword_pattern})\b", flags=re.IGNORECASE)

    working = bracket_regex.sub("", working)
    working = dash_regex.sub("", working)
    working = word_regex.sub("", working)
    working = re.sub(r"\s{2,}", " ", working)
    return working.strip(" -")


def _swap_parentheses_and_dash(value: str) -> list[str]:
    variants: list[str] = []
    if "(" in value and ")" in value:
        variants.append(_PAREN_TO_DASH.sub(lambda match: f" - {match.group(1)}", value))
    if " - " in value:
        variants.append(
            _DASH_TO_PAREN.sub(lambda match: f" ({match.group(1).strip()})", value)
        )
    return [
        _compact_whitespace(candidate)
        for candidate in variants
        if candidate and candidate != value
    ]


def _deduplicate(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value:
            continue
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _extend_with_normalised(variants: Iterable[str]) -> list[str]:
    result: list[str] = []
    for variant in variants:
        result.append(variant)
        normalised = normalize_unicode(variant)
        if normalised and normalised not in result:
            result.append(normalised)
    return result


def generate_track_variants(title: str) -> list[str]:
    """Generate conservative title variants for track matching."""

    if not title:
        return []

    base = _compact_whitespace(title)
    variants: list[str] = [base]

    cleaned = clean_track_title(base)
    if cleaned and cleaned != base:
        variants.append(cleaned)

    variants.extend(_swap_parentheses_and_dash(base))
    if cleaned:
        variants.extend(_swap_parentheses_and_dash(cleaned))

    return _deduplicate(_extend_with_normalised(variants))


def generate_album_variants(title: str) -> list[str]:
    """Generate conservative album title variants aware of editions."""

    if not title:
        return []

    base = _compact_whitespace(title)
    variants: list[str] = [base]

    cleaned = clean_album_title(base)
    if cleaned and cleaned != base:
        variants.append(cleaned)

    variants.extend(_swap_parentheses_and_dash(base))
    if cleaned:
        variants.extend(_swap_parentheses_and_dash(cleaned))

    return _deduplicate(_extend_with_normalised(variants))


@lru_cache(maxsize=128)
def normalise_artist(value: str) -> str:
    return normalize_unicode(value)


def expand_artist_aliases(artist: str) -> set[str]:
    """Return a set of potential aliases for the provided artist name."""

    if not artist:
        return {""}

    base = normalise_artist(artist)
    aliases: set[str] = {base}
    for candidates in ARTIST_ALIASES.values():
        lower_candidates = {normalize_unicode(entry) for entry in candidates}
        if base in lower_candidates:
            aliases.update(lower_candidates)
    return aliases


def extract_editions(title: str) -> set[str]:
    """Return edition keywords present in the supplied album title."""

    normalised = normalize_unicode(title)
    return {match.lower() for match in _EDITION_REGEX.findall(normalised)}
