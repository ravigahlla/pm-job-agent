#!/usr/bin/env bash
set -euo pipefail

# Create .venv, install editable package + dev deps, seed .env from .env.example if missing.
# Usage: from repo root, ./scripts/bootstrap.sh
# Override interpreter: PYTHON=/path/to/python3.12 ./scripts/bootstrap.sh

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "error: '${PYTHON}' not found on PATH" >&2
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Creating .venv with ${PYTHON} ..."
  "$PYTHON" -m venv .venv
fi

VENV_PY=".venv/bin/python"
VENV_PIP=".venv/bin/pip"

if [ ! -x "$VENV_PY" ]; then
  echo "error: ${VENV_PY} is missing or not executable (incomplete venv?)" >&2
  exit 1
fi

echo "Upgrading pip ..."
"$VENV_PY" -m pip install --upgrade pip

echo "Installing project (editable, dev extras) ..."
"$VENV_PIP" install -e ".[dev]"

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
  echo "Creating .env from .env.example — edit .env with your secrets."
  cp .env.example .env
elif [ ! -f ".env" ]; then
  echo "No .env.example found; create .env yourself when ready."
fi

echo "Done. Activate: source .venv/bin/activate"
