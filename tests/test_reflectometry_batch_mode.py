from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

from core.config_paths import default_ir_config_path
from core.data_models import EpochObservation, SatelliteState, SignalData
from core.global_config import GlobalConfig
from core.reflectometry.config import InputConfig, load_config
from core.reflectometry.models import ObservationRecord, ProcessingRunResult, ReceiverPosition
from core.reflectometry.rinex_batch import (
    build_observation_records_from_epoch,
    signal_enabled_for_reflectometry,
)


def _signal(signal_id: str, *, snr: float, pseudorange: float, phase: float, doppler: float) -> SignalData:
    return SignalData(
        signal_id=signal_id,
        snr=snr,
        phase=phase,
        pseudorange=pseudorange,
        lock_time=0,
        half_cycle=0,
        doppler=doppler,
    )


def test_build_observation_records_from_epoch_uses_override_timestamp_and_filters_inputs():
    fallback_timestamp = datetime(2025, 7, 5, 0, 0, 0, tzinfo=timezone.utc)
    receiver_position = ReceiverPosition(
        latitude_deg=43.1,
        longitude_deg=7.2,
        height_m=12.5,
        x_m=3875000.0,
        y_m=332500.0,
        z_m=5029000.0,
    )
    epoch = EpochObservation(
        gps_time=0.0,
        satellites={
            "G01": SatelliteState(
                sys_id="G",
                prn=1,
                azimuth=123.4,
                elevation=18.5,
                signals={
                    "1C": _signal("1C", snr=45.0, pseudorange=21474836.0, phase=123456.5, doppler=-1234.0),
                    "5Q": _signal("5Q", snr=48.0, pseudorange=21474840.0, phase=223456.5, doppler=-1134.0),
                },
            ),
            "E11": SatelliteState(
                sys_id="E",
                prn=11,
                azimuth=222.0,
                elevation=25.0,
                signals={"1C": _signal("1C", snr=40.0, pseudorange=23456789.0, phase=654321.0, doppler=123.0)},
            ),
        },
    )

    records = build_observation_records_from_epoch(
        epoch,
        station_id="TEST",
        timestamp=fallback_timestamp,
        receiver_position=receiver_position,
        active_systems={"G"},
        input_config=InputConfig(constellations=["G"], signals=["1C"], exclude_signals=["5Q"]),
    )

    assert len(records) == 1
    record = records[0]
    assert record.station_id == "TEST"
    assert record.timestamp == fallback_timestamp
    assert record.constellation == "G"
    assert record.satellite == "G01"
    assert record.signal == "1C"
    assert record.snr == 45.0
    assert record.azimuth_deg == 123.4
    assert record.elevation_deg == 18.5
    assert record.pseudorange_m == 21474836.0
    assert record.carrier_phase_cycles == 123456.5
    assert record.receiver_position == receiver_position


def test_signal_enabled_for_reflectometry_respects_include_and_exclude_rules():
    config = InputConfig(
        constellations=["G", "E"],
        signals=["1C", "5Q"],
        exclude_constellations=["E"],
        exclude_signals=["5Q"],
    )

    assert signal_enabled_for_reflectometry("G", "1C", active_systems={"G", "E"}, input_config=config) is True
    assert signal_enabled_for_reflectometry("E", "1C", active_systems={"G", "E"}, input_config=config) is False
    assert signal_enabled_for_reflectometry("G", "5Q", active_systems={"G", "E"}, input_config=config) is False
    assert signal_enabled_for_reflectometry("R", "1C", active_systems={"G", "E"}, input_config=config) is False


def test_global_config_round_trip_preserves_final_results_only_flag():
    config = GlobalConfig()
    config.obs_settings.source_type = "RINEX File"
    config.obs_settings.file_path = "tests/sample.obs"
    config.obs_settings.replay_speed = 15.0
    config.obs_settings.final_results_only = True
    config.eph_settings.source_type = "File"
    config.eph_settings.file_path = "tests/sample.nav"

    payload = config.to_dict()

    assert payload["obs_settings"]["final_results_only"] is True

    restored = GlobalConfig()
    restored.from_dict(payload)

    assert restored.obs_settings.source_type == "RINEX File"
    assert restored.obs_settings.file_path == "tests/sample.obs"
    assert restored.obs_settings.replay_speed == 15.0
    assert restored.obs_settings.final_results_only is True
    assert restored.eph_settings.source_type == "File"
    assert restored.eph_settings.file_path == "tests/sample.nav"


def test_rinex_fast_loop_realtime_logic_respects_analysis_interval(tmp_path, monkeypatch):
    example_config = load_config(default_ir_config_path())
    example_config.output.output_dir = str(tmp_path / "output")
    example_config.logging.console = False
    example_config.logging.rotating_file = False
    start = datetime(2026, 1, 1, 0, 0, 0)
    receiver = example_config.station.receiver_position
    timestamps = [start + timedelta(seconds=offset) for offset in (0, 5, 10, 15, 20)]
    epoch_iter = iter(timestamps)
    completed_payloads: list[object] = []

    qtcore_module = ModuleType("PySide6.QtCore")

    class QObject:
        pass

    class Signal:
        def __init__(self, *_args, **_kwargs):
            pass

        def emit(self, *_args, **_kwargs):
            pass

    qtcore_module.QObject = QObject
    qtcore_module.Signal = Signal
    pyside6_module = ModuleType("PySide6")
    pyside6_module.QtCore = qtcore_module
    monkeypatch.setitem(sys.modules, "PySide6", pyside6_module)
    monkeypatch.setitem(sys.modules, "PySide6.QtCore", qtcore_module)

    workers_path = Path(__file__).resolve().parents[1] / "ui" / "reflectometry" / "workers.py"
    module_name = "tests_reflectometry_workers_interval"
    spec = importlib.util.spec_from_file_location(module_name, workers_path)
    assert spec is not None and spec.loader is not None
    workers_module = importlib.util.module_from_spec(spec)
    sys.modules.pop(module_name, None)
    spec.loader.exec_module(workers_module)
    RinexBatchAnalysisThread = workers_module.RinexBatchAnalysisThread

    class FakeReader:
        def iter_epochs(self, **_kwargs):
            for _ in timestamps:
                yield object()

    class SpyRealtimeProcessor:
        def __init__(self, config, logger=None):
            self.config = config
            self.logger = logger
            self.ingest_calls: list[tuple[datetime, int, bool, float | None]] = []
            self.batch_processor = SimpleNamespace(
                product_converter=SimpleNamespace(aggregate=lambda products, window_start, window_end: [])
            )
            self.final_series_by_arc = {}
            self.final_spectra_by_arc = {}
            self._series_by_arc = {}
            self._spectra_by_arc = {}
            self.last_result = ProcessingRunResult(
                station_id=config.station.station_id,
                arc_solutions=[],
                products=[],
                window_aggregates=[],
            )

        def ingest(self, observations, *, reference_time=None, window_seconds=None, include_open_preview=True):
            self.ingest_calls.append(
                (reference_time, len(observations), include_open_preview, window_seconds)
            )
            return ProcessingRunResult(
                station_id=self.config.station.station_id,
                arc_solutions=[],
                products=[],
                window_aggregates=[],
            )

        def flush(self):
            return ProcessingRunResult(
                station_id=self.config.station.station_id,
                arc_solutions=[],
                products=[],
                window_aggregates=[],
            )

        def get_intermediate_series(self):
            return {}

    def fake_build_observation_records_from_epoch(
        epoch,
        *,
        station_id,
        receiver_position,
        active_systems,
        input_config,
    ):
        timestamp = next(epoch_iter)
        return [
            ObservationRecord(
                station_id=station_id,
                timestamp=timestamp,
                constellation="G",
                satellite="G01",
                signal="1C",
                snr=45.0,
                azimuth_deg=120.0,
                elevation_deg=15.0,
                receiver_position=receiver_position,
            )
        ]

    processor_holder: dict[str, SpyRealtimeProcessor] = {}

    def build_processor(config, logger=None):
        processor = SpyRealtimeProcessor(config, logger=logger)
        processor_holder["processor"] = processor
        return processor

    monkeypatch.setattr(workers_module, "RealtimeProcessor", build_processor)
    monkeypatch.setattr(workers_module, "build_observation_records_from_epoch", fake_build_observation_records_from_epoch)

    worker = RinexBatchAnalysisThread(
        obs_settings={"file_path": "dummy.obs"},
        eph_settings={},
        ir_config=example_config,
        active_systems={"G"},
        target_systems=["G"],
        receiver_position=receiver,
        receiver_position_ecef=None,
        station_id=example_config.station.station_id,
        use_realtime_logic=True,
        live_window_seconds=600.0,
        analysis_interval_seconds=10.0,
    )
    worker._emit_completed = completed_payloads.append

    worker._run_realtime_logic(FakeReader(), None)

    processor = processor_holder["processor"]
    assert [call[0] for call in processor.ingest_calls] == [
        start,
        start + timedelta(seconds=10),
        start + timedelta(seconds=20),
    ]
    assert [call[1] for call in processor.ingest_calls] == [1, 2, 2]
    assert all(call[2] is True for call in processor.ingest_calls)
    assert all(call[3] == 600.0 for call in processor.ingest_calls)
    assert completed_payloads
    payload = completed_payloads[0]
    assert payload["analysis_count"] == 3
    assert payload["result"].metadata["analysis_interval_seconds"] == 10.0
