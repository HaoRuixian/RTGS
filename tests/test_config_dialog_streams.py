import os

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
