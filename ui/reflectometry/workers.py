"""Background workers for reflectometry file analysis."""

from __future__ import annotations

from copy import deepcopy
import logging
import threading

from PySide6.QtCore import QObject, Signal

from core.rinex_loader import FileEphemerisProvider, RinexObservationReader
from core.reflectometry import BatchProcessor, ListObservationProvider
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

    def run(self) -> None:
        obs_path = str(self.obs_settings.get("file_path", "")).strip()
        if not obs_path:
            self._emit_failed("RINEX file analysis requires an observation file.")
            return

        try:
            ephemeris_provider = self._load_ephemeris_provider()
            reader = RinexObservationReader(obs_path)
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

            runtime_config = deepcopy(self.ir_config)
            runtime_config.logging.console = False
            runtime_config.logging.rotating_file = False
            runtime_config.station.station_id = self.station_id
            runtime_config.station.receiver_position = self.receiver_position

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
