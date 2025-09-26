"""Spotify FREE mode endpoints for parser-based imports."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.config import AppConfig
from app.db import session_scope
from app.dependencies import get_app_config, get_soulseek_client
from app.logging import get_logger
from app.models import Download
from app.utils.settings_store import write_setting
from app.workers.sync_worker import SyncWorker


logger = get_logger(__name__)

router = APIRouter(prefix="/spotify/free", tags=["Spotify FREE"])

LOSSLESS_FORMATS: set[str] = {"flac", "alac", "ape", "wav"}
SUPPORTED_EXTENSIONS: set[str] = {".txt", ".m3u", ".m3u8"}


class NormalizedTrack(BaseModel):
    source: str = Field(default="user")
    kind: str = Field(default="track")
    artist: str
    title: str
    album: Optional[str] = None
    release_year: Optional[int] = None
    spotify_track_id: Optional[str] = None
    spotify_album_id: Optional[str] = None
    query: str

    @field_validator("source", mode="before")
    @classmethod
    def _force_source(cls, value: str | None) -> str:
        return "user"

    @field_validator("kind", mode="before")
    @classmethod
    def _force_kind(cls, value: str | None) -> str:
        return "track"

    @field_validator("artist", "title", "album", "query", mode="before")
    @classmethod
    def _strip_strings(cls, value: Any) -> Any:
        if value is None:
            return None
        text = str(value).strip()
        return text

    @field_validator("release_year", mode="before")
    @classmethod
    def _coerce_year(cls, value: Any) -> Any:
        if value in {None, ""}:
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise ValueError("release_year must be a number")
        if parsed < 0:
            raise ValueError("release_year must be positive")
        return parsed


class ParseRequest(BaseModel):
    lines: List[str] = Field(default_factory=list)
    file_token: Optional[str] = None


class ParseResponse(BaseModel):
    items: List[NormalizedTrack]


class EnqueueRequest(BaseModel):
    items: List[NormalizedTrack]


class EnqueueResponse(BaseModel):
    queued: int
    skipped: int


class UploadPayload(BaseModel):
    filename: str
    content: str


class UploadResponse(BaseModel):
    file_token: str


@dataclass(slots=True)
class _ParsedLine:
    artist: str
    title: str
    album: Optional[str]
    year: Optional[int]
    spotify_track_id: Optional[str]
    spotify_album_id: Optional[str]


class _FreeImportFileStore:
    """In-memory token store for uploaded import files."""

    def __init__(self, *, ttl_seconds: float = 900.0) -> None:
        self._entries: dict[str, tuple[float, str]] = {}
        self._ttl = ttl_seconds

    def store(self, content: str) -> str:
        token = secrets.token_urlsafe(16)
        self._entries[token] = (time.monotonic(), content)
        self._cleanup()
        return token

    def load(self, token: str) -> Optional[str]:
        self._cleanup()
        entry = self._entries.get(token)
        if entry is None:
            return None
        created_at, content = entry
        if time.monotonic() - created_at > self._ttl:
            self._entries.pop(token, None)
            return None
        return content

    def _cleanup(self) -> None:
        threshold = time.monotonic() - self._ttl
        expired = [key for key, (created_at, _) in self._entries.items() if created_at < threshold]
        for key in expired:
            self._entries.pop(key, None)


def _get_file_store(request: Request) -> _FreeImportFileStore:
    store = getattr(request.app.state, "spotify_free_store", None)
    if not isinstance(store, _FreeImportFileStore):
        store = _FreeImportFileStore()
        request.app.state.spotify_free_store = store
    return store


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    errors: Optional[List[Dict[str, Any]]] = None,
) -> JSONResponse:
    payload: Dict[str, Any] = {"ok": False, "error": {"code": code, "message": message}}
    if errors:
        payload["error"]["details"] = errors
    return JSONResponse(status_code=status_code, content=payload)


def _split_lines(content: str) -> List[str]:
    return [line.strip() for line in content.replace("\r", "").split("\n")]


def _extract_spotify_tokens(text: str) -> tuple[str, str, str, str]:
    cleaned = text
    track_id = ""
    album_id = ""
    playlist_id = ""
    patterns = {
        "track": (
            r"https?://open\.spotify\.com/track/([A-Za-z0-9]+)",
            r"spotify:track:([A-Za-z0-9]+)",
        ),
        "album": (
            r"https?://open\.spotify\.com/album/([A-Za-z0-9]+)",
            r"spotify:album:([A-Za-z0-9]+)",
        ),
        "playlist": (
            r"https?://open\.spotify\.com/playlist/([A-Za-z0-9]+)",
            r"spotify:playlist:([A-Za-z0-9]+)",
        ),
    }

    for kind, expressions in patterns.items():
        for expression in expressions:
            matches = list(re.finditer(expression, cleaned, flags=re.IGNORECASE))
            if not matches:
                continue
            for match in matches:
                identifier = match.group(1)
                cleaned = cleaned.replace(match.group(0), " ")
                if kind == "track" and not track_id:
                    track_id = identifier
                elif kind == "album" and not album_id:
                    album_id = identifier
                elif kind == "playlist" and not playlist_id:
                    playlist_id = identifier
    return track_id, album_id, playlist_id, " ".join(cleaned.split())


def _parse_year(candidate: str) -> Optional[int]:
    stripped = candidate.strip()
    if not stripped:
        return None
    if not stripped.isdigit():
        raise ValueError("Year must be numeric")
    year = int(stripped)
    if year < 1000 or year > 2100:
        raise ValueError("Year must be in range 1000-2100")
    return year


def _parse_metadata(text: str) -> Tuple[_ParsedLine, Optional[str]]:
    if not text:
        return _ParsedLine("", "", None, None, None, None), "Missing track details"
    segments = [segment.strip() for segment in text.split("|")]
    main = segments[0]
    remainder = segments[1:]
    parts = re.split(r"\s*[-–—]\s*", main, maxsplit=1)
    if len(parts) < 2:
        return _ParsedLine("", "", None, None, None, None), "Expected format 'Artist - Title'"
    artist, title = parts[0].strip(), parts[1].strip()
    album = remainder[0].strip() if remainder else None
    year: Optional[int] = None
    if len(remainder) >= 2:
        try:
            year = _parse_metadata_year_candidate(remainder[1])
        except ValueError as exc:
            return _ParsedLine(artist, title, album or None, None, None, None), str(exc)
    elif len(remainder) == 1:
        try:
            year = _parse_metadata_year_candidate(remainder[0])
            if year is not None:
                album = None
        except ValueError:
            year = None
    if not artist:
        return _ParsedLine("", title, album, year, None, None), "Artist must not be empty"
    if not title:
        return _ParsedLine(artist, "", album, year, None, None), "Title must not be empty"
    return _ParsedLine(artist, title, album or None, year, None, None), None


def _parse_metadata_year_candidate(value: str) -> Optional[int]:
    candidate = value.strip()
    if not candidate:
        return None
    try:
        return _parse_year(candidate)
    except ValueError as exc:
        raise ValueError(str(exc))


def _build_query(artist: str, title: str, album: Optional[str], year: Optional[int]) -> str:
    parts = [title, artist]
    if album:
        parts.append(album)
    if year:
        parts.append(str(year))
    return " ".join(part for part in parts if part)


def _generate_search_queries(track: NormalizedTrack) -> List[str]:
    queries: List[str] = []
    primary = _build_query(track.artist, track.title, track.album, track.release_year)
    if primary:
        queries.append(primary)

    title_artist = " ".join(part for part in [track.title, track.artist] if part)
    if title_artist and title_artist not in queries:
        queries.append(title_artist)

    artist_title = " ".join(part for part in [track.artist, track.title] if part)
    if artist_title and artist_title not in queries:
        queries.append(artist_title)

    if track.title and track.title not in queries:
        queries.append(track.title)

    return queries


def _select_candidate(payload: Any) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    if not isinstance(payload, dict):
        return None, None
    candidates = payload.get("results")
    if not isinstance(candidates, list):
        candidates = []
    best: tuple[int, int, int, str, Dict[str, Any]] | None = None
    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        username = entry.get("username") or entry.get("user")
        files = entry.get("files")
        if not username or not isinstance(files, Iterable):
            continue
        for file_info in files:
            if not isinstance(file_info, dict):
                continue
            candidate = dict(file_info)
            filename = (
                candidate.get("filename")
                or candidate.get("name")
                or candidate.get("title")
                or candidate.get("path")
            )
            if filename:
                candidate["filename"] = str(filename)
            format_name = str(candidate.get("format") or candidate.get("extension") or "").lower()
            if not format_name and isinstance(candidate.get("filename"), str):
                filename = str(candidate["filename"])
                if "." in filename:
                    format_name = filename.rsplit(".", 1)[1].lower()
            lossless = 1 if format_name in LOSSLESS_FORMATS else 0
            try:
                bitrate = int(candidate.get("bitrate") or 0)
            except (TypeError, ValueError):
                bitrate = 0
            try:
                size = int(candidate.get("size") or 0)
            except (TypeError, ValueError):
                size = 0
            score = (lossless, bitrate, size)
            if best is None or score > best[:3]:
                best = (*score, str(username), candidate)
    if best is None:
        return None, None
    _, _, _, username, candidate = best
    return username, candidate


def _create_download_record(
    *,
    track: NormalizedTrack,
    username: str,
    file_info: Dict[str, Any],
    priority: int,
    query: str,
) -> int:
    with session_scope() as session:
        download = Download(
            filename=file_info.get("filename") or file_info.get("name") or f"{track.title}.flac",
            state="queued",
            progress=0.0,
            username=username,
            priority=priority,
            spotify_track_id=track.spotify_track_id or None,
            spotify_album_id=track.spotify_album_id or None,
        )
        session.add(download)
        session.flush()
        payload = {
            "source": "spotify_free",
            "query": query,
            "track": track.model_dump(),
            "file": dict(file_info),
        }
        payload["download_id"] = download.id
        payload["priority"] = priority
        download.request_payload = payload
        session.add(download)
        return download.id


def _ensure_worker(request: Request) -> Optional[SyncWorker]:
    worker = getattr(request.app.state, "sync_worker", None)
    return worker if isinstance(worker, SyncWorker) else None


@router.post("/upload", response_model=UploadResponse)
async def upload_import_file(
    request: Request,
    payload: UploadPayload,
    config: AppConfig = Depends(get_app_config),
) -> UploadResponse:
    filename = payload.filename or "upload.txt"
    suffix = filename.lower().rsplit(".", 1)
    extension = f".{suffix[1]}" if len(suffix) == 2 else ""
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "Unsupported file type. Allowed: .txt, .m3u, .m3u8",
            },
        )
    content_bytes = payload.content.encode("utf-8", errors="ignore")
    if len(content_bytes) > config.spotify.free_import_max_file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "File exceeds maximum allowed size",
            },
        )
    store = _get_file_store(request)
    token = store.store(payload.content)
    logger.info(
        "event=spotify_free_upload filename=%s size_bytes=%s",
        filename,
        len(content_bytes),
    )
    return UploadResponse(file_token=token)


@router.post("/parse", response_model=ParseResponse)
async def parse_import_lines(
    request: Request,
    payload: ParseRequest,
    config: AppConfig = Depends(get_app_config),
) -> ParseResponse:
    store = _get_file_store(request)
    combined_lines: List[str] = []
    if payload.lines:
        combined_lines.extend(payload.lines)
    if payload.file_token:
        content = store.load(payload.file_token)
        if content is None:
            return _error_response(
                status_code=status.HTTP_404_NOT_FOUND,
                code="NOT_FOUND",
                message="Upload token is no longer valid",
            )
        combined_lines.extend(_split_lines(content))
    if not combined_lines:
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="VALIDATION_ERROR",
            message="No input provided",
        )
    if len(combined_lines) > config.spotify.free_import_max_lines:
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="VALIDATION_ERROR",
            message="Too many lines submitted",
        )

    items: List[NormalizedTrack] = []
    errors: List[Dict[str, Any]] = []
    for index, raw_line in enumerate(combined_lines, start=1):
        line = raw_line.strip()
        if not line:
            errors.append({"line": index, "message": "Line is empty"})
            continue
        track_id, album_id, playlist_id, remainder = _extract_spotify_tokens(line)
        if playlist_id:
            errors.append(
                {
                    "line": index,
                    "message": "Playlist URLs cannot be expanded in FREE mode. Provide the track list instead.",
                }
            )
            continue
        parsed, error_message = _parse_metadata(remainder)
        if album_id and not track_id:
            errors.append(
                {
                    "line": index,
                    "message": "Album URLs require explicit track lines in FREE mode.",
                }
            )
            continue
        if error_message:
            errors.append({"line": index, "message": error_message})
            continue
        parsed.spotify_track_id = track_id or None
        parsed.spotify_album_id = album_id or None
        query = _build_query(parsed.artist, parsed.title, parsed.album, parsed.year)
        if not query:
            errors.append(
                {
                    "line": index,
                    "message": "Unable to build search query for the provided line.",
                }
            )
            continue
        track = NormalizedTrack(
            artist=parsed.artist,
            title=parsed.title,
            album=parsed.album,
            release_year=parsed.year,
            spotify_track_id=parsed.spotify_track_id,
            spotify_album_id=parsed.spotify_album_id,
            query=query,
        )
        items.append(track)

    if errors:
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="VALIDATION_ERROR",
            message="Some lines could not be parsed",
            errors=errors,
        )

    logger.info("event=spotify_free_parse count=%s", len(items))
    return ParseResponse(items=items)


@router.post("/enqueue", response_model=EnqueueResponse)
async def enqueue_tracks(
    request: Request,
    payload: EnqueueRequest,
    soulseek=Depends(get_soulseek_client),
) -> EnqueueResponse:
    if not payload.items:
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="VALIDATION_ERROR",
            message="No tracks provided",
        )

    worker = _ensure_worker(request)
    queued = 0
    skipped = 0
    seen: set[tuple[str, str, str, Optional[int]]] = set()

    for track in payload.items:
        key = (
            track.artist.lower(),
            track.title.lower(),
            (track.album or "").lower(),
            track.release_year,
        )
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        search_queries = _generate_search_queries(track)
        username: Optional[str] = None
        candidate: Optional[Dict[str, Any]] = None
        query_used: Optional[str] = None
        for query in search_queries:
            if not query:
                continue
            try:
                results = await soulseek.search(
                    query,
                    format_priority=tuple(LOSSLESS_FORMATS),
                )
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.error("Spotify FREE enqueue search failed: %s", exc)
                return _error_response(
                    status_code=status.HTTP_424_FAILED_DEPENDENCY,
                    code="DEPENDENCY_ERROR",
                    message="Unable to query Soulseek",
                )
            username, candidate = _select_candidate(results)
            if username and candidate:
                query_used = query
                break

        if not username or not candidate or not query_used:
            skipped += 1
            continue
        priority = 10 if str(candidate.get("format", "")).lower() in LOSSLESS_FORMATS else 0
        try:
            download_id = _create_download_record(
                track=track,
                username=username,
                file_info=candidate,
                priority=priority,
                query=query_used,
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.error("Failed to create download record for FREE import: %s", exc)
            skipped += 1
            continue
        job_file = dict(candidate)
        job_file.setdefault("filename", job_file.get("name"))
        job_file["download_id"] = download_id
        job_file["priority"] = priority
        job_payload = {"username": username, "files": [job_file]}
        try:
            if worker is not None:
                await worker.enqueue(job_payload)
            else:
                await soulseek.download(job_payload)
        except Exception as exc:  # pragma: no cover - defensive guard
            logger.error("Failed to enqueue FREE import download: %s", exc)
            skipped += 1
            continue
        queued += 1

    logger.info(
        "event=spotify_free_enqueue queued=%s skipped=%s",
        queued,
        skipped,
    )
    write_setting("metrics.spotify_free.last_queued", str(queued))
    write_setting("metrics.spotify_free.last_skipped", str(skipped))
    return EnqueueResponse(queued=queued, skipped=skipped)
