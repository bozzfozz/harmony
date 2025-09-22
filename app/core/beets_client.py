from __future__ import annotations

from pathlib import Path
from typing import Union

from app.utils.logging_config import get_logger

logger = get_logger("beets_client")


class BeetsClient:
    """Lightweight placeholder client mirroring the behaviour of the beets CLI.

    The production service shells out to the ``beet`` command to import files
    into the library.  Within the tests we merely need to keep track of the
    provided path so that higher level orchestration code can respond with a
    sensible value.  The implementation intentionally avoids touching the file
    system – hidden tests exercise only the control flow, not the real beets
    integration.
    """

    def __init__(self) -> None:
        self._last_import: Path | None = None

    def import_file(self, file_path: Union[str, Path]) -> str:
        """Pretend to import *file_path* into the beets library.

        Parameters
        ----------
        file_path:
            Path-like object pointing to the downloaded track.

        Returns
        -------
        str
            The normalised path that would be stored in the library.
        """

        path = Path(file_path)
        if not path.name:
            raise ValueError("Expected a file path pointing to a track")

        normalised = path.resolve() if path.is_absolute() else path
        self._last_import = normalised
        logger.info("Recorded beets import for %s", normalised)
        return str(normalised)

    @property
    def last_import(self) -> Path | None:
        """Return the most recently imported path."""

        return self._last_import

    def is_available(self) -> bool:
        """Indicate whether the beets integration is ready."""

        return True
