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
    high_rate_epoch_time: float | None = None


@dataclass(frozen=True, slots=True)
class SsrPhaseBias:
    """One signal-specific SSR carrier-phase bias."""

    signal_id: str
    bias_m: float
    integer_indicator: bool = False
    wide_lane_indicator: int = 0
    discontinuity_counter: int = 0


@dataclass(slots=True)
class SsrPhaseBiasCorrection:
    """Satellite phase-bias epoch and its ambiguity-resolution metadata."""

    satellite_id: str
    epoch_time: float
    update_interval: int | None = None
    iod_ssr: int | None = None
    provider_id: int | None = None
    solution_id: int | None = None
    dispersive_consistency: bool = False
    mw_consistency: bool = False
    yaw_angle_deg: float = 0.0
    yaw_rate_deg_s: float = 0.0
    biases: Dict[str, SsrPhaseBias] = field(default_factory=dict)


@dataclass(slots=True)
class AppliedSsrState:
    """Satellite state after optional SSR correction."""

    position_m: np.ndarray
    clock_bias_s: float
    velocity_mps: np.ndarray | None = None
    applied: bool = False
    orbit_applied: bool = False
    clock_applied: bool = False
    rejection_reason: str = ""


@dataclass(slots=True)
class SsrSnapshot:
    """Thread-safe copy of the current SSR cache."""

    orbit: Dict[str, SsrOrbitCorrection] = field(default_factory=dict)
    clock: Dict[str, SsrClockCorrection] = field(default_factory=dict)
    code_biases: Dict[str, Dict[str, float]] = field(default_factory=dict)
    phase_biases: Dict[str, SsrPhaseBiasCorrection] = field(default_factory=dict)
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
    """Return the midpoint-adjusted SSR extrapolation time delta."""
    dt = _time_difference(time_sow, reference_sow)
    try:
        index = int(update_interval) if update_interval is not None else 0
    except (TypeError, ValueError):
        index = 0
    if 0 < index < len(SSR_UPDATE_INTERVAL_SECONDS):
        dt -= 0.5 * SSR_UPDATE_INTERVAL_SECONDS[index]
    return dt


def ephemeris_iod_for_ssr(ephemeris: Mapping[str, object]) -> Optional[int]:
    """Return the broadcast-ephemeris IOD used by SSR orbit corrections.

    BDS D1/D2 is the important exception to the common IODE/IODnav lookup.
    BeiDou SSR derives its IOD from the GPST-aligned clock epoch instead of
    using the five-bit AODE carried by RTCM 1042.
    """
    satellite_id = str(ephemeris.get("satellite_id", "")).upper()
    system = satellite_id[:1]
    if not system:
        system_name = str(ephemeris.get("system", "")).strip().upper()
        if system_name in {"BEIDOU", "BDS"}:
            system = "C"

    if system == "C" and "aode" in ephemeris:
        try:
            toc_gpst = float(ephemeris.get("toc"))
        except (TypeError, ValueError, OverflowError):
            toc_gpst = math.nan
        if math.isfinite(toc_gpst):
            return int(toc_gpst / 720.0) % 240

    for key in ("iode", "iod_nav", "aode", "iodc"):
        value = ephemeris.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            continue
    return None


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


def _same_correction_set(first: object, second: object) -> bool:
    """Return whether two SSR records can be combined safely."""
    for attribute in ("provider_id", "solution_id", "iod_ssr"):
        first_value = getattr(first, attribute, None)
        second_value = getattr(second, attribute, None)
        if first_value is None or second_value is None:
            continue
        try:
            if int(first_value) != int(second_value):
                return False
        except (TypeError, ValueError, OverflowError):
            return False
    return True


class SsrCorrectionStore:
    """Thread-safe cache for live SSR orbit, clock, bias, and URA corrections."""

    def __init__(
        self,
        *,
        max_orbit_age_seconds: float = 120.0,
        max_clock_age_seconds: float = 60.0,
        max_phase_bias_age_seconds: float = 120.0,
    ) -> None:
        self.max_orbit_age_seconds = float(max_orbit_age_seconds)
        self.max_clock_age_seconds = float(max_clock_age_seconds)
        self.max_phase_bias_age_seconds = float(max_phase_bias_age_seconds)
        self._orbit: Dict[str, SsrOrbitCorrection] = {}
        self._clock: Dict[str, SsrClockCorrection] = {}
        self._base_clock: Dict[str, SsrClockCorrection] = {}
        self._code_biases: Dict[str, Dict[str, float]] = {}
        self._phase_biases: Dict[str, SsrPhaseBiasCorrection] = {}
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
            if base is None or not _same_correction_set(base, correction):
                return
            self._clock[correction.satellite_id] = SsrClockCorrection(
                satellite_id=correction.satellite_id,
                # Polynomial terms remain referenced to the base-clock epoch.
                epoch_time=base.epoch_time,
                update_interval=base.update_interval,
                iod_ssr=base.iod_ssr,
                provider_id=base.provider_id,
                solution_id=base.solution_id,
                delta_clock_m=base.delta_clock_m,
                delta_clock_rate_mps=base.delta_clock_rate_mps,
                delta_clock_accel_mps2=base.delta_clock_accel_mps2,
                high_rate_clock_m=correction.high_rate_clock_m,
                high_rate_epoch_time=correction.epoch_time,
            )

    def update_code_biases(self, satellite_id: str, code_biases: Mapping[str, float]) -> None:
        with self._lock:
            self._code_biases[satellite_id] = {str(key): float(value) for key, value in code_biases.items()}

    def update_phase_biases(self, correction: SsrPhaseBiasCorrection) -> None:
        with self._lock:
            self._phase_biases[correction.satellite_id] = correction

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

    def get_phase_biases(
        self,
        satellite_id: str,
        *,
        time_sow: float | None = None,
    ) -> Optional[SsrPhaseBiasCorrection]:
        """Return a fresh satellite phase-bias correction, if available."""
        with self._lock:
            correction = self._phase_biases.get(satellite_id)
            if correction is None:
                return None
            if time_sow is not None:
                age = abs(_time_difference(float(time_sow), correction.epoch_time))
                if age > self.max_phase_bias_age_seconds:
                    return None
            return correction

    def phase_bias_matches_orbit_clock(
        self,
        satellite_id: str,
        correction: SsrPhaseBiasCorrection,
    ) -> bool:
        """Return whether a phase bias belongs to the active state solution."""
        with self._lock:
            orbit = self._orbit.get(satellite_id)
            clock = self._clock.get(satellite_id)
        if orbit is None and clock is None:
            # Phase-only stores are valid for already-corrected satellite
            # states and for deterministic test/replay inputs.
            return True
        if orbit is None or clock is None:
            return False
        return (
            _same_correction_set(orbit, clock)
            and _same_correction_set(orbit, correction)
            and _same_correction_set(clock, correction)
        )

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
                phase_biases=dict(self._phase_biases),
                ura=dict(self._ura),
            )

    def clear(self) -> None:
        with self._lock:
            self._orbit.clear()
            self._clock.clear()
            self._base_clock.clear()
            self._code_biases.clear()
            self._phase_biases.clear()
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
            missing = "orbit-and-clock-missing"
            if orbit is not None:
                missing = "clock-missing"
            elif clock is not None:
                missing = "orbit-missing"
            return AppliedSsrState(
                position_m=corrected_position,
                clock_bias_s=corrected_clock,
                velocity_mps=corrected_velocity,
                rejection_reason=missing,
            )

        if not _same_correction_set(orbit, clock):
            return AppliedSsrState(
                position_m=corrected_position,
                clock_bias_s=corrected_clock,
                velocity_mps=corrected_velocity,
                rejection_reason="correction-set-mismatch",
            )

        if ephemeris_iod is not None and orbit.iod is not None:
            try:
                if int(ephemeris_iod) != int(orbit.iod):
                    return AppliedSsrState(
                        position_m=corrected_position,
                        clock_bias_s=corrected_clock,
                        velocity_mps=corrected_velocity,
                        rejection_reason="iod-mismatch",
                    )
            except (TypeError, ValueError):
                return AppliedSsrState(
                    position_m=corrected_position,
                    clock_bias_s=corrected_clock,
                    velocity_mps=corrected_velocity,
                    rejection_reason="invalid-iod",
                )

        orbit_age = _time_difference(transmit_time, orbit.epoch_time)
        clock_age = _time_difference(transmit_time, clock.epoch_time)
        if abs(orbit_age) > self.max_orbit_age_seconds or abs(clock_age) > self.max_clock_age_seconds:
            return AppliedSsrState(
                position_m=corrected_position,
                clock_bias_s=corrected_clock,
                velocity_mps=corrected_velocity,
                rejection_reason="stale-correction",
            )

        if clock.high_rate_epoch_time is not None:
            high_rate_age = abs(
                _time_difference(transmit_time, clock.high_rate_epoch_time)
            )
            if high_rate_age > min(self.max_clock_age_seconds, 10.0):
                # A high-rate delta is not part of the base polynomial and
                # must not survive a dropped high-rate update.
                clock = SsrClockCorrection(
                    satellite_id=clock.satellite_id,
                    epoch_time=clock.epoch_time,
                    update_interval=clock.update_interval,
                    iod_ssr=clock.iod_ssr,
                    provider_id=clock.provider_id,
                    solution_id=clock.solution_id,
                    delta_clock_m=clock.delta_clock_m,
                    delta_clock_rate_mps=clock.delta_clock_rate_mps,
                    delta_clock_accel_mps2=clock.delta_clock_accel_mps2,
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
                rejection_reason="invalid-orbit-frame",
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
                rejection_reason="invalid-clock-correction",
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
