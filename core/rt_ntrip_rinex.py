"""Config-driven RT NTRIP-to-RINEX service for multiple stations."""

from __future__ import annotations

import base64
import socket
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import yaml

from core.data_models import EpochObservation
from core.gnss_time import GNSSTime
from core.mixed_gnss_reader import MixedGNSSReader
from core.rinex3_writer import RINEX3Writer

try:
    from core.pyrtcm_compat import patch_pyrtcm_glonass_g3

    patch_pyrtcm_glonass_g3()
except Exception:
    pass

try:
    from pyrtcm import RTCMReader
except Exception:  # pragma: no cover - exercised only when pyrtcm is absent
    RTCMReader = None


DEFAULT_SYS_OBS_TYPES = {
    "G": ["C1C", "L1C", "D1C", "S1C"],
    "R": ["C4A", "L4A", "D4A", "S4A"],
    "E": ["C1C", "L1C", "D1C", "S1C"],
    "C": ["C2D", "L2D", "D2D", "S2D"],
    "J": ["C1C", "L1C", "D1C", "S1C"],
    "S": ["C1C", "L1C", "D1C", "S1C"],
    "I": ["C5A", "L5A", "D5A", "S5A"],
}

SUPPORTED_TIME_SYSTEMS = {"GPS", "UTC"}


@dataclass(slots=True)
class NtripSourceConfig:
    host: str
    port: int
    mountpoint: str
    user: str = ""
    password: str = ""
    user_agent: str = "NTRIP RTGS RTRINEX/0.1"
    connect_timeout_seconds: float = 15.0
    reconnect_delay_seconds: float = 5.0


@dataclass(slots=True)
class RinexStationConfig:
    output_directory: Path
    marker_name: str = "UNKNOWN"
    marker_number: str = "0"
    station_code: str = "RTGS"
    receiver_number: str = "00"
    country_code: str = "CHN"
    receiver_type: str = "UNKNOWN"
    antenna_type: str = "UNKNOWN"
    antenna_model: str = ""
    antenna_number: str = ""
    datatype: str = "MO"
    filename_template: Optional[str] = None
    sample_interval_seconds: Optional[int] = None
    split_enabled: bool = True
    split_period_seconds: Optional[int] = 3600
    daily_merge_min_interval_seconds: int = 15
    time_system: str = "GPS"
    approx_position: Optional[List[float]] = None
    auto_detect_obs_types: bool = True
    sys_obs_types: Dict[str, List[str]] = field(default_factory=dict)
    align_tolerance_seconds: float = 0.001


@dataclass(slots=True)
class RTStationConfig:
    name: str
    enabled: bool
    ntrip: NtripSourceConfig
    rinex: RinexStationConfig


@dataclass(slots=True)
class MultiStationRTRinexConfig:
    config_path: Path
    stations: List[RTStationConfig]


def _copy_default_sys_obs_types() -> Dict[str, List[str]]:
    return {system: list(obs_types) for system, obs_types in DEFAULT_SYS_OBS_TYPES.items()}


def _deep_merge(base: dict, overrides: dict) -> dict:
    result = dict(base or {})
    for key, value in (overrides or {}).items():
        current = result.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            result[key] = _deep_merge(current, value)
        else:
            result[key] = value
    return result


def _normalize_sys_obs_types(raw: Optional[dict]) -> Dict[str, List[str]]:
    cleaned: Dict[str, List[str]] = {}
    for system, codes in (raw or {}).items():
        if not system:
            continue
        key = str(system)[0].upper()
        normalized_codes: List[str] = []
        for code in codes or []:
            obs_code = str(code).strip().upper()
            if obs_code:
                normalized_codes.append(obs_code)
        if normalized_codes:
            cleaned[key] = normalized_codes
    return cleaned


def _detect_sys_obs_types_from_satellites(satellites: Optional[dict]) -> Dict[str, List[str]]:
    signal_ids_by_system: Dict[str, set[str]] = {}
    for sat_id, sat_state in (satellites or {}).items():
        if not sat_id:
            continue
        system = str(sat_id)[0].upper()
        for signal_id in getattr(sat_state, "signals", {}).keys():
            normalized = str(signal_id).strip().upper()
            if normalized:
                signal_ids_by_system.setdefault(system, set()).add(normalized)

    if not signal_ids_by_system:
        return _copy_default_sys_obs_types()

    sys_obs_types: Dict[str, List[str]] = {}
    for system in sorted(signal_ids_by_system.keys()):
        obs_codes: List[str] = []
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


def _merge_sys_obs_types(primary: Dict[str, List[str]], secondary: Dict[str, List[str]]) -> Dict[str, List[str]]:
    merged: Dict[str, List[str]] = {}
    systems = sorted(set(primary.keys()) | set(secondary.keys()))
    for system in systems:
        seen: set[str] = set()
        ordered_codes: List[str] = []
        for source in (primary.get(system, []), secondary.get(system, [])):
            for code in source:
                normalized = str(code).strip().upper()
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    ordered_codes.append(normalized)
        if ordered_codes:
            merged[system] = ordered_codes
    return merged or _copy_default_sys_obs_types()


def _parse_int(value: object, *, field_name: str, min_value: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if parsed < min_value:
        raise ValueError(f"{field_name} must be >= {min_value}")
    return parsed


def _parse_optional_int(
    value: object,
    *,
    field_name: str,
    min_value: int = 1,
    auto_tokens: Iterable[str] = ("", "auto", "detect", "none", "off"),
) -> Optional[int]:
    if value is None:
        return None

    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in set(auto_tokens):
            return None

    return _parse_int(value, field_name=field_name, min_value=min_value)


def _parse_float(value: object, *, field_name: str, min_value: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc
    if parsed < min_value:
        raise ValueError(f"{field_name} must be >= {min_value}")
    return parsed


def _parse_position(value: object, *, field_name: str) -> Optional[List[float]]:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        raise ValueError(f"{field_name} must be a list like [x, y, z]")
    try:
        return [float(value[0]), float(value[1]), float(value[2])]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must contain numeric XYZ values") from exc


def _resolve_path(path_text: object, *, config_dir: Path, field_name: str) -> Path:
    text = str(path_text or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    if text.startswith("/"):
        return Path(text)
    path = Path(text)
    if not path.is_absolute():
        path = (config_dir / path).resolve()
    return path


def _normalize_ntrip_user_agent(user_agent: object) -> str:
    text = str(user_agent or "").strip()
    if not text:
        return "NTRIP RTGS RTRINEX/0.1"
    if text.upper().startswith("NTRIP"):
        return text
    return f"NTRIP {text}"


def _detect_sys_obs_types_from_epochs(epochs: Iterable[EpochObservation]) -> Dict[str, List[str]]:
    detected: Dict[str, List[str]] = {}
    for epoch in epochs:
        satellites = getattr(epoch, "satellites", {}) or {}
        epoch_detected = _detect_sys_obs_types_from_satellites(satellites)
        if not detected:
            detected = epoch_detected
        else:
            detected = _merge_sys_obs_types(detected, epoch_detected)
    return detected or _copy_default_sys_obs_types()


def _normalize_station_folder_name(station_code: str, receiver_number: str) -> str:
    station = str(station_code or "RTGS")[:4].upper().ljust(4, "0")
    receiver = str(receiver_number or "00")[:2].upper().ljust(2, "0")
    return f"{station}{receiver}"


def _build_station_config(raw_station: dict, *, config_dir: Path) -> RTStationConfig:
    if not isinstance(raw_station, dict):
        raise ValueError("Each station entry must be a mapping")

    name = str(raw_station.get("name") or "").strip()
    if not name:
        raise ValueError("Each station must define a name")

    enabled = bool(raw_station.get("enabled", True))

    ntrip_block = raw_station.get("ntrip") or {}
    rinex_block = raw_station.get("rinex") or {}
    if not isinstance(ntrip_block, dict):
        raise ValueError(f"Station {name}: ntrip must be a mapping")
    if not isinstance(rinex_block, dict):
        raise ValueError(f"Station {name}: rinex must be a mapping")

    host = str(ntrip_block.get("host") or "").strip()
    mountpoint = str(ntrip_block.get("mountpoint") or "").strip()
    if not host:
        raise ValueError(f"Station {name}: ntrip.host is required")
    if not mountpoint:
        raise ValueError(f"Station {name}: ntrip.mountpoint is required")

    ntrip = NtripSourceConfig(
        host=host,
        port=_parse_int(ntrip_block.get("port", 2101), field_name=f"Station {name}: ntrip.port"),
        mountpoint=mountpoint,
        user=str(ntrip_block.get("user") or "").strip(),
        password=str(ntrip_block.get("password") or ""),
        user_agent=_normalize_ntrip_user_agent(ntrip_block.get("user_agent")),
        connect_timeout_seconds=_parse_float(
            ntrip_block.get("connect_timeout_seconds", 15.0),
            field_name=f"Station {name}: ntrip.connect_timeout_seconds",
            min_value=0.1,
        ),
        reconnect_delay_seconds=_parse_float(
            ntrip_block.get("reconnect_delay_seconds", 5.0),
            field_name=f"Station {name}: ntrip.reconnect_delay_seconds",
            min_value=0.1,
        ),
    )

    time_system = str(rinex_block.get("time_system", "GPS")).strip().upper() or "GPS"
    if time_system not in SUPPORTED_TIME_SYSTEMS:
        raise ValueError(
            f"Station {name}: rinex.time_system must be one of {sorted(SUPPORTED_TIME_SYSTEMS)}"
        )

    rinex = RinexStationConfig(
        output_directory=_resolve_path(
            rinex_block.get("output_directory", "/mnt/20t/RT_RINEX"),
            config_dir=config_dir,
            field_name=f"Station {name}: rinex.output_directory",
        ),
        marker_name=str(rinex_block.get("marker_name") or name).strip() or name,
        marker_number=str(rinex_block.get("marker_number", "0") or "0"),
        station_code=str(rinex_block.get("station_code") or name[:4] or "RTGS").strip().upper() or "RTGS",
        receiver_number=str(rinex_block.get("receiver_number", "00") or "00").strip().upper() or "00",
        country_code=str(rinex_block.get("country_code", "CHN") or "CHN").strip().upper() or "CHN",
        receiver_type=str(rinex_block.get("receiver_type", "UNKNOWN") or "UNKNOWN").strip() or "UNKNOWN",
        antenna_type=str(rinex_block.get("antenna_type", "UNKNOWN") or "UNKNOWN").strip() or "UNKNOWN",
        antenna_model=str(
            rinex_block.get("antenna_model")
            or rinex_block.get("antenna_number")
            or ""
        ).strip(),
        antenna_number=str(rinex_block.get("antenna_number") or "").strip(),
        datatype=str(rinex_block.get("datatype", "MO") or "MO").strip().upper() or "MO",
        filename_template=(
            str(rinex_block.get("filename_template")).strip()
            if rinex_block.get("filename_template") is not None
            else None
        ),
        sample_interval_seconds=_parse_optional_int(
            rinex_block.get("sample_interval_seconds", "auto"),
            field_name=f"Station {name}: rinex.sample_interval_seconds",
        ),
        split_enabled=bool(rinex_block.get("split_enabled", True)),
        split_period_seconds=_parse_optional_int(
            rinex_block.get("split_period_seconds", 3600),
            field_name=f"Station {name}: rinex.split_period_seconds",
        )
        or 3600,
        daily_merge_min_interval_seconds=_parse_int(
            rinex_block.get("daily_merge_min_interval_seconds", 15),
            field_name=f"Station {name}: rinex.daily_merge_min_interval_seconds",
        ),
        time_system=time_system,
        approx_position=_parse_position(
            rinex_block.get("approx_position"),
            field_name=f"Station {name}: rinex.approx_position",
        ),
        auto_detect_obs_types=bool(rinex_block.get("auto_detect_obs_types", True)),
        sys_obs_types=_normalize_sys_obs_types(rinex_block.get("sys_obs_types")),
        align_tolerance_seconds=_parse_float(
            rinex_block.get("align_tolerance_seconds", 0.001),
            field_name=f"Station {name}: rinex.align_tolerance_seconds",
            min_value=0.0,
        ),
    )

    if rinex.split_enabled and rinex.split_period_seconds is None:
        raise ValueError(f"Station {name}: rinex.split_period_seconds is required when split_enabled is true")

    if (
        rinex.split_enabled
        and rinex.sample_interval_seconds is not None
        and rinex.split_period_seconds is not None
        and rinex.split_period_seconds < rinex.sample_interval_seconds
    ):
        raise ValueError(
            f"Station {name}: rinex.split_period_seconds must be >= rinex.sample_interval_seconds"
        )

    return RTStationConfig(name=name, enabled=enabled, ntrip=ntrip, rinex=rinex)


def load_rt_rinex_config(path: str | Path) -> MultiStationRTRinexConfig:
    config_path = Path(path).resolve()
    with open(config_path, "r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    if not isinstance(raw, dict):
        raise ValueError("Top-level config must be a YAML mapping")

    defaults = raw.get("defaults") or {}
    stations_raw = raw.get("stations") or []

    if not isinstance(defaults, dict):
        raise ValueError("defaults must be a mapping when provided")
    if not isinstance(stations_raw, list) or not stations_raw:
        raise ValueError("stations must be a non-empty list")

    stations: List[RTStationConfig] = []
    for raw_station in stations_raw:
        merged_station = _deep_merge(defaults, raw_station or {})
        stations.append(_build_station_config(merged_station, config_dir=config_path.parent))

    return MultiStationRTRinexConfig(config_path=config_path, stations=stations)


def _normalize_utc_datetime(epoch_time: datetime) -> datetime:
    if epoch_time.tzinfo is None:
        return epoch_time
    return epoch_time.astimezone(timezone.utc).replace(tzinfo=None)


def _convert_utc_to_time_system(epoch_time: datetime, time_system: str) -> datetime:
    normalized = _normalize_utc_datetime(epoch_time)
    if time_system == "UTC":
        return normalized
    if time_system == "GPS":
        return normalized + timedelta(seconds=GNSSTime.LEAP_SECONDS)
    raise ValueError(f"Unsupported time system: {time_system}")


def _round_epoch_time(epoch_time: datetime, interval_seconds: float) -> datetime:
    interval_ms = max(1, int(round(float(interval_seconds) * 1000.0)))
    anchor = datetime(1980, 1, 6)
    total_ms = int(round((epoch_time - anchor).total_seconds() * 1000.0))
    rounded_ms = round(total_ms / interval_ms) * interval_ms
    return anchor + timedelta(milliseconds=rounded_ms)


def _bucket_start_time(epoch_time: datetime, bucket_seconds: float) -> datetime:
    interval_ms = max(1, int(round(float(bucket_seconds) * 1000.0)))
    anchor = datetime(1980, 1, 6)
    total_ms = int(round((epoch_time - anchor).total_seconds() * 1000.0))
    bucket_ms = (total_ms // interval_ms) * interval_ms
    return anchor + timedelta(milliseconds=bucket_ms)


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


class PrefetchedSocketStream:
    """Socket-like stream that returns already-read bytes before reading the socket."""

    def __init__(self, sock: socket.socket, prefetched: bytes = b""):
        self._socket = sock
        self._prefetched = bytearray(prefetched or b"")

    def _read_from_prefetched(self, size: int) -> bytes:
        if size <= 0 or not self._prefetched:
            return b""
        chunk = bytes(self._prefetched[:size])
        del self._prefetched[:size]
        return chunk

    def recv(self, size: int) -> bytes:
        prefetched = self._read_from_prefetched(size)
        if prefetched:
            return prefetched
        return self._socket.recv(size)

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            chunks: List[bytes] = []
            if self._prefetched:
                chunks.append(bytes(self._prefetched))
                self._prefetched.clear()
            while True:
                chunk = self._socket.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)

        chunks: List[bytes] = []
        remaining = size
        prefetched = self._read_from_prefetched(remaining)
        if prefetched:
            chunks.append(prefetched)
            remaining -= len(prefetched)

        while remaining > 0:
            chunk = self._socket.recv(remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)

        return b"".join(chunks)

    def close(self) -> None:
        self._socket.close()

    def __getattr__(self, item):
        return getattr(self._socket, item)


def _create_default_reader(stream):
    if RTCMReader is None:
        raise RuntimeError("pyrtcm is required for RT GNSS streaming")
    return MixedGNSSReader(stream)


def _create_rtcm_handler() -> RTCMHandler:
    from core.rtcm_handler import RTCMHandler

    reference_utc = datetime.now(timezone.utc)
    try:
        return RTCMHandler(reference_utc=reference_utc, compute_geometry=False)
    except TypeError:
        try:
            return RTCMHandler(reference_utc=reference_utc)
        except TypeError:
            return RTCMHandler()


class RTNtripRinexStation(threading.Thread):
    """RT NTRIP-to-RINEX worker for a single station."""

    def __init__(
        self,
        station: RTStationConfig,
        *,
        log_fn: Optional[Callable[[str], None]] = None,
        reader_factory: Optional[Callable[[object], Iterable[tuple[bytes | None, object]]]] = None,
        handler_factory: Optional[Callable[[], RTCMHandler]] = None,
        stream_connector: Optional[Callable[[NtripSourceConfig], object]] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        super().__init__(name=f"RTNtripRinex-{station.name}", daemon=True)
        self.station = station
        self.log_fn = log_fn or (lambda message: print(message, flush=True))
        self.reader_factory = reader_factory or _create_default_reader
        self.handler = (handler_factory or _create_rtcm_handler)()
        self.stream_connector = stream_connector or self._connect_ntrip_stream
        self.sleep_fn = sleep_fn
        self.stop_event = threading.Event()
        self._stream = None
        self._current_epoch: Optional[EpochObservation] = None
        self._current_epoch_key: Optional[int] = None
        self._last_written_epoch_time: Optional[datetime] = None
        self._active_writer: Optional[RINEX3Writer] = None
        self._active_file_start_time: Optional[datetime] = None
        self._resolved_sample_interval_seconds: Optional[int] = self.station.rinex.sample_interval_seconds
        self._last_epoch_time_for_detection: Optional[datetime] = None
        self._pending_epochs: List[EpochObservation] = []
        self._primed_sys_obs_types: Optional[Dict[str, List[str]]] = None

    def stop(self) -> None:
        self.stop_event.set()
        stream = self._stream
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass

    def run(self) -> None:
        self.log(f"Worker started for mountpoint {self.station.ntrip.mountpoint}")
        try:
            while not self.stop_event.is_set():
                try:
                    self._run_connection_cycle()
                except Exception as exc:
                    self.log(f"Stream error: {exc}")
                finally:
                    self._flush_pending_epoch()
                    self._close_stream()

                if self.stop_event.is_set():
                    break

                self.log(
                    f"Reconnect in {self.station.ntrip.reconnect_delay_seconds:.1f}s"
                )
                self.sleep_fn(self.station.ntrip.reconnect_delay_seconds)
        finally:
            self._close_writer()
            self.log("Worker stopped")

    def process_reader(self, reader: Iterable[tuple[bytes | None, object]]) -> None:
        """Consume an RTCM reader iterable once. Exposed for tests and batch driving."""
        for raw, msg in reader:
            if self.stop_event.is_set():
                break
            self._consume_message(raw, msg)
        self._flush_pending_epoch()
        self._close_writer()

    def log(self, message: str) -> None:
        self.log_fn(f"[{self.station.name}] {message}")

    def _station_folder_name(self) -> str:
        rinex_cfg = self.station.rinex
        return _normalize_station_folder_name(rinex_cfg.station_code, rinex_cfg.receiver_number)

    def _station_root_dir(self) -> Path:
        return self.station.rinex.output_directory / self._station_folder_name()

    def _year_dir(self, output_time: datetime) -> Path:
        return self._station_root_dir() / output_time.strftime("%Y")

    def _year_doy_dir(self, output_time: datetime) -> Path:
        return self._year_dir(output_time) / output_time.strftime("%Y%j")

    def _resolve_output_directory(self, output_time: datetime) -> Path:
        rinex_cfg = self.station.rinex
        if rinex_cfg.split_enabled and (rinex_cfg.split_period_seconds or 0) < 86400:
            return self._year_doy_dir(output_time)
        return self._year_dir(output_time)

    def _resolve_file_period_seconds(self) -> int:
        rinex_cfg = self.station.rinex
        if rinex_cfg.split_enabled and rinex_cfg.split_period_seconds:
            return int(rinex_cfg.split_period_seconds)
        return 86400

    def _resolve_antenna_model(self) -> str:
        rinex_cfg = self.station.rinex
        return str(rinex_cfg.antenna_model or rinex_cfg.antenna_number or "").strip()

    def _run_connection_cycle(self) -> None:
        ntrip = self.station.ntrip
        endpoint = f"{ntrip.host}:{ntrip.port}/{ntrip.mountpoint}"
        self.log(f"Connecting to {endpoint}")
        self._stream = self.stream_connector(ntrip)
        self.log(f"Connected to {endpoint}")

        reader = self.reader_factory(self._stream)
        for raw, msg in reader:
            if self.stop_event.is_set():
                break
            self._consume_message(raw, msg)

        if not self.stop_event.is_set():
            self.log("Connection closed by remote peer")

    def _consume_message(self, _raw: bytes | None, msg: object) -> None:
        if msg is None:
            return

        epoch_data = self.handler.process_message(msg)
        if epoch_data is None:
            return

        epoch_key = _epoch_key_millis(epoch_data)
        if self._current_epoch is None:
            self._current_epoch = epoch_data
            self._current_epoch_key = epoch_key
            return

        if epoch_key == self._current_epoch_key:
            _merge_epoch_data(self._current_epoch, epoch_data)
            return

        completed_epoch = self._current_epoch
        self._current_epoch = epoch_data
        self._current_epoch_key = epoch_key
        self._handle_epoch(completed_epoch)

    def _flush_pending_epoch(self) -> None:
        if self._current_epoch is None:
            return
        epoch = self._current_epoch
        self._current_epoch = None
        self._current_epoch_key = None
        self._handle_epoch(epoch)

    def _handle_epoch(self, epoch_data: EpochObservation) -> None:
        satellites = dict(getattr(epoch_data, "satellites", {}) or {})
        if not satellites:
            return

        epoch_time = getattr(epoch_data, "utc_datetime", None)
        if epoch_time is None:
            return

        if self._resolved_sample_interval_seconds is None:
            self._pending_epochs.append(epoch_data)
            self._update_detected_sample_interval(epoch_time)
            if self._resolved_sample_interval_seconds is None:
                return

            self._primed_sys_obs_types = _detect_sys_obs_types_from_epochs(self._pending_epochs)
            pending_epochs = list(self._pending_epochs)
            self._pending_epochs.clear()
            for pending_epoch in pending_epochs:
                self._write_epoch(pending_epoch)
            return

        self._write_epoch(epoch_data)

    def _update_detected_sample_interval(self, epoch_time: datetime) -> None:
        if self._resolved_sample_interval_seconds is not None:
            return

        current_time = _convert_utc_to_time_system(epoch_time, self.station.rinex.time_system)
        previous_time = self._last_epoch_time_for_detection
        self._last_epoch_time_for_detection = current_time
        if previous_time is None:
            return

        delta_seconds = (current_time - previous_time).total_seconds()
        if delta_seconds <= 0.0:
            return

        rounded_seconds = max(1, int(round(delta_seconds)))
        self._resolved_sample_interval_seconds = rounded_seconds
        self.log(f"Detected sample interval: {rounded_seconds}s")

    def _write_epoch(self, epoch_data: EpochObservation) -> None:
        satellites = dict(getattr(epoch_data, "satellites", {}) or {})
        if not satellites:
            return

        epoch_time = getattr(epoch_data, "utc_datetime", None)
        if epoch_time is None:
            return

        aligned_epoch_time = self._align_epoch_time(epoch_time)
        if aligned_epoch_time is None:
            return

        if self._last_written_epoch_time == aligned_epoch_time:
            return

        if self._needs_obs_type_rollover(satellites):
            self.log("Detected new observation types, rolling over to a new RINEX file")
            self._primed_sys_obs_types = self._build_sys_obs_types(satellites)
            self._close_writer()

        self._ensure_writer(aligned_epoch_time, satellites)
        if self._active_writer is None:
            return

        self._update_writer_position()

        if not self._active_writer.write_observation(aligned_epoch_time, satellites):
            raise RuntimeError("Failed to write RINEX observation epoch")

        self._last_written_epoch_time = aligned_epoch_time

    def _align_epoch_time(self, epoch_time: datetime) -> Optional[datetime]:
        sample_interval_seconds = self._resolved_sample_interval_seconds
        if sample_interval_seconds is None:
            return None

        rinex_time = _convert_utc_to_time_system(epoch_time, self.station.rinex.time_system)
        if self.station.rinex.sample_interval_seconds is None:
            return rinex_time

        aligned_time = _round_epoch_time(rinex_time, sample_interval_seconds)
        diff_seconds = abs((rinex_time - aligned_time).total_seconds())
        if diff_seconds > self.station.rinex.align_tolerance_seconds:
            return None
        return aligned_time

    def _ensure_writer(self, aligned_epoch_time: datetime, satellites: dict) -> None:
        bucket_start_time = _bucket_start_time(aligned_epoch_time, self._resolve_file_period_seconds())

        if self._active_writer is not None and self._active_file_start_time is not None:
            if bucket_start_time != self._active_file_start_time:
                self._close_writer()

        if self._active_writer is None:
            self._open_writer(bucket_start_time, satellites)

    def _build_sys_obs_types(self, satellites: dict) -> Dict[str, List[str]]:
        if not self.station.rinex.auto_detect_obs_types:
            configured = _normalize_sys_obs_types(self.station.rinex.sys_obs_types)
            return configured or _copy_default_sys_obs_types()

        detected = _detect_sys_obs_types_from_satellites(satellites)
        if self._primed_sys_obs_types:
            detected = _merge_sys_obs_types(self._primed_sys_obs_types, detected)
        return detected or _copy_default_sys_obs_types()

    def _needs_obs_type_rollover(self, satellites: dict) -> bool:
        if self._active_writer is None or not self.station.rinex.auto_detect_obs_types:
            return False

        current_sys_obs_types = _normalize_sys_obs_types(getattr(self._active_writer, "sys_obs_types", {}))
        epoch_sys_obs_types = _detect_sys_obs_types_from_satellites(satellites)
        for system, codes in epoch_sys_obs_types.items():
            current_codes = set(current_sys_obs_types.get(system, []))
            if any(code not in current_codes for code in codes):
                return True
        return False

    def _resolve_approx_position(self) -> Optional[List[float]]:
        position = getattr(self.handler, "last_station_coords", None)
        if position:
            parsed = _parse_position(position, field_name="handler.last_station_coords")
            if parsed is not None:
                return parsed
        if self.station.rinex.approx_position is not None:
            return self.station.rinex.approx_position
        return None

    def _open_writer(self, aligned_epoch_time: datetime, satellites: dict) -> None:
        rinex_cfg = self.station.rinex
        output_directory = self._resolve_output_directory(aligned_epoch_time)
        output_directory.mkdir(parents=True, exist_ok=True)

        writer = RINEX3Writer(
            str(output_directory),
            marker_name=rinex_cfg.marker_name,
            marker_number=rinex_cfg.marker_number,
            station_code=rinex_cfg.station_code,
            receiver_number=rinex_cfg.receiver_number,
            country_code=rinex_cfg.country_code,
            period=RINEX3Writer.format_period_code(self._resolve_file_period_seconds(), "01D"),
            interval=RINEX3Writer.format_interval_code(self._resolved_sample_interval_seconds or 1),
            datatype=rinex_cfg.datatype,
            filename_template=rinex_cfg.filename_template,
            file_time=aligned_epoch_time,
            header_interval_seconds=float(self._resolved_sample_interval_seconds or 1),
            time_system=rinex_cfg.time_system,
            antenna_number=self._resolve_antenna_model(),
        )
        if not writer.open():
            raise RuntimeError(f"Failed to open RINEX file: {writer.filename}")

        approx_position = self._resolve_approx_position()
        if approx_position is not None:
            writer.set_approx_position(approx_position)

        if not writer.write_header(
            sys_obs_types=self._build_sys_obs_types(satellites),
            receiver_type=rinex_cfg.receiver_type,
            antenna_type=rinex_cfg.antenna_type,
            antenna_number=self._resolve_antenna_model(),
        ):
            writer.close()
            raise RuntimeError(f"Failed to write RINEX header: {writer.filename}")

        self._active_writer = writer
        self._active_file_start_time = aligned_epoch_time
        self._primed_sys_obs_types = None
        self.log(f"Opened {Path(writer.filename).name}")

    def _update_writer_position(self) -> None:
        if self._active_writer is None:
            return
        approx_position = self._resolve_approx_position()
        if approx_position is not None:
            self._active_writer.set_approx_position(approx_position)

    def _close_writer(self) -> None:
        writer = self._active_writer
        file_start_time = self._active_file_start_time
        self._active_writer = None
        self._active_file_start_time = None
        if writer is None:
            return
        file_path = Path(writer.filename)
        filename = file_path.name
        writer.close()
        self.log(f"Closed {filename}")
        self._maybe_merge_daily_file(file_path, file_start_time)

    def _maybe_merge_daily_file(self, file_path: Path, file_start_time: Optional[datetime]) -> None:
        rinex_cfg = self.station.rinex
        if not (
            rinex_cfg.split_enabled
            and rinex_cfg.split_period_seconds is not None
            and rinex_cfg.split_period_seconds < 86400
            and file_start_time is not None
        ):
            return

        day_dir = self._year_doy_dir(file_start_time)
        if not day_dir.exists():
            return

        expected_count = max(1, (86400 + int(rinex_cfg.split_period_seconds) - 1) // int(rinex_cfg.split_period_seconds))
        source_files = sorted(
            path for path in day_dir.iterdir()
            if path.is_file() and path.suffix.lower() == ".rnx"
        )
        if len(source_files) < expected_count:
            return

        try:
            from utils.merge_rinex_daily import merge_rinex_daily_files
        except Exception as exc:  # pragma: no cover - depends on optional deps
            self.log(f"Daily merge skipped for {day_dir.name}: {exc}")
            return

        output_dir = day_dir.parent
        merge_interval_seconds = float(max(15, int(rinex_cfg.daily_merge_min_interval_seconds)))

        try:
            result = merge_rinex_daily_files(
                [day_dir],
                output_dir,
                marker_name=rinex_cfg.marker_name,
                receiver_type=rinex_cfg.receiver_type,
                station_code=rinex_cfg.station_code,
                receiver_number=rinex_cfg.receiver_number,
                country_code=rinex_cfg.country_code,
                antenna_type=rinex_cfg.antenna_type,
                antenna_number=self._resolve_antenna_model(),
                datatype=rinex_cfg.datatype,
                output_interval_seconds=merge_interval_seconds,
                time_system=rinex_cfg.time_system,
            )
        except Exception as exc:
            self.log(f"Daily merge failed for {day_dir.name}: {exc}")
            return

        if result.output_files:
            self.log(
                f"Merged {len(result.source_files)} split file(s) into {Path(result.output_files[0]).name}"
            )

    def _close_stream(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        try:
            stream.close()
        except Exception:
            pass

    @staticmethod
    def _connect_ntrip_stream(ntrip: NtripSourceConfig):
        sock = socket.create_connection(
            (ntrip.host, int(ntrip.port)),
            timeout=float(ntrip.connect_timeout_seconds),
        )
        sock.settimeout(float(ntrip.connect_timeout_seconds))
        try:
            auth = ""
            if ntrip.user or ntrip.password:
                token = base64.b64encode(f"{ntrip.user}:{ntrip.password}".encode("utf-8")).decode("ascii")
                auth = f"Authorization: Basic {token}\r\n"

            request = (
                f"GET /{ntrip.mountpoint} HTTP/1.0\r\n"
                f"User-Agent: {ntrip.user_agent}\r\n"
                "Accept: */*\r\n"
                f"{auth}"
                "\r\n"
            )
            sock.sendall(request.encode("ascii", errors="ignore"))

            header_buffer = b""
            while b"\n" not in header_buffer and len(header_buffer) < 8192:
                chunk = sock.recv(1024)
                if not chunk:
                    raise ConnectionError("No response from NTRIP caster")
                header_buffer += chunk

            if b"\n" not in header_buffer:
                raise ConnectionError("Incomplete NTRIP response status line")

            status_line, remainder = header_buffer.split(b"\n", 1)
            status_line = status_line.strip()
            if b"200" not in status_line:
                raise ConnectionError(status_line.decode("utf-8", errors="ignore") or "NTRIP authorization failed")

            while True:
                stripped = remainder.lstrip(b"\r\n")
                if stripped != remainder:
                    remainder = stripped
                    break

                if remainder.startswith(b"\xd3"):
                    break

                if b"\r\n\r\n" in remainder:
                    header_end = remainder.find(b"\r\n\r\n")
                    remainder = remainder[header_end + 4 :]
                    break

                if b"\n\n" in remainder:
                    header_end = remainder.find(b"\n\n")
                    remainder = remainder[header_end + 2 :]
                    break

                if len(remainder) > 16384:
                    raise ConnectionError("NTRIP response headers are too large")

                chunk = sock.recv(1024)
                if not chunk:
                    break
                remainder += chunk

            return PrefetchedSocketStream(sock, remainder)
        except Exception:
            sock.close()
            raise


class MultiStationRTRinexService:
    """Manage multiple RT NTRIP-to-RINEX workers."""

    def __init__(
        self,
        config: MultiStationRTRinexConfig,
        *,
        log_fn: Optional[Callable[[str], None]] = None,
        station_names: Optional[Iterable[str]] = None,
        worker_factory: Optional[Callable[[RTStationConfig], RTNtripRinexStation]] = None,
    ):
        selected_names = {str(name).strip() for name in (station_names or []) if str(name).strip()}
        stations = [
            station
            for station in config.stations
            if station.enabled and (not selected_names or station.name in selected_names)
        ]
        if not stations:
            raise ValueError("No enabled stations matched the requested filter")

        self.config = config
        self.log_fn = log_fn or (lambda message: print(message, flush=True))
        self._worker_factory = worker_factory
        self.workers = [
            self._build_worker(station)
            for station in stations
        ]

    def _build_worker(self, station: RTStationConfig) -> RTNtripRinexStation:
        if self._worker_factory is not None:
            return self._worker_factory(station)
        return RTNtripRinexStation(station, log_fn=self.log_fn)

    def start(self) -> None:
        for worker in self.workers:
            worker.start()

    def stop(self) -> None:
        for worker in self.workers:
            worker.stop()

    def join(self, timeout: Optional[float] = None) -> None:
        deadline = None if timeout is None else time.time() + timeout
        for worker in self.workers:
            remaining = None
            if deadline is not None:
                remaining = max(0.0, deadline - time.time())
            worker.join(remaining)
