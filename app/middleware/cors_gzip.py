"""CORS and compression middleware helpers."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.config import CorsMiddlewareConfig, GZipMiddlewareConfig


def install_cors_and_gzip(
    app: FastAPI,
    *,
    cors: CorsMiddlewareConfig,
    gzip: GZipMiddlewareConfig,
) -> None:
    """Register CORS and GZip middleware using the provided configuration."""

    allow_origins = list(cors.allowed_origins) or ["*"]
    allow_headers = list(cors.allowed_headers) or ["*"]
    allow_methods = list(cors.allowed_methods) or ["*"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_methods=allow_methods,
        allow_headers=allow_headers,
        allow_credentials=False,
        expose_headers=["X-Request-ID"],
    )

    app.add_middleware(GZipMiddleware, minimum_size=max(0, gzip.min_size))


__all__ = ["install_cors_and_gzip"]
