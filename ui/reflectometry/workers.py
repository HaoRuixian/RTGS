"""Background workers for reflectometry file analysis."""

from __future__ import annotations

from copy import deepcopy
import logging
import threading

from PySide6.QtCore import QObject, Signal

from core.rinex_loader import FileEphemerisProvider, RinexObservationReader
from core.reflectometry import BatchProcessor, ListObservationProvider, ProcessingRunResult, RealtimeProcessor
from core.reflectometry.rinex_batch import build_observation_records_from_epoch


class ReflectometryBatchSignals(QObject):
    """Qt signals for background reflectometry file analysis."""

    log_signal = Signal(str)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()


class RinexBatchAnalysisThread(threading.Thread):
    """Process a RINEX observation file into final reflectometry products."""

    def __init__(
        self,
        *,
        obs_settings: dict,
        eph_settings: dict,
        ir_config,
        active_systems: set[str],
        target_systems: list[str] | None,
        receiver_position,
        receiver_position_ecef: list[float] | None,
        station_id: str,
        handler=None,
        logger: logging.Logger | None = None,
        signals: ReflectometryBatchSignals | None = None,
        use_realtime_logic: bool = False,
        live_window_seconds: float | None = None,
        analysis_interval_seconds: float | None = None,
    ) -> None:
        super().__init__()
        self.obs_settings = deepcopy(obs_settings)
        self.eph_settings = deepcopy(eph_settings)
        self.ir_config = deepcopy(ir_config)
        self.active_systems = set(active_systems)
        self.target_systems = list(target_systems) if target_systems else None
        self.receiver_position = receiver_position
        self.receiver_position_ecef = list(receiver_position_ecef) if receiver_position_ecef else None
        self.station_id = station_id
        self.handler = handler
        self.logger = logger
        self.signals = signals
        self.use_realtime_logic = bool(use_realtime_logic)
        self.live_window_seconds = float(live_window_seconds) if live_window_seconds else None
        configured_interval = float(self.ir_config.processing.live_analysis_interval_seconds)
        self.analysis_interval_seconds = (
            float(analysis_interval_seconds)
            if analysis_interval_seconds and analysis_interval_seconds > 0.0
            else configured_interval
        )
        self.stop_event = threading.Event()
        self.daemon = True

    def stop(self) -> None:
        self.stop_event.set()

    def _emit_log(self, message: str) -> None:
        if self.signals is None:
            return
        try:
            self.signals.log_signal.emit(message)
        except RuntimeError:
            pass

    def _emit_completed(self, payload: object) -> None:
        if self.signals is None:
            return
        try:
            self.signals.completed.emit(payload)
        except RuntimeError:
            pass

    def _emit_failed(self, message: str) -> None:
        if self.signals is None:
            return
        try:
            self.signals.failed.emit(message)
        except RuntimeError:
            pass

    def _emit_cancelled(self) -> None:
        if self.signals is None:
            return
        try:
            self.signals.cancelled.emit()
        except RuntimeError:
            pass

    def _load_ephemeris_provider(self):
        file_path = str(self.eph_settings.get("file_path", "")).strip()
        if not file_path:
            return None
        return FileEphemerisProvider.from_file(
            file_path,
            file_type=str(self.eph_settings.get("file_type", "Auto Detect")),
            broadcast_ephemeris=getattr(self.handler, "broadcast_eph", None),
        )

    @staticmethod
    def _product_key(product) -> tuple[str, str, str]:
        arc_id = str(product.metadata.get("arc_id", ""))
        return (product.product_type.value, product.timestamp.isoformat(), arc_id)

    def _runtime_config(self):
        runtime_config = deepcopy(self.ir_config)
        runtime_config.logging.console = False
        runtime_config.logging.rotating_file = False
        runtime_config.station.station_id = self.station_id
        runtime_config.station.receiver_position = self.receiver_position
        return runtime_config

    def _merge_realtime_history(
        self,
        *,
        result: ProcessingRunResult,
        processor: RealtimeProcessor,
        solutions_by_arc: dict[str, object],
        products_by_key: dict[tuple[str, str, str], object],
        series_by_arc: dict[str, object],
        spectra_by_arc: dict[str, tuple[list[float], list[float]]],
    ) -> None:
        for solution in result.arc_solutions:
            solutions_by_arc[solution.arc_id] = solution
        for product in result.products:
            products_by_key[self._product_key(product)] = product
        series_by_arc.update(processor.get_intermediate_series())
        spectra_by_arc.update(dict(getattr(processor, "_spectra_by_arc", {})))

    def _run_realtime_logic(self, reader, ephemeris_provider) -> None:
        runtime_config = self._runtime_config()
        processor = RealtimeProcessor(runtime_config, logger=self.logger)
        solutions_by_arc: dict[str, object] = {}
        products_by_key: dict[tuple[str, str, str], object] = {}
        series_by_arc: dict[str, object] = {}
        spectra_by_arc: dict[str, tuple[list[float], list[float]]] = {}
        observation_count = 0
        epoch_count = 0
        analysis_count = 0
        pending_records = []
        last_analysis_time = None

        for epoch in reader.iter_epochs(
            ephemeris_provider=ephemeris_provider,
            receiver_position_ecef=self.receiver_position_ecef,
            target_systems=self.target_systems,
        ):
            if self.stop_event.is_set():
                self._emit_log("[Reflectometry] RINEX realtime-loop analysis cancelled.")
                self._emit_cancelled()
                return

            epoch_count += 1
            epoch_records = build_observation_records_from_epoch(
                epoch,
                station_id=self.station_id,
                receiver_position=self.receiver_position,
                active_systems=self.active_systems,
                input_config=self.ir_config.input,
            )
            if epoch_records:
                observation_count += len(epoch_records)
                pending_records.extend(sorted(epoch_records, key=lambda item: item.timestamp))
                reference_time = pending_records[-1].timestamp
                should_analyze = last_analysis_time is None or (
                    reference_time - last_analysis_time
                ).total_seconds() >= self.analysis_interval_seconds
                if should_analyze:
                    result = processor.ingest(
                        pending_records,
                        reference_time=reference_time,
                        window_seconds=self.live_window_seconds,
                        include_open_preview=True,
                    )
                    pending_records.clear()
                    last_analysis_time = reference_time
                    analysis_count += 1
                    self._merge_realtime_history(
                        result=result,
                        processor=processor,
                        solutions_by_arc=solutions_by_arc,
                        products_by_key=products_by_key,
                        series_by_arc=series_by_arc,
                        spectra_by_arc=spectra_by_arc,
                    )

            if epoch_count == 1:
                self._emit_log("[Reflectometry] First RINEX epoch processed with realtime logic.")
            elif epoch_count % 200 == 0:
                self._emit_log(f"[Reflectometry] Realtime-loop progress: {epoch_count} epochs")

        if self.stop_event.is_set():
            self._emit_cancelled()
            return

        if observation_count == 0:
            self._emit_failed("No reflectometry observations were extracted from the selected RINEX file.")
            return

        if pending_records:
            reference_time = pending_records[-1].timestamp
            result = processor.ingest(
                pending_records,
                reference_time=reference_time,
                window_seconds=self.live_window_seconds,
                include_open_preview=True,
            )
            pending_records.clear()
            last_analysis_time = reference_time
            analysis_count += 1
            self._merge_realtime_history(
                result=result,
                processor=processor,
                solutions_by_arc=solutions_by_arc,
                products_by_key=products_by_key,
                series_by_arc=series_by_arc,
                spectra_by_arc=spectra_by_arc,
            )

        final_result = processor.flush()
        self._merge_realtime_history(
            result=final_result,
            processor=processor,
            solutions_by_arc=solutions_by_arc,
            products_by_key=products_by_key,
            series_by_arc=series_by_arc,
            spectra_by_arc=spectra_by_arc,
        )

        ordered_solutions = sorted(solutions_by_arc.values(), key=lambda item: item.timestamp_end)
        ordered_products = sorted(
            products_by_key.values(),
            key=lambda item: (item.timestamp, item.product_type.value, str(item.metadata.get("arc_id", ""))),
        )
        if ordered_solutions:
            window_aggregates = processor.batch_processor.product_converter.aggregate(
                ordered_products,
                window_start=ordered_solutions[0].timestamp_start,
                window_end=ordered_solutions[-1].timestamp_end,
            )
        else:
            window_aggregates = []

        merged_result = ProcessingRunResult(
            station_id=self.station_id,
            arc_solutions=ordered_solutions,
            products=ordered_products,
            window_aggregates=window_aggregates,
            metadata={
                "mode": "file_realtime_loop",
                "observation_count": observation_count,
                "epoch_count": epoch_count,
                "analysis_count": analysis_count,
                "analysis_interval_seconds": self.analysis_interval_seconds,
                "live_window_seconds": self.live_window_seconds,
            },
        )
        processor.final_series_by_arc = dict(series_by_arc)
        processor._series_by_arc = dict(series_by_arc)
        processor.final_spectra_by_arc = dict(spectra_by_arc)
        processor._spectra_by_arc = dict(spectra_by_arc)
        processor.last_result = merged_result
        payload = {
            "processor": processor,
            "result": merged_result,
            "series_by_arc": dict(series_by_arc),
            "observation_count": observation_count,
            "epoch_count": epoch_count,
            "analysis_count": analysis_count,
            "used_realtime_logic": True,
        }
        self._emit_completed(payload)

    def run(self) -> None:
        obs_path = str(self.obs_settings.get("file_path", "")).strip()
        if not obs_path:
            self._emit_failed("RINEX file analysis requires an observation file.")
            return

        try:
            ephemeris_provider = self._load_ephemeris_provider()
            reader = RinexObservationReader(obs_path)
            if self.use_realtime_logic:
                self._run_realtime_logic(reader, ephemeris_provider)
                return

            observations = []
            epoch_count = 0

            for epoch in reader.iter_epochs(
                ephemeris_provider=ephemeris_provider,
                receiver_position_ecef=self.receiver_position_ecef,
                target_systems=self.target_systems,
            ):
                if self.stop_event.is_set():
                    self._emit_log("[Reflectometry] RINEX batch analysis cancelled.")
                    self._emit_cancelled()
                    return

                observations.extend(
                    build_observation_records_from_epoch(
                        epoch,
                        station_id=self.station_id,
                        receiver_position=self.receiver_position,
                        active_systems=self.active_systems,
                        input_config=self.ir_config.input,
                    )
                )
                epoch_count += 1

            if self.stop_event.is_set():
                self._emit_cancelled()
                return

            if not observations:
                self._emit_failed("No reflectometry observations were extracted from the selected RINEX file.")
                return

            runtime_config = self._runtime_config()

            processor = BatchProcessor(
                config=runtime_config,
                provider=ListObservationProvider(observations),
                logger=self.logger,
            )
            result = processor.run()
            payload = {
                "processor": processor,
                "result": result,
                "series_by_arc": processor.get_intermediate_series(),
                "observation_count": len(observations),
                "epoch_count": epoch_count,
            }
            self._emit_completed(payload)
        except Exception as exc:
            self._emit_failed(str(exc))
