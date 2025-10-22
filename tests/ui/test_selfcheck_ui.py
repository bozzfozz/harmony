"""Tests for UI readiness probes covering required assets."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ops import selfcheck_ui


def _write_required_files(root: Path) -> Path:
    templates_root = root / "templates"
    static_root = root / "static"

    for relative in selfcheck_ui.REQUIRED_TEMPLATE_FILES:
        target = templates_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("template", encoding="utf-8")

    for relative in selfcheck_ui.REQUIRED_STATIC_ASSETS:
        target = static_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("asset", encoding="utf-8")

    return root


def test_probe_ui_artifacts_ok_when_all_required_assets_exist(tmp_path: Path) -> None:
    ui_root = _write_required_files(tmp_path / "ui")

    ok, details = selfcheck_ui.probe_ui_artifacts(ui_root)

    assert ok is True
    assert details["status"] == "ok"
    assert not details["templates"]["missing"]
    assert not details["static"]["missing"]


@pytest.mark.parametrize(
    ("category", "relative_path"),
    [
        pytest.param("page", "pages/operations.j2", id="missing-page"),
        pytest.param("partial", "partials/spotify_status.j2", id="missing-partial"),
        pytest.param("static", "js/ui-bootstrap.js", id="missing-static"),
    ],
)
def test_probe_ui_artifacts_reports_missing_required_assets(
    tmp_path: Path,
    category: str,
    relative_path: str,
) -> None:
    ui_root = _write_required_files(tmp_path / "ui")

    if category == "static":
        target = ui_root / "static" / relative_path
    else:
        target = ui_root / "templates" / relative_path
    target.unlink()

    ok, details = selfcheck_ui.probe_ui_artifacts(ui_root)

    assert ok is False
    assert details["status"] == "fail"

    if category == "static":
        missing = details["static"]["missing"]
    else:
        missing = details["templates"]["missing"]

    assert relative_path in missing
