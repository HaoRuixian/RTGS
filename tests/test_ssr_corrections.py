from __future__ import annotations

import numpy as np
import pytest

from core.ssr import SsrClockCorrection, SsrCorrectionStore, SsrOrbitCorrection


def test_ssr_store_applies_orbit_and_clock_corrections_in_rac_frame():
    store = SsrCorrectionStore()
    store.update_orbit(
        SsrOrbitCorrection(
            satellite_id="G01",
            epoch_time=100.0,
            iod=7,
            delta_radial_m=1.0,
            delta_along_track_m=2.0,
            delta_cross_track_m=3.0,
        )
    )
    store.update_clock(
        SsrClockCorrection(
            satellite_id="G01",
            epoch_time=100.0,
            delta_clock_m=0.3,
            delta_clock_rate_mps=0.01,
            delta_clock_accel_mps2=0.001,
            high_rate_clock_m=0.2,
        )
    )

    position = np.array([26_560_000.0, 0.0, 0.0])
    velocity = np.array([0.0, 3_880.0, 0.0])
    corrected = store.apply_to_state(
        "G01",
        position,
        velocity,
        clock_bias_s=1.0e-6,
        transmit_time=110.0,
    )

    assert corrected.applied is True
    assert corrected.position_m.tolist() == pytest.approx([26_559_999.0, -2.0, -3.0])
    assert corrected.velocity_mps.tolist() == pytest.approx([0.0, 3_880.0, 0.0])
    assert corrected.clock_bias_s == pytest.approx(1.0e-6 + 0.7 / 299_792_458.0)


def test_ssr_store_uses_bnc_half_update_interval_for_extrapolation():
    store = SsrCorrectionStore()
    store.update_orbit(
        SsrOrbitCorrection(
            satellite_id="G01",
            epoch_time=100.0,
            update_interval=1,
            delta_radial_m=1.0,
            dot_delta_radial_mps=1.0,
        )
    )
    store.update_clock(
        SsrClockCorrection(
            satellite_id="G01",
            epoch_time=100.0,
            update_interval=1,
            delta_clock_m=0.3,
            delta_clock_rate_mps=0.1,
        )
    )

    corrected = store.apply_to_state(
        "G01",
        np.array([26_560_000.0, 0.0, 0.0]),
        np.array([0.0, 3_880.0, 0.0]),
        clock_bias_s=0.0,
        transmit_time=110.0,
    )

    assert corrected.position_m.tolist() == pytest.approx([26_559_990.0, 0.0, 0.0])
    assert corrected.clock_bias_s == pytest.approx(1.2 / 299_792_458.0)


def test_ssr_store_applies_bnc_orbit_rate_to_velocity():
    store = SsrCorrectionStore()
    store.update_orbit(
        SsrOrbitCorrection(
            satellite_id="G01",
            epoch_time=100.0,
            dot_delta_radial_mps=0.1,
            dot_delta_along_track_mps=0.2,
            dot_delta_cross_track_mps=-0.3,
        )
    )
    store.update_clock(SsrClockCorrection(satellite_id="G01", epoch_time=100.0))

    corrected = store.apply_to_state(
        "G01",
        np.array([26_560_000.0, 0.0, 0.0]),
        np.array([0.0, 3_880.0, 0.0]),
        clock_bias_s=0.0,
        transmit_time=100.0,
    )

    assert corrected.velocity_mps.tolist() == pytest.approx([-0.1, 3879.8, 0.3])


def test_ssr_store_requires_matching_clock_and_ephemeris_iod():
    store = SsrCorrectionStore()
    store.update_orbit(
        SsrOrbitCorrection(
            satellite_id="G01",
            epoch_time=100.0,
            iod=7,
            delta_radial_m=1.0,
        )
    )

    position = np.array([26_560_000.0, 0.0, 0.0])
    velocity = np.array([0.0, 3_880.0, 0.0])

    without_clock = store.apply_to_state(
        "G01",
        position,
        velocity,
        clock_bias_s=0.0,
        transmit_time=100.0,
        ephemeris_iod=7,
    )
    assert without_clock.applied is False
    assert without_clock.position_m.tolist() == pytest.approx(position.tolist())

    store.update_clock(SsrClockCorrection(satellite_id="G01", epoch_time=100.0, delta_clock_m=0.3))
    mismatched = store.apply_to_state(
        "G01",
        position,
        velocity,
        clock_bias_s=0.0,
        transmit_time=100.0,
        ephemeris_iod=8,
    )
    assert mismatched.applied is False
    assert mismatched.position_m.tolist() == pytest.approx(position.tolist())

    matched = store.apply_to_state(
        "G01",
        position,
        velocity,
        clock_bias_s=0.0,
        transmit_time=100.0,
        ephemeris_iod=7,
    )
    assert matched.applied is True
    assert matched.position_m.tolist() == pytest.approx([26_559_999.0, 0.0, 0.0])


def test_ssr_store_high_rate_clock_uses_last_base_clock_only():
    store = SsrCorrectionStore()
    store.update_orbit(SsrOrbitCorrection(satellite_id="G01", epoch_time=100.0))
    store.update_high_rate_clock(
        SsrClockCorrection(satellite_id="G01", epoch_time=101.0, high_rate_clock_m=0.5)
    )
    assert store.get_clock("G01") is None

    store.update_clock(SsrClockCorrection(satellite_id="G01", epoch_time=100.0, delta_clock_m=1.0))
    store.update_high_rate_clock(
        SsrClockCorrection(satellite_id="G01", epoch_time=101.0, high_rate_clock_m=0.5)
    )
    assert store.get_clock("G01").delta_clock_m == pytest.approx(1.0)
    assert store.get_clock("G01").high_rate_clock_m == pytest.approx(0.5)

    store.update_high_rate_clock(
        SsrClockCorrection(satellite_id="G01", epoch_time=102.0, high_rate_clock_m=0.25)
    )
    assert store.get_clock("G01").delta_clock_m == pytest.approx(1.0)
    assert store.get_clock("G01").high_rate_clock_m == pytest.approx(0.25)


def test_ssr_store_reports_orbit_clock_availability():
    store = SsrCorrectionStore()

    assert store.has_orbit_clock_corrections() is False

    store.update_orbit(SsrOrbitCorrection(satellite_id="G01", epoch_time=100.0))
    assert store.has_orbit_clock_corrections() is False

    store.update_clock(SsrClockCorrection(satellite_id="G01", epoch_time=100.0))
    assert store.has_orbit_clock_corrections() is True


def test_ssr_store_ignores_stale_orbit_correction():
    store = SsrCorrectionStore(max_orbit_age_seconds=10.0)
    store.update_orbit(
        SsrOrbitCorrection(
            satellite_id="G01",
            epoch_time=100.0,
            iod=7,
            delta_radial_m=1.0,
        )
    )

    corrected = store.apply_to_state(
        "G01",
        np.array([26_560_000.0, 0.0, 0.0]),
        np.array([0.0, 3_880.0, 0.0]),
        clock_bias_s=0.0,
        transmit_time=130.0,
    )

    assert corrected.applied is False
    assert corrected.position_m.tolist() == pytest.approx([26_560_000.0, 0.0, 0.0])
