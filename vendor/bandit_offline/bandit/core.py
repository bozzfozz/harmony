"""Kernlogik für den Bandit-Ersatz."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Iterable, Iterator, List
import ast
import fnmatch


class SeverityLevel(IntEnum):
    """Vereinfacht die Bandit-Schweregrade in numerische Vergleiche."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3

    @classmethod
    def from_string(cls, raw: str | None) -> "SeverityLevel":
        if not raw:
            return cls.LOW
        normalized = raw.strip().upper()
        if normalized == "LOW":
            return cls.LOW
        if normalized == "MEDIUM":
            return cls.MEDIUM
        if normalized == "HIGH":
            return cls.HIGH
        raise ValueError(f"Unbekannter Severity-Level: {raw}")


class ConfidenceLevel(IntEnum):
    """Unterstützt dieselbe Vergleichslogik wie Bandit."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3

    @classmethod
    def from_string(cls, raw: str | None) -> "ConfidenceLevel":
        if not raw:
            return cls.LOW
        normalized = raw.strip().upper()
        if normalized == "LOW":
            return cls.LOW
        if normalized == "MEDIUM":
            return cls.MEDIUM
        if normalized == "HIGH":
            return cls.HIGH
        raise ValueError(f"Unbekannter Confidence-Level: {raw}")


@dataclass(slots=True)
class BanditIssue:
    """Beschreibt ein gefundenes Sicherheitsproblem."""

    filename: Path
    lineno: int
    col_offset: int
    severity: SeverityLevel
    confidence: ConfidenceLevel
    test_id: str
    message: str


class SecurityVisitor(ast.NodeVisitor):
    """Durchsucht den AST nach riskanten Konstrukten."""

    def __init__(self, filename: Path) -> None:
        self.filename = filename
        self.issues: list[BanditIssue] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: D401
        issue = self._check_call(node)
        if issue is not None:
            self.issues.append(issue)
        self.generic_visit(node)

    def _check_call(self, node: ast.Call) -> BanditIssue | None:
        dotted_name = _get_dotted_name(node.func)
        if dotted_name is None:
            return None

        if dotted_name == "eval":
            return self._issue(node, "B101", "Verwendung von eval() ermöglicht Code-Injektion.", SeverityLevel.HIGH)
        if dotted_name == "exec":
            return self._issue(node, "B102", "Verwendung von exec() ermöglicht Code-Injektion.", SeverityLevel.HIGH)
        if dotted_name == "compile" and _literal_arg_at(node, 2) in {"exec", "eval"}:
            return self._issue(node, "B103", "compile(..., mode='exec') erzeugt dynamischen Code.", SeverityLevel.MEDIUM)
        if dotted_name in {
            "pickle.load",
            "pickle.loads",
            "dill.load",
            "dill.loads",
        }:
            return self._issue(node, "B301", "Unsichere Deserialisierung über pickle/dill.", SeverityLevel.HIGH)
        if dotted_name == "yaml.load" and not _has_keyword(node, "Loader"):
            return self._issue(node, "B401", "yaml.load ohne Loader ist unsicher (verwende SafeLoader).", SeverityLevel.HIGH)
        if dotted_name.startswith("subprocess.") and dotted_name.split(".")[-1] in {"Popen", "call", "check_call", "check_output", "run"}:
            if _keyword_is_true(node, "shell"):
                return self._issue(node, "B501", "subprocess.* mit shell=True erlaubt Shell-Injektion.", SeverityLevel.HIGH)
        return None

    def _issue(self, node: ast.AST, test_id: str, message: str, severity: SeverityLevel) -> BanditIssue:
        return BanditIssue(
            filename=self.filename,
            lineno=getattr(node, "lineno", 0) or 0,
            col_offset=getattr(node, "col_offset", 0) or 0,
            severity=severity,
            confidence=ConfidenceLevel.HIGH,
            test_id=test_id,
            message=message,
        )


def scan_file(path: Path) -> List[BanditIssue]:
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:  # pragma: no cover - Syntaxfehler sind im Repo unerwartet
        issue = BanditIssue(
            filename=path,
            lineno=exc.lineno or 0,
            col_offset=exc.offset or 0,
            severity=SeverityLevel.HIGH,
            confidence=ConfidenceLevel.HIGH,
            test_id="B000",
            message=f"SyntaxError: {exc.msg}",
        )
        return [issue]

    visitor = SecurityVisitor(path)
    visitor.visit(tree)
    return visitor.issues


def scan_paths(paths: Iterable[Path]) -> List[BanditIssue]:
    issues: list[BanditIssue] = []
    for path in paths:
        issues.extend(scan_file(path))
    return issues


def iter_python_files(base_paths: Iterable[Path], exclude_patterns: Iterable[str]) -> Iterator[Path]:
    normalized_patterns = [pattern.rstrip("/") for pattern in exclude_patterns if pattern]
    root = Path.cwd()
    for base in base_paths:
        target = (root / base).resolve() if not base.is_absolute() else base
        if target.is_dir():
            for candidate in target.rglob("*.py"):
                if _is_excluded(candidate, normalized_patterns):
                    continue
                yield candidate
        elif target.suffix == ".py" and not _is_excluded(target, normalized_patterns):
            yield target


def _is_excluded(path: Path, patterns: Iterable[str]) -> bool:
    rel = path.relative_to(Path.cwd()).as_posix()
    for pattern in patterns:
        if not pattern:
            continue
        normalized = pattern.strip()
        if rel == normalized or rel.startswith(f"{normalized}/"):
            return True
        if fnmatch.fnmatch(rel, normalized):
            return True
    return False


def _get_dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts: list[str] = []
        current: ast.AST | None = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
            return ".".join(reversed(parts))
    return None


def _has_keyword(call: ast.Call, name: str) -> bool:
    return any(keyword.arg == name for keyword in call.keywords if keyword.arg is not None)


def _keyword_is_true(call: ast.Call, name: str) -> bool:
    for keyword in call.keywords:
        if keyword.arg != name:
            continue
        value = keyword.value
        if isinstance(value, ast.Constant):
            return bool(value.value)
    return False


def _literal_arg_at(call: ast.Call, position: int) -> str | None:
    if position < len(call.args):
        value = call.args[position]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    return None
