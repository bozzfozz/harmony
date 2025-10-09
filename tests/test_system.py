from __future__ import annotations

from typing import Any

from app.api import system as system_router_module


class DummyStats:
    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)


class DummyPsutil:
    def __init__(self, cpu_percent_value: float) -> None:
        self._cpu_percent_value = cpu_percent_value

    def cpu_times_percent(self, interval=None, percpu=False):  # type: ignore[override]
        return DummyStats(idle=70.0, user=20.0, system=10.0)

    def virtual_memory(self):
        return DummyStats(total=8, available=4, percent=50.0, used=3, free=1)

    def disk_usage(self, path):
        assert path == "/"
        return DummyStats(total=100, used=40, free=60, percent=40.0)

    def net_io_counters(self):
        return DummyStats(bytes_sent=1, bytes_recv=2, packets_sent=3, packets_recv=4)

    def cpu_percent(self, interval=None):  # type: ignore[override]
        return self._cpu_percent_value

    def cpu_count(self, logical=True):  # type: ignore[override]
        return 8


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
    module_dummy = DummyPsutil(30.0)

    monkeypatch.setattr(system_router_module, "psutil", module_dummy)

    response = client.get("/system/stats")
    assert response.status_code == 200

    stats = response.json()
    assert stats["cpu"]["percent"] == 30.0
    assert stats["memory"]["total"] == 8
    assert stats["disk"]["free"] == 60
    assert stats["network"]["bytes_recv"] == 2


def test_system_stats_endpoint_uses_app_state_psutil_override(
    monkeypatch, client
) -> None:
    module_dummy = DummyPsutil(20.0)
    state_dummy = DummyPsutil(45.0)

    monkeypatch.setattr(system_router_module, "psutil", module_dummy)
    monkeypatch.setattr(client.app.state, "psutil", state_dummy, raising=False)

    response = client.get("/system/stats")
    assert response.status_code == 200

    stats = response.json()
    assert stats["cpu"]["percent"] == 45.0


def test_system_stats_endpoint_uses_dependency_override_psutil(
    monkeypatch, client
) -> None:
    module_dummy = DummyPsutil(10.0)
    override_dummy = DummyPsutil(55.0)

    monkeypatch.setattr(system_router_module, "psutil", module_dummy)
    monkeypatch.setitem(
        client.app.dependency_overrides,
        system_router_module._resolve_psutil,
        lambda request: override_dummy,
    )

    response = client.get("/system/stats")
    assert response.status_code == 200

    stats = response.json()
    assert stats["cpu"]["percent"] == 55.0
