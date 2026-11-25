"""Regression tests for PPP model data shipped with RTGS."""

from types import SimpleNamespace

from core.global_config import get_global_config
from core.ppp_positioning import PPPPositioner
from ui.positioning.workers import PositioningSignals, PositioningThread


def test_empty_model_paths_use_bundled_catalogs() -> None:
    positioner = PPPPositioner(
        config={
            "ppp_precise_model_enabled": True,
            "ppp_apply_ocean_loading": True,
            "ppp_antex_file": "",
            "ppp_blq_file": "",
        }
    )

    assert positioner._antex_source == "built-in"
    assert len(positioner._antex.antennas) > 500
    assert positioner._blq_source == "built-in"
    assert len(positioner._ocean_loading.stations) > 1000
    assert "SC02" in positioner._ocean_loading.stations
    assert "GR01" not in positioner._ocean_loading.stations


def test_runtime_refresh_derives_station_and_ssr_mountpoints_from_current_streams() -> None:
    config = get_global_config()
    original = config.to_dict()
    try:
        config.update_settings("OBS", {"mountpoint": "GR01_RTCM3"})
        config.update_settings("SSR", {"mountpoint": "SSRA00CAS0"})
        config.update_positioning_settings({"ppp_station_id": ""})
        thread = PositioningThread(
            "TEST",
            PositioningSignals(),
            handler=SimpleNamespace(last_station_coords=None),
        )

        thread.refresh_runtime_config()
        assert thread.ppp_positioner.station_id == "GR01"
        assert thread.ppp_positioner.ssr_mountpoint == "SSRA00CAS0"

        config.update_settings("OBS", {"mountpoint": "SC02_RTCM3P3"})
        config.update_settings("SSR", {"mountpoint": "SSRC00IGS0"})
        thread.refresh_runtime_config()
        assert thread.ppp_positioner.station_id == "SC02"
        assert thread.ppp_positioner.ssr_mountpoint == "SSRC00IGS0"
    finally:
        config.from_dict(original)
