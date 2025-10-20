from __future__ import annotations

import subprocess
from pathlib import Path


def test_htmx_error_helper_node_suite() -> None:
    script = Path("tests/ui/js/test_htmx_error_helper.mjs").resolve()
    result = subprocess.run(
        ["node", str(script)],
        check=False,
        capture_output=True,
        text=True,
    )
    message = result.stdout + result.stderr
    assert result.returncode == 0, message
