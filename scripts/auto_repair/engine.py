"""Auto-repair orchestration for build and test workflows."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

REPO_ROOT = Path(__file__).resolve().parents[2]
SUMMARY_PATH = REPO_ROOT / "reports" / "auto_repair_summary.md"
TRACE_HEADER = "AUTO-REPAIR"  # prefix for log clarity


@dataclass(slots=True)
class RepairCommand:
    """Single executable command within a repair stage."""

    name: str
    argv: Sequence[str]
    cwd: Path = REPO_ROOT
    env: dict[str, str] | None = None


@dataclass(slots=True)
class RepairStage:
    """A build/lint/test stage that can be auto-repaired."""

    name: str
    commands: Sequence[RepairCommand]


@dataclass(slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(slots=True)
class FixOutcome:
    issue_id: str
    description: str
    success: bool
    message: str
    commands: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    env_updates: dict[str, str] = field(default_factory=dict)
    resolved_without_rerun: bool = False


class ReasonTraceLogger:
    """Structured logger that emits reason-trace lines."""

    def emit(
        self,
        *,
        step: str,
        why: str,
        command: str | None = None,
        result: str | None = None,
        nxt: str | None = None,
    ) -> None:
        lines = [f"{TRACE_HEADER} | STEP: {step}", f"{TRACE_HEADER} | WHY: {why}"]
        if command:
            lines.append(f"{TRACE_HEADER} | COMMAND: {command}")
        if result:
            lines.append(f"{TRACE_HEADER} | RESULT: {result}")
        if nxt:
            lines.append(f"{TRACE_HEADER} | NEXT: {nxt}")
        print("\n".join(lines))


class Fixer:
    """Base interface for specific auto-repair fixers."""

    issue_id: str
    description: str

    def matches(self, context: RepairContext) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def apply(
        self, context: RepairContext, logger: ReasonTraceLogger
    ) -> FixOutcome:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass(slots=True)
class RepairContext:
    stage: RepairStage
    command: RepairCommand
    attempt: int
    result: CommandResult
    combined_output: str
    env: dict[str, str]


class PipHashFixer(Fixer):
    issue_id = "python.hash"
    description = "Recompile Python requirement hashes via pip-compile"

    def matches(self, context: RepairContext) -> bool:
        output = context.combined_output.lower()
        if "hash" not in output:
            return False
        return "hash" in output and ("do not match" in output or "expected" in output)

    def apply(self, context: RepairContext, logger: ReasonTraceLogger) -> FixOutcome:
        logger.emit(
            step="DECIDE",
            why="Detected pip hash drift",
            command=context.command.name,
            nxt="FIX",
        )
        pip_compile = shutil.which("pip-compile") or shutil.which("pipcompile")
        if not pip_compile:
            message = "pip-compile is required for hash regeneration"
            logger.emit(
                step="FIX",
                why=message,
                command="pip-compile",
                result="MISSING",
                nxt="DONE",
            )
            return FixOutcome(
                issue_id=self.issue_id,
                description=self.description,
                success=False,
                message=message,
                warnings=["Install pip-tools and rerun auto-repair"],
            )

        requirements_files = [
            REPO_ROOT / "requirements.txt",
            REPO_ROOT / "requirements-dev.txt",
        ]
        executed: list[str] = []
        for req_file in requirements_files:
            if not req_file.exists():
                continue
            command = [pip_compile, "--generate-hashes", str(req_file)]
            display = " ".join(command)
            completed = subprocess.run(
                command, cwd=REPO_ROOT, capture_output=True, text=True, check=False
            )
            executed.append(display)
            logger.emit(
                step="FIX",
                why="Regenerating requirement hashes",
                command=display,
                result=f"exit={completed.returncode}",
                nxt="FIX" if req_file is not requirements_files[-1] else "VERIFY",
            )
            if completed.returncode != 0:
                message = textwrap.shorten(
                    completed.stderr.strip() or completed.stdout.strip(), width=240
                )
                return FixOutcome(
                    issue_id=self.issue_id,
                    description=self.description,
                    success=False,
                    message=message,
                    commands=executed.copy(),
                    warnings=["Review pip-compile output for details"],
                )

        logger.emit(
            step="VERIFY",
            why="pip hash regeneration complete",
            command="; ".join(executed) if executed else "noop",
            result="exit=0",
            nxt="RE-RUN",
        )
        message = "Requirement hashes regenerated" if executed else "No requirements files found"
        return FixOutcome(
            issue_id=self.issue_id,
            description=self.description,
            success=bool(executed),
            message=message,
            commands=executed,
            warnings=[] if executed else ["No requirements*.txt files found for regeneration"],
        )


class RuffAutoFixer(Fixer):
    issue_id = "python.lint.ruff"
    description = "Auto-fix ruff lint violations"

    def matches(self, context: RepairContext) -> bool:
        return "ruff" in context.command.name and "check" in context.command.name

    def apply(self, context: RepairContext, logger: ReasonTraceLogger) -> FixOutcome:
        logger.emit(
            step="DECIDE",
            why="Ruff lint errors detected",
            command=context.command.name,
            nxt="FIX",
        )
        command = ["ruff", "check", "--fix", "--unsafe-fixes", "."]
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        display = " ".join(command)
        logger.emit(
            step="FIX",
            why="Applying ruff --fix",
            command=display,
            result=f"exit={completed.returncode}",
            nxt="VERIFY" if completed.returncode == 0 else "DONE",
        )
        success = completed.returncode == 0
        if success:
            logger.emit(
                step="VERIFY",
                why="Ruff autofix completed",
                command=display,
                result="OK",
                nxt="RE-RUN",
            )
        combined = (completed.stdout or "") + "\n" + (completed.stderr or "")
        message = textwrap.shorten(combined.strip() or "ruff --fix executed", width=240)
        warnings = [] if success else ["Ruff autofix failed; manual intervention required"]
        return FixOutcome(
            issue_id=self.issue_id,
            description=self.description,
            success=success,
            message=message,
            commands=[display],
            warnings=warnings,
        )


ALL_FIXERS: Sequence[Fixer] = (
    RuffAutoFixer(),
    PipHashFixer(),
)


def truthy(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def determine_warn_mode() -> bool:
    supply_mode = os.getenv("SUPPLY_MODE", "STRICT").upper()
    strict_default = not truthy(os.getenv("CI"), default=False)
    strict = truthy(os.getenv("TOOLCHAIN_STRICT"), default=strict_default)
    warn_mode = supply_mode == "WARN" or not strict
    return warn_mode


@dataclass(slots=True)
class SummaryEntry:
    stage: str
    issue_id: str
    description: str
    status: str
    message: str
    commands: Sequence[str] = ()
    warnings: Sequence[str] = ()


class AutoRepairEngine:
    def __init__(
        self,
        *,
        stages: dict[str, RepairStage],
        fixers: Sequence[Fixer] = ALL_FIXERS,
        max_iters: int = 3,
        logger: ReasonTraceLogger | None = None,
    ) -> None:
        self._stages = stages
        self._fixers = list(fixers)
        self._max_iters = max_iters
        self._logger = logger or ReasonTraceLogger()
        self._warn_mode = determine_warn_mode()
        self._summary: list[SummaryEntry] = []

    def run(self, stage_name: str) -> int:
        if stage_name not in self._stages:
            raise ValueError(f"Unknown stage '{stage_name}'")
        stage = self._stages[stage_name]
        env_overrides: dict[str, str] = {}
        for attempt in range(1, self._max_iters + 1):
            self._logger.emit(
                step="SCAN",
                why=f"Running stage '{stage.name}' attempt {attempt}",
                command="; ".join(cmd.name for cmd in stage.commands),
                nxt="VERIFY",
            )
            stage_success = True
            for command in stage.commands:
                merged_env = os.environ.copy()
                merged_env.update(command.env or {})
                merged_env.update(env_overrides)
                result = self._run_command(command, merged_env)
                context = RepairContext(
                    stage=stage,
                    command=command,
                    attempt=attempt,
                    result=result,
                    combined_output=f"{result.stdout}\n{result.stderr}",
                    env=merged_env,
                )
                if result.returncode == 0:
                    continue

                stage_success = False
                matched_fixers = [fixer for fixer in self._fixers if fixer.matches(context)]
                if not matched_fixers:
                    return self._handle_failure(context)

                rerun_required = True
                for fixer in matched_fixers:
                    outcome = fixer.apply(context, self._logger)
                    status = "fixed" if outcome.success else "warn"
                    self._summary.append(
                        SummaryEntry(
                            stage=stage.name,
                            issue_id=fixer.issue_id,
                            description=fixer.description,
                            status=status,
                            message=outcome.message,
                            commands=tuple(outcome.commands),
                            warnings=tuple(outcome.warnings),
                        )
                    )
                    env_overrides.update(outcome.env_updates)
                    if outcome.resolved_without_rerun:
                        rerun_required = False
                if not rerun_required:
                    self._logger.emit(
                        step="DONE",
                        why="Stage marked as WARN-only due to registry outage",
                        command=command.name,
                        result="WARN",
                        nxt="NONE",
                    )
                    self._write_summary(stage_success=False)
                    return 0 if self._warn_mode else result.returncode
                self._logger.emit(
                    step="RE-RUN",
                    why="Applying fixes and retrying stage",
                    command=command.name,
                    result="retry",
                    nxt="SCAN",
                )
                break
            if stage_success:
                self._logger.emit(
                    step="DONE",
                    why=f"Stage '{stage.name}' completed successfully",
                    result="OK",
                    nxt="NONE",
                )
                self._write_summary(stage_success=True)
                return 0
        self._logger.emit(
            step="DONE",
            why=f"Stage '{stage.name}' failed after {self._max_iters} attempts",
            result="ERROR",
            nxt="NONE",
        )
        self._write_summary(stage_success=False)
        return 0 if self._warn_mode else 1

    def _run_command(self, command: RepairCommand, env: dict[str, str]) -> CommandResult:
        try:
            completed = subprocess.run(
                list(command.argv),
                cwd=command.cwd,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            return CommandResult(completed.returncode, completed.stdout, completed.stderr)
        except FileNotFoundError as exc:
            message = f"Command '{command.argv[0]}' not found: {exc}"
            return CommandResult(127, "", message)

    def _handle_failure(self, context: RepairContext) -> int:
        message = textwrap.shorten(context.combined_output.strip(), width=320) or "(no output)"
        self._summary.append(
            SummaryEntry(
                stage=context.stage.name,
                issue_id="unhandled",
                description="No auto-fix available",
                status="error",
                message=message,
            )
        )
        self._logger.emit(
            step="DONE",
            why="No fixer matched failure output",
            command=context.command.name,
            result="WARN" if self._warn_mode else "ERROR",
            nxt="NONE",
        )
        self._write_summary(stage_success=False)
        return 0 if self._warn_mode else context.result.returncode

    def _write_summary(self, stage_success: bool) -> None:
        SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
        stage_status = "success" if stage_success else ("warn" if self._warn_mode else "failed")
        mode_label = "WARN" if self._warn_mode else "STRICT"
        rows = [
            "# Auto-Repair Summary",
            "",
            f"- Stage status: {stage_status}",
            f"- Attempts: {self._max_iters}",
            f"- Mode: {mode_label}",
            "",
        ]
        if self._summary:
            rows.append("| Stage | Issue | Status | Message |")
            rows.append("| --- | --- | --- | --- |")
            for entry in self._summary:
                rows.append(
                    f"| {entry.stage} | {entry.issue_id} | {entry.status} | {entry.message} |"
                )
            rows.append("")
            for entry in self._summary:
                if entry.warnings:
                    rows.append(f"### Warnings for {entry.issue_id}")
                    for warn in entry.warnings:
                        rows.append(f"- {warn}")
                    rows.append("")
                if entry.commands:
                    rows.append(f"### Commands executed for {entry.issue_id}")
                    rows.append("```")
                    rows.extend(entry.commands)
                    rows.append("```")
                    rows.append("")
        else:
            rows.append("No auto-repair actions were required.")
        SUMMARY_PATH.write_text("\n".join(rows) + "\n", encoding="utf-8")


STAGE_DEFINITIONS: dict[str, RepairStage] = {
    "fmt": RepairStage(
        name="fmt",
        commands=(
            RepairCommand(name="ruff format", argv=["ruff", "format", "."]),
            RepairCommand(
                name="ruff check fix imports",
                argv=["ruff", "check", "--select", "I", "--fix", "."],
            ),
        ),
    ),
    "lint": RepairStage(
        name="lint",
        commands=(
            RepairCommand(
                name="ruff check",
                argv=["ruff", "check", "--output-format=concise", "."],
            ),
        ),
    ),
    "test": RepairStage(
        name="test",
        commands=(
            RepairCommand(
                name="pytest",
                argv=["pytest", "-q"],
            ),
        ),
    ),
}


def build_engine(max_iters: int | None = None) -> AutoRepairEngine:
    limit = max_iters if max_iters is not None else int(os.getenv("AUTO_FIX_MAX_ITERS", "3"))
    return AutoRepairEngine(stages=STAGE_DEFINITIONS, max_iters=limit)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run commands with auto-repair capabilities")
    parser.add_argument("stage", choices=sorted(STAGE_DEFINITIONS.keys()), help="Stage to execute")
    parser.add_argument(
        "--max-iters",
        type=int,
        default=None,
        dest="max_iters",
        help="Override maximum auto-fix iterations",
    )
    args = parser.parse_args(argv)
    engine = build_engine(args.max_iters)
    return engine.run(args.stage)


if __name__ == "__main__":
    sys.exit(main())
