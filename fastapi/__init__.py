from __future__ import annotations

from typing import Any, Callable, List, Tuple


class HTTPException(Exception):
    def __init__(self, status_code: int, detail: str | None = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class APIRouter:
    def __init__(self) -> None:
        self.routes: List[Tuple[str, str, Callable[..., Any]]] = []

    def delete(self, path: str, **_kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.routes.append(("DELETE", path, func))
            return func

        return decorator

    def post(self, path: str, **_kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.routes.append(("POST", path, func))
            return func

        return decorator

    def get(self, path: str, **_kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.routes.append(("GET", path, func))
            return func

        return decorator


def Query(default: Any = None, **_kwargs: Any) -> Any:  # pragma: no cover - simple helper
    return default


class FastAPI:
    def __init__(self) -> None:
        self.routers: List[APIRouter] = []

    def include_router(self, router: APIRouter) -> None:
        self.routers.append(router)

    def get(self, path: str, **_kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            return func

        return decorator

    def post(self, path: str, **_kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            return func

        return decorator


__all__ = [
    "APIRouter",
    "FastAPI",
    "HTTPException",
    "Query",
]
