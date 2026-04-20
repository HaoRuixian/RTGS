"""Tests for reflectometry Arc Status helper utilities."""

from __future__ import annotations

from datetime import datetime, timedelta

from core.reflectometry.models import ObservationRecord, ReceiverPosition
from ui.reflectometry.arc_status import build_tracking_context, collect_latest_tracking_buffers, tracking_arc_id


def _record(
    timestamp: datetime,
    *,
    elevation_deg: float,
    satellite: str = "G12",
    signal: str = "1C",
) -> ObservationRecord:
    return ObservationRecord(
        station_id="TEST",
        timestamp=timestamp,
        constellation="G",
        satellite=satellite,
        signal=signal,
        snr=45.0,
        azimuth_deg=120.0,
        elevation_deg=elevation_deg,
        receiver_position=ReceiverPosition(latitude_deg=30.0, longitude_deg=114.0, height_m=20.0),
    )


def test_collect_latest_tracking_buffers_returns_latest_monotonic_segment():
    start = datetime(2026, 1, 1, 0, 0, 0)
    records = [
        _record(start + timedelta(seconds=0), elevation_deg=8.0),
        _record(start + timedelta(seconds=30), elevation_deg=9.0),
        _record(start + timedelta(seconds=60), elevation_deg=10.0),
        _record(start + timedelta(seconds=90), elevation_deg=9.5),
        _record(start + timedelta(seconds=120), elevation_deg=9.0),
    ]

    segments = collect_latest_tracking_buffers(records, max_time_gap_seconds=90.0)

    assert len(segments) == 1
    assert [item.elevation_deg for item in segments[0]] == [10.0, 9.5, 9.0]


def test_build_tracking_context_uses_stable_arc_id_and_solving_status():
    start = datetime(2026, 1, 1, 0, 0, 0)
    buffer = [
        _record(start + timedelta(seconds=0), elevation_deg=8.0),
        _record(start + timedelta(seconds=30), elevation_deg=9.0),
        _record(start + timedelta(seconds=60), elevation_deg=10.0),
    ]

    context = build_tracking_context(
        buffer,
        required_duration=60.0,
        ready_for_preview=True,
    )

    assert context.arc_id == tracking_arc_id(buffer)
    assert context.arc_id == "TEST-G12-1C-rising"
    assert tracking_arc_id(buffer[1:]) == context.arc_id
    assert context.status == "solving"
    assert context.reason == "Arc window ready; solving..."
    assert context.series.metadata["tracking"] is True

