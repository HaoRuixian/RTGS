"""Geometry validation and normalization."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

from ..config import GeometryConfig, ProcessingConfig, ReflectionZoneConfig
from ..models import ObservationRecord


GeometryCallback = Callable[[ObservationRecord], tuple[float, float]]


class GeometryResolver:
    """Resolve and filter azimuth/elevation values."""

    def __init__(
        self,
        config: GeometryConfig,
        processing_config: ProcessingConfig | None = None,
        geometry_callback: GeometryCallback | None = None,
    ) -> None:
        self.config = config
        self.processing_config = processing_config
        self.geometry_callback = geometry_callback

    def filter_and_resolve(self, observations: list[ObservationRecord]) -> list[ObservationRecord]:
        """Resolve missing geometry and keep only observations that fall inside any configured reflection zone."""
        resolved: list[ObservationRecord] = []
        for record in observations:
            candidate = record
            if (candidate.azimuth_deg is None or candidate.elevation_deg is None) and self.config.compute_az_el_if_missing:
                if self.geometry_callback is None:
                    continue
                azimuth_deg, elevation_deg = self.geometry_callback(candidate)
                candidate = replace(candidate, azimuth_deg=azimuth_deg, elevation_deg=elevation_deg)

            if candidate.azimuth_deg is None or candidate.elevation_deg is None:
                continue

            if not matches_reflection_zones(
                azimuth_deg=float(candidate.azimuth_deg),
                elevation_deg=float(candidate.elevation_deg),
                geometry_config=self.config,
                processing_config=self.processing_config,
            ):
                continue
            resolved.append(candidate)
        return resolved


def effective_reflection_zones(
    geometry_config: GeometryConfig,
    processing_config: ProcessingConfig | None = None,
) -> list[ReflectionZoneConfig]:
    """Return explicit reflection zones, or synthesize one fallback zone from processing limits."""
    if geometry_config.reflection_zones:
        return list(geometry_config.reflection_zones)
    if processing_config is None:
        return []
    return [
        ReflectionZoneConfig(
            name="zone_1",
            min_elevation_deg=processing_config.min_elevation_deg,
            max_elevation_deg=processing_config.max_elevation_deg,
            azimuth_windows=[[0.0, 360.0]],
        )
    ]


def matches_reflection_zones(
    azimuth_deg: float | None,
    elevation_deg: float | None,
    geometry_config: GeometryConfig,
    processing_config: ProcessingConfig | None = None,
) -> bool:
    """Return True when an observation falls inside any configured reflection zone."""
    if azimuth_deg is None or elevation_deg is None:
        return False
    zones = effective_reflection_zones(geometry_config, processing_config)
    if not zones:
        return True
    for zone in zones:
        if not (zone.min_elevation_deg <= elevation_deg <= zone.max_elevation_deg):
            continue
        if _angle_in_windows(azimuth_deg, zone.azimuth_windows):
            return True
    return False


def _angle_in_windows(angle_deg: float, windows: list[list[float]]) -> bool:
    normalized = angle_deg % 360.0
    for start_deg, end_deg in windows:
        if abs(end_deg - start_deg) >= 360.0:
            return True
        start = start_deg % 360.0
        end = end_deg % 360.0
        if start <= end and start <= normalized <= end:
            return True
        if start > end and (normalized >= start or normalized <= end):
            return True
    return False


