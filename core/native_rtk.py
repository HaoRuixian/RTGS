"""Native real-time RTK process adapter.

This module starts ``rtkrcv`` with the original rover/base streams and
translates its solution stream into RTGS positioning models.
"""

from __future__ import annotations

import math
import os
import queue
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np

from core.geo_utils import ecef2lla
from core.gnss_time import GNSSTime
from core.positioning_models import PositioningMode, PositioningSolution, SolutionStatus


class RTKConfigurationError(ValueError):
    """Raised when an RTK stream or processing setting is incomplete."""


QUALITY_LABELS = {
    0: "No solution",
    1: "RTK Fixed",
    2: "RTK Float",
    3: "SBAS",
    4: "DGPS/DGNSS",
    5: "Single",
    6: "PPP",
    7: "Dead reckoning",
}

_FORMAT_ALIASES = {
    "rtcm2": "rtcm2",
    "rtcm 2": "rtcm2",
    "rtcm3": "rtcm3",
    "rtcm 3": "rtcm3",
    "ubx": "ubx",
    "u-blox ubx": "ubx",
    "unicore": "unicore",
    "novatel oem4": "oem4",
    "oem4": "oem4",
    "novatel oem7": "oem4",
    "septentrio sbf": "sbf",
    "sbf": "sbf",
    "rinex": "rinex",
    "sp3": "sp3",
}

_NAVSYS_BITS = {"G": 1, "S": 2, "R": 4, "E": 8, "J": 16, "C": 32, "I": 64}


def _as_mapping(settings: Any) -> Mapping[str, Any]:
    if settings is None:
        return {}
    if isinstance(settings, Mapping):
        return settings
    if is_dataclass(settings):
        return asdict(settings)
    return vars(settings)


def _text(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if "\n" in result or "\r" in result:
        raise RTKConfigurationError(f"{field} contains an invalid line break")
    return result


def redact_sensitive_text(message: str) -> str:
    """Redact credentials embedded in NTRIP paths and configuration lines."""
    text = str(message)
    text = re.sub(
        r"(?P<user>[^\s/:=@]+):(?P<password>[^\s]*)@(?P<host>[^\s/]+)",
        lambda match: f"{match.group('user')}:***@{match.group('host')}",
        text,
    )
    text = re.sub(r"(?i)(password\s*[=:]\s*)\S+", r"\1***", text)
    return text


def find_rtkrcv(explicit_path: str | os.PathLike[str] | None = None) -> Path:
    """Locate an executable ``rtkrcv`` without modifying external files."""
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path).expanduser())
    for env_name in ("RTGS_RTKRCV", "RTK_ENGINE_RTKRCV"):
        if os.environ.get(env_name):
            candidates.append(Path(os.environ[env_name]).expanduser())

    which = shutil.which("rtkrcv")
    if which:
        candidates.append(Path(which))

    project_root = Path(__file__).resolve().parents[1]
    candidates.extend(
        [
            project_root / "bin" / "rtkrcv",
        ]
    )
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    raise FileNotFoundError("rtkrcv was not found. Add it to PATH or set RTGS_RTKRCV.")


def _rtk_input_format(settings: Mapping[str, Any], default: str = "rtcm3") -> str:
    value = _text(
        settings.get("data_format") or settings.get("format") or default,
        "stream format",
    ).lower()
    normalized = _FORMAT_ALIASES.get(value)
    if normalized is None:
        supported = ", ".join(sorted(set(_FORMAT_ALIASES.values())))
        raise RTKConfigurationError(f"Unsupported RTK input format '{value}' ({supported})")
    return normalized


def _ntrip_path(settings: Mapping[str, Any], label: str) -> str:
    host = _text(settings.get("host"), f"{label} host")
    port = _text(settings.get("port") or "2101", f"{label} port")
    mountpoint = _text(settings.get("mountpoint"), f"{label} mountpoint").lstrip("/")
    user = _text(settings.get("user"), f"{label} user")
    password = _text(settings.get("password"), f"{label} password")
    if not host or not mountpoint:
        raise RTKConfigurationError(f"{label} NTRIP host and mountpoint are required")
    auth = f"{user}:{password}@" if user else ""
    return f"{auth}{host}:{port}/{mountpoint}"


def _serial_path(settings: Mapping[str, Any], label: str) -> str:
    device = _text(settings.get("serial_port") or settings.get("port"), f"{label} serial port")
    if not device:
        raise RTKConfigurationError(f"{label} serial port is required")
    baud = int(settings.get("baudrate") or 115200)
    databits = int(settings.get("databits") or 8)
    stopbits = float(settings.get("stopbits") or 1)
    parity = {"none": "n", "even": "e", "odd": "o"}.get(
        str(settings.get("parity") or "None").lower(), "n"
    )
    flow = {
        "none": "off",
        "rts/cts": "rts",
        "xon/xoff": "xon",
    }.get(str(settings.get("flowctrl") or "None").lower(), "off")
    stop = str(int(stopbits)) if stopbits.is_integer() else str(stopbits)
    return f"{device}:{baud}:{databits}:{parity}:{stop}:{flow}"


def stream_to_rtk_engine(
    settings: Mapping[str, Any] | Any,
    label: str,
    *,
    default_format: str = "rtcm3",
) -> tuple[str, str, str]:
    """Convert one RTGS stream to native ``type/path/format`` values."""
    values = _as_mapping(settings)
    source = _text(values.get("source_type") or values.get("source") or "NTRIP Server", f"{label} source")
    if source == "NTRIP Server":
        return "ntripcli", _ntrip_path(values, label), _rtk_input_format(values, default_format)
    if source == "Serial Port":
        return "serial", _serial_path(values, label), _rtk_input_format(values, default_format)
    if source in {"RINEX File", "File"}:
        path = _text(values.get("file_path"), f"{label} file")
        if not path:
            raise RTKConfigurationError(f"{label} input file is required")
        path = str(Path(path).expanduser().resolve())
        file_default = "sp3" if str(values.get("file_type", "")).lower().startswith("precise") else "rinex"
        file_values = dict(values)
        if str(file_values.get("data_format", "")).lower() in {"", "rtcm3", "rtcm 3"}:
            file_values["data_format"] = file_default
        return "file", path, _rtk_input_format(file_values, file_default)
    if source == "TCP Client":
        path = _text(values.get("tcp_path") or values.get("host"), f"{label} TCP path")
        if not path:
            raise RTKConfigurationError(f"{label} TCP client path is required")
        return "tcpcli", path, _rtk_input_format(values, default_format)
    raise RTKConfigurationError(f"Unsupported {label} source '{source}'")


def _ecef_from_llh(latitude_deg: float, longitude_deg: float, height_m: float) -> tuple[float, float, float]:
    lat = math.radians(latitude_deg)
    lon = math.radians(longitude_deg)
    a = 6378137.0
    e2 = 6.69437999014e-3
    sin_lat = math.sin(lat)
    radius = a / math.sqrt(1.0 - e2 * sin_lat * sin_lat)
    x = (radius + height_m) * math.cos(lat) * math.cos(lon)
    y = (radius + height_m) * math.cos(lat) * math.sin(lon)
    z = (radius * (1.0 - e2) + height_m) * sin_lat
    return x, y, z


def _valid_triplet(value: Any) -> list[float] | None:
    try:
        result = [float(item) for item in value][:3]
    except (TypeError, ValueError):
        return None
    if len(result) != 3 or not all(math.isfinite(item) for item in result):
        return None
    return result


def _valid_llh(value: Any) -> list[float] | None:
    result = _valid_triplet(value)
    if result is None or not (-90.0 <= result[0] <= 90.0 and -180.0 <= result[1] <= 180.0):
        return None
    return result


def _navsys_mask(systems: Any) -> int:
    selected = systems if isinstance(systems, (list, tuple, set)) else [systems]
    mask = 0
    for system in selected:
        mask |= _NAVSYS_BITS.get(str(system).strip().upper()[:1], 0)
    return mask or _NAVSYS_BITS["G"]


def build_rtk_engine_config(
    obs_settings: Mapping[str, Any] | Any,
    base_settings: Mapping[str, Any] | Any,
    eph_settings: Mapping[str, Any] | Any,
    positioning_settings: Mapping[str, Any] | Any,
    output_port: int,
    *,
    approx_rec_pos: Any = None,
) -> str:
    """Build an ``rtkrcv`` option file for single-base or network RTK."""
    obs = _as_mapping(obs_settings)
    base = _as_mapping(base_settings)
    eph = _as_mapping(eph_settings)
    settings = _as_mapping(positioning_settings)
    if not bool(base.get("enabled", True)):
        raise RTKConfigurationError("RTK base/network correction stream is disabled")

    rover_values = dict(obs)
    base_values = dict(base)
    rover_values["data_format"] = settings.get("rtk_rover_format", obs.get("data_format", "rtcm3"))
    base_values["data_format"] = settings.get("rtk_base_format", base.get("data_format", "rtcm3"))
    rover_type, rover_path, rover_format = stream_to_rtk_engine(rover_values, "rover")
    base_type, base_path, base_format = stream_to_rtk_engine(base_values, "base/network")

    eph_enabled = bool(eph.get("enabled", False))
    if eph_enabled:
        eph_type, eph_path, eph_format = stream_to_rtk_engine(eph, "ephemeris", default_format="rtcm3")
    else:
        eph_type, eph_path, eph_format = "off", "", "rtcm3"

    rtk_type = str(settings.get("rtk_type", "single_base")).strip().lower()
    if rtk_type not in {"single_base", "network"}:
        raise RTKConfigurationError("rtk_type must be 'single_base' or 'network'")

    rover_mode = str(settings.get("rtk_rover_mode", "kinematic")).strip().lower()
    if rover_mode not in {"kinematic", "static", "static-start", "movingbase", "fixed"}:
        rover_mode = "kinematic"
    frequency = str(settings.get("rtk_frequency", "l1+l2")).strip().lower()
    if frequency not in {"l1", "l1+l2", "l1+l2+l5", "l1+l2+l5+l6"}:
        frequency = "l1+l2"
    ar_mode = str(settings.get("rtk_ar_mode", "fix-and-hold")).strip().lower()
    if ar_mode not in {"off", "continuous", "instantaneous", "fix-and-hold"}:
        ar_mode = "fix-and-hold"
    glo_ar = str(settings.get("rtk_glonass_ar_mode", "autocal")).strip().lower()
    if glo_ar not in {"off", "on", "autocal", "fix-and-hold"}:
        glo_ar = "autocal"

    lines = [
        "console-passwd     =",
        f"inpstr1-type       ={rover_type}",
        f"inpstr2-type       ={base_type}",
        f"inpstr3-type       ={eph_type}",
        f"inpstr1-path       ={rover_path}",
        f"inpstr2-path       ={base_path}",
        f"inpstr3-path       ={eph_path}",
        f"inpstr1-format     ={rover_format}",
        f"inpstr2-format     ={base_format}",
        f"inpstr3-format     ={eph_format}",
        "outstr1-type       =tcpsvr",
        "outstr2-type       =off",
        f"outstr1-path       =:{int(output_port)}",
        "outstr1-format     =llh",
        "misc-svrcycle      =10",
        "misc-timeout       =10000",
        "misc-reconnect     =3000",
        f"misc-nmeacycle     ={int(settings.get('rtk_gga_cycle_ms', 5000))}",
        "misc-buffsize      =65536",
        "misc-navmsgsel     =all",
        f"pos1-posmode       ={rover_mode}",
        f"pos1-frequency     ={frequency}",
        "pos1-soltype       =forward",
        f"pos1-elmask        ={float(settings.get('cutoff_elevation_deg', 10.0)):.3f}",
        f"pos1-dynamics      ={'on' if settings.get('rtk_dynamics', True) else 'off'}",
        "pos1-tidecorr      =off",
        "pos1-ionoopt       =brdc",
        "pos1-tropopt       =saas",
        "pos1-sateph        =brdc",
        f"pos1-navsys        ={_navsys_mask(settings.get('gnss_systems', ['G', 'R', 'E', 'C']))}",
        f"pos2-armode         ={ar_mode}",
        f"pos2-gloarmode      ={glo_ar}",
        f"pos2-bdsarmode      ={'on' if settings.get('rtk_bds_ar', True) else 'off'}",
        f"pos2-arthres        ={float(settings.get('rtk_ar_ratio_threshold', 3.0)):.3f}",
        f"pos2-arlockcnt      ={int(settings.get('rtk_ar_lock_count', 5))}",
        f"pos2-arminfix       ={int(settings.get('rtk_ar_min_fix', 10))}",
        f"pos2-aroutcnt       ={int(settings.get('rtk_ar_outage_count', 5))}",
        f"pos2-maxage         ={float(settings.get('rtk_max_correction_age_s', 10.0)):.3f}",
        f"pos2-slipthres      ={float(settings.get('rtk_cycle_slip_threshold_m', 0.05)):.4f}",
        f"pos2-niter          ={int(settings.get('rtk_filter_iterations', 1))}",
        "out-solformat      =llh",
        "out-outhead        =off",
        "out-outopt         =off",
        "out-outvel         =on",
        "out-timesys        =gpst",
        "out-timeform       =tow",
        "out-timendec       =3",
        "out-degform        =deg",
        "out-fieldsep       =,",
        "out-height         =ellipsoidal",
        "out-outsingle      =on",
        "out-maxsolstd      =0",
        "out-solstatic      =all",
        "out-outstat        =off",
    ]

    base_source = str(settings.get("rtk_base_position_source", "rtcm")).strip().lower()
    base_position = _valid_triplet(settings.get("rtk_base_position"))
    if base_source in {"llh", "xyz"}:
        if base_source == "llh":
            base_position = _valid_llh(base_position)
        if base_position is None or (base_source == "xyz" and np.linalg.norm(base_position) < 3_000_000.0):
            raise RTKConfigurationError("Configured RTK base position requires three coordinates")
        lines.extend(
            [
                f"ant2-postype       ={base_source}",
                f"ant2-pos1          ={base_position[0]:.9f}",
                f"ant2-pos2          ={base_position[1]:.9f}",
                f"ant2-pos3          ={base_position[2]:.4f}",
            ]
        )
    else:
        lines.append("ant2-postype       =rtcm")

    gga_mode = str(settings.get("rtk_gga_mode", "auto")).strip().lower()
    if rtk_type == "network" and gga_mode != "off":
        gga_position = _valid_llh(settings.get("rtk_gga_position"))
        if gga_mode == "auto" and gga_position is not None and not any(abs(value) > 1e-9 for value in gga_position):
            gga_position = None
        if gga_position is None:
            approximate = _valid_triplet(approx_rec_pos)
            if approximate is not None and np.linalg.norm(approximate) > 3_000_000.0:
                lat, lon, height = ecef2lla(approximate)
                gga_position = [math.degrees(lat), math.degrees(lon), height]
        if gga_mode in {"configured", "auto"} and gga_position is not None:
            lines.extend(
                [
                    "inpstr2-nmeareq    =latlon",
                    f"inpstr2-nmealat    ={gga_position[0]:.9f}",
                    f"inpstr2-nmealon    ={gga_position[1]:.9f}",
                    f"inpstr2-nmeahgt    ={gga_position[2]:.4f}",
                ]
            )
        elif gga_mode == "configured":
            raise RTKConfigurationError("Configured network GGA mode requires a valid LLH position")
        else:
            lines.append("inpstr2-nmeareq    =single")
    else:
        lines.append("inpstr2-nmeareq    =off")

    return "\n".join(lines) + "\n"


def parse_rtk_engine_solution(line: str, *, reference_ecef: Any = None) -> PositioningSolution | None:
    """Parse one comma-separated RTK LLH solution line."""
    stripped = line.strip()
    if not stripped or stripped.startswith("%"):
        return None
    fields = [field.strip() for field in stripped.split(",")]
    if len(fields) < 15:
        return None
    try:
        week = int(float(fields[0]))
        tow = float(fields[1])
        latitude = float(fields[2])
        longitude = float(fields[3])
        height = float(fields[4])
        quality = int(float(fields[5]))
        satellites = int(float(fields[6]))
        std_north = abs(float(fields[7]))
        std_east = abs(float(fields[8]))
        std_up = abs(float(fields[9]))
        age = float(fields[13])
        ratio = float(fields[14])
    except (TypeError, ValueError, OverflowError):
        return None
    if not all(math.isfinite(value) for value in (tow, latitude, longitude, height, age, ratio)):
        return None
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return None

    ecef_x, ecef_y, ecef_z = _ecef_from_llh(latitude, longitude, height)
    if quality == 1:
        status = SolutionStatus.FIXED
    elif quality in {2, 3, 4, 5, 6, 7}:
        status = SolutionStatus.UNCERTAIN
    else:
        status = SolutionStatus.NO_FIX
    quality_label = QUALITY_LABELS.get(quality, f"Quality {quality}")
    epoch_time = GNSSTime.gps_to_utc_datetime(week, tow)
    solution = PositioningSolution(
        timestamp=tow,
        gps_week=week,
        epoch_time=epoch_time,
        latitude=latitude,
        longitude=longitude,
        height=height,
        ecef_x=ecef_x,
        ecef_y=ecef_y,
        ecef_z=ecef_z,
        std_north=std_north,
        std_east=std_east,
        std_up=std_up,
        gdop=math.nan,
        pdop=math.nan,
        hdop=math.nan,
        vdop=math.nan,
        tdop=math.nan,
        num_satellites=satellites,
        convergence=quality == 1,
        status=status,
        differential_age_s=age,
        ambiguity_ratio=ratio,
        rtk_quality=quality,
        mode=PositioningMode.RTK,
        solution_source=f"RTK {quality_label}",
        quality_reason=f"{quality_label}; age={age:.2f}s; ratio={ratio:.1f}",
        diagnostics={
            "rtk_quality": quality,
            "rtk_quality_label": quality_label,
            "differential_age_s": age,
            "ambiguity_ratio": ratio,
        },
    )
    if len(fields) >= 24:
        try:
            solution.velocity_north = float(fields[15])
            solution.velocity_east = float(fields[16])
            solution.velocity_up = float(fields[17])
        except (ValueError, TypeError):
            pass

    reference = _valid_triplet(reference_ecef)
    if reference is not None and np.linalg.norm(reference) > 3_000_000.0:
        estimate = np.array([ecef_x, ecef_y, ecef_z], dtype=float)
        truth = np.array(reference, dtype=float)
        delta = estimate - truth
        lat_rad, lon_rad, _ = ecef2lla(truth)
        rotation = np.array(
            [
                [-math.sin(lon_rad), math.cos(lon_rad), 0.0],
                [
                    -math.sin(lat_rad) * math.cos(lon_rad),
                    -math.sin(lat_rad) * math.sin(lon_rad),
                    math.cos(lat_rad),
                ],
                [
                    math.cos(lat_rad) * math.cos(lon_rad),
                    math.cos(lat_rad) * math.sin(lon_rad),
                    math.sin(lat_rad),
                ],
            ]
        )
        east, north, up = rotation @ delta
        solution.has_reference_position = True
        solution.reference_source = "stream-config"
        solution.reference_ecef_x, solution.reference_ecef_y, solution.reference_ecef_z = reference
        solution.error_ecef_x, solution.error_ecef_y, solution.error_ecef_z = delta.tolist()
        solution.error_east = float(east)
        solution.error_north = float(north)
        solution.error_up = float(up)
        solution.error_horizontal = float(math.hypot(east, north))
        solution.error_3d = float(np.linalg.norm(delta))
    return solution


def _available_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class NativeRTKRunner:
    """Own one ``rtkrcv`` subprocess and its local solution connection."""

    def __init__(
        self,
        obs_settings: Any,
        base_settings: Any,
        eph_settings: Any,
        positioning_settings: Any,
        *,
        approx_rec_pos: Any = None,
        executable: str | os.PathLike[str] | None = None,
        startup_timeout: float = 10.0,
    ) -> None:
        self.obs_settings = obs_settings
        self.base_settings = base_settings
        self.eph_settings = eph_settings
        self.positioning_settings = positioning_settings
        self.approx_rec_pos = approx_rec_pos
        self.executable = executable
        self.startup_timeout = max(1.0, float(startup_timeout))
        self.stop_event = threading.Event()
        self.process: subprocess.Popen[str] | None = None
        self.solution_socket: socket.socket | None = None
        self._lock = threading.Lock()
        self._process_lines: queue.Queue[str] = queue.Queue(maxsize=200)

    def _drain_process_output(self, pipe) -> None:
        try:
            for line in iter(pipe.readline, ""):
                sanitized = redact_sensitive_text(line.strip())
                if not sanitized:
                    continue
                try:
                    self._process_lines.put_nowait(sanitized)
                except queue.Full:
                    try:
                        self._process_lines.get_nowait()
                        self._process_lines.put_nowait(sanitized)
                    except (queue.Empty, queue.Full):
                        pass
        finally:
            try:
                pipe.close()
            except OSError:
                pass

    def _emit_process_lines(self, callback: Callable[[str], None] | None) -> None:
        if callback is None:
            return
        while True:
            try:
                callback(f"[rtkrcv] {self._process_lines.get_nowait()}")
            except queue.Empty:
                return

    def _connect_solution_stream(self, port: int, log_callback: Callable[[str], None] | None) -> socket.socket:
        deadline = time.monotonic() + self.startup_timeout
        last_error: OSError | None = None
        while not self.stop_event.is_set() and time.monotonic() < deadline:
            process = self.process
            if process is not None and process.poll() is not None:
                self._emit_process_lines(log_callback)
                raise RuntimeError(f"rtkrcv exited during startup with code {process.returncode}")
            try:
                sock = socket.create_connection(("127.0.0.1", port), timeout=0.5)
                sock.settimeout(0.5)
                return sock
            except OSError as exc:
                last_error = exc
                self._emit_process_lines(log_callback)
                self.stop_event.wait(0.1)
        if self.stop_event.is_set():
            raise InterruptedError("RTK startup was cancelled")
        raise RuntimeError(f"Could not connect to the local RTK solution stream: {last_error}")

    def run(
        self,
        solution_callback: Callable[[PositioningSolution], None],
        log_callback: Callable[[str], None] | None = None,
        stream_status_callback: Callable[[str, bool], None] | None = None,
    ) -> None:
        binary = find_rtkrcv(self.executable)
        port = _available_tcp_port()
        config_text = build_rtk_engine_config(
            self.obs_settings,
            self.base_settings,
            self.eph_settings,
            self.positioning_settings,
            port,
            approx_rec_pos=self.approx_rec_pos,
        )
        if log_callback:
            rtk_type = _as_mapping(self.positioning_settings).get("rtk_type", "single_base")
            log_callback(f"RTK engine starting ({rtk_type}, {binary})")

        try:
            with tempfile.TemporaryDirectory(prefix="rtgs-rtk-") as temp_dir:
                os.chmod(temp_dir, 0o700)
                config_path = Path(temp_dir) / "rtkrcv.conf"
                config_path.write_text(config_text, encoding="utf-8")
                os.chmod(config_path, 0o600)
                process = subprocess.Popen(
                    [str(binary), "-nc", "-o", str(config_path), "-w", ""],
                    cwd=temp_dir,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    start_new_session=True,
                )
                with self._lock:
                    self.process = process
                if process.stdout is not None:
                    threading.Thread(
                        target=self._drain_process_output,
                        args=(process.stdout,),
                        name="rtkrcv-log",
                        daemon=True,
                    ).start()

                sock = self._connect_solution_stream(port, log_callback)
                with self._lock:
                    self.solution_socket = sock
                if log_callback:
                    log_callback("RTK solution stream connected")

                pending = b""
                obs_active = False
                base_active = False
                while not self.stop_event.is_set():
                    if process.poll() is not None:
                        self._emit_process_lines(log_callback)
                        if not self.stop_event.is_set():
                            raise RuntimeError(f"rtkrcv stopped unexpectedly with code {process.returncode}")
                        break
                    try:
                        chunk = sock.recv(8192)
                    except socket.timeout:
                        self._emit_process_lines(log_callback)
                        continue
                    except OSError:
                        if self.stop_event.is_set():
                            break
                        raise
                    if not chunk:
                        if self.stop_event.is_set():
                            break
                        raise ConnectionError("RTK solution stream closed")
                    pending += chunk
                    while b"\n" in pending:
                        raw_line, pending = pending.split(b"\n", 1)
                        solution = parse_rtk_engine_solution(
                            raw_line.decode("ascii", errors="replace"),
                            reference_ecef=self.approx_rec_pos,
                        )
                        if solution is not None:
                            if stream_status_callback and not obs_active:
                                stream_status_callback("OBS", True)
                                if bool(_as_mapping(self.eph_settings).get("enabled", False)):
                                    stream_status_callback("EPH", True)
                                obs_active = True
                            if (
                                stream_status_callback
                                and not base_active
                                and solution.rtk_quality in {1, 2, 4}
                            ):
                                stream_status_callback("BASE", True)
                                base_active = True
                            solution_callback(solution)
                    self._emit_process_lines(log_callback)
        finally:
            if stream_status_callback:
                stream_status_callback("OBS", False)
                stream_status_callback("BASE", False)
                stream_status_callback("EPH", False)
            self._shutdown_process(wait=True)

    def _shutdown_process(self, *, wait: bool) -> None:
        with self._lock:
            sock = self.solution_socket
            self.solution_socket = None
            process = self.process
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            try:
                process.terminate()
            except OSError:
                return
        if not wait:
            return
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                process.kill()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass

    def stop(self) -> None:
        """Interrupt socket reads and request subprocess termination immediately."""
        self.stop_event.set()
        self._shutdown_process(wait=False)


__all__ = [
    "QUALITY_LABELS",
    "RTKConfigurationError",
    "NativeRTKRunner",
    "build_rtk_engine_config",
    "find_rtkrcv",
    "parse_rtk_engine_solution",
    "redact_sensitive_text",
    "stream_to_rtk_engine",
]
