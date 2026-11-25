"""Central logging configuration for RTGS processes."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

DEFAULT_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"
_MANAGED_HANDLER_ATTRIBUTE = "_rtgs_managed_handler"


@dataclass(frozen=True, slots=True)
class LoggingSettings:
    """Runtime-neutral settings for configuring an RTGS logger hierarchy."""

    level: str | int = "INFO"
    console: bool = True
    log_file: str | Path | None = None
    max_bytes: int = 5 * 1024 * 1024
    backup_count: int = 3
    use_utc: bool = False
    log_format: str = DEFAULT_LOG_FORMAT
    date_format: str = DEFAULT_DATE_FORMAT

    def __post_init__(self) -> None:
        if self.max_bytes <= 0:
            raise ValueError("max_bytes must be greater than zero")
        if self.backup_count < 0:
            raise ValueError("backup_count cannot be negative")


def configure_logging(
    settings: LoggingSettings | None = None,
    *,
    logger_name: str = "rtgs",
    stream: TextIO | None = None,
) -> logging.Logger:
    """Configure console and optional rotating-file output for a logger hierarchy.

    Repeated calls replace only handlers created by this function. Handlers added by
    embedding applications or test harnesses remain untouched.
    """
    resolved_settings = settings or LoggingSettings()
    level = _resolve_level(resolved_settings.level)
    logger = logging.getLogger(logger_name)
    logger.disabled = False
    logger.setLevel(level)
    logger.propagate = False

    _remove_managed_handlers(logger)
    formatter = _build_formatter(resolved_settings)

    if resolved_settings.console:
        console_handler = logging.StreamHandler(stream)
        _add_managed_handler(logger, console_handler, formatter, level)

    if resolved_settings.log_file is not None:
        log_path = Path(resolved_settings.log_file).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=resolved_settings.max_bytes,
            backupCount=resolved_settings.backup_count,
            encoding="utf-8",
        )
        _add_managed_handler(logger, file_handler, formatter, level)

    if not any(getattr(handler, _MANAGED_HANDLER_ATTRIBUTE, False) for handler in logger.handlers):
        null_handler = logging.NullHandler()
        _add_managed_handler(logger, null_handler, formatter, level)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a logger below the shared ``rtgs`` hierarchy."""
    if not name or name == "rtgs":
        return logging.getLogger("rtgs")
    if name.startswith("rtgs."):
        return logging.getLogger(name)
    return logging.getLogger(f"rtgs.{name}")


def _resolve_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    resolved = logging.getLevelName(level.strip().upper())
    if not isinstance(resolved, int):
        raise ValueError(f"Unknown logging level: {level!r}")
    return resolved


def _build_formatter(settings: LoggingSettings) -> logging.Formatter:
    formatter = logging.Formatter(settings.log_format, settings.date_format)
    if settings.use_utc:
        formatter.converter = time.gmtime
    return formatter


def _add_managed_handler(
    logger: logging.Logger,
    handler: logging.Handler,
    formatter: logging.Formatter,
    level: int,
) -> None:
    handler.setLevel(level)
    handler.setFormatter(formatter)
    setattr(handler, _MANAGED_HANDLER_ATTRIBUTE, True)
    logger.addHandler(handler)


def _remove_managed_handlers(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        if not getattr(handler, _MANAGED_HANDLER_ATTRIBUTE, False):
            continue
        logger.removeHandler(handler)
        handler.close()


__all__ = [
    "DEFAULT_DATE_FORMAT",
    "DEFAULT_LOG_FORMAT",
    "LoggingSettings",
    "configure_logging",
    "get_logger",
]
