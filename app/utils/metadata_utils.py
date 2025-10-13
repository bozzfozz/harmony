"""Helpers for extracting and writing rich audio metadata."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

try:  # Python 3.11+: ``asyncio`` is only required when optional metadata
    # extraction helpers receive coroutine results. Import lazily to keep
    # running in synchronous contexts.
    import asyncio
except Exception:  # pragma: no cover - fallback when asyncio is unavailable
    asyncio = None  # type: ignore[assignment]

from app.logging import get_logger

logger = get_logger(__name__)

try:  # pragma: no cover - optional dependency in tests
    import mutagen
except ImportError:  # pragma: no cover - fallback when mutagen is unavailable
    mutagen = None  # type: ignore[assignment]

# ``extract_spotify_metadata`` relies on a configured Spotify client. The worker
# populates this attribute at runtime which keeps the function easily mockable
# during tests.
SPOTIFY_CLIENT: Any | None = None

# Mapping between Harmony metadata keys and the tag identifiers that mutagen
# understands. The keys intentionally mirror the columns on the ``downloads``
# table so persistence stays consistent across the application.
TAG_FIELDS = {
    "genre": "genre",
    "composer": "composer",
    "producer": "producer",
    "isrc": "isrc",
    "copyright": "copyright",
}


def extract_metadata_from_spotify(track_id: str) -> dict[str, str]:
    """Return rich metadata for the given Spotify track identifier.

    The helper consolidates information from the track payload itself together
    with additional lookups performed through the configured Spotify client. The
    worker injects the client instance via ``SPOTIFY_CLIENT`` and tests can
    monkeypatch this module level variable for isolated scenarios.
    """

    if not track_id:
        return {}

    client = SPOTIFY_CLIENT
    if client is None:
        logger.debug("Spotify metadata requested for %s but no client configured", track_id)
        return {}

    metadata: dict[str, str] = {}

    track_payload: Mapping[str, Any] | None = None
    try:
        track_payload = client.get_track_details(track_id)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.debug("Spotify track lookup failed for %s: %s", track_id, exc)

    if isinstance(track_payload, Mapping):
        _merge_metadata_value(metadata, "genre", _extract_genre(track_payload))
        _merge_metadata_value(
            metadata,
            "composer",
            _extract_person(track_payload, ("composer", "composers")),
        )
        _merge_metadata_value(
            metadata,
            "producer",
            _extract_person(track_payload, ("producer", "producers")),
        )

        external_ids = track_payload.get("external_ids")
        if isinstance(external_ids, Mapping):
            isrc = external_ids.get("isrc")
            if isinstance(isrc, str) and isrc.strip():
                metadata["isrc"] = isrc.strip()

        album_payload = track_payload.get("album")
        if isinstance(album_payload, Mapping):
            _merge_metadata_value(metadata, "genre", _extract_genre(album_payload))
            _merge_metadata_value(
                metadata,
                "copyright",
                _extract_copyright(album_payload.get("copyrights")),
            )
            artwork_url = _pick_best_image(album_payload.get("images"))
            if artwork_url:
                metadata["artwork_url"] = artwork_url

    # ``SpotifyClient.get_track_metadata`` performs additional album/artist
    # lookups and already normalises the values we care about. We merge the
    # results here so existing behaviour is preserved whilst ensuring Spotify is
    # still the primary source for the data.
    try:
        supplemental = client.get_track_metadata(track_id)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.debug("Supplemental Spotify metadata lookup failed for %s: %s", track_id, exc)
    else:
        for key, value in supplemental.items():
            if key not in TAG_FIELDS and key != "artwork_url":
                continue
            if isinstance(value, str) and value.strip():
                metadata.setdefault(key, value.strip())

    return metadata


def write_metadata_tags(audio_file: Path, metadata: dict[str, Any]) -> None:
    """Persist the provided metadata onto the local audio file."""

    if not metadata:
        return

    path = Path(audio_file)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")

    if mutagen is None:
        logger.debug("Mutagen not available; skipping metadata write for %s", path)
        return

    audio = mutagen.File(path, easy=True)  # type: ignore[attr-defined]
    if audio is None:
        raise ValueError(f"Unsupported audio file format for {path}")

    for key, tag in TAG_FIELDS.items():
        value = metadata.get(key)
        if not value:
            continue
        text = _normalise_text(value)
        if not text:
            continue
        try:
            audio[tag] = [text]
        except Exception:  # pragma: no cover - mutagen specific behaviours
            tags = getattr(audio, "tags", None)
            if tags is None:
                raise
            tags[tag] = [text]
    try:
        audio.save()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.debug("Failed to persist metadata for %s: %s", path, exc)
        raise


def _merge_metadata_value(metadata: dict[str, str], key: str, value: str | None) -> None:
    if value and key not in metadata:
        metadata[key] = value


def _extract_person(payload: Mapping[str, Any], keys: Iterable[str]) -> str | None:
    for key in keys:
        value = payload.get(key)
        text = _normalise_text(value)
        if text:
            return text
    credits = payload.get("credits")
    if isinstance(credits, Mapping):
        for key in keys:
            section = credits.get(key)
            text = _normalise_text(section)
            if text:
                return text
    return None


def _extract_genre(payload: Mapping[str, Any]) -> str | None:
    genres = payload.get("genres")
    if isinstance(genres, list):
        for item in genres:
            text = _normalise_text(item)
            if text:
                return text
    genre = payload.get("genre")
    return _normalise_text(genre)


def _extract_copyright(payload: Any) -> str | None:
    if isinstance(payload, list):
        for entry in payload:
            text = _normalise_text(entry)
            if text:
                return text
    if isinstance(payload, Mapping):
        return _normalise_text(payload.get("text") or payload.get("copyright"))
    return _normalise_text(payload)


def _pick_best_image(images: Any) -> str | None:
    if not isinstance(images, list):
        return None
    best_url: str | None = None
    best_score = -1
    for item in images:
        if not isinstance(item, Mapping):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        width = _coerce_int(item.get("width"))
        height = _coerce_int(item.get("height"))
        score = width * height
        if score > best_score:
            best_score = score
            best_url = url.strip()
    return best_url


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _normalise_text(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, int | float):
        text = str(value).strip()
        return text or None
    if isinstance(value, Mapping):
        for key in ("name", "title", "value", "text"):
            nested = _normalise_text(value.get(key))
            if nested:
                return nested
    if isinstance(value, list):
        for item in value:
            text = _normalise_text(item)
            if text:
                return text
    return None


extract_spotify_metadata = extract_metadata_from_spotify
write_metadata = write_metadata_tags

__all__ = [
    "extract_metadata_from_spotify",
    "write_metadata_tags",
    "extract_spotify_metadata",
    "write_metadata",
    "SPOTIFY_CLIENT",
]
