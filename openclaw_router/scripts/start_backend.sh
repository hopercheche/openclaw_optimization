#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
if [ -f ".env.local" ]; then
  set -a
  # shellcheck disable=SC1091
  . ".env.local"
  set +a
fi
PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
fi

"$PYTHON_BIN" backend/openclaw/server.py --host "${OPENCLAW_HOST:-127.0.0.1}" --port "${OPENCLAW_PORT:-8787}"
