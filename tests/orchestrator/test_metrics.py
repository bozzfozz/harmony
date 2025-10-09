from __future__ import annotations

import importlib
import random
from datetime import datetime

import pytest

from app.models import QueueJobStatus
from app.utils import metrics
from app.workers.persistence import QueueJobDTO


def _collect_metric_samples() -> dict[tuple[str, tuple[tuple[str, str], ...]], float]:
    registry = metrics.get_registry()
    samples: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
    for metric in registry.collect():
        for sample in metric.samples:
            labels = tuple(sorted(sample.labels.items()))
            samples[(sample.name, labels)] = sample.value
    return samples


@pytest.mark.asyncio()
async def test_artist_scan_records_missing_metrics() -> None:
    from app import orchestrator as orchestrator_pkg

    metrics.reset_registry()
    handlers = importlib.reload(orchestrator_pkg.handlers)

    job = QueueJobDTO(
        id=1,
        type=handlers.ARTIST_SCAN_JOB_TYPE,
        payload={"artist_id": 321},
        priority=0,
        attempts=1,
        available_at=datetime.utcnow(),
        lease_expires_at=None,
        status=QueueJobStatus.PENDING,
        idempotency_key=None,
    )

    class StubDao:
        @staticmethod
        def get_artist(artist_id: int) -> None:
            return None

    class StubDeps:
        def __init__(self) -> None:
            self.dao = StubDao()
            self.db_mode = "thread"
            self.retry_budget = 1
            self.now_factory = datetime.utcnow
            self.cooldown_minutes = 0
            self.backoff_base_ms = 0
            self.jitter_pct = 0.0
            self.retry_max = 1
            self.rng = random.Random()
            self.cache_service = None

    result = await handlers.artist_scan(job, StubDeps())
    assert result["status"] == "missing"

    samples = _collect_metric_samples()
    assert samples[("artist_scan_outcomes_total", (("status", "missing"),))] == 1.0
    assert samples[("artist_scan_duration_seconds_count", ())] == 1.0


@pytest.mark.asyncio()
async def test_artist_refresh_records_missing_metrics() -> None:
    from app import orchestrator as orchestrator_pkg

    metrics.reset_registry()
    handlers = importlib.reload(orchestrator_pkg.handlers)

    job = QueueJobDTO(
        id=2,
        type=handlers.ARTIST_REFRESH_JOB_TYPE,
        payload={"artist_id": 987},
        priority=0,
        attempts=0,
        available_at=datetime.utcnow(),
        lease_expires_at=None,
        status=QueueJobStatus.PENDING,
        idempotency_key=None,
    )

    class StubDao:
        @staticmethod
        def get_artist(artist_id: int) -> None:
            return None

    class StubDeps:
        def __init__(self) -> None:
            self.dao = StubDao()
            self.retry_budget = 1
            self.now_factory = datetime.utcnow
            self.delta_priority = 0
            self.cache_service = None

    result = await handlers.artist_refresh(job, StubDeps())
    assert result["status"] == "missing"

    samples = _collect_metric_samples()
    assert samples[("artist_refresh_outcomes_total", (("status", "missing"),))] == 1.0
    assert samples[("artist_refresh_duration_seconds_count", ())] == 1.0
