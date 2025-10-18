from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from jinja2 import Template
from starlette.requests import Request

from app.integrations.health import IntegrationHealth
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
    build_soulseek_navigation_badge,
    build_soulseek_page_context,
    build_search_page_context,
    build_spotify_artists_context,
    build_spotify_account_context,
    build_spotify_backfill_context,
    build_spotify_page_context,
    build_spotify_playlist_items_context,
    build_spotify_playlists_context,
    build_spotify_free_ingest_context,
    build_spotify_recommendations_context,
    build_spotify_track_detail_context,
    build_spotify_saved_tracks_context,
    build_spotify_top_artists_context,
    build_spotify_top_tracks_context,
    build_spotify_status_context,
    build_watchlist_fragment_context,
)
from app.ui.router import templates
from app.schemas import StatusResponse
from app.ui.services import (
    SpotifyArtistRow,
    SpotifyAccountSummary,
    SpotifyBackfillSnapshot,
    SpotifyFreeIngestAccepted,
    SpotifyFreeIngestJobCounts,
    SpotifyFreeIngestJobSnapshot,
    SpotifyFreeIngestResult,
    SpotifyFreeIngestSkipped,
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
    assert "nav-spotify" in html
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


def test_dashboard_template_hides_spotify_navigation_for_read_only_sessions() -> None:
    request = _make_request("/ui")
    features = UiFeatures(spotify=True, soulseek=False, dlq=True, imports=False)
    now = datetime.now(tz=UTC)
    session = UiSession(
        identifier="session-read-only",
        role="read_only",
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

    assert 'data-test="nav-home"' in html
    assert 'data-test="nav-spotify"' not in html
    assert 'data-test="nav-operator"' not in html


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
    assert 'hx-get="/ui/spotify/top/tracks"' in html
    assert 'hx-get="/ui/spotify/top/artists"' in html
    assert 'hx-get="/ui/spotify/recommendations"' in html
    assert 'hx-get="/ui/spotify/saved"' in html
    assert 'hx-get="/ui/spotify/playlists"' in html
    assert 'hx-get="/ui/spotify/artists"' in html
    assert 'hx-get="/ui/spotify/free"' in html
    assert 'hx-get="/ui/spotify/backfill"' in html
    assert 'hx-target="#hx-spotify-status"' in html
    assert 'hx-target="#hx-spotify-account"' in html
    assert 'hx-target="#hx-spotify-top-tracks"' in html
    assert 'hx-target="#hx-spotify-top-artists"' in html
    assert 'hx-target="#hx-spotify-recommendations"' in html
    assert 'hx-target="#hx-spotify-saved"' in html
    assert 'hx-target="#hx-spotify-playlists"' in html
    assert 'hx-target="#hx-spotify-artists"' in html
    assert 'hx-target="#hx-spotify-free-ingest"' in html
    assert 'hx-target="#hx-spotify-backfill"' in html
    assert 'hx-trigger="load, every 60s"' in html
    assert 'hx-trigger="load, every 30s"' in html
    assert html.count('hx-trigger="load"') >= 4
    assert 'hx-swap="innerHTML"' in html
    assert 'role="status"' in html
    assert html.count('role="region"') >= 7
    assert 'data-fragment="spotify-status"' in html
    assert 'data-fragment="spotify-account"' in html
    assert 'data-fragment="spotify-top-tracks"' in html
    assert 'data-fragment="spotify-top-artists"' in html
    assert 'data-fragment="spotify-recommendations"' in html
    assert 'data-fragment="spotify-saved-tracks"' in html
    assert 'data-fragment="spotify-playlists"' in html
    assert 'data-fragment="spotify-artists"' in html
    assert 'data-fragment="spotify-free-ingest"' in html
    assert 'data-fragment="spotify-backfill"' in html
    assert 'class="async-fragment"' in html
    assert 'aria-live="polite"' in html
    assert "Checking Spotify connection…" in html
    assert "Loading Spotify account details…" in html
    assert "Loading top Spotify tracks…" in html
    assert "Loading top Spotify artists…" in html
    assert "Preparing Spotify recommendations…" in html
    assert "Loading saved Spotify tracks…" in html
    assert "Loading cached Spotify playlists…" in html
    assert "Loading followed Spotify artists…" in html
    assert "Fetching Spotify backfill status…" in html


def test_spotify_top_tracks_partial_renders_table() -> None:
    request = _make_request("/ui/spotify/top/tracks")
    tracks = [
        SpotifyTopTrackRow(
            identifier="track-1",
            name="Track One",
            artists=("Artist One", "Artist Two"),
            album="Album One",
            popularity=95,
            duration_ms=183000,
            rank=1,
        )
    ]
    context = build_spotify_top_tracks_context(request, tracks=tracks)
    template = templates.get_template("partials/spotify_top_tracks.j2")
    html = template.render(**context)

    assert 'id="hx-spotify-top-tracks"' in html
    assert 'class="table"' in html
    assert "Track One" in html
    assert "Artist One, Artist Two" in html
    assert "3:03" in html
    assert 'data-count="1"' in html


def test_spotify_top_artists_partial_renders_table() -> None:
    request = _make_request("/ui/spotify/top/artists")
    artists = [
        SpotifyTopArtistRow(
            identifier="artist-1",
            name="Artist One",
            followers=543210,
            popularity=99,
            genres=("rock", "indie"),
            rank=1,
        )
    ]
    context = build_spotify_top_artists_context(request, artists=artists)
    template = templates.get_template("partials/spotify_top_artists.j2")
    html = template.render(**context)

    assert 'id="hx-spotify-top-artists"' in html
    assert 'class="table"' in html
    assert "Artist One" in html
    assert "543,210" in html
    assert "rock, indie" in html
    assert 'data-count="1"' in html


def test_spotify_recommendations_partial_renders_form_and_results() -> None:
    request = _make_request("/ui/spotify/recommendations")
    rows = (
        SpotifyRecommendationRow(
            identifier="track-1",
            name="Track One",
            artists=("Artist One", "Artist Two"),
            album="Album Name",
            preview_url=None,
        ),
    )
    seeds = (
        SpotifyRecommendationSeed(
            seed_type="artist",
            identifier="artist-9",
            initial_pool_size=120,
            after_filtering_size=80,
            after_relinking_size=60,
        ),
    )
    context = build_spotify_recommendations_context(
        request,
        csrf_token="csrf-token",
        rows=rows,
        seeds=seeds,
        form_values={
            "seed_tracks": "track-123",
            "seed_artists": "artist-1",
            "seed_genres": "rock, jazz",
            "limit": "150",
        },
        form_errors={"limit": "Enter a number between 1 and 100."},
        alerts=(AlertMessage(level="warning", text="Example warning"),),
    )
    template = templates.get_template("partials/spotify_recommendations.j2")
    html = template.render(**context)

    assert 'id="spotify-recommendations-form"' in html
    assert 'hx-post="/ui/spotify/recommendations"' in html
    assert 'name="csrftoken" value="csrf-token"' in html
    assert 'name="seed_tracks"' in html and 'value="track-123"' in html
    assert 'name="seed_artists"' in html and 'value="artist-1"' in html
    assert 'name="seed_genres"' in html
    assert "rock, jazz" in html
    assert "Enter a number between 1 and 100." in html
    assert "Example warning" in html
    assert "Fetch recommendations" in html
    assert "Seed summary" in html
    assert "spotify-recommendation-seed-artist-artist-9" in html
    assert "<strong>Artist:</strong>" in html
    assert ">\n            artist-9" in html
    assert "pool 120" in html and "filtered 80" in html and "relinked 60" in html
    assert "Track One" in html
    assert "Artist One, Artist Two" in html
    assert "Album Name" in html
    assert 'data-count="1"' in html


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


def test_spotify_saved_tracks_fragment_template_renders_table() -> None:
    request = _make_request("/ui/spotify")
    rows = (
        SpotifySavedTrackRow(
            identifier="track-1",
            name="Track One",
            artists=("Artist One", "Artist Two"),
            album="Album Name",
            added_at=datetime(2023, 9, 1, 10, 0, tzinfo=UTC),
        ),
    )
    context = build_spotify_saved_tracks_context(
        request,
        rows=rows,
        total_count=1,
        limit=25,
        offset=0,
        csrf_token="csrf-token",
    )
    template = templates.get_template("partials/spotify_saved_tracks.j2")
    html = template.render(**context)

    assert 'id="spotify-save-track-form"' in html
    assert 'hx-post="/ui/spotify/saved/save"' in html
    assert 'name="csrftoken" value="csrf-token"' in html
    assert 'data-count="1"' in html
    assert "Track One" in html
    assert "Artist One, Artist Two" in html
    assert "Album Name" in html
    assert "2023-09-01T10:00:00+00:00" in html
    assert 'data-test="spotify-saved-track-actions-track-1"' in html
    assert 'hx-get="/ui/spotify/tracks/track-1"' in html
    assert 'hx-delete="/ui/spotify/saved/remove"' in html


def test_spotify_track_detail_template_renders_modal() -> None:
    request = _make_request("/ui/spotify")
    track = SpotifyTrackDetail(
        track_id="track-1",
        name="Example Track",
        artists=("Artist One", "Artist Two"),
        album="Example Album",
        release_date="2023-09-01",
        duration_ms=185000,
        popularity=1050,
        explicit=True,
        preview_url="https://preview.example/track-1",
        external_url="https://open.spotify.com/track/track-1",
        detail={"id": "track-1"},
        features={
            "danceability": 0.82,
            "tempo": 123.45,
            "mode": 0,
            "time_signature": 4,
        },
    )
    context = build_spotify_track_detail_context(request, track=track)
    template = templates.get_template("partials/spotify_track_detail.j2")
    html = template.render(**context)

    assert 'id="spotify-track-detail-modal"' in html
    assert "Track details · Example Track" in html
    assert "Artist One, Artist Two" in html
    assert "Example Album" in html
    assert "3:05" in html
    assert "1,050" in html
    assert "Yes" in html
    assert 'href="https://preview.example/track-1"' in html
    assert 'href="https://open.spotify.com/track/track-1"' in html
    assert "82%" in html
    assert "123.5 BPM" in html
    assert "Minor" in html
    assert "4/4" in html
    assert 'hx-on="htmx:afterSwap: this.showModal()"' in html


def test_spotify_playlists_template_includes_actions() -> None:
    request = _make_request("/ui/spotify")
    playlists = (
        SpotifyPlaylistRow(
            identifier="playlist-1",
            name="Example Playlist",
            track_count=12,
            updated_at=datetime(2023, 9, 1, 12, 0, tzinfo=UTC),
        ),
    )
    context = build_spotify_playlists_context(request, playlists=playlists)
    template = templates.get_template("partials/spotify_playlists.j2")
    html = template.render(**context)

    assert 'id="spotify-playlists-table"' in html
    assert 'data-test="spotify-playlist-view-playlist-1"' in html
    assert 'hx-get="/ui/spotify/playlists/playlist-1/tracks"' in html
    assert 'name="limit" value="25"' in html
    assert 'id="spotify-playlist-items"' in html
    assert 'aria-label="Playlist tracks list"' in html


def test_spotify_playlist_items_template_renders_table() -> None:
    request = _make_request("/ui/spotify")
    rows = (
        SpotifyPlaylistItemRow(
            identifier="track-1",
            name="Track One",
            artists=("Artist One",),
            album="Album One",
            added_at=datetime(2023, 9, 1, 12, 0, tzinfo=UTC),
            added_by="Curator",
            is_local=False,
            metadata={},
        ),
    )
    context = build_spotify_playlist_items_context(
        request,
        playlist_id="playlist-1",
        playlist_name="Example Playlist",
        rows=rows,
        total_count=5,
        limit=25,
        offset=0,
    )
    template = templates.get_template("partials/spotify_playlist_items.j2")
    html = template.render(**context)

    assert "Tracks in Example Playlist" in html
    assert "Showing 1-1 of 5 tracks." in html
    assert 'id="spotify-playlist-items-table"' in html
    assert "Track One" in html
    assert "Artist One" in html
    assert "Curator" in html
    assert 'data-test="spotify-playlist-item-detail-track-1"' in html
    assert 'hx-get="/ui/spotify/tracks/track-1"' in html


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
    nav_badge = StatusBadge(
        label_key="soulseek.integration.ok",
        variant="success",
        test_id="nav-soulseek-status",
    )
    context = build_soulseek_page_context(
        request,
        session=session,
        csrf_token="csrf-soulseek",
        soulseek_badge=nav_badge,
    )
    template = templates.get_template("pages/soulseek.j2")
    html = template.render(**context)

    assert 'meta name="csrf-token" content="csrf-soulseek"' in html
    assert 'href="/ui/soulseek"' in html
    assert 'data-test="nav-soulseek"' in html
    assert 'data-test="nav-soulseek-status"' in html
    assert "status-badge--success" in html
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


def test_primary_nav_renders_soulseek_success_badge() -> None:
    items = (
        NavItem(
            label_key="nav.soulseek",
            href="/ui/soulseek",
            test_id="nav-soulseek",
            badge=build_soulseek_navigation_badge(
                connection=StatusResponse(status="connected"),
                integration=IntegrationHealth(overall="ok", providers=()),
            ),
        ),
    )
    html = _render_inline(
        "{% import 'partials/nav.j2' as nav %}{{ nav.render_primary_nav(items) }}",
        items=items,
    )

    assert 'data-test="nav-soulseek"' in html
    assert 'data-test="nav-soulseek-status"' in html
    assert "status-badge--success" in html
    assert "Healthy" in html


def test_primary_nav_renders_soulseek_degraded_badge() -> None:
    items = (
        NavItem(
            label_key="nav.soulseek",
            href="/ui/soulseek",
            test_id="nav-soulseek",
            badge=build_soulseek_navigation_badge(
                connection=StatusResponse(status="connected"),
                integration=IntegrationHealth(overall="degraded", providers=()),
            ),
        ),
    )
    html = _render_inline(
        "{% import 'partials/nav.j2' as nav %}{{ nav.render_primary_nav(items) }}",
        items=items,
    )

    assert 'data-test="nav-soulseek"' in html
    assert 'data-test="nav-soulseek-status"' in html
    assert "status-badge--danger" in html
    assert "Degraded" in html


def test_primary_nav_renders_soulseek_down_badge() -> None:
    items = (
        NavItem(
            label_key="nav.soulseek",
            href="/ui/soulseek",
            test_id="nav-soulseek",
            badge=build_soulseek_navigation_badge(
                connection=StatusResponse(status="disconnected"),
                integration=IntegrationHealth(overall="down", providers=()),
            ),
        ),
    )
    html = _render_inline(
        "{% import 'partials/nav.j2' as nav %}{{ nav.render_primary_nav(items) }}",
        items=items,
    )

    assert 'data-test="nav-soulseek"' in html
    assert 'data-test="nav-soulseek-status"' in html
    assert "status-badge--danger" in html
    assert "Offline" in html


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


def test_spotify_free_ingest_partial_renders_form_and_status() -> None:
    request = _make_request("/ui/spotify/free")
    result = SpotifyFreeIngestResult(
        ok=True,
        job_id="job-free",
        accepted=SpotifyFreeIngestAccepted(playlists=2, tracks=5, batches=1),
        skipped=SpotifyFreeIngestSkipped(playlists=1, tracks=0, reason="limit"),
        error=None,
    )
    job_status = SpotifyFreeIngestJobSnapshot(
        job_id="job-free",
        state="running",
        counts=SpotifyFreeIngestJobCounts(
            registered=3,
            normalized=3,
            queued=2,
            completed=1,
            failed=0,
        ),
        accepted=SpotifyFreeIngestAccepted(playlists=2, tracks=5, batches=1),
        skipped=SpotifyFreeIngestSkipped(playlists=0, tracks=0, reason=None),
        queued_tracks=4,
        failed_tracks=0,
        skipped_tracks=1,
        skip_reason=None,
        error=None,
    )
    context = build_spotify_free_ingest_context(
        request,
        csrf_token="csrf-token",
        form_values={
            "playlist_links": "https://open.spotify.com/playlist/demo",
            "tracks": "Artist - Track",
        },
        result=result,
        job_status=job_status,
        alerts=(AlertMessage(level="success", text="Job enqueued"),),
    )
    template = templates.get_template("partials/spotify_free_ingest.j2")
    html = template.render(**context)

    assert 'id="spotify-free-ingest-form"' in html
    assert 'hx-post="/ui/spotify/free/run"' in html
    assert 'id="spotify-free-ingest-upload-form"' in html
    assert 'enctype="multipart/form-data"' in html
    assert 'hx-post="/ui/spotify/free/upload"' in html
    assert 'name="file"' in html
    assert "Job enqueued" in html
    assert "job-free" in html
    assert "Queued tracks" in html


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
