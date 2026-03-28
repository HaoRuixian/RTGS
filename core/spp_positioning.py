"""RTKLIB-style single point positioning (SPP) with pseudorange observations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from core.BE2pos import brdc2pos
from core.broadcast_ephemeris import get_var_ura
from core.geo_utils import calculate_az_el, ecef2lla, get_freq, ionospheric_model, tropsphere_model


logger = logging.getLogger(__name__)

SYS_OFFSET_INDICES = {"R": 4, "E": 5, "C": 6, "I": 7, "J": 8}
EARTH_ROTATION_RATE = 7.2921151467e-5
WGS84_SEMI_MAJOR_AXIS_M = 6378137.0
GPS_L1_FREQUENCY_HZ = 1575.42e6
MIN_ERROR_ELEVATION_RAD = math.radians(5.0)
DEFAULT_CLOCK_CONSTRAINT_VARIANCE = 0.01
MAX_GDOP = 30.0


@dataclass
class PositioningResult:
    """SPP solution result."""

    timestamp: float
    epoch_time: datetime

    position_ecef: List[float]
    clock_bias: float
    clock_bias_seconds: float

    num_satellites: int
    residuals: List[float]
    variance: float
    std_dev_north: float
    std_dev_east: float
    std_dev_up: float
    std_dev_clock: float

    gdop: float
    pdop: float
    hdop: float
    vdop: float
    tdop: float

    latitude: float
    longitude: float
    height: float

    convergence: bool
    solution_status: str
    time_offsets: Dict[str, float] = field(default_factory=dict)


class SPPPositioner:
    """Single point positioning engine."""

    CLIGHT = 299792458.0

    DEFAULT_WEIGHT_MODE = "elevation"
    DEFAULT_MIN_ELEVATION = 10.0
    DEFAULT_MIN_SATELLITES = 4
    DEFAULT_IONOSPHERE_OPT = "IFLC"
    DEFAULT_TROPOSPHERE_MODEL = "Sastamoinen"
    DEFAULT_MAX_PDOP = 10.0

    MAX_ITERATIONS = 10
    CONVERGENCE_THRESHOLD = 1e-4

    def __init__(self, ephemeris_handler=None, config: Optional[Dict] = None):
        self.handler = ephemeris_handler
        self.last_solution: Optional[PositioningResult] = None
        self.logger = logging.getLogger(__name__)

        if config is None:
            config = {}

        self.ionosphere_option = config.get("ionosphere_option", self.DEFAULT_IONOSPHERE_OPT)
        self.troposphere_model = config.get("troposphere_model", self.DEFAULT_TROPOSPHERE_MODEL)
        self.MIN_SATELLITES = int(config.get("min_satellites", self.DEFAULT_MIN_SATELLITES))
        self.MIN_ELEVATION = float(
            config.get(
                "min_elevation",
                config.get("cutoff_elevation_deg", self.DEFAULT_MIN_ELEVATION),
            )
        )
        self.WEIGHT_MODE = config.get("weight_mode", self.DEFAULT_WEIGHT_MODE)
        self.gnss_systems = config.get("gnss_systems", ["G", "R", "E", "C", "J", "I"])
        self.uncertain_std_pos = float(config.get("uncertain_std_pos", 5.0))
        self.fixed_std_pos = float(config.get("fixed_std_pos", 2.5))
        self.max_pdop = float(config.get("max_pdop", self.DEFAULT_MAX_PDOP))

    def _find_signal(self, pr_list: List[Tuple[str, float]], bands: List[str]) -> Tuple[Optional[str], float]:
        for band in bands:
            for sig_id, value in pr_list:
                if sig_id.startswith(band):
                    return sig_id, float(value)
        return None, 0.0

    def _select_primary_signal(self, sat_key: str, pr_list: List[Tuple[str, float]]) -> Tuple[Optional[str], float]:
        system = sat_key[0]
        primary_bands = {
            "G": ["1"],
            "R": ["1"],
            "E": ["1"],
            "C": ["2", "1"],
            "J": ["1"],
            "I": ["5", "1"],
            "S": ["1"],
        }
        return self._find_signal(pr_list, primary_bands.get(system, ["1"]))

    def get_tgd_for_sys(self, sys: str, sat_key: str, sig_id: str) -> float:
        """Return the broadcast group delay correction in meters."""
        eph = self._fetch_ephemeris(sat_key)
        if not eph:
            return 0.0

        try:
            if sys in {"G", "J"}:
                return float(eph.get("TGD", 0.0) or 0.0) * self.CLIGHT

            if sys == "R":
                return -float(eph.get("tau_n", 0.0) or 0.0) * self.CLIGHT

            if sys == "E":
                band = sig_id[:1]
                if band == "5":
                    return float(eph.get("BGD_E5aE1", 0.0) or 0.0) * self.CLIGHT
                bgd = eph.get("BGD_E5bE1")
                if bgd is None:
                    bgd = eph.get("BGD_E5aE1")
                return float(bgd or 0.0) * self.CLIGHT

            if sys == "C":
                band = sig_id[:1]
                if band == "7":
                    return float(eph.get("TGD2", 0.0) or 0.0) * self.CLIGHT
                return float(eph.get("TGD1", 0.0) or 0.0) * self.CLIGHT

            if sys == "I":
                return float(eph.get("TGD", 0.0) or 0.0) * self.CLIGHT
        except (TypeError, ValueError):
            return 0.0

        return 0.0

    def _calculate_ionospheric_delay(
        self,
        rec_lla_rad: Tuple[float, float, float],
        azel_rad: Tuple[float, float],
        gps_time_sow: float,
        freq_hz: float = GPS_L1_FREQUENCY_HZ,
    ) -> Tuple[float, float]:
        if self.ionosphere_option == "IFLC":
            return 0.0, 0.0

        if self.ionosphere_option != "SINGLE":
            return 0.0, 0.0

        try:
            ion_model = [0.0] * 8
            delay = ionospheric_model(rec_lla_rad, azel_rad, gps_time_sow, ion_model)
            if isinstance(delay, tuple):
                ion_delay, ion_var = float(delay[0]), float(delay[1])
            else:
                ion_delay = float(delay or 0.0)
                ion_var = (ion_delay * 0.5) ** 2

            if freq_hz > 0.0:
                scale = (GPS_L1_FREQUENCY_HZ / float(freq_hz)) ** 2
                ion_delay *= scale
                ion_var *= scale ** 2
            return ion_delay, ion_var
        except Exception as exc:
            self.logger.debug("Ionospheric correction failed: %s", exc)
            return 0.0, 0.0

    def calculate_prange(self, sat_key: str, pr_list: List[Tuple[str, float]], fcn: int = 0) -> Tuple[float, float]:
        """Return corrected pseudorange and measurement variance."""
        system = sat_key[0]

        primary_bands = {
            "G": ["1"],
            "R": ["1"],
            "E": ["1"],
            "C": ["2", "1"],
            "J": ["1"],
            "I": ["5", "1"],
            "S": ["1"],
        }
        secondary_bands = {
            "G": ["2", "5"],
            "R": ["2", "3"],
            "E": ["7", "5"],
            "C": ["7", "6", "5"],
            "J": ["2", "5"],
            "I": ["9", "1"],
            "S": ["5"],
        }

        sig1_id, p1 = self._find_signal(pr_list, primary_bands.get(system, ["1"]))
        if sig1_id is None or p1 <= 0.0:
            return 0.0, 0.0

        if self.ionosphere_option != "IFLC":
            tgd = self.get_tgd_for_sys(system, sat_key, sig1_id)
            if system == "R":
                f1, _ = get_freq(sig1_id, sat_key, fcn)
                f2, _ = get_freq("2C", sat_key, fcn)
                if f1 > 0.0 and f2 > 0.0 and abs(f1 - f2) > 0.0:
                    gamma = (f1 / f2) ** 2
                    return p1 - tgd / (gamma - 1.0), 0.3 ** 2
            return p1 - tgd, 0.3 ** 2

        sig2_id, p2 = self._find_signal(pr_list, secondary_bands.get(system, ["2"]))
        if sig2_id is None or p2 <= 0.0:
            tgd = self.get_tgd_for_sys(system, sat_key, sig1_id)
            if system == "R":
                f1, _ = get_freq(sig1_id, sat_key, fcn)
                f2, _ = get_freq("2C", sat_key, fcn)
                if f1 > 0.0 and f2 > 0.0 and abs(f1 - f2) > 0.0:
                    gamma = (f1 / f2) ** 2
                    return p1 - tgd / (gamma - 1.0), 0.3 ** 2
            return p1 - tgd, 0.3 ** 2

        f1, _ = get_freq(sig1_id, sat_key, fcn)
        f2, _ = get_freq(sig2_id, sat_key, fcn)
        if f1 <= 0.0 or f2 <= 0.0 or abs(f1 - f2) < 1e-9:
            tgd = self.get_tgd_for_sys(system, sat_key, sig1_id)
            return p1 - tgd, 0.3 ** 2

        gamma = (f1 / f2) ** 2

        if system == "E" and sig2_id.startswith("7"):
            eph = self._fetch_ephemeris(sat_key)
            if eph is not None:
                bgd_e5a = eph.get("BGD_E5aE1")
                bgd_e5b = eph.get("BGD_E5bE1")
                if bgd_e5a is not None and bgd_e5b is not None:
                    try:
                        p2 -= (float(bgd_e5a) - float(bgd_e5b)) * self.CLIGHT
                    except (TypeError, ValueError):
                        pass

        p_if = (p2 - gamma * p1) / (1.0 - gamma)

        if system == "C":
            tgd1 = self.get_tgd_for_sys(system, sat_key, sig1_id)
            tgd2 = self.get_tgd_for_sys(system, sat_key, sig2_id)
            p_if -= (tgd2 - gamma * tgd1) / (1.0 - gamma)

        return p_if, (0.3 * 3.0) ** 2

    def _fetch_ephemeris(self, satellite_id: str) -> Optional[Dict]:
        if self.handler is None:
            return None

        try:
            if hasattr(self.handler, "get_ephemeris") and callable(getattr(self.handler, "get_ephemeris")):
                return self.handler.get_ephemeris(satellite_id)
        except Exception:
            pass

        try:
            broadcast_eph = getattr(self.handler, "broadcast_eph", None)
            if (
                broadcast_eph is not None
                and hasattr(broadcast_eph, "get_ephemeris")
                and callable(getattr(broadcast_eph, "get_ephemeris"))
            ):
                return broadcast_eph.get_ephemeris(satellite_id)
        except Exception:
            pass

        try:
            if hasattr(self.handler, "get_broadcast_eph_correction") and callable(
                getattr(self.handler, "get_broadcast_eph_correction")
            ):
                return self.handler.get_broadcast_eph_correction(satellite_id)
        except Exception:
            pass

        return None

    def _geodist(self, rs: np.ndarray, rr: np.ndarray) -> Tuple[Optional[float], Optional[np.ndarray]]:
        dr = rs - rr
        r2 = float(dr.dot(dr))
        if np.linalg.norm(rs) < WGS84_SEMI_MAJOR_AXIS_M:
            return None, None

        rho = math.sqrt(r2)
        if rho <= 0.0:
            return None, None

        line_of_sight = dr / rho
        sagnac = EARTH_ROTATION_RATE * (rs[0] * rr[1] - rs[1] * rr[0]) / self.CLIGHT
        return rho + sagnac, line_of_sight

    def var_err(
        self,
        sat_key: str,
        elevation_rad: float,
        snr: Optional[float] = None,
        pstd: Optional[float] = None,
    ) -> float:
        """Approximate pseudorange measurement variance, aligned with RTKLIB's `varerr`."""
        system_factor = {
            "G": 1.0,
            "R": 1.5,
            "S": 2.0,
            "E": 1.0,
            "C": 1.0,
            "J": 1.0,
            "I": 1.0,
        }.get(sat_key[0], 1.0)

        elevation_rad = max(float(elevation_rad), MIN_ERROR_ELEVATION_RAD)

        if self.WEIGHT_MODE == "equal":
            variance = 1.0 ** 2
        else:
            err_a = 0.3
            err_b = 0.3
            variance = err_a ** 2 + err_b ** 2 / max(math.sin(elevation_rad), 1e-3)

            if self.WEIGHT_MODE == "snr" and snr is not None and snr > 0.0:
                snr_max = 52.0
                snr_factor = 0.3
                variance += snr_factor ** 2 * math.pow(10.0, 0.1 * max(snr_max - float(snr), 0.0))

        if pstd is not None and pstd > 0.0:
            variance += float(pstd) ** 2

        if self.ionosphere_option == "IFLC":
            variance *= 3.0 ** 2

        return (system_factor ** 2) * variance

    def _normalize_position_guess(self, approx_position: Optional[np.ndarray]) -> Optional[np.ndarray]:
        if approx_position is None:
            return None

        try:
            arr = np.asarray(approx_position, dtype=float).reshape(-1)
        except Exception:
            return None

        if arr.size < 3 or not np.all(np.isfinite(arr[:3])):
            return None

        arr = arr[:3]
        if np.linalg.norm(arr) < 1e6:
            return None
        return arr.copy()

    def _compute_initial_position(self, observations: List[Dict]) -> Optional[np.ndarray]:
        if len(observations) < self.MIN_SATELLITES:
            return None

        sat_pos_arr = np.vstack([obs["sat_pos"] for obs in observations])
        centroid = sat_pos_arr.mean(axis=0)
        if np.linalg.norm(centroid) > 0.0:
            x_curr = centroid / np.linalg.norm(centroid) * WGS84_SEMI_MAJOR_AXIS_M
        else:
            x_curr = np.array([WGS84_SEMI_MAJOR_AXIS_M, 0.0, 0.0], dtype=float)
        clk_bias = 0.0

        for _ in range(10):
            design_rows: List[List[float]] = []
            residuals: List[float] = []

            for obs in observations:
                sat_pos = obs["sat_pos"]
                rho = np.linalg.norm(sat_pos - x_curr)
                if rho <= 0.0:
                    continue

                corrected_pr, _ = self.calculate_prange(obs["sat_key"], obs["pr_list"], obs["fcn"])
                if corrected_pr <= 0.0:
                    continue

                design_rows.append(
                    [
                        -(sat_pos[0] - x_curr[0]) / rho,
                        -(sat_pos[1] - x_curr[1]) / rho,
                        -(sat_pos[2] - x_curr[2]) / rho,
                        1.0,
                    ]
                )
                residuals.append(corrected_pr - (rho + clk_bias - self.CLIGHT * obs["sat_clock_correction_s"]))

            if len(design_rows) < 4:
                return None

            design = np.asarray(design_rows, dtype=float)
            residual_vec = np.asarray(residuals, dtype=float)

            try:
                dx, *_ = np.linalg.lstsq(design, residual_vec, rcond=None)
            except np.linalg.LinAlgError:
                return None

            x_curr = x_curr + dx[:3]
            clk_bias += float(dx[3])

            if np.linalg.norm(dx[:3]) < 1.0 and abs(dx[3]) < 1.0:
                return x_curr

        return x_curr

    def process_epoch(
        self,
        epoch_obs,
        approx_position: Optional[np.ndarray] = None,
    ) -> Optional[PositioningResult]:
        try:
            self._update_satellite_positions(epoch_obs)
            observations = self._extract_observations(epoch_obs)
            if len(observations) < self.MIN_SATELLITES:
                return None

            initial_guess = self._normalize_position_guess(approx_position)
            if initial_guess is None and self.last_solution is not None:
                initial_guess = self._normalize_position_guess(self.last_solution.position_ecef)
            if initial_guess is None:
                initial_guess = self._compute_initial_position(observations)
            if initial_guess is None:
                return None

            solution = self._solve_least_squares(observations, initial_guess, epoch_obs)
            if solution is not None and solution.solution_status != "No Fix":
                self.last_solution = solution
            return solution
        except Exception as exc:
            self.logger.error("SPP processing error: %s", exc, exc_info=True)
            return None

    def _build_be2pos_input(self, eph: Dict) -> Optional[Tuple[str, Dict]]:
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

    def _compute_satellite_clock_correction(self, eph: Dict, transmit_time: float) -> float:
        af0 = float(eph.get("af0", 0.0) or 0.0)
        af1 = float(eph.get("af1", 0.0) or 0.0)
        af2 = float(eph.get("af2", 0.0) or 0.0)
        toc = float(eph.get("toc") or eph.get("Toc") or 0.0)

        dt = transmit_time - toc
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
                tk = transmit_time - float(toe)
                if tk > 302400.0:
                    tk -= 604800.0
                elif tk < -302400.0:
                    tk += 604800.0
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

    def _update_satellite_positions(self, epoch_obs) -> None:
        gps_time = getattr(epoch_obs, "gps_time", None)
        if gps_time is None:
            return

        for sat_key, satellite in epoch_obs.satellites.items():
            signals = getattr(satellite, "signals", None)
            if not signals:
                continue

            pr_list: List[Tuple[str, float]] = []
            for sig_id, signal in signals.items():
                if signal is None:
                    continue
                pseudorange = getattr(signal, "pseudorange", None)
                if pseudorange is not None and float(pseudorange) > 0.0:
                    pr_list.append((sig_id, float(pseudorange)))
            if not pr_list:
                continue

            if getattr(satellite, "sat_pos_ecef", None) is not None and getattr(satellite, "sat_clk_corr", None) is not None:
                if not hasattr(satellite, "sat_var"):
                    satellite.sat_var = 30.0 ** 2
                continue

            eph = self._fetch_ephemeris(sat_key)
            if eph is None:
                continue

            primary_signal_id, primary_pr = self._select_primary_signal(sat_key, pr_list)
            if primary_signal_id is None or primary_pr <= 0.0:
                continue

            transmit_time = float(gps_time) - primary_pr / self.CLIGHT
            built_input = self._build_be2pos_input(eph)
            if built_input is None:
                continue

            sys_type, payload = built_input
            sat_pos = brdc2pos(payload, sys_type, transmit_time)
            if sat_pos is None:
                continue

            sat_clock_correction = self._compute_satellite_clock_correction(eph, transmit_time)
            sat_variance = get_var_ura(eph)

            satellite.sat_pos_ecef = np.asarray(sat_pos, dtype=float).tolist()
            satellite.sat_clk_corr = float(sat_clock_correction)
            satellite.sat_var = float(sat_variance if sat_variance is not None else 30.0 ** 2)

    def _extract_observations(self, epoch_obs) -> List[Dict]:
        observations: List[Dict] = []

        for sat_key, satellite in epoch_obs.satellites.items():
            if sat_key[0] not in self.gnss_systems:
                continue

            signals = getattr(satellite, "signals", None)
            if not signals:
                continue

            pr_list: List[Tuple[str, float]] = []
            snr_by_signal: Dict[str, float] = {}
            for sig_id, signal in signals.items():
                if signal is None:
                    continue
                pseudorange = getattr(signal, "pseudorange", None)
                if pseudorange is None or float(pseudorange) <= 0.0:
                    continue
                pr_list.append((sig_id, float(pseudorange)))
                snr_by_signal[sig_id] = float(getattr(signal, "snr", 0.0) or 0.0)

            if not pr_list:
                continue

            sat_pos = getattr(satellite, "sat_pos_ecef", None)
            sat_clk_corr = getattr(satellite, "sat_clk_corr", None)
            if sat_pos is None or sat_clk_corr is None:
                continue

            primary_signal_id, raw_pseudorange = self._select_primary_signal(sat_key, pr_list)
            if primary_signal_id is None or raw_pseudorange <= 0.0:
                continue

            eph = self._fetch_ephemeris(sat_key)
            frequency_channel = 0
            if eph is not None:
                try:
                    frequency_channel = int(eph.get("frequency_channel", 0) or 0)
                except (TypeError, ValueError):
                    frequency_channel = 0

            observations.append(
                {
                    "sat_key": sat_key,
                    "sat_pos": np.asarray(sat_pos, dtype=float),
                    "sat_clock_correction_s": float(sat_clk_corr),
                    "sat_var": float(getattr(satellite, "sat_var", 30.0 ** 2) or 30.0 ** 2),
                    "pr_list": pr_list,
                    "primary_signal_id": primary_signal_id,
                    "raw_pseudorange": float(raw_pseudorange),
                    "snr": snr_by_signal.get(primary_signal_id),
                    "fcn": frequency_channel,
                    "satellite_ref": satellite,
                }
            )

        return observations

    def _calculate_tropospheric_delay(
        self,
        rec_lla_rad: Tuple[float, float, float],
        azel_rad: Tuple[float, float],
    ) -> Tuple[float, float]:
        if self.troposphere_model in {"None", None}:
            return 0.0, 0.0

        if self.troposphere_model == "Sastamoinen":
            try:
                return tropsphere_model(rec_lla_rad, azel_rad, humi=0.7)
            except Exception as exc:
                self.logger.debug("Sastamoinen troposphere model failed: %s", exc)
                return 0.0, 0.0

        if self.troposphere_model == "HMSL":
            try:
                height_m = float(rec_lla_rad[2])
                trop_delay = max(0.0, 2.3 - 0.0001 * height_m)
                trop_var = 0.5 ** 2
                return trop_delay, trop_var
            except Exception as exc:
                self.logger.debug("HMSL troposphere model failed: %s", exc)
                return 0.0, 0.0

        self.logger.warning("Unknown troposphere model: %s", self.troposphere_model)
        return 0.0, 0.0

    def _build_measurement_model(self, observations: List[Dict], x_curr: np.ndarray, gps_time: float, iteration: int) -> Dict:
        nx = 4 + len(SYS_OFFSET_INDICES)
        rec_pos = x_curr[:3]
        rec_lla = None
        if np.linalg.norm(rec_pos) > WGS84_SEMI_MAJOR_AXIS_M * 0.5:
            try:
                rec_lla = ecef2lla(rec_pos)
            except Exception:
                rec_lla = None

        residual_rows: List[float] = []
        design_rows: List[np.ndarray] = []
        variance_rows: List[float] = []
        measurement_rows: List[np.ndarray] = []
        measurement_residuals: List[float] = []
        clock_state_present = [False] * (nx - 3)

        for obs in observations:
            sat_pos = obs["sat_pos"]
            rho, line_of_sight = self._geodist(sat_pos, rec_pos)
            if rho is None or line_of_sight is None:
                continue

            az_deg, el_deg = calculate_az_el(sat_pos, rec_pos)
            az_rad = math.radians(float(az_deg))
            el_rad = math.radians(float(el_deg))
            if el_deg < self.MIN_ELEVATION:
                continue

            try:
                obs["satellite_ref"].azimuth = float(az_deg)
                obs["satellite_ref"].elevation = float(el_deg)
            except Exception:
                pass

            iono_delay = 0.0
            iono_var = 0.0
            tropo_delay = 0.0
            tropo_var = 0.0

            if iteration > 0 and rec_lla is not None:
                if self.ionosphere_option == "SINGLE":
                    freq_hz, _ = get_freq(obs["primary_signal_id"], obs["sat_key"], obs["fcn"])
                    iono_delay, iono_var = self._calculate_ionospheric_delay(
                        rec_lla,
                        (az_rad, el_rad),
                        gps_time,
                        freq_hz=freq_hz or GPS_L1_FREQUENCY_HZ,
                    )
                tropo_delay, tropo_var = self._calculate_tropospheric_delay(rec_lla, (az_rad, el_rad))

            corrected_pr, code_bias_var = self.calculate_prange(obs["sat_key"], obs["pr_list"], obs["fcn"])
            if corrected_pr <= 0.0:
                continue

            residual = corrected_pr - (
                rho
                + x_curr[3]
                - self.CLIGHT * obs["sat_clock_correction_s"]
                + iono_delay
                + tropo_delay
            )

            design_row = np.zeros(nx, dtype=float)
            design_row[:3] = -line_of_sight
            design_row[3] = 1.0

            system = obs["sat_key"][0]
            if system in SYS_OFFSET_INDICES:
                state_index = SYS_OFFSET_INDICES[system]
                residual -= x_curr[state_index]
                design_row[state_index] = 1.0
                clock_state_present[state_index - 3] = True
            else:
                clock_state_present[0] = True

            variance = (
                float(obs["sat_var"])
                + float(code_bias_var)
                + self.var_err(obs["sat_key"], el_rad, snr=obs.get("snr"))
                + float(iono_var)
                + float(tropo_var)
            )
            variance = max(variance, 1e-6)

            residual_rows.append(float(residual))
            design_rows.append(design_row)
            variance_rows.append(variance)
            measurement_rows.append(design_row.copy())
            measurement_residuals.append(float(residual))

        for clock_offset_index, present in enumerate(clock_state_present):
            if present:
                continue
            design_row = np.zeros(nx, dtype=float)
            design_row[clock_offset_index + 3] = 1.0
            design_rows.append(design_row)
            residual_rows.append(0.0)
            variance_rows.append(DEFAULT_CLOCK_CONSTRAINT_VARIANCE)

        return {
            "H": np.asarray(design_rows, dtype=float),
            "v": np.asarray(residual_rows, dtype=float),
            "var": np.asarray(variance_rows, dtype=float),
            "measurement_H": np.asarray(measurement_rows, dtype=float),
            "measurement_v": np.asarray(measurement_residuals, dtype=float),
        }

    def _solve_least_squares(self, observations: List[Dict], approx_position: np.ndarray, epoch_obs) -> Optional[PositioningResult]:
        nx = 4 + len(SYS_OFFSET_INDICES)
        x_curr = np.zeros(nx, dtype=float)
        x_curr[:3] = approx_position.copy()

        convergence = False
        final_model = None

        for iteration in range(self.MAX_ITERATIONS):
            model = self._build_measurement_model(observations, x_curr, float(epoch_obs.gps_time), iteration)
            h_mat = model["H"]
            residual_vec = model["v"]
            variance_vec = model["var"]

            if model["measurement_H"].shape[0] < self.MIN_SATELLITES or h_mat.shape[0] < nx:
                return None

            sigma = np.sqrt(np.maximum(variance_vec, 1e-6))
            weighted_h = h_mat / sigma[:, np.newaxis]
            weighted_v = residual_vec / sigma

            try:
                dx, _, rank, _ = np.linalg.lstsq(weighted_h, weighted_v, rcond=None)
            except np.linalg.LinAlgError:
                return None

            if rank < nx:
                return None

            x_curr += dx
            final_model = model

            if np.linalg.norm(dx[:3]) < self.CONVERGENCE_THRESHOLD and abs(dx[3]) < self.CONVERGENCE_THRESHOLD:
                convergence = True
                break

        if final_model is None:
            return None

        final_model = self._build_measurement_model(observations, x_curr, float(epoch_obs.gps_time), self.MAX_ITERATIONS)
        h_mat = final_model["H"]
        residual_vec = final_model["v"]
        variance_vec = final_model["var"]
        measurement_h = final_model["measurement_H"]
        measurement_residuals = final_model["measurement_v"]

        if measurement_h.shape[0] < self.MIN_SATELLITES:
            return None

        sigma = np.sqrt(np.maximum(variance_vec, 1e-6))
        weighted_h = h_mat / sigma[:, np.newaxis]
        weighted_v = residual_vec / sigma
        dof = max(1, weighted_h.shape[0] - nx)
        variance_uow = float(np.dot(weighted_v, weighted_v) / dof)

        try:
            information_matrix = weighted_h.T @ weighted_h
            cov_matrix = variance_uow * np.linalg.inv(information_matrix + 1e-12 * np.eye(nx))
        except np.linalg.LinAlgError:
            cov_matrix = None

        lat_rad, lon_rad, height_m = ecef2lla(x_curr[:3])

        std_clock = math.sqrt(max(cov_matrix[3, 3], 0.0)) if cov_matrix is not None else float("inf")
        if cov_matrix is not None:
            sin_lat = math.sin(lat_rad)
            cos_lat = math.cos(lat_rad)
            sin_lon = math.sin(lon_rad)
            cos_lon = math.cos(lon_rad)
            rot = np.array(
                [
                    [-sin_lon, cos_lon, 0.0],
                    [-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat],
                    [cos_lat * cos_lon, cos_lat * sin_lon, sin_lat],
                ],
                dtype=float,
            )
            cov_enu = rot @ cov_matrix[:3, :3] @ rot.T
            std_east = math.sqrt(max(cov_enu[0, 0], 0.0))
            std_north = math.sqrt(max(cov_enu[1, 1], 0.0))
            std_up = math.sqrt(max(cov_enu[2, 2], 0.0))
        else:
            std_north = float("inf")
            std_east = float("inf")
            std_up = float("inf")

        gdop, pdop, hdop, vdop, tdop = self._compute_dop(x_curr[:3], measurement_h[:, :4])
        std_pos_3d = math.sqrt(std_north ** 2 + std_east ** 2 + std_up ** 2)

        solution_status = "No Fix"
        if convergence and gdop > 0.0 and gdop <= MAX_GDOP and pdop > 0.0 and pdop <= self.max_pdop:
            if std_pos_3d <= self.fixed_std_pos:
                solution_status = "Fixed"
            elif std_pos_3d <= self.uncertain_std_pos:
                solution_status = "Uncertain"

        epoch_time = getattr(epoch_obs, "utc_datetime", None) or datetime.now(timezone.utc)
        return PositioningResult(
            timestamp=float(epoch_obs.gps_time),
            epoch_time=epoch_time,
            position_ecef=x_curr[:3].tolist(),
            clock_bias=float(x_curr[3]),
            clock_bias_seconds=float(x_curr[3] / self.CLIGHT),
            num_satellites=int(measurement_h.shape[0]),
            residuals=measurement_residuals.tolist(),
            variance=variance_uow,
            std_dev_north=std_north,
            std_dev_east=std_east,
            std_dev_up=std_up,
            std_dev_clock=std_clock,
            gdop=gdop,
            pdop=pdop,
            hdop=hdop,
            vdop=vdop,
            tdop=tdop,
            latitude=math.degrees(lat_rad),
            longitude=math.degrees(lon_rad),
            height=height_m,
            convergence=convergence,
            solution_status=solution_status,
            time_offsets={
                system: float(x_curr[index] / self.CLIGHT)
                for system, index in SYS_OFFSET_INDICES.items()
                if index < nx
            },
        )

    def _compute_dop(self, position: np.ndarray, geometry_matrix: np.ndarray) -> Tuple[float, float, float, float, float]:
        if geometry_matrix is None or geometry_matrix.shape[0] < 4:
            return 0.0, 0.0, 0.0, 0.0, 0.0

        try:
            q_dop = np.linalg.inv(geometry_matrix.T @ geometry_matrix)
        except np.linalg.LinAlgError:
            return 0.0, 0.0, 0.0, 0.0, 0.0

        gdop = math.sqrt(max(np.trace(q_dop), 0.0))
        pdop = math.sqrt(max(q_dop[0, 0] + q_dop[1, 1] + q_dop[2, 2], 0.0))
        tdop = math.sqrt(max(q_dop[3, 3], 0.0))

        lat_rad, lon_rad, _ = ecef2lla(position)
        sin_lat = math.sin(lat_rad)
        cos_lat = math.cos(lat_rad)
        sin_lon = math.sin(lon_rad)
        cos_lon = math.cos(lon_rad)
        rot = np.array(
            [
                [-sin_lon, cos_lon, 0.0],
                [-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat],
                [cos_lat * cos_lon, cos_lat * sin_lon, sin_lat],
            ],
            dtype=float,
        )
        q_enu = rot @ q_dop[:3, :3] @ rot.T
        hdop = math.sqrt(max(q_enu[0, 0] + q_enu[1, 1], 0.0))
        vdop = math.sqrt(max(q_enu[2, 2], 0.0))
        return gdop, pdop, hdop, vdop, tdop
