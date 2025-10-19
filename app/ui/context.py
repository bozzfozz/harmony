from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
import json
from html import escape
from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import Request
from starlette.datastructures import URL

from app.api.search import DEFAULT_SOURCES
from app.config import SecurityConfig, SoulseekConfig
from app.integrations.health import IntegrationHealth
from app.schemas import SOULSEEK_RETRYABLE_STATES, StatusResponse
from app.ui.services import (
    DownloadPage,
    DownloadRow,
    OrchestratorJob,
    SearchResultsPage,
    SoulseekUploadRow,
    SpotifyAccountSummary,
    SpotifyArtistRow,
    SpotifyBackfillSnapshot,
    SpotifyFreeIngestJobSnapshot,
    SpotifyFreeIngestResult,
    SpotifyManualResult,
    SpotifyOAuthHealth,
    SpotifyPlaylistItemRow,
    SpotifyPlaylistRow,
    SpotifyRecommendationRow,
    SpotifyRecommendationSeed,
    SpotifySavedTrackRow,
    SpotifyTrackDetail,
    SpotifyTopArtistRow,
    SpotifyTopTrackRow,
    SpotifyStatus,
    WatchlistRow,
)
from app.ui.session import UiFeatures, UiSession

AlertLevel = Literal["info", "success", "warning", "error"]
ButtonMethod = Literal["get", "post"]
HxMethod = Literal["get", "post", "put", "patch", "delete"]
StatusVariant = Literal["success", "danger", "muted"]


@dataclass(slots=True)
class NavItem:
    label_key: str
    href: str
    active: bool = False
    test_id: str | None = None
    badge: StatusBadge | None = None


@dataclass(slots=True)
class NavigationContext:
    primary: Sequence[NavItem] = field(default_factory=tuple)


@dataclass(slots=True)
class AlertMessage:
    level: AlertLevel
    text: str


@dataclass(slots=True)
class MetaTag:
    name: str
    content: str


@dataclass(slots=True)
class ModalDefinition:
    identifier: str
    title_key: str
    body: str


@dataclass(slots=True)
class DefinitionItem:
    label_key: str
    value: str
    test_id: str | None = None
    is_missing: bool = False


@dataclass(slots=True)
class LayoutContext:
    page_id: str
    role: str | None
    navigation: NavigationContext = field(default_factory=NavigationContext)
    alerts: Sequence[AlertMessage] = field(default_factory=tuple)
    head_meta: Sequence[MetaTag] = field(default_factory=tuple)
    modals: Sequence[ModalDefinition] = field(default_factory=tuple)


@dataclass(slots=True)
class FormField:
    name: str
    input_type: str
    label_key: str
    autocomplete: str | None = None
    required: bool = False


@dataclass(slots=True)
class CheckboxOption:
    value: str
    label_key: str
    checked: bool = False
    test_id: str | None = None


@dataclass(slots=True)
class CheckboxGroup:
    name: str
    legend_key: str
    description_key: str | None = None
    options: Sequence[CheckboxOption] = field(default_factory=tuple)


@dataclass(slots=True)
class FormDefinition:
    identifier: str
    method: ButtonMethod
    action: str
    submit_label_key: str
    fields: Sequence[FormField] = field(default_factory=tuple)
    checkbox_groups: Sequence[CheckboxGroup] = field(default_factory=tuple)


@dataclass(slots=True)
class ActionButton:
    identifier: str
    label_key: str


@dataclass(slots=True)
class StatusBadge:
    label_key: str
    variant: StatusVariant
    test_id: str | None = None


@dataclass(slots=True)
class TableCell:
    text_key: str | None = None
    text: str | None = None
    html: str | None = None
    badge: StatusBadge | None = None
    test_id: str | None = None
    form: "TableCellForm" | None = None
    forms: Sequence["TableCellForm"] = field(default_factory=tuple)


def _build_external_link_cell(
    url: str | None,
    *,
    cell_test_id: str,
    anchor_test_id: str,
    label: str,
    aria_label: str,
) -> TableCell:
    if not url:
        return TableCell(text="—", test_id=cell_test_id)

    anchor_html = (
        f'<a class="table-external-link" '
        f'href="{escape(url, quote=True)}" '
        'target="_blank" '
        'rel="noopener" '
        f'data-test="{escape(anchor_test_id, quote=True)}" '
        f'aria-label="{escape(aria_label, quote=True)}">'
        f"{escape(label)} "
        '<span class="table-external-link__icon" aria-hidden="true">↗</span>'
        "</a>"
    )
    return TableCell(html=anchor_html, test_id=cell_test_id)


@dataclass(slots=True)
class TableRow:
    cells: Sequence[TableCell]
    test_id: str | None = None


@dataclass(slots=True)
class TableDefinition:
    identifier: str
    column_keys: Sequence[str]
    rows: Sequence[TableRow]
    caption_key: str | None = None


@dataclass(slots=True)
class PaginationContext:
    label_key: str
    target: str
    swap: str = "outerHTML"
    previous_url: str | None = None
    next_url: str | None = None


@dataclass(slots=True)
class TableFragment:
    identifier: str
    table: TableDefinition
    empty_state_key: str
    data_attributes: Mapping[str, str] = field(default_factory=dict)
    pagination: PaginationContext | None = None


@dataclass(slots=True)
class TableCellForm:
    action: str
    method: ButtonMethod
    submit_label_key: str
    hidden_fields: Mapping[str, str] = field(default_factory=dict)
    hx_target: str | None = None
    hx_swap: str = "innerHTML"
    disabled: bool = False
    hx_method: HxMethod = "post"
    test_id: str | None = None


@dataclass(slots=True)
class AsyncFragment:
    identifier: str
    url: str
    target: str
    load_event: str = "load"
    poll_interval_seconds: int | None = None
    swap: str = "outerHTML"
    loading_key: str = "loading"

    @property
    def trigger(self) -> str:
        parts = [self.load_event]
        if self.poll_interval_seconds is not None:
            parts.append(f"every {self.poll_interval_seconds}s")
        return ", ".join(parts)


@dataclass(slots=True)
class SpotifyTimeRangeOption:
    value: str
    label: str
    url: str
    active: bool
    test_id: str


_SPOTIFY_TIME_RANGE_LABELS: Mapping[str, str] = {
    "short_term": "Last 4 weeks",
    "medium_term": "Last 6 months",
    "long_term": "All time",
}


def _build_time_range_options(
    request: Request,
    *,
    endpoint_name: str,
    fragment_id: str,
    selected: str,
    fallback_path: str,
) -> tuple[SpotifyTimeRangeOption, ...]:
    try:
        base_raw = request.url_for(endpoint_name)
    except Exception:
        base_raw = fallback_path
    base_url = URL(str(base_raw))
    options: list[SpotifyTimeRangeOption] = []
    for value, label in _SPOTIFY_TIME_RANGE_LABELS.items():
        option_url = base_url.include_query_params(time_range=value)
        options.append(
            SpotifyTimeRangeOption(
                value=value,
                label=label,
                url=str(option_url),
                active=value == selected,
                test_id=f"{fragment_id}-range-{value}",
            )
        )
    return tuple(options)


@dataclass(slots=True)
class SpotifyFreeIngestFormContext:
    csrf_token: str
    playlist_value: str
    tracks_value: str
    accepted_items: Sequence[DefinitionItem] = field(default_factory=tuple)
    skipped_items: Sequence[DefinitionItem] = field(default_factory=tuple)
    result: SpotifyFreeIngestResult | None = None
    form_errors: Mapping[str, str] = field(default_factory=dict)
    upload_error: str | None = None


@dataclass(slots=True)
class SpotifyFreeIngestJobContext:
    job_id: str
    state: str
    counts: Sequence[DefinitionItem]
    accepted_items: Sequence[DefinitionItem]
    skipped_items: Sequence[DefinitionItem]
    queued_tracks: int
    failed_tracks: int
    skipped_tracks: int
    error: str | None = None
    skip_reason: str | None = None


_SEARCH_SOURCE_LABELS: dict[str, str] = {
    "spotify": "search.sources.spotify",
    "soulseek": "search.sources.soulseek",
}


def _normalise_status(value: str) -> str:
    return value.strip().lower() if value else ""


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


def _safe_url_for(request: Request, name: str, fallback: str) -> str:
    try:
        return request.url_for(name)
    except Exception:  # pragma: no cover - fallback for tests
        return fallback


def _build_search_form(default_sources: Sequence[str]) -> FormDefinition:
    default_source_set = {source for source in default_sources}
    ordered_sources = list(_SEARCH_SOURCE_LABELS.keys())
    for source in DEFAULT_SOURCES:
        if source not in ordered_sources:
            ordered_sources.append(source)

    checkbox_options: list[CheckboxOption] = []
    for source in ordered_sources:
        label_key = _SEARCH_SOURCE_LABELS.get(source, f"search.sources.{source}")
        checkbox_options.append(
            CheckboxOption(
                value=source,
                label_key=label_key,
                checked=source in default_source_set,
                test_id=f"search-source-{source}",
            )
        )

    sources_group = CheckboxGroup(
        name="sources",
        legend_key="search.sources.legend",
        description_key="search.sources.description",
        options=tuple(checkbox_options),
    )

    return FormDefinition(
        identifier="search-form",
        method="post",
        action="/ui/search/results",
        submit_label_key="search.submit",
        fields=(
            FormField(
                name="query",
                input_type="search",
                label_key="search.query",
                autocomplete="off",
                required=True,
            ),
            FormField(
                name="limit",
                input_type="number",
                label_key="search.limit",
            ),
        ),
        checkbox_groups=(sources_group,),
    )


def build_login_page_context(request: Request, *, error: str | None = None) -> Mapping[str, Any]:
    alerts: list[AlertMessage] = []
    if error:
        alerts.append(AlertMessage(level="error", text=error))

    layout = LayoutContext(
        page_id="login",
        role="anonymous",
        alerts=tuple(alerts),
    )

    login_form = FormDefinition(
        identifier="login-form",
        method="post",
        action="/ui/login",
        submit_label_key="login.submit",
        fields=(
            FormField(
                name="api_key",
                input_type="password",
                label_key="login.api_key",
                autocomplete="off",
                required=True,
            ),
        ),
    )

    return {
        "request": request,
        "layout": layout,
        "form": login_form,
    }


def _build_primary_navigation(
    session: UiSession,
    *,
    active: str,
    soulseek_badge: StatusBadge | None = None,
) -> NavigationContext:
    items: list[NavItem] = [
        NavItem(
            label_key="nav.home",
            href="/ui",
            active=active == "home",
            test_id="nav-home",
        )
    ]

    if session.features.spotify and session.allows("operator"):
        items.append(
            NavItem(
                label_key="nav.spotify",
                href="/ui/spotify",
                active=active == "spotify",
                test_id="nav-spotify",
            )
        )

    if session.features.soulseek:
        items.append(
            NavItem(
                label_key="nav.soulseek",
                href="/ui/soulseek",
                active=active in {"soulseek", "search"},
                test_id="nav-soulseek",
                badge=soulseek_badge,
            )
        )

    if session.allows("operator"):
        items.append(
            NavItem(
                label_key="nav.operations",
                href="/ui/operations",
                active=active == "operations",
                test_id="nav-operator",
            )
        )

    if session.allows("admin"):
        items.append(
            NavItem(
                label_key="nav.admin",
                href="/ui/admin",
                active=active == "admin",
                test_id="nav-admin",
            )
        )

    return NavigationContext(primary=tuple(items))


def build_primary_navigation(
    session: UiSession,
    *,
    active: str,
    soulseek_badge: StatusBadge | None = None,
) -> NavigationContext:
    """Public wrapper to build the primary navigation context."""

    return _build_primary_navigation(
        session,
        active=active,
        soulseek_badge=soulseek_badge,
    )


def build_dashboard_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
) -> Mapping[str, Any]:
    actions: list[ActionButton] = []

    if session.allows("operator"):
        actions.append(
            ActionButton(
                identifier="operator-action",
                label_key="dashboard.action.operator",
            )
        )

    if session.allows("admin"):
        actions.append(
            ActionButton(
                identifier="admin-action",
                label_key="dashboard.action.admin",
            )
        )

    layout = LayoutContext(
        page_id="dashboard",
        role=session.role,
        navigation=_build_primary_navigation(session, active="home"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
    )

    features_table = _build_features_table(session.features)

    try:
        activity_url = request.url_for("activity_table")
    except Exception:
        activity_url = "/ui/activity/table"

    activity_fragment = AsyncFragment(
        identifier="hx-activity-table",
        url=activity_url,
        target="#hx-activity-table",
        poll_interval_seconds=60,
    )

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "features_table": features_table,
        "actions": tuple(actions),
        "csrf_token": csrf_token,
        "activity_fragment": activity_fragment,
    }


def _format_activity_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str | int | float):
        return str(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _build_activity_rows(items: Sequence[Mapping[str, Any]]) -> Sequence[TableRow]:
    rows: list[TableRow] = []
    for item in items:
        timestamp = _format_activity_cell(item.get("timestamp", ""))
        action_type = _format_activity_cell(item.get("type", ""))
        status = _format_activity_cell(item.get("status", ""))
        details_value = item.get("details")
        details = _format_activity_cell(details_value)
        rows.append(
            TableRow(
                cells=(
                    TableCell(text=timestamp),
                    TableCell(text=action_type),
                    TableCell(text=status),
                    TableCell(text=details or "—"),
                )
            )
        )
    return tuple(rows)


def build_activity_fragment_context(
    request: Request,
    *,
    items: Sequence[Mapping[str, Any]],
    limit: int,
    offset: int,
    total_count: int,
    type_filter: str | None,
    status_filter: str | None,
) -> Mapping[str, Any]:
    rows = _build_activity_rows(items)
    table = TableDefinition(
        identifier="activity-table",
        column_keys=(
            "activity.timestamp",
            "activity.type",
            "activity.status",
            "activity.details",
        ),
        rows=rows,
        caption_key="activity.table.caption",
    )

    data_attributes: dict[str, str] = {
        "total": str(total_count),
        "limit": str(limit),
        "offset": str(offset),
    }
    if type_filter:
        data_attributes["type"] = type_filter
    if status_filter:
        data_attributes["status"] = status_filter

    try:
        base_url = request.url_for("activity_table")
    except Exception:
        base_url = "/ui/activity/table"
    filters: list[tuple[str, str]] = []
    if type_filter:
        filters.append(("type", type_filter))
    if status_filter:
        filters.append(("status", status_filter))

    def _page_url(new_offset: int | None) -> str | None:
        if new_offset is None:
            return None
        query = [("limit", str(limit)), ("offset", str(max(new_offset, 0)))]
        query.extend(filters)
        return f"{base_url}?{urlencode(query)}"

    previous_offset = offset - limit if offset > 0 else None
    next_offset = offset + limit if offset + limit < total_count else None

    pagination = PaginationContext(
        label_key="activity",
        target="#hx-activity-table",
        previous_url=_page_url(previous_offset),
        next_url=_page_url(next_offset),
    )

    fragment = TableFragment(
        identifier="hx-activity-table",
        table=table,
        empty_state_key="activity",
        data_attributes=data_attributes,
        pagination=pagination,
    )

    return {"request": request, "fragment": fragment}


def build_spotify_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
) -> Mapping[str, Any]:
    layout = LayoutContext(
        page_id="spotify",
        role=session.role,
        navigation=_build_primary_navigation(session, active="spotify"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
    )

    try:
        status_url = request.url_for("spotify_status_fragment")
    except Exception:
        status_url = "/ui/spotify/status"
    status_fragment = AsyncFragment(
        identifier="hx-spotify-status",
        url=status_url,
        target="#hx-spotify-status",
        poll_interval_seconds=60,
        swap="innerHTML",
        loading_key="spotify.status",
    )

    try:
        account_url = request.url_for("spotify_account_fragment")
    except Exception:
        account_url = "/ui/spotify/account"
    account_fragment = AsyncFragment(
        identifier="hx-spotify-account",
        url=account_url,
        target="#hx-spotify-account",
        swap="innerHTML",
        loading_key="spotify.account",
    )

    try:
        top_tracks_url = request.url_for("spotify_top_tracks_fragment")
    except Exception:
        top_tracks_url = "/ui/spotify/top/tracks"
    top_tracks_fragment = AsyncFragment(
        identifier="hx-spotify-top-tracks",
        url=top_tracks_url,
        target="#hx-spotify-top-tracks",
        swap="innerHTML",
        loading_key="spotify.top_tracks",
    )

    try:
        top_artists_url = request.url_for("spotify_top_artists_fragment")
    except Exception:
        top_artists_url = "/ui/spotify/top/artists"
    top_artists_fragment = AsyncFragment(
        identifier="hx-spotify-top-artists",
        url=top_artists_url,
        target="#hx-spotify-top-artists",
        swap="innerHTML",
        loading_key="spotify.top_artists",
    )

    try:
        recommendations_url = request.url_for("spotify_recommendations_fragment")
    except Exception:
        recommendations_url = "/ui/spotify/recommendations"
    recommendations_fragment = AsyncFragment(
        identifier="hx-spotify-recommendations",
        url=recommendations_url,
        target="#hx-spotify-recommendations",
        swap="innerHTML",
        loading_key="spotify.recommendations",
    )

    try:
        saved_url = request.url_for("spotify_saved_tracks_fragment")
    except Exception:
        saved_url = "/ui/spotify/saved"
    saved_fragment = AsyncFragment(
        identifier="hx-spotify-saved",
        url=saved_url,
        target="#hx-spotify-saved",
        swap="innerHTML",
        loading_key="spotify.saved_tracks",
    )

    try:
        playlists_url = request.url_for("spotify_playlists_fragment")
    except Exception:
        playlists_url = "/ui/spotify/playlists"
    playlists_fragment = AsyncFragment(
        identifier="hx-spotify-playlists",
        url=playlists_url,
        target="#hx-spotify-playlists",
        swap="innerHTML",
        loading_key="spotify.playlists",
    )

    try:
        artists_url = request.url_for("spotify_artists_fragment")
    except Exception:
        artists_url = "/ui/spotify/artists"
    artists_fragment = AsyncFragment(
        identifier="hx-spotify-artists",
        url=artists_url,
        target="#hx-spotify-artists",
        swap="innerHTML",
        loading_key="spotify.artists",
    )

    free_ingest_fragment: AsyncFragment | None = None
    if session.features.imports:
        try:
            free_ingest_url = request.url_for("spotify_free_ingest_fragment")
        except Exception:
            free_ingest_url = "/ui/spotify/free"
        free_ingest_fragment = AsyncFragment(
            identifier="hx-spotify-free-ingest",
            url=free_ingest_url,
            target="#hx-spotify-free-ingest",
            swap="innerHTML",
            loading_key="spotify.free_ingest",
        )

    try:
        backfill_url = request.url_for("spotify_backfill_fragment")
    except Exception:
        backfill_url = "/ui/spotify/backfill"
    backfill_fragment = AsyncFragment(
        identifier="hx-spotify-backfill",
        url=backfill_url,
        target="#hx-spotify-backfill",
        poll_interval_seconds=30,
        swap="innerHTML",
        loading_key="spotify.backfill",
    )

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "csrf_token": csrf_token,
        "status_fragment": status_fragment,
        "account_fragment": account_fragment,
        "top_tracks_fragment": top_tracks_fragment,
        "top_artists_fragment": top_artists_fragment,
        "recommendations_fragment": recommendations_fragment,
        "saved_fragment": saved_fragment,
        "playlists_fragment": playlists_fragment,
        "artists_fragment": artists_fragment,
        "free_ingest_fragment": free_ingest_fragment,
        "backfill_fragment": backfill_fragment,
    }


def build_search_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
) -> Mapping[str, Any]:
    layout = LayoutContext(
        page_id="search",
        role=session.role,
        navigation=_build_primary_navigation(session, active="soulseek"),
        head_meta=(MetaTag(name="csrf-token", content=csrf_token),),
    )

    search_form = _build_search_form(DEFAULT_SOURCES)

    results_url = _safe_url_for(request, "search_results", "/ui/search/results")
    results_fragment = AsyncFragment(
        identifier="hx-search-results",
        url=results_url,
        target="#hx-search-results",
        swap="innerHTML",
        loading_key="search.results",
    )

    queue_fragment: AsyncFragment | None = None
    if session.features.dlq:
        queue_url = _safe_url_for(request, "downloads_table", "/ui/downloads/table")
        queue_fragment = AsyncFragment(
            identifier="hx-search-queue",
            url=f"{queue_url}?limit=20",
            target="#hx-search-queue",
            poll_interval_seconds=30,
            swap="innerHTML",
            loading_key="search.queue",
        )

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "csrf_token": csrf_token,
        "search_form": search_form,
        "results_fragment": results_fragment,
        "queue_fragment": queue_fragment,
    }


def build_soulseek_page_context(
    request: Request,
    *,
    session: UiSession,
    csrf_token: str,
    soulseek_badge: StatusBadge | None = None,
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
        request, "soulseek_configuration_fragment", "/ui/soulseek/configuration"
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

    return {
        "request": request,
        "layout": layout,
        "session": session,
        "csrf_token": csrf_token,
        "status_fragment": status_fragment,
        "configuration_fragment": configuration_fragment,
        "uploads_fragment": uploads_fragment,
        "downloads_fragment": downloads_fragment,
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
) -> Mapping[str, Any]:
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
    }


def build_soulseek_downloads_context(
    request: Request,
    *,
    page: DownloadPage,
    csrf_token: str,
    include_all: bool,
) -> Mapping[str, Any]:
    scope_value = "all" if include_all else "active"
    retryable_states = set(SOULSEEK_RETRYABLE_STATES)
    target = "#hx-soulseek-downloads"

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

        hidden_fields = {
            "csrftoken": csrf_token,
            "scope": scope_value,
            "limit": str(page.limit),
            "offset": str(page.offset),
        }
        can_requeue = (entry.status or "").lower() in retryable_states
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
                        form=TableCellForm(
                            action=requeue_url,
                            method="post",
                            submit_label_key="soulseek.downloads.requeue",
                            hidden_fields=hidden_fields,
                            hx_target=target,
                            hx_swap="outerHTML",
                            disabled=not can_requeue,
                        )
                    ),
                    TableCell(
                        form=TableCellForm(
                            action=cancel_url,
                            method="post",
                            submit_label_key="soulseek.downloads.cancel",
                            hidden_fields=hidden_fields,
                            hx_target=target,
                            hx_swap="outerHTML",
                            hx_method="delete",
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
    }


def build_spotify_status_context(
    request: Request,
    *,
    status: SpotifyStatus,
    oauth: SpotifyOAuthHealth,
    manual_form: FormDefinition,
    csrf_token: str,
    manual_result: SpotifyManualResult | None = None,
    manual_redirect_url: str | None = None,
) -> Mapping[str, Any]:
    alerts: list[AlertMessage] = []
    if manual_result is not None:
        message = (manual_result.message or "").strip()
        if manual_result.ok:
            if not message:
                message = "Spotify authorization completed successfully."
            alerts.append(AlertMessage(level="success", text=message))
        else:
            if not message:
                message = "Manual completion failed. Check the redirect URL and try again."
            alerts.append(AlertMessage(level="error", text=message))

    badges: list[StatusBadge] = []
    badges.append(
        StatusBadge(
            label_key="status.enabled" if status.free_available else "status.disabled",
            variant="success" if status.free_available else "muted",
            test_id="spotify-status-free",
        )
    )
    badges.append(
        StatusBadge(
            label_key="status.enabled" if status.pro_available else "status.disabled",
            variant="success" if status.pro_available else "muted",
            test_id="spotify-status-pro",
        )
    )
    badges.append(
        StatusBadge(
            label_key="status.enabled" if status.authenticated else "status.disabled",
            variant="success" if status.authenticated else "danger",
            test_id="spotify-status-auth",
        )
    )

    status_label_key = (
        f"spotify.status.{status.status}" if status.status else "spotify.status.unconfigured"
    )

    return {
        "request": request,
        "status": status,
        "oauth": oauth,
        "badges": tuple(badges),
        "alert_messages": tuple(alerts),
        "manual_form": manual_form,
        "csrf_token": csrf_token,
        "status_label_key": status_label_key,
        "manual_redirect_url": manual_redirect_url,
    }


def build_spotify_account_context(
    request: Request,
    *,
    account: SpotifyAccountSummary | None,
) -> Mapping[str, Any]:
    alerts: tuple[AlertMessage, ...] = ()
    if account is None:
        return {
            "request": request,
            "alert_messages": alerts,
            "has_account": False,
            "summary": None,
            "fields": (),
        }

    product_text = account.product or "—"
    followers_text = f"{account.followers:,}" if account.followers else "0"
    country_text = account.country or "—"

    fields: tuple[DefinitionItem, ...] = (
        DefinitionItem(
            label_key="spotify.account.display_name",
            value=account.display_name,
            test_id="spotify-account-display-name",
        ),
        DefinitionItem(
            label_key="spotify.account.product",
            value=product_text,
            test_id="spotify-account-product",
        ),
        DefinitionItem(
            label_key="spotify.account.followers",
            value=followers_text,
            test_id="spotify-account-followers",
        ),
        DefinitionItem(
            label_key="spotify.account.country",
            value=country_text,
            test_id="spotify-account-country",
        ),
    )

    return {
        "request": request,
        "alert_messages": alerts,
        "has_account": True,
        "summary": account,
        "fields": fields,
    }


def _build_spotify_top_context(
    request: Request,
    *,
    fragment_id: str,
    table_identifier: str,
    column_keys: Sequence[str],
    rows: Sequence[TableRow],
    caption_key: str,
    empty_state_key: str,
    time_range: str | None = None,
    time_range_options: Sequence[SpotifyTimeRangeOption] | None = None,
) -> Mapping[str, Any]:
    table = TableDefinition(
        identifier=table_identifier,
        column_keys=tuple(column_keys),
        rows=tuple(rows),
        caption_key=caption_key,
    )

    fragment = TableFragment(
        identifier=fragment_id,
        table=table,
        empty_state_key=empty_state_key,
        data_attributes={"count": str(len(rows))},
    )
    context: dict[str, Any] = {"request": request, "fragment": fragment}
    if time_range_options is not None:
        context["time_range"] = time_range
        context["time_range_options"] = tuple(time_range_options)
    return context


def build_spotify_top_tracks_context(
    request: Request,
    *,
    tracks: Sequence[SpotifyTopTrackRow],
    csrf_token: str,
    limit: int,
    offset: int,
    time_range: str,
) -> Mapping[str, Any]:
    def _format_duration(duration_ms: int | None) -> str:
        if duration_ms is None or duration_ms < 0:
            return ""
        total_seconds = duration_ms // 1000
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}:{seconds:02d}"

    try:
        save_url = request.url_for("spotify_saved_tracks_action", action="save")
    except Exception:  # pragma: no cover - fallback for tests
        save_url = "/ui/spotify/saved/save"

    rows: list[TableRow] = []
    for track in tracks:
        artists_text = ", ".join(track.artists)
        duration_text = _format_duration(track.duration_ms)
        try:
            detail_url = request.url_for("spotify_track_detail", track_id=track.identifier)
        except Exception:  # pragma: no cover - fallback for tests
            detail_url = (
                f"/ui/spotify/tracks/{track.identifier}"
                if track.identifier
                else "/ui/spotify/tracks"
            )
        detail_form = TableCellForm(
            action=detail_url,
            method="get",
            submit_label_key="spotify.track.view",
            hx_target="#modal-root",
            hx_swap="innerHTML",
            hx_method="get",
        )
        save_form = TableCellForm(
            action=save_url,
            method="post",
            submit_label_key="spotify.saved.save",
            hidden_fields={
                "csrftoken": csrf_token,
                "track_id": track.identifier,
                "limit": str(limit),
                "offset": str(offset),
            },
            hx_target="#hx-spotify-saved",
            hx_swap="outerHTML",
            disabled=not bool(track.identifier),
            test_id=(
                f"spotify-top-track-save-{track.identifier}"
                if track.identifier
                else "spotify-top-track-save"
            ),
        )
        rows.append(
            TableRow(
                cells=(
                    TableCell(text=str(track.rank)),
                    TableCell(text=track.name),
                    TableCell(text=artists_text),
                    TableCell(text=track.album or ""),
                    TableCell(text=str(track.popularity)),
                    TableCell(text=duration_text),
                    _build_external_link_cell(
                        track.external_url,
                        cell_test_id=(
                            f"spotify-top-track-link-cell-{track.identifier}"
                            if track.identifier
                            else "spotify-top-track-link-cell"
                        ),
                        anchor_test_id=(
                            f"spotify-top-track-link-{track.identifier}"
                            if track.identifier
                            else "spotify-top-track-link"
                        ),
                        label="Spotify",
                        aria_label=(
                            f"Open {track.name} on Spotify" if track.name else "Open in Spotify"
                        ),
                    ),
                    TableCell(
                        forms=(detail_form, save_form),
                        test_id=(
                            f"spotify-top-track-actions-{track.identifier}"
                            if track.identifier
                            else "spotify-top-track-actions"
                        ),
                    ),
                ),
                test_id=f"spotify-top-track-{track.identifier}",
            )
        )

    return _build_spotify_top_context(
        request,
        fragment_id="hx-spotify-top-tracks",
        table_identifier="spotify-top-tracks-table",
        column_keys=(
            "spotify.top_tracks.rank",
            "spotify.top_tracks.name",
            "spotify.top_tracks.artists",
            "spotify.top_tracks.album",
            "spotify.top_tracks.popularity",
            "spotify.top_tracks.duration",
            "spotify.top_tracks.link",
            "spotify.top_tracks.actions",
        ),
        rows=rows,
        caption_key="spotify.top_tracks.caption",
        empty_state_key="spotify.top_tracks",
        time_range=time_range,
        time_range_options=_build_time_range_options(
            request,
            endpoint_name="spotify_top_tracks_fragment",
            fragment_id="hx-spotify-top-tracks",
            selected=time_range,
            fallback_path="/ui/spotify/top/tracks",
        ),
    )


def build_spotify_top_artists_context(
    request: Request,
    *,
    artists: Sequence[SpotifyTopArtistRow],
    time_range: str,
) -> Mapping[str, Any]:
    rows: list[TableRow] = []
    for artist in artists:
        genres_text = ", ".join(artist.genres)
        rows.append(
            TableRow(
                cells=(
                    TableCell(text=str(artist.rank)),
                    TableCell(text=artist.name),
                    TableCell(text=f"{artist.followers:,}" if artist.followers else "0"),
                    TableCell(text=str(artist.popularity)),
                    TableCell(text=genres_text),
                ),
                test_id=f"spotify-top-artist-{artist.identifier}",
            )
        )

    return _build_spotify_top_context(
        request,
        fragment_id="hx-spotify-top-artists",
        table_identifier="spotify-top-artists-table",
        column_keys=(
            "spotify.top_artists.rank",
            "spotify.top_artists.name",
            "spotify.top_artists.followers",
            "spotify.top_artists.popularity",
            "spotify.top_artists.genres",
        ),
        rows=rows,
        caption_key="spotify.top_artists.caption",
        empty_state_key="spotify.top_artists",
        time_range=time_range,
        time_range_options=_build_time_range_options(
            request,
            endpoint_name="spotify_top_artists_fragment",
            fragment_id="hx-spotify-top-artists",
            selected=time_range,
            fallback_path="/ui/spotify/top/artists",
        ),
    )


def build_spotify_playlists_context(
    request: Request,
    *,
    playlists: Sequence[SpotifyPlaylistRow],
) -> Mapping[str, Any]:
    default_limit = 25
    rows: list[TableRow] = []
    for playlist in playlists:
        try:
            items_url = request.url_for(
                "spotify_playlist_items_fragment", playlist_id=playlist.identifier
            )
        except Exception:  # pragma: no cover - fallback for tests
            items_url = f"/ui/spotify/playlists/{playlist.identifier}/tracks"

        hidden_fields: dict[str, str] = {
            "limit": str(default_limit),
            "offset": "0",
        }
        if playlist.name:
            hidden_fields["name"] = playlist.name

        action_form = TableCellForm(
            action=items_url,
            method="get",
            submit_label_key="spotify.playlists.view_tracks",
            hidden_fields=hidden_fields,
            hx_target="#spotify-playlist-items",
            hx_swap="innerHTML",
            hx_method="get",
        )
        rows.append(
            TableRow(
                cells=(
                    TableCell(text=playlist.name),
                    TableCell(text=str(playlist.track_count)),
                    TableCell(text=playlist.updated_at.isoformat()),
                    TableCell(
                        form=action_form,
                        test_id=f"spotify-playlist-view-{playlist.identifier}",
                    ),
                ),
                test_id=f"spotify-playlist-{playlist.identifier}",
            )
        )

    table = TableDefinition(
        identifier="spotify-playlists-table",
        column_keys=(
            "spotify.playlists.name",
            "spotify.playlists.tracks",
            "spotify.playlists.updated",
            "spotify.playlists.actions",
        ),
        rows=tuple(rows),
        caption_key="spotify.playlists.caption",
    )

    fragment = TableFragment(
        identifier="hx-spotify-playlists",
        table=table,
        empty_state_key="spotify.playlists",
        data_attributes={"count": str(len(rows))},
    )

    return {
        "request": request,
        "fragment": fragment,
        "playlist_items_target": "#spotify-playlist-items",
    }


def build_spotify_playlist_items_context(
    request: Request,
    *,
    playlist_id: str,
    playlist_name: str | None,
    rows: Sequence[SpotifyPlaylistItemRow],
    total_count: int,
    limit: int,
    offset: int,
) -> Mapping[str, Any]:
    table_rows: list[TableRow] = []
    for row in rows:
        artists_text = ", ".join(row.artists)
        added_text = row.added_at.isoformat() if row.added_at else ""
        track_text = row.name if not row.is_local else f"{row.name} (local)"
        try:
            detail_url = request.url_for("spotify_track_detail", track_id=row.identifier)
        except Exception:  # pragma: no cover - fallback for tests
            detail_url = (
                f"/ui/spotify/tracks/{row.identifier}" if row.identifier else "/ui/spotify/tracks"
            )
        detail_form = TableCellForm(
            action=detail_url,
            method="get",
            submit_label_key="spotify.track.view",
            hx_target="#modal-root",
            hx_swap="innerHTML",
            hx_method="get",
        )
        table_rows.append(
            TableRow(
                cells=(
                    TableCell(text=track_text),
                    TableCell(text=artists_text),
                    TableCell(text=row.album or ""),
                    TableCell(text=added_text),
                    TableCell(text=row.added_by or ""),
                    TableCell(
                        forms=(detail_form,),
                        test_id=f"spotify-playlist-item-detail-{row.identifier}",
                    ),
                ),
                test_id=f"spotify-playlist-item-{row.identifier}",
            )
        )

    row_count = len(table_rows)

    table = TableDefinition(
        identifier="spotify-playlist-items-table",
        column_keys=(
            "spotify.playlist_items.track",
            "spotify.playlist_items.artists",
            "spotify.playlist_items.album",
            "spotify.playlist_items.added",
            "spotify.playlist_items.added_by",
            "spotify.playlist_items.actions",
        ),
        rows=tuple(table_rows),
        caption_key="spotify.playlist_items.caption",
    )

    try:
        base_url = request.url_for("spotify_playlist_items_fragment", playlist_id=playlist_id)
    except Exception:  # pragma: no cover - fallback for tests
        base_url = f"/ui/spotify/playlists/{playlist_id}/tracks"

    pagination: PaginationContext | None = None
    previous_url: str | None = None
    next_url: str | None = None

    params: dict[str, Any] = {"limit": limit}
    if playlist_name:
        params["name"] = playlist_name

    if offset > 0:
        prev_params = dict(params)
        prev_params["offset"] = max(0, offset - limit)
        previous_url = f"{base_url}?{urlencode(prev_params)}"

    if offset + limit < total_count:
        next_params = dict(params)
        next_params["offset"] = offset + limit
        next_url = f"{base_url}?{urlencode(next_params)}"

    if previous_url or next_url:
        pagination = PaginationContext(
            label_key="spotify.playlist_items",
            target="#spotify-playlist-items",
            swap="innerHTML",
            previous_url=previous_url,
            next_url=next_url,
        )

    fragment = TableFragment(
        identifier="hx-spotify-playlist-items",
        table=table,
        empty_state_key="spotify.playlist_items",
        data_attributes={
            "playlist-id": playlist_id,
            "count": str(row_count),
        },
        pagination=pagination,
    )

    return {
        "request": request,
        "fragment": fragment,
        "playlist_id": playlist_id,
        "playlist_name": playlist_name,
        "page_limit": limit,
        "page_offset": offset,
        "total_count": total_count,
        "row_count": row_count,
    }


def build_spotify_saved_tracks_context(
    request: Request,
    *,
    rows: Sequence[SpotifySavedTrackRow],
    total_count: int,
    limit: int,
    offset: int,
    csrf_token: str,
) -> Mapping[str, Any]:
    artists_label = "spotify.saved_tracks.artists"
    try:
        remove_url = request.url_for("spotify_saved_tracks_action", action="remove")
    except Exception:  # pragma: no cover - fallback for tests
        remove_url = "/ui/spotify/saved/remove"

    try:
        save_url = request.url_for("spotify_saved_tracks_action", action="save")
    except Exception:  # pragma: no cover - fallback for tests
        save_url = "/ui/spotify/saved/save"

    table_rows: list[TableRow] = []
    for row in rows:
        artist_text = ", ".join(row.artists)
        added_text = row.added_at.isoformat() if row.added_at else ""
        try:
            detail_url = request.url_for("spotify_track_detail", track_id=row.identifier)
        except Exception:  # pragma: no cover - fallback for tests
            detail_url = (
                f"/ui/spotify/tracks/{row.identifier}" if row.identifier else "/ui/spotify/tracks"
            )
        view_form = TableCellForm(
            action=detail_url,
            method="get",
            submit_label_key="spotify.track.view",
            hx_target="#modal-root",
            hx_swap="innerHTML",
            hx_method="get",
        )
        remove_form = TableCellForm(
            action=remove_url,
            method="post",
            submit_label_key="spotify.saved.remove",
            hidden_fields={
                "csrftoken": csrf_token,
                "track_id": row.identifier,
                "limit": str(limit),
                "offset": str(offset),
            },
            hx_target="#hx-spotify-saved",
            hx_swap="outerHTML",
            hx_method="delete",
        )
        table_rows.append(
            TableRow(
                cells=(
                    TableCell(text=row.name),
                    TableCell(text=artist_text),
                    TableCell(text=row.album or ""),
                    TableCell(text=added_text),
                    TableCell(
                        forms=(view_form, remove_form),
                        test_id=f"spotify-saved-track-actions-{row.identifier}",
                    ),
                ),
                test_id=f"spotify-saved-track-{row.identifier}",
            )
        )

    table = TableDefinition(
        identifier="spotify-saved-tracks-table",
        column_keys=(
            "spotify.saved_tracks.name",
            artists_label,
            "spotify.saved_tracks.album",
            "spotify.saved_tracks.added",
            "spotify.saved_tracks.actions",
        ),
        rows=tuple(table_rows),
        caption_key="spotify.saved_tracks.caption",
    )

    data_attributes = {
        "count": str(len(table_rows)),
        "total": str(total_count),
        "limit": str(limit),
        "offset": str(offset),
    }

    try:
        base_url = request.url_for("spotify_saved_tracks_fragment")
    except Exception:  # pragma: no cover - fallback for tests
        base_url = "/ui/spotify/saved"

    def _page_url(new_offset: int | None) -> str | None:
        if new_offset is None:
            return None
        return f"{base_url}?{urlencode({'limit': limit, 'offset': max(new_offset, 0)})}"

    previous_offset = offset - limit if offset > 0 else None
    next_offset = offset + limit if offset + limit < total_count else None

    pagination = PaginationContext(
        label_key="spotify.saved_tracks",
        target="#hx-spotify-saved",
        previous_url=_page_url(previous_offset),
        next_url=_page_url(next_offset),
    )

    fragment = TableFragment(
        identifier="hx-spotify-saved",
        table=table,
        empty_state_key="spotify.saved_tracks",
        data_attributes=data_attributes,
        pagination=pagination,
    )

    return {
        "request": request,
        "fragment": fragment,
        "save_action_url": save_url,
        "csrf_token": csrf_token,
        "page_limit": limit,
        "page_offset": offset,
    }


def build_spotify_track_detail_context(
    request: Request,
    *,
    track: SpotifyTrackDetail,
) -> Mapping[str, Any]:
    def _format_duration(duration_ms: int | None) -> str | None:
        if duration_ms is None or duration_ms < 0:
            return None
        total_seconds = duration_ms // 1000
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}:{seconds:02d}"

    def _format_popularity(value: int | None) -> str | None:
        if value is None or value < 0:
            return None
        return f"{value:,}"

    def _format_percentage(value: object) -> str | None:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if numeric < 0:
            return None
        return f"{numeric * 100:.0f}%"

    def _format_tempo(value: object) -> str | None:
        try:
            tempo = float(value)
        except (TypeError, ValueError):
            return None
        if tempo <= 0:
            return None
        return f"{tempo:.1f} BPM"

    def _format_loudness(value: object) -> str | None:
        try:
            loudness = float(value)
        except (TypeError, ValueError):
            return None
        return f"{loudness:.1f} dB"

    def _format_time_signature(value: object) -> str | None:
        try:
            signature = int(value)
        except (TypeError, ValueError):
            return None
        if signature <= 0:
            return None
        return f"{signature}/4"

    key_lookup = {
        0: "C",
        1: "C♯ / D♭",
        2: "D",
        3: "D♯ / E♭",
        4: "E",
        5: "F",
        6: "F♯ / G♭",
        7: "G",
        8: "G♯ / A♭",
        9: "A",
        10: "A♯ / B♭",
        11: "B",
    }

    metadata_entries: list[dict[str, Any]] = []

    def _append_metadata(
        key: str,
        value: Any,
        *,
        test_suffix: str,
        url: str | None = None,
    ) -> None:
        is_missing = False
        if value is None or (isinstance(value, str) and not value.strip()):
            is_missing = True
        metadata_entries.append(
            {
                "key": key,
                "value": value,
                "is_missing": is_missing,
                "test_id": f"spotify-track-detail-{test_suffix}",
                "url": url,
            }
        )

    artist_summary = ", ".join(track.artists)

    _append_metadata("name", track.name, test_suffix="name")
    _append_metadata("artists", artist_summary, test_suffix="artists")
    _append_metadata("album", track.album, test_suffix="album")
    _append_metadata("release_date", track.release_date, test_suffix="release-date")
    _append_metadata(
        "duration",
        _format_duration(track.duration_ms),
        test_suffix="duration",
    )
    _append_metadata(
        "popularity",
        _format_popularity(track.popularity),
        test_suffix="popularity",
    )
    metadata_entries.append(
        {
            "key": "explicit",
            "value": bool(track.explicit),
            "is_missing": False,
            "test_id": "spotify-track-detail-explicit",
            "url": None,
        }
    )
    _append_metadata(
        "preview_url",
        track.preview_url,
        test_suffix="preview",
        url=track.preview_url,
    )
    _append_metadata(
        "external_url",
        track.external_url,
        test_suffix="external",
        url=track.external_url,
    )

    feature_entries: list[dict[str, Any]] = []
    features_source = track.features if isinstance(track.features, Mapping) else {}

    def _format_key(value: object) -> str | None:
        try:
            key_index = int(value)
        except (TypeError, ValueError):
            return None
        return key_lookup.get(key_index)

    def _format_mode(value: object) -> str | None:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return None
        if numeric == 1:
            return "major"
        if numeric == 0:
            return "minor"
        return None

    feature_specs = (
        ("danceability", _format_percentage),
        ("energy", _format_percentage),
        ("acousticness", _format_percentage),
        ("instrumentalness", _format_percentage),
        ("liveness", _format_percentage),
        ("speechiness", _format_percentage),
        ("valence", _format_percentage),
        ("tempo", _format_tempo),
        ("loudness", _format_loudness),
        ("key", _format_key),
        ("mode", _format_mode),
        ("time_signature", _format_time_signature),
    )

    for key, formatter in feature_specs:
        raw_value = features_source.get(key) if isinstance(features_source, Mapping) else None
        formatted = formatter(raw_value) if formatter else raw_value
        is_missing = formatted is None
        feature_entries.append(
            {
                "key": key,
                "value": formatted,
                "is_missing": is_missing,
                "test_id": f"spotify-track-feature-{key}",
            }
        )

    modal_title = track.name or track.track_id

    return {
        "request": request,
        "modal_id": "spotify-track-detail-modal",
        "track_identifier": track.track_id,
        "track_title": modal_title,
        "artist_summary": artist_summary,
        "metadata_entries": tuple(metadata_entries),
        "has_metadata": any(not entry["is_missing"] for entry in metadata_entries),
        "feature_entries": tuple(feature_entries),
        "features_available": track.features is not None,
        "has_features": any(not entry["is_missing"] for entry in feature_entries),
    }


def build_spotify_recommendations_context(
    request: Request,
    *,
    csrf_token: str,
    rows: Sequence[SpotifyRecommendationRow] = (),
    seeds: Sequence[SpotifyRecommendationSeed] = (),
    limit: int = 25,
    offset: int = 0,
    form_values: Mapping[str, str] | None = None,
    form_errors: Mapping[str, str] | None = None,
    alerts: Sequence[AlertMessage] | None = None,
) -> Mapping[str, Any]:
    values = dict(form_values or {})
    defaults = {
        "seed_artists": values.get("seed_artists", ""),
        "seed_tracks": values.get("seed_tracks", ""),
        "seed_genres": values.get("seed_genres", ""),
        "limit": values.get("limit", "20"),
    }
    errors = {key: value for key, value in (form_errors or {}).items() if value}

    table_rows: list[TableRow] = []
    try:
        save_url = request.url_for("spotify_saved_tracks_action", action="save")
    except Exception:  # pragma: no cover - fallback for tests
        save_url = "/ui/spotify/saved/save"
    for row in rows:
        try:
            detail_url = request.url_for("spotify_track_detail", track_id=row.identifier)
        except Exception:  # pragma: no cover - fallback for tests
            detail_url = (
                f"/ui/spotify/tracks/{row.identifier}" if row.identifier else "/ui/spotify/tracks"
            )
        if row.preview_url:
            preview_html = (
                '<audio controls preload="none" '
                f'data-test="spotify-recommendation-preview-{row.identifier}">'
                f'<source src="{row.preview_url}" type="audio/mpeg" />'
                "Your browser does not support audio playback."
                f' <a href="{row.preview_url}" target="_blank" rel="noopener">'
                "Open preview"
                "</a>."
                "</audio>"
            )
            preview_cell = TableCell(
                html=preview_html,
                test_id=f"spotify-recommendation-preview-cell-{row.identifier}",
            )
        else:
            preview_cell = TableCell(
                text="—",
                test_id=f"spotify-recommendation-preview-cell-{row.identifier}",
            )
        view_form = TableCellForm(
            action=detail_url,
            method="get",
            submit_label_key="spotify.track.view",
            hx_target="#modal-root",
            hx_swap="innerHTML",
            hx_method="get",
        )
        save_form = TableCellForm(
            action=save_url,
            method="post",
            submit_label_key="spotify.saved.save",
            hidden_fields={
                "csrftoken": csrf_token,
                "track_id": row.identifier,
                "limit": str(limit),
                "offset": str(offset),
            },
            hx_target="#hx-spotify-saved",
            hx_swap="outerHTML",
            disabled=not bool(row.identifier),
            test_id=(
                f"spotify-recommendation-save-{row.identifier}"
                if row.identifier
                else "spotify-recommendation-save"
            ),
        )
        table_rows.append(
            TableRow(
                cells=(
                    TableCell(text=row.name, test_id=f"spotify-reco-track-{row.identifier}"),
                    TableCell(text=", ".join(row.artists)),
                    TableCell(text=row.album or "—"),
                    _build_external_link_cell(
                        row.external_url,
                        cell_test_id=(
                            f"spotify-recommendation-link-cell-{row.identifier}"
                            if row.identifier
                            else "spotify-recommendation-link-cell"
                        ),
                        anchor_test_id=(
                            f"spotify-recommendation-link-{row.identifier}"
                            if row.identifier
                            else "spotify-recommendation-link"
                        ),
                        label="Spotify",
                        aria_label=(
                            f"Open {row.name} on Spotify" if row.name else "Open in Spotify"
                        ),
                    ),
                    preview_cell,
                    TableCell(
                        forms=(view_form, save_form),
                        test_id=f"spotify-recommendation-actions-{row.identifier}",
                    ),
                ),
                test_id=f"spotify-recommendation-{row.identifier}",
            )
        )

    table = TableDefinition(
        identifier="spotify-recommendations-table",
        column_keys=(
            "spotify.recommendations.track",
            "spotify.recommendations.artists",
            "spotify.recommendations.album",
            "spotify.recommendations.link",
            "spotify.recommendations.preview",
            "spotify.recommendations.actions",
        ),
        rows=tuple(table_rows),
        caption_key="spotify.recommendations.caption",
    )

    data_attributes = {
        "count": str(len(table_rows)),
    }

    fragment = TableFragment(
        identifier="hx-spotify-recommendations",
        table=table,
        empty_state_key="spotify.recommendations",
        data_attributes=data_attributes,
    )

    return {
        "request": request,
        "csrf_token": csrf_token,
        "form_defaults": defaults,
        "form_errors": errors,
        "alerts": tuple(alerts or ()),
        "fragment": fragment,
        "seeds": tuple(seeds),
    }


def build_spotify_artists_context(
    request: Request,
    *,
    artists: Sequence[SpotifyArtistRow],
) -> Mapping[str, Any]:
    rows: list[TableRow] = []
    for artist in artists:
        genres_text = ", ".join(artist.genres)
        rows.append(
            TableRow(
                cells=(
                    TableCell(text=artist.name),
                    _build_external_link_cell(
                        artist.external_url,
                        cell_test_id=(
                            f"spotify-artist-link-cell-{artist.identifier}"
                            if artist.identifier
                            else "spotify-artist-link-cell"
                        ),
                        anchor_test_id=(
                            f"spotify-artist-link-{artist.identifier}"
                            if artist.identifier
                            else "spotify-artist-link"
                        ),
                        label="Spotify",
                        aria_label=(
                            f"Open {artist.name} on Spotify" if artist.name else "Open in Spotify"
                        ),
                    ),
                    TableCell(text=f"{artist.followers:,}" if artist.followers else "0"),
                    TableCell(text=str(artist.popularity)),
                    TableCell(text=genres_text),
                ),
                test_id=f"spotify-artist-{artist.identifier}",
            )
        )

    table = TableDefinition(
        identifier="spotify-artists-table",
        column_keys=(
            "spotify.artists.name",
            "spotify.artists.link",
            "spotify.artists.followers",
            "spotify.artists.popularity",
            "spotify.artists.genres",
        ),
        rows=tuple(rows),
        caption_key="spotify.artists.caption",
    )

    fragment = TableFragment(
        identifier="hx-spotify-artists",
        table=table,
        empty_state_key="spotify.artists",
        data_attributes={"count": str(len(rows))},
    )

    return {"request": request, "fragment": fragment}


def build_spotify_backfill_context(
    request: Request,
    *,
    snapshot: SpotifyBackfillSnapshot,
    alert: AlertMessage | None = None,
) -> Mapping[str, Any]:
    alert_messages: tuple[AlertMessage, ...]
    if alert is None:
        alert_messages = tuple()
    else:
        alert_messages = (alert,)
    return {
        "request": request,
        "snapshot": snapshot,
        "alert_messages": alert_messages,
    }


def build_spotify_free_ingest_form_context(
    *,
    csrf_token: str,
    form_values: Mapping[str, str] | None = None,
    form_errors: Mapping[str, str] | None = None,
    result: SpotifyFreeIngestResult | None = None,
) -> SpotifyFreeIngestFormContext:
    values = {key: value for key, value in (form_values or {}).items()}
    playlist_value = values.get("playlist_links", "")
    tracks_value = values.get("tracks", "")
    errors = {key: value for key, value in (form_errors or {}).items() if value}

    accepted_items: list[DefinitionItem] = []
    skipped_items: list[DefinitionItem] = []
    if result is not None:
        accepted_items = [
            DefinitionItem(
                label_key="spotify.free_ingest.summary.accepted_playlists",
                value=f"{result.accepted.playlists:,}",
            ),
            DefinitionItem(
                label_key="spotify.free_ingest.summary.accepted_tracks",
                value=f"{result.accepted.tracks:,}",
            ),
            DefinitionItem(
                label_key="spotify.free_ingest.summary.accepted_batches",
                value=f"{result.accepted.batches:,}",
            ),
        ]
        skipped_items = [
            DefinitionItem(
                label_key="spotify.free_ingest.summary.skipped_playlists",
                value=f"{result.skipped.playlists:,}",
            ),
            DefinitionItem(
                label_key="spotify.free_ingest.summary.skipped_tracks",
                value=f"{result.skipped.tracks:,}",
            ),
        ]

    return SpotifyFreeIngestFormContext(
        csrf_token=csrf_token,
        playlist_value=playlist_value,
        tracks_value=tracks_value,
        accepted_items=tuple(accepted_items),
        skipped_items=tuple(skipped_items),
        result=result,
        form_errors=errors,
        upload_error=errors.get("upload"),
    )


def build_spotify_free_ingest_status_context(
    *, status: SpotifyFreeIngestJobSnapshot | None
) -> SpotifyFreeIngestJobContext | None:
    if status is None:
        return None

    counts = (
        DefinitionItem(
            label_key="spotify.free_ingest.status.registered",
            value=f"{status.counts.registered:,}",
        ),
        DefinitionItem(
            label_key="spotify.free_ingest.status.normalized",
            value=f"{status.counts.normalized:,}",
        ),
        DefinitionItem(
            label_key="spotify.free_ingest.status.queued",
            value=f"{status.counts.queued:,}",
        ),
        DefinitionItem(
            label_key="spotify.free_ingest.status.completed",
            value=f"{status.counts.completed:,}",
        ),
        DefinitionItem(
            label_key="spotify.free_ingest.status.failed",
            value=f"{status.counts.failed:,}",
        ),
    )

    accepted_items = (
        DefinitionItem(
            label_key="spotify.free_ingest.summary.accepted_playlists",
            value=f"{status.accepted.playlists:,}",
        ),
        DefinitionItem(
            label_key="spotify.free_ingest.summary.accepted_tracks",
            value=f"{status.accepted.tracks:,}",
        ),
        DefinitionItem(
            label_key="spotify.free_ingest.summary.accepted_batches",
            value=f"{status.accepted.batches:,}",
        ),
    )

    skipped_items = (
        DefinitionItem(
            label_key="spotify.free_ingest.summary.skipped_playlists",
            value=f"{status.skipped.playlists:,}",
        ),
        DefinitionItem(
            label_key="spotify.free_ingest.summary.skipped_tracks",
            value=f"{status.skipped.tracks:,}",
        ),
    )

    return SpotifyFreeIngestJobContext(
        job_id=status.job_id,
        state=status.state,
        counts=counts,
        accepted_items=accepted_items,
        skipped_items=skipped_items,
        queued_tracks=status.queued_tracks,
        failed_tracks=status.failed_tracks,
        skipped_tracks=status.skipped_tracks,
        error=status.error,
        skip_reason=status.skip_reason,
    )


def build_spotify_free_ingest_context(
    request: Request,
    *,
    csrf_token: str,
    form_values: Mapping[str, str] | None = None,
    form_errors: Mapping[str, str] | None = None,
    result: SpotifyFreeIngestResult | None = None,
    job_status: SpotifyFreeIngestJobSnapshot | None = None,
    alerts: Sequence[AlertMessage] | None = None,
) -> Mapping[str, Any]:
    form = build_spotify_free_ingest_form_context(
        csrf_token=csrf_token,
        form_values=form_values,
        form_errors=form_errors,
        result=result,
    )
    status_context = build_spotify_free_ingest_status_context(status=job_status)
    return {
        "request": request,
        "alert_messages": tuple(alerts or ()),
        "form": form,
        "job_status": status_context,
    }


def build_watchlist_fragment_context(
    request: Request,
    *,
    entries: Sequence[WatchlistRow],
) -> Mapping[str, Any]:
    rows: list[TableRow] = []
    for entry in entries:
        rows.append(
            TableRow(
                cells=(
                    TableCell(text=entry.artist_key),
                    TableCell(text=str(entry.priority)),
                    TableCell(text_key=entry.state_key),
                )
            )
        )

    table = TableDefinition(
        identifier="watchlist-table",
        column_keys=(
            "watchlist.artist",
            "watchlist.priority",
            "watchlist.state",
        ),
        rows=tuple(rows),
        caption_key="watchlist.table.caption",
    )

    fragment = TableFragment(
        identifier="hx-watchlist-table",
        table=table,
        empty_state_key="watchlist",
        data_attributes={"count": str(len(rows))},
    )

    return {"request": request, "fragment": fragment}


def build_downloads_fragment_context(
    request: Request,
    *,
    page: DownloadPage,
    status_filter: str | None = None,
    include_all: bool = False,
) -> Mapping[str, Any]:
    rows: list[TableRow] = []
    for entry in page.items:
        progress = ""
        if entry.progress is not None:
            progress = f"{entry.progress * 100:.0f}%"
        updated_at = entry.updated_at.isoformat() if entry.updated_at else ""
        rows.append(
            TableRow(
                cells=(
                    TableCell(text=str(entry.identifier)),
                    TableCell(text=entry.filename),
                    TableCell(text=entry.status),
                    TableCell(text=progress),
                    TableCell(text=str(entry.priority)),
                    TableCell(text=entry.username or ""),
                    TableCell(text=updated_at),
                )
            )
        )

    table = TableDefinition(
        identifier="downloads-table",
        column_keys=(
            "downloads.id",
            "downloads.filename",
            "downloads.status",
            "downloads.progress",
            "downloads.priority",
            "downloads.user",
            "downloads.updated",
        ),
        rows=tuple(rows),
        caption_key="downloads.table.caption",
    )

    try:
        base_url = request.url_for("downloads_table")
    except Exception:  # pragma: no cover - fallback for tests without routing context
        base_url = "/ui/downloads/table"

    def _build_url(offset: int | None) -> str | None:
        if offset is None or offset < 0:
            return None
        query: list[tuple[str, str]] = [("limit", str(page.limit)), ("offset", str(offset))]
        if include_all:
            query.append(("all", "1"))
        if status_filter:
            query.append(("status", status_filter))
        return f"{base_url}?{urlencode(query)}"

    previous_url = _build_url(page.offset - page.limit) if page.has_previous else None
    next_offset = page.offset + page.limit if page.has_next else None
    next_url = _build_url(next_offset) if next_offset is not None else None

    data_attributes = {
        "count": str(len(rows)),
        "limit": str(page.limit),
        "offset": str(page.offset),
    }
    if include_all:
        data_attributes["scope"] = "all"
    if status_filter:
        data_attributes["status"] = status_filter

    pagination = PaginationContext(
        label_key="downloads",
        target="#hx-downloads-table",
        previous_url=previous_url,
        next_url=next_url,
    )

    fragment = TableFragment(
        identifier="hx-downloads-table",
        table=table,
        empty_state_key="downloads",
        data_attributes=data_attributes,
        pagination=pagination if previous_url or next_url else None,
    )

    return {
        "request": request,
        "fragment": fragment,
        "include_all": include_all,
        "active_url": None,
        "all_url": None,
        "refresh_url": None,
    }


def build_jobs_fragment_context(
    request: Request,
    *,
    jobs: Sequence[OrchestratorJob],
) -> Mapping[str, Any]:
    rows: list[TableRow] = []
    for job in jobs:
        badge = StatusBadge(
            label_key="status.enabled" if job.enabled else "status.disabled",
            variant="success" if job.enabled else "muted",
        )
        rows.append(
            TableRow(
                cells=(
                    TableCell(text=job.name),
                    TableCell(text=job.status),
                    TableCell(badge=badge),
                )
            )
        )

    table = TableDefinition(
        identifier="jobs-table",
        column_keys=("jobs.name", "jobs.status", "jobs.enabled"),
        rows=tuple(rows),
        caption_key="jobs.table.caption",
    )

    fragment = TableFragment(
        identifier="hx-jobs-table",
        table=table,
        empty_state_key="jobs",
        data_attributes={"count": str(len(rows))},
    )

    return {"request": request, "fragment": fragment}


def build_search_results_context(
    request: Request,
    *,
    page: SearchResultsPage,
    query: str,
    sources: Sequence[str],
    csrf_token: str,
) -> Mapping[str, Any]:
    rows: list[TableRow] = []
    try:
        action_url = request.url_for("search_download_action")
    except Exception:  # pragma: no cover - fallback for tests
        action_url = "/ui/search/download"
    feedback_target = "#hx-search-feedback"
    for item in page.items:
        score = f"{item.score * 100:.0f}%"
        bitrate = f"{item.bitrate} kbps" if item.bitrate else ""
        if item.download:
            serialised_files = json.dumps(
                [dict(file) for file in item.download.files],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            hidden_fields = {
                "csrftoken": csrf_token,
                "identifier": item.identifier,
                "username": item.download.username,
                "files": serialised_files,
            }
            form = TableCellForm(
                action=action_url,
                method="post",
                submit_label_key="search.action.queue",
                hidden_fields=hidden_fields,
                hx_target=feedback_target,
            )
            action_cell = TableCell(form=form, test_id=f"queue-{item.identifier}")
        else:
            action_cell = TableCell(text_key="search.action.unavailable")
        rows.append(
            TableRow(
                cells=(
                    TableCell(text=item.title),
                    TableCell(text=item.artist or ""),
                    TableCell(text=item.source),
                    TableCell(text=score),
                    TableCell(text=bitrate),
                    action_cell,
                )
            )
        )

    table = TableDefinition(
        identifier="search-results-table",
        column_keys=(
            "search.title",
            "search.artist",
            "search.source",
            "search.score",
            "search.bitrate",
            "search.actions",
        ),
        rows=tuple(rows),
        caption_key="search.results.caption",
    )

    try:
        base_url = request.url_for("search_results")
    except Exception:  # pragma: no cover - fallback for tests
        base_url = "/ui/search/results"

    resolved_sources: tuple[str, ...]
    if sources:
        resolved_sources = tuple(dict.fromkeys(sources))
    else:
        resolved_sources = DEFAULT_SOURCES

    def _make_query(offset: int | None) -> str | None:
        if offset is None or offset < 0:
            return None
        query_params: list[tuple[str, str]] = [
            ("query", query),
            ("limit", str(page.limit)),
            ("offset", str(offset)),
        ]
        for source in resolved_sources:
            query_params.append(("sources", source))
        return f"{base_url}?{urlencode(query_params)}"

    has_previous = page.offset > 0
    previous_offset = page.offset - page.limit if has_previous else None
    next_offset = page.offset + page.limit
    has_next = next_offset < page.total

    pagination = PaginationContext(
        label_key="search",
        target="#hx-search-results",
        previous_url=_make_query(previous_offset) if has_previous else None,
        next_url=_make_query(next_offset) if has_next else None,
    )

    fragment = TableFragment(
        identifier="hx-search-results",
        table=table,
        empty_state_key="search",
        data_attributes={
            "total": str(page.total),
            "limit": str(page.limit),
            "offset": str(page.offset),
            "query": query,
            "sources": ",".join(resolved_sources),
        },
        pagination=pagination if pagination.previous_url or pagination.next_url else None,
    )

    return {"request": request, "fragment": fragment}


def _build_features_table(features: UiFeatures) -> TableDefinition:
    feature_rows = [
        ("feature.spotify", features.spotify, "spotify"),
        ("feature.soulseek", features.soulseek, "soulseek"),
        ("feature.dlq", features.dlq, "dlq"),
        ("feature.imports", features.imports, "imports"),
    ]

    rows = [
        TableRow(
            cells=(
                TableCell(text_key=label_key, test_id=f"feature-{slug}"),
                TableCell(
                    badge=StatusBadge(
                        label_key="status.enabled" if enabled else "status.disabled",
                        variant="success" if enabled else "muted",
                        test_id=f"feature-{slug}-status",
                    )
                ),
            ),
        )
        for label_key, enabled, slug in feature_rows
    ]

    return TableDefinition(
        identifier="features-table",
        column_keys=("dashboard.features.name", "dashboard.features.status"),
        rows=tuple(rows),
        caption_key="dashboard.features.caption",
    )


__all__ = [
    "ActionButton",
    "AsyncFragment",
    "AlertMessage",
    "CheckboxGroup",
    "CheckboxOption",
    "DefinitionItem",
    "PaginationContext",
    "FormDefinition",
    "FormField",
    "LayoutContext",
    "NavigationContext",
    "NavItem",
    "TableFragment",
    "StatusBadge",
    "TableCell",
    "TableCellForm",
    "TableDefinition",
    "TableRow",
    "SpotifyFreeIngestFormContext",
    "SpotifyFreeIngestJobContext",
    "build_spotify_backfill_context",
    "build_spotify_artists_context",
    "build_spotify_page_context",
    "build_spotify_playlists_context",
    "build_spotify_playlist_items_context",
    "build_spotify_track_detail_context",
    "build_spotify_recommendations_context",
    "build_spotify_saved_tracks_context",
    "build_spotify_top_artists_context",
    "build_spotify_top_tracks_context",
    "build_spotify_account_context",
    "build_spotify_status_context",
    "build_spotify_free_ingest_context",
    "build_spotify_free_ingest_form_context",
    "build_spotify_free_ingest_status_context",
    "build_activity_fragment_context",
    "build_dashboard_page_context",
    "build_login_page_context",
    "build_primary_navigation",
    "build_soulseek_page_context",
    "build_soulseek_status_context",
    "build_soulseek_config_context",
    "build_soulseek_uploads_context",
    "build_soulseek_downloads_context",
    "build_soulseek_navigation_badge",
    "build_search_page_context",
    "build_downloads_fragment_context",
    "build_jobs_fragment_context",
    "build_search_results_context",
    "build_watchlist_fragment_context",
]
