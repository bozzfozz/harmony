from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.search import DEFAULT_SOURCES
from app.config import AppConfig
from app.dependencies import (
    get_app_config,
    get_db,
    get_download_service,
)
from app.errors import AppError
from app.logging_events import log_event
from app.schemas import SoulseekDownloadRequest
from app.schemas.watchlist import WatchlistEntryCreate, WatchlistPriorityUpdate
from app.services.download_service import DownloadService
from app.ui.context import (
    AlertMessage,
    LayoutContext,
    build_activity_fragment_context,
    build_activity_page_context,
    build_admin_page_context,
    build_dashboard_page_context,
    build_downloads_fragment_context,
    build_downloads_page_context,
    build_jobs_fragment_context,
    build_jobs_page_context,
    build_primary_navigation,
    build_search_page_context,
    build_search_results_context,
    build_settings_artist_preferences_fragment_context,
    build_settings_form_fragment_context,
    build_settings_history_fragment_context,
    build_settings_page_context,
    build_watchlist_fragment_context,
    build_watchlist_page_context,
)
from app.ui.csrf import attach_csrf_cookie, clear_csrf_cookie, enforce_csrf, get_csrf_manager
from app.ui.routes.shared import (
    _ensure_csrf_token,
    _parse_form_body,
    _render_alert_fragment,
    _resolve_live_updates_mode,
    logger,
    templates,
)
from app.ui.services import (
    ActivityUiService,
    DownloadsUiService,
    JobsUiService,
    SearchUiService,
    SettingsOverview,
    SettingsUiService,
    WatchlistUiService,
    get_activity_ui_service,
    get_downloads_ui_service,
    get_jobs_ui_service,
    get_search_ui_service,
    get_settings_ui_service,
    get_watchlist_ui_service,
)
from app.ui.session import (
    UiSession,
    attach_session_cookie,
    clear_session_cookie,
    clear_spotify_job_state,
    get_session_manager,
    require_admin_with_feature,
    require_role,
    require_session,
)

router = APIRouter()




















































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


@router.get("/downloads", include_in_schema=False, name="downloads_page")
async def downloads_page(
    request: Request,
    session: UiSession = Depends(require_role("operator")),
    config: AppConfig = Depends(get_app_config),
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
        live_updates_mode=_resolve_live_updates_mode(config),
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
    config: AppConfig = Depends(get_app_config),
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
        live_updates_mode=_resolve_live_updates_mode(config),
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
    config: AppConfig = Depends(get_app_config),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_watchlist_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
        live_updates_mode=_resolve_live_updates_mode(config),
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
    config: AppConfig = Depends(get_app_config),
) -> Response:
    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)
    context = build_activity_page_context(
        request,
        session=session,
        csrf_token=csrf_token,
        live_updates_mode=_resolve_live_updates_mode(config),
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
    response.headers.setdefault("HX-Redirect", "/ui/login")
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
