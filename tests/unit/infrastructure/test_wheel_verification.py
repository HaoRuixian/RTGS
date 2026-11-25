"""Tests for the release wheel contract verifier."""

from __future__ import annotations

import zipfile

import pytest

from scripts.verify_wheel import WheelVerificationError, verify_wheel


def _write_wheel(tmp_path, *, yaml_payload: str | None = None, omit_prefix: str = ""):
    wheel_path = tmp_path / "rtgs-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w") as archive:
        for name in (
            "core/__init__.py",
            "rtgs/__init__.py",
            "ui/__init__.py",
            "utils/__init__.py",
            "gui_main.py",
            "main.py",
            "rtcm_batch_gui.py",
            "utils/realtime_ekf_gnssir/static/app.js",
            "utils/realtime_ekf_gnssir/static/index.html",
            "utils/realtime_ekf_gnssir/static/styles.css",
            "utils/rt_ntrip_rinex_service/static/app.css",
            "utils/rt_ntrip_rinex_service/static/app.js",
            "utils/rt_ntrip_rinex_service/static/index.html",
        ):
            if not omit_prefix or not name.startswith(omit_prefix):
                archive.writestr(name, "")
        archive.writestr(
            "rtgs-0.1.0.dist-info/entry_points.txt",
            "[gui_scripts]\n"
            "rtgs = gui_main:main\n"
            "rtgs-rtcm-batch = ui.rtcm_batch_converter:main\n",
        )
        if yaml_payload is not None:
            archive.writestr("rtgs/resources/config.yaml", yaml_payload)
    return wheel_path


def test_complete_wheel_with_safe_environment_credentials_passes(tmp_path) -> None:
    wheel_path = _write_wheel(
        tmp_path,
        yaml_payload="ntrip:\n  user: ${NTRIP_USER}\n  password: ''\n",
    )

    report = verify_wheel(wheel_path)

    assert report.python_file_count == 7
    assert report.yaml_file_count == 1


def test_missing_business_package_is_rejected(tmp_path) -> None:
    wheel_path = _write_wheel(tmp_path, omit_prefix="core/")

    with pytest.raises(WheelVerificationError, match="missing Python package prefix: core/"):
        verify_wheel(wheel_path)


def test_missing_static_resource_is_rejected(tmp_path) -> None:
    wheel_path = _write_wheel(
        tmp_path,
        omit_prefix="utils/rt_ntrip_rinex_service/static/app.css",
    )

    with pytest.raises(WheelVerificationError, match="missing package resource"):
        verify_wheel(wheel_path)


def test_credential_bearing_yaml_is_rejected_without_exposing_value(tmp_path) -> None:
    wheel_path = _write_wheel(
        tmp_path,
        yaml_payload="ntrip:\n  user: station-user\n  password: station-password\n",
    )

    with pytest.raises(WheelVerificationError, match="credential-bearing YAML field") as error:
        verify_wheel(wheel_path)

    assert "station-user" not in str(error.value)
    assert "station-password" not in str(error.value)
