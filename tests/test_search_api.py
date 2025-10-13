from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.search import router as search_router
from app.dependencies import get_integration_service, get_matching_engine
from app.middleware.errors import setup_exception_handlers
from app.schemas.errors import ApiError, ErrorCode
from app.services.errors import ServiceError


class StubIntegrationService:
    def __init__(self, api_error: ApiError) -> None:
        self._api_error = api_error

    async def search_providers(self, providers: list[str], query: object) -> object:
        raise ServiceError(self._api_error)


class StubMatchingEngine:
    def compute_relevance_score(self, query: str, payload: dict[str, object]) -> float:
        return 0.0


def _create_app(service: StubIntegrationService, matching_engine: StubMatchingEngine) -> FastAPI:
    app = FastAPI()
    setup_exception_handlers(app)
    app.include_router(search_router)
    app.dependency_overrides[get_integration_service] = lambda: service
    app.dependency_overrides[get_matching_engine] = lambda: matching_engine
    return app


def test_smart_search_returns_service_error_payload() -> None:
    api_error = ApiError.from_components(
        code=ErrorCode.DEPENDENCY_ERROR,
        message="Requested search source is not available.",
        details={"provider": "spotify"},
    )
    service = StubIntegrationService(api_error)
    matching_engine = StubMatchingEngine()
    app = _create_app(service, matching_engine)
    client = TestClient(app)

    response = client.post("/search", json={"query": "test"})

    assert response.status_code == 503
    payload = response.json()
    assert payload == {
        "ok": False,
        "error": {
            "code": "DEPENDENCY_ERROR",
            "message": "Requested search source is not available.",
            "meta": {"provider": "spotify"},
        },
    }
