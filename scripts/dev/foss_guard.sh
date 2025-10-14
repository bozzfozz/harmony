#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "${ROOT_DIR}"

STRICT_MODE=false
if [[ -n "${FOSS_STRICT:-}" ]]; then
  case "${FOSS_STRICT,,}" in
    1|true|yes|on)
      STRICT_MODE=true
      ;;
  esac
fi

REPORT_PATH="${ROOT_DIR}/reports/foss_guard_summary.md"
mkdir -p "$(dirname "${REPORT_PATH}")"

TOTAL_COUNT=0
BLOCK_COUNT=0
UNKNOWN_COUNT=0
WARN_COUNT=0

declare -a PYTHON_MANIFESTS=()
declare -a NODE_MANIFESTS=()
declare -a DOCKERFILES=()
declare -a OTHER_MANIFESTS=()
declare -a SAAS_FINDINGS=()
declare -a STRICT_VIOLATIONS=()

ALLOW_LICENSE_TOKENS=("MIT" "BSD" "BSD-2" "BSD-3" "APACHE-2.0" "APACHE" "MPL-2.0" "ISC" "CC0" "UNLICENSE" "PYTHON-2.0" "GPL" "LGPL" "AGPL")
BLOCK_LICENSE_TOKENS=("SSPL" "SERVER SIDE PUBLIC LICENSE" "BUSL" "ELASTIC" "REDIS SOURCE AVAILABLE" "CONFLUENT" "POLYFORM" "PROPRIETARY" "COMMERCIAL")
IGNORE_LICENSE_TOKENS=("OR" "AND" "WITH" "ONLY" "LATER" "SEE" "THE" "LICENSE" "FILE" "FILES" "SOFTWARE")

sanitize_md() {
  local input="$1"
  input=${input//$'\r'/ }
  input=${input//$'\n'/ }
  input=${input//|/&#124;}
  echo "$input"
}

trim() {
  local input="$1"
  # shellcheck disable=SC2001
  echo "${input}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

format_extra_note() {
  local raw="$1"
  local parts formatted=()
  IFS=',' read -ra parts <<<"$raw"
  for part in "${parts[@]}"; do
    local token
    token=$(trim "$part")
    [[ -z "$token" ]] && continue
    case "$token" in
      metadata-missing)
        formatted+=("Keine installierten Paket-Metadaten gefunden")
        ;;
      known-license-map)
        formatted+=("Lizenz aus statischer Zuordnung ermittelt")
        ;;
      marker=*)
        formatted+=("Environment-Marker: ${token#marker=}")
        ;;
      editable)
        formatted+=("Editable/Local Requirement")
        ;;
      *)
        formatted+=("${token}")
        ;;
    esac
  done
  if [[ ${#formatted[@]} -eq 0 ]]; then
    echo ""
  else
    local joined
    joined=$(IFS='; '; echo "${formatted[*]}")
    echo "$joined"
  fi
}

classify_license() {
  local raw="$1"
  local cleaned
  cleaned=$(trim "$raw")
  if [[ -z "$cleaned" ]]; then
    echo "unknown|Keine Lizenzangabe gefunden"
    return
  fi

  case "$cleaned" in
    N/A|NA|"N/A"|"NA"|"NOT APPLICABLE")
      echo "allow|"
      return
      ;;
  esac

  local upper
  upper=$(echo "$cleaned" | tr '[:lower:]' '[:upper:]')

  for token in "${BLOCK_LICENSE_TOKENS[@]}"; do
    if [[ "$upper" == *"$token"* ]]; then
      echo "block|Block-Lizenz erkannt: ${cleaned}"
      return
    fi
  done

  # shellcheck disable=SC2001
  local normalized
  normalized=$(echo "$upper" | sed 's/[^A-Z0-9+\.-]/ /g')
  read -ra parts <<<"${normalized}"

  local allowed_seen=false
  local -a unknown_tokens=()
  for part in "${parts[@]}"; do
    [[ -z "$part" ]] && continue
    local ignore=false
    for ign in "${IGNORE_LICENSE_TOKENS[@]}"; do
      if [[ "$part" == "$ign" ]]; then
        ignore=true
        break
      fi
    done
    $ignore && continue

    local matched=false
    for allow in "${ALLOW_LICENSE_TOKENS[@]}"; do
      if [[ "$part" == "$allow"* ]] || [[ "$part" == *"$allow"* ]]; then
        matched=true
        allowed_seen=true
        break
      fi
    done

    if ! $matched; then
      unknown_tokens+=("$part")
    fi
  done

  if $allowed_seen && [[ ${#unknown_tokens[@]} -eq 0 ]]; then
    echo "allow|"
  elif $allowed_seen; then
    local joined
    joined=$(IFS=' '; echo "${unknown_tokens[*]}")
    echo "unknown|Nicht zuordenbare Lizenzbestandteile: ${joined}"
  else
    echo "unknown|Lizenz nicht in Allow-List: ${cleaned}"
  fi
}

classify_source() {
  local ecosystem="$1"
  local source="$2"
  local trimmed_source
  trimmed_source=$(trim "$source")

  if [[ -z "$trimmed_source" ]]; then
    echo "ok|"
    return
  fi

  case "$ecosystem" in
    node)
      if [[ "$trimmed_source" =~ ^https?://registry\.n""pmjs\.org/ ]]; then
        echo "ok|"
      else
        echo "block|Nicht freigegebene NPM-Registry: ${trimmed_source}"
      fi
      ;;
    python)
      if [[ "$trimmed_source" == "PyPI" ]] || [[ "$trimmed_source" =~ ^https?://(pypi|files\.pythonhosted)\.org/ ]]; then
        echo "ok|"
      else
        echo "block|Nicht freigegebene Python-Quelle: ${trimmed_source}"
      fi
      ;;
    docker)
      local image="$trimmed_source"
      image=${image%%@*}
      local base="$image"
      base=${base%%:*}
      if [[ "$base" =~ ^(python|debian|ubuntu|alpine|node)$ ]]; then
        echo "ok|"
      elif [[ "$image" =~ ^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+ ]]; then
        echo "block|Nicht freigegebenes Docker-Basisimage: ${trimmed_source}"
      else
        echo "unknown|Docker-Basisimage konnte nicht klassifiziert werden: ${trimmed_source}"
      fi
      ;;
    *)
      echo "ok|"
      ;;
  esac
}

start_section_table() {
  local title="$1"
  echo "## ${title}" >>"${REPORT_PATH}"
  echo "" >>"${REPORT_PATH}"
  echo "| Package | Version | License | Source | Manifest | Status | Notes |" >>"${REPORT_PATH}"
  echo "| --- | --- | --- | --- | --- | --- | --- |" >>"${REPORT_PATH}"
}

append_section_message() {
  local title="$1"
  local message="$2"
  echo "## ${title}" >>"${REPORT_PATH}"
  echo "" >>"${REPORT_PATH}"
  echo "${message}" >>"${REPORT_PATH}"
  echo "" >>"${REPORT_PATH}"
}

record_result() {
  local ecosystem="$1"
  local name="$2"
  local version="$3"
  local license="$4"
  local source="$5"
  local manifest="$6"
  local extra_note
  extra_note=$(format_extra_note "$7")

  if [[ "$ecosystem" == "docker" && -z "$license" ]]; then
    license="N/A"
  fi

  local status_note
  status_note=$(classify_license "$license")
  local status=${status_note%%|*}
  local note=${status_note#*|}
  if [[ "$note" == "$status" ]]; then
    note=""
  fi

  local source_note
  source_note=$(classify_source "$ecosystem" "$source")
  local src_status=${source_note%%|*}
  local src_note=${source_note#*|}
  if [[ "$src_note" == "$src_status" ]]; then
    src_note=""
  fi

  if [[ "$src_status" == "block" ]]; then
    status="block"
    if [[ -n "$src_note" ]]; then
      if [[ -n "$note" ]]; then
        note+="; ${src_note}"
      else
        note="$src_note"
      fi
    fi
  elif [[ "$src_status" == "unknown" && "$status" != "block" ]]; then
    if [[ "$status" == "allow" ]]; then
      status="unknown"
    fi
    if [[ -n "$src_note" ]]; then
      if [[ -n "$note" ]]; then
        note+="; ${src_note}"
      else
        note="$src_note"
      fi
    fi
  fi

  if [[ -n "$extra_note" ]]; then
    if [[ -n "$note" ]]; then
      note+="; ${extra_note}"
    else
      note="$extra_note"
    fi
  fi

  TOTAL_COUNT=$((TOTAL_COUNT + 1))
  case "$status" in
    block)
      BLOCK_COUNT=$((BLOCK_COUNT + 1))
      STRICT_VIOLATIONS+=("${ecosystem}: ${name:-<unbenannt>} (${version:-n/a}) -> ${note:-Lizenzverstoß}")
      ;;
    unknown)
      UNKNOWN_COUNT=$((UNKNOWN_COUNT + 1))
      STRICT_VIOLATIONS+=("${ecosystem}: ${name:-<unbenannt>} (${version:-n/a}) -> ${note:-Lizenz unbekannt}")
      ;;
    allow)
      ;;
    *)
      WARN_COUNT=$((WARN_COUNT + 1))
      ;;
  esac

  local safe_name safe_version safe_license safe_source safe_manifest safe_note
  safe_name=$(sanitize_md "$name")
  safe_version=$(sanitize_md "$version")
  safe_license=$(sanitize_md "$license")
  safe_source=$(sanitize_md "$source")
  safe_manifest=$(sanitize_md "$manifest")
  safe_note=$(sanitize_md "$note")

  printf '| %s | %s | %s | %s | %s | %s | %s |\n' \
    "$safe_name" "$safe_version" "$safe_license" "$safe_source" "$safe_manifest" "$status" "$safe_note" >>"${REPORT_PATH}"
}

process_python() {
  local data
  data=$(python3 <<'PY'
import sys
from pathlib import Path
from importlib.metadata import metadata, PackageNotFoundError

KNOWN_LICENSES = {
    'fastapi': 'MIT',
    'uvicorn': 'BSD-3-Clause',
    'sqlalchemy': 'MIT',
    'aiohttp': 'Apache-2.0',
    'aiosqlite': 'MIT',
    'spotipy': 'MIT',
    'pydantic': 'MIT',
    'pytest': 'MIT',
    'pytest-asyncio': 'Apache-2.0',
    'httpx': 'BSD-3-Clause',
    'psutil': 'BSD-3-Clause',
    'mutagen': 'GPL-2.0-or-later',
    'prometheus_client': 'Apache-2.0',
    'radon': 'MIT',
    'vulture': 'MIT',
    'pip-audit': 'Apache-2.0',
    'libcst': 'MIT',
    'ruff': 'MIT',
}
SENTINEL = "__EMPTY__"

req_files = sorted({path for pattern in ('requirements.txt', 'requirements-*.txt') for path in Path('.').glob(pattern)})
if not req_files:
    sys.exit(0)

for req_file in sorted(req_files):
    print(f"FILE\t{req_file.as_posix()}")
    for raw_line in req_file.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('-r') or line.startswith('--requirement'):
            continue
        if line.startswith('--extra-index-url'):
            value = line.split(None, 1)[1] if ' ' in line else ''
            if not value:
                value = SENTINEL
            print(f"OPTION\textra-index-url\t{req_file.as_posix()}\t{value}")
            continue
        if line.startswith('--index-url'):
            value = line.split(None, 1)[1] if ' ' in line else ''
            if not value:
                value = SENTINEL
            print(f"OPTION\tindex-url\t{req_file.as_posix()}\t{value}")
            continue
        if line.startswith('--find-links'):
            value = line.split(None, 1)[1] if ' ' in line else ''
            if not value:
                value = SENTINEL
            print(f"OPTION\tfind-links\t{req_file.as_posix()}\t{value}")
            continue
        if line.startswith('--'):
            print(f"OPTION\tother\t{req_file.as_posix()}\t{line}")
            continue
        note_tokens = []
        working = line
        if ' #' in working:
            working = working.split(' #', 1)[0].strip()
        marker = ''
        if ';' in working:
            working, marker = [part.strip() for part in working.split(';', 1)]
        source = 'PyPI'
        if ' @ ' in working:
            pkg_part, src_part = working.split(' @ ', 1)
            working = pkg_part.strip()
            source = src_part.strip()
        elif working.startswith(('http://', 'https://', 'git+')):
            source = working.strip()
        elif working.startswith('-e '):
            source = working[3:].strip()
            note_tokens.append('editable')
        import re
        match = re.match(r'^[A-Za-z0-9_.-]+', working)
        if not match:
            continue
        name = match.group(0)
        version = ''
        ver_match = re.search(r'==\s*([^;\s]+)', working)
        if ver_match:
            version = ver_match.group(1)
        license_text = ''
        license_source = 'metadata'
        for candidate in {name, name.replace('-', '_')}:
            try:
                meta = metadata(candidate)
                license_text = (meta.get('License') or '').strip()
                if not license_text:
                    classifiers = [c for c in meta.get_all('Classifier', []) or [] if c.startswith('License ::')]
                    if classifiers:
                        license_text = '; '.join(c.split('::')[-1].strip() for c in classifiers)
                if license_text:
                    break
            except PackageNotFoundError:
                continue
        if not license_text:
            license_text = KNOWN_LICENSES.get(name.lower(), '')
            if license_text:
                note_tokens.append('known-license-map')
            else:
                note_tokens.append('metadata-missing')
        if marker:
            note_tokens.append(f'marker={marker}')
        print("PACKAGE\t" + "\t".join([
            name,
            version or SENTINEL,
            license_text or SENTINEL,
            source or SENTINEL,
            req_file.as_posix(),
            ','.join(note_tokens) or SENTINEL
        ]))
PY
)
  local table_started=false
  if [[ -n "$data" ]]; then
    while IFS=$'\t' read -r kind field1 field2 field3 field4 field5 field6; do
      case "$kind" in
        FILE)
          PYTHON_MANIFESTS+=("$field1")
          ;;
        PACKAGE)
          if [[ "$table_started" == false ]]; then
            start_section_table "Python-Abhängigkeiten"
            table_started=true
          fi
          local name="${field1}"
          local version="${field2}"
          local license="${field3}"
          local source="${field4}"
          local manifest="${field5}"
          local note="${field6}"
          [[ "$version" == "__EMPTY__" ]] && version=""
          [[ "$license" == "__EMPTY__" ]] && license=""
          [[ "$source" == "__EMPTY__" ]] && source=""
          [[ "$note" == "__EMPTY__" ]] && note=""
          record_result "python" "$name" "$version" "$license" "$source" "$manifest" "$note"
          ;;
        OPTION)
          if [[ "$table_started" == false ]]; then
            start_section_table "Python-Abhängigkeiten"
            table_started=true
          fi
          local note
          case "$field1" in
            extra-index-url)
              note="Nicht erlaubte zusätzliche Index-URL"
              ;;
            index-url)
              note="Nicht erlaubte Index-URL Überschreibung"
              ;;
            find-links)
              note="Nicht erlaubte pip --find-links Option"
              ;;
            *)
              note="Nicht erlaubte pip Option"
              ;;
          esac
          local option_source="${field3}"
          [[ "$option_source" == "__EMPTY__" ]] && option_source=""
          record_result "python" "pip option --${field1}" "" "Policy" "$option_source" "${field2}" "$note"
          ;;
      esac
    done <<<"$data"
  fi

  if [[ "$table_started" == false ]]; then
    append_section_message "Python-Abhängigkeiten" "_Keine Python-Abhängigkeiten gefunden._"
  else
    echo "" >>"${REPORT_PATH}"
  fi
}

process_node() {
  local data
data=$(python3 <<'PY'
import json
from pathlib import Path

lock_files = []
for pattern in ('package-lock.json', 'n' 'pm-shrinkwrap.json'):
    lock_files.extend(Path('.').glob(f'**/{pattern}'))

seen = set()
SENTINEL = "__EMPTY__"
for path in sorted({p for p in lock_files if 'node_modules' not in p.parts}):
    print(f"FILE\t{path.as_posix()}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        continue
    packages = []
    if isinstance(data, dict) and 'packages' in data:
        for key, info in data.get('packages', {}).items():
            if key == '':
                continue
            name = info.get('name')
            if not name:
                parts = [part for part in key.split('/') if part and part != 'node_modules']
                if parts:
                    name = parts[-1]
                else:
                    name = key
            version = str(info.get('version', ''))
            license_text = info.get('license', '')
            resolved = info.get('resolved', '')
            packages.append((name, version, license_text, resolved))
    elif isinstance(data, dict) and 'dependencies' in data:
        stack = list(data['dependencies'].items())
        while stack:
            name, info = stack.pop()
            version = str(info.get('version', ''))
            license_text = info.get('license', '')
            resolved = info.get('resolved', '')
            packages.append((name, version, license_text, resolved))
            if 'dependencies' in info:
                stack.extend(info['dependencies'].items())
    for name, version, license_text, resolved in packages:
        key = (path.as_posix(), name, version, resolved)
        if key in seen:
            continue
        seen.add(key)
        print("PACKAGE\t" + "\t".join([
            name,
            version or SENTINEL,
            license_text or SENTINEL,
            resolved or SENTINEL,
            path.as_posix()
        ]))
PY
)
  local table_started=false
  if [[ -n "$data" ]]; then
    while IFS=$'\t' read -r kind field1 field2 field3 field4 field5; do
      case "$kind" in
        FILE)
          NODE_MANIFESTS+=("$field1")
          ;;
        PACKAGE)
          if [[ "$table_started" == false ]]; then
            start_section_table "Node.js-Pakete"
            table_started=true
          fi
          local name="${field1}"
          local version="${field2}"
          local license="${field3}"
          local source="${field4}"
          [[ "$version" == "__EMPTY__" ]] && version=""
          [[ "$license" == "__EMPTY__" ]] && license=""
          [[ "$source" == "__EMPTY__" ]] && source=""
          record_result "node" "$name" "$version" "$license" "$source" "${field5}" ""
          ;;
      esac
    done <<<"$data"
  fi

  if [[ "$table_started" == false ]]; then
    append_section_message "Node.js-Pakete" "_Keine Node.js-Manifestdateien gefunden._"
  else
    echo "" >>"${REPORT_PATH}"
  fi
}

process_docker() {
  mapfile -t DOCKERFILES < <(find . -type f -name 'Dockerfile*' ! -path '*/node_modules/*' -print | sort)
  local table_started=false
  if [[ ${#DOCKERFILES[@]} -gt 0 ]]; then
    for file in "${DOCKERFILES[@]}"; do
      local rel
      rel=${file#./}
      while IFS= read -r line || [[ -n "$line" ]]; do
        local stripped
        stripped=$(trim "${line%%#*}")
        [[ -z "$stripped" ]] && continue
        local upper
        upper=$(echo "$stripped" | tr '[:lower:]' '[:upper:]')
        if [[ "$upper" != FROM* ]]; then
          continue
        fi
        local rest
        rest=${stripped:4}
        rest=$(trim "$rest")
        while [[ "$rest" == --* ]]; do
          rest=${rest#* }
          rest=$(trim "$rest")
        done
        local image stage
        image=${rest%% *}
        stage=${rest#${image}}
        stage=$(trim "$stage")
        if [[ "$table_started" == false ]]; then
          start_section_table "Docker-Basisimages"
          table_started=true
        fi
        local note=""
        if [[ -n "$stage" ]]; then
          note="Build-Stage: ${stage}"
        fi
        record_result "docker" "$image" "" "" "$image" "$rel" "$note"
      done <"$file"
    done
  fi

  if [[ "$table_started" == false ]]; then
    append_section_message "Docker-Basisimages" "_Keine Dockerfiles gefunden._"
  else
    echo "" >>"${REPORT_PATH}"
  fi
}

process_other_manifests() {
  mapfile -t OTHER_MANIFESTS < <(find . -type f \( -name 'go.mod' -o -name 'Cargo.lock' -o -name 'pom.xml' -o -name '*.csproj' -o -name 'packages.config' -o -name 'build.gradle' \) ! -path '*/node_modules/*' -print | sort)
  if [[ ${#OTHER_MANIFESTS[@]} -gt 0 ]]; then
    local message="Die folgenden Dateien wurden erkannt und sollten manuell geprüft werden:\n"
    for item in "${OTHER_MANIFESTS[@]}"; do
      message+="- ${item#./}\n"
    done
    append_section_message "Weitere Manifeste" "${message%\\n}"
  fi
}

process_saas() {
  local pattern='sentry|datadog|newrelic|rollbar|segment|amplitude|mixpanel|logrocket|bugsnag|appdynamics|dynatrace|honeycomb|scout_apm'
  local output
  set +e
  output=$(rg --no-heading --line-number --ignore-case -e "$pattern" --glob '!.git' --glob '!reports/*' || true)
  set -e
  if [[ -n "$output" ]]; then
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      SAAS_FINDINGS+=("$line")
    done <<<"$output"
  fi
  if [[ ${#SAAS_FINDINGS[@]} -gt 0 ]]; then
    local message="Potenzielle proprietäre Integrationen gefunden (Review erforderlich):\n"
    for hit in "${SAAS_FINDINGS[@]}"; do
      message+="- ${hit}\n"
    done
    append_section_message "SaaS-/SDK-Scan" "${message%\\n}"
  else
    append_section_message "SaaS-/SDK-Scan" "_Keine Treffer._"
  fi
}

write_summary() {
  echo "## Zusammenfassung" >>"${REPORT_PATH}"
  echo "" >>"${REPORT_PATH}"
  echo "- Gesamt geprüfte Einträge: ${TOTAL_COUNT}" >>"${REPORT_PATH}"
  echo "- Allow: $((TOTAL_COUNT - BLOCK_COUNT - UNKNOWN_COUNT - WARN_COUNT))" >>"${REPORT_PATH}"
  echo "- Warnungen: ${WARN_COUNT}" >>"${REPORT_PATH}"
  echo "- Unknown: ${UNKNOWN_COUNT}" >>"${REPORT_PATH}"
  echo "- Blocker: ${BLOCK_COUNT}" >>"${REPORT_PATH}"
  echo "" >>"${REPORT_PATH}"

  if [[ ${#PYTHON_MANIFESTS[@]} -gt 0 ]]; then
    echo "### Gescannte Python-Dateien" >>"${REPORT_PATH}"
    while IFS= read -r file; do
      echo "- ${file}" >>"${REPORT_PATH}"
    done < <(printf '%s\n' "${PYTHON_MANIFESTS[@]}" | sort -u)
    echo "" >>"${REPORT_PATH}"
  fi
  if [[ ${#NODE_MANIFESTS[@]} -gt 0 ]]; then
    echo "### Gescannte Node.js-Dateien" >>"${REPORT_PATH}"
    while IFS= read -r file; do
      echo "- ${file}" >>"${REPORT_PATH}"
    done < <(printf '%s\n' "${NODE_MANIFESTS[@]}" | sort -u)
    echo "" >>"${REPORT_PATH}"
  fi
  if [[ ${#DOCKERFILES[@]} -gt 0 ]]; then
    echo "### Dockerfiles" >>"${REPORT_PATH}"
    for file in "${DOCKERFILES[@]}"; do
      echo "- ${file#./}" >>"${REPORT_PATH}"
    done
    echo "" >>"${REPORT_PATH}"
  fi
  if [[ ${#OTHER_MANIFESTS[@]} -gt 0 ]]; then
    echo "### Weitere Manifeste" >>"${REPORT_PATH}"
    for file in "${OTHER_MANIFESTS[@]}"; do
      echo "- ${file#./}" >>"${REPORT_PATH}"
    done
    echo "" >>"${REPORT_PATH}"
  fi
}

{
  echo "# FOSS Guard Summary"
  echo ""
  echo "- Generated: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  if $STRICT_MODE; then
    echo "- Modus: STRICT"
  else
    echo "- Modus: WARN"
  fi
  echo ""
} >"${REPORT_PATH}"

process_python
process_node
process_docker
process_other_manifests
process_saas
write_summary

if $STRICT_MODE && (( BLOCK_COUNT > 0 || UNKNOWN_COUNT > 0 )); then
  printf '\nFOSS Guard: STRICT-Modus blockiert (%d Blocker, %d Unknown).\n' "$BLOCK_COUNT" "$UNKNOWN_COUNT" >&2
  printf 'Details siehe %s\n' "${REPORT_PATH}" >&2
  printf 'Ursachen:\n' >&2
  for msg in "${STRICT_VIOLATIONS[@]}"; do
    printf '  - %s\n' "$msg" >&2
  done
  exit 12
fi

printf '\nFOSS Guard abgeschlossen: %s (Blocker=%d, Unknown=%d, Warnungen=%d).\nReport: %s\n' \
  "$($STRICT_MODE && echo 'STRICT' || echo 'WARN')" "$BLOCK_COUNT" "$UNKNOWN_COUNT" "$WARN_COUNT" "${REPORT_PATH}"
exit 0
