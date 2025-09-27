from __future__ import annotations

from typing import Any

import importlib

system_router_module = importlib.import_module("app.routers.system_router")


def test_status_endpoint_reports_workers(client) -> None:
    response = client.get("/status")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "ok"
    assert "uptime_seconds" in payload
    assert "version" in payload

    workers = payload["workers"]
    assert isinstance(workers, dict)
    assert "sync" in workers
    assert "matching" in workers
    assert "artwork" in workers


def test_system_stats_endpoint_uses_psutil(monkeypatch, client) -> None:
    class DummyStats:
        def __init__(self, **values: Any) -> None:
            self.__dict__.update(values)

    class DummyPsutil:
        @staticmethod
        def cpu_times_percent(interval=None, percpu=False):  # type: ignore[override]
            return DummyStats(idle=70.0, user=20.0, system=10.0)

        @staticmethod
        def virtual_memory():
            return DummyStats(total=8, available=4, percent=50.0, used=3, free=1)

        @staticmethod
        def disk_usage(path):
            assert path == "/"
            return DummyStats(total=100, used=40, free=60, percent=40.0)

        @staticmethod
        def net_io_counters():
            return DummyStats(bytes_sent=1, bytes_recv=2, packets_sent=3, packets_recv=4)

        @staticmethod
        def cpu_percent(interval=None):  # type: ignore[override]
            return 30.0

        @staticmethod
        def cpu_count(logical=True):  # type: ignore[override]
            return 8

    monkeypatch.setattr(system_router_module, "psutil", DummyPsutil)

    response = client.get("/system/stats")
    assert response.status_code == 200

    stats = response.json()
    assert stats["cpu"]["percent"] == 30.0
    assert stats["memory"]["total"] == 8
    assert stats["disk"]["free"] == 60
    assert stats["network"]["bytes_recv"] == 2
