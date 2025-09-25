from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence
import os
import shlex
import subprocess
import re
import tempfile
from contextlib import suppress
from urllib.parse import urlparse
from urllib.request import urlopen

from app.utils.logging_config import get_logger


class BeetsClientError(RuntimeError):
    """Raised when execution of a beets command fails."""


logger = get_logger("beets_client")


class BeetsClient:
    """Thin wrapper around the :mod:`beets` CLI."""

    def __init__(
        self,
        env: Mapping[str, str] | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._env = {**os.environ, **env} if env else None
        self._timeout = timeout

    def _run(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        """Execute *args* with the ``beet`` CLI and return the process result."""

        command = " ".join(args)
        logger.info("Executing beets command: %s", command)

        try:
            run_kwargs = dict(capture_output=True, text=True, check=True)
            if self._env is not None:
                run_kwargs["env"] = self._env
            result = subprocess.run(list(args), timeout=self._timeout, **run_kwargs)
        except subprocess.TimeoutExpired as exc:
            logger.error("Beets command timed out: %s", command)
            raise BeetsClientError("Command timed out") from exc
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            if stderr:
                logger.error("Beets command failed (%s): %s", command, stderr)
            else:
                logger.error("Beets command failed (%s)", command)
            raise BeetsClientError(stderr or f"Command '{command}' failed") from exc
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unexpected error while executing '%s'", command)
            raise BeetsClientError(f"Unexpected error running '{command}'") from exc

        stdout = (result.stdout or "").strip()
        if stdout:
            logger.info("Beets command output: %s", stdout)

        return result

    def import_file(
        self, path: str | Path, quiet: bool = True, autotag: bool = True
    ) -> str:
        """Import *path* into the beets library using ``beet import``."""

        args: list[str] = ["beet", "import"]
        if quiet:
            args.append("-q")
        if not autotag:
            args.append("-A")
        args.append(str(path))

        result = self._run(args)
        return (result.stdout or "").strip()

    def update(self, path: str | Path | None = None) -> str:
        """Run ``beet update`` optionally scoped to *path*."""

        args: list[str] = ["beet", "update"]
        if path is not None:
            args.append(str(path))

        result = self._run(args)
        return (result.stdout or "").strip()

    def list_albums(self) -> list[str]:
        """Return a list of album names from ``beet ls -a``."""

        result = self._run(["beet", "ls", "-a"])
        stdout = result.stdout or ""
        albums = [line for line in stdout.splitlines() if line.strip()]
        logger.debug("Parsed albums: %s", albums)
        return albums

    def list_tracks(self) -> list[str]:
        """Return a list of track titles from ``beet ls -f '$title'``."""

        result = self._run(["beet", "ls", "-f", "$title"])
        stdout = result.stdout or ""
        tracks = [line for line in stdout.splitlines() if line.strip()]
        logger.debug("Parsed tracks: %s", tracks)
        return tracks

    def stats(self) -> dict[str, str]:
        """Return parsed key/value pairs from ``beet stats``."""

        result = self._run(["beet", "stats"])
        stdout = result.stdout or ""
        stats: dict[str, str] = {}
        for line in stdout.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key:
                stats[key] = value
        logger.debug("Parsed stats: %s", stats)
        return stats

    def is_available(self) -> bool:
        """Return ``True`` when the ``beet`` CLI is reachable."""

        try:
            self._run(["beet", "version"])
        except BeetsClientError:
            return False
        return True

    def remove(self, query: str, force: bool = False) -> dict[str, object]:
        """Remove items matching *query* using ``beet remove``."""

        query_args = self._parse_query(query)
        args: list[str] = ["beet", "remove"]
        if force:
            args.append("-f")
        args.extend(query_args)

        result = self._run(args)
        parsed = self._parse_count_output(result.stdout, "Removed", "removed")
        logger.debug("Parsed remove output: %s", parsed)
        return parsed

    def move(self, query: str | None = None) -> dict[str, object]:
        """Move items in the library using ``beet move`` with an optional query."""

        args: list[str] = ["beet", "move"]
        if query:
            args.extend(self._parse_query(query))

        result = self._run(args)
        parsed = self._parse_count_output(result.stdout, "Moved", "moved")
        logger.debug("Parsed move output: %s", parsed)
        return parsed

    def write(self, query: str | None = None) -> dict[str, object]:
        """Write tags for items using ``beet write`` with an optional query."""

        args: list[str] = ["beet", "write"]
        if query:
            args.extend(self._parse_query(query))

        result = self._run(args)
        parsed = self._parse_count_output(result.stdout, "Wrote", "written")
        logger.debug("Parsed write output: %s", parsed)
        return parsed

    def update_metadata(self, file_path: str | Path, tags: Mapping[str, object]) -> None:
        """Persist *tags* to *file_path* via ``beet modify`` and ``beet write``."""

        path = Path(file_path)
        assignments = [
            f"{key}={value}"
            for key, value in tags.items()
            if value not in {None, ""}
        ]
        if assignments:
            modify_args: list[str] = ["beet", "modify", "-y", str(path)]
            modify_args.extend(assignments)
            self._run(modify_args)

        write_args: list[str] = ["beet", "write", "-y", str(path)]
        if assignments:
            for key in tags:
                write_args.extend(["-f", key])
        self._run(write_args)

    def embed_artwork(self, file_path: str | Path, image_url: str) -> None:
        """Download *image_url* and embed it into *file_path* via ``beet embedart``."""

        if not image_url:
            raise BeetsClientError("image_url must not be empty")

        suffix = Path(urlparse(image_url).path or "").suffix or ".jpg"
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp_path = Path(tmp.name)
                with urlopen(image_url) as response:
                    tmp.write(response.read())

            args = ["beet", "embedart", "-f", str(tmp_path), str(Path(file_path))]
            self._run(args)
        finally:
            if tmp_path is not None:
                with suppress(FileNotFoundError):
                    tmp_path.unlink()

    def fields(self) -> list[str]:
        """Return the list of available fields from ``beet fields``."""

        result = self._run(["beet", "fields"])
        stdout = result.stdout or ""
        fields = [line for line in stdout.splitlines() if line.strip()]
        logger.debug("Parsed fields: %s", fields)
        return fields

    def query(
        self, query: str, fmt: str = "$artist - $album - $title"
    ) -> list[str]:
        """Return formatted items for *query* via ``beet ls``."""

        query_args = self._parse_query(query)
        args: list[str] = ["beet", "ls", "-f", fmt]
        args.extend(query_args)

        result = self._run(args)
        stdout = result.stdout or ""
        results = [line for line in stdout.splitlines() if line.strip()]
        logger.debug("Parsed query results: %s", results)
        return results

    @staticmethod
    def _parse_query(query: str) -> list[str]:
        if not query or not query.strip():
            raise BeetsClientError("Query must not be empty")
        try:
            parts = shlex.split(query)
        except ValueError as exc:  # pragma: no cover - defensive
            raise BeetsClientError(f"Invalid query syntax: {exc}") from exc
        return parts

    @staticmethod
    def _parse_count_output(
        stdout: str | None, verb: str, key: str
    ) -> dict[str, object]:
        output = (stdout or "").strip()
        pattern = rf"{verb} (\d+) items"
        match = re.search(pattern, output)
        if match:
            count = int(match.group(1))
            return {"success": True, key: count}
        return {"success": True, "output": output}
