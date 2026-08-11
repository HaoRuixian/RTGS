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
from core.spp_positioning import SPPPositioner, PositioningResult
from core.positioning_models import (
    PositioningSolution, PositioningMode, SolutionStatus, PositionTrack
)
from core.global_config import get_global_config
from core.ring_buffer import RingBuffer
import logging

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
        pos_config = config.get_positioning_settings()
        
        # Initialize SPPPositioner with configuration
        self.positioner = SPPPositioner(ephemeris_handler=handler, config=pos_config)
        self.position_track = PositionTrack()
        
        apr = config.approx_rec_pos
        if apr is None:
            self.approx_position = None
        else:
            try:
                self.approx_position = np.array(apr, dtype=float)
            except Exception:
                self.approx_position = None
        if self.approx_position is None or np.all(self.approx_position == 0):
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

    def update_positioning_settings(self, settings: dict) -> None:
        """Apply SPP settings to the live positioner."""
        if not settings:
            return

        min_satellites = settings.get("min_satellites")
        if min_satellites is not None:
            self.min_satellites = int(min_satellites)
            self.positioner.MIN_SATELLITES = int(min_satellites)

        min_elevation = settings.get("cutoff_elevation_deg", settings.get("min_elevation"))
        if min_elevation is not None:
            self.min_elevation = float(min_elevation)
            self.positioner.MIN_ELEVATION = float(min_elevation)

        if "max_pdop" in settings:
            self.positioner.max_pdop = float(settings["max_pdop"])
        if "ionosphere_option" in settings:
            self.positioner.ionosphere_option = settings["ionosphere_option"]
        if "troposphere_model" in settings:
            self.positioner.troposphere_model = settings["troposphere_model"]
        if "gnss_systems" in settings:
            self.positioner.gnss_systems = SPPPositioner.normalize_gnss_systems(settings["gnss_systems"])
        if "prefer_gps_only" in settings:
            self.positioner.prefer_gps_only = bool(settings["prefer_gps_only"])
        if "allow_gps_fallback" in settings:
            self.positioner.allow_gps_fallback = bool(settings["allow_gps_fallback"])
        if "require_ssr_corrections" in settings:
            self.positioner.require_ssr_corrections = bool(settings["require_ssr_corrections"])
        if "weight_mode" in settings:
            self.positioner.WEIGHT_MODE = settings["weight_mode"]
        if "code_sigma_m" in settings:
            self.positioner.code_sigma_m = float(settings["code_sigma_m"])
        if "system_code_weight_factors" in settings:
            self.positioner.system_code_weight_factors = {
                str(system).upper(): float(factor)
                for system, factor in dict(settings["system_code_weight_factors"]).items()
            }
        if "uncertain_std_pos" in settings:
            self.positioner.uncertain_std_pos = float(settings["uncertain_std_pos"])
        if "fixed_std_pos" in settings:
            self.positioner.fixed_std_pos = float(settings["fixed_std_pos"])
        
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
            
            # Use SPP to compute position
            # Pass approx_position only if it was successfully updated from a previous solution
            # Otherwise let the positioner compute an initial approximation from satellite positions
            if self.mode == PositioningMode.SPP:
                if self.last_position is not None:
                    # Use previous solution as initial guess
                    approx_pos = np.array(self.last_position.position_ecef, dtype=float)
                else:
                    # First epoch: use configured approximate position when available.
                    approx_pos = np.array(self.approx_position, dtype=float) if self.approx_position is not None else None
                
                result = self.positioner.process_epoch(epoch_obs, approx_pos)
            else:
                # Placeholder for other modes
                return None
            
            if result is None:
                self._emit_failure_diagnostics(getattr(self.positioner, "last_diagnostics", {}))
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
        
        # Extract GPS week from global config if available
        gps_week = 0  # Placeholder
        
        solution = PositioningSolution(
            timestamp=result.timestamp,
            gps_week=gps_week,
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
            f"[{self.name}] SPP used {solution.num_satellites} satellites "
            f"({used_counts}); candidates {candidate_counts}; source={source}; sats={used_satellites}"
        )
        if solution.fallback_reason:
            message += f"; fallback={solution.fallback_reason}"
        if solution.quality_reason:
            message += f"; quality={solution.quality_reason}"
        self.signals.log_signal.emit(message)

        reject_counts = (solution.diagnostics or {}).get("reject_counts", {})
        if reject_counts:
            self.signals.log_signal.emit(
                f"[{self.name}] SPP rejected observations: {self._format_counts(reject_counts)}"
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
        self.signals.log_signal.emit(
            f"[{self.name}] SPP no solution: {reason}; raw {raw_counts}; "
            f"extracted {extracted_counts}; selected {selected_counts}"
        )
        reject_counts = diagnostics.get("reject_counts", {})
        if reject_counts:
            self.signals.log_signal.emit(
                f"[{self.name}] SPP rejected observations: {self._format_counts(reject_counts)}"
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
    
    def set_parameters(self, min_satellites: int = None, min_elevation: float = None):
        """Update positioning parameters."""
        if min_satellites is not None:
            self.min_satellites = min_satellites
            self.positioner.MIN_SATELLITES = min_satellites
        if min_elevation is not None:
            self.min_elevation = min_elevation
            self.positioner.MIN_ELEVATION = min_elevation
    
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
