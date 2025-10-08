from typing import Any

import pytest

from app.services.free_ingest_service import (IngestAccepted, IngestSkipped,
                                              IngestSubmission)
from tests.simple_client import SimpleTestClient


def test_free_import_invokes_orchestrator_and_logs(
    monkeypatch: pytest.MonkeyPatch, client: SimpleTestClient
) -> None:
    submission = IngestSubmission(
        ok=True,
        job_id="job-test",
        accepted=IngestAccepted(playlists=1, tracks=2, batches=1),
        skipped=IngestSkipped(playlists=0, tracks=0, reason=None),
        error=None,
    )
    captured: dict[str, Any] = {}

    async def fake_enqueue(service, **kwargs: Any):  # type: ignore[override]
        captured["service"] = service
        captured["kwargs"] = kwargs
        return submission

    events: list[dict[str, Any]] = []

    def fake_log_event(logger: Any, event: str, /, **fields: Any) -> None:
        events.append({"event": event, **fields})

    monkeypatch.setattr(
        "app.orchestrator.handlers.enqueue_spotify_free_import",
        fake_enqueue,
    )
    monkeypatch.setattr("app.services.spotify_domain_service.log_event", fake_log_event)

    response = client.post(
        "/spotify/import/free",
        json={
            "playlist_links": ["https://open.spotify.com/playlist/abc123"],
            "tracks": ["Artist - Track"],
            "batch_hint": 4,
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["ok"] is True
    assert payload["job_id"] == submission.job_id
    assert payload["accepted"]["tracks"] == submission.accepted.tracks
    assert payload["skipped"]["tracks"] == submission.skipped.tracks

    assert captured["kwargs"] == {
        "playlist_links": ["https://open.spotify.com/playlist/abc123"],
        "tracks": ["Artist - Track"],
        "batch_hint": 4,
    }
    assert "service" in captured

    matching_events = [event for event in events if event.get("event") == "spotify.free_import"]
    assert matching_events, "expected spotify.free_import log event"
    logged = matching_events[0]
    assert logged["status"] == "ok"
    assert logged["accepted_tracks"] == submission.accepted.tracks
    assert logged["skipped_tracks"] == submission.skipped.tracks
    assert "duration_ms" in logged
