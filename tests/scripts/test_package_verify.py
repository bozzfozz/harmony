from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from scripts.dev import package_verify


def _create_artifacts(root: Path) -> None:
    (root / "build").mkdir(exist_ok=True)
    (root / "dist").mkdir(exist_ok=True)
    (root / "example.egg-info").mkdir(exist_ok=True)


def test_run_pipeline_cleans_between_steps(tmp_path: Path) -> None:
    commands = (("cmd1",), ("cmd2",))
    observed: list[tuple[str, ...]] = []

    _create_artifacts(tmp_path)

    def runner(command: tuple[str, ...], root: Path) -> None:
        observed.append(command)
        assert root == tmp_path
        assert not (root / "build").exists()
        assert not (root / "dist").exists()
        assert not list(root.glob("*.egg-info"))
        if len(observed) < len(commands):
            _create_artifacts(root)

    package_verify.run_pipeline(tmp_path, commands=commands, runner=runner)

    assert observed == list(commands)


def test_run_pipeline_stops_after_failure(tmp_path: Path) -> None:
    commands = (("cmd1",), ("cmd2",), ("cmd3",))
    observed: list[tuple[str, ...]] = []

    _create_artifacts(tmp_path)

    def failing_runner(command: tuple[str, ...], root: Path) -> None:
        observed.append(command)
        assert not (root / "build").exists()
        assert not (root / "dist").exists()
        assert not list(root.glob("*.egg-info"))
        if len(observed) == 2:
            raise subprocess.CalledProcessError(returncode=1, cmd=command)
        _create_artifacts(root)

    with pytest.raises(subprocess.CalledProcessError):
        package_verify.run_pipeline(tmp_path, commands=commands, runner=failing_runner)

    assert observed == [("cmd1",), ("cmd2",)]
