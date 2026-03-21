"""Offline and windowed batch processing pipeline."""

from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path

import pandas as pd

from core.reflectometry.outputs import ResultSerializer
from core.reflectometry.outputs import OutputManager
from core.reflectometry.providers import (
    CacheObservationProvider,
    CsvObservationProvider,
    JsonObservationProvider,
    MockObservationProvider,
    ObservationProvider,
    ParquetObservationProvider,
)
from core.reflectometry.config import ReflectorConfig
from core.reflectometry.models import ArcDirection
from core.reflectometry.models import ArcSolution, ObservationRequest, ProcessingRunResult, SnrSeries
from core.reflectometry.logging_utils import configure_logging
from core.reflectometry.services.arc_builder import ArcBuilder
from core.reflectometry.services.geometry import GeometryResolver
from core.reflectometry.services.height_estimator import HeightEstimator
from core.reflectometry.services.preprocessing import SnrPreprocessor
from core.reflectometry.services.products import ProductConverter
from core.reflectometry.services.quality import QualityController
from core.reflectometry.services.spectrum import SpectrumAnalyzer


class BatchProcessor:
    """Configuration-driven GNSS-IR batch pipeline."""

    def __init__(
        self,
        config: ReflectorConfig,
        provider: ObservationProvider | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.logger = logger or configure_logging(config.logging)
        self.provider = provider or self._build_provider()
        self.geometry_resolver = GeometryResolver(config.geometry, processing_config=config.processing)
        self.arc_builder = ArcBuilder(config.processing, config.ir, config.input.sampling_interval)
        self.preprocessor = SnrPreprocessor(config.processing, config.ir)
        self.spectrum_analyzer = SpectrumAnalyzer(config.ir)
        self.quality_controller = QualityController(config.processing, config.qc, config.ir)
        self.height_estimator = HeightEstimator(self.quality_controller)
        self.product_converter = ProductConverter(config.products, environment_type=config.station.environment_type)
        self.output_manager = OutputManager(config.output)
        self._series_by_arc: dict[str, SnrSeries] = {}
        self._spectra_by_arc: dict[str, tuple[list[float], list[float]]] = {}

    def run(self) -> ProcessingRunResult:
        """Run the end-to-end batch pipeline and return structured results."""
        request = self._build_request()
        observations = self.provider.fetch_observations(request)
        self.logger.info("Loaded %d observations from %s", len(observations), self.config.input.source_type)

        observations = self.geometry_resolver.filter_and_resolve(observations)
        arcs = self.arc_builder.build_arcs(observations)
        self.logger.info("Built %d candidate arcs", len(arcs))

        arc_solutions = []
        self._series_by_arc.clear()
        self._spectra_by_arc.clear()
        for arc in arcs:
            try:
                series = self.preprocessor.preprocess(arc)
                spectrum = self.spectrum_analyzer.analyze(series)
                solution = self.height_estimator.solve(arc, series, spectrum)
                self._series_by_arc[arc.arc_id] = series
                self._spectra_by_arc[arc.arc_id] = (solution.spectrum_frequency, solution.spectrum_power)
            except Exception as exc:
                self.logger.warning("Arc %s failed during preprocessing/estimation: %s", arc.arc_id, exc)
                solution = self._failed_solution(arc, str(exc))
            arc_solutions.append(solution)

        products = self.product_converter.convert(arc_solutions)
        aggregates = self.product_converter.aggregate(
            products,
            window_start=request.start_time or (arc_solutions[0].timestamp_start if arc_solutions else datetime.utcnow()),
            window_end=request.end_time or (arc_solutions[-1].timestamp_end if arc_solutions else datetime.utcnow()),
        )
        result = ProcessingRunResult(
            station_id=self.config.station.station_id,
            arc_solutions=arc_solutions,
            products=products,
            window_aggregates=aggregates,
            metadata={"observation_count": len(observations), "arc_count": len(arcs)},
        )
        self.logger.info(
            "Completed batch run: %d arc solutions, %d products",
            len(result.arc_solutions),
            len(result.products),
        )
        return result

    def write_outputs(self, result: ProcessingRunResult) -> list[Path]:
        """Write configured outputs and optional intermediate artifacts."""
        written = self.output_manager.write(result)
        output_dir = Path(self.config.output.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if self.config.output.save_intermediate and self._series_by_arc:
            intermediate_rows = []
            for arc_id, series in self._series_by_arc.items():
                for timestamp, elevation, sin_el, azimuth, snr_db, snr_linear, residual in zip(
                    series.timestamps,
                    series.elevation_deg,
                    series.sin_elevation,
                    series.azimuth_deg,
                    series.snr_db_hz,
                    series.snr_linear,
                    series.residual,
                ):
                    intermediate_rows.append(
                        {
                            "arc_id": arc_id,
                            "timestamp": timestamp,
                            "elevation_deg": elevation,
                            "sin_elevation": sin_el,
                            "azimuth_deg": azimuth,
                            "snr_db_hz": snr_db,
                            "snr_linear": snr_linear,
                            "residual": residual,
                        }
                    )
            path = output_dir / "intermediate_arc_series.csv"
            pd.DataFrame(intermediate_rows).to_csv(path, index=False)
            written.append(path)

        if self.config.output.save_spectrum and self._spectra_by_arc:
            spectrum_rows = []
            for arc_id, (frequency, power) in self._spectra_by_arc.items():
                for freq_value, power_value in zip(frequency, power):
                    spectrum_rows.append({"arc_id": arc_id, "frequency": freq_value, "power": power_value})
            path = output_dir / "arc_spectra.csv"
            pd.DataFrame(spectrum_rows).to_csv(path, index=False)
            written.append(path)

        return written

    def to_dataframes(self, result: ProcessingRunResult) -> dict[str, pd.DataFrame]:
        """Expose DataFrame outputs for notebooks, APIs, or web backends."""
        return ResultSerializer.to_frames(result)

    def get_intermediate_series(self) -> dict[str, SnrSeries]:
        """Return the most recent preprocessed arc series keyed by arc id."""
        return dict(self._series_by_arc)

    def _build_provider(self) -> ObservationProvider:
        source_type = self.config.input.source_type
        station_id = self.config.station.station_id
        receiver_position = self.config.station.receiver_position
        source_path = self.config.input.source_path

        if source_type == "csv":
            return CsvObservationProvider(source_path or "", station_id, receiver_position)
        if source_type == "json":
            return JsonObservationProvider(source_path or "", station_id, receiver_position)
        if source_type == "parquet":
            return ParquetObservationProvider(source_path or "", station_id, receiver_position)
        if source_type == "mock":
            return MockObservationProvider(
                station_id=station_id,
                receiver_position=receiver_position,
                source_options=self.config.input.source_options,
            )
        if source_type == "cache":
            raise ValueError(
                "input.source_type=cache requires injecting a CacheObservationProvider "
                "or another ObservationProvider instance from the host application."
            )
        raise ValueError(f"Unsupported provider source_type: {source_type}")

    def _build_request(self) -> ObservationRequest:
        start_time = (
            datetime.fromisoformat(self.config.input.time_window.start)
            if self.config.input.time_window.start
            else None
        )
        end_time = (
            datetime.fromisoformat(self.config.input.time_window.end)
            if self.config.input.time_window.end
            else None
        )
        return ObservationRequest(
            start_time=start_time,
            end_time=end_time,
            constellations=tuple(self.config.input.constellations),
            signals=tuple(self.config.input.signals),
            exclude_constellations=tuple(self.config.input.exclude_constellations),
            exclude_signals=tuple(self.config.input.exclude_signals),
            sampling_interval_seconds=self.config.input.sampling_interval,
        )

    def _failed_solution(self, arc, reason: str) -> ArcSolution:
        return ArcSolution(
            station_id=arc.station_id,
            arc_id=arc.arc_id,
            timestamp_start=arc.timestamp_start,
            timestamp_end=arc.timestamp_end,
            constellation=arc.constellation,
            satellite=arc.satellite,
            signal=arc.signal,
            arc_direction=arc.direction if arc.direction else ArcDirection.UNKNOWN,
            reflector_height_m=None,
            peak_frequency=None,
            peak_power=None,
            peak_to_noise_ratio=None,
            qc_flags=["processing_failure"],
            success=False,
            fail_reason=reason,
        )


