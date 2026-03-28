"""Helpers for reflectometry realtime-arc tracking and Arc Status presentation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from core.reflectometry.models import ArcSolution, ObservationRecord, SnrSeries


@dataclass(slots=True)
class TrackingArcContext:
    """UI-facing state for one currently tracked realtime arc."""

    arc_id: str
    satellite: str
    signal: str
    direction: str
    time_summary: str
    elevation_summary: str
    mean_az: str
    status: str
    reason: str
    buffer: list[ObservationRecord]
    series: SnrSeries
    ready_for_preview: bool


@dataclass(slots=True)
class ArcStatusRow:
    """One Arc Status table row."""

    arc_id: str
    tooltip: str
    values: list[str]
    status_color: str | None = None


@dataclass(slots=True)
class ArcSelectorOption:
    """One Arc Series selector option."""

    arc_id: str
    label: str


def collect_latest_tracking_buffers(
    records: list[ObservationRecord],
    *,
    max_time_gap_seconds: float,
) -> list[list[ObservationRecord]]:
    """Return the latest monotonic segment for each satellite/signal key."""
    grouped: dict[tuple[str, str, str], list[ObservationRecord]] = defaultdict(list)
    for record in records:
        grouped[record.satellite_system_key].append(record)

    if not grouped:
        return []

    reference_time = max(record.timestamp for record in records)
    latest_segments: list[list[ObservationRecord]] = []
    for grouped_records in grouped.values():
        ordered = sorted(grouped_records, key=lambda item: item.timestamp)
        segment = latest_tracking_segment(ordered, max_time_gap_seconds=max_time_gap_seconds)
        if segment and (reference_time - segment[-1].timestamp).total_seconds() <= max_time_gap_seconds:
            if len(segment) >= 2:
                latest_segments.append(segment)
    return latest_segments


def latest_tracking_segment(
    records: list[ObservationRecord],
    *,
    max_time_gap_seconds: float,
) -> list[ObservationRecord]:
    """Return the most recent continuous monotonic arc segment from sorted records."""
    if len(records) <= 2:
        return records

    current: list[ObservationRecord] = [records[0]]
    direction_sign: int | None = None
    segments: list[list[ObservationRecord]] = []

    for record in records[1:]:
        previous = current[-1]
        time_gap = (record.timestamp - previous.timestamp).total_seconds()
        previous_el = previous.elevation_deg
        current_el = record.elevation_deg
        diff = (current_el or 0.0) - (previous_el or 0.0)
        step_sign = 1 if diff > 1e-6 else -1 if diff < -1e-6 else 0

        split_required = time_gap > max_time_gap_seconds
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
    return segments[-1] if segments else records[-2:]


def buffer_direction_text(buffer: list[ObservationRecord]) -> str:
    """Return the instantaneous arc direction for a tracking buffer."""
    if len(buffer) < 2:
        return "--"
    previous = buffer[-2].elevation_deg
    current = buffer[-1].elevation_deg
    if previous is None or current is None:
        return "--"
    if current > previous:
        return "rising"
    if current < previous:
        return "setting"
    return "--"


def tracking_arc_id(buffer: list[ObservationRecord]) -> str:
    """Return the stable realtime-arc identifier used in the UI."""
    first = buffer[0]
    direction = buffer_direction_text(buffer)
    return f"{first.station_id}-{first.satellite}-{first.signal}-{direction}"


def format_arc_time_summary(start: datetime, end: datetime) -> str:
    """Format arc midpoint plus start/end times."""
    midpoint = start + (end - start) / 2
    return f"{midpoint.strftime('%H:%M:%S')} ({start.strftime('%H:%M:%S')}-{end.strftime('%H:%M:%S')})"


def format_tracking_elevation_summary(buffer: list[ObservationRecord]) -> str:
    """Format mean plus start/end elevation for a tracking arc."""
    elevations = [item.elevation_deg for item in buffer if item.elevation_deg is not None]
    if not elevations:
        return "--"
    mean_elevation = float(sum(elevations) / len(elevations))
    return f"{mean_elevation:.2f} ({elevations[0]:.2f}->{elevations[-1]:.2f})"


def build_tracking_series(arc_id: str, buffer: list[ObservationRecord]) -> SnrSeries:
    """Build the lightweight tracking-stage SNR series used in Arc Series."""
    timestamps = [item.timestamp for item in buffer]
    elevation_deg = np.asarray([float(item.elevation_deg or 0.0) for item in buffer], dtype=float)
    azimuth_deg = np.asarray([float(item.azimuth_deg or 0.0) for item in buffer], dtype=float)
    snr_db = np.asarray([float(item.snr) for item in buffer], dtype=float)
    snr_linear = np.power(10.0, snr_db / 10.0)
    sin_elevation = np.sin(np.deg2rad(elevation_deg))
    return SnrSeries(
        arc_id=arc_id,
        timestamps=timestamps,
        elevation_deg=elevation_deg.tolist(),
        sin_elevation=sin_elevation.tolist(),
        azimuth_deg=azimuth_deg.tolist(),
        snr_db_hz=snr_db.tolist(),
        snr_linear=snr_linear.tolist(),
        residual=[],
        wavelength_m=0.0,
        metadata={"tracking": True, "detrend_preview": False},
    )


def build_tracking_context(
    buffer: list[ObservationRecord],
    *,
    required_duration: float,
    ready_for_preview: bool,
) -> TrackingArcContext:
    """Create the UI context for one tracking or solving arc."""
    start = buffer[0].timestamp
    end = buffer[-1].timestamp
    duration = max(0.0, (end - start).total_seconds())
    sample_count = len(buffer)
    arc_id = tracking_arc_id(buffer)
    direction = buffer_direction_text(buffer)
    mean_az = format_mean_azimuth([item.azimuth_deg for item in buffer if item.azimuth_deg is not None])
    first = buffer[0]
    return TrackingArcContext(
        arc_id=arc_id,
        satellite=first.satellite,
        signal=first.signal,
        direction=direction,
        time_summary=format_arc_time_summary(start, end),
        elevation_summary=format_tracking_elevation_summary(buffer),
        mean_az=mean_az,
        status="solving" if ready_for_preview else "tracking",
        reason=(
            "Arc window ready; solving..."
            if ready_for_preview
            else f"{sample_count} samples, {duration:.0f}/{required_duration:.0f}s"
        ),
        buffer=buffer,
        series=build_tracking_series(arc_id, buffer),
        ready_for_preview=ready_for_preview,
    )


def match_live_arc_id_for_solution(
    solution: ArcSolution,
    contexts: dict[str, TrackingArcContext],
) -> str | None:
    """Match a solved realtime arc back onto the active tracking key shown in the UI."""
    for arc_id, context in contexts.items():
        if context.satellite != solution.satellite:
            continue
        if context.signal != solution.signal:
            continue
        if context.direction != solution.arc_direction.value:
            continue
        start = context.buffer[0].timestamp
        end = context.buffer[-1].timestamp
        if solution.timestamp_end < start or solution.timestamp_start > end:
            continue
        return arc_id
    return None


def build_solution_status_row(
    solution: ArcSolution,
    *,
    browse_key: str,
    display_arc_id: str,
    time_summary: str,
    elevation_text: str,
    mean_az_text: str,
) -> ArcStatusRow:
    """Build one solved-arc table row."""
    status_text = "OK" if solution.success else "FAIL"
    qc_text = ", ".join(solution.qc_flags) if solution.qc_flags else (solution.fail_reason or "")
    return ArcStatusRow(
        arc_id=browse_key,
        tooltip=solution.arc_id,
        values=[
            display_arc_id,
            solution.satellite,
            solution.signal,
            solution.arc_direction.value,
            time_summary,
            elevation_text,
            mean_az_text,
            f"{solution.reflector_height_m:.3f}" if solution.reflector_height_m is not None else "--",
            f"{solution.peak_to_noise_ratio:.2f}" if solution.peak_to_noise_ratio is not None else "--",
            status_text,
            qc_text,
        ],
        status_color="#2A692D" if solution.success else "#B42318",
    )


def build_tracking_status_row(context: TrackingArcContext, *, display_arc_id: str) -> ArcStatusRow:
    """Build one tracking/solving table row."""
    return ArcStatusRow(
        arc_id=context.arc_id,
        tooltip=context.arc_id,
        values=[
            display_arc_id,
            context.satellite,
            context.signal,
            context.direction,
            context.time_summary,
            context.elevation_summary,
            context.mean_az,
            "--",
            "--",
            context.status,
            context.reason,
        ],
        status_color="#B7791F",
    )


def build_solution_selector_option(
    solution: ArcSolution,
    *,
    browse_key: str,
    elevation_text: str,
    mean_az_text: str,
    time_summary: str,
) -> ArcSelectorOption:
    """Build one selector label for a solved arc."""
    status = "OK" if solution.success else "FAIL"
    return ArcSelectorOption(
        arc_id=browse_key,
        label=(
            f"{solution.satellite} {solution.signal} | "
            f"{solution.arc_direction.value} | "
            f"El {elevation_text} | "
            f"Az {mean_az_text} | "
            f"{time_summary} | "
            f"{status}"
        ),
    )


def build_tracking_selector_option(context: TrackingArcContext) -> ArcSelectorOption:
    """Build one selector label for a tracking/solving arc."""
    return ArcSelectorOption(
        arc_id=context.arc_id,
        label=(
            f"{context.satellite} {context.signal} | "
            f"{context.direction} | "
            f"El {context.elevation_summary} | "
            f"Az {context.mean_az} | "
            f"{context.time_summary} | "
            f"{context.status}"
        ),
    )


def format_mean_azimuth(values: list[float | None]) -> str:
    """Format circular-mean azimuth text."""
    numeric_values = [float(value) for value in values if value is not None]
    mean_azimuth = _circular_mean_deg(numeric_values)
    return f"{mean_azimuth:.2f}" if mean_azimuth is not None else "--"


def _circular_mean_deg(values: list[float]) -> float | None:
    if not values:
        return None
    radians = np.radians(np.asarray(values, dtype=float) % 360.0)
    sin_mean = float(np.mean(np.sin(radians)))
    cos_mean = float(np.mean(np.cos(radians)))
    if abs(sin_mean) < 1e-12 and abs(cos_mean) < 1e-12:
        return None
    return (float(np.degrees(np.arctan2(sin_mean, cos_mean))) + 360.0) % 360.0


__all__ = [
    "ArcSelectorOption",
    "ArcStatusRow",
    "TrackingArcContext",
    "build_solution_selector_option",
    "build_solution_status_row",
    "build_tracking_context",
    "build_tracking_selector_option",
    "build_tracking_status_row",
    "buffer_direction_text",
    "collect_latest_tracking_buffers",
    "format_arc_time_summary",
    "format_tracking_elevation_summary",
    "match_live_arc_id_for_solution",
    "tracking_arc_id",
]
