"""Core reflectometry enums and dataclass models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from .signal_utils import normalize_signal_id


class SnrUnit(str, Enum):
    DB_HZ = "db_hz"
    LINEAR = "linear"


class ArcDirection(str, Enum):
    RISING = "rising"
    SETTING = "setting"
    UNKNOWN = "unknown"


class ProductType(str, Enum):
    REFLECTOR_HEIGHT = "reflector_height"
    SEA_LEVEL = "sea_level"
    SEA_LEVEL_DYNAMIC_CORRECTED = "sea_level_dynamic_corrected"
    SEA_LEVEL_RATE = "sea_level_rate"
    SEA_LEVEL_ACCELERATION = "sea_level_acceleration"
    SNOW_DEPTH = "snow_depth"


@dataclass(slots=True)
class ReceiverPosition:
    latitude_deg: float | None = None
    longitude_deg: float | None = None
    height_m: float | None = None
    x_m: float | None = None
    y_m: float | None = None
    z_m: float | None = None

    def as_dict(self) -> dict[str, float | None]:
        return {
            "latitude_deg": self.latitude_deg,
            "longitude_deg": self.longitude_deg,
            "height_m": self.height_m,
            "x_m": self.x_m,
            "y_m": self.y_m,
            "z_m": self.z_m,
        }


@dataclass(slots=True)
class StationMetadata:
    station_id: str
    receiver_position: ReceiverPosition
    antenna_height_m: float = 0.0
    monument_height_m: float = 0.0
    environment_type: str = "unknown"
    reflector_surface_type: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ObservationRecord:
    station_id: str
    timestamp: datetime
    constellation: str
    satellite: str
    signal: str
    snr: float
    snr_unit: SnrUnit = SnrUnit.DB_HZ
    azimuth_deg: float | None = None
    elevation_deg: float | None = None
    pseudorange_m: float | None = None
    carrier_phase_cycles: float | None = None
    multipath_indicator: float | None = None
    receiver_position: ReceiverPosition | None = None
    environment_metadata: dict[str, Any] = field(default_factory=dict)
    observation_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def satellite_system_key(self) -> tuple[str, str, str]:
        return (self.constellation, self.satellite, normalize_signal_id(self.signal))


@dataclass(slots=True)
class ObservationRequest:
    start_time: datetime | None = None
    end_time: datetime | None = None
    constellations: tuple[str, ...] = ()
    signals: tuple[str, ...] = ()
    exclude_constellations: tuple[str, ...] = ()
    exclude_signals: tuple[str, ...] = ()
    sampling_interval_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ArcStatistics:
    sample_count: int
    duration_seconds: float
    elevation_span_deg: float
    azimuth_span_deg: float | None
    time_gap_ratio: float
    mean_snr_db_hz: float
    snr_amplitude_db_hz: float


@dataclass(slots=True)
class SatelliteArc:
    arc_id: str
    station_id: str
    constellation: str
    satellite: str
    signal: str
    direction: ArcDirection
    observations: list[ObservationRecord]
    statistics: ArcStatistics
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def timestamp_start(self) -> datetime:
        return self.observations[0].timestamp

    @property
    def timestamp_end(self) -> datetime:
        return self.observations[-1].timestamp


@dataclass(slots=True)
class SnrSeries:
    arc_id: str
    timestamps: list[datetime]
    elevation_deg: list[float]
    sin_elevation: list[float]
    azimuth_deg: list[float]
    snr_db_hz: list[float]
    snr_linear: list[float]
    residual: list[float]
    wavelength_m: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PeakCandidate:
    rank: int
    peak_index: int
    spectral_frequency: float
    reflector_height_m: float
    power: float
    prominence: float
    width: float
    peak_to_noise_ratio: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class QualityMetrics:
    sample_count: int
    duration_seconds: float
    gap_ratio: float
    snr_amplitude_db_hz: float
    residual_rms: float
    peak_power: float | None = None
    peak_to_noise_ratio: float | None = None
    confidence: float = 0.0
    qc_flags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ArcSolution:
    station_id: str
    arc_id: str
    timestamp_start: datetime
    timestamp_end: datetime
    constellation: str
    satellite: str
    signal: str
    arc_direction: ArcDirection
    reflector_height_m: float | None
    peak_frequency: float | None
    peak_power: float | None
    peak_to_noise_ratio: float | None
    qc_flags: list[str]
    success: bool
    fail_reason: str | None = None
    wavelength_m: float | None = None
    candidates: list[PeakCandidate] = field(default_factory=list)
    quality_metrics: QualityMetrics | None = None
    spectrum_frequency: list[float] = field(default_factory=list)
    spectrum_power: list[float] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProductResult:
    product_type: ProductType
    timestamp: datetime
    value: float
    unit: str
    source_arc_count: int
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReflectorHeightResult(ProductResult):
    def __init__(
        self,
        timestamp: datetime,
        value: float,
        source_arc_count: int,
        confidence: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        ProductResult.__init__(
            self,
            product_type=ProductType.REFLECTOR_HEIGHT,
            timestamp=timestamp,
            value=value,
            unit="m",
            source_arc_count=source_arc_count,
            confidence=confidence,
            metadata=metadata or {},
        )


@dataclass(slots=True)
class SeaLevelResult(ProductResult):
    def __init__(
        self,
        timestamp: datetime,
        value: float,
        source_arc_count: int,
        confidence: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        ProductResult.__init__(
            self,
            product_type=ProductType.SEA_LEVEL,
            timestamp=timestamp,
            value=value,
            unit="m",
            source_arc_count=source_arc_count,
            confidence=confidence,
            metadata=metadata or {},
        )


@dataclass(slots=True)
class SnowDepthResult(ProductResult):
    def __init__(
        self,
        timestamp: datetime,
        value: float,
        source_arc_count: int,
        confidence: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        ProductResult.__init__(
            self,
            product_type=ProductType.SNOW_DEPTH,
            timestamp=timestamp,
            value=value,
            unit="m",
            source_arc_count=source_arc_count,
            confidence=confidence,
            metadata=metadata or {},
        )


@dataclass(slots=True)
class WindowAggregateResult:
    window_start: datetime
    window_end: datetime
    products: list[ProductResult]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class DailySummaryResult:
    summary_date: str
    products: list[ProductResult]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProcessingRunResult:
    station_id: str
    arc_solutions: list[ArcSolution]
    products: list[ProductResult]
    window_aggregates: list[WindowAggregateResult]
    daily_summaries: list[DailySummaryResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "ArcDirection",
    "ArcSolution",
    "ArcStatistics",
    "DailySummaryResult",
    "ObservationRecord",
    "ObservationRequest",
    "PeakCandidate",
    "ProcessingRunResult",
    "ProductResult",
    "ProductType",
    "QualityMetrics",
    "ReceiverPosition",
    "ReflectorHeightResult",
    "SatelliteArc",
    "SeaLevelResult",
    "SnrSeries",
    "SnrUnit",
    "SnowDepthResult",
    "StationMetadata",
    "WindowAggregateResult",
]
