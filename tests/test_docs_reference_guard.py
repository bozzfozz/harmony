"""Tests for :mod:`scripts.docs_reference_guard`."""

from __future__ import annotations

import scripts.docs_reference_guard as guard


def test_default_paths_include_core_docs() -> None:
    """The default path list should include the curated core documents."""

    paths = set(guard._default_paths())  # type: ignore[attr-defined]

    expected_paths = {
        guard.REPO_ROOT / "README.md",
        guard.REPO_ROOT / "CHANGELOG.md",
        guard.REPO_ROOT / "docs" / "overview.md",
        guard.REPO_ROOT / "docs" / "architecture.md",
        guard.REPO_ROOT / "docs" / "observability.md",
        guard.REPO_ROOT / "docs" / "security.md",
    }

    missing = expected_paths.difference(paths)
    assert not missing, f"core docs missing from default guard set: {sorted(missing)}"


def test_main_reports_missing_reference(tmp_path, monkeypatch, capsys) -> None:
    """The CLI should exit with failure when a broken link is detected."""

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    doc_path = repo_root / "doc.md"
    doc_path.write_text("[missing](docs/missing.md)\n", encoding="utf-8")

    monkeypatch.setattr(guard, "REPO_ROOT", repo_root)

    exit_code = guard.main([str(doc_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "missing link" in captured.err
    assert "docs/missing.md" in captured.err


def test_main_succeeds_when_all_links_exist(tmp_path, monkeypatch, capsys) -> None:
    """The CLI should succeed when all references resolve to real files."""

    repo_root = tmp_path / "repo"
    docs_dir = repo_root / "docs"
    docs_dir.mkdir(parents=True)
    target = docs_dir / "target.md"
    target.write_text("ok\n", encoding="utf-8")

    doc_path = repo_root / "doc.md"
    doc_path.write_text("[ok](docs/target.md)\n", encoding="utf-8")

    monkeypatch.setattr(guard, "REPO_ROOT", repo_root)

    exit_code = guard.main([str(doc_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "all references resolved" in captured.out
