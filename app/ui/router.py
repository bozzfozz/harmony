from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.errors import AppError
from app.logging import get_logger
from app.logging_events import log_event
from app.schemas.watchlist import WatchlistEntryCreate, WatchlistPriorityUpdate
from app.ui.context import (
    AlertMessage,
    build_activity_fragment_context,
    build_dashboard_page_context,
    build_downloads_fragment_context,
    build_jobs_fragment_context,
    build_login_page_context,
    build_search_results_context,
    build_watchlist_fragment_context,
)
from app.ui.csrf import attach_csrf_cookie, clear_csrf_cookie, enforce_csrf, get_csrf_manager
from app.ui.services import (
    ActivityUiService,
    DownloadsUiService,
    JobsUiService,
    SearchUiService,
    WatchlistUiService,
    get_activity_ui_service,
    get_downloads_ui_service,
    get_jobs_ui_service,
    get_search_ui_service,
    get_watchlist_ui_service,
)
from app.ui.session import (
    UiSession,
    attach_session_cookie,
    clear_session_cookie,
    get_session_manager,
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
    query = values.get("query", [""])[0].strip()
    limit_raw = values.get("limit", [""])[0]
    sources = [source for source in values.get("sources", []) if source]

    try:
        limit_value = int(limit_raw) if limit_raw else 25
    except ValueError:
        limit_value = 25
    limit_value = max(1, min(limit_value, 100))

    if not query:
        return _render_alert_fragment(
            request,
            "Please provide a search query.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        page = await service.search(
            request,
            query=query,
            limit=limit_value,
            sources=sources,
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

    context = build_search_results_context(
        request,
        page=page,
        query=query,
        sources=sources,
    )
    log_event(
        logger,
        "ui.fragment.search",
        component="ui.router",
        status="success",
        role=session.role,
        count=len(context["fragment"].table.rows),
    )
    return templates.TemplateResponse(
        request,
        "partials/search_results.j2",
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
