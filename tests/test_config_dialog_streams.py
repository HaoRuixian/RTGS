import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.global_config import get_global_config
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
