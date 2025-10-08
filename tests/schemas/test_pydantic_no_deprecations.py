"""Ensure representative Pydantic models do not emit deprecation warnings."""

from __future__ import annotations

import warnings
from datetime import datetime, timezone

from app.schemas import DownloadFileRequest
from app.schemas.common import ID, URI, ISODateTime, ProblemDetail
from app.schemas.watchlist import (WatchlistEntryResponse,
                                   WatchlistListResponse,
                                   WatchlistPauseRequest,
                                   WatchlistPriorityUpdate)


def test_pydantic_models_emit_no_deprecations() -> None:
    """Instantiating key models should not trigger deprecated behaviours."""

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)

        download = DownloadFileRequest(filename="  example.flac  ", priority=2)
        assert download.resolved_filename == "example.flac"

        detail = ProblemDetail(code="E001", message="something went wrong")
        assert detail.code == "E001"
        assert detail.timestamp.endswith("+00:00")

        pause = WatchlistPauseRequest(reason="  hiatus  ")
        assert pause.reason == "hiatus"

        update = WatchlistPriorityUpdate(priority=3)
        assert update.priority == 3

        entry = WatchlistEntryResponse(
            id=1,
            artist_key="artist-key",
            priority=update.priority,
            paused=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        listing = WatchlistListResponse(items=[entry])
        assert listing.items[0].artist_key == "artist-key"

        assert isinstance(ID.validate("  abc  "), ID)
        assert isinstance(URI.validate("https://example.com"), URI)
        assert isinstance(ISODateTime.validate("2024-01-01T00:00:00Z"), ISODateTime)
