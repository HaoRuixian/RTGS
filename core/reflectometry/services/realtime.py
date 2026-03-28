"""Stateful near-real-time processor for realtime reflectometry."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timedelta
import logging
from pathlib import Path

from core.reflectometry.providers import ListObservationProvider
from core.reflectometry.config import ReflectorConfig, minimum_required_arc_samples
from core.reflectometry.models import ArcSolution, ObservationRecord, ProcessingRunResult, SnrSeries
from core.reflectometry.services.batch import BatchProcessor


class RealtimeProcessor:
    """Maintain open arcs, finalize closed arcs, and emit realtime preview solutions."""

    def __init__(
        self,
        config: ReflectorConfig,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.logger = logger
        self.batch_processor = BatchProcessor(
            config=deepcopy(config),
            provider=ListObservationProvider([]),
            logger=logger,
        )
        self.buffers: dict[tuple[str, str, str], list[ObservationRecord]] = defaultdict(list)
        self.final_solutions: dict[str, ArcSolution] = {}
        self.final_series_by_arc: dict[str, SnrSeries] = {}
        self.final_spectra_by_arc: dict[str, tuple[list[float], list[float]]] = {}
        self._series_by_arc: dict[str, SnrSeries] = {}
        self._spectra_by_arc: dict[str, tuple[list[float], list[float]]] = {}
        self.last_result = ProcessingRunResult(
            station_id=self.config.station.station_id,
            arc_solutions=[],
            products=[],
            window_aggregates=[],
        )

    def ingest(
        self,
        observations: list[ObservationRecord],
        *,
        reference_time: datetime | None = None,
        window_seconds: float | None = None,
        include_open_preview: bool = True,
    ) -> ProcessingRunResult:
        """Ingest new observations and return a current realtime snapshot."""
        ordered = sorted(observations, key=lambda item: item.timestamp)
        completed_records: list[ObservationRecord] = []
        latest_timestamp = reference_time

        for observation in ordered:
            latest_timestamp = observation.timestamp
            key = observation.satellite_system_key
            buffer = self.buffers[key]
            if buffer and self._should_split(buffer[-1], observation):
                completed_records.extend(buffer)
                self.buffers[key] = [observation]
            else:
                buffer.append(observation)

        if latest_timestamp is None:
            latest_timestamp = reference_time or datetime.utcnow()

        self._trim_open_buffers(latest_timestamp, window_seconds)
        completed_records.extend(self._collect_stale_buffers(latest_timestamp))

        if completed_records:
            result, series_by_arc, spectra_by_arc = self._run_records(completed_records)
            for solution in result.arc_solutions:
                self.final_solutions[solution.arc_id] = solution
            self.final_series_by_arc.update(series_by_arc)
            self.final_spectra_by_arc.update(spectra_by_arc)

        return self.snapshot(
            reference_time=latest_timestamp,
            window_seconds=window_seconds,
            include_open_preview=include_open_preview,
        )

    def snapshot(
        self,
        *,
        reference_time: datetime | None = None,
        window_seconds: float | None = None,
        include_open_preview: bool = True,
    ) -> ProcessingRunResult:
        """Compose a realtime snapshot from finalized arcs plus optional open-arc previews."""
        snapshot_time = reference_time or datetime.utcnow()
        self._trim_open_buffers(snapshot_time, window_seconds)
        stale_records = self._collect_stale_buffers(snapshot_time)
        if stale_records:
            result, series_by_arc, spectra_by_arc = self._run_records(stale_records)
            for solution in result.arc_solutions:
                self.final_solutions[solution.arc_id] = solution
            self.final_series_by_arc.update(series_by_arc)
            self.final_spectra_by_arc.update(spectra_by_arc)
        window_start = snapshot_time - timedelta(seconds=window_seconds) if window_seconds else None
        self._prune_history(window_start)

        preview_solutions: dict[str, ArcSolution] = {}
        preview_series: dict[str, SnrSeries] = {}
        preview_spectra: dict[str, tuple[list[float], list[float]]] = {}
        if include_open_preview:
            preview_observations = [
                item
                for buffer in self.buffers.values()
                if self._buffer_is_ready_for_preview(buffer, window_seconds=window_seconds)
                for item in buffer
            ]
            if preview_observations:
                preview_result, preview_series, preview_spectra = self._run_records(preview_observations)
                preview_solutions = {solution.arc_id: solution for solution in preview_result.arc_solutions}

        final_solutions = self._windowed_final_solutions(window_start)
        merged_solutions = dict(preview_solutions)
        merged_solutions.update(final_solutions)

        self._series_by_arc = dict(preview_series)
        self._series_by_arc.update(self._windowed_mapping(self.final_series_by_arc, final_solutions))
        self._spectra_by_arc = dict(preview_spectra)
        self._spectra_by_arc.update(self._windowed_mapping(self.final_spectra_by_arc, final_solutions))

        solutions = sorted(merged_solutions.values(), key=lambda item: item.timestamp_end)
        if solutions:
            start_time = window_start or solutions[0].timestamp_start
            end_time = max(snapshot_time, solutions[-1].timestamp_end)
        else:
            start_time = window_start or snapshot_time
            end_time = snapshot_time

        products = self.batch_processor.product_converter.convert(solutions)
        aggregates = self.batch_processor.product_converter.aggregate(products, start_time, end_time)
        self.last_result = ProcessingRunResult(
            station_id=self.config.station.station_id,
            arc_solutions=solutions,
            products=products,
            window_aggregates=aggregates,
            metadata={
                "mode": "realtime",
                "open_arc_count": len(preview_solutions),
                "final_arc_count": len(final_solutions),
            },
        )
        return self.last_result

    def flush(self) -> ProcessingRunResult:
        """Finalize all open arcs."""
        completed_records: list[ObservationRecord] = []
        for key, buffer in list(self.buffers.items()):
            completed_records.extend(buffer)
            del self.buffers[key]
        if completed_records:
            result, series_by_arc, spectra_by_arc = self._run_records(completed_records)
            for solution in result.arc_solutions:
                self.final_solutions[solution.arc_id] = solution
            self.final_series_by_arc.update(series_by_arc)
            self.final_spectra_by_arc.update(spectra_by_arc)
            return self.snapshot(reference_time=max(item.timestamp for item in completed_records))
        return self.snapshot()

    def reset(self) -> None:
        """Clear realtime state and cached results."""
        self.buffers.clear()
        self.clear_finalized_history()
        self._series_by_arc.clear()
        self._spectra_by_arc.clear()
        self.last_result = ProcessingRunResult(
            station_id=self.config.station.station_id,
            arc_solutions=[],
            products=[],
            window_aggregates=[],
        )

    def clear_finalized_history(self) -> None:
        """Drop finalized arc caches to keep realtime mode lightweight."""
        self.final_solutions.clear()
        self.final_series_by_arc.clear()
        self.final_spectra_by_arc.clear()

    def write_outputs(self, result: ProcessingRunResult) -> list[Path]:
        """Write realtime outputs using the same serializers as batch mode."""
        original_series = self.batch_processor._series_by_arc
        original_spectra = self.batch_processor._spectra_by_arc
        self.batch_processor._series_by_arc = dict(self._series_by_arc)
        self.batch_processor._spectra_by_arc = dict(self._spectra_by_arc)
        try:
            return self.batch_processor.write_outputs(result)
        finally:
            self.batch_processor._series_by_arc = original_series
            self.batch_processor._spectra_by_arc = original_spectra

    def to_dataframes(self, result: ProcessingRunResult):
        """Expose tabular outputs for APIs and notebooks."""
        return self.batch_processor.to_dataframes(result)

    def get_intermediate_series(self) -> dict[str, SnrSeries]:
        """Return current finalized plus preview series keyed by arc id."""
        return dict(self._series_by_arc)

    def _collect_stale_buffers(self, reference_time: datetime) -> list[ObservationRecord]:
        stale_records: list[ObservationRecord] = []
        stale_keys = [
            key
            for key, buffer in self.buffers.items()
            if buffer
            and (reference_time - buffer[-1].timestamp).total_seconds() > self.config.processing.max_time_gap_seconds
        ]
        for key in stale_keys:
            stale_records.extend(self.buffers.pop(key))
        return stale_records

    def _trim_open_buffers(self, reference_time: datetime, window_seconds: float | None) -> None:
        """Discard open-arc samples older than the realtime analysis window."""
        if window_seconds is None or window_seconds <= 0:
            return
        cutoff = reference_time - timedelta(seconds=window_seconds)
        for key, buffer in list(self.buffers.items()):
            trimmed = [item for item in buffer if item.timestamp >= cutoff]
            if trimmed:
                self.buffers[key] = trimmed
            else:
                self.buffers.pop(key, None)

    def _windowed_final_solutions(self, window_start: datetime | None) -> dict[str, ArcSolution]:
        if window_start is None:
            return dict(self.final_solutions)
        return {
            arc_id: solution
            for arc_id, solution in self.final_solutions.items()
            if solution.timestamp_end >= window_start
        }

    @staticmethod
    def _windowed_mapping(mapping, valid_solutions: dict[str, ArcSolution]):
        return {arc_id: mapping[arc_id] for arc_id in valid_solutions if arc_id in mapping}

    def _prune_history(self, window_start: datetime | None) -> None:
        if window_start is None:
            return
        stale_arc_ids = [
            arc_id
            for arc_id, solution in self.final_solutions.items()
            if solution.timestamp_end < window_start
        ]
        for arc_id in stale_arc_ids:
            self.final_solutions.pop(arc_id, None)
            self.final_series_by_arc.pop(arc_id, None)
            self.final_spectra_by_arc.pop(arc_id, None)

    def _run_records(
        self,
        observations: list[ObservationRecord],
    ) -> tuple[ProcessingRunResult, dict[str, SnrSeries], dict[str, tuple[list[float], list[float]]]]:
        if not observations:
            empty = ProcessingRunResult(
                station_id=self.config.station.station_id,
                arc_solutions=[],
                products=[],
                window_aggregates=[],
            )
            return empty, {}, {}

        original_provider = self.batch_processor.provider
        self.batch_processor.provider = ListObservationProvider(sorted(observations, key=lambda item: item.timestamp))
        try:
            result = self.batch_processor.run()
            series = self.batch_processor.get_intermediate_series()
            spectra = dict(self.batch_processor._spectra_by_arc)
            return result, series, spectra
        finally:
            self.batch_processor.provider = original_provider

    def _should_split(self, previous: ObservationRecord, current: ObservationRecord) -> bool:
        time_gap = (current.timestamp - previous.timestamp).total_seconds()
        if time_gap > self.config.processing.max_time_gap_seconds:
            return True
        if previous.elevation_deg is None or current.elevation_deg is None:
            return True
        buffer = self.buffers[current.satellite_system_key]
        if len(buffer) < 2 or buffer[-2].elevation_deg is None:
            return False
        previous_delta = (buffer[-1].elevation_deg or 0.0) - (buffer[-2].elevation_deg or 0.0)
        current_delta = (current.elevation_deg or 0.0) - (previous.elevation_deg or 0.0)
        if abs(previous_delta) <= 1e-6 or abs(current_delta) <= 1e-6:
            return False
        return (previous_delta > 0 > current_delta) or (previous_delta < 0 < current_delta)

    def _buffer_is_ready_for_preview(
        self,
        buffer: list[ObservationRecord],
        *,
        window_seconds: float | None = None,
    ) -> bool:
        if len(buffer) < minimum_required_arc_samples(self.config.processing):
            return False
        if len(buffer) < 2:
            return False
        duration_seconds = (buffer[-1].timestamp - buffer[0].timestamp).total_seconds()
        required_duration = max(
            float(self.config.qc.min_arc_duration),
            float(window_seconds or 0.0),
        )
        return duration_seconds >= required_duration
