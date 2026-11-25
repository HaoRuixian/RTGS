"""Unit tests for constellation-specific RINEX navigation records."""

from __future__ import annotations

import pytest

from core.rinex_loader import FileEphemerisProvider


def _navigation_line(prefix: str, *values: float) -> str:
    return prefix + "".join(f"{value:19.12E}" for value in values) + "\n"


def _keplerian_record(satellite_id: str) -> list[str]:
    return [
        _navigation_line(f"{satellite_id} 2025 07 05 00 00 00", 1e-4, 2e-12, 0.0, 0.0),
        _navigation_line("    ", 1.0, 2.0, 3.0, 4.0),
        _navigation_line("    ", 5.0, 0.01, 6.0, 5153.6),
        _navigation_line("    ", 604790.0, 7.0, 8.0, 9.0),
        _navigation_line("    ", 0.3, 10.0, 11.0, 12.0),
        _navigation_line("    ", 13.0, 14.0, 1000.0, 15.0),
        _navigation_line("    ", 16.0, 17.0, 18.0, 19.0),
        _navigation_line("    ", 20.0, 21.0, 22.0, 23.0),
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("satellite_id", "system", "expected_prn"),
    [
        ("G06", "GPS", 6),
        ("J03", "QZSS", 195),
        ("E12", "Galileo", 12),
        ("C06", "BeiDou", 6),
        ("I04", "IRNSS", 4),
    ],
)
def test_keplerian_navigation_record_dispatch(
    satellite_id: str,
    system: str,
    expected_prn: int,
) -> None:
    record = FileEphemerisProvider._parse_nav_record(
        satellite_id,
        _keplerian_record(satellite_id),
    )

    assert record is not None
    assert record["system"] == system
    assert record["satellite_id"] == satellite_id
    assert record["PRN"] == expected_prn
    assert record["sqrt_a"] == 5153.6
    assert record["a"] == pytest.approx(5153.6**2)
    assert record["e"] == 0.01
    assert record["af0"] == 1e-4


@pytest.mark.unit
def test_glonass_navigation_record_dispatch() -> None:
    lines = [
        _navigation_line("R08 2025 07 05 00 00 00", -1e-4, 2e-12, 0.0, 0.0),
        _navigation_line("    ", 19_100.0, -1.5, 0.001, 1.0),
        _navigation_line("    ", -11_200.0, 2.5, -0.002, -7.0),
        _navigation_line("    ", 21_500.0, 0.5, 0.003, 0.0),
    ]

    record = FileEphemerisProvider._parse_nav_record("R08", lines)

    assert record is not None
    assert record["system"] == "GLONASS"
    assert record["frequency_channel"] == -7
    assert record["X"] == 19_100.0
    assert record["Y"] == -11_200.0
    assert record["Z"] == 21_500.0
    assert record["tau_n"] == -1e-4


@pytest.mark.unit
def test_navigation_record_rejects_malformed_or_unsupported_satellite() -> None:
    assert FileEphemerisProvider._parse_nav_record("GXX", ["malformed\n"]) is None
    assert FileEphemerisProvider._parse_nav_record("S01", _keplerian_record("S01")) is None
