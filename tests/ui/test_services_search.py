"""Tests for :mod:`app.ui.services.search` result formatting."""

from __future__ import annotations

import pytest

from app.schemas_search import SearchItem
from app.ui.services.search import SearchUiService


def test_to_result_builds_download_payload_with_candidate_metadata() -> None:
    """A rich Soulseek candidate should surface all metadata for downloads."""

    item = SearchItem(
        type="track",
        id="abc123",
        source="soulseek",
        title="  Primary Song  ",
        artist="Artist",
        score=0.87,
        metadata={
            "candidate": {
                "username": "  uploader  ",
                "download_uri": "magnet:?xt=urn:btih:abc123",
                "title": "Candidate Song",
                "artist": "Candidate Artist",
                "format": "FLAC",
                "bitrate_kbps": 320,
                "size_bytes": 123456789,
                "seeders": 5,
                "metadata": {
                    "filename": "candidate.flac",
                    "path": "/music/candidate.flac",
                },
            }
        },
    )

    result = SearchUiService._to_result(item)

    assert result.identifier == "abc123"
    assert result.title == "  Primary Song  "
    assert result.artist == "Artist"
    assert result.source == "soulseek"
    assert result.score == pytest.approx(0.87)
    assert result.download is not None

    download = result.download
    assert download is not None
    assert download.username == "uploader"
    assert len(download.files) == 1

    (file_payload,) = download.files
    assert file_payload["filename"] == "candidate.flac"
    assert file_payload["name"] == "candidate.flac"
    assert file_payload["download_uri"] == "magnet:?xt=urn:btih:abc123"
    assert file_payload["source"] == "ui-search:soulseek"
    assert file_payload["format"] == "FLAC"
    assert file_payload["bitrate_kbps"] == 320
    assert file_payload["size_bytes"] == 123456789
    assert file_payload["seeders"] == 5

    metadata = file_payload["metadata"]
    assert metadata["search_identifier"] == "abc123"
    assert metadata["search_source"] == "soulseek"
    assert metadata["search_title"] == "Primary Song"
    assert metadata["search_artist"] == "Artist"
    assert metadata["candidate_path"] == "/music/candidate.flac"


def test_to_result_derives_filename_from_candidate_title_and_artist() -> None:
    """Spotify downloads derive filenames from the candidate when needed."""

    item = SearchItem(
        type="track",
        id="sp-1",
        source="spotify",
        title="Song Example",
        artist="Artist Example",
        metadata={
            "candidate": {
                "username": "collector",
                "download_uri": "https://example.com/download",
                "title": "Archive Title",
                "artist": "Archive Artist",
                "format": "MP3",
                "bitrate_kbps": 192,
            }
        },
    )

    result = SearchUiService._to_result(item)

    assert result.download is not None
    (file_payload,) = result.download.files

    assert file_payload["filename"] == "Archive Artist - Archive Title"
    assert file_payload["name"] == "Archive Artist - Archive Title"
    assert file_payload["download_uri"] == "https://example.com/download"
    assert file_payload["source"] == "ui-search:spotify"
    assert file_payload["format"] == "MP3"
    assert file_payload["bitrate_kbps"] == 192

    metadata = file_payload["metadata"]
    assert metadata["search_identifier"] == "sp-1"
    assert metadata["search_source"] == "spotify"
    assert metadata["search_title"] == "Song Example"
    assert metadata["search_artist"] == "Artist Example"
    assert "candidate_path" not in metadata


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"candidate": None},
        {"candidate": "not-a-mapping"},
        {"candidate": {"username": "", "download_uri": "magnet:?xt=urn:btih:1"}},
        {"candidate": {"username": "listener", "download_uri": ""}},
        {"candidate": {"username": "listener"}},
        {"candidate": {"download_uri": "magnet:?xt=urn:btih:1"}},
    ],
)
def test_to_result_rejects_incomplete_candidates(metadata: dict[str, object]) -> None:
    """Only fully-formed candidates should be promoted to downloads."""

    item = SearchItem(
        type="track",
        id="missing",
        source="soulseek",
        title="Example",
        metadata=metadata,
    )

    result = SearchUiService._to_result(item)

    assert result.download is None
