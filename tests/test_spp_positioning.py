from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pytest

from core.broadcast_ephemeris import BroadcastEphemeris
from core.data_models import EpochObservation, SatelliteState, SignalData
from core.geo_utils import ecef2lla
from core.ssr import SsrClockCorrection, SsrCorrectionStore, SsrOrbitCorrection
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


def test_spp_positioner_prefers_gps_when_other_system_biases_are_unmodelled():
    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    receiver_clock_bias_m = 25000.0

    epoch = EpochObservation(gps_time=100000.0)
    gps_geometry = [
        ("G01", 20.0, 65.0, 2.20e7),
        ("G02", 120.0, 50.0, 2.18e7),
        ("G03", 220.0, 55.0, 2.24e7),
        ("G04", 310.0, 40.0, 2.16e7),
        ("G05", 60.0, 30.0, 2.23e7),
    ]
    biased_geometry = [
        ("C06", 80.0, 55.0, 2.28e7, 8000.0),
        ("C07", 160.0, 45.0, 2.30e7, -6000.0),
        ("R08", 260.0, 50.0, 2.19e7, 5000.0),
    ]

    for sat_id, az_deg, el_deg, slant_range_m in gps_geometry:
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

    for sat_id, az_deg, el_deg, slant_range_m, bias_m in biased_geometry:
        sat_pos = _satellite_position(receiver_ecef, az_deg, el_deg, slant_range_m)
        geometric_range = np.linalg.norm(sat_pos - receiver_ecef)
        sagnac = EARTH_ROTATION_RATE * (
            sat_pos[0] * receiver_ecef[1] - sat_pos[1] * receiver_ecef[0]
        ) / LIGHT_SPEED
        sat = SatelliteState(sys_id=sat_id[0], prn=int(sat_id[1:]))
        sat.signals["1C"] = _signal(geometric_range + sagnac + receiver_clock_bias_m + bias_m)
        sat.sat_pos_ecef = sat_pos.tolist()
        sat.sat_clk_corr = 0.0
        sat.sat_var = 1.0
        epoch.satellites[sat_id] = sat

    positioner = SPPPositioner(
        config={
            "ionosphere_option": "SINGLE",
            "troposphere_model": "None",
            "gnss_systems": ["G", "C", "R"],
            "prefer_gps_only": True,
            "min_satellites": 4,
            "cutoff_elevation_deg": 10.0,
        }
    )

    result = positioner.process_epoch(epoch, approx_position=None)

    assert result is not None
    assert result.solution_status in {"Fixed", "Uncertain"}
    assert result.num_satellites == len(gps_geometry)
    assert np.linalg.norm(np.asarray(result.position_ecef) - receiver_ecef) < 20.0


def test_spp_positioner_uses_selected_multi_gnss_by_default():
    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    receiver_clock_bias_m = 30000.0

    epoch = EpochObservation(gps_time=100000.0)
    geometry = [
        ("G01", 20.0, 65.0, 2.20e7),
        ("G02", 120.0, 50.0, 2.18e7),
        ("G03", 220.0, 55.0, 2.24e7),
        ("G04", 310.0, 40.0, 2.16e7),
        ("C06", 80.0, 55.0, 2.28e7),
        ("C07", 160.0, 45.0, 2.30e7),
        ("R08", 260.0, 50.0, 2.19e7),
        ("E09", 350.0, 60.0, 2.25e7),
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
            "gnss_systems": ["G", "C", "R", "E"],
            "min_satellites": 4,
            "cutoff_elevation_deg": 10.0,
        }
    )

    result = positioner.process_epoch(epoch, approx_position=None)

    assert result is not None
    assert result.solution_status in {"Fixed", "Uncertain"}
    assert result.num_satellites == len(geometry)
    assert np.linalg.norm(np.asarray(result.position_ecef) - receiver_ecef) < 20.0


def test_spp_positioner_estimates_multi_gnss_system_offsets():
    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    receiver_clock_bias_m = 32000.0

    epoch = EpochObservation(gps_time=100000.0)
    geometry = [
        ("G01", 20.0, 65.0, 2.20e7, 0.0),
        ("G02", 120.0, 50.0, 2.18e7, 0.0),
        ("G03", 220.0, 55.0, 2.24e7, 0.0),
        ("G04", 310.0, 40.0, 2.16e7, 0.0),
        ("C06", 80.0, 55.0, 2.28e7, 8000.0),
        ("C07", 160.0, 45.0, 2.30e7, 8000.0),
        ("R08", 260.0, 50.0, 2.19e7, -6000.0),
        ("R09", 40.0, 35.0, 2.23e7, -6000.0),
        ("E10", 350.0, 60.0, 2.25e7, 4000.0),
        ("E11", 190.0, 42.0, 2.26e7, 4000.0),
    ]

    for sat_id, az_deg, el_deg, slant_range_m, system_bias_m in geometry:
        sat_pos = _satellite_position(receiver_ecef, az_deg, el_deg, slant_range_m)
        geometric_range = np.linalg.norm(sat_pos - receiver_ecef)
        sagnac = EARTH_ROTATION_RATE * (
            sat_pos[0] * receiver_ecef[1] - sat_pos[1] * receiver_ecef[0]
        ) / LIGHT_SPEED
        sat = SatelliteState(sys_id=sat_id[0], prn=int(sat_id[1:]))
        sat.signals["1C"] = _signal(
            geometric_range + sagnac + receiver_clock_bias_m + system_bias_m
        )
        sat.sat_pos_ecef = sat_pos.tolist()
        sat.sat_clk_corr = 0.0
        sat.sat_var = 1.0
        epoch.satellites[sat_id] = sat

    positioner = SPPPositioner(
        config={
            "ionosphere_option": "SINGLE",
            "troposphere_model": "None",
            "gnss_systems": ["G", "C", "R", "E"],
            "prefer_gps_only": False,
            "min_satellites": 4,
            "cutoff_elevation_deg": 10.0,
        }
    )

    result = positioner.process_epoch(epoch, approx_position=None)

    assert result is not None
    assert result.solution_status in {"Fixed", "Uncertain"}
    assert result.num_satellites == len(geometry)
    assert np.linalg.norm(np.asarray(result.position_ecef) - receiver_ecef) < 20.0
    assert abs(result.clock_bias - receiver_clock_bias_m) < 20.0
    assert abs(result.time_offsets["C"] - 8000.0 / LIGHT_SPEED) < 1e-9
    assert abs(result.time_offsets["R"] - (-6000.0) / LIGHT_SPEED) < 1e-9
    assert abs(result.time_offsets["E"] - 4000.0 / LIGHT_SPEED) < 1e-9


def test_spp_positioner_applies_cached_ssr_to_satellite_state(monkeypatch):
    import core.spp_positioning as spp_module

    def fake_brdc2state(_payload, _sys_type, _transmit_time):
        return (
            np.array([26_560_000.0, 0.0, 0.0]),
            np.array([0.0, 3_880.0, 0.0]),
        )

    monkeypatch.setattr(spp_module, "brdc2state", fake_brdc2state)

    ssr_store = SsrCorrectionStore()
    ssr_store.update_orbit(
        SsrOrbitCorrection(
            satellite_id="G01",
            epoch_time=110.0,
            iod=7,
            delta_radial_m=1.0,
            delta_along_track_m=2.0,
            delta_cross_track_m=3.0,
        )
    )
    ssr_store.update_clock(
        SsrClockCorrection(
            satellite_id="G01",
            epoch_time=110.0,
            delta_clock_m=0.3,
        )
    )

    handler = SimpleNamespace(
        ssr_corrections=ssr_store,
        get_ephemeris=lambda _sat_id: {
            "satellite_id": "G01",
            "system": "GPS",
            "PRN": 1,
            "week": 2412,
            "toe": 110.0,
            "toc": 110.0,
            "sqrt_a": 5153.6,
            "e": 0.01,
            "M0": 0.0,
            "omega": 0.0,
            "i0": 0.94,
            "Omega0": 0.0,
            "delta_n": 0.0,
            "Omega_dot": 0.0,
            "idot": 0.0,
            "Crs": 0.0,
            "Crc": 0.0,
            "Cus": 0.0,
            "Cuc": 0.0,
            "Cis": 0.0,
            "Cic": 0.0,
            "af0": 0.0,
            "af1": 0.0,
            "af2": 0.0,
        },
    )

    epoch = EpochObservation(gps_time=110.001)
    satellite = SatelliteState(sys_id="G", prn=1)
    satellite.signals["1C"] = _signal(299_792.458)
    epoch.satellites["G01"] = satellite

    positioner = SPPPositioner(ephemeris_handler=handler, config={"gnss_systems": ["G"]})
    positioner._update_satellite_positions(epoch)

    assert satellite.sat_pos_ecef == pytest.approx([26_559_999.0, -2.0, -3.0])
    assert satellite.sat_clk_corr == pytest.approx(0.3 / LIGHT_SPEED)
    assert satellite.sat_pos_source == "SSR"


def test_spp_positioner_normalizes_named_gnss_systems():
    positioner = SPPPositioner(config={"gnss_systems": ["GPS", "GLONASS", "BeiDou", "Galileo"]})

    assert positioner.gnss_systems == ["G", "R", "C", "E"]


def test_spp_positioner_does_not_hide_numeric_multi_gnss_solution_with_gps_fallback():
    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    receiver_clock_bias_m = 32000.0

    epoch = EpochObservation(gps_time=100000.0)
    geometry = [
        ("G01", 20.0, 65.0, 2.20e7, 0.0),
        ("G02", 120.0, 50.0, 2.18e7, 0.0),
        ("G03", 220.0, 55.0, 2.24e7, 0.0),
        ("G04", 310.0, 40.0, 2.16e7, 0.0),
        ("C06", 80.0, 55.0, 2.28e7, 8000.0),
        ("C07", 160.0, 45.0, 2.30e7, 8000.0),
    ]

    for sat_id, az_deg, el_deg, slant_range_m, system_bias_m in geometry:
        sat_pos = _satellite_position(receiver_ecef, az_deg, el_deg, slant_range_m)
        geometric_range = np.linalg.norm(sat_pos - receiver_ecef)
        sagnac = EARTH_ROTATION_RATE * (
            sat_pos[0] * receiver_ecef[1] - sat_pos[1] * receiver_ecef[0]
        ) / LIGHT_SPEED
        sat = SatelliteState(sys_id=sat_id[0], prn=int(sat_id[1:]))
        sat.signals["1C"] = _signal(
            geometric_range + sagnac + receiver_clock_bias_m + system_bias_m
        )
        sat.sat_pos_ecef = sat_pos.tolist()
        sat.sat_clk_corr = 0.0
        sat.sat_var = 1.0
        epoch.satellites[sat_id] = sat

    positioner = SPPPositioner(
        config={
            "ionosphere_option": "SINGLE",
            "troposphere_model": "None",
            "gnss_systems": ["G", "C"],
            "prefer_gps_only": False,
            "min_satellites": 4,
            "cutoff_elevation_deg": 10.0,
            "max_pdop": 0.1,
        }
    )

    result = positioner.process_epoch(epoch, approx_position=None)

    assert result is not None
    assert result.solution_source == "Multi-GNSS"
    assert result.solution_status == "Uncertain"
    assert result.used_system_counts == {"C": 2, "G": 4}
    assert "PDOP" in result.quality_reason


def test_spp_positioner_follows_rtklib_rank_requirement_for_multi_gnss_offsets():
    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    receiver_clock_bias_m = 32000.0

    epoch = EpochObservation(gps_time=100000.0)
    geometry = [
        ("G01", 20.0, 65.0, 2.20e7, 0.0),
        ("G02", 120.0, 50.0, 2.18e7, 0.0),
        ("G03", 220.0, 55.0, 2.24e7, 0.0),
        ("C06", 80.0, 55.0, 2.28e7, 30.0),
        ("R08", 260.0, 50.0, 2.19e7, -25.0),
        ("E10", 350.0, 60.0, 2.25e7, 15.0),
    ]

    for sat_id, az_deg, el_deg, slant_range_m, system_bias_m in geometry:
        sat_pos = _satellite_position(receiver_ecef, az_deg, el_deg, slant_range_m)
        geometric_range = np.linalg.norm(sat_pos - receiver_ecef)
        sagnac = EARTH_ROTATION_RATE * (
            sat_pos[0] * receiver_ecef[1] - sat_pos[1] * receiver_ecef[0]
        ) / LIGHT_SPEED
        sat = SatelliteState(sys_id=sat_id[0], prn=int(sat_id[1:]))
        sat.signals["1C"] = _signal(
            geometric_range + sagnac + receiver_clock_bias_m + system_bias_m
        )
        sat.sat_pos_ecef = sat_pos.tolist()
        sat.sat_clk_corr = 0.0
        sat.sat_var = 1.0
        epoch.satellites[sat_id] = sat

    positioner = SPPPositioner(
        config={
            "ionosphere_option": "SINGLE",
            "troposphere_model": "None",
            "gnss_systems": ["G", "C", "R", "E"],
            "prefer_gps_only": False,
            "min_satellites": 4,
            "cutoff_elevation_deg": 10.0,
        }
    )

    result = positioner.process_epoch(epoch, approx_position=None)

    assert result is None
    assert "underdetermined system: rows 8 < states 9" in positioner.last_diagnostics["solver_failure_reason"]


def test_spp_positioner_rejects_non_finite_multi_gnss_observations():
    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    receiver_clock_bias_m = 32000.0

    epoch = EpochObservation(gps_time=100000.0)
    geometry = [
        ("G01", 20.0, 65.0, 2.20e7, 0.0),
        ("G02", 120.0, 50.0, 2.18e7, 0.0),
        ("G03", 220.0, 55.0, 2.24e7, 0.0),
        ("G04", 310.0, 40.0, 2.16e7, 0.0),
        ("C06", 80.0, 55.0, 2.28e7, 8000.0),
        ("R08", 260.0, 50.0, 2.19e7, -6000.0),
        ("E10", 350.0, 60.0, 2.25e7, 4000.0),
    ]

    for sat_id, az_deg, el_deg, slant_range_m, system_bias_m in geometry:
        sat_pos = _satellite_position(receiver_ecef, az_deg, el_deg, slant_range_m)
        geometric_range = np.linalg.norm(sat_pos - receiver_ecef)
        sagnac = EARTH_ROTATION_RATE * (
            sat_pos[0] * receiver_ecef[1] - sat_pos[1] * receiver_ecef[0]
        ) / LIGHT_SPEED
        sat = SatelliteState(sys_id=sat_id[0], prn=int(sat_id[1:]))
        pseudorange = geometric_range + sagnac + receiver_clock_bias_m + system_bias_m
        sat.signals["1C"] = _signal(pseudorange)
        sat.sat_pos_ecef = sat_pos.tolist()
        sat.sat_clk_corr = 0.0
        sat.sat_var = 1.0
        epoch.satellites[sat_id] = sat

    epoch.satellites["C06"].signals["1C"].pseudorange = float("nan")
    epoch.satellites["R08"].sat_pos_ecef = [float("inf"), 0.0, 0.0]
    epoch.satellites["E10"].sat_clk_corr = float("nan")

    positioner = SPPPositioner(
        config={
            "ionosphere_option": "SINGLE",
            "troposphere_model": "None",
            "gnss_systems": ["G", "C", "R", "E"],
            "prefer_gps_only": False,
            "min_satellites": 4,
            "cutoff_elevation_deg": 10.0,
        }
    )

    result = positioner.process_epoch(epoch, approx_position=None)

    assert result is not None
    assert result.solution_source == "GPS-only observations"
    assert result.used_system_counts == {"G": 4}
    assert np.all(np.isfinite(result.position_ecef))
    assert math.isfinite(result.latitude)
    assert positioner.last_diagnostics["reject_counts"]["C:no-pseudorange"] == 1
    assert positioner.last_diagnostics["reject_counts"]["R:no-position-clock"] == 1
    assert positioner.last_diagnostics["reject_counts"]["E:no-position-clock"] == 1


def test_spp_troposphere_wrapper_handles_out_of_model_height():
    positioner = SPPPositioner(config={"troposphere_model": "Sastamoinen"})

    delay, variance = positioner._calculate_tropospheric_delay((0.0, 0.0, -200.0), (0.0, math.radians(30.0)))

    assert delay == 0.0
    assert variance == 0.0


def test_bds_ephemeris_converts_bdt_to_gpst_seconds():
    msg = SimpleNamespace(
        DF488=6,
        DF489=1000,
        DF505=604790.0,
        DF493=100.0,
        DF492=1,
        DF497=1,
        DF504=5153.6,
        DF502=0.01,
        DF500=0.0,
        DF511=0.0,
        DF507=0.0,
        DF509=0.3,
        DF499=0.0,
        DF512=0.0,
        DF491=0.0,
        DF498=0.0,
        DF510=0.0,
        DF503=0.0,
        DF501=0.0,
        DF508=0.0,
        DF506=0.0,
        DF496=0.0,
        DF495=0.0,
        DF494=0.0,
        DF513=0.0,
        DF514=0.0,
        DF490=0,
        DF515=0,
    )

    eph = BroadcastEphemeris().extract_bds_ephemeris(msg)

    assert eph is not None
    assert eph["bds_week"] == 1000
    assert eph["bds_toe"] == 604790.0
    assert eph["bds_toc"] == 100.0
    assert eph["week"] == 2357
    assert eph["toe"] == 4.0
    assert eph["toc_week"] == 2356
    assert eph["toc"] == 114.0
