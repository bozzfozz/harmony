#!/usr/bin/env python3
"""Enforce diff coverage thresholds configured in ``pyproject.toml``.

This script reads the coverage policy from ``[tool.harmony.coverage]`` and
executes ``diff-cover`` with the configured options. It is intentionally
defensive so CI logs are actionable and reproducible.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError as exc:  # pragma: no cover - guards older runtimes
    raise RuntimeError("Python 3.11+ with tomllib support is required") from exc


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"
REPORTS_DIR = PROJECT_ROOT / "reports"
DEFAULT_COVERAGE_XML = REPORTS_DIR / "coverage.xml"
DIFF_OUTPUT = REPORTS_DIR / "diff_coverage.txt"
DEFAULT_COMPARE_BRANCH = "origin/main"
FALLBACK_REF = "HEAD~1"
MISSING_COVERAGE_EXIT_CODE_ENV = "DIFF_COVERAGE_MISSING_COVERAGE_EXIT_CODE"


class CoverageConfigError(RuntimeError):
    """Raised when the coverage configuration is incomplete."""


class MissingCoverageReportError(CoverageConfigError):
    """Raised when the XML coverage report is absent."""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def load_coverage_policy() -> Dict[str, Any]:
    if not PYPROJECT_PATH.exists():
        raise CoverageConfigError("pyproject.toml not found; cannot read coverage policy")

    with PYPROJECT_PATH.open("rb") as handle:
        data = tomllib.load(handle)

    tool_cfg = data.get("tool", {})
    harmony_cfg = tool_cfg.get("harmony", {})
    coverage_cfg = harmony_cfg.get("coverage", {})

    if not coverage_cfg:
        raise CoverageConfigError(
            "Missing [tool.harmony.coverage] configuration in pyproject.toml"
        )

    return coverage_cfg


def determine_compare_ref(configured_ref: str | None) -> str:
    override = os.environ.get("DIFF_COVER_COMPARE_BRANCH")
    candidate = override or configured_ref or DEFAULT_COMPARE_BRANCH

    if ref_exists(candidate):
        return candidate

    print(
        f"::warning::Reference '{candidate}' not found. Falling back to '{FALLBACK_REF}'.",
        file=sys.stderr,
    )

    if ref_exists(FALLBACK_REF):
        return FALLBACK_REF

    raise CoverageConfigError(
        "Neither the configured compare branch nor fallback HEAD~1 exist; cannot compute diff coverage"
    )


def ref_exists(ref: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", ref],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=PROJECT_ROOT,
    )
    return result.returncode == 0


def ensure_reports_dir() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def resolve_coverage_xml_path() -> Path:
    configured = os.environ.get("COVERAGE_XML")
    if not configured:
        return DEFAULT_COVERAGE_XML

    candidate = Path(configured)
    if not candidate.is_absolute():
        candidate = (PROJECT_ROOT / candidate).resolve()

    return candidate


def missing_coverage_exit_code() -> int:
    raw_value = os.environ.get(MISSING_COVERAGE_EXIT_CODE_ENV)
    if not raw_value:
        return 1

    try:
        parsed = int(raw_value)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise CoverageConfigError(
            f"Invalid {MISSING_COVERAGE_EXIT_CODE_ENV} value: '{raw_value}'"
        ) from exc

    return parsed


def run_diff_cover(compare_ref: str, threshold: float) -> int:
    coverage_xml = resolve_coverage_xml_path()

    if not coverage_xml.exists():
        exit_code = missing_coverage_exit_code()
        raise MissingCoverageReportError(
            (
                f"Coverage report not found at {coverage_xml}. "
                "Ensure the 'tests' job executed pytest --cov and uploaded the 'test-reports' artifact. "
                "Override the expected path via COVERAGE_XML if your workspace layout differs."
            ),
            exit_code,
        )

    ensure_reports_dir()

    command = [
        "diff-cover",
        str(coverage_xml),
        f"--compare-branch={compare_ref}",
        f"--fail-under={threshold}",
    ]

    print("Executing:", " ".join(command))

    process = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    DIFF_OUTPUT.write_text(process.stdout)
    sys.stdout.write(process.stdout)

    return process.returncode


def main() -> int:
    try:
        coverage_cfg = load_coverage_policy()
    except CoverageConfigError as exc:
        print(f"::error::{exc}")
        return 1

    diff_threshold = coverage_cfg.get("diff_fail_under")
    if diff_threshold is None:
        print("::error::diff_fail_under missing in coverage policy")
        return 1

    try:
        compare_ref = determine_compare_ref(coverage_cfg.get("compare_branch"))
    except CoverageConfigError as exc:
        print(f"::error::{exc}")
        return 1

    try:
        exit_code = run_diff_cover(compare_ref, float(diff_threshold))
    except MissingCoverageReportError as exc:
        print(f"::error::{exc}")
        return exc.exit_code
    except CoverageConfigError as exc:
        print(f"::error::{exc}")
        return 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
