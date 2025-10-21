from __future__ import annotations

from datetime import UTC, datetime

from starlette.requests import Request

from app.ui.context.base import AlertMessage
from app.ui.context.spotify import (
    build_spotify_free_ingest_context,
    build_spotify_free_ingest_form_context,
    build_spotify_free_ingest_status_context,
    build_spotify_page_context,
    build_spotify_recommendations_context,
    build_spotify_saved_tracks_context,
)
from app.ui.services import (
    SpotifyFreeIngestAccepted,
    SpotifyFreeIngestJobCounts,
    SpotifyFreeIngestJobSnapshot,
    SpotifyFreeIngestResult,
    SpotifyFreeIngestSkipped,
    SpotifyRecommendationRow,
    SpotifySavedTrackRow,
)
from app.ui.session import UiFeatures, UiSession


def _make_request(path: str = "/ui/spotify/free") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
    }
    return Request(scope)


def test_build_spotify_free_ingest_form_context_populates_summary() -> None:
    result = SpotifyFreeIngestResult(
        ok=True,
        job_id="job-42",
        accepted=SpotifyFreeIngestAccepted(playlists=3, tracks=8, batches=2),
        skipped=SpotifyFreeIngestSkipped(playlists=1, tracks=0, reason="limit"),
        error=None,
    )

    form_context = build_spotify_free_ingest_form_context(
        csrf_token="csrf-token",
        form_values={
            "playlist_links": "https://open.spotify.com/playlist/1",
            "tracks": "Artist - Track",
        },
        form_errors={"playlist_links": "bad url", "tracks": ""},
        result=result,
    )

    assert form_context.playlist_value.startswith("https://open.spotify.com/")
    assert form_context.tracks_value == "Artist - Track"
    assert form_context.form_errors == {"playlist_links": "bad url"}
    assert [item.value for item in form_context.accepted_items] == ["3", "8", "2"]
    assert [item.value for item in form_context.skipped_items] == ["1", "0"]


def test_build_spotify_free_ingest_status_context_handles_snapshot() -> None:
    status = SpotifyFreeIngestJobSnapshot(
        job_id="job-99",
        state="running",
        counts=SpotifyFreeIngestJobCounts(
            registered=5,
            normalized=5,
            queued=4,
            completed=1,
            failed=0,
        ),
        accepted=SpotifyFreeIngestAccepted(playlists=2, tracks=7, batches=1),
        skipped=SpotifyFreeIngestSkipped(playlists=1, tracks=1, reason="duplicate"),
        queued_tracks=12,
        failed_tracks=1,
        skipped_tracks=2,
        skip_reason="duplicate",
        error="Minor issue",
    )

    snapshot = build_spotify_free_ingest_status_context(status=status)

    assert snapshot is not None
    assert snapshot.job_id == "job-99"
    assert snapshot.state == "running"
    assert [item.value for item in snapshot.counts] == ["5", "5", "4", "1", "0"]
    assert [item.value for item in snapshot.accepted_items] == ["2", "7", "1"]
    assert [item.value for item in snapshot.skipped_items] == ["1", "1"]
    assert snapshot.queued_tracks == 12
    assert snapshot.failed_tracks == 1
    assert snapshot.skipped_tracks == 2
    assert snapshot.error == "Minor issue"
    assert snapshot.skip_reason == "duplicate"


def test_build_spotify_free_ingest_status_context_returns_none_without_status() -> None:
    assert build_spotify_free_ingest_status_context(status=None) is None


def test_build_spotify_free_ingest_context_includes_alerts_and_form_values() -> None:
    request = _make_request()
    context = build_spotify_free_ingest_context(
        request,
        csrf_token="csrf-token",
        form_values={"playlist_links": "link", "tracks": "track"},
        form_errors={"playlist_links": "error"},
        alerts=(AlertMessage(level="error", text="Something failed"),),
    )

    assert context["form"].playlist_value == "link"
    assert context["form"].form_errors == {"playlist_links": "error"}
    assert context["alert_messages"] == (AlertMessage(level="error", text="Something failed"),)
    assert context["job_status"] is None


def test_build_spotify_page_context_sets_free_ingest_poll_interval() -> None:
    request = _make_request("/ui/spotify")
    now = datetime.now(tz=UTC)
    session = UiSession(
        identifier="session-1",
        role="operator",
        features=UiFeatures(spotify=True, soulseek=True, dlq=True, imports=True),
        fingerprint="fingerprint",
        issued_at=now,
        last_seen_at=now,
    )

    context = build_spotify_page_context(request, session=session, csrf_token="csrf")

    fragment = context["free_ingest_fragment"]
    assert fragment is not None
    assert fragment.poll_interval_seconds == 15
    assert fragment.trigger == "revealed, every 15s"


def test_build_spotify_recommendations_context_disables_queue_forms() -> None:
    request = _make_request("/ui/spotify/recommendations")
    rows = (
        SpotifyRecommendationRow(
            identifier="track-1",
            name="Track One",
            artists=("Artist",),
            album=None,
            preview_url=None,
        ),
    )
    context = build_spotify_recommendations_context(
        request,
        csrf_token="csrf",
        rows=rows,
        queue_enabled=False,
    )

    fragment = context["fragment"]
    actions_cell = fragment.table.rows[0].cells[-1]
    assert all(form.submit_label_key != "spotify.saved.queue" for form in actions_cell.forms)
    assert fragment.data_attributes["queue-enabled"] == "0"
    assert context["queue_enabled"] is False


def test_build_spotify_saved_tracks_context_disables_queue_forms() -> None:
    request = _make_request("/ui/spotify")
    rows = (
        SpotifySavedTrackRow(
            identifier="track-1",
            name="Track One",
            artists=("Artist",),
            album=None,
            added_at=datetime.now(tz=UTC),
        ),
    )
    context = build_spotify_saved_tracks_context(
        request,
        rows=rows,
        total_count=1,
        limit=25,
        offset=0,
        csrf_token="csrf",
        queue_enabled=False,
    )

    fragment = context["fragment"]
    actions_cell = fragment.table.rows[0].cells[-1]
    assert all(form.submit_label_key != "spotify.saved.queue" for form in actions_cell.forms)
    assert fragment.data_attributes["queue-enabled"] == "0"
    assert context["queue_enabled"] is False
    assert context["queue_action_url"] is None
