"""Merge hourly RINEX observation files into daily RINEX 3 files."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import chain
from pathlib import Path
from typing import Iterable, Iterator, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.rinex3_writer import RINEX3Writer
from core.rinex_loader import RinexObservationReader, read_rinex_observation_header
from core.gnss_time import GNSSTime
from utils.split_rinex_hourly import (
    _estimate_interval_seconds,
    _normalize_utc_datetime,
    _round_epoch_time,
    derive_station_code,
)


@dataclass
class MergeResult:
    source_files: list[Path]
    output_files: list[Path]
    interval_seconds: float


def _iter_input_files(inputs: Iterable[str | Path]) -> list[Path]:
    resolved: list[Path] = []

    for item in inputs:
        path = Path(item)
        if path.is_dir():
            resolved.extend(sorted(child for child in path.iterdir() if child.is_file() and child.suffix.lower() == ".rnx"))
        elif path.is_file() and path.suffix.lower() == ".rnx":
            resolved.append(path)

    unique_paths: list[Path] = []
    seen: set[Path] = set()
    for path in sorted(resolved):
        normalized = path.resolve()
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_paths.append(normalized)

    return unique_paths


def _iter_source_epochs(paths: Iterable[Path]) -> Iterator:
    for path in paths:
        reader = RinexObservationReader(path)
        yield from reader.iter_epochs()


def _day_bucket(epoch_time: datetime) -> datetime:
    normalized = _normalize_utc_datetime(epoch_time)
    return normalized.replace(hour=0, minute=0, second=0, microsecond=0)


def _select_aligned_epoch_time(
    epoch_time: datetime,
    target_interval_seconds: float,
    *,
    tolerance_seconds: float = 0.01,
) -> datetime | None:
    normalized = _normalize_utc_datetime(epoch_time)
    rounded = _round_epoch_time(normalized, target_interval_seconds)
    if abs((normalized - rounded).total_seconds()) > max(0.001, float(tolerance_seconds)):
        return None
    return rounded


def _convert_output_time(epoch_time: datetime, time_system: str) -> datetime:
    normalized = _normalize_utc_datetime(epoch_time)
    system = str(time_system or "UTC").strip().upper() or "UTC"
    if system == "UTC":
        return normalized
    if system == "GPS":
        return normalized + timedelta(seconds=GNSSTime.LEAP_SECONDS)
    raise ValueError(f"Unsupported output time system: {time_system}")


def _merge_sys_obs_types(target: dict[str, list[str]], source: dict[str, list[str]]) -> None:
    for system, obs_types in source.items():
        merged = target.setdefault(system, [])
        seen = set(merged)
        for obs_type in obs_types:
            if obs_type not in seen:
                merged.append(obs_type)
                seen.add(obs_type)


def merge_rinex_daily_files(
    inputs: Iterable[str | Path],
    output_dir: str | Path,
    *,
    marker_name: str,
    receiver_type: str,
    station_code: Optional[str] = None,
    receiver_number: str = "00",
    country_code: str = "CHN",
    antenna_type: str = "UNKNOWN",
    antenna_number: str = "",
    datatype: str = "MO",
    output_interval_seconds: Optional[float] = None,
    time_system: str = "UTC",
) -> MergeResult:
    source_files = _iter_input_files(inputs)
    if not source_files:
        raise ValueError("No input RINEX observation files were found.")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    combined_sys_obs_types: dict[str, list[str]] = {}
    approx_position = None
    metadata_interval = None

    for path in source_files:
        metadata = read_rinex_observation_header(path)
        _merge_sys_obs_types(combined_sys_obs_types, metadata.sys_obs_types)
        if metadata_interval is None and metadata.interval_seconds and metadata.interval_seconds > 0:
            metadata_interval = float(metadata.interval_seconds)
        if approx_position is None and metadata.approx_position_ecef:
            approx_position = tuple(float(value) for value in metadata.approx_position_ecef[:3])

    epoch_iter = _iter_source_epochs(source_files)

    buffered_epochs = []
    for epoch in epoch_iter:
        buffered_epochs.append(epoch)
        if len(buffered_epochs) >= 200:
            break

    if not buffered_epochs:
        raise ValueError("No observation epochs found in the input RINEX files.")

    source_interval_seconds = _estimate_interval_seconds(
        [_normalize_utc_datetime(epoch.utc_datetime) for epoch in buffered_epochs if epoch.utc_datetime is not None],
        fallback=float(metadata_interval or 1.0),
    )
    target_interval_seconds = max(
        float(source_interval_seconds),
        float(output_interval_seconds or source_interval_seconds),
    )

    derived_station_code = station_code or derive_station_code(marker_name)
    output_files: list[Path] = []
    writer: Optional[RINEX3Writer] = None
    current_bucket: Optional[datetime] = None
    last_written_time: Optional[datetime] = None

    def open_writer(bucket_start: datetime) -> RINEX3Writer:
        file_time = _convert_output_time(bucket_start, time_system)
        daily_writer = RINEX3Writer(
            str(output_dir),
            marker_name=marker_name,
            marker_number="0",
            station_code=derived_station_code,
            receiver_number=receiver_number,
            country_code=country_code,
            period="01D",
            interval=RINEX3Writer.format_interval_code(target_interval_seconds),
            datatype=datatype,
            file_time=file_time,
            header_interval_seconds=target_interval_seconds,
            time_system=time_system,
            antenna_number=antenna_number,
        )
        if not daily_writer.open():
            raise OSError(f"Failed to open daily RINEX output: {daily_writer.filename}")
        if approx_position is not None:
            daily_writer.set_approx_position(list(approx_position))
        if not daily_writer.write_header(
            sys_obs_types=combined_sys_obs_types,
            receiver_type=receiver_type,
            antenna_type=antenna_type,
            antenna_number=antenna_number,
        ):
            raise OSError(f"Failed to write daily RINEX header: {daily_writer.filename}")
        output_files.append(Path(daily_writer.filename))
        return daily_writer

    try:
        for epoch in chain(buffered_epochs, epoch_iter):
            if epoch.utc_datetime is None or not epoch.satellites:
                continue

            selected_time = _select_aligned_epoch_time(epoch.utc_datetime, target_interval_seconds)
            if selected_time is None:
                continue
            if last_written_time is not None and selected_time == last_written_time:
                continue

            bucket = _day_bucket(selected_time)

            if writer is None or bucket != current_bucket:
                if writer is not None:
                    writer.close()
                writer = open_writer(bucket)
                current_bucket = bucket

            output_time = _convert_output_time(selected_time, time_system)
            if not writer.write_observation(output_time, epoch.satellites):
                raise OSError(f"Failed to write daily observation epoch at {output_time.isoformat()}")
            last_written_time = selected_time
    finally:
        if writer is not None:
            writer.close()

    return MergeResult(
        source_files=source_files,
        output_files=output_files,
        interval_seconds=target_interval_seconds,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Merge hourly RINEX observation files into daily RINEX 3 files.",
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Input hourly RINEX files or directories containing .rnx files.",
    )
    parser.add_argument("output_dir", type=Path, help="Directory for daily output files.")
    parser.add_argument("--marker-name", required=True, help="Marker name to write into the daily headers.")
    parser.add_argument("--receiver-type", required=True, help="Receiver type string for the daily headers.")
    parser.add_argument("--station-code", default=None, help="Optional 4-character station code for long filenames.")
    parser.add_argument("--receiver-number", default="00", help="Receiver number for long filenames.")
    parser.add_argument("--country-code", default="CHN", help="Country code for long filenames.")
    parser.add_argument("--antenna-type", default="UNKNOWN", help="Antenna type string for the daily headers.")
    parser.add_argument("--antenna-number", default="", help="Antenna serial number for the daily headers.")
    parser.add_argument("--datatype", default="MO", help="RINEX datatype code.")
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Optional output sampling interval in seconds. When omitted, keep the native interval.",
    )
    parser.add_argument(
        "--time-system",
        default="UTC",
        choices=["UTC", "GPS"],
        help="Output observation time system written in the RINEX header and epochs.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        result = merge_rinex_daily_files(
            args.inputs,
            args.output_dir.resolve(),
            marker_name=args.marker_name,
            receiver_type=args.receiver_type,
            station_code=args.station_code,
            receiver_number=args.receiver_number,
            country_code=args.country_code,
            antenna_type=args.antenna_type,
            antenna_number=args.antenna_number,
            datatype=args.datatype,
            output_interval_seconds=args.interval,
            time_system=args.time_system,
        )
    except Exception as exc:
        print(f"RINEX daily merge failed: {exc}", file=sys.stderr)
        return 1

    print(f"Merged daily files: {len(result.output_files)}")
    print(f"Estimated interval: {result.interval_seconds:g}s")
    for path in result.output_files:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
