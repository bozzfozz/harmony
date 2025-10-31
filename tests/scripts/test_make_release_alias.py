from __future__ import annotations

import subprocess


def test_make_release_alias_invokes_release_check() -> None:
    result = subprocess.run(
        ["make", "-n", "Release"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "python scripts/dev/release_check.py" in result.stdout
