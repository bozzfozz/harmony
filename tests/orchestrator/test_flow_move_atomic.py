"""Tests for atomic file move fallbacks in the Harmony Download Manager."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.hdm.move import AtomicFileMover
from tests.orchestrator._flow_fixtures import (  # noqa: F401
    configure_environment,
    reset_activity_manager,
)


def _write_file(path: Path, content: bytes = b"payload") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_atomic_move_succeeds(tmp_path: Path) -> None:
    mover = AtomicFileMover()
    source = tmp_path / "tmp" / "file.flac"
    destination = tmp_path / "library" / "file.flac"
    _write_file(source)

    result = mover.move(source, destination)

    assert result == destination
    assert destination.exists()
    assert not source.exists()


def test_cross_device_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mover = AtomicFileMover()
    source = tmp_path / "tmp" / "file.flac"
    destination = tmp_path / "library" / "file.flac"
    _write_file(source, b"data")

    original_replace = Path.replace

    def failing_replace(self: Path, target: Path) -> Path:
        if self == source:
            raise OSError(getattr(os, "EXDEV", 18), "cross-device link")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", failing_replace)

    result = mover.move(source, destination)

    assert result == destination
    assert destination.exists()
    assert destination.read_bytes() == b"data"
    assert not source.exists()
