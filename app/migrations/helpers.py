"""Utility helpers shared across Alembic migrations.

The helpers in this module provide defensive guards that keep migrations
idempotent when schema objects already exist. They intentionally avoid Alembic
internals so that they can be imported directly from revision scripts without
introducing circular dependencies.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import Connection, Inspector


def get_inspector(connection: Connection | None = None) -> Inspector:
    """Return a SQLAlchemy inspector for the given (or current) connection."""

    bind = connection if connection is not None else op.get_bind()
    return sa.inspect(bind)


def has_table(inspector: Inspector, table_name: str) -> bool:
    """Return ``True`` when *table_name* exists in the current schema."""

    return table_name in inspector.get_table_names()


def column_map(inspector: Inspector, table_name: str) -> dict[str, dict[str, Any]]:
    """Return the reflected column metadata keyed by column name."""

    return {column["name"]: column for column in inspector.get_columns(table_name)}


def has_column(inspector: Inspector, table_name: str, column_name: str) -> bool:
    """Return ``True`` when *column_name* exists on *table_name*."""

    if not has_table(inspector, table_name):
        return False
    return column_name in column_map(inspector, table_name)


def index_names(inspector: Inspector, table_name: str) -> set[str]:
    """Return the set of index names defined on *table_name*."""

    if not has_table(inspector, table_name):
        return set()
    return {index["name"] for index in inspector.get_indexes(table_name)}


def has_index(inspector: Inspector, table_name: str, index_name: str) -> bool:
    """Return ``True`` when *index_name* exists on *table_name*."""

    return index_name in index_names(inspector, table_name)


def unique_constraint_names(inspector: Inspector, table_name: str) -> set[str]:
    """Return the set of unique constraint names defined on *table_name*."""

    if not has_table(inspector, table_name):
        return set()
    return {
        constraint["name"]
        for constraint in inspector.get_unique_constraints(table_name)
        if constraint.get("name")
    }


def has_unique_constraint(inspector: Inspector, table_name: str, constraint_name: str) -> bool:
    """Return ``True`` when *constraint_name* exists on *table_name*."""

    return constraint_name in unique_constraint_names(inspector, table_name)


def drop_index_if_exists(inspector: Inspector, table_name: str, index_name: str) -> None:
    """Drop *index_name* if it exists on *table_name*."""

    if has_index(inspector, table_name, index_name):
        op.drop_index(index_name, table_name=table_name)


def drop_unique_constraint_if_exists(
    inspector: Inspector, table_name: str, constraint_name: str
) -> None:
    """Drop *constraint_name* if it exists on *table_name*."""

    if has_unique_constraint(inspector, table_name, constraint_name):
        op.drop_constraint(constraint_name, table_name, type_="unique")


def create_index_if_missing(
    inspector: Inspector,
    table_name: str,
    index_name: str,
    columns: Iterable[str],
    *,
    unique: bool = False,
    **kwargs: Any,
) -> None:
    """Create *index_name* if it does not already exist."""

    if not has_index(inspector, table_name, index_name):
        op.create_index(index_name, table_name, list(columns), unique=unique, **kwargs)


def create_unique_constraint_if_missing(
    inspector: Inspector,
    table_name: str,
    constraint_name: str,
    columns: Iterable[str],
) -> None:
    """Create *constraint_name* if it does not already exist."""

    if not has_unique_constraint(inspector, table_name, constraint_name):
        op.create_unique_constraint(constraint_name, table_name, list(columns))


__all__ = [
    "column_map",
    "create_index_if_missing",
    "create_unique_constraint_if_missing",
    "drop_index_if_exists",
    "drop_unique_constraint_if_exists",
    "get_inspector",
    "has_column",
    "has_index",
    "has_table",
    "has_unique_constraint",
    "index_names",
    "unique_constraint_names",
]
