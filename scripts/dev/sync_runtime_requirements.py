#!/usr/bin/env python3
"""Keep ``requirements.txt`` aligned with ``pyproject.toml`` runtime dependencies."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
import sys
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
REQUIREMENTS_PATH = REPO_ROOT / "requirements.txt"
DEFAULT_HEADER = ("# Runtime dependencies for Harmony backend",)


@dataclass(frozen=True)
class Dependency:
    """Canonical representation of a pinned dependency."""

    canonical_name: str
    requirement: Requirement
    raw: str


class DependencySyncError(RuntimeError):
    """Raised when requirements drift from the project configuration."""


def _load_pyproject_dependencies(path: Path) -> list[Dependency]:
    if not path.exists():
        raise DependencySyncError(f"Missing pyproject file at {path}")

    data = tomllib.loads(path.read_text("utf-8"))
    try:
        dependency_strings: Sequence[str] = data["project"]["dependencies"]
    except KeyError as exc:  # pragma: no cover - configuration errors are fatal
        raise DependencySyncError(
            "[project] dependencies not configured in pyproject.toml"
        ) from exc

    entries: list[Dependency] = []
    seen: set[str] = set()
    for raw in dependency_strings:
        requirement = Requirement(raw)
        specifiers = list(requirement.specifier)
        if len(specifiers) != 1 or specifiers[0].operator != "==":
            raise DependencySyncError(
                "Dependency "
                f"'{requirement.name}' must be pinned with '=='; "
                f"found '{requirement.specifier}'."
            )
        canonical = canonicalize_name(requirement.name)
        if canonical in seen:
            raise DependencySyncError(
                f"Duplicate dependency '{requirement.name}' in pyproject.toml."
            )
        seen.add(canonical)
        entries.append(
            Dependency(canonical_name=canonical, requirement=requirement, raw=str(requirement))
        )
    return entries


def _split_header(lines: Sequence[str]) -> tuple[list[str], list[str]]:
    header: list[str] = []
    body_start = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or stripped == "":
            header.append(line)
            body_start = index + 1
            continue
        break
    body = [line for line in lines[body_start:] if line.strip()]
    return header, body


def _load_requirements(path: Path) -> tuple[list[str], dict[str, Requirement]]:
    if not path.exists():
        return list(DEFAULT_HEADER), {}

    lines = path.read_text("utf-8").splitlines()
    header, body = _split_header(lines)

    requirements: dict[str, Requirement] = {}
    for raw in body:
        candidate = raw.split("#", 1)[0].strip()
        if not candidate:
            continue
        requirement = Requirement(candidate)
        canonical = canonicalize_name(requirement.name)
        if canonical in requirements:
            raise DependencySyncError(
                f"Duplicate dependency '{requirement.name}' in requirements.txt."
            )
        requirements[canonical] = requirement
    return header or list(DEFAULT_HEADER), requirements


def _generate_requirements_content(
    header: Iterable[str], dependencies: Sequence[Dependency]
) -> str:
    lines = list(header)
    if lines and lines[-1].strip():
        lines.append("")
    for dependency in dependencies:
        lines.append(str(dependency.requirement))
    return "\n".join(lines) + "\n"


def _diff_message(dependencies: Sequence[Dependency], requirements: dict[str, Requirement]) -> str:
    errors: list[str] = []
    expected = {dependency.canonical_name: dependency for dependency in dependencies}
    found_names = set(requirements)
    expected_names = set(expected)

    missing = sorted(expected_names - found_names)
    if missing:
        errors.append("Missing from requirements.txt: " + ", ".join(missing))

    extra = sorted(found_names - expected_names)
    if extra:
        errors.append("Unexpected entries in requirements.txt: " + ", ".join(extra))

    for name in sorted(expected_names & found_names):
        expected_spec = str(expected[name].requirement.specifier)
        current_spec = str(requirements[name].specifier)
        if expected_spec != current_spec:
            errors.append(
                "Version mismatch for "
                f"{name}: expected '{expected_spec}' but found "
                f"'{current_spec}' in requirements.txt."
            )
    if not errors:
        errors.append("requirements.txt ordering or formatting differs from pyproject.toml")
    return "\n".join(errors)


def sync_dependencies(*, check_only: bool) -> None:
    dependencies = _load_pyproject_dependencies(PYPROJECT_PATH)
    header, requirements = _load_requirements(REQUIREMENTS_PATH)
    desired = _generate_requirements_content(header, dependencies)

    if check_only:
        current = REQUIREMENTS_PATH.read_text("utf-8") if REQUIREMENTS_PATH.exists() else ""
        if current != desired:
            message = _diff_message(dependencies, requirements)
            raise DependencySyncError(
                message + "\nRun 'python scripts/dev/sync_runtime_requirements.py --write' "
                "to update requirements.txt."
            )
        return

    REQUIREMENTS_PATH.write_text(desired, encoding="utf-8")
    print("[dep-sync] Updated requirements.txt from pyproject.toml", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Validate that requirements.txt matches the pyproject dependencies "
            "without modifying files."
        ),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Rewrite requirements.txt to mirror the pyproject dependencies.",
    )
    args = parser.parse_args(argv)

    if args.check and args.write:
        parser.error("--check and --write are mutually exclusive")

    check_only = args.check and not args.write
    write = args.write or not args.check

    try:
        sync_dependencies(check_only=check_only)
    except DependencySyncError as exc:
        print(f"Dependency sync failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - defensive guard
        print(f"Unexpected error while syncing dependencies: {exc}", file=sys.stderr)
        return 1

    if write:
        return 0
    return 0


if __name__ == "__main__":  # pragma: no cover - script entrypoint
    sys.exit(main())
