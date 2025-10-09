from __future__ import annotations

from pathlib import Path

import pytest

from app.db import init_db, reset_engine_for_tests, session_scope
from app.models import Download
from app.utils.file_utils import guess_album_from_filename, organize_file, sanitize_name
from app.workers.sync_worker import SyncWorker


class FileOrganizeStubSoulseekClient:
    async def cancel_download(
        self, download_id: str
    ) -> None:  # pragma: no cover - stub
        return None


def test_sanitize_name() -> None:
    assert sanitize_name("AC/DC: Greatest Hits!") == "ACDC Greatest Hits"
    assert sanitize_name("   ") == "Unknown"


def test_guess_album_from_filename() -> None:
    assert (
        guess_album_from_filename("Artist - Album Name - 01 - Track.flac")
        == "Album Name"
    )
    assert guess_album_from_filename("Artist -  - 02 - Track.flac") == "<Unknown Album>"
    assert guess_album_from_filename("TrackOnly.flac") is None


def test_organize_file_with_album(tmp_path: Path) -> None:
    source = tmp_path / "downloads" / "Song One.flac"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"data")

    download = Download(
        filename=str(source),
        request_payload={
            "metadata": {
                "artist": "Test Artist",
                "album": "Greatest Hits",
                "title": "Song One",
                "track_number": "1",
            }
        },
    )

    destination = organize_file(download, tmp_path / "music")

    expected = (
        tmp_path / "music" / "Test Artist" / "Greatest Hits" / "01 - Song One.flac"
    )
    assert destination == expected
    assert destination.exists()
    assert download.organized_path == str(expected)
    assert download.filename == str(expected)


def test_organize_file_without_album(tmp_path: Path) -> None:
    source = tmp_path / "incoming" / "Mystery Track.mp3"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"binary")

    download = Download(
        filename=str(source),
        request_payload={"metadata": {"artist": "Mystery", "title": "Hidden Gem"}},
    )

    destination = organize_file(download, tmp_path / "library")

    assert destination.parent.name == "Unknown Album"
    assert destination.parent.parent.name == "Mystery"
    assert destination.name == "Hidden Gem.mp3"


def test_duplicate_files(tmp_path: Path) -> None:
    base_dir = tmp_path / "music"
    base_dir.mkdir()

    source_one = tmp_path / "incoming" / "Track One.flac"
    source_one.parent.mkdir(parents=True, exist_ok=True)
    source_one.write_bytes(b"one")
    download_one = Download(
        filename=str(source_one),
        request_payload={
            "metadata": {
                "artist": "Band",
                "album": "Debut",
                "title": "Anthem",
                "track_number": "1",
            }
        },
    )

    first_path = organize_file(download_one, base_dir)
    assert first_path.name == "01 - Anthem.flac"

    source_two = tmp_path / "incoming" / "Track Two.flac"
    source_two.write_bytes(b"two")
    download_two = Download(
        filename=str(source_two),
        request_payload={
            "metadata": {
                "artist": "Band",
                "album": "Debut",
                "title": "Anthem",
                "track_number": "1",
            }
        },
    )

    second_path = organize_file(download_two, base_dir)
    assert second_path.name == "01 - Anthem_1.flac"
    assert second_path.exists()


@pytest.mark.asyncio
async def test_completed_album_tracks_are_organized(
    tmp_path: Path, monkeypatch
) -> None:
    reset_engine_for_tests()
    init_db()

    music_dir = tmp_path / "library"
    monkeypatch.setenv("MUSIC_DIR", str(music_dir))

    download_dir = tmp_path / "downloads"
    download_dir.mkdir()

    track_one = download_dir / "Track1.flac"
    track_two = download_dir / "Track2.flac"
    track_one.write_bytes(b"one")
    track_two.write_bytes(b"two")

    with session_scope() as session:
        first = Download(
            filename=str(track_one),
            state="completed",
            progress=100.0,
            request_payload={
                "metadata": {
                    "artist": "Integration Band",
                    "album": "Live Session",
                    "title": "Opening",
                    "track_number": "1",
                }
            },
        )
        second = Download(
            filename=str(track_two),
            state="completed",
            progress=100.0,
            request_payload={
                "metadata": {
                    "artist": "Integration Band",
                    "album": "Live Session",
                    "title": "Encore",
                    "track_number": "2",
                }
            },
        )
        session.add_all([first, second])
        session.flush()
        first_id = first.id
        second_id = second.id

    worker = SyncWorker(soulseek_client=FileOrganizeStubSoulseekClient())

    await worker._handle_download_completion(
        first_id,
        {"download_id": first_id, "state": "completed", "local_path": str(track_one)},
    )
    await worker._handle_download_completion(
        second_id,
        {"download_id": second_id, "state": "completed", "local_path": str(track_two)},
    )

    organized_files = list(music_dir.rglob("*.flac"))
    assert len(organized_files) == 2
    assert organized_files[0].parent == organized_files[1].parent

    with session_scope() as session:
        refreshed_first = session.get(Download, first_id)
        refreshed_second = session.get(Download, second_id)
    assert refreshed_first is not None and refreshed_second is not None
    assert Path(refreshed_first.organized_path).exists()
    assert Path(refreshed_second.organized_path).exists()
