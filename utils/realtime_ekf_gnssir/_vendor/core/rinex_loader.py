"""RINEX observation and ephemeris helpers used by file replay mode."""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import gzip
import math
from pathlib import Path
from typing import Iterable

try:
    import numpy as np
except Exception:  # pragma: no cover - depends on environment
    np = None

from .data_models import EpochObservation, SatelliteState, SignalData
from .gnss_time import GNSSTime


SECONDS_PER_WEEK = 7 * 24 * 3600.0
LIGHT_SPEED = 299792458.0
GPS_LIKE_TIME_SYSTEMS = {"GPS", "GAL", "GST", "QZS", "QZSS", "IRN", "IRNSS"}
SATELLITE_SYSTEM_CODES = {"G", "R", "E", "J", "C", "I", "S"}


def _open_text(path: str | Path):
    source_path = Path(path)
    if source_path.suffix.lower() == ".gz":
        return gzip.open(source_path, "rt", encoding="utf-8", errors="ignore")
    return source_path.open("r", encoding="utf-8", errors="ignore")


@dataclass(slots=True)
class RinexObservationMetadata:
    """Header metadata extracted from a RINEX observation file."""

    path: str
    version: str = ""
    time_system: str = "GPS"
    interval_seconds: float | None = None
    approx_position_ecef: tuple[float, float, float] | None = None
    sys_obs_types: dict[str, list[str]] = field(default_factory=dict)

    @property
    def has_nonzero_approx_position(self) -> bool:
        coords = self.approx_position_ecef
        if coords is None:
            return False
        return any(abs(float(value)) > 1e-6 for value in coords[:3])


@dataclass(slots=True)
class SatelliteEphemerisState:
    """Interpolated satellite state from a file ephemeris provider."""

    position_ecef_m: np.ndarray
    clock_correction_s: float = 0.0
    source: str = ""


def _parse_float(text: str) -> float | None:
    value = text.strip()
    if not value:
        return None
    normalized = value.replace("D", "E").replace("d", "e")
    try:
        return float(normalized)
    except ValueError:
        # Some receivers/RINEX exporters squeeze the LLI/SSI flag into the
        # numeric field with whitespace, e.g. "6483452.632 5". In that case,
        # keep the leading numeric token and ignore the trailing quality flag.
        token = normalized.split()[0]
        return float(token)


def _build_datetime(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second: float,
) -> datetime:
    second_int = int(math.floor(second))
    microseconds = int(round((second - second_int) * 1_000_000.0))
    epoch = datetime(year, month, day, hour, minute, second_int, tzinfo=timezone.utc)
    return epoch + timedelta(microseconds=microseconds)


def _timescale_to_utc_and_gps(epoch_dt: datetime, time_system: str) -> tuple[datetime, int, float]:
    system = (time_system or "GPS").strip().upper()

    if system == "UTC":
        utc_dt = epoch_dt
    elif system == "GLO":
        utc_dt = epoch_dt - timedelta(hours=3)
    elif system in {"BDT", "BDS", "BEIDOU"}:
        gps_dt = epoch_dt + timedelta(seconds=14.0)
        utc_dt = gps_dt - timedelta(seconds=GNSSTime.LEAP_SECONDS)
    elif system in GPS_LIKE_TIME_SYSTEMS:
        utc_dt = epoch_dt - timedelta(seconds=GNSSTime.LEAP_SECONDS)
    else:
        utc_dt = epoch_dt

    gps_week, gps_sow = GNSSTime.utc_to_gps(utc_dt)
    return utc_dt, gps_week, gps_sow


def _normalize_gps_sow(week: int, sow: float) -> tuple[int, float]:
    sow = float(sow)
    while sow < 0.0:
        sow += SECONDS_PER_WEEK
        week -= 1
    while sow >= SECONDS_PER_WEEK:
        sow -= SECONDS_PER_WEEK
        week += 1
    return week, sow


def _wrapped_time_difference(time_sow: float, reference_sow: float) -> float:
    dt = float(time_sow) - float(reference_sow)
    if dt > SECONDS_PER_WEEK / 2.0:
        dt -= SECONDS_PER_WEEK
    elif dt < -SECONDS_PER_WEEK / 2.0:
        dt += SECONDS_PER_WEEK
    return dt


def _parse_obs_header(handle) -> RinexObservationMetadata:
    metadata = RinexObservationMetadata(path=str(getattr(handle, "name", "")))
    current_system: str | None = None
    expected_obs_counts: dict[str, int] = {}

    while True:
        line = handle.readline()
        if not line:
            break
        label = line[60:80].strip()
        content = line[:60]

        if label == "RINEX VERSION / TYPE":
            metadata.version = content[:9].strip()
        elif label == "APPROX POSITION XYZ":
            values = content.split()
            if len(values) >= 3:
                metadata.approx_position_ecef = (
                    float(values[0]),
                    float(values[1]),
                    float(values[2]),
                )
        elif label == "INTERVAL":
            values = content.split()
            if values:
                metadata.interval_seconds = float(values[0])
        elif label == "TIME OF FIRST OBS":
            values = content.split()
            if values:
                metadata.time_system = values[-1].upper()
        elif label == "SYS / # / OBS TYPES":
            if line[0].strip():
                current_system = line[0].strip().upper()
                parts = content.split()
                if len(parts) >= 2:
                    try:
                        expected_obs_counts[current_system] = int(parts[1])
                    except ValueError:
                        pass
                metadata.sys_obs_types.setdefault(current_system, []).extend(parts[2:])
            elif current_system is not None:
                metadata.sys_obs_types.setdefault(current_system, []).extend(content.split())
        elif label == "END OF HEADER":
            break

    for system, obs_types in list(metadata.sys_obs_types.items()):
        expected_count = expected_obs_counts.get(system)
        if expected_count is not None:
            metadata.sys_obs_types[system] = obs_types[:expected_count]

    return metadata


def read_rinex_observation_header(path: str | Path) -> RinexObservationMetadata:
    """Read a RINEX observation file header without parsing the body."""

    with _open_text(path) as handle:
        metadata = _parse_obs_header(handle)
    metadata.path = str(path)
    return metadata


def _parse_epoch_header(line: str) -> tuple[datetime, int, int] | None:
    if not line.startswith(">"):
        return None

    try:
        year = int(line[2:6])
        month = int(line[7:9])
        day = int(line[10:12])
        hour = int(line[13:15])
        minute = int(line[16:18])
        second = float(line[19:29])
        flag = int(line[30:32])
        satellite_count = int(line[32:35])
    except ValueError:
        return None

    return _build_datetime(year, month, day, hour, minute, second), flag, satellite_count


def _parse_observation_fields(raw_fields: str, obs_types: list[str]) -> dict[str, dict[str, float]]:
    values_by_signal: dict[str, dict[str, float]] = defaultdict(dict)
    if len(raw_fields) < len(obs_types) * 16:
        raw_fields = raw_fields.ljust(len(obs_types) * 16)

    for index, obs_code in enumerate(obs_types):
        field = raw_fields[index * 16 : (index + 1) * 16]
        if not field:
            break
        value = _parse_float(field[:14])
        if value is None:
            continue
        values_by_signal[obs_code[1:].upper()][obs_code[0].upper()] = float(value)

    return values_by_signal


def _choose_best_pseudorange(signal_map: dict[str, SignalData]) -> float | None:
    priorities = [
        "1C",
        "1S",
        "1L",
        "1X",
        "1P",
        "1W",
        "1Z",
        "2I",
        "2Q",
        "2X",
        "2C",
        "5I",
        "5Q",
        "5X",
        "5A",
        "7I",
        "7Q",
        "7X",
        "6I",
        "6Q",
        "6X",
    ]

    for signal_id in priorities:
        signal = signal_map.get(signal_id)
        if signal is not None and float(signal.pseudorange) > 0.0:
            return float(signal.pseudorange)

    for signal in signal_map.values():
        if float(signal.pseudorange) > 0.0:
            return float(signal.pseudorange)
    return None


def _coerce_receiver_position(values: Iterable[float] | None) -> list[float] | None:
    if values is None:
        return None
    try:
        coords = [float(value) for value in list(values)[:3]]
    except (TypeError, ValueError):
        return None
    return coords if len(coords) >= 3 else None


def _has_nonzero_position(values: Iterable[float] | None) -> bool:
    coords = _coerce_receiver_position(values)
    if coords is None:
        return False
    return any(abs(float(value)) > 1e-6 for value in coords[:3])


def _build_satellite_state(satellite_id: str, obs_types: list[str], raw_fields: str) -> SatelliteState | None:
    if len(satellite_id) < 2:
        return None

    signal_values = _parse_observation_fields(raw_fields, obs_types)
    if not signal_values:
        return None

    try:
        prn = int(satellite_id[1:])
    except ValueError:
        return None

    sat_state = SatelliteState(sys_id=satellite_id[0].upper(), prn=prn)
    for signal_id, values in signal_values.items():
        sat_state.signals[signal_id] = SignalData(
            signal_id=signal_id,
            pseudorange=float(values.get("C", 0.0) or 0.0),
            phase=float(values.get("L", 0.0) or 0.0),
            doppler=float(values.get("D", 0.0) or 0.0),
            snr=float(values.get("S", 0.0) or 0.0),
            lock_time=0,
            half_cycle=0,
        )

    return sat_state if sat_state.signals else None


def _is_satellite_record_start(line: str) -> bool:
    if len(line) < 3:
        return False
    return line[0].upper() in SATELLITE_SYSTEM_CODES and line[1:3].isdigit()


def _read_observation_record_payload(handle, first_line: str, expected_fields: int) -> str:
    payload = first_line[3:].rstrip("\r\n")
    expected_width = max(0, int(expected_fields)) * 16

    if expected_width <= 0:
        return payload
    if len(payload) >= expected_width:
        return payload[:expected_width]

    # RINEX 3 observation records are variable length and may exceed 80 columns.
    # Some producers still wrap long records, usually with a blank continuation prefix.
    while len(payload) < expected_width:
        next_position = handle.tell()
        continuation = handle.readline()
        if not continuation:
            break
        if continuation.startswith(">") or _is_satellite_record_start(continuation):
            handle.seek(next_position)
            break

        continuation_payload = continuation.rstrip("\r\n")
        if len(continuation_payload) >= 3 and continuation_payload[:3].isspace():
            continuation_payload = continuation_payload[3:]
        payload += continuation_payload

    return payload[:expected_width].ljust(expected_width)


def _system_to_be2pos_type(system: str) -> str:
    if system == "R":
        return "GLO"
    if system == "S":
        return "SBS"
    return system


def _build_be2pos_input(eph: dict) -> tuple[str, dict] | None:
    system = str(eph.get("satellite_id", ""))[:1]
    sys_type = _system_to_be2pos_type(system)
    payload = {"SatType": sys_type, "PRN": eph.get("PRN")}

    if sys_type == "GLO":
        payload.update(
            {
                "X": eph.get("X"),
                "Y": eph.get("Y"),
                "Z": eph.get("Z"),
                "Vx": eph.get("Vx"),
                "Vy": eph.get("Vy"),
                "Vz": eph.get("Vz"),
                "Ax": eph.get("Ax"),
                "Ay": eph.get("Ay"),
                "Az": eph.get("Az"),
                "tb": eph.get("tb"),
                "tau_n": eph.get("tau_n"),
                "gamma_n": eph.get("gamma_n"),
            }
        )
    elif sys_type == "SBS":
        payload.update(
            {
                "t0": eph.get("t0", eph.get("toe")),
                "pos": eph.get("pos"),
                "vel": eph.get("vel"),
                "acc": eph.get("acc"),
                "af0": eph.get("af0", 0.0),
                "af1": eph.get("af1", 0.0),
                "af2": eph.get("af2", 0.0),
                "Toc": eph.get("toc", eph.get("t0", 0.0)),
            }
        )
    else:
        payload.update(
            {
                "Week": eph.get("week"),
                "Toe": eph.get("toe"),
                "sqrtA": eph.get("sqrt_a"),
                "Eccentricity": eph.get("e"),
                "M0": eph.get("M0"),
                "omega": eph.get("omega"),
                "i0": eph.get("i0"),
                "OMEGA0": eph.get("Omega0"),
                "Delta_n": eph.get("delta_n"),
                "OMEGA_DOT": eph.get("Omega_dot"),
                "IDOT": eph.get("idot"),
                "Crs": eph.get("Crs"),
                "Crc": eph.get("Crc"),
                "Cus": eph.get("Cus"),
                "Cuc": eph.get("Cuc"),
                "Cis": eph.get("Cis"),
                "Cic": eph.get("Cic"),
                "af0": eph.get("af0"),
                "af1": eph.get("af1"),
                "af2": eph.get("af2"),
                "Toc": eph.get("toc"),
            }
        )

    return sys_type, payload


def _compute_broadcast_clock(eph: dict, transmit_time: float) -> float:
    af0 = float(eph.get("af0", 0.0) or 0.0)
    af1 = float(eph.get("af1", 0.0) or 0.0)
    af2 = float(eph.get("af2", 0.0) or 0.0)
    toc = float(eph.get("toc") or eph.get("Toc") or 0.0)
    dt = _wrapped_time_difference(transmit_time, toc)
    saved_dt = dt
    for _ in range(2):
        dt = saved_dt - (af0 + af1 * dt + af2 * dt * dt)
    clock_bias = af0 + af1 * dt + af2 * dt * dt

    sqrt_a = eph.get("sqrt_a")
    ecc = eph.get("e")
    m0 = eph.get("M0")
    delta_n = eph.get("delta_n")
    toe = eph.get("toe")
    if sqrt_a and ecc is not None and m0 is not None and delta_n is not None and toe is not None:
        try:
            semi_major_axis = float(sqrt_a) ** 2
            mean_motion = math.sqrt(3.986005e14 / (semi_major_axis ** 3)) + float(delta_n)
            tk = _wrapped_time_difference(transmit_time, float(toe))
            mean_anomaly = float(m0) + mean_motion * tk
            eccentric_anomaly = mean_anomaly
            for _ in range(10):
                next_value = mean_anomaly + float(ecc) * math.sin(eccentric_anomaly)
                if abs(next_value - eccentric_anomaly) < 1e-13:
                    eccentric_anomaly = next_value
                    break
                eccentric_anomaly = next_value
            clock_bias -= 4.442807633e-10 * float(ecc) * float(sqrt_a) * math.sin(eccentric_anomaly)
        except (TypeError, ValueError, ZeroDivisionError):
            pass

    return clock_bias


def _parse_nav_values(line: str, line_index: int = 0) -> list[float | None]:
    values: list[float | None] = []
    start = 23 if line_index == 0 else 4
    for field_index in range(4):
        begin = start + field_index * 19
        end = begin + 19
        values.append(_parse_float(line[begin:end]))
    return values


class FileEphemerisProvider:
    """Broadcast-nav and SP3 provider for file replay mode."""

    def __init__(
        self,
        kind: str,
        source_path: str,
        broadcast_ephemeris: "BroadcastEphemeris | None" = None,
        precise_records: dict[str, list[tuple[float, np.ndarray, float | None]]] | None = None,
    ) -> None:
        self.kind = kind
        self.source_path = source_path
        if broadcast_ephemeris is None:
            from realtime_ekf_gnssir._vendor.rt_ntrip_rinex_service.broadcast_ephemeris import BroadcastEphemeris

            broadcast_ephemeris = BroadcastEphemeris()
        self.broadcast_ephemeris = broadcast_ephemeris
        self.precise_records = precise_records or {}
        self._precise_times = {
            sat_id: [item[0] for item in records]
            for sat_id, records in self.precise_records.items()
        }

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        file_type: str = "auto",
        broadcast_ephemeris: "BroadcastEphemeris | None" = None,
    ) -> "FileEphemerisProvider":
        source_path = str(path)
        resolved_type = cls._resolve_file_type(source_path, file_type)

        if resolved_type == "precise":
            if np is None:
                raise RuntimeError("numpy is required for precise SP3 ephemeris support.")
            precise_records = cls._load_sp3(source_path)
            return cls("precise", source_path, precise_records=precise_records)

        if broadcast_ephemeris is None:
            from realtime_ekf_gnssir._vendor.rt_ntrip_rinex_service.broadcast_ephemeris import BroadcastEphemeris

            broadcast_ephemeris = BroadcastEphemeris()
        eph_cache = broadcast_ephemeris
        cls._load_broadcast_nav(source_path, eph_cache)
        return cls("broadcast", source_path, broadcast_ephemeris=eph_cache)

    @staticmethod
    def _resolve_file_type(path: str, file_type: str) -> str:
        hint = (file_type or "auto").strip().lower()
        if hint in {"broadcast", "broadcast rinex", "nav", "rinex"}:
            return "broadcast"
        if hint in {"precise", "sp3", "precise sp3"}:
            return "precise"

        if Path(path).suffix.lower() == ".sp3":
            return "precise"

        with _open_text(path) as handle:
            first_line = handle.readline()
        if first_line.startswith("#"):
            return "precise"
        return "broadcast"

    @staticmethod
    def _load_broadcast_nav(path: str, eph_cache: "BroadcastEphemeris") -> None:
        with _open_text(path) as handle:
            while True:
                line = handle.readline()
                if not line:
                    return
                if line[60:80].strip() == "END OF HEADER":
                    break

            while True:
                line = handle.readline()
                if not line:
                    break
                if len(line) < 3 or not line[:3].strip():
                    continue

                satellite_id = line[:3].strip().upper()
                system = satellite_id[0]
                record_length = 8 if system in {"G", "E", "C", "J", "I"} else 4
                record_lines = [line]
                for _ in range(record_length - 1):
                    continuation = handle.readline()
                    if not continuation:
                        break
                    record_lines.append(continuation)

                eph = FileEphemerisProvider._parse_nav_record(satellite_id, record_lines)
                if eph is not None:
                    time_key = "tb" if system == "R" else "toe"
                    eph_cache.cache_ephemeris(eph, time_key=time_key)

    @staticmethod
    def _parse_nav_record(satellite_id: str, record_lines: list[str]) -> dict | None:
        system = satellite_id[0]
        try:
            year = int(record_lines[0][4:8])
            month = int(record_lines[0][9:11])
            day = int(record_lines[0][12:14])
            hour = int(record_lines[0][15:17])
            minute = int(record_lines[0][18:20])
            second = float(record_lines[0][21:23].strip() or "0")
        except ValueError:
            return None

        toc_dt = _build_datetime(year, month, day, hour, minute, second)
        time_scale = {
            "G": "GPS",
            "J": "GPS",
            "E": "GAL",
            "C": "BDT",
            "I": "GPS",
            "R": "UTC",
        }.get(system, "GPS")
        _, toc_week, toc_sow = _timescale_to_utc_and_gps(toc_dt, time_scale)
        values = [_parse_nav_values(line, idx) for idx, line in enumerate(record_lines)]
        line0 = values[0]

        try:
            prn = int(satellite_id[1:])
        except ValueError:
            return None

        if system in {"G", "J"}:
            line2, line3, line4, line5, line6, line7, line8 = values[1:8]
            return {
                "system": "GPS" if system == "G" else "QZSS",
                "satellite_id": satellite_id,
                "PRN": prn if system == "G" else prn + 192,
                "slot_number": prn if system == "J" else None,
                "week": int(round(line6[2] or toc_week)),
                "toe": float(line4[0] or 0.0),
                "toc": float(toc_sow),
                "iode": int(round(line2[0] or 0.0)),
                "iodc": int(round(line7[3] or line2[0] or 0.0)),
                "a": float(line3[3] or 0.0) ** 2,
                "sqrt_a": float(line3[3] or 0.0),
                "e": float(line3[1] or 0.0),
                "M0": float(line2[3] or 0.0),
                "omega": float(line5[2] or 0.0),
                "Omega0": float(line4[2] or 0.0),
                "i0": float(line5[0] or 0.0),
                "delta_n": float(line2[2] or 0.0),
                "Omega_dot": float(line5[3] or 0.0),
                "idot": float(line6[0] or 0.0),
                "Crs": float(line2[1] or 0.0),
                "Crc": float(line5[1] or 0.0),
                "Cus": float(line3[2] or 0.0),
                "Cuc": float(line3[0] or 0.0),
                "Cis": float(line4[3] or 0.0),
                "Cic": float(line4[1] or 0.0),
                "af0": float(line0[0] or 0.0),
                "af1": float(line0[1] or 0.0),
                "af2": float(line0[2] or 0.0),
                "TGD": float(line7[2] or 0.0),
                "ura": int(round(line7[0] or 0.0)),
                "health": int(round(line7[1] or 0.0)),
                "fit_interval": float(line8[1] or 0.0),
            }

        if system == "E":
            line2, line3, line4, line5, line6, line7, _line8 = values[1:8]
            return {
                "system": "Galileo",
                "satellite_id": satellite_id,
                "PRN": prn,
                "week": int(round(line6[2] or toc_week)),
                "toe": float(line4[0] or 0.0),
                "toc": float(toc_sow),
                "iod_nav": int(round(line2[0] or 0.0)),
                "a": float(line3[3] or 0.0) ** 2,
                "sqrt_a": float(line3[3] or 0.0),
                "e": float(line3[1] or 0.0),
                "M0": float(line2[3] or 0.0),
                "omega": float(line5[2] or 0.0),
                "Omega0": float(line4[2] or 0.0),
                "i0": float(line5[0] or 0.0),
                "delta_n": float(line2[2] or 0.0),
                "Omega_dot": float(line5[3] or 0.0),
                "idot": float(line6[0] or 0.0),
                "Crs": float(line2[1] or 0.0),
                "Crc": float(line5[1] or 0.0),
                "Cus": float(line3[2] or 0.0),
                "Cuc": float(line3[0] or 0.0),
                "Cis": float(line4[3] or 0.0),
                "Cic": float(line4[1] or 0.0),
                "af0": float(line0[0] or 0.0),
                "af1": float(line0[1] or 0.0),
                "af2": float(line0[2] or 0.0),
                "SISA": int(round(line7[0] or 0.0)),
                "health": int(round(line7[1] or 0.0)),
                "BGD_E5aE1": float(line7[2] or 0.0),
                "BGD_E5bE1": float(line7[3] or 0.0),
            }

        if system == "C":
            line2, line3, line4, line5, line6, line7, line8 = values[1:8]
            bds_week = int(round(line6[2] or 0.0))
            gps_week = bds_week + 1356
            bds_toe = float(line4[0] or 0.0)
            gps_toe_week, gps_toe = _normalize_gps_sow(gps_week, bds_toe + 14.0)
            return {
                "system": "BeiDou",
                "satellite_id": satellite_id,
                "PRN": prn,
                "week": gps_toe_week,
                "bds_week": bds_week,
                "toe": gps_toe,
                "toc": float(toc_sow),
                "toe_week": gps_toe_week,
                "toc_week": toc_week,
                "bds_toe": bds_toe,
                "aode": int(round(line2[0] or 0.0)),
                "aodc": int(round(line7[0] or 0.0)),
                "a": float(line3[3] or 0.0) ** 2,
                "sqrt_a": float(line3[3] or 0.0),
                "e": float(line3[1] or 0.0),
                "M0": float(line2[3] or 0.0),
                "omega": float(line5[2] or 0.0),
                "Omega0": float(line4[2] or 0.0),
                "i0": float(line5[0] or 0.0),
                "delta_n": float(line2[2] or 0.0),
                "Omega_dot": float(line5[3] or 0.0),
                "idot": float(line6[0] or 0.0),
                "Crs": float(line2[1] or 0.0),
                "Crc": float(line5[1] or 0.0),
                "Cus": float(line3[2] or 0.0),
                "Cuc": float(line3[0] or 0.0),
                "Cis": float(line4[3] or 0.0),
                "Cic": float(line4[1] or 0.0),
                "af0": float(line0[0] or 0.0),
                "af1": float(line0[1] or 0.0),
                "af2": float(line0[2] or 0.0),
                "TGD1": float(line7[2] or 0.0),
                "TGD2": float(line7[3] or 0.0),
                "ura": int(round(line7[0] or 0.0)),
                "health": int(round(line7[1] or 0.0)),
                "transmission_time": float(line8[0] or 0.0),
            }

        if system == "I":
            line2, line3, line4, line5, line6, line7, _line8 = values[1:8]
            return {
                "system": "IRNSS",
                "satellite_id": satellite_id,
                "PRN": prn,
                "week": int(round(line6[2] or toc_week)),
                "toe": float(line4[0] or 0.0),
                "toc": float(toc_sow),
                "iode": int(round(line2[0] or 0.0)),
                "a": float(line3[3] or 0.0) ** 2,
                "sqrt_a": float(line3[3] or 0.0),
                "e": float(line3[1] or 0.0),
                "M0": float(line2[3] or 0.0),
                "omega": float(line5[2] or 0.0),
                "Omega0": float(line4[2] or 0.0),
                "i0": float(line5[0] or 0.0),
                "delta_n": float(line2[2] or 0.0),
                "Omega_dot": float(line5[3] or 0.0),
                "idot": float(line6[0] or 0.0),
                "Crs": float(line2[1] or 0.0),
                "Crc": float(line5[1] or 0.0),
                "Cus": float(line3[2] or 0.0),
                "Cuc": float(line3[0] or 0.0),
                "Cis": float(line4[3] or 0.0),
                "Cic": float(line4[1] or 0.0),
                "af0": float(line0[0] or 0.0),
                "af1": float(line0[1] or 0.0),
                "af2": float(line0[2] or 0.0),
                "TGD": float(line7[2] or 0.0),
                "ura": int(round(line7[0] or 0.0)),
                "health": int(round(line7[1] or 0.0)),
            }

        if system == "R":
            line2, line3, line4 = values[1:4]
            return {
                "system": "GLONASS",
                "satellite_id": satellite_id,
                "PRN": prn,
                "slot_number": prn,
                "frequency_channel": int(round(line3[3] or 0.0)),
                "tb": float(toc_sow),
                "tk": float(toc_sow),
                "tb_seconds": float(toc_sow % (24 * 3600)),
                "X": float(line2[0] or 0.0),
                "Y": float(line3[0] or 0.0),
                "Z": float(line4[0] or 0.0),
                "Vx": float(line2[1] or 0.0),
                "Vy": float(line3[1] or 0.0),
                "Vz": float(line4[1] or 0.0),
                "Ax": float(line2[2] or 0.0),
                "Ay": float(line3[2] or 0.0),
                "Az": float(line4[2] or 0.0),
                "tau_n": float(line0[0] or 0.0),
                "gamma_n": float(line0[1] or 0.0),
                "health": int(round(line2[3] or 0.0)),
            }

        return None

    @staticmethod
    def _load_sp3(path: str) -> dict[str, list[tuple[float, np.ndarray, float | None]]]:
        if np is None:
            raise RuntimeError("numpy is required for SP3 loading.")
        records: dict[str, list[tuple[float, np.ndarray, float | None]]] = defaultdict(list)
        current_abs_time: float | None = None

        with _open_text(path) as handle:
            for raw_line in handle:
                line = raw_line.rstrip("\n")
                if line.startswith("*"):
                    parts = line[1:].split()
                    if len(parts) >= 6:
                        epoch = _build_datetime(
                            int(parts[0]),
                            int(parts[1]),
                            int(parts[2]),
                            int(parts[3]),
                            int(parts[4]),
                            float(parts[5]),
                        )
                        _, gps_week, gps_sow = _timescale_to_utc_and_gps(epoch, "GPS")
                        current_abs_time = gps_week * SECONDS_PER_WEEK + gps_sow
                elif line.startswith("P") and current_abs_time is not None:
                    satellite_id = line[1:4].strip().upper()
                    try:
                        position = np.array(
                            [
                                float(line[4:18]) * 1000.0,
                                float(line[18:32]) * 1000.0,
                                float(line[32:46]) * 1000.0,
                            ],
                            dtype=float,
                        )
                        clock_us = float(line[46:60])
                    except ValueError:
                        continue

                    clock_seconds = None if abs(clock_us) >= 999999.0 else clock_us * 1e-6
                    records[satellite_id].append((current_abs_time, position, clock_seconds))

        return {sat_id: values for sat_id, values in records.items() if values}

    def get_ephemeris(self, satellite_id: str) -> dict | None:
        if self.kind != "broadcast":
            return None
        return self.broadcast_ephemeris.get_ephemeris(satellite_id)

    def get_state(
        self,
        satellite_id: str,
        gps_week: int,
        gps_sow: float,
        pseudorange_m: float | None = None,
    ) -> SatelliteEphemerisState | None:
        if self.kind == "broadcast":
            eph = self.broadcast_ephemeris.get_ephemeris(satellite_id)
            if eph is None:
                return None

            transmission_time = float(gps_sow)
            if pseudorange_m is not None and float(pseudorange_m) > 0.0:
                transmission_time -= float(pseudorange_m) / LIGHT_SPEED
            transmission_time %= SECONDS_PER_WEEK

            built = _build_be2pos_input(eph)
            if built is None:
                return None
            sys_type, payload = built
            from realtime_ekf_gnssir._vendor.rt_ntrip_rinex_service.BE2pos import brdc2pos

            position = brdc2pos(payload, sys_type, transmission_time)
            if position is None:
                return None

            if np is None:
                position_value = [float(item) for item in position]
            else:
                position_value = np.asarray(position, dtype=float)

            return SatelliteEphemerisState(
                position_ecef_m=position_value,
                clock_correction_s=_compute_broadcast_clock(eph, transmission_time),
                source="broadcast",
            )

        if np is None:
            raise RuntimeError("numpy is required for precise ephemeris interpolation.")
        target_time = gps_week * SECONDS_PER_WEEK + float(gps_sow)
        if pseudorange_m is not None and float(pseudorange_m) > 0.0:
            target_time -= float(pseudorange_m) / LIGHT_SPEED
        return self._interpolate_precise_state(satellite_id, target_time)

    def _interpolate_precise_state(self, satellite_id: str, target_time: float) -> SatelliteEphemerisState | None:
        records = self.precise_records.get(satellite_id)
        times = self._precise_times.get(satellite_id)
        if not records or not times:
            return None

        insert_index = bisect_left(times, target_time)
        if insert_index < len(times) and abs(times[insert_index] - target_time) < 1e-6:
            _time_value, position, clock = records[insert_index]
            return SatelliteEphemerisState(
                position_ecef_m=np.asarray(position, dtype=float),
                clock_correction_s=float(clock or 0.0),
                source="precise",
            )

        if insert_index == 0 or insert_index >= len(times):
            return None

        left_time, left_position, left_clock = records[insert_index - 1]
        right_time, right_position, right_clock = records[insert_index]
        span = right_time - left_time
        if span <= 0.0:
            return None

        weight = (target_time - left_time) / span
        position = np.asarray(left_position, dtype=float) * (1.0 - weight) + np.asarray(right_position, dtype=float) * weight

        if left_clock is None or right_clock is None:
            clock_value = left_clock if left_clock is not None else right_clock
        else:
            clock_value = (1.0 - weight) * float(left_clock) + weight * float(right_clock)

        return SatelliteEphemerisState(
            position_ecef_m=position,
            clock_correction_s=float(clock_value or 0.0),
            source="precise",
        )


class RinexObservationReader:
    """Stream observation epochs from a RINEX observation file."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self.metadata = read_rinex_observation_header(self.path)

    def iter_epochs(
        self,
        ephemeris_provider: FileEphemerisProvider | None = None,
        receiver_position_ecef: Iterable[float] | None = None,
        target_systems: Iterable[str] | None = None,
    ) -> Iterable[EpochObservation]:
        allowed_systems = {item.upper() for item in target_systems} if target_systems else None

        receiver_position: list[float] | None = None
        if receiver_position_ecef is not None:
            receiver_position = _coerce_receiver_position(receiver_position_ecef)
        elif self.metadata.has_nonzero_approx_position:
            receiver_position = _coerce_receiver_position(self.metadata.approx_position_ecef)

        if receiver_position is not None and not _has_nonzero_position(receiver_position):
            receiver_position = None

        with _open_text(self.path) as handle:
            _parse_obs_header(handle)

            while True:
                epoch_line = handle.readline()
                if not epoch_line:
                    break

                epoch_header = _parse_epoch_header(epoch_line)
                if epoch_header is None:
                    continue

                epoch_dt, flag, satellite_count = epoch_header
                utc_dt, gps_week, gps_sow = _timescale_to_utc_and_gps(epoch_dt, self.metadata.time_system)
                epoch = EpochObservation(gps_time=gps_sow, utc_datetime=utc_dt)
                skip_epoch = flag not in (0, 1)

                for _ in range(satellite_count):
                    observation_line = handle.readline()
                    if not observation_line:
                        break
                    satellite_id = observation_line[:3].strip().upper()
                    obs_types = self.metadata.sys_obs_types.get(satellite_id[:1], [])
                    raw_fields = _read_observation_record_payload(handle, observation_line, len(obs_types))

                    if skip_epoch or not satellite_id or not obs_types:
                        continue
                    if allowed_systems is not None and satellite_id[0] not in allowed_systems:
                        continue

                    sat_state = _build_satellite_state(satellite_id, obs_types, raw_fields)
                    if sat_state is None:
                        continue

                    if ephemeris_provider is not None:
                        pseudorange = _choose_best_pseudorange(sat_state.signals)
                        state = ephemeris_provider.get_state(
                            satellite_id,
                            gps_week=gps_week,
                            gps_sow=gps_sow,
                            pseudorange_m=pseudorange,
                        )
                        if state is not None:
                            if hasattr(state.position_ecef_m, "tolist"):
                                sat_state.sat_pos_ecef = state.position_ecef_m.tolist()
                            else:
                                sat_state.sat_pos_ecef = list(state.position_ecef_m)
                            sat_state.sat_clk_corr = float(state.clock_correction_s)
                            sat_state.sat_var = 0.0
                            if receiver_position is not None:
                                from .geo_utils import calculate_az_el

                                azimuth, elevation = calculate_az_el(state.position_ecef_m, receiver_position)
                                sat_state.azimuth = float(azimuth)
                                sat_state.elevation = float(elevation)

                    epoch.satellites[satellite_id] = sat_state

                if epoch.satellites:
                    yield epoch


__all__ = [
    "FileEphemerisProvider",
    "RinexObservationMetadata",
    "RinexObservationReader",
    "SatelliteEphemerisState",
    "read_rinex_observation_header",
]
