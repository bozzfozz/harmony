from __future__ import annotations

import errno
import os
from pathlib import Path

from app.hdm import AtomicFileMover as PublicAtomicFileMover
from app.hdm.move import AtomicFileMover, logger


def test_cross_device_fallback_fsync(monkeypatch, tmp_path, caplog):
    mover = AtomicFileMover()
    source = tmp_path / "source.txt"
    destination_dir = tmp_path / "dest"
    destination_dir.mkdir()
    destination = destination_dir / "payload.txt"
    source.write_text("payload")

    original_replace = Path.replace
    call_state = {"count": 0}

    def fake_replace(self: Path, target: Path):
        if self == source and call_state["count"] == 0:
            call_state["count"] += 1
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fake_replace)

    fsync_calls: list[int] = []

    def fake_fsync(fd: int) -> None:
        fsync_calls.append(fd)

    monkeypatch.setattr(os, "fsync", fake_fsync)

    with caplog.at_level("INFO", logger.name):
        result = mover.move(source, destination)

    assert result == destination
    assert destination.read_text() == "payload"
    # one fsync for the temp file, and at least one for the directory
    assert len(fsync_calls) >= 2
    assert any(
        getattr(record, "event", None) == "hdm.move.copy_fallback.succeeded"
        for record in caplog.records
    )


def test_atomic_file_mover_is_publicly_exposed():
    assert PublicAtomicFileMover is AtomicFileMover
