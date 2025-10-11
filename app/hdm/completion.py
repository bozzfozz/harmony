"""Completion tracking for downloads processed by the pipeline."""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from app.logging import get_logger

from .models import DownloadItem, DownloadWorkItem, ItemEvent

logger = get_logger("hdm.completion")


@dataclass(slots=True)
class DownloadCompletionEvent:
    """Represents an observed completion for a dedupe key."""

    path: Path
    bytes_written: int
    timestamp: datetime


class CompletionEventBus:
    """In-memory event bus for completion notifications."""

    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue[DownloadCompletionEvent]]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def publish(self, dedupe_key: str, event: DownloadCompletionEvent) -> None:
        async with self._lock:
            queues = list(self._queues.get(dedupe_key, ()))
        for queue in queues:
            await queue.put(event)

    async def subscribe(self, dedupe_key: str) -> asyncio.Queue[DownloadCompletionEvent]:
        queue: asyncio.Queue[DownloadCompletionEvent] = asyncio.Queue()
        async with self._lock:
            self._queues[dedupe_key].append(queue)
        return queue

    async def unsubscribe(
        self, dedupe_key: str, queue: asyncio.Queue[DownloadCompletionEvent]
    ) -> None:
        async with self._lock:
            listeners = self._queues.get(dedupe_key)
            if listeners and queue in listeners:
                listeners.remove(queue)
            if listeners == []:
                self._queues.pop(dedupe_key, None)


@dataclass(slots=True)
class CompletionResult:
    """Result describing a completed download ready for further steps."""

    path: Path
    bytes_written: int
    codec: str | None
    duration_seconds: float | None


class DownloadCompletionMonitor:
    """Observe filesystem state to determine when downloads are complete."""

    def __init__(
        self,
        *,
        downloads_dir: Path,
        size_stable_seconds: int,
        event_bus: CompletionEventBus,
        poll_interval: float = 1.0,
    ) -> None:
        self._downloads_dir = downloads_dir
        self._size_stable_seconds = max(1, int(size_stable_seconds))
        self._bus = event_bus
        self._poll_interval = max(0.25, float(poll_interval))

    async def wait_for_completion(
        self,
        work_item: DownloadWorkItem,
        *,
        expected_path: Path | None,
    ) -> CompletionResult:
        """Wait for the download represented by *work_item* to finish."""

        candidate = await self._check_existing(expected_path)
        if candidate is not None:
            return candidate

        dedupe_key = work_item.item.dedupe_key
        queue = await self._bus.subscribe(dedupe_key)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=self._poll_interval)
                except asyncio.TimeoutError:
                    candidate = await self._check_existing(expected_path)
                    if candidate is not None:
                        return candidate
                    fallback = await self._scan_candidates(work_item.item)
                    if fallback is not None:
                        return fallback
                    continue
                if self._is_valid(event.path):
                    bytes_written = event.bytes_written
                    if bytes_written <= 0:
                        bytes_written = await self._ensure_stable(event.path)
                    return await self._build_result(event.path, bytes_written)
                work_item.record_event(
                    "download.event_ignored",
                    meta={
                        "path": str(event.path),
                        "reason": "missing",
                    },
                )
        finally:
            await self._bus.unsubscribe(dedupe_key, queue)

    async def publish_event(
        self,
        dedupe_key: str,
        *,
        path: Path,
        bytes_written: int,
    ) -> None:
        """Publish an externally observed completion event for *dedupe_key*."""

        event = DownloadCompletionEvent(
            path=path,
            bytes_written=bytes_written,
            timestamp=datetime.now(timezone.utc),
        )
        await self._bus.publish(dedupe_key, event)

    async def _check_existing(self, expected_path: Path | None) -> CompletionResult | None:
        if expected_path is not None and self._is_valid(expected_path):
            bytes_written = await self._ensure_stable(expected_path)
            return await self._build_result(expected_path, bytes_written)
        return None

    def _is_valid(self, path: Path) -> bool:
        return path is not None and path.exists() and path.is_file()

    async def _scan_candidates(self, item: DownloadItem) -> CompletionResult | None:
        dedupe_key = item.dedupe_key.lower()
        tokens = {
            item.artist.lower(),
            item.title.lower(),
        }
        for path in self._downloads_dir.iterdir():
            if not path.is_file():
                continue
            name = path.name.lower()
            if dedupe_key in name or all(token in name for token in tokens):
                bytes_written = await self._ensure_stable(path)
                return await self._build_result(path, bytes_written)
        return None

    async def _ensure_stable(self, path: Path) -> int:
        stable_since: float | None = None
        last_size: int | None = None
        while True:
            try:
                stat = await asyncio.to_thread(path.stat)
            except FileNotFoundError:
                stable_since = None
                last_size = None
                await asyncio.sleep(self._poll_interval)
                continue
            size = int(stat.st_size)
            now = time.monotonic()
            if last_size == size and size > 0:
                if stable_since is None:
                    stable_since = now
                elif now - stable_since >= self._size_stable_seconds:
                    return size
            else:
                stable_since = now if size > 0 else None
                last_size = size
            await asyncio.sleep(self._poll_interval)

    async def ensure_stable(self, path: Path) -> int:
        """Public wrapper that waits for the file size to stabilise."""

        return await self._ensure_stable(path)

    async def _build_result(self, path: Path, bytes_written: int) -> CompletionResult:
        codec: str | None = None
        duration: float | None = None
        try:
            from mutagen import File  # type: ignore

            metadata = File(path)
            if metadata is not None:
                info = getattr(metadata, "info", None)
                if info is not None:
                    codec = getattr(info, "codec", None) or getattr(info, "mime", [None])[0]
                    length = getattr(info, "length", None)
                    if isinstance(length, (int, float)):
                        duration = float(length)
        except Exception:  # pragma: no cover - metadata extraction best effort
            logger.debug("Failed to inspect audio metadata", exc_info=True)

        return CompletionResult(
            path=path,
            bytes_written=bytes_written,
            codec=codec,
            duration_seconds=duration,
        )


def record_detection_event(work_item: DownloadWorkItem, *, path: Path, bytes_written: int) -> None:
    work_item.record_event(
        "download.detected",
        meta={
            "path": str(path),
            "bytes_written": bytes_written,
        },
    )


def build_item_event(name: str, **meta: object) -> ItemEvent:
    return ItemEvent(
        name=name,
        timestamp=datetime.now(timezone.utc),
        meta={k: v for k, v in meta.items() if v is not None},
    )


__all__ = [
    "CompletionEventBus",
    "CompletionResult",
    "DownloadCompletionEvent",
    "DownloadCompletionMonitor",
    "build_item_event",
    "record_detection_event",
]
