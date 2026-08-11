"""SSR correction models and cache utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import threading
from typing import Dict, Mapping, Optional

import numpy as np


LIGHT_SPEED = 299_792_458.0
SECONDS_PER_WEEK = 604_800.0
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


@dataclass(slots=True)
class SsrOrbitCorrection:
    """Orbit correction in the radial, along-track, cross-track frame."""

    satellite_id: str
    epoch_time: float
    iod: int | None = None
    update_interval: int | None = None
    iod_ssr: int | None = None
    provider_id: int | None = None
    solution_id: int | None = None
    datum: int | None = None
    delta_radial_m: float = 0.0
    delta_along_track_m: float = 0.0
    delta_cross_track_m: float = 0.0
    dot_delta_radial_mps: float = 0.0
    dot_delta_along_track_mps: float = 0.0
    dot_delta_cross_track_mps: float = 0.0


@dataclass(slots=True)
class SsrClockCorrection:
    """Clock correction expressed as range-domain meters."""

    satellite_id: str
    epoch_time: float
    update_interval: int | None = None
    iod_ssr: int | None = None
    provider_id: int | None = None
    solution_id: int | None = None
    delta_clock_m: float = 0.0
    delta_clock_rate_mps: float = 0.0
    delta_clock_accel_mps2: float = 0.0
    high_rate_clock_m: float = 0.0


@dataclass(slots=True)
class AppliedSsrState:
    """Satellite state after optional SSR correction."""

    position_m: np.ndarray
    clock_bias_s: float
    velocity_mps: np.ndarray | None = None
    applied: bool = False
    orbit_applied: bool = False
    clock_applied: bool = False


@dataclass(slots=True)
class SsrSnapshot:
    """Thread-safe copy of the current SSR cache."""

    orbit: Dict[str, SsrOrbitCorrection] = field(default_factory=dict)
    clock: Dict[str, SsrClockCorrection] = field(default_factory=dict)
    code_biases: Dict[str, Dict[str, float]] = field(default_factory=dict)
    ura: Dict[str, float] = field(default_factory=dict)


def _time_difference(time_sow: float, reference_sow: float) -> float:
    """Return a week-wrapped time difference in seconds."""
    dt = float(time_sow) - float(reference_sow)
    if dt > SECONDS_PER_WEEK / 2.0:
        dt -= SECONDS_PER_WEEK
    elif dt < -SECONDS_PER_WEEK / 2.0:
        dt += SECONDS_PER_WEEK
    return dt


def _ssr_time_delta(time_sow: float, reference_sow: float, update_interval: int | None) -> float:
    """Return BNC-compatible SSR extrapolation time delta."""
    dt = _time_difference(time_sow, reference_sow)
    try:
        index = int(update_interval) if update_interval is not None else 0
    except (TypeError, ValueError):
        index = 0
    if 0 < index < len(SSR_UPDATE_INTERVAL_SECONDS):
        dt -= 0.5 * SSR_UPDATE_INTERVAL_SECONDS[index]
    return dt


def _finite_vector3(values: object) -> Optional[np.ndarray]:
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


class SsrCorrectionStore:
    """Thread-safe cache for live SSR orbit, clock, bias, and URA corrections."""

    def __init__(
        self,
        *,
        max_orbit_age_seconds: float = 120.0,
        max_clock_age_seconds: float = 60.0,
    ) -> None:
        self.max_orbit_age_seconds = float(max_orbit_age_seconds)
        self.max_clock_age_seconds = float(max_clock_age_seconds)
        self._orbit: Dict[str, SsrOrbitCorrection] = {}
        self._clock: Dict[str, SsrClockCorrection] = {}
        self._base_clock: Dict[str, SsrClockCorrection] = {}
        self._code_biases: Dict[str, Dict[str, float]] = {}
        self._ura: Dict[str, float] = {}
        self._lock = threading.Lock()

    def update_orbit(self, correction: SsrOrbitCorrection) -> None:
        with self._lock:
            self._orbit[correction.satellite_id] = correction

    def update_clock(self, correction: SsrClockCorrection) -> None:
        with self._lock:
            self._base_clock[correction.satellite_id] = correction
            self._clock[correction.satellite_id] = correction

    def update_high_rate_clock(self, correction: SsrClockCorrection) -> None:
        with self._lock:
            base = self._base_clock.get(correction.satellite_id)
            if base is None:
                return
            self._clock[correction.satellite_id] = SsrClockCorrection(
                satellite_id=correction.satellite_id,
                epoch_time=correction.epoch_time,
                update_interval=correction.update_interval,
                iod_ssr=correction.iod_ssr,
                provider_id=correction.provider_id,
                solution_id=correction.solution_id,
                delta_clock_m=base.delta_clock_m,
                delta_clock_rate_mps=base.delta_clock_rate_mps,
                delta_clock_accel_mps2=base.delta_clock_accel_mps2,
                high_rate_clock_m=correction.high_rate_clock_m,
            )

    def update_code_biases(self, satellite_id: str, code_biases: Mapping[str, float]) -> None:
        with self._lock:
            self._code_biases[satellite_id] = {str(key): float(value) for key, value in code_biases.items()}

    def update_ura(self, satellite_id: str, ura: float) -> None:
        with self._lock:
            self._ura[satellite_id] = float(ura)

    def get_orbit(self, satellite_id: str) -> Optional[SsrOrbitCorrection]:
        with self._lock:
            return self._orbit.get(satellite_id)

    def get_clock(self, satellite_id: str) -> Optional[SsrClockCorrection]:
        with self._lock:
            return self._clock.get(satellite_id)

    def get_code_biases(self, satellite_id: str) -> Dict[str, float]:
        with self._lock:
            return dict(self._code_biases.get(satellite_id, {}))

    def get_ura(self, satellite_id: str) -> Optional[float]:
        with self._lock:
            return self._ura.get(satellite_id)

    def has_orbit_clock_corrections(self) -> bool:
        """Return True once SSR orbit and clock streams are both populated."""
        with self._lock:
            return bool(self._orbit and self._clock)

    def snapshot(self) -> SsrSnapshot:
        with self._lock:
            return SsrSnapshot(
                orbit=dict(self._orbit),
                clock=dict(self._clock),
                code_biases={sat: dict(values) for sat, values in self._code_biases.items()},
                ura=dict(self._ura),
            )

    def clear(self) -> None:
        with self._lock:
            self._orbit.clear()
            self._clock.clear()
            self._base_clock.clear()
            self._code_biases.clear()
            self._ura.clear()

    def apply_to_state(
        self,
        satellite_id: str,
        position_m: object,
        velocity_mps: object,
        *,
        clock_bias_s: float,
        transmit_time: float,
        ephemeris_iod: int | None = None,
    ) -> AppliedSsrState:
        """Apply fresh SSR corrections to a broadcast satellite state."""
        position = _finite_vector3(position_m)
        velocity = _finite_vector3(velocity_mps)
        if position is None:
            position = np.asarray(position_m, dtype=float)
        if velocity is None:
            velocity = np.zeros(3, dtype=float)

        corrected_position = position.copy()
        corrected_velocity = velocity.copy()
        corrected_clock = float(clock_bias_s)
        orbit_applied = False
        clock_applied = False

        with self._lock:
            orbit = self._orbit.get(satellite_id)
            clock = self._clock.get(satellite_id)

        if orbit is None or clock is None:
            return AppliedSsrState(
                position_m=corrected_position,
                clock_bias_s=corrected_clock,
                velocity_mps=corrected_velocity,
            )

        if ephemeris_iod is not None and orbit.iod is not None:
            try:
                if int(ephemeris_iod) != int(orbit.iod):
                    return AppliedSsrState(
                        position_m=corrected_position,
                        clock_bias_s=corrected_clock,
                        velocity_mps=corrected_velocity,
                    )
            except (TypeError, ValueError):
                return AppliedSsrState(
                    position_m=corrected_position,
                    clock_bias_s=corrected_clock,
                    velocity_mps=corrected_velocity,
                )

        orbit_age = _time_difference(transmit_time, orbit.epoch_time)
        clock_age = _time_difference(transmit_time, clock.epoch_time)
        if abs(orbit_age) > self.max_orbit_age_seconds or abs(clock_age) > self.max_clock_age_seconds:
            return AppliedSsrState(
                position_m=corrected_position,
                clock_bias_s=corrected_clock,
                velocity_mps=corrected_velocity,
            )

        orbit_dt = _ssr_time_delta(transmit_time, orbit.epoch_time, orbit.update_interval)
        rac_delta = np.array(
            [
                orbit.delta_radial_m + orbit.dot_delta_radial_mps * orbit_dt,
                orbit.delta_along_track_m + orbit.dot_delta_along_track_mps * orbit_dt,
                orbit.delta_cross_track_m + orbit.dot_delta_cross_track_mps * orbit_dt,
            ],
            dtype=float,
        )
        transform = self._rac_to_ecef(position, velocity)
        if transform is None or not np.all(np.isfinite(rac_delta)):
            return AppliedSsrState(
                position_m=corrected_position,
                clock_bias_s=corrected_clock,
                velocity_mps=corrected_velocity,
            )

        clock_dt = _ssr_time_delta(transmit_time, clock.epoch_time, clock.update_interval)
        correction_m = (
            clock.delta_clock_m
            + clock.delta_clock_rate_mps * clock_dt
            + clock.delta_clock_accel_mps2 * clock_dt * clock_dt
            + clock.high_rate_clock_m
        )
        if not math.isfinite(correction_m):
            return AppliedSsrState(
                position_m=corrected_position,
                clock_bias_s=corrected_clock,
                velocity_mps=corrected_velocity,
            )

        corrected_position = position - transform @ rac_delta
        velocity_transform = self._rac_to_ecef(corrected_position, velocity)
        if velocity_transform is None:
            velocity_transform = transform
        rate_delta = np.array(
            [
                orbit.dot_delta_radial_mps,
                orbit.dot_delta_along_track_mps,
                orbit.dot_delta_cross_track_mps,
            ],
            dtype=float,
        )
        if np.all(np.isfinite(rate_delta)):
            corrected_velocity = velocity - velocity_transform @ rate_delta
        corrected_clock += correction_m / LIGHT_SPEED
        orbit_applied = True
        clock_applied = True

        return AppliedSsrState(
            position_m=corrected_position,
            clock_bias_s=corrected_clock,
            velocity_mps=corrected_velocity,
            applied=orbit_applied or clock_applied,
            orbit_applied=orbit_applied,
            clock_applied=clock_applied,
        )

    @staticmethod
    def _rac_to_ecef(position: np.ndarray, velocity: np.ndarray) -> Optional[np.ndarray]:
        """Build a matrix whose columns are radial, along-track, and cross-track unit vectors."""
        speed = np.linalg.norm(velocity)
        if speed <= 0.0:
            return None

        along = velocity / speed
        cross_vec = np.cross(position, velocity)
        cross_norm = np.linalg.norm(cross_vec)
        if cross_norm <= 0.0:
            return None

        cross_track = cross_vec / cross_norm
        radial = np.cross(along, cross_track)
        radial_norm = np.linalg.norm(radial)
        if radial_norm <= 0.0:
            return None

        radial = radial / radial_norm
        return np.column_stack((radial, along, cross_track))
