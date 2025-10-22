"""Tests for `app.utils.path_safety`."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.utils.path_safety import ensure_within_roots, normalise_download_path


@pytest.fixture
def allowed_roots(tmp_path: Path) -> tuple[Path, ...]:
    root = tmp_path / "downloads"
    root.mkdir(exist_ok=True)
    return (root,)


def test_normalise_download_path_resolves_under_allowed_root(
    allowed_roots: tuple[Path, ...],
) -> None:
    relative_name = "album/track.mp3"

    result = normalise_download_path(relative_name, allowed_roots=allowed_roots)

    expected = (allowed_roots[0] / relative_name).resolve(strict=False)
    assert result == expected


@pytest.mark.parametrize(
    "raw, message",
    [
        ("", "filename must not be empty"),
        ("/absolute/path", "absolute paths are not allowed"),
        ("C:\\songs\\track.mp3", "drive-qualified paths are not allowed"),
        ("../escape.mp3", "parent directory segments are not allowed"),
    ],
)
def test_normalise_download_path_rejects_invalid_inputs(
    raw: str, message: str, allowed_roots: tuple[Path, ...]
) -> None:
    with pytest.raises(ValueError, match=message):
        normalise_download_path(raw, allowed_roots=allowed_roots)


def test_ensure_within_roots_allows_path_inside_roots(allowed_roots: tuple[Path, ...]) -> None:
    target = allowed_roots[0] / "mix" / "set.flac"

    result = ensure_within_roots(str(target), allowed_roots=allowed_roots)

    assert result == target.resolve(strict=False)


def test_ensure_within_roots_rejects_path_outside_roots(
    tmp_path: Path, allowed_roots: tuple[Path, ...]
) -> None:
    outside = tmp_path / "outside" / "sneaky.mp3"

    with pytest.raises(ValueError, match="path escapes configured download roots"):
        ensure_within_roots(outside, allowed_roots=allowed_roots)
