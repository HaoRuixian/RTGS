#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${RTGS_PYTHON:-$ROOT_DIR/.venv/bin/python}"

if [[ ! -x "$VENV_PYTHON" ]]; then
    printf 'RTGS environment is not ready. Run:\n  %s\n' "$ROOT_DIR/scripts/setup_environment.sh" >&2
    exit 1
fi

cd "$ROOT_DIR"
exec "$VENV_PYTHON" "$ROOT_DIR/gui_main.py" "$@"
