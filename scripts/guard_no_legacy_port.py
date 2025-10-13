#!/usr/bin/env python3
"""Fail the build if legacy port references remain in critical paths."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
import sys

TARGET_DIRS: tuple[Path, ...] = (
    Path(".github/workflows"),
    Path("scripts"),
    Path("docs"),
)
LEGACY_PORTS: tuple[int, ...] = (8 * 1000, 5 * 1000 + 432)
LEGACY_TOKENS: tuple[str, ...] = tuple(f":{port}" for port in LEGACY_PORTS)
EXIT_CODE_LEGACY = 4
SELF_PATH = Path(__file__).resolve()


@dataclass
class Violation:
    path: Path
    line_number: int
    line_content: str


def find_violations(base_dirs: Iterable[Path]) -> list[Violation]:
    violations: list[Violation] = []
    for base_dir in base_dirs:
        if not base_dir.exists():
            continue
        for candidate in sorted(base_dir.rglob("*")):
            if not candidate.is_file():
                continue
            try:
                if candidate.resolve() == SELF_PATH:
                    continue
            except FileNotFoundError:
                continue
            try:
                text = candidate.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                if any(token in line for token in LEGACY_TOKENS):
                    violations.append(
                        Violation(
                            path=candidate,
                            line_number=line_number,
                            line_content=line.strip(),
                        )
                    )
    return violations


def main() -> int:
    violations = find_violations(TARGET_DIRS)
    if not violations:
        print("No legacy port references found in guarded paths.")
        return 0

    joined_tokens = ", ".join(LEGACY_TOKENS)
    print(f"Legacy port references detected ({joined_tokens}):", file=sys.stderr)
    for violation in violations:
        print(
            f"  {violation.path}:{violation.line_number}: {violation.line_content}",
            file=sys.stderr,
        )
    print(
        "Failing guard: replace legacy ports with the canonical configuration before retrying.",
        file=sys.stderr,
    )
    return EXIT_CODE_LEGACY


if __name__ == "__main__":
    sys.exit(main())
