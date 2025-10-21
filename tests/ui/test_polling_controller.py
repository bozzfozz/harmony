from __future__ import annotations

from pathlib import Path
import subprocess


def test_polling_controller_node_suite() -> None:
    script = Path("tests/ui/js/test_polling_controller.mjs").resolve()
    result = subprocess.run(
        ["node", str(script)],
        check=False,
        capture_output=True,
        text=True,
    )
    message = result.stdout + result.stderr
    assert result.returncode == 0, message
