from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core.broadcast_ephemeris import BroadcastEphemeris
from core.ephemeris_output import BroadcastNavWriter, PreciseSp3Writer, _compute_clock_correction
from core.gnss_time import GNSSTime


def test_broadcast_nav_writer_writes_rinex_nav_record(tmp_path):
    path = tmp_path / "live_nav.rnx"
    writer = BroadcastNavWriter(path)

    wrote = writer.write_ephemeris(
        {
            "satellite_id": "G01",
            "system": "GPS",
            "PRN": 1,
            "week": 2412,
            "toe": 345600.0,
            "toc": 345600.0,
            "af0": 1.0e-4,
            "af1": 2.0e-12,
            "af2": 0.0,
            "iode": 7,
            "Crs": 1.0,
            "delta_n": 2.0e-9,
            "M0": 0.1,
            "Cuc": 1.0e-6,
            "e": 0.01,
            "Cus": 2.0e-6,
            "sqrt_a": 5153.6,
            "Cic": 3.0e-6,
            "Omega0": 1.0,
            "Cis": 4.0e-6,
            "i0": 0.94,
            "Crc": 2.0,
            "omega": 0.2,
            "Omega_dot": -8.0e-9,
            "idot": 1.0e-10,
            "ura": 2,
            "health": 0,
            "TGD": -2.3e-9,
            "iodc": 7,
        }
    )
    writer.close()

    text = path.read_text(encoding="utf-8")
    assert wrote is True
    assert "RINEX VERSION / TYPE" in text
    assert "END OF HEADER" in text
    assert "G01 2026 04 01 23 59 42" in text
    assert "1.000000000000E-04" in text


def test_precise_sp3_writer_writes_corrected_epoch_records(tmp_path):
    path = tmp_path / "live_precise.sp3"
    writer = PreciseSp3Writer(path, epoch_interval_seconds=5)
    writer.write_epoch(
        datetime(2026, 3, 26, 0, 0, 0, tzinfo=timezone.utc),
        {
            "G01": ([20_200_000.0, 14_000_000.0, 21_700_000.0], 1.0e-6, True),
            "E11": ([23_200_000.0, 12_000_000.0, 19_700_000.0], -2.0e-6, False),
        },
    )
    writer.close()

    text = path.read_text(encoding="utf-8")
    assert text.startswith("#cP2026 03 26 00 00 00.00000000")
    assert "*  2026 03 26 00 00 00.00000000" in text
    assert "PG01  20200.000000  14000.000000  21700.000000      1.000000" in text
    assert "PE11  23200.000000  12000.000000  19700.000000     -2.000000" in text
    assert text.rstrip().endswith("EOF")


def test_precise_sp3_writer_clamps_invalid_clock_field(tmp_path):
    path = tmp_path / "invalid_clock.sp3"
    writer = PreciseSp3Writer(path, epoch_interval_seconds=5)
    writer.write_epoch(
        datetime(2026, 3, 26, 0, 0, 0, tzinfo=timezone.utc),
        {"R01": ([20_200_000.0, 14_000_000.0, 21_700_000.0], 186_386.0, False)},
    )
    writer.close()

    text = path.read_text(encoding="utf-8")
    assert "PR01  20200.000000  14000.000000  21700.000000 999999.999999" in text


def test_glonass_sp3_clock_uses_tau_and_gamma_with_rinex_sign():
    clock = _compute_clock_correction(
        {
            "satellite_id": "R08",
            "tau_n": 100.0e-6,
            "gamma_n": 2.0e-10,
            "tb": 10_000.0,
        },
        10_900.0,
    )

    assert clock == pytest.approx(100.180000036e-6)


def test_rtcm_glonass_tau_is_normalized_to_rinex_clock_bias(monkeypatch):
    monkeypatch.setattr(GNSSTime, "gps_day_of_week", classmethod(lambda cls: 5))
    handler = BroadcastEphemeris()
    msg = SimpleNamespace(
        DF038=8,
        DF040=7,
        DF110=32,
        DF107=0,
        DF112=10_000.0,
        DF115=12_000.0,
        DF118=18_000.0,
        DF111=0.1,
        DF114=0.2,
        DF117=0.3,
        DF113=0.0,
        DF116=0.0,
        DF119=0.0,
        DF124=-134_218,
        DF121=330,
        DF104=0,
        DF105=1,
    )

    eph = handler.extract_glonass_ephemeris(msg)

    assert eph["tau_n"] == pytest.approx(134_218 * (2 ** -30))
    assert eph["gamma_n"] == pytest.approx(330 * (2 ** -40))
    assert eph["tb"] == pytest.approx(5 * 86_400 + 32 * 900 - 3 * 3600 + 18)
    assert eph["tk"] == pytest.approx(5 * 86_400 - 3 * 3600 + 18)
