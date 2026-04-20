"""SNR preprocessing for GNSS-IR spectral analysis."""

from __future__ import annotations

import numpy as np
from scipy.signal import savgol_filter

from core.geo_utils import get_freq
from core.reflectometry.config import IrConfig, ProcessingConfig, minimum_required_arc_samples
from core.reflectometry.models import SnrUnit
from core.reflectometry.models import SatelliteArc, SnrSeries


class SnrPreprocessor:
    """Normalize, filter, detrend, and package SNR series."""

    def __init__(
        self,
        processing_config: ProcessingConfig,
        ir_config: IrConfig,
    ) -> None:
        self.processing_config = processing_config
        self.ir_config = ir_config

    def preprocess(self, arc: SatelliteArc) -> SnrSeries:
        """Convert a raw arc into a detrended residual series."""
        timestamps = []
        elevations = []
        azimuths = []
        snr_db_values = []
        snr_linear_values = []

        wavelength_m = _resolve_wavelength(
            arc.constellation,
            arc.signal,
            overrides=self.ir_config.wavelength_overrides_m,
        )

        for observation in arc.observations:
            if observation.elevation_deg is None or observation.azimuth_deg is None:
                continue
            if observation.snr_unit == SnrUnit.LINEAR:
                snr_linear = float(observation.snr)
                snr_db_hz = float(_linear_to_dbhz(np.array([snr_linear], dtype=float))[0])
            else:
                snr_db_hz = float(observation.snr)
                snr_linear = float(_dbhz_to_linear(np.array([snr_db_hz], dtype=float))[0])

            timestamps.append(observation.timestamp)
            elevations.append(float(observation.elevation_deg))
            azimuths.append(float(observation.azimuth_deg))
            snr_db_values.append(snr_db_hz)
            snr_linear_values.append(snr_linear)

        minimum_samples = minimum_required_arc_samples(self.processing_config)

        if len(timestamps) < minimum_samples:
            raise ValueError("Not enough samples remain after geometry filtering")

        snr_db = np.asarray(snr_db_values, dtype=float)
        snr_linear = np.asarray(snr_linear_values, dtype=float)
        elevation_deg = np.asarray(elevations, dtype=float)
        azimuth_deg = np.asarray(azimuths, dtype=float)
        sin_elevation = _sin_elevation_deg(elevation_deg)

        mask = self._build_outlier_mask(snr_db)
        if np.count_nonzero(mask) < minimum_samples:
            raise ValueError("Outlier rejection removed too many samples")

        timestamps = [timestamp for timestamp, keep in zip(timestamps, mask) if keep]
        snr_db = snr_db[mask]
        snr_linear = snr_linear[mask]
        elevation_deg = elevation_deg[mask]
        azimuth_deg = azimuth_deg[mask]
        sin_elevation = sin_elevation[mask]

        smoothed_linear = self._smooth(snr_linear)
        detrend_x = sin_elevation if "sin_elevation" in self.processing_config.detrend_method else elevation_deg
        residual, trend = _detrend_polynomial(detrend_x, smoothed_linear, self.processing_config.detrend_order)

        return SnrSeries(
            arc_id=arc.arc_id,
            timestamps=timestamps,
            elevation_deg=elevation_deg.tolist(),
            sin_elevation=sin_elevation.tolist(),
            azimuth_deg=azimuth_deg.tolist(),
            snr_db_hz=snr_db.tolist(),
            snr_linear=smoothed_linear.tolist(),
            residual=residual.tolist(),
            wavelength_m=wavelength_m,
            metadata={
                "removed_outliers": int(len(mask) - np.count_nonzero(mask)),
                "trend_preview": trend[: min(5, len(trend))].tolist(),
            },
        )

    def _build_outlier_mask(self, snr_db: np.ndarray) -> np.ndarray:
        if self.processing_config.outlier_method == "mad":
            return _mad_mask(snr_db, self.processing_config.outlier_threshold)
        if self.processing_config.outlier_method == "sigma":
            return _sigma_mask(snr_db, self.processing_config.outlier_threshold)
        return np.ones(snr_db.shape, dtype=bool)

    def _smooth(self, values: np.ndarray) -> np.ndarray:
        method = self.processing_config.smoothing_method
        window = self.processing_config.smoothing_window
        if method == "moving_average":
            return _moving_average(values, window)
        if method == "savgol":
            return _savgol(values, window, polyorder=min(self.processing_config.detrend_order, 3))
        return values.copy()


def _resolve_wavelength(
    constellation: str,
    signal: str,
    overrides: dict[str, float] | None = None,
) -> float:
    """Resolve wavelength using shared core frequency utilities plus IR overrides."""
    key = f"{constellation}:{signal}"
    if overrides and key in overrides:
        return float(overrides[key])

    _frequency_hz, wavelength_m = get_freq(signal, f"{constellation}00")
    if wavelength_m > 0.0:
        return float(wavelength_m)

    raise ValueError(
        f"Unknown wavelength for constellation={constellation!r}, signal={signal!r}. "
        "Provide ir.wavelength_overrides_m to extend support."
    )


def _dbhz_to_linear(values: np.ndarray) -> np.ndarray:
    """Convert dB-Hz SNR values into the linear domain used by preprocessing."""
    return np.power(10.0, values / 20.0)


def _linear_to_dbhz(values: np.ndarray) -> np.ndarray:
    """Convert linear-domain SNR values back to dB-Hz."""
    clipped = np.clip(values, 1e-12, None)
    return 20.0 * np.log10(clipped)


def _sin_elevation_deg(values_deg: np.ndarray) -> np.ndarray:
    """Compute sin(elevation) directly from degree values."""
    return np.sin(np.deg2rad(values_deg))


def _fit_polynomial_trend(x: np.ndarray, y: np.ndarray, order: int) -> np.ndarray:
    """Fit a polynomial trend line for SNR detrending."""
    effective_order = min(order, max(len(x) - 1, 1))
    coefficients = np.polyfit(x, y, effective_order)
    polynomial = np.poly1d(coefficients)
    return polynomial(x)


def _detrend_polynomial(x: np.ndarray, y: np.ndarray, order: int) -> tuple[np.ndarray, np.ndarray]:
    """Remove a polynomial trend from a series and return residual and trend."""
    trend = _fit_polynomial_trend(x, y, order)
    residual = y - trend
    residual -= np.mean(residual)
    return residual, trend


def _mad_mask(values: np.ndarray, threshold: float) -> np.ndarray:
    """Return a boolean mask based on median absolute deviation."""
    median = np.median(values)
    deviation = np.abs(values - median)
    mad = np.median(deviation)
    if mad <= 1e-12:
        return np.ones(values.shape, dtype=bool)
    modified_z = 0.6745 * deviation / mad
    return modified_z <= threshold


def _sigma_mask(values: np.ndarray, threshold: float) -> np.ndarray:
    """Return a boolean mask based on standard deviation."""
    mean = np.mean(values)
    std = np.std(values)
    if std <= 1e-12:
        return np.ones(values.shape, dtype=bool)
    return np.abs(values - mean) <= threshold * std


def _moving_average(values: np.ndarray, window: int) -> np.ndarray:
    """Apply a centered moving-average smoother."""
    if window <= 1 or len(values) < window:
        return values.copy()
    kernel = np.ones(window, dtype=float) / float(window)
    return np.convolve(values, kernel, mode="same")


def _savgol(values: np.ndarray, window: int, polyorder: int = 2) -> np.ndarray:
    """Apply Savitzky-Golay smoothing when enough samples are available."""
    if len(values) < window or window < 3:
        return values.copy()
    if window % 2 == 0:
        window += 1
    effective_polyorder = min(polyorder, window - 1)
    return savgol_filter(values, window_length=window, polyorder=effective_polyorder, mode="interp")

