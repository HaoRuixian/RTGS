from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from core.data_models import EpochObservation, SatelliteState, SignalData
from core.geo_utils import ecef2lla, get_freq
from core.positioning_models import PositioningMode, SolutionStatus
from core.ppp_positioning import PPPPositioner
from core.ssr import SsrCorrectionStore, SsrPhaseBias, SsrPhaseBiasCorrection


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


def _signal(sat_key: str, signal_id: str, pseudorange_m: float, phase_range_m: float) -> SignalData:
    freq_hz, wavelength_m = get_freq(signal_id, sat_key, 0)
    assert freq_hz > 0.0
    return SignalData(
        signal_id=signal_id,
        snr=47.0,
        phase=phase_range_m / wavelength_m,
        pseudorange=float(pseudorange_m),
        lock_time=100,
        half_cycle=0,
        doppler=0.0,
    )


def _dual_frequency_epoch(
    receiver_ecef: np.ndarray,
    *,
    include_bds: bool = False,
    gps_time: float = 100000.0,
    zwd_m: float | None = None,
    vary_geometry: bool = False,
) -> EpochObservation:
    receiver_clock_bias_m = 40000.0
    epoch = EpochObservation(
        gps_time=gps_time,
        utc_datetime=datetime(2026, 7, 16, tzinfo=timezone.utc) + timedelta(seconds=gps_time - 100000.0),
    )
    geometry = [
        ("G01", "1C", "2W", 20.0, 65.0, 2.20e7),
        ("G02", "1C", "2W", 115.0, 50.0, 2.18e7),
        ("G03", "1C", "2W", 210.0, 55.0, 2.24e7),
        ("G04", "1C", "2W", 310.0, 42.0, 2.16e7),
        ("E11", "1C", "5Q", 55.0, 40.0, 2.32e7),
        ("E12", "1C", "5Q", 250.0, 58.0, 2.28e7),
        ("R05", "1P", "2P", 155.0, 45.0, 2.19e7),
        ("R06", "1P", "2P", 335.0, 62.0, 2.25e7),
    ]
    if include_bds:
        geometry.extend(
            [
                ("C06", "2I", "6I", 80.0, 48.0, 2.30e7),
                ("C07", "2I", "6I", 275.0, 52.0, 2.27e7),
            ]
        )

    for index, (sat_id, sig1, sig2, az_deg, el_deg, slant_range_m) in enumerate(geometry, start=1):
        if vary_geometry:
            epoch_step = (gps_time - 100000.0) / 30.0
            direction = -1.0 if index % 2 else 1.0
            az_deg = (az_deg + direction * epoch_step * (0.08 + 0.01 * index)) % 360.0
            el_deg = min(82.0, max(12.0, el_deg + 12.0 * math.sin(epoch_step / 55.0 + index)))
        sat_pos = _satellite_position(receiver_ecef, az_deg, el_deg, slant_range_m)
        geometric_range = np.linalg.norm(sat_pos - receiver_ecef)
        sagnac = EARTH_ROTATION_RATE * (
            sat_pos[0] * receiver_ecef[1] - sat_pos[1] * receiver_ecef[0]
        ) / LIGHT_SPEED
        trop_delay = 0.0
        if zwd_m is not None:
            zhd_m, _standard_zwd, height_term = PPPPositioner._standard_troposphere_components(receiver_ecef)
            sin_el = math.sin(math.radians(el_deg))
            cot_sq = (math.cos(math.radians(el_deg)) / sin_el) ** 2
            trop_delay = (zhd_m + zwd_m - height_term * cot_sq) / sin_el
        code_range = geometric_range + sagnac + receiver_clock_bias_m + trop_delay
        phase_range = code_range + 12.0 + index

        sat = SatelliteState(sys_id=sat_id[0], prn=int(sat_id[1:]))
        sat.signals[sig1] = _signal(sat_id, sig1, code_range, phase_range)
        sat.signals[sig2] = _signal(sat_id, sig2, code_range, phase_range)
        sat.sat_pos_ecef = sat_pos.tolist()
        sat.sat_clk_corr = 0.0
        sat.sat_var = 0.01
        sat.ssr_applied = True
        epoch.satellites[sat_id] = sat

    return epoch


def _prepare_gps_ar_epoch(
    receiver_ecef: np.ndarray,
    store: SsrCorrectionStore,
    epoch_index: int,
) -> EpochObservation:
    gps_time = 100000.0 + epoch_index * 30.0
    epoch = _dual_frequency_epoch(receiver_ecef, gps_time=gps_time, vary_geometry=True)
    sat_id = "G05"
    sat_pos = _satellite_position(receiver_ecef, 72.0 + epoch_index * 0.05, 36.0, 2.26e7)
    geometric_range = np.linalg.norm(sat_pos - receiver_ecef)
    sagnac = EARTH_ROTATION_RATE * (
        sat_pos[0] * receiver_ecef[1] - sat_pos[1] * receiver_ecef[0]
    ) / LIGHT_SPEED
    code_range = geometric_range + sagnac + 40000.0
    sat = SatelliteState(sys_id="G", prn=5)
    sat.signals["1C"] = _signal(sat_id, "1C", code_range, code_range)
    sat.signals["2W"] = _signal(sat_id, "2W", code_range, code_range)
    sat.sat_pos_ecef = sat_pos.tolist()
    sat.sat_clk_corr = 0.0
    sat.sat_var = 0.01
    sat.ssr_applied = True
    epoch.satellites[sat_id] = sat

    for sat_index, (sat_key, satellite) in enumerate(
        sorted((key, value) for key, value in epoch.satellites.items() if key.startswith("G")),
        start=1,
    ):
        n1 = 100000 + sat_index * 13
        n_wl = 45 + sat_index * 2
        n2 = n1 - n_wl
        phase_bias_1 = 0.015 * sat_index
        phase_bias_2 = -0.010 * sat_index
        for signal_id, integer, phase_bias in (
            ("1C", n1, phase_bias_1),
            ("2W", n2, phase_bias_2),
        ):
            signal = satellite.signals[signal_id]
            frequency_hz, wavelength_m = get_freq(signal_id, sat_key, 0)
            # RTCM/BNC phase bias convention: the raw phase contains the
            # negative of the broadcast correction.
            signal.phase = (signal.pseudorange + wavelength_m * integer - phase_bias) * frequency_hz / LIGHT_SPEED
        store.update_phase_biases(
            SsrPhaseBiasCorrection(
                satellite_id=sat_key,
                epoch_time=gps_time,
                provider_id=12,
                solution_id=1,
                mw_consistency=True,
                biases={
                    "1C": SsrPhaseBias("1C", phase_bias_1, True, 2, 0),
                    "2W": SsrPhaseBias("2W", phase_bias_2, True, 2, 0),
                },
            )
        )
    return epoch


def test_ppp_positioner_solves_synthetic_multi_gnss_dual_frequency_epoch() -> None:
    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    epoch = _dual_frequency_epoch(receiver_ecef)
    positioner = PPPPositioner(
        config={
            "troposphere_model": "None",
            "gnss_systems": ["G", "E", "R"],
            "require_ssr_corrections": False,
            "min_satellites": 4,
            "cutoff_elevation_deg": 10.0,
            "code_sigma_m": 1.0,
            "system_code_weight_factors": {"R": 5.0},
        }
    )

    result = positioner.process_epoch(epoch)

    assert result is not None
    assert result.solution_status in {"Fixed", "Uncertain"}
    assert result.solution_source == "PPP float"
    assert result.used_system_counts == {"E": 2, "G": 4, "R": 2}
    assert np.linalg.norm(np.asarray(result.position_ecef) - receiver_ecef) < 5.0


def test_ppp_positioner_keeps_bds_dual_frequency_ssr_observations() -> None:
    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    epoch = _dual_frequency_epoch(receiver_ecef, include_bds=True)
    positioner = PPPPositioner(
        config={
            "troposphere_model": "None",
            "gnss_systems": ["G", "E", "R", "C"],
            "require_ssr_corrections": True,
            "min_satellites": 4,
            "cutoff_elevation_deg": 10.0,
        }
    )

    result = positioner.process_epoch(epoch)

    assert result is not None
    assert result.used_system_counts == {"C": 2, "E": 2, "G": 4, "R": 2}
    assert "AMB:C06:2I-6I" in positioner.state_names
    assert "AMB:C07:2I-6I" in positioner.state_names


def test_ppp_bds_code_if_uses_ssr_bias_without_reapplying_broadcast_tgd() -> None:
    ssr_store = SsrCorrectionStore()
    ssr_store.update_code_biases("C06", {"2I": 1.25, "6I": -0.50})
    handler = SimpleNamespace(
        ssr_corrections=ssr_store,
        get_ephemeris=lambda _sat_id: {"satellite_id": "C06", "TGD1": 20e-9, "TGD2": -30e-9},
    )
    positioner = PPPPositioner(handler, config={"troposphere_model": "None"})
    satellite = SatelliteState(sys_id="C", prn=6)
    satellite.signals["2I"] = _signal("C06", "2I", 20_000_000.0, 20_000_010.0)
    satellite.signals["6I"] = _signal("C06", "6I", 20_000_020.0, 20_000_030.0)

    measurement = positioner._code_if_measurement(
        {"sat_key": "C06", "satellite_ref": satellite, "fcn": 0}
    )

    assert measurement is not None
    value, _variance, sig1, sig2 = measurement
    f1 = 1561.098e6
    f2 = 1268.52e6
    expected = (
        f1 * f1 * (20_000_000.0 + 1.25) - f2 * f2 * (20_000_020.0 - 0.50)
    ) / (f1 * f1 - f2 * f2)
    assert (sig1, sig2) == ("2I", "6I")
    assert value == pytest.approx(expected)


def test_ppp_ar_fixes_validated_between_satellite_ambiguities() -> None:
    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    store = SsrCorrectionStore(max_phase_bias_age_seconds=120.0)
    handler = SimpleNamespace(ssr_corrections=store, get_ephemeris=lambda _sat_id: None)
    positioner = PPPPositioner(
        handler,
        config={
            "troposphere_model": "None",
            "gnss_systems": ["G"],
            "require_ssr_corrections": False,
            "min_satellites": 4,
            "ppp_ar_enabled": True,
            "ppp_ar_min_epochs": 8,
            "ppp_ar_min_satellites": 5,
            "ppp_ar_max_wl_fraction": 0.05,
            "ppp_ar_max_nl_fraction": 0.15,
            "ppp_ar_max_wl_sigma_cycles": 0.05,
            "ppp_ar_max_nl_sigma_cycles": 2.0,
            "ppp_ar_ratio_threshold": 3.0,
        },
    )

    result = None
    for epoch_index in range(24):
        result = positioner.process_epoch(
            _prepare_gps_ar_epoch(receiver_ecef, store, epoch_index),
            approx_position=receiver_ecef if epoch_index == 0 else None,
        )
        assert result is not None

    assert result is not None
    assert result.solution_status == "Fixed"
    assert result.solution_source == "PPP AR fixed"
    assert result.ambiguity_fixed_count >= 4
    assert result.ambiguity_ratio >= 3.0
    assert positioner.last_diagnostics["ar_status"] == "fixed"
    assert np.linalg.norm(np.asarray(result.position_ecef) - receiver_ecef) < 0.25


def test_uncombined_ppp_directly_fixes_per_frequency_ambiguities() -> None:
    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    store = SsrCorrectionStore(max_phase_bias_age_seconds=120.0)
    handler = SimpleNamespace(ssr_corrections=store, get_ephemeris=lambda _sat_id: None)
    positioner = PPPPositioner(
        handler,
        config={
            "troposphere_model": "None",
            "gnss_systems": ["G"],
            "require_ssr_corrections": False,
            "min_satellites": 4,
            "ppp_observation_model": "UNCOMBINED",
            "ppp_ar_enabled": True,
            "ppp_ar_min_epochs": 8,
            "ppp_ar_min_satellites": 5,
            "ppp_ar_max_nl_fraction": 0.15,
            "ppp_ar_max_nl_sigma_cycles": 3.0,
            "ppp_ar_require_full_group": True,
        },
    )

    result = None
    for epoch_index in range(24):
        result = positioner.process_epoch(
            _prepare_gps_ar_epoch(receiver_ecef, store, epoch_index),
            approx_position=receiver_ecef if epoch_index == 0 else None,
        )
        assert result is not None

    assert result is not None
    assert "ION:G01" in positioner.state_names
    assert "AMB:G01:1C" in positioner.state_names
    assert "AMB:G01:2W" in positioner.state_names
    assert result.solution_source == "PPP AR fixed"
    assert result.ambiguity_fixed_count >= 8
    assert positioner.last_diagnostics["observation_model"] == "UNCOMBINED"
    assert np.linalg.norm(np.asarray(result.position_ecef) - receiver_ecef) < 0.25


def test_ppp_ar_stays_float_without_integer_phase_biases() -> None:
    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    positioner = PPPPositioner(
        config={
            "troposphere_model": "None",
            "gnss_systems": ["G", "E", "R"],
            "require_ssr_corrections": False,
            "ppp_ar_enabled": True,
            "ppp_ar_min_epochs": 1,
        }
    )

    result = positioner.process_epoch(_dual_frequency_epoch(receiver_ecef))

    assert result is not None
    assert result.solution_status == "Uncertain"
    assert result.solution_source == "PPP float"
    assert positioner.last_diagnostics["ar_fixed_count"] == 0


def test_ppp_float_applies_non_integer_phase_biases_when_ar_is_disabled() -> None:
    store = SsrCorrectionStore(max_phase_bias_age_seconds=120.0)
    store.update_phase_biases(
        SsrPhaseBiasCorrection(
            satellite_id="G01",
            epoch_time=100.0,
            biases={
                "1C": SsrPhaseBias("1C", 0.30, False, 0, 0),
                "2W": SsrPhaseBias("2W", -0.20, False, 0, 0),
            },
        )
    )
    handler = SimpleNamespace(ssr_corrections=store, get_ephemeris=lambda _sat_id: None)
    positioner = PPPPositioner(
        handler,
        config={"troposphere_model": "None", "ppp_ar_enabled": False},
    )
    satellite = SatelliteState(sys_id="G", prn=1)
    satellite.signals["1C"] = _signal("G01", "1C", 20_000_000.0, 20_000_010.0)
    satellite.signals["2W"] = _signal("G01", "2W", 20_000_020.0, 20_000_030.0)

    measurement = positioner._phase_if_measurement(
        {"sat_key": "G01", "satellite_ref": satellite, "fcn": 0},
        100.0,
    )

    assert measurement is not None
    value, _variance, _sig1, _sig2, ar_data = measurement
    f1, _ = get_freq("1C", "G01", 0)
    f2, _ = get_freq("2W", "G01", 0)
    expected = (
        f1 * f1 * (20_000_010.0 + 0.30) - f2 * f2 * (20_000_030.0 - 0.20)
    ) / (f1 * f1 - f2 * f2)
    assert value == pytest.approx(expected)
    assert ar_data["phase_bias_correction"] is not None
    assert not ar_data["integer_pair"]


def test_precise_mode_ignores_non_integer_phase_biases_outside_ar() -> None:
    store = SsrCorrectionStore(max_phase_bias_age_seconds=120.0)
    store.update_phase_biases(
        SsrPhaseBiasCorrection(
            satellite_id="G01",
            epoch_time=100.0,
            biases={
                "1C": SsrPhaseBias("1C", 0.30, False, 0, 0),
                "2W": SsrPhaseBias("2W", -0.20, False, 0, 0),
            },
        )
    )
    handler = SimpleNamespace(ssr_corrections=store, get_ephemeris=lambda _sat_id: None)
    positioner = PPPPositioner(
        handler,
        config={
            "troposphere_model": "None",
            "ppp_ar_enabled": False,
            "ppp_precise_model_enabled": True,
        },
    )
    satellite = SatelliteState(sys_id="G", prn=1)
    satellite.signals["1C"] = _signal("G01", "1C", 20_000_000.0, 20_000_010.0)
    satellite.signals["2W"] = _signal("G01", "2W", 20_000_020.0, 20_000_030.0)

    measurement = positioner._phase_if_measurement(
        {"sat_key": "G01", "satellite_ref": satellite, "fcn": 0},
        100.0,
    )

    assert measurement is not None
    value, _variance, _sig1, _sig2, ar_data = measurement
    f1, _ = get_freq("1C", "G01", 0)
    f2, _ = get_freq("2W", "G01", 0)
    expected = (
        f1 * f1 * 20_000_010.0 - f2 * f2 * 20_000_030.0
    ) / (f1 * f1 - f2 * f2)
    assert value == pytest.approx(expected)
    assert ar_data["phase_bias_correction"] is None


def test_precise_mode_auto_detects_apc_referenced_ssra_mountpoint() -> None:
    positioner = PPPPositioner(
        config={
            "ppp_precise_model_enabled": True,
            "ppp_auto_ssr_apc_reference": True,
            "ppp_ssr_mountpoint": "SSRA02IGS1",
        }
    )

    assert positioner._ssr_apc_reference_enabled() is True
    positioner.update_config({"ppp_ssr_mountpoint": "SSRC00IGS1"})
    assert positioner._ssr_apc_reference_enabled() is False


def test_precise_physical_models_are_exercised_in_ppp_epoch() -> None:
    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    positioner = PPPPositioner(
        config={
            "troposphere_model": "None",
            "gnss_systems": ["G", "E", "R"],
            "require_ssr_corrections": False,
            "ppp_precise_model_enabled": True,
            "ppp_apply_ocean_loading": False,
            "ppp_ar_enabled": False,
        }
    )

    result = positioner.process_epoch(
        _dual_frequency_epoch(receiver_ecef),
        approx_position=receiver_ecef,
    )

    assert result is not None
    assert positioner.last_diagnostics["precise_model_enabled"] is True
    assert positioner.last_diagnostics["solid_tide_displacement_m"] > 0.0
    corrections = positioner.last_diagnostics["model_corrections"]
    assert corrections["shapiro"]["max_abs_m"] > 0.0
    assert corrections["phase_windup"]["count"] >= result.num_satellites


def test_precise_postfit_code_outlier_removes_entire_satellite() -> None:
    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    positioner = PPPPositioner(
        config={
            "troposphere_model": "None",
            "gnss_systems": ["G", "E", "R"],
            "require_ssr_corrections": False,
            "ppp_postfit_enabled": True,
        }
    )
    assert positioner.process_epoch(_dual_frequency_epoch(receiver_ecef)) is not None
    epoch = _dual_frequency_epoch(receiver_ecef, gps_time=100030.0)
    for signal in epoch.satellites["G01"].signals.values():
        signal.pseudorange += 100.0

    result = positioner.process_epoch(epoch)

    assert result is not None
    assert "G01" not in result.used_satellites
    assert positioner.last_diagnostics["postfit_rejected_satellites"] == ["G01"]
    assert positioner.last_diagnostics["reject_counts"]["G:ppp-code-postfit"] == 1


def test_precise_postfit_phase_outlier_resets_only_ambiguity() -> None:
    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    positioner = PPPPositioner(
        config={
            "troposphere_model": "None",
            "gnss_systems": ["G", "E", "R"],
            "require_ssr_corrections": False,
            "ppp_postfit_enabled": True,
        }
    )
    assert positioner.process_epoch(_dual_frequency_epoch(receiver_ecef)) is not None
    epoch = _dual_frequency_epoch(receiver_ecef, gps_time=100030.0)
    for signal_id, signal in epoch.satellites["G01"].signals.items():
        _frequency, wavelength = get_freq(signal_id, "G01", 0)
        signal.phase += 0.5 / wavelength

    result = positioner.process_epoch(epoch)

    assert result is not None
    assert "G01" in result.used_satellites
    assert positioner.last_diagnostics["postfit_rejected_satellites"] == []
    assert positioner.last_diagnostics["postfit_reset_ambiguities"] == ["AMB:G01:1C-2W"]
    assert positioner.last_diagnostics["reject_counts"]["G:ppp-phase-postfit"] == 1


def test_ppp_ar_does_not_mix_phase_bias_providers() -> None:
    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    store = SsrCorrectionStore(max_phase_bias_age_seconds=120.0)
    handler = SimpleNamespace(ssr_corrections=store, get_ephemeris=lambda _sat_id: None)
    positioner = PPPPositioner(
        handler,
        config={
            "troposphere_model": "None",
            "gnss_systems": ["G"],
            "require_ssr_corrections": False,
            "min_satellites": 4,
            "ppp_ar_enabled": True,
            "ppp_ar_min_epochs": 5,
            "ppp_ar_min_satellites": 5,
        },
    )

    result = None
    for epoch_index in range(12):
        epoch = _prepare_gps_ar_epoch(receiver_ecef, store, epoch_index)
        other_provider = store.get_phase_biases("G05", time_sow=epoch.gps_time)
        assert other_provider is not None
        other_provider.provider_id = 99
        result = positioner.process_epoch(
            epoch,
            approx_position=receiver_ecef if epoch_index == 0 else None,
        )

    assert result is not None
    assert result.solution_source == "PPP float"
    assert positioner.last_diagnostics["ar_candidate_count"] == 5
    assert positioner.last_diagnostics["ar_fixed_count"] == 0


def test_ppp_integer_search_uses_full_correlated_covariance() -> None:
    float_ambiguities = np.array([-0.3763371, -0.1533471], dtype=float)
    covariance = np.array(
        [[0.84448481, -0.95650380], [-0.95650380, 1.85740743]],
        dtype=float,
    )

    search = PPPPositioner._integer_least_squares(float_ambiguities, covariance)

    assert search is not None
    best, best_score, _second, second_score, _nodes = search
    assert np.array_equal(best, np.array([0, -1]))
    assert not np.array_equal(best, np.rint(float_ambiguities).astype(int))
    assert second_score > best_score


def test_ppp_precise_bie_uses_weighted_integer_candidates() -> None:
    float_ambiguities = np.array([0.02, -0.03], dtype=float)
    covariance = np.array(
        [[0.0025, 0.0005], [0.0005, 0.0036]],
        dtype=float,
    )

    result = PPPPositioner._integer_bie(float_ambiguities, covariance)

    assert result is not None
    bie, bie_covariance, best_score, second_score, best_weight, nodes = result
    assert np.allclose(bie, np.zeros(2), atol=1e-8)
    assert np.all(np.diag(bie_covariance) > 0.0)
    assert second_score > best_score
    assert 0.0 < best_weight <= 1.0
    assert nodes > 0


def test_ppp_precise_bie_fixes_validated_ambiguities() -> None:
    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    store = SsrCorrectionStore(max_phase_bias_age_seconds=120.0)
    handler = SimpleNamespace(ssr_corrections=store, get_ephemeris=lambda _sat_id: None)
    positioner = PPPPositioner(
        handler,
        config={
            "troposphere_model": "None",
            "gnss_systems": ["G"],
            "require_ssr_corrections": False,
            "min_satellites": 4,
            "ppp_precise_model_enabled": True,
            "ppp_apply_phase_windup": False,
            "ppp_apply_shapiro_delay": False,
            "ppp_apply_solid_earth_tide": False,
            "ppp_apply_ocean_loading": False,
            "ppp_postfit_enabled": False,
            "ppp_ar_enabled": True,
            "ppp_ar_min_epochs": 8,
            "ppp_ar_min_satellites": 5,
            "ppp_ar_max_wl_fraction": 0.05,
            "ppp_ar_max_nl_fraction": 0.15,
            "ppp_ar_max_wl_sigma_cycles": 0.05,
            "ppp_ar_max_nl_sigma_cycles": 3.0,
        },
    )

    result = None
    for epoch_index in range(24):
        result = positioner.process_epoch(
            _prepare_gps_ar_epoch(receiver_ecef, store, epoch_index),
            approx_position=receiver_ecef if epoch_index == 0 else None,
        )
        assert result is not None

    assert result is not None
    assert result.solution_status == "Fixed"
    assert result.ambiguity_fixed_count >= 4
    assert result.ambiguity_ratio == pytest.approx(1.0)
    assert positioner.last_diagnostics["ar_bie_candidates"] == 100
    assert positioner.last_diagnostics["ar_bie_best_weight"] > 0.0


def test_ppp_log_zwd_state_remains_physical_without_boundary_clipping() -> None:
    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    positioner = PPPPositioner(config={"troposphere_model": "Sastamoinen"})
    names = ["X", "Y", "Z", "CLK:G", "LOG_ZWD"]
    positioner._sync_state(names, receiver_ecef, 100000.0)
    zwd_index = positioner.state_names.index("LOG_ZWD")

    assert positioner.x[zwd_index] == 0.0

    design = np.zeros((1, len(names)), dtype=float)
    design[0, zwd_index] = 1.0
    positioner._kalman_update(design, np.array([-10.0]), np.array([1e-8]))
    ztd, zhd, zwd = positioner._estimated_zenith_troposphere()

    assert positioner.x[zwd_index] < 0.0
    assert zwd > 0.0
    assert ztd > zhd


def test_ppp_zwd_and_position_remain_stable_over_many_epochs() -> None:
    receiver_ecef = np.array([-2171646.234, 4385696.114, 4076742.303], dtype=float)
    true_zwd_m = 0.22
    positioner = PPPPositioner(
        config={
            "troposphere_model": "Sastamoinen",
            "gnss_systems": ["G", "E", "R", "C"],
            "require_ssr_corrections": True,
            "min_satellites": 4,
            "cutoff_elevation_deg": 10.0,
            "ppp_trop_process_noise_mps": 5e-5,
            "ppp_zwd_correlation_time_s": 7 * 86400.0,
        }
    )
    initial = receiver_ecef + np.array([3.0, -2.0, 4.0])

    result = None
    # 1,800 x 30 s covers 15 hours, matching the overnight failure mode that
    # previously drove the clipped wet delay to 0.0001 m.
    for epoch_index in range(1800):
        epoch = _dual_frequency_epoch(
            receiver_ecef,
            include_bds=True,
            gps_time=100000.0 + epoch_index * 30.0,
            zwd_m=true_zwd_m,
            vary_geometry=True,
        )
        result = positioner.process_epoch(epoch, approx_position=initial if epoch_index == 0 else None)
        assert result is not None

    assert result is not None
    assert result.zwd == pytest.approx(true_zwd_m, abs=0.06)
    assert result.zwd > 0.10
    assert np.linalg.norm(np.asarray(result.position_ecef) - receiver_ecef) < 0.20
    assert not any("ppp-code-prefit" in reason for reason in positioner.last_diagnostics["reject_counts"])


def test_ppp_reinitializes_unflagged_phase_outlier_without_corrupting_position() -> None:
    receiver_ecef = np.array([-2171646.234, 4385696.114, 4076742.303], dtype=float)
    positioner = PPPPositioner(
        config={
            "troposphere_model": "Sastamoinen",
            "gnss_systems": ["G", "E", "R", "C"],
            "require_ssr_corrections": True,
            "ppp_max_phase_prefit_residual_m": 1.0,
        }
    )
    first = positioner.process_epoch(
        _dual_frequency_epoch(receiver_ecef, include_bds=True, zwd_m=0.20),
        approx_position=receiver_ecef + np.array([1.0, -1.0, 2.0]),
    )
    assert first is not None

    second_epoch = _dual_frequency_epoch(
        receiver_ecef,
        include_bds=True,
        gps_time=100030.0,
        zwd_m=0.20,
    )
    for signal in second_epoch.satellites["G01"].signals.values():
        frequency_hz, _wavelength_m = get_freq(signal.signal_id, "G01", 0)
        signal.phase += 20.0 * frequency_hz / LIGHT_SPEED

    second = positioner.process_epoch(second_epoch)

    assert second is not None
    assert positioner.last_diagnostics["reject_counts"]["G:ppp-phase-slip"] == 1
    assert np.linalg.norm(np.asarray(second.position_ecef) - receiver_ecef) < 1.0


def test_ppp_positioner_prefers_rtcm_station_apriori_when_available() -> None:
    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    bad_initial = receiver_ecef + np.array([80.0, -60.0, 40.0], dtype=float)
    epoch = _dual_frequency_epoch(receiver_ecef)
    handler = SimpleNamespace(last_station_coords=receiver_ecef.tolist())
    positioner = PPPPositioner(
        handler,
        config={
            "troposphere_model": "None",
            "gnss_systems": ["G", "E", "R"],
            "require_ssr_corrections": False,
            "ppp_use_station_apriori": True,
            "ppp_station_apriori_sigma_m": 0.05,
        },
    )

    result = positioner.process_epoch(epoch, approx_position=bad_initial)

    assert result is not None
    assert np.linalg.norm(np.asarray(result.position_ecef) - receiver_ecef) < 0.5
    assert positioner.last_diagnostics["position_apriori_source"] == "station-1006"


def test_ppp_defaults_to_spp_bootstrap_when_rtcm_station_position_is_available() -> None:
    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    station_position = receiver_ecef + np.array([80.0, -60.0, 40.0], dtype=float)
    epoch = _dual_frequency_epoch(receiver_ecef)
    handler = SimpleNamespace(last_station_coords=station_position.tolist())
    positioner = PPPPositioner(
        handler,
        config={
            "troposphere_model": "None",
            "gnss_systems": ["G", "E", "R"],
            "require_ssr_corrections": False,
        },
    )

    result = positioner.process_epoch(epoch)

    assert result is not None
    assert np.linalg.norm(np.asarray(result.position_ecef) - receiver_ecef) < 5.0
    assert positioner.last_diagnostics["position_apriori_source"] == "spp-bootstrap"


def test_independent_ppp_ignores_rtcm_and_external_coordinates() -> None:
    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    handler = SimpleNamespace(
        last_station_coords=(receiver_ecef + np.array([500.0, -400.0, 300.0])).tolist()
    )
    external = receiver_ecef + np.array([-800.0, 600.0, -500.0])
    positioner = PPPPositioner(
        handler,
        config={
            "troposphere_model": "None",
            "gnss_systems": ["G", "E", "R"],
            "require_ssr_corrections": False,
            "ppp_independent_mode": True,
            "ppp_use_station_apriori": True,
            "ppp_station_apriori_sigma_m": 0.001,
            "ppp_initial_position_sigma_m": 0.001,
            "ppp_spp_bootstrap_sigma_m": 100.0,
        },
    )

    result = positioner.process_epoch(
        _dual_frequency_epoch(receiver_ecef),
        approx_position=external,
    )

    assert result is not None
    assert np.linalg.norm(np.asarray(result.position_ecef) - receiver_ecef) < 5.0
    assert np.linalg.norm(np.asarray(result.position_ecef) - external) > 100.0
    assert positioner.last_diagnostics["independent_mode"] is True
    assert positioner.last_diagnostics["position_apriori_source"] == (
        "spp-bootstrap-observation-only"
    )
    assert positioner.last_diagnostics["external_position_ignored"] is True
    assert positioner.last_diagnostics["configured_position_used"] is False
    assert positioner.last_diagnostics["rtcm_station_position_used"] is False


def test_precise_ppp_estimates_horizontal_troposphere_gradients() -> None:
    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    positioner = PPPPositioner(
        config={
            "troposphere_model": "Sastamoinen",
            "gnss_systems": ["G", "E", "R"],
            "require_ssr_corrections": False,
            "ppp_precise_model_enabled": True,
            "ppp_estimate_trop_gradients": True,
            "ppp_apply_ocean_loading": False,
        }
    )

    result = positioner.process_epoch(_dual_frequency_epoch(receiver_ecef))

    assert result is not None
    assert "TROP_GRAD_N" in positioner.state_names
    assert "TROP_GRAD_E" in positioner.state_names
    assert positioner.last_diagnostics["troposphere_mapping"] == (
        "Niell hydrostatic/wet"
    )
    assert positioner.last_diagnostics["troposphere_gradients_enabled"] is True


def test_positioning_thread_routes_ppp_mode_to_ppp_positioner() -> None:
    pytest.importorskip("PySide6")
    from ui.positioning.workers import PositioningSignals, PositioningThread

    receiver_ecef = np.array([3875000.0, 332500.0, 5029000.0], dtype=float)
    from core.global_config import get_global_config

    global_config = get_global_config()
    original_position = global_config.approx_rec_pos
    global_config.approx_rec_pos = receiver_ecef.tolist()
    thread = PositioningThread("TEST", PositioningSignals(), handler=None)
    thread.set_mode(PositioningMode.PPP)
    thread.update_positioning_settings(
        {
            "troposphere_model": "None",
            "gnss_systems": ["G", "E", "R"],
            "require_ssr_corrections": False,
            "min_satellites": 4,
            "cutoff_elevation_deg": 10.0,
        }
    )

    try:
        solution = thread._process_epoch(_dual_frequency_epoch(receiver_ecef))

        assert solution is not None
        assert solution.mode == PositioningMode.PPP
        assert solution.status != SolutionStatus.NO_FIX
        assert solution.solution_source == "PPP float"
        assert solution.used_system_counts == {"E": 2, "G": 4, "R": 2}
        assert np.linalg.norm(np.asarray(solution.position_ecef) - receiver_ecef) < 5.0
        assert solution.diagnostics["position_apriori_source"] == "spp-bootstrap"
        assert solution.has_reference_position
        assert solution.reference_source == "stream-config"
        assert solution.error_3d == pytest.approx(
            np.linalg.norm(np.asarray(solution.position_ecef) - receiver_ecef)
        )
        assert solution.error_horizontal == pytest.approx(math.hypot(solution.error_east, solution.error_north))
    finally:
        global_config.approx_rec_pos = original_position


def test_stream_config_reference_takes_priority_over_rtcm_station_position() -> None:
    pytest.importorskip("PySide6")
    from core.global_config import get_global_config
    from ui.positioning.workers import PositioningSignals, PositioningThread

    configured = np.array([-2171646.234, 4385696.114, 4076742.303], dtype=float)
    rtcm_position = configured + np.array([50.0, -40.0, 30.0])
    global_config = get_global_config()
    original_position = global_config.approx_rec_pos
    global_config.approx_rec_pos = configured.tolist()
    try:
        thread = PositioningThread(
            "TEST",
            PositioningSignals(),
            handler=SimpleNamespace(last_station_coords=rtcm_position.tolist()),
        )
        thread._refresh_reference_position()
        assert thread.reference_source == "stream-config"
        assert np.array_equal(thread.reference_position, configured)
    finally:
        global_config.approx_rec_pos = original_position
