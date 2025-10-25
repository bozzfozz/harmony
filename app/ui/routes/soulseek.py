from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.config import AppConfig
from app.core.soulseek_client import SoulseekClient
from app.db import run_session, session_scope
from app.dependencies import get_app_config, get_soulseek_client
from app.errors import AppError
from app.logging_events import log_event
from app.models import DiscographyJob, Download
from app.routers.soulseek_router import (
    refresh_download_lyrics as api_refresh_download_lyrics,
    refresh_download_metadata as api_refresh_download_metadata,
    soulseek_cancel,
    soulseek_discography_download,
    soulseek_download_artwork as api_soulseek_download_artwork,
    soulseek_download_lyrics as api_soulseek_download_lyrics,
    soulseek_download_metadata as api_soulseek_download_metadata,
    soulseek_refresh_artwork as api_soulseek_refresh_artwork,
    soulseek_remove_completed_downloads,
    soulseek_remove_completed_uploads,
    soulseek_requeue_download,
)
from app.schemas import DiscographyDownloadRequest
from app.ui.context.base import AlertMessage, LayoutContext, SuggestedTask, build_primary_navigation
from app.ui.context.soulseek import (
    build_soulseek_config_context,
    build_soulseek_discography_jobs_context,
    build_soulseek_discography_modal_context,
    build_soulseek_download_artwork_modal_context,
    build_soulseek_download_lyrics_modal_context,
    build_soulseek_download_metadata_modal_context,
    build_soulseek_downloads_context,
    build_soulseek_navigation_badge,
    build_soulseek_page_context,
    build_soulseek_status_context,
    build_soulseek_uploads_context,
    build_soulseek_user_directory_context,
    build_soulseek_user_profile_context,
)
from app.ui.csrf import attach_csrf_cookie, enforce_csrf, get_csrf_manager
from app.ui.routes.shared import (
    _ensure_csrf_token,
    _extract_download_refresh_params,
    _parse_form_body,
    _render_alert_fragment,
    logger,
    templates,
)
from app.ui.services import (
    DownloadsUiService,
    SoulseekUiService,
    get_downloads_ui_service,
    get_soulseek_ui_service,
)
from app.ui.session import UiSession, require_admin_with_feature, require_operator_with_feature
from sqlalchemy.orm import Session

T = TypeVar("T")


class DownloadLookupError(Exception):
    """Raised when a download lookup fails within a database session."""

    def __init__(self, download_id: int) -> None:
        super().__init__(f"Download {download_id} not found")
        self.download_id = download_id

router = APIRouter()


_DISCOGRAPHY_JOB_LIMIT = 20


async def _load_discography_jobs(limit: int = _DISCOGRAPHY_JOB_LIMIT) -> list[DiscographyJob]:
    """Return the most recent discography jobs using a background session."""

    def _query(session: Session) -> list[DiscographyJob]:
        query = session.query(DiscographyJob).order_by(DiscographyJob.created_at.desc())
        if limit:
            query = query.limit(limit)
        return list(query.all())

    return await run_session(_query)


async def _run_download_lookup(
    download_id: int,
    callback: Callable[[Session, Download], T],
) -> T:
    """Execute ``callback`` with the located download in a worker thread."""

    def _call(session: Session) -> T:
        download = session.get(Download, download_id)
        if download is None:
            raise DownloadLookupError(download_id)
        result = callback(session, download)
        session.expunge(download)
        return result

    return await run_session(_call)


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
        page = await service.list_downloads_async(
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
    "/soulseek/discography/jobs",
    include_in_schema=False,
    name="soulseek_discography_jobs_fragment",
)
async def soulseek_discography_jobs_fragment(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("soulseek")),
) -> Response:
    event_name = "ui.fragment.soulseek.discography.jobs"
    try:
        jobs = await _load_discography_jobs()
    except Exception:
        logger.exception(event_name)
        return _render_alert_fragment(
            request,
            "Unable to load discography jobs.",
            retry_url=str(request.url),
            retry_target="#hx-soulseek-discography-jobs",
            retry_label_key="soulseek.retry",
        )

    try:
        modal_url = str(request.url_for("soulseek_discography_job_modal"))
    except Exception:
        modal_url = "/ui/soulseek/discography/jobs/modal"

    context = build_soulseek_discography_jobs_context(
        request,
        jobs=jobs,
        modal_url=modal_url,
    )
    log_event(
        logger,
        event_name,
        component="ui.router",
        status="success",
        role=session.role,
        count=len(jobs),
    )
    return templates.TemplateResponse(
        request,
        "partials/soulseek_discography_jobs.j2",
        context,
    )


@router.get(
    "/soulseek/discography/jobs/modal",
    include_in_schema=False,
    name="soulseek_discography_job_modal",
)
async def soulseek_discography_job_modal(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("soulseek")),
) -> Response:
    try:
        submit_url = str(request.url_for("soulseek_discography_jobs_submit"))
    except Exception:
        submit_url = "/ui/soulseek/discography/jobs"
    csrf_token = request.cookies.get("csrftoken", "")
    target_id = "#hx-soulseek-discography-jobs"
    context = build_soulseek_discography_modal_context(
        request,
        submit_url=submit_url,
        csrf_token=csrf_token,
        target_id=target_id,
    )
    log_event(
        logger,
        "ui.fragment.soulseek.discography.modal",
        component="ui.router",
        status="success",
        role=session.role,
    )
    return templates.TemplateResponse(
        request,
        "partials/soulseek_discography_modal.j2",
        context,
    )


@router.post(
    "/soulseek/discography/jobs",
    include_in_schema=False,
    name="soulseek_discography_jobs_submit",
    dependencies=[Depends(enforce_csrf)],
)
async def soulseek_discography_jobs_submit(
    request: Request,
    session: UiSession = Depends(require_operator_with_feature("soulseek")),
) -> Response:
    event_name = "ui.fragment.soulseek.discography.jobs.submit"
    values = _parse_form_body(await request.body())
    artist_id = (values.get("artist_id") or "").strip()
    raw_name = values.get("artist_name")
    artist_name = raw_name.strip() if isinstance(raw_name, str) else ""
    form_values = {"artist_id": artist_id, "artist_name": artist_name}
    csrf_token = request.cookies.get("csrftoken", "")
    try:
        submit_url = str(request.url_for("soulseek_discography_jobs_submit"))
    except Exception:
        submit_url = "/ui/soulseek/discography/jobs"

    if not artist_id:
        context = build_soulseek_discography_modal_context(
            request,
            submit_url=submit_url,
            csrf_token=csrf_token,
            target_id="#hx-soulseek-discography-jobs",
            form_values=form_values,
            form_errors={"artist_id": "An artist ID is required."},
        )
        response = templates.TemplateResponse(
            request,
            "partials/soulseek_discography_modal.j2",
            context,
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        response.headers["HX-Retarget"] = "#modal-root"
        response.headers["HX-Reswap"] = "innerHTML"
        return response

    payload = DiscographyDownloadRequest(
        artist_id=artist_id,
        artist_name=artist_name or None,
    )
    try:
        with session_scope() as db_session:
            job_response = await soulseek_discography_download(
                payload=payload,
                request=request,
                session=db_session,
            )
    except HTTPException as exc:
        detail = (
            exc.detail if isinstance(exc.detail, str) else "Unable to queue the discography job."
        )
        context = build_soulseek_discography_modal_context(
            request,
            submit_url=submit_url,
            csrf_token=csrf_token,
            target_id="#hx-soulseek-discography-jobs",
            form_values=form_values,
            form_errors={"artist_id": detail},
        )
        response = templates.TemplateResponse(
            request,
            "partials/soulseek_discography_modal.j2",
            context,
            status_code=exc.status_code,
        )
        response.headers["HX-Retarget"] = "#modal-root"
        response.headers["HX-Reswap"] = "innerHTML"
        log_event(
            logger,
            event_name,
            component="ui.router",
            status="error",
            role=session.role,
            error=str(exc.status_code),
        )
        return response
    except Exception:
        logger.exception(event_name)
        context = build_soulseek_discography_modal_context(
            request,
            submit_url=submit_url,
            csrf_token=csrf_token,
            target_id="#hx-soulseek-discography-jobs",
            form_values=form_values,
            form_errors={"artist_id": "Unable to queue the discography job."},
        )
        response = templates.TemplateResponse(
            request,
            "partials/soulseek_discography_modal.j2",
            context,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        response.headers["HX-Retarget"] = "#modal-root"
        response.headers["HX-Reswap"] = "innerHTML"
        return response

    artist_label = artist_name or artist_id
    alerts = (
        AlertMessage(
            level="success",
            text=f"Queued discography download for {artist_label}.",
        ),
    )
    try:
        modal_url = str(request.url_for("soulseek_discography_job_modal"))
    except Exception:
        modal_url = "/ui/soulseek/discography/jobs/modal"
    jobs = await _load_discography_jobs()
    context = build_soulseek_discography_jobs_context(
        request,
        jobs=jobs,
        modal_url=modal_url,
        alerts=alerts,
    )
    log_event(
        logger,
        event_name,
        component="ui.router",
        status="success",
        role=session.role,
        job_id=job_response.job_id,
        job_status=job_response.status,
    )
    return templates.TemplateResponse(
        request,
        "partials/soulseek_discography_jobs.j2",
        context,
    )


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
        download, api_response = await _run_download_lookup(
            download_id,
            lambda db_session, db_download: (
                db_download,
                api_soulseek_download_lyrics(
                    download_id=download_id,
                    request=request,
                    config=config,
                    session=db_session,
                ),
            ),
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
    except DownloadLookupError:
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
        download, metadata_response = await _run_download_lookup(
            download_id,
            lambda db_session, db_download: (
                db_download,
                api_soulseek_download_metadata(
                    download_id=download_id,
                    session=db_session,
                ),
            ),
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
    except DownloadLookupError:
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
        download = await _run_download_lookup(
            download_id,
            lambda db_session, db_download: (
                api_soulseek_download_artwork(
                    download_id=download_id,
                    request=request,
                    session=db_session,
                    config=config,
                ),
                db_download,
            )[1],
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
    except DownloadLookupError:
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
        page = await service.list_downloads_async(
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
        page = await service.list_downloads_async(
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
        page = await service.list_downloads_async(
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
        page = await service.list_downloads_async(
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
        page = await service.list_downloads_async(
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
        page = await service.list_downloads_async(
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
    user_status = None
    browsing_status = None
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
        try:
            user_status = await service.user_status(username=trimmed)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else "Unable to load user status."
            log_event(
                logger,
                "ui.fragment.soulseek.user_status",
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
            logger.exception("ui.fragment.soulseek.user_status")
            log_event(
                logger,
                "ui.fragment.soulseek.user_status",
                component="ui.router",
                status="error",
                role=session.role,
                error="unexpected",
            )
            return _render_alert_fragment(
                request,
                "Unable to load Soulseek user status.",
                retry_url=str(request.url),
                retry_target="#hx-soulseek-user-info",
                retry_label_key="soulseek.retry",
            )
        try:
            browsing_status = await service.user_browsing_status(username=trimmed)
        except HTTPException as exc:
            detail = (
                exc.detail
                if isinstance(exc.detail, str)
                else "Unable to load user browsing status."
            )
            log_event(
                logger,
                "ui.fragment.soulseek.user_browsing_status",
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
            logger.exception("ui.fragment.soulseek.user_browsing_status")
            log_event(
                logger,
                "ui.fragment.soulseek.user_browsing_status",
                component="ui.router",
                status="error",
                role=session.role,
                error="unexpected",
            )
            return _render_alert_fragment(
                request,
                "Unable to load Soulseek user browsing status.",
                retry_url=str(request.url),
                retry_target="#hx-soulseek-user-info",
                retry_label_key="soulseek.retry",
            )

    context = build_soulseek_user_profile_context(
        request,
        username=trimmed,
        profile=profile,
        status=user_status,
        browsing_status=browsing_status,
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
    user_status = None
    browsing_status = None
    if trimmed:
        try:
            user_status = await service.user_status(username=trimmed)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else "Unable to load user status."
            log_event(
                logger,
                "ui.fragment.soulseek.user_status",
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
            logger.exception("ui.fragment.soulseek.user_status")
            log_event(
                logger,
                "ui.fragment.soulseek.user_status",
                component="ui.router",
                status="error",
                role=session.role,
                error="unexpected",
            )
            return _render_alert_fragment(
                request,
                "Unable to load Soulseek user status.",
                retry_url=str(request.url),
                retry_target="#hx-soulseek-user-directory",
                retry_label_key="soulseek.retry",
            )
        try:
            browsing_status = await service.user_browsing_status(username=trimmed)
        except HTTPException as exc:
            detail = (
                exc.detail
                if isinstance(exc.detail, str)
                else "Unable to load user browsing status."
            )
            log_event(
                logger,
                "ui.fragment.soulseek.user_browsing_status",
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
            logger.exception("ui.fragment.soulseek.user_browsing_status")
            log_event(
                logger,
                "ui.fragment.soulseek.user_browsing_status",
                component="ui.router",
                status="error",
                role=session.role,
                error="unexpected",
            )
            return _render_alert_fragment(
                request,
                "Unable to load Soulseek user browsing status.",
                retry_url=str(request.url),
                retry_target="#hx-soulseek-user-directory",
                retry_label_key="soulseek.retry",
            )
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
        status=user_status,
        browsing_status=browsing_status,
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


__all__ = ["router"]
