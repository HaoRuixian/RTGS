"""Quality control and scoring."""

from __future__ import annotations

from statistics import mean

import numpy as np

from core.reflectometry.config import IrConfig, ProcessingConfig, QcConfig, minimum_required_arc_samples
from core.reflectometry.models import PeakCandidate, QualityMetrics, SatelliteArc, SnrSeries

FATAL_QC_FLAGS = {
    "short_arc",
    "high_gap_ratio",
    "low_snr_amplitude",
    "low_peak_to_noise",
    "ambiguous_spectrum",
    "multipath_outlier",
}


class QualityController:
    """Evaluate arc and spectral quality."""

    def __init__(
        self,
        processing_config: ProcessingConfig,
        qc_config: QcConfig,
        ir_config: IrConfig,
    ) -> None:
        self.processing_config = processing_config
        self.qc_config = qc_config
        self.ir_config = ir_config

    def assess(
        self,
        arc: SatelliteArc,
        series: SnrSeries,
        candidate: PeakCandidate | None,
        candidates: list[PeakCandidate],
    ) -> QualityMetrics:
        """Compute QC flags and a confidence score."""
        flags: list[str] = []

        if arc.statistics.duration_seconds < self.qc_config.min_arc_duration:
            flags.append("short_arc")
        if arc.statistics.time_gap_ratio > self.qc_config.max_gap_ratio:
            flags.append("high_gap_ratio")
        if arc.statistics.snr_amplitude_db_hz < self.qc_config.min_snr_amplitude:
            flags.append("low_snr_amplitude")
        if candidate is None or candidate.peak_to_noise_ratio < self.qc_config.min_peak_to_noise_ratio:
            flags.append("low_peak_to_noise")
        if self._primary_peak_ratio(candidates) < self.qc_config.min_primary_peak_ratio:
            flags.append("ambiguous_spectrum")
        if self.qc_config.reject_multipath_outliers and self._has_multipath_outliers(arc):
            flags.append("multipath_outlier")
        if self.ir_config.harmonic_check and self._has_harmonic(candidate, candidates):
            flags.append("harmonic_candidate_present")

        residual_rms = float(np.sqrt(np.mean(np.square(np.asarray(series.residual, dtype=float)))))
        confidence = self._compute_confidence(arc, candidate, flags)
        return QualityMetrics(
            sample_count=arc.statistics.sample_count,
            duration_seconds=arc.statistics.duration_seconds,
            gap_ratio=arc.statistics.time_gap_ratio,
            snr_amplitude_db_hz=arc.statistics.snr_amplitude_db_hz,
            residual_rms=residual_rms,
            peak_power=candidate.power if candidate else None,
            peak_to_noise_ratio=candidate.peak_to_noise_ratio if candidate else None,
            confidence=confidence,
            qc_flags=flags,
        )

    def _compute_confidence(
        self,
        arc: SatelliteArc,
        candidate: PeakCandidate | None,
        flags: list[str],
    ) -> float:
        scores = [
            min(1.0, arc.statistics.sample_count / max(minimum_required_arc_samples(self.processing_config) * 2.0, 1.0)),
            min(1.0, arc.statistics.duration_seconds / max(self.qc_config.min_arc_duration * 2.0, 1.0)),
            max(0.0, 1.0 - arc.statistics.time_gap_ratio / max(self.qc_config.max_gap_ratio, 1e-6)),
            min(1.0, arc.statistics.snr_amplitude_db_hz / max(self.qc_config.min_snr_amplitude * 2.0, 1e-6)),
        ]
        if candidate is not None:
            scores.append(
                min(
                    1.0,
                    candidate.peak_to_noise_ratio / max(self.qc_config.min_peak_to_noise_ratio * 2.0, 1e-6),
                )
            )
        penalty = max(0.0, 1.0 - 0.15 * sum(flag in FATAL_QC_FLAGS for flag in flags))
        return round(float(mean(scores)) * penalty, 4)

    def _has_multipath_outliers(self, arc: SatelliteArc) -> bool:
        multipath = [obs.multipath_indicator for obs in arc.observations if obs.multipath_indicator is not None]
        if len(multipath) < 5:
            return False
        values = np.asarray(multipath, dtype=float)
        median = np.median(values)
        mad = np.median(np.abs(values - median))
        if mad <= 1e-12:
            return False
        modified_z = 0.6745 * np.abs(values - median) / mad
        return bool(np.mean(modified_z > 3.5) > 0.1)

    @staticmethod
    def _has_harmonic(candidate: PeakCandidate | None, candidates: list[PeakCandidate]) -> bool:
        if candidate is None:
            return False
        for other in candidates[1:]:
            ratio = other.reflector_height_m / max(candidate.reflector_height_m, 1e-6)
            if abs(ratio - 2.0) < 0.15 or abs(ratio - 0.5) < 0.1:
                if other.power >= 0.6 * candidate.power:
                    return True
        return False

    @staticmethod
    def _primary_peak_ratio(candidates: list[PeakCandidate]) -> float:
        if len(candidates) < 2:
            return float("inf")
        primary = max(candidates[0].power, 1e-12)
        secondary = max(candidates[1].power, 1e-12)
        return primary / secondary


