"""Logging bootstrap for the reflector subsystem."""

from __future__ import annotations

import logging
from pathlib import Path

from core.reflectometry.config import LoggingConfig
from rtgs.infrastructure import LoggingSettings
from rtgs.infrastructure import configure_logging as configure_rtgs_logging


def configure_logging(config: LoggingConfig) -> logging.Logger:
    """Configure reflectometry output through the shared RTGS logging system."""
    log_file = Path(config.log_dir) / "reflectometry.log" if config.rotating_file else None
    return configure_rtgs_logging(
        LoggingSettings(
            level=config.level,
            console=config.console,
            log_file=log_file,
            max_bytes=config.max_bytes,
            backup_count=config.backup_count,
            date_format="%Y-%m-%d %H:%M:%S",
        ),
        logger_name="rtgs.reflectometry",
    )
