"""Spectrum analysis service and helper routines."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.signal import find_peaks, lombscargle, peak_widths

from core.reflectometry.config import IrConfig
from core.reflectometry.models import PeakCandidate, SnrSeries


@dataclass(slots=True)
class SpectrumAnalysisResult:
    """Spectrum result bundle returned by the analyzer."""

    frequencies: np.ndarray
    power: np.ndarray
    noise_floor: float
    candidates: list[PeakCandidate] = field(default_factory=list)


def compute_lomb_scargle(
    x: np.ndarray,
    y: np.ndarray,
    frequencies: np.ndarray,
    normalize: str = "power",
    floating_mean: bool = True,
) -> np.ndarray:
    """Compute Lomb-Scargle power for non-uniformly sampled data."""
    angular_frequencies = 2.0 * np.pi * frequencies
    return lombscargle(
        x,
        y,
        angular_frequencies,
        normalize=normalize,
        floating_mean=floating_mean,
    )


def detect_peaks(
    frequencies: np.ndarray,
    power: np.ndarray,
    wavelength_m: float,
    min_prominence: float,
    min_width_bins: float,
    max_candidates: int,
    prefer_high_power: bool,
) -> SpectrumAnalysisResult:
    """Detect and rank spectral peaks."""
    if len(power) == 0:
        return SpectrumAnalysisResult(frequencies=frequencies, power=power, noise_floor=0.0, candidates=[])

    noise_floor = float(np.mean(power))
    peak_indices, properties = find_peaks(power, prominence=min_prominence)
    if len(peak_indices) == 0:
        return SpectrumAnalysisResult(frequencies=frequencies, power=power, noise_floor=noise_floor, candidates=[])

    widths = peak_widths(power, peak_indices, rel_height=0.5)[0]
    candidates: list[PeakCandidate] = []
    for index, peak_index in enumerate(peak_indices):
        width = float(widths[index])
        if width < min_width_bins:
            continue
        peak_power = float(power[peak_index])
        prominence = float(properties["prominences"][index])
        frequency = float(frequencies[peak_index])
        reflector_height = 0.5 * wavelength_m * frequency
        peak_to_noise = peak_power / max(noise_floor, 1e-12)
        candidates.append(
            PeakCandidate(
                rank=0,
                peak_index=int(peak_index),
                spectral_frequency=frequency,
                reflector_height_m=reflector_height,
                power=peak_power,
                prominence=prominence,
                width=width,
                peak_to_noise_ratio=peak_to_noise,
                metadata={"spectral_contrast": peak_power - noise_floor},
            )
        )

    sort_key = (
        (lambda item: (item.power, item.peak_to_noise_ratio, item.prominence))
        if prefer_high_power
        else (lambda item: (item.peak_to_noise_ratio, item.prominence, item.power))
    )
    ranked = sorted(candidates, key=sort_key, reverse=True)[:max_candidates]
    for rank, candidate in enumerate(ranked, start=1):
        candidate.rank = rank

    return SpectrumAnalysisResult(
        frequencies=frequencies,
        power=power,
        noise_floor=noise_floor,
        candidates=ranked,
    )


class SpectrumAnalyzer:
    """Compute Lomb-Scargle spectrum and identify spectral peaks."""

    def __init__(self, config: IrConfig) -> None:
        self.config = config

    def analyze(self, series: SnrSeries) -> SpectrumAnalysisResult:
        """Run spectral analysis on a preprocessed SNR series."""
        x = np.asarray(series.sin_elevation, dtype=float)
        y = np.asarray(series.residual, dtype=float)
        order = np.argsort(x)
        x = x[order]
        y = y[order]

        if len(x) < 3 or np.ptp(x) <= 1e-6:
            return SpectrumAnalysisResult(
                frequencies=np.array([], dtype=float),
                power=np.array([], dtype=float),
                noise_floor=0.0,
                candidates=[],
            )

        frequency_min, frequency_max = self._frequency_range(series.wavelength_m)
        frequencies = np.linspace(frequency_min, frequency_max, self.config.frequency_grid_size)
        power = compute_lomb_scargle(
            x=x,
            y=y,
            frequencies=frequencies,
            normalize=self.config.lomb_scargle.normalize,
            floating_mean=self.config.lomb_scargle.floating_mean,
        )
        power = _normalize_lsp_amplitude(power, sample_count=len(x))
        return detect_peaks(
            frequencies=frequencies,
            power=power,
            wavelength_m=series.wavelength_m,
            min_prominence=self.config.peak_selection.min_prominence,
            min_width_bins=self.config.peak_selection.min_width_bins,
            max_candidates=max(self.config.peak_selection.max_candidates, 3),
            prefer_high_power=self.config.peak_selection.prefer_high_power,
        )

    def _frequency_range(self, wavelength_m: float) -> tuple[float, float]:
        if self.config.frequency_search_mode == "explicit_frequency":
            if self.config.explicit_frequency_min is None or self.config.explicit_frequency_max is None:
                raise ValueError("Explicit frequency mode requires ir.explicit_frequency_min/max")
            return float(self.config.explicit_frequency_min), float(self.config.explicit_frequency_max)

        frequency_min = 2.0 * self.config.min_reflector_height / wavelength_m
        frequency_max = 2.0 * self.config.max_reflector_height / wavelength_m
        return frequency_min, frequency_max


def _normalize_lsp_amplitude(power: np.ndarray, *, sample_count: int) -> np.ndarray:
    """Convert Lomb-Scargle power into MATLAB snr2RH_lsp-style amplitude."""
    if power.size == 0:
        return power
    clipped = np.clip(np.asarray(power, dtype=float), 0.0, None)
    return 2.0 * np.sqrt(clipped / max(sample_count, 1))
