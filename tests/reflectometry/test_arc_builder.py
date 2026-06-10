"""Arc builder tests."""

from datetime import datetime, timedelta
import math

from core.reflectometry.models import ObservationRecord
from core.reflectometry.config import ReflectionZoneConfig
from core.reflectometry.services.arc_builder import ArcBuilder
from core.reflectometry.services.geometry import GeometryResolver, matches_reflection_zones
from tests.reflectometry.helpers import generate_synthetic_observations


def test_arc_builder_creates_rising_and_setting_arcs(example_config):
    example_config.input.constellations = ["G"]
    example_config.input.signals = ["1C"]
    observations = generate_synthetic_observations(
        station_id=example_config.station.station_id,
        receiver_position=example_config.station.receiver_position,
        constellations=("G",),
        signals=("1C",),
        arc_count=4,
        samples_per_arc=50,
        reflector_height_m=4.0,
        noise_std_db=0.2,
        sampling_interval_seconds=example_config.input.sampling_interval,
    )
    observations = GeometryResolver(example_config.geometry).filter_and_resolve(observations)
    arcs = ArcBuilder(
        example_config.processing,
        example_config.ir,
        example_config.input.sampling_interval,
    ).build_arcs(observations)

    assert len(arcs) == 4
    directions = {arc.direction.value for arc in arcs}
    assert directions == {"rising", "setting"}
    assert all(arc.statistics.sample_count >= 40 for arc in arcs)


def test_arc_builder_records_midpoint_dynamic_geometry(example_config):
    start = datetime(2026, 3, 19, 0, 0, 0)
    observations = [
        ObservationRecord(
            station_id=example_config.station.station_id,
            timestamp=start + timedelta(seconds=index * 30),
            constellation="G",
            satellite="G01",
            signal="1C",
            snr=45.0 + 0.1 * index,
            azimuth_deg=180.0,
            elevation_deg=6.0 + index,
        )
        for index in range(11)
    ]

    arcs = ArcBuilder(
        example_config.processing,
        example_config.ir,
        example_config.input.sampling_interval,
    ).build_arcs(observations)

    assert len(arcs) == 1
    metadata = arcs[0].metadata
    expected_rate = math.radians(1.0 / 30.0)
    expected_roc = math.tan(math.radians(11.0)) / expected_rate
    assert metadata["midpoint_elevation_deg"] == 11.0
    assert abs(metadata["elevation_rate_rad_per_s"] - expected_rate) < 1e-12
    assert abs(metadata["roc_like"] - expected_roc) < 1e-9


def test_multiple_reflection_zones_are_treated_as_union(example_config):
    example_config.geometry.reflection_zones = [
        ReflectionZoneConfig(
            name="west_face",
            min_elevation_deg=5.0,
            max_elevation_deg=12.0,
            azimuth_windows=[[140.0, 180.0]],
        ),
        ReflectionZoneConfig(
            name="south_face",
            min_elevation_deg=10.0,
            max_elevation_deg=20.0,
            azimuth_windows=[[220.0, 260.0]],
        ),
    ]

    assert matches_reflection_zones(150.0, 8.0, example_config.geometry, example_config.processing) is True
    assert matches_reflection_zones(235.0, 15.0, example_config.geometry, example_config.processing) is True
    assert matches_reflection_zones(190.0, 8.0, example_config.geometry, example_config.processing) is False
    assert matches_reflection_zones(150.0, 16.0, example_config.geometry, example_config.processing) is False
