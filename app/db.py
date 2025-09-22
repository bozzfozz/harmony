"""Compatibility wrapper exposing the database helpers."""

from backend.app.db import Base, DATABASE_URL, SessionLocal, engine, get_db, init_db

__all__ = [
    "Base",
    "DATABASE_URL",
    "SessionLocal",
    "engine",
    "get_db",
    "init_db",
]
