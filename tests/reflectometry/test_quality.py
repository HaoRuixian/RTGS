"""Quality-control behavior tests."""

from __future__ import annotations

from datetime import datetime

from core.reflectometry.providers import ListObservationProvider, MockObservationProvider
from core.reflectometry.models import ObservationRequest
from core.reflectometry.services.batch import BatchProcessor


def test_cycle_slip_flags_do_not_fail_snr_ir(example_config):
    example_config.input.constellations = ["G"]
    example_config.input.signals = ["1C"]
    example_config.qc.reject_cycle_slip_suspects = True
    example_config.input.source_options = {
        "arc_count": 3,
        "samples_per_arc": 60,
        "reflector_height_m": 4.1,
        "noise_std_db": 0.18,
        "amplitude_db": 2.7,
    }

    provider = MockObservationProvider(
        station_id=example_config.station.station_id,
        receiver_position=example_config.station.receiver_position,
        source_options=example_config.input.source_options,
    )
    observations = provider.fetch_observations(
        ObservationRequest(
            start_time=datetime.fromisoformat(example_config.input.time_window.start),
            end_time=datetime.fromisoformat(example_config.input.time_window.end),
            constellations=tuple(example_config.input.constellations),
            signals=tuple(example_config.input.signals),
            sampling_interval_seconds=example_config.input.sampling_interval,
        )
    )
    for index in range(10, len(observations), 18):
        if observations[index].carrier_phase_cycles is not None:
            observations[index].carrier_phase_cycles += 24.0

    processor = BatchProcessor(example_config, provider=ListObservationProvider(observations))
    result = processor.run()

    assert all("cycle_slip_suspect" not in solution.qc_flags for solution in result.arc_solutions)
    assert all("cycle_slip_suspect" not in (solution.fail_reason or "") for solution in result.arc_solutions)
    assert any(solution.success for solution in result.arc_solutions)

