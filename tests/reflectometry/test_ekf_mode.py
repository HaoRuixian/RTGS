"""EKF reflectometry mode tests."""

from __future__ import annotations

from core.reflectometry.models import ProductType
from core.reflectometry.config import ReflectionZoneConfig
from core.reflectometry.providers import ListObservationProvider
from core.reflectometry.services.batch import BatchProcessor
from core.reflectometry.services.realtime import RealtimeProcessor
from tests.reflectometry.helpers import generate_synthetic_observations


def _configure_ekf(example_config):
    example_config.input.constellations = ["G"]
    example_config.input.signals = ["1C"]
    example_config.input.sampling_interval = 30.0
    example_config.ir.estimation_mode = "ekf"
    example_config.ir.min_reflector_height = 2.0
    example_config.ir.max_reflector_height = 7.0
    example_config.ir.ekf.initial_rh_m = 4.2
    example_config.ir.ekf.rh_init_min_height_m = None
    example_config.ir.ekf.rh_init_max_height_m = None
    example_config.ir.ekf.rh_init_min_samples = 20
    example_config.ir.ekf.rh_init_max_samples_per_arc = 80
    example_config.ir.ekf.output_interval_seconds = 300
    example_config.ir.ekf.output_window_seconds = 300
    example_config.ir.ekf.measurement_variance = 0.25
    example_config.ir.ekf.max_time_gap_seconds = 90.0
    example_config.processing.min_elevation_deg = 5.0
    example_config.processing.max_elevation_deg = 28.0
    example_config.qc.min_arc_duration = 60.0
    example_config.products.enable_dynamic_sea_level_correction = False
    return example_config


def test_batch_processor_emits_ekf_products(example_config):
    config = _configure_ekf(example_config)
    observations = generate_synthetic_observations(
        station_id=config.station.station_id,
        receiver_position=config.station.receiver_position,
        constellations=("G",),
        signals=("1C",),
        arc_count=6,
        samples_per_arc=80,
        reflector_height_m=4.25,
        noise_std_db=0.05,
        amplitude_db=3.0,
        sampling_interval_seconds=config.input.sampling_interval,
    )

    processor = BatchProcessor(config, provider=ListObservationProvider(observations))
    result = processor.run()

    rh_products = [item for item in result.products if item.product_type == ProductType.REFLECTOR_HEIGHT]
    assert result.metadata["estimation_mode"] == "ekf"
    assert rh_products
    assert abs(rh_products[-1].value - 4.25) < 0.75
    assert processor.config.ir.ekf.initial_rh_m == 4.2


def test_realtime_processor_emits_ekf_products(example_config):
    config = _configure_ekf(example_config)
    observations = generate_synthetic_observations(
        station_id=config.station.station_id,
        receiver_position=config.station.receiver_position,
        constellations=("G",),
        signals=("1C",),
        arc_count=4,
        samples_per_arc=75,
        reflector_height_m=4.25,
        noise_std_db=0.08,
        amplitude_db=3.0,
        sampling_interval_seconds=config.input.sampling_interval,
    )

    processor = RealtimeProcessor(config)
    for index in range(0, len(observations), 25):
        chunk = observations[index : index + 25]
        processor.ingest(chunk, reference_time=chunk[-1].timestamp, include_open_preview=True)

    result = processor.flush()
    rh_products = [item for item in result.products if item.product_type == ProductType.REFLECTOR_HEIGHT]
    assert result.metadata["estimation_mode"] == "ekf"
    assert rh_products
    assert any(item.metadata["active_arc_count"] >= 1 for item in rh_products)


def test_realtime_ekf_emits_when_output_window_exceeds_interval(example_config):
    config = _configure_ekf(example_config)
    config.ir.ekf.output_interval_seconds = 60
    config.ir.ekf.output_window_seconds = 120
    observations = generate_synthetic_observations(
        station_id=config.station.station_id,
        receiver_position=config.station.receiver_position,
        constellations=("G",),
        signals=("1C",),
        arc_count=4,
        samples_per_arc=90,
        reflector_height_m=4.25,
        noise_std_db=0.05,
        amplitude_db=3.0,
        sampling_interval_seconds=config.input.sampling_interval,
    )

    processor = RealtimeProcessor(config)
    for index in range(0, len(observations), 10):
        chunk = observations[index : index + 10]
        processor.ingest(chunk, reference_time=chunk[-1].timestamp)

    rh_products = [
        item for item in processor.last_result.products if item.product_type == ProductType.REFLECTOR_HEIGHT
    ]
    assert rh_products
    assert all(item.metadata["active_arc_count"] > 0 for item in rh_products)


def test_ekf_initializes_reflector_height_from_lsp_not_configured_fallback(example_config):
    config = _configure_ekf(example_config)
    config.ir.ekf.initial_rh_m = 6.8
    config.ir.ekf.rh_init_min_samples = 20
    config.ir.ekf.rh_init_max_arcs = 4
    observations = generate_synthetic_observations(
        station_id=config.station.station_id,
        receiver_position=config.station.receiver_position,
        constellations=("G",),
        signals=("1C",),
        arc_count=4,
        samples_per_arc=85,
        reflector_height_m=4.25,
        noise_std_db=0.02,
        amplitude_db=3.0,
        sampling_interval_seconds=config.input.sampling_interval,
    )

    processor = RealtimeProcessor(config)
    processor.ingest(observations[:170], reference_time=observations[169].timestamp)

    assert processor.ekf_processor is not None
    initialization = processor.ekf_processor.rh_initialization
    assert initialization is not None
    assert initialization.arc_count >= 1
    assert abs(initialization.reflector_height_m - 4.25) < abs(6.8 - 4.25)


def test_ekf_lsp_min_arcs_counts_satellites_not_signals(example_config):
    config = _configure_ekf(example_config)
    config.input.signals = ["1C", "2W"]
    config.ir.ekf.initial_rh_m = 4.2
    config.ir.ekf.rh_init_min_arcs = 2
    config.ir.ekf.rh_init_max_arcs = 4
    observations = generate_synthetic_observations(
        station_id=config.station.station_id,
        receiver_position=config.station.receiver_position,
        constellations=("G",),
        signals=("1C", "2W"),
        arc_count=2,
        samples_per_arc=85,
        reflector_height_m=4.25,
        noise_std_db=0.02,
        amplitude_db=3.0,
        sampling_interval_seconds=config.input.sampling_interval,
    )
    for observation in observations:
        observation.satellite = "G01"

    processor = RealtimeProcessor(config)
    processor.ingest(observations[:170], reference_time=observations[169].timestamp)

    assert processor.ekf_processor is not None
    assert processor.ekf_processor.rh_initialization is None


def test_ekf_gap_threshold_tracks_realtime_sampling_interval(example_config):
    config = _configure_ekf(example_config)
    config.input.sampling_interval = 30.0
    config.ir.ekf.max_time_gap_seconds = 22.5
    config.ir.ekf.rh_init_min_samples = 20
    observations = generate_synthetic_observations(
        station_id=config.station.station_id,
        receiver_position=config.station.receiver_position,
        constellations=("G",),
        signals=("1C",),
        arc_count=2,
        samples_per_arc=85,
        reflector_height_m=4.25,
        noise_std_db=0.02,
        amplitude_db=3.0,
        sampling_interval_seconds=config.input.sampling_interval,
    )

    processor = RealtimeProcessor(config)
    processor.ingest(observations[:90], reference_time=observations[89].timestamp)

    assert processor.ekf_processor is not None
    assert processor.ekf_processor.rh_initialization is not None


def test_realtime_ekf_filters_observations_outside_reflection_zone(example_config):
    config = _configure_ekf(example_config)
    config.geometry.reflection_zones = [
        ReflectionZoneConfig(
            name="narrow_zone",
            min_elevation_deg=5.0,
            max_elevation_deg=28.0,
            azimuth_windows=[[300.0, 320.0]],
        )
    ]
    observations = generate_synthetic_observations(
        station_id=config.station.station_id,
        receiver_position=config.station.receiver_position,
        constellations=("G",),
        signals=("1C",),
        arc_count=2,
        samples_per_arc=85,
        reflector_height_m=4.25,
        noise_std_db=0.02,
        amplitude_db=3.0,
        sampling_interval_seconds=config.input.sampling_interval,
    )

    processor = RealtimeProcessor(config)
    processor.ingest(observations, reference_time=observations[-1].timestamp)

    assert processor.ekf_processor is not None
    assert not processor.ekf_processor.arc_states
    assert processor.ekf_processor.rh_initialization is None
