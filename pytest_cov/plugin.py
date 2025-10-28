"""Minimal coverage plugin to satisfy --cov usage without third-party dependencies."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import os
from pathlib import Path
import sys
import threading
import time
import trace
import types
from typing import cast
from xml.etree import ElementTree as ET

import pytest


@dataclass(slots=True)
class ReportOptions:
    term: bool
    term_missing: bool
    xml_path: Path | None


@dataclass(slots=True)
class FileCoverage:
    path: Path
    relative: Path
    statements: list[int]
    executed: dict[int, int]

    @property
    def total(self) -> int:
        return len(self.statements)

    @property
    def covered(self) -> int:
        return sum(1 for line in self.statements if line in self.executed)

    @property
    def missed(self) -> list[int]:
        return [line for line in self.statements if line not in self.executed]

    @property
    def coverage_ratio(self) -> float:
        if not self.total:
            return 1.0
        return self.covered / self.total


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("harmony-cov")
    group.addoption(
        "--cov",
        action="append",
        dest="harmony_cov_targets",
        default=[],
        metavar="TARGET",
        help="Measure coverage for the given package/module/path.",
    )
    group.addoption(
        "--cov-report",
        action="append",
        dest="harmony_cov_reports",
        default=[],
        metavar="TYPE",
        help="Generate coverage report: term, term-missing, or xml[:path]",
    )


class HarmonyCoveragePlugin:
    """Collect simple line coverage information for --cov usage."""

    def __init__(self, config: pytest.Config) -> None:
        self._root = Path(str(config.rootpath)).resolve()
        self._targets = list(config.getoption("harmony_cov_targets") or [])
        self._report_specs = list(config.getoption("harmony_cov_reports") or [])
        self._reports = self._parse_reports()
        self._target_files = self._resolve_target_files()
        self._enabled = bool(self._target_files)
        self._tracer: trace.Trace | None = None
        self._previous_sys_trace: types.TraceFunction | None = None
        self._previous_thread_trace: types.TraceFunction | None = None
        self._data: list[FileCoverage] | None = None

        if self._targets and not self._target_files:
            joined = ", ".join(self._targets)
            raise pytest.UsageError(f"No Python files found for --cov target(s): {joined}")

    def _parse_reports(self) -> ReportOptions:
        term = False
        term_missing = False
        xml_path: Path | None = None
        for raw in self._report_specs:
            spec = (raw or "").strip()
            if not spec:
                continue
            name, _, value = spec.partition(":")
            name = name.lower()
            if name == "term":
                term = True
            elif name == "term-missing":
                term = True
                term_missing = True
            elif name == "xml":
                resolved = value or "coverage.xml"
                xml_path = (self._root / resolved).resolve()
            else:
                raise pytest.UsageError(
                    f"Unsupported --cov-report option '{spec}'. Use term or xml[:path]."
                )
        return ReportOptions(
            term=term or term_missing, term_missing=term_missing, xml_path=xml_path
        )

    def _resolve_target_files(self) -> list[Path]:
        if not self._targets:
            return []
        files: set[Path] = set()
        for token in self._targets:
            for path in self._interpret_target(token):
                files.add(path.resolve())
        return sorted(files)

    def _interpret_target(self, token: str) -> list[Path]:
        """Yield file paths for a coverage token."""
        normalized = token.replace(".", os.sep)
        candidate = (self._root / normalized).resolve()
        candidates: list[Path] = []
        if candidate.is_dir():
            candidates.extend(path for path in candidate.rglob("*.py") if path.is_file())
        elif candidate.is_file():
            candidates.append(candidate)
        else:
            alt = candidate.with_suffix(".py")
            if alt.is_file():
                candidates.append(alt)
        return candidates

    @pytest.hookimpl
    def pytest_sessionstart(self, session: pytest.Session) -> None:  # noqa: D401 - pytest hook
        if not self._enabled:
            return
        tracer = trace.Trace(count=True, trace=False)
        self._tracer = tracer
        tracefunc = tracer.globaltrace
        self._previous_sys_trace = sys.gettrace()
        self._previous_thread_trace = threading.gettrace()
        sys.settrace(tracefunc)
        threading.settrace(tracefunc)

    @pytest.hookimpl
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:  # noqa: D401 - pytest hook
        if not self._enabled or self._tracer is None:
            return
        sys.settrace(self._previous_sys_trace)
        threading.settrace(self._previous_thread_trace)
        results = self._tracer.results()
        counts = results.counts
        coverage = self._build_reports(counts)
        self._data = coverage
        if self._reports.xml_path is not None:
            self._write_xml_report(coverage, self._reports.xml_path)

    def _build_reports(self, counts: dict[tuple[str, int], int]) -> list[FileCoverage]:
        reports: list[FileCoverage] = []
        for path in self._target_files:
            executed: dict[int, int] = {}
            for (filename, lineno), hits in counts.items():
                if Path(filename).resolve() == path:
                    executed[int(lineno)] = hits
            statements = self._statement_lines(path)
            reports.append(
                FileCoverage(
                    path=path,
                    relative=path.relative_to(self._root),
                    statements=sorted(statements),
                    executed=executed,
                )
            )
        return sorted(reports, key=lambda item: item.relative.as_posix())

    def _statement_lines(self, path: Path) -> set[int]:
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            return set()
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            return set()
        lines: set[int] = set()
        for node in ast.walk(tree):
            lineno = getattr(node, "lineno", None)
            end_lineno = getattr(node, "end_lineno", None)
            if lineno is None:
                continue
            lines.add(int(lineno))
            if end_lineno is not None:
                for value in range(int(lineno), int(end_lineno) + 1):
                    lines.add(value)
        return {line for line in lines if line > 0}

    @pytest.hookimpl
    def pytest_terminal_summary(self, terminalreporter: pytest.TerminalReporter) -> None:
        if not self._enabled or not self._reports.term or not self._data:
            return
        terminalreporter.write_sep("-", "coverage summary")
        header = f"{'Name':<50} {'Stmts':>6} {'Miss':>6} {'Cover':>6}"
        terminalreporter.write_line(header)
        total_statements = 0
        total_covered = 0
        for report in self._data:
            total_statements += report.total
            total_covered += report.covered
            percent = 100.0 * report.coverage_ratio
            missed = report.total - report.covered
            summary = (
                f"{report.relative.as_posix():<50} "
                f"{report.total:>6} {missed:>6} {percent:>5.1f}%"
            )
            terminalreporter.write_line(summary)
            if self._reports.term_missing and report.missed:
                missing = ",".join(str(num) for num in report.missed)
                terminalreporter.write_line(f"  Missing: {missing}")
        overall = 100.0 if total_statements == 0 else (100.0 * total_covered / total_statements)
        overall_missed = total_statements - total_covered
        total_line = (
            f"{'TOTAL':<50} {total_statements:>6} {overall_missed:>6} {overall:>5.1f}%"
        )
        terminalreporter.write_line(total_line)

    def _write_xml_report(self, reports: list[FileCoverage], destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        total_statements = sum(report.total for report in reports)
        total_covered = sum(report.covered for report in reports)
        line_rate = 1.0 if total_statements == 0 else total_covered / total_statements
        root = ET.Element(
            "coverage",
            attrib={
                "branch-rate": "0",
                "line-rate": f"{line_rate:.4f}",
                "timestamp": str(int(time.time())),
                "version": "harmony-pytest-cov",
            },
        )
        packages_el = ET.SubElement(root, "packages")
        grouped: dict[str, list[FileCoverage]] = {}
        for report in reports:
            package = ".".join(report.relative.parts[:-1]) or "."
            grouped.setdefault(package, []).append(report)
        for package, entries in sorted(grouped.items()):
            package_total = sum(item.total for item in entries)
            package_cov = sum(item.covered for item in entries)
            package_rate = 1.0 if package_total == 0 else package_cov / package_total
            package_el = ET.SubElement(
                packages_el,
                "package",
                attrib={
                    "name": package,
                    "branch-rate": "0",
                    "line-rate": f"{package_rate:.4f}",
                },
            )
            classes_el = ET.SubElement(package_el, "classes")
            for entry in entries:
                class_rate = entry.coverage_ratio
                class_el = ET.SubElement(
                    classes_el,
                    "class",
                    attrib={
                        "name": entry.relative.stem,
                        "filename": entry.relative.as_posix(),
                        "branch-rate": "0",
                        "line-rate": f"{class_rate:.4f}",
                    },
                )
                lines_el = ET.SubElement(class_el, "lines")
                for number in entry.statements:
                    hits = entry.executed.get(number, 0)
                    ET.SubElement(
                        lines_el,
                        "line",
                        attrib={"number": str(number), "hits": str(hits)},
                    )
        ET.ElementTree(root).write(destination, encoding="utf-8", xml_declaration=True)


def pytest_configure(config: pytest.Config) -> None:
    plugin = HarmonyCoveragePlugin(config)
    config.pluginmanager.register(plugin, "harmony_simple_cov")


def pytest_unconfigure(config: pytest.Config) -> None:
    plugin = cast(
        HarmonyCoveragePlugin | None, config.pluginmanager.get_plugin("harmony_simple_cov")
    )
    if plugin is not None:
        config.pluginmanager.unregister(name="harmony_simple_cov")
