"""Tests for repository-managed configuration file locations."""

from core.config_paths import (
    CONFIG_ROOT,
    IR_CONFIG_DIR,
    LEGACY_STREAM_CONFIG_DIR,
    STREAM_CONFIG_DIR,
    default_ir_config_path,
    default_stream_config_path,
)


def test_bundled_config_files_live_under_config_directory():
    assert CONFIG_ROOT.name == "config"
    assert STREAM_CONFIG_DIR.parent == CONFIG_ROOT
    assert IR_CONFIG_DIR.parent == CONFIG_ROOT
    assert LEGACY_STREAM_CONFIG_DIR.parent == CONFIG_ROOT
    assert default_stream_config_path().parent == STREAM_CONFIG_DIR
    assert default_ir_config_path().parent == IR_CONFIG_DIR
    assert default_stream_config_path().is_file()
    assert default_ir_config_path().is_file()
    assert (LEGACY_STREAM_CONFIG_DIR / "config.py").is_file()
    assert (LEGACY_STREAM_CONFIG_DIR / "config_NBFH.py").is_file()
