"""Shared pytest fixtures for reflectometry tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.reflectometry.config import load_config


@pytest.fixture()
def example_config(tmp_path):
    """Load the bundled example config and redirect outputs into a temp directory."""
    config_path = Path("core/reflectometry/mock_reflectometry.yaml")
    config = load_config(config_path)
    config.output.output_dir = str(tmp_path / "output")
    config.logging.console = False
    config.logging.rotating_file = False
    return config

