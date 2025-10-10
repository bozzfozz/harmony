"""Helpers for moving downloaded files into the library."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from app.logging import get_logger

logger = get_logger(__name__)


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
                    "event": "download_flow.move.copy_fallback",
                    "source": str(source),
                    "destination": str(destination),
                },
            )
            self._copy_across_devices(source, destination)
            return destination

    def _copy_across_devices(self, source: Path, destination: Path) -> None:
        tmp = destination.with_suffix(destination.suffix + ".tmpcopy")
        shutil.copy2(source, tmp)
        tmp.replace(destination)
        try:
            source.unlink()
        except FileNotFoundError:  # pragma: no cover - race with other cleanup
            return


__all__ = ["AtomicFileMover"]

