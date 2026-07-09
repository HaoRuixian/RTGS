"""Observation-provider processing pipeline for GNSS-IR runs."""

from __future__ import annotations

import csv
from datetime import datetime
import json
import logging
from pathlib import Path

try:
    import pandas as pd
except Exception:  # pragma: no cover - optional CSV/DataFrame dependency
    pd = None

from ..outputs import ResultSerializer
from ..outputs import OutputManager
from ..providers import ObservationProvider
from ..config import ReflectorConfig
from ..models import ArcDirection
from ..models import ArcSolution, ObservationRequest, ProcessingRunResult, SnrSeries
from ..logging_utils import configure_logging
from .arc_builder import ArcBuilder
from .ekf import EkfReflectometryProcessor
from .geometry import GeometryResolver
from .height_estimator import HeightEstimator
from .preprocessing import SnrPreprocessor
from .products import ProductConverter
from .quality import QualityController
from .spectrum import SpectrumAnalyzer


def _require_pandas():
    if pd is None:
        raise RuntimeError("pandas is required for CSV/DataFrame reflectometry outputs.")
    return pd


def _write_csv_rows(path: Path, rows: list[dict]) -> None:
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if fieldnames:
            writer.writeheader()
            for row in rows:
                writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _csv_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value


class BatchProcessor:
    """Observation-provider-driven GNSS-IR processing pipeline."""

    def __init__(
        self,
        config: ReflectorConfig,
        provider: ObservationProvider | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.logger = logger or configure_logging(config.logging)
        if provider is None:
            raise ValueError("BatchProcessor now requires an explicit ObservationProvider.")
        self.provider = provider
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
        self.logger.info("Loaded %d observations from %s", len(observations), type(self.provider).__name__)

        observations = self.geometry_resolver.filter_and_resolve(observations)
        if self.config.ir.estimation_mode == "ekf":
            return self._run_ekf(observations)

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
            window_start=arc_solutions[0].timestamp_start if arc_solutions else datetime.utcnow(),
            window_end=arc_solutions[-1].timestamp_end if arc_solutions else datetime.utcnow(),
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

    def _run_ekf(self, observations) -> ProcessingRunResult:
        ekf_processor = EkfReflectometryProcessor(
            self.config.ir,
            self.config.products,
            station_id=self.config.station.station_id,
            sampling_interval_seconds=self.config.input.sampling_interval,
        )
        outputs = ekf_processor.ingest(observations)
        products = ekf_processor.build_products(outputs)
        if products:
            start_time = products[0].timestamp
            end_time = products[-1].timestamp
        else:
            start_time = datetime.utcnow()
            end_time = start_time
        aggregates = self.product_converter.aggregate(products, window_start=start_time, window_end=end_time)
        result = ProcessingRunResult(
            station_id=self.config.station.station_id,
            arc_solutions=[],
            products=products,
            window_aggregates=aggregates,
            metadata={
                "estimation_mode": "ekf",
                "observation_count": len(observations),
                "ekf_output_count": len(outputs),
            },
        )
        self.logger.info(
            "Completed EKF batch run: %d outputs, %d products",
            len(outputs),
            len(products),
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
            _write_csv_rows(path, intermediate_rows)
            written.append(path)

        if self.config.output.save_spectrum and self._spectra_by_arc:
            spectrum_rows = []
            for arc_id, (frequency, power) in self._spectra_by_arc.items():
                for freq_value, power_value in zip(frequency, power):
                    spectrum_rows.append({"arc_id": arc_id, "frequency": freq_value, "power": power_value})
            path = output_dir / "arc_spectra.csv"
            _write_csv_rows(path, spectrum_rows)
            written.append(path)

        return written

    def to_dataframes(self, result: ProcessingRunResult) -> dict[str, pd.DataFrame]:
        """Expose DataFrame outputs for notebooks, APIs, or web backends."""
        return ResultSerializer.to_frames(result)

    def get_intermediate_series(self) -> dict[str, SnrSeries]:
        """Return the most recent preprocessed arc series keyed by arc id."""
        return dict(self._series_by_arc)

    def _build_request(self) -> ObservationRequest:
        return ObservationRequest(
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
