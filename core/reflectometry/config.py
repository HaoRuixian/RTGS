"""Reflectometry configuration models, defaults, and YAML loading."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from core.reflectometry.models import ReceiverPosition

DEFAULT_CONFIG_YAML = """\
station:
  station_id: "DEMO"
  receiver_position:
    latitude_deg: 31.2304
    longitude_deg: 121.4737
    height_m: 12.5
  antenna_height: 2.35
  monument_height: 0.80
  environment_type: "coastal"
  reflector_surface_type: "sea"

input:
  constellations: []
  signals: []
  exclude_constellations: []
  exclude_signals: []
  sampling_interval: 30.0

processing:
  min_elevation_deg: 5.0
  max_elevation_deg: 28.0
  live_arc_window_minutes: 20
  live_analysis_interval_seconds: 20
  elevation_rate_mode: "monotonic"
  min_arc_length: 300.0
  max_time_gap_seconds: 90.0
  detrend_method: "polynomial_sin_elevation"
  detrend_order: 2
  smoothing_method: "none"
  smoothing_window: 5
  outlier_method: "mad"
  outlier_threshold: 3.5

ir:
  wavelength_source: "built_in"
  wavelength_overrides_m: {}
  frequency_search_mode: "reflector_height"
  min_reflector_height: 0.5
  max_reflector_height: 8.0
  explicit_frequency_min:
  explicit_frequency_max:
  frequency_grid_size: 2048
  lomb_scargle:
    samples_per_peak: 8
    oversampling_factor: 4.0
    normalize: "power"
    floating_mean: true
  peak_selection:
    max_candidates: 1
    min_prominence: 0.05
    min_width_bins: 1.0
    prefer_high_power: true
  harmonic_check: true

geometry:
  use_external_az_el: true
  compute_az_el_if_missing: false
  reflection_zones:
    - name: "primary_reflector"
      min_elevation_deg: 5.0
      max_elevation_deg: 28.0
      azimuth_windows:
        - [150.0, 330.0]

qc:
  min_peak_to_noise_ratio: 3.0
  min_primary_peak_ratio: 1.25
  min_arc_duration: 300.0
  min_snr_amplitude: 1.0
  max_gap_ratio: 0.2
  reject_cycle_slip_suspects: false
  reject_multipath_outliers: true
  cycle_slip_phase_jump_cycles: 8.0

products:
  enable_reflector_height: true
  enable_sea_level: true
  enable_snow_depth: false
  sea_level_reference: 6.8
  snow_depth_reference_height:

output:
  output_dir: "output/reflectometry"
  file_format: ["csv", "json"]
  save_intermediate: true
  save_arc_level_results: true
  save_spectrum: true
  save_qc_flags: true

logging:
  level: "INFO"
  console: true
  rotating_file: true
  log_dir: "log/reflectometry"
  max_bytes: 2000000
  backup_count: 5
"""


@dataclass(slots=True)
class StationConfig:
    station_id: str
    receiver_position: ReceiverPosition
    antenna_height: float = 0.0
    monument_height: float = 0.0
    environment_type: str = "unknown"
    reflector_surface_type: str = "unknown"

    def __post_init__(self) -> None:
        if not self.station_id:
            raise ValueError("station.station_id is required")


@dataclass(slots=True)
class InputConfig:
    constellations: list[str] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    exclude_constellations: list[str] = field(default_factory=list)
    exclude_signals: list[str] = field(default_factory=list)
    sampling_interval: float = 30.0


@dataclass(slots=True)
class ProcessingConfig:
    min_elevation_deg: float = 5.0
    max_elevation_deg: float = 30.0
    live_arc_window_minutes: int = 20
    live_analysis_interval_seconds: int = 20
    elevation_rate_mode: str = "monotonic"
    min_arc_length: float = 300.0
    max_time_gap_seconds: float = 90.0
    detrend_method: str = "polynomial_sin_elevation"
    detrend_order: int = 2
    smoothing_method: str = "none"
    smoothing_window: int = 5
    outlier_method: str = "mad"
    outlier_threshold: float = 3.5

    def __post_init__(self) -> None:
        if self.min_elevation_deg >= self.max_elevation_deg:
            raise ValueError("processing.min_elevation_deg must be smaller than max_elevation_deg")
        if self.live_arc_window_minutes <= 0:
            raise ValueError("processing.live_arc_window_minutes must be > 0")
        if self.live_analysis_interval_seconds <= 0:
            raise ValueError("processing.live_analysis_interval_seconds must be > 0")


def minimum_required_arc_samples(processing_config: ProcessingConfig) -> int:
    """Return the internal minimum sample count needed for stable preprocessing.

    This stays as an implementation detail instead of a user-facing config knob.
    """
    return max(int(processing_config.detrend_order) + 2, 4)


@dataclass(slots=True)
class ReflectionZoneConfig:
    name: str = "zone_1"
    min_elevation_deg: float = 5.0
    max_elevation_deg: float = 30.0
    azimuth_windows: list[list[float]] = field(default_factory=lambda: [[0.0, 360.0]])

    def __post_init__(self) -> None:
        if self.min_elevation_deg >= self.max_elevation_deg:
            raise ValueError("geometry.reflection_zones[].min_elevation_deg must be smaller than max_elevation_deg")
        if not self.azimuth_windows:
            raise ValueError("geometry.reflection_zones[].azimuth_windows must not be empty")


@dataclass(slots=True)
class LombScargleConfig:
    samples_per_peak: int = 8
    oversampling_factor: float = 4.0
    normalize: str = "power"
    floating_mean: bool = True


@dataclass(slots=True)
class PeakSelectionConfig:
    max_candidates: int = 1
    min_prominence: float = 0.05
    min_width_bins: float = 1.0
    prefer_high_power: bool = True


@dataclass(slots=True)
class IrConfig:
    wavelength_source: str = "built_in"
    wavelength_overrides_m: dict[str, float] = field(default_factory=dict)
    frequency_search_mode: str = "reflector_height"
    min_reflector_height: float = 0.5
    max_reflector_height: float = 20.0
    explicit_frequency_min: float | None = None
    explicit_frequency_max: float | None = None
    frequency_grid_size: int = 2048
    lomb_scargle: LombScargleConfig = field(default_factory=LombScargleConfig)
    peak_selection: PeakSelectionConfig = field(default_factory=PeakSelectionConfig)
    harmonic_check: bool = True
    use_rising_arcs: bool = True
    use_setting_arcs: bool = True

    def __post_init__(self) -> None:
        if self.min_reflector_height <= 0:
            raise ValueError("ir.min_reflector_height must be > 0")
        if self.max_reflector_height <= self.min_reflector_height:
            raise ValueError("ir.max_reflector_height must be greater than min_reflector_height")


@dataclass(slots=True)
class GeometryConfig:
    use_external_az_el: bool = True
    compute_az_el_if_missing: bool = False
    reflection_zones: list[ReflectionZoneConfig] = field(default_factory=list)


@dataclass(slots=True)
class QcConfig:
    min_peak_to_noise_ratio: float = 3.0
    min_primary_peak_ratio: float = 1.25
    min_arc_duration: float = 300.0
    min_snr_amplitude: float = 1.0
    max_gap_ratio: float = 0.2
    reject_cycle_slip_suspects: bool = False
    reject_multipath_outliers: bool = True
    cycle_slip_phase_jump_cycles: float = 8.0


@dataclass(slots=True)
class ProductsConfig:
    enable_reflector_height: bool = True
    enable_sea_level: bool = False
    enable_snow_depth: bool = False
    sea_level_reference: float | None = None
    snow_depth_reference_height: float | None = None


@dataclass(slots=True)
class OutputConfig:
    output_dir: str = "output/reflectometry"
    file_format: list[str] = field(default_factory=lambda: ["csv", "json"])
    save_intermediate: bool = False
    save_arc_level_results: bool = True
    save_spectrum: bool = False
    save_qc_flags: bool = True

    def __post_init__(self) -> None:
        supported = {"csv", "json"}
        invalid = set(self.file_format) - supported
        if invalid:
            raise ValueError(f"output.file_format contains unsupported values: {sorted(invalid)}")


@dataclass(slots=True)
class LoggingConfig:
    level: str = "INFO"
    console: bool = True
    rotating_file: bool = True
    log_dir: str = "log/reflectometry"
    max_bytes: int = 2_000_000
    backup_count: int = 5


@dataclass(slots=True)
class ReflectorConfig:
    station: StationConfig
    input: InputConfig
    processing: ProcessingConfig
    ir: IrConfig
    geometry: GeometryConfig
    qc: QcConfig
    products: ProductsConfig
    output: OutputConfig
    logging: LoggingConfig


def _read_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("Configuration root must be a mapping")
    return data


def _build_receiver_position(data: dict[str, Any]) -> ReceiverPosition:
    return ReceiverPosition(
        latitude_deg=data.get("latitude_deg"),
        longitude_deg=data.get("longitude_deg"),
        height_m=data.get("height_m"),
        x_m=data.get("x_m"),
        y_m=data.get("y_m"),
        z_m=data.get("z_m"),
    )


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _parse_angle_windows(value: Any) -> list[list[float]]:
    windows: list[list[float]] = []
    for item in _as_list(value):
        if isinstance(item, dict):
            start = item.get("start_deg")
            end = item.get("end_deg")
            if start is None or end is None:
                continue
            windows.append([float(start), float(end)])
            continue
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            windows.append([float(item[0]), float(item[1])])
    return windows


def _legacy_reflection_zones(
    geometry_raw: dict[str, Any],
    processing_raw: dict[str, Any],
) -> list[ReflectionZoneConfig]:
    min_elevation_deg = float(processing_raw.get("min_elevation_deg", 5.0))
    max_elevation_deg = float(processing_raw.get("max_elevation_deg", 30.0))
    azimuth_windows = _parse_angle_windows(geometry_raw.get("reflector_azimuth_sector"))
    if not azimuth_windows:
        azimuth_windows = _parse_angle_windows(geometry_raw.get("azimuth_mask"))
    if not azimuth_windows:
        azimuth_windows = [[0.0, 360.0]]
    return [
        ReflectionZoneConfig(
            name="zone_1",
            min_elevation_deg=min_elevation_deg,
            max_elevation_deg=max_elevation_deg,
            azimuth_windows=azimuth_windows,
        )
    ]


def _load_reflection_zones(
    geometry_raw: dict[str, Any],
    processing_raw: dict[str, Any],
) -> list[ReflectionZoneConfig]:
    zones_raw = _as_list(geometry_raw.get("reflection_zones", []))
    zones: list[ReflectionZoneConfig] = []
    for index, zone_raw in enumerate(zones_raw, start=1):
        if not isinstance(zone_raw, dict):
            continue
        min_elevation_deg = float(zone_raw.get("min_elevation_deg", processing_raw.get("min_elevation_deg", 5.0)))
        max_elevation_deg = float(zone_raw.get("max_elevation_deg", processing_raw.get("max_elevation_deg", 30.0)))
        azimuth_windows = _parse_angle_windows(zone_raw.get("azimuth_windows"))
        if not azimuth_windows:
            azimuth_windows = _parse_angle_windows(zone_raw.get("azimuth_ranges"))
        if not azimuth_windows:
            azimuth_windows = [[0.0, 360.0]]
        zones.append(
            ReflectionZoneConfig(
                name=str(zone_raw.get("name") or f"zone_{index}"),
                min_elevation_deg=min_elevation_deg,
                max_elevation_deg=max_elevation_deg,
                azimuth_windows=azimuth_windows,
            )
        )
    return zones or _legacy_reflection_zones(geometry_raw, processing_raw)


def load_config(path: str | Path) -> ReflectorConfig:
    raw = _read_yaml(path)
    station_raw = raw.get("station", {})
    input_raw = raw.get("input", {})
    processing_raw = raw.get("processing", {})
    ir_raw = raw.get("ir", {})
    geometry_raw = raw.get("geometry", {})
    qc_raw = raw.get("qc", {})
    products_raw = raw.get("products", {})
    output_raw = raw.get("output", {})
    logging_raw = raw.get("logging", {})
    reflection_zones = _load_reflection_zones(geometry_raw, processing_raw)
    effective_min_elevation = min(zone.min_elevation_deg for zone in reflection_zones)
    effective_max_elevation = max(zone.max_elevation_deg for zone in reflection_zones)

    return ReflectorConfig(
        station=StationConfig(
            station_id=station_raw.get("station_id", ""),
            receiver_position=_build_receiver_position(station_raw.get("receiver_position", {})),
            antenna_height=float(station_raw.get("antenna_height", 0.0) or 0.0),
            monument_height=float(station_raw.get("monument_height", 0.0) or 0.0),
            environment_type=station_raw.get("environment_type", "unknown"),
            reflector_surface_type=station_raw.get("reflector_surface_type", "unknown"),
        ),
        input=InputConfig(
            constellations=[str(item) for item in _as_list(input_raw.get("constellations", []))],
            signals=[str(item) for item in _as_list(input_raw.get("signals", []))],
            exclude_constellations=[str(item) for item in _as_list(input_raw.get("exclude_constellations", []))],
            exclude_signals=[str(item) for item in _as_list(input_raw.get("exclude_signals", []))],
            sampling_interval=float(input_raw.get("sampling_interval", 30.0) or 30.0),
        ),
        processing=ProcessingConfig(
            min_elevation_deg=effective_min_elevation,
            max_elevation_deg=effective_max_elevation,
            live_arc_window_minutes=int(processing_raw.get("live_arc_window_minutes", 20)),
            live_analysis_interval_seconds=int(processing_raw.get("live_analysis_interval_seconds", 20)),
            elevation_rate_mode=processing_raw.get("elevation_rate_mode", "monotonic"),
            min_arc_length=float(processing_raw.get("min_arc_length", 300.0)),
            max_time_gap_seconds=float(processing_raw.get("max_time_gap_seconds", 90.0)),
            detrend_method=processing_raw.get("detrend_method", "polynomial_sin_elevation"),
            detrend_order=int(processing_raw.get("detrend_order", 2)),
            smoothing_method=processing_raw.get("smoothing_method", "none"),
            smoothing_window=int(processing_raw.get("smoothing_window", 5)),
            outlier_method=processing_raw.get("outlier_method", "mad"),
            outlier_threshold=float(processing_raw.get("outlier_threshold", 3.5)),
        ),
        ir=IrConfig(
            wavelength_source=ir_raw.get("wavelength_source", "built_in"),
            wavelength_overrides_m=ir_raw.get("wavelength_overrides_m", {}) or {},
            frequency_search_mode=ir_raw.get("frequency_search_mode", "reflector_height"),
            min_reflector_height=float(ir_raw.get("min_reflector_height", 0.5)),
            max_reflector_height=float(ir_raw.get("max_reflector_height", 20.0)),
            explicit_frequency_min=ir_raw.get("explicit_frequency_min"),
            explicit_frequency_max=ir_raw.get("explicit_frequency_max"),
            frequency_grid_size=int(ir_raw.get("frequency_grid_size", 2048)),
            lomb_scargle=LombScargleConfig(**((ir_raw.get("lomb_scargle") or {}) | {})),
            peak_selection=PeakSelectionConfig(**((ir_raw.get("peak_selection") or {}) | {})),
            harmonic_check=bool(ir_raw.get("harmonic_check", True)),
            use_rising_arcs=bool(ir_raw.get("use_rising_arcs", True)),
            use_setting_arcs=bool(ir_raw.get("use_setting_arcs", True)),
        ),
        geometry=GeometryConfig(
            use_external_az_el=bool(geometry_raw.get("use_external_az_el", True)),
            compute_az_el_if_missing=bool(geometry_raw.get("compute_az_el_if_missing", False)),
            reflection_zones=reflection_zones,
        ),
        qc=QcConfig(
            min_peak_to_noise_ratio=float(qc_raw.get("min_peak_to_noise_ratio", 3.0)),
            min_primary_peak_ratio=float(qc_raw.get("min_primary_peak_ratio", 1.25)),
            min_arc_duration=float(qc_raw.get("min_arc_duration", 300.0)),
            min_snr_amplitude=float(qc_raw.get("min_snr_amplitude", 1.0)),
            max_gap_ratio=float(qc_raw.get("max_gap_ratio", 0.2)),
            reject_cycle_slip_suspects=bool(qc_raw.get("reject_cycle_slip_suspects", False)),
            reject_multipath_outliers=bool(qc_raw.get("reject_multipath_outliers", True)),
            cycle_slip_phase_jump_cycles=float(qc_raw.get("cycle_slip_phase_jump_cycles", 8.0)),
        ),
        products=ProductsConfig(
            enable_reflector_height=bool(products_raw.get("enable_reflector_height", True)),
            enable_sea_level=bool(products_raw.get("enable_sea_level", False)),
            enable_snow_depth=bool(products_raw.get("enable_snow_depth", False)),
            sea_level_reference=products_raw.get("sea_level_reference"),
            snow_depth_reference_height=products_raw.get("snow_depth_reference_height"),
        ),
        output=OutputConfig(
            output_dir=output_raw.get("output_dir", "output/reflectometry"),
            file_format=[str(item) for item in _as_list(output_raw.get("file_format", ["csv", "json"]))],
            save_intermediate=bool(output_raw.get("save_intermediate", False)),
            save_arc_level_results=bool(output_raw.get("save_arc_level_results", True)),
            save_spectrum=bool(output_raw.get("save_spectrum", False)),
            save_qc_flags=bool(output_raw.get("save_qc_flags", True)),
        ),
        logging=LoggingConfig(
            level=logging_raw.get("level", "INFO"),
            console=bool(logging_raw.get("console", True)),
            rotating_file=bool(logging_raw.get("rotating_file", True)),
            log_dir=logging_raw.get("log_dir", "log/reflectometry"),
            max_bytes=int(logging_raw.get("max_bytes", 2_000_000)),
            backup_count=int(logging_raw.get("backup_count", 5)),
        ),
    )


def dump_example_config(path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(DEFAULT_CONFIG_YAML, encoding="utf-8")
    return target


def config_to_dict(config: ReflectorConfig) -> dict[str, Any]:
    return asdict(config)


__all__ = [
    "DEFAULT_CONFIG_YAML",
    "GeometryConfig",
    "InputConfig",
    "IrConfig",
    "LombScargleConfig",
    "LoggingConfig",
    "minimum_required_arc_samples",
    "OutputConfig",
    "PeakSelectionConfig",
    "ProcessingConfig",
    "ProductsConfig",
    "QcConfig",
    "ReflectionZoneConfig",
    "ReflectorConfig",
    "StationConfig",
    "config_to_dict",
    "dump_example_config",
    "load_config",
]
