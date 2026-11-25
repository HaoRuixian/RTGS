"""Regression tests for the EKF reflector-height grid search."""

from __future__ import annotations

import math

import numpy as np
import pytest

from core.reflectometry.services.ekf import _estimate_arc_rh_grid


def _reference_grid_search(
    residual: np.ndarray,
    sin_elevation: np.ndarray,
    wavelength_m: float,
    rh_grid: np.ndarray,
) -> float | None:
    """Retain the original scalar implementation as a compatibility oracle."""
    best_rss = float("inf")
    best_rh = None
    values = residual.reshape(-1, 1)
    for rh_value in rh_grid:
        theta = (4.0 * math.pi * float(rh_value) / wavelength_m) * sin_elevation
        design = np.column_stack((np.sin(theta), np.cos(theta)))
        coefficients, *_ = np.linalg.lstsq(design, values, rcond=None)
        rss = float(np.sum(np.square(values - design @ coefficients)))
        if rss < best_rss:
            best_rss = rss
            best_rh = float(rh_value)
    return best_rh


@pytest.mark.regression
@pytest.mark.parametrize("sample_count", [8, 20, 80])
def test_batched_grid_search_matches_original_solver(sample_count: int) -> None:
    rng = np.random.default_rng(20260726 + sample_count)
    rh_grid = np.linspace(0.2, 8.0, 1024)
    sin_elevation = np.sort(rng.uniform(0.05, 0.75, sample_count))
    wavelength_m = 0.244
    residual = 2.0 * np.sin((4.0 * math.pi * 3.456 / wavelength_m) * sin_elevation + 0.37)
    residual += rng.normal(0.0, 0.2, sample_count)

    expected = _reference_grid_search(
        residual,
        sin_elevation,
        wavelength_m,
        rh_grid,
    )

    assert (
        _estimate_arc_rh_grid(
            residual,
            sin_elevation,
            wavelength_m,
            rh_grid,
        )
        == expected
    )


@pytest.mark.regression
def test_batched_grid_search_preserves_empty_grid_result() -> None:
    empty_grid = np.asarray([], dtype=float)

    assert (
        _estimate_arc_rh_grid(
            np.asarray([1.0, -1.0]),
            np.asarray([0.1, 0.2]),
            0.19,
            empty_grid,
        )
        is None
    )
