"""Worker lifecycle stubs for exercising the FastAPI lifespan hooks."""

from __future__ import annotations

import asyncio
import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Dict, Iterable

import pytest

from tests.support.async_utils import cancel_and_await


LOGGER = logging.getLogger("tests.worker.stub")


@dataclass
class WorkerScenario:
    """Behavioural toggles for a worker stub."""

    fail_on_start: bool = False
    start_delay: float = 0.0
    run_forever: bool = False
    crash_during_run: bool = False
    crash_delay: float = 0.05
    stop_timeout: float = 0.5


class RecordingWorker:
    """Simple async worker with observable start/stop lifecycle."""

    def __init__(
        self,
        *,
        name: str,
        scenario: WorkerScenario,
        registry: "WorkerRegistry",
    ) -> None:
        self.name = name
        self.scenario = scenario
        self.registry = registry
        self.start_calls = 0
        self.stop_calls = 0
        self.started = False
        self.stopped = False
        self.start_durations: list[float] = []
        self.stop_durations: list[float] = []
        self.background_task: asyncio.Task[None] | None = None
        self.background_started = asyncio.Event()
        self.background_finished = asyncio.Event()
        self.background_error: Exception | None = None
        self._stop_signal = asyncio.Event()
        registry.register(name, self)

    async def start(self) -> None:
        self.start_calls += 1
        started_at = perf_counter()
        try:
            if self.scenario.start_delay:
                await asyncio.sleep(self.scenario.start_delay)
            if self.scenario.fail_on_start:
                raise RuntimeError(f"{self.name} failed during start")
            if self.scenario.run_forever or self.scenario.crash_during_run:
                self.background_task = asyncio.create_task(self._background())
                self.background_started.set()
            self.started = True
        except Exception:
            duration = (perf_counter() - started_at) * 1_000
            event = {
                "event": "worker.start",
                "worker": self.name,
                "status": "error",
                "duration_ms": round(duration, 3),
            }
            LOGGER.error("worker.start %s failed", self.name, extra=event)
            self.registry.log_events.append(event)
            raise
        else:
            duration = (perf_counter() - started_at) * 1_000
            self.start_durations.append(duration)
            event = {
                "event": "worker.start",
                "worker": self.name,
                "status": "ok",
                "duration_ms": round(duration, 3),
            }
            LOGGER.info("worker.start %s ok", self.name, extra=event)
            self.registry.log_events.append(event)

    async def _background(self) -> None:
        try:
            if self.scenario.crash_during_run:
                await asyncio.sleep(self.scenario.crash_delay)
                raise RuntimeError(f"{self.name} background crash")
            await self._stop_signal.wait()
        except Exception as exc:  # pragma: no cover - defensive logging
            self.background_error = exc
            event = {"event": "worker.run", "worker": self.name, "status": "error"}
            LOGGER.error("worker.run %s error", self.name, extra=event)
            self.registry.log_events.append(event)
        finally:
            self.background_finished.set()

    async def stop(self) -> None:
        self.stop_calls += 1
        started_at = perf_counter()
        try:
            if self.background_task is not None and not self.background_task.done():
                self._stop_signal.set()
                try:
                    await asyncio.wait_for(self.background_task, timeout=self.scenario.stop_timeout)
                except asyncio.TimeoutError:
                    await cancel_and_await(self.background_task)
            self.stopped = True
        finally:
            duration = (perf_counter() - started_at) * 1_000
            self.stop_durations.append(duration)
            event = {
                "event": "worker.stop",
                "worker": self.name,
                "status": "ok",
                "duration_ms": round(duration, 3),
            }
            LOGGER.info("worker.stop %s ok", self.name, extra=event)
            self.registry.log_events.append(event)


class WorkerRegistry:
    """Tracks worker stub instances and installs them into ``app.main``."""

    WORKER_ATTRIBUTES = {
        "artwork": "ArtworkWorker",
        "lyrics": "LyricsWorker",
        "metadata": "MetadataWorker",
        "sync": "SyncWorker",
        "retry_scheduler": "RetryScheduler",
        "matching": "MatchingWorker",
        "playlist_sync": "PlaylistSyncWorker",
        "backfill": "BackfillWorker",
        "watchlist": "WatchlistWorker",
    }

    def __init__(self) -> None:
        self.scenarios: Dict[str, WorkerScenario] = {
            name: WorkerScenario() for name in self.WORKER_ATTRIBUTES
        }
        self.instances: Dict[str, list[RecordingWorker]] = defaultdict(list)
        self.log_events: list[Dict[str, Any]] = []

    def register(self, name: str, worker: RecordingWorker) -> None:
        self.instances[name].append(worker)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app import main as app_main

        class _BackfillServiceStub:
            def __init__(self, *args, **kwargs) -> None:  # noqa: D401 - simple stub
                self.args = args
                self.kwargs = kwargs

        monkeypatch.setattr(app_main, "BackfillService", _BackfillServiceStub)

        for logical_name, attribute in self.WORKER_ATTRIBUTES.items():
            scenario = self.scenarios[logical_name]

            def _make_worker(name: str, behaviour: WorkerScenario) -> type[RecordingWorker]:
                registry = self

                class _Worker(RecordingWorker):
                    def __init__(self, *args, **kwargs) -> None:
                        super().__init__(name=name, scenario=behaviour, registry=registry)

                _Worker.__name__ = f"{name.title()}WorkerStub"
                return _Worker

            monkeypatch.setattr(app_main, attribute, _make_worker(logical_name, scenario))

        monkeypatch.setattr("app.main.get_spotify_client", lambda: object())
        monkeypatch.setattr("app.main.get_soulseek_client", lambda: object())
        monkeypatch.setattr("app.main.get_matching_engine", lambda: object())

    def all_workers(self) -> Iterable[RecordingWorker]:
        for workers in self.instances.values():
            yield from workers


@pytest.fixture
def worker_registry(monkeypatch: pytest.MonkeyPatch) -> WorkerRegistry:
    registry = WorkerRegistry()
    registry.install(monkeypatch)
    return registry
