"""Batch processor integration tests."""

from pathlib import Path

from core.reflectometry.providers import ListObservationProvider
from core.reflectometry.services.batch import BatchProcessor
from tests.reflectometry.helpers import generate_synthetic_observations


def test_batch_processor_recovers_reflector_height(example_config):
    example_config.input.constellations = ["G"]
    example_config.input.signals = ["1C"]
    observations = generate_synthetic_observations(
        station_id=example_config.station.station_id,
        receiver_position=example_config.station.receiver_position,
        constellations=("G",),
        signals=("1C",),
        arc_count=4,
        samples_per_arc=70,
        reflector_height_m=4.3,
        noise_std_db=0.2,
        amplitude_db=2.8,
        sampling_interval_seconds=example_config.input.sampling_interval,
    )

    processor = BatchProcessor(example_config, provider=ListObservationProvider(observations))
    result = processor.run()

    successful = [item for item in result.arc_solutions if item.success and item.reflector_height_m is not None]
    assert len(successful) >= 3
    mean_height = sum(item.reflector_height_m for item in successful) / len(successful)
    assert abs(mean_height - 4.3) < 0.35
    assert all(len(item.candidates) <= 1 for item in result.arc_solutions)
    assert len(result.products) >= len(successful)


def test_batch_processor_writes_outputs(example_config):
    example_config.input.constellations = ["G"]
    example_config.input.signals = ["1C"]
    observations = generate_synthetic_observations(
        station_id=example_config.station.station_id,
        receiver_position=example_config.station.receiver_position,
        constellations=("G",),
        signals=("1C",),
        arc_count=2,
        samples_per_arc=50,
        reflector_height_m=4.0,
        noise_std_db=0.15,
        sampling_interval_seconds=example_config.input.sampling_interval,
    )

    processor = BatchProcessor(example_config, provider=ListObservationProvider(observations))
    result = processor.run()
    written = processor.write_outputs(result)

    names = {Path(path).name for path in written}
    assert "arc_solutions.csv" in names
    assert "products.csv" in names
    assert "results.json" in names
    assert "intermediate_arc_series.csv" in names
    assert "arc_spectra.csv" in names
