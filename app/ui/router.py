from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import re
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.api.search import DEFAULT_SOURCES
from app.core.soulseek_client import SoulseekClient
from app.db import session_scope
from app.dependencies import get_download_service, get_soulseek_client
from app.errors import AppError
from app.logging import get_logger
from app.logging_events import log_event
from app.schemas import SoulseekDownloadRequest
from app.schemas.watchlist import WatchlistEntryCreate, WatchlistPriorityUpdate
from app.services.download_service import DownloadService
from app.ui.context import (
    AlertMessage,
    FormDefinition,
    build_activity_fragment_context,
    build_dashboard_page_context,
    build_downloads_fragment_context,
    build_jobs_fragment_context,
    build_login_page_context,
    build_soulseek_config_context,
    build_soulseek_downloads_context,
    build_soulseek_page_context,
    build_soulseek_status_context,
    build_soulseek_uploads_context,
    build_search_page_context,
    build_search_results_context,
    build_spotify_artists_context,
    build_spotify_account_context,
    build_spotify_backfill_context,
    build_spotify_page_context,
    build_spotify_playlists_context,
    build_spotify_recommendations_context,
    build_spotify_saved_tracks_context,
    build_spotify_top_artists_context,
    build_spotify_top_tracks_context,
    build_spotify_status_context,
    build_watchlist_fragment_context,
)
from app.ui.csrf import attach_csrf_cookie, clear_csrf_cookie, enforce_csrf, get_csrf_manager
from app.routers.soulseek_router import soulseek_cancel, soulseek_requeue_download
from app.ui.services import (
    ActivityUiService,
    DownloadsUiService,
    JobsUiService,
    SearchUiService,
    SoulseekUiService,
    SpotifyUiService,
    SpotifyRecommendationRow,
    SpotifyRecommendationSeed,
    WatchlistUiService,
    get_activity_ui_service,
    get_downloads_ui_service,
    get_jobs_ui_service,
    get_search_ui_service,
    get_soulseek_ui_service,
    get_spotify_ui_service,
    get_watchlist_ui_service,
)
from app.ui.session import (
    UiSession,
    attach_session_cookie,
    clear_session_cookie,
    get_session_manager,
    require_feature,
    require_role,
    require_session,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/ui", tags=["UI"])

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

ParsedRecommendationsForm = tuple[
    Mapping[str, str],
    Sequence[str],
    Sequence[str],
    Sequence[str],
    Mapping[str, str],
    Sequence[AlertMessage],
    int,
    bool,
]


def _render_alert_fragment(
    request: Request,
    message: str,
    *,
    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
) -> Response:
    alert = AlertMessage(level="error", text=message or "An unexpected error occurred.")
    context = {
        "request": request,
        "alerts": (alert,),
    }
    return templates.TemplateResponse(
        request,
        "partials/alerts_fragment.j2",
        context,
        status_code=status_code,
    )


def _render_playlist_fragment_response(
    request: Request,
    session: UiSession,
    service: SpotifyUiService,
    *,
    status_code: int = status.HTTP_200_OK,
    error_message: str = "Unable to load Spotify playlists.",
) -> Response:
    try:
        playlists = service.list_playlists()
        status_info = service.status()
    except Exception:
        logger.exception("ui.fragment.spotify.playlists.refresh")
        return _render_alert_fragment(
            request,
            error_message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_spotify_playlists_context(
        request,
        playlists=playlists,
        csrf_token=csrf_token,
        is_authenticated=status_info.authenticated,
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_playlists.j2",
        context,
        status_code=status_code,
    )
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    log_event(
        logger,
        "ui.fragment.spotify.playlists",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return response


def _parse_form_payload(raw_body: bytes) -> dict[str, list[str]]:
    try:
        decoded = raw_body.decode("utf-8")
    except UnicodeDecodeError:
        decoded = ""
    parsed = parse_qs(decoded)
    return {key: [value for value in values if isinstance(value, str)] for key, values in parsed.items()}


def _ensure_csrf_token(request: Request, session: UiSession, manager) -> tuple[str, bool]:
    token = request.cookies.get("csrftoken")
    if token:
        return token, False
    issued = manager.issue(session)
    return issued, True


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
    status_code: int = status.HTTP_200_OK,
) -> Response:
    context = build_spotify_recommendations_context(
        request,
        csrf_token=csrf_token,
        rows=rows,
        seeds=seeds,
        form_values=form_values,
        form_errors=form_errors,
        alerts=alerts,
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
    form: Mapping[str, object]
) -> tuple[
    dict[str, str],
    list[str],
    list[str],
    list[str],
    dict[str, str],
    list[AlertMessage],
    int,
    bool,
]:
    form_values = {
        "seed_artists": str(form.get("seed_artists") or "").strip(),
        "seed_tracks": str(form.get("seed_tracks") or "").strip(),
        "seed_genres": str(form.get("seed_genres") or "").strip(),
        "limit": str(form.get("limit") or "").strip(),
    }
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

    artist_seeds = _split_seed_ids(form_values["seed_artists"])
    track_seeds = _split_seed_ids(form_values["seed_tracks"])
    genre_seeds = _split_seed_genres(form_values["seed_genres"])

    total_seeds = len(artist_seeds) + len(track_seeds) + len(genre_seeds)
    general_error = False
    if total_seeds == 0:
        alerts.append(AlertMessage(level="error", text="Provide at least one seed value."))
        general_error = True
    elif total_seeds > 5:
        alerts.append(AlertMessage(level="error", text="Specify no more than five seeds in total."))
        general_error = True

    return (
        form_values,
        artist_seeds,
        track_seeds,
        genre_seeds,
        errors,
        alerts,
        limit_value,
        general_error,
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
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _execute_recommendations_request(
    *,
    service: SpotifyUiService,
    artist_seeds: Sequence[str],
    track_seeds: Sequence[str],
    genre_seeds: Sequence[str],
    limit_value: int,
    alerts: Sequence[AlertMessage],
    request: Request,
    session: UiSession,
    csrf_manager,
    csrf_token: str,
    issued: bool,
    form_values: Mapping[str, str],
) -> tuple[tuple[Sequence[SpotifyRecommendationRow], Sequence[SpotifyRecommendationSeed]] | None, Response | None]:
    base_args = {
        "request": request,
        "session": session,
        "csrf_manager": csrf_manager,
        "csrf_token": csrf_token,
        "issued": issued,
    }
    try:
        rows, seeds = service.recommendations(
            seed_tracks=track_seeds,
            seed_artists=artist_seeds,
            seed_genres=genre_seeds,
            limit=limit_value,
        )
        return (rows, seeds), None
    except ValueError as exc:
        return None, _recommendations_value_error_response(
            **base_args,
            alerts=alerts,
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
    parsed_form: ParsedRecommendationsForm,
) -> tuple[Mapping[str, str], tuple[Sequence[SpotifyRecommendationRow], Sequence[SpotifyRecommendationSeed]] | None, Response | None]:
    (
        _form_values,
        artist_seeds,
        track_seeds,
        genre_seeds,
        _errors,
        alerts,
        limit_value,
        _general_error,
    ) = parsed_form
    normalised_values = _build_recommendation_form_values(
        artist_seeds=artist_seeds,
        track_seeds=track_seeds,
        genre_seeds=genre_seeds,
        limit_value=limit_value,
    )
    result, error_response = _execute_recommendations_request(
        service=service,
        artist_seeds=artist_seeds,
        track_seeds=track_seeds,
        genre_seeds=genre_seeds,
        limit_value=limit_value,
        alerts=alerts,
        request=request,
        session=session,
        csrf_manager=csrf_manager,
        csrf_token=csrf_token,
        issued=issued,
        form_values=normalised_values,
    )
    return normalised_values, result, error_response


def _process_recommendations_submission(
    *,
    request: Request,
    session: UiSession,
    service: SpotifyUiService,
    csrf_manager,
    csrf_token: str,
    issued: bool,
    parsed_form: ParsedRecommendationsForm,
) -> Response:
    (form_values, artist_seeds, track_seeds, genre_seeds, errors, alerts, limit_value, general_error) = parsed_form
    if errors or general_error:
        return _render_recommendations_response(
            request,
            session,
            csrf_manager,
            csrf_token,
            issued=issued,
            form_values=form_values,
            form_errors=errors,
            alerts=alerts,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    normalised_values, result, error_response = _fetch_recommendation_rows(
        request=request,
        session=session,
        service=service,
        csrf_manager=csrf_manager,
        csrf_token=csrf_token,
        issued=issued,
        parsed_form=parsed_form,
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
    )


async def _read_recommendations_form(request: Request) -> Mapping[str, str]:
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
        "seed_artists": _first("seed_artists"),
        "seed_tracks": _first("seed_tracks"),
        "seed_genres": _first("seed_genres"),
        "limit": _first("limit"),
    }


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
    session: UiSession = Depends(require_feature("spotify")),
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
    session: UiSession = Depends(require_feature("soulseek")),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_soulseek_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
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
    session: UiSession = Depends(require_feature("soulseek")),
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
        )

    context = build_soulseek_status_context(
        request,
        status=connection,
        health=health,
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
    session: UiSession = Depends(require_feature("soulseek")),
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
    session: UiSession = Depends(require_feature("soulseek")),
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
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_soulseek_uploads_context(
        request,
        uploads=uploads,
        csrf_token=csrf_token,
        include_all=include_all,
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
    session: UiSession = Depends(require_feature("soulseek")),
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
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_soulseek_downloads_context(
        request,
        page=page,
        csrf_token=csrf_token,
        include_all=include_all,
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


@router.post(
    "/soulseek/downloads/{download_id}/requeue",
    include_in_schema=False,
    name="soulseek_download_requeue",
    dependencies=[Depends(enforce_csrf)],
)
async def soulseek_download_requeue(
    request: Request,
    download_id: int,
    session: UiSession = Depends(require_feature("soulseek")),
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
    session: UiSession = Depends(require_feature("soulseek")),
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
    "/soulseek/uploads/cancel",
    include_in_schema=False,
    name="soulseek_upload_cancel",
    dependencies=[Depends(enforce_csrf)],
)
async def soulseek_upload_cancel(
    request: Request,
    session: UiSession = Depends(require_feature("soulseek")),
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
    session: UiSession = Depends(require_feature("spotify")),
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
    session: UiSession = Depends(require_feature("spotify")),
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
    "/spotify/backfill/run",
    include_in_schema=False,
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_backfill_run(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    if not session.features.spotify:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="The requested UI feature is disabled."
        )
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

    request.app.state.ui_spotify_backfill_job_id = job_id
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


@router.get("/spotify/account", include_in_schema=False, name="spotify_account_fragment")
async def spotify_account_fragment(
    request: Request,
    session: UiSession = Depends(require_feature("spotify")),
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

    context = build_spotify_account_context(request, account=summary)
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


@router.get("/spotify/top/tracks", include_in_schema=False, name="spotify_top_tracks_fragment")
async def spotify_top_tracks_fragment(
    request: Request,
    session: UiSession = Depends(require_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    try:
        tracks = service.top_tracks()
    except Exception:
        logger.exception("ui.fragment.spotify.top_tracks")
        return _render_alert_fragment(
            request,
            "Unable to load Spotify top tracks.",
        )

    context = build_spotify_top_tracks_context(request, tracks=tracks)
    log_event(
        logger,
        "ui.fragment.spotify.top_tracks",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/spotify_top_tracks.j2",
        context,
    )


@router.get("/spotify/top/artists", include_in_schema=False, name="spotify_top_artists_fragment")
async def spotify_top_artists_fragment(
    request: Request,
    session: UiSession = Depends(require_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    try:
        artists = service.top_artists()
    except Exception:
        logger.exception("ui.fragment.spotify.top_artists")
        return _render_alert_fragment(
            request,
            "Unable to load Spotify top artists.",
        )

    context = build_spotify_top_artists_context(request, artists=artists)
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
    session: UiSession = Depends(require_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    job_id = getattr(request.app.state, "ui_spotify_backfill_job_id", None)
    status_payload = service.backfill_status(job_id)
    snapshot = service.build_backfill_snapshot(
        csrf_token=csrf_token,
        job_id=job_id,
        status_payload=status_payload,
    )
    context = build_spotify_backfill_context(request, snapshot=snapshot)
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
    session: UiSession = Depends(require_feature("spotify")),
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
    session: UiSession = Depends(require_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    return _render_playlist_fragment_response(request, session, service)


@router.post(
    "/spotify/playlists/{playlist_id}/tracks/{action}",
    include_in_schema=False,
    name="spotify_playlist_tracks_action",
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_playlist_tracks_action(
    request: Request,
    playlist_id: str,
    action: str,
    session: UiSession = Depends(require_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    action_key = action.strip().lower()
    if action_key not in {"add", "remove"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unsupported action.")

    raw_body = await request.body()
    form_entries = _parse_form_payload(raw_body)
    raw_values: list[str] = []
    for key in ("uris", "uri", "uri[]", "track_uri", "track_uris", "track_uri[]"):
        raw_values.extend(form_entries.get(key, []))
        raw_values.extend(request.query_params.getlist(key))

    extracted: list[str] = []
    for raw in raw_values:
        if not isinstance(raw, str):
            continue
        for part in re.split(r"[\s,]+", raw.strip()):
            candidate = part.strip()
            if candidate:
                extracted.append(candidate)

    if not extracted:
        return _render_alert_fragment(
            request,
            "Provide at least one Spotify track URI.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        if action_key == "add":
            service.add_tracks_to_playlist(playlist_id, extracted)
        else:
            service.remove_tracks_from_playlist(playlist_id, extracted)
    except ValueError as exc:
        return _render_alert_fragment(
            request,
            str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        logger.exception("ui.spotify.playlists.tracks.%s", action_key)
        return _render_alert_fragment(
            request,
            "Unable to update the Spotify playlist. Try again shortly.",
        )

    return _render_playlist_fragment_response(
        request,
        session,
        service,
    )


@router.post(
    "/spotify/playlists/{playlist_id}/reorder",
    include_in_schema=False,
    name="spotify_playlist_reorder",
    dependencies=[Depends(enforce_csrf)],
)
async def spotify_playlist_reorder(
    request: Request,
    playlist_id: str,
    session: UiSession = Depends(require_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    raw_body = await request.body()
    form_entries = _parse_form_payload(raw_body)
    range_start_values = form_entries.get("range_start", [])
    insert_before_values = form_entries.get("insert_before", [])

    range_start_raw = range_start_values[0] if range_start_values else request.query_params.get("range_start")
    insert_before_raw = (
        insert_before_values[0]
        if insert_before_values
        else request.query_params.get("insert_before")
    )

    if range_start_raw in (None, "") or insert_before_raw in (None, ""):
        return _render_alert_fragment(
            request,
            "Provide both start and target positions for the reorder operation.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        range_start_value = int(str(range_start_raw).strip())
        insert_before_value = int(str(insert_before_raw).strip())
    except (TypeError, ValueError):
        return _render_alert_fragment(
            request,
            "Provide both start and target positions for the reorder operation.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        service.reorder_playlist(
            playlist_id,
            range_start=range_start_value,
            insert_before=insert_before_value,
        )
    except ValueError as exc:
        return _render_alert_fragment(
            request,
            str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        logger.exception("ui.spotify.playlists.reorder")
        return _render_alert_fragment(
            request,
            "Unable to update the Spotify playlist. Try again shortly.",
        )

    return _render_playlist_fragment_response(
        request,
        session,
        service,
    )

@router.get(
    "/spotify/recommendations",
    include_in_schema=False,
    name="spotify_recommendations_fragment",
)
async def spotify_recommendations_fragment(
    request: Request,
    session: UiSession = Depends(require_feature("spotify")),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    response = _render_recommendations_response(
        request,
        session,
        csrf_manager,
        csrf_token,
        issued=issued,
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
    session: UiSession = Depends(require_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    form = await _read_recommendations_form(request)
    (
        form_values,
        artist_seeds,
        track_seeds,
        genre_seeds,
        errors,
        alerts,
        limit_value,
        general_error,
    ) = _parse_recommendations_form(form)

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)

    return _process_recommendations_submission(
        request=request,
        session=session,
        service=service,
        csrf_manager=csrf_manager,
        csrf_token=csrf_token,
        issued=issued,
        parsed_form=(
            form_values,
            artist_seeds,
            track_seeds,
            genre_seeds,
            errors,
            alerts,
            limit_value,
            general_error,
        ),
    )


@router.get("/spotify/saved", include_in_schema=False, name="spotify_saved_tracks_fragment")
async def spotify_saved_tracks_fragment(
    request: Request,
    limit: int = Query(25, ge=1, le=50),
    offset: int = Query(0, ge=0),
    session: UiSession = Depends(require_feature("spotify")),
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
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_saved_tracks.j2",
        context,
    )
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
    session: UiSession = Depends(require_feature("spotify")),
    service: SpotifyUiService = Depends(get_spotify_ui_service),
) -> Response:
    action_key = action.strip().lower()
    if action_key not in {"save", "remove"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unsupported action.")

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

    limit = _coerce_int(_first("limit"), 25, minimum=1, maximum=50)
    offset = _coerce_int(_first("offset"), 0, minimum=0)

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
        else:
            affected = service.remove_saved_tracks(extracted_ids)
            event_name = "ui.spotify.saved.remove"
            failure_message = "Unable to remove Spotify tracks."
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
    )
    response = templates.TemplateResponse(
        request,
        "partials/spotify_saved_tracks.j2",
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
        count=affected,
    )
    return response


@router.get("/spotify/status", include_in_schema=False, name="spotify_status_fragment")
async def spotify_status_fragment(
    request: Request,
    session: UiSession = Depends(require_feature("spotify")),
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
