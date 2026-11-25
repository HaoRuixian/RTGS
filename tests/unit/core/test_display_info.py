"""Tests for the compatibility console-reporting pipeline."""

from __future__ import annotations

import pytest

from core.data_models import EpochObservation, SatelliteState, SignalData
from core.display_info import group_satellites_by_system, print_satellite_block
from core.process import process_epoch


def _signal() -> SignalData:
    return SignalData(
        signal_id="1C",
        snr=45.0,
        phase=123_456.25,
        pseudorange=21_000_000.5,
        lock_time=10,
        half_cycle=0,
        doppler=-1200.0,
    )


@pytest.mark.unit
def test_group_satellites_preserves_system_mapping_and_satellite_order() -> None:
    epoch = EpochObservation(
        gps_time=100.0,
        satellites={
            "G01": SatelliteState("G", 1),
            "R03": SatelliteState("R", 3),
            "G02": SatelliteState("G", 2),
        },
    )

    grouped, system_names = group_satellites_by_system(epoch)

    assert [satellite_id for satellite_id, _satellite in grouped["G"]] == ["G01", "G02"]
    assert [satellite_id for satellite_id, _satellite in grouped["R"]] == ["R03"]
    assert system_names["C"] == "BeiDou"


@pytest.mark.unit
def test_satellite_block_counts_only_present_signals(capsys) -> None:
    satellite = SatelliteState(
        "G",
        1,
        elevation=30.0,
        azimuth=120.0,
        signals={"1C": _signal(), "2W": None},
    )

    count = print_satellite_block("G", [("G01", satellite)], {"G": "GPS"})

    output = capsys.readouterr().out
    assert count == 1
    assert "[GPS] (1 sats)" in output
    assert "G01" in output
    assert "21000000.500" in output


@pytest.mark.unit
def test_process_epoch_prints_header_body_and_footer(capsys) -> None:
    epoch = EpochObservation(
        gps_time=123.5,
        satellites={
            "E11": SatelliteState("E", 11, elevation=25.0, azimuth=80.0, signals={"1C": _signal()})
        },
    )

    process_epoch(epoch)

    output = capsys.readouterr().out
    assert "EPOCH TIME : 123.5" in output
    assert "[Galileo]" in output
    assert "Valid SNR sats = 1" in output
