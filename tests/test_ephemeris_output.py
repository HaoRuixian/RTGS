from __future__ import annotations

from datetime import datetime, timezone

from core.ephemeris_output import BroadcastNavWriter, PreciseSp3Writer


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
