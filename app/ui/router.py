from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.api.search import DEFAULT_SOURCES
from app.api.spotify import _parse_multipart_file
from app.core.soulseek_client import SoulseekClient
from app.db import session_scope
from app.dependencies import (
    get_app_config,
    get_db,
    get_download_service,
    get_soulseek_client,
)
from app.errors import AppError
from app.logging import get_logger
from app.logging_events import log_event
from app.routers.soulseek_router import (
    soulseek_cancel,
    soulseek_remove_completed_downloads,
    soulseek_remove_completed_uploads,
    soulseek_requeue_download,
    refresh_download_lyrics as api_refresh_download_lyrics,
    refresh_download_metadata as api_refresh_download_metadata,
    soulseek_download_artwork as api_soulseek_download_artwork,
    soulseek_download_lyrics as api_soulseek_download_lyrics,
    soulseek_download_metadata as api_soulseek_download_metadata,
    soulseek_refresh_artwork as api_soulseek_refresh_artwork,
)
from app.schemas import SoulseekDownloadRequest
from app.models import Download
from app.schemas.watchlist import WatchlistEntryCreate, WatchlistPriorityUpdate
from app.services.download_service import DownloadService
from app.ui.assets import asset_url
from app.ui.context import (
    AlertMessage,
    FormDefinition,
    LayoutContext,
    SuggestedTask,
    get_ui_assets,
    attach_secret_result,
    build_activity_fragment_context,
    build_activity_page_context,
    build_admin_page_context,
    build_settings_artist_preferences_fragment_context,
    build_settings_form_fragment_context,
    build_settings_history_fragment_context,
    build_settings_page_context,
    build_dashboard_page_context,
    build_downloads_fragment_context,
    build_downloads_page_context,
    build_jobs_fragment_context,
    build_jobs_page_context,
    build_login_page_context,
    build_operations_page_context,
    build_primary_navigation,
    build_search_page_context,
    build_search_results_context,
    build_soulseek_config_context,
    build_soulseek_downloads_context,
    build_soulseek_download_artwork_modal_context,
    build_soulseek_download_lyrics_modal_context,
    build_soulseek_download_metadata_modal_context,
    build_soulseek_navigation_badge,
    build_soulseek_page_context,
    build_soulseek_status_context,
    build_soulseek_uploads_context,
    build_soulseek_user_directory_context,
    build_soulseek_user_profile_context,
    build_spotify_account_context,
    build_spotify_artists_context,
    build_spotify_backfill_context,
    build_spotify_free_ingest_context,
    build_spotify_page_context,
    build_spotify_playlist_items_context,
    build_spotify_playlists_context,
    build_spotify_recommendations_context,
    build_spotify_saved_tracks_context,
    build_spotify_status_context,
    build_spotify_top_artists_context,
    build_spotify_top_tracks_context,
    build_spotify_track_detail_context,
    build_system_integrations_context,
    build_system_liveness_context,
    build_system_page_context,
    build_system_readiness_context,
    build_system_secret_card_context,
    build_system_secret_cards,
    build_system_service_health_context,
    build_watchlist_fragment_context,
    build_watchlist_page_context,
    select_system_secret_card,
)
from app.ui.csrf import attach_csrf_cookie, clear_csrf_cookie, enforce_csrf, get_csrf_manager
from app.ui.services import (
    ActivityUiService,
    DownloadsUiService,
    JobsUiService,
    SearchUiService,
    SoulseekUiService,
    SpotifyFreeIngestResult,
    SpotifyPlaylistFilters,
    SpotifyPlaylistRow,
    SpotifyRecommendationRow,
    SpotifyRecommendationSeed,
    SpotifyUiService,
    SystemUiService,
    WatchlistUiService,
    SettingsUiService,
    SettingsOverview,
    get_activity_ui_service,
    get_downloads_ui_service,
    get_jobs_ui_service,
    get_search_ui_service,
    get_settings_ui_service,
    get_soulseek_ui_service,
    get_spotify_ui_service,
    get_system_ui_service,
    get_watchlist_ui_service,
)
from app.ui.session import (
    UiSession,
    attach_session_cookie,
    clear_session_cookie,
    clear_spotify_job_state,
    get_session_manager,
    get_spotify_backfill_job_id,
    get_spotify_free_ingest_job_id,
    require_admin_with_feature,
    require_operator_with_feature,
    require_role,
    require_session,
    set_spotify_backfill_job_id,
    set_spotify_free_ingest_job_id,
)

logger = get_logger(__name__)

_SPOTIFY_TIME_RANGES = frozenset({"short_term", "medium_term", "long_term"})
_DEFAULT_TIME_RANGE = "medium_term"

_SAVED_TRACKS_LIMIT_COOKIE = "spotify_saved_tracks_limit"
_SAVED_TRACKS_OFFSET_COOKIE = "spotify_saved_tracks_offset"
_SPOTIFY_BACKFILL_TIMELINE_LIMIT = 10

router = APIRouter(prefix="/ui", tags=["UI"])

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
templates.env.globals["asset_url"] = asset_url
templates.env.globals["get_ui_assets"] = get_ui_assets


@dataclass(slots=True)
class RecommendationsFormData:
    values: Mapping[str, str]
    artist_seeds: tuple[str, ...]
    track_seeds: tuple[str, ...]
    genre_seeds: tuple[str, ...]
    errors: Mapping[str, str]
    alerts: tuple[AlertMessage, ...]
    limit: int
    general_error: bool
    action: str
    queue_track_ids: tuple[str, ...]


def _render_alert_fragment(
    request: Request,
    message: str,
    *,
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
    retry_url: str | None = None,
    retry_target: str | None = None,
    retry_label_key: str = "fragments.retry",
) -> Response:
    alert = AlertMessage(level="error", text=message or "An unexpected error occurred.")
    context = {
        "request": request,
        "alerts": (alert,),
        "retry_url": retry_url,
        "retry_target": retry_target,
        "retry_label_key": retry_label_key,
    }
    return templates.TemplateResponse(
        request,
        "partials/async_error.j2",
        context,
        status_code=status_code,
    )


def _parse_form_body(raw_body: bytes) -> dict[str, str]:
    try:
        payload = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        payload = ""
    parsed = parse_qs(payload)
    return {key: (values[0].strip() if values else "") for key, values in parsed.items()}


def _extract_download_refresh_params(
    request: Request, values: Mapping[str, str]
) -> tuple[int, int, bool]:
    def _parse_int(
        value: str | None,
        *,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        if value is None or not value.strip():
            return default
        try:
            parsed = int(value)
        except ValueError:
            return default
        return max(min(parsed, maximum), minimum)

    limit_value = _parse_int(
        values.get("limit") or request.query_params.get("limit"),
        default=20,
        minimum=1,
        maximum=100,
    )
    offset_value = _parse_int(
        values.get("offset") or request.query_params.get("offset"),
        default=0,
        minimum=0,
        maximum=10_000,
    )
    scope_raw = (values.get("scope") or request.query_params.get("scope") or "").lower()
    include_all = scope_raw in {"all", "true", "1", "yes"}
    if not include_all:
        include_all = request.query_params.get("all", "").lower() in {"1", "true", "all", "yes"}
    return limit_value, offset_value, include_all


async def _handle_backfill_action(
    request: Request,
    session: UiSession,
    service: SpotifyUiService,
    *,
    action: Callable[[SpotifyUiService, str], Mapping[str, object]],
    success_message: str,
    event_key: str,
) -> Response:
    values = _parse_form_body(await request.body())
    job_id = values.get("job_id", "")
    if not job_id:
        return _render_alert_fragment(
            request,
            "A backfill job identifier is required.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        status_payload = action(service, job_id)
    except PermissionError as exc:
        logger.warning("spotify.ui.backfill.denied", extra={"error": str(exc)})
        return _render_alert_fragment(
            request,
            "Spotify authentication is required before managing backfill jobs.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    except LookupError:
        return _render_alert_fragment(
            request,
            "The requested backfill job could not be found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    except ValueError as exc:
        return _render_alert_fragment(
            request,
            str(exc) or "Invalid backfill action request.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except AppError as exc:
        logger.warning("spotify.ui.backfill.error", extra={"error": exc.code})
        return _render_alert_fragment(
            request,
            exc.message if exc.message else "Unable to update the backfill job.",
        )
    except Exception:
        logger.exception("spotify.ui.backfill.error")
        return _render_alert_fragment(
            request,
            "Failed to update the backfill job.",
        )

    await set_spotify_backfill_job_id(request, session, job_id)
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    snapshot = service.build_backfill_snapshot(
        csrf_token=csrf_token,
        job_id=job_id,
        status_payload=status_payload,
    )
    alert = AlertMessage(level="success", text=success_message.format(job_id=job_id))
    context = build_spotify_backfill_context(
        request,
        snapshot=snapshot,
        alert=alert,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_backfill.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        event_key,
        component="ui.router",
        status="success",
        role=session.role,
        job_id=job_id,
        state=status_payload.get("state"),
    )
    return response


def _ensure_csrf_token(request: Request, session: UiSession, manager) -> tuple[str, bool]:
    token = request.cookies.get("csrftoken")
    if token:
        return token, False
    issued = manager.issue(session)
    return issued, True


def _extract_saved_tracks_pagination(request: Request) -> tuple[int, int]:
    def _coerce(
        raw: str | None,
        default: int,
        *,
        minimum: int,
        maximum: int | None = None,
    ) -> int:
        try:
            value = int(raw) if raw not in (None, "") else default
        except (TypeError, ValueError):
            value = default
        value = max(minimum, value)
        if maximum is not None:
            value = min(value, maximum)
        return value

    default_limit = 25
    default_offset = 0

    header_url = request.headers.get("hx-current-url")
    header_params: dict[str, str] = {}
    if header_url:
        try:
            parsed = urlparse(header_url)
        except ValueError:
            parsed = None
        if parsed is not None:
            header_params = {
                key: values[0] for key, values in parse_qs(parsed.query).items() if values
            }

    def _resolve(key: str, *, fallback: str | None = None) -> str | None:
        value = request.query_params.get(key)
        if value not in (None, ""):
            return value
        value = header_params.get(key)
        if value not in (None, ""):
            return value
        value = request.cookies.get(
            {
                "limit": _SAVED_TRACKS_LIMIT_COOKIE,
                "offset": _SAVED_TRACKS_OFFSET_COOKIE,
            }[key]
        )
        if value not in (None, ""):
            return value
        return fallback

    limit = _coerce(
        _resolve("limit", fallback=str(default_limit)),
        default_limit,
        minimum=1,
        maximum=50,
    )
    offset = _coerce(
        _resolve("offset", fallback=str(default_offset)),
        default_offset,
        minimum=0,
    )
    return limit, offset


def _persist_saved_tracks_pagination(response: Response, *, limit: int, offset: int) -> None:
    response.set_cookie(
        _SAVED_TRACKS_LIMIT_COOKIE,
        str(limit),
        httponly=True,
        secure=True,
        samesite="lax",
        path="/ui/spotify",
    )
    response.set_cookie(
        _SAVED_TRACKS_OFFSET_COOKIE,
        str(offset),
        httponly=True,
        secure=True,
        samesite="lax",
        path="/ui/spotify",
    )


def _extract_time_range(request: Request) -> str:
    value = request.query_params.get("time_range")
    if value in _SPOTIFY_TIME_RANGES:
        return value
    return _DEFAULT_TIME_RANGE


def _split_seed_ids(raw_value: str) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for entry in re.split(r"[\s,]+", raw_value.strip()):
        candidate = entry.strip()
        if not candidate:
            continue
        lowered = candidate.lower()
        if lowered in seen:
            continue
        cleaned.append(candidate)
        seen.add(lowered)
    return cleaned


def _split_seed_genres(raw_value: str) -> list[str]:
    entries: list[str] = []
    seen: set[str] = set()
    normalised = raw_value.replace("\r", "\n")
    for part in normalised.split("\n"):
        for chunk in part.split(","):
            candidate = chunk.strip()
            if not candidate:
                continue
            lowered = candidate.lower()
            if lowered in seen:
                continue
            entries.append(candidate)
            seen.add(lowered)
    return entries


def _split_ingest_lines(raw_value: str) -> list[str]:
    entries: list[str] = []
    normalised = raw_value.replace("\r", "\n")
    for part in normalised.split("\n"):
        candidate = part.strip()
        if not candidate:
            continue
        entries.append(candidate)
    return entries


def _ensure_imports_feature_enabled(session: UiSession) -> None:
    if not session.features.imports:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested UI feature is disabled.",
        )


def _render_recommendations_response(
    request: Request,
    session: UiSession,
    csrf_manager,
    csrf_token: str,
    *,
    issued: bool,
    rows: Sequence[SpotifyRecommendationRow] = (),
    seeds: Sequence[SpotifyRecommendationSeed] = (),
    form_values: Mapping[str, str] | None = None,
    form_errors: Mapping[str, str] | None = None,
    alerts: Sequence[AlertMessage] | None = None,
    seed_defaults: Mapping[str, str] | None = None,
    show_admin_controls: bool = False,
    status_code: int = status.HTTP_200_OK,
) -> Response:
    limit, offset = _extract_saved_tracks_pagination(request)
    context = build_spotify_recommendations_context(
        request,
        csrf_token=csrf_token,
        rows=rows,
        seeds=seeds,
        limit=limit,
        offset=offset,
        form_values=form_values,
        form_errors=form_errors,
        alerts=alerts,
        seed_defaults=seed_defaults,
        show_admin_controls=show_admin_controls,
        queue_enabled=session.features.imports,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_recommendations.j2",
        context,
        status_code=status_code,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


def _parse_recommendations_form(
    form: Mapping[str, Sequence[str]],
) -> RecommendationsFormData:
    def _first(name: str) -> str:
        entries = form.get(name, ())
        if entries:
            entry = entries[0]
            return str(entry) if entry is not None else ""
        return ""

    action_raw = _first("action").strip().lower()
    action = action_raw or "submit"

    form_values = {
        "seed_artists": _first("seed_artists").strip(),
        "seed_tracks": _first("seed_tracks").strip(),
        "seed_genres": _first("seed_genres").strip(),
        "limit": _first("limit").strip(),
    }

    queue_candidates: list[str] = []
    for key in ("track_id", "track_ids", "track_id[]"):
        entries = form.get(key, ())
        for entry in entries:
            if isinstance(entry, str):
                queue_candidates.append(entry)

    queue_ids: list[str] = []
    seen_queue: set[str] = set()
    for candidate in queue_candidates:
        for part in re.split(r"[\s,]+", candidate):
            cleaned = part.strip()
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered in seen_queue:
                continue
            seen_queue.add(lowered)
            queue_ids.append(cleaned)

    errors: dict[str, str] = {}
    alerts: list[AlertMessage] = []

    limit_value = 20
    limit_raw = form_values["limit"]
    if limit_raw:
        try:
            limit_value = int(limit_raw)
        except (TypeError, ValueError):
            errors["limit"] = "Enter a number between 1 and 100."
    if "limit" not in errors and not 1 <= limit_value <= 100:
        errors["limit"] = "Enter a number between 1 and 100."

    artist_seeds = tuple(_split_seed_ids(form_values["seed_artists"]))
    track_seeds = tuple(_split_seed_ids(form_values["seed_tracks"]))
    genre_seeds = tuple(_split_seed_genres(form_values["seed_genres"]))

    total_seeds = len(artist_seeds) + len(track_seeds) + len(genre_seeds)
    general_error = False
    if action not in {"save_defaults", "load_defaults"}:
        if total_seeds == 0:
            alerts.append(AlertMessage(level="error", text="Provide at least one seed value."))
            general_error = True
        elif total_seeds > 5:
            alerts.append(
                AlertMessage(level="error", text="Specify no more than five seeds in total.")
            )
            general_error = True

    return RecommendationsFormData(
        values=form_values,
        artist_seeds=artist_seeds,
        track_seeds=track_seeds,
        genre_seeds=genre_seeds,
        errors=errors,
        alerts=tuple(alerts),
        limit=limit_value,
        general_error=general_error,
        action=action,
        queue_track_ids=tuple(queue_ids),
    )


def _recommendations_value_error_response(
    *,
    request: Request,
    session: UiSession,
    csrf_manager,
    csrf_token: str,
    issued: bool,
    alerts: Sequence[AlertMessage],
    form_values: Mapping[str, str],
    message: str,
    seed_defaults: Mapping[str, str] | None,
    show_admin_controls: bool,
) -> Response:
    combined_alerts = list(alerts)
    combined_alerts.append(AlertMessage(level="error", text=message))
    log_event(
        logger,
        "ui.fragment.spotify.recommendations",
        component="ui.router",
        status="error",
        role=session.role,
        error="validation",
    )
    return _render_recommendations_response(
        request,
        session,
        csrf_manager,
        csrf_token,
        issued=issued,
        form_values=form_values,
        alerts=combined_alerts,
        seed_defaults=seed_defaults,
        show_admin_controls=show_admin_controls,
        status_code=status.HTTP_400_BAD_REQUEST,
    )


def _recommendations_app_error_response(
    *,
    request: Request,
    session: UiSession,
    csrf_manager,
    csrf_token: str,
    issued: bool,
    form_values: Mapping[str, str],
    alerts: Sequence[AlertMessage],
    error_code: str,
    status_code: int,
    seed_defaults: Mapping[str, str] | None,
    show_admin_controls: bool,
) -> Response:
    log_event(
        logger,
        "ui.fragment.spotify.recommendations",
        component="ui.router",
        status="error",
        role=session.role,
        error=error_code,
    )
    return _render_recommendations_response(
        request,
        session,
        csrf_manager,
        csrf_token,
        issued=issued,
        form_values=form_values,
        alerts=alerts,
        seed_defaults=seed_defaults,
        show_admin_controls=show_admin_controls,
        status_code=status_code,
    )


def _recommendations_unexpected_response(
    *,
    request: Request,
    session: UiSession,
    csrf_manager,
    csrf_token: str,
    issued: bool,
    form_values: Mapping[str, str],
    seed_defaults: Mapping[str, str] | None,
    show_admin_controls: bool,
) -> Response:
    logger.exception("ui.fragment.spotify.recommendations")
    log_event(
        logger,
        "ui.fragment.spotify.recommendations",
        component="ui.router",
        status="error",
        role=session.role,
        error="unexpected",
    )
    fallback_alerts = [
        AlertMessage(
            level="error",
            text="Unable to fetch Spotify recommendations.",
        )
    ]
    return _render_recommendations_response(
        request,
        session,
        csrf_manager,
        csrf_token,
        issued=issued,
        form_values=form_values,
        alerts=fallback_alerts,
        seed_defaults=seed_defaults,
        show_admin_controls=show_admin_controls,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _execute_recommendations_request(
    *,
    service: SpotifyUiService,
    form_data: RecommendationsFormData,
    request: Request,
    session: UiSession,
    csrf_manager,
    csrf_token: str,
    issued: bool,
    form_values: Mapping[str, str],
    seed_defaults: Mapping[str, str] | None,
    show_admin_controls: bool,
) -> tuple[
    tuple[Sequence[SpotifyRecommendationRow], Sequence[SpotifyRecommendationSeed]] | None,
    Response | None,
]:
    base_args = {
        "request": request,
        "session": session,
        "csrf_manager": csrf_manager,
        "csrf_token": csrf_token,
        "issued": issued,
        "seed_defaults": seed_defaults,
        "show_admin_controls": show_admin_controls,
    }
    form_values = _build_recommendation_form_values(
        artist_seeds=form_data.artist_seeds,
        track_seeds=form_data.track_seeds,
        genre_seeds=form_data.genre_seeds,
        limit_value=form_data.limit,
    )
    try:
        rows, seeds = service.recommendations(
            seed_tracks=form_data.track_seeds,
            seed_artists=form_data.artist_seeds,
            seed_genres=form_data.genre_seeds,
            limit=form_data.limit,
        )
        return (rows, seeds), None
    except ValueError as exc:
        return None, _recommendations_value_error_response(
            **base_args,
            alerts=form_data.alerts,
            form_values=form_values,
            message=str(exc) or "Unable to fetch Spotify recommendations.",
        )
    except AppError as exc:
        return None, _recommendations_app_error_response(
            **base_args,
            form_values=form_values,
            alerts=[AlertMessage(level="error", text=exc.message)],
            error_code=exc.code,
            status_code=exc.http_status,
        )
    except Exception:
        return None, _recommendations_unexpected_response(
            **base_args,
            form_values=form_values,
        )


def _build_recommendation_form_values(
    *,
    artist_seeds: Sequence[str],
    track_seeds: Sequence[str],
    genre_seeds: Sequence[str],
    limit_value: int,
) -> Mapping[str, str]:
    return {
        "seed_artists": ", ".join(artist_seeds),
        "seed_tracks": ", ".join(track_seeds),
        "seed_genres": ", ".join(genre_seeds),
        "limit": str(limit_value),
    }


def _finalize_recommendations_success(
    *,
    request: Request,
    session: UiSession,
    csrf_manager,
    csrf_token: str,
    issued: bool,
    rows: Sequence[SpotifyRecommendationRow],
    seeds: Sequence[SpotifyRecommendationSeed],
    form_values: Mapping[str, str],
    alerts: Sequence[AlertMessage] | None,
    seed_defaults: Mapping[str, str] | None,
    show_admin_controls: bool,
) -> Response:
    response = _render_recommendations_response(
        request,
        session,
        csrf_manager,
        csrf_token,
        issued=issued,
        rows=rows,
        seeds=seeds,
        form_values=form_values,
        alerts=alerts,
        seed_defaults=seed_defaults,
        show_admin_controls=show_admin_controls,
    )
    log_event(
        logger,
        "ui.fragment.spotify.recommendations",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(rows),
    )
    return response


def _fetch_recommendation_rows(
    *,
    request: Request,
    session: UiSession,
    service: SpotifyUiService,
    csrf_manager,
    csrf_token: str,
    issued: bool,
    parsed_form: RecommendationsFormData,
    seed_defaults: Mapping[str, str] | None,
    show_admin_controls: bool,
) -> tuple[
    Mapping[str, str],
    tuple[Sequence[SpotifyRecommendationRow], Sequence[SpotifyRecommendationSeed]] | None,
    Response | None,
]:
    normalised_values = _build_recommendation_form_values(
        artist_seeds=parsed_form.artist_seeds,
        track_seeds=parsed_form.track_seeds,
        genre_seeds=parsed_form.genre_seeds,
        limit_value=parsed_form.limit,
    )
    result, error_response = _execute_recommendations_request(
        service=service,
        form_data=parsed_form,
        request=request,
        session=session,
        csrf_manager=csrf_manager,
        csrf_token=csrf_token,
        issued=issued,
        form_values=normalised_values,
        seed_defaults=seed_defaults,
        show_admin_controls=show_admin_controls,
    )
    return normalised_values, result, error_response


def _render_recommendations_form(
    *,
    request: Request,
    session: UiSession,
    csrf_manager,
    csrf_token: str,
    issued: bool,
    form_values: Mapping[str, str],
    seed_defaults: Mapping[str, str],
    show_admin_controls: bool,
    alerts: Sequence[AlertMessage] | None = None,
    form_errors: Mapping[str, str] | None = None,
    status_code: int = status.HTTP_200_OK,
) -> Response:
    return _render_recommendations_response(
        request,
        session,
        csrf_manager,
        csrf_token,
        issued=issued,
        form_values=form_values,
        form_errors=form_errors,
        alerts=alerts,
        seed_defaults=seed_defaults,
        show_admin_controls=show_admin_controls,
        status_code=status_code,
    )


def _ensure_admin(show_admin_controls: bool) -> None:
    if not show_admin_controls:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted.")


async def _handle_queue_action(
    *,
    service: SpotifyUiService,
    request: Request,
    session: UiSession,
    csrf_manager,
    csrf_token: str,
    issued: bool,
    parsed_form: RecommendationsFormData,
    alerts: list[AlertMessage],
    normalised_values: Mapping[str, str],
    current_defaults: Mapping[str, str],
    show_admin_controls: bool,
) -> Response | None:
    if not parsed_form.queue_track_ids:
        alerts.append(
            AlertMessage(level="error", text="Select at least one recommendation to queue.")
        )
        return _render_recommendations_form(
            request=request,
            session=session,
            csrf_manager=csrf_manager,
            csrf_token=csrf_token,
            issued=issued,
            form_values=normalised_values,
            alerts=alerts,
            seed_defaults=current_defaults,
            show_admin_controls=show_admin_controls,
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    try:
        result = await service.queue_recommendation_tracks(
            parsed_form.queue_track_ids, imports_enabled=session.features.imports
        )
    except ValueError as exc:
        alerts.append(AlertMessage(level="error", text=str(exc)))
        return _render_recommendations_form(
            request=request,
            session=session,
            csrf_manager=csrf_manager,
            csrf_token=csrf_token,
            issued=issued,
            form_values=normalised_values,
            alerts=alerts,
            seed_defaults=current_defaults,
            show_admin_controls=show_admin_controls,
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except AppError as exc:
        alerts.append(AlertMessage(level="error", text=exc.message))
        log_event(
            logger,
            "ui.spotify.recommendations.queue",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
        )
        return _render_recommendations_form(
            request=request,
            session=session,
            csrf_manager=csrf_manager,
            csrf_token=csrf_token,
            issued=issued,
            form_values=normalised_values,
            alerts=alerts,
            seed_defaults=current_defaults,
            show_admin_controls=show_admin_controls,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.spotify.recommendations.queue")
        alerts.append(AlertMessage(level="error", text="Unable to queue Spotify downloads."))
        return _render_recommendations_form(
            request=request,
            session=session,
            csrf_manager=csrf_manager,
            csrf_token=csrf_token,
            issued=issued,
            form_values=normalised_values,
            alerts=alerts,
            seed_defaults=current_defaults,
            show_admin_controls=show_admin_controls,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    alerts.append(
        AlertMessage(
            level="success",
            text=(
                "Queued "
                f"{result.accepted.tracks:,} Spotify track"
                f"{'s' if result.accepted.tracks != 1 else ''} for download."
            ),
        )
    )
    log_event(
        logger,
        "ui.spotify.recommendations.queue",
        component="ui.router",
        status="success",
        role=session.role,
        count=result.accepted.tracks,
        job_id=result.job_id,
    )
    return None


def _handle_defaults_action(
    *,
    action: str,
    service: SpotifyUiService,
    parsed_form: RecommendationsFormData,
    alerts: list[AlertMessage],
    current_defaults: Mapping[str, str],
    show_admin_controls: bool,
) -> Mapping[str, str]:
    if action == "save_defaults":
        _ensure_admin(show_admin_controls)
        updated = service.save_recommendation_seed_defaults(
            seed_tracks=parsed_form.track_seeds,
            seed_artists=parsed_form.artist_seeds,
            seed_genres=parsed_form.genre_seeds,
        )
        alerts.append(AlertMessage(level="success", text="Default recommendation seeds saved."))
        return dict(updated)
    if action == "load_defaults":
        _ensure_admin(show_admin_controls)
        if not any(value.strip() for value in current_defaults.values()):
            alerts.append(
                AlertMessage(level="info", text="No default recommendation seeds are configured.")
            )
        return current_defaults
    return current_defaults


async def _process_recommendations_submission(
    *,
    request: Request,
    session: UiSession,
    service: SpotifyUiService,
    csrf_manager,
    csrf_token: str,
    issued: bool,
    parsed_form: RecommendationsFormData,
    seed_defaults: Mapping[str, str] | None,
    show_admin_controls: bool,
) -> Response:
    current_defaults = dict(seed_defaults or {})
    alerts = list(parsed_form.alerts)
    form_errors = dict(parsed_form.errors)
    normalised_values = _build_recommendation_form_values(
        artist_seeds=parsed_form.artist_seeds,
        track_seeds=parsed_form.track_seeds,
        genre_seeds=parsed_form.genre_seeds,
        limit_value=parsed_form.limit,
    )

    if form_errors or parsed_form.general_error:
        return _render_recommendations_form(
            request=request,
            session=session,
            csrf_manager=csrf_manager,
            csrf_token=csrf_token,
            issued=issued,
            form_values=parsed_form.values,
            form_errors=form_errors,
            alerts=alerts,
            seed_defaults=current_defaults,
            show_admin_controls=show_admin_controls,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if parsed_form.action == "queue":
        queue_response = await _handle_queue_action(
            service=service,
            request=request,
            session=session,
            csrf_manager=csrf_manager,
            csrf_token=csrf_token,
            issued=issued,
            parsed_form=parsed_form,
            alerts=alerts,
            normalised_values=normalised_values,
            current_defaults=current_defaults,
            show_admin_controls=show_admin_controls,
        )
        if queue_response is not None:
            return queue_response

    else:
        current_defaults = _handle_defaults_action(
            action=parsed_form.action,
            service=service,
            parsed_form=parsed_form,
            alerts=alerts,
            current_defaults=current_defaults,
            show_admin_controls=show_admin_controls,
        )

    normalised_values, result, error_response = _fetch_recommendation_rows(
        request=request,
        session=session,
        service=service,
        csrf_manager=csrf_manager,
        csrf_token=csrf_token,
        issued=issued,
        parsed_form=parsed_form,
        seed_defaults=current_defaults,
        show_admin_controls=show_admin_controls,
    )
    if error_response is not None:
        return error_response

    rows, seeds = result
    return _finalize_recommendations_success(
        request=request,
        session=session,
        csrf_manager=csrf_manager,
        csrf_token=csrf_token,
        issued=issued,
        rows=rows,
        seeds=seeds,
        form_values=normalised_values,
        alerts=tuple(alerts),
        seed_defaults=current_defaults,
        show_admin_controls=show_admin_controls,
    )


async def _read_recommendations_form(request: Request) -> Mapping[str, Sequence[str]]:
    raw_body = await request.body()
    try:
        payload = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        payload = ""
    values = parse_qs(payload)
    return {key: list(entries) for key, entries in values.items()}


def _normalize_playlist_filter(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    return candidate or None


async def _read_playlist_filter_form(request: Request) -> dict[str, str]:
    raw_body = await request.body()
    try:
        payload = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        payload = ""
    values = parse_qs(payload)

    def _first(name: str) -> str:
        entries = values.get(name)
        if entries:
            return entries[0]
        return ""

    return {
        "owner": _first("owner"),
        "status": _first("status"),
    }


def _render_spotify_playlists_fragment_response(
    *,
    request: Request,
    session: UiSession,
    csrf_manager,
    csrf_token: str,
    issued: bool,
    playlists: Sequence[SpotifyPlaylistRow],
    filter_options: SpotifyPlaylistFilters,
    owner_filter: str | None,
    status_filter: str | None,
) -> Response:
    filter_action = request.url_for("spotify_playlists_filter")
    refresh_url = request.url_for("spotify_playlists_refresh")
    table_target = "#spotify-playlists-fragment"
    force_sync_url: str | None = None
    if session.allows("admin"):
        try:
            force_sync_url = request.url_for("spotify_playlists_force_sync")
        except Exception:  # pragma: no cover - defensive guard
            force_sync_url = None

    context = build_spotify_playlists_context(
        request,
        playlists=playlists,
        csrf_token=csrf_token,
        filter_action=filter_action,
        refresh_url=refresh_url,
        table_target=table_target,
        owner_options=filter_options.owners,
        sync_status_options=filter_options.sync_statuses,
        owner_filter=owner_filter,
        status_filter=status_filter,
        force_sync_url=force_sync_url,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_playlists.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


async def _render_search_results_fragment(
    request: Request,
    session: UiSession,
    service: SearchUiService,
    *,
    raw_query: str | None,
    raw_limit: str | int | None,
    raw_offset: str | int | None,
    raw_sources: Sequence[str] | None,
) -> Response:
    if not session.features.soulseek:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested UI feature is disabled.",
        )

    query = (raw_query or "").strip()
    if not query:
        return _render_alert_fragment(
            request,
            "Please provide a search query.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    def _coerce_int(
        value: str | int | None, default: int, *, minimum: int, maximum: int | None = None
    ) -> int:
        try:
            coerced = int(value) if value not in (None, "") else default
        except (TypeError, ValueError):
            coerced = default
        if maximum is None:
            return max(minimum, coerced)
        return max(minimum, min(coerced, maximum))

    limit_value = _coerce_int(raw_limit, 25, minimum=1, maximum=100)
    offset_value = _coerce_int(raw_offset, 0, minimum=0)

    cleaned_sources: list[str] = []
    for entry in raw_sources or ():
        normalised = str(entry).strip().lower()
        if normalised and normalised not in cleaned_sources:
            cleaned_sources.append(normalised)
    resolved_sources: tuple[str, ...] = tuple(cleaned_sources) or DEFAULT_SOURCES

    try:
        page = await service.search(
            request,
            query=query,
            limit=limit_value,
            offset=offset_value,
            sources=resolved_sources,
        )
    except ValidationError:
        return _render_alert_fragment(
            request,
            "Please provide valid search parameters.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.search",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
            retry_url=str(request.url),
            retry_target="#hx-soulseek-downloads",
            retry_label_key="soulseek.retry",
        )
    except Exception:
        logger.exception("ui.fragment.search")
        log_event(
            logger,
            "ui.fragment.search",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        return _render_alert_fragment(
            request,
            "Search failed due to an unexpected error.",
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_search_results_context(
        request,
        page=page,
        query=query,
        sources=resolved_sources,
        csrf_token=csrf_token,
    )
    log_event(
        logger,
        "ui.fragment.search",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    response = templates.TemplateResponse(
        request,
        "partials/search_results.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get("/login", include_in_schema=False)
async def login_form(request: Request) -> Response:
    manager = get_session_manager(request)
    existing_id = request.cookies.get("ui_session")
    if existing_id:
        existing = await manager.get_session(existing_id)
        if existing is not None:
            return RedirectResponse("/ui", status_code=status.HTTP_303_SEE_OTHER)
    context = build_login_page_context(request, error=None)
    return templates.TemplateResponse(request, "pages/login.j2", context)


@router.post("/login", include_in_schema=False)
async def login_action(request: Request) -> Response:
    raw_body = await request.body()
    try:
        payload = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        payload = ""
    values = parse_qs(payload)
    api_key = values.get("api_key", [""])[0]
    manager = get_session_manager(request)
    try:
        session = await manager.create_session(api_key)
    except HTTPException as exc:
        if exc.status_code in {status.HTTP_400_BAD_REQUEST, status.HTTP_503_SERVICE_UNAVAILABLE}:
            message = exc.detail
        else:
            message = "Login failed."
        status_code = (
            exc.status_code
            if exc.status_code != status.HTTP_401_UNAUTHORIZED
            else status.HTTP_400_BAD_REQUEST
        )
        context = build_login_page_context(request, error=message)
        return templates.TemplateResponse(
            request,
            "pages/login.j2",
            context,
            status_code=status_code,
        )

    response = RedirectResponse("/ui", status_code=status.HTTP_303_SEE_OTHER)
    attach_session_cookie(response, session, manager)
    csrf_manager = get_csrf_manager(request)
    attach_csrf_cookie(response, session, csrf_manager)
    log_event(
        logger,
        "ui.session.created",
        component="ui.router",
        status="success",
        role=session.role,
    )
    response.headers.setdefault("HX-Redirect", "/ui")
    return response


@router.get("/", include_in_schema=False)
async def dashboard(
    request: Request,
    session: UiSession = Depends(require_session),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token = csrf_manager.issue(session)
    context = build_dashboard_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
    )
    response = templates.TemplateResponse(
        request,
        "pages/dashboard.j2",
        context,
    )
    attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get("/spotify", include_in_schema=False)
async def spotify_page(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_spotify_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
    )
    response = templates.TemplateResponse(
        request,
        "pages/spotify.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get("/soulseek", include_in_schema=False)
async def soulseek_page(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("soulseek")),
    service: SoulseekUiService = Depends(get_soulseek_ui_service),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    tasks: Sequence[SuggestedTask] = ()
    tasks_completion = 0
    try:
        connection = await service.status()
        integration = await service.integration_health()
        tasks = service.suggested_tasks(status=connection, health=integration)
        if tasks:
            completed_count = sum(1 for task in tasks if task.completed)
            tasks_completion = int(round((completed_count / len(tasks)) * 100))
        else:
            tasks_completion = 100
        soulseek_badge = build_soulseek_navigation_badge(
            connection=connection,
            integration=integration,
        )
        log_event(
            logger,
            "ui.page.soulseek.badge",
            component="ui.router",
            status="success",
            role=session.role,
            meta={
                "connection": connection.status,
                "integration": integration.overall,
                "badge_variant": soulseek_badge.variant,
                "tasks_total": len(tasks),
                "tasks_completion": tasks_completion,
            },
        )
        log_event(
            logger,
            "ui.page.soulseek.tasks",
            component="ui.router",
            status="success",
            role=session.role,
            meta={
                "tasks_total": len(tasks),
                "tasks_completion": tasks_completion,
            },
        )
    except Exception:
        logger.exception("ui.page.soulseek.badge")
        log_event(
            logger,
            "ui.page.soulseek.badge",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        soulseek_badge = build_soulseek_navigation_badge(connection=None, integration=None)
        tasks = ()
        tasks_completion = 0
    context = build_soulseek_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
        soulseek_badge=soulseek_badge,
        suggested_tasks=tasks,
        tasks_completion=tasks_completion,
    )
    response = templates.TemplateResponse(
        request,
        "pages/soulseek.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get("/soulseek/status", include_in_schema=False, name="soulseek_status_fragment")
async def soulseek_status_fragment(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("soulseek")),
    service: SoulseekUiService = Depends(get_soulseek_ui_service),
) -> Response:
    try:
        connection = await service.status()
        health = await service.integration_health()
    except Exception:
        logger.exception("ui.fragment.soulseek.status")
        log_event(
            logger,
            "ui.fragment.soulseek.status",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        return _render_alert_fragment(
            request,
            "Unable to load Soulseek status.",
            retry_url=str(request.url),
            retry_target="#hx-soulseek-status",
            retry_label_key="soulseek.retry",
        )

    soulseek_badge = build_soulseek_navigation_badge(
        connection=connection,
        integration=health,
    )
    navigation = build_primary_navigation(
        session,
        active="soulseek",
        soulseek_badge=soulseek_badge,
    )
    layout = LayoutContext(
        page_id="soulseek",
        role=session.role,
        navigation=navigation,
    )

    context = build_soulseek_status_context(
        request,
        status=connection,
        health=health,
        layout=layout,
    )
    log_event(
        logger,
        "ui.fragment.soulseek.status",
        component="ui.router",
        status="success",
        role=session.role,
    )
    return templates.TemplateResponse(
        request,
        "partials/soulseek_status.j2",
        context,
    )


@router.get(
    "/soulseek/config",
    include_in_schema=False,
    name="soulseek_configuration_fragment",
)
async def soulseek_configuration_fragment(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("soulseek")),
    service: SoulseekUiService = Depends(get_soulseek_ui_service),
) -> Response:
    try:
        soulseek_config = service.soulseek_config()
        security_config = service.security_config()
    except Exception:
        logger.exception("ui.fragment.soulseek.config")
        log_event(
            logger,
            "ui.fragment.soulseek.config",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        return _render_alert_fragment(
            request,
            "Unable to load Soulseek configuration.",
            retry_url=str(request.url),
            retry_target="#hx-soulseek-configuration",
            retry_label_key="soulseek.retry",
        )

    context = build_soulseek_config_context(
        request,
        soulseek_config=soulseek_config,
        security_config=security_config,
    )
    log_event(
        logger,
        "ui.fragment.soulseek.config",
        component="ui.router",
        status="success",
        role=session.role,
    )
    return templates.TemplateResponse(
        request,
        "partials/soulseek_config.j2",
        context,
    )


@router.get(
    "/soulseek/uploads",
    include_in_schema=False,
    name="soulseek_uploads_fragment",
)
async def soulseek_uploads_fragment(
    request: Request,
    include_all: bool = Query(False, alias="all"),
    session: UiSession = Depends(require_operator_with_feature("soulseek")),
    service: SoulseekUiService = Depends(get_soulseek_ui_service),
) -> Response:
    try:
        uploads = await service.uploads(include_all=include_all)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Unable to load uploads."
        log_event(
            logger,
            "ui.fragment.soulseek.uploads",
            component="ui.router",
            status="error",
            role=session.role,
            error=str(exc.status_code),
        )
        return _render_alert_fragment(
            request,
            detail,
            status_code=exc.status_code,
            retry_url=str(request.url),
            retry_target="#hx-soulseek-uploads",
            retry_label_key="soulseek.retry",
        )
    except Exception:
        logger.exception("ui.fragment.soulseek.uploads")
        log_event(
            logger,
            "ui.fragment.soulseek.uploads",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        return _render_alert_fragment(
            request,
            "Unable to load Soulseek uploads.",
            retry_url=str(request.url),
            retry_target="#hx-soulseek-uploads",
            retry_label_key="soulseek.retry",
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_soulseek_uploads_context(
        request,
        uploads=uploads,
        csrf_token=csrf_token,
        include_all=include_all,
        session=session,
    )
    log_event(
        logger,
        "ui.fragment.soulseek.uploads",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
        scope="all" if include_all else "active",
    )
    response = templates.TemplateResponse(
        request,
        "partials/soulseek_uploads.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get(
    "/soulseek/downloads",
    include_in_schema=False,
    name="soulseek_downloads_fragment",
)
async def soulseek_downloads_fragment(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_all: bool = Query(False, alias="all"),
    session: UiSession = Depends(require_operator_with_feature("soulseek")),
    service: DownloadsUiService = Depends(get_downloads_ui_service),
) -> Response:
    try:
        page = service.list_downloads(
            limit=limit,
            offset=offset,
            include_all=include_all,
            status_filter=None,
        )
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.soulseek.downloads",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
            retry_url=str(request.url),
            retry_target="#hx-soulseek-downloads",
            retry_label_key="soulseek.retry",
        )
    except Exception:
        logger.exception("ui.fragment.soulseek.downloads")
        log_event(
            logger,
            "ui.fragment.soulseek.downloads",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        return _render_alert_fragment(
            request,
            "Unable to load Soulseek downloads.",
            retry_url=str(request.url),
            retry_target="#hx-soulseek-downloads",
            retry_label_key="soulseek.retry",
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_soulseek_downloads_context(
        request,
        page=page,
        csrf_token=csrf_token,
        include_all=include_all,
        session=session,
    )
    log_event(
        logger,
        "ui.fragment.soulseek.downloads",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
        scope="all" if include_all else "active",
        limit=limit,
        offset=offset,
    )
    response = templates.TemplateResponse(
        request,
        "partials/downloads_table.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get(
    "/soulseek/download/{download_id}/lyrics",
    include_in_schema=False,
    name="soulseek_download_lyrics_modal",
)
async def soulseek_download_lyrics_modal(
    request: Request,
    download_id: int,
    session: UiSession = Depends(require_operator_with_feature("soulseek")),
    config: AppConfig = Depends(get_app_config),
) -> Response:
    event_name = "ui.fragment.soulseek.downloads.lyrics"
    try:
        with session_scope() as db_session:
            download = db_session.get(Download, download_id)
            if download is None:
                log_event(
                    logger,
                    event_name,
                    component="ui.router",
                    status="error",
                    role=session.role,
                    error="not_found",
                    download_id=download_id,
                )
                return _render_alert_fragment(
                    request,
                    "Download not found.",
                    status_code=status.HTTP_404_NOT_FOUND,
                    retry_url=str(request.url),
                    retry_target="#modal-root",
                    retry_label_key="soulseek.retry",
                )

            api_response = api_soulseek_download_lyrics(
                download_id=download_id,
                request=request,
                config=config,
                session=db_session,
            )

            status_code = api_response.status_code
            content: str | None = None
            pending = status_code == status.HTTP_202_ACCEPTED
            if status_code == status.HTTP_200_OK:
                try:
                    content = api_response.body.decode("utf-8")
                except UnicodeDecodeError:
                    content = api_response.body.decode("utf-8", "replace")
            elif status_code not in {status.HTTP_202_ACCEPTED}:
                log_event(
                    logger,
                    event_name,
                    component="ui.router",
                    status="error",
                    role=session.role,
                    error=str(status_code),
                    download_id=download_id,
                )
                return _render_alert_fragment(
                    request,
                    "Unable to load lyrics for this download.",
                    status_code=status_code,
                    retry_url=str(request.url),
                    retry_target="#modal-root",
                    retry_label_key="soulseek.retry",
                )

            filename = download.filename or f"Download {download_id}"
            asset_status = download.lyrics_status or ""
            has_lyrics = bool(download.has_lyrics)

        context = build_soulseek_download_lyrics_modal_context(
            request,
            download_id=download_id,
            filename=filename,
            asset_status=asset_status,
            has_lyrics=has_lyrics,
            content=content,
            pending=pending,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Unable to load lyrics."
        log_event(
            logger,
            event_name,
            component="ui.router",
            status="error",
            role=session.role,
            error=str(exc.status_code),
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            detail,
            status_code=exc.status_code,
            retry_url=str(request.url),
            retry_target="#modal-root",
            retry_label_key="soulseek.retry",
        )
    except AppError as exc:
        log_event(
            logger,
            event_name,
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
            retry_url=str(request.url),
            retry_target="#modal-root",
            retry_label_key="soulseek.retry",
        )
    except Exception:
        logger.exception("ui.fragment.soulseek.downloads.lyrics")
        log_event(
            logger,
            event_name,
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            "Unable to load lyrics for this download.",
            retry_url=str(request.url),
            retry_target="#modal-root",
            retry_label_key="soulseek.retry",
        )

    response = templates.TemplateResponse(
        request,
        "partials/soulseek_download_lyrics.j2",
        context,
    )
    log_event(
        logger,
        event_name,
        component="ui.router",
        status="success",
        role=session.role,
        download_id=download_id,
    )
    return response


@router.get(
    "/soulseek/download/{download_id}/metadata",
    include_in_schema=False,
    name="soulseek_download_metadata_modal",
)
async def soulseek_download_metadata_modal(
    request: Request,
    download_id: int,
    session: UiSession = Depends(require_operator_with_feature("soulseek")),
    config: AppConfig = Depends(get_app_config),
) -> Response:
    event_name = "ui.fragment.soulseek.downloads.metadata"
    try:
        with session_scope() as db_session:
            download = db_session.get(Download, download_id)
            if download is None:
                log_event(
                    logger,
                    event_name,
                    component="ui.router",
                    status="error",
                    role=session.role,
                    error="not_found",
                    download_id=download_id,
                )
                return _render_alert_fragment(
                    request,
                    "Download not found.",
                    status_code=status.HTTP_404_NOT_FOUND,
                    retry_url=str(request.url),
                    retry_target="#modal-root",
                    retry_label_key="soulseek.retry",
                )

            metadata_response = api_soulseek_download_metadata(
                download_id=download_id,
                session=db_session,
            )

            metadata = {
                "genre": metadata_response.genre,
                "composer": metadata_response.composer,
                "producer": metadata_response.producer,
                "isrc": metadata_response.isrc,
                "copyright": metadata_response.copyright,
            }
            filename = metadata_response.filename or (
                download.filename or f"Download {download_id}"
            )

        context = build_soulseek_download_metadata_modal_context(
            request,
            download_id=download_id,
            filename=filename,
            metadata=metadata,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Unable to load metadata."
        log_event(
            logger,
            event_name,
            component="ui.router",
            status="error",
            role=session.role,
            error=str(exc.status_code),
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            detail,
            status_code=exc.status_code,
            retry_url=str(request.url),
            retry_target="#modal-root",
            retry_label_key="soulseek.retry",
        )
    except AppError as exc:
        log_event(
            logger,
            event_name,
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
            retry_url=str(request.url),
            retry_target="#modal-root",
            retry_label_key="soulseek.retry",
        )
    except Exception:
        logger.exception("ui.fragment.soulseek.downloads.metadata")
        log_event(
            logger,
            event_name,
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            "Unable to load download metadata.",
            retry_url=str(request.url),
            retry_target="#modal-root",
            retry_label_key="soulseek.retry",
        )

    response = templates.TemplateResponse(
        request,
        "partials/soulseek_download_metadata.j2",
        context,
    )
    log_event(
        logger,
        event_name,
        component="ui.router",
        status="success",
        role=session.role,
        download_id=download_id,
    )
    return response


@router.get(
    "/soulseek/download/{download_id}/artwork",
    include_in_schema=False,
    name="soulseek_download_artwork_modal",
)
async def soulseek_download_artwork_modal(
    request: Request,
    download_id: int,
    session: UiSession = Depends(require_operator_with_feature("soulseek")),
    config: AppConfig = Depends(get_app_config),
) -> Response:
    event_name = "ui.fragment.soulseek.downloads.artwork"
    try:
        with session_scope() as db_session:
            download = db_session.get(Download, download_id)
            if download is None:
                log_event(
                    logger,
                    event_name,
                    component="ui.router",
                    status="error",
                    role=session.role,
                    error="not_found",
                    download_id=download_id,
                )
                return _render_alert_fragment(
                    request,
                    "Download not found.",
                    status_code=status.HTTP_404_NOT_FOUND,
                    retry_url=str(request.url),
                    retry_target="#modal-root",
                    retry_label_key="soulseek.retry",
                )

            api_soulseek_download_artwork(
                download_id=download_id,
                request=request,
                session=db_session,
                config=config,
            )
            filename = download.filename or f"Download {download_id}"
            asset_status = download.artwork_status or ""
            has_artwork = bool(download.has_artwork)

        try:
            image_url = request.url_for("soulseek_download_artwork", download_id=str(download_id))
        except Exception:  # pragma: no cover - fallback for tests
            image_url = f"/soulseek/download/{download_id}/artwork"

        context = build_soulseek_download_artwork_modal_context(
            request,
            download_id=download_id,
            filename=filename,
            asset_status=asset_status,
            has_artwork=has_artwork,
            image_url=image_url,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Unable to load artwork."
        log_event(
            logger,
            event_name,
            component="ui.router",
            status="error",
            role=session.role,
            error=str(exc.status_code),
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            detail,
            status_code=exc.status_code,
            retry_url=str(request.url),
            retry_target="#modal-root",
            retry_label_key="soulseek.retry",
        )
    except AppError as exc:
        log_event(
            logger,
            event_name,
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
            retry_url=str(request.url),
            retry_target="#modal-root",
            retry_label_key="soulseek.retry",
        )
    except Exception:
        logger.exception("ui.fragment.soulseek.downloads.artwork")
        log_event(
            logger,
            event_name,
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            "Unable to load artwork for this download.",
            retry_url=str(request.url),
            retry_target="#modal-root",
            retry_label_key="soulseek.retry",
        )

    response = templates.TemplateResponse(
        request,
        "partials/soulseek_download_artwork.j2",
        context,
    )
    log_event(
        logger,
        event_name,
        component="ui.router",
        status="success",
        role=session.role,
        download_id=download_id,
    )
    return response


@router.post(
    "/soulseek/downloads/{download_id}/requeue",
    include_in_schema=False,
    name="soulseek_download_requeue",
    dependencies=[Depends(enforce_csrf)],
)
async def soulseek_download_requeue(
    request: Request,
    download_id: int,
    session: UiSession = Depends(require_admin_with_feature("soulseek")),
    service: DownloadsUiService = Depends(get_downloads_ui_service),
) -> Response:
    raw_body = await request.body()
    try:
        body = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        body = ""
    values = parse_qs(body)

    def _parse_int(value: str | None, *, default: int, minimum: int, maximum: int) -> int:
        if value is None or not value.strip():
            return default
        try:
            parsed = int(value)
        except ValueError:
            return default
        return max(min(parsed, maximum), minimum)

    limit_value = _parse_int(
        (values.get("limit", [None])[0] or request.query_params.get("limit")),
        default=20,
        minimum=1,
        maximum=100,
    )
    offset_value = _parse_int(
        (values.get("offset", [None])[0] or request.query_params.get("offset")),
        default=0,
        minimum=0,
        maximum=10_000,
    )
    scope_raw = (values.get("scope", [request.query_params.get("scope")])[0] or "").lower()
    include_all = scope_raw in {"all", "true", "1", "yes"}
    if not include_all:
        include_all = request.query_params.get("all", "").lower() in {"1", "true", "all", "yes"}

    try:
        with session_scope() as db_session:
            await soulseek_requeue_download(
                download_id=download_id,
                request=request,
                session=db_session,
            )
        page = service.list_downloads(
            limit=limit_value,
            offset=offset_value,
            include_all=include_all,
            status_filter=None,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Failed to requeue download."
        log_event(
            logger,
            "ui.fragment.soulseek.downloads",
            component="ui.router",
            status="error",
            role=session.role,
            error=str(exc.status_code),
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            detail,
            status_code=exc.status_code,
        )
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.soulseek.downloads",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.fragment.soulseek.downloads.requeue")
        log_event(
            logger,
            "ui.fragment.soulseek.downloads",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            "Failed to requeue the download.",
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_soulseek_downloads_context(
        request,
        page=page,
        csrf_token=csrf_token,
        include_all=include_all,
        session=session,
    )
    log_event(
        logger,
        "ui.fragment.soulseek.downloads",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
        download_id=download_id,
        scope="all" if include_all else "active",
        limit=limit_value,
        offset=offset_value,
    )
    response = templates.TemplateResponse(
        request,
        "partials/downloads_table.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.api_route(
    "/soulseek/download/{download_id}",
    methods=["POST", "DELETE"],
    include_in_schema=False,
    name="soulseek_download_cancel",
    dependencies=[Depends(enforce_csrf)],
)
async def soulseek_download_cancel(
    request: Request,
    download_id: int,
    session: UiSession = Depends(require_admin_with_feature("soulseek")),
    service: DownloadsUiService = Depends(get_downloads_ui_service),
    client: SoulseekClient = Depends(get_soulseek_client),
) -> Response:
    raw_body = await request.body()
    try:
        body = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        body = ""
    values = parse_qs(body)

    def _parse_int(value: str | None, *, default: int, minimum: int, maximum: int) -> int:
        if value is None or not value.strip():
            return default
        try:
            parsed = int(value)
        except ValueError:
            return default
        return max(min(parsed, maximum), minimum)

    limit_value = _parse_int(
        (values.get("limit", [None])[0] or request.query_params.get("limit")),
        default=20,
        minimum=1,
        maximum=100,
    )
    offset_value = _parse_int(
        (values.get("offset", [None])[0] or request.query_params.get("offset")),
        default=0,
        minimum=0,
        maximum=10_000,
    )
    scope_raw = (values.get("scope", [request.query_params.get("scope")])[0] or "").lower()
    include_all = scope_raw in {"all", "true", "1", "yes"}
    if not include_all:
        include_all = request.query_params.get("all", "").lower() in {"1", "true", "all", "yes"}

    try:
        with session_scope() as db_session:
            await soulseek_cancel(
                download_id=download_id,
                session=db_session,
                client=client,
            )
        page = service.list_downloads(
            limit=limit_value,
            offset=offset_value,
            include_all=include_all,
            status_filter=None,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Failed to cancel download."
        log_event(
            logger,
            "ui.fragment.soulseek.downloads",
            component="ui.router",
            status="error",
            role=session.role,
            error=str(exc.status_code),
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            detail,
            status_code=exc.status_code,
        )
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.soulseek.downloads",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.fragment.soulseek.downloads.cancel")
        log_event(
            logger,
            "ui.fragment.soulseek.downloads",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            "Failed to cancel the download.",
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_soulseek_downloads_context(
        request,
        page=page,
        csrf_token=csrf_token,
        include_all=include_all,
        session=session,
    )
    log_event(
        logger,
        "ui.fragment.soulseek.downloads",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
        download_id=download_id,
        scope="all" if include_all else "active",
        limit=limit_value,
        offset=offset_value,
    )
    response = templates.TemplateResponse(
        request,
        "partials/downloads_table.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.post(
    "/soulseek/download/{download_id}/lyrics/refresh",
    include_in_schema=False,
    name="soulseek_download_lyrics_refresh",
    dependencies=[Depends(enforce_csrf)],
)
async def soulseek_download_lyrics_refresh(
    request: Request,
    download_id: int,
    session: UiSession = Depends(require_admin_with_feature("soulseek")),
    service: DownloadsUiService = Depends(get_downloads_ui_service),
    config: AppConfig = Depends(get_app_config),
) -> Response:
    values = _parse_form_body(await request.body())
    limit_value, offset_value, include_all = _extract_download_refresh_params(request, values)
    event_name = "ui.fragment.soulseek.downloads.lyrics.refresh"

    try:
        with session_scope() as db_session:
            await api_refresh_download_lyrics(
                download_id=download_id,
                request=request,
                session=db_session,
                config=config,
            )
        page = service.list_downloads(
            limit=limit_value,
            offset=offset_value,
            include_all=include_all,
            status_filter=None,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Failed to refresh lyrics."
        log_event(
            logger,
            event_name,
            component="ui.router",
            status="error",
            role=session.role,
            error=str(exc.status_code),
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            detail,
            status_code=exc.status_code,
        )
    except AppError as exc:
        log_event(
            logger,
            event_name,
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.fragment.soulseek.downloads.lyrics.refresh")
        log_event(
            logger,
            event_name,
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            "Failed to refresh lyrics for this download.",
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_soulseek_downloads_context(
        request,
        page=page,
        csrf_token=csrf_token,
        include_all=include_all,
        session=session,
    )
    response = templates.TemplateResponse(
        request,
        "partials/downloads_table.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        event_name,
        component="ui.router",
        status="success",
        role=session.role,
        download_id=download_id,
        scope="all" if include_all else "active",
        limit=limit_value,
        offset=offset_value,
        count=len(context["fragment"].table.rows),
    )
    return response


@router.post(
    "/soulseek/download/{download_id}/metadata/refresh",
    include_in_schema=False,
    name="soulseek_download_metadata_refresh",
    dependencies=[Depends(enforce_csrf)],
)
async def soulseek_download_metadata_refresh(
    request: Request,
    download_id: int,
    session: UiSession = Depends(require_admin_with_feature("soulseek")),
    service: DownloadsUiService = Depends(get_downloads_ui_service),
    config: AppConfig = Depends(get_app_config),
) -> Response:
    values = _parse_form_body(await request.body())
    limit_value, offset_value, include_all = _extract_download_refresh_params(request, values)
    event_name = "ui.fragment.soulseek.downloads.metadata.refresh"

    try:
        with session_scope() as db_session:
            await api_refresh_download_metadata(
                download_id=download_id,
                request=request,
                session=db_session,
                config=config,
            )
        page = service.list_downloads(
            limit=limit_value,
            offset=offset_value,
            include_all=include_all,
            status_filter=None,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Failed to refresh metadata."
        log_event(
            logger,
            event_name,
            component="ui.router",
            status="error",
            role=session.role,
            error=str(exc.status_code),
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            detail,
            status_code=exc.status_code,
        )
    except AppError as exc:
        log_event(
            logger,
            event_name,
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.fragment.soulseek.downloads.metadata.refresh")
        log_event(
            logger,
            event_name,
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            "Failed to refresh metadata for this download.",
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_soulseek_downloads_context(
        request,
        page=page,
        csrf_token=csrf_token,
        include_all=include_all,
        session=session,
    )
    response = templates.TemplateResponse(
        request,
        "partials/downloads_table.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        event_name,
        component="ui.router",
        status="success",
        role=session.role,
        download_id=download_id,
        scope="all" if include_all else "active",
        limit=limit_value,
        offset=offset_value,
        count=len(context["fragment"].table.rows),
    )
    return response


@router.post(
    "/soulseek/download/{download_id}/artwork/refresh",
    include_in_schema=False,
    name="soulseek_download_artwork_refresh",
    dependencies=[Depends(enforce_csrf)],
)
async def soulseek_download_artwork_refresh(
    request: Request,
    download_id: int,
    session: UiSession = Depends(require_admin_with_feature("soulseek")),
    service: DownloadsUiService = Depends(get_downloads_ui_service),
    config: AppConfig = Depends(get_app_config),
) -> Response:
    values = _parse_form_body(await request.body())
    limit_value, offset_value, include_all = _extract_download_refresh_params(request, values)
    event_name = "ui.fragment.soulseek.downloads.artwork.refresh"

    try:
        with session_scope() as db_session:
            await api_soulseek_refresh_artwork(
                download_id=download_id,
                request=request,
                session=db_session,
                config=config,
            )
        page = service.list_downloads(
            limit=limit_value,
            offset=offset_value,
            include_all=include_all,
            status_filter=None,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Failed to refresh artwork."
        log_event(
            logger,
            event_name,
            component="ui.router",
            status="error",
            role=session.role,
            error=str(exc.status_code),
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            detail,
            status_code=exc.status_code,
        )
    except AppError as exc:
        log_event(
            logger,
            event_name,
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.fragment.soulseek.downloads.artwork.refresh")
        log_event(
            logger,
            event_name,
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
            download_id=download_id,
        )
        return _render_alert_fragment(
            request,
            "Failed to refresh artwork for this download.",
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_soulseek_downloads_context(
        request,
        page=page,
        csrf_token=csrf_token,
        include_all=include_all,
        session=session,
    )
    response = templates.TemplateResponse(
        request,
        "partials/downloads_table.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        event_name,
        component="ui.router",
        status="success",
        role=session.role,
        download_id=download_id,
        scope="all" if include_all else "active",
        limit=limit_value,
        offset=offset_value,
        count=len(context["fragment"].table.rows),
    )
    return response


@router.api_route(
    "/soulseek/downloads/cleanup",
    methods=["POST", "DELETE"],
    include_in_schema=False,
    name="soulseek_downloads_cleanup",
    dependencies=[Depends(enforce_csrf)],
)
async def soulseek_downloads_cleanup(
    request: Request,
    session: UiSession = Depends(require_admin_with_feature("soulseek")),
    service: DownloadsUiService = Depends(get_downloads_ui_service),
    client: SoulseekClient = Depends(get_soulseek_client),
) -> Response:
    values = _parse_form_body(await request.body())

    def _parse_int(value: str | None, *, default: int, minimum: int, maximum: int) -> int:
        if value is None or not value.strip():
            return default
        try:
            parsed = int(value)
        except ValueError:
            return default
        return max(min(parsed, maximum), minimum)

    limit_value = _parse_int(
        values.get("limit"),
        default=20,
        minimum=1,
        maximum=100,
    )
    offset_value = _parse_int(
        values.get("offset"),
        default=0,
        minimum=0,
        maximum=10_000,
    )
    scope_raw = (values.get("scope") or request.query_params.get("scope") or "").lower()
    include_all = scope_raw in {"all", "true", "1", "yes"}
    if not include_all:
        include_all = request.query_params.get("all", "").lower() in {"1", "true", "all", "yes"}

    try:
        await soulseek_remove_completed_downloads(client=client)
        page = service.list_downloads(
            limit=limit_value,
            offset=offset_value,
            include_all=include_all,
            status_filter=None,
        )
    except HTTPException as exc:
        detail = (
            exc.detail if isinstance(exc.detail, str) else "Failed to remove completed downloads."
        )
        log_event(
            logger,
            "ui.fragment.soulseek.downloads.cleanup",
            component="ui.router",
            status="error",
            role=session.role,
            error=str(exc.status_code),
        )
        return _render_alert_fragment(
            request,
            detail,
            status_code=exc.status_code,
        )
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.soulseek.downloads.cleanup",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.fragment.soulseek.downloads.cleanup")
        log_event(
            logger,
            "ui.fragment.soulseek.downloads.cleanup",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        return _render_alert_fragment(
            request,
            "Failed to remove completed downloads.",
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_soulseek_downloads_context(
        request,
        page=page,
        csrf_token=csrf_token,
        include_all=include_all,
        session=session,
    )
    log_event(
        logger,
        "ui.fragment.soulseek.downloads.cleanup",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
        scope="all" if include_all else "active",
        limit=limit_value,
        offset=offset_value,
    )
    response = templates.TemplateResponse(
        request,
        "partials/downloads_table.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get(
    "/soulseek/user/info",
    include_in_schema=False,
    name="soulseek_user_info_fragment",
)
async def soulseek_user_info_fragment(
    request: Request,
    username: str | None = Query(None),
    session: UiSession = Depends(require_operator_with_feature("soulseek")),
    service: SoulseekUiService = Depends(get_soulseek_ui_service),
) -> Response:
    trimmed = (username or "").strip()
    profile = None
    if trimmed:
        try:
            profile = await service.user_profile(username=trimmed)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else "Unable to load user profile."
            log_event(
                logger,
                "ui.fragment.soulseek.user_info",
                component="ui.router",
                status="error",
                role=session.role,
                error=str(exc.status_code),
            )
            return _render_alert_fragment(
                request,
                detail,
                status_code=exc.status_code,
                retry_url=str(request.url),
                retry_target="#hx-soulseek-user-info",
                retry_label_key="soulseek.retry",
            )
        except Exception:
            logger.exception("ui.fragment.soulseek.user_info")
            log_event(
                logger,
                "ui.fragment.soulseek.user_info",
                component="ui.router",
                status="error",
                role=session.role,
                error="unexpected",
            )
            return _render_alert_fragment(
                request,
                "Unable to load Soulseek user profile.",
                retry_url=str(request.url),
                retry_target="#hx-soulseek-user-info",
                retry_label_key="soulseek.retry",
            )

    context = build_soulseek_user_profile_context(
        request,
        username=trimmed,
        profile=profile,
    )
    log_event(
        logger,
        "ui.fragment.soulseek.user_info",
        component="ui.router",
        status="success",
        role=session.role,
    )
    return templates.TemplateResponse(
        request,
        "partials/soulseek_user_info.j2",
        context,
    )


@router.get(
    "/soulseek/user/directory",
    include_in_schema=False,
    name="soulseek_user_directory_fragment",
)
async def soulseek_user_directory_fragment(
    request: Request,
    username: str | None = Query(None),
    path: str | None = Query(None),
    session: UiSession = Depends(require_operator_with_feature("soulseek")),
    service: SoulseekUiService = Depends(get_soulseek_ui_service),
) -> Response:
    trimmed = (username or "").strip()
    listing = None
    if trimmed:
        try:
            listing = await service.user_directory(username=trimmed, path=path)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else "Unable to load user directory."
            log_event(
                logger,
                "ui.fragment.soulseek.user_directory",
                component="ui.router",
                status="error",
                role=session.role,
                error=str(exc.status_code),
            )
            return _render_alert_fragment(
                request,
                detail,
                status_code=exc.status_code,
                retry_url=str(request.url),
                retry_target="#hx-soulseek-user-directory",
                retry_label_key="soulseek.retry",
            )
        except Exception:
            logger.exception("ui.fragment.soulseek.user_directory")
            log_event(
                logger,
                "ui.fragment.soulseek.user_directory",
                component="ui.router",
                status="error",
                role=session.role,
                error="unexpected",
            )
            return _render_alert_fragment(
                request,
                "Unable to load Soulseek user directory.",
                retry_url=str(request.url),
                retry_target="#hx-soulseek-user-directory",
                retry_label_key="soulseek.retry",
            )

    context = build_soulseek_user_directory_context(
        request,
        username=trimmed,
        path=path,
        listing=listing,
    )
    log_event(
        logger,
        "ui.fragment.soulseek.user_directory",
        component="ui.router",
        status="success",
        role=session.role,
    )
    return templates.TemplateResponse(
        request,
        "partials/soulseek_user_directory.j2",
        context,
    )


@router.post(
    "/soulseek/uploads/cancel",
    include_in_schema=False,
    name="soulseek_upload_cancel",
    dependencies=[Depends(enforce_csrf)],
)
async def soulseek_upload_cancel(
    request: Request,
    session: UiSession = Depends(require_admin_with_feature("soulseek")),
    service: SoulseekUiService = Depends(get_soulseek_ui_service),
) -> Response:
    raw_body = await request.body()
    try:
        body = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        body = ""
    values = parse_qs(body)
    upload_id = values.get("upload_id", [""])[0].strip()
    scope_value = values.get("scope", [""])[0].strip().lower()
    include_all = scope_value in {"all", "true", "1", "yes"}
    if not include_all:
        include_all = request.query_params.get("all", "").lower() in {"1", "true", "all", "yes"}

    if not upload_id:
        return _render_alert_fragment(
            request,
            "Missing upload identifier.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        await service.cancel_upload(upload_id=upload_id)
        uploads = await service.uploads(include_all=include_all)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Failed to cancel the upload."
        log_event(
            logger,
            "ui.fragment.soulseek.uploads",
            component="ui.router",
            status="error",
            role=session.role,
            error=str(exc.status_code),
            upload_id=upload_id,
        )
        return _render_alert_fragment(
            request,
            detail,
            status_code=exc.status_code,
        )
    except Exception:
        logger.exception("ui.fragment.soulseek.uploads.cancel")
        log_event(
            logger,
            "ui.fragment.soulseek.uploads",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
            upload_id=upload_id,
        )
        return _render_alert_fragment(
            request,
            "Failed to cancel the upload.",
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_soulseek_uploads_context(
        request,
        uploads=uploads,
        csrf_token=csrf_token,
        include_all=include_all,
        session=session,
    )
    log_event(
        logger,
        "ui.fragment.soulseek.uploads",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
        upload_id=upload_id,
        scope="all" if include_all else "active",
    )
    response = templates.TemplateResponse(
        request,
        "partials/soulseek_uploads.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.post(
    "/soulseek/uploads/cleanup",
    include_in_schema=False,
    name="soulseek_uploads_cleanup",
    dependencies=[Depends(enforce_csrf)],
)
async def soulseek_uploads_cleanup(
    request: Request,
    session: UiSession = Depends(require_admin_with_feature("soulseek")),
    service: SoulseekUiService = Depends(get_soulseek_ui_service),
    client: SoulseekClient = Depends(get_soulseek_client),
) -> Response:
    values = _parse_form_body(await request.body())
    scope_value = (values.get("scope") or request.query_params.get("scope") or "").lower()
    include_all = scope_value in {"all", "true", "1", "yes"}
    if not include_all:
        include_all = request.query_params.get("all", "").lower() in {"1", "true", "all", "yes"}

    try:
        await soulseek_remove_completed_uploads(client=client)
        uploads = await service.uploads(include_all=include_all)
    except HTTPException as exc:
        detail = (
            exc.detail if isinstance(exc.detail, str) else "Failed to remove completed uploads."
        )
        log_event(
            logger,
            "ui.fragment.soulseek.uploads.cleanup",
            component="ui.router",
            status="error",
            role=session.role,
            error=str(exc.status_code),
        )
        return _render_alert_fragment(
            request,
            detail,
            status_code=exc.status_code,
        )
    except Exception:
        logger.exception("ui.fragment.soulseek.uploads.cleanup")
        log_event(
            logger,
            "ui.fragment.soulseek.uploads.cleanup",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        return _render_alert_fragment(
            request,
            "Failed to remove completed uploads.",
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_soulseek_uploads_context(
        request,
        uploads=uploads,
        csrf_token=csrf_token,
        include_all=include_all,
        session=session,
    )
    log_event(
        logger,
        "ui.fragment.soulseek.uploads.cleanup",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
        scope="all" if include_all else "active",
    )
    response = templates.TemplateResponse(
        request,
        "partials/soulseek_uploads.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get("/search", include_in_schema=False)
async def search_page(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
) -> Response:
    if not session.features.soulseek:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested UI feature is disabled.",
        )
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_search_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
    )
    response = templates.TemplateResponse(
        request,
        "pages/search.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get("/admin", include_in_schema=False, name="admin_page")
async def admin_page(
    request: Request,
    session: UiSession = Depends(require_role("admin")),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_admin_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
    )
    response = templates.TemplateResponse(
        request,
        "pages/admin.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get("/settings", include_in_schema=False, name="settings_page")
async def settings_page(
    request: Request,
    session: UiSession = Depends(require_role("admin")),
    service: SettingsUiService = Depends(get_settings_ui_service),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)

    try:
        overview = service.list_settings()
    except Exception:
        logger.exception("ui.page.settings")
        overview = SettingsOverview(rows=(), updated_at=datetime.utcnow())
        context = build_settings_page_context(
            request,
            session=session,
            csrf_token=csrf_token,
            overview=overview,
        )
        alert = AlertMessage(
            level="error",
            text="Unable to load settings. Please try again shortly.",
        )
        layout: LayoutContext = context["layout"]
        context["layout"] = replace(layout, alerts=(alert,))
        status_value = "error"
    else:
        context = build_settings_page_context(
            request,
            session=session,
            csrf_token=csrf_token,
            overview=overview,
        )
        status_value = "success"

    response = templates.TemplateResponse(
        request,
        "pages/settings.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)

    log_event(
        logger,
        "ui.page.settings",
        component="ui.router",
        status=status_value,
        role=session.role,
        count=len(overview.rows),
    )
    return response


@router.get(
    "/settings/history",
    include_in_schema=False,
    name="settings_history_fragment",
)
async def settings_history_fragment(
    request: Request,
    session: UiSession = Depends(require_role("admin")),
    service: SettingsUiService = Depends(get_settings_ui_service),
) -> Response:
    try:
        history = service.list_history()
    except Exception:
        logger.exception("ui.fragment.settings.history")
        return _render_alert_fragment(
            request,
            "Unable to load the settings history.",
            retry_url="/ui/settings/history",
            retry_target="#hx-settings-history",
        )

    context = build_settings_history_fragment_context(
        request,
        rows=history.rows,
    )
    log_event(
        logger,
        "ui.fragment.settings.history",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/settings_history.j2",
        context,
    )


@router.get(
    "/settings/artist-preferences",
    include_in_schema=False,
    name="settings_artist_preferences_fragment",
)
async def settings_artist_preferences_fragment(
    request: Request,
    session: UiSession = Depends(require_role("admin")),
    service: SettingsUiService = Depends(get_settings_ui_service),
) -> Response:
    try:
        table = service.list_artist_preferences()
    except Exception:
        logger.exception("ui.fragment.settings.artist_preferences")
        return _render_alert_fragment(
            request,
            "Unable to load artist preferences.",
            retry_url="/ui/settings/artist-preferences",
            retry_target="#hx-settings-artist-preferences",
        )

    csrf_token = request.cookies.get("csrftoken", "")
    context = build_settings_artist_preferences_fragment_context(
        request,
        rows=table.rows,
        csrf_token=csrf_token,
    )
    log_event(
        logger,
        "ui.fragment.settings.artist_preferences",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/settings_artist_preferences.j2",
        context,
    )


@router.post(
    "/settings",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def settings_save(
    request: Request,
    session: UiSession = Depends(require_role("admin")),
    service: SettingsUiService = Depends(get_settings_ui_service),
) -> Response:
    values = _parse_form_body(await request.body())
    key = values.get("key", "").strip()
    if not key:
        return _render_alert_fragment(
            request,
            "Please provide a setting key.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    raw_value = values.get("value")
    value = raw_value.strip() if raw_value is not None else None
    if value == "":
        value = None

    try:
        overview = service.save_setting(key=key, value=value)
    except HTTPException as exc:
        return _render_alert_fragment(
            request,
            exc.detail if isinstance(exc.detail, str) else "Failed to save the setting.",
            status_code=exc.status_code,
        )
    except Exception:
        logger.exception("ui.fragment.settings.save")
        return _render_alert_fragment(
            request,
            "Failed to save the setting.",
        )

    context = build_settings_form_fragment_context(
        request,
        overview=overview,
    )
    context["csrf_token"] = request.cookies.get("csrftoken", "")
    log_event(
        logger,
        "ui.fragment.settings.save",
        component="ui.router",
        status="success",
        role=session.role,
        key=key,
    )
    return templates.TemplateResponse(
        request,
        "partials/settings_form.j2",
        context,
    )


@router.post(
    "/settings/artist-preferences",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def settings_artist_preferences_save(
    request: Request,
    session: UiSession = Depends(require_role("admin")),
    service: SettingsUiService = Depends(get_settings_ui_service),
) -> Response:
    values = _parse_form_body(await request.body())
    action = values.get("action", "").strip().lower()
    artist_id = values.get("artist_id", "").strip()
    release_id = values.get("release_id", "").strip()

    if action == "add":
        if not artist_id or not release_id:
            return _render_alert_fragment(
                request,
                "Artist and release identifiers are required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        selected_raw = values.get("selected", "")
        selected = selected_raw.lower() in {"on", "true", "1", "yes"}

        def handler():
            return service.add_or_update_artist_preference(
                artist_id=artist_id,
                release_id=release_id,
                selected=selected,
            )

    elif action == "toggle":
        if not artist_id or not release_id:
            return _render_alert_fragment(
                request,
                "Artist and release identifiers are required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        selected_raw = values.get("selected", "false")
        selected = selected_raw.lower() in {"true", "1", "yes", "on"}

        def handler():
            return service.add_or_update_artist_preference(
                artist_id=artist_id,
                release_id=release_id,
                selected=selected,
            )

    elif action == "remove":
        if not artist_id or not release_id:
            return _render_alert_fragment(
                request,
                "Artist and release identifiers are required.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        def handler():
            return service.remove_artist_preference(
                artist_id=artist_id,
                release_id=release_id,
            )

    else:
        return _render_alert_fragment(
            request,
            "Unsupported action.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        table = handler()
    except HTTPException as exc:
        return _render_alert_fragment(
            request,
            exc.detail if isinstance(exc.detail, str) else "Failed to update artist preferences.",
            status_code=exc.status_code,
        )
    except Exception:
        logger.exception("ui.fragment.settings.artist_preferences.save")
        return _render_alert_fragment(
            request,
            "Failed to update artist preferences.",
        )

    csrf_token = request.cookies.get("csrftoken", "")
    context = build_settings_artist_preferences_fragment_context(
        request,
        rows=table.rows,
        csrf_token=csrf_token,
    )
    log_event(
        logger,
        "ui.fragment.settings.artist_preferences.save",
        component="ui.router",
        status="success",
        role=session.role,
        action=action,
    )
    return templates.TemplateResponse(
        request,
        "partials/settings_artist_preferences.j2",
        context,
    )


@router.get("/system", include_in_schema=False, name="system_page")
async def system_page(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_system_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
    )
    response = templates.TemplateResponse(
        request,
        "pages/system.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get(
    "/system/liveness",
    include_in_schema=False,
    name="system_liveness_fragment",
)
async def system_liveness_fragment(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    service: SystemUiService = Depends(get_system_ui_service),
) -> Response:
    try:
        summary = await service.fetch_liveness(request)
    except AppError as exc:
        message = exc.message or "Unable to load liveness information."
        return _render_alert_fragment(
            request,
            message,
            status_code=status.HTTP_200_OK,
            retry_url="/ui/system/liveness",
            retry_target="#hx-system-liveness",
        )
    except Exception:
        logger.exception("system.ui.liveness.fragment")
        return _render_alert_fragment(
            request,
            "Failed to load liveness information.",
            retry_url="/ui/system/liveness",
            retry_target="#hx-system-liveness",
        )

    context = build_system_liveness_context(request, summary=summary)
    return templates.TemplateResponse(
        request,
        "partials/system_liveness.j2",
        context,
    )


@router.get(
    "/system/readiness",
    include_in_schema=False,
    name="system_readiness_fragment",
)
async def system_readiness_fragment(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    service: SystemUiService = Depends(get_system_ui_service),
) -> Response:
    try:
        summary = await service.fetch_readiness(request)
    except AppError as exc:
        message = exc.message or "Unable to load readiness information."
        return _render_alert_fragment(
            request,
            message,
            status_code=status.HTTP_200_OK,
            retry_url="/ui/system/readiness",
            retry_target="#hx-system-readiness",
        )
    except Exception:
        logger.exception("system.ui.readiness.fragment")
        return _render_alert_fragment(
            request,
            "Failed to load readiness information.",
            retry_url="/ui/system/readiness",
            retry_target="#hx-system-readiness",
        )

    context = build_system_readiness_context(request, summary=summary)
    return templates.TemplateResponse(
        request,
        "partials/system_readiness.j2",
        context,
    )


@router.get(
    "/system/integrations",
    include_in_schema=False,
    name="system_integrations_fragment",
)
async def system_integrations_fragment(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    service: SystemUiService = Depends(get_system_ui_service),
) -> Response:
    try:
        summary = await service.fetch_integrations()
    except AppError as exc:
        message = exc.message or "Unable to load integration status."
        return _render_alert_fragment(
            request,
            message,
            status_code=status.HTTP_200_OK,
            retry_url="/ui/system/integrations",
            retry_target="#hx-system-integrations",
        )
    except Exception:
        logger.exception("system.ui.integrations.fragment")
        return _render_alert_fragment(
            request,
            "Failed to load integration status.",
            retry_url="/ui/system/integrations",
            retry_target="#hx-system-integrations",
        )

    context = build_system_integrations_context(request, summary=summary)
    return templates.TemplateResponse(
        request,
        "partials/system_integrations.j2",
        context,
    )


@router.get(
    "/system/services",
    include_in_schema=False,
    name="system_services_fragment",
)
async def system_services_fragment(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    service: SystemUiService = Depends(get_system_ui_service),
) -> Response:
    try:
        badges = await service.fetch_service_badges()
    except AppError as exc:
        message = exc.message or "Failed to load service health."
        return _render_alert_fragment(
            request,
            message,
            status_code=status.HTTP_200_OK,
            retry_url="/ui/system/services",
            retry_target="#hx-system-services",
        )
    except Exception:
        logger.exception("system.ui.services.fragment")
        return _render_alert_fragment(
            request,
            "Failed to load service health.",
            retry_url="/ui/system/services",
            retry_target="#hx-system-services",
        )

    context = build_system_service_health_context(request, badges=badges)
    return templates.TemplateResponse(
        request,
        "partials/system_services.j2",
        context,
    )


@router.get(
    "/system/secrets/{provider}",
    include_in_schema=False,
    name="system_secret_card",
)
async def system_secret_card(
    provider: str,
    request: Request,
    session: UiSession = Depends(require_role("operator")),
) -> Response:
    cards = build_system_secret_cards()
    card = select_system_secret_card(cards, provider)
    if card is None:
        return _render_alert_fragment(
            request,
            "Unknown secret provider requested.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_system_secret_card_context(
        request,
        card=card,
        csrf_token=csrf_token,
    )
    response = templates.TemplateResponse(
        request,
        "partials/system_secret_card.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.post(
    "/system/secrets/{provider}",
    include_in_schema=False,
    name="system_validate_secret",
    dependencies=[Depends(enforce_csrf)],
)
async def system_validate_secret(
    provider: str,
    request: Request,
    session: UiSession = Depends(require_admin_with_feature("imports")),
    service: SystemUiService = Depends(get_system_ui_service),
    db_session: Session = Depends(get_db),
) -> Response:
    cards = build_system_secret_cards()
    base_card = select_system_secret_card(cards, provider)
    if base_card is None:
        return _render_alert_fragment(
            request,
            "Unknown secret provider requested.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    target_selector = f"#{base_card.target_id}"

    form_values = _parse_form_body(await request.body())
    override_value = form_values.get("value", "")
    override_value = override_value.strip() or None

    try:
        result = await service.validate_secret(
            request,
            provider=provider,
            override=override_value,
            session=db_session,
        )
    except AppError as exc:
        message = exc.message or "Secret validation failed."
        return _render_alert_fragment(
            request,
            message,
            status_code=status.HTTP_200_OK,
            retry_url=f"/ui/system/secrets/{base_card.provider}",
            retry_target=target_selector,
        )
    except Exception:
        logger.exception("system.ui.secret.validate")
        return _render_alert_fragment(
            request,
            "Secret validation failed.",
            retry_url=f"/ui/system/secrets/{base_card.provider}",
            retry_target=target_selector,
        )

    updated_card = attach_secret_result(base_card, result)
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_system_secret_card_context(
        request,
        card=updated_card,
        csrf_token=csrf_token,
    )
    response = templates.TemplateResponse(
        request,
        "partials/system_secret_card.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get("/operations", include_in_schema=False, name="operations_page")
async def operations_page(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_operations_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
    )
    response = templates.TemplateResponse(
        request,
        "pages/operations.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get("/downloads", include_in_schema=False, name="downloads_page")
async def downloads_page(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
) -> Response:
    if not session.features.dlq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested UI feature is disabled.",
        )
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_downloads_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
    )
    response = templates.TemplateResponse(
        request,
        "pages/downloads.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get("/jobs", include_in_schema=False, name="jobs_page")
async def jobs_page(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
) -> Response:
    if not session.features.dlq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested UI feature is disabled.",
        )
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_jobs_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
    )
    response = templates.TemplateResponse(
        request,
        "pages/jobs.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get("/watchlist", include_in_schema=False, name="watchlist_page")
async def watchlist_page(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_watchlist_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
    )
    response = templates.TemplateResponse(
        request,
        "pages/watchlist.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get("/activity", include_in_schema=False, name="activity_page")
async def activity_page(
    request: Request,
    session: UiSession = Depends(require_session),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_activity_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
    )
    response = templates.TemplateResponse(
        request,
        "pages/activity.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.post(
    "/logout",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def logout(
    request: Request,
    session: UiSession = Depends(require_session),
) -> Response:
    manager = get_session_manager(request)
    await clear_spotify_job_state(request, session)
    await manager.invalidate(session.identifier)
    response = RedirectResponse("/ui/login", status_code=status.HTTP_303_SEE_OTHER)
    clear_session_cookie(response)
    clear_csrf_cookie(response)
    log_event(
        logger,
        "ui.session.ended",
        component="ui.router",
        status="success",
        role=session.role,
    )
    response.headers.setdefault("HX-Redirect", "/ui/login")
    return response


@router.post(
    "/spotify/oauth/start",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_oauth_start(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    try:
        authorization_url = service.start_oauth()
    except ValueError as exc:
        logger.warning("spotify.ui.oauth.start.error", extra={"error": str(exc)})
        return _render_alert_fragment(
            request,
            str(exc) or "Spotify OAuth is currently unavailable.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    response = RedirectResponse(authorization_url, status_code=status.HTTP_303_SEE_OTHER)
    response.headers.setdefault("HX-Redirect", authorization_url)
    log_event(
        logger,
        "ui.spotify.oauth.start",
        component="ui.router",
        status="success",
        role=session.role,
    )
    return response


@router.post(
    "/spotify/oauth/manual",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_oauth_manual(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    raw_body = await request.body()
    try:
        payload = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        payload = ""
    values = parse_qs(payload)
    redirect_url = values.get("redirect_url", [""])[0].strip()
    if not redirect_url:
        return _render_alert_fragment(
            request,
            "A redirect URL from Spotify is required.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    result = await service.manual_complete(redirect_url=redirect_url)
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    manual_form = FormDefinition(
        identifier="spotify-manual-form",
        method="post",
        action="/ui/spotify/oauth/manual",
        submit_label_key="spotify.manual.submit",
    )
    context = build_spotify_status_context(
        request,
        status=service.status(),
        oauth=service.oauth_health(),
        manual_form=manual_form,
        csrf_token=csrf_token,
        manual_result=result,
        manual_redirect_url=redirect_url if not result.ok else None,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_status.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        "ui.spotify.oauth.manual",
        component="ui.router",
        status="success" if result.ok else "error",
        role=session.role,
    )
    return response


@router.post(
    "/spotify/free/run",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_free_ingest_run(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    _ensure_imports_feature_enabled(session)

    raw_body = await request.body()
    try:
        payload = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        payload = ""
    values = parse_qs(payload)
    playlist_raw = values.get("playlist_links", [""])[0]
    tracks_raw = values.get("tracks", [""])[0]
    form_values = {"playlist_links": playlist_raw, "tracks": tracks_raw}
    playlist_links = _split_ingest_lines(playlist_raw)
    track_entries = _split_ingest_lines(tracks_raw)

    alerts: list[AlertMessage] = []
    form_errors: dict[str, str] = {}
    result: SpotifyFreeIngestResult | None

    if not playlist_links and not track_entries:
        message = "Provide at least one playlist link or track entry."
        form_errors["playlist_links"] = message
        alerts.append(AlertMessage(level="error", text=message))
        result = None
        service.consume_free_ingest_feedback()
    else:
        awaited_result = await service.free_import(
            playlist_links=playlist_links or None,
            tracks=track_entries or None,
        )
        stored_result, stored_error = service.consume_free_ingest_feedback()
        result = stored_result or awaited_result
        message = stored_error or (result.error if result else None)
        if result and message and not result.ok:
            alerts.append(AlertMessage(level="error", text=message))
        elif result and result.job_id:
            alerts.append(
                AlertMessage(
                    level="success",
                    text=f"Free ingest job {result.job_id} enqueued.",
                )
            )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)

    stored_job_id = await get_spotify_free_ingest_job_id(request, session)
    if result and result.ok and result.job_id:
        stored_job_id = result.job_id
        await set_spotify_free_ingest_job_id(request, session, result.job_id)

    job_status = service.free_ingest_job_status(stored_job_id)

    context = build_spotify_free_ingest_context(
        request,
        csrf_token=csrf_token,
        form_values=form_values,
        form_errors=form_errors,
        result=result,
        job_status=job_status,
        alerts=alerts,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_free_ingest.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)

    if result is not None:
        log_event(
            logger,
            "ui.spotify.free_ingest.run",
            component="ui.router",
            status="success" if result.ok else "error",
            role=session.role,
            job_id=result.job_id,
        )
    return response


@router.post(
    "/spotify/free/upload",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_free_ingest_upload(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    _ensure_imports_feature_enabled(session)

    content_type = request.headers.get("content-type") or ""
    body = await request.body()
    try:
        filename, content = _parse_multipart_file(content_type, body)
    except ValueError as exc:
        message = str(exc) or "Select a track list file to upload."
        return _render_alert_fragment(
            request,
            message,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        awaited_result = await service.upload_free_ingest_file(
            filename=filename,
            content=content,
        )
    except ValueError as exc:
        message = str(exc) or "The uploaded file could not be processed."
        return _render_alert_fragment(
            request,
            message,
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        logger.exception("ui.spotify.free_ingest.upload_error")
        return _render_alert_fragment(
            request,
            "Failed to process the uploaded file.",
        )

    result, stored_error = service.consume_free_ingest_feedback()
    result = result or awaited_result

    alerts: list[AlertMessage] = []
    form_errors: dict[str, str] = {}
    if result and stored_error and not result.ok:
        form_errors["upload"] = stored_error
        alerts.append(AlertMessage(level="error", text=stored_error))
    elif result and result.error and not result.ok:
        form_errors["upload"] = result.error
        alerts.append(AlertMessage(level="error", text=result.error))
    elif result and result.job_id:
        alerts.append(
            AlertMessage(
                level="success",
                text=f"Free ingest job {result.job_id} enqueued.",
            )
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)

    stored_job_id = await get_spotify_free_ingest_job_id(request, session)
    if result and result.ok and result.job_id:
        stored_job_id = result.job_id
        await set_spotify_free_ingest_job_id(request, session, result.job_id)

    job_status = service.free_ingest_job_status(stored_job_id)

    context = build_spotify_free_ingest_context(
        request,
        csrf_token=csrf_token,
        form_values={"playlist_links": "", "tracks": ""},
        form_errors=form_errors,
        result=result,
        job_status=job_status,
        alerts=alerts,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_free_ingest.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)

    if result is not None:
        log_event(
            logger,
            "ui.spotify.free_ingest.upload",
            component="ui.router",
            status="success" if result.ok else "error",
            role=session.role,
            job_id=result.job_id,
        )
    return response


@router.post(
    "/spotify/backfill/run",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_backfill_run(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    raw_body = await request.body()
    try:
        payload = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        payload = ""
    values = parse_qs(payload)
    max_items_raw = values.get("max_items", [""])[0].strip()
    expand_playlists = "expand_playlists" in values
    max_items: int | None
    if max_items_raw:
        try:
            max_items = int(max_items_raw)
            if max_items < 1:
                raise ValueError
        except ValueError:
            return _render_alert_fragment(
                request,
                "Max items must be a positive integer.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
    else:
        max_items = None

    try:
        job_id = await service.run_backfill(
            max_items=max_items,
            expand_playlists=expand_playlists,
        )
    except PermissionError as exc:
        logger.warning("spotify.ui.backfill.denied", extra={"error": str(exc)})
        return _render_alert_fragment(
            request,
            "Spotify authentication is required before running backfill.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    except Exception:
        logger.exception("spotify.ui.backfill.error")
        return _render_alert_fragment(
            request,
            "Failed to enqueue the backfill job.",
        )

    await set_spotify_backfill_job_id(request, session, job_id)
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    status_payload = service.backfill_status(job_id)
    snapshot = service.build_backfill_snapshot(
        csrf_token=csrf_token,
        job_id=job_id,
        status_payload=status_payload,
    )
    alert = AlertMessage(level="success", text=f"Backfill job {job_id} enqueued.")
    context = build_spotify_backfill_context(
        request,
        snapshot=snapshot,
        alert=alert,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_backfill.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        "ui.spotify.backfill.run",
        component="ui.router",
        status="success",
        role=session.role,
        job_id=job_id,
    )
    return response


@router.post(
    "/spotify/backfill/pause",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_backfill_pause(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    return await _handle_backfill_action(
        request,
        session,
        service,
        action=lambda svc, job_id: svc.pause_backfill(job_id),
        success_message="Backfill job {job_id} paused.",
        event_key="ui.spotify.backfill.pause",
    )


@router.post(
    "/spotify/backfill/resume",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_backfill_resume(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    return await _handle_backfill_action(
        request,
        session,
        service,
        action=lambda svc, job_id: svc.resume_backfill(job_id),
        success_message="Backfill job {job_id} resumed.",
        event_key="ui.spotify.backfill.resume",
    )


@router.post(
    "/spotify/backfill/cancel",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_backfill_cancel(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    return await _handle_backfill_action(
        request,
        session,
        service,
        action=lambda svc, job_id: svc.cancel_backfill(job_id),
        success_message="Backfill job {job_id} cancelled.",
        event_key="ui.spotify.backfill.cancel",
    )


@router.get("/activity/table", include_in_schema=False)
async def activity_table(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    type_filter: str | None = Query(None, alias="type"),
    status_filter: str | None = Query(None, alias="status"),
    session: UiSession = Depends(require_session),
    service: ActivityUiService = Depends(get_activity_ui_service),
) -> Response:
    try:
        page = service.list_activity(
            limit=limit,
            offset=offset,
            type_filter=type_filter,
            status_filter=status_filter,
        )
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.activity",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.fragment.activity", extra={"limit": limit, "offset": offset})
        log_event(
            logger,
            "ui.fragment.activity",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        return _render_alert_fragment(
            request,
            "Unable to load activity entries.",
        )

    context = build_activity_fragment_context(
        request,
        items=page.items,
        limit=page.limit,
        offset=page.offset,
        total_count=page.total_count,
        type_filter=page.type_filter,
        status_filter=page.status_filter,
    )
    log_event(
        logger,
        "ui.fragment.activity",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/activity_table.j2",
        context,
    )


@router.get(
    "/spotify/free",
    include_in_schema=False,
    name="spotify_free_ingest_fragment",
)
async def spotify_free_ingest_fragment(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    _ensure_imports_feature_enabled(session)

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    job_id = await get_spotify_free_ingest_job_id(request, session)
    job_status = service.free_ingest_job_status(job_id)
    context = build_spotify_free_ingest_context(
        request,
        csrf_token=csrf_token,
        job_status=job_status,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_free_ingest.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get("/spotify/account", include_in_schema=False, name="spotify_account_fragment")
async def spotify_account_fragment(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    try:
        summary = service.account()
    except Exception:
        logger.exception("ui.fragment.spotify.account")
        return _render_alert_fragment(
            request,
            "Unable to load Spotify account details.",
        )

    try:
        refresh_action = request.url_for("spotify_account_refresh")
    except Exception:  # pragma: no cover - fallback for tests
        refresh_action = "/ui/spotify/account/refresh"
    show_reset = session.allows("admin")
    reset_action: str | None
    if show_reset:
        try:
            reset_action = request.url_for("spotify_account_reset_scopes")
        except Exception:  # pragma: no cover - fallback for tests
            reset_action = "/ui/spotify/account/reset-scopes"
    else:
        reset_action = None

    context = build_spotify_account_context(
        request,
        account=summary,
        csrf_token=csrf_token,
        refresh_action=refresh_action,
        show_refresh=True,
        show_reset=show_reset,
        reset_action=reset_action,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_account.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        "ui.fragment.spotify.account",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fields"]),
    )
    return response


@router.post(
    "/spotify/account/refresh",
    include_in_schema=False,
    name="spotify_account_refresh",
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_account_refresh(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    try:
        summary = service.refresh_account()
    except Exception:
        logger.exception("ui.fragment.spotify.account.refresh")
        return _render_alert_fragment(
            request,
            "Unable to refresh Spotify account details.",
        )

    try:
        refresh_action = request.url_for("spotify_account_refresh")
    except Exception:  # pragma: no cover - fallback for tests
        refresh_action = "/ui/spotify/account/refresh"
    show_reset = session.allows("admin")
    reset_action: str | None
    if show_reset:
        try:
            reset_action = request.url_for("spotify_account_reset_scopes")
        except Exception:  # pragma: no cover - fallback for tests
            reset_action = "/ui/spotify/account/reset-scopes"
    else:
        reset_action = None

    context = build_spotify_account_context(
        request,
        account=summary,
        csrf_token=csrf_token,
        refresh_action=refresh_action,
        show_refresh=True,
        show_reset=show_reset,
        reset_action=reset_action,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_account.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        "ui.fragment.spotify.account.refresh",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fields"]),
    )
    return response


@router.post(
    "/spotify/account/reset-scopes",
    include_in_schema=False,
    name="spotify_account_reset_scopes",
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_account_reset_scopes(
    request: Request,
    session: UiSession = Depends(require_role("admin")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    if not session.features.spotify:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested UI feature is disabled.",
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    try:
        summary = service.reset_scopes()
    except Exception:
        logger.exception("ui.fragment.spotify.account.reset_scopes")
        return _render_alert_fragment(
            request,
            "Unable to reset Spotify scopes.",
        )

    try:
        refresh_action = request.url_for("spotify_account_refresh")
    except Exception:  # pragma: no cover - fallback for tests
        refresh_action = "/ui/spotify/account/refresh"
    try:
        reset_action = request.url_for("spotify_account_reset_scopes")
    except Exception:  # pragma: no cover - fallback for tests
        reset_action = "/ui/spotify/account/reset-scopes"

    context = build_spotify_account_context(
        request,
        account=summary,
        csrf_token=csrf_token,
        refresh_action=refresh_action,
        show_refresh=True,
        show_reset=True,
        reset_action=reset_action,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_account.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        "ui.fragment.spotify.account.reset_scopes",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fields"]),
    )
    return response


@router.get("/spotify/top/tracks", include_in_schema=False, name="spotify_top_tracks_fragment")
async def spotify_top_tracks_fragment(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    time_range = _extract_time_range(request)
    try:
        tracks = service.top_tracks(time_range=time_range)
    except Exception:
        logger.exception("ui.fragment.spotify.top_tracks")
        return _render_alert_fragment(
            request,
            "Unable to load Spotify top tracks.",
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    limit, offset = _extract_saved_tracks_pagination(request)
    context = build_spotify_top_tracks_context(
        request,
        tracks=tracks,
        csrf_token=csrf_token,
        limit=limit,
        offset=offset,
        time_range=time_range,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_top_tracks.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        "ui.fragment.spotify.top_tracks",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return response


@router.get("/spotify/top/artists", include_in_schema=False, name="spotify_top_artists_fragment")
async def spotify_top_artists_fragment(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    time_range = _extract_time_range(request)
    try:
        artists = service.top_artists(time_range=time_range)
    except Exception:
        logger.exception("ui.fragment.spotify.top_artists")
        return _render_alert_fragment(
            request,
            "Unable to load Spotify top artists.",
        )

    context = build_spotify_top_artists_context(
        request,
        artists=artists,
        time_range=time_range,
    )
    log_event(
        logger,
        "ui.fragment.spotify.top_artists",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/spotify_top_artists.j2",
        context,
    )


@router.get("/spotify/backfill", include_in_schema=False, name="spotify_backfill_fragment")
async def spotify_backfill_fragment(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    job_id = await get_spotify_backfill_job_id(request, session)
    status_payload = service.backfill_status(job_id)
    snapshot = service.build_backfill_snapshot(
        csrf_token=csrf_token,
        job_id=job_id,
        status_payload=status_payload,
    )
    timeline = service.backfill_timeline(limit=_SPOTIFY_BACKFILL_TIMELINE_LIMIT)
    context = build_spotify_backfill_context(request, snapshot=snapshot, timeline=timeline)
    response = templates.TemplateResponse(
        request,
        "partials/spotify_backfill.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


@router.get("/spotify/artists", include_in_schema=False, name="spotify_artists_fragment")
async def spotify_artists_fragment(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    try:
        artists = service.list_followed_artists()
    except Exception:
        logger.exception("ui.fragment.spotify.artists")
        return _render_alert_fragment(
            request,
            "Unable to load Spotify artists.",
        )
    context = build_spotify_artists_context(request, artists=artists)
    log_event(
        logger,
        "ui.fragment.spotify.artists",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/spotify_artists.j2",
        context,
    )


@router.get("/spotify/playlists", include_in_schema=False, name="spotify_playlists_fragment")
async def spotify_playlists_fragment(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    owner_filter = _normalize_playlist_filter(request.query_params.get("owner"))
    status_filter = _normalize_playlist_filter(request.query_params.get("status"))
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    try:
        filter_options = service.playlist_filters()
        playlists = service.list_playlists(
            owner=owner_filter,
            sync_status=status_filter,
        )
    except Exception:
        logger.exception("ui.fragment.spotify.playlists")
        return _render_alert_fragment(
            request,
            "Unable to load Spotify playlists.",
        )
    response = _render_spotify_playlists_fragment_response(
        request=request,
        session=session,
        csrf_manager=csrf_manager,
        csrf_token=csrf_token,
        issued=issued,
        playlists=playlists,
        filter_options=filter_options,
        owner_filter=owner_filter,
        status_filter=status_filter,
    )
    log_event(
        logger,
        "ui.fragment.spotify.playlists",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(playlists),
        owner_filter=owner_filter,
        status_filter=status_filter,
    )
    return response


@router.post(
    "/spotify/playlists/filter",
    include_in_schema=False,
    name="spotify_playlists_filter",
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_playlists_filter(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    form = await _read_playlist_filter_form(request)
    owner_filter = _normalize_playlist_filter(form.get("owner"))
    status_filter = _normalize_playlist_filter(form.get("status"))
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    try:
        filter_options = service.playlist_filters()
        playlists = service.list_playlists(
            owner=owner_filter,
            sync_status=status_filter,
        )
    except Exception:
        logger.exception("ui.fragment.spotify.playlists.filter")
        return _render_alert_fragment(
            request,
            "Unable to load Spotify playlists.",
        )
    response = _render_spotify_playlists_fragment_response(
        request=request,
        session=session,
        csrf_manager=csrf_manager,
        csrf_token=csrf_token,
        issued=issued,
        playlists=playlists,
        filter_options=filter_options,
        owner_filter=owner_filter,
        status_filter=status_filter,
    )
    log_event(
        logger,
        "ui.fragment.spotify.playlists.filter",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(playlists),
        owner_filter=owner_filter,
        status_filter=status_filter,
    )
    return response


@router.post(
    "/spotify/playlists/refresh",
    include_in_schema=False,
    name="spotify_playlists_refresh",
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_playlists_refresh(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    form = await _read_playlist_filter_form(request)
    owner_filter = _normalize_playlist_filter(form.get("owner"))
    status_filter = _normalize_playlist_filter(form.get("status"))
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    try:
        await service.refresh_playlists()
        filter_options = service.playlist_filters()
        playlists = service.list_playlists(
            owner=owner_filter,
            sync_status=status_filter,
        )
    except Exception:
        logger.exception("ui.spotify.playlists.refresh")
        return _render_alert_fragment(
            request,
            "Unable to refresh Spotify playlists.",
        )
    response = _render_spotify_playlists_fragment_response(
        request=request,
        session=session,
        csrf_manager=csrf_manager,
        csrf_token=csrf_token,
        issued=issued,
        playlists=playlists,
        filter_options=filter_options,
        owner_filter=owner_filter,
        status_filter=status_filter,
    )
    log_event(
        logger,
        "ui.spotify.playlists.refresh",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(playlists),
        owner_filter=owner_filter,
        status_filter=status_filter,
    )
    return response


@router.post(
    "/spotify/playlists/force-sync",
    include_in_schema=False,
    name="spotify_playlists_force_sync",
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_playlists_force_sync(
    request: Request,
    session: UiSession = Depends(require_role("admin")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    if not session.features.spotify:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested UI feature is disabled.",
        )
    form = await _read_playlist_filter_form(request)
    owner_filter = _normalize_playlist_filter(form.get("owner"))
    status_filter = _normalize_playlist_filter(form.get("status"))
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    try:
        await service.force_sync_playlists()
        filter_options = service.playlist_filters()
        playlists = service.list_playlists(
            owner=owner_filter,
            sync_status=status_filter,
        )
    except Exception:
        logger.exception("ui.spotify.playlists.force_sync")
        return _render_alert_fragment(
            request,
            "Unable to force sync Spotify playlists.",
        )
    response = _render_spotify_playlists_fragment_response(
        request=request,
        session=session,
        csrf_manager=csrf_manager,
        csrf_token=csrf_token,
        issued=issued,
        playlists=playlists,
        filter_options=filter_options,
        owner_filter=owner_filter,
        status_filter=status_filter,
    )
    log_event(
        logger,
        "ui.spotify.playlists.force_sync",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(playlists),
        owner_filter=owner_filter,
        status_filter=status_filter,
    )
    return response


@router.get(
    "/spotify/playlists/{playlist_id}/tracks",
    include_in_schema=False,
    name="spotify_playlist_items_fragment",
)
async def spotify_playlist_items_fragment(
    request: Request,
    playlist_id: str,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    playlist_name: str | None = Query(None, alias="name"),
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    try:
        rows, total, page_limit, page_offset = service.playlist_items(
            playlist_id, limit=limit, offset=offset
        )
    except ValueError as exc:
        return _render_alert_fragment(
            request,
            str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        logger.exception("ui.fragment.spotify.playlist_items")
        return _render_alert_fragment(
            request,
            "Unable to load Spotify playlist tracks.",
        )

    context = build_spotify_playlist_items_context(
        request,
        playlist_id=playlist_id,
        playlist_name=playlist_name,
        rows=rows,
        total_count=total,
        limit=page_limit,
        offset=page_offset,
    )
    log_event(
        logger,
        "ui.fragment.spotify.playlist_items",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/spotify_playlist_items.j2",
        context,
    )


@router.get(
    "/spotify/recommendations",
    include_in_schema=False,
    name="spotify_recommendations_fragment",
)
async def spotify_recommendations_fragment(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    seed_defaults = service.get_recommendation_seed_defaults()
    response = _render_recommendations_response(
        request,
        session,
        csrf_manager,
        csrf_token,
        issued=issued,
        seed_defaults=seed_defaults,
        show_admin_controls=session.allows("admin"),
    )
    log_event(
        logger,
        "ui.fragment.spotify.recommendations",
        component="ui.router",
        status="success",
        role=session.role,
        count=0,
    )
    return response


@router.post(
    "/spotify/recommendations",
    include_in_schema=False,
    name="spotify_recommendations_submit",
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_recommendations_submit(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    raw_form = await _read_recommendations_form(request)
    form = dict(raw_form)

    def _first_action(values: Mapping[str, Sequence[str]]) -> str:
        entries = values.get("action", ())
        if entries:
            candidate = entries[0]
            return str(candidate or "").strip().lower()
        return ""

    action = _first_action(form)
    if action == "queue":
        _ensure_imports_feature_enabled(session)
    show_admin_controls = session.allows("admin")
    seed_defaults = service.get_recommendation_seed_defaults()
    if action == "load_defaults" and show_admin_controls:
        form = dict(form)
        for key in ("seed_artists", "seed_tracks", "seed_genres"):
            form[key] = [seed_defaults.get(key, "")]

    parsed_form = _parse_recommendations_form(form)

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)

    return await _process_recommendations_submission(
        request=request,
        session=session,
        service=service,
        csrf_manager=csrf_manager,
        csrf_token=csrf_token,
        issued=issued,
        parsed_form=parsed_form,
        seed_defaults=seed_defaults,
        show_admin_controls=show_admin_controls,
    )


@router.get("/spotify/saved", include_in_schema=False, name="spotify_saved_tracks_fragment")
async def spotify_saved_tracks_fragment(
    request: Request,
    limit: int = Query(25, ge=1, le=50),
    offset: int = Query(0, ge=0),
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    try:
        rows, total = service.list_saved_tracks(limit=limit, offset=offset)
    except ValueError as exc:
        return _render_alert_fragment(
            request,
            str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        logger.exception("ui.fragment.spotify.saved")
        return _render_alert_fragment(
            request,
            "Unable to load Spotify saved tracks.",
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_spotify_saved_tracks_context(
        request,
        rows=rows,
        total_count=total,
        limit=limit,
        offset=offset,
        csrf_token=csrf_token,
        queue_enabled=session.features.imports,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_saved_tracks.j2",
        context,
    )
    _persist_saved_tracks_pagination(response, limit=limit, offset=offset)
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        "ui.fragment.spotify.saved",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return response


@router.api_route(
    "/spotify/saved/{action}",
    methods=["POST", "DELETE"],
    include_in_schema=False,
    name="spotify_saved_tracks_action",
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_saved_tracks_action(
    request: Request,
    action: str,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    action_key = action.strip().lower()
    if action_key not in {"save", "remove", "queue"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unsupported action.")

    if action_key == "queue":
        _ensure_imports_feature_enabled(session)

    raw_body = await request.body()
    try:
        payload = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        payload = ""
    values = parse_qs(payload)

    def _first(key: str) -> str | None:
        entries = values.get(key)
        if not entries:
            query_entries = request.query_params.getlist(key)  # type: ignore[attr-defined]
        else:
            query_entries = []
        source = entries or query_entries
        if not source:
            return None
        return source[0]

    def _coerce_int(
        raw: str | None, default: int, *, minimum: int, maximum: int | None = None
    ) -> int:
        try:
            value = int(raw) if raw not in (None, "") else default
        except (TypeError, ValueError):
            value = default
        if maximum is None:
            return max(minimum, value)
        return max(minimum, min(value, maximum))

    default_limit, default_offset = _extract_saved_tracks_pagination(request)
    limit = _coerce_int(_first("limit"), default_limit, minimum=1, maximum=50)
    offset = _coerce_int(_first("offset"), default_offset, minimum=0)

    track_values: list[str] = []
    for key in ("track_id", "track_ids", "track_id[]"):
        track_values.extend(values.get(key, []))
    if not track_values:
        query_values = []
        for key in ("track_id", "track_ids", "track_id[]"):
            query_values.extend(request.query_params.getlist(key))
        track_values.extend(query_values)

    extracted_ids: list[str] = []
    for candidate in track_values:
        if not isinstance(candidate, str):
            continue
        parts = re.split(r"[\s,]+", candidate)
        for part in parts:
            cleaned = part.strip()
            if cleaned:
                extracted_ids.append(cleaned)

    try:
        if action_key == "save":
            affected = service.save_tracks(extracted_ids)
            event_name = "ui.spotify.saved.save"
            failure_message = "Unable to save Spotify tracks."
        elif action_key == "remove":
            affected = service.remove_saved_tracks(extracted_ids)
            event_name = "ui.spotify.saved.remove"
            failure_message = "Unable to remove Spotify tracks."
        else:
            result = await service.queue_saved_tracks(
                extracted_ids, imports_enabled=session.features.imports
            )
            affected = int(result.accepted.tracks)
            event_name = "ui.spotify.saved.queue"
            failure_message = "Unable to queue Spotify downloads."
    except ValueError as exc:
        return _render_alert_fragment(
            request,
            str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except AppError as exc:
        log_event(
            logger,
            "ui.spotify.saved.action",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.spotify.saved.action")
        return _render_alert_fragment(
            request,
            failure_message,
        )

    rows, total = service.list_saved_tracks(limit=limit, offset=offset)
    if total and offset >= total:
        offset = max(total - (total % limit or limit), 0)
        rows, total = service.list_saved_tracks(limit=limit, offset=offset)

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_spotify_saved_tracks_context(
        request,
        rows=rows,
        total_count=total,
        limit=limit,
        offset=offset,
        csrf_token=csrf_token,
        queue_enabled=session.features.imports,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_saved_tracks.j2",
        context,
    )
    _persist_saved_tracks_pagination(response, limit=limit, offset=offset)
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        event_name,
        component="ui.router",
        status="success",
        role=session.role,
        count=affected,
    )
    return response


@router.get(
    "/spotify/tracks/{track_id}",
    include_in_schema=False,
    name="spotify_track_detail",
)
async def spotify_track_detail_modal(
    request: Request,
    track_id: str,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    try:
        detail = service.track_detail(track_id)
    except ValueError as exc:
        return _render_alert_fragment(
            request,
            str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        logger.exception("ui.fragment.spotify.track_detail")
        return _render_alert_fragment(
            request,
            "Unable to load Spotify track details.",
        )

    context = build_spotify_track_detail_context(request, track=detail)
    response = templates.TemplateResponse(
        request,
        "partials/spotify_track_detail.j2",
        context,
    )
    log_event(
        logger,
        "ui.fragment.spotify.track_detail",
        component="ui.router",
        status="success",
        role=session.role,
        count=1,
    )
    return response


@router.get("/spotify/status", include_in_schema=False, name="spotify_status_fragment")
async def spotify_status_fragment(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    manual_form = FormDefinition(
        identifier="spotify-manual-form",
        method="post",
        action="/ui/spotify/oauth/manual",
        submit_label_key="spotify.manual.submit",
    )
    context = build_spotify_status_context(
        request,
        status=service.status(),
        oauth=service.oauth_health(),
        manual_form=manual_form,
        csrf_token=csrf_token,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_status.j2",
        context,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        "ui.fragment.spotify.status",
        component="ui.router",
        status="success",
        role=session.role,
    )
    return response


@router.get("/downloads/table", include_in_schema=False)
async def downloads_table(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_all: bool = Query(False, alias="all"),
    status_filter: str | None = Query(None, alias="status"),
    session: UiSession = Depends(require_role("operator")),
    service: DownloadsUiService = Depends(get_downloads_ui_service),
) -> Response:
    if not session.features.dlq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested UI feature is disabled.",
        )

    try:
        page = service.list_downloads(
            limit=limit,
            offset=offset,
            include_all=include_all,
            status_filter=status_filter,
        )
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.downloads",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.fragment.downloads")
        log_event(
            logger,
            "ui.fragment.downloads",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        return _render_alert_fragment(
            request,
            "Unable to load download entries.",
        )

    context = build_downloads_fragment_context(
        request,
        page=page,
        status_filter=status_filter,
        include_all=include_all,
    )
    log_event(
        logger,
        "ui.fragment.downloads",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/downloads_table.j2",
        context,
    )


@router.post(
    "/downloads/{download_id}/priority",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def downloads_priority_update(
    request: Request,
    download_id: int,
    session: UiSession = Depends(require_role("operator")),
    service: DownloadsUiService = Depends(get_downloads_ui_service),
) -> Response:
    if not session.features.dlq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested UI feature is disabled.",
        )

    raw_body = await request.body()
    try:
        body = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        body = ""
    values = parse_qs(body)
    priority_raw = values.get("priority", [""])[0]
    try:
        priority_value = int(priority_raw.strip())
    except ValueError:
        return _render_alert_fragment(
            request,
            "Please provide a numeric priority value.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    query_params = request.query_params

    def _parse_int(value: str | None, *, default: int, minimum: int, maximum: int) -> int:
        if value is None:
            return default
        try:
            parsed = int(value)
        except ValueError:
            return default
        return max(min(parsed, maximum), minimum)

    limit = _parse_int(query_params.get("limit"), default=20, minimum=1, maximum=100)
    offset = _parse_int(query_params.get("offset"), default=0, minimum=0, maximum=10_000)
    include_all = query_params.get("all") in {"1", "true", "on", "yes"}
    status_filter = query_params.get("status")

    try:
        service.update_priority(
            download_id=download_id,
            priority=priority_value,
        )
        page = service.list_downloads(
            limit=limit,
            offset=offset,
            include_all=include_all,
            status_filter=status_filter,
        )
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.downloads",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.fragment.downloads.priority")
        log_event(
            logger,
            "ui.fragment.downloads",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        return _render_alert_fragment(
            request,
            "Failed to update the download priority.",
        )

    context = build_downloads_fragment_context(
        request,
        page=page,
        status_filter=status_filter,
        include_all=include_all,
    )
    log_event(
        logger,
        "ui.fragment.downloads",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
        download_id=download_id,
        priority=priority_value,
    )
    return templates.TemplateResponse(
        request,
        "partials/downloads_table.j2",
        context,
    )


@router.get("/jobs/table", include_in_schema=False)
async def jobs_table(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    service: JobsUiService = Depends(get_jobs_ui_service),
) -> Response:
    if not session.features.dlq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested UI feature is disabled.",
        )

    try:
        jobs = await service.list_jobs(request)
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.jobs",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.fragment.jobs")
        log_event(
            logger,
            "ui.fragment.jobs",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        return _render_alert_fragment(
            request,
            "Unable to load orchestrator jobs.",
        )

    context = build_jobs_fragment_context(
        request,
        jobs=jobs,
    )
    log_event(
        logger,
        "ui.fragment.jobs",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/jobs_fragment.j2",
        context,
    )


@router.get("/watchlist/table", include_in_schema=False)
async def watchlist_table(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    service: WatchlistUiService = Depends(get_watchlist_ui_service),
) -> Response:
    try:
        table = service.list_entries(request)
    except Exception:
        logger.exception("ui.fragment.watchlist")
        log_event(
            logger,
            "ui.fragment.watchlist",
            component="ui.router",
            status="error",
            role=session.role,
        )
        return _render_alert_fragment(
            request,
            "Unable to load watchlist entries.",
        )

    context = build_watchlist_fragment_context(
        request,
        entries=table.entries,
    )
    log_event(
        logger,
        "ui.fragment.watchlist",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/watchlist_table.j2",
        context,
    )


@router.post(
    "/watchlist/{artist_key}/priority",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def watchlist_priority_update(
    request: Request,
    artist_key: str,
    session: UiSession = Depends(require_role("operator")),
    service: WatchlistUiService = Depends(get_watchlist_ui_service),
) -> Response:
    raw_body = await request.body()
    try:
        body = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        body = ""
    values = parse_qs(body)
    priority_raw = values.get("priority", [""])[0]

    try:
        payload = WatchlistPriorityUpdate.model_validate({"priority": priority_raw})
    except ValidationError:
        return _render_alert_fragment(
            request,
            "Please provide a valid priority value.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        table = service.update_priority(
            request,
            artist_key=artist_key,
            priority=payload.priority,
        )
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.watchlist",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.fragment.watchlist.priority")
        log_event(
            logger,
            "ui.fragment.watchlist",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        return _render_alert_fragment(
            request,
            "Failed to update the watchlist priority.",
        )

    context = build_watchlist_fragment_context(
        request,
        entries=table.entries,
    )
    log_event(
        logger,
        "ui.fragment.watchlist",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/watchlist_table.j2",
        context,
    )


@router.post(
    "/search/results",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def search_results(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    service: SearchUiService = Depends(get_search_ui_service),
) -> Response:
    raw_body = await request.body()
    try:
        body = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        body = ""
    values = parse_qs(body)
    return await _render_search_results_fragment(
        request,
        session,
        service,
        raw_query=values.get("query", [""])[0],
        raw_limit=values.get("limit", [""])[0],
        raw_offset=values.get("offset", [""])[0],
        raw_sources=values.get("sources", []),
    )


@router.get("/search/results", include_in_schema=False)
async def search_results_get(
    request: Request,
    query: str = Query(default=""),
    limit: str = Query(default=""),
    offset: str = Query(default=""),
    sources: Sequence[str] | None = Query(default=None),
    session: UiSession = Depends(require_role("operator")),
    service: SearchUiService = Depends(get_search_ui_service),
) -> Response:
    """Serve search results via GET for HTMX pagination links."""
    return await _render_search_results_fragment(
        request,
        session,
        service,
        raw_query=query,
        raw_limit=limit,
        raw_offset=offset,
        raw_sources=sources or (),
    )


@router.post(
    "/search/download",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def search_download_action(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    download_service: DownloadService = Depends(get_download_service),
) -> Response:
    if not session.features.soulseek:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested UI feature is disabled.",
        )

    raw_body = await request.body()
    try:
        body = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        body = ""
    values = parse_qs(body)
    username = values.get("username", [""])[0].strip()
    files_raw = values.get("files", [""])[0]
    identifier = values.get("identifier", [""])[0]

    if not username or not files_raw:
        return _render_alert_fragment(
            request,
            "Missing download selection details.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        decoded_files = json.loads(files_raw)
    except json.JSONDecodeError:
        return _render_alert_fragment(
            request,
            "Unable to parse the selected download details.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(decoded_files, dict):
        files_data = [dict(decoded_files)]
    elif isinstance(decoded_files, list):
        files_data = [dict(item) for item in decoded_files if isinstance(item, dict)]
    else:
        files_data = []

    if not files_data:
        return _render_alert_fragment(
            request,
            "No valid download files were provided.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        payload = SoulseekDownloadRequest.model_validate(
            {"username": username, "files": files_data}
        )
    except ValidationError:
        return _render_alert_fragment(
            request,
            "Unable to queue the download request.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    worker = getattr(request.app.state, "sync_worker", None)
    try:
        await download_service.queue_downloads(payload, worker=worker)
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.search.download",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
            identifier=identifier or None,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.fragment.search.download")
        log_event(
            logger,
            "ui.fragment.search.download",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
            identifier=identifier or None,
        )
        return _render_alert_fragment(
            request,
            "Failed to queue the download request.",
        )

    first_file = payload.files[0]
    filename = first_file.resolved_filename
    alert = AlertMessage(
        level="success",
        text=f"Queued download request for {filename}.",
    )
    context = {"request": request, "alerts": (alert,)}
    log_event(
        logger,
        "ui.fragment.search.download",
        component="ui.router",
        status="success",
        role=session.role,
        username=payload.username,
        count=len(payload.files),
        identifier=identifier or None,
    )
    return templates.TemplateResponse(
        request,
        "partials/alerts_fragment.j2",
        context,
    )


@router.post(
    "/watchlist",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def watchlist_create(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    service: WatchlistUiService = Depends(get_watchlist_ui_service),
) -> Response:
    raw_body = await request.body()
    try:
        body = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        body = ""
    values = parse_qs(body)
    payload_data = {
        "artist_key": values.get("artist_key", [""])[0],
        "priority": values.get("priority", [None])[0],
    }
    try:
        payload = WatchlistEntryCreate.model_validate(payload_data)
    except ValidationError:
        return _render_alert_fragment(
            request,
            "Please provide a valid artist identifier.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        table = service.create_entry(
            request,
            artist_key=payload.artist_key,
            priority=payload.priority,
        )
    except AppError as exc:
        log_event(
            logger,
            "ui.fragment.watchlist",
            component="ui.router",
            status="error",
            role=session.role,
            error=exc.code,
        )
        return _render_alert_fragment(
            request,
            exc.message,
            status_code=exc.http_status,
        )
    except Exception:
        logger.exception("ui.fragment.watchlist.create")
        log_event(
            logger,
            "ui.fragment.watchlist",
            component="ui.router",
            status="error",
            role=session.role,
            error="unexpected",
        )
        return _render_alert_fragment(
            request,
            "Failed to add the artist to the watchlist.",
        )

    context = build_watchlist_fragment_context(
        request,
        entries=table.entries,
    )
    log_event(
        logger,
        "ui.fragment.watchlist",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/watchlist_table.j2",
        context,
    )
