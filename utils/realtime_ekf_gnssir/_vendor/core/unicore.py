"""Unicore proprietary raw observation message support.

The N4 high-precision receivers can output raw observations as ASCII logs
(``#OBSVMA,...``) or binary logs (``AA 44 B5 ...``).  This module decodes the
raw-observation families used by the RINEX pipeline:

* ``OBSVM`` / ``OBSVMCMP``: main antenna observations
* ``OBSVH`` / ``OBSVHCMP``: secondary antenna observations
* ``OBSVBASE``: base-station observations received by the receiver
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import re
import struct
from typing import Iterable

from .data_models import EpochObservation, SatelliteState, SignalData
from .geo_utils import CLIGHT, get_freq
from .gnss_time import GNSSTime


UNICORE_BINARY_SYNC = b"\xaa\x44\xb5"
UNICORE_BINARY_HEADER_LENGTH = 24
GPS_WEEK_SECONDS = 7 * 24 * 3600
BDS_GPS_WEEK_OFFSET = 1356
BDS_TO_GPS_SECONDS = 14.0


class UnicoreParseError(ValueError):
    """Raised when a Unicore frame is structurally invalid."""


@dataclass(frozen=True)
class UnicoreMessageInfo:
    identity: str
    message_id: int
    compressed: bool
    antenna: str


UNICORE_OBSERVATION_MESSAGES: dict[str, UnicoreMessageInfo] = {
    "OBSVM": UnicoreMessageInfo("OBSVM", 12, False, "master"),
    "OBSVH": UnicoreMessageInfo("OBSVH", 13, False, "slave"),
    "OBSVMCMP": UnicoreMessageInfo("OBSVMCMP", 138, True, "master"),
    "OBSVHCMP": UnicoreMessageInfo("OBSVHCMP", 139, True, "slave"),
    "OBSVBASE": UnicoreMessageInfo("OBSVBASE", 284, False, "base"),
}

_MESSAGE_ID_TO_INFO = {info.message_id: info for info in UNICORE_OBSERVATION_MESSAGES.values()}

_PSR_STD_BY_INDEX = (
    0.050,
    0.075,
    0.113,
    0.169,
    0.253,
    0.380,
    0.570,
    0.854,
    1.281,
    2.375,
    4.750,
    9.500,
    19.000,
    38.000,
    76.000,
    152.000,
)

_SYSTEM_BY_TRACKING_CODE = {
    0: "G",
    1: "R",
    2: "S",
    3: "E",
    4: "C",
    5: "J",
    6: "I",
}

_DEFAULT_SIGNAL_BY_SYSTEM = {
    "G": "1C",
    "R": "1C",
    "S": "1C",
    "E": "1C",
    "C": "2I",
    "J": "1C",
    "I": "5A",
}

_SIGNAL_BY_SYSTEM_AND_TRACKING_CODE = {
    "G": {
        0: "1C",
        3: "1L",
        6: "5I",
        9: "2W",
        11: "1S",
        14: "5Q",
        17: "2L",
    },
    "R": {
        0: "1C",
        5: "2C",
        6: "3I",
        7: "3Q",
    },
    "S": {
        0: "1C",
        6: "5I",
    },
    "E": {
        1: "1B",
        2: "1C",
        12: "5Q",
        17: "7Q",
        18: "6B",
        22: "6C",
    },
    "C": {
        0: "2I",
        4: "2Q",
        5: "7Q",
        6: "6Q",
        8: "1P",
        12: "5P",
        13: "7I",
        17: "7I",
        21: "6I",
        23: "1D",
        28: "5D",
    },
    "J": {
        0: "1C",
        1: "1B",
        3: "1L",
        4: "1Z",
        6: "5I",
        11: "1S",
        14: "5Q",
        17: "2L",
        21: "6S",
        27: "6L",
    },
    "I": {
        6: "5I",
        14: "5Q",
    },
}


@dataclass(slots=True)
class UnicoreHeader:
    message_name: str
    message_format: str
    cpu_idle: int = 0
    message_id: int | None = None
    message_length: int = 0
    time_ref: str | int = "GPS"
    time_status: str | int = "UNKNOWN"
    week: int = 0
    milliseconds: int = 0
    version: int = 0
    reserved: int = 0
    leap_seconds: int = 18
    delay_ms: int = 0


@dataclass(slots=True)
class UnicoreObservationRecord:
    system_freq: int
    raw_prn: int
    pseudorange: float
    phase: float
    psr_std: float
    adr_std: float
    doppler: float
    cn0: float
    lock_time: float
    tracking_status: int
    sys_id: str
    prn: int
    signal_id: str
    antenna: str
    compressed: bool

    @property
    def satellite_id(self) -> str:
        return f"{self.sys_id}{self.prn:02d}"

    @property
    def glonass_fcn(self) -> int:
        return int(self.system_freq) - 7 if self.sys_id == "R" else 0


@dataclass(slots=True)
class UnicoreMessage:
    identity: str
    header: UnicoreHeader
    records: list[UnicoreObservationRecord] = field(default_factory=list)
    raw: bytes = b""
    crc_ok: bool | None = None
    compressed: bool = False
    antenna: str = "master"
    protocol: str = "UNICORE"
    source: str = "UNICORE"

    @classmethod
    def parse_frame(cls, frame: bytes) -> "UnicoreMessage":
        if frame.startswith(b"#"):
            return cls.parse_ascii(frame)
        if frame.startswith(UNICORE_BINARY_SYNC):
            return cls.parse_binary(frame)
        raise UnicoreParseError("Not a Unicore frame")

    @classmethod
    def parse_ascii(cls, frame: bytes | str) -> "UnicoreMessage":
        raw = frame.encode("ascii", errors="ignore") if isinstance(frame, str) else bytes(frame)
        line = raw.strip()
        if not line.startswith(b"#"):
            raise UnicoreParseError("ASCII Unicore frame must start with #")

        crc_ok: bool | None = None
        payload = line[1:]
        star_index = payload.rfind(b"*")
        if star_index >= 0:
            crc_bytes = payload[star_index + 1 : star_index + 9]
            if len(crc_bytes) < 8 or not re.fullmatch(rb"[0-9A-Fa-f]{8}", crc_bytes):
                raise UnicoreParseError("ASCII Unicore frame has an invalid CRC field")
            expected_crc = int(crc_bytes.decode("ascii"), 16)
            actual_crc = unicore_crc32(payload[:star_index])
            crc_ok = actual_crc == expected_crc
            if not crc_ok:
                raise UnicoreParseError("ASCII Unicore frame failed CRC")
            payload = payload[:star_index]

        try:
            header_blob, data_blob = payload.split(b";", 1)
        except ValueError as exc:
            raise UnicoreParseError("ASCII Unicore frame is missing ';' separator") from exc

        header_parts = [part.decode("ascii", errors="ignore").strip() for part in header_blob.split(b",")]
        if not header_parts or not header_parts[0]:
            raise UnicoreParseError("ASCII Unicore frame has an empty message name")

        raw_name = header_parts[0].lstrip("#").upper()
        identity = normalize_unicore_message_name(raw_name)
        info = UNICORE_OBSERVATION_MESSAGES.get(identity)
        if info is None:
            raise UnicoreParseError(f"Unsupported Unicore observation message: {raw_name}")

        header = UnicoreHeader(
            message_name=identity,
            message_format="ASCII",
            cpu_idle=_parse_int(header_parts, 1),
            message_id=info.message_id,
            time_ref=_parse_text(header_parts, 2, "GPS"),
            time_status=_parse_text(header_parts, 3, "UNKNOWN"),
            week=_parse_int(header_parts, 4),
            milliseconds=_parse_int(header_parts, 5),
            version=_parse_int(header_parts, 6),
            reserved=_parse_int(header_parts, 7),
            leap_seconds=_parse_int(header_parts, 8, 18),
            delay_ms=_parse_int(header_parts, 9),
        )

        data_text = data_blob.decode("ascii", errors="ignore").strip()
        records = _parse_ascii_records(data_text, info)
        return cls(
            identity=identity,
            header=header,
            records=records,
            raw=raw,
            crc_ok=crc_ok,
            compressed=info.compressed,
            antenna=info.antenna,
        )

    @classmethod
    def parse_binary(cls, frame: bytes) -> "UnicoreMessage":
        raw = bytes(frame)
        if len(raw) < UNICORE_BINARY_HEADER_LENGTH + 4:
            raise UnicoreParseError("Binary Unicore frame is too short")
        if not raw.startswith(UNICORE_BINARY_SYNC):
            raise UnicoreParseError("Binary Unicore frame has invalid sync bytes")

        (
            message_id,
            message_length,
            time_ref,
            time_status,
            week,
            milliseconds,
            version,
            reserved,
            leap_seconds,
            delay_ms,
        ) = struct.unpack_from("<HHBBHIIBBH", raw, 4)
        expected_length = UNICORE_BINARY_HEADER_LENGTH + message_length + 4
        if len(raw) < expected_length:
            raise UnicoreParseError("Binary Unicore frame is truncated")
        if len(raw) > expected_length:
            raw = raw[:expected_length]

        transmitted_crc = int.from_bytes(raw[-4:], "little")
        actual_crc = unicore_crc32(raw[:-4])
        if transmitted_crc != actual_crc:
            raise UnicoreParseError("Binary Unicore frame failed CRC")

        info = _MESSAGE_ID_TO_INFO.get(message_id)
        if info is None:
            raise UnicoreParseError(f"Unsupported Unicore observation message ID: {message_id}")

        body = raw[UNICORE_BINARY_HEADER_LENGTH:-4]
        header = UnicoreHeader(
            message_name=info.identity,
            message_format="BINARY",
            cpu_idle=int(raw[3]),
            message_id=message_id,
            message_length=message_length,
            time_ref=_binary_time_ref_label(time_ref),
            time_status=time_status,
            week=week,
            milliseconds=milliseconds,
            version=version,
            reserved=reserved,
            leap_seconds=leap_seconds,
            delay_ms=delay_ms,
        )
        records = _parse_binary_records(body, info)
        return cls(
            identity=info.identity,
            header=header,
            records=records,
            raw=raw,
            crc_ok=True,
            compressed=info.compressed,
            antenna=info.antenna,
        )

    def to_epoch(self, target_systems: Iterable[str] | None = None) -> EpochObservation:
        target_set = {str(system).upper()[0] for system in (target_systems or []) if str(system).strip()}
        gps_week, gps_seconds = _header_gps_time(self.header)
        utc_datetime = GNSSTime.gps_to_utc_datetime(gps_week, gps_seconds)
        epoch = EpochObservation(gps_time=gps_seconds % GPS_WEEK_SECONDS, utc_datetime=utc_datetime)
        setattr(epoch, "source_protocol", self.protocol)
        setattr(epoch, "source_message", self.identity)
        setattr(epoch, "receiver_antenna", self.antenna)

        for record in self.records:
            if target_set and record.sys_id not in target_set:
                continue
            sat_key = record.satellite_id
            sat_state = epoch.satellites.get(sat_key)
            if sat_state is None:
                sat_state = SatelliteState(record.sys_id, record.prn)
                setattr(sat_state, "receiver_antenna", record.antenna)
                epoch.satellites[sat_key] = sat_state

            has_range = _tracking_pseudorange_valid(record.tracking_status) and record.pseudorange > 0.0
            has_phase = _tracking_phase_valid(record.tracking_status) and record.phase != 0.0
            if not (has_range or has_phase or record.cn0 > 0.0):
                continue

            signal = SignalData(
                signal_id=record.signal_id,
                pseudorange=float(record.pseudorange if has_range else 0.0),
                phase=float(record.phase if has_phase else 0.0),
                snr=float(record.cn0),
                lock_time=int(round(record.lock_time)),
                half_cycle=0,
                doppler=float(record.doppler),
            )
            setattr(signal, "receiver_antenna", record.antenna)
            setattr(signal, "tracking_status", record.tracking_status)
            setattr(signal, "glonass_fcn", record.glonass_fcn)
            sat_state.signals[record.signal_id] = signal

        return epoch


def normalize_unicore_message_name(raw_name: str) -> str:
    name = str(raw_name or "").strip().upper()
    if name in UNICORE_OBSERVATION_MESSAGES:
        return name
    if name.endswith(("A", "B")) and name[:-1] in UNICORE_OBSERVATION_MESSAGES:
        return name[:-1]
    return name


def is_unicore_ascii_candidate(prefix: bytes) -> bool:
    return prefix == b"#"


def is_unicore_binary_candidate(prefix: bytes) -> bool:
    return prefix == UNICORE_BINARY_SYNC[:1]


def unicore_crc32(data: bytes) -> int:
    """Return the Unicore/NovAtel CRC-32 value (init 0, no final xor)."""
    crc = 0
    for value in bytes(data):
        byte = value
        for _ in range(8):
            if (crc ^ byte) & 1:
                crc = (crc >> 1) ^ 0xEDB88320
            else:
                crc >>= 1
            byte >>= 1
    return crc & 0xFFFFFFFF


def build_unicore_binary_frame(
    message_id: int,
    body: bytes,
    *,
    cpu_idle: int = 90,
    time_ref: int = 1,
    time_status: int = 1,
    week: int = 0,
    milliseconds: int = 0,
    version: int = 0,
    reserved: int = 0,
    leap_seconds: int = 18,
    delay_ms: int = 0,
) -> bytes:
    """Build a CRC-protected binary Unicore frame, mainly for tests/tools."""
    header = bytearray(UNICORE_BINARY_SYNC)
    header.extend(bytes([int(cpu_idle) & 0xFF]))
    header.extend(
        struct.pack(
            "<HHBBHIIBBH",
            int(message_id),
            len(body),
            int(time_ref) & 0xFF,
            int(time_status) & 0xFF,
            int(week) & 0xFFFF,
            int(milliseconds) & 0xFFFFFFFF,
            int(version) & 0xFFFFFFFF,
            int(reserved) & 0xFF,
            int(leap_seconds) & 0xFF,
            int(delay_ms) & 0xFFFF,
        )
    )
    frame = bytes(header) + bytes(body)
    return frame + unicore_crc32(frame).to_bytes(4, "little")


def _parse_ascii_records(data_text: str, info: UnicoreMessageInfo) -> list[UnicoreObservationRecord]:
    if not data_text:
        return []
    parts = [part.strip() for part in data_text.split(",")]
    if not parts or parts[0] == "":
        return []
    obs_count = int(parts[0], 0)
    records: list[UnicoreObservationRecord] = []
    if obs_count <= 0:
        return records

    if info.compressed:
        for record_hex in parts[1 : 1 + obs_count]:
            cleaned = "".join(record_hex.split())
            if not cleaned:
                continue
            records.append(_decode_compressed_record(bytes.fromhex(cleaned), info))
        return records

    record_width = 11
    expected_values = min(len(parts) - 1, obs_count * record_width)
    for offset in range(1, 1 + expected_values, record_width):
        chunk = parts[offset : offset + record_width]
        if len(chunk) < record_width:
            break
        records.append(_decode_uncompressed_record(chunk, info))
    return records


def _parse_binary_records(body: bytes, info: UnicoreMessageInfo) -> list[UnicoreObservationRecord]:
    if len(body) < 4:
        return []
    obs_count = struct.unpack_from("<I", body, 0)[0]
    records: list[UnicoreObservationRecord] = []
    if obs_count <= 0:
        return records

    if info.compressed:
        offset = 4
        for _ in range(obs_count):
            chunk = body[offset : offset + 24]
            if len(chunk) < 24:
                break
            records.append(_decode_compressed_record(chunk, info))
            offset += 24
        return records

    offset = 4
    record_size = struct.calcsize("<HHddHHfHHfI")
    for _ in range(obs_count):
        chunk = body[offset : offset + record_size]
        if len(chunk) < record_size:
            break
        values = struct.unpack("<HHddHHfHHfI", chunk)
        records.append(_decode_uncompressed_record(values, info))
        offset += record_size
    return records


def _decode_uncompressed_record(values, info: UnicoreMessageInfo) -> UnicoreObservationRecord:
    system_freq = int(values[0])
    raw_prn = int(values[1])
    pseudorange = float(values[2])
    phase = float(values[3])
    psr_std = float(values[4]) / 100.0
    adr_std = float(values[5]) / 10000.0
    doppler = float(values[6])
    cn0 = float(values[7]) / 100.0
    lock_time = float(values[9])
    tracking_status = _parse_tracking_status(values[10])
    return _build_record(
        system_freq=system_freq,
        raw_prn=raw_prn,
        pseudorange=pseudorange,
        phase=phase,
        psr_std=psr_std,
        adr_std=adr_std,
        doppler=doppler,
        cn0=cn0,
        lock_time=lock_time,
        tracking_status=tracking_status,
        info=info,
    )


def _decode_compressed_record(record: bytes, info: UnicoreMessageInfo) -> UnicoreObservationRecord:
    if len(record) != 24:
        raise UnicoreParseError("Compressed Unicore observation record must be 24 bytes")
    value = int.from_bytes(record, "little", signed=False)
    tracking_status = _extract_unsigned(value, 0, 32)
    doppler = _extract_signed(value, 32, 28) / 256.0
    pseudorange = _extract_unsigned(value, 60, 36) / 128.0
    raw_phase = _extract_signed(value, 96, 32) / 256.0
    psr_std_index = _extract_unsigned(value, 128, 4)
    adr_std_index = _extract_unsigned(value, 132, 4)
    raw_prn = _extract_unsigned(value, 136, 8)
    lock_time = _extract_unsigned(value, 144, 21) / 32.0
    cn0 = 20.0 + _extract_unsigned(value, 165, 5)
    system_freq = _extract_unsigned(value, 170, 6)

    sys_id = _system_from_record(tracking_status, raw_prn)
    prn = _normalize_prn(sys_id, raw_prn)
    signal_id = _signal_id_from_tracking(sys_id, tracking_status)
    fcn = system_freq - 7 if sys_id == "R" else 0
    phase = _unwrap_compressed_phase(raw_phase, pseudorange, sys_id, prn, signal_id, fcn)

    return UnicoreObservationRecord(
        system_freq=system_freq,
        raw_prn=raw_prn,
        pseudorange=pseudorange,
        phase=phase,
        psr_std=_PSR_STD_BY_INDEX[psr_std_index],
        adr_std=(adr_std_index + 1) / 512.0,
        doppler=doppler,
        cn0=cn0,
        lock_time=lock_time,
        tracking_status=tracking_status,
        sys_id=sys_id,
        prn=prn,
        signal_id=signal_id,
        antenna=info.antenna,
        compressed=True,
    )


def _build_record(
    *,
    system_freq: int,
    raw_prn: int,
    pseudorange: float,
    phase: float,
    psr_std: float,
    adr_std: float,
    doppler: float,
    cn0: float,
    lock_time: float,
    tracking_status: int,
    info: UnicoreMessageInfo,
) -> UnicoreObservationRecord:
    sys_id = _system_from_record(tracking_status, raw_prn)
    prn = _normalize_prn(sys_id, raw_prn)
    signal_id = _signal_id_from_tracking(sys_id, tracking_status)
    return UnicoreObservationRecord(
        system_freq=system_freq,
        raw_prn=raw_prn,
        pseudorange=pseudorange,
        phase=phase,
        psr_std=psr_std,
        adr_std=adr_std,
        doppler=doppler,
        cn0=cn0,
        lock_time=lock_time,
        tracking_status=tracking_status,
        sys_id=sys_id,
        prn=prn,
        signal_id=signal_id,
        antenna=info.antenna,
        compressed=False,
    )


def _tracking_pseudorange_valid(tracking_status: int) -> bool:
    return bool(int(tracking_status) & 0x00001000)


def _tracking_phase_valid(tracking_status: int) -> bool:
    return bool(int(tracking_status) & 0x00000400)


def _system_from_record(tracking_status: int, raw_prn: int) -> str:
    sys_code = (int(tracking_status) >> 16) & 0x7
    sys_id = _SYSTEM_BY_TRACKING_CODE.get(sys_code)
    if sys_id is not None:
        return sys_id
    return _infer_system_from_prn(raw_prn)


def _infer_system_from_prn(raw_prn: int) -> str:
    prn = int(raw_prn)
    if 193 <= prn <= 202 or 33 <= prn <= 42:
        return "J"
    if 161 <= prn <= 223:
        return "C"
    if 120 <= prn <= 158:
        return "S"
    if 75 <= prn <= 110:
        return "E"
    if 67 <= prn <= 74 or 111 <= prn <= 117:
        return "I"
    if 38 <= prn <= 66:
        return "R"
    return "G"


def _normalize_prn(sys_id: str, raw_prn: int) -> int:
    prn = int(raw_prn)
    if sys_id == "R" and prn >= 38:
        return prn - 37
    if sys_id == "J":
        if 193 <= prn <= 202:
            return prn - 192
        if 33 <= prn <= 42:
            return prn - 32
    if sys_id == "C" and prn >= 161:
        return prn - 160
    if sys_id == "S" and prn >= 120:
        return prn - 100
    if sys_id == "E" and prn >= 75:
        return prn - 74
    if sys_id == "I":
        if 67 <= prn <= 74:
            return prn - 66
        if 111 <= prn <= 117:
            return prn - 102
    return prn


def _signal_id_from_tracking(sys_id: str, tracking_status: int) -> str:
    signal_code = (int(tracking_status) >> 21) & 0x1F
    if sys_id == "G" and signal_code == 9 and ((int(tracking_status) >> 26) & 1):
        return "2L"
    return _SIGNAL_BY_SYSTEM_AND_TRACKING_CODE.get(sys_id, {}).get(
        signal_code,
        _DEFAULT_SIGNAL_BY_SYSTEM.get(sys_id, "1C"),
    )


def _unwrap_compressed_phase(
    phase_cycles: float,
    pseudorange: float,
    sys_id: str,
    prn: int,
    signal_id: str,
    fcn: int,
) -> float:
    if pseudorange <= 0.0:
        return phase_cycles
    sat_key = f"{sys_id}{prn:02d}"
    frequency, _ = get_freq(signal_id, sat_key, fcn)
    if frequency <= 0.0:
        return phase_cycles
    approximate_cycles = pseudorange * frequency / CLIGHT
    cycle_modulus = (2**32) / 256.0
    wraps = round((approximate_cycles - phase_cycles) / cycle_modulus)
    return phase_cycles + wraps * cycle_modulus


def _extract_unsigned(value: int, offset: int, width: int) -> int:
    return (int(value) >> offset) & ((1 << width) - 1)


def _extract_signed(value: int, offset: int, width: int) -> int:
    raw = _extract_unsigned(value, offset, width)
    sign_bit = 1 << (width - 1)
    if raw & sign_bit:
        return raw - (1 << width)
    return raw


def _parse_tracking_status(value) -> int:
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return 0
    if text.lower().startswith("0x"):
        return int(text, 16)
    return int(text, 16)


def _parse_int(parts: list[str], index: int, default: int = 0) -> int:
    if index >= len(parts):
        return default
    text = str(parts[index]).strip()
    if not text:
        return default
    try:
        return int(float(text))
    except ValueError:
        return default


def _parse_text(parts: list[str], index: int, default: str) -> str:
    if index >= len(parts):
        return default
    text = str(parts[index]).strip()
    return text or default


def _binary_time_ref_label(value: int) -> str:
    return {0: "UNKNOWN", 1: "GPS", 2: "BDS"}.get(int(value), str(int(value)))


def _header_gps_time(header: UnicoreHeader) -> tuple[int, float]:
    seconds = float(header.milliseconds) / 1000.0
    time_ref = str(header.time_ref).strip().upper()
    if time_ref in {"BDS", "BDST", "BD"}:
        return int(header.week) + BDS_GPS_WEEK_OFFSET, seconds + BDS_TO_GPS_SECONDS
    return int(header.week), seconds


def current_unicore_ascii_crc(frame_without_crc: str) -> str:
    """Return an 8-hex CRC for a frame body, excluding leading '#'.

    This helper is intentionally small and useful in fixtures where constructing
    a valid ASCII Unicore line by hand would be noisy.
    """
    payload = frame_without_crc[1:] if frame_without_crc.startswith("#") else frame_without_crc
    return f"{unicore_crc32(payload.encode('ascii')):08x}"
