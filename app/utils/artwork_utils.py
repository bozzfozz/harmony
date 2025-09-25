"""Utility helpers for downloading and embedding artwork files."""
from __future__ import annotations

import mimetypes
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx

from app.logging import get_logger

logger = get_logger(__name__)

SPOTIFY_CLIENT: Any | None = None


def _guess_extension(url: str, content_type: str | None) -> str:
    """Guess a sensible file extension for an artwork file."""

    if content_type:
        guessed = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if guessed:
            return guessed

    suffix = Path(url).suffix
    if suffix:
        return suffix

    return ".jpg"


def fetch_spotify_artwork(album_id: str) -> Optional[str]:
    """Return the highest resolution Spotify artwork URL for an album."""

    if not album_id:
        return None

    client = SPOTIFY_CLIENT
    if client is None:
        logger.debug("Spotify artwork requested for %s but no client configured", album_id)
        return None

    try:
        album_payload = client.get_album_details(album_id)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.debug("Spotify album lookup failed for %s: %s", album_id, exc)
        return None

    if not isinstance(album_payload, dict):
        return None

    images = album_payload.get("images")
    if not isinstance(images, list):
        return None

    best_url: Optional[str] = None
    best_score = -1
    for entry in images:
        if not isinstance(entry, dict):
            continue
        url = entry.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        width = int(entry.get("width") or 0)
        height = int(entry.get("height") or 0)
        score = width * height
        if score > best_score:
            best_score = score
            best_url = url.strip()

    return best_url


def _resolve_destination(path: Path, suffix: str) -> Path:
    if path.suffix:
        return path
    if path.exists() and path.is_dir():
        filename = f"{uuid.uuid4().hex}{suffix}"
        return path / filename
    return path.with_suffix(suffix)


def download_artwork(url: str, path: Path) -> Path:
    """Download artwork to the desired location and return the stored path."""

    if not url:
        raise ValueError("Artwork URL must be provided")

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as exc:  # pragma: no cover - network failure
        logger.debug("Failed to download artwork from %s: %s", url, exc)
        raise

    suffix = _guess_extension(url, response.headers.get("content-type"))
    destination = _resolve_destination(Path(path), suffix)
    destination.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(prefix="harmony-artwork-", suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(response.content)
        if destination.exists():
            destination.unlink()
        os.replace(temp_path, destination)
    except Exception:
        os.unlink(temp_path)
        raise

    return destination


def embed_artwork(audio_file: Path, artwork_file: Path) -> None:
    """Embed the supplied artwork image into the audio file using mutagen."""

    audio_path = Path(audio_file)
    image_path = Path(artwork_file)

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    if not image_path.exists():
        raise FileNotFoundError(f"Artwork file not found: {image_path}")

    try:  # pragma: no cover - import guarded for optional dependency
        from mutagen.flac import FLAC, Picture
        from mutagen.id3 import APIC, ID3, ID3NoHeaderError
        from mutagen.mp4 import MP4, MP4Cover
    except ImportError as exc:  # pragma: no cover - defensive logging
        raise RuntimeError("mutagen is required to embed artwork") from exc

    suffix = audio_path.suffix.lower()
    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    image_data = image_path.read_bytes()

    if suffix in {".mp3", ".wav", ".aiff", ".aif"}:
        try:
            tags = ID3(audio_path)
        except ID3NoHeaderError:
            tags = ID3()
        tags.delall("APIC")
        tags.add(
            APIC(
                encoding=3,
                mime=mime_type,
                type=3,
                desc="Cover",
                data=image_data,
            )
        )
        tags.save(audio_path)
        return

    if suffix == ".flac":
        audio = FLAC(audio_path)
        picture = Picture()
        picture.type = 3
        picture.mime = mime_type
        picture.desc = "Cover"
        picture.data = image_data
        audio.clear_pictures()
        audio.add_picture(picture)
        audio.save()
        return

    if suffix in {".m4a", ".mp4", ".aac", ".m4b"}:
        cover_format = MP4Cover.FORMAT_PNG if mime_type == "image/png" else MP4Cover.FORMAT_JPEG
        mp4 = MP4(audio_path)
        mp4.tags["covr"] = [MP4Cover(image_data, imageformat=cover_format)]
        mp4.save()
        return

    # Fall back to ID3 if mutagen supports the format; this covers formats
    # such as WMA that share the same tagging structure.
    try:
        tags = ID3(audio_path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.delall("APIC")
    tags.add(
        APIC(
            encoding=3,
            mime=mime_type,
            type=3,
            desc="Cover",
            data=image_data,
        )
    )
    tags.save(audio_path)

