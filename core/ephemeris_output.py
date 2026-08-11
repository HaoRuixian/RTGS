"""Writers for live broadcast and SSR-corrected ephemeris products."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Dict, Iterable, Mapping, Sequence

import numpy as np

from core.BE2pos import brdc2state
from core.gnss_time import GNSSTime
from core.ssr import ephemeris_iod_for_ssr


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _format_float(value: object) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return f"{number:19.12E}"


def _header_line(content: str, label: str) -> str:
    return f"{str(content or '')[:60].ljust(60)}{str(label or '')[:20].ljust(20)}\n"


def _gps_utc_datetime(week: object, seconds: object) -> datetime:
    try:
        gps_week = int(week)
        gps_seconds = float(seconds)
    except (TypeError, ValueError):
        return datetime.utcnow()
    return _normalize_datetime(GNSSTime.gps_to_utc_datetime(gps_week, gps_seconds))


def _time_difference(time_sow: float, reference_sow: float) -> float:
    dt = float(time_sow) - float(reference_sow)
    if dt > 302_400.0:
        dt -= 604_800.0
    elif dt < -302_400.0:
        dt += 604_800.0
    return dt


def _finite_vector3(values: object):
    try:
        arr = np.asarray(values, dtype=float).reshape(-1)
    except Exception:
        return None
    if arr.size < 3:
        return None
    vec = arr[:3]
    if not np.all(np.isfinite(vec)):
        return None
    return vec.copy()


def _build_be2pos_input(eph: Mapping[str, object]):
    sat_id = str(eph.get("satellite_id", ""))
    if not sat_id:
        return None
    system = sat_id[0]
    sys_type = "GLO" if system == "R" else "SBS" if system == "S" else system
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


def _compute_clock_correction(eph: Mapping[str, object], transmit_time: float) -> float:
    if str(eph.get("satellite_id", "")).startswith("R"):
        tau = float(eph.get("tau_n", 0.0) or 0.0)
        gamma = float(eph.get("gamma_n", 0.0) or 0.0)
        tb = float(eph.get("tb") or eph.get("toe") or eph.get("toc") or 0.0)
        dt = _time_difference(transmit_time, tb)
        reference_dt = dt
        for _ in range(2):
            dt = reference_dt - (tau + gamma * dt)
        return tau + gamma * dt

    af0 = float(eph.get("af0", 0.0) or 0.0)
    af1 = float(eph.get("af1", 0.0) or 0.0)
    af2 = float(eph.get("af2", 0.0) or 0.0)
    toc = float(eph.get("toc") or eph.get("Toc") or 0.0)
    dt = _time_difference(transmit_time, toc)
    return af0 + af1 * dt + af2 * dt * dt


def build_sp3_states(
    ephemerides: Mapping[str, Mapping[str, object]] | Iterable[Mapping[str, object]],
    epoch_time: datetime,
    *,
    ssr_store=None,
) -> Dict[str, tuple[Sequence[float], float, bool]]:
    """Build SP3-ready satellite states from broadcast ephemerides and optional SSR."""
    if isinstance(ephemerides, Mapping):
        items = ephemerides.items()
    else:
        items = ((str(eph.get("satellite_id", "")), eph) for eph in ephemerides)

    _, gps_sow = GNSSTime.utc_to_gps(epoch_time if epoch_time.tzinfo else epoch_time.replace(tzinfo=timezone.utc))
    states: Dict[str, tuple[Sequence[float], float, bool]] = {}
    for sat_id, eph in items:
        if not sat_id:
            continue
        built = _build_be2pos_input(eph)
        if built is None:
            continue
        sys_type, payload = built
        state = brdc2state(payload, sys_type, gps_sow)
        if state is None:
            continue
        position = _finite_vector3(state[0])
        velocity = _finite_vector3(state[1])
        if position is None or velocity is None:
            continue
        clock = _compute_clock_correction(eph, gps_sow)
        ssr_applied = False
        if ssr_store is not None and hasattr(ssr_store, "apply_to_state"):
            corrected = ssr_store.apply_to_state(
                sat_id,
                position,
                velocity,
                clock_bias_s=clock,
                transmit_time=gps_sow,
                ephemeris_iod=ephemeris_iod_for_ssr(eph),
            )
            corrected_position = _finite_vector3(corrected.position_m)
            if corrected_position is not None:
                position = corrected_position
            corrected_velocity = _finite_vector3(corrected.velocity_mps)
            if corrected_velocity is not None:
                velocity = corrected_velocity
            clock = float(corrected.clock_bias_s)
            ssr_applied = bool(corrected.applied)
        states[sat_id] = (position.tolist(), clock, ssr_applied)
    return states


class BroadcastNavWriter:
    """Append broadcast ephemerides to a RINEX 3 navigation file."""

    def __init__(self, path: str | Path, *, rinex_version: str = "3.05") -> None:
        self.path = Path(path)
        self.rinex_version = rinex_version
        self._handle = None
        self._written_keys: set[tuple[str, object, object]] = set()

    def open(self) -> None:
        if self._handle is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not self.path.exists() or self.path.stat().st_size == 0
        self._handle = self.path.open("a", encoding="utf-8", newline="")
        if is_new:
            self._write_header()

    def close(self) -> None:
        if self._handle is None:
            return
        self._handle.close()
        self._handle = None

    def _write_header(self) -> None:
        if self._handle is None:
            return
        self._handle.write(_header_line(f"{self.rinex_version:>9}           NAVIGATION DATA     M", "RINEX VERSION / TYPE"))
        now = datetime.utcnow().strftime("%Y%m%d %H%M%S UTC")
        self._handle.write(_header_line(f"{'RTGS':<20}{'GNSS_ToolBox':<20}{now}", "PGM / RUN BY / DATE"))
        self._handle.write(_header_line("", "END OF HEADER"))

    def write_ephemeris(self, eph: Mapping[str, object]) -> bool:
        sat_id = str(eph.get("satellite_id") or "").strip().upper()
        if len(sat_id) < 3:
            return False

        key = (sat_id, eph.get("toe") or eph.get("tb") or eph.get("t0"), eph.get("iode") or eph.get("iod_nav") or eph.get("aode"))
        if key in self._written_keys:
            return False

        self.open()
        if self._handle is None:
            return False

        if sat_id.startswith("R"):
            lines = self._format_glonass_record(sat_id, eph)
        else:
            lines = self._format_kepler_record(sat_id, eph)

        for line in lines:
            self._handle.write(line)
        self._handle.flush()
        self._written_keys.add(key)
        return True

    def write_many(self, ephemerides: Iterable[Mapping[str, object]]) -> int:
        count = 0
        for eph in ephemerides:
            if self.write_ephemeris(eph):
                count += 1
        return count

    @staticmethod
    def _record_time(eph: Mapping[str, object]) -> datetime:
        if "toc_week" in eph:
            return _gps_utc_datetime(eph.get("toc_week"), eph.get("toc"))
        if "week" in eph:
            return _gps_utc_datetime(eph.get("week"), eph.get("toc", eph.get("toe", 0.0)))
        return datetime.utcnow()

    def _format_kepler_record(self, sat_id: str, eph: Mapping[str, object]) -> list[str]:
        toc = self._record_time(eph)
        first = (
            f"{sat_id:<3} {toc.year:04d} {toc.month:02d} {toc.day:02d} "
            f"{toc.hour:02d} {toc.minute:02d} {toc.second:02d}"
            f"{_format_float(eph.get('af0'))}{_format_float(eph.get('af1'))}{_format_float(eph.get('af2'))}\n"
        )
        rows = [
            [eph.get("iode", eph.get("iod_nav", eph.get("aode", 0))), eph.get("Crs"), eph.get("delta_n"), eph.get("M0")],
            [eph.get("Cuc"), eph.get("e"), eph.get("Cus"), eph.get("sqrt_a")],
            [eph.get("toe"), eph.get("Cic"), eph.get("Omega0"), eph.get("Cis")],
            [eph.get("i0"), eph.get("Crc"), eph.get("omega"), eph.get("Omega_dot")],
            [eph.get("idot"), eph.get("code_on_l2", 0), eph.get("week"), eph.get("l2_p_data_flag", 0)],
            [eph.get("ura", eph.get("SISA", 0)), eph.get("health", 0), eph.get("TGD", eph.get("BGD_E5aE1", eph.get("TGD1", 0))), eph.get("iodc", eph.get("aodc", 0))],
            [eph.get("transmission_time", 0), eph.get("fit_interval", 0), 0, 0],
        ]
        return [first] + [self._format_nav_row(row) for row in rows]

    def _format_glonass_record(self, sat_id: str, eph: Mapping[str, object]) -> list[str]:
        toe = _gps_utc_datetime(GNSSTime.current_gps_week(), eph.get("tb", 0.0))
        first = (
            f"{sat_id:<3} {toe.year:04d} {toe.month:02d} {toe.day:02d} "
            f"{toe.hour:02d} {toe.minute:02d} {toe.second:02d}"
            f"{_format_float(eph.get('tau_n'))}{_format_float(eph.get('gamma_n'))}{_format_float(0.0)}\n"
        )
        rows = [
            [eph.get("X"), eph.get("Vx"), eph.get("Ax"), eph.get("health", 0)],
            [eph.get("Y"), eph.get("Vy"), eph.get("Ay"), eph.get("frequency_channel", 0)],
            [eph.get("Z"), eph.get("Vz"), eph.get("Az"), eph.get("tb", 0)],
        ]
        return [first] + [self._format_nav_row(row) for row in rows]

    @staticmethod
    def _format_nav_row(values: Sequence[object]) -> str:
        return "    " + "".join(_format_float(value) for value in values[:4]) + "\n"


class PreciseSp3Writer:
    """Write SP3 orbit snapshots from broadcast or SSR-corrected satellite states."""

    def __init__(self, path: str | Path, *, epoch_interval_seconds: float = 5.0) -> None:
        self.path = Path(path)
        self.epoch_interval_seconds = float(epoch_interval_seconds)
        self._handle = None
        self._header_written = False
        self._closed = False

    def open(self, first_epoch: datetime, satellites: Iterable[str]) -> None:
        if self._handle is not None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", encoding="utf-8", newline="")
        self._write_header(first_epoch, sorted(set(satellites)))
        self._header_written = True

    def close(self) -> None:
        if self._handle is None:
            return
        if not self._closed:
            self._handle.write("EOF\n")
            self._closed = True
        self._handle.close()
        self._handle = None

    def write_epoch(
        self,
        epoch_time: datetime,
        states: Mapping[str, tuple[Sequence[float], float, bool]],
    ) -> bool:
        if not states:
            return False
        epoch_time = _normalize_datetime(epoch_time)
        if self._handle is None:
            self.open(epoch_time, states.keys())
        if self._handle is None:
            return False

        self._handle.write(
            f"*  {epoch_time.year:04d} {epoch_time.month:02d} {epoch_time.day:02d} "
            f"{epoch_time.hour:02d} {epoch_time.minute:02d} {epoch_time.second:02d}."
            f"{epoch_time.microsecond:06d}00\n"
        )
        for satellite_id in sorted(states.keys()):
            position_m, clock_bias_s, _ssr_applied = states[satellite_id]
            x_m, y_m, z_m = [float(value) for value in position_m[:3]]
            clock_us = float(clock_bias_s) * 1.0e6
            if not math.isfinite(clock_us) or abs(clock_us) >= 999999.0:
                clock_us = 999999.999999
            self._handle.write(
                f"P{satellite_id:<3}{x_m / 1000.0:14.6f}{y_m / 1000.0:14.6f}"
                f"{z_m / 1000.0:14.6f}{clock_us:14.6f}\n"
            )
        self._handle.flush()
        return True

    def _write_header(self, first_epoch: datetime, satellites: list[str]) -> None:
        if self._handle is None:
            return
        gps_week, gps_sow = GNSSTime.utc_to_gps(first_epoch.replace(tzinfo=timezone.utc))
        self._handle.write(
            f"#cP{first_epoch.year:04d} {first_epoch.month:02d} {first_epoch.day:02d} "
            f"{first_epoch.hour:02d} {first_epoch.minute:02d} {first_epoch.second:02d}."
            f"{first_epoch.microsecond:06d}00      96 ORBIT IGb14 RTGS\n"
        )
        self._handle.write(f"## {gps_week:4d} {gps_sow:15.8f} {self.epoch_interval_seconds:14.8f}    0 0.0000000000000\n")
        self._write_satellite_header(satellites)
        self._handle.write("%c cc cc ccc ccc cccc cccc cccc cccc ccccc ccccc ccccc ccccc\n")
        self._handle.write("%f  0.0000000  0.000000000  0.00000000000  0.000000000000000\n")
        self._handle.write("%i    0    0    0    0      0      0      0      0         0\n")

    def _write_satellite_header(self, satellites: list[str]) -> None:
        total = len(satellites)
        chunks = [satellites[index : index + 17] for index in range(0, max(total, 1), 17)]
        for index, chunk in enumerate(chunks):
            prefix = f"+  {total:3d}   " if index == 0 else "+        "
            body = "".join(f"{sat:<3}" for sat in chunk)
            self._handle.write(f"{prefix}{body:<51}\n")
