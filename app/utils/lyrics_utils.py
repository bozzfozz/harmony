"""Utility helpers for fetching and storing synchronised lyrics."""

from __future__ import annotations

import base64
import os
import re
import zlib
from pathlib import Path
from typing import (Any, Dict, Iterable, List, Mapping, Optional, Sequence,
                    Tuple)

import httpx

from app.logging import get_logger

logger = get_logger(__name__)

# ``fetch_spotify_lyrics`` mirrors the behaviour of ``metadata_utils`` by relying
# on a runtime injected Spotify client.  Workers assign the configured client to
# this module level attribute which keeps the helpers easily mockable in tests.
SPOTIFY_CLIENT: Any | None = None

MUSIXMATCH_ENDPOINT = "https://api.musixmatch.com/ws/1.1/matcher.subtitle.get"


def fetch_spotify_lyrics(track_id: str) -> Optional[Dict[str, Any]]:
    """Return lyric information for a Spotify track if available."""

    if not track_id:
        return None

    client = SPOTIFY_CLIENT
    if client is None:
        logger.debug("Spotify lyrics requested for %s but no client configured", track_id)
        return None

    try:
        payload = client.get_track_details(track_id)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.debug("Spotify lyric lookup failed for %s: %s", track_id, exc)
        return None

    if not isinstance(payload, Mapping):
        return None

    lyrics_payload: Dict[str, Any] = {}
    metadata = _extract_track_metadata(payload)
    if metadata:
        lyrics_payload.update(metadata)

    sync_lines = _extract_sync_lyrics(payload)
    if sync_lines:
        lyrics_payload["sync_lyrics"] = sync_lines

    plain_lyrics = _extract_plain_lyrics(payload)
    if plain_lyrics:
        lyrics_payload["lyrics"] = plain_lyrics

    if "sync_lyrics" not in lyrics_payload and "lyrics" not in lyrics_payload:
        return None

    return lyrics_payload


def convert_to_lrc(lyrics_data: Dict[str, Any]) -> str:
    """Convert lyric metadata into an LRC formatted string."""

    if not isinstance(lyrics_data, Mapping):
        raise ValueError("Lyrics payload must be a mapping")

    info = dict(lyrics_data)
    title = _resolve_field(info, ("title", "name", "track"), default="Unknown Title")
    artist = _resolve_field(info, ("artist", "artist_name", "artists"), default="Unknown Artist")
    album = _resolve_field(info, ("album", "album_name", "release"), default="")
    duration = _resolve_duration(info)

    sync_lines = _normalise_sync_lines(info.get("sync_lyrics"))
    if not sync_lines:
        sync_lines = _normalise_sync_lines(info.get("lines"))

    header = [f"[ti:{title}]", f"[ar:{artist}]"]
    if album:
        header.append(f"[al:{album}]")

    if sync_lines:
        lrc_lines = list(header)
        for timestamp, line in sync_lines:
            lrc_lines.append(f"{_format_timestamp(timestamp)}{line}")
        return "\n".join(lrc_lines)

    lyrics = _coerce_text(info.get("lyrics"))
    if not lyrics:
        raise ValueError("Lyrics payload is empty")

    lines = [line for line in _normalise_plain_lines(lyrics)]
    if not lines:
        raise ValueError("Lyrics payload did not contain any usable lines")

    spacing = _calculate_spacing(duration, len(lines))

    lrc_lines = list(header)
    for index, line in enumerate(lines):
        lrc_lines.append(f"{_format_timestamp(index * spacing)}{line}")
    return "\n".join(lrc_lines)


def save_lrc_file(path: Path, lrc: str) -> None:
    """Persist the generated LRC content to disk."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(lrc, encoding="utf-8")


async def fetch_musixmatch_subtitles(track_info: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Attempt to retrieve synchronised lyrics from the Musixmatch API."""

    api_key = os.getenv("MUSIXMATCH_API_KEY")
    if not api_key:
        return None

    artist = _coerce_text(_resolve_field(track_info, ("artist", "artist_name", "artists")))
    title = _coerce_text(_resolve_field(track_info, ("title", "name", "track")))
    if not artist or not title:
        return None

    params = {"format": "json", "q_artist": artist, "q_track": title, "apikey": api_key}
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(MUSIXMATCH_ENDPOINT, params=params)
        except httpx.HTTPError as exc:  # pragma: no cover - network errors in tests are mocked
            logger.debug("Musixmatch lookup failed for %s - %s: %s", artist, title, exc)
            return None

    if response.status_code != 200:
        logger.debug(
            "Musixmatch returned status %s for %s - %s",
            response.status_code,
            artist,
            title,
        )
        return None

    try:
        payload = response.json()
    except ValueError:  # pragma: no cover - invalid payload
        logger.debug("Musixmatch response was not valid JSON for %s - %s", artist, title)
        return None

    subtitle = payload.get("message", {}).get("body", {}).get("subtitle")
    if not isinstance(subtitle, Mapping):
        return None

    encoded = subtitle.get("subtitle_body")
    if not isinstance(encoded, str) or not encoded:
        return None

    try:
        raw = base64.b64decode(encoded)
        decoded = zlib.decompress(raw, 15 + 32).decode("utf-8")
    except Exception:  # pragma: no cover - defensive decoding
        return None

    sync_lines = _normalise_sync_lines(decoded)
    if not sync_lines:
        return None

    return {
        "title": title,
        "artist": artist,
        "album": _coerce_text(track_info.get("album")),
        "sync_lyrics": sync_lines,
    }


def _extract_track_metadata(payload: Mapping[str, Any]) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {}
    metadata["title"] = _coerce_text(
        payload.get("name") or payload.get("title") or payload.get("track")
    )
    artist = ""
    artists = payload.get("artists")
    if isinstance(artists, list) and artists:
        first = artists[0]
        if isinstance(first, Mapping):
            artist = _coerce_text(first.get("name"))
        else:
            artist = _coerce_text(first)
    metadata["artist"] = artist or _coerce_text(payload.get("artist"))
    album_payload = payload.get("album")
    if isinstance(album_payload, Mapping):
        metadata["album"] = _coerce_text(album_payload.get("name"))
    metadata["duration"] = (
        payload.get("duration_ms") or payload.get("duration") or payload.get("length")
    )
    return {key: value for key, value in metadata.items() if value}


def _extract_plain_lyrics(payload: Mapping[str, Any]) -> str:
    for key in ("lyrics", "plain_lyrics", "text"):  # common naming patterns
        value = payload.get(key)
        if isinstance(value, Mapping):
            text = value.get("text") or value.get("lyrics")
            if isinstance(text, str) and text.strip():
                return text.strip()
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_sync_lyrics(payload: Mapping[str, Any]) -> List[Tuple[float, str]]:
    for key in ("sync_lyrics", "syncLyrics", "synchronised_lyrics", "synchronizedLyrics"):
        value = payload.get(key)
        lines = _normalise_sync_lines(value)
        if lines:
            return lines
    return []


def _resolve_field(
    data: Mapping[str, Any] | None, candidates: Sequence[str], *, default: str = ""
) -> str:
    if not isinstance(data, Mapping):
        return default
    for key in candidates:
        value = data.get(key)
        if isinstance(value, Mapping):
            nested = value.get("name")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, Mapping):
                nested = first.get("name")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
            elif isinstance(first, str) and first.strip():
                return first.strip()
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


def _coerce_text(value: Any, fallback: str = "") -> str:
    if isinstance(value, str):
        text = value.strip()
        return text or fallback
    if isinstance(value, (int, float)):
        return str(value)
    return fallback


def _normalise_plain_lines(lyrics: str) -> Iterable[str]:
    for line in lyrics.splitlines():
        cleaned = line.strip()
        if cleaned:
            yield cleaned


def _normalise_sync_lines(data: Any) -> List[Tuple[float, str]]:
    if isinstance(data, str):
        return _parse_lrc_payload(data)

    entries: List[Tuple[float, str]] = []
    if isinstance(data, Mapping):
        sequence = data.get("lines")
    else:
        sequence = data

    if isinstance(sequence, Sequence):
        for item in sequence:
            timestamp: Optional[float] = None
            text = ""
            if isinstance(item, Mapping):
                text = _coerce_text(item.get("text") or item.get("line") or item.get("lyrics"))
                timestamp = _coerce_timestamp(
                    item.get("time")
                    or item.get("timestamp")
                    or item.get("start")
                    or item.get("offset")
                )
            elif isinstance(item, Sequence) and len(item) >= 2:
                timestamp = _coerce_timestamp(item[0])
                text = _coerce_text(item[1])
            if text and timestamp is not None:
                entries.append((timestamp, text))
    entries.sort(key=lambda item: item[0])
    return entries


def _parse_lrc_payload(lrc: str) -> List[Tuple[float, str]]:
    pattern = re.compile(r"\[(\d{1,2}):(\d{2})(?:\.(\d{1,2}))?\](.*)")
    lines: List[Tuple[float, str]] = []
    for raw_line in lrc.splitlines():
        match = pattern.match(raw_line.strip())
        if not match:
            continue
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        centiseconds = int(match.group(3) or 0)
        text = match.group(4).strip()
        timestamp = minutes * 60 + seconds + centiseconds / 100
        if text:
            lines.append((timestamp, text))
    return lines


def _coerce_timestamp(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 1000:  # treat as milliseconds
            seconds /= 1000.0
        if seconds >= 0:
            return seconds
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        match = re.match(r"^(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?$", value)
        if match:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            fraction = match.group(3)
            centiseconds = int(fraction) / (10 ** len(fraction)) if fraction else 0
            return minutes * 60 + seconds + centiseconds
        try:
            seconds = float(value)
        except ValueError:
            return None
        if seconds > 1000:
            seconds /= 1000.0
        if seconds >= 0:
            return seconds
    return None


def _format_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes = int(seconds // 60)
    remainder = seconds - minutes * 60
    return f"[{minutes:02d}:{remainder:05.2f}]"


def _calculate_spacing(duration: float, line_count: int) -> float:
    if duration <= 0 or line_count <= 0:
        return 5.0
    return max(duration / line_count, 0.5)


def _resolve_duration(info: Mapping[str, Any]) -> float:
    for key in ("duration", "duration_ms", "durationMs", "length"):
        value = info.get(key)
        if value is None:
            continue
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            continue
        if key.endswith("ms") or key.endswith("Ms"):
            seconds /= 1000.0
        if seconds > 0:
            return seconds
    return 0.0


__all__ = [
    "SPOTIFY_CLIENT",
    "fetch_spotify_lyrics",
    "convert_to_lrc",
    "save_lrc_file",
    "fetch_musixmatch_subtitles",
]
