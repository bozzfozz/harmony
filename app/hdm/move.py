"""Helpers for moving downloaded files into the library."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from app.logging import get_logger

logger = get_logger("hdm.move")


class AtomicFileMover:
    """Perform atomic moves with safe cross-device fallbacks."""

    def move(self, source: Path, destination: Path) -> Path:
        """Move *source* to *destination*, ensuring durability."""

        if not source.exists():
            raise FileNotFoundError(source)

        destination.parent.mkdir(parents=True, exist_ok=True)

        try:
            return source.replace(destination)
        except OSError as exc:
            if exc.errno != getattr(os, "EXDEV", 18):
                raise
            logger.info(
                "Cross-device move detected, falling back to copy",
                extra={
                    "event": "hdm.move.copy_fallback",
                    "source": str(source),
                    "destination": str(destination),
                },
            )
            self._copy_across_devices(source, destination)
            return destination

    def _copy_across_devices(self, source: Path, destination: Path) -> None:
        tmp = destination.with_suffix(destination.suffix + ".tmpcopy")
        shutil.copy2(source, tmp)
        self._fsync_file(tmp)
        self._fsync_directory(destination.parent)
        tmp.replace(destination)
        self._fsync_directory(destination.parent)
        logger.info(
            "Cross-device copy fallback completed",
            extra={
                "event": "hdm.move.copy_fallback.succeeded",
                "source": str(source),
                "destination": str(destination),
            },
        )
        try:
            source.unlink()
        except FileNotFoundError:  # pragma: no cover - race with other cleanup
            return

    def _fsync_file(self, path: Path) -> None:
        with path.open("rb") as handle:
            try:
                os.fsync(handle.fileno())
            except OSError:
                logger.warning(
                    "fsync failed for temporary file",
                    extra={
                        "event": "hdm.move.fsync_failed",
                        "path": str(path),
                        "path_type": "file",
                    },
                    exc_info=True,
                )

    def _fsync_directory(self, directory: Path) -> None:
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        try:
            fd = os.open(str(directory), flags)
        except OSError:
            logger.warning(
                "fsync failed to open directory",
                extra={
                    "event": "hdm.move.fsync_failed",
                    "path": str(directory),
                    "path_type": "directory",
                },
                exc_info=True,
            )
            return
        try:
            os.fsync(fd)
        except OSError:
            logger.warning(
                "fsync failed for directory",
                extra={
                    "event": "hdm.move.fsync_failed",
                    "path": str(directory),
                    "path_type": "directory",
                },
                exc_info=True,
            )
        finally:
            os.close(fd)


__all__ = ["AtomicFileMover"]
