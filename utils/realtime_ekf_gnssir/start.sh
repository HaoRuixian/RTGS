#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
CONFIG="${CONFIG:-$SCRIPT_DIR/config/app.yaml}"
PYTHON_BIN="${PYTHON:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN=python
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/run.py" --config "$CONFIG" "$@"
