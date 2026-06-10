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
    assert corrected.clock_bias_s == pytest.approx(1.0e-6 + 0.7 / 299_792_458.0)


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
