"""Isolated worker process for one batch-console station."""

from __future__ import annotations

import multiprocessing as mp
import queue
import time
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any

from core.global_config import get_global_config
from core.ring_buffer import RingBuffer
from core.rtcm_handler import RTCMHandler
from core.stream_settings import (
    is_file_stream_configured,
    is_realtime_stream_configured,
    stream_source,
)
from ui.monitoring.workers import DataProcessingThread, IOThread, RinexReplayThread
from ui.positioning.workers import PositioningSignals, PositioningThread


class _CallbackSignal:
    """Small signal-compatible adapter used without a QApplication in a child."""

    def __init__(self) -> None:
        self._callbacks: list[Any] = []

    def connect(self, callback: Any) -> None:
        self._callbacks.append(callback)

    def emit(self, *args: Any) -> None:
        for callback in tuple(self._callbacks):
            try:
                callback(*args)
            except Exception:
                # A status update must never stop the acquisition thread.
                continue


class _ChildStreamSignals:
    def __init__(self) -> None:
        self.log_signal = _CallbackSignal()
        self.epoch_signal = _CallbackSignal()
        self.status_signal = _CallbackSignal()
        self.receiver_metadata_signal = _CallbackSignal()


def _send(out_queue: Any, event: dict[str, Any]) -> None:
    event.setdefault("time", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    with suppress(queue.Full, OSError, EOFError):
        out_queue.put_nowait(event)


def _metadata_value(metadata: Any, *names: str) -> str:
    if isinstance(metadata, dict):
        for name in names:
            value = metadata.get(name)
            if value:
                return str(value)
    for name in names:
        value = getattr(metadata, name, "")
        if value:
            return str(value)
    return ""


def _station_process_main(
    station_id: str,
    mode: str,
    config_payload: dict[str, Any],
    out_queue: Any,
    stop_event: Any,
) -> None:
    """Run one complete station pipeline in a separate process."""
    config = get_global_config()
    config.from_dict(config_payload)
    signals = _ChildStreamSignals()
    handler = RTCMHandler(compute_geometry=True)
    buffers: list[RingBuffer] = []
    io_threads: list[Any] = []
    processing_threads: list[Any] = []
    positioning_thread: PositioningThread | None = None
    positioning_buffer: RingBuffer | None = None

    counts = {"messages": 0, "epochs": 0, "satellites": 0}

    def status(name: str, active: bool) -> None:
        if name == "OBS":
            _send(out_queue, {"kind": "stream", "value": "Connected" if active else "Disconnected"})
        elif name in {"EPH", "SSR", "BASE"} and active:
            _send(out_queue, {"kind": "log", "value": f"{name} stream connected"})

    def log(message: str) -> None:
        text = str(message)
        # Connection failures are expected during NTRIP reconnects.  Only
        # configuration/processing failures should turn the station red.
        if "Config Error" in text or "Processing Error" in text or "Traceback" in text:
            _send(out_queue, {"kind": "error", "value": text})

    def epoch(epoch: Any) -> None:
        counts["epochs"] += 1
        counts["satellites"] = len(getattr(epoch, "satellites", {}) or {})
        if positioning_buffer is not None:
            positioning_buffer.put(epoch, block=False)

    def metadata(value: Any) -> None:
        position = value.get("position_ecef") if isinstance(value, dict) else getattr(value, "position_ecef", None)
        position_text = ""
        if position is not None:
            try:
                position_text = "ECEF " + ", ".join(f"{float(item):.1f}" for item in position[:3])
            except (TypeError, ValueError):
                position_text = ""
        _send(
            out_queue,
            {
                "kind": "metadata",
                "receiver": _metadata_value(value, "receiver_type", "receiver", "receiver_type_descriptor"),
                "antenna": _metadata_value(value, "antenna_descriptor", "antenna", "antenna_type"),
                "position": position_text,
            },
        )

    signals.status_signal.connect(status)
    signals.log_signal.connect(log)
    signals.epoch_signal.connect(epoch)
    signals.receiver_metadata_signal.connect(metadata)

    def add_stream(name: str, settings: dict[str, Any]) -> None:
        source = stream_source(settings)
        if not settings.get("enabled", True):
            return
        if not (is_realtime_stream_configured(settings) or is_file_stream_configured(settings)):
            return
        if source in {"RINEX File", "File"} and name != "OBS":
            return
        buffer = RingBuffer(maxsize=1500)
        buffers.append(buffer)
        if source in {"RINEX File", "File"}:
            replay = RinexReplayThread(
                name,
                settings,
                signals,
                handler=handler,
                eph_settings=config.eph_settings.__dict__,
                target_systems=list(config.target_systems),
            )
            replay.start()
            io_threads.append(replay)
            return
        io_thread = IOThread(name, settings, buffer, signals)
        processing = DataProcessingThread(name, buffer, handler, signals)
        io_thread.start()
        processing.start()
        io_threads.append(io_thread)
        processing_threads.append(processing)

    obs_settings = dict(config.obs_settings.__dict__)
    add_stream("OBS", obs_settings)
    add_stream("EPH", dict(config.eph_settings.__dict__))
    add_stream("SSR", dict(config.ssr_settings.__dict__))
    add_stream("BASE", dict(config.base_settings.__dict__))

    if mode == "Positioning":
        positioning_buffer = RingBuffer(maxsize=500)
        buffers.append(positioning_buffer)
        position_signals = PositioningSignals()

        def solution(value: Any) -> None:
            position = getattr(value, "position", None)
            if position is None:
                lat = getattr(value, "latitude", None)
                lon = getattr(value, "longitude", None)
                height = getattr(value, "height", None)
            else:
                lat = getattr(value, "latitude", None)
                lon = getattr(value, "longitude", None)
                height = getattr(value, "height", None)
            if lat is not None and lon is not None and height is not None:
                _send(
                    out_queue,
                    {"kind": "position", "value": f"{float(lat):.5f}, {float(lon):.5f}, {float(height):.1f} m"},
                )

        position_signals.solution_signal.connect(solution)
        position_signals.log_signal.connect(log)
        positioning_thread = PositioningThread(
            f"{station_id}-positioning", position_signals, positioning_buffer, handler
        )
        positioning_thread.start()

    _send(out_queue, {"kind": "started", "mode": mode})
    try:
        last_report = 0.0
        while not stop_event.wait(0.25):
            now = time.monotonic()
            if now - last_report >= 1.0:
                counts["messages"] = sum(getattr(thread, "msg_count", 0) for thread in processing_threads)
                _send(out_queue, {"kind": "metrics", **counts})
                last_report = now
            if io_threads and not any(thread.is_alive() for thread in io_threads + processing_threads):
                _send(out_queue, {"kind": "error", "value": "All station streams stopped"})
                break
    finally:
        for thread in io_threads + processing_threads:
            with suppress(Exception):
                thread.stop()
        if positioning_thread is not None:
            with suppress(Exception):
                positioning_thread.stop()
        for buffer in buffers:
            buffer.close()
        for thread in io_threads + processing_threads + ([positioning_thread] if positioning_thread else []):
            if thread is not None:
                with suppress(Exception):
                    thread.join(timeout=2.0)
        _send(out_queue, {"kind": "stopped"})


class StationProcess:
    """Parent-side process handle used by ``BatchConsole``."""

    def __init__(self, station_id: str, mode: str, payload: dict[str, Any]) -> None:
        self.context = mp.get_context("spawn")
        self.events = self.context.Queue(maxsize=2000)
        self.stop_event = self.context.Event()
        self.process = self.context.Process(
            target=_station_process_main,
            args=(station_id, mode, payload, self.events, self.stop_event),
            name=f"rtgs-station-{station_id}",
        )

    def start(self) -> None:
        self.process.start()

    def stop(self) -> None:
        self.stop_event.set()

    def poll(self) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        while True:
            try:
                values.append(self.events.get_nowait())
            except queue.Empty:
                break
        return values

    def is_alive(self) -> bool:
        return self.process.is_alive()

    def join(self, timeout: float = 2.0) -> None:
        self.process.join(timeout)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout)
