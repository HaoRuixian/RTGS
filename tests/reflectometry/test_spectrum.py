"""Spectrum analysis tests for GNSS-IR LSP inversion."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from core.geo_utils import get_freq
from core.reflectometry.models import SnrSeries
from core.reflectometry.services.preprocessing import _resolve_wavelength
from core.reflectometry.services.spectrum import SpectrumAnalyzer


def test_lsp_inversion_recovers_reflector_height_from_descending_arc(example_config):
    example_config.ir.min_reflector_height = 3.0
    example_config.ir.max_reflector_height = 6.0
    example_config.ir.frequency_grid_size = 3000
    example_config.ir.peak_selection.min_prominence = 0.01

    _frequency_hz, wavelength_m = get_freq("1C", "G00")
    true_height_m = 4.35
    elevations = np.linspace(26.0, 6.0, 90)
    sin_elevation = np.sin(np.deg2rad(elevations))
    residual = 2.5 * np.cos((4.0 * np.pi * true_height_m / wavelength_m) * sin_elevation + 0.3)
    start = datetime(2026, 3, 19, 0, 0, 0)

    series = SnrSeries(
        arc_id="TEST-G01-1C-setting",
        timestamps=[start + timedelta(seconds=index * 30) for index in range(len(elevations))],
        elevation_deg=elevations.tolist(),
        sin_elevation=sin_elevation.tolist(),
        azimuth_deg=np.linspace(190.0, 210.0, len(elevations)).tolist(),
        snr_db_hz=(44.0 + residual).tolist(),
        snr_linear=np.power(10.0, (44.0 + residual) / 20.0).tolist(),
        residual=residual.tolist(),
        wavelength_m=wavelength_m,
    )

    result = SpectrumAnalyzer(example_config.ir).analyze(series)

    assert result.candidates
    assert abs(result.candidates[0].reflector_height_m - true_height_m) < 0.12
    assert result.noise_floor == float(np.mean(result.power))


def test_wavelength_resolution_accepts_snr_observation_type_prefix():
    assert _resolve_wavelength("C", "S2I") == _resolve_wavelength("C", "2I")
