"""Regression tests for the Harmony version constant."""

from app.main import app
from app.version import __version__


def test_app_version_matches_constant() -> None:
    """Ensure the FastAPI application exposes the packaged version."""

    assert app.version == __version__ == "1.0.0"
