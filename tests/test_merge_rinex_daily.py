from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.rinex3_writer import RINEX3Writer
from utils.merge_rinex_daily import merge_rinex_daily_files


def _write_hourly_rinex(path: Path, epoch_time: datetime, pseudorange: float) -> Path:
    writer = RINEX3Writer(
        str(path),
        marker_name="DEVICE",
        station_code="TEST",
        receiver_number="00",
        country_code="CHN",
        period="01H",
        interval="01S",
        header_interval_seconds=1.0,
        time_system="UTC",
        file_time=epoch_time.replace(minute=0, second=0, microsecond=0),
    )
    assert writer.open()
    assert writer.write_header(
        sys_obs_types={"G": ["C1C", "L1C", "D1C", "S1C"]},
        receiver_type="DEVICE",
        antenna_type="UNKNOWN",
    )
    assert writer.write_observation(
        epoch_time,
        {"G01": type("Sat", (), {"signals": {"1C": type("Sig", (), {"pseudorange": pseudorange, "phase": 2.0, "doppler": 3.0, "snr": 4.0, "half_cycle": 0})()}})()},
    )
    writer.close()
    return path


def test_merge_rinex_daily_files_writes_one_daily_file(tmp_path):
    source_dir = tmp_path / "hourly"
    source_dir.mkdir()
    _write_hourly_rinex(source_dir / "part1.rnx", datetime(2026, 3, 24, 0, 59, 59), 1.0)
    _write_hourly_rinex(source_dir / "part2.rnx", datetime(2026, 3, 24, 1, 0, 0), 5.0)

    out_dir = tmp_path / "daily"
    result = merge_rinex_daily_files(
        [source_dir],
        out_dir,
        marker_name="Mosaic-X5",
        receiver_type="Mosaic-X5",
    )

    assert result.interval_seconds == 1.0
    assert len(result.output_files) == 1
    assert result.output_files[0].name.startswith("MOSA00CHN_R_20260830000_01D_01S_MO")

    text = result.output_files[0].read_text(encoding="utf-8")
    assert "TIME OF FIRST OBS" in text and "UTC" in text
    assert "> 2026 03 24 00 59 59.0000000" in text
    assert "> 2026 03 24 01 00  0.0000000" in text


def test_merge_rinex_daily_files_resamples_to_15s(tmp_path):
    source_dir = tmp_path / "hourly_15s"
    source_dir.mkdir()

    writer = RINEX3Writer(
        str(source_dir / "part.rnx"),
        marker_name="DEVICE",
        station_code="TEST",
        receiver_number="00",
        country_code="CHN",
        period="01H",
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
    for second in range(31):
        assert writer.write_observation(
            datetime(2026, 3, 24, 0, 0, second),
            {"G01": type("Sat", (), {"signals": {"1C": type("Sig", (), {"pseudorange": float(second), "phase": 2.0, "doppler": 3.0, "snr": 4.0, "half_cycle": 0})()}})()},
        )
    writer.close()

    out_dir = tmp_path / "daily_15s"
    result = merge_rinex_daily_files(
        [source_dir],
        out_dir,
        marker_name="Mosaic-X5",
        receiver_type="Mosaic-X5",
        output_interval_seconds=15.0,
    )

    assert result.interval_seconds == 15.0
    assert len(result.output_files) == 1
    assert result.output_files[0].name.startswith("MOSA00CHN_R_20260830000_01D_15S_MO")

    text = result.output_files[0].read_text(encoding="utf-8")
    assert "> 2026 03 24 00 00  0.0000000" in text
    assert "> 2026 03 24 00 00 15.0000000" in text
    assert "> 2026 03 24 00 00 30.0000000" in text
    assert "> 2026 03 24 00 00  1.0000000" not in text


def test_merge_rinex_daily_files_can_write_gps_time_and_antenna_serial(tmp_path):
    source_dir = tmp_path / "hourly_gps"
    source_dir.mkdir()
    _write_hourly_rinex(source_dir / "part.rnx", datetime(2026, 3, 24, 0, 0, 0), 1.0)

    out_dir = tmp_path / "daily_gps"
    result = merge_rinex_daily_files(
        [source_dir],
        out_dir,
        marker_name="Mosaic-X5",
        receiver_type="Mosaic-X5",
        antenna_number="HXCCGX611A",
        antenna_type="HXCM",
        time_system="GPS",
    )

    assert len(result.output_files) == 1
    text = result.output_files[0].read_text(encoding="utf-8")
    assert "HXCCGX611A" in text and "HXCM" in text and "ANT # / TYPE" in text
    assert "TIME OF FIRST OBS" in text and "GPS" in text
    assert "> 2026 03 24 00 00 18.0000000" in text
