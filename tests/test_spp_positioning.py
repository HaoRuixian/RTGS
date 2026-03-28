from __future__ import annotations

import math

import numpy as np

from core.data_models import EpochObservation, SatelliteState, SignalData
from core.geo_utils import ecef2lla
from core.spp_positioning import SPPPositioner


EARTH_ROTATION_RATE = 7.2921151467e-5
LIGHT_SPEED = 299792458.0


def _ecef_to_enu_rotation(rec_ecef: np.ndarray) -> np.ndarray:
    lat_rad, lon_rad, _ = ecef2lla(rec_ecef)
    sin_lat = math.sin(lat_rad)
    cos_lat = math.cos(lat_rad)
    sin_lon = math.sin(lon_rad)
    cos_lon = math.cos(lon_rad)
    return np.array(
        [
            [-sin_lon, cos_lon, 0.0],
            [-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat],
            [cos_lat * cos_lon, cos_lat * sin_lon, sin_lat],
        ],
        dtype=float,
    )


def _satellite_position(rec_ecef: np.ndarray, az_deg: float, el_deg: float, slant_range_m: float) -> np.ndarray:
    az_rad = math.radians(az_deg)
    el_rad = math.radians(el_deg)
    enu = np.array(
        [
            slant_range_m * math.sin(az_rad) * math.cos(el_rad),
            slant_range_m * math.cos(az_rad) * math.cos(el_rad),
            slant_range_m * math.sin(el_rad),
        ],
        dtype=float,
    )
    return rec_ecef + _ecef_to_enu_rotation(rec_ecef).T @ enu


def _signal(pseudorange_m: float) -> SignalData:
    return SignalData(
        signal_id="1C",
        snr=45.0,
        phase=0.0,
        pseudorange=float(pseudorange_m),
        lock_time=0,
        half_cycle=0,
        doppler=0.0,
    )


def test_spp_positioner_solves_first_epoch_without_external_initial_guess():
    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    receiver_clock_bias_m = 75000.0

    epoch = EpochObservation(gps_time=100000.0)
    geometry = [
        ("G01", 20.0, 65.0, 2.20e7),
        ("G02", 120.0, 50.0, 2.18e7),
        ("G03", 220.0, 55.0, 2.24e7),
        ("G04", 310.0, 40.0, 2.16e7),
        ("G05", 60.0, 30.0, 2.23e7),
        ("G06", 180.0, 70.0, 2.21e7),
    ]

    for sat_id, az_deg, el_deg, slant_range_m in geometry:
        sat_pos = _satellite_position(receiver_ecef, az_deg, el_deg, slant_range_m)
        geometric_range = np.linalg.norm(sat_pos - receiver_ecef)
        sagnac = EARTH_ROTATION_RATE * (
            sat_pos[0] * receiver_ecef[1] - sat_pos[1] * receiver_ecef[0]
        ) / LIGHT_SPEED
        sat = SatelliteState(sys_id=sat_id[0], prn=int(sat_id[1:]))
        sat.signals["1C"] = _signal(geometric_range + sagnac + receiver_clock_bias_m)
        sat.sat_pos_ecef = sat_pos.tolist()
        sat.sat_clk_corr = 0.0
        sat.sat_var = 1.0
        epoch.satellites[sat_id] = sat

    positioner = SPPPositioner(
        config={
            "ionosphere_option": "SINGLE",
            "troposphere_model": "None",
            "gnss_systems": ["G"],
            "min_satellites": 4,
            "cutoff_elevation_deg": 10.0,
        }
    )

    result = positioner.process_epoch(epoch, approx_position=None)

    assert result is not None
    assert result.solution_status in {"Fixed", "Uncertain"}
    assert result.num_satellites == len(geometry)
    assert isinstance(result.residuals, list)
    assert np.linalg.norm(np.asarray(result.position_ecef) - receiver_ecef) < 20.0
    assert abs(result.clock_bias - receiver_clock_bias_m) < 20.0
