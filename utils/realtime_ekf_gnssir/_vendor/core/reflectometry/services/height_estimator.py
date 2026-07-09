"""Reflector height estimation from spectral peaks."""

from __future__ import annotations

from .spectrum import SpectrumAnalysisResult
from ..models import ArcSolution, SatelliteArc, SnrSeries
from .quality import FATAL_QC_FLAGS, QualityController


class HeightEstimator:
    """Select the main peak and convert it into an arc-level solution."""

    def __init__(self, quality_controller: QualityController) -> None:
        self.quality_controller = quality_controller

    def solve(
        self,
        arc: SatelliteArc,
        series: SnrSeries,
        spectrum: SpectrumAnalysisResult,
    ) -> ArcSolution:
        """Build an arc solution from a spectrum result."""
        primary = spectrum.candidates[0] if spectrum.candidates else None
        quality_metrics = self.quality_controller.assess(arc, series, primary, spectrum.candidates)
        fatal_flags = [flag for flag in quality_metrics.qc_flags if flag in FATAL_QC_FLAGS]

        fail_reason = None
        success = True
        peak_frequency = primary.spectral_frequency if primary else None
        reflector_height_m = 0.5 * series.wavelength_m * peak_frequency if peak_frequency is not None else None
        peak_power = primary.power if primary else None
        peak_to_noise_ratio = primary.peak_to_noise_ratio if primary else None
        primary_candidates = [primary] if primary is not None else []

        if primary is None:
            success = False
            fail_reason = "no_spectral_peak"
        elif fatal_flags:
            success = False
            fail_reason = ",".join(fatal_flags)

        return ArcSolution(
            station_id=arc.station_id,
            arc_id=arc.arc_id,
            timestamp_start=arc.timestamp_start,
            timestamp_end=arc.timestamp_end,
            constellation=arc.constellation,
            satellite=arc.satellite,
            signal=arc.signal,
            arc_direction=arc.direction,
            reflector_height_m=reflector_height_m,
            peak_frequency=peak_frequency,
            peak_power=peak_power,
            peak_to_noise_ratio=peak_to_noise_ratio,
            qc_flags=quality_metrics.qc_flags,
            success=success,
            fail_reason=fail_reason,
            wavelength_m=series.wavelength_m,
            candidates=primary_candidates,
            quality_metrics=quality_metrics,
            spectrum_frequency=spectrum.frequencies.tolist(),
            spectrum_power=spectrum.power.tolist(),
            metadata={
                **arc.metadata,
                "noise_floor": spectrum.noise_floor,
            },
        )


