"""Test helpers for synthetic reflectometry observations."""

from __future__ import annotations

from datetime import datetime, timedelta
import math

import numpy as np

from core.geo_utils import get_freq
from core.reflectometry.models import ObservationRecord, ReceiverPosition


def generate_synthetic_observations(
    *,
    station_id: str,
    receiver_position: ReceiverPosition | None,
    constellations: tuple[str, ...] = ("G",),
    signals: tuple[str, ...] = ("1C",),
    arc_count: int = 4,
    samples_per_arc: int = 60,
    reflector_height_m: float = 4.0,
    noise_std_db: float = 0.25,
    amplitude_db: float = 2.6,
    trend_bias_db: float = 44.0,
    sampling_interval_seconds: float = 30.0,
    start_time: datetime | None = None,
    seed: int = 42,
) -> list[ObservationRecord]:
    """Generate deterministic GNSS-IR-like observations for tests."""

    if not constellations:
        return []

    start = start_time or datetime(2026, 3, 19, 0, 0, 0)
    rng = np.random.default_rng(seed)
    records: list[ObservationRecord] = []
    gap_seconds = max(float(sampling_interval_seconds) * 2.0, 180.0)
    arc_duration_seconds = max(float(samples_per_arc - 1), 1.0) * float(sampling_interval_seconds)

    for arc_index in range(arc_count):
        constellation = constellations[arc_index % len(constellations)]
        signal = signals[arc_index % len(signals)]
        _frequency_hz, wavelength = get_freq(signal, f"{constellation}00")
        if wavelength <= 0.0:
            continue

        direction = 1.0 if arc_index % 2 == 0 else -1.0
        arc_start = start + timedelta(seconds=arc_index * (arc_duration_seconds + gap_seconds))
        satellite = f"{constellation}{(arc_index % 16) + 1:02d}"

        elevations = np.linspace(6.0, 26.0, samples_per_arc)
        if direction < 0:
            elevations = elevations[::-1]
        azimuth_start = 150.0 + 20.0 * (arc_index % 6)
        azimuths = azimuth_start + np.linspace(0.0, 12.0, samples_per_arc)
        sin_elevation = np.sin(np.deg2rad(elevations))
        spectral_phase = 2.0 * np.pi * rng.uniform(0.0, 1.0)
        oscillation = amplitude_db * np.cos((4.0 * np.pi * reflector_height_m / wavelength) * sin_elevation + spectral_phase)
        trend = trend_bias_db + 3.0 * sin_elevation - 1.5 * np.square(sin_elevation)
        snr = trend + oscillation + rng.normal(0.0, noise_std_db, samples_per_arc)

        for sample_index in range(samples_per_arc):
            timestamp = arc_start + timedelta(seconds=sample_index * float(sampling_interval_seconds))
            phase = 100_000.0 + sample_index * 0.25 + math.sin(sample_index / 5.0)
            records.append(
                ObservationRecord(
                    station_id=station_id,
                    timestamp=timestamp,
                    constellation=constellation,
                    satellite=satellite,
                    signal=signal,
                    snr=float(snr[sample_index]),
                    azimuth_deg=float(azimuths[sample_index] % 360.0),
                    elevation_deg=float(elevations[sample_index]),
                    pseudorange_m=23_000_000.0 + 50.0 * sample_index,
                    carrier_phase_cycles=float(phase),
                    multipath_indicator=float(abs(oscillation[sample_index]) / max(amplitude_db, 1e-6)),
                    receiver_position=receiver_position,
                )
            )

    return sorted(records, key=lambda item: item.timestamp)
