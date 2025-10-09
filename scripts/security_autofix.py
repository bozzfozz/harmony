#!/usr/bin/env python3
"""Rule-based Bandit autofixer for Harmony.

This script reads a Bandit JSON report, applies allowlisted mechanical fixes
and emits a structured summary for the CI workflow and manual runs. The
implementation deliberately keeps the set of automated transformations narrow
and guarded; when heuristics cannot guarantee a safe rewrite the issue is
flagged for manual security review instead of applying a speculative patch.
"""
from __future__ import annotations

import argparse
import ast
import json
import logging
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence

import libcst as cst
from libcst import metadata

LOGGER = logging.getLogger("security_autofix")
ALLOWED_RULES = {"B506", "B603", "B602", "B324", "B306", "B311", "B108"}


@dataclass
class BanditIssue:
    filename: Path
    test_id: str
    issue_text: str
    line_number: int


@dataclass
class FixReport:
    rule_id: str
    changed: bool = False
    requires_manual_review: bool = False
    messages: List[str] = field(default_factory=list)


@dataclass
class FileReport:
    path: Path
    reports: List[FixReport] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return any(report.changed for report in self.reports)

    @property
    def requires_manual_review(self) -> bool:
        return any(report.requires_manual_review for report in self.reports)

    @property
    def rule_ids(self) -> List[str]:
        seen: List[str] = []
        for report in self.reports:
            if report.rule_id not in seen:
                seen.append(report.rule_id)
        return seen

    @property
    def messages(self) -> List[str]:
        notes: List[str] = []
        for report in self.reports:
            notes.extend(report.messages)
        return notes


@dataclass(frozen=True)
class FileContext:
    path: Path
    project_root: Path

    @property
    def relative_path(self) -> Path:
        try:
            return self.path.relative_to(self.project_root)
        except ValueError:
            return self.path


@dataclass
class Summary:
    changed_files: List[str]
    rule_ids: List[str]
    auto_merge_recommended: bool
    requires_manual_review: bool
    messages: List[str]

    def to_dict(self) -> Dict[str, object]:
        return {
            "changed_files": self.changed_files,
            "rule_ids": self.rule_ids,
            "auto_merge_recommended": self.auto_merge_recommended,
            "requires_manual_review": self.requires_manual_review,
            "messages": self.messages,
        }


class BaseFixer:
    """Common interface for individual rule fixers."""

    RULE_IDS: Sequence[str]

    def apply(
        self,
        module: cst.Module,
        issues: Sequence[BanditIssue],
        context: FileContext,
    ) -> tuple[cst.Module, FixReport]:
        raise NotImplementedError


def run_bandit(paths: Sequence[str], exclude: Sequence[str]) -> Dict[str, object]:
    args = [
        "bandit",
        "-r",
        ":".join(paths),
        "-f",
        "json",
    ]
    if exclude:
        args.extend(["-x", ":".join(exclude)])
    LOGGER.debug("Running bandit: %s", " ".join(args))
    completed = subprocess.run(args, check=False, capture_output=True, text=True)
    if completed.returncode not in {0, 1}:  # 0 = clean, 1 = findings
        LOGGER.error("bandit exited with %s\nstdout: %s\nstderr: %s", completed.returncode, completed.stdout, completed.stderr)
        raise RuntimeError("bandit execution failed")
    if completed.stdout:
        data = completed.stdout
    else:
        data = Path("bandit.json").read_text(encoding="utf-8")
    return json.loads(data)


def parse_issues(report: Dict[str, object], project_root: Path) -> List[BanditIssue]:
    raw_results = report.get("results", [])
    issues: List[BanditIssue] = []
    for entry in raw_results:
        try:
            issue = BanditIssue(
                filename=project_root / Path(entry["filename"]),
                test_id=str(entry["test_id"]),
                issue_text=str(entry.get("issue_text", "")),
                line_number=int(entry.get("line_number", 0)),
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            LOGGER.warning("Skipping malformed Bandit entry: %s (%s)", entry, exc)
            continue
        if issue.test_id not in ALLOWED_RULES:
            LOGGER.debug("Skipping issue %s (not in allowlist)", issue)
            continue
        issues.append(issue)
    return issues


def load_source(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        LOGGER.warning("File disappeared while processing: %s", path)
        return ""


def ensure_import(module: cst.Module, module_name: str) -> tuple[cst.Module, bool]:
    """Ensure ``import <module_name>`` exists; return updated module and flag."""
    for statement in module.body:
        if not isinstance(statement, cst.SimpleStatementLine):
            continue
        for element in statement.body:
            if isinstance(element, cst.Import):
                for alias in element.names:
                    if alias.evaluated_name == module_name:
                        return module, False
            if isinstance(element, cst.ImportFrom):
                module_attr = element.module
                if module_attr and isinstance(module_attr, cst.Name) and module_attr.value == module_name:
                    return module, False
    import_stmt = cst.SimpleStatementLine(
        body=[cst.Import(names=[cst.ImportAlias(name=cst.Name(module_name))])]
    )
    body = list(module.body)
    insert_at = 0
    if body:
        first = body[0]
        if isinstance(first, cst.SimpleStatementLine) and first.body:
            first_expr = first.body[0]
            if isinstance(first_expr, cst.Expr) and isinstance(first_expr.value, cst.SimpleString):
                insert_at = 1
    body.insert(insert_at, import_stmt)
    return module.with_changes(body=body), True


class YamlSafeLoaderFixer(BaseFixer):
    RULE_IDS = ("B506",)

    class _Transformer(cst.CSTTransformer):
        METADATA_DEPENDENCIES = (metadata.PositionProvider,)

        def __init__(self, target_lines: Sequence[int]):
            self.target_lines = set(target_lines)
            self.changed = False
            self.messages: List[str] = []

        def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.BaseExpression:
            position = self.get_metadata(metadata.PositionProvider, original_node)
            if position.start.line not in self.target_lines:
                return updated_node
            func = updated_node.func
            if not isinstance(func, cst.Attribute):
                self.messages.append(
                    "B506: Unsupported call shape for yaml.load; manual review required."
                )
                return updated_node
            if not (isinstance(func.value, cst.Name) and func.value.value == "yaml" and func.attr.value == "load"):
                return updated_node
            for arg in updated_node.args:
                if arg.keyword and arg.keyword.value == "Loader":
                    return updated_node
            loader_arg = cst.Arg(
                keyword=cst.Name("Loader"),
                value=cst.Attribute(value=cst.Name("yaml"), attr=cst.Name("SafeLoader")),
            )
            self.changed = True
            return updated_node.with_changes(args=[*updated_node.args, loader_arg])

    def apply(
        self,
        module: cst.Module,
        issues: Sequence[BanditIssue],
        context: FileContext,
    ) -> tuple[cst.Module, FixReport]:
        transformer = self._Transformer(issue.line_number for issue in issues)
        wrapper = metadata.MetadataWrapper(module)
        new_module = wrapper.visit(transformer)
        return new_module, FixReport(
            rule_id="B506",
            changed=transformer.changed,
            requires_manual_review=bool(transformer.messages),
            messages=transformer.messages,
        )


class SubprocessShellFixer(BaseFixer):
    RULE_IDS = ("B603", "B602")

    class _Transformer(cst.CSTTransformer):
        METADATA_DEPENDENCIES = (metadata.PositionProvider,)

        def __init__(self, target_lines: Sequence[int]):
            self.target_lines = set(target_lines)
            self.changed = False
            self.messages: List[str] = []
            self.manual_review = False

        def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.BaseExpression:
            position = self.get_metadata(metadata.PositionProvider, original_node)
            if position.start.line not in self.target_lines:
                return updated_node
            func = updated_node.func
            if not isinstance(func, cst.Attribute):
                self.manual_review = True
                self.messages.append(
                    "B603/B602: Unsupported subprocess call (not an attribute access)."
                )
                return updated_node
            if not (isinstance(func.value, cst.Name) and func.value.value == "subprocess"):
                return updated_node
            shell_arg = None
            for arg in updated_node.args:
                if arg.keyword and arg.keyword.value == "shell":
                    shell_arg = arg
                    break
            if shell_arg is None:
                return updated_node
            if not isinstance(shell_arg.value, cst.Name) or shell_arg.value.value != "True":
                self.manual_review = True
                self.messages.append(
                    "B603/B602: shell keyword is not a literal True; manual review required."
                )
                return updated_node
            command_arg = None
            for arg in updated_node.args:
                if arg.keyword is None:
                    command_arg = arg
                    break
            if command_arg is None:
                self.manual_review = True
                self.messages.append(
                    "B603/B602: Unable to locate command argument; manual review required."
                )
                return updated_node
            cmd_value = command_arg.value
            if not isinstance(cmd_value, cst.SimpleString):
                self.manual_review = True
                self.messages.append(
                    "B603/B602: Command argument is not a simple string literal; manual review required."
                )
                return updated_node
            try:
                literal = ast.literal_eval(cmd_value.value)
            except Exception:  # pragma: no cover - defensive
                self.manual_review = True
                self.messages.append(
                    "B603/B602: Unable to evaluate command string literal; manual review required."
                )
                return updated_node
            if any(token in literal for token in ("$", "`", "&&", "||", ";")):
                self.manual_review = True
                self.messages.append(
                    "B603/B602: Command contains shell metacharacters; manual review required."
                )
                return updated_node
            parts = shlex.split(literal)
            if not parts:
                self.manual_review = True
                self.messages.append("B603/B602: Empty command after splitting; manual review required.")
                return updated_node
            list_elements = [
                cst.Element(value=cst.SimpleString(repr(part))) for part in parts
            ]
            new_args = []
            for arg in updated_node.args:
                if arg is command_arg:
                    new_args.append(arg.with_changes(value=cst.List(elements=list_elements)))
                elif arg is shell_arg:
                    new_args.append(arg.with_changes(value=cst.Name("False")))
                else:
                    new_args.append(arg)
            self.changed = True
            return updated_node.with_changes(args=new_args)

    def apply(
        self,
        module: cst.Module,
        issues: Sequence[BanditIssue],
        context: FileContext,
    ) -> tuple[cst.Module, FixReport]:
        transformer = self._Transformer(issue.line_number for issue in issues)
        wrapper = metadata.MetadataWrapper(module)
        new_module = wrapper.visit(transformer)
        return new_module, FixReport(
            rule_id="B603/B602",
            changed=transformer.changed,
            requires_manual_review=transformer.manual_review,
            messages=transformer.messages,
        )


class TempfileMktempFixer(BaseFixer):
    RULE_IDS = ("B306",)

    class _Transformer(cst.CSTTransformer):
        METADATA_DEPENDENCIES = (metadata.PositionProvider,)

        def __init__(self, target_lines: Sequence[int]):
            self.target_lines = set(target_lines)
            self.changed = False
            self.messages: List[str] = []
            self.manual_review = False

        def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.BaseExpression:
            position = self.get_metadata(metadata.PositionProvider, original_node)
            if position.start.line not in self.target_lines:
                return updated_node
            func = updated_node.func
            if not isinstance(func, cst.Attribute):
                self.manual_review = True
                self.messages.append("B306: Unsupported call shape (no attribute access).")
                return updated_node
            if not (isinstance(func.value, cst.Name) and func.value.value == "tempfile" and func.attr.value == "mktemp"):
                return updated_node
            if updated_node.args:
                self.manual_review = True
                self.messages.append("B306: mktemp call has arguments; manual review required.")
                return updated_node
            named_tempfile_call = cst.Call(
                func=cst.Attribute(value=cst.Name("tempfile"), attr=cst.Name("NamedTemporaryFile")),
                args=[cst.Arg(keyword=cst.Name("delete"), value=cst.Name("False"))],
            )
            replacement = cst.Attribute(value=named_tempfile_call, attr=cst.Name("name"))
            self.changed = True
            return replacement

    def apply(
        self,
        module: cst.Module,
        issues: Sequence[BanditIssue],
        context: FileContext,
    ) -> tuple[cst.Module, FixReport]:
        transformer = self._Transformer(issue.line_number for issue in issues)
        wrapper = metadata.MetadataWrapper(module)
        new_module = wrapper.visit(transformer)
        return new_module, FixReport(
            rule_id="B306",
            changed=transformer.changed,
            requires_manual_review=transformer.manual_review,
            messages=transformer.messages,
        )


class HashlibMd5Fixer(BaseFixer):
    RULE_IDS = ("B324",)

    class _Transformer(cst.CSTTransformer):
        METADATA_DEPENDENCIES = (metadata.PositionProvider,)

        def __init__(self, target_lines: Sequence[int]):
            self.target_lines = set(target_lines)
            self.changed = False
            self.messages: List[str] = []
            self.manual_review = False

        def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.BaseExpression:
            position = self.get_metadata(metadata.PositionProvider, original_node)
            if position.start.line not in self.target_lines:
                return updated_node
            func = updated_node.func
            if not isinstance(func, cst.Attribute):
                self.manual_review = True
                self.messages.append("B324: Unsupported call shape (not hashlib.new).")
                return updated_node
            if not (isinstance(func.value, cst.Name) and func.value.value == "hashlib" and func.attr.value == "new"):
                return updated_node
            target_arg = None
            for arg in updated_node.args:
                if arg.keyword and arg.keyword.value == "name":
                    target_arg = arg
                    break
            if target_arg is None and updated_node.args:
                candidate = updated_node.args[0]
                if candidate.keyword is None:
                    target_arg = candidate
            if target_arg is None:
                self.manual_review = True
                self.messages.append("B324: Unable to locate md5 argument; manual review required.")
                return updated_node
            if not isinstance(target_arg.value, cst.SimpleString):
                self.manual_review = True
                self.messages.append("B324: Hash name is not a simple string literal; manual review required.")
                return updated_node
            try:
                literal = ast.literal_eval(target_arg.value.value)
            except Exception:  # pragma: no cover - defensive
                self.manual_review = True
                self.messages.append("B324: Unable to evaluate hash literal; manual review required.")
                return updated_node
            if literal.lower() != "md5":
                return updated_node
            new_arg = target_arg.with_changes(value=cst.SimpleString("'sha256'"))
            new_args = [new_arg if arg is target_arg else arg for arg in updated_node.args]
            self.changed = True
            return updated_node.with_changes(args=new_args)

    def apply(
        self,
        module: cst.Module,
        issues: Sequence[BanditIssue],
        context: FileContext,
    ) -> tuple[cst.Module, FixReport]:
        if "tests" not in context.relative_path.parts and not context.relative_path.name.startswith("test_"):
            message = (
                "B324: hashlib.new('md5') detected outside the tests/ tree; manual review required."
            )
            return module, FixReport("B324", changed=False, requires_manual_review=True, messages=[message])
        transformer = self._Transformer(issue.line_number for issue in issues)
        wrapper = metadata.MetadataWrapper(module)
        new_module = wrapper.visit(transformer)
        return new_module, FixReport(
            rule_id="B324",
            changed=transformer.changed,
            requires_manual_review=transformer.manual_review,
            messages=transformer.messages,
        )


class RandomForSecurityFixer(BaseFixer):
    RULE_IDS = ("B311",)

    class _Transformer(cst.CSTTransformer):
        METADATA_DEPENDENCIES = (metadata.PositionProvider,)
        SUPPORTED_METHODS = {"random", "randint", "randrange", "choice", "shuffle"}

        def __init__(self, target_lines: Sequence[int]):
            self.target_lines = set(target_lines)
            self.changed = False
            self.manual_review = False
            self.messages: List[str] = []

        def leave_Call(self, original_node: cst.Call, updated_node: cst.Call) -> cst.BaseExpression:
            position = self.get_metadata(metadata.PositionProvider, original_node)
            if position.start.line not in self.target_lines:
                return updated_node
            func = updated_node.func
            if not isinstance(func, cst.Attribute):
                self.manual_review = True
                self.messages.append("B311: Unsupported call shape (expected random.<method>).")
                return updated_node
            if not (isinstance(func.value, cst.Name) and func.value.value == "random"):
                return updated_node
            method = func.attr.value
            if method not in self.SUPPORTED_METHODS:
                self.manual_review = True
                self.messages.append(
                    f"B311: random.{method} not supported by autofix; manual review required."
                )
                return updated_node
            new_func = cst.Attribute(
                value=cst.Call(
                    func=cst.Attribute(value=cst.Name("secrets"), attr=cst.Name("SystemRandom")),
                    args=[],
                ),
                attr=cst.Name(method),
            )
            self.changed = True
            return updated_node.with_changes(func=new_func)

    def apply(
        self,
        module: cst.Module,
        issues: Sequence[BanditIssue],
        context: FileContext,
    ) -> tuple[cst.Module, FixReport]:
        transformer = self._Transformer(issue.line_number for issue in issues)
        wrapper = metadata.MetadataWrapper(module)
        new_module = wrapper.visit(transformer)
        if transformer.changed:
            new_module, added = ensure_import(new_module, "secrets")
            if added:
                transformer.messages.append("B311: Added missing `import secrets`.")
        return new_module, FixReport(
            rule_id="B311",
            changed=transformer.changed,
            requires_manual_review=transformer.manual_review,
            messages=transformer.messages,
        )


class TmpPathFixer(BaseFixer):
    RULE_IDS = ("B108",)

    def apply(
        self,
        module: cst.Module,
        issues: Sequence[BanditIssue],
        context: FileContext,
    ) -> tuple[cst.Module, FixReport]:
        message = (
            "B108: Automatic rewrite for hard-coded /tmp paths is not implemented; manual review required."
        )
        return module, FixReport("B108", changed=False, requires_manual_review=True, messages=[message])


FIXERS: List[BaseFixer] = [
    YamlSafeLoaderFixer(),
    SubprocessShellFixer(),
    TempfileMktempFixer(),
    HashlibMd5Fixer(),
    RandomForSecurityFixer(),
    TmpPathFixer(),
]


def build_summary(file_reports: Sequence[FileReport]) -> Summary:
    changed_files = [str(report.path) for report in file_reports if report.changed]
    rule_ids: List[str] = []
    messages: List[str] = []
    requires_manual_review = False
    for report in file_reports:
        messages.extend(report.messages)
        if report.requires_manual_review:
            requires_manual_review = True
        for rule_id in report.rule_ids:
            if rule_id not in rule_ids:
                rule_ids.append(rule_id)
    auto_merge = bool(changed_files) and not requires_manual_review
    return Summary(
        changed_files=changed_files,
        rule_ids=rule_ids,
        auto_merge_recommended=auto_merge,
        requires_manual_review=requires_manual_review,
        messages=messages,
    )


def process(
    issues: Sequence[BanditIssue],
    project_root: Path,
    apply_changes: bool,
) -> Summary:
    grouped: Dict[Path, List[BanditIssue]] = {}
    for issue in issues:
        grouped.setdefault(issue.filename, []).append(issue)
    file_reports: List[FileReport] = []
    for path, file_issues in grouped.items():
        source = load_source(path)
        if not source:
            continue
        try:
            module = cst.parse_module(source)
        except Exception as exc:
            LOGGER.warning("Unable to parse %s: %s", path, exc)
            file_reports.append(
                FileReport(
                    path=path,
                    reports=[
                        FixReport(
                            rule_id="parse-error",
                            changed=False,
                            requires_manual_review=True,
                            messages=[f"Failed to parse {path}: {exc}"],
                        )
                    ],
                )
            )
            continue
        context = FileContext(path=path, project_root=project_root)
        reports: List[FixReport] = []
        for fixer in FIXERS:
            relevant = [issue for issue in file_issues if issue.test_id in fixer.RULE_IDS]
            if not relevant:
                continue
            module, report = fixer.apply(module, relevant, context)
            reports.append(report)
        if reports and apply_changes:
            path.write_text(module.code, encoding="utf-8")
        file_reports.append(FileReport(path=path, reports=reports))
    return build_summary(file_reports)


def format_markdown(summary: Summary) -> str:
    if not summary.changed_files:
        return "## Security autofix\n\nKeine Änderungen erforderlich."  # pragma: no cover - formatting only
    lines = ["## Security autofix", ""]
    lines.append("### Betroffene Regeln")
    lines.append("")
    for rule in summary.rule_ids:
        lines.append(f"- {rule}")
    lines.append("")
    lines.append("### Geänderte Dateien")
    lines.append("")
    for path in summary.changed_files:
        lines.append(f"- `{path}`")
    if summary.messages:
        lines.append("")
        lines.append("### Hinweise")
        lines.append("")
        for message in summary.messages:
            lines.append(f"- {message}")
    if summary.requires_manual_review:
        lines.append("")
        lines.append(
            "> ⚠️ Mindestens eine Änderung benötigt eine manuelle Sicherheitsprüfung, Auto-Merge wurde deaktiviert."
        )
    else:
        lines.append("")
        lines.append(
            "> ✅ Alle Änderungen stammen aus der Allowlist, Auto-Merge ist aktiviert sofern die Quality-Gates grün sind."
        )
    return "\n".join(lines)


def build_commit_message(summary: Summary) -> str:
    if not summary.rule_ids:
        return "security(autofix): noop run [skip-changelog]"
    if len(summary.rule_ids) == 1:
        rule = summary.rule_ids[0]
    else:
        rule = "multi"
    return f"security(autofix): {rule.lower()} remediation [skip-changelog]"


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply allowlisted Bandit autofixes.")
    parser.add_argument("--bandit-report", type=Path, help="Optional pre-generated Bandit JSON report.")
    parser.add_argument("--paths", nargs="*", default=["app"], help="Target paths for Bandit (default: app).")
    parser.add_argument("--exclude", nargs="*", default=["tests"], help="Excluded paths for Bandit.")
    parser.add_argument("--summary", type=Path, help="Write machine-readable summary JSON to this path.")
    parser.add_argument("--report-markdown", type=Path, help="Write Markdown summary to this path.")
    parser.add_argument("--check", action="store_true", help="Dry-run mode (no file writes, exit 1 if changes required).")
    parser.add_argument("--apply", action="store_true", help="Apply changes in place.")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging output.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    project_root = Path.cwd()
    if args.check and args.apply:
        LOGGER.error("--check and --apply are mutually exclusive")
        return 2
    if not args.bandit_report:
        LOGGER.info("Running bandit to generate report …")
        report = run_bandit(args.paths, args.exclude)
    else:
        report = json.loads(args.bandit_report.read_text(encoding="utf-8"))
    issues = parse_issues(report, project_root)
    apply_changes = args.apply and not args.check
    summary = process(issues, project_root, apply_changes=apply_changes)
    if args.summary:
        args.summary.write_text(json.dumps(summary.to_dict(), indent=2), encoding="utf-8")
    if args.report_markdown:
        args.report_markdown.write_text(format_markdown(summary), encoding="utf-8")
    LOGGER.info("Changed files: %s", summary.changed_files)
    LOGGER.info("Rules: %s", summary.rule_ids)
    LOGGER.info("Auto-merge recommended: %s", summary.auto_merge_recommended)
    if summary.messages:
        for message in summary.messages:
            LOGGER.info("Note: %s", message)
    if args.check and summary.changed_files:
        LOGGER.info("Dry-run detected pending changes; exiting with status 1.")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    sys.exit(main())
