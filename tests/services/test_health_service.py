"""Tests for :mod:`app.services.health` dependency status normalisation."""

from __future__ import annotations

import pytest

from app.services.health import DependencyStatus, HealthService


@pytest.mark.parametrize(
    "value, expected",
    [
        (
            DependencyStatus(ok=True, status=" Ready "),
            DependencyStatus(ok=True, status="ready"),
        ),
        (
            DependencyStatus(ok=False, status="  "),
            DependencyStatus(ok=False, status="down"),
        ),
        (
            DependencyStatus(ok=True, status=""),
            DependencyStatus(ok=True, status="up"),
        ),
    ],
)
def test_normalise_dependency_status_existing_objects(
    value: DependencyStatus, expected: DependencyStatus
) -> None:
    """Existing :class:`DependencyStatus` instances are normalised consistently."""

    normalised = HealthService._normalise_dependency_status(value)

    assert normalised == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("up", DependencyStatus(ok=True, status="up")),
        (" disabled ", DependencyStatus(ok=True, status="disabled")),
        ("error", DependencyStatus(ok=False, status="error")),
        ("   ", DependencyStatus(ok=False, status="down")),
    ],
)
def test_normalise_dependency_status_strings(value: str, expected: DependencyStatus) -> None:
    """String inputs are mapped onto standardised dependency status results."""

    normalised = HealthService._normalise_dependency_status(value)

    assert normalised == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        (True, DependencyStatus(ok=True, status="up")),
        (False, DependencyStatus(ok=False, status="down")),
        (1, DependencyStatus(ok=True, status="up")),
        (0, DependencyStatus(ok=False, status="down")),
    ],
)
def test_normalise_dependency_status_truthy_values(
    value: bool | int, expected: DependencyStatus
) -> None:
    """Non-string, non-status inputs rely on their truthiness when normalising."""

    normalised = HealthService._normalise_dependency_status(value)

    assert normalised == expected
