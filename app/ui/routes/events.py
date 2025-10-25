from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from app.config import AppConfig
from app.dependencies import get_app_config
from app.ui.context.downloads import build_downloads_fragment_context
from app.ui.context.jobs import build_jobs_fragment_context
from app.ui.context.operations import (
    build_activity_fragment_context,
    build_watchlist_fragment_context,
)
from app.ui.csrf import attach_csrf_cookie
from app.ui.routes.shared import (
    _LIVE_UPDATES_SSE,
    _ensure_csrf_token,
    _LiveFragmentBuilder,
    _resolve_live_updates_mode,
    _ui_event_stream,
    get_csrf_manager,
    logger,
    templates,
)
from app.ui.services import (
    ActivityUiService,
    DownloadsUiService,
    JobsUiService,
    WatchlistUiService,
    get_activity_ui_service,
    get_downloads_ui_service,
    get_jobs_ui_service,
    get_watchlist_ui_service,
)
from app.ui.session import UiSession, require_session

router = APIRouter()


@router.get("/events", include_in_schema=False, name="ui_events")
async def ui_events(
    request: Request,
    session: UiSession = Depends(require_session),
    downloads_service: DownloadsUiService = Depends(get_downloads_ui_service),
    jobs_service: JobsUiService = Depends(get_jobs_ui_service),
    watchlist_service: WatchlistUiService = Depends(get_watchlist_ui_service),
    activity_service: ActivityUiService = Depends(get_activity_ui_service),
    config: AppConfig = Depends(get_app_config),
) -> Response:
    if _resolve_live_updates_mode(config) != _LIVE_UPDATES_SSE:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Live updates via SSE are disabled.",
        )

    csrf_manager = get_csrf_manager(request)
    csrf_token, issued = _ensure_csrf_token(request, session, csrf_manager)

    def _render_fragment(
        event_name: str,
        template_name: str,
        context: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        fragment = context.get("fragment")
        if fragment is None:
            return None
        template = templates.get_template(template_name)
        render_context = dict(context)
        if "request" in context:
            render_context["request"] = context["request"]
        html = template.render(**render_context)
        data_attributes = dict(getattr(fragment, "data_attributes", {}))
        return {
            "event": event_name,
            "fragment_id": fragment.identifier,
            "html": html,
            "data_attributes": data_attributes,
        }

    builders: list[_LiveFragmentBuilder] = []

    if session.features.dlq and session.allows("operator"):

        async def _build_downloads() -> dict[str, Any] | None:
            page = await downloads_service.list_downloads_async(
                limit=20,
                offset=0,
                include_all=False,
                status_filter=None,
            )
            context = build_downloads_fragment_context(
                request,
                page=page,
                csrf_token=csrf_token,
                status_filter=None,
                include_all=False,
            )
            return _render_fragment("downloads", "partials/downloads_table.j2", context)

        async def _build_jobs() -> dict[str, Any] | None:
            jobs = await jobs_service.list_jobs(request)
            context = build_jobs_fragment_context(
                request,
                jobs=jobs,
            )
            return _render_fragment("jobs", "partials/jobs_fragment.j2", context)

        builders.append(
            _LiveFragmentBuilder(name="downloads", interval=15.0, build=_build_downloads)
        )
        builders.append(_LiveFragmentBuilder(name="jobs", interval=15.0, build=_build_jobs))

    if session.allows("operator"):

        async def _build_watchlist() -> dict[str, Any] | None:
            table = await watchlist_service.list_entries_async(request)
            context = build_watchlist_fragment_context(
                request,
                entries=table.entries,
                csrf_token=csrf_token,
                limit=None,
                offset=None,
            )
            return _render_fragment("watchlist", "partials/watchlist_table.j2", context)

        builders.append(
            _LiveFragmentBuilder(name="watchlist", interval=30.0, build=_build_watchlist)
        )

    async def _build_activity() -> dict[str, Any] | None:
        page = await activity_service.list_activity_async(
            limit=50,
            offset=0,
            type_filter=None,
            status_filter=None,
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
        return _render_fragment("activity", "partials/activity_table.j2", context)

    builders.append(_LiveFragmentBuilder(name="activity", interval=60.0, build=_build_activity))

    logger.info(
        "ui.events.start",
        extra={"role": session.role, "fragments": [builder.name for builder in builders]},
    )

    stream = _ui_event_stream(request, builders)
    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    response = StreamingResponse(stream, media_type="text/event-stream", headers=headers)
    if issued:
        attach_csrf_cookie(response, session, csrf_manager, token=csrf_token)
    return response


__all__ = ["router"]
