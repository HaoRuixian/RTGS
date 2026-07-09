"""Convert a GNSS observation stream file into a RINEX observation file."""

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
from core.gnss_time import GNSSTime
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
    """Metadata discovered during the GNSS stream scan pass."""

    input_path: Path
    epoch_count: int = 0
    first_epoch: Optional[datetime] = None
    last_epoch: Optional[datetime] = None
    interval_seconds: float = 1.0
    sys_obs_types: Dict[str, list[str]] = field(default_factory=dict)
    approx_position: Optional[list[float]] = None
    receiver_type: str = ""
    receiver_serial: str = ""
    receiver_version: str = ""
    antenna_type: str = ""
    antenna_number: str = ""


@dataclass
class ConversionResult:
    """Result for one GNSS-stream-to-RINEX conversion run."""

    output_path: Path
    summary: ScanSummary
    written_epoch_count: int = 0


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
    return normalized + timedelta(seconds=GNSSTime.LEAP_SECONDS)


def _convert_utc_to_time_system(epoch_time: datetime, time_system: str) -> datetime:
    normalized = _normalize_utc_datetime(epoch_time)
    system = str(time_system or "UTC").strip().upper() or "UTC"
    if system == "UTC":
        return normalized
    if system == "GPS":
        return normalized + timedelta(seconds=GNSSTime.LEAP_SECONDS)
    raise ValueError(f"Unsupported time system: {time_system}")


def _convert_time_system_to_utc(epoch_time: datetime, time_system: str) -> datetime:
    system = str(time_system or "UTC").strip().upper() or "UTC"
    if system == "UTC":
        return epoch_time
    if system == "GPS":
        return epoch_time - timedelta(seconds=GNSSTime.LEAP_SECONDS)
    raise ValueError(f"Unsupported time system: {time_system}")


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
    observation_codes_by_system: Dict[str, set[str]] = {}

    for epoch in epochs:
        for sat_id, sat_state in getattr(epoch, "satellites", {}).items():
            if not sat_id:
                continue

            system = sat_id[0].upper()
            for signal_id, signal_data in getattr(sat_state, "signals", {}).items():
                normalized = str(signal_id).strip().upper()
                if normalized:
                    known_codes = observation_codes_by_system.setdefault(system, set())
                    for prefix, attribute in (
                        ("C", "pseudorange"),
                        ("L", "phase"),
                        ("D", "doppler"),
                        ("S", "snr"),
                    ):
                        if getattr(signal_data, attribute, None) is not None:
                            known_codes.add(f"{prefix}{normalized}")

    return _build_sys_obs_types(observation_codes_by_system)


def _build_sys_obs_types(observation_codes_by_system: Dict[str, set[str]]) -> Dict[str, list[str]]:
    if not observation_codes_by_system:
        return _copy_default_sys_obs_types()

    sys_obs_types: Dict[str, list[str]] = {}
    for system in sorted(observation_codes_by_system.keys()):
        known_codes = observation_codes_by_system[system]
        obs_codes: list[str] = []
        signal_ids = sorted({code[1:] for code in known_codes if len(code) > 1})
        for signal_id in signal_ids:
            for prefix in ("C", "L", "D", "S"):
                code = f"{prefix}{signal_id}"
                if code in known_codes:
                    obs_codes.append(code)
        if obs_codes:
            sys_obs_types[system] = obs_codes

    return sys_obs_types or _copy_default_sys_obs_types()


def _round_epoch_time(epoch_time: datetime, interval_seconds: float) -> datetime:
    normalized = _normalize_utc_datetime(epoch_time)
    interval_ms = max(1, int(round(float(interval_seconds) * 1000.0)))
    anchor = datetime(1980, 1, 6)
    total_ms = int(round((normalized - anchor).total_seconds() * 1000.0))
    rounded_ms = round(total_ms / interval_ms) * interval_ms
    return anchor + timedelta(milliseconds=rounded_ms)


def _select_aligned_epoch_time(
    epoch_time: datetime,
    target_interval_seconds: float,
    *,
    alignment_time_system: str = "UTC",
    return_time_system: Optional[str] = None,
    tolerance_seconds: float = 0.01,
) -> datetime | None:
    alignment_epoch = _convert_utc_to_time_system(epoch_time, alignment_time_system)
    rounded = _round_epoch_time(alignment_epoch, target_interval_seconds)
    if abs((alignment_epoch - rounded).total_seconds()) > max(0.001, float(tolerance_seconds)):
        return None

    result_time_system = str(return_time_system or alignment_time_system).strip().upper() or alignment_time_system
    if result_time_system == str(alignment_time_system or "UTC").strip().upper():
        return rounded

    utc_time = _convert_time_system_to_utc(rounded, alignment_time_system)
    return _convert_utc_to_time_system(utc_time, result_time_system)


def _resolve_output_target(input_path: Path, output_path: Optional[Path]) -> Path:
    if output_path is None:
        return input_path.parent
    return output_path


def _build_handler(handler_factory, reference_utc: Optional[datetime]) -> RTCMHandler:
    factory = handler_factory or RTCMHandler

    try:
        return factory(reference_utc=reference_utc, compute_geometry=False)
    except TypeError:
        try:
            return factory(reference_utc=reference_utc)
        except TypeError:
            return factory()


def _infer_reference_utc(input_path: Path) -> Optional[datetime]:
    stem = input_path.stem

    match = re.search(r"(?<!\d)(20\d{2})(\d{3})(\d{2})(?!\d)", stem)
    if match:
        year = int(match.group(1))
        day_of_year = int(match.group(2))
        hour = int(match.group(3))
        try:
            return datetime(year, 1, 1, hour, tzinfo=timezone.utc) + timedelta(days=day_of_year - 1)
        except ValueError:
            pass

    match = re.search(r"(?<!\d)(20\d{2})(\d{3})(?!\d)", stem)
    if match:
        year = int(match.group(1))
        day_of_year = int(match.group(2))
        try:
            return datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=day_of_year - 1)
        except ValueError:
            pass

    match = re.search(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", stem)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            pass

    match = re.search(r"(?<!\d)(\d{2})(\d{2})(\d{2})(?!\d)", stem)
    if match:
        year = 2000 + int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        try:
            return datetime(year, month, day, tzinfo=timezone.utc)
        except ValueError:
            pass

    return None


def _clean_header_value(value: object) -> str:
    return " ".join(str(value or "").split())


def _update_summary_from_handler(summary: ScanSummary, handler: RTCMHandler) -> None:
    receiver_type = _clean_header_value(getattr(handler, "last_receiver_type_descriptor", ""))
    if receiver_type:
        summary.receiver_type = receiver_type

    receiver_serial = _clean_header_value(getattr(handler, "last_receiver_serial_number", ""))
    if receiver_serial:
        summary.receiver_serial = receiver_serial

    receiver_version = _clean_header_value(getattr(handler, "last_receiver_firmware_version", ""))
    if receiver_version:
        summary.receiver_version = receiver_version

    antenna_type = _clean_header_value(getattr(handler, "last_antenna_descriptor", ""))
    if antenna_type:
        summary.antenna_type = antenna_type

    antenna_number = _clean_header_value(getattr(handler, "last_antenna_serial_number", ""))
    if antenna_number:
        summary.antenna_number = antenna_number


def scan_rtcm_file(
    input_path: str | Path,
    *,
    reference_utc: Optional[datetime] = None,
    reader_factory=None,
    handler_factory=None,
    max_epochs: Optional[int] = None,
    stop_when_stable: bool = False,
    stable_epoch_threshold: int = 100,
    require_approx_position: bool = True,
) -> ScanSummary:
    """Scan a GNSS stream file to discover observation metadata before writing RINEX."""

    input_path = Path(input_path)
    reader_factory = reader_factory or MixedGNSSReader
    resolved_reference_utc = reference_utc or _infer_reference_utc(input_path)
    handler = _build_handler(handler_factory, resolved_reference_utc)
    summary = ScanSummary(input_path=input_path)
    previous_epoch_ms: Optional[int] = None
    delta_counter: Counter[int] = Counter()
    reasonable_delta_counter: Counter[int] = Counter()
    observation_codes_by_system: Dict[str, set[str]] = {}
    stable_epoch_count = 0

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
                    if delta_ms <= 600_000:
                        reasonable_delta_counter[delta_ms] += 1
            previous_epoch_ms = epoch_ms

            signal_changed = False
            for sat_id, sat_state in getattr(epoch, "satellites", {}).items():
                if not sat_id:
                    continue
                system = sat_id[0].upper()
                for signal_id, signal_data in getattr(sat_state, "signals", {}).items():
                    normalized_signal = str(signal_id).strip().upper()
                    if normalized_signal:
                        known_codes = observation_codes_by_system.setdefault(system, set())
                        for prefix, attribute in (
                            ("C", "pseudorange"),
                            ("L", "phase"),
                            ("D", "doppler"),
                            ("S", "snr"),
                        ):
                            if getattr(signal_data, attribute, None) is None:
                                continue
                            observation_code = f"{prefix}{normalized_signal}"
                            if observation_code not in known_codes:
                                known_codes.add(observation_code)
                                signal_changed = True

            approx_position = getattr(handler, "last_station_coords", None)
            if approx_position:
                try:
                    summary.approx_position = [float(value) for value in approx_position[:3]]
                except (TypeError, ValueError):
                    summary.approx_position = None
            _update_summary_from_handler(summary, handler)

            if signal_changed:
                stable_epoch_count = 0
            else:
                stable_epoch_count += 1

            if max_epochs is not None and summary.epoch_count >= max(1, int(max_epochs)):
                break

            if stop_when_stable:
                has_position = (summary.approx_position is not None) or (not require_approx_position)
                if (
                    summary.epoch_count >= max(10, int(stable_epoch_threshold))
                    and stable_epoch_count >= max(1, int(stable_epoch_threshold))
                    and has_position
                ):
                    break

    _update_summary_from_handler(summary, handler)
    summary.sys_obs_types = _build_sys_obs_types(observation_codes_by_system)

    selected_counter = reasonable_delta_counter or delta_counter
    if selected_counter:
        most_common_delta_ms, _ = selected_counter.most_common(1)[0]
        summary.interval_seconds = max(0.001, most_common_delta_ms / 1000.0)

    if summary.epoch_count > 1 and summary.first_epoch is not None and summary.last_epoch is not None:
        span_seconds = max(0.0, (summary.last_epoch - summary.first_epoch).total_seconds())
        average_interval = span_seconds / max(1, summary.epoch_count - 1)
        if 0.0 < average_interval <= 600.0 and summary.interval_seconds > 600.0:
            summary.interval_seconds = average_interval

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
    receiver_type: Optional[str] = None,
    receiver_serial: str = "",
    receiver_version: str = "",
    antenna_type: str = "UNKNOWN",
    antenna_number: str = "",
    datatype: str = "MO",
    interval_seconds: Optional[float] = None,
    period_code: Optional[str] = None,
    approx_position: Optional[Iterable[float]] = None,
    reference_utc: Optional[datetime] = None,
    reader_factory=None,
    handler_factory=None,
    summary: Optional[ScanSummary] = None,
) -> ConversionResult:
    """Convert one RTCM file into a RINEX observation file.

    When ``interval_seconds`` is larger than the detected source cadence, only epochs
    aligned to that interval are written so the output file is truly decimated.
    """

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
        raise ValueError(f"No observation epochs found in GNSS stream file: {input_path}")

    target_interval_seconds = float(interval_seconds or summary.interval_seconds or 1.0)
    target_interval_seconds = max(0.001, target_interval_seconds)
    source_interval_seconds = max(0.001, float(summary.interval_seconds or target_interval_seconds))
    summary.interval_seconds = target_interval_seconds

    effective_first_epoch = summary.first_epoch or _normalize_utc_datetime(datetime.utcnow())
    effective_last_epoch = summary.last_epoch or effective_first_epoch
    file_span_seconds = max(
        target_interval_seconds,
        (effective_last_epoch - effective_first_epoch).total_seconds() + target_interval_seconds,
    )
    effective_period_code = period_code or RINEX3Writer.format_period_code(file_span_seconds, fallback="01D")
    daily_file_start_time_utc: Optional[datetime] = None
    if effective_period_code == "01D" and resolved_reference_utc is not None:
        daily_file_start_time_utc = _normalize_utc_datetime(resolved_reference_utc)
    writer_file_time = _utc_to_gps_file_datetime(daily_file_start_time_utc or effective_first_epoch)

    effective_receiver_type = _clean_header_value(receiver_type) or summary.receiver_type or "Generic"
    effective_receiver_serial = _clean_header_value(receiver_serial) or summary.receiver_serial
    effective_receiver_version = _clean_header_value(receiver_version) or summary.receiver_version
    effective_antenna_type = _clean_header_value(antenna_type)
    if not effective_antenna_type or effective_antenna_type.upper() == "UNKNOWN":
        effective_antenna_type = summary.antenna_type or "UNKNOWN"
    effective_antenna_number = _clean_header_value(antenna_number) or summary.antenna_number

    writer = RINEX3Writer(
        str(output_target),
        marker_name=marker_name or station_code,
        marker_number=marker_number,
        station_code=station_code,
        receiver_number=receiver_number,
        country_code=country_code,
        period=effective_period_code,
        interval=RINEX3Writer.format_interval_code(target_interval_seconds),
        datatype=datatype,
        file_time=writer_file_time,
        header_interval_seconds=target_interval_seconds,
        antenna_number=effective_antenna_number,
        receiver_serial=effective_receiver_serial,
        receiver_version=effective_receiver_version,
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
            receiver_type=effective_receiver_type,
            receiver_serial=effective_receiver_serial,
            receiver_version=effective_receiver_version,
            antenna_type=effective_antenna_type,
            antenna_number=effective_antenna_number,
        ):
            raise OSError(f"Failed to write RINEX header: {writer.filename}")

        handler = _build_handler(handler_factory, resolved_reference_utc)
        last_written_time: Optional[datetime] = None
        written_epoch_count = 0
        with input_path.open("rb") as stream:
            reader = reader_factory(stream)
            for epoch in _iter_merged_epochs(reader, handler):
                epoch_time = getattr(epoch, "utc_datetime", None)
                if epoch_time is None:
                    continue
                normalized_time = _normalize_utc_datetime(epoch_time)

                if daily_file_start_time_utc is not None:
                    daily_file_end_time_utc = daily_file_start_time_utc + timedelta(days=1)
                    if normalized_time < daily_file_start_time_utc or normalized_time >= daily_file_end_time_utc:
                        continue

                output_time = _utc_to_gps_file_datetime(normalized_time)

                if target_interval_seconds > source_interval_seconds + 1e-6:
                    selected_time = _select_aligned_epoch_time(
                        normalized_time,
                        target_interval_seconds,
                        alignment_time_system="GPS",
                        return_time_system="GPS",
                    )
                    if selected_time is None:
                        continue
                    if last_written_time is not None and selected_time == last_written_time:
                        continue
                    output_time = selected_time

                if not writer.write_observation(output_time, getattr(epoch, "satellites", {})):
                    raise OSError(f"Failed to write RINEX observation epoch at {output_time.isoformat()}")
                last_written_time = output_time
                written_epoch_count += 1
    finally:
        writer.close()

    return ConversionResult(
        output_path=Path(writer.filename),
        summary=summary,
        written_epoch_count=written_epoch_count,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    prog_name = Path(sys.argv[0]).stem or "rtcm_to_rinex"
    parser = argparse.ArgumentParser(
        prog=prog_name,
        description="Convert RTCM/Unicore observation data to a RINEX 3 observation file.",
        formatter_class=argparse.RawTextHelpFormatter,
        usage=(
            f"{prog_name} <input.rtcm3/dat> [-o OUT] [-i SEC] [-d YYYY-MM-DD] "
            "[-s SITE] [-n NAME] [-r RX]"
        ),
        epilog=(
            "Examples:\n"
            f"  {prog_name} sample.rtcm3 -o output\n"
            f"  {prog_name} 20251025.dat -o output\\20251025.rnx -d 2025-10-25\n"
            f"  {prog_name} sample.rtcm3 -o output -s F9P0 -n F9P -r F9P\n"
            f"  {prog_name} sample.rtcm3 -o output -i 15 -p 01D\n"
        ),
    )
    parser.add_argument("input", type=Path, help="Input RTCM/Unicore stream file.")

    common = parser.add_argument_group("common options")
    advanced = parser.add_argument_group("advanced options")

    common.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output .rnx file path or output directory. Default: input file directory.",
    )
    common.add_argument("-s", "--site", dest="station_code", default="RTGS", help="Station code in the long filename.")
    common.add_argument("-n", "--name", dest="marker_name", default=None, help="Marker name written to the header.")
    common.add_argument("-r", "--rx", dest="receiver_type", default=None, help="Receiver type written to the header.")
    common.add_argument("--rx-serial", dest="receiver_serial", default="", help="Receiver serial number for the header.")
    common.add_argument("--rx-version", dest="receiver_version", default="", help="Receiver firmware/version for the header.")
    common.add_argument("-a", "--ant", dest="antenna_type", default="UNKNOWN", help="Antenna type written to the header.")
    common.add_argument(
        "--ant-num",
        "--antenna-number",
        dest="antenna_number",
        default="",
        help="Antenna serial number for the header.",
    )
    common.add_argument(
        "-i",
        "--interval",
        type=float,
        default=None,
        help="Output sampling interval in seconds, for example 1 or 15.",
    )
    common.add_argument(
        "-p",
        "--period",
        default=None,
        help="Override the long-filename period code, for example 01H or 01D.",
    )
    common.add_argument(
        "-d",
        "--date",
        dest="reference_date",
        default=None,
        help="Reference UTC date in YYYY-MM-DD for offline files.",
    )
    common.add_argument(
        "--xyz",
        dest="approx_position",
        nargs=3,
        type=float,
        metavar=("X", "Y", "Z"),
        default=None,
        help="Approximate receiver ECEF position in meters for the header.",
    )
    advanced.add_argument("--num", dest="receiver_number", default="00", help="Receiver number in the long filename.")
    advanced.add_argument("--country", dest="country_code", default="CHN", help="Country code in the long filename.")

    parser.add_argument("--station-code", dest="station_code", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    parser.add_argument("--receiver-number", dest="receiver_number", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    parser.add_argument("--country-code", dest="country_code", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    parser.add_argument("--marker-name", dest="marker_name", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    parser.add_argument("--marker-number", dest="marker_number", default="0", help=argparse.SUPPRESS)
    parser.add_argument("--receiver-type", dest="receiver_type", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    parser.add_argument("--receiver-serial", dest="receiver_serial", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    parser.add_argument("--receiver-version", dest="receiver_version", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    parser.add_argument("--antenna-type", dest="antenna_type", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    parser.add_argument("--datatype", dest="datatype", default="MO", help=argparse.SUPPRESS)
    parser.add_argument("--approx-position", dest="approx_position", nargs=3, type=float, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    parser.add_argument("--reference-date", dest="reference_date", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    input_path = args.input.resolve()
    if not input_path.is_file():
        parser.error(f"Input GNSS stream file does not exist: {input_path}")

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
            receiver_serial=args.receiver_serial,
            receiver_version=args.receiver_version,
            antenna_type=args.antenna_type,
            antenna_number=args.antenna_number,
            datatype=args.datatype,
            interval_seconds=args.interval,
            period_code=args.period,
            approx_position=args.approx_position,
            reference_utc=reference_utc,
        )
    except Exception as exc:
        print(f"GNSS stream to RINEX conversion failed: {exc}", file=sys.stderr)
        return 1

    print(f"Converted GNSS stream to RINEX: {result.output_path}")
    print(f"Epochs written: {result.written_epoch_count}")
    print(f"Interval: {result.summary.interval_seconds:g}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
