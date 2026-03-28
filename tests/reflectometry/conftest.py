"""Shared pytest fixtures for reflectometry tests."""

from __future__ import annotations

import pytest

from core.config_paths import default_ir_config_path
from core.reflectometry.config import load_config


@pytest.fixture()
def example_config(tmp_path):
    """Load the bundled example config and redirect outputs into a temp directory."""
    config_path = default_ir_config_path()
    config = load_config(config_path)
    config.output.output_dir = str(tmp_path / "output")
    config.logging.console = False
    config.logging.rotating_file = False
    return config

