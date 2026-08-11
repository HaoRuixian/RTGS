from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

import numpy as np
import pytest

from core.ppp_physical_models import (
    AntexCalibration,
    BlqOceanLoading,
    PhaseWindupModel,
    moon_position_ecef,
    niell_mapping_factors,
    propagated_ssr_yaw_deg,
    shapiro_delay,
    solid_earth_tide_displacement,
    sun_position_ecef,
)
from core.geo_utils import ecef2lla, rot_ecef2enu


EPOCH = datetime(2026, 7, 17, 4, 0, tzinfo=timezone.utc)
RECEIVER_ECEF = np.array([-2171646.234, 4385696.114, 4076742.303], dtype=float)
SATELLITE_ECEF = np.array([15600000.0, 20100000.0, 21700000.0], dtype=float)


def _antex_line(content: str = "", label: str = "") -> str:
    return f"{content:<60}{label}"


def test_precise_sun_moon_and_solid_tide_have_physical_magnitudes() -> None:
    sun = sun_position_ecef(EPOCH)
    moon = moon_position_ecef(EPOCH)
    displacement = solid_earth_tide_displacement(EPOCH, RECEIVER_ECEF)

    assert np.all(np.isfinite(sun))
    assert np.all(np.isfinite(moon))
    assert 1.45e11 < np.linalg.norm(sun) < 1.53e11
    assert 3.4e8 < np.linalg.norm(moon) < 4.1e8
    assert 0.01 < np.linalg.norm(displacement) < 0.50


def test_precise_shapiro_delay_is_centimeter_scale() -> None:
    delay = shapiro_delay(RECEIVER_ECEF, SATELLITE_ECEF)

    assert 0.005 < delay < 0.05


def test_precise_phase_windup_is_continuous_across_epochs() -> None:
    model = PhaseWindupModel()
    values = []
    for index in range(4):
        values.append(
            model.correction_cycles(
                "G01",
                EPOCH + timedelta(seconds=30 * index),
                RECEIVER_ECEF,
                SATELLITE_ECEF + np.array([1000.0 * index, -500.0 * index, 200.0 * index]),
            )
        )

    assert np.all(np.isfinite(values))
    assert np.max(np.abs(np.diff(values))) < 0.5


def test_precise_antex_parser_applies_receiver_and_satellite_noazi(tmp_path) -> None:
    lines = [
        _antex_line(label="START OF ANTENNA"),
        _antex_line(f"{'TESTANT NONE':<20}{'':<20}", "TYPE / SERIAL NO"),
        _antex_line("  0.0  90.0   5.0", "ZEN1 / ZEN2 / DZEN"),
        _antex_line("   G01", "START OF FREQUENCY"),
        _antex_line("   10.0   20.0   30.0", "NORTH / EAST / UP"),
        _antex_line("   NOAZI   1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19"),
        _antex_line("   G01", "END OF FREQUENCY"),
        _antex_line(label="END OF ANTENNA"),
        _antex_line(label="START OF ANTENNA"),
        _antex_line(f"{'BLOCK IIF':<20}{'G01':<20}", "TYPE / SERIAL NO"),
        _antex_line("  0.0  90.0   5.0", "ZEN1 / ZEN2 / DZEN"),
        _antex_line("   G01", "START OF FREQUENCY"),
        _antex_line("    1.0    2.0    3.0", "NORTH / EAST / UP"),
        _antex_line("   NOAZI   0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0"),
        _antex_line("   G01", "END OF FREQUENCY"),
        _antex_line(label="END OF ANTENNA"),
    ]
    path = tmp_path / "test.atx"
    path.write_text("\n".join(lines), encoding="ascii")

    calibration = AntexCalibration(path)
    receiver, receiver_found = calibration.receiver_correction(
        "TESTANT NONE", "G01", math.pi / 2.0, 0.0
    )
    satellite, satellite_found = calibration.satellite_correction(
        "G01", "G01", math.pi / 2.0, 0.0
    )

    assert calibration.loaded
    assert receiver_found and satellite_found
    assert receiver == pytest.approx(-0.029)
    assert satellite == pytest.approx(-0.003)


def test_precise_blq_parser_produces_station_displacement(tmp_path) -> None:
    amplitudes = [
        "0.010 0 0 0 0 0 0 0 0 0 0",
        "0.004 0 0 0 0 0 0 0 0 0 0",
        "0.002 0 0 0 0 0 0 0 0 0 0",
    ]
    phases = ["0 0 0 0 0 0 0 0 0 0 0"] * 3
    path = tmp_path / "test.blq"
    path.write_text("\n".join(["TEST", *amplitudes, *phases]), encoding="ascii")

    loading = BlqOceanLoading(path)
    displacement, found = loading.displacement(EPOCH, RECEIVER_ECEF, "test")
    missing, missing_found = loading.displacement(EPOCH, RECEIVER_ECEF, "none")

    assert found
    assert np.all(np.isfinite(displacement))
    assert 0.0 < np.linalg.norm(displacement) < 0.02
    assert not missing_found
    assert np.array_equal(missing, np.zeros(3))


def test_sc02_got48_blq_matches_iers_argument_reference_epoch() -> None:
    receiver = np.array(
        [-2304501.715471, -3547589.403673, 4757288.493561],
        dtype=float,
    )
    loading = BlqOceanLoading("config/blq/SC02_GOT48.blq")

    displacement, found = loading.displacement(
        datetime(2026, 7, 19, tzinfo=timezone.utc),
        receiver,
        "SC02",
    )
    latitude, longitude, _height = ecef2lla(receiver)
    east_north_up = rot_ecef2enu(latitude, longitude) @ displacement

    assert found
    assert east_north_up == pytest.approx(
        [-0.007390535825, -0.001064984308, -0.019128967210],
        abs=1e-11,
    )


def test_niell_mapping_uses_distinct_hydrostatic_and_wet_factors() -> None:
    epoch = datetime(2026, 7, 19, tzinfo=timezone.utc)
    latitude = math.radians(48.5461932208)

    hydro_zenith, wet_zenith = niell_mapping_factors(
        epoch, latitude, -15.0345, math.pi / 2.0
    )
    hydro_low, wet_low = niell_mapping_factors(
        epoch, latitude, -15.0345, math.radians(10.0)
    )

    assert hydro_zenith == pytest.approx(1.0)
    assert wet_zenith == pytest.approx(1.0)
    assert hydro_low == pytest.approx(5.548305600839, abs=1e-12)
    assert wet_low == pytest.approx(5.656498171044, abs=1e-12)
    assert wet_low > hydro_low


def test_precise_ssr_yaw_uses_update_interval_midpoint() -> None:
    correction = type(
        "PhaseBias",
        (),
        {
            "yaw_angle_deg": 90.0,
            "yaw_rate_deg_s": 0.1,
            "epoch_time": 100.0,
            "update_interval": 3,
        },
    )()

    assert propagated_ssr_yaw_deg(correction, 110.0) == pytest.approx(90.5)
