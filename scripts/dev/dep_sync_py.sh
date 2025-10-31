#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
cd "$ROOT_DIR"

if ! command -v uv >/dev/null 2>&1; then
  echo "[dep-sync] uv is required to run dependency guards." >&2
  exit 1
fi

export_requirements() {
  local output_path=$1
  shift

  local export_cmd=(uv export --locked --format requirements.txt --output-file "$output_path" "$@")

  if ! "${export_cmd[@]}" >/dev/null 2>&1; then
    rm -f "$output_path"

    if [[ -n ${CI:-} ]]; then
      echo "[dep-sync] Failed to export requirements from uv.lock. Run 'uv lock' locally and commit the result." >&2
      return 1
    fi

    echo "[dep-sync] Unable to export requirements via 'uv export'; falling back to parsing uv.lock locally." >&2
    if ! python - "$output_path" "$@" <<'PY'
import sys
from pathlib import Path
import tomllib

OUTPUT = Path(sys.argv[1])
args = sys.argv[2:]

include_default = True
groups: list[str] = []
i = 0
while i < len(args):
    arg = args[i]
    if arg == "--only-group":
        include_default = False
        i += 1
        if i >= len(args):
            print("[dep-sync] Missing value for --only-group.", file=sys.stderr)
            raise SystemExit(1)
        groups.append(args[i])
    elif arg == "--group":
        i += 1
        if i >= len(args):
            print("[dep-sync] Missing value for --group.", file=sys.stderr)
            raise SystemExit(1)
        groups.append(args[i])
    elif arg in {"--no-default-groups", "--no-dev"}:
        include_default = False
    else:
        print(f"[dep-sync] Unsupported export option in fallback: {arg}", file=sys.stderr)
        raise SystemExit(1)
    i += 1

if include_default:
    groups.insert(0, "harmony")
if not groups:
    groups.append("harmony")

with open("uv.lock", "rb") as f:
    data = tomllib.load(f)

packages = {pkg["name"]: pkg for pkg in data.get("package", [])}

def format_requirement(pkg: dict[str, object]) -> str:
    name = pkg["name"]
    source = pkg.get("source", {})
    if not isinstance(source, dict):
        raise SystemExit(f"[dep-sync] Invalid source metadata for package: {name}")

    version = pkg.get("version")
    if not isinstance(version, str):
        raise SystemExit(f"[dep-sync] Missing version for package: {name}")

    if "registry" in source:
        return f"{name}=={version}"

    if "git" in source:
        rev = source.get("rev")
        spec = f"git+{source['git']}"
        if isinstance(rev, str):
            spec = f"{spec}@{rev}"
        return f"{name} @ {spec}"

    if "url" in source:
        return f"{name} @ {source['url']}"

    if "path" in source:
        return f"{name} @ {source['path']}"

    raise SystemExit(f"[dep-sync] Unsupported source for package '{name}' in fallback export.")

requirements: dict[str, str] = {}
visited: set[str] = set()

def traverse(root: str) -> None:
    stack = [root]
    while stack:
        name = stack.pop()
        if name in visited:
            continue
        visited.add(name)
        pkg = packages.get(name)
        if pkg is None:
            continue
        for dep in pkg.get("dependencies", []):
            dep_name = dep.get("name")
            if isinstance(dep_name, str):
                stack.append(dep_name)

        source = pkg.get("source", {})
        if isinstance(source, dict) and "editable" in source:
            continue

        requirements[name] = format_requirement(pkg)

for group in groups:
    traverse(group)

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
with OUTPUT.open("w", encoding="utf-8") as handle:
    for name in sorted(requirements):
        handle.write(f"{requirements[name]}\n")
PY
    then
      return 1
    fi
  fi

  if [[ ! -s "$output_path" ]]; then
    rm -f "$output_path"
    return 1
  fi

  return 0
}

tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT

runtime_requirements="$tmp_dir/runtime.txt"
if ! export_requirements "$runtime_requirements"; then
  echo "[dep-sync] Failed to export runtime dependencies via 'uv export'." >&2
  exit 1
fi

declare -a extra_requirement_files=()

dev_requirements="$tmp_dir/dev.txt"
if export_requirements "$dev_requirements" --only-group dev; then
  extra_requirement_files+=("$dev_requirements")
fi

strict=false
case "${DOCTOR_PIP_REQS:-}" in
  1|true|TRUE|True|yes|YES|on|ON)
    strict=true
    ;;
esac

run_with_pip_check_reqs() {
  if ! uv run --locked --with pip-check-reqs "$@"; then
    return 1
  fi
  return 0
}

if ! run_with_pip_check_reqs pip-missing-reqs app; then
  if [[ "$strict" == true ]]; then
    echo "[dep-sync] pip-missing-reqs failed (DOCTOR_PIP_REQS=1)." >&2
    exit 1
  fi
  echo "[dep-sync] Unable to run pip-missing-reqs; skipping missing-requirements scan." >&2
fi

requirements_args=(--requirements-file "$runtime_requirements")
for req_file in "${extra_requirement_files[@]}"; do
  requirements_args+=(--requirements-file "$req_file")
done

if ! run_with_pip_check_reqs pip-extra-reqs "${requirements_args[@]}" app; then
  if [[ "$strict" == true ]]; then
    echo "[dep-sync] pip-extra-reqs failed (DOCTOR_PIP_REQS=1)." >&2
    exit 1
  fi
  echo "[dep-sync] Unable to run pip-extra-reqs; skipping extra-requirements scan." >&2
fi
