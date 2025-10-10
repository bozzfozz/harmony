"""Crash recovery helpers and sidecar state management."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.logging import get_logger

from .completion import (
    CompletionEventBus,
    DownloadCompletionEvent,
    DownloadCompletionMonitor,
)
from .models import DownloadItem

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class DownloadSidecar:
    """Persisted state for an in-flight download."""

    path: Path
    batch_id: str
    item_id: str
    dedupe_key: str
    attempt: int
    status: str = "pending"
    source_path: str | None = None
    final_path: str | None = None
    bytes_written: int | None = None
    download_id: str | None = None
    updated_at: datetime = field(default_factory=_now)

    def to_dict(self) -> dict[str, object]:
        return {
            "batch_id": self.batch_id,
            "item_id": self.item_id,
            "dedupe_key": self.dedupe_key,
            "attempt": self.attempt,
            "status": self.status,
            "source_path": self.source_path,
            "final_path": self.final_path,
            "bytes_written": self.bytes_written,
            "download_id": self.download_id,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, path: Path, payload: dict[str, object]) -> "DownloadSidecar":
        updated_raw = payload.get("updated_at")
        if isinstance(updated_raw, str):
            try:
                updated = datetime.fromisoformat(updated_raw)
            except ValueError:
                updated = _now()
        else:
            updated = _now()
        return cls(
            path=path,
            batch_id=str(payload.get("batch_id")),
            item_id=str(payload.get("item_id")),
            dedupe_key=str(payload.get("dedupe_key")),
            attempt=int(payload.get("attempt", 1)),
            status=str(payload.get("status", "pending")),
            source_path=str(payload.get("source_path"))
            if payload.get("source_path")
            else None,
            final_path=str(payload.get("final_path")) if payload.get("final_path") else None,
            bytes_written=int(payload.get("bytes_written"))
            if payload.get("bytes_written") is not None
            else None,
            download_id=str(payload.get("download_id"))
            if payload.get("download_id")
            else None,
            updated_at=updated,
        )

    def mark(self, *, status: str, source_path: Path | None = None) -> None:
        self.status = status
        if source_path is not None:
            self.source_path = str(source_path)
        self.updated_at = _now()

    def set_final(self, path: Path, bytes_written: int) -> None:
        self.final_path = str(path)
        self.bytes_written = bytes_written
        self.status = "completed"
        self.updated_at = _now()


class SidecarStore:
    """Manage persistence of :class:`DownloadSidecar` entries."""

    def __init__(self, base_dir: Path) -> None:
        self._dir = base_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[Path, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    def path_for(self, item: DownloadItem) -> Path:
        return self._dir / f"{item.batch_id}_{item.item_id}.json"

    async def load(self, item: DownloadItem, *, attempt: int) -> DownloadSidecar:
        path = self.path_for(item)
        lock = await self._lock_for(path)
        async with lock:
            if path.exists():
                payload = await asyncio.to_thread(self._read_json, path)
                sidecar = DownloadSidecar.from_dict(path, payload)
            else:
                sidecar = DownloadSidecar(
                    path=path,
                    batch_id=item.batch_id,
                    item_id=item.item_id,
                    dedupe_key=item.dedupe_key,
                    attempt=attempt,
                )
                await asyncio.to_thread(self._write_json, path, sidecar.to_dict())
        return sidecar

    async def save(self, sidecar: DownloadSidecar) -> None:
        lock = await self._lock_for(sidecar.path)
        async with lock:
            await asyncio.to_thread(self._write_json, sidecar.path, sidecar.to_dict())

    async def iter_active(self) -> list[DownloadSidecar]:
        entries = await asyncio.to_thread(list, self._dir.glob("*.json"))
        result: list[DownloadSidecar] = []
        for entry in entries:
            try:
                payload = await asyncio.to_thread(self._read_json, entry)
            except json.JSONDecodeError:  # pragma: no cover - corrupted sidecar
                logger.warning("Corrupted sidecar %s", entry)
                continue
            result.append(DownloadSidecar.from_dict(entry, payload))
        return result

    async def _lock_for(self, path: Path) -> asyncio.Lock:
        async with self._global_lock:
            lock = self._locks.get(path)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[path] = lock
            return lock

    @staticmethod
    def _read_json(path: Path) -> dict[str, object]:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    @staticmethod
    def _write_json(path: Path, payload: dict[str, object]) -> None:
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)


class DownloadFlowRecovery:
    """Background recovery task scanning for stale downloads."""

    def __init__(
        self,
        *,
        size_stable_seconds: int,
        sidecars: SidecarStore,
        completion_monitor: DownloadCompletionMonitor,
        event_bus: CompletionEventBus,
        poll_interval: float = 10.0,
    ) -> None:
        self._size_stable_seconds = max(1, int(size_stable_seconds))
        self._sidecars = sidecars
        self._monitor = completion_monitor
        self._bus = event_bus
        self._poll_interval = max(5.0, float(poll_interval))
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopping.clear()
        self._task = asyncio.create_task(self._run())
        logger.info(
            "Download flow recovery started",
            extra={
                "event": "download_flow.recovery_started",
                "size_stable_seconds": self._size_stable_seconds,
            },
        )

    async def shutdown(self) -> None:
        if self._task is None:
            return
        self._stopping.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info(
            "Download flow recovery stopped", extra={"event": "download_flow.recovery_stopped"}
        )

    async def _run(self) -> None:
        try:
            while not self._stopping.is_set():
                await self._scan()
                try:
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=self._poll_interval
                    )
                except asyncio.TimeoutError:
                    continue
        except asyncio.CancelledError:  # pragma: no cover - shutdown path
            return

    async def _scan(self) -> None:
        sidecars = await self._sidecars.iter_active()
        for sidecar in sidecars:
            if sidecar.status == "completed":
                continue
            if not sidecar.source_path:
                continue
            path = Path(sidecar.source_path)
            if not path.exists():
                continue
            bytes_written = await self._monitor.ensure_stable(path)
            event = DownloadCompletionEvent(
                path=path,
                bytes_written=bytes_written,
                timestamp=_now(),
            )
            await self._bus.publish(sidecar.dedupe_key, event)


__all__ = ["DownloadFlowRecovery", "DownloadSidecar", "SidecarStore"]

