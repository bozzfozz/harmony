from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
import json
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from fastapi import Request
from starlette.datastructures import URL

from app.config import SecurityConfig, SoulseekConfig
from app.integrations.health import IntegrationHealth
from app.schemas import SOULSEEK_RETRYABLE_STATES, StatusResponse
from app.ui.formatters import format_datetime_display
from app.ui.session import UiSession

from .base import (
    AlertMessage,
    AsyncFragment,
    DefinitionItem,
    FormDefinition,
    FormField,
    LayoutContext,
    MetaTag,
    PaginationContext,
    StatusBadge,
    StatusVariant,
    SuggestedTask,
    TableCell,
    TableCellForm,
    TableDefinition,
    TableFragment,
    TableRow,
    _build_primary_navigation,
    _format_duration_seconds,
    _format_status_text,
    _normalise_status,
    _normalize_status,
    _safe_url_for,
    _system_status_badge,
)

if TYPE_CHECKING:
    from app.ui.services import (
        DownloadPage,
        SoulseekUploadRow,
        SoulseekUserBrowsingStatus,
        SoulseekUserDirectoryEntry,
        SoulseekUserDirectoryListing,
        SoulseekUserFileEntry,
        SoulseekUserProfile,
        SoulseekUserStatus,
    )


def _status_badge(
    *,
    status: str,
    test_id: str,
    success_label: str,
    degraded_label: str,
    down_label: str,
    unknown_label: str,
    degrade_is_warning: bool = True,
) -> StatusBadge:
    normalised = _normalise_status(status)
    if normalised in {"connected", "ok", "online"}:
        return StatusBadge(label_key=success_label, variant="success", test_id=test_id)
    if normalised in {"disconnected", "down", "failed", "error"}:
        return StatusBadge(label_key=down_label, variant="danger", test_id=test_id)
    if normalised == "degraded":
        variant: StatusVariant = "danger" if degrade_is_warning else "muted"
        return StatusBadge(label_key=degraded_label, variant=variant, test_id=test_id)
    return StatusBadge(label_key=unknown_label, variant="muted", test_id=test_id)


def _discography_status_badge(status: str) -> StatusBadge:
    normalized = (status or "").strip().lower()
    label_map = {
        "pending": "soulseek.discography.status.pending",
        "queued": "soulseek.discography.status.queued",
        "running": "soulseek.discography.status.running",
        "completed": "soulseek.discography.status.completed",
        "failed": "soulseek.discography.status.failed",
        "cancelled": "soulseek.discography.status.cancelled",
    }
    variant_map: Mapping[str, StatusVariant] = {
        "pending": "muted",
        "queued": "muted",
        "running": "success",
        "completed": "success",
        "failed": "danger",
        "cancelled": "muted",
    }
    label_key = label_map.get(normalized, "soulseek.discography.status.unknown")
    variant = variant_map.get(normalized, "muted")
    return StatusBadge(label_key=label_key, variant=variant)


def build_soulseek_navigation_badge(
    *,
    connection: StatusResponse | None,
    integration: IntegrationHealth | None,
    test_id: str = "nav-soulseek-status",
) -> StatusBadge:
    connection_status = _normalise_status(connection.status if connection else "")
    integration_status = _normalise_status(integration.overall if integration else "")

    if (
        connection_status in {"disconnected", "down", "failed", "error"}
        or integration_status == "down"
    ):
        return StatusBadge(
            label_key="soulseek.integration.down",
            variant="danger",
            test_id=test_id,
        )

    if connection_status == "degraded" or integration_status == "degraded":
        return StatusBadge(
            label_key="soulseek.integration.degraded",
            variant="danger",
            test_id=test_id,
        )

    if connection_status in {"connected", "ok", "online"} and integration_status in {"", "ok"}:
        label_key = (
            "soulseek.integration.ok" if integration_status == "ok" else "soulseek.status.connected"
        )
        return StatusBadge(label_key=label_key, variant="success", test_id=test_id)

    if integration_status == "ok":
        return StatusBadge(
            label_key="soulseek.integration.ok",
            variant="success",
            test_id=test_id,
        )

    return StatusBadge(
        label_key="soulseek.integration.unknown",
        variant="muted",
        test_id=test_id,
    )


def _format_health_details(details: Mapping[str, Any]) -> str:
    if not details:
        return ""
    rendered: list[str] = []
    for key, value in details.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            rendered.append(f"{key}: {value}")
            continue
        try:
            rendered.append(f"{key}: {json.dumps(value, sort_keys=True)}")
        except TypeError:
            rendered.append(f"{key}: {value}")
    return ", ".join(rendered)


def _download_action_base_url(request: Request, name: str, fallback_template: str) -> str:
    try:
        resolved = URL(str(request.url_for(name, download_id="0")))
    except Exception:  # pragma: no cover - fallback for tests
        return fallback_template

    segments = [segment for segment in resolved.path.split("/") if segment]
    for index, segment in enumerate(segments):
        if segment == "0":
            segments[index] = "{download_id}"
            break
    else:
        return fallback_template

    path = "/" + "/".join(segments)
    if resolved.query:
        return f"{path}?{resolved.query}"
    return path


def build_soulseek_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
    soulseek_badge: StatusBadge | None = None,
    suggested_tasks: Sequence[SuggestedTask] = (),
    tasks_completion: int = 0,
) -> Mapping[str, Any]:
    layout = LayoutContext(
        page_id="soulseek",
        role=session.role,
        navigation=_build_primary_navigation(
            session,
            active="soulseek",
            soulseek_badge=soulseek_badge,
        ),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
    )

    status_url = _safe_url_for(request, "soulseek_status_fragment", "/ui/soulseek/status")
    status_fragment = AsyncFragment(
        identifier="hx-soulseek-status",
        url=status_url,
        target="#hx-soulseek-status",
        poll_interval_seconds=60,
        loading_key="soulseek.status",
    )

    configuration_url = _safe_url_for(
        request, "soulseek_configuration_fragment", "/ui/soulseek/config"
    )
    configuration_fragment = AsyncFragment(
        identifier="hx-soulseek-configuration",
        url=configuration_url,
        target="#hx-soulseek-configuration",
        loading_key="soulseek.configuration",
    )

    uploads_url = _safe_url_for(request, "soulseek_uploads_fragment", "/ui/soulseek/uploads")
    uploads_fragment = AsyncFragment(
        identifier="hx-soulseek-uploads",
        url=uploads_url,
        target="#hx-soulseek-uploads",
        poll_interval_seconds=30,
        loading_key="soulseek.uploads",
    )

    downloads_url = _safe_url_for(request, "soulseek_downloads_fragment", "/ui/soulseek/downloads")
    downloads_fragment = AsyncFragment(
        identifier="hx-soulseek-downloads",
        url=downloads_url,
        target="#hx-soulseek-downloads",
        poll_interval_seconds=30,
        loading_key="soulseek.downloads",
    )

    discography_url = _safe_url_for(
        request,
        "soulseek_discography_jobs_fragment",
        "/ui/soulseek/discography/jobs",
    )
    discography_fragment = AsyncFragment(
        identifier="hx-soulseek-discography-jobs",
        url=discography_url,
        target="#hx-soulseek-discography-jobs",
        poll_interval_seconds=60,
        loading_key="soulseek.discography",
    )

    user_info_url = _safe_url_for(
        request,
        "soulseek_user_info_fragment",
        "/ui/soulseek/user/info",
    )
    user_info_fragment = AsyncFragment(
        identifier="hx-soulseek-user-info",
        url=user_info_url,
        target="#hx-soulseek-user-info",
        loading_key="soulseek.user.profile",
    )

    user_directory_url = _safe_url_for(
        request,
        "soulseek_user_directory_fragment",
        "/ui/soulseek/user/directory",
    )
    user_directory_fragment = AsyncFragment(
        identifier="hx-soulseek-user-directory",
        url=user_directory_url,
        target="#hx-soulseek-user-directory",
        loading_key="soulseek.user.directory",
    )

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "csrf_token": csrf_token,
        "status_fragment": status_fragment,
        "configuration_fragment": configuration_fragment,
        "uploads_fragment": uploads_fragment,
        "downloads_fragment": downloads_fragment,
        "discography_fragment": discography_fragment,
        "user_info_fragment": user_info_fragment,
        "user_directory_fragment": user_directory_fragment,
        "suggested_tasks": tuple(suggested_tasks),
        "tasks_completion": tasks_completion,
    }


def build_soulseek_status_context(
    request: Request,
    *,
    status: StatusResponse,
    health: IntegrationHealth,
    layout: LayoutContext | None = None,
) -> Mapping[str, Any]:
    connection_badge = _status_badge(
        status=status.status,
        test_id="soulseek-status-connection",
        success_label="soulseek.status.connected",
        degraded_label="soulseek.status.degraded",
        down_label="soulseek.status.disconnected",
        unknown_label="soulseek.status.unknown",
        degrade_is_warning=False,
    )
    integration_badge = _status_badge(
        status=health.overall,
        test_id="soulseek-status-integrations",
        success_label="soulseek.integration.ok",
        degraded_label="soulseek.integration.degraded",
        down_label="soulseek.integration.down",
        unknown_label="soulseek.integration.unknown",
    )

    provider_rows: list[TableRow] = []
    for report in sorted(health.providers, key=lambda entry: (entry.provider or "").lower()):
        provider_name = report.provider or "unknown"
        provider_badge = _status_badge(
            status=report.status,
            test_id=f"soulseek-provider-{provider_name}-status",
            success_label="soulseek.integration.ok",
            degraded_label="soulseek.integration.degraded",
            down_label="soulseek.integration.down",
            unknown_label="soulseek.integration.unknown",
        )
        details_text = _format_health_details(report.details)
        if details_text:
            details_cell = TableCell(text=details_text)
        else:
            details_cell = TableCell(text_key="soulseek.providers.details.none")
        provider_rows.append(
            TableRow(
                cells=(
                    TableCell(text=provider_name),
                    TableCell(badge=provider_badge),
                    details_cell,
                ),
                test_id=f"soulseek-provider-{provider_name}",
            )
        )

    provider_table = TableDefinition(
        identifier="soulseek-providers-table",
        column_keys=(
            "soulseek.providers.name",
            "soulseek.providers.status",
            "soulseek.providers.details",
        ),
        rows=tuple(provider_rows),
        caption_key="soulseek.providers.caption",
    )

    return {
        "request": request,
        "connection_badge": connection_badge,
        "integration_badge": integration_badge,
        "provider_table": provider_table,
        "layout": layout,
    }


def _boolean_badge(
    value: bool,
    *,
    test_id: str,
    highlight_missing: bool = False,
) -> StatusBadge:
    if value:
        return StatusBadge(
            label_key="status.enabled",
            variant="success",
            test_id=test_id,
        )
    return StatusBadge(
        label_key="status.disabled",
        variant="danger" if highlight_missing else "muted",
        test_id=test_id,
    )


def _format_percentage(value: float | None) -> str:
    if value is None:
        return ""
    clamped = max(0.0, min(value, 1.0))
    return f"{clamped * 100.0:.0f}%"


def _format_transfer_size(size: int | None) -> str:
    if size is None or size < 0:
        return ""
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    value = float(size)
    for index, unit in enumerate(units):
        if value < 1024.0 or index == len(units) - 1:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return ""


def _format_transfer_speed(speed: float | None) -> str:
    if speed is None or speed < 0:
        return ""
    value = float(speed)
    if value < 1024.0:
        return f"{value:.0f} B/s"
    value /= 1024.0
    if value < 1024.0:
        return f"{value:.1f} KiB/s"
    value /= 1024.0
    return f"{value:.1f} MiB/s"


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    trimmed = value.replace(microsecond=0)
    return trimmed.isoformat(sep=" ")


def _summarize_live_metadata(metadata: Mapping[str, Any] | None) -> str:
    if not metadata:
        return ""
    highlights: list[str] = []
    for key in ("status", "progress", "speed", "eta", "peer"):
        if key in metadata:
            highlights.append(f"{key}={metadata[key]}")
    if not highlights:
        for index, (key, value) in enumerate(metadata.items()):
            highlights.append(f"{key}={value}")
            if index >= 2:
                break
    return ", ".join(str(entry) for entry in highlights if entry)


def _soulseek_download_status_badge(status: str) -> StatusBadge:
    normalised = (status or "").strip().lower() or "unknown"
    label_key = f"soulseek.downloads.status.{normalised}"
    test_id = f"soulseek-download-status-{normalised}"
    if normalised in {"queued", "pending", "running", "downloading"}:
        return StatusBadge(label_key=label_key, variant="success", test_id=test_id)
    if normalised in set(SOULSEEK_RETRYABLE_STATES) | {"failed", "dead_letter"}:
        return StatusBadge(label_key=label_key, variant="danger", test_id=test_id)
    return StatusBadge(label_key=label_key, variant="muted", test_id=test_id)


def build_soulseek_config_context(
    request: Request,
    *,
    soulseek_config: SoulseekConfig,
    security_config: SecurityConfig,
) -> Mapping[str, Any]:
    has_api_key = bool((soulseek_config.api_key or "").strip())
    if soulseek_config.preferred_formats:
        preferred_formats = ", ".join(soulseek_config.preferred_formats)
    else:
        preferred_formats = "Any"

    if has_api_key:
        api_key_cell = TableCell(
            text_key="soulseek.config.api_key_set",
            test_id="soulseek-config-api-key",
        )
    else:
        api_key_cell = TableCell(
            badge=StatusBadge(
                label_key="soulseek.config.api_key_missing",
                variant="danger",
                test_id="soulseek-config-api-key",
            )
        )

    rows = [
        TableRow(
            cells=(
                TableCell(text_key="soulseek.config.base_url"),
                TableCell(text=soulseek_config.base_url),
            ),
            test_id="soulseek-config-base-url",
        ),
        TableRow(
            cells=(
                TableCell(text_key="soulseek.config.api_key"),
                api_key_cell,
            ),
        ),
        TableRow(
            cells=(
                TableCell(text_key="soulseek.config.timeout"),
                TableCell(text=f"{soulseek_config.timeout_ms} ms"),
            ),
        ),
        TableRow(
            cells=(
                TableCell(text_key="soulseek.config.retry_max"),
                TableCell(text=str(soulseek_config.retry_max)),
            ),
        ),
        TableRow(
            cells=(
                TableCell(text_key="soulseek.config.retry_backoff"),
                TableCell(text=f"{soulseek_config.retry_backoff_base_ms} ms"),
            ),
        ),
        TableRow(
            cells=(
                TableCell(text_key="soulseek.config.retry_jitter"),
                TableCell(text=f"{soulseek_config.retry_jitter_pct}%"),
            ),
        ),
        TableRow(
            cells=(
                TableCell(text_key="soulseek.config.preferred_formats"),
                TableCell(text=preferred_formats),
            ),
        ),
        TableRow(
            cells=(
                TableCell(text_key="soulseek.config.max_results"),
                TableCell(text=str(soulseek_config.max_results)),
            ),
        ),
        TableRow(
            cells=(
                TableCell(text_key="soulseek.config.security_profile"),
                TableCell(text=security_config.profile),
            ),
        ),
        TableRow(
            cells=(
                TableCell(text_key="soulseek.config.require_auth"),
                TableCell(
                    badge=_boolean_badge(
                        security_config.require_auth,
                        test_id="soulseek-config-require-auth",
                    )
                ),
            ),
        ),
        TableRow(
            cells=(
                TableCell(text_key="soulseek.config.rate_limiting"),
                TableCell(
                    badge=_boolean_badge(
                        security_config.rate_limiting_enabled,
                        test_id="soulseek-config-rate-limiting",
                    )
                ),
            ),
        ),
    ]

    table = TableDefinition(
        identifier="soulseek-config-table",
        column_keys=("soulseek.config.setting", "soulseek.config.value"),
        rows=tuple(rows),
        caption_key="soulseek.config.caption",
    )

    return {
        "request": request,
        "table": table,
    }


def build_soulseek_uploads_context(
    request: Request,
    *,
    uploads: Sequence[SoulseekUploadRow],
    csrf_token: str,
    include_all: bool,
    session: UiSession,
) -> Mapping[str, Any]:
    can_manage_uploads = session.allows("admin")
    rows: list[TableRow] = []
    cancel_url = _safe_url_for(
        request,
        "soulseek_upload_cancel",
        "/ui/soulseek/uploads/cancel",
    )
    target = "#hx-soulseek-uploads"
    for upload in uploads:
        hidden_fields = {
            "csrftoken": csrf_token,
            "upload_id": upload.identifier,
        }
        if include_all:
            hidden_fields["scope"] = "all"
        rows.append(
            TableRow(
                cells=(
                    TableCell(text=upload.identifier),
                    TableCell(text=upload.username or ""),
                    TableCell(text=upload.filename),
                    TableCell(text=upload.status),
                    TableCell(text=_format_percentage(upload.progress)),
                    TableCell(text=_format_transfer_size(upload.size_bytes)),
                    TableCell(text=_format_transfer_speed(upload.speed_bps)),
                    TableCell(
                        form=TableCellForm(
                            action=cancel_url,
                            method="post",
                            submit_label_key="soulseek.uploads.cancel",
                            hidden_fields=hidden_fields,
                            hx_target=target,
                            hx_swap="outerHTML",
                            disabled=not can_manage_uploads,
                            test_id="soulseek-upload-cancel",
                        )
                    ),
                ),
                test_id=f"soulseek-upload-{upload.identifier}",
            )
        )

    table = TableDefinition(
        identifier="soulseek-uploads-table",
        column_keys=(
            "soulseek.uploads.id",
            "soulseek.uploads.user",
            "soulseek.uploads.filename",
            "soulseek.uploads.status",
            "soulseek.uploads.progress",
            "soulseek.uploads.size",
            "soulseek.uploads.speed",
            "soulseek.uploads.actions",
        ),
        rows=tuple(rows),
        caption_key="soulseek.uploads.caption",
    )

    base_url = _safe_url_for(
        request,
        "soulseek_uploads_fragment",
        "/ui/soulseek/uploads",
    )
    refresh_url = f"{base_url}?all=1" if include_all else base_url
    cleanup_url = _safe_url_for(
        request,
        "soulseek_uploads_cleanup",
        "/ui/soulseek/uploads/cleanup",
    )

    fragment = TableFragment(
        identifier="hx-soulseek-uploads",
        table=table,
        empty_state_key="soulseek.uploads",
        data_attributes={
            "count": str(len(rows)),
            "scope": "all" if include_all else "active",
            "refresh-url": refresh_url,
        },
    )

    return {
        "request": request,
        "fragment": fragment,
        "csrf_token": csrf_token,
        "include_all": include_all,
        "refresh_url": refresh_url,
        "active_url": base_url,
        "all_url": f"{base_url}?all=1",
        "cleanup_url": cleanup_url,
        "cleanup_target": target,
        "cleanup_swap": "outerHTML",
        "cleanup_disabled": not can_manage_uploads,
        "can_manage_uploads": can_manage_uploads,
    }


def build_soulseek_downloads_context(
    request: Request,
    *,
    page: DownloadPage,
    csrf_token: str,
    include_all: bool,
    session: UiSession,
) -> Mapping[str, Any]:
    scope_value = "all" if include_all else "active"
    retryable_states = set(SOULSEEK_RETRYABLE_STATES)
    target = "#hx-soulseek-downloads"
    can_manage_downloads = session.allows("admin")
    modal_target = "#modal-root"
    modal_swap = "innerHTML"
    action_swap = "outerHTML"

    lyrics_view_base = _download_action_base_url(
        request,
        "soulseek_download_lyrics_modal",
        "/ui/soulseek/download/{download_id}/lyrics",
    )
    lyrics_refresh_base = _download_action_base_url(
        request,
        "soulseek_download_lyrics_refresh",
        "/ui/soulseek/download/{download_id}/lyrics/refresh",
    )
    metadata_view_base = _download_action_base_url(
        request,
        "soulseek_download_metadata_modal",
        "/ui/soulseek/download/{download_id}/metadata",
    )
    metadata_refresh_base = _download_action_base_url(
        request,
        "soulseek_download_metadata_refresh",
        "/ui/soulseek/download/{download_id}/metadata/refresh",
    )
    artwork_view_base = _download_action_base_url(
        request,
        "soulseek_download_artwork_modal",
        "/ui/soulseek/download/{download_id}/artwork",
    )
    artwork_refresh_base = _download_action_base_url(
        request,
        "soulseek_download_artwork_refresh",
        "/ui/soulseek/download/{download_id}/artwork/refresh",
    )

    rows: list[TableRow] = []
    for entry in page.items:
        try:
            requeue_url = request.url_for(
                "soulseek_download_requeue", download_id=str(entry.identifier)
            )
        except Exception:  # pragma: no cover - fallback for tests
            requeue_url = f"/ui/soulseek/downloads/{entry.identifier}/requeue"
        try:
            cancel_url = request.url_for(
                "soulseek_download_cancel", download_id=str(entry.identifier)
            )
        except Exception:  # pragma: no cover - fallback for tests
            cancel_url = f"/ui/soulseek/download/{entry.identifier}"

        try:
            lyrics_view_url = request.url_for(
                "soulseek_download_lyrics_modal", download_id=str(entry.identifier)
            )
        except Exception:  # pragma: no cover - fallback for tests
            lyrics_view_url = f"/ui/soulseek/download/{entry.identifier}/lyrics"
        try:
            lyrics_refresh_url = request.url_for(
                "soulseek_download_lyrics_refresh", download_id=str(entry.identifier)
            )
        except Exception:  # pragma: no cover - fallback for tests
            lyrics_refresh_url = f"/ui/soulseek/download/{entry.identifier}/lyrics/refresh"

        try:
            metadata_view_url = request.url_for(
                "soulseek_download_metadata_modal", download_id=str(entry.identifier)
            )
        except Exception:  # pragma: no cover - fallback for tests
            metadata_view_url = f"/ui/soulseek/download/{entry.identifier}/metadata"
        try:
            metadata_refresh_url = request.url_for(
                "soulseek_download_metadata_refresh", download_id=str(entry.identifier)
            )
        except Exception:  # pragma: no cover - fallback for tests
            metadata_refresh_url = f"/ui/soulseek/download/{entry.identifier}/metadata/refresh"

        try:
            artwork_view_url = request.url_for(
                "soulseek_download_artwork_modal", download_id=str(entry.identifier)
            )
        except Exception:  # pragma: no cover - fallback for tests
            artwork_view_url = f"/ui/soulseek/download/{entry.identifier}/artwork"
        try:
            artwork_refresh_url = request.url_for(
                "soulseek_download_artwork_refresh", download_id=str(entry.identifier)
            )
        except Exception:  # pragma: no cover - fallback for tests
            artwork_refresh_url = f"/ui/soulseek/download/{entry.identifier}/artwork/refresh"

        hidden_fields = {
            "csrftoken": csrf_token,
            "scope": scope_value,
            "limit": str(page.limit),
            "offset": str(page.offset),
        }
        can_requeue = (entry.status or "").lower() in retryable_states
        lyrics_status = (entry.lyrics_status or "").strip().lower()
        artwork_status = (entry.artwork_status or "").strip().lower()
        lyrics_pending = lyrics_status in {"pending", "running", "processing", "queued"}
        artwork_pending = artwork_status in {"pending", "running", "processing", "queued"}
        lyrics_view_disabled = not (entry.has_lyrics and entry.lyrics_path)
        lyrics_refresh_disabled = (not can_manage_downloads) or lyrics_pending
        metadata_view_disabled = entry.organized_path is None
        metadata_refresh_disabled = not can_manage_downloads
        artwork_view_disabled = not (entry.has_artwork and entry.artwork_path)
        artwork_refresh_disabled = (not can_manage_downloads) or artwork_pending

        lyrics_view_form = TableCellForm(
            action=lyrics_view_url,
            method="get",
            submit_label_key="soulseek.downloads.lyrics.view",
            hx_target=modal_target,
            hx_swap=modal_swap,
            hx_method="get",
            disabled=lyrics_view_disabled,
            test_id=f"soulseek-download-lyrics-view-{entry.identifier}",
        )
        lyrics_refresh_form = TableCellForm(
            action=lyrics_refresh_url,
            method="post",
            submit_label_key="soulseek.downloads.lyrics.refresh",
            hidden_fields=hidden_fields,
            hx_target=target,
            hx_swap=action_swap,
            disabled=lyrics_refresh_disabled,
            test_id=f"soulseek-download-lyrics-refresh-{entry.identifier}",
        )

        metadata_view_form = TableCellForm(
            action=metadata_view_url,
            method="get",
            submit_label_key="soulseek.downloads.metadata.view",
            hx_target=modal_target,
            hx_swap=modal_swap,
            hx_method="get",
            disabled=metadata_view_disabled,
            test_id=f"soulseek-download-metadata-view-{entry.identifier}",
        )
        metadata_refresh_form = TableCellForm(
            action=metadata_refresh_url,
            method="post",
            submit_label_key="soulseek.downloads.metadata.refresh",
            hidden_fields=hidden_fields,
            hx_target=target,
            hx_swap=action_swap,
            disabled=metadata_refresh_disabled,
            test_id=f"soulseek-download-metadata-refresh-{entry.identifier}",
        )

        artwork_view_form = TableCellForm(
            action=artwork_view_url,
            method="get",
            submit_label_key="soulseek.downloads.artwork.view",
            hx_target=modal_target,
            hx_swap=modal_swap,
            hx_method="get",
            disabled=artwork_view_disabled,
            test_id=f"soulseek-download-artwork-view-{entry.identifier}",
        )
        artwork_refresh_form = TableCellForm(
            action=artwork_refresh_url,
            method="post",
            submit_label_key="soulseek.downloads.artwork.refresh",
            hidden_fields=hidden_fields,
            hx_target=target,
            hx_swap=action_swap,
            disabled=artwork_refresh_disabled,
            test_id=f"soulseek-download-artwork-refresh-{entry.identifier}",
        )

        rows.append(
            TableRow(
                cells=(
                    TableCell(text=str(entry.identifier)),
                    TableCell(text=entry.filename),
                    TableCell(badge=_soulseek_download_status_badge(entry.status)),
                    TableCell(text=_format_percentage(entry.progress)),
                    TableCell(text=str(entry.priority)),
                    TableCell(text=entry.username or ""),
                    TableCell(text=str(entry.retry_count)),
                    TableCell(text=_format_datetime(entry.next_retry_at)),
                    TableCell(text=entry.last_error or ""),
                    TableCell(text=_summarize_live_metadata(entry.live_queue)),
                    TableCell(
                        forms=(lyrics_view_form, lyrics_refresh_form),
                        test_id=f"soulseek-download-lyrics-actions-{entry.identifier}",
                    ),
                    TableCell(
                        forms=(metadata_view_form, metadata_refresh_form),
                        test_id=f"soulseek-download-metadata-actions-{entry.identifier}",
                    ),
                    TableCell(
                        forms=(artwork_view_form, artwork_refresh_form),
                        test_id=f"soulseek-download-artwork-actions-{entry.identifier}",
                    ),
                    TableCell(
                        form=TableCellForm(
                            action=requeue_url,
                            method="post",
                            submit_label_key="soulseek.downloads.requeue",
                            hidden_fields=hidden_fields,
                            hx_target=target,
                            hx_swap=action_swap,
                            disabled=not (can_manage_downloads and can_requeue),
                            test_id="soulseek-download-requeue",
                        )
                    ),
                    TableCell(
                        form=TableCellForm(
                            action=cancel_url,
                            method="post",
                            submit_label_key="soulseek.downloads.cancel",
                            hidden_fields=hidden_fields,
                            hx_target=target,
                            hx_swap=action_swap,
                            hx_method="delete",
                            disabled=not can_manage_downloads,
                            test_id="soulseek-download-cancel",
                        )
                    ),
                ),
                test_id=f"soulseek-download-{entry.identifier}",
            )
        )

    table = TableDefinition(
        identifier="soulseek-downloads-table",
        column_keys=(
            "downloads.id",
            "downloads.filename",
            "downloads.status",
            "downloads.progress",
            "downloads.priority",
            "downloads.user",
            "soulseek.downloads.retry_count",
            "soulseek.downloads.next_retry",
            "soulseek.downloads.last_error",
            "soulseek.downloads.live",
            "soulseek.downloads.lyrics",
            "soulseek.downloads.metadata",
            "soulseek.downloads.artwork",
            "soulseek.downloads.requeue",
            "soulseek.downloads.cancel",
        ),
        rows=tuple(rows),
        caption_key="downloads.table.caption",
    )

    base_url = _safe_url_for(
        request,
        "soulseek_downloads_fragment",
        "/ui/soulseek/downloads",
    )

    def _url_for_scope(all_scope: bool) -> str:
        query = [("limit", str(page.limit)), ("offset", str(page.offset))]
        if all_scope:
            query.append(("all", "1"))
        return f"{base_url}?{urlencode(query)}"

    refresh_url = _url_for_scope(include_all)
    cleanup_url = _safe_url_for(
        request,
        "soulseek_downloads_cleanup",
        "/ui/soulseek/downloads/cleanup",
    )

    def _page_url(new_offset: int) -> str:
        query = [("limit", str(page.limit)), ("offset", str(max(new_offset, 0)))]
        if include_all:
            query.append(("all", "1"))
        return f"{base_url}?{urlencode(query)}"

    previous_url = _page_url(page.offset - page.limit) if page.has_previous else None
    next_url = _page_url(page.offset + page.limit) if page.has_next else None

    pagination: PaginationContext | None = None
    if previous_url or next_url:
        pagination = PaginationContext(
            label_key="downloads",
            target=target,
            previous_url=previous_url,
            next_url=next_url,
        )

    fragment = TableFragment(
        identifier="hx-soulseek-downloads",
        table=table,
        empty_state_key="soulseek.downloads",
        data_attributes={
            "count": str(len(rows)),
            "limit": str(page.limit),
            "offset": str(page.offset),
            "scope": scope_value,
            "refresh-url": refresh_url,
            "modal-target": modal_target,
            "modal-swap": modal_swap,
            "action-target": target,
            "action-swap": action_swap,
            "lyrics-view-base": lyrics_view_base,
            "lyrics-refresh-base": lyrics_refresh_base,
            "metadata-view-base": metadata_view_base,
            "metadata-refresh-base": metadata_refresh_base,
            "artwork-view-base": artwork_view_base,
            "artwork-refresh-base": artwork_refresh_base,
        },
        pagination=pagination,
    )

    return {
        "request": request,
        "fragment": fragment,
        "csrf_token": csrf_token,
        "include_all": include_all,
        "refresh_url": refresh_url,
        "active_url": _url_for_scope(False),
        "all_url": _url_for_scope(True),
        "cleanup_url": cleanup_url,
        "cleanup_target": pagination.target if pagination else target,
        "cleanup_swap": pagination.swap if pagination else "outerHTML",
        "cleanup_disabled": not can_manage_downloads,
        "can_manage_downloads": can_manage_downloads,
    }


@dataclass(slots=True)
class SoulseekDirectoryLinkView:
    name: str
    path: str
    url: str


@dataclass(slots=True)
class SoulseekFileView:
    name: str
    path: str | None
    size: str


_USER_ONLINE_STATES = frozenset({"online", "connected", "available"})
_USER_OFFLINE_STATES = frozenset({"offline", "disconnected"})
_USER_IDLE_STATES = frozenset({"idle", "away"})
_BROWSE_ACTIVE_STATES = frozenset({"browsing", "running", "processing"})
_BROWSE_WAITING_STATES = frozenset({"queued", "pending", "waiting"})


def _format_percentage_optional(value: float | None) -> str | None:
    if value is None:
        return None
    bounded = max(0.0, min(value, 1.0)) * 100.0
    if abs(bounded - round(bounded)) < 0.01:
        return f"{int(round(bounded))}%"
    return f"{bounded:.0f}%"


def _user_status_badge(status: SoulseekUserStatus | None) -> StatusBadge | None:
    if status is None:
        return None
    state = (status.state or "unknown").lower()
    if state in _USER_ONLINE_STATES:
        variant: StatusVariant = "success"
        label_key = "soulseek.user.online"
    elif state in _USER_OFFLINE_STATES:
        variant = "danger"
        label_key = "soulseek.user.offline"
    elif state in _USER_IDLE_STATES:
        variant = "muted"
        label_key = "soulseek.user.away"
    else:
        variant = "muted"
        label_key = "soulseek.user.unknown"
    return StatusBadge(label_key=label_key, variant=variant, test_id="soulseek-user-status-badge")


def _user_browse_badge(status: SoulseekUserBrowsingStatus | None) -> StatusBadge | None:
    if status is None:
        return None
    state = (status.state or "unknown").lower()
    if state in _BROWSE_ACTIVE_STATES:
        variant: StatusVariant = "success"
        label_key = "soulseek.user.browse.active"
    elif state in _BROWSE_WAITING_STATES:
        variant = "muted"
        label_key = "soulseek.user.browse.waiting"
    elif state in {"complete", "completed", "done"}:
        variant = "success"
        label_key = "soulseek.user.browse.completed"
    else:
        variant = "muted"
        label_key = "soulseek.user.browse.unknown"
    return StatusBadge(label_key=label_key, variant=variant, test_id="soulseek-user-browse-badge")


def _user_browse_queue(status: SoulseekUserBrowsingStatus | None) -> tuple[int, int | None] | None:
    if status is None:
        return None
    if status.queue_position is None:
        return None
    return (status.queue_position, status.queue_length)


def _build_user_status_context(
    status: SoulseekUserStatus | None,
    browsing: SoulseekUserBrowsingStatus | None,
) -> dict[str, Any]:
    shared_value = status.shared_files if status else None
    status_message = status.message if status and status.message else None
    browse_message = browsing.message if browsing and browsing.message else None
    progress_value = _format_percentage_optional(browsing.progress if browsing else None)
    queue_value = _user_browse_queue(browsing)
    return {
        "user_status": status,
        "user_status_badge": _user_status_badge(status),
        "user_status_message": status_message,
        "user_status_shared": shared_value,
        "user_status_has_shared": shared_value is not None,
        "user_browse_status": browsing,
        "user_browse_badge": _user_browse_badge(browsing),
        "user_browse_message": browse_message,
        "user_browse_progress": progress_value,
        "user_browse_has_progress": bool(progress_value),
        "user_browse_queue": queue_value,
        "user_browse_has_queue": queue_value is not None,
        "has_user_status": status is not None,
        "has_user_browse_status": browsing is not None,
    }


def build_soulseek_user_profile_context(
    request: Request,
    *,
    username: str | None,
    profile: SoulseekUserProfile | None,
    status: SoulseekUserStatus | None,
    browsing_status: SoulseekUserBrowsingStatus | None,
) -> Mapping[str, Any]:
    lookup_url = _safe_url_for(
        request,
        "soulseek_user_info_fragment",
        "/ui/soulseek/user/info",
    )
    trimmed_username = (username or "").strip()
    address_items: tuple[tuple[str, str], ...] = ()
    info_items: tuple[tuple[str, str], ...] = ()
    if profile is not None:
        address_items = tuple(sorted(profile.address.items()))
        info_items = tuple(sorted(profile.info.items()))
        trimmed_username = profile.username
    context = {
        "request": request,
        "lookup_url": lookup_url,
        "username": trimmed_username,
        "profile": profile,
        "address_items": address_items,
        "info_items": info_items,
        "has_profile": bool(profile and (address_items or info_items)),
    }
    context.update(_build_user_status_context(status, browsing_status))
    return context


def build_soulseek_user_directory_context(
    request: Request,
    *,
    username: str | None,
    path: str | None,
    listing: SoulseekUserDirectoryListing | None,
    status: SoulseekUserStatus | None,
    browsing_status: SoulseekUserBrowsingStatus | None,
) -> Mapping[str, Any]:
    browse_url = _safe_url_for(
        request,
        "soulseek_user_directory_fragment",
        "/ui/soulseek/user/directory",
    )
    base_url = URL(browse_url)
    trimmed_username = (username or "").strip()
    if listing is not None:
        trimmed_username = listing.username

    def _entry_url(path_value: str | None) -> str:
        params: dict[str, str] = {}
        if trimmed_username:
            params["username"] = trimmed_username
        if path_value:
            params["path"] = path_value
        if not params:
            return browse_url
        return str(base_url.include_query_params(**params))

    directories: tuple[SoulseekDirectoryLinkView, ...] = ()
    files: tuple[SoulseekFileView, ...] = ()
    current_path = path.strip() if isinstance(path, str) else None
    parent_path: str | None = None
    if listing is not None:
        current_path = listing.current_path
        parent_path = listing.parent_path
        directories = tuple(
            SoulseekDirectoryLinkView(
                name=entry.name,
                path=entry.path,
                url=_entry_url(entry.path),
            )
            for entry in listing.directories
        )
        files = tuple(
            SoulseekFileView(
                name=file.name,
                path=file.path,
                size=_format_transfer_size(file.size_bytes) or "",
            )
            for file in listing.files
        )
    parent_url = _entry_url(parent_path) if parent_path else None
    context = {
        "request": request,
        "browse_url": browse_url,
        "username": trimmed_username,
        "path": current_path,
        "directories": directories,
        "files": files,
        "listing": listing,
        "parent_path": parent_path,
        "parent_url": parent_url,
        "has_listing": bool(listing),
    }
    context.update(_build_user_status_context(status, browsing_status))
    return context


def build_soulseek_discography_jobs_context(
    request: Request,
    *,
    jobs: Sequence[Any],
    modal_url: str,
    alerts: Sequence[AlertMessage] = (),
) -> Mapping[str, Any]:
    rows: list[TableRow] = []
    for job in jobs:
        artist_name = getattr(job, "artist_name", None) or ""
        artist_id = getattr(job, "artist_id", "")
        if artist_name and artist_id:
            artist_label = f"{artist_name} ({artist_id})"
        else:
            artist_label = artist_name or artist_id or ""
        identifier = getattr(job, "id", "unknown")
        rows.append(
            TableRow(
                cells=(
                    TableCell(
                        text=str(getattr(job, "id", "")),
                        test_id=f"soulseek-discography-job-{identifier}-id",
                    ),
                    TableCell(
                        text=artist_label,
                        test_id=f"soulseek-discography-job-{identifier}-artist",
                    ),
                    TableCell(
                        badge=_discography_status_badge(getattr(job, "status", "")),
                        test_id=f"soulseek-discography-job-{identifier}-status",
                    ),
                    TableCell(
                        text=_format_datetime(getattr(job, "created_at", None)),
                        test_id=f"soulseek-discography-job-{identifier}-created",
                    ),
                    TableCell(
                        text=_format_datetime(getattr(job, "updated_at", None)),
                        test_id=f"soulseek-discography-job-{identifier}-updated",
                    ),
                ),
                test_id=f"soulseek-discography-job-{identifier}",
            )
        )

    table = TableDefinition(
        identifier="soulseek-discography-jobs-table",
        column_keys=(
            "soulseek.discography.job_id",
            "soulseek.discography.artist",
            "soulseek.discography.status",
            "soulseek.discography.created",
            "soulseek.discography.updated",
        ),
        rows=tuple(rows),
    )
    fragment = TableFragment(
        identifier="hx-soulseek-discography-jobs",
        table=table,
        empty_state_key="soulseek.discography.jobs",
        data_attributes={"count": str(len(rows))},
    )
    return {
        "request": request,
        "fragment": fragment,
        "modal_url": modal_url,
        "alerts": tuple(alerts),
    }


def build_soulseek_discography_modal_context(
    request: Request,
    *,
    submit_url: str,
    csrf_token: str,
    target_id: str,
    form_values: Mapping[str, str] | None = None,
    form_errors: Mapping[str, str] | None = None,
) -> Mapping[str, Any]:
    values = {"artist_id": "", "artist_name": ""}
    if form_values:
        for key, value in form_values.items():
            if key in values:
                values[key] = value
    errors = dict(form_errors or {})
    return {
        "request": request,
        "modal_id": "soulseek-discography-job-modal",
        "submit_url": submit_url,
        "csrf_token": csrf_token,
        "target_id": target_id,
        "form_values": values,
        "form_errors": errors,
    }


def build_soulseek_download_lyrics_modal_context(
    request: Request,
    *,
    download_id: int,
    filename: str,
    asset_status: str | None,
    has_lyrics: bool,
    content: str | None,
    pending: bool,
) -> Mapping[str, Any]:
    status_value = asset_status or ("ready" if has_lyrics else "")
    return {
        "request": request,
        "modal_id": "soulseek-download-lyrics-modal",
        "asset": "lyrics",
        "download_id": download_id,
        "filename": filename,
        "asset_status": _normalise_status(status_value),
        "has_asset": has_lyrics,
        "content": content,
        "pending": pending,
    }


def build_soulseek_download_metadata_modal_context(
    request: Request,
    *,
    download_id: int,
    filename: str,
    metadata: Mapping[str, str | None],
) -> Mapping[str, Any]:
    entries: list[Mapping[str, str | None]] = []
    for key in ("genre", "composer", "producer", "isrc", "copyright"):
        entries.append(
            {
                "key": key,
                "value": metadata.get(key),
            }
        )
    has_metadata = any((value or "").strip() for value in metadata.values())
    status_value = "ready" if has_metadata else ""
    return {
        "request": request,
        "modal_id": "soulseek-download-metadata-modal",
        "asset": "metadata",
        "download_id": download_id,
        "filename": filename,
        "asset_status": _normalise_status(status_value),
        "metadata_entries": tuple(entries),
        "has_metadata": has_metadata,
    }


def build_soulseek_download_artwork_modal_context(
    request: Request,
    *,
    download_id: int,
    filename: str,
    asset_status: str | None,
    has_artwork: bool,
    image_url: str | None,
) -> Mapping[str, Any]:
    status_value = asset_status or ("ready" if has_artwork else "")
    return {
        "request": request,
        "modal_id": "soulseek-download-artwork-modal",
        "asset": "artwork",
        "download_id": download_id,
        "filename": filename,
        "asset_status": _normalise_status(status_value),
        "has_asset": has_artwork,
        "image_url": image_url,
    }


__all__ = [
    "SoulseekDirectoryLinkView",
    "SoulseekFileView",
    "build_soulseek_navigation_badge",
    "build_soulseek_page_context",
    "build_soulseek_status_context",
    "build_soulseek_config_context",
    "build_soulseek_uploads_context",
    "build_soulseek_downloads_context",
    "build_soulseek_user_profile_context",
    "build_soulseek_user_directory_context",
    "build_soulseek_discography_jobs_context",
    "build_soulseek_discography_modal_context",
    "build_soulseek_download_lyrics_modal_context",
    "build_soulseek_download_metadata_modal_context",
    "build_soulseek_download_artwork_modal_context",
]
