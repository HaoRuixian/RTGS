#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RTGS_PYTHON_BIN="${RTGS_PYTHON:-python3}"

"$RTGS_PYTHON_BIN" - "$ROOT_DIR" "${1:-}" <<'PY'
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1])
remove_stale_envs = sys.argv[2] == "--all"
paths = (
    ".coverage", "coverage.xml", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "build", "dist", "htmlcov", "rtgs.egg-info", "src/rtgs.egg-info",
)
for relative in paths:
    path = root / relative
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()

for path in root.rglob("__pycache__"):
    if path.is_dir():
        shutil.rmtree(path)
for path in root.rglob("*.pyc"):
    if path.is_file():
        path.unlink()

if remove_stale_envs:
    for path in root.glob(".venv-*"):
        if path.is_dir():
            shutil.rmtree(path)

print("Removed RTGS caches and build metadata. The canonical .venv, config, log, and output directories were kept.")
if remove_stale_envs:
    print("Removed stale virtual-environment copies.")
PY
