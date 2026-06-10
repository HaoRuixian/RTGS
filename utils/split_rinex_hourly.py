"""Split RINEX observation files into hourly RINEX 3 files."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import chain
from pathlib import Path
from typing import Iterable, Iterator, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.rinex3_writer import RINEX3Writer
from core.rinex_loader import RinexObservationReader, read_rinex_observation_header


@dataclass
class SplitResult:
    source_path: Path
    output_files: list[Path]
    interval_seconds: float


def derive_station_code(device_name: str) -> str:
    cleaned = "".join(ch for ch in str(device_name).upper() if ch.isalnum())
    return (cleaned[:4] or "RTGS").ljust(4, "0")


def _normalize_utc_datetime(epoch_time: datetime) -> datetime:
    if epoch_time.tzinfo is None:
        return epoch_time
    return epoch_time.astimezone(timezone.utc).replace(tzinfo=None)


def _round_epoch_time(epoch_time: datetime, interval_seconds: float) -> datetime:
    normalized = _normalize_utc_datetime(epoch_time)
    interval = max(0.001, float(interval_seconds))
    anchor = datetime(1980, 1, 6)
    total_seconds = (normalized - anchor).total_seconds()
    rounded_seconds = round(total_seconds / interval) * interval
    rounded_time = anchor + timedelta(seconds=rounded_seconds)
    return rounded_time.replace(microsecond=int(round((rounded_time.microsecond) / 1000.0)) * 1000)


def _estimate_interval_seconds(epoch_times: Iterable[datetime], fallback: float = 1.0) -> float:
    deltas = []
    previous = None
    for epoch_time in epoch_times:
        if previous is not None:
            delta = (epoch_time - previous).total_seconds()
            if 0.0 < delta <= 600.0:
                deltas.append(round(delta, 3))
        previous = epoch_time

    if not deltas:
        return max(0.001, float(fallback or 1.0))

    common_delta = Counter(deltas).most_common(1)[0][0]
    canonical = [0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 15.0, 30.0, 60.0]
    for candidate in canonical:
        if abs(common_delta - candidate) < 0.01:
            return candidate
    return float(common_delta)


def _hour_bucket(epoch_time: datetime) -> datetime:
    normalized = _normalize_utc_datetime(epoch_time)
    return normalized.replace(minute=0, second=0, microsecond=0)


def _iter_source_epochs(path: Path) -> Iterator:
    reader = RinexObservationReader(path)
    yield from reader.iter_epochs()


def split_rinex_hourly_file(
    source_path: str | Path,
    output_dir: str | Path,
    *,
    marker_name: str,
    receiver_type: str,
    receiver_serial: str = "",
    receiver_version: str = "",
    station_code: Optional[str] = None,
    receiver_number: str = "00",
    country_code: str = "CHN",
    antenna_type: str = "UNKNOWN",
    antenna_number: str = "",
    datatype: str = "MO",
) -> SplitResult:
    source_path = Path(source_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = read_rinex_observation_header(source_path)
    epoch_iter = _iter_source_epochs(source_path)

    buffered_epochs = []
    for epoch in epoch_iter:
        buffered_epochs.append(epoch)
        if len(buffered_epochs) >= 200:
            break

    if not buffered_epochs:
        raise ValueError(f"No observation epochs found in source RINEX file: {source_path}")

    estimated_interval = _estimate_interval_seconds(
        [_normalize_utc_datetime(epoch.utc_datetime) for epoch in buffered_epochs if epoch.utc_datetime is not None],
        fallback=float(metadata.interval_seconds or 1.0),
    )

    derived_station_code = station_code or derive_station_code(marker_name)
    output_files: list[Path] = []
    writer: Optional[RINEX3Writer] = None
    current_bucket: Optional[datetime] = None

    def open_writer(bucket_start: datetime) -> RINEX3Writer:
        writer = RINEX3Writer(
            str(output_dir),
            marker_name=marker_name,
            marker_number="0",
            station_code=derived_station_code,
            receiver_number=receiver_number,
            country_code=country_code,
            period="01H",
            interval=RINEX3Writer.format_interval_code(estimated_interval),
            datatype=datatype,
            file_time=bucket_start,
            header_interval_seconds=estimated_interval,
            time_system="UTC",
            antenna_number=antenna_number,
            receiver_serial=receiver_serial,
            receiver_version=receiver_version,
        )
        if not writer.open():
            raise OSError(f"Failed to open hourly RINEX output: {writer.filename}")
        if metadata.approx_position_ecef:
            writer.set_approx_position(list(metadata.approx_position_ecef))
        if not writer.write_header(
            sys_obs_types=metadata.sys_obs_types,
            receiver_type=receiver_type,
            receiver_serial=receiver_serial,
            receiver_version=receiver_version,
            antenna_type=antenna_type,
            antenna_number=antenna_number,
        ):
            raise OSError(f"Failed to write hourly RINEX header: {writer.filename}")
        output_files.append(Path(writer.filename))
        return writer

    try:
        for epoch in chain(buffered_epochs, epoch_iter):
            if epoch.utc_datetime is None or not epoch.satellites:
                continue

            rounded_time = _round_epoch_time(epoch.utc_datetime, estimated_interval)
            bucket = _hour_bucket(rounded_time)

            if writer is None or bucket != current_bucket:
                if writer is not None:
                    writer.close()
                writer = open_writer(bucket)
                current_bucket = bucket

            if not writer.write_observation(rounded_time, epoch.satellites):
                raise OSError(f"Failed to write hourly observation epoch for {source_path}")
    finally:
        if writer is not None:
            writer.close()

    return SplitResult(source_path=source_path, output_files=output_files, interval_seconds=estimated_interval)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Split a RINEX observation file into hourly RINEX 3 files.")
    parser.add_argument("input", type=Path, help="Input RINEX observation file.")
    parser.add_argument("output_dir", type=Path, help="Directory for hourly output files.")
    parser.add_argument("--marker-name", required=True, help="Marker name to write into the hourly headers.")
    parser.add_argument("--receiver-type", required=True, help="Receiver type string for the hourly headers.")
    parser.add_argument("--receiver-serial", default="", help="Receiver serial number for the hourly headers.")
    parser.add_argument("--receiver-version", default="", help="Receiver firmware/version for the hourly headers.")
    parser.add_argument("--station-code", default=None, help="Optional 4-character station code for long filenames.")
    parser.add_argument("--receiver-number", default="00", help="Receiver number for long filenames.")
    parser.add_argument("--country-code", default="CHN", help="Country code for long filenames.")
    parser.add_argument("--antenna-type", default="UNKNOWN", help="Antenna type string for the hourly headers.")
    parser.add_argument("--antenna-number", default="", help="Antenna serial number for the hourly headers.")
    parser.add_argument("--datatype", default="MO", help="RINEX datatype code.")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        result = split_rinex_hourly_file(
            args.input.resolve(),
            args.output_dir.resolve(),
            marker_name=args.marker_name,
            receiver_type=args.receiver_type,
            receiver_serial=args.receiver_serial,
            receiver_version=args.receiver_version,
            station_code=args.station_code,
            receiver_number=args.receiver_number,
            country_code=args.country_code,
            antenna_type=args.antenna_type,
            antenna_number=args.antenna_number,
            datatype=args.datatype,
        )
    except Exception as exc:
        print(f"RINEX hourly split failed: {exc}", file=sys.stderr)
        return 1

    print(f"Split hourly files: {len(result.output_files)}")
    print(f"Estimated interval: {result.interval_seconds:g}s")
    for path in result.output_files[:5]:
        print(path)
    if len(result.output_files) > 5:
        print("...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
