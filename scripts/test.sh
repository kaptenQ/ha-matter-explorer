#!/usr/bin/env bash
# Single entry point for every check: deps, lint, tests.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"

echo "== Python deps"
command -v uv >/dev/null || python3 -m pip install -q uv
# HA needs Python >= 3.14
if [ ! -x "$PY" ] || ! "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 14))'; then
  rm -rf "$ROOT/.venv"
  uv venv -q --python 3.14 "$ROOT/.venv"
fi
uv pip install -q --python "$PY" -r "$ROOT/requirements-dev.txt"

cd "$ROOT"
echo "== Lint"
"$PY" -m ruff check .
"$PY" -m ruff format --check .
echo "== Types"
"$PY" -m mypy

echo "== Tests"
"$PY" -m pytest -q

echo "== Panel JS tests"
if command -v node >/dev/null; then
  node --test tests/js/*.test.mjs
else
  echo "node not found, skipping the panel JS tests"
fi

echo "All checks passed."
