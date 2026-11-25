#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${RTGS_VENV:-$ROOT_DIR/.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    printf 'Python executable not found: %s\n' "$PYTHON_BIN" >&2
    printf 'Set PYTHON_BIN to Python 3.10 or newer and run this script again.\n' >&2
    exit 1
fi

if ! "$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
    printf 'RTGS requires Python 3.10 or newer.\n' >&2
    exit 1
fi

venv_is_usable=false
if [[ -x "$VENV_DIR/bin/python" ]]; then
    venv_version="$("$VENV_DIR/bin/python" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
    host_version="$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    configured_version="$(sed -n 's/^version = \([0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' "$VENV_DIR/pyvenv.cfg" 2>/dev/null || true)"
    if [[ "$venv_version" == "$host_version" && ( -z "$configured_version" || "$configured_version" == "$host_version" ) ]]; then
        venv_is_usable=true
    fi
fi

if [[ "$venv_is_usable" != true ]]; then
    if [[ -e "$VENV_DIR" ]]; then
        if [[ "${RTGS_KEEP_ENV_BACKUP:-0}" == "1" ]]; then
            backup_dir="${VENV_DIR}.backup.$(date +%Y%m%d%H%M%S)"
            mv "$VENV_DIR" "$backup_dir"
            printf 'Moved unusable virtual environment to %s\n' "$backup_dir"
        else
            rm -rf "$VENV_DIR"
            printf 'Removed unusable virtual environment at %s\n' "$VENV_DIR"
        fi
    fi
    "$PYTHON_BIN" -m venv "$VENV_DIR" || {
        printf 'Could not create a virtual environment. Install the Python venv package and retry.\n' >&2
        exit 1
    }
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV_DIR/bin/python" -m pip install --editable "$ROOT_DIR[dev,maps]"

printf '\nRTGS is ready. Launch it with:\n  %s\n' "$ROOT_DIR/scripts/run_rtgs.sh"
