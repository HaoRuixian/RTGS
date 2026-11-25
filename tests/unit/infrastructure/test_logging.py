"""Tests for the shared logging infrastructure."""

from __future__ import annotations

import io
import logging
from uuid import uuid4

import pytest

from core.reflectometry.config import LoggingConfig
from core.reflectometry.logging_utils import configure_logging as configure_reflectometry_logging
from rtgs.infrastructure.logging import LoggingSettings, configure_logging, get_logger


def test_configure_logging_writes_to_console_and_rotating_file(tmp_path) -> None:
    logger_name = f"rtgs.tests.{uuid4().hex}"
    stream = io.StringIO()
    log_path = tmp_path / "logs" / "rtgs.log"

    logger = configure_logging(
        LoggingSettings(level="DEBUG", log_file=log_path, max_bytes=1024),
        logger_name=logger_name,
        stream=stream,
    )
    logger.debug("logging-ready")
    for handler in logger.handlers:
        handler.flush()

    assert "logging-ready" in stream.getvalue()
    assert "logging-ready" in log_path.read_text(encoding="utf-8")


def test_reconfiguration_replaces_only_managed_handlers() -> None:
    logger_name = f"rtgs.tests.{uuid4().hex}"
    logger = logging.getLogger(logger_name)
    external_handler = logging.NullHandler()
    logger.addHandler(external_handler)

    configure_logging(LoggingSettings(console=False), logger_name=logger_name)
    configure_logging(LoggingSettings(console=False), logger_name=logger_name)

    assert external_handler in logger.handlers
    assert len(logger.handlers) == 2


def test_logging_settings_and_logger_names_are_validated() -> None:
    with pytest.raises(ValueError, match="max_bytes"):
        LoggingSettings(max_bytes=0)

    with pytest.raises(ValueError, match="Unknown logging level"):
        configure_logging(LoggingSettings(level="not-a-level", console=False))

    assert get_logger("positioning").name == "rtgs.positioning"
    assert get_logger("rtgs.monitoring").name == "rtgs.monitoring"


def test_child_loggers_propagate_to_configured_rtgs_hierarchy() -> None:
    stream = io.StringIO()
    configure_logging(LoggingSettings(level="INFO"), stream=stream)
    child_logger = get_logger(f"tests.{uuid4().hex}")

    child_logger.info("child-ready")

    assert "child-ready" in stream.getvalue()


def test_reflectometry_logging_uses_shared_namespace_and_rotating_file(tmp_path) -> None:
    logger = configure_reflectometry_logging(
        LoggingConfig(
            level="DEBUG",
            console=False,
            rotating_file=True,
            log_dir=str(tmp_path),
            max_bytes=1024,
            backup_count=1,
        )
    )

    logger.debug("reflectometry-ready")
    for handler in logger.handlers:
        handler.flush()

    assert logger.name == "rtgs.reflectometry"
    assert "reflectometry-ready" in (tmp_path / "reflectometry.log").read_text(encoding="utf-8")

    configure_reflectometry_logging(LoggingConfig(console=False, rotating_file=False))
