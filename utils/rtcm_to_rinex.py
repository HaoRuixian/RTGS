"""Convert an RTCM file into a RINEX observation file from the command line."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, Iterator, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.pyrtcm_compat import patch_pyrtcm_glonass_g3

patch_pyrtcm_glonass_g3()

from core.data_models import EpochObservation
from core.mixed_gnss_reader import MixedGNSSReader
from core.rinex3_writer import RINEX3Writer
from core.rtcm_handler import RTCMHandler


DEFAULT_SYS_OBS_TYPES = {
    "G": ["C1C", "L1C", "D1C", "S1C"],
    "R": ["C4A", "L4A", "D4A", "S4A"],
    "E": ["C1C", "L1C", "D1C", "S1C"],
    "C": ["C2D", "L2D", "D2D", "S2D"],
    "J": ["C1C", "L1C", "D1C", "S1C"],
    "S": ["C1C", "L1C", "D1C", "S1C"],
    "I": ["C5A", "L5A", "D5A", "S5A"],
}


@dataclass
class ScanSummary:
    """Metadata discovered during the RTCM scan pass."""

    input_path: Path
    epoch_count: int = 0
    first_epoch: Optional[datetime] = None
    last_epoch: Optional[datetime] = None
    interval_seconds: float = 1.0
    sys_obs_types: Dict[str, list[str]] = field(default_factory=dict)
    approx_position: Optional[list[float]] = None


@dataclass
class ConversionResult:
    """Result for one RTCM-to-RINEX conversion run."""

    output_path: Path
    summary: ScanSummary


def _copy_default_sys_obs_types() -> Dict[str, list[str]]:
    return {system: list(obs_types) for system, obs_types in DEFAULT_SYS_OBS_TYPES.items()}


def _normalize_utc_datetime(epoch_time: datetime) -> datetime:
    if epoch_time.tzinfo is None:
        return epoch_time
    return epoch_time.astimezone(timezone.utc).replace(tzinfo=None)


def _utc_to_gps_file_datetime(epoch_time: datetime) -> datetime:
    """Convert an internal UTC epoch to the GPS-like timescale used in the RINEX file."""
    normalized = epoch_time
    if normalized.tzinfo is not None:
        normalized = normalized.astimezone(timezone.utc).replace(tzinfo=None)
    return normalized + timedelta(seconds=18)


def _epoch_key_millis(epoch: EpochObservation) -> int:
    epoch_time = getattr(epoch, "utc_datetime", None)
    if epoch_time is not None:
        if epoch_time.tzinfo is None:
            epoch_time = epoch_time.replace(tzinfo=timezone.utc)
        else:
            epoch_time = epoch_time.astimezone(timezone.utc)
        return int(round(epoch_time.timestamp() * 1000.0))
    return int(round(float(getattr(epoch, "gps_time", 0.0)) * 1000.0))


def _merge_epoch_data(target: EpochObservation, source: EpochObservation) -> EpochObservation:
    if target.utc_datetime is None and source.utc_datetime is not None:
        target.utc_datetime = source.utc_datetime

    for sat_id, sat_state in getattr(source, "satellites", {}).items():
        target.satellites[sat_id] = sat_state

    target.ionospheric_corrections.update(getattr(source, "ionospheric_corrections", {}))
    target.satellite_bias_corrections.update(getattr(source, "satellite_bias_corrections", {}))
    target.satellite_clock_corrections.update(getattr(source, "satellite_clock_corrections", {}))
    target.broadcast_eph_corrections.update(getattr(source, "broadcast_eph_corrections", {}))

    if getattr(target, "tropospheric_correction", None) is None:
        target.tropospheric_correction = getattr(source, "tropospheric_correction", None)

    for attr in (
        "gps_glonass_time_bias",
        "gps_galileo_time_bias",
        "gps_bds_time_bias",
    ):
        if getattr(target, attr, None) is None:
            setattr(target, attr, getattr(source, attr, None))

    return target


def _iter_merged_epochs(messages: Iterable[tuple[bytes | None, object]], handler: RTCMHandler) -> Iterator[EpochObservation]:
    current_epoch: Optional[EpochObservation] = None
    current_key: Optional[int] = None

    for _raw, msg in messages:
        if msg is None:
            continue

        epoch_data = handler.process_message(msg)
        if epoch_data is None:
            continue

        epoch_key = _epoch_key_millis(epoch_data)
        if current_epoch is None:
            current_epoch = epoch_data
            current_key = epoch_key
            continue

        if epoch_key == current_key:
            _merge_epoch_data(current_epoch, epoch_data)
            continue

        yield current_epoch
        current_epoch = epoch_data
        current_key = epoch_key

    if current_epoch is not None:
        yield current_epoch


def _detect_sys_obs_types(epochs: Iterable[EpochObservation]) -> Dict[str, list[str]]:
    signal_ids_by_system: Dict[str, set[str]] = {}

    for epoch in epochs:
        for sat_id, sat_state in getattr(epoch, "satellites", {}).items():
            if not sat_id:
                continue

            system = sat_id[0].upper()
            for signal_id in getattr(sat_state, "signals", {}).keys():
                normalized = str(signal_id).strip().upper()
                if normalized:
                    signal_ids_by_system.setdefault(system, set()).add(normalized)

    return _build_sys_obs_types(signal_ids_by_system)


def _build_sys_obs_types(signal_ids_by_system: Dict[str, set[str]]) -> Dict[str, list[str]]:
    if not signal_ids_by_system:
        return _copy_default_sys_obs_types()

    sys_obs_types: Dict[str, list[str]] = {}
    for system in sorted(signal_ids_by_system.keys()):
        obs_codes: list[str] = []
        for signal_id in sorted(signal_ids_by_system[system]):
            obs_codes.extend(
                [
                    f"C{signal_id}",
                    f"L{signal_id}",
                    f"D{signal_id}",
                    f"S{signal_id}",
                ]
            )
        if obs_codes:
            sys_obs_types[system] = obs_codes

    return sys_obs_types or _copy_default_sys_obs_types()


def _resolve_output_target(input_path: Path, output_path: Optional[Path]) -> Path:
    if output_path is None:
        return input_path.parent
    return output_path


def _build_handler(handler_factory, reference_utc: Optional[datetime]) -> RTCMHandler:
    factory = handler_factory or RTCMHandler

    try:
        return factory(reference_utc=reference_utc)
    except TypeError:
        return factory()


def _infer_reference_utc(input_path: Path) -> Optional[datetime]:
    stem = input_path.stem

    match = re.search(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", stem)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            return None

    return None


def scan_rtcm_file(
    input_path: str | Path,
    *,
    reference_utc: Optional[datetime] = None,
    reader_factory=None,
    handler_factory=None,
) -> ScanSummary:
    """Scan an RTCM file to discover observation metadata before writing RINEX."""

    input_path = Path(input_path)
    reader_factory = reader_factory or MixedGNSSReader
    resolved_reference_utc = reference_utc or _infer_reference_utc(input_path)
    handler = _build_handler(handler_factory, resolved_reference_utc)
    summary = ScanSummary(input_path=input_path)
    previous_epoch_ms: Optional[int] = None
    delta_counter: Counter[int] = Counter()
    signal_ids_by_system: Dict[str, set[str]] = {}

    with input_path.open("rb") as stream:
        reader = reader_factory(stream)
        for epoch in _iter_merged_epochs(reader, handler):
            summary.epoch_count += 1

            epoch_time = getattr(epoch, "utc_datetime", None)
            if epoch_time is not None:
                normalized_time = _normalize_utc_datetime(epoch_time)
                if summary.first_epoch is None or normalized_time < summary.first_epoch:
                    summary.first_epoch = normalized_time
                if summary.last_epoch is None or normalized_time > summary.last_epoch:
                    summary.last_epoch = normalized_time

            epoch_ms = _epoch_key_millis(epoch)
            if previous_epoch_ms is not None:
                delta_ms = epoch_ms - previous_epoch_ms
                if delta_ms > 0:
                    delta_counter[delta_ms] += 1
            previous_epoch_ms = epoch_ms

            for sat_id, sat_state in getattr(epoch, "satellites", {}).items():
                if not sat_id:
                    continue
                system = sat_id[0].upper()
                for signal_id in getattr(sat_state, "signals", {}).keys():
                    normalized_signal = str(signal_id).strip().upper()
                    if normalized_signal:
                        signal_ids_by_system.setdefault(system, set()).add(normalized_signal)

    summary.sys_obs_types = _build_sys_obs_types(signal_ids_by_system)

    if delta_counter:
        most_common_delta_ms, _ = delta_counter.most_common(1)[0]
        summary.interval_seconds = max(0.001, most_common_delta_ms / 1000.0)

    approx_position = getattr(handler, "last_station_coords", None)
    if approx_position:
        try:
            summary.approx_position = [float(value) for value in approx_position[:3]]
        except (TypeError, ValueError):
            summary.approx_position = None

    return summary


def convert_rtcm_file_to_rinex(
    input_path: str | Path,
    output_path: str | Path | None = None,
    *,
    station_code: str = "RTGS",
    receiver_number: str = "00",
    country_code: str = "CHN",
    marker_name: Optional[str] = None,
    marker_number: str = "0",
    receiver_type: str = "Generic",
    antenna_type: str = "UNKNOWN",
    datatype: str = "MO",
    interval_seconds: Optional[float] = None,
    period_code: Optional[str] = None,
    approx_position: Optional[Iterable[float]] = None,
    reference_utc: Optional[datetime] = None,
    reader_factory=None,
    handler_factory=None,
    summary: Optional[ScanSummary] = None,
) -> ConversionResult:
    """Convert one RTCM file into a RINEX observation file."""

    input_path = Path(input_path)
    output_target = _resolve_output_target(input_path, Path(output_path) if output_path is not None else None)
    reader_factory = reader_factory or MixedGNSSReader
    resolved_reference_utc = reference_utc or _infer_reference_utc(input_path)

    if summary is None:
        summary = scan_rtcm_file(
            input_path,
            reference_utc=resolved_reference_utc,
            reader_factory=reader_factory,
            handler_factory=handler_factory,
        )

    if summary.epoch_count == 0:
        raise ValueError(f"No observation epochs found in RTCM file: {input_path}")

    interval_seconds = float(interval_seconds or summary.interval_seconds or 1.0)
    interval_seconds = max(0.001, interval_seconds)
    summary.interval_seconds = interval_seconds

    effective_first_epoch = summary.first_epoch or _normalize_utc_datetime(datetime.utcnow())
    effective_last_epoch = summary.last_epoch or effective_first_epoch
    file_span_seconds = max(
        interval_seconds,
        (effective_last_epoch - effective_first_epoch).total_seconds() + interval_seconds,
    )
    effective_period_code = period_code or RINEX3Writer.format_period_code(file_span_seconds, fallback="01D")

    writer = RINEX3Writer(
        str(output_target),
        marker_name=marker_name or station_code,
        marker_number=marker_number,
        station_code=station_code,
        receiver_number=receiver_number,
        country_code=country_code,
        period=effective_period_code,
        interval=RINEX3Writer.format_interval_code(interval_seconds),
        datatype=datatype,
        file_time=_utc_to_gps_file_datetime(effective_first_epoch),
    )

    if not writer.open():
        raise OSError(f"Failed to open RINEX output file: {writer.filename}")

    effective_position = approx_position if approx_position is not None else summary.approx_position
    if effective_position is not None:
        summary.approx_position = [float(value) for value in effective_position]
        writer.set_approx_position(summary.approx_position)

    try:
        if not writer.write_header(
            sys_obs_types=summary.sys_obs_types,
            receiver_type=receiver_type,
            antenna_type=antenna_type,
        ):
            raise OSError(f"Failed to write RINEX header: {writer.filename}")

        handler = _build_handler(handler_factory, resolved_reference_utc)
        with input_path.open("rb") as stream:
            reader = reader_factory(stream)
            for epoch in _iter_merged_epochs(reader, handler):
                epoch_time = getattr(epoch, "utc_datetime", None)
                if epoch_time is None:
                    continue
                normalized_time = _normalize_utc_datetime(epoch_time)
                rinex_epoch_time = _utc_to_gps_file_datetime(normalized_time)
                if not writer.write_observation(rinex_epoch_time, getattr(epoch, "satellites", {})):
                    raise OSError(f"Failed to write RINEX observation epoch at {rinex_epoch_time.isoformat()}")
    finally:
        writer.close()

    return ConversionResult(output_path=Path(writer.filename), summary=summary)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert an RTCM binary file into a RINEX observation file.",
    )
    parser.add_argument("input", type=Path, help="Input RTCM file path.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output .rnx file path or output directory. Defaults to the input file directory.",
    )
    parser.add_argument("--station-code", default="RTGS", help="4-character station code for the RINEX long filename.")
    parser.add_argument("--receiver-number", default="00", help="2-character receiver number for the RINEX long filename.")
    parser.add_argument("--country-code", default="CHN", help="3-character country code for the RINEX long filename.")
    parser.add_argument("--marker-name", default=None, help="Marker name to write into the RINEX header.")
    parser.add_argument("--marker-number", default="0", help="Marker number to write into the RINEX header.")
    parser.add_argument("--receiver-type", default="Generic", help="Receiver type string for the RINEX header.")
    parser.add_argument("--antenna-type", default="UNKNOWN", help="Antenna type string for the RINEX header.")
    parser.add_argument("--datatype", default="MO", help="RINEX datatype code, for example MO.")
    parser.add_argument(
        "--interval",
        type=float,
        default=None,
        help="Sampling interval in seconds. Defaults to the most common epoch delta detected from the file.",
    )
    parser.add_argument(
        "--period",
        default=None,
        help="Override the RINEX long-filename period code, for example 01H or 01D.",
    )
    parser.add_argument(
        "--approx-position",
        nargs=3,
        type=float,
        metavar=("X", "Y", "Z"),
        default=None,
        help="Approximate receiver ECEF position in meters for the RINEX header.",
    )
    parser.add_argument(
        "--reference-date",
        default=None,
        help="Reference UTC date in YYYY-MM-DD format for offline epoch week inference. Defaults to a YYYYMMDD date found in the input filename when available.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    input_path = args.input.resolve()
    if not input_path.is_file():
        parser.error(f"Input RTCM file does not exist: {input_path}")

    reference_utc = None
    if args.reference_date:
        try:
            reference_utc = datetime.strptime(args.reference_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            parser.error(f"Invalid --reference-date value: {args.reference_date}. Expected YYYY-MM-DD.")

    try:
        result = convert_rtcm_file_to_rinex(
            input_path,
            output_path=args.output.resolve() if args.output is not None else None,
            station_code=args.station_code,
            receiver_number=args.receiver_number,
            country_code=args.country_code,
            marker_name=args.marker_name,
            marker_number=args.marker_number,
            receiver_type=args.receiver_type,
            antenna_type=args.antenna_type,
            datatype=args.datatype,
            interval_seconds=args.interval,
            period_code=args.period,
            approx_position=args.approx_position,
            reference_utc=reference_utc,
        )
    except Exception as exc:
        print(f"RTCM to RINEX conversion failed: {exc}", file=sys.stderr)
        return 1

    print(f"Converted RTCM to RINEX: {result.output_path}")
    print(f"Epochs written: {result.summary.epoch_count}")
    print(f"Interval: {result.summary.interval_seconds:g}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
