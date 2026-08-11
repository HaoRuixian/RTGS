"""Batch RTCM/Unicore stream to RINEX 3 observation conversion.

The real-time logger already contains the low-level RTCM decoder and RINEX
writer.  This module provides the offline, folder-oriented orchestration that
the GUI uses: files are scanned, observations are filtered, epochs are sampled,
and output files are rotated on a UTC time grid.
"""

from __future__ import annotations

import copy
import multiprocessing
import os
import threading
from concurrent.futures import FIRST_COMPLETED, CancelledError, ProcessPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable, Optional

from core.mixed_gnss_reader import MixedGNSSReader
from core.rinex3_writer import RINEX3Writer
from core.rtcm_handler import RTCMHandler
from utils.rtcm_to_rinex import (
    ScanSummary,
    _build_handler,
    _infer_reference_utc,
    _iter_merged_epochs,
    _normalize_utc_datetime,
    _utc_to_gps_file_datetime,
    scan_rtcm_file,
)


DEFAULT_EXTENSIONS = (".rtcm", ".rtcm3", ".dat", ".bin", ".ubx", ".log")
OBSERVATION_ATTRIBUTES = {
    "C": "pseudorange",
    "L": "phase",
    "D": "doppler",
    "S": "snr",
}
DEFAULT_SYSTEMS = ("G", "R", "E", "C")
METADATA_SCAN_STABLE_EPOCHS = 100
DEFAULT_MAX_WORKERS = max(1, min(16, (os.cpu_count() or 2) // 2))
CANCEL_CHECK_EPOCHS = 32


@dataclass(slots=True)
class BatchConversionOptions:
    """Configuration for :func:`convert_folder`.

    ``sample_interval_seconds=None`` keeps the source cadence detected during
    the scan.  ``split_seconds`` is aligned to UTC midnight for one-day files
    and to the 1980-01-06 UTC epoch for other durations.
    """

    input_dir: Path
    output_dir: Path
    recursive: bool = True
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS
    systems: tuple[str, ...] = DEFAULT_SYSTEMS
    observation_types: tuple[str, ...] = ("C", "L", "D", "S")
    split_seconds: float = 86_400.0
    sample_interval_seconds: Optional[float] = None
    station_code: str = "RTGS"
    receiver_number: str = "00"
    country_code: str = "CHN"
    marker_name: str = ""
    marker_number: str = "0"
    receiver_type: str = ""
    receiver_serial: str = ""
    receiver_version: str = ""
    antenna_type: str = "UNKNOWN"
    antenna_number: str = ""
    datatype: str = "MO"
    reference_utc: Optional[datetime] = None
    approx_position: Optional[tuple[float, float, float]] = None
    overwrite: bool = False
    max_workers: int = DEFAULT_MAX_WORKERS

    def __post_init__(self) -> None:
        self.input_dir = Path(self.input_dir).expanduser()
        self.output_dir = Path(self.output_dir).expanduser()
        raw_extensions = (self.extensions,) if isinstance(self.extensions, str) else self.extensions
        self.extensions = tuple(
            sorted({
                (str(ext).strip().lower() if str(ext).strip().startswith(".") else f".{str(ext).strip().lower()}")
                for ext in raw_extensions
                if str(ext).strip()
            })
        ) or DEFAULT_EXTENSIONS
        self.systems = tuple(dict.fromkeys(str(item).strip().upper()[:1] for item in self.systems if str(item).strip()))
        self.observation_types = tuple(
            dict.fromkeys(
                normalized
                for item in self.observation_types
                if (normalized := str(item).strip().upper()[:1]) in OBSERVATION_ATTRIBUTES
            )
        )
        if not self.systems:
            raise ValueError("At least one GNSS system must be selected")
        if not self.observation_types:
            raise ValueError("At least one observation type must be selected")
        self.split_seconds = float(self.split_seconds)
        if self.split_seconds <= 0:
            raise ValueError("split_seconds must be greater than zero")
        if self.sample_interval_seconds is not None:
            self.sample_interval_seconds = float(self.sample_interval_seconds)
            if self.sample_interval_seconds <= 0:
                raise ValueError("sample_interval_seconds must be greater than zero")
        self.max_workers = max(1, min(32, int(self.max_workers)))


@dataclass(slots=True)
class BatchFileResult:
    input_path: Path
    output_paths: list[Path] = field(default_factory=list)
    scanned_epochs: int = 0
    written_epochs: int = 0
    detected_interval_seconds: float = 0.0
    error: str = ""


@dataclass(slots=True)
class BatchConversionReport:
    files: list[BatchFileResult] = field(default_factory=list)
    cancelled: bool = False

    @property
    def succeeded_files(self) -> int:
        return sum(1 for item in self.files if not item.error)

    @property
    def failed_files(self) -> int:
        return sum(1 for item in self.files if item.error)

    @property
    def written_epochs(self) -> int:
        return sum(item.written_epochs for item in self.files)


ProgressCallback = Callable[[int, int, Path, BatchFileResult], None]
LogCallback = Callable[[str], None]


def find_input_files(
    input_dir: str | Path,
    *,
    recursive: bool = True,
    extensions: Iterable[str] = DEFAULT_EXTENSIONS,
) -> list[Path]:
    """Return supported files in deterministic path order."""

    root = Path(input_dir).expanduser()
    raw_extensions = (extensions,) if isinstance(extensions, str) else extensions
    suffixes = {
        (str(item).strip().lower() if str(item).strip().startswith(".") else f".{str(item).strip().lower()}")
        for item in raw_extensions
        if str(item).strip()
    }
    iterator = root.rglob("*") if recursive else root.glob("*")
    return sorted(path for path in iterator if path.is_file() and path.suffix.lower() in suffixes)


def _filtered_sys_obs_types(summary: ScanSummary, options: BatchConversionOptions) -> dict[str, list[str]]:
    selected_systems = set(options.systems)
    selected_prefixes = set(options.observation_types)
    return {
        system: [code for code in codes if code[:1].upper() in selected_prefixes]
        for system, codes in summary.sys_obs_types.items()
        if system.upper() in selected_systems
        and any(code[:1].upper() in selected_prefixes for code in codes)
    }


def filter_epoch(epoch: object, options: BatchConversionOptions) -> object | None:
    """Copy an epoch while retaining only selected systems and value kinds."""

    selected_systems = set(options.systems)
    selected_attributes = {OBSERVATION_ATTRIBUTES[key] for key in options.observation_types}
    filtered = copy.copy(epoch)
    filtered.satellites = {}

    for sat_id, satellite in (getattr(epoch, "satellites", {}) or {}).items():
        if not sat_id or sat_id[0].upper() not in selected_systems:
            continue
        satellite_copy = copy.copy(satellite)
        satellite_copy.signals = {}
        for signal_id, signal in (getattr(satellite, "signals", {}) or {}).items():
            signal_copy = copy.copy(signal)
            for attribute in OBSERVATION_ATTRIBUTES.values():
                if attribute not in selected_attributes:
                    setattr(signal_copy, attribute, None)
            if any(getattr(signal_copy, attribute, None) is not None for attribute in selected_attributes):
                satellite_copy.signals[signal_id] = signal_copy
        if satellite_copy.signals:
            filtered.satellites[sat_id] = satellite_copy
    return filtered if filtered.satellites else None


def _select_satellites(epoch: object, options: BatchConversionOptions) -> dict[str, object]:
    """Select satellites without copying the decoded observation objects."""

    selected_systems = set(options.systems)
    selected_attributes = {OBSERVATION_ATTRIBUTES[key] for key in options.observation_types}
    selected: dict[str, object] = {}
    for sat_id, satellite in (getattr(epoch, "satellites", {}) or {}).items():
        if not sat_id or sat_id[0].upper() not in selected_systems:
            continue
        signals = getattr(satellite, "signals", {}) or {}
        if any(
            getattr(signal, attribute, None) is not None
            for signal in signals.values()
            for attribute in selected_attributes
        ):
            selected[sat_id] = satellite
    return selected


def _segment_start(epoch_time: datetime, split_seconds: float) -> datetime:
    normalized = _normalize_utc_datetime(epoch_time)
    split_ms = max(1, int(round(split_seconds * 1000.0)))
    anchor = datetime(1980, 1, 6)
    elapsed_ms = int(round((normalized - anchor).total_seconds() * 1000.0))
    return anchor + timedelta(milliseconds=(elapsed_ms // split_ms) * split_ms)


def _available_output_path(path: Path, overwrite: bool) -> Path:
    if overwrite:
        return path
    for index in range(0, 10_000):
        candidate = path if index == 0 else path.with_name(f"{path.stem}_{index:02d}{path.suffix}")
        try:
            descriptor = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        else:
            os.close(descriptor)
            return candidate
    raise OSError(f"Unable to find an unused output filename for {path}")


def _make_writer(
    output_dir: Path,
    segment_start: datetime,
    summary: ScanSummary,
    options: BatchConversionOptions,
    sys_obs_types: dict[str, list[str]],
) -> RINEX3Writer:
    period = RINEX3Writer.format_period_code(options.split_seconds, fallback="01D")
    source_interval = max(0.001, float(summary.interval_seconds or 1.0))
    sample_interval = max(source_interval, float(options.sample_interval_seconds or source_interval))
    file_time = _utc_to_gps_file_datetime(segment_start)
    writer = RINEX3Writer(
        str(output_dir),
        marker_name=options.marker_name or options.station_code,
        marker_number=options.marker_number,
        station_code=options.station_code,
        receiver_number=options.receiver_number,
        country_code=options.country_code,
        period=period,
        interval=RINEX3Writer.format_interval_code(sample_interval),
        datatype=options.datatype,
        file_time=file_time,
        header_interval_seconds=sample_interval,
        antenna_number=options.antenna_number or summary.antenna_number,
        receiver_serial=options.receiver_serial or summary.receiver_serial,
        receiver_version=options.receiver_version or summary.receiver_version,
        flush_each_epoch=False,
    )
    writer.filename = str(_available_output_path(Path(writer.filename), options.overwrite))
    writer.output_directory = str(Path(writer.filename).parent)
    if not writer.open():
        raise OSError(f"Failed to open RINEX output file: {writer.filename}")

    position = options.approx_position or summary.approx_position
    if position is not None:
        writer.set_approx_position(position)
    if not writer.write_header(
        sys_obs_types=sys_obs_types,
        receiver_type=options.receiver_type or summary.receiver_type or "Generic",
        receiver_serial=options.receiver_serial or summary.receiver_serial,
        receiver_version=options.receiver_version or summary.receiver_version,
        antenna_type=options.antenna_type or summary.antenna_type or "UNKNOWN",
        antenna_number=options.antenna_number or summary.antenna_number,
    ):
        writer.close()
        raise OSError(f"Failed to write RINEX header: {writer.filename}")
    return writer


def convert_file(
    input_path: str | Path,
    options: BatchConversionOptions,
    *,
    reader_factory=None,
    handler_factory=None,
    cancel_event: Optional[threading.Event] = None,
    log_callback: Optional[LogCallback] = None,
) -> BatchFileResult:
    """Convert one input file, creating one RINEX file per time segment."""

    input_path = Path(input_path)
    result = BatchFileResult(input_path=input_path)
    reader_factory = reader_factory or MixedGNSSReader
    handler_factory = handler_factory or RTCMHandler
    reference_utc = options.reference_utc or _infer_reference_utc(input_path)
    writers: dict[datetime, RINEX3Writer] = {}
    try:
        summary = scan_rtcm_file(
            input_path,
            reference_utc=reference_utc,
            reader_factory=reader_factory,
            handler_factory=handler_factory,
            stop_when_stable=True,
            stable_epoch_threshold=METADATA_SCAN_STABLE_EPOCHS,
            require_approx_position=False,
        )
        result.scanned_epochs = summary.epoch_count
        result.detected_interval_seconds = summary.interval_seconds
        if summary.epoch_count == 0:
            raise ValueError("No observation epochs found")
        sys_obs_types = _filtered_sys_obs_types(summary, options)
        if not sys_obs_types:
            raise ValueError("Selected systems/observation types are not present in the file")
        source_interval = max(0.001, float(summary.interval_seconds or 1.0))
        requested_interval = options.sample_interval_seconds or source_interval
        # Decimation cannot create samples absent from the source.  Keep the
        # source cadence and the RINEX INTERVAL header truthful in that case.
        target_interval = max(source_interval, float(requested_interval))
        handler = _build_handler(handler_factory, reference_utc)
        last_output_time: Optional[datetime] = None
        sampling_anchor: Optional[datetime] = None

        with input_path.open("rb") as stream:
            for epoch_index, epoch in enumerate(_iter_merged_epochs(reader_factory(stream), handler)):
                if (
                    cancel_event is not None
                    and epoch_index % CANCEL_CHECK_EPOCHS == 0
                    and cancel_event.is_set()
                ):
                    break
                epoch_time = getattr(epoch, "utc_datetime", None)
                if epoch_time is None:
                    continue
                normalized_time = _normalize_utc_datetime(epoch_time)
                selected_satellites = _select_satellites(epoch, options)
                if not selected_satellites:
                    continue
                output_time = _utc_to_gps_file_datetime(normalized_time)
                if target_interval > source_interval + 1e-6:
                    if sampling_anchor is None:
                        sampling_anchor = normalized_time
                    elapsed = (normalized_time - sampling_anchor).total_seconds()
                    rounded_elapsed = round(elapsed / target_interval) * target_interval
                    tolerance = max(0.01, min(source_interval * 0.45, target_interval * 0.1))
                    if abs(elapsed - rounded_elapsed) > tolerance:
                        continue
                    output_time = _utc_to_gps_file_datetime(
                        sampling_anchor + timedelta(seconds=rounded_elapsed)
                    )
                    if output_time == last_output_time:
                        continue
                last_output_time = output_time
                segment = _segment_start(normalized_time, options.split_seconds)
                writer = writers.get(segment)
                if writer is None:
                    writer = _make_writer(options.output_dir, segment, summary, options, sys_obs_types)
                    writers[segment] = writer
                    result.output_paths.append(Path(writer.filename))
                    if log_callback:
                        log_callback(f"Output: {Path(writer.filename).name}")
                if writer.write_observation(output_time, selected_satellites):
                    result.written_epochs += 1
                else:
                    raise OSError(f"Failed to write epoch at {output_time.isoformat()}")
    except Exception as exc:
        result.error = str(exc)
        if log_callback:
            log_callback(f"Failed: {input_path.name}: {exc}")
    finally:
        for writer in writers.values():
            writer.close()
    return result


def _convert_file_in_process(
    path: Path,
    options: BatchConversionOptions,
    cancel_event,
) -> BatchFileResult:
    """Pickle-friendly process-pool entry point."""

    return convert_file(path, options, cancel_event=cancel_event)


def _convert_folder_parallel(
    paths: list[Path],
    options: BatchConversionOptions,
    *,
    cancel_event: Optional[threading.Event],
    progress_callback: Optional[ProgressCallback],
    log_callback: Optional[LogCallback],
) -> BatchConversionReport:
    report = BatchConversionReport()
    total = len(paths)
    context = multiprocessing.get_context("spawn")

    with context.Manager() as manager:
        process_cancel = manager.Event()
        with ProcessPoolExecutor(max_workers=options.max_workers, mp_context=context) as executor:
            futures = {
                executor.submit(_convert_file_in_process, path, options, process_cancel): path
                for path in paths
            }
            pending = set(futures)
            completed_count = 0
            while pending:
                if cancel_event is not None and cancel_event.is_set():
                    report.cancelled = True
                    process_cancel.set()
                    for future in pending:
                        future.cancel()

                done, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
                for future in done:
                    path = futures[future]
                    try:
                        item = future.result()
                    except CancelledError:
                        continue
                    except Exception as exc:
                        item = BatchFileResult(input_path=path, error=f"Worker process failed: {exc}")
                    report.files.append(item)
                    completed_count += 1
                    if log_callback:
                        state = f"failed: {item.error}" if item.error else f"{item.written_epochs} epochs"
                        log_callback(f"[{completed_count}/{total}] {path.name}: {state}")
                        for output_path in item.output_paths:
                            log_callback(f"Output: {output_path.name}")
                    if progress_callback:
                        progress_callback(completed_count, total, path, item)

    if cancel_event is not None and cancel_event.is_set():
        report.cancelled = True
    report.files.sort(key=lambda item: str(item.input_path))
    return report


def convert_folder(
    options: BatchConversionOptions,
    *,
    reader_factory=None,
    handler_factory=None,
    cancel_event: Optional[threading.Event] = None,
    progress_callback: Optional[ProgressCallback] = None,
    log_callback: Optional[LogCallback] = None,
) -> BatchConversionReport:
    """Convert all matching files in ``options.input_dir``."""

    if not options.input_dir.is_dir():
        raise NotADirectoryError(f"Input directory does not exist: {options.input_dir}")
    options.output_dir.mkdir(parents=True, exist_ok=True)
    paths = find_input_files(options.input_dir, recursive=options.recursive, extensions=options.extensions)
    report = BatchConversionReport()
    total = len(paths)
    if log_callback:
        log_callback(f"Found {total} input file(s)")
    use_processes = options.max_workers > 1 and reader_factory is None and handler_factory is None
    if use_processes and paths:
        if log_callback:
            log_callback(f"Using {min(options.max_workers, total)} worker process(es)")
        return _convert_folder_parallel(
            paths,
            options,
            cancel_event=cancel_event,
            progress_callback=progress_callback,
            log_callback=log_callback,
        )
    for index, path in enumerate(paths, start=1):
        if cancel_event is not None and cancel_event.is_set():
            report.cancelled = True
            break
        if log_callback:
            log_callback(f"[{index}/{total}] Processing {path.name}")
        item = convert_file(
            path,
            options,
            reader_factory=reader_factory,
            handler_factory=handler_factory,
            cancel_event=cancel_event,
            log_callback=log_callback,
        )
        report.files.append(item)
        if progress_callback:
            progress_callback(index, total, path, item)
    if cancel_event is not None and cancel_event.is_set():
        report.cancelled = True
    return report


__all__ = [
    "BatchConversionOptions",
    "BatchConversionReport",
    "BatchFileResult",
    "DEFAULT_EXTENSIONS",
    "DEFAULT_MAX_WORKERS",
    "convert_file",
    "convert_folder",
    "filter_epoch",
    "find_input_files",
]
