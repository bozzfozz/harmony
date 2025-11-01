from __future__ import annotations

import pytest


def _install_entrypoint(monkeypatch: pytest.MonkeyPatch):
    # Import lazily to avoid mutating global state in unrelated tests.
    import app.runtime.container_entrypoint as entrypoint

    def _patch_os(fake_os):
        monkeypatch.setattr(entrypoint, "os", fake_os)

    return entrypoint, _patch_os


def test_drop_privileges_switches_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    entrypoint, patch_os = _install_entrypoint(monkeypatch)

    class _FakeOS:
        def __init__(self) -> None:
            self.uid = 0
            self.gid = 0
            self.groups: list[int] = []

        def getuid(self) -> int:
            return self.uid

        def getgid(self) -> int:
            return self.gid

        def setuid(self, value: int) -> None:
            self.uid = value

        def setgid(self, value: int) -> None:
            self.gid = value

        def setgroups(self, values: list[int]) -> None:
            self.groups = values

    fake_os = _FakeOS()
    patch_os(fake_os)
    monkeypatch.setattr(entrypoint, "log_info", lambda *args, **kwargs: None)

    entrypoint.drop_privileges(target_uid=1000, target_gid=1000)

    assert fake_os.uid == 1000
    assert fake_os.gid == 1000
    assert fake_os.groups == [1000]


def test_drop_privileges_requires_root(monkeypatch: pytest.MonkeyPatch) -> None:
    entrypoint, patch_os = _install_entrypoint(monkeypatch)

    class _FakeOS:
        def __init__(self) -> None:
            self.uid = 200
            self.gid = 200

        def getuid(self) -> int:
            return self.uid

        def getgid(self) -> int:
            return self.gid

    fake_os = _FakeOS()
    patch_os(fake_os)

    with pytest.raises(entrypoint.EntrypointError) as exc_info:
        entrypoint.drop_privileges(target_uid=1000, target_gid=1000)

    assert "insufficient permissions" in str(exc_info.value)
