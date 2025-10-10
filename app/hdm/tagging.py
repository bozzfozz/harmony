"""Audio tagging helpers for the download pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.logging import get_logger

from .models import DownloadItem

logger = get_logger("hdm.tagging")


@dataclass(slots=True)
class TaggingResult:
    """Represents the outcome of a tagging operation."""

    applied: bool
    codec: str | None = None
    bitrate: int | None = None
    duration_seconds: float | None = None


class AudioTagger:
    """Apply simple metadata tags using :mod:`mutagen`."""

    def apply_tags(self, path: Path, item: DownloadItem) -> TaggingResult:
        try:
            from mutagen import File  # type: ignore
        except Exception as exc:  # pragma: no cover - mutagen import failure
            logger.warning("mutagen unavailable: %s", exc)
            return TaggingResult(applied=False)

        audio = File(path, easy=True)
        if audio is None:
            logger.info(
                "Unsupported audio file for tagging",
                extra={
                    "event": "hdm.tagging.unsupported",
                    "path": str(path),
                },
            )
            return TaggingResult(applied=False)

        audio["artist"] = [item.artist]
        audio["title"] = [item.title]
        if item.album:
            audio["album"] = [item.album]
        if item.duration_seconds:
            audio["length"] = [str(item.duration_seconds)]
        if item.isrc:
            audio["isrc"] = [item.isrc]

        audio.save()

        codec: str | None = None
        bitrate: int | None = None
        duration_seconds: float | None = None

        info = getattr(audio, "info", None)
        if info is not None:
            codec = getattr(info, "codec", None) or getattr(info, "mime", [None])[0]
            bitrate_value = getattr(info, "bitrate", None)
            if isinstance(bitrate_value, (int, float)):
                bitrate = int(round(bitrate_value / 1000)) if bitrate_value else None
            duration_value = getattr(info, "length", None)
            if isinstance(duration_value, (int, float)):
                duration_seconds = float(duration_value)

        return TaggingResult(
            applied=True,
            codec=codec,
            bitrate=bitrate,
            duration_seconds=duration_seconds,
        )


__all__ = ["AudioTagger", "TaggingResult"]

