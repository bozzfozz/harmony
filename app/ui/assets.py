from __future__ import annotations

from functools import lru_cache
import hashlib
from pathlib import Path

_STATIC_DIR = Path(__file__).resolve().parent / "static"
_STATIC_URL_PREFIX = "/ui/static"


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()[:12]


def _normalise_asset_path(path: str) -> str:
    stripped = path.lstrip("/")
    return stripped


@lru_cache(maxsize=1)
def _asset_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    if not _STATIC_DIR.exists():
        return versions
    for file_path in _STATIC_DIR.rglob("*"):
        if not file_path.is_file():
            continue
        relative_path = file_path.relative_to(_STATIC_DIR).as_posix()
        versions[relative_path] = _hash_file(file_path)
    return versions


def get_asset_version(path: str) -> str:
    normalised = _normalise_asset_path(path)
    versions = _asset_versions()
    try:
        return versions[normalised]
    except KeyError as exc:  # pragma: no cover - configuration error guard
        raise FileNotFoundError(f"Static asset '{path}' is not bundled") from exc


def asset_url(path: str) -> str:
    normalised = _normalise_asset_path(path)
    version = get_asset_version(normalised)
    return f"{_STATIC_URL_PREFIX}/{normalised}?v={version}"


__all__ = ["asset_url", "get_asset_version"]
