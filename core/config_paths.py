"""Repository-managed configuration file locations."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_ROOT = PROJECT_ROOT / "config"
STREAM_CONFIG_DIR = CONFIG_ROOT / "streams"
IR_CONFIG_DIR = CONFIG_ROOT / "ir"
LEGACY_STREAM_CONFIG_DIR = CONFIG_ROOT / "legacy"

DEFAULT_STREAM_CONFIG_NAME = "example_config.yaml"
DEFAULT_STREAM_SAVE_NAME = "stream_config.yaml"
DEFAULT_IR_CONFIG_NAME = "default_ir.yaml"


def ensure_config_directories() -> None:
    for path in (CONFIG_ROOT, STREAM_CONFIG_DIR, IR_CONFIG_DIR, LEGACY_STREAM_CONFIG_DIR):
        path.mkdir(parents=True, exist_ok=True)


def _resolve_repo_config_path(path: str | Path, base_dir: Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    if candidate.parts and candidate.parts[0] == "config":
        return PROJECT_ROOT / candidate
    return base_dir / candidate


def resolve_stream_config_path(
    path: str | Path | None = None,
    default_name: str = DEFAULT_STREAM_CONFIG_NAME,
) -> Path:
    ensure_config_directories()
    if path is None or not str(path).strip():
        return STREAM_CONFIG_DIR / default_name
    return _resolve_repo_config_path(path, STREAM_CONFIG_DIR)


def resolve_ir_config_path(
    path: str | Path | None = None,
    default_name: str = DEFAULT_IR_CONFIG_NAME,
) -> Path:
    ensure_config_directories()
    if path is None or not str(path).strip():
        return IR_CONFIG_DIR / default_name
    return _resolve_repo_config_path(path, IR_CONFIG_DIR)


def default_stream_config_path(filename: str = DEFAULT_STREAM_CONFIG_NAME) -> Path:
    return resolve_stream_config_path(filename)


def default_stream_save_path(filename: str = DEFAULT_STREAM_SAVE_NAME) -> Path:
    return resolve_stream_config_path(filename)


def default_ir_config_path(filename: str = DEFAULT_IR_CONFIG_NAME) -> Path:
    return resolve_ir_config_path(filename)


__all__ = [
    "CONFIG_ROOT",
    "DEFAULT_IR_CONFIG_NAME",
    "DEFAULT_STREAM_CONFIG_NAME",
    "DEFAULT_STREAM_SAVE_NAME",
    "IR_CONFIG_DIR",
    "LEGACY_STREAM_CONFIG_DIR",
    "PROJECT_ROOT",
    "STREAM_CONFIG_DIR",
    "default_ir_config_path",
    "default_stream_config_path",
    "default_stream_save_path",
    "ensure_config_directories",
    "resolve_ir_config_path",
    "resolve_stream_config_path",
]
