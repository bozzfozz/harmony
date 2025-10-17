from __future__ import annotations

from collections.abc import Sequence
import json
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.api.search import DEFAULT_SOURCES
from app.dependencies import get_download_service
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
    build_soulseek_page_context,
    build_soulseek_status_context,
    build_soulseek_uploads_context,
    build_search_page_context,
    build_search_results_context,
    build_spotify_artists_context,
    build_spotify_backfill_context,
    build_spotify_page_context,
    build_spotify_playlists_context,
    build_spotify_status_context,
    build_watchlist_fragment_context,
)
from app.ui.csrf import attach_csrf_cookie, clear_csrf_cookie, enforce_csrf, get_csrf_manager
from app.ui.services import (
    ActivityUiService,
    DownloadsUiService,
    JobsUiService,
    SearchUiService,
    SoulseekUiService,
    SpotifyUiService,
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


def _ensure_csrf_token(request: Request, session: UiSession, manager) -> tuple[str, bool]:
    token = request.cookies.get("csrftoken")
    if token:
        return token, False
    issued = manager.issue(session)
    return issued, True


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
    try:
        playlists = service.list_playlists()
    except Exception:
        logger.exception("ui.fragment.spotify.playlists")
        return _render_alert_fragment(
            request,
            "Unable to load Spotify playlists.",
        )
    context = build_spotify_playlists_context(request, playlists=playlists)
    log_event(
        logger,
        "ui.fragment.spotify.playlists",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/spotify_playlists.j2",
        context,
    )


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
