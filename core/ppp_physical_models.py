"""Physical correction models used by the real-time PPP filter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import gzip
import math
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

from core.geo_utils import ecef2lla, rot_ecef2enu


LIGHT_SPEED = 299_792_458.0
EARTH_ROTATION_RATE = 7.2921151467e-5
MJD_J2000 = 51_544.5
ARCSEC_PER_RADIAN = 206_264.80624709636
DEG_PER_RADIAN = 57.29577951308232
SSR_UPDATE_INTERVAL_SECONDS = (
    1.0,
    2.0,
    5.0,
    10.0,
    15.0,
    30.0,
    60.0,
    120.0,
    240.0,
    300.0,
    600.0,
    900.0,
    1800.0,
    3600.0,
    7200.0,
    10800.0,
)


def _unit(vector: np.ndarray) -> Optional[np.ndarray]:
    value = np.asarray(vector, dtype=float).reshape(-1)
    if value.size < 3 or not np.all(np.isfinite(value[:3])):
        return None
    value = value[:3]
    norm = float(np.linalg.norm(value))
    if norm <= 1e-12:
        return None
    return value / norm


def _frac(value: float) -> float:
    return float(value - math.floor(value))


def _rot_x(angle: float) -> np.ndarray:
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return np.array(
        [[1.0, 0.0, 0.0], [0.0, cosine, sine], [0.0, -sine, cosine]],
        dtype=float,
    )


def _rot_y(angle: float) -> np.ndarray:
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return np.array(
        [[cosine, 0.0, -sine], [0.0, 1.0, 0.0], [sine, 0.0, cosine]],
        dtype=float,
    )


def _rot_z(angle: float) -> np.ndarray:
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return np.array(
        [[cosine, sine, 0.0], [-sine, cosine, 0.0], [0.0, 0.0, 1.0]],
        dtype=float,
    )


def datetime_to_mjd(epoch: datetime) -> float:
    """Return UTC MJD for a timezone-aware or naive datetime."""
    if epoch.tzinfo is None:
        epoch = epoch.replace(tzinfo=timezone.utc)
    else:
        epoch = epoch.astimezone(timezone.utc)
    return 40_587.0 + epoch.timestamp() / 86_400.0


def _gmst(mjd_ut1: float) -> float:
    seconds_per_day = 86_400.0
    mjd_zero = math.floor(mjd_ut1)
    ut1 = seconds_per_day * (mjd_ut1 - mjd_zero)
    t_zero = (mjd_zero - MJD_J2000) / 36_525.0
    t_value = (mjd_ut1 - MJD_J2000) / 36_525.0
    gmst_seconds = (
        24_110.54841
        + 8_640_184.812866 * t_zero
        + 1.002737909350795 * ut1
        + (0.093104 - 6.2e-6 * t_value) * t_value * t_value
    )
    return 2.0 * math.pi * _frac(gmst_seconds / seconds_per_day)


def _nutation_matrix(mjd_tt: float) -> np.ndarray:
    t_value = (mjd_tt - MJD_J2000) / 36_525.0
    solar_mean_anomaly = 2.0 * math.pi * _frac(0.993133 + 99.997306 * t_value)
    moon_elongation = 2.0 * math.pi * _frac(0.827362 + 1236.853087 * t_value)
    moon_argument = 2.0 * math.pi * _frac(0.259089 + 1342.227826 * t_value)
    ascending_node = 2.0 * math.pi * _frac(0.347346 - 5.372447 * t_value)
    dpsi = (
        -17.200 * math.sin(ascending_node)
        - 1.319 * math.sin(2.0 * (moon_argument - moon_elongation + ascending_node))
        - 0.227 * math.sin(2.0 * (moon_argument + ascending_node))
        + 0.206 * math.sin(2.0 * ascending_node)
        + 0.143 * math.sin(solar_mean_anomaly)
    ) / ARCSEC_PER_RADIAN
    deps = (
        9.203 * math.cos(ascending_node)
        + 0.574 * math.cos(2.0 * (moon_argument - moon_elongation + ascending_node))
        + 0.098 * math.cos(2.0 * (moon_argument + ascending_node))
        - 0.090 * math.cos(2.0 * ascending_node)
    ) / ARCSEC_PER_RADIAN
    epsilon = 0.4090928 - 2.2696e-4 * t_value
    return _rot_x(-epsilon - deps) @ _rot_z(-dpsi) @ _rot_x(epsilon)


def _precession_matrix(mjd_start: float, mjd_end: float) -> np.ndarray:
    t_value = (mjd_start - MJD_J2000) / 36_525.0
    dt = (mjd_end - mjd_start) / 36_525.0
    zeta = (
        (2306.2181 + (1.39656 - 0.000139 * t_value) * t_value)
        + ((0.30188 - 0.000344 * t_value) + 0.017998 * dt) * dt
    ) * dt / ARCSEC_PER_RADIAN
    z_value = zeta + (
        (0.79280 + 0.000411 * t_value) + 0.000205 * dt
    ) * dt * dt / ARCSEC_PER_RADIAN
    theta = (
        (2004.3109 - (0.85330 + 0.000217 * t_value) * t_value)
        - ((0.42665 + 0.000217 * t_value) + 0.041833 * dt) * dt
    ) * dt / ARCSEC_PER_RADIAN
    return _rot_z(-z_value) @ _rot_y(theta) @ _rot_z(-zeta)


def sun_position_ecef(epoch: datetime) -> np.ndarray:
    """Return a low-order Sun position in ECEF coordinates."""
    mjd = datetime_to_mjd(epoch)
    epsilon = math.radians(23.43929111)
    t_value = (mjd - MJD_J2000) / 36_525.0
    mean_anomaly = 2.0 * math.pi * _frac(0.9931267 + 99.9973583 * t_value)
    longitude = 2.0 * math.pi * _frac(
        0.7859444
        + mean_anomaly / (2.0 * math.pi)
        + (6892.0 * math.sin(mean_anomaly) + 72.0 * math.sin(2.0 * mean_anomaly)) / 1_296_000.0
    )
    radius = 149.619e9 - 2.499e9 * math.cos(mean_anomaly) - 0.021e9 * math.cos(2.0 * mean_anomaly)
    sun = np.array([radius * math.cos(longitude), radius * math.sin(longitude), 0.0], dtype=float)
    sun = _rot_x(-epsilon) @ sun
    return _rot_z(_gmst(mjd)) @ _nutation_matrix(mjd) @ _precession_matrix(MJD_J2000, mjd) @ sun


def moon_position_ecef(epoch: datetime) -> np.ndarray:
    """Return a low-order Moon position in ECEF coordinates."""
    mjd = datetime_to_mjd(epoch)
    epsilon = math.radians(23.43929111)
    t_value = (mjd - MJD_J2000) / 36_525.0
    l_zero = _frac(0.606433 + 1336.851344 * t_value)
    moon_anomaly = 2.0 * math.pi * _frac(0.374897 + 1325.552410 * t_value)
    sun_anomaly = 2.0 * math.pi * _frac(0.993133 + 99.997361 * t_value)
    elongation = 2.0 * math.pi * _frac(0.827361 + 1236.853086 * t_value)
    argument = 2.0 * math.pi * _frac(0.259086 + 1342.227825 * t_value)
    delta_longitude = (
        22_640.0 * math.sin(moon_anomaly)
        - 4586.0 * math.sin(moon_anomaly - 2.0 * elongation)
        + 2370.0 * math.sin(2.0 * elongation)
        + 769.0 * math.sin(2.0 * moon_anomaly)
        - 668.0 * math.sin(sun_anomaly)
        - 412.0 * math.sin(2.0 * argument)
        - 212.0 * math.sin(2.0 * moon_anomaly - 2.0 * elongation)
        - 206.0 * math.sin(moon_anomaly + sun_anomaly - 2.0 * elongation)
        + 192.0 * math.sin(moon_anomaly + 2.0 * elongation)
        - 165.0 * math.sin(sun_anomaly - 2.0 * elongation)
        - 125.0 * math.sin(elongation)
        - 110.0 * math.sin(moon_anomaly + sun_anomaly)
        + 148.0 * math.sin(moon_anomaly - sun_anomaly)
        - 55.0 * math.sin(2.0 * argument - 2.0 * elongation)
    )
    longitude = 2.0 * math.pi * _frac(l_zero + delta_longitude / 1_296_000.0)
    s_value = argument + (
        delta_longitude + 412.0 * math.sin(2.0 * argument) + 541.0 * math.sin(sun_anomaly)
    ) / ARCSEC_PER_RADIAN
    h_value = argument - 2.0 * elongation
    latitude_term = (
        -526.0 * math.sin(h_value)
        + 44.0 * math.sin(moon_anomaly + h_value)
        - 31.0 * math.sin(-moon_anomaly + h_value)
        - 23.0 * math.sin(sun_anomaly + h_value)
        + 11.0 * math.sin(-sun_anomaly + h_value)
        - 25.0 * math.sin(-2.0 * moon_anomaly + argument)
        + 21.0 * math.sin(-moon_anomaly + argument)
    )
    latitude = (18_520.0 * math.sin(s_value) + latitude_term) / ARCSEC_PER_RADIAN
    cos_latitude = math.cos(latitude)
    radius = (
        385_000e3
        - 20_905e3 * math.cos(moon_anomaly)
        - 3699e3 * math.cos(2.0 * elongation - moon_anomaly)
        - 2956e3 * math.cos(2.0 * elongation)
        - 570e3 * math.cos(2.0 * moon_anomaly)
        + 246e3 * math.cos(2.0 * moon_anomaly - 2.0 * elongation)
        - 205e3 * math.cos(sun_anomaly - 2.0 * elongation)
        - 171e3 * math.cos(moon_anomaly + 2.0 * elongation)
        - 152e3 * math.cos(moon_anomaly + sun_anomaly - 2.0 * elongation)
    )
    moon = np.array(
        [
            radius * math.cos(longitude) * cos_latitude,
            radius * math.sin(longitude) * cos_latitude,
            radius * math.sin(latitude),
        ],
        dtype=float,
    )
    moon = _rot_x(-epsilon) @ moon
    return _rot_z(_gmst(mjd)) @ _nutation_matrix(mjd) @ _precession_matrix(MJD_J2000, mjd) @ moon


def solid_earth_tide_displacement(epoch: datetime, receiver_ecef: np.ndarray) -> np.ndarray:
    """Return the degree-2 solid Earth tide displacement in ECEF meters."""
    receiver = np.asarray(receiver_ecef, dtype=float).reshape(3)
    receiver_radius = float(np.linalg.norm(receiver))
    if receiver_radius <= 0.0:
        return np.zeros(3, dtype=float)
    sun = sun_position_ecef(epoch)
    moon = moon_position_ecef(epoch)
    sun_radius = float(np.linalg.norm(sun))
    moon_radius = float(np.linalg.norm(moon))
    receiver_unit = receiver / receiver_radius
    sun_unit = sun / sun_radius
    moon_unit = moon / moon_radius
    h2 = 0.6078
    l2 = 0.0847
    dot_sun = float(receiver_unit @ sun_unit)
    dot_moon = float(receiver_unit @ moon_unit)
    p2_sun = 3.0 * (h2 / 2.0 - l2) * dot_sun * dot_sun - h2 / 2.0
    p2_moon = 3.0 * (h2 / 2.0 - l2) * dot_moon * dot_moon - h2 / 2.0
    x2_sun = 3.0 * l2 * dot_sun
    x2_moon = 3.0 * l2 * dot_moon
    gm_wgs = 398.6005e12
    gm_sun = 1.3271250e20
    gm_moon = 4.9027890e12
    factor_sun = gm_sun / gm_wgs * receiver_radius ** 4 / sun_radius ** 3
    factor_moon = gm_moon / gm_wgs * receiver_radius ** 4 / moon_radius ** 3
    return (
        factor_sun * (x2_sun * sun_unit + p2_sun * receiver_unit)
        + factor_moon * (x2_moon * moon_unit + p2_moon * receiver_unit)
    )


def shapiro_delay(receiver_ecef: np.ndarray, satellite_ecef: np.ndarray) -> float:
    """Return the relativistic path delay due to the Earth's gravity."""
    receiver = np.asarray(receiver_ecef, dtype=float).reshape(3)
    satellite = np.asarray(satellite_ecef, dtype=float).reshape(3)
    receiver_radius = float(np.linalg.norm(receiver))
    satellite_radius = float(np.linalg.norm(satellite))
    distance = float(np.linalg.norm(satellite - receiver))
    numerator = satellite_radius + receiver_radius + distance
    denominator = satellite_radius + receiver_radius - distance
    if denominator <= 0.0 or numerator <= denominator:
        return 0.0
    earth_gm = 3.986004418e14
    return float(2.0 * earth_gm / LIGHT_SPEED ** 2 * math.log(numerator / denominator))


def _niell_interpolate(coefficients: np.ndarray, latitude_deg: float) -> float:
    """Interpolate a Niell coefficient at absolute geodetic latitude."""
    latitude = abs(float(latitude_deg))
    if latitude <= 15.0:
        return float(coefficients[0])
    if latitude >= 75.0:
        return float(coefficients[-1])
    lower = min(int(latitude / 15.0) - 1, 3)
    fraction = latitude / 15.0 - (lower + 1)
    return float(
        coefficients[lower] * (1.0 - fraction)
        + coefficients[lower + 1] * fraction
    )


def _niell_map(elevation_rad: float, a_value: float, b_value: float, c_value: float) -> float:
    sin_elevation = math.sin(float(elevation_rad))
    numerator = 1.0 + a_value / (1.0 + b_value / (1.0 + c_value))
    denominator = sin_elevation + a_value / (
        sin_elevation + b_value / (sin_elevation + c_value)
    )
    return float(numerator / denominator)


def niell_mapping_factors(
    epoch: datetime,
    latitude_rad: float,
    height_m: float,
    elevation_rad: float,
) -> Tuple[float, float]:
    """Return Niell (1996) hydrostatic and wet mapping factors."""
    if elevation_rad <= 0.0:
        return 0.0, 0.0
    if epoch.tzinfo is None:
        epoch = epoch.replace(tzinfo=timezone.utc)
    else:
        epoch = epoch.astimezone(timezone.utc)

    hydro_average = np.array(
        [
            [1.2769934e-3, 1.2683230e-3, 1.2465397e-3, 1.2196049e-3, 1.2045996e-3],
            [2.9153695e-3, 2.9152299e-3, 2.9288445e-3, 2.9022565e-3, 2.9024912e-3],
            [62.610505e-3, 62.837393e-3, 63.721774e-3, 63.824265e-3, 64.258455e-3],
        ],
        dtype=float,
    )
    hydro_amplitude = np.array(
        [
            [0.0, 1.2709626e-5, 2.6523662e-5, 3.4000452e-5, 4.1202191e-5],
            [0.0, 2.1414979e-5, 3.0160779e-5, 7.2562722e-5, 11.723375e-5],
            [0.0, 9.0128400e-5, 4.3497037e-5, 84.795348e-5, 170.37206e-5],
        ],
        dtype=float,
    )
    wet = np.array(
        [
            [5.8021897e-4, 5.6794847e-4, 5.8118019e-4, 5.9727542e-4, 6.1641693e-4],
            [1.4275268e-3, 1.5138625e-3, 1.4572752e-3, 1.5007428e-3, 1.7599082e-3],
            [4.3472961e-2, 4.6729510e-2, 4.3908931e-2, 4.4626982e-2, 5.4736038e-2],
        ],
        dtype=float,
    )
    latitude_deg = math.degrees(float(latitude_rad))
    day_fraction = (
        epoch.hour * 3600.0
        + epoch.minute * 60.0
        + epoch.second
        + epoch.microsecond * 1e-6
    ) / 86_400.0
    seasonal_year = (
        int(epoch.strftime("%j")) + day_fraction - 28.0
    ) / 365.25
    if latitude_deg < 0.0:
        seasonal_year += 0.5
    seasonal_cosine = math.cos(2.0 * math.pi * seasonal_year)
    hydro = [
        _niell_interpolate(hydro_average[index], latitude_deg)
        - _niell_interpolate(hydro_amplitude[index], latitude_deg) * seasonal_cosine
        for index in range(3)
    ]
    wet_values = [
        _niell_interpolate(wet[index], latitude_deg)
        for index in range(3)
    ]
    hydro_mapping = _niell_map(elevation_rad, *hydro)
    wet_mapping = _niell_map(elevation_rad, *wet_values)

    height_mapping = _niell_map(elevation_rad, 2.53e-5, 5.49e-3, 1.14e-3)
    hydro_mapping += (
        1.0 / math.sin(elevation_rad) - height_mapping
    ) * float(height_m) / 1000.0
    return float(hydro_mapping), float(wet_mapping)


def neu_to_ecef(receiver_ecef: np.ndarray, north_east_up: np.ndarray) -> np.ndarray:
    """Convert a local North/East/Up displacement to ECEF."""
    latitude, longitude, _height = ecef2lla(receiver_ecef)
    east_north_up = np.array(
        [north_east_up[1], north_east_up[0], north_east_up[2]],
        dtype=float,
    )
    return rot_ecef2enu(latitude, longitude).T @ east_north_up


def satellite_body_axes(
    epoch: datetime,
    satellite_ecef: np.ndarray,
    satellite_velocity_ecef: Optional[np.ndarray] = None,
    yaw_angle_deg: Optional[float] = None,
) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Return satellite body X/Y/Z axes for nominal or supplied yaw."""
    satellite = np.asarray(satellite_ecef, dtype=float).reshape(3)
    z_axis = _unit(-satellite)
    if z_axis is None:
        return None
    sun_axis = _unit(sun_position_ecef(epoch))
    if sun_axis is None:
        return None
    y_axis = _unit(np.cross(z_axis, sun_axis))
    if y_axis is None:
        return None
    x_axis = _unit(np.cross(y_axis, z_axis))
    if x_axis is None:
        return None

    velocity = None if satellite_velocity_ecef is None else _unit(satellite_velocity_ecef)
    if yaw_angle_deg is not None and velocity is not None:
        raw_velocity = np.asarray(satellite_velocity_ecef, dtype=float).reshape(3)
        inertial_velocity = raw_velocity + np.cross(
            np.array([0.0, 0.0, EARTH_ROTATION_RATE], dtype=float),
            satellite,
        )
        velocity_axis = _unit(inertial_velocity)
        if velocity_axis is not None:
            y_orbit = _unit(np.cross(z_axis, velocity_axis))
            if y_orbit is not None:
                x_orbit = _unit(np.cross(y_orbit, z_axis))
                if x_orbit is not None:
                    yaw = math.radians(float(yaw_angle_deg))
                    cosine = math.cos(yaw)
                    sine = math.sin(yaw)
                    x_axis = _unit(x_orbit * cosine + np.cross(z_axis, x_orbit) * sine)
                    y_axis = _unit(y_orbit * cosine + np.cross(z_axis, y_orbit) * sine)
    if x_axis is None or y_axis is None:
        return None
    return x_axis, y_axis, z_axis


class PhaseWindupModel:
    """Continuous phase wind-up correction stored per satellite."""

    def __init__(self) -> None:
        self._cycles: Dict[str, float] = {}

    def clear(self) -> None:
        self._cycles.clear()

    def drop(self, satellite_id: str) -> None:
        self._cycles.pop(str(satellite_id), None)

    def correction_cycles(
        self,
        satellite_id: str,
        epoch: datetime,
        receiver_ecef: np.ndarray,
        satellite_ecef: np.ndarray,
        *,
        satellite_velocity_ecef: Optional[np.ndarray] = None,
        yaw_angle_deg: Optional[float] = None,
    ) -> float:
        receiver = np.asarray(receiver_ecef, dtype=float).reshape(3)
        satellite = np.asarray(satellite_ecef, dtype=float).reshape(3)
        line_of_sight = _unit(receiver - satellite)
        axes = satellite_body_axes(
            epoch,
            satellite,
            satellite_velocity_ecef,
            yaw_angle_deg,
        )
        if line_of_sight is None or axes is None:
            return 0.0
        x_satellite, y_satellite, _z_satellite = axes
        dipole_satellite = (
            x_satellite
            - line_of_sight * float(line_of_sight @ x_satellite)
            - np.cross(line_of_sight, y_satellite)
        )

        latitude, longitude, _height = ecef2lla(receiver)
        ecef_from_enu = rot_ecef2enu(latitude, longitude).T
        receiver_north = ecef_from_enu @ np.array([0.0, 1.0, 0.0], dtype=float)
        receiver_west = ecef_from_enu @ np.array([-1.0, 0.0, 0.0], dtype=float)
        dipole_receiver = (
            receiver_north
            - line_of_sight * float(line_of_sight @ receiver_north)
            + np.cross(line_of_sight, receiver_west)
        )
        sat_norm = float(np.linalg.norm(dipole_satellite))
        rec_norm = float(np.linalg.norm(dipole_receiver))
        if sat_norm <= 1e-12 or rec_norm <= 1e-12:
            return 0.0
        cosine = float(dipole_satellite @ dipole_receiver) / (sat_norm * rec_norm)
        cosine = min(max(cosine, -1.0), 1.0)
        phase = math.acos(cosine) / (2.0 * math.pi)
        if float(line_of_sight @ np.cross(dipole_satellite, dipole_receiver)) < 0.0:
            phase = -phase
        satellite_id = str(satellite_id)
        previous = self._cycles.get(satellite_id)
        if previous is None:
            continuous = phase
        else:
            continuous = math.floor(previous - phase + 0.5) + phase
        self._cycles[satellite_id] = float(continuous)
        return float(continuous)


@dataclass(slots=True)
class _AntexFrequency:
    north_east_up_m: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=float))
    no_azimuth_pattern_m: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=float))


@dataclass(slots=True)
class _AntexAntenna:
    name: str
    zenith_start_deg: float = 0.0
    zenith_end_deg: float = 90.0
    zenith_step_deg: float = 5.0
    frequencies: Dict[str, _AntexFrequency] = field(default_factory=dict)


class AntexCalibration:
    """ANTEX reader for frequency-dependent PCO and NOAZI PCV corrections."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = ""
        self.antennas: Dict[str, _AntexAntenna] = {}
        if path:
            self.load(path)

    @staticmethod
    def _key(value: str) -> str:
        return " ".join(str(value or "").strip().upper().split())

    @property
    def loaded(self) -> bool:
        return bool(self.antennas)

    def load(self, path: str | Path) -> None:
        source = Path(path).expanduser()
        antennas: Dict[str, _AntexAntenna] = {}
        current: Optional[_AntexAntenna] = None
        current_frequency = ""
        current_frequency_data: Optional[_AntexFrequency] = None
        if source.suffix.lower() == ".gz":
            source_handle = gzip.open(source, "rt", encoding="utf-8", errors="ignore")
        else:
            source_handle = source.open("r", encoding="utf-8", errors="ignore")
        with source_handle as handle:
            for raw_line in handle:
                line = raw_line.rstrip("\n")
                label = line[60:80].strip() if len(line) >= 60 else ""
                if label == "START OF ANTENNA":
                    current = _AntexAntenna(name="")
                    current_frequency = ""
                    current_frequency_data = None
                    continue
                if current is None:
                    continue
                if label == "TYPE / SERIAL NO":
                    antenna_type = self._key(line[:20])
                    serial = self._key(line[20:40])
                    if len(serial) >= 3 and serial[0] in "GRECJIS" and serial[1:3].isdigit():
                        current.name = serial[:3]
                    else:
                        current.name = antenna_type
                elif label == "ZEN1 / ZEN2 / DZEN":
                    values = line[:60].split()
                    if len(values) >= 3:
                        current.zenith_start_deg = float(values[0])
                        current.zenith_end_deg = float(values[1])
                        current.zenith_step_deg = float(values[2])
                elif label == "START OF FREQUENCY":
                    current_frequency = line[:10].strip().upper()
                    current_frequency_data = _AntexFrequency()
                elif label == "NORTH / EAST / UP" and current_frequency_data is not None:
                    values = line[:60].split()
                    if len(values) >= 3:
                        current_frequency_data.north_east_up_m = (
                            np.asarray(values[:3], dtype=float) * 1e-3
                        )
                elif line[3:8].strip().upper() == "NOAZI" and current_frequency_data is not None:
                    # NOAZI patterns have no ANTEX label column and may extend
                    # beyond character 60.  Cutting at that boundary can leave
                    # a standalone minus sign from the next value.
                    values = line[8:].split()
                    try:
                        current_frequency_data.no_azimuth_pattern_m = (
                            np.asarray(values, dtype=float) * 1e-3
                        )
                    except ValueError:
                        current_frequency_data.no_azimuth_pattern_m = np.zeros(
                            0,
                            dtype=float,
                        )
                elif label == "END OF FREQUENCY" and current_frequency_data is not None:
                    end_frequency = line[:10].strip().upper()
                    key = end_frequency or current_frequency
                    if key:
                        current.frequencies[key] = current_frequency_data
                    current_frequency = ""
                    current_frequency_data = None
                elif label == "END OF ANTENNA":
                    if current.name:
                        antennas[self._key(current.name)] = current
                    current = None
                    current_frequency = ""
                    current_frequency_data = None
        self.path = str(source)
        self.antennas = antennas

    @staticmethod
    def frequency_code(satellite_id: str, signal_id: str) -> str:
        system = str(satellite_id).upper()[:1]
        band = str(signal_id).upper()[:1]
        if not system or not band:
            return ""
        return f"{system}0{band}"

    @staticmethod
    def reference_frequency_code(system: str) -> str:
        return {
            "G": "G01",
            "R": "R01",
            "E": "E01",
            "C": "C02",
            "J": "J01",
            "S": "S01",
            "I": "I05",
        }.get(str(system).upper()[:1], "")

    @staticmethod
    def _pattern_value(antenna: _AntexAntenna, frequency: _AntexFrequency, zenith_deg: float) -> float:
        pattern = frequency.no_azimuth_pattern_m
        if pattern.size == 0 or antenna.zenith_step_deg <= 0.0:
            return 0.0
        index = int(round((zenith_deg - antenna.zenith_start_deg) / antenna.zenith_step_deg))
        index = min(max(index, 0), pattern.size - 1)
        return float(pattern[index])

    def receiver_correction(
        self,
        antenna_name: str,
        frequency_code: str,
        elevation_rad: float,
        azimuth_rad: float,
    ) -> Tuple[float, bool]:
        if "NULLANTENNA" in str(antenna_name).upper():
            return 0.0, True
        antenna = self.antennas.get(self._key(antenna_name))
        if antenna is None:
            return 0.0, False
        frequency = antenna.frequencies.get(str(frequency_code).upper())
        if frequency is None:
            return 0.0, False
        zenith = 90.0 - math.degrees(elevation_rad)
        variation = self._pattern_value(antenna, frequency, zenith)
        north, east, up = frequency.north_east_up_m
        correction = (
            variation
            - north * math.cos(azimuth_rad) * math.cos(elevation_rad)
            - east * math.sin(azimuth_rad) * math.cos(elevation_rad)
            - up * math.sin(elevation_rad)
        )
        return float(correction), True

    def satellite_correction(
        self,
        satellite_id: str,
        frequency_code: str,
        transmit_elevation_rad: float,
        transmit_azimuth_rad: float,
    ) -> Tuple[float, bool]:
        antenna = self.antennas.get(self._key(str(satellite_id)[:3]))
        if antenna is None:
            return 0.0, False
        frequency = antenna.frequencies.get(str(frequency_code).upper())
        if frequency is None:
            return 0.0, False
        zenith = 90.0 - math.degrees(transmit_elevation_rad)
        variation = self._pattern_value(antenna, frequency, zenith)
        north, east, up = frequency.north_east_up_m
        correction = (
            variation
            - north * math.cos(transmit_azimuth_rad) * math.cos(transmit_elevation_rad)
            - east * math.sin(transmit_azimuth_rad) * math.cos(transmit_elevation_rad)
            - up * math.sin(transmit_elevation_rad)
        )
        return float(correction), True


@dataclass(slots=True)
class _BlqStation:
    amplitudes_m: np.ndarray
    phases_deg: np.ndarray


class BlqOceanLoading:
    """BLQ ocean-loading displacement model."""

    SPEED = np.array(
        [
            1.40519e-4,
            1.45444e-4,
            1.3788e-4,
            1.45842e-4,
            7.2921e-5,
            6.7598e-5,
            7.2523e-5,
            6.4959e-5,
            5.3234e-6,
            2.6392e-6,
            3.982e-7,
        ],
        dtype=float,
    )
    ANGULAR_FACTORS = np.array(
        [
            [2.0, 0.0, 2.0, 2.0, 1.0, 1.0, -1.0, 1.0, 0.0, 0.0, 2.0],
            [-2.0, 0.0, -3.0, 0.0, 0.0, -2.0, 0.0, -3.0, 2.0, 1.0, 0.0],
            [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, -1.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.25, -0.25, -0.25, -0.25, 0.0, 0.0, 0.0],
        ],
        dtype=float,
    )

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = ""
        self.stations: Dict[str, _BlqStation] = {}
        if path:
            self.load(path)

    @staticmethod
    def _key(value: str) -> str:
        return str(value or "").strip().upper()

    def load(self, path: str | Path) -> None:
        source = Path(path).expanduser()
        content = []
        with source.open("r", encoding="utf-8", errors="ignore") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or "$$" in line:
                    continue
                content.append(line)
        stations: Dict[str, _BlqStation] = {}
        index = 0
        while index + 6 < len(content):
            station = self._key(content[index])
            try:
                amplitudes = np.asarray(
                    [[float(value) for value in content[index + row].split()[:11]] for row in range(1, 4)],
                    dtype=float,
                )
                phases = np.asarray(
                    [[float(value) for value in content[index + row].split()[:11]] for row in range(4, 7)],
                    dtype=float,
                )
            except (TypeError, ValueError):
                index += 1
                continue
            if amplitudes.shape == (3, 11) and phases.shape == (3, 11):
                stations[station] = _BlqStation(amplitudes, phases)
                index += 7
            else:
                index += 1
        self.path = str(source)
        self.stations = stations

    def displacement(
        self,
        epoch: datetime,
        receiver_ecef: np.ndarray,
        station_id: str,
    ) -> Tuple[np.ndarray, bool]:
        station = self.stations.get(self._key(station_id))
        if station is None:
            return np.zeros(3, dtype=float), False
        if epoch.tzinfo is None:
            epoch = epoch.replace(tzinfo=timezone.utc)
        else:
            epoch = epoch.astimezone(timezone.utc)
        midnight = epoch.replace(hour=0, minute=0, second=0, microsecond=0)
        reference = datetime(1975, 1, 1, tzinfo=timezone.utc)
        # IERS arg2/RTKLIB counts 1975-01-01 as day one.  The previous
        # year-offset expression used a 2000 rather than 1900 epoch and put
        # every constituent roughly one century out of phase.
        days_since_1975 = (midnight - reference).days + 1
        fractional_day_seconds = (
            epoch.hour * 3600.0
            + epoch.minute * 60.0
            + epoch.second
            + epoch.microsecond * 1e-6
        )
        capt = (days_since_1975 * 1.000000035 + 27_392.500528) / 36_525.0
        degrees_to_radians = math.pi / 180.0
        sun_longitude = (
            279.69668 + (36_000.768930485 + 3.03e-4 * capt) * capt
        ) * degrees_to_radians
        moon_longitude = (
            ((1.9e-6 * capt - 0.001133) * capt + 481_267.88314137) * capt + 270.434358
        ) * degrees_to_radians
        perigee_longitude = (
            ((-1.2e-5 * capt - 0.010325) * capt + 4069.0340329577) * capt + 334.329653
        ) * degrees_to_radians
        angles = (
            self.SPEED * fractional_day_seconds
            + self.ANGULAR_FACTORS[0] * sun_longitude
            + self.ANGULAR_FACTORS[1] * moon_longitude
            + self.ANGULAR_FACTORS[2] * perigee_longitude
            + self.ANGULAR_FACTORS[3] * 2.0 * math.pi
        ) % (2.0 * math.pi)
        radial_west_south = np.sum(
            station.amplitudes_m
            * np.cos(angles[np.newaxis, :] - np.radians(station.phases_deg)),
            axis=1,
        )
        north_east_up = np.array(
            [-radial_west_south[2], -radial_west_south[1], radial_west_south[0]],
            dtype=float,
        )
        return neu_to_ecef(receiver_ecef, north_east_up), True


def propagated_ssr_yaw_deg(correction, gps_time_sow: float) -> Optional[float]:
    """Propagate SSR yaw to the observation epoch."""
    if correction is None:
        return None
    try:
        yaw = float(getattr(correction, "yaw_angle_deg"))
        yaw_rate = float(getattr(correction, "yaw_rate_deg_s"))
        correction_time = float(getattr(correction, "epoch_time"))
    except (TypeError, ValueError, AttributeError):
        return None
    dt = float(gps_time_sow) - correction_time
    if dt > 302_400.0:
        dt -= 604_800.0
    elif dt < -302_400.0:
        dt += 604_800.0
    update_index = getattr(correction, "update_interval", None)
    try:
        if update_index is not None:
            index = int(update_index)
            if 0 <= index < len(SSR_UPDATE_INTERVAL_SECONDS):
                dt -= 0.5 * SSR_UPDATE_INTERVAL_SECONDS[index]
    except (TypeError, ValueError):
        pass
    value = yaw + yaw_rate * dt
    return float(value) if math.isfinite(value) else None


__all__ = [
    "AntexCalibration",
    "BlqOceanLoading",
    "PhaseWindupModel",
    "datetime_to_mjd",
    "moon_position_ecef",
    "neu_to_ecef",
    "niell_mapping_factors",
    "propagated_ssr_yaw_deg",
    "satellite_body_axes",
    "shapiro_delay",
    "solid_earth_tide_displacement",
    "sun_position_ecef",
]
