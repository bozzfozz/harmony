from __future__ import annotations

from pathlib import Path

from app.config import load_runtime_env, override_runtime_env


def _load_env(
    config_path: Path, *, base: dict[str, str] | None = None, env_file: Path | None = None
) -> dict[str, str]:
    base_env = dict(base or {})
    base_env["HARMONY_CONFIG_FILE"] = str(config_path)
    env = load_runtime_env(env_file=env_file, base_env=base_env)
    return env


def test_load_runtime_env_creates_config_file(tmp_path: Path) -> None:
    config_path = tmp_path / "harmony.yml"
    env_file = tmp_path / "env"
    env = _load_env(config_path, env_file=env_file)
    try:
        assert config_path.exists()
        assert env["APP_PORT"] == "8080"
        contents = config_path.read_text(encoding="utf-8")
        assert "APP_PORT: 8080" in contents
    finally:
        override_runtime_env(None)


def test_yaml_values_override_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "harmony.yml"
    env_file = tmp_path / "env"
    _load_env(config_path, env_file=env_file)
    contents = config_path.read_text(encoding="utf-8")
    contents = contents.replace("APP_PORT: 8080", "APP_PORT: 9090")
    contents = contents.replace(
        "INTEGRATIONS_ENABLED: [spotify, slskd]",
        "INTEGRATIONS_ENABLED: [spotify, slskd, demo]",
    )
    config_path.write_text(contents, encoding="utf-8")
    try:
        override_runtime_env(None)
        env = _load_env(config_path, env_file=env_file)
        assert env["APP_PORT"] == "9090"
        assert env["INTEGRATIONS_ENABLED"] == "spotify,slskd,demo"
    finally:
        override_runtime_env(None)


def test_environment_overrides_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "harmony.yml"
    env_file = tmp_path / "env"
    _load_env(config_path, env_file=env_file)
    contents = config_path.read_text(encoding="utf-8")
    config_path.write_text(contents.replace("APP_PORT: 8080", "APP_PORT: 7000"), encoding="utf-8")
    try:
        override_runtime_env(None)
        env = _load_env(config_path, base={"APP_PORT": "8100"}, env_file=env_file)
        assert env["APP_PORT"] == "8100"
    finally:
        override_runtime_env(None)
