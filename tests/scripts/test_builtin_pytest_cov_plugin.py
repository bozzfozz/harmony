from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

pytest_plugins = ("pytester",)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_builtin_pytest_cov_generates_reports(pytester: pytest.Pytester) -> None:
    pytester.syspathinsert(_repo_root())
    pytester.makeconftest("pytest_plugins = ('pytest_cov.plugin',)\n")
    pytester.makepyfile(
        sample_module="""
from typing import Any


def useful(value: int) -> int:
    if value > 0:
        return value * 2
    return -value


class Sample:
    def compute(self, payload: int) -> int:
        return useful(payload)
"""
    )
    pytester.makepyfile(
        test_sample="""
from sample_module import Sample


def test_compute_positive() -> None:
    assert Sample().compute(2) == 4


def test_compute_negative() -> None:
    assert Sample().compute(-3) == 3
"""
    )

    result = pytester.runpytest(
        "--cov=sample_module",
        "--cov-report=xml:coverage.xml",
        "--cov-report=term-missing",
    )
    result.assert_outcomes(passed=2)
    result.stdout.fnmatch_lines(["*- coverage summary -*", "*sample_module.py*100.0%*"])

    xml_path = pytester.path / "coverage.xml"
    assert xml_path.exists()
    tree = ET.parse(xml_path)
    root = tree.getroot()
    filenames = [elem.attrib["filename"] for elem in root.findall(".//class")]
    assert "sample_module.py" in filenames
    line_entries = root.findall(".//line")
    assert any(entry.attrib.get("hits") == "0" for entry in line_entries) is False


def test_builtin_pytest_cov_missing_target(pytester: pytest.Pytester) -> None:
    pytester.syspathinsert(_repo_root())
    pytester.makeconftest("pytest_plugins = ('pytest_cov.plugin',)\n")
    pytester.makepyfile(
        test_dummy="""
def test_dummy() -> None:
    assert True
"""
    )

    result = pytester.runpytest("--cov=does_not_exist")
    assert result.ret != 0
    result.stderr.fnmatch_lines(
        ["*No Python files found for --cov target(s): does_not_exist*"]
    )
