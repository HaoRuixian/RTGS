"""Focused tests for the independent batch station model and lifecycle."""

from __future__ import annotations

import time

from ui.batch.station import StationRecord, default_station_config
from ui.batch.worker import StationProcess


def test_station_configs_are_independent() -> None:
    first = StationRecord("A")
    second = StationRecord("B")
    first.config["obs_settings"]["mountpoint"] = "A01"
    assert second.config["obs_settings"].get("mountpoint", "") != "A01"


def test_station_process_can_start_and_stop_without_stream() -> None:
    process = StationProcess("test", "Monitoring", default_station_config())
    process.start()
    events = []
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        events.extend(process.poll())
        if any(event.get("kind") == "started" for event in events):
            break
        time.sleep(0.05)
    assert any(event.get("kind") == "started" for event in events)
    process.stop()
    process.join(5.0)
    assert not process.is_alive()


def test_positioning_station_process_can_start_and_stop_without_stream() -> None:
    process = StationProcess("test-positioning", "Positioning", default_station_config())
    process.start()
    events = []
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        events.extend(process.poll())
        if any(event.get("kind") == "started" for event in events):
            break
        time.sleep(0.05)
    assert any(event.get("kind") == "started" for event in events)
    process.stop()
    process.join(5.0)
    assert not process.is_alive()
