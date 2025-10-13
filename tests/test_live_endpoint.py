from fastapi.routing import APIRoute
import pytest

from app.api import health as health_api
from app.main import app, live_probe


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_health_live_endpoint_returns_ok() -> None:
    result = await health_api.live()
    assert result == {"status": "ok"}


@pytest.mark.anyio
async def test_live_probe_returns_ok() -> None:
    payload = await live_probe()

    assert payload == {"status": "ok"}


def test_live_route_registered_without_prefix() -> None:
    routes = [route for route in app.routes if isinstance(route, APIRoute)]
    live_routes = [route for route in routes if route.path == "/live"]
    assert live_routes, "Expected /live route to be registered"
    for route in live_routes:
        assert "GET" in route.methods
        assert route.include_in_schema is False
