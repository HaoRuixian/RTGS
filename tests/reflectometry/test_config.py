"""Configuration tests."""

from pathlib import Path

from core.config_paths import default_ir_config_path
from core.reflectometry.config import load_config


def test_example_config_loads():
    config = load_config(default_ir_config_path())

    assert config.station.station_id
    assert "csv" in config.output.file_format
    assert len(config.geometry.reflection_zones) == 1
    assert config.geometry.reflection_zones[0].azimuth_windows == [[150.0, 330.0]]
    assert config.processing.smoothing_method == "none"
    assert config.processing.detrend_order == 2
    assert config.ir.peak_selection.max_candidates == 1
    assert config.qc.min_primary_peak_ratio == 1.25
    assert config.processing.live_arc_window_minutes == 20
    assert config.processing.live_analysis_interval_seconds == 60
    assert config.ir.estimation_mode == "spectrum"
    assert config.ir.ekf.output_interval_seconds == 300
    assert config.ir.ekf.output_window_seconds == 60
    assert config.ir.ekf.rh_init_min_samples == 80
    assert config.products.enable_dynamic_sea_level_correction is True
    assert config.products.dynamic_sea_level_window_hours == 4.0
    assert config.products.dynamic_sea_level_igg3_k0 == 0.5
    assert config.products.dynamic_sea_level_igg3_k1 == 2.0
    assert config.products.dynamic_sea_level_normalize_design is True


def test_legacy_geometry_fields_are_migrated_to_reflection_zones(tmp_path):
    config_path = Path(tmp_path) / "legacy_geometry.yaml"
    config_path.write_text(
        """
station:
  station_id: LEGACY
  receiver_position:
    latitude_deg: 31.0
    longitude_deg: 121.0
    height_m: 10.0
input:
  constellations: []
processing:
  min_elevation_deg: 6.0
  max_elevation_deg: 18.0
geometry:
  azimuth_mask:
    - [140.0, 210.0]
products:
  enable_reflector_height: true
output:
  output_dir: output/test
  file_format: [csv]
logging:
  level: INFO
  console: false
  rotating_file: false
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert len(config.geometry.reflection_zones) == 1
    zone = config.geometry.reflection_zones[0]
    assert zone.min_elevation_deg == 6.0
    assert zone.max_elevation_deg == 18.0
    assert zone.azimuth_windows == [[140.0, 210.0]]
