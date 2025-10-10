from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.no_database
def test_frontend_build_generates_runtime_config() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    frontend_dir = repo_root / "frontend"
    dist_dir = frontend_dir / "dist"
    runtime_file = dist_dir / "env.runtime.js"
    dev_runtime_file = frontend_dir / "public" / "env.runtime.js"

    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    if dev_runtime_file.exists():
        dev_runtime_file.unlink()

    env = os.environ.copy()
    env.setdefault("PUBLIC_BACKEND_URL", "http://localhost:8080")
    env["PUBLIC_FEATURE_FLAGS"] = "{invalid json"

    if not (frontend_dir / "node_modules").exists():
        pytest.skip("frontend node_modules missing; run `npm ci` before executing this test")

    subprocess.run(
        ["npm", "run", "build"],
        cwd=frontend_dir,
        check=True,
        env=env,
    )

    assert runtime_file.exists(), "npm run build must render dist/env.runtime.js"
    content = runtime_file.read_text(encoding="utf-8")
    assert "featureFlags: {}" in content, "Invalid feature flag JSON should fallback to {}"
