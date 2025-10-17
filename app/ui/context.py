from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import Request

from app.api.search import DEFAULT_SOURCES
from app.ui.services import (
    DownloadPage,
    OrchestratorJob,
    SearchResultsPage,
    SpotifyArtistRow,
    SpotifyBackfillSnapshot,
    SpotifyManualResult,
    SpotifyOAuthHealth,
    SpotifyPlaylistRow,
    SpotifyStatus,
    WatchlistRow,
)
from app.ui.session import UiFeatures, UiSession

AlertLevel = Literal["info", "success", "warning", "error"]
ButtonMethod = Literal["get", "post"]
StatusVariant = Literal["success", "danger", "muted"]


@dataclass(slots=True)
class NavItem:
    label_key: str
    href: str
    active: bool = False
    test_id: str | None = None


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
    badge: StatusBadge | None = None
    test_id: str | None = None
    form: "TableCellForm" | None = None


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


_SEARCH_SOURCE_LABELS: dict[str, str] = {
    "spotify": "search.sources.spotify",
    "soulseek": "search.sources.soulseek",
}


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


def _build_primary_navigation(session: UiSession, *, active: str) -> NavigationContext:
    items: list[NavItem] = [
        NavItem(
            label_key="nav.home",
            href="/ui",
            active=active == "home",
            test_id="nav-home",
        )
    ]

    if session.features.spotify:
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
        "playlists_fragment": playlists_fragment,
        "artists_fragment": artists_fragment,
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
) -> Mapping[str, Any]:
    layout = LayoutContext(
        page_id="soulseek",
        role=session.role,
        navigation=_build_primary_navigation(session, active="soulseek"),
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


def build_spotify_playlists_context(
    request: Request,
    *,
    playlists: Sequence[SpotifyPlaylistRow],
) -> Mapping[str, Any]:
    rows: list[TableRow] = []
    for playlist in playlists:
        rows.append(
            TableRow(
                cells=(
                    TableCell(text=playlist.name),
                    TableCell(text=str(playlist.track_count)),
                    TableCell(text=playlist.updated_at.isoformat()),
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

    return {"request": request, "fragment": fragment}


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

    return {"request": request, "fragment": fragment}


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
    "build_spotify_backfill_context",
    "build_spotify_artists_context",
    "build_spotify_page_context",
    "build_spotify_playlists_context",
    "build_spotify_status_context",
    "build_activity_fragment_context",
    "build_dashboard_page_context",
    "build_login_page_context",
    "build_soulseek_page_context",
    "build_search_page_context",
    "build_downloads_fragment_context",
    "build_jobs_fragment_context",
    "build_search_results_context",
    "build_watchlist_fragment_context",
]
