from __future__ import annotations

from datetime import datetime, timezone

from core.data_models import EpochObservation, SatelliteState, SignalData
from core.global_config import GlobalConfig
from core.reflectometry.config import InputConfig
from core.reflectometry.models import ReceiverPosition
from core.reflectometry.rinex_batch import (
    build_observation_records_from_epoch,
    signal_enabled_for_reflectometry,
)


def _signal(signal_id: str, *, snr: float, pseudorange: float, phase: float, doppler: float) -> SignalData:
    return SignalData(
        signal_id=signal_id,
        snr=snr,
        phase=phase,
        pseudorange=pseudorange,
        lock_time=0,
        half_cycle=0,
        doppler=doppler,
    )


def test_build_observation_records_from_epoch_uses_override_timestamp_and_filters_inputs():
    fallback_timestamp = datetime(2025, 7, 5, 0, 0, 0, tzinfo=timezone.utc)
    receiver_position = ReceiverPosition(
        latitude_deg=43.1,
        longitude_deg=7.2,
        height_m=12.5,
        x_m=3875000.0,
        y_m=332500.0,
        z_m=5029000.0,
    )
    epoch = EpochObservation(
        gps_time=0.0,
        satellites={
            "G01": SatelliteState(
                sys_id="G",
                prn=1,
                azimuth=123.4,
                elevation=18.5,
                signals={
                    "1C": _signal("1C", snr=45.0, pseudorange=21474836.0, phase=123456.5, doppler=-1234.0),
                    "5Q": _signal("5Q", snr=48.0, pseudorange=21474840.0, phase=223456.5, doppler=-1134.0),
                },
            ),
            "E11": SatelliteState(
                sys_id="E",
                prn=11,
                azimuth=222.0,
                elevation=25.0,
                signals={"1C": _signal("1C", snr=40.0, pseudorange=23456789.0, phase=654321.0, doppler=123.0)},
            ),
        },
    )

    records = build_observation_records_from_epoch(
        epoch,
        station_id="TEST",
        timestamp=fallback_timestamp,
        receiver_position=receiver_position,
        active_systems={"G"},
        input_config=InputConfig(constellations=["G"], signals=["1C"], exclude_signals=["5Q"]),
    )

    assert len(records) == 1
    record = records[0]
    assert record.station_id == "TEST"
    assert record.timestamp == fallback_timestamp
    assert record.constellation == "G"
    assert record.satellite == "G01"
    assert record.signal == "1C"
    assert record.snr == 45.0
    assert record.azimuth_deg == 123.4
    assert record.elevation_deg == 18.5
    assert record.pseudorange_m == 21474836.0
    assert record.carrier_phase_cycles == 123456.5
    assert record.receiver_position == receiver_position


def test_signal_enabled_for_reflectometry_respects_include_and_exclude_rules():
    config = InputConfig(
        constellations=["G", "E"],
        signals=["1C", "5Q"],
        exclude_constellations=["E"],
        exclude_signals=["5Q"],
    )

    assert signal_enabled_for_reflectometry("G", "1C", active_systems={"G", "E"}, input_config=config) is True
    assert signal_enabled_for_reflectometry("E", "1C", active_systems={"G", "E"}, input_config=config) is False
    assert signal_enabled_for_reflectometry("G", "5Q", active_systems={"G", "E"}, input_config=config) is False
    assert signal_enabled_for_reflectometry("R", "1C", active_systems={"G", "E"}, input_config=config) is False


def test_global_config_round_trip_preserves_final_results_only_flag():
    config = GlobalConfig()
    config.obs_settings.source_type = "RINEX File"
    config.obs_settings.file_path = "tests/sample.obs"
    config.obs_settings.replay_speed = 15.0
    config.obs_settings.final_results_only = True
    config.eph_settings.source_type = "File"
    config.eph_settings.file_path = "tests/sample.nav"

    payload = config.to_dict()

    assert payload["obs_settings"]["final_results_only"] is True

    restored = GlobalConfig()
    restored.from_dict(payload)

    assert restored.obs_settings.source_type == "RINEX File"
    assert restored.obs_settings.file_path == "tests/sample.obs"
    assert restored.obs_settings.replay_speed == 15.0
    assert restored.obs_settings.final_results_only is True
    assert restored.eph_settings.source_type == "File"
    assert restored.eph_settings.file_path == "tests/sample.nav"
