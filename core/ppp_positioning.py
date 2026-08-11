"""Real-time PPP positioning with SSR corrections and optional PPP-AR."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import math
from typing import Dict, List, Optional, Tuple

import numpy as np

from core.config_paths import PROJECT_ROOT
from core.geo_utils import calculate_az_el, ecef2lla, get_freq
from core.ppp_physical_models import (
    AntexCalibration,
    BlqOceanLoading,
    PhaseWindupModel,
    neu_to_ecef,
    niell_mapping_factors,
    propagated_ssr_yaw_deg,
    satellite_body_axes,
    shapiro_delay,
    solid_earth_tide_displacement,
)
from core.spp_positioning import (
    DEFAULT_CLOCK_CONSTRAINT_VARIANCE,
    GPS_L1_FREQUENCY_HZ,
    SPPPositioner,
    PositioningResult,
    WGS84_SEMI_MAJOR_AXIS_M,
)


LOGGER = logging.getLogger(__name__)
LIGHT_SPEED = 299_792_458.0

PRIMARY_PRIORITIES = {
    # Match BNC's CNES PPP-AR signal selection (G1C + G2W).  L1W is a
    # fallback only; preferring it made the MW average depend on the noisier
    # encrypted-code observable even when clean C/A code was available.
    "G": ["1C", "1W", "1P", "1S", "1L", "1X", "1"],
    "R": ["1P", "1C", "1"],
    "E": ["1C", "1B", "1X", "1"],
    "C": ["2I", "2Q", "2X", "2", "1D", "1P", "1X", "1"],
    "J": ["1C", "1S", "1L", "1X", "1"],
    "I": ["5A", "5B", "5C", "5X", "5", "1"],
    "S": ["1C", "1"],
}
SECONDARY_PRIORITIES = {
    "G": ["2W", "2S", "2L", "2X", "2P", "2C", "2", "5Q", "5I", "5X", "5"],
    "R": ["2P", "2C", "2", "3I", "3Q", "3X", "3"],
    "E": ["5Q", "5I", "5X", "5", "7Q", "7I", "7X", "7"],
    "C": ["6I", "6Q", "6X", "6", "7I", "7Q", "7D", "7P", "7X", "7", "5D", "5P", "5X", "5"],
    "J": ["2S", "2L", "2X", "2", "5Q", "5I", "5X", "5"],
    "I": ["9A", "9B", "9C", "9X", "9", "1"],
    "S": ["5I", "5Q", "5X", "5"],
}
SYSTEM_OFFSET_ORDER = ("R", "E", "C", "I", "J")


@dataclass(slots=True)
class _PppMeasurement:
    sat_key: str
    kind: str
    value_m: float
    variance_m2: float
    sat_variance_m2: float
    sat_pos: np.ndarray
    sat_vel: Optional[np.ndarray]
    sat_clock_s: float
    system: str
    snr: Optional[float]
    fcn: int
    ambiguity_name: Optional[str] = None
    phase_pair: Optional[Tuple[str, str]] = None
    ionosphere_name: Optional[str] = None
    ionosphere_coefficient: float = 0.0
    wide_lane_name: Optional[str] = None
    wide_lane_coefficient: float = 0.0


@dataclass(slots=True)
class _MwTrack:
    """Running Melbourne-Wubbena estimate for one satellite signal pair."""

    count: int = 0
    mean_cycles: float = 0.0
    m2_cycles2: float = 0.0
    last_time: Optional[float] = None

    def add(self, value: float, epoch_time: float) -> None:
        if self.last_time is not None and abs(float(epoch_time) - self.last_time) > 180.0:
            self.count = 0
            self.mean_cycles = 0.0
            self.m2_cycles2 = 0.0
        self.count += 1
        delta = float(value) - self.mean_cycles
        self.mean_cycles += delta / self.count
        self.m2_cycles2 += delta * (float(value) - self.mean_cycles)
        self.last_time = float(epoch_time)

    @property
    def sigma_mean_cycles(self) -> float:
        if self.count < 2:
            return math.inf
        return math.sqrt(max(self.m2_cycles2 / (self.count - 1), 0.0) / self.count)


def _finite_float(value, default: Optional[float] = None) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def _finite_vector3(values) -> Optional[np.ndarray]:
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


class PPPPositioner:
    """
    PPP filter using ionosphere-free code and carrier-phase measurements.

    The filter applies SSR orbit, clock, code-bias, and phase-bias products,
    while retaining carrier ambiguities as float states.  Integer-compatible
    phase biases enable between-satellite PPP ambiguity resolution.
    """

    def __init__(self, ephemeris_handler=None, config: Optional[Dict] = None):
        config = dict(config or {})
        ppp_config = dict(config)
        ppp_config["prefer_gps_only"] = False
        ppp_config["allow_gps_fallback"] = False
        ppp_config["ionosphere_option"] = "IFLC"
        self.spp = SPPPositioner(ephemeris_handler=ephemeris_handler, config=ppp_config)
        self.handler = ephemeris_handler
        self.logger = LOGGER

        self.phase_sigma_m = float(config.get("ppp_phase_sigma_m", 0.01))
        observation_model = str(
            config.get("ppp_observation_model", "IFLC") or "IFLC"
        ).strip().upper()
        self.observation_model = (
            "UNCOMBINED" if observation_model in {"UNCOMBINED", "UC"} else "IFLC"
        )
        self.initial_position_sigma_m = float(config.get("ppp_initial_position_sigma_m", 100.0))
        # A standalone PPP run is normally seeded from an SPP solution.  That
        # seed must remain weak even when the operator selected a very tight
        # sigma for an explicitly configured station coordinate.
        self.spp_bootstrap_position_sigma_m = float(
            config.get("ppp_spp_bootstrap_sigma_m", 100.0)
        )
        # Independent mode is a hard safety boundary: RTCM 1005/1006,
        # configured truth coordinates, and arbitrary external seeds are never
        # allowed to initialize or constrain the PPP state.
        self.independent_mode = bool(config.get("ppp_independent_mode", False))
        # SPP is the normal PPP bootstrap.  RTCM 1005/1006 can be opted into
        # explicitly through ``ppp_use_station_apriori``.
        self.use_station_apriori = (
            bool(config.get("ppp_use_station_apriori", False))
            and not self.independent_mode
        )
        self.station_apriori_sigma_m = float(config.get("ppp_station_apriori_sigma_m", 0.05))
        self.initial_clock_sigma_m = float(config.get("ppp_initial_clock_sigma_m", 1000.0))
        self.initial_trop_sigma_m = float(config.get("ppp_initial_trop_sigma_m", 0.1))
        self.initial_ambiguity_sigma_m = float(config.get("ppp_initial_ambiguity_sigma_m", 1000.0))
        self.initial_ionosphere_sigma_m = float(
            config.get("ppp_initial_ionosphere_sigma_m", 30.0)
        )
        self.ionosphere_process_noise_mps = float(
            config.get("ppp_ionosphere_process_noise_mps", 0.001)
        )
        position_noise = config.get("ppp_position_process_noise_mps", config.get("random_walk", 0.0))
        self.position_process_noise_mps = float(0.0 if position_noise is None else position_noise)
        self.clock_process_noise_m = float(config.get("ppp_clock_process_noise_m", 100.0))
        self.system_clock_process_noise_m = float(config.get("ppp_system_clock_process_noise_m", 30.0))
        # Physical ZWD random-walk amplitude in m/sqrt(s).  The historical
        # ``_mps`` key is retained for configuration compatibility.
        self.trop_process_noise_mps = float(config.get("ppp_trop_process_noise_mps", 5e-5))
        self.initial_trop_gradient_sigma_m = float(
            config.get("ppp_initial_trop_gradient_sigma_m", 0.01)
        )
        self.trop_gradient_process_noise_mps = float(
            config.get("ppp_trop_gradient_process_noise_mps", 1e-5)
        )
        # A weak Gauss-Markov restoring term prevents the wet-delay state from
        # becoming permanently unobservable during poor geometry or outages.
        self.zwd_correlation_time_s = float(config.get("ppp_zwd_correlation_time_s", 7 * 86400.0))
        self.zwd_min_ratio = float(config.get("ppp_zwd_min_ratio", 0.05))
        self.zwd_max_ratio = float(config.get("ppp_zwd_max_ratio", 10.0))
        self.max_zwd_log_step = float(config.get("ppp_max_zwd_log_step", 0.25))
        self.ssr_default_sigma_m = float(config.get("ppp_ssr_default_sigma_m", 0.10))
        self.max_code_prefit_residual_m = float(config.get("ppp_max_code_prefit_residual_m", 200.0))
        self.max_phase_prefit_residual_m = float(config.get("ppp_max_phase_prefit_residual_m", 1.0))

        # Full physical modelling is enabled by the application defaults.
        # Keeping the constructor fallback disabled preserves compatibility for
        # callers that create a bare positioner around already-modelled data.
        self.precise_model_enabled = bool(config.get("ppp_precise_model_enabled", False))
        self._estimate_trop_gradients_requested = bool(
            config.get("ppp_estimate_trop_gradients", True)
        )
        self.estimate_trop_gradients = (
            self.precise_model_enabled and self._estimate_trop_gradients_requested
        )
        self.apply_phase_windup = self.precise_model_enabled and bool(
            config.get("ppp_apply_phase_windup", True)
        )
        self.use_ssr_yaw = self.precise_model_enabled and bool(config.get("ppp_use_ssr_yaw", True))
        self.apply_shapiro = self.precise_model_enabled and bool(
            config.get("ppp_apply_shapiro_delay", True)
        )
        self.apply_solid_earth_tide = self.precise_model_enabled and bool(
            config.get("ppp_apply_solid_earth_tide", True)
        )
        self.apply_ocean_loading = self.precise_model_enabled and bool(
            config.get("ppp_apply_ocean_loading", True)
        )
        self.apply_receiver_antenna = self.precise_model_enabled and bool(
            config.get("ppp_apply_receiver_antenna", True)
        )
        self.apply_satellite_antenna = self.precise_model_enabled and bool(
            config.get("ppp_apply_satellite_antenna", True)
        )
        self.antex_file = str(config.get("ppp_antex_file", "") or "").strip()
        self.blq_file = str(config.get("ppp_blq_file", "") or "").strip()
        self.receiver_antenna = str(config.get("ppp_receiver_antenna", "") or "").strip()
        self.station_id = str(config.get("ppp_station_id", "") or "").strip().upper()
        self.auto_ssr_apc_reference = bool(config.get("ppp_auto_ssr_apc_reference", True))
        self.ssr_apc_reference = bool(config.get("ppp_ssr_apc_reference", False))
        self.ssr_mountpoint = str(config.get("ppp_ssr_mountpoint", "") or "").strip()
        self.postfit_enabled = bool(
            config.get("ppp_postfit_enabled", self.precise_model_enabled)
        )
        self.max_code_postfit_residual_m = float(
            config.get("ppp_max_code_postfit_residual_m", 3.0)
        )
        self.max_phase_postfit_residual_m = float(
            config.get("ppp_max_phase_postfit_residual_m", 0.03)
        )
        antenna_eccentricity = config.get("ppp_antenna_eccentricity_neu_m", [0.0, 0.0, 0.0])
        try:
            self.antenna_eccentricity_neu_m = np.asarray(
                antenna_eccentricity,
                dtype=float,
            ).reshape(3)
        except (TypeError, ValueError):
            self.antenna_eccentricity_neu_m = np.zeros(3, dtype=float)
        self._windup_model = PhaseWindupModel()
        self._antex = AntexCalibration()
        self._ocean_loading = BlqOceanLoading()
        self._model_config_errors: List[str] = []
        self._load_external_models()

        # PPP-AR is deliberately opt-in at the measurement level: a float
        # solution remains available when the SSR provider does not publish
        # integer-compatible phase biases.  The default thresholds mirror the
        # conservative validation settings while allowing noisy real-time MW data to
        # converge before a constraint is attempted.
        self.ar_enabled = bool(config.get("ppp_ar_enabled", True))
        self.ar_systems = tuple(str(item).upper()[0] for item in config.get(
            "ppp_ar_systems", ["G", "E", "C", "J"]
        ))
        self.ar_min_epochs = int(config.get("ppp_ar_min_epochs", 30))
        self.ar_min_satellites = int(config.get("ppp_ar_min_satellites", 5))
        self.ar_min_elevation_deg = float(config.get("ppp_ar_min_elevation_deg", 10.0))
        self.ar_max_wl_fraction = float(config.get("ppp_ar_max_wl_fraction", 0.15))
        self.ar_max_nl_fraction = float(config.get("ppp_ar_max_nl_fraction", 0.12))
        self.ar_max_wl_sigma_cycles = float(config.get("ppp_ar_max_wl_sigma_cycles", 0.20))
        self.ar_max_nl_sigma_cycles = float(config.get("ppp_ar_max_nl_sigma_cycles", 0.20))
        self.ar_ratio_threshold = float(config.get("ppp_ar_ratio_threshold", 3.0))
        self.ar_constraint_sigma_m = float(config.get("ppp_ar_constraint_sigma_m", 1e-4))
        self.ar_max_position_shift_m = float(config.get("ppp_ar_max_position_shift_m", 0.50))
        self.ar_require_mw_consistency = bool(config.get("ppp_ar_require_mw_consistency", True))
        # Keep the library fallback compatible for callers that construct a
        # bare positioner; the application defaults enable the stricter mode.
        self.ar_require_full_group = bool(config.get("ppp_ar_require_full_group", False))

        self.state_names: List[str] = []
        self.x = np.zeros(0, dtype=float)
        self.P = np.zeros((0, 0), dtype=float)
        self.last_time: Optional[float] = None
        self.last_solution: Optional[PositioningResult] = None
        self.last_diagnostics: Dict[str, object] = {}
        self._amb_meta: Dict[str, Tuple[int, int]] = {}
        self._last_spp_failure = ""
        self._position_apriori_source = ""
        self._pending_initial_position_sigma_m = self.initial_position_sigma_m
        self._pending_initial_clock_m = 0.0
        self._pending_system_offsets_m: Dict[str, float] = {}
        self._mw_tracks: Dict[str, _MwTrack] = {}
        self._uncombined_ar_tracks: Dict[str, _MwTrack] = {}
        self._uncombined_ar_observations: List[dict] = []
        self._phase_bias_meta: Dict[str, tuple] = {}
        self._ar_observations: List[dict] = []
        self._current_epoch_time: float = 0.0
        self._current_epoch_datetime: Optional[datetime] = None
        self._solid_tide_ecef = np.zeros(3, dtype=float)
        self._ocean_tide_ecef = np.zeros(3, dtype=float)
        self._antenna_eccentricity_ecef = np.zeros(3, dtype=float)
        self._last_filter_measurements: List[_PppMeasurement] = []

    def _load_external_models(self) -> None:
        self._model_config_errors = []
        self._antex = AntexCalibration()
        self._ocean_loading = BlqOceanLoading()
        if self.antex_file:
            try:
                self._antex.load(self._resolve_model_path(self.antex_file))
                if not self._antex.loaded:
                    self._model_config_errors.append("ANTEX contains no supported antennas")
            except (OSError, ValueError) as exc:
                self._model_config_errors.append(f"ANTEX: {exc}")
        if self.blq_file:
            try:
                self._ocean_loading.load(self._resolve_model_path(self.blq_file))
                if not self._ocean_loading.stations:
                    self._model_config_errors.append("BLQ contains no station records")
            except (OSError, ValueError) as exc:
                self._model_config_errors.append(f"BLQ: {exc}")

    @staticmethod
    def _resolve_model_path(path: str) -> str:
        source = str(path or "").strip()
        if source.startswith("config/"):
            return str(PROJECT_ROOT / source)
        return source

    def _record_model_correction(self, name: str, value_m: float) -> None:
        if not math.isfinite(float(value_m)):
            return
        corrections = self.last_diagnostics.setdefault("model_corrections", {})
        entry = corrections.setdefault(name, {"count": 0, "max_abs_m": 0.0})
        entry["count"] = int(entry.get("count", 0)) + 1
        entry["max_abs_m"] = max(
            float(entry.get("max_abs_m", 0.0)),
            abs(float(value_m)),
        )

    def _resolve_receiver_antenna(self) -> str:
        if self.receiver_antenna:
            return self.receiver_antenna
        return str(getattr(self.handler, "last_antenna_descriptor", "") or "").strip()

    def _ssr_apc_reference_enabled(self) -> bool:
        if self.ssr_apc_reference:
            return True
        mountpoint = self.ssr_mountpoint.replace("\\", "/").rsplit("/", 1)[-1].upper()
        return self.auto_ssr_apc_reference and mountpoint.startswith("SSRA")

    def _prepare_epoch_models(self, receiver_position: np.ndarray) -> None:
        self._solid_tide_ecef = np.zeros(3, dtype=float)
        self._ocean_tide_ecef = np.zeros(3, dtype=float)
        self._antenna_eccentricity_ecef = np.zeros(3, dtype=float)
        self.last_diagnostics["precise_model_enabled"] = bool(self.precise_model_enabled)
        self.last_diagnostics["model_config_errors"] = list(self._model_config_errors)
        self.last_diagnostics["antex_loaded"] = bool(self._antex.loaded)
        self.last_diagnostics["blq_loaded"] = bool(self._ocean_loading.stations)
        self.last_diagnostics["receiver_antenna"] = self._resolve_receiver_antenna()
        self.last_diagnostics["ssr_apc_reference"] = self._ssr_apc_reference_enabled()
        self.last_diagnostics["ssr_reference_point"] = (
            "APC" if self._ssr_apc_reference_enabled() else "CoM"
        )
        self.last_diagnostics["receiver_coordinate_reference"] = "ARP"
        missing_models = []
        if not self._antex.loaded:
            missing_models.append("ANTEX unavailable: antenna PCO/PCV disabled")
        if self.apply_ocean_loading and not self._ocean_loading.stations:
            missing_models.append("BLQ unavailable: ocean loading disabled")
        self.last_diagnostics["missing_precise_models"] = missing_models
        self.last_diagnostics["model_corrections"] = {}
        if not self.precise_model_enabled:
            return
        try:
            self._antenna_eccentricity_ecef = neu_to_ecef(
                receiver_position,
                self.antenna_eccentricity_neu_m,
            )
        except (TypeError, ValueError, FloatingPointError):
            self._antenna_eccentricity_ecef = np.zeros(3, dtype=float)
        epoch = self._current_epoch_datetime
        if epoch is None:
            self.last_diagnostics["model_time_status"] = "UTC epoch unavailable"
            return
        self.last_diagnostics["model_time_status"] = "UTC"
        if self.apply_solid_earth_tide:
            try:
                self._solid_tide_ecef = solid_earth_tide_displacement(
                    epoch,
                    receiver_position,
                )
            except (TypeError, ValueError, FloatingPointError):
                self._solid_tide_ecef = np.zeros(3, dtype=float)
        if self.apply_ocean_loading and self._ocean_loading.stations:
            station_id = self.station_id
            if station_id:
                try:
                    displacement, found = self._ocean_loading.displacement(
                        epoch,
                        receiver_position,
                        station_id,
                    )
                    if found:
                        self._ocean_tide_ecef = displacement
                    else:
                        self.last_diagnostics["ocean_loading_status"] = (
                            f"station {station_id} not found"
                        )
                except (TypeError, ValueError, FloatingPointError):
                    self.last_diagnostics["ocean_loading_status"] = "calculation failed"
            else:
                self.last_diagnostics["ocean_loading_status"] = "station ID not configured"
        self.last_diagnostics["solid_tide_displacement_m"] = float(
            np.linalg.norm(self._solid_tide_ecef)
        )
        self.last_diagnostics["ocean_tide_displacement_m"] = float(
            np.linalg.norm(self._ocean_tide_ecef)
        )

    def update_config(self, settings: Dict) -> None:
        """Apply live positioning settings."""
        self.spp.MIN_SATELLITES = int(settings.get("min_satellites", self.spp.MIN_SATELLITES))
        if "cutoff_elevation_deg" in settings or "min_elevation" in settings:
            self.spp.MIN_ELEVATION = float(settings.get("cutoff_elevation_deg", settings.get("min_elevation")))
        if "max_pdop" in settings:
            self.spp.max_pdop = float(settings["max_pdop"])
        if "troposphere_model" in settings:
            self.spp.troposphere_model = settings["troposphere_model"]
        if "ppp_observation_model" in settings:
            configured_model = str(settings["ppp_observation_model"] or "IFLC").strip().upper()
            observation_model = (
                "UNCOMBINED"
                if configured_model in {"UNCOMBINED", "UC"}
                else "IFLC"
            )
            if observation_model != self.observation_model:
                self.observation_model = observation_model
                self.reset_filter()
        if "gnss_systems" in settings:
            self.spp.gnss_systems = SPPPositioner.normalize_gnss_systems(settings["gnss_systems"])
        if "require_ssr_corrections" in settings:
            self.spp.require_ssr_corrections = bool(settings["require_ssr_corrections"])
        if "weight_mode" in settings:
            self.spp.WEIGHT_MODE = settings["weight_mode"]
        if "code_sigma_m" in settings:
            self.spp.code_sigma_m = float(settings["code_sigma_m"])
        if "system_code_weight_factors" in settings:
            self.spp.system_code_weight_factors = {
                str(system).upper(): float(factor)
                for system, factor in dict(settings["system_code_weight_factors"]).items()
            }
        if "uncertain_std_pos" in settings:
            self.spp.uncertain_std_pos = float(settings["uncertain_std_pos"])
        if "fixed_std_pos" in settings:
            self.spp.fixed_std_pos = float(settings["fixed_std_pos"])
        if "ppp_independent_mode" in settings:
            independent_mode = bool(settings["ppp_independent_mode"])
            if independent_mode != self.independent_mode:
                self.independent_mode = independent_mode
                if independent_mode:
                    self.use_station_apriori = False
                self.reset_filter()
        if "ppp_use_station_apriori" in settings:
            use_station_apriori = (
                bool(settings["ppp_use_station_apriori"])
                and not self.independent_mode
            )
            if use_station_apriori != self.use_station_apriori:
                self.use_station_apriori = use_station_apriori
                self.reset_filter()
        for attr, key in (
            ("phase_sigma_m", "ppp_phase_sigma_m"),
            ("initial_position_sigma_m", "ppp_initial_position_sigma_m"),
            ("spp_bootstrap_position_sigma_m", "ppp_spp_bootstrap_sigma_m"),
            ("station_apriori_sigma_m", "ppp_station_apriori_sigma_m"),
            ("initial_clock_sigma_m", "ppp_initial_clock_sigma_m"),
            ("initial_trop_sigma_m", "ppp_initial_trop_sigma_m"),
            ("initial_ambiguity_sigma_m", "ppp_initial_ambiguity_sigma_m"),
            ("initial_ionosphere_sigma_m", "ppp_initial_ionosphere_sigma_m"),
            ("ionosphere_process_noise_mps", "ppp_ionosphere_process_noise_mps"),
            ("position_process_noise_mps", "ppp_position_process_noise_mps"),
            ("clock_process_noise_m", "ppp_clock_process_noise_m"),
            ("system_clock_process_noise_m", "ppp_system_clock_process_noise_m"),
            ("trop_process_noise_mps", "ppp_trop_process_noise_mps"),
            ("initial_trop_gradient_sigma_m", "ppp_initial_trop_gradient_sigma_m"),
            ("trop_gradient_process_noise_mps", "ppp_trop_gradient_process_noise_mps"),
            ("zwd_correlation_time_s", "ppp_zwd_correlation_time_s"),
            ("zwd_min_ratio", "ppp_zwd_min_ratio"),
            ("zwd_max_ratio", "ppp_zwd_max_ratio"),
            ("max_zwd_log_step", "ppp_max_zwd_log_step"),
            ("ssr_default_sigma_m", "ppp_ssr_default_sigma_m"),
            ("max_code_prefit_residual_m", "ppp_max_code_prefit_residual_m"),
            ("max_phase_prefit_residual_m", "ppp_max_phase_prefit_residual_m"),
            ("max_code_postfit_residual_m", "ppp_max_code_postfit_residual_m"),
            ("max_phase_postfit_residual_m", "ppp_max_phase_postfit_residual_m"),
        ):
            if key in settings:
                setattr(self, attr, float(settings[key]))
        for attr, key in (
            ("ar_min_elevation_deg", "ppp_ar_min_elevation_deg"),
            ("ar_max_wl_fraction", "ppp_ar_max_wl_fraction"),
            ("ar_max_nl_fraction", "ppp_ar_max_nl_fraction"),
            ("ar_max_wl_sigma_cycles", "ppp_ar_max_wl_sigma_cycles"),
            ("ar_max_nl_sigma_cycles", "ppp_ar_max_nl_sigma_cycles"),
            ("ar_ratio_threshold", "ppp_ar_ratio_threshold"),
            ("ar_constraint_sigma_m", "ppp_ar_constraint_sigma_m"),
            ("ar_max_position_shift_m", "ppp_ar_max_position_shift_m"),
        ):
            if key in settings:
                setattr(self, attr, float(settings[key]))
        if "ppp_ar_min_epochs" in settings:
            self.ar_min_epochs = int(settings["ppp_ar_min_epochs"])
        if "ppp_ar_min_satellites" in settings:
            self.ar_min_satellites = int(settings["ppp_ar_min_satellites"])
        if "ppp_ar_enabled" in settings:
            self.ar_enabled = bool(settings["ppp_ar_enabled"])
        if "ppp_ar_require_mw_consistency" in settings:
            self.ar_require_mw_consistency = bool(settings["ppp_ar_require_mw_consistency"])
        if "ppp_ar_require_full_group" in settings:
            self.ar_require_full_group = bool(settings["ppp_ar_require_full_group"])
        if "ppp_ar_systems" in settings:
            self.ar_systems = tuple(str(item).upper()[0] for item in settings["ppp_ar_systems"])
        if "ppp_postfit_enabled" in settings:
            self.postfit_enabled = bool(settings["ppp_postfit_enabled"])
        previous_apc_reference = self._ssr_apc_reference_enabled()
        model_changed = False
        for attr, key in (
            ("precise_model_enabled", "ppp_precise_model_enabled"),
            ("auto_ssr_apc_reference", "ppp_auto_ssr_apc_reference"),
            ("ssr_apc_reference", "ppp_ssr_apc_reference"),
        ):
            if key in settings:
                value = bool(settings[key])
                model_changed = model_changed or value != getattr(self, attr)
                setattr(self, attr, value)
        if "ppp_estimate_trop_gradients" in settings:
            self._estimate_trop_gradients_requested = bool(
                settings["ppp_estimate_trop_gradients"]
            )
        estimate_trop_gradients = (
            self.precise_model_enabled and self._estimate_trop_gradients_requested
        )
        model_changed = (
            model_changed
            or estimate_trop_gradients != self.estimate_trop_gradients
        )
        self.estimate_trop_gradients = estimate_trop_gradients
        for attr, key, default in (
            ("apply_phase_windup", "ppp_apply_phase_windup", True),
            ("use_ssr_yaw", "ppp_use_ssr_yaw", True),
            ("apply_shapiro", "ppp_apply_shapiro_delay", True),
            ("apply_solid_earth_tide", "ppp_apply_solid_earth_tide", True),
            ("apply_ocean_loading", "ppp_apply_ocean_loading", True),
            ("apply_receiver_antenna", "ppp_apply_receiver_antenna", True),
            ("apply_satellite_antenna", "ppp_apply_satellite_antenna", True),
        ):
            if key in settings or "ppp_precise_model_enabled" in settings:
                value = self.precise_model_enabled and bool(settings.get(key, default))
                model_changed = model_changed or value != getattr(self, attr)
                setattr(self, attr, value)
        external_changed = False
        for attr, key in (
            ("antex_file", "ppp_antex_file"),
            ("blq_file", "ppp_blq_file"),
            ("receiver_antenna", "ppp_receiver_antenna"),
            ("station_id", "ppp_station_id"),
        ):
            if key in settings:
                value = str(settings[key] or "").strip()
                if attr == "station_id":
                    value = value.upper()
                external_changed = external_changed or value != getattr(self, attr)
                setattr(self, attr, value)
        if "ppp_antenna_eccentricity_neu_m" in settings:
            try:
                eccentricity = np.asarray(
                    settings["ppp_antenna_eccentricity_neu_m"],
                    dtype=float,
                ).reshape(3)
            except (TypeError, ValueError):
                eccentricity = np.zeros(3, dtype=float)
            model_changed = model_changed or not np.allclose(
                eccentricity,
                self.antenna_eccentricity_neu_m,
            )
            self.antenna_eccentricity_neu_m = eccentricity
        if "ppp_ssr_mountpoint" in settings:
            self.ssr_mountpoint = str(settings["ppp_ssr_mountpoint"] or "").strip()
        model_changed = (
            model_changed
            or previous_apc_reference != self._ssr_apc_reference_enabled()
        )
        if external_changed:
            self._load_external_models()
        if model_changed or external_changed:
            self.reset_filter()
        self.spp.ssr_default_sigma_m = self.ssr_default_sigma_m

    def reset_filter(self) -> None:
        """Drop the PPP state so a changed initialization policy takes effect."""
        self.state_names.clear()
        self.x = np.zeros(0, dtype=float)
        self.P = np.zeros((0, 0), dtype=float)
        self.last_time = None
        self.last_solution = None
        self._amb_meta.clear()
        self._last_spp_failure = ""
        self._position_apriori_source = ""
        self._pending_initial_position_sigma_m = self.initial_position_sigma_m
        self._pending_initial_clock_m = 0.0
        self._pending_system_offsets_m.clear()
        self._mw_tracks.clear()
        self._uncombined_ar_tracks.clear()
        self._uncombined_ar_observations.clear()
        self._phase_bias_meta.clear()
        self._ar_observations.clear()
        self._windup_model.clear()
        self._last_filter_measurements.clear()

    @property
    def gnss_systems(self) -> List[str]:
        return self.spp.gnss_systems

    @gnss_systems.setter
    def gnss_systems(self, systems) -> None:
        self.spp.gnss_systems = SPPPositioner.normalize_gnss_systems(systems)

    def process_epoch(self, epoch_obs, approx_position: Optional[np.ndarray] = None) -> Optional[PositioningResult]:
        try:
            self._current_epoch_time = float(epoch_obs.gps_time)
            epoch_datetime = getattr(epoch_obs, "utc_datetime", None)
            if isinstance(epoch_datetime, datetime):
                if epoch_datetime.tzinfo is None:
                    epoch_datetime = epoch_datetime.replace(tzinfo=timezone.utc)
                self._current_epoch_datetime = epoch_datetime.astimezone(timezone.utc)
            else:
                self._current_epoch_datetime = None
            self.spp._update_satellite_positions(epoch_obs)
            raw_system_counts = self.spp._count_satellite_keys(getattr(epoch_obs, "satellites", {}).keys())
            observations = self.spp._extract_observations(epoch_obs)
            extracted_system_counts = self.spp._system_counts(observations)
            observations = self.spp._select_solution_observations(observations)
            selected_system_counts = self.spp._system_counts(observations)

            self.last_diagnostics = {
                "raw_system_counts": raw_system_counts,
                "extracted_system_counts": extracted_system_counts,
                "selected_system_counts": selected_system_counts,
                "used_system_counts": {},
                "used_satellites": [],
                "reject_counts": dict(getattr(self.spp, "_last_extract_reject_counts", {})),
                "solution_source": "PPP float",
                "fallback_reason": "",
                "failure_reason": "",
                "solver_failure_reason": "",
                "configured_systems": list(self.spp.gnss_systems),
                "position_apriori_source": self._position_apriori_source,
                "independent_mode": bool(self.independent_mode),
                "configured_position_used": False,
                "rtcm_station_position_used": False,
                "ar_enabled": bool(self.ar_enabled),
                "ar_status": "disabled" if not self.ar_enabled else "waiting",
                "ar_candidate_count": 0,
                "ar_fixed_count": 0,
                "ar_ratio": 0.0,
                "ar_rejection_reason": "",
            }
            if len(observations) < self.spp.MIN_SATELLITES:
                self.last_diagnostics["failure_reason"] = "not enough extracted observations"
                return None

            initial = self._resolve_initial_state(epoch_obs, observations, approx_position)
            if initial is None:
                self.last_diagnostics["failure_reason"] = "initial PPP position unavailable"
                self.last_diagnostics["solver_failure_reason"] = self._last_spp_failure
                return None
            self.last_diagnostics["position_apriori_source"] = self._position_apriori_source
            self._prepare_epoch_models(initial)

            ppp_measurements, phase_names, ionosphere_names, wide_lane_names = self._collect_measurements(
                observations,
                initial,
            )
            measurement_satellites = {measurement.sat_key for measurement in ppp_measurements}
            if len(measurement_satellites) < self.spp.MIN_SATELLITES:
                self.last_diagnostics["failure_reason"] = "not enough PPP measurements"
                return None

            reference_system, system_state_names = self._system_clock_names(observations)
            required_names = self._state_names(
                system_state_names,
                phase_names,
                ionosphere_names,
                wide_lane_names,
            )
            self._sync_state(required_names, initial, epoch_obs.gps_time)
            self._predict(float(epoch_obs.gps_time))

            (
                filtered_measurements,
                post_h,
                post_v,
                post_var,
                post_sats,
                code_geometry,
            ) = self._robust_filter_update(
                ppp_measurements,
                reference_system,
                system_state_names,
            )
            if len(set(post_sats)) < self.spp.MIN_SATELLITES:
                self.last_diagnostics["failure_reason"] = "not enough PPP usable measurements"
                return None
            float_position = self.x[:3].copy()
            float_state = self.x.copy()
            float_covariance = self.P.copy()
            float_postfit = self._weighted_rms(post_v, post_var)
            active_satellites = {measurement.sat_key for measurement in filtered_measurements}
            reset_ambiguities = set(self.last_diagnostics.get("postfit_reset_ambiguities", []))
            self._ar_observations = [
                item
                for item in self._ar_observations
                if item.get("sat_key") in active_satellites
                and item.get("amb_name") not in reset_ambiguities
            ]
            fixed_applied = self._attempt_ambiguity_resolution(
                filtered_measurements,
                post_v,
                post_var,
            )
            if fixed_applied:
                fixed_h, fixed_v, fixed_var, fixed_sats, fixed_geometry = self._build_filter_matrices(
                    filtered_measurements,
                    reference_system,
                    system_state_names,
                    initialise_ambiguities=False,
                    gate_outliers=False,
                )
                fixed_postfit = self._weighted_rms(fixed_v, fixed_var)
                position_shift = float(np.linalg.norm(self.x[:3] - float_position))
                if (
                    position_shift > self.ar_max_position_shift_m
                    or not math.isfinite(fixed_postfit)
                    or fixed_postfit > max(float_postfit + 0.02, float_postfit * 1.35 + 1e-6)
                ):
                    self.x = float_state
                    self.P = float_covariance
                    fixed_applied = False
                    self.last_diagnostics["ar_status"] = "rejected"
                    self.last_diagnostics["ar_fixed_count"] = 0
                    self.last_diagnostics["ar_rejection_reason"] = (
                        "postfit/position validation failed"
                    )
                else:
                    post_h, post_v, post_var, post_sats, code_geometry = (
                        fixed_h, fixed_v, fixed_var, fixed_sats, fixed_geometry
                    )
                    self.last_diagnostics["ar_position_shift_m"] = position_shift
                    self.last_diagnostics["ar_postfit_rms_m"] = fixed_postfit
            if not fixed_applied:
                self.last_diagnostics.setdefault("ar_status", "float")
                self.last_diagnostics.setdefault("ar_rejection_reason", "no validated integer candidate")
            if len(set(post_sats)) < self.spp.MIN_SATELLITES:
                self.last_diagnostics["failure_reason"] = "not enough PPP postfit measurements"
                return None

            result = self._make_result(
                epoch_obs,
                reference_system,
                system_state_names,
                post_h,
                post_v,
                post_var,
                post_sats,
                code_geometry,
                ar_fixed=fixed_applied,
            )
            self.last_solution = result
            self.last_time = float(epoch_obs.gps_time)
            self.last_diagnostics["used_system_counts"] = dict(result.used_system_counts)
            self.last_diagnostics["used_satellites"] = list(result.used_satellites)
            return result
        except Exception as exc:
            self.logger.error("PPP processing error: %s", exc, exc_info=True)
            self.last_diagnostics["failure_reason"] = f"PPP exception: {exc}"
            return None

    def _station_apriori_position(self) -> Optional[np.ndarray]:
        if self.independent_mode or not self.use_station_apriori:
            return None
        arr = _finite_vector3(getattr(self.handler, "last_station_coords", None))
        if arr is not None and np.linalg.norm(arr) > WGS84_SEMI_MAJOR_AXIS_M * 0.5:
            return arr
        return None

    def _apply_station_apriori_to_existing_state(self) -> None:
        station_pos = self._station_apriori_position()
        if station_pos is None or self._position_apriori_source == "station-1006":
            return
        if not all(name in self.state_names for name in ("X", "Y", "Z")):
            return
        for axis, value in zip(("X", "Y", "Z"), station_pos):
            idx = self.state_names.index(axis)
            self.x[idx] = float(value)
            self.P[idx, :] = 0.0
            self.P[:, idx] = 0.0
            self.P[idx, idx] = max(self.station_apriori_sigma_m, 1e-4) ** 2
        self._position_apriori_source = "station-1006"
        self.last_diagnostics["rtcm_station_position_used"] = True

    def _resolve_initial_state(self, epoch_obs, observations: List[Dict], approx_position) -> Optional[np.ndarray]:
        self._pending_initial_position_sigma_m = self.initial_position_sigma_m
        self._apply_station_apriori_to_existing_state()
        if self.x.size >= 3 and np.linalg.norm(self.x[:3]) > WGS84_SEMI_MAJOR_AXIS_M * 0.5:
            return self.x[:3].copy()

        arr = self._station_apriori_position()
        if arr is not None:
            self._pending_initial_position_sigma_m = max(self.station_apriori_sigma_m, 1e-4)
            self._position_apriori_source = "station-1006"
            self.last_diagnostics["rtcm_station_position_used"] = True
            self._prime_initial_clock(epoch_obs, arr)
            return arr

        if not self.independent_mode:
            arr = _finite_vector3(approx_position)
            if arr is not None and np.linalg.norm(arr) > WGS84_SEMI_MAJOR_AXIS_M * 0.5:
                self._position_apriori_source = "external"
                self.last_diagnostics["configured_position_used"] = True
                self._prime_initial_clock(epoch_obs, arr)
                return arr
        elif _finite_vector3(approx_position) is not None:
            self.last_diagnostics["external_position_ignored"] = True

        if self.last_solution is not None:
            arr = _finite_vector3(self.last_solution.position_ecef)
            if arr is not None and np.linalg.norm(arr) > WGS84_SEMI_MAJOR_AXIS_M * 0.5:
                self._position_apriori_source = "previous-ppp"
                return arr

        spp_seed = None if self.independent_mode else approx_position
        spp_result = self.spp.process_epoch(epoch_obs, spp_seed)
        if spp_result is None:
            self._last_spp_failure = str(self.spp.last_diagnostics.get("failure_reason", ""))
            return None
        self._last_spp_failure = ""
        self._position_apriori_source = (
            "spp-bootstrap-observation-only"
            if self.independent_mode
            else "spp-bootstrap"
        )
        self._pending_initial_position_sigma_m = max(
            float(self.spp_bootstrap_position_sigma_m), 1e-3
        )
        self._set_pending_clock_from_spp(spp_result)
        return np.asarray(spp_result.position_ecef, dtype=float)

    def _prime_initial_clock(self, epoch_obs, position: np.ndarray) -> None:
        """Estimate clock/ISB states while preserving the chosen position prior."""
        spp_result = self.spp.process_epoch(epoch_obs, position)
        if spp_result is not None:
            self._set_pending_clock_from_spp(spp_result)

    def _set_pending_clock_from_spp(self, spp_result: PositioningResult) -> None:
        clock_m = _finite_float(getattr(spp_result, "clock_bias", None), 0.0)
        self._pending_initial_clock_m = float(clock_m or 0.0)
        offsets = dict(getattr(spp_result, "time_offsets", {}) or {})
        self._pending_system_offsets_m = {
            str(system): float(offset_seconds) * LIGHT_SPEED
            for system, offset_seconds in offsets.items()
            if _finite_float(offset_seconds) is not None
        }

    def _find_signal(self, signals: Dict, priorities: List[str], *, require_phase: bool = False) -> Tuple[Optional[str], float, float]:
        for priority in priorities:
            for sig_id, signal in signals.items():
                if len(priority) > 1 and sig_id != priority:
                    continue
                if len(priority) == 1 and not sig_id.startswith(priority):
                    continue
                code = _finite_float(getattr(signal, "pseudorange", None))
                phase = _finite_float(getattr(signal, "phase", None))
                if code is None or code <= 0.0:
                    continue
                if require_phase and (phase is None or phase == 0.0):
                    continue
                return sig_id, float(code), float(phase or 0.0)
        return None, 0.0, 0.0

    @staticmethod
    def _matching_phase_bias(correction, signal_id: str):
        biases = getattr(correction, "biases", {}) or {}
        if signal_id in biases:
            return biases[signal_id]
        same_band = [bias for name, bias in biases.items() if str(name).startswith(signal_id[:1])]
        return same_band[0] if len(same_band) == 1 else None

    def _signal_antenna_correction(
        self,
        obs: Dict,
        signal_id: str,
        receiver_position: np.ndarray,
    ) -> float:
        if not self.precise_model_enabled or not self._antex.loaded:
            return 0.0
        epoch = self._current_epoch_datetime
        if epoch is None:
            return 0.0
        sat_key = str(obs["sat_key"])
        sat_pos = _finite_vector3(obs.get("sat_pos"))
        if sat_pos is None:
            return 0.0
        try:
            az_deg, el_deg = calculate_az_el(sat_pos, receiver_position)
            azimuth = math.radians(float(az_deg))
            elevation = math.radians(float(el_deg))
        except (TypeError, ValueError, FloatingPointError):
            return 0.0
        frequency_code = self._antex.frequency_code(sat_key, signal_id)
        if self.apply_receiver_antenna:
            receiver_correction, receiver_found = self._antex.receiver_correction(
                self._resolve_receiver_antenna(),
                frequency_code,
                elevation,
                azimuth,
            )
        else:
            receiver_correction, receiver_found = 0.0, True

        axes = satellite_body_axes(epoch, sat_pos) if self.apply_satellite_antenna else None
        satellite_correction = 0.0
        satellite_found = False
        if axes is not None:
            x_axis, y_axis, z_axis = axes
            sat_to_receiver = _finite_vector3(receiver_position - sat_pos)
            if sat_to_receiver is not None:
                norm = float(np.linalg.norm(sat_to_receiver))
                if norm > 0.0:
                    direction = sat_to_receiver / norm
                    body = np.array(
                        [
                            float(x_axis @ direction),
                            float(y_axis @ direction),
                            float(z_axis @ direction),
                        ],
                        dtype=float,
                    )
                    transmit_elevation = math.atan2(
                        body[2],
                        math.hypot(body[0], body[1]),
                    )
                    transmit_azimuth = math.atan2(body[1], body[0])
                    satellite_correction, satellite_found = self._antex.satellite_correction(
                        sat_key,
                        frequency_code,
                        transmit_elevation,
                        transmit_azimuth,
                    )
                    if self._ssr_apc_reference_enabled() and satellite_found:
                        reference_code = self._antex.reference_frequency_code(sat_key[0])
                        reference_correction, reference_found = self._antex.satellite_correction(
                            sat_key,
                            reference_code,
                            transmit_elevation,
                            transmit_azimuth,
                        )
                        if reference_found:
                            satellite_correction -= reference_correction
        if not receiver_found:
            missing_name = self._resolve_receiver_antenna() or "<not configured>"
            missing = self.last_diagnostics.setdefault("antex_missing_receiver", [])
            if missing_name not in missing:
                missing.append(missing_name)
        if not satellite_found:
            missing_name = f"{sat_key}:{frequency_code}"
            missing = self.last_diagnostics.setdefault("antex_missing_satellites", [])
            if missing_name not in missing:
                missing.append(missing_name)
        correction = float(receiver_correction + satellite_correction)
        self._record_model_correction("antenna", correction)
        return correction

    def _phase_windup_cycles(
        self,
        obs: Dict,
        phase_bias_correction,
        receiver_position: np.ndarray,
    ) -> float:
        if not self.apply_phase_windup or self._current_epoch_datetime is None:
            return 0.0
        sat_pos = _finite_vector3(obs.get("sat_pos"))
        if sat_pos is None:
            return 0.0
        sat_vel = _finite_vector3(obs.get("sat_vel"))
        yaw = None
        sat_system = str(obs.get("sat_key", ""))[:1]
        yaw_enabled = self.use_ssr_yaw and (
            not self.precise_model_enabled
            or (self.ar_enabled and sat_system in self.ar_systems)
        )
        if yaw_enabled:
            yaw = propagated_ssr_yaw_deg(
                phase_bias_correction,
                self._current_epoch_time,
            )
        try:
            cycles = self._windup_model.correction_cycles(
                str(obs["sat_key"]),
                self._current_epoch_datetime,
                receiver_position,
                sat_pos,
                satellite_velocity_ecef=sat_vel,
                yaw_angle_deg=yaw,
            )
        except (TypeError, ValueError, FloatingPointError):
            return 0.0
        self.last_diagnostics["ssr_yaw_satellite_count"] = int(
            self.last_diagnostics.get("ssr_yaw_satellite_count", 0)
        ) + int(yaw is not None and sat_vel is not None)
        return float(cycles)

    def _phase_if_measurement(
        self,
        obs: Dict,
        gps_time: float,
        receiver_position: Optional[np.ndarray] = None,
    ) -> Optional[Tuple[float, float, str, str, dict]]:
        if receiver_position is None:
            receiver_position = self.x[:3] if self.x.size >= 3 else np.zeros(3, dtype=float)
        sat_key = str(obs["sat_key"])
        system = sat_key[0]
        satellite = obs["satellite_ref"]
        signals = getattr(satellite, "signals", {}) or {}

        sig1, _code1, phase1 = self._find_signal(signals, PRIMARY_PRIORITIES.get(system, ["1"]), require_phase=True)
        sig2, _code2, phase2 = self._find_signal(signals, SECONDARY_PRIORITIES.get(system, ["2"]), require_phase=True)
        if sig1 is None or sig2 is None:
            return None

        f1, _ = get_freq(sig1, sat_key, obs["fcn"])
        f2, _ = get_freq(sig2, sat_key, obs["fcn"])
        if f1 <= 0.0 or f2 <= 0.0 or abs(f1 - f2) < 1e-9:
            return None

        phase_bias_correction = None
        ssr_store = getattr(self.handler, "ssr_corrections", None)
        if ssr_store is not None and hasattr(ssr_store, "get_phase_biases"):
            try:
                phase_bias_correction = ssr_store.get_phase_biases(sat_key, time_sow=gps_time)
            except Exception:
                phase_bias_correction = None
        raw_phase_bias_correction = phase_bias_correction
        if phase_bias_correction is not None and hasattr(
            ssr_store, "phase_bias_matches_orbit_clock"
        ):
            try:
                compatible = ssr_store.phase_bias_matches_orbit_clock(
                    sat_key,
                    phase_bias_correction,
                )
            except Exception:
                compatible = False
            if not compatible:
                phase_bias_correction = None
                raw_phase_bias_correction = None
                self.last_diagnostics["phase_bias_set_mismatch_count"] = int(
                    self.last_diagnostics.get("phase_bias_set_mismatch_count", 0)
                ) + 1
        bias1 = self._matching_phase_bias(phase_bias_correction, sig1) if phase_bias_correction else None
        bias2 = self._matching_phase_bias(phase_bias_correction, sig2) if phase_bias_correction else None
        integer_pair = (
            self.ar_enabled
            and system in self.ar_systems
            and bias1 is not None
            and bias2 is not None
            and bool(getattr(bias1, "integer_indicator", False))
            and bool(getattr(bias2, "integer_indicator", False))
        )
        # Phase biases are consumed only for enabled AR systems and require
        # both signals to carry the integer indicator.
        phase_bias_pair = bias1 is not None and bias2 is not None
        if self.precise_model_enabled:
            use_phase_bias = bool(integer_pair)
        else:
            use_phase_bias = phase_bias_pair and (not self.ar_enabled or integer_pair)
        if not use_phase_bias:
            phase_bias_correction = None
            bias1 = None
            bias2 = None
        if phase_bias_pair:
            self.last_diagnostics["phase_bias_pair_count"] = int(
                self.last_diagnostics.get("phase_bias_pair_count", 0)
            ) + 1
        if integer_pair:
            self.last_diagnostics["integer_phase_bias_pair_count"] = int(
                self.last_diagnostics.get("integer_phase_bias_pair_count", 0)
            ) + 1
        bias1_m = float(getattr(bias1, "bias_m", 0.0) or 0.0)
        bias2_m = float(getattr(bias2, "bias_m", 0.0) or 0.0)

        # RTCM phase biases are range-domain corrections, applied to carrier
        # phase after conversion from cycles to meters.
        windup_cycles = self._phase_windup_cycles(
            obs,
            raw_phase_bias_correction,
            receiver_position,
        )
        antenna1_m = self._signal_antenna_correction(obs, sig1, receiver_position)
        antenna2_m = self._signal_antenna_correction(obs, sig2, receiver_position)
        # SSR phase-bias values are range-domain observation corrections.  The
        # RTCM/IGS convention used by BNC-compatible streams adds them to the
        # carrier observable; antenna and wind-up terms are moved to the
        # observation side with the opposite sign.
        l1_m = phase1 * LIGHT_SPEED / f1 + bias1_m - antenna1_m - windup_cycles * LIGHT_SPEED / f1
        l2_m = phase2 * LIGHT_SPEED / f2 + bias2_m - antenna2_m - windup_cycles * LIGHT_SPEED / f2
        denom = f1 * f1 - f2 * f2
        coeff1 = f1 * f1 / denom
        coeff2 = -f2 * f2 / denom
        phase_if = coeff1 * l1_m + coeff2 * l2_m
        windup_if_m = windup_cycles * (
            coeff1 * LIGHT_SPEED / f1 + coeff2 * LIGHT_SPEED / f2
        )
        self._record_model_correction("phase_windup", windup_if_m)
        phase_var = (coeff1 * coeff1 + coeff2 * coeff2) * self.phase_sigma_m ** 2
        if not math.isfinite(phase_if) or phase_var <= 0.0:
            return None

        code1 = float(getattr(signals[sig1], "pseudorange", 0.0) or 0.0)
        code2 = float(getattr(signals[sig2], "pseudorange", 0.0) or 0.0)
        code1 += self.spp._get_code_bias(sat_key, sig1)
        code2 += self.spp._get_code_bias(sat_key, sig2)
        # The MW combination must use the same APC/ARP antenna reference as
        # the phase observables.  Omitting these terms shifts its fractional
        # wide-lane ambiguity and can prevent otherwise valid fixing.
        code1 -= antenna1_m
        code2 -= antenna2_m
        wavelength_wl = LIGHT_SPEED / (f1 - f2)
        phase_wl_m = (f1 * l1_m - f2 * l2_m) / (f1 - f2)
        code_nl_m = (f1 * code1 + f2 * code2) / (f1 + f2)
        mw_cycles = (phase_wl_m - code_nl_m) / wavelength_wl
        ar_data = {
            "f1_hz": float(f1),
            "f2_hz": float(f2),
            "mw_cycles": float(mw_cycles),
            "phase_bias_correction": phase_bias_correction,
            "bias1": bias1,
            "bias2": bias2,
            "integer_pair": bool(integer_pair),
            "dispersive_consistent": bool(
                getattr(phase_bias_correction, "dispersive_consistency", False)
            ),
            "mw_consistent": bool(
                getattr(phase_bias_correction, "mw_consistency", False)
            ),
            "windup_cycles": float(windup_cycles),
        }
        return phase_if, phase_var, sig1, sig2, ar_data

    def _code_if_measurement(
        self,
        obs: Dict,
        receiver_position: Optional[np.ndarray] = None,
    ) -> Optional[Tuple[float, float, str, str]]:
        """Build an SSR-corrected code IF without reapplying broadcast TGD/BGD."""
        if receiver_position is None:
            receiver_position = self.x[:3] if self.x.size >= 3 else np.zeros(3, dtype=float)
        sat_key = str(obs["sat_key"])
        system = sat_key[0]
        signals = getattr(obs["satellite_ref"], "signals", {}) or {}
        sig1, code1, _phase1 = self._find_signal(signals, PRIMARY_PRIORITIES.get(system, ["1"]))
        sig2, code2, _phase2 = self._find_signal(signals, SECONDARY_PRIORITIES.get(system, ["2"]))
        if sig1 is None or sig2 is None:
            return None

        f1, _ = get_freq(sig1, sat_key, obs["fcn"])
        f2, _ = get_freq(sig2, sat_key, obs["fcn"])
        if f1 <= 0.0 or f2 <= 0.0 or abs(f1 - f2) < 1e-9:
            return None

        code1 += self.spp._get_code_bias(sat_key, sig1)
        code2 += self.spp._get_code_bias(sat_key, sig2)
        code1 -= self._signal_antenna_correction(obs, sig1, receiver_position)
        code2 -= self._signal_antenna_correction(obs, sig2, receiver_position)
        denom = f1 * f1 - f2 * f2
        coeff1 = f1 * f1 / denom
        coeff2 = -f2 * f2 / denom
        code_if = coeff1 * code1 + coeff2 * code2
        code_var = (coeff1 * coeff1 + coeff2 * coeff2) * self.spp.code_sigma_m ** 2
        if not math.isfinite(code_if) or code_var <= 0.0:
            return None
        return code_if, code_var, sig1, sig2

    def _uncombined_phase_bias_pair(
        self,
        sat_key: str,
        sig1: str,
        sig2: str,
        gps_time: float,
    ) -> tuple:
        """Resolve one integer-compatible SSR phase-bias signal pair."""
        correction = None
        ssr_store = getattr(self.handler, "ssr_corrections", None)
        if ssr_store is not None and hasattr(ssr_store, "get_phase_biases"):
            try:
                correction = ssr_store.get_phase_biases(
                    sat_key,
                    time_sow=gps_time,
                )
            except Exception:
                correction = None
        if correction is not None and hasattr(
            ssr_store,
            "phase_bias_matches_orbit_clock",
        ):
            try:
                compatible = ssr_store.phase_bias_matches_orbit_clock(
                    sat_key,
                    correction,
                )
            except Exception:
                compatible = False
            if not compatible:
                correction = None
                self.last_diagnostics["phase_bias_set_mismatch_count"] = int(
                    self.last_diagnostics.get("phase_bias_set_mismatch_count", 0)
                ) + 1
        raw_correction = correction
        bias1 = self._matching_phase_bias(correction, sig1) if correction else None
        bias2 = self._matching_phase_bias(correction, sig2) if correction else None
        integer_pair = (
            self.ar_enabled
            and sat_key[0] in self.ar_systems
            and bias1 is not None
            and bias2 is not None
            and bool(getattr(bias1, "integer_indicator", False))
            and bool(getattr(bias2, "integer_indicator", False))
        )
        phase_bias_pair = bias1 is not None and bias2 is not None
        if phase_bias_pair:
            self.last_diagnostics["phase_bias_pair_count"] = int(
                self.last_diagnostics.get("phase_bias_pair_count", 0)
            ) + 1
        if integer_pair:
            self.last_diagnostics["integer_phase_bias_pair_count"] = int(
                self.last_diagnostics.get("integer_phase_bias_pair_count", 0)
            ) + 1
        if self.precise_model_enabled and not integer_pair:
            correction = None
            bias1 = None
            bias2 = None
        elif not self.precise_model_enabled and not phase_bias_pair:
            correction = None
            bias1 = None
            bias2 = None
        return correction, raw_correction, bias1, bias2, bool(integer_pair)

    def _append_uncombined_ar_observations(
        self,
        obs: Dict,
        signals: Tuple[str, str],
        frequencies: Tuple[float, float],
        ambiguity_names: Tuple[str, str],
        correction,
        biases: tuple,
    ) -> None:
        if correction is None or any(bias is None for bias in biases):
            return
        for signal_id, frequency_hz, ambiguity_name, bias in zip(
            signals,
            frequencies,
            ambiguity_names,
            biases,
        ):
            track = self._uncombined_ar_tracks.setdefault(
                ambiguity_name,
                _MwTrack(),
            )
            track.add(0.0, float(self._current_epoch_time))
            self._uncombined_ar_observations.append(
                {
                    "amb_name": ambiguity_name,
                    "sat_key": str(obs["sat_key"]),
                    "system": str(obs["sat_key"])[0],
                    "sat_pos": np.asarray(obs["sat_pos"], dtype=float),
                    "signal": signal_id,
                    "frequency_hz": float(frequency_hz),
                    "wavelength_m": float(LIGHT_SPEED / frequency_hz),
                    "track": track,
                    "integer_ready": bool(
                        getattr(bias, "integer_indicator", False)
                    ),
                    "provider_key": (
                        getattr(correction, "provider_id", None),
                        getattr(correction, "solution_id", None),
                        getattr(correction, "iod_ssr", None),
                    ),
                }
            )

    def _collect_uncombined_measurements(
        self,
        observations: List[Dict],
        receiver_position: np.ndarray,
    ) -> Tuple[List[_PppMeasurement], List[str], List[str]]:
        measurements: List[_PppMeasurement] = []
        ambiguity_names: List[str] = []
        ionosphere_names: List[str] = []
        self._ar_observations = []
        self._uncombined_ar_observations = []
        reject_counts: Dict[str, int] = dict(
            self.last_diagnostics.get("reject_counts", {})
        )

        def reject(system: str, reason: str) -> None:
            key = f"{system}:{reason}"
            reject_counts[key] = reject_counts.get(key, 0) + 1

        for obs in observations:
            sat_key = str(obs["sat_key"])
            system = sat_key[0]
            satellite = obs["satellite_ref"]
            signals = getattr(satellite, "signals", {}) or {}
            sig1, code1, phase1 = self._find_signal(
                signals,
                PRIMARY_PRIORITIES.get(system, ["1"]),
                require_phase=True,
            )
            sig2, code2, phase2 = self._find_signal(
                signals,
                SECONDARY_PRIORITIES.get(system, ["2"]),
                require_phase=True,
            )
            sat_pos = _finite_vector3(obs.get("sat_pos"))
            sat_clock = _finite_float(obs.get("sat_clock_correction_s"))
            if (
                sig1 is None
                or sig2 is None
                or sat_pos is None
                or sat_clock is None
            ):
                reject(system, "ppp-no-uncombined-pair")
                continue
            f1, _wavelength1 = get_freq(sig1, sat_key, int(obs["fcn"]))
            f2, _wavelength2 = get_freq(sig2, sat_key, int(obs["fcn"]))
            if f1 <= 0.0 or f2 <= 0.0 or abs(f1 - f2) < 1e-9:
                reject(system, "ppp-invalid-uncombined-frequency")
                continue

            correction, raw_correction, bias1, bias2, integer_pair = (
                self._uncombined_phase_bias_pair(
                    sat_key,
                    sig1,
                    sig2,
                    float(self._current_epoch_time),
                )
            )
            antenna1 = self._signal_antenna_correction(
                obs,
                sig1,
                receiver_position,
            )
            antenna2 = self._signal_antenna_correction(
                obs,
                sig2,
                receiver_position,
            )
            windup_cycles = self._phase_windup_cycles(
                obs,
                raw_correction,
                receiver_position,
            )
            bias1_m = float(getattr(bias1, "bias_m", 0.0) or 0.0)
            bias2_m = float(getattr(bias2, "bias_m", 0.0) or 0.0)
            wavelength1 = LIGHT_SPEED / f1
            wavelength2 = LIGHT_SPEED / f2
            corrected_codes = (
                float(code1) + self.spp._get_code_bias(sat_key, sig1) - antenna1,
                float(code2) + self.spp._get_code_bias(sat_key, sig2) - antenna2,
            )
            corrected_phases = (
                float(phase1) * wavelength1
                + bias1_m
                - antenna1
                - windup_cycles * wavelength1,
                float(phase2) * wavelength2
                + bias2_m
                - antenna2
                - windup_cycles * wavelength2,
            )
            if not all(
                math.isfinite(value)
                for value in (*corrected_codes, *corrected_phases)
            ):
                reject(system, "ppp-invalid-uncombined-observable")
                continue

            ionosphere_name = f"ION:{sat_key}"
            amb1 = f"AMB:{sat_key}:{sig1}"
            amb2 = f"AMB:{sat_key}:{sig2}"
            if ionosphere_name not in ionosphere_names:
                ionosphere_names.append(ionosphere_name)
            for ambiguity_name in (amb1, amb2):
                if ambiguity_name not in ambiguity_names:
                    ambiguity_names.append(ambiguity_name)
            ar_data = {
                "phase_bias_correction": correction,
                "bias1": bias1,
                "bias2": bias2,
            }
            for ambiguity_name in (amb1, amb2):
                self._update_phase_bias_continuity(ambiguity_name, ar_data)
            self._reset_ambiguity_on_slip(amb1, satellite, sig1, sig1)
            self._reset_ambiguity_on_slip(amb2, satellite, sig2, sig2)

            gamma = (f1 / f2) ** 2
            sat_variance = max(
                float(_finite_float(obs.get("sat_var"), 30.0 ** 2) or 30.0 ** 2),
                0.0,
            )
            common = dict(
                sat_key=sat_key,
                sat_variance_m2=sat_variance,
                sat_pos=sat_pos,
                sat_vel=_finite_vector3(obs.get("sat_vel")),
                sat_clock_s=float(sat_clock),
                system=system,
                snr=obs.get("snr"),
                fcn=int(obs["fcn"]),
                phase_pair=(sig1, sig2),
                ionosphere_name=ionosphere_name,
            )
            for value, coefficient in zip(corrected_codes, (1.0, gamma)):
                measurements.append(
                    _PppMeasurement(
                        kind="code",
                        value_m=float(value),
                        variance_m2=max(self.spp.code_sigma_m ** 2, 1e-6),
                        ionosphere_coefficient=float(coefficient),
                        **common,
                    )
                )
            for value, coefficient, ambiguity_name in zip(
                corrected_phases,
                (-1.0, -gamma),
                (amb1, amb2),
            ):
                measurements.append(
                    _PppMeasurement(
                        kind="phase",
                        value_m=float(value),
                        variance_m2=max(self.phase_sigma_m ** 2, 1e-8),
                        ambiguity_name=ambiguity_name,
                        ionosphere_coefficient=float(coefficient),
                        **common,
                    )
                )
            if integer_pair:
                self._append_uncombined_ar_observations(
                    obs,
                    (sig1, sig2),
                    (f1, f2),
                    (amb1, amb2),
                    correction,
                    (bias1, bias2),
                )
        self.last_diagnostics["reject_counts"] = reject_counts
        self.last_diagnostics["observation_model"] = "UNCOMBINED"
        return measurements, ambiguity_names, ionosphere_names, []

    def _collect_measurements(
        self,
        observations: List[Dict],
        receiver_position: np.ndarray,
    ) -> Tuple[List[_PppMeasurement], List[str], List[str], List[str]]:
        if self.observation_model == "UNCOMBINED":
            return self._collect_uncombined_measurements(
                observations,
                receiver_position,
            )
        self.last_diagnostics["observation_model"] = "IFLC"
        return self._collect_if_measurements(observations, receiver_position)

    def _collect_if_measurements(
        self,
        observations: List[Dict],
        receiver_position: np.ndarray,
    ) -> Tuple[List[_PppMeasurement], List[str], List[str], List[str]]:
        measurements: List[_PppMeasurement] = []
        phase_names: List[str] = []
        wide_lane_names: List[str] = []
        self._ar_observations = []
        reject_counts: Dict[str, int] = dict(self.last_diagnostics.get("reject_counts", {}))

        def reject(system: str, reason: str) -> None:
            key = f"{system}:{reason}"
            reject_counts[key] = reject_counts.get(key, 0) + 1

        for obs in observations:
            sat_key = str(obs["sat_key"])
            system = sat_key[0]
            sat_pos = _finite_vector3(obs["sat_pos"])
            sat_clock = _finite_float(obs["sat_clock_correction_s"])
            if sat_pos is None or sat_clock is None:
                reject(system, "ppp-no-position-clock")
                continue

            code = self._code_if_measurement(obs, receiver_position)
            phase = self._phase_if_measurement(
                obs,
                float(self._current_epoch_time),
                receiver_position,
            )
            if code is None:
                reject(system, "ppp-no-dual-code")
                continue
            if phase is None:
                reject(system, "ppp-no-dual-phase")
                continue

            code_value, code_variance, _code_sig1, _code_sig2 = code
            sat_variance = _finite_float(obs.get("sat_var"), 30.0 ** 2) or 30.0 ** 2
            measurements.append(
                _PppMeasurement(
                    sat_key=sat_key,
                    kind="code",
                    value_m=float(code_value),
                    variance_m2=max(float(code_variance), 1e-6),
                    sat_variance_m2=max(float(sat_variance), 0.0),
                    sat_pos=sat_pos,
                    sat_vel=_finite_vector3(obs.get("sat_vel")),
                    sat_clock_s=float(sat_clock),
                    system=system,
                    snr=obs.get("snr"),
                    fcn=int(obs["fcn"]),
                    phase_pair=(_code_sig1, _code_sig2),
                )
            )

            phase_value, phase_variance, sig1, sig2, ar_data = phase
            amb_name = f"AMB:{sat_key}:{sig1}-{sig2}"
            wide_lane_name = None
            wide_lane_coefficient = 0.0
            if (
                ar_data.get("phase_bias_correction") is not None
                and math.isfinite(float(ar_data.get("mw_cycles", math.nan)))
            ):
                wide_lane_name = f"WL:{amb_name}"
                f1_hz = float(ar_data["f1_hz"])
                f2_hz = float(ar_data["f2_hz"])
                wide_lane_coefficient = LIGHT_SPEED * f2_hz / (
                    (f1_hz - f2_hz) * (f1_hz + f2_hz)
                )
            self._update_phase_bias_continuity(amb_name, ar_data)
            self._reset_ambiguity_on_slip(amb_name, obs["satellite_ref"], sig1, sig2)
            if amb_name not in phase_names:
                phase_names.append(amb_name)
            measurements.append(
                _PppMeasurement(
                    sat_key=sat_key,
                    kind="phase",
                    value_m=float(phase_value),
                    variance_m2=max(float(phase_variance), 1e-8),
                    sat_variance_m2=max(float(sat_variance), 0.0),
                    sat_pos=sat_pos,
                    sat_vel=_finite_vector3(obs.get("sat_vel")),
                    sat_clock_s=float(sat_clock),
                    system=system,
                    snr=obs.get("snr"),
                    fcn=int(obs["fcn"]),
                    ambiguity_name=amb_name,
                    phase_pair=(sig1, sig2),
                    wide_lane_name=wide_lane_name,
                    wide_lane_coefficient=float(wide_lane_coefficient),
                )
            )
            self._update_ar_observation(amb_name, obs, sig1, sig2, ar_data)
        self.last_diagnostics["reject_counts"] = reject_counts
        return measurements, phase_names, [], wide_lane_names

    def _update_phase_bias_continuity(self, amb_name: str, ar_data: dict) -> None:
        correction = ar_data.get("phase_bias_correction")
        bias1 = ar_data.get("bias1")
        bias2 = ar_data.get("bias2")
        meta = None
        if correction is not None and bias1 is not None and bias2 is not None:
            meta = (
                getattr(correction, "provider_id", None),
                getattr(correction, "solution_id", None),
                getattr(correction, "iod_ssr", None),
                getattr(bias1, "discontinuity_counter", None),
                getattr(bias2, "discontinuity_counter", None),
            )
        if amb_name in self._phase_bias_meta and self._phase_bias_meta[amb_name] != meta:
            self._drop_state(amb_name)
            self._mw_tracks.pop(amb_name, None)
            self._uncombined_ar_tracks.pop(amb_name, None)
        self._phase_bias_meta[amb_name] = meta

    def _update_ar_observation(self, amb_name: str, obs: Dict, sig1: str, sig2: str, ar_data: dict) -> None:
        correction = ar_data.get("phase_bias_correction")
        bias1 = ar_data.get("bias1")
        bias2 = ar_data.get("bias2")
        if correction is None or bias1 is None or bias2 is None:
            return
        if not math.isfinite(float(ar_data.get("mw_cycles", math.nan))):
            return
        track = self._mw_tracks.setdefault(amb_name, _MwTrack())
        track.add(float(ar_data["mw_cycles"]), float(self._current_epoch_time))
        self._ar_observations.append(
            {
                "amb_name": amb_name,
                "wide_lane_name": f"WL:{amb_name}",
                "sat_key": str(obs["sat_key"]),
                "system": str(obs["sat_key"])[0],
                "sat_pos": np.asarray(obs["sat_pos"], dtype=float),
                "signals": (sig1, sig2),
                "f1_hz": float(ar_data["f1_hz"]),
                "f2_hz": float(ar_data["f2_hz"]),
                "track": track,
                "integer_ready": bool(getattr(bias1, "integer_indicator", False))
                and bool(getattr(bias2, "integer_indicator", False)),
                "mw_consistent": bool(getattr(correction, "mw_consistency", False)),
                "dispersive_consistent": bool(
                    getattr(correction, "dispersive_consistency", False)
                ),
                "provider_key": (
                    getattr(correction, "provider_id", None),
                    getattr(correction, "solution_id", None),
                    getattr(correction, "iod_ssr", None),
                ),
            }
        )

    def _reset_ambiguity_on_slip(self, amb_name: str, satellite, sig1: str, sig2: str) -> None:
        signals = getattr(satellite, "signals", {}) or {}
        lock_values = []
        half_values = []
        for sig in (sig1, sig2):
            signal = signals.get(sig)
            lock_values.append(int(getattr(signal, "lock_time", 0) or 0) if signal is not None else 0)
            half_values.append(int(getattr(signal, "half_cycle", 0) or 0) if signal is not None else 0)
        meta = (min(lock_values), max(half_values))
        old_meta = self._amb_meta.get(amb_name)
        if old_meta is not None and (meta[0] < old_meta[0] or meta[1] != old_meta[1]):
            self._drop_state(amb_name)
            self._mw_tracks.pop(amb_name, None)
            self._uncombined_ar_tracks.pop(amb_name, None)
        self._amb_meta[amb_name] = meta

    def _drop_state(self, name: str) -> None:
        if name not in self.state_names:
            return
        idx = self.state_names.index(name)
        keep = [i for i in range(len(self.state_names)) if i != idx]
        self.state_names = [self.state_names[i] for i in keep]
        self.x = self.x[keep]
        self.P = self.P[np.ix_(keep, keep)]

    def _system_clock_names(self, observations: List[Dict]) -> Tuple[str, Dict[str, str]]:
        counts = self.spp._system_counts(observations)
        reference = "G" if counts.get("G", 0) > 0 else next(iter(counts), "G")
        names: Dict[str, str] = {}
        for system in SYSTEM_OFFSET_ORDER:
            if system == reference:
                continue
            if counts.get(system, 0) > 0:
                names[system] = f"CLK:{system}"
        return reference, names

    def _state_names(
        self,
        system_names: Dict[str, str],
        phase_names: List[str],
        ionosphere_names: Optional[List[str]] = None,
        wide_lane_names: Optional[List[str]] = None,
    ) -> List[str]:
        names = ["X", "Y", "Z", "CLK:G"]
        for system in SYSTEM_OFFSET_ORDER:
            name = system_names.get(system)
            if name:
                names.append(name)
        if self.spp.troposphere_model not in {"None", None}:
            names.append("LOG_ZWD")
            if self.estimate_trop_gradients:
                names.extend(("TROP_GRAD_N", "TROP_GRAD_E"))
        names.extend(sorted(ionosphere_names or []))
        names.extend(sorted(wide_lane_names or []))
        names.extend(sorted(phase_names))
        return names

    def _sync_state(self, required_names: List[str], initial_position: np.ndarray, gps_time: float) -> None:
        old_names = list(self.state_names)
        old_x = self.x.copy()
        old_p = self.P.copy()
        old_index = {name: idx for idx, name in enumerate(old_names)}

        n = len(required_names)
        x_new = np.zeros(n, dtype=float)
        p_new = np.zeros((n, n), dtype=float)
        for i, name in enumerate(required_names):
            if name in old_index:
                j = old_index[name]
                x_new[i] = old_x[j]
                for k, other in enumerate(required_names):
                    if other in old_index:
                        p_new[i, k] = old_p[j, old_index[other]]
                continue

            if name == "X":
                x_new[i] = initial_position[0]
                p_new[i, i] = self._pending_initial_position_sigma_m ** 2
            elif name == "Y":
                x_new[i] = initial_position[1]
                p_new[i, i] = self._pending_initial_position_sigma_m ** 2
            elif name == "Z":
                x_new[i] = initial_position[2]
                p_new[i, i] = self._pending_initial_position_sigma_m ** 2
            elif name.startswith("CLK"):
                if name == "CLK:G":
                    x_new[i] = self._pending_initial_clock_m
                else:
                    x_new[i] = self._pending_system_offsets_m.get(name.split(":", 1)[1], 0.0)
                p_new[i, i] = self.initial_clock_sigma_m ** 2
            elif name == "LOG_ZWD":
                _zhd, standard_zwd = self._standard_zenith_components(initial_position)
                x_new[i] = 0.0
                wet_scale = max(float(standard_zwd), 0.02)
                p_new[i, i] = (self.initial_trop_sigma_m / wet_scale) ** 2
            elif name in {"TROP_GRAD_N", "TROP_GRAD_E"}:
                x_new[i] = 0.0
                p_new[i, i] = max(self.initial_trop_gradient_sigma_m, 1e-4) ** 2
            elif name.startswith("ION:"):
                x_new[i] = 0.0
                p_new[i, i] = max(self.initial_ionosphere_sigma_m, 0.1) ** 2
            elif name.startswith("WL:"):
                x_new[i] = 0.0
                p_new[i, i] = max(self.initial_ambiguity_sigma_m, 1.0) ** 2
            elif name.startswith("AMB:"):
                x_new[i] = 0.0
                p_new[i, i] = self.initial_ambiguity_sigma_m ** 2
            else:
                p_new[i, i] = 100.0 ** 2

        self.state_names = list(required_names)
        self.x = x_new
        self.P = 0.5 * (p_new + p_new.T)
        if self.last_time is None:
            self.last_time = float(gps_time)

    def _predict(self, gps_time: float) -> None:
        if self.x.size == 0:
            return
        dt = 1.0 if self.last_time is None else max(0.0, min(abs(float(gps_time) - float(self.last_time)), 30.0))
        if "LOG_ZWD" in self.state_names:
            idx = self.state_names.index("LOG_ZWD")
            tau = float(self.zwd_correlation_time_s)
            if tau > 0.0:
                phi = math.exp(-dt / max(tau, 1.0))
                self.x[idx] *= phi
                self.P[idx, :] *= phi
                self.P[:, idx] *= phi

        for idx, name in enumerate(self.state_names):
            if name in {"X", "Y", "Z"}:
                q = (self.position_process_noise_mps ** 2) * dt
            elif name == "CLK:G":
                q = self.clock_process_noise_m ** 2
            elif name.startswith("CLK:"):
                q = self.system_clock_process_noise_m ** 2
            elif name == "LOG_ZWD":
                _zhd, standard_zwd = self._standard_zenith_components(self.x[:3])
                current_zwd = max(standard_zwd * math.exp(max(-20.0, min(20.0, self.x[idx]))), 0.02)
                q = (self.trop_process_noise_mps / current_zwd) ** 2 * dt
            elif name in {"TROP_GRAD_N", "TROP_GRAD_E"}:
                q = self.trop_gradient_process_noise_mps ** 2 * dt
            elif name.startswith("ION:"):
                q = self.ionosphere_process_noise_mps ** 2 * dt
            else:
                q = 0.0
            self.P[idx, idx] += max(q, 0.0)
        self.P = 0.5 * (self.P + self.P.T)

    def _zwd_state_bounds(self) -> Tuple[float, float]:
        lower_ratio = max(min(self.zwd_min_ratio, 1.0), 1e-3)
        upper_ratio = max(self.zwd_max_ratio, 1.0)
        return math.log(lower_ratio), math.log(upper_ratio)

    def _stabilize_zwd_state(self) -> None:
        """Keep an exceptional update inside a broad physical ZWD envelope."""
        if "LOG_ZWD" not in self.state_names:
            return
        idx = self.state_names.index("LOG_ZWD")
        lower, upper = self._zwd_state_bounds()
        old_value = float(self.x[idx])
        bounded = min(max(old_value, lower), upper)
        if bounded == old_value:
            return
        self.x[idx] = bounded
        # Do not let a guarded update make the boundary artificially certain.
        _zhd, standard_zwd = self._standard_zenith_components(self.x[:3])
        wet_scale = max(float(standard_zwd), 0.02)
        self.P[idx, idx] = max(
            float(self.P[idx, idx]),
            (self.initial_trop_sigma_m / wet_scale) ** 2,
        )
        self.last_diagnostics["zwd_state_guard_count"] = int(
            self.last_diagnostics.get("zwd_state_guard_count", 0)
        ) + 1

    def _geometry_for_measurement(self, measurement: _PppMeasurement):
        rec_pos = self.x[:3]
        rho, los = self.spp._geodist(measurement.sat_pos, rec_pos)
        if rho is None or los is None:
            return None
        az_deg, el_deg = calculate_az_el(measurement.sat_pos, rec_pos)
        if not math.isfinite(float(el_deg)):
            return None
        if el_deg < self.spp.MIN_ELEVATION:
            return None
        az_rad = math.radians(float(az_deg))
        el_rad = math.radians(float(el_deg))
        sin_el = max(math.sin(el_rad), 0.1)
        zhd, standard_zwd, _height_correction = self._standard_troposphere_components(rec_pos)
        try:
            latitude, _longitude, height_m = ecef2lla(rec_pos)
            if self._current_epoch_datetime is None:
                raise ValueError("UTC epoch unavailable")
            hydro_mapping, wet_mapping = niell_mapping_factors(
                self._current_epoch_datetime,
                latitude,
                height_m,
                el_rad,
            )
        except (TypeError, ValueError, OverflowError, FloatingPointError):
            hydro_mapping = wet_mapping = 1.0 / sin_el
        gradient_n_mapping = 0.0
        gradient_e_mapping = 0.0
        if "LOG_ZWD" in self.state_names:
            log_zwd = float(self.x[self.state_names.index("LOG_ZWD")])
            zwd = standard_zwd * math.exp(max(-20.0, min(20.0, log_zwd)))
            hydrostatic_delay = hydro_mapping * zhd
            wet_delay = zwd * wet_mapping
            if all(
                name in self.state_names
                for name in ("TROP_GRAD_N", "TROP_GRAD_E")
            ):
                gradient_mapping = wet_mapping / max(math.tan(el_rad), 0.05)
                gradient_n_mapping = gradient_mapping * math.cos(az_rad)
                gradient_e_mapping = gradient_mapping * math.sin(az_rad)
                wet_delay += (
                    gradient_n_mapping
                    * float(self.x[self.state_names.index("TROP_GRAD_N")])
                    + gradient_e_mapping
                    * float(self.x[self.state_names.index("TROP_GRAD_E")])
                )
        else:
            hydrostatic_delay = 0.0
            wet_delay = 0.0
            zwd = 0.0
        antenna_eccentricity = -float(self._antenna_eccentricity_ecef @ los)
        solid_tide = -float(self._solid_tide_ecef @ los)
        ocean_tide = -float(self._ocean_tide_ecef @ los)
        relativity = shapiro_delay(rec_pos, measurement.sat_pos) if self.apply_shapiro else 0.0
        self._record_model_correction("antenna_eccentricity", antenna_eccentricity)
        self._record_model_correction("solid_earth_tide", solid_tide)
        self._record_model_correction("ocean_loading", ocean_tide)
        self._record_model_correction("shapiro", relativity)
        non_dispersive_correction = (
            antenna_eccentricity + solid_tide + ocean_tide + relativity
        )
        return (
            float(rho), los, el_rad, float(hydrostatic_delay + wet_delay),
            0.0, wet_mapping, float(zwd), float(gradient_n_mapping),
            float(gradient_e_mapping), float(non_dispersive_correction),
        )

    @staticmethod
    def _standard_zenith_components(position: np.ndarray) -> Tuple[float, float]:
        """Return standard-atmosphere ZHD and ZWD components."""
        zhd, zwd, _height_correction = PPPPositioner._standard_troposphere_components(position)
        return zhd, zwd

    @staticmethod
    def _standard_troposphere_components(position: np.ndarray) -> Tuple[float, float, float]:
        """Return zenith components and the low-elevation height term."""
        try:
            lat_rad, _lon_rad, height_m = ecef2lla(position)
            height_m = max(float(height_m), 0.0)
            pressure_hpa = 1013.25 * (1.0 - 2.26e-5 * height_m) ** 5.225
            temperature_k = 18.0 - 6.5e-3 * height_m + 273.15
            humidity_pct = 50.0 * math.exp(-6.396e-4 * height_m)
            vapour_hpa = humidity_pct / 100.0 * math.exp(
                -37.2465 + 0.213166 * temperature_k - 0.000256908 * temperature_k ** 2
            )
            hydrostatic_denominator = (
                1.0
                - 0.00266 * math.cos(2.0 * lat_rad)
                - 0.00028 * height_m / 1000.0
            )
            zhd = 0.0022768 * pressure_hpa / hydrostatic_denominator
            zwd = 0.002277 * (1255.0 / temperature_k + 0.05) * vapour_hpa

            height_km = min(max(height_m / 1000.0, 0.0), 5.0)
            b_values = (1.156, 1.006, 0.874, 0.757, 0.654, 0.563)
            lower = min(int(height_km), 4)
            fraction = height_km - lower
            b_term = b_values[lower] + (b_values[lower + 1] - b_values[lower]) * fraction
            return float(zhd), float(zwd), float(0.002277 * b_term)
        except (TypeError, ValueError, OverflowError, FloatingPointError):
            return 0.0, 0.0, 0.0

    def _estimated_zenith_troposphere(self) -> Tuple[float, float, float]:
        """Resolve PPP's physical wet-delay state into ZTD, ZHD and ZWD."""
        if self.x.size < 3:
            return 0.0, 0.0, 0.0
        if "LOG_ZWD" not in self.state_names:
            return 0.0, 0.0, 0.0
        zhd, standard_zwd = self._standard_zenith_components(self.x[:3])
        log_zwd = float(self.x[self.state_names.index("LOG_ZWD")])
        zwd = standard_zwd * math.exp(max(-20.0, min(20.0, log_zwd)))
        return float(zhd + zwd), float(zhd), float(zwd)

    def _build_filter_matrices(
        self,
        measurements: List[_PppMeasurement],
        reference_system: str,
        system_state_names: Dict[str, str],
        *,
        initialise_ambiguities: bool,
        gate_outliers: bool = True,
    ):
        name_to_index = {name: idx for idx, name in enumerate(self.state_names)}
        h_rows: List[np.ndarray] = []
        residuals: List[float] = []
        variances: List[float] = []
        used_satellites: List[str] = []
        code_geometry_rows: List[np.ndarray] = []
        row_measurements: List[_PppMeasurement] = []
        phase_gate_candidates = []
        reject_counts: Dict[str, int] = dict(self.last_diagnostics.get("reject_counts", {}))

        for measurement in measurements:
            if measurement.kind == "mw":
                if (
                    not measurement.wide_lane_name
                    or measurement.wide_lane_name not in name_to_index
                ):
                    continue
                row = np.zeros(len(self.state_names), dtype=float)
                row[name_to_index[measurement.wide_lane_name]] = 1.0
                residual = measurement.value_m - float(
                    self.x[name_to_index[measurement.wide_lane_name]]
                )
                if not math.isfinite(residual):
                    continue
                h_rows.append(row)
                residuals.append(float(residual))
                variances.append(max(float(measurement.variance_m2), 1e-8))
                used_satellites.append(measurement.sat_key)
                row_measurements.append(measurement)
                continue
            geom = self._geometry_for_measurement(measurement)
            if geom is None:
                key = f"{measurement.system}:ppp-geometry"
                reject_counts[key] = reject_counts.get(key, 0) + 1
                continue
            (
                rho,
                los,
                el_rad,
                tropo,
                trop_var,
                trop_mapping,
                current_zwd,
                gradient_n_mapping,
                gradient_e_mapping,
                non_dispersive_correction,
            ) = geom

            row = np.zeros(len(self.state_names), dtype=float)
            row[:3] = -los
            row[name_to_index["CLK:G"]] = 1.0
            predicted = (
                rho
                + self.x[name_to_index["CLK:G"]]
                - LIGHT_SPEED * measurement.sat_clock_s
                + tropo
                + non_dispersive_correction
            )

            if measurement.system != reference_system and measurement.system in system_state_names:
                offset_name = system_state_names[measurement.system]
                idx = name_to_index[offset_name]
                row[idx] = 1.0
                predicted += self.x[idx]

            if "LOG_ZWD" in name_to_index:
                idx = name_to_index["LOG_ZWD"]
                row[idx] = current_zwd * trop_mapping
            if "TROP_GRAD_N" in name_to_index:
                row[name_to_index["TROP_GRAD_N"]] = gradient_n_mapping
            if "TROP_GRAD_E" in name_to_index:
                row[name_to_index["TROP_GRAD_E"]] = gradient_e_mapping

            if (
                measurement.ionosphere_name
                and measurement.ionosphere_name in name_to_index
            ):
                ionosphere_index = name_to_index[measurement.ionosphere_name]
                ionosphere_coefficient = float(
                    measurement.ionosphere_coefficient
                )
                row[ionosphere_index] = ionosphere_coefficient
                predicted += ionosphere_coefficient * self.x[ionosphere_index]

            # The MW/WL state is an auxiliary observable used for wide-lane
            # validation.  Keep it out of the IF phase equation: the IF
            # ambiguity remains the independently estimated meter-domain
            # state, which avoids injecting the noisy code-derived MW datum
            # into the position/ambiguity covariance.

            new_ambiguity = False
            predicted_without_ambiguity = predicted
            if measurement.kind == "phase":
                if not measurement.ambiguity_name or measurement.ambiguity_name not in name_to_index:
                    continue
                amb_idx = name_to_index[measurement.ambiguity_name]
                if initialise_ambiguities and self.P[amb_idx, amb_idx] >= self.initial_ambiguity_sigma_m ** 2 * 0.9:
                    self.x[amb_idx] = measurement.value_m - predicted
                    new_ambiguity = True
                row[amb_idx] = 1.0
                predicted += self.x[amb_idx]

            residual = measurement.value_m - predicted
            if not math.isfinite(residual):
                continue

            if gate_outliers:
                if measurement.kind == "code" and abs(residual) > self.max_code_prefit_residual_m:
                    key = f"{measurement.system}:ppp-code-prefit"
                    reject_counts[key] = reject_counts.get(key, 0) + 1
                    continue
            variance = measurement.sat_variance_m2 + trop_var
            if measurement.kind == "code":
                variance += self.spp.var_err(
                    measurement.sat_key,
                    el_rad,
                    snr=measurement.snr,
                    code_variance=measurement.variance_m2,
                )
                code_row = np.zeros(4, dtype=float)
                code_row[:3] = -los
                code_row[3] = 1.0
                code_geometry_rows.append(code_row)
            else:
                elevation_factor = 1.0
                if self.spp.WEIGHT_MODE == "elevation":
                    elevation_factor = 1.0 + abs(90.0 - math.degrees(el_rad)) ** 3 * 0.000004
                system_factor = self.spp.system_code_weight_factors.get(
                    measurement.system,
                    2.0 if measurement.system == "C" else 1.0,
                )
                variance += measurement.variance_m2 * elevation_factor ** 2 * system_factor ** 2

            h_rows.append(row)
            residuals.append(float(residual))
            variances.append(max(float(variance), 1e-8))
            used_satellites.append(measurement.sat_key)
            row_measurements.append(measurement)
            if gate_outliers and measurement.kind == "phase" and not new_ambiguity:
                phase_gate_candidates.append(
                    (
                        len(residuals) - 1,
                        measurement,
                        amb_idx,
                        float(predicted_without_ambiguity),
                        float(residual),
                    )
                )

        # Receiver clock changes are common to every carrier-phase residual and
        # can be tens of metres between epochs.  Detect a single-satellite jump
        # only after removing that common mode; absolute prefit gating resets all
        # ambiguities whenever the receiver clock moves.
        if len(phase_gate_candidates) >= self.spp.MIN_SATELLITES:
            all_phase_residuals = np.asarray(
                [candidate[4] for candidate in phase_gate_candidates], dtype=float
            )
            global_common = float(np.median(all_phase_residuals))
            grouped_candidates: Dict[str, List[tuple]] = {}
            for candidate in phase_gate_candidates:
                grouped_candidates.setdefault(candidate[1].system, []).append(candidate)

            common_by_system = {}
            gate_by_system = {}
            for system, candidates in grouped_candidates.items():
                system_residuals = np.asarray(
                    [candidate[4] for candidate in candidates], dtype=float
                )
                common_residual = (
                    float(np.median(system_residuals))
                    if len(candidates) >= self.spp.MIN_SATELLITES
                    else global_common
                )
                absolute_deviations = np.abs(system_residuals - common_residual)
                robust_sigma = 1.4826 * float(np.median(absolute_deviations))
                gate = max(self.max_phase_prefit_residual_m, 6.0 * robust_sigma)
                common_by_system[system] = common_residual
                gate_by_system[system] = float(gate)
                for candidate, deviation in zip(candidates, absolute_deviations):
                    if float(deviation) <= gate:
                        continue
                    row_index, measurement, amb_idx, predicted_without_ambiguity, _residual = candidate
                    # Retain the constellation clock innovation while
                    # reinitialising only the affected ambiguity in place.
                    self.x[amb_idx] = (
                        measurement.value_m - predicted_without_ambiguity - common_residual
                    )
                    self.P[amb_idx, :] = 0.0
                    self.P[:, amb_idx] = 0.0
                    self.P[amb_idx, amb_idx] = self.initial_ambiguity_sigma_m ** 2
                    residuals[row_index] = common_residual
                    key = f"{measurement.system}:ppp-phase-slip"
                    reject_counts[key] = reject_counts.get(key, 0) + 1

            self.last_diagnostics["phase_prefit_common_m"] = global_common
            self.last_diagnostics["phase_prefit_common_m_by_system"] = common_by_system
            self.last_diagnostics["phase_prefit_gate_m_by_system"] = gate_by_system

        self.last_diagnostics["reject_counts"] = reject_counts
        self._last_filter_measurements = row_measurements
        return h_rows, residuals, variances, used_satellites, np.asarray(code_geometry_rows, dtype=float).reshape((-1, 4))

    def _postfit_residual_limit(self, measurement: _PppMeasurement) -> float:
        """Return the linear-combination residual limit in meters."""
        base_limit = (
            self.max_code_postfit_residual_m
            if measurement.kind == "code"
            else self.max_phase_postfit_residual_m
        )
        pair = measurement.phase_pair
        if not pair or len(pair) != 2:
            return max(float(base_limit), 0.0)
        f1, _wavelength1 = get_freq(pair[0], measurement.sat_key, measurement.fcn)
        f2, _wavelength2 = get_freq(pair[1], measurement.sat_key, measurement.fcn)
        denominator = f1 * f1 - f2 * f2
        if f1 <= 0.0 or f2 <= 0.0 or abs(denominator) < 1e-9:
            return max(float(base_limit), 0.0)
        coefficient1 = f1 * f1 / denominator
        coefficient2 = -f2 * f2 / denominator
        return max(
            float(base_limit) * math.hypot(coefficient1, coefficient2),
            0.0,
        )

    def _initialise_prior_ambiguity(
        self,
        measurement: _PppMeasurement,
        prior_state: np.ndarray,
        prior_covariance: np.ndarray,
        reference_system: str,
        system_state_names: Dict[str, str],
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Reset one ambiguity in the saved epoch prior."""
        ambiguity_name = measurement.ambiguity_name
        if not ambiguity_name or ambiguity_name not in self.state_names:
            return prior_state, prior_covariance
        index = self.state_names.index(ambiguity_name)
        self.x = prior_state.copy()
        self.P = prior_covariance.copy()
        self.x[index] = 0.0
        self.P[index, :] = 0.0
        self.P[:, index] = 0.0
        self.P[index, index] = self.initial_ambiguity_sigma_m ** 2
        self._build_filter_matrices(
            [measurement],
            reference_system,
            system_state_names,
            initialise_ambiguities=True,
            gate_outliers=False,
        )
        return self.x.copy(), self.P.copy()

    def _robust_filter_update(
        self,
        measurements: List[_PppMeasurement],
        reference_system: str,
        system_state_names: Dict[str, str],
    ):
        """Repeat the epoch update from one prior until residual tests pass."""
        initial_matrices = self._build_filter_matrices(
            measurements,
            reference_system,
            system_state_names,
            initialise_ambiguities=True,
            gate_outliers=True,
        )
        initial_h, initial_v, initial_var, initial_sats, initial_geometry = initial_matrices
        initial_measurements = list(self._last_filter_measurements)
        if len(set(initial_sats)) < self.spp.MIN_SATELLITES:
            return initial_measurements, *initial_matrices

        prior_state = self.x.copy()
        prior_covariance = self.P.copy()
        if not self.postfit_enabled:
            self._kalman_update(
                np.asarray(initial_h, dtype=float),
                np.asarray(initial_v, dtype=float),
                np.asarray(initial_var, dtype=float),
            )
            post_matrices = self._build_filter_matrices(
                initial_measurements,
                reference_system,
                system_state_names,
                initialise_ambiguities=False,
                gate_outliers=False,
            )
            self.last_diagnostics["postfit_enabled"] = False
            self.last_diagnostics["postfit_iterations"] = 1
            return initial_measurements, *post_matrices

        active_measurements = list(initial_measurements)
        rejected_satellites: List[str] = []
        reset_ambiguities: List[str] = []
        outlier_log: List[dict] = []
        final_matrices = initial_matrices
        max_iterations = max(len(active_measurements), 1) + 1
        for iteration in range(max_iterations):
            self.x = prior_state.copy()
            self.P = prior_covariance.copy()
            update_matrices = self._build_filter_matrices(
                active_measurements,
                reference_system,
                system_state_names,
                initialise_ambiguities=False,
                gate_outliers=False,
            )
            h_rows, residuals, variances, used_satellites, _code_geometry = update_matrices
            if len(set(used_satellites)) < self.spp.MIN_SATELLITES:
                final_matrices = update_matrices
                break
            self._kalman_update(
                np.asarray(h_rows, dtype=float),
                np.asarray(residuals, dtype=float),
                np.asarray(variances, dtype=float),
            )
            final_matrices = self._build_filter_matrices(
                active_measurements,
                reference_system,
                system_state_names,
                initialise_ambiguities=False,
                gate_outliers=False,
            )
            _post_h, post_v, _post_var, _post_sats, _post_geometry = final_matrices
            post_measurements = list(self._last_filter_measurements)
            candidates = []
            for measurement, residual in zip(post_measurements, post_v):
                limit = self._postfit_residual_limit(measurement)
                if limit > 0.0 and abs(float(residual)) > limit:
                    candidates.append((abs(float(residual)), measurement, float(residual), limit))
            if not candidates:
                self.last_diagnostics["postfit_iterations"] = iteration + 1
                break

            _magnitude, outlier, signed_residual, limit = max(
                candidates,
                key=lambda item: item[0],
            )
            outlier_log.append(
                {
                    "satellite": outlier.sat_key,
                    "kind": outlier.kind,
                    "residual_m": signed_residual,
                    "limit_m": float(limit),
                }
            )
            reject_counts = dict(self.last_diagnostics.get("reject_counts", {}))
            if outlier.kind == "phase" and outlier.ambiguity_name:
                prior_state, prior_covariance = self._initialise_prior_ambiguity(
                    outlier,
                    prior_state,
                    prior_covariance,
                    reference_system,
                    system_state_names,
                )
                if outlier.ambiguity_name not in reset_ambiguities:
                    reset_ambiguities.append(outlier.ambiguity_name)
                self._mw_tracks.pop(outlier.ambiguity_name, None)
                key = f"{outlier.system}:ppp-phase-postfit"
            else:
                active_measurements = [
                    measurement for measurement in active_measurements
                    if measurement.sat_key != outlier.sat_key
                ]
                if outlier.sat_key not in rejected_satellites:
                    rejected_satellites.append(outlier.sat_key)
                key = f"{outlier.system}:ppp-code-postfit"
            reject_counts[key] = reject_counts.get(key, 0) + 1
            self.last_diagnostics["reject_counts"] = reject_counts
        else:
            self.last_diagnostics["postfit_iterations"] = max_iterations

        self.last_diagnostics["postfit_outliers"] = outlier_log
        self.last_diagnostics["postfit_rejected_satellites"] = rejected_satellites
        self.last_diagnostics["postfit_reset_ambiguities"] = reset_ambiguities
        self.last_diagnostics["postfit_enabled"] = True
        return active_measurements, *final_matrices

    def _kalman_update(self, h_mat: np.ndarray, residual: np.ndarray, variance: np.ndarray) -> None:
        if h_mat.size == 0:
            return
        r_mat = np.diag(np.maximum(variance, 1e-8))
        p_ht = self.P @ h_mat.T
        innovation = h_mat @ p_ht + r_mat
        try:
            gain = p_ht @ np.linalg.inv(innovation)
        except np.linalg.LinAlgError:
            gain = p_ht @ np.linalg.pinv(innovation)
        dx = gain @ residual
        if not np.all(np.isfinite(dx)):
            return
        if "LOG_ZWD" in self.state_names:
            zwd_idx = self.state_names.index("LOG_ZWD")
            max_step = max(float(self.max_zwd_log_step), 0.01)
            if abs(float(dx[zwd_idx])) > max_step:
                scale = max_step / abs(float(dx[zwd_idx]))
                gain[zwd_idx, :] *= scale
                dx[zwd_idx] *= scale
                self.last_diagnostics["zwd_step_limit_count"] = int(
                    self.last_diagnostics.get("zwd_step_limit_count", 0)
                ) + 1
        self.x = self.x + dx
        identity = np.eye(self.P.shape[0])
        kh = gain @ h_mat
        self.P = (identity - kh) @ self.P @ (identity - kh).T + gain @ r_mat @ gain.T
        self.P = 0.5 * (self.P + self.P.T)
        self._stabilize_zwd_state()

    @staticmethod
    def _weighted_rms(residuals, variances) -> float:
        values = np.asarray(residuals, dtype=float).reshape(-1)
        sigma2 = np.asarray(variances, dtype=float).reshape(-1)
        if values.size == 0 or sigma2.size != values.size:
            return 0.0
        weighted = values / np.sqrt(np.maximum(sigma2, 1e-8))
        return float(math.sqrt(max(float(np.mean(weighted * weighted)), 0.0)))

    @staticmethod
    def _integer_least_squares(
        float_vector: np.ndarray,
        covariance: np.ndarray,
        *,
        max_nodes: int = 250_000,
    ) -> Optional[Tuple[np.ndarray, float, np.ndarray, float, int]]:
        """Return the two nearest integer vectors using a small LAMBDA search.

        This decorrelated LAMBDA/BIE search avoids rounding each ambiguity
        independently.  The sphere decoder operates directly on
        the full covariance matrix and is sufficient for the small
        between-satellite groups used by real-time PPP-AR.
        """
        a = np.asarray(float_vector, dtype=float).reshape(-1)
        q = np.asarray(covariance, dtype=float)
        if a.size == 0 or q.shape != (a.size, a.size) or not np.all(np.isfinite(a)):
            return None
        q = 0.5 * (q + q.T)
        if not np.all(np.isfinite(q)):
            return None
        try:
            smallest = float(np.min(np.linalg.eigvalsh(q)))
        except np.linalg.LinAlgError:
            return None
        if smallest <= 1e-10:
            q = q + np.eye(a.size, dtype=float) * (1e-10 - smallest + 1e-10)
        try:
            precision = np.linalg.inv(q)
            precision_root = np.linalg.cholesky(precision).T
        except np.linalg.LinAlgError:
            try:
                precision = np.linalg.pinv(q)
                precision_root = np.linalg.cholesky(precision).T
            except np.linalg.LinAlgError:
                return None
        if not np.all(np.isfinite(precision_root)):
            return None

        nearest = np.rint(a).astype(np.int64)
        nearest_delta = a - nearest
        try:
            nearest_metric = float(nearest_delta @ precision @ nearest_delta)
        except (ValueError, np.linalg.LinAlgError, FloatingPointError):
            return None
        # The rounded vector and its one-cycle neighbours provide a finite
        # upper bound for the second-best solution.  Therefore both true ILS
        # candidates must lie inside this sphere, including after ambiguities
        # have already been tightly constrained by a previous fixed epoch.
        seed_metrics = [nearest_metric]
        for index in range(a.size):
            for step in (-1, 1):
                neighbour = nearest.copy()
                neighbour[index] += step
                delta = a - neighbour
                seed_metrics.append(float(delta @ precision @ delta))
        seed_metrics.sort()
        radius2 = max(seed_metrics[1], seed_metrics[0] + 1e-12)
        radius2 = radius2 * (1.0 + 1e-10) + 1e-12
        vectors: List[Tuple[float, np.ndarray]] = []
        candidate = np.zeros(a.size, dtype=np.int64)
        nodes = 0

        def search(index: int, metric: float) -> None:
            nonlocal nodes, radius2
            nodes += 1
            if nodes > max_nodes:
                return
            if index < 0:
                vectors.append((float(metric), candidate.copy()))
                vectors.sort(key=lambda item: item[0])
                del vectors[2:]
                if len(vectors) >= 2:
                    radius2 = min(radius2, vectors[-1][0])
                return

            tail = 0.0
            if index + 1 < a.size:
                tail = float(
                    np.dot(
                        precision_root[index, index + 1 :],
                        a[index + 1 :] - candidate[index + 1 :],
                    )
                )
            diagonal = float(precision_root[index, index])
            if abs(diagonal) < 1e-14:
                return
            center = float(a[index] + tail / diagonal)
            radius = math.sqrt(max(radius2 - metric, 0.0)) / abs(diagonal)
            lower = int(math.ceil(center - radius))
            upper = int(math.floor(center + radius))
            # Bound pathological searches when the float covariance has not
            # converged.  Such groups will fail the ratio test below.
            if upper - lower > 24:
                middle = int(round(center))
                lower = middle - 12
                upper = middle + 12
            values = sorted(range(lower, upper + 1), key=lambda value: abs(value - center))
            for value in values:
                term = diagonal * (a[index] - value) + tail
                new_metric = metric + term * term
                if new_metric <= radius2 + 1e-12:
                    candidate[index] = value
                    search(index - 1, new_metric)

        search(a.size - 1, 0.0)
        if len(vectors) < 2:
            return None
        best_metric, best_vector = vectors[0]
        second_metric, second_vector = vectors[1]
        return best_vector, float(best_metric), second_vector, float(second_metric), nodes

    @staticmethod
    def _lambda_decorrelate(
        covariance: np.ndarray,
    ) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """Return integer decorrelation and back-transformation matrices."""
        q_mat = np.asarray(covariance, dtype=float)
        if q_mat.ndim != 2 or q_mat.shape[0] != q_mat.shape[1] or q_mat.size == 0:
            return None
        size = q_mat.shape[0]
        working = 0.5 * (q_mat + q_mat.T)
        lower = np.zeros_like(working)
        diagonal = np.zeros(size, dtype=float)
        for row in range(size - 1, -1, -1):
            diagonal[row] = float(working[row, row])
            if diagonal[row] <= 0.0 or not math.isfinite(diagonal[row]):
                return None
            root = math.sqrt(diagonal[row])
            lower[row, : row + 1] = working[row, : row + 1] / root
            for previous_row in range(row):
                for column in range(previous_row + 1):
                    working[previous_row, column] -= (
                        lower[row, column] * lower[row, previous_row]
                    )
                    working[column, previous_row] = working[previous_row, column]
            lower[row, : row + 1] /= lower[row, row]

        back_transform = np.eye(size, dtype=float)
        first_reduced = size - 1
        swapped = True
        while swapped:
            column = size - 1
            swapped = False
            while not swapped and column > 0:
                column -= 1
                if column <= first_reduced:
                    for later in range(column + 1, size):
                        mu = int(
                            math.copysign(
                                math.floor(abs(float(lower[later, column])) + 0.5),
                                float(lower[later, column]),
                            )
                        )
                        if mu == 0:
                            continue
                        lower[later:, column] -= mu * lower[later:, later]
                        back_transform[:, later] += mu * back_transform[:, column]

                coefficient = float(lower[column + 1, column])
                delta = diagonal[column] + coefficient * coefficient * diagonal[column + 1]
                if delta < diagonal[column + 1]:
                    lambda_value = diagonal[column + 1] * coefficient / delta
                    eta = diagonal[column] / delta
                    diagonal[column] = eta * diagonal[column + 1]
                    diagonal[column + 1] = delta
                    if column > 0:
                        block = lower[column : column + 2, :column].copy()
                        lower[column : column + 2, :column] = np.array(
                            [[-coefficient, 1.0], [eta, lambda_value]],
                            dtype=float,
                        ) @ block
                    lower[column + 1, column] = lambda_value
                    if column + 2 < size:
                        lower[column + 2 :, [column, column + 1]] = lower[
                            column + 2 :, [column + 1, column]
                        ]
                    back_transform[:, [column, column + 1]] = back_transform[
                        :, [column + 1, column]
                    ]
                    first_reduced = column
                    swapped = True

        try:
            transform = np.linalg.inv(back_transform)
        except np.linalg.LinAlgError:
            return None
        transform = np.rint(transform)
        back_transform = np.rint(back_transform)
        if not np.allclose(back_transform @ transform, np.eye(size), atol=1e-8):
            return None
        return transform, back_transform

    @staticmethod
    def _integer_bie(
        float_vector: np.ndarray,
        covariance: np.ndarray,
        *,
        candidate_count: int = 100,
        max_nodes: int = 750_000,
    ) -> Optional[Tuple[np.ndarray, np.ndarray, float, float, float, int]]:
        """Return a 100-candidate best integer equivariant estimate."""
        values = np.asarray(float_vector, dtype=float).reshape(-1)
        q_mat = np.asarray(covariance, dtype=float)
        count = max(int(candidate_count), 2)
        if (
            values.size == 0
            or q_mat.shape != (values.size, values.size)
            or not np.all(np.isfinite(values))
            or not np.all(np.isfinite(q_mat))
        ):
            return None
        q_mat = 0.5 * (q_mat + q_mat.T)
        try:
            smallest = float(np.min(np.linalg.eigvalsh(q_mat)))
        except np.linalg.LinAlgError:
            return None
        if smallest <= 1e-10:
            q_mat = q_mat + np.eye(values.size, dtype=float) * (1e-10 - smallest + 1e-10)
        increments = np.where(
            values < 0.0,
            -np.floor(np.abs(values) + 0.5),
            np.floor(values + 0.5),
        )
        centered_values = values - increments
        decorrelation = PPPPositioner._lambda_decorrelate(q_mat)
        if decorrelation is None:
            return None
        transform, back_transform = decorrelation
        search_values = transform @ centered_values
        search_covariance = transform @ q_mat @ transform.T
        search_covariance = 0.5 * (search_covariance + search_covariance.T)
        try:
            precision = np.linalg.inv(search_covariance)
            precision_root = np.linalg.cholesky(precision).T
        except np.linalg.LinAlgError:
            return None

        nearest = np.rint(search_values).astype(np.int64)
        candidates: Dict[Tuple[int, ...], float] = {}

        def add_candidate(integer_vector: np.ndarray) -> None:
            key = tuple(int(item) for item in integer_vector)
            delta = search_values - integer_vector
            metric = float(delta @ precision @ delta)
            if math.isfinite(metric):
                candidates[key] = min(metric, candidates.get(key, math.inf))

        add_candidate(nearest)
        required_steps = int(math.ceil((count - 1) / max(2 * search_values.size, 1)))
        for step in range(1, required_steps + 1):
            for index in range(search_values.size):
                for direction in (-1, 1):
                    seed = nearest.copy()
                    seed[index] += direction * step
                    add_candidate(seed)
        if len(candidates) < count:
            return None

        def trim_candidates() -> float:
            ordered = sorted(candidates.items(), key=lambda item: item[1])
            for key, _metric in ordered[count:]:
                candidates.pop(key, None)
            return float(ordered[min(count, len(ordered)) - 1][1])

        radius2 = trim_candidates() * (1.0 + 1e-12) + 1e-12
        candidate = np.zeros(search_values.size, dtype=np.int64)
        nodes = 0
        truncated = False

        def search(index: int, metric: float) -> None:
            nonlocal nodes, radius2, truncated
            nodes += 1
            if nodes > max_nodes:
                truncated = True
                return
            if index < 0:
                add_candidate(candidate.copy())
                if len(candidates) >= count:
                    radius2 = trim_candidates() * (1.0 + 1e-12) + 1e-12
                return

            tail = 0.0
            if index + 1 < search_values.size:
                tail = float(
                    np.dot(
                        precision_root[index, index + 1 :],
                        search_values[index + 1 :] - candidate[index + 1 :],
                    )
                )
            diagonal = float(precision_root[index, index])
            if abs(diagonal) < 1e-14:
                truncated = True
                return
            remaining = radius2 - metric
            if remaining < -1e-12:
                return
            center = float(search_values[index] + tail / diagonal)
            radius = math.sqrt(max(remaining, 0.0)) / abs(diagonal)
            lower = int(math.ceil(center - radius))
            upper = int(math.floor(center + radius))
            if upper - lower > 128:
                truncated = True
                return
            integers = sorted(range(lower, upper + 1), key=lambda value: abs(value - center))
            for integer in integers:
                term = diagonal * (search_values[index] - integer) + tail
                new_metric = metric + term * term
                if new_metric <= radius2 + 1e-12:
                    candidate[index] = integer
                    search(index - 1, new_metric)
                    if truncated:
                        return

        search(search_values.size - 1, 0.0)
        if truncated or len(candidates) < count:
            return None
        ordered = sorted(candidates.items(), key=lambda item: item[1])[:count]
        integer_candidates = np.asarray([key for key, _metric in ordered], dtype=float)
        metrics = np.asarray([metric for _key, metric in ordered], dtype=float)
        relative = np.clip(-0.5 * (metrics - metrics[0]), -745.0, 0.0)
        weights = np.exp(relative)
        weight_sum = float(np.sum(weights))
        if not math.isfinite(weight_sum) or weight_sum <= 0.0:
            return None
        weights /= weight_sum
        bie_transformed = weights @ integer_candidates
        differences = integer_candidates - bie_transformed[np.newaxis, :]
        # Keep only the candidate variance of each decorrelated ambiguity
        # before transforming the covariance back to the original domain.
        transformed_variances = np.sum(
            weights[:, np.newaxis] * differences * differences,
            axis=0,
        )
        covariance_transformed = np.diag(np.maximum(transformed_variances, 1e-12))
        bie = back_transform @ bie_transformed + increments
        bie_covariance = back_transform @ covariance_transformed @ back_transform.T
        bie_covariance = 0.5 * (bie_covariance + bie_covariance.T)
        for index in range(values.size):
            bie_covariance[index, index] = max(
                float(bie_covariance[index, index]),
                1e-12,
            )
        best_weight = float(weights[0])
        return (
            bie,
            bie_covariance,
            float(metrics[0]),
            float(metrics[1]),
            best_weight,
            nodes,
        )

    def _attempt_uncombined_ambiguity_resolution(self) -> bool:
        """Resolve per-frequency between-satellite ambiguities directly."""
        eligible = [
            item
            for item in self._uncombined_ar_observations
            if (
                item["system"] in self.ar_systems
                and item["integer_ready"]
                and item["track"].count >= self.ar_min_epochs
                and item["amb_name"] in self.state_names
            )
        ]
        self.last_diagnostics["ar_candidate_count"] = len(eligible)
        if not eligible:
            self.last_diagnostics["ar_status"] = "waiting"
            self.last_diagnostics["ar_rejection_reason"] = (
                "no converged uncombined integer ambiguities"
            )
            return False

        groups: Dict[tuple, List[dict]] = {}
        for item in eligible:
            try:
                _azimuth, elevation = calculate_az_el(item["sat_pos"], self.x[:3])
            except Exception:
                elevation = -90.0
            item["elevation_deg"] = float(elevation)
            if item["elevation_deg"] < self.ar_min_elevation_deg:
                continue
            key = (
                item["system"],
                item["signal"],
                round(item["frequency_hz"], -2),
                item.get("provider_key"),
            )
            groups.setdefault(key, []).append(item)

        constraints = []
        group_diagnostics = []
        rejected_groups = []
        fixed_count = 0
        fixed_ratios = []
        for key, candidates in groups.items():
            group_diag = {
                "system": key[0],
                "signals": (key[1],),
                "candidate_count": len(candidates),
                "wl_accepted_count": len(candidates),
            }
            if len(candidates) < self.ar_min_satellites:
                group_diag["status"] = "not-enough-satellites"
                group_diagnostics.append(group_diag)
                continue

            wavelength = float(candidates[0]["wavelength_m"])

            def reference_score(item: dict) -> Tuple[float, float]:
                index = self.state_names.index(item["amb_name"])
                variance_sum = 0.0
                for other in candidates:
                    other_index = self.state_names.index(other["amb_name"])
                    variance_sum += float(
                        self.P[index, index]
                        + self.P[other_index, other_index]
                        - 2.0 * self.P[index, other_index]
                    )
                return variance_sum, -float(item["elevation_deg"])

            candidates = sorted(candidates, key=reference_score)
            reference = candidates[0]
            reference_index = self.state_names.index(reference["amb_name"])
            meter_rows = []
            float_cycles = []
            for item in candidates[1:]:
                index = self.state_names.index(item["amb_name"])
                row = np.zeros(len(self.state_names), dtype=float)
                row[index] = 1.0
                row[reference_index] = -1.0
                meter_rows.append(row)
                float_cycles.append(float(row @ self.x) / wavelength)
            transform_m = np.asarray(meter_rows, dtype=float)
            covariance_cycles = (
                transform_m @ self.P @ transform_m.T
            ) / max(wavelength * wavelength, 1e-12)
            bie_search = self._integer_bie(
                np.asarray(float_cycles, dtype=float),
                covariance_cycles,
            )
            if bie_search is None:
                group_diag["status"] = "bie-search-failed"
                group_diagnostics.append(group_diag)
                rejected_groups.append(f"{key[0]}:{key[1]} BIE search failed")
                continue
            bie, bie_covariance, _best, _second, best_weight, search_nodes = bie_search
            bie_sigmas = np.sqrt(np.maximum(np.diag(bie_covariance), 0.0))
            fixable = (
                np.abs(bie - np.rint(bie)) <= self.ar_max_nl_fraction
            ) & (bie_sigmas <= self.ar_max_nl_sigma_cycles)
            fixed_in_group = int(np.count_nonzero(fixable))
            required = (
                len(candidates) - 1
                if self.ar_require_full_group
                else self.ar_min_satellites - 1
            )
            group_diag["bie_sigma_max"] = float(np.max(bie_sigmas))
            group_diag["bie_fraction_max"] = float(
                np.max(np.abs(bie - np.rint(bie)))
            )
            group_diag["bie_fixable_count"] = fixed_in_group
            if fixed_in_group < required:
                group_diag["status"] = "bie-validation-failed"
                group_diagnostics.append(group_diag)
                rejected_groups.append(f"{key[0]}:{key[1]} BIE validation failed")
                continue
            self.last_diagnostics["ar_bie_best_weight"] = float(best_weight)
            self.last_diagnostics["ar_search_nodes"] = int(
                self.last_diagnostics.get("ar_search_nodes", 0)
            ) + int(search_nodes)
            for index, row in enumerate(meter_rows):
                if not fixable[index]:
                    continue
                target_m = wavelength * float(bie[index])
                constraints.append((row, target_m - float(row @ self.x)))
                fixed_count += 1
            fixed_ratios.append(fixed_in_group / max(len(meter_rows), 1))
            group_diag["status"] = "fixed"
            group_diag["fixed_count"] = fixed_in_group
            group_diagnostics.append(group_diag)

        self.last_diagnostics["ar_groups"] = group_diagnostics
        self.last_diagnostics["ar_fixed_count"] = fixed_count
        self.last_diagnostics["ar_ratio"] = min(fixed_ratios) if fixed_ratios else 0.0
        if not constraints:
            self.last_diagnostics["ar_status"] = "waiting"
            self.last_diagnostics["ar_rejection_reason"] = (
                "; ".join(rejected_groups)
                if rejected_groups
                else "uncombined integer validation failed"
            )
            return False
        for row, residual in constraints:
            self._kalman_update(
                row.reshape(1, -1),
                np.asarray([residual], dtype=float),
                np.asarray(
                    [max(self.ar_constraint_sigma_m ** 2, 1e-10)],
                    dtype=float,
                ),
            )
        self.last_diagnostics["ar_status"] = "fixed"
        self.last_diagnostics["ar_rejection_reason"] = ""
        return True

    def _attempt_ambiguity_resolution(self, measurements, float_residuals, float_variances) -> bool:
        """Try between-satellite WL/NL integer constraints.

        The existing filter estimates one ionosphere-free ambiguity per signal
        pair.  We therefore fix *differences* between satellites, where the
        receiver clock and phase datum cancel.  This is the same zero-difference
        to between-satellite strategy, without treating an IF ambiguity itself
        as an integer number of cycles.
        """
        if not self.ar_enabled:
            return False
        if self.observation_model == "UNCOMBINED":
            return self._attempt_uncombined_ambiguity_resolution()
        eligible = [item for item in self._ar_observations if (
            item["system"] in self.ar_systems
            and item["integer_ready"]
            and (not self.ar_require_mw_consistency or item["mw_consistent"])
            and item["track"].count >= self.ar_min_epochs
            and item["amb_name"] in self.state_names
        )]
        self.last_diagnostics["ar_candidate_count"] = len(eligible)
        if not eligible:
            self.last_diagnostics["ar_status"] = "waiting"
            self.last_diagnostics["ar_rejection_reason"] = "no fresh integer-compatible phase biases"
            return False

        groups: Dict[tuple, List[dict]] = {}
        for item in eligible:
            pair = tuple(item["signals"])
            key = (
                item["system"],
                pair,
                round(item["f1_hz"], -2),
                round(item["f2_hz"], -2),
                item.get("provider_key"),
            )
            try:
                _az, elevation = calculate_az_el(item["sat_pos"], self.x[:3])
            except Exception:
                elevation = -90.0
            item["elevation_deg"] = float(elevation)
            if item["elevation_deg"] >= self.ar_min_elevation_deg:
                groups.setdefault(key, []).append(item)

        constraints = []
        ratios = []
        bie_fix_ratios = []
        fixed_count = 0
        rejected_groups = []
        group_diagnostics = []
        for key, candidates in groups.items():
            group_diag = {
                "system": key[0],
                "signals": key[1],
                "candidate_count": len(candidates),
                "wl_accepted_count": 0,
                "wl_fraction_max": 0.0,
                "wl_sigma_max": 0.0,
            }
            if len(candidates) < self.ar_min_satellites:
                group_diag["status"] = "not-enough-satellites"
                group_diagnostics.append(group_diag)
                continue

            # Choose the reference ambiguity that
            # minimises the summed variance of all between-satellite
            # differences in the group.  Elevation and MW stability only
            # break numerical ties.
            def reference_score(item: dict) -> Tuple[float, float, float]:
                index = self.state_names.index(item["amb_name"])
                variance_sum = 0.0
                for other in candidates:
                    other_index = self.state_names.index(other["amb_name"])
                    variance_sum += float(
                        self.P[index, index]
                        + self.P[other_index, other_index]
                        - 2.0 * self.P[index, other_index]
                    )
                return (
                    variance_sum,
                    -float(item["elevation_deg"]),
                    float(item["track"].sigma_mean_cycles),
                )

            candidates = sorted(
                candidates,
                key=reference_score,
            )
            reference = candidates[0]
            f1 = reference["f1_hz"]
            f2 = reference["f2_hz"]
            lambda_n = LIGHT_SPEED / (f1 + f2)
            k_wl = LIGHT_SPEED * f2 / ((f1 - f2) * (f1 + f2))
            rows = []
            difference_rows = []
            for item in candidates[1:]:
                if (
                    item.get("wide_lane_name") in self.state_names
                    and reference.get("wide_lane_name") in self.state_names
                ):
                    wl_float = float(
                        self.x[self.state_names.index(item["wide_lane_name"])]
                        - self.x[self.state_names.index(reference["wide_lane_name"])]
                    )
                    # The empirical MW-track scatter is the relevant
                    # wide-lane validation statistic.  MW remains an AR-only
                    # observable and is deliberately excluded from the
                    # position filter's residual/outlier loop.
                    wl_sigma = math.hypot(
                        item["track"].sigma_mean_cycles,
                        reference["track"].sigma_mean_cycles,
                    )
                else:
                    wl_float = item["track"].mean_cycles - reference["track"].mean_cycles
                    wl_sigma = math.hypot(item["track"].sigma_mean_cycles, reference["track"].sigma_mean_cycles)
                wl_int = int(round(wl_float))
                group_diag["wl_fraction_max"] = max(
                    float(group_diag["wl_fraction_max"]),
                    abs(float(wl_float - wl_int)),
                )
                if math.isfinite(wl_sigma):
                    group_diag["wl_sigma_max"] = max(
                        float(group_diag["wl_sigma_max"]),
                        float(wl_sigma),
                    )
                if abs(wl_float - wl_int) > self.ar_max_wl_fraction or wl_sigma > self.ar_max_wl_sigma_cycles:
                    continue
                idx = self.state_names.index(item["amb_name"])
                ref_idx = self.state_names.index(reference["amb_name"])
                b_float = float(self.x[idx] - self.x[ref_idx])
                if not math.isfinite(b_float):
                    continue
                # The IF ambiguity state is in metres.  Remove the validated
                # wide-lane contribution before converting the remaining
                # narrow-lane combination to cycles.
                nl_float = (b_float - k_wl * wl_int) / lambda_n
                nl_int = int(round(nl_float))
                # The float fractional part is a useful inexpensive gate,
                # but do not reject on the marginal sigma here.  The correlated
                # integer search first evaluates the
                # conditional/BIE result; a common-reference covariance can
                # otherwise reject a valid fix prematurely.
                if (
                    not self.precise_model_enabled
                    and abs(nl_float - nl_int) > self.ar_max_nl_fraction
                ):
                    continue
                difference_row = np.zeros(len(self.state_names), dtype=float)
                difference_row[idx] = 1.0
                difference_row[ref_idx] = -1.0
                rows.append((item, wl_int, difference_row))
                difference_rows.append(difference_row)
                group_diag["wl_accepted_count"] = int(
                    group_diag["wl_accepted_count"]
                ) + 1
            if len(rows) < self.ar_min_satellites - 1:
                group_diag["status"] = "wide-lane-validation-failed"
                group_diagnostics.append(group_diag)
                continue

            transform = np.asarray(difference_rows, dtype=float)
            # Match BNC's BIE datum handling: condition the zero-difference
            # ambiguities on the selected reference ambiguity being the
            # nearest integer.  This removes the common phase datum before
            # the integer search and materially reduces the conditional
            # covariance without adding a position prior.
            reference_index = self.state_names.index(reference["amb_name"])
            reference_wl_int = int(round(reference["track"].mean_cycles))
            reference_nl_float = (
                float(self.x[reference_index]) - k_wl * reference_wl_int
            ) / lambda_n
            reference_nl_int = int(round(reference_nl_float))
            reference_target_m = (
                lambda_n * reference_nl_int + k_wl * reference_wl_int
            )
            reference_residual_m = reference_target_m - float(
                self.x[reference_index]
            )
            reference_covariance_m2 = max(
                float(self.P[reference_index, reference_index])
                + max(self.ar_constraint_sigma_m ** 2, 1e-10),
                1e-10,
            )
            cross_covariance_m2 = transform @ self.P[:, reference_index]
            difference_m = transform @ self.x
            conditioned_difference_m = difference_m + (
                cross_covariance_m2 * reference_residual_m
                / reference_covariance_m2
            )
            covariance_m2 = (
                transform @ self.P @ transform.T
                - np.outer(cross_covariance_m2, cross_covariance_m2)
                / reference_covariance_m2
            )
            covariance_m2 = 0.5 * (covariance_m2 + covariance_m2.T)
            float_vec = np.asarray(
                [
                    (conditioned_difference_m[index] - k_wl * wl_int)
                    / lambda_n
                    for index, (_item, wl_int, _row) in enumerate(rows)
                ],
                dtype=float,
            )
            covariance = covariance_m2 / max(lambda_n * lambda_n, 1e-12)
            if self.precise_model_enabled:
                bie_search = self._integer_bie(float_vec, covariance)
                if bie_search is None:
                    rejected_groups.append(f"{key[0]}:{key[1]} BIE search failed")
                    group_diag["status"] = "bie-search-failed"
                    group_diagnostics.append(group_diag)
                    continue
                best_nl, bie_covariance, best_score, second_score, best_weight, search_nodes = bie_search
                bie_sigmas = np.sqrt(np.maximum(np.diag(bie_covariance), 0.0))
                fixable = np.ones(best_nl.size, dtype=bool)
                if self.ar_max_nl_fraction > 0.0 and self.ar_max_nl_sigma_cycles > 0.0:
                    fixable = (
                        np.abs(best_nl - np.rint(best_nl)) <= self.ar_max_nl_fraction
                    ) & (bie_sigmas <= self.ar_max_nl_sigma_cycles)
                fixed_in_group = int(np.count_nonzero(fixable))
                required_fix_count = (
                    len(candidates) - 1
                    if self.ar_require_full_group
                    else self.ar_min_satellites - 1
                )
                if fixed_in_group < required_fix_count:
                    rejected_groups.append(f"{key[0]}:{key[1]} BIE validation failed")
                    group_diag["status"] = "bie-validation-failed"
                    group_diag["bie_fixable_count"] = fixed_in_group
                    group_diag["bie_sigma_max"] = float(np.max(bie_sigmas))
                    group_diagnostics.append(group_diag)
                    continue
                bie_fix_ratios.append(fixed_in_group / max(len(rows), 1))
                self.last_diagnostics["ar_bie_best_weight"] = float(best_weight)
                self.last_diagnostics["ar_bie_max_sigma_cycles"] = float(np.max(bie_sigmas))
                self.last_diagnostics["ar_bie_candidates"] = 100
                self.last_diagnostics["ar_search_nodes"] = int(
                    self.last_diagnostics.get("ar_search_nodes", 0)
                ) + int(search_nodes)
                for row_index, (_item, wl_int, row) in enumerate(rows):
                    if not fixable[row_index]:
                        continue
                    fixed_value = lambda_n * float(best_nl[row_index]) + k_wl * wl_int
                    current_difference = float(row @ self.x)
                    constraints.append((row, float(fixed_value - current_difference)))
                    fixed_count += 1
                group_diag["status"] = "fixed"
                group_diag["fixed_count"] = fixed_in_group
                group_diagnostics.append(group_diag)
            else:
                try:
                    precision = np.linalg.pinv(covariance)
                    conditional_sigma = 1.0 / np.sqrt(
                        np.maximum(np.diag(precision), 1e-12)
                    )
                except (ValueError, np.linalg.LinAlgError, FloatingPointError):
                    continue
                max_conditional_sigma = float(np.max(conditional_sigma))
                self.last_diagnostics["ar_max_conditional_sigma_cycles"] = max_conditional_sigma
                if (
                    self.ar_max_nl_sigma_cycles > 0.0
                    and max_conditional_sigma > self.ar_max_nl_sigma_cycles
                ):
                    continue
                search = self._integer_least_squares(float_vec, covariance)
                if search is None:
                    continue
                best_nl, best_score, _second_nl, second_score, search_nodes = search
                ratio = second_score / max(best_score, 1e-12)
                self.last_diagnostics["ar_search_nodes"] = int(
                    self.last_diagnostics.get("ar_search_nodes", 0)
                ) + int(search_nodes)
                if ratio < self.ar_ratio_threshold:
                    rejected_groups.append(f"{key[0]}:{key[1]} ratio={ratio:.2f}")
                    group_diag["status"] = "ratio-failed"
                    group_diag["ratio"] = float(ratio)
                    group_diagnostics.append(group_diag)
                    continue
                ratios.append(ratio)
                for row_index, (_item, wl_int, row) in enumerate(rows):
                    fixed_value = lambda_n * float(best_nl[row_index]) + k_wl * wl_int
                    current_difference = float(row @ self.x)
                    constraints.append((row, float(fixed_value - current_difference)))
                    fixed_count += 1
                group_diag["status"] = "fixed"
                group_diag["fixed_count"] = len(rows)
                group_diag["ratio"] = float(ratio)
                group_diagnostics.append(group_diag)

        self.last_diagnostics["ar_groups"] = group_diagnostics
        self.last_diagnostics["ar_fixed_count"] = fixed_count
        self.last_diagnostics["ar_ratio"] = (
            min(bie_fix_ratios) if self.precise_model_enabled and bie_fix_ratios
            else min(ratios) if ratios
            else 0.0
        )
        if not constraints:
            self.last_diagnostics["ar_status"] = "waiting"
            self.last_diagnostics["ar_rejection_reason"] = (
                "; ".join(rejected_groups) if rejected_groups else "integer validation failed"
            )
            return False
        for row, residual in constraints:
            self._kalman_update(
                row.reshape(1, -1),
                np.asarray([residual], dtype=float),
                np.asarray([max(self.ar_constraint_sigma_m ** 2, 1e-10)], dtype=float),
            )
        self.last_diagnostics["ar_status"] = "fixed"
        self.last_diagnostics["ar_rejection_reason"] = ""
        return True

    def _make_result(
        self,
        epoch_obs,
        reference_system: str,
        system_state_names: Dict[str, str],
        h_rows: List[np.ndarray],
        residuals: List[float],
        variances: List[float],
        used_satellites: List[str],
        code_geometry: np.ndarray,
        ar_fixed: bool = False,
    ) -> PositioningResult:
        lat_rad, lon_rad, height_m = ecef2lla(self.x[:3])
        cov_xyz = self.P[:3, :3]
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
        cov_enu = rot @ cov_xyz @ rot.T
        std_east = math.sqrt(max(float(cov_enu[0, 0]), 0.0))
        std_north = math.sqrt(max(float(cov_enu[1, 1]), 0.0))
        std_up = math.sqrt(max(float(cov_enu[2, 2]), 0.0))
        clk_idx = self.state_names.index("CLK:G")
        std_clock = math.sqrt(max(float(self.P[clk_idx, clk_idx]), 0.0))
        std_pos = math.sqrt(std_east ** 2 + std_north ** 2 + std_up ** 2)

        gdop, pdop, hdop, vdop, tdop = self.spp._compute_dop(self.x[:3], code_geometry)
        ztd, zhd, zwd = self._estimated_zenith_troposphere()
        if "LOG_ZWD" in self.state_names:
            zwd_idx = self.state_names.index("LOG_ZWD")
            self.last_diagnostics["zwd_sigma_m"] = float(
                zwd * math.sqrt(max(float(self.P[zwd_idx, zwd_idx]), 0.0))
            )
            self.last_diagnostics["zwd_log_state"] = float(self.x[zwd_idx])
        self.last_diagnostics["troposphere_mapping"] = (
            "Niell hydrostatic/wet" if self.precise_model_enabled else "sine"
        )
        self.last_diagnostics["troposphere_gradients_enabled"] = bool(
            all(
                name in self.state_names
                for name in ("TROP_GRAD_N", "TROP_GRAD_E")
            )
        )
        if self.last_diagnostics["troposphere_gradients_enabled"]:
            self.last_diagnostics["troposphere_gradient_n_m"] = float(
                self.x[self.state_names.index("TROP_GRAD_N")]
            )
            self.last_diagnostics["troposphere_gradient_e_m"] = float(
                self.x[self.state_names.index("TROP_GRAD_E")]
            )
        weighted = np.asarray(residuals, dtype=float) / np.sqrt(np.maximum(np.asarray(variances, dtype=float), 1e-8))
        dof = max(1, len(residuals) - min(len(residuals), len(self.state_names)))
        variance_uow = float(weighted.dot(weighted) / dof) if weighted.size else 0.0

        status = "Fixed" if ar_fixed else "Uncertain"
        quality = ["PPP AR fixed" if ar_fixed else "PPP float"]
        if self._position_apriori_source:
            quality.append(f"apriori={self._position_apriori_source}")
        if not ar_fixed and math.isfinite(std_pos) and std_pos <= self.spp.fixed_std_pos:
            quality.append("float covariance stable")

        time_offsets = {}
        for system, name in system_state_names.items():
            if name in self.state_names:
                time_offsets[system] = float(self.x[self.state_names.index(name)] / LIGHT_SPEED)

        unique_used = []
        for sat in used_satellites:
            if sat not in unique_used:
                unique_used.append(sat)

        return PositioningResult(
            timestamp=float(epoch_obs.gps_time),
            epoch_time=getattr(epoch_obs, "utc_datetime", None) or datetime.now(timezone.utc),
            position_ecef=self.x[:3].tolist(),
            clock_bias=float(self.x[clk_idx]),
            clock_bias_seconds=float(self.x[clk_idx] / LIGHT_SPEED),
            num_satellites=len(unique_used),
            residuals=[float(value) for value in residuals],
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
            ztd=ztd,
            zhd=zhd,
            zwd=zwd,
            ambiguity_ratio=float(self.last_diagnostics.get("ar_ratio", 0.0) or 0.0),
            ambiguity_fixed_count=int(self.last_diagnostics.get("ar_fixed_count", 0) or 0),
            latitude=math.degrees(lat_rad),
            longitude=math.degrees(lon_rad),
            height=float(height_m),
            convergence=True,
            solution_status=status,
            time_offsets=time_offsets,
            used_satellites=unique_used,
            used_system_counts=self.spp._count_satellite_keys(unique_used),
            candidate_system_counts=dict(self.last_diagnostics.get("selected_system_counts", {})),
            solution_source="PPP AR fixed" if ar_fixed else "PPP float",
            quality_reason="; ".join(quality),
        )

    def _ambiguity_names_in_state(self) -> List[str]:
        return [name for name in self.state_names if name.startswith("AMB:")]
