import os
from pathlib import Path

import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.global_config import get_global_config
from ui.positioning.positioning_config_dialog import PositioningConfigDialog
from ui.shared.config_dialog import ConfigDialog


def _qapp():
    return QApplication.instance() or QApplication([])


def test_config_dialog_keeps_broadcast_ephemeris_and_ssr_mountpoints_separate():
    _qapp()
    global_config = get_global_config()
    original_config = global_config.to_dict()
    dialog = ConfigDialog(
        None,
        {
            "OBS": {"source": "NTRIP Server", "host": "caster.example.com", "port": "2101"},
            "EPH_ENABLED": True,
            "EPH": {
                "source": "NTRIP Server",
                "host": "caster.example.com",
                "port": "2101",
                "mountpoint": "BRDC",
                "user": "user",
                "password": "pass",
            },
            "SSR_ENABLED": True,
            "SSR": {
                "source": "NTRIP Server",
                "host": "caster.example.com",
                "port": "2101",
                "mountpoint": "SSRA",
                "user": "user",
                "password": "pass",
            },
            "APPROX_REC_POS": None,
            "TARGET_SYSTEMS": ["G", "E", "C"],
        },
    )

    try:
        settings = dialog.get_settings()
    finally:
        dialog.close()
        global_config.from_dict(original_config)

    assert settings["EPH_ENABLED"] is True
    assert settings["EPH"]["mountpoint"] == "BRDC"
    assert settings["SSR_ENABLED"] is True
    assert settings["SSR"]["mountpoint"] == "SSRA"


def test_positioning_config_dialog_preserves_ssr_required_and_fallback_flags():
    _qapp()
    global_config = get_global_config()
    original_config = global_config.to_dict()
    global_config.update_positioning_settings(
        {
            "require_ssr_corrections": False,
            "allow_gps_fallback": True,
            "system_code_weight_factors": {"R": 5.0},
            "code_sigma_m": 1.0,
        }
    )
    dialog = PositioningConfigDialog()

    try:
        assert dialog.require_ssr_corrections.isChecked() is False
        assert dialog.allow_gps_fallback.isChecked() is True

        dialog.require_ssr_corrections.setChecked(True)
        dialog.allow_gps_fallback.setChecked(False)
        settings = dialog.get_settings()
    finally:
        dialog.close()
        global_config.from_dict(original_config)

    assert settings["require_ssr_corrections"] is True
    assert settings["allow_gps_fallback"] is False
    assert settings["code_sigma_m"] == 1.0
    assert settings["system_code_weight_factors"] == {"R": 5.0}


def test_positioning_config_dialog_round_trips_precise_ppp_settings():
    _qapp()
    global_config = get_global_config()
    original_config = global_config.to_dict()
    global_config.update_positioning_settings(
        {
            "ppp_precise_model_enabled": True,
            "ppp_auto_ssr_apc_reference": False,
            "ppp_ssr_apc_reference": True,
            "ppp_antex_file": "/tmp/igs.atx",
            "ppp_blq_file": "/tmp/ocean.blq",
            "ppp_receiver_antenna": "LEIAR25.R4 NONE",
            "ppp_station_id": "abcd",
            "ppp_antenna_eccentricity_neu_m": [0.1, -0.2, 1.3],
            "ppp_postfit_enabled": True,
            "ppp_max_code_postfit_residual_m": 2.5,
            "ppp_max_phase_postfit_residual_m": 0.02,
        }
    )
    dialog = PositioningConfigDialog()

    try:
        settings = dialog.get_settings()
    finally:
        dialog.close()
        global_config.from_dict(original_config)

    assert settings["ppp_precise_model_enabled"] is True
    assert settings["ppp_auto_ssr_apc_reference"] is False
    assert settings["ppp_ssr_apc_reference"] is True
    assert settings["ppp_antex_file"] == "/tmp/igs.atx"
    assert settings["ppp_blq_file"] == "/tmp/ocean.blq"
    assert settings["ppp_receiver_antenna"] == "LEIAR25.R4 NONE"
    assert settings["ppp_station_id"] == "ABCD"
    assert settings["ppp_antenna_eccentricity_neu_m"] == [0.1, -0.2, 1.3]
    assert settings["ppp_postfit_enabled"] is True
    assert settings["ppp_max_code_postfit_residual_m"] == 2.5
    assert settings["ppp_max_phase_postfit_residual_m"] == 0.02


def test_stream_yaml_positioning_settings_are_applied_on_accept(tmp_path):
    _qapp()
    global_config = get_global_config()
    original_config = global_config.to_dict()
    config_path = Path(tmp_path) / "station.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "approx_rec_pos": [-2171646.234, 4385696.114, 4076742.303],
                "positioning_settings": {
                    "ppp_trop_process_noise_mps": 5e-5,
                    "ppp_zwd_correlation_time_s": 604800.0,
                    "require_ssr_corrections": True,
                },
            }
        ),
        encoding="utf-8",
    )
    dialog = ConfigDialog()
    try:
        dialog._load_yaml_file(str(config_path))
        dialog.get_settings()
        settings = global_config.get_positioning_settings()
        assert settings["ppp_trop_process_noise_mps"] == 5e-5
        assert settings["ppp_zwd_correlation_time_s"] == 604800.0
        assert global_config.approx_rec_pos == [-2171646.234, 4385696.114, 4076742.303]
    finally:
        dialog.close()
        global_config.from_dict(original_config)


def test_config_dialog_preserves_rtk_base_network_stream():
    _qapp()
    global_config = get_global_config()
    original_config = global_config.to_dict()
    dialog = ConfigDialog(
        None,
        {
            "OBS": {"source": "NTRIP Server", "host": "rover.example.com", "port": "2101"},
            "BASE_ENABLED": True,
            "BASE": {
                "source": "NTRIP Server",
                "host": "network.example.com",
                "port": "2101",
                "mountpoint": "VRS3",
                "user": "user",
                "password": "pass",
                "data_format": "RTCM3",
            },
        },
    )
    try:
        settings = dialog.get_settings()
        assert settings["BASE_ENABLED"] is True
        assert settings["BASE"]["mountpoint"] == "VRS3"
        assert global_config.base_settings.enabled is True
        assert global_config.base_settings.mountpoint == "VRS3"
    finally:
        dialog.close()
        global_config.from_dict(original_config)
