"""Tests for repository and installed-runtime configuration locations."""

from __future__ import annotations

from pathlib import Path

import yaml

import core.config_paths as config_paths
from core.config_paths import (
    CONFIG_ROOT,
    IR_CONFIG_DIR,
    LEGACY_STREAM_CONFIG_DIR,
    STREAM_CONFIG_DIR,
    default_ir_config_path,
    default_stream_config_path,
)


def test_bundled_config_files_live_under_config_directory() -> None:
    assert CONFIG_ROOT.name == "config"
    assert STREAM_CONFIG_DIR.parent == CONFIG_ROOT
    assert IR_CONFIG_DIR.parent == CONFIG_ROOT
    assert LEGACY_STREAM_CONFIG_DIR.parent == CONFIG_ROOT
    assert default_stream_config_path().parent == STREAM_CONFIG_DIR
    assert default_ir_config_path().parent == IR_CONFIG_DIR
    assert default_stream_config_path().is_file()
    assert default_ir_config_path().is_file()
    assert LEGACY_STREAM_CONFIG_DIR.is_dir()


def test_config_root_prefers_override_then_repository_then_user_directory(tmp_path) -> None:
    project_root = tmp_path / "project"
    repository_config = project_root / "config"
    repository_config.mkdir(parents=True)

    assert (
        config_paths._select_config_root(
            project_root,
            environ={},
            platform_name="linux",
            home=tmp_path / "home",
        )
        == repository_config
    )
    assert config_paths._select_config_root(
        project_root,
        environ={"RTGS_CONFIG_DIR": str(tmp_path / "explicit")},
        platform_name="linux",
        home=tmp_path / "home",
    ) == Path(tmp_path / "explicit")

    repository_config.rmdir()
    assert (
        config_paths._select_config_root(
            project_root,
            environ={"XDG_CONFIG_HOME": str(tmp_path / "xdg")},
            platform_name="linux",
            home=tmp_path / "home",
        )
        == tmp_path / "xdg" / "rtgs"
    )


def test_missing_installed_defaults_are_generated_without_credentials(
    tmp_path, monkeypatch
) -> None:
    config_root = tmp_path / "user-config"
    monkeypatch.setattr(config_paths, "CONFIG_ROOT", config_root)
    monkeypatch.setattr(config_paths, "STREAM_CONFIG_DIR", config_root / "streams")
    monkeypatch.setattr(config_paths, "IR_CONFIG_DIR", config_root / "ir")
    monkeypatch.setattr(config_paths, "LEGACY_STREAM_CONFIG_DIR", config_root / "legacy")

    stream_path = config_paths.default_stream_config_path()
    ir_path = config_paths.default_ir_config_path()

    stream_payload = yaml.safe_load(stream_path.read_text(encoding="utf-8"))
    for section_name in ("obs_settings", "eph_settings", "ssr_settings", "base_settings"):
        section = stream_payload[section_name]
        assert section["user"] == ""
        assert section["password"] == ""
    ir_payload = yaml.safe_load(ir_path.read_text(encoding="utf-8"))
    assert ir_payload["station"]["station_id"] == "DEMO"
