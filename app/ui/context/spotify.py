from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import urlencode

from fastapi import Request
from starlette.datastructures import URL

from app.dependencies import get_app_config
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
    TableCell,
    TableCellForm,
    TableDefinition,
    TableFragment,
    TableRow,
    _build_external_link_cell,
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
        SpotifyAccountSummary,
        SpotifyArtistRow,
        SpotifyBackfillSnapshot,
        SpotifyBackfillTimelineEntry,
        SpotifyFreeIngestJobSnapshot,
        SpotifyFreeIngestResult,
        SpotifyManualResult,
        SpotifyOAuthHealth,
        SpotifyPlaylistFilterOption,
        SpotifyPlaylistItemRow,
        SpotifyPlaylistRow,
        SpotifyRecommendationRow,
        SpotifyRecommendationSeed,
        SpotifySavedTrackRow,
        SpotifyStatus,
        SpotifyTopArtistRow,
        SpotifyTopTrackRow,
        SpotifyTrackDetail,
    )


@dataclass(slots=True)
class SpotifyTimeRangeOption:
    value: str
    label_key: str
    url: str
    active: bool
    test_id: str


_SPOTIFY_TIME_RANGE_LABELS: Mapping[str, str] = {
    "short_term": "spotify.time_range.short",
    "medium_term": "spotify.time_range.medium",
    "long_term": "spotify.time_range.long",
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
    for value, label_key in _SPOTIFY_TIME_RANGE_LABELS.items():
        option_url = base_url.include_query_params(time_range=value)
        options.append(
            SpotifyTimeRangeOption(
                value=value,
                label_key=label_key,
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


_SPOTIFY_RUNBOOK_PATH = "/docs/operations/runbooks/hdm.md"


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
        load_event="revealed",
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
        load_event="revealed",
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
        load_event="revealed",
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
        load_event="revealed",
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
        load_event="revealed",
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
        load_event="revealed",
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
            poll_interval_seconds=15,
            swap="innerHTML",
            loading_key="spotify.free_ingest",
            load_event="revealed",
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
        load_event="revealed",
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


def _get_request_state(request: Request) -> Any | None:
    scope_app = request.scope.get("app")
    if scope_app is None:
        return None
    return getattr(scope_app, "state", None)


def _resolve_docs_base_url(request: Request) -> str | None:
    state = _get_request_state(request)
    if state is not None:
        config_snapshot = getattr(state, "config_snapshot", None)
        if config_snapshot is not None:
            ui_config = getattr(config_snapshot, "ui", None)
            docs_base_url = getattr(ui_config, "docs_base_url", None)
            if isinstance(docs_base_url, str) and docs_base_url:
                return docs_base_url
    docs_base_url = get_app_config().ui.docs_base_url
    if isinstance(docs_base_url, str) and docs_base_url:
        return docs_base_url
    return None


def _resolve_api_base_path(request: Request) -> str:
    state = _get_request_state(request)
    if state is not None:
        base_path = getattr(state, "api_base_path", None)
        if isinstance(base_path, str):
            return base_path
    return get_app_config().api_base_path


def _compose_prefixed_path(base_path: str, suffix: str) -> str:
    normalized = (base_path or "").strip()
    if not normalized or normalized == "/":
        return suffix
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    normalized = normalized.rstrip("/")
    return f"{normalized}{suffix}"


def _join_external_url(base_url: str, suffix: str) -> str:
    base = base_url.rstrip("/")
    path = suffix.lstrip("/")
    return f"{base}/{path}"


def _build_spotify_runbook_url(request: Request) -> str:
    docs_base_url = _resolve_docs_base_url(request)
    if docs_base_url:
        return _join_external_url(docs_base_url, _SPOTIFY_RUNBOOK_PATH)
    prefixed_path = _compose_prefixed_path(_resolve_api_base_path(request), _SPOTIFY_RUNBOOK_PATH)
    base_url = request.base_url
    if isinstance(base_url, URL) and base_url.netloc:
        return str(
            base_url.replace(
                path=prefixed_path.lstrip("/"),
                query="",
                fragment="",
            )
        )
    return prefixed_path


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
        "runbook_url": _build_spotify_runbook_url(request),
    }


def build_spotify_account_context(
    request: Request,
    *,
    account: SpotifyAccountSummary | None,
    csrf_token: str,
    refresh_action: str,
    show_refresh: bool,
    show_reset: bool,
    reset_action: str | None,
) -> Mapping[str, Any]:
    alerts: tuple[AlertMessage, ...] = ()
    base_context = {
        "request": request,
        "alert_messages": alerts,
        "csrf_token": csrf_token,
        "refresh_action": refresh_action,
        "show_refresh": show_refresh,
        "show_reset": show_reset,
        "reset_action": reset_action,
    }
    if account is None:
        return {
            **base_context,
            "has_account": False,
            "summary": None,
            "fields": (),
        }

    product_text = account.product or "—"
    followers_text = f"{account.followers:,}" if account.followers else "0"
    country_text = account.country or "—"
    email_text = account.email or "—"

    fields: tuple[DefinitionItem, ...] = (
        DefinitionItem(
            label_key="spotify.account.display_name",
            value=account.display_name,
            test_id="spotify-account-display-name",
        ),
        DefinitionItem(
            label_key="spotify.account.email",
            value=email_text,
            test_id="spotify-account-email",
            is_missing=account.email is None,
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
        **base_context,
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
                    _build_external_link_cell(
                        artist.external_url,
                        cell_test_id=(
                            f"spotify-top-artist-link-cell-{artist.identifier}"
                            if artist.identifier
                            else "spotify-top-artist-link-cell"
                        ),
                        anchor_test_id=(
                            f"spotify-top-artist-link-{artist.identifier}"
                            if artist.identifier
                            else "spotify-top-artist-link"
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
            "spotify.top_artists.link",
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
    csrf_token: str,
    filter_action: str,
    refresh_url: str,
    table_target: str,
    owner_options: Sequence[SpotifyPlaylistFilterOption],
    sync_status_options: Sequence[SpotifyPlaylistFilterOption],
    owner_filter: str | None = None,
    status_filter: str | None = None,
    force_sync_url: str | None = None,
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
                    TableCell(text=playlist.owner or "—"),
                    TableCell(text=str(playlist.track_count)),
                    TableCell(text=str(playlist.follower_count)),
                    TableCell(
                        text=(
                            playlist.sync_status.replace("_", " ").title()
                            if playlist.sync_status
                            else "—"
                        )
                    ),
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
            "spotify.playlists.owner",
            "spotify.playlists.tracks",
            "spotify.playlists.followers",
            "spotify.playlists.sync_status",
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
        "csrf_token": csrf_token,
        "filter_action": filter_action,
        "refresh_url": refresh_url,
        "force_sync_url": force_sync_url,
        "table_target": table_target,
        "owner_options": tuple(owner_options),
        "sync_status_options": tuple(sync_status_options),
        "owner_filter": owner_filter,
        "status_filter": status_filter,
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
        added_text = format_datetime_display(row.added_at)
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
    queue_enabled: bool = True,
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

    queue_url: str | None = None
    if queue_enabled:
        try:
            queue_url = request.url_for("spotify_saved_tracks_action", action="queue")
        except Exception:  # pragma: no cover - fallback for tests
            queue_url = "/ui/spotify/saved/queue"

    table_rows: list[TableRow] = []
    for row in rows:
        artist_text = ", ".join(row.artists)
        added_text = format_datetime_display(row.added_at)
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
        queue_form: TableCellForm | None = None
        if queue_url:
            queue_form = TableCellForm(
                action=queue_url,
                method="post",
                submit_label_key="spotify.saved.queue",
                hidden_fields={
                    "csrftoken": csrf_token,
                    "track_id": row.identifier,
                    "limit": str(limit),
                    "offset": str(offset),
                },
                hx_target="#hx-spotify-saved",
                hx_swap="outerHTML",
                hx_method="post",
            )
        forms: list[TableCellForm] = [view_form]
        if queue_form is not None:
            forms.append(queue_form)
        forms.append(remove_form)

        table_rows.append(
            TableRow(
                cells=(
                    TableCell(text=row.name),
                    TableCell(text=artist_text),
                    TableCell(text=row.album or ""),
                    TableCell(text=added_text),
                    TableCell(
                        forms=tuple(forms),
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
        "queue-enabled": "1" if queue_enabled and queue_url else "0",
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
        "queue_action_url": queue_url,
        "csrf_token": csrf_token,
        "page_limit": limit,
        "page_offset": offset,
        "queue_enabled": queue_enabled and queue_url is not None,
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
    seed_defaults: Mapping[str, str] | None = None,
    show_admin_controls: bool = False,
    queue_enabled: bool = True,
) -> Mapping[str, Any]:
    values = dict(form_values or {})
    defaults_source = dict(seed_defaults or {})

    def _resolve_default(key: str, fallback: str) -> str:
        value = values.get(key)
        if value not in (None, ""):
            return str(value)
        default_value = defaults_source.get(key)
        if default_value not in (None, ""):
            return str(default_value)
        return fallback

    defaults = {
        "seed_artists": _resolve_default("seed_artists", ""),
        "seed_tracks": _resolve_default("seed_tracks", ""),
        "seed_genres": _resolve_default("seed_genres", ""),
        "limit": _resolve_default("limit", str(limit)),
    }
    errors = {key: value for key, value in (form_errors or {}).items() if value}

    table_rows: list[TableRow] = []
    try:
        save_url = request.url_for("spotify_saved_tracks_action", action="save")
    except Exception:  # pragma: no cover - fallback for tests
        save_url = "/ui/spotify/saved/save"
    queue_url: str | None = None
    if queue_enabled:
        try:
            queue_url = request.url_for("spotify_recommendations_submit")
        except Exception:  # pragma: no cover - fallback for tests
            queue_url = "/ui/spotify/recommendations"
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
        queue_form: TableCellForm | None = None
        if queue_enabled and queue_url:
            queue_form = TableCellForm(
                action=queue_url,
                method="post",
                submit_label_key="spotify.saved.queue",
                hidden_fields={
                    "csrftoken": csrf_token,
                    "action": "queue",
                    "track_id": row.identifier,
                    "seed_artists": defaults["seed_artists"],
                    "seed_tracks": defaults["seed_tracks"],
                    "seed_genres": defaults["seed_genres"],
                    "limit": defaults["limit"],
                },
                hx_target="#hx-spotify-recommendations",
                hx_swap="outerHTML",
                disabled=not bool(row.identifier),
                test_id=(
                    f"spotify-recommendation-queue-{row.identifier}"
                    if row.identifier
                    else "spotify-recommendation-queue"
                ),
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
        forms: list[TableCellForm] = [view_form]
        if queue_form is not None:
            forms.append(queue_form)
        forms.append(save_form)

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
                        forms=tuple(forms),
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
        "queue-enabled": "1" if queue_enabled else "0",
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
        "show_admin_controls": show_admin_controls,
        "seed_defaults": defaults_source,
        "queue_enabled": queue_enabled,
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
    timeline: Sequence["SpotifyBackfillTimelineEntry"] | None = None,
    alert: AlertMessage | None = None,
) -> Mapping[str, Any]:
    alert_messages: tuple[AlertMessage, ...]
    if alert is None:
        alert_messages = tuple()
    else:
        alert_messages = (alert,)
    history = tuple(timeline or ())
    return {
        "request": request,
        "snapshot": snapshot,
        "alert_messages": alert_messages,
        "timeline": history,
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


__all__ = [
    "SpotifyTimeRangeOption",
    "SpotifyFreeIngestFormContext",
    "SpotifyFreeIngestJobContext",
    "build_spotify_page_context",
    "build_spotify_status_context",
    "build_spotify_account_context",
    "build_spotify_top_tracks_context",
    "build_spotify_top_artists_context",
    "build_spotify_playlists_context",
    "build_spotify_playlist_items_context",
    "build_spotify_saved_tracks_context",
    "build_spotify_track_detail_context",
    "build_spotify_recommendations_context",
    "build_spotify_artists_context",
    "build_spotify_backfill_context",
    "build_spotify_free_ingest_form_context",
    "build_spotify_free_ingest_status_context",
    "build_spotify_free_ingest_context",
]
