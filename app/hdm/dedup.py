"""Deduplication helpers for the HDM pipeline."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.logging import get_logger

from .models import DownloadItem

try:  # pragma: no cover - windows fallback
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


logger = get_logger("hdm.dedup")


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(slots=True)
class _DedupLockHandle:
    """Represents an acquired filesystem lock."""

    path: Path
    handle: Any

    def release(self) -> None:
        if fcntl is not None:
            try:
                fcntl.flock(self.handle, fcntl.LOCK_UN)
            except OSError:  # pragma: no cover - defensive unlock failure
                logger.warning("Failed to release dedupe lock", exc_info=True)
        try:
            self.handle.close()
        except OSError:  # pragma: no cover - defensive close failure
            logger.warning("Failed to close dedupe lock handle", exc_info=True)


class _AsyncLockContext:
    """Async context manager wrapping a synchronous lock handle."""

    def __init__(self, acquire: asyncio.Future[_DedupLockHandle]) -> None:
        self._acquire_future = acquire
        self._handle: _DedupLockHandle | None = None

    async def __aenter__(self) -> _DedupLockHandle:
        self._handle = await self._acquire_future
        return self._handle

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        if self._handle is not None:
            await asyncio.to_thread(self._handle.release)
            self._handle = None


class DeduplicationManager:
    """Coordinate deduplication locking and bookkeeping."""

    def __init__(
        self,
        *,
        music_dir: Path,
        state_dir: Path,
        move_template: str,
    ) -> None:
        self._music_dir = music_dir
        self._state_dir = _ensure_dir(state_dir)
        self._locks_dir = _ensure_dir(self._state_dir / "locks")
        self._index_path = self._state_dir / "dedupe_index.json"
        self._index_lock = asyncio.Lock()
        self._move_template = move_template

    # ------------------------------------------------------------------
    # Locking helpers
    # ------------------------------------------------------------------
    async def acquire_lock(self, item: DownloadItem) -> _AsyncLockContext:
        """Acquire a process-wide lock for the given *item* dedupe key."""

        key = item.dedupe_key
        future: asyncio.Future[_DedupLockHandle] = asyncio.ensure_future(
            asyncio.to_thread(self._acquire_lock_sync, key)
        )
        return _AsyncLockContext(future)

    def _acquire_lock_sync(self, dedupe_key: str) -> _DedupLockHandle:
        lock_path = self._locks_dir / f"{dedupe_key}.lock"
        handle = lock_path.open("a+b")
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_EX)
        else:  # pragma: no cover - Windows fallback best effort
            try:
                os.lockf(handle.fileno(), os.F_LOCK, 0)
            except OSError:
                logger.warning("Failed to lock %s", lock_path, exc_info=True)
        return _DedupLockHandle(path=lock_path, handle=handle)

    # ------------------------------------------------------------------
    # Index helpers
    # ------------------------------------------------------------------
    async def lookup_existing(self, dedupe_key: str) -> Path | None:
        """Return the known destination for *dedupe_key* if recorded."""

        index = await self._load_index()
        existing = index.get(dedupe_key)
        return Path(existing) if existing else None

    async def register_completion(self, dedupe_key: str, final_path: Path) -> None:
        """Persist the destination path for *dedupe_key*."""

        async with self._index_lock:
            index = await self._load_index()
            index[dedupe_key] = str(final_path)
            await self._write_index(index)

    async def _load_index(self) -> dict[str, str]:
        if not self._index_path.exists():
            return {}
        return await asyncio.to_thread(self._read_index_sync)

    def _read_index_sync(self) -> dict[str, str]:
        try:
            with self._index_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError:  # pragma: no cover - corrupted file
            logger.warning("dedupe index corrupted, recreating", exc_info=True)
            data = {}
        return {str(key): str(value) for key, value in data.items()}

    async def _write_index(self, data: dict[str, str]) -> None:
        await asyncio.to_thread(self._write_index_sync, data)

    def _write_index_sync(self, data: dict[str, str]) -> None:
        tmp = self._index_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(self._index_path)

    # ------------------------------------------------------------------
    # Destination resolution
    # ------------------------------------------------------------------
    def plan_destination(self, item: DownloadItem, source_path: Path) -> Path:
        """Resolve the final library path for *item* based on the template."""

        metadata = self._build_metadata(item, source_path)
        relative = self._render_template(metadata)
        destination = self._music_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        return destination

    def _render_template(self, metadata: dict[str, str]) -> Path:
        try:
            rendered = self._move_template.format(**metadata)
        except KeyError as exc:  # pragma: no cover - template misconfiguration
            missing = exc.args[0]
            raise RuntimeError(f"Unknown placeholder in move template: {missing}") from exc
        clean = rendered.strip().strip("/")
        return Path(clean)

    def _build_metadata(self, item: DownloadItem, source_path: Path) -> dict[str, str]:
        from app.utils.file_utils import sanitize_name

        extension = source_path.suffix.lstrip(".") or "bin"
        return {
            "artist": sanitize_name(item.artist) or "Unknown Artist",
            "album": sanitize_name(item.album or "Unknown Album"),
            "title": sanitize_name(item.title) or "Track",
            "dedupe_key": sanitize_name(item.dedupe_key),
            "batch_id": item.batch_id,
            "item_id": item.item_id,
            "extension": extension.lower(),
        }


__all__ = ["DeduplicationManager"]
