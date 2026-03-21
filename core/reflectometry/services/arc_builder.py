"""Arc construction from raw observation records."""

from __future__ import annotations

from collections import defaultdict
import math
from statistics import mean

from core.reflectometry.config import IrConfig, ProcessingConfig, minimum_required_arc_samples
from core.reflectometry.models import ArcDirection
from core.reflectometry.models import ArcStatistics, ObservationRecord, SatelliteArc


class ArcBuilder:
    """Group observations into rising/setting arcs."""

    def __init__(
        self,
        processing_config: ProcessingConfig,
        ir_config: IrConfig,
        sampling_interval_seconds: float,
    ) -> None:
        self.processing_config = processing_config
        self.ir_config = ir_config
        self.sampling_interval_seconds = sampling_interval_seconds

    def build_arcs(self, observations: list[ObservationRecord]) -> list[SatelliteArc]:
        """Build valid arcs from timestamp-sorted observations."""
        grouped: dict[tuple[str, str, str], list[ObservationRecord]] = defaultdict(list)
        for record in observations:
            if record.elevation_deg is None:
                continue
            if not (self.processing_config.min_elevation_deg <= record.elevation_deg <= self.processing_config.max_elevation_deg):
                continue
            grouped[record.satellite_system_key].append(record)

        arcs: list[SatelliteArc] = []
        arc_counter = 0
        for group in grouped.values():
            ordered = sorted(group, key=lambda item: item.timestamp)
            for segment in self._segment_group(ordered):
                direction = _estimate_direction(segment)
                if direction == ArcDirection.RISING and not self.ir_config.use_rising_arcs:
                    continue
                if direction == ArcDirection.SETTING and not self.ir_config.use_setting_arcs:
                    continue
                statistics = self._build_statistics(segment)
                if statistics.sample_count < minimum_required_arc_samples(self.processing_config):
                    continue
                if statistics.duration_seconds < self.processing_config.min_arc_length:
                    continue

                first = segment[0]
                arc_id = self._arc_id(first, segment[-1], direction)
                arc_counter += 1
                arcs.append(
                    SatelliteArc(
                        arc_id=arc_id,
                        station_id=first.station_id,
                        constellation=first.constellation,
                        satellite=first.satellite,
                        signal=first.signal,
                        direction=direction,
                        observations=segment,
                        statistics=statistics,
                        metadata=self._build_metadata(segment, direction, arc_counter),
                    )
                )
        return arcs

    def _segment_group(self, records: list[ObservationRecord]) -> list[list[ObservationRecord]]:
        segments: list[list[ObservationRecord]] = []
        if not records:
            return segments

        current: list[ObservationRecord] = [records[0]]
        direction_sign: int | None = None

        for record in records[1:]:
            previous = current[-1]
            time_gap = (record.timestamp - previous.timestamp).total_seconds()
            diff = (record.elevation_deg or 0.0) - (previous.elevation_deg or 0.0)
            step_sign = 1 if diff > 1e-6 else -1 if diff < -1e-6 else 0

            split_required = time_gap > self.processing_config.max_time_gap_seconds
            if not split_required and direction_sign is not None and step_sign != 0 and step_sign != direction_sign:
                split_required = True

            if split_required:
                if len(current) >= 2:
                    segments.append(current)
                current = [previous, record] if previous.timestamp != record.timestamp else [record]
                direction_sign = step_sign if step_sign != 0 else None
                continue

            current.append(record)
            if step_sign != 0:
                direction_sign = step_sign

        if len(current) >= 2:
            segments.append(current)
        return segments

    def _build_statistics(self, observations: list[ObservationRecord]) -> ArcStatistics:
        duration_seconds = (observations[-1].timestamp - observations[0].timestamp).total_seconds()
        elevations = [item.elevation_deg or 0.0 for item in observations]
        azimuths = [item.azimuth_deg for item in observations if item.azimuth_deg is not None]
        snr_values = [item.snr for item in observations]
        expected_samples = int(round(duration_seconds / max(self.sampling_interval_seconds, 1e-6))) + 1
        gap_ratio = max(0.0, 1.0 - (len(observations) / max(expected_samples, 1)))
        return ArcStatistics(
            sample_count=len(observations),
            duration_seconds=duration_seconds,
            elevation_span_deg=max(elevations) - min(elevations),
            azimuth_span_deg=(max(azimuths) - min(azimuths)) if azimuths else None,
            time_gap_ratio=gap_ratio,
            mean_snr_db_hz=float(mean(snr_values)),
            snr_amplitude_db_hz=max(snr_values) - min(snr_values),
        )

    def _build_metadata(
        self,
        observations: list[ObservationRecord],
        direction: ArcDirection,
        arc_index: int,
    ) -> dict[str, float | int | str | None]:
        elevations = [item.elevation_deg for item in observations if item.elevation_deg is not None]
        azimuths = [item.azimuth_deg for item in observations if item.azimuth_deg is not None]
        duration_seconds = max((observations[-1].timestamp - observations[0].timestamp).total_seconds(), 1e-6)
        mean_azimuth = _circular_mean_deg(azimuths) if azimuths else None
        elevation_rate_deg_per_min = None
        if elevations:
            elevation_rate_deg_per_min = (elevations[-1] - elevations[0]) / duration_seconds * 60.0
        roc = None
        if len(elevations) >= 2:
            elevation_delta = elevations[-1] - elevations[0]
            if abs(elevation_delta) > 1e-6:
                roc = _roc_like(mean(elevations), elevation_delta, duration_seconds)
        return {
            "sequence_index": arc_index,
            "direction": direction.value,
            "min_elevation_deg": min(elevations) if elevations else None,
            "max_elevation_deg": max(elevations) if elevations else None,
            "mean_azimuth_deg": mean_azimuth,
            "elevation_rate_deg_per_min": elevation_rate_deg_per_min,
            "roc_like": roc,
        }

    @staticmethod
    def _arc_id(first: ObservationRecord, last: ObservationRecord, direction: ArcDirection) -> str:
        start_token = first.timestamp.strftime("%Y%m%dT%H%M%S")
        end_token = last.timestamp.strftime("%H%M%S")
        return f"{first.station_id}-{first.satellite}-{first.signal}-{direction.value}-{start_token}-{end_token}"


def _estimate_direction(observations: list[ObservationRecord]) -> ArcDirection:
    diffs = []
    for current, previous in zip(observations[1:], observations[:-1]):
        if current.elevation_deg is None or previous.elevation_deg is None:
            continue
        delta = current.elevation_deg - previous.elevation_deg
        if abs(delta) > 1e-6:
            diffs.append(delta)
    if not diffs:
        return ArcDirection.UNKNOWN
    return ArcDirection.RISING if sum(diffs) > 0 else ArcDirection.SETTING


def _circular_mean_deg(values: list[float]) -> float | None:
    if not values:
        return None
    radians = [math.radians(value) for value in values]
    sin_mean = sum(math.sin(value) for value in radians) / len(radians)
    cos_mean = sum(math.cos(value) for value in radians) / len(radians)
    if abs(sin_mean) < 1e-12 and abs(cos_mean) < 1e-12:
        return None
    return (math.degrees(math.atan2(sin_mean, cos_mean)) + 360.0) % 360.0


def _roc_like(mean_elevation_deg: float, elevation_delta_deg: float, duration_seconds: float) -> float:
    tangent = math.tan(math.radians(mean_elevation_deg))
    slope = (math.pi / 180.0) * elevation_delta_deg / duration_seconds
    if abs(slope) <= 1e-12:
        return 0.0
    return tangent / slope


