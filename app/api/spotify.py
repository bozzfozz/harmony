"""Unified Spotify domain routers delegating to :class:`SpotifyDomainService`."""

from __future__ import annotations

import re
import secrets
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.cache_policy import CACHEABLE_RESPONSES
from app.config import AppConfig
from app.core.soulseek_client import SoulseekClient
from app.core.spotify_client import SpotifyClient
from app.db import session_scope
from app.dependencies import (
    SessionRunner,
    get_app_config,
    get_db,
    get_session_runner,
    get_soulseek_client,
    get_spotify_client,
)
from app.errors import DependencyError, NotFoundError, ValidationAppError
from app.logging import get_logger
from app.models import Download
from app.orchestrator.handlers import (
    enqueue_spotify_backfill,
    get_spotify_backfill_status,
)
from app.schemas import (
    ArtistReleasesResponse,
    AudioFeaturesResponse,
    DiscographyResponse,
    FollowedArtistsResponse,
    PlaylistItemsResponse,
    PlaylistResponse,
    RecommendationsResponse,
    SavedTracksResponse,
    SpotifySearchResponse,
    StatusResponse,
    TrackDetailResponse,
    UserProfileResponse,
)
from app.services.backfill_service import BackfillJobStatus
from app.services.cache import playlist_filters_hash
from app.services.free_ingest_service import IngestSubmission, PlaylistValidationError
from app.services.spotify_domain_service import (
    PlaylistItemsResult,
    SpotifyDomainService,
)
from app.utils.http_cache import (
    compute_playlist_collection_metadata,
    is_request_not_modified,
)
from app.utils.settings_store import write_setting
from app.workers.sync_worker import SyncWorker

router = APIRouter()
core_router = APIRouter(prefix="/spotify", tags=["Spotify"], responses=CACHEABLE_RESPONSES)
backfill_router = APIRouter(prefix="/spotify/backfill", tags=["Spotify Backfill"])
free_router = APIRouter(prefix="/spotify/free", tags=["Spotify FREE"])
free_ingest_router = APIRouter(prefix="/spotify/import", tags=["Spotify FREE Ingest"])

logger = get_logger(__name__)


class PlaylistTracksPayload(BaseModel):
    uris: List[str]


class PlaylistReorderPayload(BaseModel):
    range_start: int
    insert_before: int


class TrackIdsPayload(BaseModel):
    ids: List[str]


class SpotifyStatusResponse(BaseModel):
    status: Literal["connected", "unauthenticated", "unconfigured"]
    free_available: bool = Field(..., description="Whether FREE ingest features are available.")
    pro_available: bool = Field(..., description="Whether Spotify API integrations are configured.")
    authenticated: bool = Field(
        ...,
        description="Indicates if the Spotify client currently holds a valid session.",
    )


def _get_spotify_service(
    request: Request,
    config=Depends(get_app_config),
    spotify_client: SpotifyClient | None = Depends(get_spotify_client),
    soulseek_client: SoulseekClient = Depends(get_soulseek_client),
    session_runner: SessionRunner = Depends(get_session_runner),
) -> SpotifyDomainService:
    return SpotifyDomainService(
        config=config,
        spotify_client=spotify_client,
        soulseek_client=soulseek_client,
        app_state=request.app.state,
        session_runner=session_runner,
    )


@core_router.get("/status", response_model=SpotifyStatusResponse)
def spotify_status(
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> SpotifyStatusResponse:
    status_payload = service.get_status()
    return SpotifyStatusResponse(**asdict(status_payload))


@core_router.get("/search/tracks", response_model=SpotifySearchResponse)
def search_tracks(
    query: str = Query(..., min_length=1),
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> SpotifySearchResponse:
    items = [asdict(track) for track in service.search_tracks(query)]
    return SpotifySearchResponse(items=items)


@core_router.get("/search/artists", response_model=SpotifySearchResponse)
def search_artists(
    query: str = Query(..., min_length=1),
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> SpotifySearchResponse:
    items = service.search_artists(query)
    return SpotifySearchResponse(items=list(items))


@core_router.get("/search/albums", response_model=SpotifySearchResponse)
def search_albums(
    query: str = Query(..., min_length=1),
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> SpotifySearchResponse:
    items = service.search_albums(query)
    return SpotifySearchResponse(items=list(items))


@core_router.get("/artists/followed", response_model=FollowedArtistsResponse)
def get_followed_artists(
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> FollowedArtistsResponse:
    return FollowedArtistsResponse(artists=list(service.get_followed_artists()))


@core_router.get("/artist/{artist_id}/releases", response_model=ArtistReleasesResponse)
def get_artist_releases(
    artist_id: str,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> ArtistReleasesResponse:
    releases = service.get_artist_releases(artist_id)
    return ArtistReleasesResponse(artist_id=artist_id, releases=list(releases))


@core_router.get("/artist/{artist_id}/discography", response_model=DiscographyResponse)
def get_artist_discography(
    artist_id: str,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> DiscographyResponse:
    albums = service.get_artist_discography(artist_id)
    return DiscographyResponse(artist_id=artist_id, albums=list(albums))


@core_router.get("/playlists", response_model=PlaylistResponse)
def list_playlists(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> PlaylistResponse | Response:
    playlists = list(service.list_playlists(db))
    filters_hash = playlist_filters_hash(request.url.query)
    metadata = compute_playlist_collection_metadata(playlists, filters_hash=filters_hash)

    if is_request_not_modified(
        request,
        etag=metadata.etag,
        last_modified=metadata.last_modified,
    ):
        headers = metadata.as_headers()
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)

    headers = metadata.as_headers()
    for header_name, header_value in headers.items():
        response.headers[header_name] = header_value

    return PlaylistResponse(playlists=playlists)


@core_router.get(
    "/playlists/{playlist_id}/tracks",
    response_model=PlaylistItemsResponse,
)
def get_playlist_items(
    playlist_id: str,
    limit: int = Query(100, ge=1, le=100),
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> PlaylistItemsResponse:
    result: PlaylistItemsResult = service.get_playlist_items(playlist_id, limit=limit)
    normalized_items = [asdict(track) for track in result.items]
    return PlaylistItemsResponse(items=normalized_items, total=result.total)


@core_router.post(
    "/playlists/{playlist_id}/tracks",
    response_model=StatusResponse,
)
def add_tracks_to_playlist(
    playlist_id: str,
    payload: PlaylistTracksPayload,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> StatusResponse:
    if not payload.uris:
        raise HTTPException(status_code=400, detail="No track URIs provided")
    service.add_tracks_to_playlist(playlist_id, payload.uris)
    return StatusResponse(status="tracks-added")


@core_router.delete(
    "/playlists/{playlist_id}/tracks",
    response_model=StatusResponse,
)
def remove_tracks_from_playlist(
    playlist_id: str,
    payload: PlaylistTracksPayload,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> StatusResponse:
    if not payload.uris:
        raise HTTPException(status_code=400, detail="No track URIs provided")
    service.remove_tracks_from_playlist(playlist_id, payload.uris)
    return StatusResponse(status="tracks-removed")


@core_router.put(
    "/playlists/{playlist_id}/reorder",
    response_model=StatusResponse,
)
def reorder_playlist(
    playlist_id: str,
    payload: PlaylistReorderPayload,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> StatusResponse:
    service.reorder_playlist(
        playlist_id,
        range_start=payload.range_start,
        insert_before=payload.insert_before,
    )
    return StatusResponse(status="playlist-reordered")


@core_router.get("/track/{track_id}", response_model=TrackDetailResponse)
def get_track_details(
    track_id: str,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> TrackDetailResponse:
    details = service.get_track_details(track_id)
    if not details:
        raise HTTPException(status_code=404, detail="Track not found")
    return TrackDetailResponse(track=details)


@core_router.get("/audio-features/{track_id}", response_model=AudioFeaturesResponse)
def get_audio_features(
    track_id: str,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> AudioFeaturesResponse:
    features = service.get_audio_features(track_id)
    if not features:
        raise HTTPException(status_code=404, detail="Audio features not found")
    return AudioFeaturesResponse(audio_features=features)


@core_router.get("/audio-features", response_model=AudioFeaturesResponse)
def get_multiple_audio_features(
    ids: str = Query(..., min_length=1),
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> AudioFeaturesResponse:
    track_ids = [item.strip() for item in ids.split(",") if item.strip()]
    if not track_ids:
        raise HTTPException(status_code=400, detail="No track IDs provided")
    features = service.get_multiple_audio_features(track_ids)
    return AudioFeaturesResponse(audio_features=list(features))


@core_router.get("/me/tracks", response_model=SavedTracksResponse)
def get_saved_tracks(
    limit: int = Query(20, ge=1, le=50),
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> SavedTracksResponse:
    saved = service.get_saved_tracks(limit=limit)
    return SavedTracksResponse(items=list(saved["items"]), total=saved["total"])


@core_router.put("/me/tracks", response_model=StatusResponse)
def save_tracks(
    payload: TrackIdsPayload,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> StatusResponse:
    if not payload.ids:
        raise HTTPException(status_code=400, detail="No track IDs provided")
    service.save_tracks(payload.ids)
    return StatusResponse(status="tracks-saved")


@core_router.delete("/me/tracks", response_model=StatusResponse)
def remove_saved_tracks(
    payload: TrackIdsPayload,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> StatusResponse:
    if not payload.ids:
        raise HTTPException(status_code=400, detail="No track IDs provided")
    service.remove_saved_tracks(payload.ids)
    return StatusResponse(status="tracks-removed")


@core_router.get("/me", response_model=UserProfileResponse)
def get_current_user(
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> UserProfileResponse:
    profile = service.get_current_user() or {}
    return UserProfileResponse(profile=profile)


@core_router.get("/me/top/tracks", response_model=SpotifySearchResponse)
def get_top_tracks(
    limit: int = Query(20, ge=1, le=50),
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> SpotifySearchResponse:
    items = service.get_top_tracks(limit=limit)
    return SpotifySearchResponse(items=list(items))


@core_router.get("/me/top/artists", response_model=SpotifySearchResponse)
def get_top_artists(
    limit: int = Query(20, ge=1, le=50),
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> SpotifySearchResponse:
    items = service.get_top_artists(limit=limit)
    return SpotifySearchResponse(items=list(items))


@core_router.get("/recommendations", response_model=RecommendationsResponse)
def get_recommendations(
    seed_tracks: Optional[str] = Query(None),
    seed_artists: Optional[str] = Query(None),
    seed_genres: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> RecommendationsResponse:
    def _split(value: Optional[str]) -> Optional[list[str]]:
        if value is None:
            return None
        result = [item.strip() for item in value.split(",") if item.strip()]
        return result or None

    payload = service.get_recommendations(
        seed_tracks=_split(seed_tracks),
        seed_artists=_split(seed_artists),
        seed_genres=_split(seed_genres),
        limit=limit,
    )
    return RecommendationsResponse(
        tracks=list(payload["tracks"]),
        seeds=list(payload["seeds"]),
    )


class BackfillRunRequest(BaseModel):
    max_items: int | None = Field(default=None, ge=1, le=10_000)
    expand_playlists: bool = True


class BackfillRunResponse(BaseModel):
    ok: bool
    job_id: str


class BackfillJobCounts(BaseModel):
    requested: int
    processed: int
    matched: int
    cache_hits: int
    cache_misses: int
    expanded_playlists: int
    expanded_tracks: int


class BackfillJobResponse(BaseModel):
    ok: bool
    job_id: str
    state: str
    counts: BackfillJobCounts
    expand_playlists: bool
    duration_ms: int | None = None
    error: str | None = None


@backfill_router.post("/run", response_model=BackfillRunResponse)
async def run_backfill(
    payload: BackfillRunRequest,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> JSONResponse:
    if not service.is_authenticated():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Spotify credentials are required for backfill",
        )

    try:
        job_id = await enqueue_spotify_backfill(
            service,
            max_items=payload.max_items,
            expand_playlists=payload.expand_playlists,
        )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Spotify credentials are required for backfill",
        ) from None

    response = BackfillRunResponse(ok=True, job_id=job_id)
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=response.model_dump())


def _build_counts(status: BackfillJobStatus) -> BackfillJobCounts:
    return BackfillJobCounts(
        requested=status.requested_items,
        processed=status.processed_items,
        matched=status.matched_items,
        cache_hits=status.cache_hits,
        cache_misses=status.cache_misses,
        expanded_playlists=status.expanded_playlists,
        expanded_tracks=status.expanded_tracks,
    )


@backfill_router.get("/jobs/{job_id}", response_model=BackfillJobResponse)
async def get_backfill_job(
    job_id: str,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> BackfillJobResponse:
    status_payload = get_spotify_backfill_status(service, job_id)
    if status_payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    counts = _build_counts(status_payload)
    return BackfillJobResponse(
        ok=True,
        job_id=status_payload.id,
        state=status_payload.state,
        counts=counts,
        expand_playlists=status_payload.expand_playlists,
        duration_ms=status_payload.duration_ms,
        error=status_payload.error,
    )


class FreeIngestRequest(BaseModel):
    playlist_links: list[str] = Field(default_factory=list)
    tracks: list[str] = Field(default_factory=list)
    batch_hint: Optional[int] = Field(default=None, ge=1, le=10_000)

    @field_validator("playlist_links", mode="before")
    @classmethod
    def _ensure_list(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        raise ValueError("playlist_links must be an array")

    @field_validator("tracks", mode="before")
    @classmethod
    def _ensure_tracks(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        raise ValueError("tracks must be an array")


class SubmissionAccepted(BaseModel):
    playlists: int
    tracks: int
    batches: int


class SubmissionSkipped(BaseModel):
    playlists: int
    tracks: int
    reason: Optional[str] = None


class SubmissionResponse(BaseModel):
    ok: bool
    job_id: Optional[str]
    accepted: SubmissionAccepted
    skipped: SubmissionSkipped
    error: Optional[Dict[str, Any]] = None


class JobCountsModel(BaseModel):
    registered: int
    normalized: int
    queued: int
    completed: int
    failed: int


class JobStatusModel(BaseModel):
    id: str
    state: str
    counts: JobCountsModel
    accepted: SubmissionAccepted
    skipped: SubmissionSkipped
    error: Optional[str] = None
    queued_tracks: int = 0
    failed_tracks: int = 0
    skipped_tracks: int = 0
    skip_reason: Optional[str] = None


class JobResponse(BaseModel):
    ok: bool
    job: JobStatusModel
    error: Optional[Dict[str, Any]] = None


def _build_submission_response(result: IngestSubmission) -> SubmissionResponse:
    skipped_payload = SubmissionSkipped(
        playlists=result.skipped.playlists,
        tracks=result.skipped.tracks,
        reason=result.skipped.reason,
    )
    accepted_payload = SubmissionAccepted(
        playlists=result.accepted.playlists,
        tracks=result.accepted.tracks,
        batches=result.accepted.batches,
    )
    error_payload: Optional[Dict[str, Any]] = None
    if result.error:
        code = "PARTIAL_SUCCESS" if result.error == "partial" else result.error.upper()
        error_payload = {"code": code, "message": result.error}
    return SubmissionResponse(
        ok=result.ok,
        job_id=result.job_id,
        accepted=accepted_payload,
        skipped=skipped_payload,
        error=error_payload,
    )


def _submission_status_code(result: IngestSubmission) -> int:
    if result.error or result.skipped.reason or result.skipped.playlists or result.skipped.tracks:
        return status.HTTP_207_MULTI_STATUS
    return status.HTTP_202_ACCEPTED


@free_ingest_router.post("/free", response_model=SubmissionResponse)
async def submit_free_ingest(
    payload: FreeIngestRequest,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> JSONResponse:
    if not payload.playlist_links and not payload.tracks:
        raise ValidationAppError("playlist_links or tracks required")

    try:
        result = await service.free_import(
            playlist_links=payload.playlist_links,
            tracks=payload.tracks,
            batch_hint=payload.batch_hint,
        )
    except PlaylistValidationError as exc:
        details = [{"url": item.url, "reason": item.reason} for item in exc.invalid_links]
        raise ValidationAppError(
            "invalid playlist links",
            meta={"details": details},
        ) from exc

    response = _build_submission_response(result)
    status_code = _submission_status_code(result)
    return JSONResponse(status_code=status_code, content=response.model_dump())


@free_ingest_router.post("/free/upload", response_model=SubmissionResponse)
async def upload_free_ingest(
    request: Request,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> JSONResponse:
    content_type = request.headers.get("content-type") or ""
    body = await request.body()
    try:
        filename, content = _parse_multipart_file(content_type, body)
    except ValueError as exc:
        raise ValidationAppError(str(exc)) from exc

    if not content:
        raise ValidationAppError("file is empty")

    try:
        tracks = service.parse_tracks_from_file(content, filename)
    except ValueError as exc:
        raise ValidationAppError(str(exc)) from exc

    if not tracks:
        raise ValidationAppError("no tracks found in file")

    result = await service.free_import(tracks=tracks)
    response = _build_submission_response(result)
    status_code = _submission_status_code(result)
    return JSONResponse(status_code=status_code, content=response.model_dump())


@free_ingest_router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_free_ingest_job(
    job_id: str,
    service: SpotifyDomainService = Depends(_get_spotify_service),
) -> JobResponse:
    status_info = service.get_free_ingest_job(job_id)
    if status_info is None:
        raise NotFoundError("job not found")

    counts = JobCountsModel(
        registered=status_info.counts.registered,
        normalized=status_info.counts.normalized,
        queued=status_info.counts.queued,
        completed=status_info.counts.completed,
        failed=status_info.counts.failed,
    )
    accepted = SubmissionAccepted(
        playlists=status_info.accepted.playlists,
        tracks=status_info.accepted.tracks,
        batches=status_info.accepted.batches,
    )
    skipped = SubmissionSkipped(
        playlists=status_info.skipped.playlists,
        tracks=status_info.skipped.tracks,
        reason=status_info.skipped.reason,
    )
    payload = JobStatusModel(
        id=status_info.id,
        state=status_info.state,
        counts=counts,
        accepted=accepted,
        skipped=skipped,
        error=status_info.error,
        queued_tracks=status_info.queued_tracks,
        failed_tracks=status_info.failed_tracks,
        skipped_tracks=status_info.skipped_tracks,
        skip_reason=status_info.skip_reason,
    )
    return JobResponse(ok=True, job=payload, error=None)


def _parse_multipart_file(content_type: str, body: bytes) -> Tuple[str, bytes]:
    if "multipart/form-data" not in content_type.lower():
        raise ValueError("expected multipart/form-data request")
    boundary_match = re.search(r"boundary=([^;]+)", content_type, flags=re.IGNORECASE)
    if not boundary_match:
        raise ValueError("missing multipart boundary")
    boundary = boundary_match.group(1).strip().strip('"')
    if not boundary:
        raise ValueError("invalid multipart boundary")
    delimiter = f"--{boundary}".encode("utf-8")
    closing = f"--{boundary}--".encode("utf-8")
    sections = body.split(delimiter)
    for section in sections:
        if not section or section.startswith(b"--"):
            continue
        part = section.strip(b"\r\n")
        if not part:
            continue
        if part == closing:
            continue
        header_blob, _, data = part.partition(b"\r\n\r\n")
        if not data:
            continue
        headers = {}
        for line in header_blob.split(b"\r\n"):
            if b":" not in line:
                continue
            name, value = line.split(b":", 1)
            headers[name.decode("utf-8", errors="ignore").strip().lower()] = value.decode(
                "utf-8", errors="ignore"
            ).strip()
        disposition = headers.get("content-disposition", "")
        if 'name="file"' not in disposition:
            continue
        filename_match = re.search(r'filename="([^"]*)"', disposition)
        filename = filename_match.group(1) if filename_match else "upload.txt"
        content = data.rstrip(b"\r\n")
        return filename, content
    raise ValueError("no file part in request")


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
        return (
            _ParsedLine("", "", None, None, None, None),
            "Expected format 'Artist - Title'",
        )
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
        return (
            _ParsedLine("", title, album, year, None, None),
            "Artist must not be empty",
        )
    if not title:
        return (
            _ParsedLine(artist, "", album, year, None, None),
            "Title must not be empty",
        )
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


@free_router.post("/upload", response_model=UploadResponse)
async def upload_import_file(
    request: Request,
    payload: UploadPayload,
    config: AppConfig = Depends(get_app_config),
) -> UploadResponse:
    filename = payload.filename or "upload.txt"
    suffix = filename.lower().rsplit(".", 1)
    extension = f".{suffix[1]}" if len(suffix) == 2 else ""
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValidationAppError("Unsupported file type. Allowed: .txt, .m3u, .m3u8")
    content_bytes = payload.content.encode("utf-8", errors="ignore")
    if len(content_bytes) > config.spotify.free_import_max_file_bytes:
        raise ValidationAppError("File exceeds maximum allowed size")
    store = _get_file_store(request)
    token = store.store(payload.content)
    logger.info(
        "event=spotify_free_upload filename=%s size_bytes=%s",
        filename,
        len(content_bytes),
    )
    return UploadResponse(file_token=token)


@free_router.post("/parse", response_model=ParseResponse)
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
            raise NotFoundError("Upload token is no longer valid")
        combined_lines.extend(_split_lines(content))
    if not combined_lines:
        raise ValidationAppError("No input provided")
    if len(combined_lines) > config.spotify.free_import_max_lines:
        raise ValidationAppError("Too many lines submitted")

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
        raise ValidationAppError(
            "Some lines could not be parsed",
            meta={"details": errors},
        )

    logger.info("event=spotify_free_parse count=%s", len(items))
    return ParseResponse(items=items)


@free_router.post("/enqueue", response_model=EnqueueResponse)
async def enqueue_tracks(
    request: Request,
    payload: EnqueueRequest,
    soulseek=Depends(get_soulseek_client),
) -> EnqueueResponse:
    if not payload.items:
        raise ValidationAppError("No tracks provided")

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
                raise DependencyError(
                    "Unable to query Soulseek",
                    status_code=status.HTTP_424_FAILED_DEPENDENCY,
                ) from exc
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


router.include_router(core_router)
router.include_router(backfill_router)
router.include_router(free_ingest_router)
router.include_router(free_router)

__all__ = [
    "router",
    "core_router",
    "backfill_router",
    "free_router",
    "free_ingest_router",
]
