"""Realtime reflectometry processor tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from core.reflectometry.models import ObservationRecord, ReceiverPosition
from core.reflectometry.services.realtime import RealtimeProcessor
from tests.reflectometry.helpers import generate_synthetic_observations


def test_realtime_processor_emits_windowed_results(example_config):
    example_config.input.constellations = ["G"]
    example_config.input.signals = ["1C"]
    observations = generate_synthetic_observations(
        station_id=example_config.station.station_id,
        receiver_position=example_config.station.receiver_position,
        constellations=("G",),
        signals=("1C",),
        arc_count=3,
        samples_per_arc=55,
        reflector_height_m=4.25,
        noise_std_db=0.2,
        amplitude_db=2.7,
        sampling_interval_seconds=example_config.input.sampling_interval,
    )
    processor = RealtimeProcessor(example_config)

    chunk_size = 30
    result = None
    for index in range(0, len(observations), chunk_size):
        chunk = observations[index : index + chunk_size]
        result = processor.ingest(
            chunk,
            reference_time=chunk[-1].timestamp,
            window_seconds=3600.0,
            include_open_preview=True,
        )

    assert result is not None
    assert result.arc_solutions
    assert any(item.success for item in result.arc_solutions)
    assert len({item.arc_id for item in result.arc_solutions}) == len(result.arc_solutions)


def test_realtime_processor_discards_open_arc_samples_outside_window(example_config):
    example_config.qc.min_arc_duration = 1.0
    processor = RealtimeProcessor(example_config)
    receiver = ReceiverPosition(latitude_deg=30.0, longitude_deg=114.0, height_m=20.0)
    start = datetime(2026, 1, 1, 0, 0, 0)
    observations = [
        ObservationRecord(
            station_id=example_config.station.station_id,
            timestamp=start + timedelta(seconds=index * 60),
            constellation="G",
            satellite="G12",
            signal="1C",
            snr=45.0 + index,
            azimuth_deg=180.0,
            elevation_deg=8.0 + index,
            receiver_position=receiver,
        )
        for index in range(4)
    ]

    processor.ingest(
        observations,
        reference_time=observations[-1].timestamp,
        window_seconds=120.0,
        include_open_preview=True,
    )

    key = observations[-1].satellite_system_key
    assert key in processor.buffers
    kept_timestamps = [item.timestamp for item in processor.buffers[key]]
    assert kept_timestamps == [observations[1].timestamp, observations[2].timestamp, observations[3].timestamp]


def test_realtime_preview_waits_for_realtime_window(example_config):
    example_config.qc.min_arc_duration = 60.0
    processor = RealtimeProcessor(example_config)
    receiver = ReceiverPosition(latitude_deg=30.0, longitude_deg=114.0, height_m=20.0)
    start = datetime(2026, 1, 1, 0, 0, 0)
    buffer = [
        ObservationRecord(
            station_id=example_config.station.station_id,
            timestamp=start + timedelta(seconds=index * 60),
            constellation="G",
            satellite="G12",
            signal="1C",
            snr=45.0 + index,
            azimuth_deg=120.0,
            elevation_deg=8.0 + index,
            receiver_position=receiver,
        )
        for index in range(4)
    ]

    assert processor._buffer_is_ready_for_preview(buffer, window_seconds=120.0)
    assert not processor._buffer_is_ready_for_preview(buffer, window_seconds=300.0)
