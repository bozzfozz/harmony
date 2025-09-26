"""Utilities for organising downloaded audio files."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Optional

from app.models import Download

_INVALID_CHARS = re.compile(r"[^A-Za-z0-9 _.-]")
_MULTI_SEP = re.compile(r"[\s._-]+")
_ALBUM_PATTERN = re.compile(r"^(?P<artist>.+?)\s*-\s*(?P<album>.+?)\s*-\s*(?P<rest>.+)$")


def sanitize_name(name: str) -> str:
    """Return a filesystem-friendly representation of *name*."""

    normalised = unicodedata.normalize("NFKD", name or "")
    # Remove accents by encoding to ASCII and dropping unconvertible characters.
    ascii_text = normalised.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.replace("/", "").replace("\\", "")
    cleaned = _INVALID_CHARS.sub("_", ascii_text)
    cleaned = _MULTI_SEP.sub(" ", cleaned)
    cleaned = cleaned.strip().strip(".-")
    return cleaned or "Unknown"


def guess_album_from_filename(filename: str) -> Optional[str]:
    """Attempt to infer an album name from a raw *filename*."""

    stem = Path(filename).stem
    match = _ALBUM_PATTERN.match(stem)
    if match:
        raw_album = match.group("album")
        album = raw_album.strip()
        if not album or album.startswith("-"):
            return "<Unknown Album>"
        return album

    parts = [part.strip() for part in re.split(r"\s*-\s*", stem) if part.strip()]
    if len(parts) >= 3:
        album_candidate = parts[1]
        if album_candidate.startswith("-"):
            return "<Unknown Album>"
        return album_candidate or "<Unknown Album>"

    return None


def _normalise_value(value: Any) -> Optional[str]:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, (int, float)):
        text = str(value).strip()
        return text or None
    if isinstance(value, Mapping):
        for key in ("name", "title", "value"):
            nested = _normalise_value(value.get(key))
            if nested:
                return nested
    if isinstance(value, (list, tuple)):
        for item in value:
            nested = _normalise_value(item)
            if nested:
                return nested
    return None


def _collect_metadata(download: Download) -> Mapping[str, str]:
    result: dict[str, str] = {}
    payload = download.request_payload
    if isinstance(payload, Mapping):
        _merge_metadata(result, payload)
        nested = payload.get("metadata")
        if isinstance(nested, Mapping):
            _merge_metadata(result, nested)
    return result


def _merge_metadata(target: MutableMapping[str, str], source: Mapping[str, Any]) -> None:
    for key, value in source.items():
        text = _normalise_value(value)
        if not text:
            continue
        target.setdefault(key.lower(), text)


def _first_text(metadata: Mapping[str, str], *keys: str) -> Optional[str]:
    for key in keys:
        value = metadata.get(key.lower())
        if value:
            return value
    return None


def _parse_track_number(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        match = re.search(r"\d+", value)
        if match:
            try:
                return int(match.group())
            except ValueError:
                return None
    return None


def organize_file(download: Download, base_dir: Path) -> Path:
    """Move *download* into a normalised directory structure under *base_dir*."""

    source_path = Path(download.filename)
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    metadata = dict(_collect_metadata(download))
    artist = _first_text(metadata, "artist", "artist_name", "artists") or "Unknown Artist"
    album = (
        _first_text(metadata, "album", "album_name", "release")
        or guess_album_from_filename(source_path.name)
        or "<Unknown Album>"
    )
    title = _first_text(metadata, "title", "track", "name") or source_path.stem or "Track"
    disc_number = _parse_track_number(_first_text(metadata, "disc_number", "discnumber", "disc"))

    track_number = _parse_track_number(
        _first_text(
            metadata,
            "track_number",
            "tracknumber",
            "track_no",
            "track",
            "number",
            "position",
            "index",
        )
    )
    if track_number is None:
        track_number = _parse_track_number(source_path.stem)

    artist_dir = sanitize_name(artist)
    album_dir = sanitize_name(album)
    title_part = sanitize_name(title)
    if disc_number is not None and disc_number > 0:
        album_dir = f"{album_dir} (Disc {disc_number})"

    destination_dir = Path(base_dir) / artist_dir / album_dir
    destination_dir.mkdir(parents=True, exist_ok=True)

    if track_number is not None and track_number < 1000:
        track_prefix = f"{track_number:02d}"
    elif track_number is not None:
        track_prefix = str(track_number)
    else:
        track_prefix = ""

    if track_prefix:
        filename_stem = f"{track_prefix} - {title_part}"
    else:
        filename_stem = title_part

    extension = source_path.suffix
    destination = destination_dir / f"{filename_stem}{extension}"

    suffix = 1
    while destination.exists():
        destination = destination_dir / f"{filename_stem}_{suffix}{extension}"
        suffix += 1

    temp_name = f".{destination.name}.tmp"
    temp_path = destination.with_name(temp_name)
    counter = 0
    while temp_path.exists():
        counter += 1
        temp_path = destination.with_name(f".{destination.stem}.tmp{counter}{extension}")

    moved = source_path.replace(temp_path)
    try:
        final_path = moved.replace(destination)
    except Exception:
        moved.replace(source_path)
        raise

    download.filename = str(final_path)
    download.organized_path = str(final_path)
    return final_path
