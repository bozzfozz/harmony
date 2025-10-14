from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("SLSKD_API_KEY", "test-key")

from app.main import FRONTEND_DIST, app


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _html_files() -> list[Path]:
    return sorted(path for path in FRONTEND_DIST.glob("*.html") if path.is_file())


@pytest.mark.parametrize("html_file", [path.name for path in _html_files()])
def test_frontend_html_files_available_with_extension(
    client: TestClient, html_file: str
) -> None:
    response = client.get(f"/{html_file}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


@pytest.mark.parametrize(
    "html_file",
    [path for path in _html_files() if path.stem != "index"],
)
def test_frontend_html_files_available_without_extension(
    client: TestClient, html_file: Path
) -> None:
    response = client.get(f"/{html_file.stem}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_frontend_fallback_serves_dashboard(client: TestClient) -> None:
    dashboard = client.get("/")
    assert dashboard.status_code == 200

    response = client.get("/missing-page", headers={"accept": "text/html"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.content == dashboard.content


def test_api_404_remains_json_response(client: TestClient) -> None:
    api_base = getattr(app.state, "api_base_path", "") or ""
    if not api_base:
        pytest.skip("API base path is not configured")
    if not api_base.startswith("/"):
        api_base = f"/{api_base}"

    response = client.get(f"{api_base}/__missing__")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert isinstance(payload, dict)
    error_payload = payload.get("error")
    assert isinstance(error_payload, dict)
    assert error_payload.get("code")


def test_openapi_document_available(client: TestClient) -> None:
    response = client.get(app.openapi_url)
    assert response.status_code == 200
