"""Helpers for constraining filesystem paths to configured roots."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
import re

from app.config import AppConfig, Settings, settings as global_settings

_WINDOWS_DRIVE_PATTERN = re.compile(r"^[a-zA-Z]:[\\/]")


def _resolve_root(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def allowed_download_roots(config: AppConfig | None) -> tuple[Path, ...]:
    """Return the canonical download directories permitted for media files."""

    hdm_config = getattr(config, "hdm", None)
    if hdm_config is None:
        hdm_config = getattr(global_settings, "hdm", None)
    if hdm_config is None:
        hdm_config = Settings.load().hdm

    roots: list[Path] = []
    for candidate in (hdm_config.downloads_dir, hdm_config.music_dir):
        if not candidate:
            continue
        resolved = _resolve_root(candidate)
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def _normalise_relative(path: str | Path) -> Path:
    candidate = Path(path)
    parts = [part for part in candidate.parts if part not in {"", "."}]
    return Path(*parts) if parts else Path()


def _is_within(candidate: Path, base: Path) -> bool:
    try:
        candidate.relative_to(base)
        return True
    except ValueError:
        return False


def normalise_download_path(
    raw: str,
    *,
    allowed_roots: Sequence[Path],
) -> Path:
    """Sanitise *raw* relative filename and resolve it under an allowed root."""

    text = raw.strip()
    if not text:
        raise ValueError("filename must not be empty")
    if text.startswith(("/", "\\")) or text.startswith("//"):
        raise ValueError("absolute paths are not allowed")
    if _WINDOWS_DRIVE_PATTERN.match(text):
        raise ValueError("drive-qualified paths are not allowed")

    relative = _normalise_relative(text)
    if not relative.parts:
        raise ValueError("filename must not be empty")
    if any(part == ".." for part in relative.parts):
        raise ValueError("parent directory segments are not allowed")

    for root in allowed_roots:
        resolved_root = root.resolve(strict=False)
        candidate = (resolved_root / relative).resolve(strict=False)
        if _is_within(candidate, resolved_root):
            return candidate
    raise ValueError("path escapes configured download roots")


def ensure_within_roots(
    path: str | Path,
    *,
    allowed_roots: Iterable[Path],
) -> Path:
    """Resolve *path* and ensure it resides under one of *allowed_roots*."""

    candidate = Path(path).expanduser().resolve(strict=False)
    for root in allowed_roots:
        resolved_root = root.resolve(strict=False)
        if _is_within(candidate, resolved_root):
            return candidate
    raise ValueError("path escapes configured download roots")


__all__ = [
    "allowed_download_roots",
    "ensure_within_roots",
    "normalise_download_path",
]
