from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _load_monitoring_workers_module(monkeypatch):
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

    pyrtcm_module = ModuleType("pyrtcm")

    class RTCMReader:
        pass

    pyrtcm_module.RTCMReader = RTCMReader
    pyrtcm_module.rtcmtables = SimpleNamespace(
        GLONASS_SIG_MAP={},
        QZSS_SIG_MAP={},
        IRNSS_SIG_MAP={},
        PRNSIGMAP={},
    )
    monkeypatch.setitem(sys.modules, "pyrtcm", pyrtcm_module)

    serial_client_module = ModuleType("core.serial_client")

    class SerialClient:
        pass

    serial_client_module.SerialClient = SerialClient
    monkeypatch.setitem(sys.modules, "core.serial_client", serial_client_module)

    global_config_module = ModuleType("core.global_config")
    global_config_module.get_global_config = lambda: SimpleNamespace(
        approx_rec_pos=[0.0, 0.0, 0.0],
        obs_settings=SimpleNamespace(mountpoint="TEST"),
    )
    monkeypatch.setitem(sys.modules, "core.global_config", global_config_module)

    rinex_loader_module = ModuleType("core.rinex_loader")

    class FileEphemerisProvider:
        pass

    class RinexObservationReader:
        pass

    rinex_loader_module.FileEphemerisProvider = FileEphemerisProvider
    rinex_loader_module.RinexObservationReader = RinexObservationReader
    rinex_loader_module.read_rinex_observation_header = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "core.rinex_loader", rinex_loader_module)

    mixed_reader_module = ModuleType("core.mixed_gnss_reader")

    class MixedGNSSReader:
        pass

    mixed_reader_module.MixedGNSSReader = MixedGNSSReader
    monkeypatch.setitem(sys.modules, "core.mixed_gnss_reader", mixed_reader_module)

    workers_path = Path(__file__).resolve().parents[1] / "ui" / "monitoring" / "workers.py"
    module_name = "tests_monitoring_workers_live_rinex"
    spec = importlib.util.spec_from_file_location(module_name, workers_path)
    assert spec is not None and spec.loader is not None

    workers_module = importlib.util.module_from_spec(spec)
    sys.modules.pop(module_name, None)
    spec.loader.exec_module(workers_module)
    return workers_module


def _build_logging_thread(logging_thread_cls, *, latest_epoch_time=None, handler=None):
    signals = SimpleNamespace(
        log_signal=SimpleNamespace(emit=lambda *_args, **_kwargs: None),
        status_signal=SimpleNamespace(emit=lambda *_args, **_kwargs: None),
        epoch_signal=SimpleNamespace(emit=lambda *_args, **_kwargs: None),
    )

    latest_epoch = (
        SimpleNamespace(utc_datetime=latest_epoch_time, satellites={})
        if latest_epoch_time is not None
        else None
    )

    return logging_thread_cls(
        settings={},
        ring_buffers={},
        merged_satellites={},
        signals=signals,
        get_latest_epoch=(lambda: latest_epoch),
        handler=handler,
    )


def test_logging_thread_aligns_5s_epochs_in_gps_time(monkeypatch):
    workers_module = _load_monitoring_workers_module(monkeypatch)
    logging_thread = _build_logging_thread(workers_module.LoggingThread)

    aligned = logging_thread._align_epoch_time(
        datetime(2026, 3, 26, 0, 0, 12, tzinfo=timezone.utc),
        5,
    )

    assert aligned == datetime(2026, 3, 26, 0, 0, 30)


def test_logging_thread_initial_rinex_file_time_uses_same_alignment(monkeypatch):
    workers_module = _load_monitoring_workers_module(monkeypatch)
    logging_thread = _build_logging_thread(
        workers_module.LoggingThread,
        latest_epoch_time=datetime(2026, 3, 26, 0, 0, 12, tzinfo=timezone.utc),
    )

    file_time = logging_thread._get_initial_rinex_file_time(5)
    not_aligned = logging_thread._align_epoch_time(
        datetime(2026, 3, 26, 0, 0, 10, tzinfo=timezone.utc),
        5,
    )

    assert file_time == datetime(2026, 3, 26, 0, 0, 30)
    assert not_aligned is None


def test_logging_thread_maps_ephemeris_formats_to_file_extensions(monkeypatch):
    workers_module = _load_monitoring_workers_module(monkeypatch)

    assert workers_module.LoggingThread._file_extension_for_format("csv") == "csv"
    assert workers_module.LoggingThread._file_extension_for_format("binary") == "rtcm"
    assert workers_module.LoggingThread._file_extension_for_format("rinex") == "rnx"
    assert workers_module.LoggingThread._file_extension_for_format("rinex_nav") == "rnx"
    assert workers_module.LoggingThread._file_extension_for_format("sp3") == "sp3"


def test_logging_thread_uses_rtcm_1006_1033_metadata_for_rinex(monkeypatch):
    workers_module = _load_monitoring_workers_module(monkeypatch)
    handler = SimpleNamespace(
        last_station_coords=[1.0, 2.0, 3.0],
        last_receiver_type_descriptor="SEPT MOSAIC-X5",
        last_receiver_serial_number="4014259",
        last_receiver_firmware_version="4.14.4",
        last_antenna_descriptor="LEIAR25.R4 NONE",
        last_antenna_serial_number="725235",
    )
    logging_thread = _build_logging_thread(
        workers_module.LoggingThread,
        handler=handler,
    )

    metadata = logging_thread._rinex_station_metadata()
    assert metadata == {
        "receiver_type": "SEPT MOSAIC-X5",
        "receiver_serial": "4014259",
        "receiver_version": "4.14.4",
        "antenna_type": "LEIAR25.R4 NONE",
        "antenna_number": "725235",
    }

    class _Writer:
        receiver_type = "Generic"
        receiver_serial = "00"
        receiver_version = ""
        antenna_type = "UNKNOWN"
        antenna_number = ""

        @staticmethod
        def _format_a20(value):
            return str(value or "").strip().ljust(20)

        def set_approx_position(self, value):
            self.approx_position = value

    writer = _Writer()
    logging_thread._update_rinex_writer_position(writer)
    assert writer.approx_position == [1.0, 2.0, 3.0]
    assert writer.receiver_type == "SEPT MOSAIC-X5"
    assert writer.receiver_serial.strip() == "4014259"
    assert writer.receiver_version.strip() == "4.14.4"
    assert writer.antenna_type.strip() == "LEIAR25.R4 NONE"
    assert writer.antenna_number.strip() == "725235"
