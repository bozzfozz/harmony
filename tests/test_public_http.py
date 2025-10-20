from collections.abc import Iterator
import os

from fastapi.testclient import TestClient
import pytest

os.environ.setdefault("SLSKD_API_KEY", "test-key")

from app.main import app  # noqa: E402  pylint: disable=wrong-import-position
from app.ui.assets import asset_url


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def test_openapi_document_available(client: TestClient) -> None:
    response = client.get(app.openapi_url)
    assert response.status_code == 200


def test_html_404_returns_json_payload(client: TestClient) -> None:
    response = client.get("/missing-page", headers={"accept": "text/html"})
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert payload.get("ok") is False
    assert payload.get("error")


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


def test_ui_static_assets_are_versioned_and_cached(client: TestClient) -> None:
    url = asset_url("css/app.css")
    assert "?v=" in url

    response = client.get(url)

    assert response.status_code == 200
    assert response.headers.get("cache-control") == "max-age=86400, immutable"
