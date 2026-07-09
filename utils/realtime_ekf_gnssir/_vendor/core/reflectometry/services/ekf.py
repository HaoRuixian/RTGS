"""Extended Kalman Filter mode for realtime GNSS-IR sea-level retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import math

import numpy as np

from ...geo_utils import get_freq
from ..config import EkfConfig, IrConfig, ProductsConfig
from ..models import ProductResult, ReflectorHeightResult, SeaLevelResult
from ..models import ObservationRecord, SnrUnit
from .preprocessing import _resolve_wavelength
from ..signal_utils import normalize_signal_id


@dataclass(slots=True)
class EkfPoint:
    timestamp: datetime
    reflector_height_m: float
    covariance_m2: float
    active_arc_count: int
    active_frequency_arc_count: int = 0
    active_satellite_arc_count: int = 0
    innovation_rms: float | None = None


@dataclass(slots=True)
class RhInitialization:
    reflector_height_m: float
    arc_count: int
    estimates: list[float]


@dataclass(slots=True)
class EkfOutput:
    timestamp: datetime
    reflector_height_m: float
    active_arc_count: int
    sample_count: int
    covariance_m2: float
    innovation_rms: float | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    active_frequency_arc_count: int = 0
    active_satellite_arc_count: int = 0


@dataclass(slots=True)
class _ArcState:
    key: tuple[str, str, str]
    wavelength_m: float
    pco_m: float = 0.0
    samples: list[ObservationRecord] = field(default_factory=list)
    detrended_samples: list[tuple[datetime, float, float]] = field(default_factory=list)
    initialized: bool = False
    ended: bool = False
    local_index: int | None = None
    last_timestamp: datetime | None = None
    last_elevation_deg: float | None = None
    arc_start_timestamp: datetime | None = None
    direction_sign: int | None = None
    varphi: float = 0.0
    amplitude: float = 0.0
    phase: float = 0.0
    sigma: float | None = None


class EkfReflectometryProcessor:
    """Online multi-arc EKF over RH and per-arc interferometric phase states.

    The implementation follows the MATLAB EKF_GNSSIR high-accuracy model in
    realtime/no-tide mode: one shared reflector height state RH, explicit
    local [varphi, A, phi] states per initialized arc, and full covariance
    across arcs until each arc ends.
    """

    def __init__(
        self,
        ir_config: IrConfig,
        products_config: ProductsConfig,
        *,
        station_id: str,
        sampling_interval_seconds: float | None = None,
    ) -> None:
        self.ir_config = ir_config
        self.config: EkfConfig = ir_config.ekf
        self.products_config = products_config
        self.station_id = station_id
        self.sampling_interval_seconds = float(sampling_interval_seconds or 0.0)
        self.rh = self._fallback_reflector_height()
        self.P = np.array([[float(self.config.initial_rh_variance)]], dtype=float)
        self.state_arcs: list[_ArcState] = []
        self.arc_states: dict[tuple[str, str, str], _ArcState] = {}
        self.points: list[EkfPoint] = []
        self.outputs: list[EkfOutput] = []
        self._last_output_time: datetime | None = None
        self.rh_initialized = False
        self.rh_initialization: RhInitialization | None = None

    def ingest(self, observations: list[ObservationRecord]) -> list[EkfOutput]:
        """Ingest decoded observations and return newly emitted EKF outputs."""
        new_outputs: list[EkfOutput] = []
        for timestamp, epoch_records in _group_by_timestamp(observations):
            self._ingest_epoch(timestamp, epoch_records)
            emitted = self._maybe_emit_output(timestamp)
            if emitted is not None:
                self.outputs.append(emitted)
                new_outputs.append(emitted)
        return new_outputs

    def build_products(self, outputs: list[EkfOutput] | None = None) -> list[ProductResult]:
        """Convert EKF outputs to the package's product model."""
        selected_outputs = outputs if outputs is not None else self.outputs
        products: list[ProductResult] = []
        for output in selected_outputs:
            confidence = _confidence_from_output(output)
            metadata = {
                "estimation_mode": "ekf",
                "active_arc_count": output.active_arc_count,
                "active_satellite_arc_count": output.active_satellite_arc_count,
                "active_frequency_arc_count": output.active_frequency_arc_count,
                "sample_count": output.sample_count,
                "covariance_m2": output.covariance_m2,
                "innovation_rms": output.innovation_rms,
                "window_start": output.window_start.isoformat() if output.window_start else None,
                "window_end": output.window_end.isoformat() if output.window_end else None,
                "windowing": "trailing",
                "rh_initialization": "lsp_grid",
                "rh_initial_arc_count": self.rh_initialization.arc_count if self.rh_initialization else 0,
                "rh_initial_m": self.rh_initialization.reflector_height_m if self.rh_initialization else None,
            }
            products.append(
                ReflectorHeightResult(
                    timestamp=output.timestamp,
                    value=output.reflector_height_m,
                    source_arc_count=output.active_arc_count,
                    confidence=confidence,
                    metadata=dict(metadata),
                )
            )
            if self.products_config.enable_sea_level and self.products_config.sea_level_reference is not None:
                sea_level_m = float(self.products_config.sea_level_reference) - output.reflector_height_m
                products.append(
                    SeaLevelResult(
                        timestamp=output.timestamp,
                        value=sea_level_m,
                        source_arc_count=output.active_arc_count,
                        confidence=confidence,
                        metadata={
                            **metadata,
                            "reference_level_m": self.products_config.sea_level_reference,
                        },
                    )
                )
        return products

    def snapshot_outputs(self) -> list[EkfOutput]:
        return list(self.outputs)

    def _fallback_reflector_height(self) -> float:
        if self.config.initial_rh_m is not None and math.isfinite(float(self.config.initial_rh_m)):
            return float(self.config.initial_rh_m)
        return 0.5 * (float(self.ir_config.min_reflector_height) + float(self.ir_config.max_reflector_height))

    def _ingest_epoch(self, timestamp: datetime, observations: list[ObservationRecord]) -> None:
        valid_epoch: list[tuple[_ArcState, float, float]] = []
        for observation in sorted(observations, key=lambda item: item.satellite_system_key):
            arc_state = self._arc_for_observation(observation)
            if arc_state is None:
                continue
            if self._should_start_new_arc(arc_state, observation):
                self._remove_arc(arc_state.key)
                arc_state = self._new_arc_state(observation)
            z, sin_elevation = self._append_and_detrend(arc_state, observation)
            if z is None or sin_elevation is None:
                continue
            if not arc_state.initialized:
                if not self.rh_initialized:
                    self._try_initialize_reflector_height()
            valid_epoch.append((arc_state, z, sin_elevation))

        if self.rh_initialized:
            self._prune_stale_arcs(timestamp)
            self._ekf_step(timestamp, valid_epoch)

    def _arc_for_observation(self, observation: ObservationRecord) -> _ArcState | None:
        if observation.elevation_deg is None or observation.azimuth_deg is None:
            return None
        if not (self.ir_config.min_reflector_height < self.ir_config.max_reflector_height):
            return None
        if observation.snr_unit == SnrUnit.LINEAR and observation.snr <= 0.0:
            return None
        key = observation.satellite_system_key
        arc_state = self.arc_states.get(key)
        if arc_state is None:
            arc_state = self._new_arc_state(observation)
        return arc_state

    def _new_arc_state(self, observation: ObservationRecord) -> _ArcState:
        key = observation.satellite_system_key
        wavelength = _resolve_observation_wavelength(observation, self.ir_config.wavelength_overrides_m)
        pco_m = _resolve_phase_center_offset(observation, self.config.phase_center_offsets_m)
        arc_state = _ArcState(key=key, wavelength_m=wavelength, pco_m=pco_m)
        self.arc_states[key] = arc_state
        return arc_state

    def _should_start_new_arc(self, arc_state: _ArcState, observation: ObservationRecord) -> bool:
        if arc_state.last_timestamp is None or arc_state.last_elevation_deg is None:
            return False
        time_gap = (observation.timestamp - arc_state.last_timestamp).total_seconds()
        if time_gap > self._arc_gap_threshold_seconds():
            return True
        if time_gap > 0 and arc_state.last_elevation_deg is not None and observation.elevation_deg is not None:
            delta = float(observation.elevation_deg) - float(arc_state.last_elevation_deg)
            step_sign = 1 if delta > 1e-6 else -1 if delta < -1e-6 else 0
            if arc_state.direction_sign is not None and step_sign != 0 and step_sign != arc_state.direction_sign:
                return True
        return False

    def _append_and_detrend(
        self,
        arc_state: _ArcState,
        observation: ObservationRecord,
    ) -> tuple[float | None, float | None]:
        elevation_deg = float(observation.elevation_deg)
        sin_elevation = math.sin(math.radians(elevation_deg))
        if arc_state.arc_start_timestamp is None:
            arc_state.arc_start_timestamp = observation.timestamp
        arc_state.samples.append(observation)
        max_samples = max(int(self.config.init_max_samples), int(self.config.init_min_samples))
        if len(arc_state.samples) > max_samples:
            arc_state.samples = arc_state.samples[-max_samples:]

        detrended_window = _detrend_observation_window(arc_state.samples)
        if detrended_window is None:
            arc_state.last_timestamp = observation.timestamp
            arc_state.last_elevation_deg = elevation_deg
            return None, None
        window_timestamps, residual, sin_values = detrended_window
        detrended = float(residual[-1])
        arc_state.detrended_samples = [
            (sample_time, float(sample_residual), float(sample_sin))
            for sample_time, sample_residual, sample_sin in zip(window_timestamps, residual, sin_values)
        ]

        if arc_state.last_elevation_deg is not None:
            delta = elevation_deg - arc_state.last_elevation_deg
            step_sign = 1 if delta > 1e-6 else -1 if delta < -1e-6 else 0
            if step_sign != 0 and arc_state.direction_sign is None:
                arc_state.direction_sign = step_sign
        arc_state.last_timestamp = observation.timestamp
        arc_state.last_elevation_deg = elevation_deg
        return detrended, sin_elevation

    def _arc_gap_threshold_seconds(self) -> float:
        configured_gap = float(self.config.max_time_gap_seconds)
        if self.sampling_interval_seconds <= 0.0:
            return configured_gap
        return max(configured_gap, 1.5 * self.sampling_interval_seconds)

    def _prune_stale_arcs(self, timestamp: datetime) -> None:
        threshold_seconds = self._arc_gap_threshold_seconds()
        stale_keys = [
            key
            for key, arc_state in self.arc_states.items()
            if arc_state.last_timestamp is not None
            and (timestamp - arc_state.last_timestamp).total_seconds() > threshold_seconds
        ]
        for key in stale_keys:
            self._remove_arc(key)

    def _try_initialize_reflector_height(self) -> None:
        initialization = _estimate_rh_lsp_from_arcs(
            list(self.arc_states.values()),
            min_height_m=self._rh_initialization_min_height(),
            max_height_m=self._rh_initialization_max_height(),
            min_samples=int(self.config.rh_init_min_samples),
            min_arcs=int(self.config.rh_init_min_arcs),
            max_arcs=int(self.config.rh_init_max_arcs),
            max_samples_per_arc=int(self.config.rh_init_max_samples_per_arc),
            search_step_m=float(self.config.rh_search_step_m),
            cycle_count=float(self.config.rh_init_cycles),
            average=str(self.config.rh_init_average or "mean"),
        )
        if initialization is None:
            return
        self.rh = initialization.reflector_height_m
        self.P = np.array([[float(self.config.initial_rh_variance)]], dtype=float)
        self.rh_initialized = True
        self.rh_initialization = initialization

    def _rh_initialization_min_height(self) -> float:
        value = self.config.rh_init_min_height_m
        if value is not None and math.isfinite(float(value)):
            return float(value)
        return float(self.ir_config.min_reflector_height)

    def _rh_initialization_max_height(self) -> float:
        value = self.config.rh_init_max_height_m
        if value is not None and math.isfinite(float(value)):
            return float(value)
        return float(self.ir_config.max_reflector_height)

    def _initialize_ready_arcs(
        self,
        x_pred: np.ndarray,
        P_pred: np.ndarray,
        current_sin_by_key: dict[tuple[str, str, str], float],
    ) -> tuple[np.ndarray, np.ndarray]:
        for arc_state in sorted(
            self.arc_states.values(),
            key=lambda arc: arc.arc_start_timestamp or datetime.min,
        ):
            if arc_state.initialized:
                continue
            samples = _arc_detrended_prefix(arc_state, max_samples=int(self.config.init_max_samples))
            if len(samples) < int(self.config.init_min_samples):
                continue
            rh_now = max(abs(float(x_pred[0])), 0.5)
            sin_values = np.asarray([item[2] for item in samples], dtype=float)
            reach = _first_reach_index(
                sin_values,
                arc_state.wavelength_m / rh_now,
                min_samples=int(self.config.init_min_samples),
            )
            if reach is None:
                continue
            y = np.asarray([item[1] for item in samples[:reach]], dtype=float)
            s = sin_values[:reach]
            A0, phi0, sigma = _fit_amplitude_phase(
                y,
                s,
                float(x_pred[0]),
                arc_state.wavelength_m,
                arc_state.pco_m,
            )
            if not np.isfinite(A0) or not np.isfinite(phi0):
                continue
            init_sin = current_sin_by_key.get(arc_state.key)
            if init_sin is None or not math.isfinite(float(init_sin)):
                init_sin = float(s[min(reach - 1, len(s) - 1)])
            x_pred, P_pred = self._insert_arc_into_state(
                x_pred,
                P_pred,
                arc_state,
                float(A0),
                float(phi0),
                float(init_sin),
            )
            arc_state.sigma = float(sigma) if np.isfinite(sigma) else None
        return x_pred, P_pred

    def _insert_arc_into_state(
        self,
        x_pred: np.ndarray,
        P_pred: np.ndarray,
        arc_state: _ArcState,
        amplitude: float,
        phase: float,
        sin_elevation: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        if arc_state.initialized:
            return x_pred, P_pred
        n_old = len(self.state_arcs)
        n_new = n_old + 1
        new_x = np.zeros(1 + 3 * n_new, dtype=float)
        old_rows = [0]
        new_rows = [0]
        if n_old:
            old_rows += list(range(1, 1 + n_old))
            old_rows += list(range(1 + n_old, 1 + 2 * n_old))
            old_rows += list(range(1 + 2 * n_old, 1 + 3 * n_old))
            new_rows += list(range(1, 1 + n_old))
            new_rows += list(range(1 + n_new, 1 + n_new + n_old))
            new_rows += list(range(1 + 2 * n_new, 1 + 2 * n_new + n_old))
        new_x[new_rows] = x_pred[old_rows]

        new_varphi_row = _idx_varphi(n_old, n_new)
        new_amplitude_row = _idx_amplitude(n_old, n_new)
        new_phase_row = _idx_phase(n_old, n_new)
        alpha = _alpha(arc_state.wavelength_m, sin_elevation)
        new_x[new_varphi_row] = alpha * (float(x_pred[0]) - arc_state.pco_m) + phase
        new_x[new_amplitude_row] = amplitude
        new_x[new_phase_row] = phase

        P_new = np.zeros((1 + 3 * n_new, 1 + 3 * n_new), dtype=float)
        P_new[np.ix_(new_rows, new_rows)] = P_pred[np.ix_(old_rows, old_rows)]
        local_var = float(self.config.local_state_variance)
        P_new[new_amplitude_row, new_amplitude_row] = local_var
        P_new[new_phase_row, new_phase_row] = local_var
        P_new[new_varphi_row, :] = alpha * P_new[0, :]
        P_new[:, new_varphi_row] = P_new[new_varphi_row, :]
        P_new[new_varphi_row, new_phase_row] = local_var
        P_new[new_phase_row, new_varphi_row] = local_var
        P_new[new_varphi_row, new_varphi_row] = alpha * alpha * P_new[0, 0] + local_var

        self.state_arcs.append(arc_state)
        arc_state.initialized = True
        arc_state.local_index = n_old
        self._set_state_vector(new_x)
        self._refresh_local_indices()
        return new_x, 0.5 * (P_new + P_new.T)

    def _remove_arc(self, key: tuple[str, str, str]) -> None:
        arc_state = self.arc_states.get(key)
        if arc_state is None:
            return
        if arc_state.initialized and arc_state in self.state_arcs:
            remove_index = self.state_arcs.index(arc_state)
            keep_local = [index for index in range(len(self.state_arcs)) if index != remove_index]
            old_x = self._state_vector()
            n_old = len(self.state_arcs)
            n_new = n_old - 1
            rows = (
                [0]
                + [_idx_varphi(index, n_old) for index in keep_local]
                + [_idx_amplitude(index, n_old) for index in keep_local]
                + [_idx_phase(index, n_old) for index in keep_local]
            )
            new_x = old_x[rows]
            self.P = self.P[np.ix_(rows, rows)]
            self.state_arcs.pop(remove_index)
            self._set_state_vector(new_x if n_new else np.asarray([new_x[0]], dtype=float))
            self._refresh_local_indices()
        self.arc_states.pop(key, None)

    def _refresh_local_indices(self) -> None:
        for index, arc_state in enumerate(self.state_arcs):
            arc_state.local_index = index

    def _ekf_step(self, timestamp: datetime, valid_epoch: list[tuple[_ArcState, float, float]]) -> None:
        current_sin_by_key = {arc_state.key: sin_elevation for arc_state, _z, sin_elevation in valid_epoch}
        x_pred = self._state_vector()
        n_local = len(self.state_arcs)
        P_pred = self._predict_covariance(x_pred, current_sin_by_key)
        x_pred = self._predict_state(x_pred, current_sin_by_key)
        x_pred, P_pred = self._initialize_ready_arcs(x_pred, P_pred, current_sin_by_key)
        n_local = len(self.state_arcs)

        measurements: list[tuple[float, _ArcState]] = []
        for arc_state, z_value, _sin_elevation in valid_epoch:
            if arc_state.local_index is None or arc_state not in self.state_arcs:
                continue
            measurements.append((z_value, arc_state))

        m = len(measurements)
        active_satellite_arc_count = _satellite_arc_count(arc_state for _z, arc_state in measurements)
        if m < int(self.config.min_active_arcs):
            self._set_state_vector(x_pred)
            self.P = P_pred
            return

        local_indices = [int(arc_state.local_index) for _z, arc_state in measurements]
        varphi_rows = [_idx_varphi(local_index, n_local) for local_index in local_indices]
        amplitude_rows = [_idx_amplitude(local_index, n_local) for local_index in local_indices]
        active_rows = varphi_rows + amplitude_rows

        H = np.zeros((m, 2 * m), dtype=float)
        z = np.zeros(m, dtype=float)
        h = np.zeros(m, dtype=float)
        for obs_index, (z_value, arc_state) in enumerate(measurements):
            local_index = int(arc_state.local_index)
            varphi = float(x_pred[_idx_varphi(local_index, n_local)])
            amplitude = float(x_pred[_idx_amplitude(local_index, n_local)])
            z[obs_index] = z_value
            h[obs_index] = amplitude * math.sin(varphi)
            H[obs_index, obs_index] = amplitude * math.cos(varphi)
            H[obs_index, m + obs_index] = math.sin(varphi)

        active_rows_array = np.asarray(active_rows, dtype=int)
        P_active = P_pred[np.ix_(active_rows_array, active_rows_array)]
        innovation = z - h
        r_vec = _measurement_noise_vector(innovation, self.config)
        S = H @ P_active @ H.T + np.diag(r_vec)
        K = P_pred[:, active_rows_array] @ H.T @ np.linalg.pinv(S)
        dx = K @ innovation
        x_new = x_pred + dx
        P_new = P_pred - K @ (H @ P_pred[active_rows_array, :])
        P_new = 0.5 * (P_new + P_new.T)
        P_new[0, 0] = max(P_new[0, 0], np.finfo(float).eps)
        self._set_state_vector(x_new)
        self.P = P_new
        innovation_rms = float(np.sqrt(np.mean(np.square(innovation)))) if innovation.size else None
        self.points.append(
            EkfPoint(
                timestamp,
                self.rh,
                float(self.P[0, 0]),
                m,
                m,
                active_satellite_arc_count,
                innovation_rms,
            )
        )

    def _predict_state(
        self,
        x: np.ndarray,
        current_sin_by_key: dict[tuple[str, str, str], float],
    ) -> np.ndarray:
        n_local = len(self.state_arcs)
        x_pred = x.copy()
        x_pred[0] = x[0]
        if n_local:
            for local_index, arc_state in enumerate(self.state_arcs):
                sin_elevation = current_sin_by_key.get(arc_state.key)
                alpha = _alpha(arc_state.wavelength_m, sin_elevation)
                x_pred[_idx_varphi(local_index, n_local)] = (
                    alpha * (float(x_pred[0]) - arc_state.pco_m)
                    + x[_idx_phase(local_index, n_local)]
                )
        return x_pred

    def _predict_covariance(
        self,
        x: np.ndarray,
        current_sin_by_key: dict[tuple[str, str, str], float],
    ) -> np.ndarray:
        n_local = len(self.state_arcs)
        if n_local == 0:
            P_pred = self.P.copy()
            P_pred[0, 0] += float(self.config.q_rh)
            return P_pred

        state_size = 1 + 3 * n_local
        F = np.zeros((state_size, state_size), dtype=float)
        F[0, 0] = 1.0
        for local_index, arc_state in enumerate(self.state_arcs):
            alpha = _alpha(arc_state.wavelength_m, current_sin_by_key.get(arc_state.key))
            F[_idx_varphi(local_index, n_local), 0] = alpha
            F[_idx_varphi(local_index, n_local), _idx_phase(local_index, n_local)] = 1.0
            F[_idx_amplitude(local_index, n_local), _idx_amplitude(local_index, n_local)] = 1.0
            F[_idx_phase(local_index, n_local), _idx_phase(local_index, n_local)] = 1.0
        P_pred = F @ self.P @ F.T
        P_pred[0, 0] += float(self.config.q_rh)
        varphi_rows = [_idx_varphi(index, n_local) for index in range(n_local)]
        amplitude_rows = [_idx_amplitude(index, n_local) for index in range(n_local)]
        phase_rows = [_idx_phase(index, n_local) for index in range(n_local)]
        if float(self.config.q_varphi) > 0.0:
            P_pred[varphi_rows, varphi_rows] += float(self.config.q_varphi)
        P_pred[amplitude_rows, amplitude_rows] += float(self.config.q_amplitude)
        if float(self.config.q_phase) > 0.0:
            P_pred[phase_rows, phase_rows] += float(self.config.q_phase)
        return 0.5 * (P_pred + P_pred.T)

    def _state_vector(self) -> np.ndarray:
        n_local = len(self.state_arcs)
        x = np.zeros(1 + 3 * n_local, dtype=float)
        x[0] = self.rh
        for index, arc_state in enumerate(self.state_arcs):
            x[_idx_varphi(index, n_local)] = arc_state.varphi
            x[_idx_amplitude(index, n_local)] = arc_state.amplitude
            x[_idx_phase(index, n_local)] = arc_state.phase
        return x

    def _set_state_vector(self, x: np.ndarray) -> None:
        self.rh = float(x[0])
        n_local = len(self.state_arcs)
        for index, arc_state in enumerate(self.state_arcs):
            arc_state.varphi = float(x[_idx_varphi(index, n_local)])
            arc_state.amplitude = float(x[_idx_amplitude(index, n_local)])
            arc_state.phase = float(x[_idx_phase(index, n_local)])

    def _maybe_emit_output(self, timestamp: datetime) -> EkfOutput | None:
        if not self.rh_initialized:
            return None
        interval = timedelta(seconds=float(self.config.output_interval_seconds))
        if self._last_output_time is not None and timestamp < self._last_output_time + interval:
            return None

        # Realtime products must be causal. A centered window made the first
        # valid EKF point wait for future observations after RH initialization.
        output_time = timestamp
        window_end = timestamp
        window_start = window_end - timedelta(seconds=float(self.config.output_window_seconds))
        window_points = [
            point
            for point in self.points
            if window_start <= point.timestamp <= window_end
            and point.active_arc_count >= int(self.config.min_active_arcs)
        ]
        if not window_points:
            return None
        self._last_output_time = output_time
        rh = float(np.mean([point.reflector_height_m for point in window_points]))
        covariance = float(np.mean([point.covariance_m2 for point in window_points]))
        active_arc_count = int(max(point.active_arc_count for point in window_points))
        active_frequency_arc_count = int(max(point.active_frequency_arc_count for point in window_points))
        active_satellite_arc_count = int(max(point.active_satellite_arc_count for point in window_points))
        innovation_values = [point.innovation_rms for point in window_points if point.innovation_rms is not None]
        innovation_rms = float(np.mean(innovation_values)) if innovation_values else None
        return EkfOutput(
            timestamp=output_time,
            reflector_height_m=rh,
            active_arc_count=active_arc_count,
            sample_count=len(window_points),
            covariance_m2=covariance,
            innovation_rms=innovation_rms,
            window_start=window_start,
            window_end=window_end,
            active_frequency_arc_count=active_frequency_arc_count,
            active_satellite_arc_count=active_satellite_arc_count,
        )


def _group_by_timestamp(observations: list[ObservationRecord]) -> list[tuple[datetime, list[ObservationRecord]]]:
    groups: dict[datetime, list[ObservationRecord]] = {}
    for observation in sorted(observations, key=lambda item: item.timestamp):
        groups.setdefault(observation.timestamp, []).append(observation)
    return list(groups.items())


def _idx_varphi(local_index: int, n_local: int) -> int:
    return 1 + local_index


def _idx_amplitude(local_index: int, n_local: int) -> int:
    return 1 + n_local + local_index


def _idx_phase(local_index: int, n_local: int) -> int:
    return 1 + 2 * n_local + local_index


def _alpha(wavelength_m: float, sin_elevation: float | None) -> float:
    if sin_elevation is None or not math.isfinite(float(sin_elevation)):
        return 0.0
    return (4.0 * math.pi / float(wavelength_m)) * float(sin_elevation)


def _satellite_arc_key(arc_state: _ArcState) -> tuple[str, str]:
    key = getattr(arc_state, "key", ("", "", ""))
    constellation = str(key[0]) if len(key) > 0 else ""
    satellite = str(key[1]) if len(key) > 1 else ""
    return constellation, satellite


def _satellite_arc_count(arcs) -> int:
    return len({_satellite_arc_key(arc) for arc in arcs if any(_satellite_arc_key(arc))})


def _fit_amplitude_phase(
    residual: np.ndarray,
    sin_elevation: np.ndarray,
    rh_m: float,
    wavelength_m: float,
    pco_m: float = 0.0,
) -> tuple[float, float, float]:
    theta = (4.0 * math.pi * (float(rh_m) - float(pco_m)) / float(wavelength_m)) * sin_elevation
    G = np.column_stack((np.sin(theta), np.cos(theta)))
    coef, *_ = np.linalg.lstsq(G, residual, rcond=None)
    c1, c2 = coef
    amplitude = math.hypot(float(c1), float(c2))
    phase = math.atan2(float(c2), float(c1))
    fitted = G @ coef
    sigma = float(np.std(residual - fitted)) if residual.size else float("nan")
    return amplitude, phase, sigma


def _measurement_noise_vector(innovation: np.ndarray, config: EkfConfig) -> np.ndarray:
    r_base = float(config.measurement_variance)
    r_vec = r_base * np.ones(innovation.size, dtype=float)
    if not bool(config.robust_measurement_update) or innovation.size == 0:
        return r_vec
    finite = innovation[np.isfinite(innovation)]
    if finite.size == 0:
        return r_vec
    center = float(np.median(finite))
    sigma = 1.4826 * float(np.median(np.abs(finite - center)))
    sigma = max(sigma, math.sqrt(max(r_base, np.finfo(float).eps)), float(config.robust_min_sigma))
    weights = np.minimum(1.0, (float(config.robust_huber_k) * sigma) / np.maximum(np.abs(innovation), np.finfo(float).eps))
    weights[~np.isfinite(weights)] = float(config.robust_min_weight)
    weights = np.maximum(weights, float(config.robust_min_weight))
    return r_base / np.square(weights)


def _first_reach_index(
    sin_values: np.ndarray,
    span_needed: float,
    *,
    min_samples: int,
) -> int | None:
    if sin_values.size < min_samples or not np.isfinite(span_needed) or span_needed <= 0:
        return None
    delta = np.abs(sin_values - sin_values[0])
    reached = np.flatnonzero(delta >= span_needed)
    if reached.size == 0:
        return None
    reach = max(int(reached[0]) + 1, int(min_samples))
    if reach > sin_values.size:
        return None
    return reach


def _estimate_rh_lsp_from_arcs(
    arcs: list[_ArcState],
    *,
    min_height_m: float,
    max_height_m: float,
    min_samples: int,
    min_arcs: int,
    max_arcs: int,
    max_samples_per_arc: int,
    search_step_m: float,
    cycle_count: float,
    average: str,
) -> RhInitialization | None:
    rh_grid = _make_rh_grid(min_height_m, max_height_m, search_step_m)

    ready_arcs = sorted(
        (arc for arc in arcs if not arc.initialized and len(arc.detrended_samples) >= min_samples),
        key=lambda arc: arc.arc_start_timestamp or arc.detrended_samples[0][0],
    )[:max(1, int(max_arcs))]
    estimates: list[float] = []
    rss_values: list[float] = []
    for arc_state in ready_arcs:
        samples = _arc_detrended_prefix(arc_state, max_samples=max_samples_per_arc)
        if len(samples) < min_samples:
            continue
        y = np.asarray([item[1] for item in samples], dtype=float)
        s = np.asarray([item[2] for item in samples], dtype=float)
        if not np.all(np.isfinite(y)) or not np.all(np.isfinite(s)):
            continue
        if float(np.ptp(s)) <= 1e-6:
            continue

        estimate = _estimate_arc_rh_grid(
            y,
            s,
            arc_state.wavelength_m,
            rh_grid,
            arc_state.pco_m,
            min_samples=min_samples,
            cycle_count=cycle_count,
        )
        if estimate is None:
            continue
        estimates.append(float(estimate[0]))
        rss_values.append(float(estimate[1]))

    if not estimates:
        return None
    arc_count = len(estimates)
    if arc_count < min_arcs:
        return None

    if average.strip().lower() in {"weighted_median", "median_weighted"}:
        reflector_height = _weighted_median(
            np.asarray(estimates, dtype=float),
            1.0 / np.maximum(np.asarray(rss_values, dtype=float), np.finfo(float).eps),
        )
    else:
        reflector_height = float(np.mean(estimates))
    return RhInitialization(
        reflector_height_m=reflector_height,
        arc_count=arc_count,
        estimates=[float(value) for value in estimates],
    )


def _estimate_arc_rh_grid(
    residual: np.ndarray,
    sin_elevation: np.ndarray,
    wavelength_m: float,
    rh_grid: np.ndarray,
    pco_m: float,
    *,
    min_samples: int,
    cycle_count: float,
) -> tuple[float, float] | None:
    best_rss = float("inf")
    best_rh = None
    for rh_value in rh_grid:
        delta_s_needed = (float(cycle_count) * float(wavelength_m)) / (2.0 * max(abs(float(rh_value)), 0.5))
        reach = _first_reach_index(sin_elevation, delta_s_needed, min_samples=min_samples)
        if reach is None:
            continue
        y = residual[:reach].reshape(-1, 1)
        s = sin_elevation[:reach]
        theta = (4.0 * math.pi * (float(rh_value) - float(pco_m)) / float(wavelength_m)) * s
        design = np.column_stack((np.sin(theta), np.cos(theta)))
        coef, *_ = np.linalg.lstsq(design, y, rcond=None)
        fitted = design @ coef
        rss = float(np.sum(np.square(y - fitted)) / max(reach - 2, 1))
        if rss < best_rss:
            best_rss = rss
            best_rh = float(rh_value)
    if best_rh is None:
        return None
    return best_rh, best_rss


def _make_rh_grid(min_height_m: float, max_height_m: float, step_m: float) -> np.ndarray:
    lo, hi = sorted((float(min_height_m), float(max_height_m)))
    step = float(step_m)
    values = np.arange(lo, hi + 0.5 * step, step, dtype=float)
    if values.size == 0 or values[-1] < hi:
        values = np.append(values, hi)
    return values


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    ok = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    values = values[ok]
    weights = weights[ok]
    if values.size == 0:
        return float("nan")
    order = np.argsort(values)
    values = values[order]
    weights = weights[order]
    cumulative = np.cumsum(weights) / np.sum(weights)
    return float(values[int(np.searchsorted(cumulative, 0.5, side="left"))])


def _resolve_phase_center_offset(
    observation: ObservationRecord,
    configured_offsets: list[dict[str, object]] | None,
) -> float:
    metadata_value = _metadata_float(observation.observation_metadata, "pco_m")
    if metadata_value is None:
        metadata_value = _metadata_float(observation.environment_metadata, "pco_m")
    if metadata_value is not None:
        return metadata_value

    signal = str(observation.signal).strip().upper()
    normalized_signal = str(observation.satellite_system_key[2]).strip().upper()
    constellation = str(observation.constellation).strip().upper()
    satellite = str(observation.satellite).strip().upper()
    for item in configured_offsets or []:
        if not isinstance(item, dict):
            continue
        item_constellation = str(item.get("constellation", "")).strip().upper()
        item_signal = str(item.get("signal", "")).strip().upper()
        item_prn = str(item.get("prn", item.get("satellite", ""))).strip().upper()
        if item_constellation and item_constellation != constellation:
            continue
        if item_signal and item_signal not in {signal, normalized_signal}:
            continue
        if item_prn and item_prn != satellite:
            continue
        try:
            return float(item.get("pco_m", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _resolve_observation_wavelength(
    observation: ObservationRecord,
    overrides: dict[str, float] | None = None,
) -> float:
    signal_id = normalize_signal_id(observation.signal)
    constellation = str(observation.constellation)
    satellite = str(observation.satellite or f"{constellation}00")
    fcn = int(_metadata_float(observation.observation_metadata, "glonass_fcn") or 0)
    if constellation.upper() == "R":
        _frequency_hz, wavelength_m = get_freq(signal_id, satellite, fcn)
        if wavelength_m > 0.0:
            return float(wavelength_m)
    return _resolve_wavelength(constellation, signal_id, overrides=overrides)


def _metadata_float(metadata: dict[str, object], key: str) -> float | None:
    try:
        value = metadata.get(key)
    except AttributeError:
        return None
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _arc_detrended_prefix(
    arc_state: _ArcState,
    *,
    max_samples: int,
) -> list[tuple[datetime, float, float]]:
    max_count = max(int(max_samples), 1)
    samples = arc_state.samples[:max_count]
    detrended_window = _detrend_observation_window(samples)
    if detrended_window is None:
        return []
    timestamps, residual, sin_values = detrended_window
    return [
        (sample_time, float(sample_residual), float(sample_sin))
        for sample_time, sample_residual, sample_sin in zip(timestamps, residual, sin_values)
    ]


def _detrend_observation_window(
    observations: list[ObservationRecord],
) -> tuple[list[datetime], np.ndarray, np.ndarray] | None:
    valid = [item for item in observations if item.elevation_deg is not None]
    if len(valid) < 3:
        return None
    timestamps = [item.timestamp for item in valid]
    sin_values = np.asarray(
        [math.sin(math.radians(float(item.elevation_deg))) for item in valid],
        dtype=float,
    )
    snr_values = np.asarray([_snr_db_hz(item) for item in valid], dtype=float)
    if not np.all(np.isfinite(sin_values)) or not np.all(np.isfinite(snr_values)):
        return None
    order = min(2, max(snr_values.size - 1, 1))
    trend = np.polyval(np.polyfit(sin_values, snr_values, order), sin_values)
    residual = snr_values - trend
    residual -= float(np.mean(residual))
    return timestamps, residual, sin_values


def _snr_db_hz(observation: ObservationRecord) -> float:
    if observation.snr_unit == SnrUnit.LINEAR:
        return 20.0 * math.log10(max(float(observation.snr), 1e-12))
    return float(observation.snr)


def _confidence_from_output(output: EkfOutput) -> float:
    arc_score = min(1.0, output.active_arc_count / 8.0)
    sample_score = min(1.0, output.sample_count / 4.0)
    sigma = math.sqrt(max(output.covariance_m2, 0.0))
    covariance_score = max(0.0, min(1.0, 1.0 - sigma / 0.5))
    return round(float((arc_score + sample_score + covariance_score) / 3.0), 4)


__all__ = ["EkfOutput", "EkfPoint", "EkfReflectometryProcessor", "RhInitialization"]
