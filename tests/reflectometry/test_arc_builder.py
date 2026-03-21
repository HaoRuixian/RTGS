"""Arc builder tests."""

from core.reflectometry.providers import MockObservationProvider
from core.reflectometry.config import ReflectionZoneConfig
from core.reflectometry.models import ObservationRequest
from core.reflectometry.services.arc_builder import ArcBuilder
from core.reflectometry.services.geometry import GeometryResolver, matches_reflection_zones


def test_arc_builder_creates_rising_and_setting_arcs(example_config):
    example_config.input.constellations = ["G"]
    example_config.input.signals = ["1C"]
    example_config.input.source_options = {
        "arc_count": 4,
        "samples_per_arc": 50,
        "reflector_height_m": 4.0,
        "noise_std_db": 0.2,
    }

    provider = MockObservationProvider(
        station_id=example_config.station.station_id,
        receiver_position=example_config.station.receiver_position,
        source_options=example_config.input.source_options,
    )
    request = ObservationRequest(
        sampling_interval_seconds=example_config.input.sampling_interval,
        constellations=tuple(example_config.input.constellations),
        signals=tuple(example_config.input.signals),
    )
    observations = provider.fetch_observations(request)
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


