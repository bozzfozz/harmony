from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from jinja2 import Template
from starlette.requests import Request

from app.ui.context import (
    AlertMessage,
    AsyncFragment,
    FormDefinition,
    LayoutContext,
    MetaTag,
    NavigationContext,
    NavItem,
    PaginationContext,
    StatusBadge,
    TableCell,
    TableDefinition,
    TableFragment,
    TableRow,
    build_activity_fragment_context,
    build_dashboard_page_context,
    build_login_page_context,
    build_soulseek_page_context,
    build_search_page_context,
    build_spotify_artists_context,
    build_spotify_account_context,
    build_spotify_backfill_context,
    build_spotify_page_context,
    build_spotify_playlists_context,
    build_spotify_status_context,
    build_watchlist_fragment_context,
)
from app.ui.router import templates
from app.ui.services import (
    SpotifyArtistRow,
    SpotifyAccountSummary,
    SpotifyBackfillSnapshot,
    SpotifyManualResult,
    SpotifyOAuthHealth,
    SpotifyPlaylistRow,
    SpotifyStatus,
    WatchlistRow,
)
from app.ui.session import UiFeatures, UiSession


def _make_request(path: str) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
    }
    return Request(scope)


def _render_inline(source: str, **context: Any) -> str:
    template = Template(templates.env, "<inline>", source)
    return template.render(**context)


def test_async_fragment_trigger_without_polling() -> None:
    fragment = AsyncFragment(
        identifier="hx-test",
        url="/test",
        target="#hx-test",
    )

    assert fragment.trigger == "load"


def test_async_fragment_trigger_with_polling() -> None:
    fragment = AsyncFragment(
        identifier="hx-test",
        url="/test",
        target="#hx-test",
        poll_interval_seconds=45,
    )

    assert fragment.trigger == "load, every 45s"


def test_login_template_renders_error_and_form() -> None:
    request = _make_request("/ui/login")
    context = build_login_page_context(request, error="Invalid key")
    template = templates.get_template("pages/login.j2")
    html = template.render(**context)

    assert "Harmony Operator Console" in html
    assert "<!DOCTYPE html>" in html
    assert "Invalid key" in html
    assert 'id="login-form"' in html
    assert 'data-role="anonymous"' in html
    assert "nav-home" not in html


def test_dashboard_template_renders_navigation_and_features() -> None:
    request = _make_request("/ui")
    features = UiFeatures(spotify=True, soulseek=False, dlq=True, imports=False)
    now = datetime.now(tz=UTC)
    session = UiSession(
        identifier="session-1",
        role="admin",
        features=features,
        fingerprint="fp",
        issued_at=now,
        last_seen_at=now,
    )
    context = build_dashboard_page_context(
        request,
        session=session,
        csrf_token="csrf-token-value",
    )
    template = templates.get_template("pages/dashboard.j2")
    html = template.render(**context)

    assert 'meta name="csrf-token" content="csrf-token-value"' in html
    assert "nav-home" in html
    assert "nav-operator" in html
    assert "nav-admin" in html
    assert 'id="features-table"' in html
    assert "status-badge--success" in html
    assert "status-badge--muted" in html
    assert "operator-action" in html
    assert "admin-action" in html
    assert "Welcome" in html
    assert "Current role: Admin" in html
    assert 'hx-get="/ui/activity/table"' in html
    assert 'hx-trigger="load, every 60s"' in html
    assert 'hx-target="#hx-activity-table"' in html


def test_spotify_page_template_renders_sections() -> None:
    request = _make_request("/ui/spotify")
    features = UiFeatures(spotify=True, soulseek=True, dlq=True, imports=True)
    now = datetime.now(tz=UTC)
    session = UiSession(
        identifier="session-spotify",
        role="operator",
        features=features,
        fingerprint="fp",
        issued_at=now,
        last_seen_at=now,
    )
    context = build_spotify_page_context(
        request,
        session=session,
        csrf_token="csrf-token",
    )
    template = templates.get_template("pages/spotify.j2")
    html = template.render(**context)

    assert "nav-spotify" in html
    assert 'hx-get="/ui/spotify/status"' in html
    assert 'hx-get="/ui/spotify/account"' in html
    assert 'hx-get="/ui/spotify/playlists"' in html
    assert 'hx-get="/ui/spotify/artists"' in html
    assert 'hx-get="/ui/spotify/backfill"' in html
    assert 'hx-target="#hx-spotify-status"' in html
    assert 'hx-target="#hx-spotify-account"' in html
    assert 'hx-target="#hx-spotify-playlists"' in html
    assert 'hx-target="#hx-spotify-artists"' in html
    assert 'hx-target="#hx-spotify-backfill"' in html
    assert 'hx-trigger="load, every 60s"' in html
    assert 'hx-trigger="load, every 30s"' in html
    assert html.count('hx-trigger="load"') >= 2
    assert 'hx-swap="innerHTML"' in html
    assert 'role="status"' in html
    assert html.count('role="region"') >= 4
    assert 'data-fragment="spotify-status"' in html
    assert 'data-fragment="spotify-account"' in html
    assert 'data-fragment="spotify-playlists"' in html
    assert 'data-fragment="spotify-artists"' in html
    assert 'data-fragment="spotify-backfill"' in html
    assert 'class="async-fragment"' in html
    assert 'aria-live="polite"' in html
    assert "Checking Spotify connection…" in html
    assert "Loading Spotify account details…" in html
    assert "Loading cached Spotify playlists…" in html
    assert "Loading followed Spotify artists…" in html
    assert "Fetching Spotify backfill status…" in html


def test_spotify_account_fragment_template_renders_summary() -> None:
    request = _make_request("/ui/spotify")
    summary = SpotifyAccountSummary(
        display_name="Example User",
        product="Premium",
        followers=2500,
        country="GB",
    )
    context = build_spotify_account_context(request, account=summary)
    template = templates.get_template("partials/spotify_account.j2")
    html = template.render(**context)

    assert "Example User" in html
    assert "Premium" in html
    assert "2,500" in html
    assert "GB" in html
    assert 'data-test="spotify-account-product"' in html


def test_spotify_account_fragment_template_handles_missing_profile() -> None:
    request = _make_request("/ui/spotify")
    context = build_spotify_account_context(request, account=None)
    template = templates.get_template("partials/spotify_account.j2")
    html = template.render(**context)

    assert "No Spotify profile information is available." in html
    assert 'data-has-account="0"' in html


def test_soulseek_page_template_renders_fragments() -> None:
    request = _make_request("/ui/soulseek")
    features = UiFeatures(spotify=False, soulseek=True, dlq=True, imports=False)
    now = datetime.now(tz=UTC)
    session = UiSession(
        identifier="session-soulseek",
        role="operator",
        features=features,
        fingerprint="fp",
        issued_at=now,
        last_seen_at=now,
    )
    context = build_soulseek_page_context(
        request,
        session=session,
        csrf_token="csrf-soulseek",
    )
    template = templates.get_template("pages/soulseek.j2")
    html = template.render(**context)

    assert 'meta name="csrf-token" content="csrf-soulseek"' in html
    assert 'href="/ui/soulseek"' in html
    assert 'data-test="nav-soulseek"' in html
    assert 'hx-get="/ui/soulseek/status"' in html
    assert 'hx-get="/ui/soulseek/configuration"' in html
    assert 'hx-get="/ui/soulseek/uploads"' in html
    assert 'hx-get="/ui/soulseek/downloads"' in html
    assert 'hx-trigger="load, every 60s"' in html
    assert html.count('hx-trigger="load, every 30s"') == 2
    assert html.count('hx-trigger="load"') >= 1
    assert 'data-fragment="soulseek-status"' in html
    assert 'data-fragment="soulseek-configuration"' in html
    assert 'data-fragment="soulseek-uploads"' in html
    assert 'data-fragment="soulseek-downloads"' in html
    assert "Checking Soulseek connection…" in html
    assert "Loading Soulseek configuration…" in html
    assert "Loading active Soulseek uploads…" in html
    assert "Loading active Soulseek downloads…" in html


def test_search_page_template_renders_form_and_queue() -> None:
    request = _make_request("/ui/search")
    features = UiFeatures(spotify=False, soulseek=True, dlq=True, imports=False)
    now = datetime.now(tz=UTC)
    session = UiSession(
        identifier="session-search",
        role="operator",
        features=features,
        fingerprint="fp",
        issued_at=now,
        last_seen_at=now,
    )
    context = build_search_page_context(
        request,
        session=session,
        csrf_token="csrf-search",
    )
    template = templates.get_template("pages/search.j2")
    html = template.render(**context)

    assert 'meta name="csrf-token" content="csrf-search"' in html
    assert 'href="/ui/soulseek"' in html
    assert 'data-test="nav-soulseek"' in html
    assert 'hx-post="/ui/search/results"' in html
    assert 'hx-push-url="/ui/search/results"' in html
    assert 'hx-target="#hx-search-results"' in html
    assert 'id="hx-search-results"' in html
    assert "<legend>Sources</legend>" in html
    assert 'id="sources-spotify"' in html
    assert 'data-test="search-source-spotify"' in html
    assert 'id="sources-soulseek"' in html
    assert 'data-test="search-source-soulseek"' in html
    assert 'type="checkbox"' in html
    assert "Select the providers to include in your search." in html
    assert 'hx-get="/ui/downloads/table?limit=20"' in html
    assert 'hx-trigger="load, every 30s"' in html
    assert 'hx-target="#hx-search-queue"' in html


def test_search_page_template_hides_queue_when_dlq_disabled() -> None:
    request = _make_request("/ui/search")
    features = UiFeatures(spotify=False, soulseek=True, dlq=False, imports=False)
    now = datetime.now(tz=UTC)
    session = UiSession(
        identifier="session-search",
        role="operator",
        features=features,
        fingerprint="fp",
        issued_at=now,
        last_seen_at=now,
    )
    context = build_search_page_context(
        request,
        session=session,
        csrf_token="csrf-search",
    )
    template = templates.get_template("pages/search.j2")
    html = template.render(**context)

    assert 'hx-get="/ui/downloads/table"' not in html
    assert 'data-fragment="search-queue"' not in html


def test_base_layout_renders_navigation_and_alerts() -> None:
    request = _make_request("/ui")
    layout = LayoutContext(
        page_id="dashboard",
        role="operator",
        navigation=NavigationContext(
            primary=(
                NavItem(
                    label_key="nav.home",
                    href="/ui",
                    active=True,
                    test_id="nav-home",
                ),
            )
        ),
        alerts=(AlertMessage(level="warning", text="Check status"),),
        head_meta=(MetaTag(name="csrf-token", content="token"),),
    )
    template = templates.get_template("layouts/base.j2")
    html = template.render(request=request, layout=layout)

    assert '<nav aria-label="Primary">' in html
    assert 'data-test="nav-home"' in html
    assert "alert alert--warning" in html
    assert "Check status" in html
    assert '<meta name="csrf-token" content="token" />' in html


def test_activity_fragment_template_uses_table_macro() -> None:
    request = _make_request("/ui/activity/table")
    items = [
        {
            "timestamp": "2024-01-01T00:00:00Z",
            "type": "test",
            "status": "ok",
            "details": {"foo": "bar"},
        }
    ]
    context = build_activity_fragment_context(
        request,
        items=items,
        limit=25,
        offset=0,
        total_count=1,
        type_filter=None,
        status_filter=None,
    )
    template = templates.get_template("partials/activity_table.j2")
    html = template.render(**context)

    assert 'id="hx-activity-table"' in html
    assert 'data-total="1"' in html
    assert '<table id="activity-table"' in html
    assert 'class="table"' in html
    assert "foo" in html
    assert 'class="pagination"' not in html


def test_watchlist_fragment_template_renders_rows() -> None:
    request = _make_request("/ui/watchlist/table")
    entries = [
        WatchlistRow(
            artist_key="spotify:artist:1",
            priority=1,
            state_key="watchlist.state.active",
        ),
        WatchlistRow(
            artist_key="spotify:artist:2",
            priority=2,
            state_key="watchlist.state.paused",
        ),
    ]
    context = build_watchlist_fragment_context(request, entries=entries)
    template = templates.get_template("partials/watchlist_table.j2")
    html = template.render(**context)

    assert 'id="hx-watchlist-table"' in html
    assert 'data-count="2"' in html
    assert "spotify:artist:1" in html
    assert "Paused" in html


def test_spotify_status_partial_renders_forms_and_badges() -> None:
    request = _make_request("/ui/spotify/status")
    status = SpotifyStatus(
        status="unauthenticated",
        free_available=True,
        pro_available=True,
        authenticated=False,
    )
    oauth = SpotifyOAuthHealth(
        manual_enabled=True,
        redirect_uri="http://localhost/callback",
        public_host_hint=None,
        active_transactions=0,
        ttl_seconds=300,
    )
    manual_form = FormDefinition(
        identifier="spotify-manual-form",
        method="post",
        action="/ui/spotify/oauth/manual",
        submit_label_key="spotify.manual.submit",
    )
    context = build_spotify_status_context(
        request,
        status=status,
        oauth=oauth,
        manual_form=manual_form,
        csrf_token="csrf-token",
    )
    template = templates.get_template("partials/spotify_status.j2")
    html = template.render(**context)

    assert "spotify-oauth-start" in html
    assert "spotify-manual-form" in html
    assert 'hx-post="/ui/spotify/oauth/manual"' in html
    assert 'hx-target="closest .async-fragment"' in html
    assert 'hx-swap="innerHTML"' in html
    assert "Authentication is required" in html
    assert "Redirect URI" in html
    assert "Manual session timeout" in html
    assert 'name="redirect_url" value=' not in html


def test_spotify_status_partial_hides_manual_form_when_disabled() -> None:
    request = _make_request("/ui/spotify/status")
    status = SpotifyStatus(
        status="unauthenticated",
        free_available=True,
        pro_available=True,
        authenticated=False,
    )
    oauth = SpotifyOAuthHealth(
        manual_enabled=False,
        redirect_uri=None,
        public_host_hint="https://console.example",
        active_transactions=2,
        ttl_seconds=0,
    )
    manual_form = FormDefinition(
        identifier="spotify-manual-form",
        method="post",
        action="/ui/spotify/oauth/manual",
        submit_label_key="spotify.manual.submit",
    )
    context = build_spotify_status_context(
        request,
        status=status,
        oauth=oauth,
        manual_form=manual_form,
        csrf_token="csrf-token",
    )
    template = templates.get_template("partials/spotify_status.j2")
    html = template.render(**context)

    assert "spotify-manual-form" not in html
    assert "Manual completion is disabled" in html
    assert "Ensure the public host is reachable" in html
    assert "No active manual sessions" in html
    assert "Redirect URI" not in html


def test_spotify_status_partial_renders_default_manual_messages() -> None:
    request = _make_request("/ui/spotify/status")
    status = SpotifyStatus(
        status="unauthenticated",
        free_available=True,
        pro_available=True,
        authenticated=False,
    )
    oauth = SpotifyOAuthHealth(
        manual_enabled=True,
        redirect_uri=None,
        public_host_hint=None,
        active_transactions=0,
        ttl_seconds=0,
    )
    manual_form = FormDefinition(
        identifier="spotify-manual-form",
        method="post",
        action="/ui/spotify/oauth/manual",
        submit_label_key="spotify.manual.submit",
    )
    template = templates.get_template("partials/spotify_status.j2")

    success_context = build_spotify_status_context(
        request,
        status=status,
        oauth=oauth,
        manual_form=manual_form,
        csrf_token="csrf-token",
        manual_result=SpotifyManualResult(ok=True, message=""),
    )
    success_html = template.render(**success_context)
    assert "Spotify authorization completed successfully." in success_html

    failure_context = build_spotify_status_context(
        request,
        status=status,
        oauth=oauth,
        manual_form=manual_form,
        csrf_token="csrf-token",
        manual_result=SpotifyManualResult(ok=False, message="   "),
    )
    failure_html = template.render(**failure_context)
    assert "Manual completion failed. Check the redirect URL and try again." in failure_html


def test_spotify_playlists_partial_renders_table() -> None:
    request = _make_request("/ui/spotify/playlists")
    playlists = [
        SpotifyPlaylistRow(
            identifier="playlist-1",
            name="Daily Mix",
            track_count=42,
            updated_at=datetime.now(tz=UTC),
        )
    ]
    context = build_spotify_playlists_context(request, playlists=playlists)
    template = templates.get_template("partials/spotify_playlists.j2")
    html = template.render(**context)

    assert 'id="hx-spotify-playlists"' in html
    assert 'class="table"' in html
    assert "Daily Mix" in html
    assert 'data-count="1"' in html


def test_spotify_artists_partial_renders_table() -> None:
    request = _make_request("/ui/spotify/artists")
    artists = [
        SpotifyArtistRow(
            identifier="artist-1",
            name="Artist One",
            followers=123456,
            popularity=87,
            genres=("rock", "indie"),
        )
    ]
    context = build_spotify_artists_context(request, artists=artists)
    template = templates.get_template("partials/spotify_artists.j2")
    html = template.render(**context)

    assert 'id="hx-spotify-artists"' in html
    assert 'class="table"' in html
    assert "Artist One" in html
    assert "123,456" in html
    assert "rock, indie" in html
    assert 'data-count="1"' in html


def test_spotify_backfill_partial_renders_snapshot() -> None:
    request = _make_request("/ui/spotify/backfill")
    snapshot = SpotifyBackfillSnapshot(
        csrf_token="csrf-token",
        can_run=True,
        default_max_items=500,
        expand_playlists=True,
        last_job_id="job-1",
        state="running",
        requested=100,
        processed=50,
        matched=25,
        cache_hits=10,
        cache_misses=5,
        expanded_playlists=2,
        expanded_tracks=10,
        duration_ms=1234,
        error=None,
    )
    context = build_spotify_backfill_context(request, snapshot=snapshot)
    template = templates.get_template("partials/spotify_backfill.j2")
    html = template.render(**context)

    assert "spotify-backfill-form" in html
    assert 'value="500"' in html
    assert "job-1" in html
    assert "Expand playlists" in html
    assert 'hx-target="closest .async-fragment"' in html
    assert 'hx-swap="innerHTML"' in html


def test_table_fragment_renders_badge_and_pagination() -> None:
    table = TableDefinition(
        identifier="test-table",
        column_keys=("dashboard.features.name", "dashboard.features.status"),
        rows=(
            TableRow(
                cells=(
                    TableCell(text_key="feature.spotify"),
                    TableCell(
                        badge=StatusBadge(
                            label_key="status.enabled",
                            variant="success",
                        )
                    ),
                )
            ),
        ),
        caption_key="dashboard.features.caption",
    )
    fragment = TableFragment(
        identifier="hx-test-table",
        table=table,
        empty_state_key="dashboard",
        data_attributes={"count": "1"},
        pagination=PaginationContext(
            label_key="watchlist",
            target="#hx-test-table",
            previous_url="/prev",
            next_url="/next",
        ),
    )
    html = _render_inline(
        "{% import 'partials/tables.j2' as tables %}{{ tables.render_table_fragment(fragment) }}",
        fragment=fragment,
    )

    assert 'id="hx-test-table"' in html
    assert 'data-count="1"' in html
    assert "status-badge--success" in html
    assert 'aria-label="Watchlist pagination"' in html
    assert 'hx-get="/prev"' in html
    assert 'hx-get="/next"' in html
    assert 'hx-push-url="/prev"' in html
    assert 'hx-push-url="/next"' in html


def test_pass_context_globals_receive_runtime_context_mapping() -> None:
    assert "url_for" in templates.env.globals

    class DummyRequest:
        def url_for(self, name: str, **path_params: Any) -> str:
            parts = [name]
            if path_params:
                parts.extend(f"{key}-{value}" for key, value in sorted(path_params.items()))
            return "/".join(parts)

    html = _render_inline(
        "{{ url_for('dashboard', item_id=7) }}",
        request=DummyRequest(),
    )

    assert html == "dashboard/item_id-7"
