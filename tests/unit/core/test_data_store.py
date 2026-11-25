"""Unit tests for the bounded GNSS-IR observation store."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from core.data_store import GnssIrStore


@dataclass
class _Signal:
    snr: float
    pseudorange: float = 20_000_000.0
    phase: float = 100_000.0


@dataclass
class _Satellite:
    sys_id: str
    elevation: float
    azimuth: float
    signals: dict[str, _Signal] = field(default_factory=dict)


@pytest.mark.unit
def test_store_filters_system_geometry_and_invalid_snr() -> None:
    store = GnssIrStore()
    satellites = {
        "G01": _Satellite("G", 15.0, 45.0, {"1C": _Signal(42.0)}),
        "G02": _Satellite("G", 5.0, 45.0, {"1C": _Signal(40.0)}),
        "G03": _Satellite("G", 15.0, 180.0, {"1C": _Signal(39.0)}),
        "R01": _Satellite("R", 15.0, 45.0, {"1C": _Signal(38.0)}),
        "G04": _Satellite("G", 15.0, 45.0, {"1C": _Signal(0.0)}),
    }

    store.add_epoch(
        100.0,
        satellites,
        {
            "MIN_ELEVATION_DEG": 10.0,
            "MAX_ELEVATION_DEG": 30.0,
            "AZ_WINDOWS_DEG": [(30.0, 60.0)],
        },
        {"G"},
    )

    samples = store.get_series()
    assert len(samples) == 1
    assert samples[0].prn == "G01"
    assert samples[0].signal_id == "1C"


@pytest.mark.unit
def test_store_evicts_expired_samples_and_filters_queries() -> None:
    store = GnssIrStore(keep_seconds=10)
    satellite = _Satellite(
        "G",
        20.0,
        90.0,
        {"1C": _Signal(45.0), "2W": _Signal(40.0)},
    )

    store.add_epoch(100.0, {"G01": satellite}, {}, {"G"})
    store.add_epoch(111.0, {"G02": satellite}, {}, {"G"})

    assert store.size() == 2
    assert {sample.prn for sample in store.get_series()} == {"G02"}
    assert [sample.signal_id for sample in store.get_series(signal_id="2W")] == ["2W"]
    assert store.get_series(sys="R") == []
