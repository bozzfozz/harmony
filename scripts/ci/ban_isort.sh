#!/usr/bin/env bash
set -euo pipefail

# Alle Fundstellen von "isort" (ohne CHANGELOG und Archiv)
matches="$(git grep -n '\bisort\b' -- . ':!CHANGELOG*' ':!docs/archive/**' || true)"

# Keine Funde → OK
[ -z "$matches" ] && exit 0

# Genau diese eine Ruff-Headerzeile erlauben:
# pyproject.toml:<linenr>:[tool.ruff.lint.isort]
allowed_pattern='^pyproject\.toml:[0-9]+:\[tool\.ruff\.lint\.isort\]$'

# Unerlaubte Treffer herausfiltern
filtered="$(printf '%s\n' "$matches" | grep -Ev "$allowed_pattern" || true)"

# Wenn noch etwas übrig ist → Fail und ausgeben
if [ -n "$filtered" ]; then
  printf '%s\n' "$filtered"
  exit 1
fi

exit 0
