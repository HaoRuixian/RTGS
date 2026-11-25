"""Configuration locations for repository and installed RTGS runtimes."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR_ENVIRONMENT_VARIABLE = "RTGS_CONFIG_DIR"
_REPOSITORY_CONFIG_ROOT = PROJECT_ROOT / "config"


def _user_config_root(
    *,
    environ: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    home: Path | None = None,
) -> Path:
    """Return the writable per-user configuration directory for this platform."""
    resolved_environ = os.environ if environ is None else environ
    override = str(resolved_environ.get(CONFIG_DIR_ENVIRONMENT_VARIABLE, "")).strip()
    if override:
        return Path(override).expanduser()

    resolved_platform = sys.platform if platform_name is None else platform_name
    resolved_home = Path.home() if home is None else home
    if resolved_platform == "win32":
        app_data = str(resolved_environ.get("APPDATA", "")).strip()
        return (Path(app_data) if app_data else resolved_home / "AppData" / "Roaming") / "RTGS"
    if resolved_platform == "darwin":
        return resolved_home / "Library" / "Application Support" / "RTGS"

    xdg_config_home = str(resolved_environ.get("XDG_CONFIG_HOME", "")).strip()
    return (Path(xdg_config_home) if xdg_config_home else resolved_home / ".config") / "rtgs"


def _select_config_root(
    project_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    home: Path | None = None,
) -> Path:
    """Prefer an explicit override, then repository config, then user config."""
    resolved_environ = os.environ if environ is None else environ
    if str(resolved_environ.get(CONFIG_DIR_ENVIRONMENT_VARIABLE, "")).strip():
        return _user_config_root(
            environ=resolved_environ,
            platform_name=platform_name,
            home=home,
        )

    repository_config = project_root / "config"
    if repository_config.is_dir():
        return repository_config
    return _user_config_root(
        environ=resolved_environ,
        platform_name=platform_name,
        home=home,
    )


CONFIG_ROOT = _select_config_root(PROJECT_ROOT)
STREAM_CONFIG_DIR = CONFIG_ROOT / "streams"
IR_CONFIG_DIR = CONFIG_ROOT / "ir"
LEGACY_STREAM_CONFIG_DIR = CONFIG_ROOT / "legacy"

DEFAULT_STREAM_CONFIG_NAME = "example_config.yaml"
DEFAULT_STREAM_SAVE_NAME = "stream_config.yaml"
DEFAULT_IR_CONFIG_NAME = "default_ir.yaml"


def ensure_config_directories() -> None:
    """Ensure writable configuration directories exist."""
    for path in (CONFIG_ROOT, STREAM_CONFIG_DIR, IR_CONFIG_DIR, LEGACY_STREAM_CONFIG_DIR):
        path.mkdir(parents=True, exist_ok=True)


def _resolve_repo_config_path(path: str | Path, base_dir: Path) -> Path:
    """Resolve legacy ``config/...`` and relative paths under the active root."""
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    if candidate.parts and candidate.parts[0] == "config":
        return CONFIG_ROOT.joinpath(*candidate.parts[1:])
    return base_dir / candidate


def _ensure_default_stream_config(path: Path) -> None:
    """Create a credential-free stream configuration when no default exists."""
    if path.is_file():
        return
    from core.global_config import GlobalConfig

    GlobalConfig().save_to_file(str(path))


def _ensure_default_ir_config(path: Path) -> None:
    """Create the built-in DEMO reflectometry configuration when missing."""
    if path.is_file():
        return
    from core.reflectometry.config import dump_example_config

    dump_example_config(path)


def resolve_stream_config_path(
    path: str | Path | None = None,
    default_name: str = DEFAULT_STREAM_CONFIG_NAME,
) -> Path:
    """
    解析实时数据流配置路径。

    Args:
        path: 用户传入路径，支持绝对路径、``config/...`` 路径或相对文件名。
        default_name: 未提供路径时使用的默认文件名。

    Returns:
        解析后的配置文件路径。
    """
    ensure_config_directories()
    if path is None or not str(path).strip():
        return STREAM_CONFIG_DIR / default_name
    return _resolve_repo_config_path(path, STREAM_CONFIG_DIR)


def resolve_ir_config_path(
    path: str | Path | None = None,
    default_name: str = DEFAULT_IR_CONFIG_NAME,
) -> Path:
    """
    解析 GNSS-IR 配置路径。

    Args:
        path: 用户传入路径，支持绝对路径、``config/...`` 路径或相对文件名。
        default_name: 未提供路径时使用的默认文件名。

    Returns:
        解析后的配置文件路径。
    """
    ensure_config_directories()
    if path is None or not str(path).strip():
        return IR_CONFIG_DIR / default_name
    return _resolve_repo_config_path(path, IR_CONFIG_DIR)


def default_stream_config_path(filename: str = DEFAULT_STREAM_CONFIG_NAME) -> Path:
    """Return a stream config path, provisioning the safe default when needed."""
    path = resolve_stream_config_path(filename)
    if filename == DEFAULT_STREAM_CONFIG_NAME:
        _ensure_default_stream_config(path)
    return path


def default_stream_save_path(filename: str = DEFAULT_STREAM_SAVE_NAME) -> Path:
    """返回默认实时数据流配置保存路径。"""
    return resolve_stream_config_path(filename)


def default_ir_config_path(filename: str = DEFAULT_IR_CONFIG_NAME) -> Path:
    """Return an IR config path, provisioning the DEMO default when needed."""
    path = resolve_ir_config_path(filename)
    if filename == DEFAULT_IR_CONFIG_NAME:
        _ensure_default_ir_config(path)
    return path


__all__ = [
    "CONFIG_ROOT",
    "CONFIG_DIR_ENVIRONMENT_VARIABLE",
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
