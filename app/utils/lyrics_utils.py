"""Helpers for working with LRC lyric files."""
from __future__ import annotations

from typing import Dict, Iterable


def _coerce_text(value: object, fallback: str = "") -> str:
    if isinstance(value, str):
        text = value.strip()
        return text or fallback
    if isinstance(value, (int, float)):
        return str(value).strip()
    return fallback


def _resolve_field(track_info: Dict[str, object], *candidates: str, default: str = "") -> str:
    for key in candidates:
        value = track_info.get(key)
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, dict):
                text = _coerce_text(first.get("name"), fallback="")
                if text:
                    return text
            return _coerce_text(value[0], fallback="")
        if isinstance(value, dict):
            text = _coerce_text(value.get("name"), fallback="")
            if text:
                return text
        text = _coerce_text(value)
        if text:
            return text
    return default


def _seconds_from_track_info(track_info: Dict[str, object]) -> float:
    for key in ("duration", "duration_ms", "length", "durationMs", "total_time"):
        value = track_info.get(key)
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


def _format_timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    minutes = int(seconds // 60)
    remainder = seconds - minutes * 60
    return f"[{minutes:02d}:{remainder:05.2f}]"


def _normalise_lines(lyrics: str) -> Iterable[str]:
    for raw_line in lyrics.splitlines():
        line = raw_line.strip()
        if line:
            yield line


def generate_lrc(track_info: Dict[str, object], lyrics: str) -> str:
    """Convert raw lyrics into a simple LRC formatted string."""

    if not lyrics:
        raise ValueError("Lyrics payload is empty")

    info = dict(track_info or {})
    title = _resolve_field(info, "title", "name", "track", "filename", default="Unknown Title")
    artist = _resolve_field(info, "artist", "artist_name", "artists", "author", default="Unknown Artist")
    album = _resolve_field(info, "album", "album_name", "release", default="")

    lines = list(_normalise_lines(lyrics))
    if not lines:
        raise ValueError("Lyrics payload did not contain any usable lines")

    total_duration = _seconds_from_track_info(info)
    if total_duration <= 0:
        spacing = 5.0
    else:
        spacing = max(total_duration / max(len(lines), 1), 0.5)

    header = [
        f"[ti:{title}]",
        f"[ar:{artist}]",
    ]
    if album:
        header.append(f"[al:{album}]")

    lrc_lines = list(header)
    for index, line in enumerate(lines):
        timestamp = _format_timestamp(index * spacing)
        lrc_lines.append(f"{timestamp}{line}")

    return "\n".join(lrc_lines)

