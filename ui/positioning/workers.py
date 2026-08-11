"""
Positioning module workers - threaded positioning computation.

This module implements background threads for GNSS positioning calculations:
  - PositioningSignals: Qt signals for inter-thread communication
  - PositioningThread: Consumes observation epochs and computes positioning solutions

Threading model:
  - Observation data flows from monitoring module via RingBuffer
  - PositioningThread processes each epoch asynchronously
  - Solutions are emitted as Qt signals back to UI thread
"""

import threading
import time
import math
import numpy as np
from typing import Optional

from PySide6.QtCore import QObject, Signal
from core.ppp_positioning import PPPPositioner
from core.spp_positioning import SPPPositioner, PositioningResult
from core.positioning_models import (
    PositioningSolution, PositioningMode, SolutionStatus, PositionTrack
)
from core.global_config import get_global_config
from core.ring_buffer import RingBuffer
import logging
from core.geo_utils import ecef2lla
from core.gnss_time import GNSSTime
from core.native_rtk import NativeRTKRunner

logger = logging.getLogger(__name__)


class PositioningSignals(QObject):
    """
    Qt signal container for positioning thread communication.
    
    Attributes:
        solution_signal (Signal): Emitted when a new positioning solution is available
                                 Carries: PositioningSolution object
        log_signal (Signal): Emitted for logging and status messages
        status_signal (Signal): Emitted when positioning status changes
    """
    solution_signal = Signal(object)  # PositioningSolution
    log_signal = Signal(str)
    status_signal = Signal(str, bool)  # (status_name, is_active)
    stream_status_signal = Signal(str, bool)  # OBS/BASE/EPH native RTK streams


class PositioningThread(threading.Thread):
    """
    GNSS positioning computation thread.
    
    Consumes observation epochs from a queue and computes positioning solutions
    using SPP or other algorithms. Solutions are emitted as Qt signals.
    
    Responsibilities:
    - Receive EpochObservation objects from monitoring module
    - Maintain approximate receiver position
    - Compute SPP solutions using pseudorange observations
    - Track position history
    - Emit solutions to UI thread
    """
    
    def __init__(self, name: str, signals: PositioningSignals, ring_buffer: RingBuffer = None, handler=None):
        """
        Initialize positioning thread.
        
        Args:
            name: Thread identifier string
            signals: PositioningSignals object for Qt signal emission
            ring_buffer: RingBuffer containing observation epochs
            handler: RTCMHandler instance (for ephemeris cache access)
        """
        super().__init__()
        self.name = name
        self.signals = signals
        self.ring_buffer = ring_buffer
        self.handler = handler
        self.daemon = True
        self.running = True
        
        # Configuration
        config = get_global_config()
        pos_config = dict(config.get_positioning_settings())
        pos_config["ppp_ssr_mountpoint"] = str(config.ssr_settings.mountpoint or "")
        if not str(pos_config.get("ppp_station_id", "") or "").strip():
            pos_config["ppp_station_id"] = str(config.obs_settings.mountpoint or "")[:4].upper()
        
        # Initialize positioning engines with shared ephemeris/SSR caches.
        self.spp_positioner = SPPPositioner(ephemeris_handler=handler, config=pos_config)
        self.ppp_positioner = PPPPositioner(ephemeris_handler=handler, config=pos_config)
        self.positioner = self.spp_positioner
        self.position_track = PositionTrack()
        
        self._configured_reference_position = self._valid_reference_position(
            config.approx_rec_pos
        )
        self.reference_position = (
            None
            if self._configured_reference_position is None
            else self._configured_reference_position.copy()
        )
        self.reference_source = "stream-config" if self.reference_position is not None else ""
        self.ppp_independent_mode = bool(
            pos_config.get("ppp_independent_mode", False)
        )
        self.approx_position = (
            None
            if self.ppp_independent_mode or self.reference_position is None
            else self.reference_position.copy()
        )
        self.ppp_use_config_initial_position = bool(
            pos_config.get("ppp_use_config_initial_position", False)
        )
        if self.approx_position is None:
            # Let SPP compute the first coarse position from satellite geometry.
            self.approx_position = None
        
        self.mode = PositioningMode.SPP
        self.min_satellites = pos_config.get('min_satellites', 4)
        self.min_elevation = pos_config.get('cutoff_elevation_deg', 10.0)
        
        # Epoch caching and merging: combine observations from same UTC time
        # self.current_epoch_utc: normalized UTC time of the pending epoch (datetime object)
        # self.pending_epoch: EpochObservation being accumulated
        self.current_epoch_utc = None
        self.pending_epoch = None
        
        # Statistics
        self.solution_count = 0
        self.last_log_time = time.time()
        self.last_position = None
        self.first_solution = True
        self.last_diagnostic_log_time = 0.0
        self.last_solution_source = ""

    @staticmethod
    def _valid_reference_position(values) -> Optional[np.ndarray]:
        try:
            position = np.asarray(values, dtype=float).reshape(-1)[:3]
        except Exception:
            return None
        if position.size != 3 or not np.all(np.isfinite(position)):
            return None
        if np.linalg.norm(position) < 3_000_000.0:
            return None
        return position.copy()

    def _refresh_reference_position(self) -> None:
        """Refresh accuracy truth without accepting a live RTCM overwrite."""
        if self._configured_reference_position is not None:
            self.reference_position = self._configured_reference_position.copy()
            self.reference_source = "stream-config"
            return

        if self.ppp_independent_mode:
            self.reference_position = None
            self.reference_source = ""
            return

        station_position = self._valid_reference_position(
            getattr(self.handler, "last_station_coords", None)
        )
        if station_position is not None:
            self.reference_position = station_position
            self.reference_source = "RTCM 1005/1006"
            return

        self.reference_position = None
        self.reference_source = ""

    def refresh_runtime_config(self) -> None:
        """Apply stream-loaded positioning settings before a run starts."""
        config = get_global_config()
        self.update_positioning_settings(config.get_positioning_settings())
        self._configured_reference_position = self._valid_reference_position(
            config.approx_rec_pos
        )
        self._refresh_reference_position()
        self.approx_position = (
            None
            if self.ppp_independent_mode or self.reference_position is None
            else self.reference_position.copy()
        )

    def _apply_reference_errors(self, solution: PositioningSolution) -> None:
        self._refresh_reference_position()
        if self.reference_position is None:
            return

        estimate = np.array([solution.ecef_x, solution.ecef_y, solution.ecef_z], dtype=float)
        delta_xyz = estimate - self.reference_position
        lat_rad, lon_rad, _height_m = ecef2lla(self.reference_position)
        sin_lat, cos_lat = math.sin(lat_rad), math.cos(lat_rad)
        sin_lon, cos_lon = math.sin(lon_rad), math.cos(lon_rad)
        rotation = np.array(
            [
                [-sin_lon, cos_lon, 0.0],
                [-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat],
                [cos_lat * cos_lon, cos_lat * sin_lon, sin_lat],
            ],
            dtype=float,
        )
        east, north, up = rotation @ delta_xyz
        solution.has_reference_position = True
        solution.reference_source = self.reference_source
        solution.reference_ecef_x = float(self.reference_position[0])
        solution.reference_ecef_y = float(self.reference_position[1])
        solution.reference_ecef_z = float(self.reference_position[2])
        solution.error_ecef_x = float(delta_xyz[0])
        solution.error_ecef_y = float(delta_xyz[1])
        solution.error_ecef_z = float(delta_xyz[2])
        solution.error_east = float(east)
        solution.error_north = float(north)
        solution.error_up = float(up)
        solution.error_horizontal = float(math.hypot(east, north))
        solution.error_3d = float(np.linalg.norm(delta_xyz))

    def update_positioning_settings(self, settings: dict) -> None:
        """Apply SPP settings to the live positioner."""
        if not settings:
            return

        min_satellites = settings.get("min_satellites")
        if min_satellites is not None:
            self.min_satellites = int(min_satellites)
            self.spp_positioner.MIN_SATELLITES = int(min_satellites)

        min_elevation = settings.get("cutoff_elevation_deg", settings.get("min_elevation"))
        if min_elevation is not None:
            self.min_elevation = float(min_elevation)
            self.spp_positioner.MIN_ELEVATION = float(min_elevation)

        if "max_pdop" in settings:
            self.spp_positioner.max_pdop = float(settings["max_pdop"])
        if "ionosphere_option" in settings:
            self.spp_positioner.ionosphere_option = settings["ionosphere_option"]
        if "troposphere_model" in settings:
            self.spp_positioner.troposphere_model = settings["troposphere_model"]
        if "gnss_systems" in settings:
            self.spp_positioner.gnss_systems = SPPPositioner.normalize_gnss_systems(settings["gnss_systems"])
        if "prefer_gps_only" in settings:
            self.spp_positioner.prefer_gps_only = bool(settings["prefer_gps_only"])
        if "allow_gps_fallback" in settings:
            self.spp_positioner.allow_gps_fallback = bool(settings["allow_gps_fallback"])
        if "require_ssr_corrections" in settings:
            self.spp_positioner.require_ssr_corrections = bool(settings["require_ssr_corrections"])
        if "weight_mode" in settings:
            self.spp_positioner.WEIGHT_MODE = settings["weight_mode"]
        if "code_sigma_m" in settings:
            self.spp_positioner.code_sigma_m = float(settings["code_sigma_m"])
        if "system_code_weight_factors" in settings:
            self.spp_positioner.system_code_weight_factors = {
                str(system).upper(): float(factor)
                for system, factor in dict(settings["system_code_weight_factors"]).items()
            }
        if "uncertain_std_pos" in settings:
            self.spp_positioner.uncertain_std_pos = float(settings["uncertain_std_pos"])
        if "fixed_std_pos" in settings:
            self.spp_positioner.fixed_std_pos = float(settings["fixed_std_pos"])
        ppp_settings = dict(settings)
        if "ppp_use_config_initial_position" in settings:
            self.ppp_use_config_initial_position = bool(
                settings["ppp_use_config_initial_position"]
            )
        if "ppp_independent_mode" in settings:
            self.ppp_independent_mode = bool(settings["ppp_independent_mode"])
            if self.ppp_independent_mode:
                self.ppp_use_config_initial_position = False
                self.approx_position = None
        config = get_global_config()
        ppp_settings["ppp_ssr_mountpoint"] = str(config.ssr_settings.mountpoint or "")
        if not str(ppp_settings.get("ppp_station_id", "") or "").strip():
            ppp_settings["ppp_station_id"] = str(config.obs_settings.mountpoint or "")[:4].upper()
        self.ppp_positioner.update_config(ppp_settings)
        self.positioner = self._active_positioner()

    def _active_positioner(self):
        if self.mode == PositioningMode.PPP:
            return self.ppp_positioner
        return self.spp_positioner
        
    def run(self):
        """
        Main positioning computation loop with epoch caching and merging.
        
        Procedure:
        1. Wait for EpochObservation from ring_buffer (blocking with 100ms timeout)
        2. Extract UTC time (normalized to seconds) from epoch_obs
        3. If UTC time matches pending epoch, merge satellites/signals (accumulate)
        4. If UTC time differs from pending epoch, process the pending epoch and start caching the new one
        5. Every 30 seconds, log statistics: solution rate, position accuracy
        """
        self.signals.log_signal.emit(f"[{self.name}] Positioning thread started")
        self.signals.status_signal.emit("Ready", True)
        
        while self.running:
            try:
                # Check if ring_buffer is available
                if self.ring_buffer is None:
                    time.sleep(0.1)
                    continue
                
                # Step 1: Blocking get from ring_buffer with timeout
                # Blocks up to 100ms if no data available, allows responsive shutdown
                epoch_obs = self.ring_buffer.get(block=True, timeout=0.1)
                
                # Check if buffer is closed or empty
                if epoch_obs is None:
                    if self.ring_buffer.closed:
                        # Process any pending epoch before stopping
                        if self.pending_epoch is not None:
                            solution = self._process_epoch(self.pending_epoch)
                            if solution is not None:
                                self.solution_count += 1
                                if solution.status != SolutionStatus.NO_FIX:
                                    self.last_position = solution
                                    self.position_track.add_solution(solution)
                                self.signals.solution_signal.emit(solution)
                        self.signals.log_signal.emit(f"[{self.name}] Buffer closed, stopping")
                        break
                    continue
                
                # Step 2: Extract UTC time (normalized to seconds for merging)
                utc_dt = getattr(epoch_obs, 'utc_datetime', None)
                if utc_dt is None:
                    logger.warning(f"[{self.name}] epoch_obs missing utc_datetime, skipping")
                    continue
                
                # Normalize to whole second (remove microseconds)
                utc_normalized = utc_dt.replace(microsecond=0)
                
                # Step 3 & 4: Handle epoch caching and merging
                if self.current_epoch_utc is None:
                    # First epoch: start caching
                    self.current_epoch_utc = utc_normalized
                    self.pending_epoch = epoch_obs
                    
                elif utc_normalized == self.current_epoch_utc:
                    # Same UTC time: merge satellites/signals into pending epoch
                    for sat_k, sat_v in epoch_obs.satellites.items():
                        self.pending_epoch.satellites[sat_k] = sat_v
                    
                else:
                    # Different UTC time: process pending epoch, then start new
                    if self.pending_epoch is not None:
                        solution = self._process_epoch(self.pending_epoch)
                        
                        if solution is not None:
                            self.solution_count += 1
                            if solution.status != SolutionStatus.NO_FIX:
                                self.last_position = solution
                                self.position_track.add_solution(solution)

                            # Log first solution
                            if self.first_solution:
                                self.signals.log_signal.emit(
                                    f"[{self.name}] First solution computed: {solution.num_satellites} satellites, "
                                    f"UTC: {utc_normalized.strftime('%Y-%m-%d %H:%M:%S')}"
                                )
                                self.first_solution = False
                            
                            # Emit solution
                            self.signals.solution_signal.emit(solution)
                    
                    # Start caching the new epoch
                    self.current_epoch_utc = utc_normalized
                    self.pending_epoch = epoch_obs
                
                # Step 5: Periodic status logging every 30 seconds
                now = time.time()
                if now - self.last_log_time >= 30.0 and self.last_position is not None:
                    solution = self.last_position
                    self.signals.log_signal.emit(
                        f"[{self.name}] Stats: {self.solution_count} solutions, "
                        f"Last: {solution.status.value}, "
                        f"Sats: {solution.num_satellites}, "
                        f"Lat: {solution.latitude:.6f}°, Lon: {solution.longitude:.6f}°, "
                        f"Height: {solution.height:.2f}m, HDOP: {solution.hdop:.2f}"
                    )
                    self.solution_count = 0
                    self.last_log_time = now
                
            except Exception as e:
                self.signals.log_signal.emit(f"[{self.name}] Error: {str(e)}")
                logger.error(f"[{self.name}] Exception in positioning thread: {str(e)}", exc_info=True)
        
        self.signals.log_signal.emit(f"[{self.name}] Positioning thread stopped")
        self.signals.status_signal.emit("Stopped", False)
    
    def _process_epoch(self, epoch_obs) -> Optional[PositioningSolution]:
        """
        Process a single observation epoch.
        
        Args:
            epoch_obs: EpochObservation object
        
        Returns:
            PositioningSolution if successful, None otherwise
        """
        try:
            start_time = time.time()
            
            if self.mode in (PositioningMode.SPP, PositioningMode.PPP):
                active_positioner = self._active_positioner()
                self.positioner = active_positioner
                if self.mode == PositioningMode.PPP and self.ppp_independent_mode:
                    # The PPP core performs its own observation-only SPP
                    # bootstrap and rejects every external coordinate argument.
                    approx_pos = None
                elif (
                    self.mode == PositioningMode.PPP
                    and not self.ppp_positioner.use_station_apriori
                    and not self.ppp_use_config_initial_position
                ):
                    # The default PPP bootstrap is an SPP solution.  Do not pass
                    # the configured approximate/1005-1006 position into PPP on
                    # its first epoch; PPPPositioner will run SPP internally.
                    # A preceding SPP solution is safe to reuse when switching
                    # modes while the stream is already running.
                    if (
                        self.last_position is not None
                        and getattr(self.last_position, "mode", None) == PositioningMode.SPP
                    ):
                        approx_pos = np.array(self.last_position.position_ecef, dtype=float)
                    else:
                        approx_pos = None
                elif self.last_position is not None:
                    # Use previous solution as initial guess.
                    approx_pos = np.array(self.last_position.position_ecef, dtype=float)
                else:
                    # Station-apriori mode may use the configured approximate
                    # position when no decoded RTCM station coordinates exist.
                    approx_pos = np.array(self.approx_position, dtype=float) if self.approx_position is not None else None
                
                result = active_positioner.process_epoch(epoch_obs, approx_pos)
            else:
                self.signals.log_signal.emit(f"[{self.name}] {self.mode.name} positioning is not implemented")
                return None
            
            if result is None:
                self._emit_failure_diagnostics(getattr(active_positioner, "last_diagnostics", {}))
                return None
            
            # Convert RTCMHandler's PositioningResult to our PositioningSolution
            solution = self._convert_result_to_solution(result, epoch_obs)
            if solution.status != SolutionStatus.NO_FIX:
                self.approx_position = np.array(result.position_ecef, dtype=float)
            
            # Timing
            solution.processing_time_ms = (time.time() - start_time) * 1000
            self._emit_solution_diagnostics(solution)
            
            return solution
        
        except Exception as e:
            logger.error(f"Epoch processing failed: {str(e)}")
            return None
    
    def _convert_result_to_solution(
        self, result: PositioningResult, epoch_obs
    ) -> PositioningSolution:
        """Convert SPPPositioner's PositioningResult to PositioningSolution."""
        
        status_map = {
            "Fixed": SolutionStatus.FIXED,
            "Uncertain": SolutionStatus.UNCERTAIN,
            "Unfixed": SolutionStatus.UNCERTAIN,
            "No Fix": SolutionStatus.NO_FIX,
        }
        status = status_map.get(result.solution_status, SolutionStatus.NO_FIX)
        
        # Count total signals
        num_signals = sum(
            len(sat.signals) for sat in epoch_obs.satellites.values()
        )
        
        epoch_time = getattr(result, "epoch_time", None) or getattr(epoch_obs, "utc_datetime", None)
        try:
            gps_week, _gps_sow = GNSSTime.utc_to_gps(epoch_time)
        except Exception:
            gps_week = 0
        
        solution = PositioningSolution(
            timestamp=result.timestamp,
            gps_week=gps_week,
            epoch_time=epoch_time,
            latitude=result.latitude,
            longitude=result.longitude,
            height=result.height,
            ecef_x=result.position_ecef[0],
            ecef_y=result.position_ecef[1],
            ecef_z=result.position_ecef[2],
            clock_bias=result.clock_bias,
            std_north=result.std_dev_north,
            std_east=result.std_dev_east,
            std_up=result.std_dev_up,
            std_clock=result.std_dev_clock,
            gdop=result.gdop,
            pdop=result.pdop,
            hdop=result.hdop,
            vdop=result.vdop,
            tdop=result.tdop,
            ztd=float(getattr(result, "ztd", 0.0) or 0.0),
            zhd=float(getattr(result, "zhd", 0.0) or 0.0),
            zwd=float(getattr(result, "zwd", 0.0) or 0.0),
            ambiguity_ratio=float(getattr(result, "ambiguity_ratio", 0.0) or 0.0),
            num_satellites=result.num_satellites,
            num_signals=num_signals,
            variance_unit_weight=result.variance,
            convergence=result.convergence,
            status=status,
            mode=self.mode,
            time_offsets=getattr(result, 'time_offsets', {}),
            used_satellites=list(getattr(result, "used_satellites", []) or []),
            used_system_counts=dict(getattr(result, "used_system_counts", {}) or {}),
            candidate_system_counts=dict(getattr(result, "candidate_system_counts", {}) or {}),
            solution_source=str(getattr(result, "solution_source", "") or ""),
            fallback_reason=str(getattr(result, "fallback_reason", "") or ""),
            quality_reason=str(getattr(result, "quality_reason", "") or ""),
            diagnostics=dict(getattr(self.positioner, "last_diagnostics", {}) or {}),
        )
        
        # Compute residuals statistics
        if result.residuals:
            residuals_array = np.array(result.residuals)
            solution.residuals_mean = float(np.mean(residuals_array))
            solution.residuals_std = float(np.std(residuals_array))
            solution.residuals_max = float(np.max(np.abs(residuals_array)))

        self._apply_reference_errors(solution)
        
        return solution

    @staticmethod
    def _format_counts(counts: dict) -> str:
        if not counts:
            return "-"
        return ",".join(f"{system}:{int(count)}" for system, count in sorted(counts.items()))

    @staticmethod
    def _format_satellites(satellites: list[str], limit: int = 24) -> str:
        if not satellites:
            return "-"
        ordered = sorted(str(item) for item in satellites)
        if len(ordered) <= limit:
            return ",".join(ordered)
        shown = ",".join(ordered[:limit])
        return f"{shown},...(+{len(ordered) - limit})"

    def _emit_solution_diagnostics(self, solution: PositioningSolution) -> None:
        now = time.time()
        source = solution.solution_source or "Unknown"
        should_log = (
            self.last_diagnostic_log_time == 0.0
            or source != self.last_solution_source
            or bool(solution.fallback_reason)
            or now - self.last_diagnostic_log_time >= 15.0
        )
        if not should_log:
            return

        candidate_counts = self._format_counts(solution.candidate_system_counts)
        used_counts = self._format_counts(solution.used_system_counts)
        used_satellites = self._format_satellites(solution.used_satellites)
        message = (
            f"[{self.name}] {solution.mode.name} used {solution.num_satellites} satellites "
            f"({used_counts}); candidates {candidate_counts}; source={source}; sats={used_satellites}"
        )
        if solution.fallback_reason:
            message += f"; fallback={solution.fallback_reason}"
        if solution.quality_reason:
            message += f"; quality={solution.quality_reason}"
        diagnostics = solution.diagnostics or {}
        if solution.mode == PositioningMode.PPP:
            message += (
                f"; SSR-ref={diagnostics.get('ssr_reference_point', '?')}"
                f"; ANTEX={'on' if diagnostics.get('antex_loaded') else 'off'}"
                f"; AR={diagnostics.get('ar_status', 'unknown')}"
                f" candidates={int(diagnostics.get('ar_candidate_count', 0) or 0)}"
                f" fixed={int(diagnostics.get('ar_fixed_count', 0) or 0)}"
            )
            ar_reason = str(diagnostics.get("ar_rejection_reason", "") or "")
            if ar_reason:
                message += f" ({ar_reason})"
        self.signals.log_signal.emit(message)

        reject_counts = diagnostics.get("reject_counts", {})
        if reject_counts:
            self.signals.log_signal.emit(
                f"[{self.name}] {solution.mode.name} rejected observations: {self._format_counts(reject_counts)}"
            )

        self.last_diagnostic_log_time = now
        self.last_solution_source = source

    def _emit_failure_diagnostics(self, diagnostics: dict) -> None:
        now = time.time()
        if now - self.last_diagnostic_log_time < 15.0:
            return

        raw_counts = self._format_counts(diagnostics.get("raw_system_counts", {}))
        extracted_counts = self._format_counts(diagnostics.get("extracted_system_counts", {}))
        selected_counts = self._format_counts(diagnostics.get("selected_system_counts", {}))
        reason = diagnostics.get("failure_reason", "no solution")
        solver_reason = diagnostics.get("solver_failure_reason", "")
        if solver_reason:
            reason = f"{reason}; {solver_reason}"
        mode_label = self.mode.name
        self.signals.log_signal.emit(
            f"[{self.name}] {mode_label} no solution: {reason}; raw {raw_counts}; "
            f"extracted {extracted_counts}; selected {selected_counts}"
        )
        reject_counts = diagnostics.get("reject_counts", {})
        if reject_counts:
            self.signals.log_signal.emit(
                f"[{self.name}] {mode_label} rejected observations: {self._format_counts(reject_counts)}"
            )
        self.last_diagnostic_log_time = now
    
    def set_ring_buffer(self, ring_buffer: RingBuffer):
        """
        Set the ring buffer for receiving observation epochs.
        
        Args:
            ring_buffer: RingBuffer containing observation epochs
        """
        self.ring_buffer = ring_buffer
    
    def set_mode(self, mode: PositioningMode):
        """Set positioning mode."""
        self.mode = mode
        self.positioner = self._active_positioner()
    
    def set_parameters(self, min_satellites: int = None, min_elevation: float = None):
        """Update positioning parameters."""
        if min_satellites is not None:
            self.min_satellites = min_satellites
            self.spp_positioner.MIN_SATELLITES = min_satellites
            self.ppp_positioner.spp.MIN_SATELLITES = min_satellites
        if min_elevation is not None:
            self.min_elevation = min_elevation
            self.spp_positioner.MIN_ELEVATION = min_elevation
            self.ppp_positioner.spp.MIN_ELEVATION = min_elevation
    
    def get_position_history(self):
        """Get complete position history."""
        return self.position_track.positions
    
    def get_last_solution(self) -> Optional[PositioningSolution]:
        """Get the most recent positioning solution."""
        return self.last_position
    
    def stop(self):
        """Signal the thread to stop."""
        self.running = False
        if self.ring_buffer:
            self.ring_buffer.close()


class RTKEngineThread(threading.Thread):
    """Run the RTK engine against the original rover and base/network streams."""

    def __init__(self, name: str, signals: PositioningSignals):
        super().__init__(name=name, daemon=True)
        self.signals = signals
        self.running = True
        config = get_global_config()
        self.runner = NativeRTKRunner(
            config.obs_settings,
            config.base_settings,
            config.eph_settings,
            dict(config.get_positioning_settings()),
            approx_rec_pos=config.approx_rec_pos,
        )
        self._last_quality = ""
        self._last_quality_log = 0.0

    def _on_solution(self, solution: PositioningSolution) -> None:
        if not self.running:
            return
        quality = str(solution.diagnostics.get("rtk_quality_label", ""))
        now = time.monotonic()
        if quality != self._last_quality or now - self._last_quality_log >= 30.0:
            age = float(solution.diagnostics.get("differential_age_s", 0.0))
            ratio = float(solution.diagnostics.get("ambiguity_ratio", 0.0))
            self.signals.log_signal.emit(
                f"[{self.name}] {quality}: sats={solution.num_satellites}, "
                f"age={age:.2f}s, ratio={ratio:.1f}"
            )
            self._last_quality = quality
            self._last_quality_log = now
        self.signals.solution_signal.emit(solution)

    def _on_log(self, message: str) -> None:
        self.signals.log_signal.emit(f"[{self.name}] {message}")

    def _on_stream_status(self, stream_name: str, active: bool) -> None:
        self.signals.stream_status_signal.emit(stream_name, active)

    def run(self) -> None:
        self.signals.log_signal.emit(f"[{self.name}] Native RTK positioning thread started")
        self.signals.status_signal.emit("RTK", True)
        try:
            self.runner.run(
                self._on_solution,
                log_callback=self._on_log,
                stream_status_callback=self._on_stream_status,
            )
        except InterruptedError:
            pass
        except Exception as exc:
            if self.running:
                logger.error("RTK worker failed: %s", exc, exc_info=True)
                self.signals.log_signal.emit(f"[{self.name}] RTK error: {exc}")
        finally:
            self.running = False
            self.signals.status_signal.emit("RTK", False)
            self.signals.log_signal.emit(f"[{self.name}] Native RTK positioning thread stopped")

    def stop(self) -> None:
        self.running = False
        self.runner.stop()
