from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.rinex3_writer import RINEX3Writer
from utils.split_rinex_hourly import derive_station_code, split_rinex_hourly_file


def _write_sample_rinex(path: Path) -> Path:
    writer = RINEX3Writer(
        str(path),
        marker_name="DEVICE",
        station_code="TEST",
        receiver_number="00",
        country_code="CHN",
        interval="01S",
        header_interval_seconds=1.0,
        time_system="UTC",
        file_time=datetime(2026, 3, 24, 0, 0, 0),
    )
    assert writer.open()
    assert writer.write_header(
        sys_obs_types={"G": ["C1C", "L1C", "D1C", "S1C"]},
        receiver_type="DEVICE",
        antenna_type="UNKNOWN",
    )
    assert writer.write_observation(
        datetime(2026, 3, 24, 0, 59, 59),
        {"G01": type("Sat", (), {"signals": {"1C": type("Sig", (), {"pseudorange": 1.0, "phase": 2.0, "doppler": 3.0, "snr": 4.0, "half_cycle": 0})()}})()},
    )
    assert writer.write_observation(
        datetime(2026, 3, 24, 1, 0, 0),
        {"G01": type("Sat", (), {"signals": {"1C": type("Sig", (), {"pseudorange": 5.0, "phase": 6.0, "doppler": 7.0, "snr": 8.0, "half_cycle": 0})()}})()},
    )
    writer.close()
    return path


def test_derive_station_code():
    assert derive_station_code("F9P") == "F9P0"
    assert derive_station_code("UM982") == "UM98"
    assert derive_station_code("Mosaic-X5") == "MOSA"


def test_split_rinex_hourly_file_writes_two_hourly_files(tmp_path):
    source = _write_sample_rinex(tmp_path / "source.rnx")
    out_dir = tmp_path / "hourly"

    result = split_rinex_hourly_file(
        source,
        out_dir,
        marker_name="Mosaic-X5",
        receiver_type="Mosaic-X5",
    )

    assert result.interval_seconds == 1.0
    assert len(result.output_files) == 2
    assert result.output_files[0].name.startswith("MOSA00CHN_R_20260830000_01H_01S_MO")
    assert result.output_files[1].name.startswith("MOSA00CHN_R_20260830100_01H_01S_MO")

    first_text = result.output_files[0].read_text(encoding="utf-8")
    second_text = result.output_files[1].read_text(encoding="utf-8")
    assert "TIME OF FIRST OBS" in first_text and "UTC" in first_text
    assert "> 2026 03 24 00 59 59.0000000" in first_text
    assert "> 2026 03 24 01 00  0.0000000" in second_text
