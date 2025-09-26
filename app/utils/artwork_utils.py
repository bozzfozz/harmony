"""Helper utilities for fetching, caching and embedding album artwork."""

from __future__ import annotations

import mimetypes
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

import httpx

from app.logging import get_logger
from app.models import Download

logger = get_logger(__name__)

SPOTIFY_CLIENT: Any | None = None

DEFAULT_TIMEOUT = 15.0
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024


def fetch_spotify_artwork(album_id: str) -> Optional[str]:
    """Return the best available Spotify artwork URL for ``album_id``."""

    album_id = (album_id or "").strip()
    if not album_id:
        return None

    client = SPOTIFY_CLIENT
    if client is None:
        logger.debug("Spotify client missing when resolving album %s", album_id)
        return None

    try:
        album_payload = client.get_album_details(album_id)
    except Exception as exc:  # pragma: no cover - network errors mocked in tests
        logger.debug("Spotify album lookup failed for %s: %s", album_id, exc)
        return None

    if not isinstance(album_payload, Mapping):
        return None

    return _pick_best_image(album_payload.get("images"))


def download_artwork(
    url: str,
    path: Path,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = MAX_IMAGE_SIZE_BYTES,
) -> Path:
    """Download ``url`` to ``path`` enforcing sane timeouts and file sizes."""

    url = (url or "").strip()
    if not url:
        raise ValueError("Artwork URL must be provided")

    headers = {"User-Agent": "Harmony/1.0"}

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as exc:  # pragma: no cover - dependent on network
        logger.debug("Failed to download artwork from %s: %s", url, exc)
        raise

    content_type = (response.headers.get("content-type") or "").split(";")[0].strip()
    if content_type and not content_type.startswith("image/"):
        logger.debug("Discarding non-image artwork payload from %s (%s)", url, content_type)
        raise ValueError("Downloaded file is not a recognised image")

    length_header = response.headers.get("content-length")
    if length_header:
        try:
            content_length = int(length_header)
        except (TypeError, ValueError):
            content_length = None
        if content_length and content_length > max_bytes:
            raise ValueError("Artwork exceeds maximum allowed size")

    suffix = _guess_extension(url, content_type or None)
    destination = _resolve_destination(Path(path), suffix)
    destination.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(prefix="harmony-artwork-", suffix=suffix)
    written = 0
    try:
        with os.fdopen(fd, "wb") as handle:
            for chunk in response.iter_bytes():
                if not chunk:
                    continue
                written += len(chunk)
                if written > max_bytes:
                    raise ValueError("Artwork exceeds maximum allowed size")
                handle.write(chunk)
        if destination.exists():
            destination.unlink()
        os.replace(temp_path, destination)
    except Exception:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:  # pragma: no cover - best effort cleanup
            pass
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

    try:  # pragma: no cover - dependency import is environment specific
        from mutagen.flac import FLAC, Picture
        from mutagen.mp4 import MP4, MP4Cover
    except ImportError as exc:  # pragma: no cover - defensive logging
        raise RuntimeError("mutagen is required to embed artwork") from exc

    suffix = audio_path.suffix.lower()
    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    image_data = image_path.read_bytes()

    try:
        if suffix in {".mp3", ".wav", ".aiff", ".aif"}:
            _embed_id3_artwork(audio_path, image_data, mime_type)
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

        _embed_id3_artwork(audio_path, image_data, mime_type)
    except Exception as exc:
        logger.error("Failed to embed artwork into %s: %s", audio_path, exc)
        raise


def infer_spotify_album_id(download: Download) -> Optional[str]:
    """Best-effort inference of a Spotify album identifier for a download."""

    if download.spotify_album_id:
        candidate = download.spotify_album_id.strip()
        if candidate:
            return candidate

    payloads: list[Mapping[str, Any]] = []
    if isinstance(download.request_payload, Mapping):
        payloads.append(download.request_payload)
        metadata = download.request_payload.get("metadata")
        if isinstance(metadata, Mapping):
            payloads.append(metadata)

    for payload in payloads:
        album_id = _extract_album_identifier(payload)
        if album_id:
            return album_id

    track_id = (download.spotify_track_id or "").strip()
    if not track_id:
        for payload in payloads:
            track_id = _extract_spotify_track_id(payload) or ""
            if track_id:
                break

    client = SPOTIFY_CLIENT
    if track_id and client is not None:
        try:
            track_payload = client.get_track_details(track_id)
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.debug("Failed to resolve album via track %s: %s", track_id, exc)
        else:
            if isinstance(track_payload, Mapping):
                album = track_payload.get("album")
                if isinstance(album, Mapping):
                    album_id = _extract_album_identifier(album)
                    if album_id:
                        return album_id

    # Heuristic fallback: derive album name from filename and query Spotify.
    client = SPOTIFY_CLIENT
    if client is None:
        return None

    stem = Path(download.filename or "").stem
    if not stem:
        return None

    tokens = [part.strip() for part in re.split(r"[-–]+", stem) if part.strip()]
    queries: Iterable[str]
    if len(tokens) >= 2:
        queries = (f"{tokens[0]} {tokens[1]}", stem)
    else:
        queries = (stem,)

    for query in queries:
        try:
            result = client.search_albums(query, limit=1)
        except Exception as exc:  # pragma: no cover - best effort logging
            logger.debug("Album search failed for %s: %s", query, exc)
            continue
        album_payload = None
        if isinstance(result, Mapping):
            albums = result.get("albums")
            if isinstance(albums, Mapping):
                items = albums.get("items")
                if isinstance(items, list) and items:
                    album_payload = items[0]
        if isinstance(album_payload, Mapping):
            album_id = _extract_album_identifier(album_payload)
            if album_id:
                return album_id

    return None


def _guess_extension(url: str, content_type: str | None) -> str:
    if content_type:
        guessed = mimetypes.guess_extension(content_type)
        if guessed:
            return guessed

    suffix = Path(url).suffix
    if suffix:
        return suffix
    return ".jpg"


def _resolve_destination(path: Path, suffix: str) -> Path:
    if path.suffix:
        return path
    if path.exists() and path.is_dir():
        return path / f"{next(_uuid_sequence())}{suffix}"
    return path.with_suffix(suffix)


def _embed_id3_artwork(audio_path: Path, image_data: bytes, mime_type: str) -> None:
    from mutagen.id3 import APIC, ID3, ID3NoHeaderError  # type: ignore

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


def _pick_best_image(images: Any) -> Optional[str]:
    if not isinstance(images, list):
        return None
    best_url: Optional[str] = None
    best_score = -1
    for entry in images:
        if not isinstance(entry, Mapping):
            continue
        url = (entry.get("url") or "").strip()
        if not url:
            continue
        width = int(entry.get("width") or 0)
        height = int(entry.get("height") or 0)
        score = width * height
        if score > best_score:
            best_score = score
            best_url = url
    return best_url


def _extract_album_identifier(payload: Mapping[str, Any]) -> Optional[str]:
    for key in ("spotify_album_id", "album_id", "id", "spotifyId", "spotify_id"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    images = payload.get("images")
    if isinstance(images, list):
        for image in images:
            if isinstance(image, Mapping):
                candidate = image.get("id")
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
    return None


def _extract_spotify_track_id(payload: Mapping[str, Any]) -> Optional[str]:
    for key in (
        "spotify_track_id",
        "spotify_id",
        "spotifyTrackId",
        "spotifyId",
        "id",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, Mapping):
            nested = value.get("id")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    track_payload = payload.get("track")
    if isinstance(track_payload, Mapping):
        return _extract_spotify_track_id(track_payload)
    return None


def _uuid_sequence() -> Iterable[str]:
    while True:
        yield os.urandom(16).hex()
