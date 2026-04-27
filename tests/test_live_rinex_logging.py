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


def _build_logging_thread(logging_thread_cls, *, latest_epoch_time=None):
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
