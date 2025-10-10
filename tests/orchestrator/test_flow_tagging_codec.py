"""Tests covering tagging codec extraction behaviour."""

from __future__ import annotations

import sys
from pathlib import Path
import types

import pytest

from app.hdm.models import DownloadItem
from app.hdm.tagging import AudioTagger
from tests.orchestrator._flow_fixtures import (  # noqa: F401
    configure_environment,
    reset_activity_manager,
)


def _make_item() -> DownloadItem:
    return DownloadItem(
        batch_id="batch",
        item_id="item",
        artist="Artist",
        title="Track",
        album="Album",
        isrc="ISRC123",
        requested_by="tester",
        priority=0,
        dedupe_key="dedupe",
        duration_seconds=180.5,
    )


class _FakeAudio:
    def __init__(self) -> None:
        self.data: dict[str, list[str]] = {}
        self.saved = False
        self.info = types.SimpleNamespace(codec="flac", bitrate=96000, length=181.2)

    def __setitem__(self, key: str, value: list[str]) -> None:
        self.data[key] = value

    def save(self) -> None:
        self.saved = True


def test_apply_tags_records_codec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audio = _FakeAudio()

    def fake_file(path: Path, easy: bool = False):  # type: ignore[override]
        return audio

    module = types.SimpleNamespace(File=fake_file)
    monkeypatch.setitem(sys.modules, "mutagen", module)

    tagger = AudioTagger()
    item = _make_item()
    path = tmp_path / "file.flac"
    path.write_bytes(b"data")

    result = tagger.apply_tags(path, item)

    assert result.applied is True
    assert result.codec == "flac"
    assert result.bitrate == 96
    assert pytest.approx(result.duration_seconds or 0, rel=1e-3) == 181.2
    assert audio.saved is True
    assert audio.data["artist"] == [item.artist]
    assert audio.data["isrc"] == [item.isrc]
    assert audio.data["length"] == [str(item.duration_seconds)]


def test_apply_tags_handles_unsupported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_file(path: Path, easy: bool = False):  # type: ignore[override]
        return None

    module = types.SimpleNamespace(File=fake_file)
    monkeypatch.setitem(sys.modules, "mutagen", module)

    tagger = AudioTagger()
    item = _make_item()
    path = tmp_path / "file.bin"
    path.write_bytes(b"data")

    result = tagger.apply_tags(path, item)

    assert result.applied is False
