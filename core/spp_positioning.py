"""
Single Point Positioning (SPP) using pseudorange measurements.

Theory:
  SPP solves for 4 unknowns (X, Y, Z, clock_bias) using pseudorange observations.
  The observation equation is:
    P = ρ + dT·c + ε
  where:
    P: measured pseudorange (meters)
    ρ: geometric range from satellite to receiver (meters)
    dT: receiver clock bias (seconds)
    c: speed of light
    ε: measurement noise

  For each satellite i:
    P_i = sqrt((X_sat_i - X_rec)^2 + (Y_sat_i - Y_rec)^2 + (Z_sat_i - Z_rec)^2) + c·dT + ε_i

  We linearize and solve using Least Squares:
    x = (A^T·W·A)^(-1)·A^T·W·l
  where:
    A: design matrix (partial derivatives)
    W: weight matrix (optional: based on elevation angle)
    l: observation vector (pseudorange - computed ranges)

References:
  - GNSS Data Processing Vol. I & II by Teunissen & Montenbruck
  - Leick, A. GPS Satellite Surveying (3rd ed.), Wiley, 2004
"""

import math
import numpy as np
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class PositioningResult:
    """SPP solution result."""
    timestamp: float  # GPS time of week (seconds)
    epoch_time: datetime  # Epoch datetime
    
    # Solution
    position_ecef: List[float]  # [X, Y, Z] in meters (ECEF)
    clock_bias: float  # Clock bias in meters (dt * c)
    clock_bias_seconds: float  # Clock bias in seconds
    
    # Accuracy metrics
    num_satellites: int  # Number of satellites used
    residuals: List[float]  # Observation residuals
    variance: float  # Variance of unit weight
    std_dev_north: float  # Standard deviation in North
    std_dev_east: float  # Standard deviation in East
    std_dev_up: float  # Standard deviation in Up
    std_dev_clock: float  # Standard deviation of clock bias
    
    # DOP values
    gdop: float  # Geometric DOP
    pdop: float  # Position DOP
    hdop: float  # Horizontal DOP
    vdop: float  # Vertical DOP
    tdop: float  # Time DOP
    
    # Receiver position in LLA
    latitude: float  # Degrees
    longitude: float  # Degrees
    height: float  # Meters
    
    # Quality indicators
    convergence: bool  # Whether solution converged
    solution_status: str  # 'Fixed', 'Uncertain', or 'No Fix'


class SPPPositioner:
    """Single Point Positioning engine."""
    
    # Constants
    CLIGHT = 299792458.0  # Speed of light (m/s)
    WEIGHT_MODE = 'elevation'  # Options: 'equal', 'elevation', 'snr'
    MAX_ITERATIONS = 10
    CONVERGENCE_THRESHOLD = 1e-4  # meters
    MIN_SATELLITES = 4
    MIN_ELEVATION = 10.0  # Degrees
    
    def __init__(self, ephemeris_handler=None):
        """
        Initialize SPP positioner.
        
        Args:
            ephemeris_handler: RTCMHandler instance for accessing ephemeris cache
        """
        self.handler = ephemeris_handler
        self.last_solution = None
        self.logger = logging.getLogger(__name__)
    
    def process_epoch(self, epoch_obs, approx_position: np.ndarray) -> Optional[PositioningResult]:
        """
        Process one observation epoch and compute SPP solution.
        
        Args:
            epoch_obs: EpochObservation object with satellite observations
            approx_position: Approximate receiver position [X, Y, Z] in ECEF (meters)
                           Used as initial guess for iteration
        
        Returns:
            PositioningResult object if solution is valid, None otherwise
        """
        try:
            # Step 1: Extract available satellites and check minimum
            observations = self._extract_observations(epoch_obs, approx_position)
            if observations is None or len(observations) < self.MIN_SATELLITES:
                self.logger.warning(f"Insufficient satellites: {len(observations) if observations else 0}")
                return None
            
            # Step 2: Iterative least-squares solver
            solution = self._solve_least_squares(
                observations, approx_position, epoch_obs.gps_time
            )
            
            if solution is not None:
                self.last_solution = solution
                return solution
            else:
                return None
                
        except Exception as e:
            self.logger.error(f"SPP processing error: {str(e)}")
            return None
    
    def _extract_observations(
        self, epoch_obs, approx_position: np.ndarray
    ) -> Optional[List[Dict]]:
        """
        Extract usable pseudorange observations from epoch.
        
        Filters by:
          - Signal availability (need at least one signal with pseudorange)
          - Elevation angle > MIN_ELEVATION
          - Valid pseudorange and position data
        
        Returns:
            List of observation dicts, each containing:
              - sat_key: Satellite identifier (e.g., 'G01', 'C12')
              - pseudorange: Measured pseudorange (meters)
              - elevation: Elevation angle (degrees)
              - azimuth: Azimuth angle (degrees)
              - sat_pos: Satellite ECEF position [X, Y, Z]
              - satellite: Original SatelliteState object (for SNR, phase, etc.)
        """
        observations = []

        for sat_key, satellite in epoch_obs.satellites.items():
            # Ensure satellite position exists
            sat_pos = getattr(satellite, 'sat_pos_ecef', None)
            if sat_pos is None:
                continue
            # Accept both list and numpy array
            try:
                if len(sat_pos) == 0:
                    continue
            except Exception:
                # If sat_pos doesn't support len but is valid, continue
                pass

            # Ensure signals present
            sigs = getattr(satellite, 'signals', None)
            if not sigs:
                continue

            # Elevation must be present and above threshold
            el = getattr(satellite, 'elevation', None)
            if el is None:
                continue
            if el < self.MIN_ELEVATION:
                continue

            # Extract first valid pseudorange among signals (be permissive)
            pseudorange = None
            for sig_id, signal in sigs.items():
                if signal is None:
                    continue
                # Many parsers may use attribute names slightly different; try common ones
                pr = None
                if hasattr(signal, 'pseudorange'):
                    pr = getattr(signal, 'pseudorange')
                elif hasattr(signal, 'psr'):
                    pr = getattr(signal, 'psr')
                elif hasattr(signal, 'code'):
                    pr = getattr(signal, 'code')

                try:
                    if pr is not None and float(pr) > 0:
                        pseudorange = float(pr)
                        break
                except Exception:
                    continue

            if pseudorange is None:
                continue

            observations.append({
                'sat_key': sat_key,
                'pseudorange': pseudorange,
                'elevation': float(getattr(satellite, 'elevation', 0.0) or 0.0),
                'azimuth': float(getattr(satellite, 'azimuth', 0.0) or 0.0),
                'sat_pos': np.array(sat_pos, dtype=float),
                'satellite': satellite,
            })

        return observations if len(observations) > 0 else None
    
    def _solve_least_squares(
        self, observations: List[Dict], approx_position: np.ndarray, gps_time: float
    ) -> Optional[PositioningResult]:
        """
        Iterative least-squares solution for SPP.
        
        Solves the system:
          A·x = b
        where:
          A: Design matrix (4 x n_sat), each row is [∂ρ/∂X, ∂ρ/∂Y, ∂ρ/∂Z, -1]
          x: State vector [ΔX, ΔY, ΔZ, Δcdt]
          b: Pseudorange residuals
        """
        # Initial state estimate
        x_curr = np.zeros(4)  # [ΔX, ΔY, ΔZ, Δcdt]
        pos_curr = approx_position.copy()
        
        convergence = False
        iteration = 0
        residuals_list = []
        
        # Iterative refinement
        while iteration < self.MAX_ITERATIONS:
            n_sat = len(observations)
            
            # Design matrix and observation vector
            A = np.zeros((n_sat, 4))  # Design matrix
            b = np.zeros(n_sat)  # Observation vector (pseudorange residuals)
            W = np.eye(n_sat)  # Weight matrix
            
            # Build equations
            for i, obs in enumerate(observations):
                sat_pos = obs['sat_pos']
                pr_meas = obs['pseudorange']
                
                # Approximate geometric range
                dr = sat_pos - pos_curr
                rho = np.linalg.norm(dr)
                
                # Design matrix: partial derivatives of geometric range
                if rho > 0:
                    A[i, 0] = -dr[0] / rho  # ∂ρ/∂X
                    A[i, 1] = -dr[1] / rho  # ∂ρ/∂Y
                    A[i, 2] = -dr[2] / rho  # ∂ρ/∂Z
                
                # Clock term (coefficient = 1.0) - we treat clock_bias in meters
                A[i, 3] = 1.0

                # Residual: measured pseudorange - (geometric range + clock bias)
                # x_curr[3] is clock bias in meters (cdt * c)
                pr_computed = rho + x_curr[3]
                b[i] = pr_meas - pr_computed
                
                # Weight by elevation angle (higher elevation = higher weight)
                if self.WEIGHT_MODE == 'elevation':
                    el = obs['elevation']
                    # Weight = 1/sin^2(el), with minimum to avoid singular matrix
                    el_rad = math.radians(el)
                    sin_el = math.sin(el_rad)
                    if sin_el > 0:
                        W[i, i] = 1.0 / (sin_el ** 2)
                    else:
                        W[i, i] = 1.0  # Fallback
            
            # Normal equations: (A^T·W·A)·x = A^T·W·b
            try:
                AtWA = A.T @ W @ A
                AtWb = A.T @ W @ b
                
                # Add regularization for numerical stability
                AtWA += 1e-6 * np.eye(4)
                
                delta_x = np.linalg.solve(AtWA, AtWb)
            except np.linalg.LinAlgError:
                self.logger.error("Singular matrix in normal equations")
                return None
            
            # Update position and state
            pos_new = pos_curr + delta_x[:3]
            x_new = x_curr + delta_x
            
            # Check convergence: position change < threshold
            pos_change = np.linalg.norm(delta_x[:3])
            if pos_change < self.CONVERGENCE_THRESHOLD:
                convergence = True
                x_curr = x_new
                pos_curr = pos_new
                break
            
            # Update for next iteration
            x_curr = x_new
            pos_curr = pos_new
            iteration += 1
        
        # Compute final residuals and statistics
        residuals_final = []
        for i, obs in enumerate(observations):
            sat_pos = obs['sat_pos']
            pr_meas = obs['pseudorange']
            dr = sat_pos - pos_curr
            rho = np.linalg.norm(dr)
            pr_computed = rho + x_curr[3] / self.CLIGHT
            residual = pr_meas - pr_computed
            residuals_final.append(residual)
        
        # Compute variance of unit weight
        if len(observations) > 4:
            residuals_squared = np.array(residuals_final) ** 2
            variance_uow = np.sum(residuals_squared) / (len(observations) - 4)
        else:
            variance_uow = 0.0
        
        # Compute covariance matrix
        try:
            A_final = np.zeros((len(observations), 4))
            for i, obs in enumerate(observations):
                sat_pos = obs['sat_pos']
                dr = sat_pos - pos_curr
                rho = np.linalg.norm(dr)
                if rho > 0:
                    A_final[i, :3] = -dr / rho
                A_final[i, 3] = 1.0
            
            W_final = np.eye(len(observations))
            if self.WEIGHT_MODE == 'elevation':
                for i, obs in enumerate(observations):
                    el = obs['elevation']
                    el_rad = math.radians(el)
                    sin_el = math.sin(el_rad)
                    if sin_el > 0:
                        W_final[i, i] = 1.0 / (sin_el ** 2)
            
            AtWA_final = A_final.T @ W_final @ A_final
            AtWA_final += 1e-6 * np.eye(4)
            cov_matrix = variance_uow * np.linalg.inv(AtWA_final)
            
            # Extract standard deviations
            std_x = math.sqrt(max(cov_matrix[0, 0], 0))
            std_y = math.sqrt(max(cov_matrix[1, 1], 0))
            std_z = math.sqrt(max(cov_matrix[2, 2], 0))
            std_clock = math.sqrt(max(cov_matrix[3, 3], 0))
            
        except Exception as e:
            self.logger.warning(f"Covariance computation failed: {str(e)}")
            std_x = std_y = std_z = std_clock = 0.0
            cov_matrix = None
        
        # Compute DOP values
        try:
            gdop, pdop, hdop, vdop, tdop = self._compute_dop(pos_curr, observations, cov_matrix, variance_uow)
        except Exception:
            gdop = pdop = hdop = vdop = tdop = 0.0
        
        # Convert ECEF to LLA
        lla = self._ecef2lla(pos_curr)
        
        # Determine solution status
        if convergence and len(observations) >= self.MIN_SATELLITES:
            solution_status = 'Fixed'
        elif len(observations) >= self.MIN_SATELLITES:
            solution_status = 'Uncertain'
        else:
            solution_status = 'No Fix'
        
        # Convert coordinates (ENU) for uncertainty
        lat_rad = math.radians(lla[0])
        lon_rad = math.radians(lla[1])
        
        # Rotation matrix ECEF->ENU
        sl = math.sin(lat_rad)
        cl = math.cos(lat_rad)
        slon = math.sin(lon_rad)
        clon = math.cos(lon_rad)
        
        R = np.array([
            [-slon, clon, 0],
            [-sl*clon, -sl*slon, cl],
            [cl*clon, cl*slon, sl]
        ])
        
        cov_enu = R @ cov_matrix[:3, :3] @ R.T if cov_matrix is not None else np.zeros((3, 3))
        std_north = math.sqrt(max(cov_enu[0, 0], 0)) if cov_matrix is not None else 0.0
        std_east = math.sqrt(max(cov_enu[1, 1], 0)) if cov_matrix is not None else 0.0
        std_up = math.sqrt(max(cov_enu[2, 2], 0)) if cov_matrix is not None else 0.0
        
        return PositioningResult(
            timestamp=gps_time,
            epoch_time=datetime.utcnow(),
            position_ecef=pos_curr.tolist(),
            clock_bias=x_curr[3],
            clock_bias_seconds=x_curr[3] / self.CLIGHT,
            num_satellites=len(observations),
            residuals=residuals_final,
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
            latitude=lla[0],
            longitude=lla[1],
            height=lla[2],
            convergence=convergence,
            solution_status=solution_status,
        )
    
    def _compute_dop(self, position: np.ndarray, observations: List[Dict], cov_matrix: np.ndarray, variance_uow: float) -> Tuple:
        """
        Compute DOP (Dilution of Precision) values.
        
        Returns:
            (GDOP, PDOP, HDOP, VDOP, TDOP)
        """
        if cov_matrix is None:
            return 0.0, 0.0, 0.0, 0.0, 0.0
        
        try:
            # Convert covariance matrix to geometry matrix inverse (unitless Q = Cov / variance_uow)
            if variance_uow > 0:
                Q = cov_matrix / variance_uow
            else:
                Q = cov_matrix * 0.0

            # GDOP = sqrt(trace(Q))
            trace = np.trace(Q)
            gdop = math.sqrt(trace) if trace > 0 else 0.0

            # PDOP = sqrt(Qxx + Qyy + Qzz)
            pdop_var = Q[0, 0] + Q[1, 1] + Q[2, 2]
            pdop = math.sqrt(pdop_var) if pdop_var > 0 else 0.0
            
            # Convert to ENU for HDOP/VDOP
            lat = math.radians(self._ecef2lla(position)[0])
            lon = math.radians(self._ecef2lla(position)[1])
            
            sl = math.sin(lat)
            cl = math.cos(lat)
            slon = math.sin(lon)
            clon = math.cos(lon)
            
            R = np.array([
                [-slon, clon, 0],
                [-sl*clon, -sl*slon, cl],
                [cl*clon, cl*slon, sl]
            ])
            
            cov_enu = R @ Q[:3, :3] @ R.T

            # HDOP = sqrt(Qee + Qnn)
            hdop_var = cov_enu[1, 1] + cov_enu[0, 0]
            hdop = math.sqrt(hdop_var) if hdop_var > 0 else 0.0

            # VDOP = sqrt(Quu)
            vdop_var = cov_enu[2, 2]
            vdop = math.sqrt(vdop_var) if vdop_var > 0 else 0.0

            # TDOP = sqrt(Qtt)
            tdop_var = Q[3, 3]
            tdop = math.sqrt(tdop_var) if tdop_var > 0 else 0.0
            
            return gdop, pdop, hdop, vdop, tdop
        except Exception as e:
            self.logger.warning(f"DOP computation failed: {str(e)}")
            return 0.0, 0.0, 0.0, 0.0, 0.0
    
    @staticmethod
    def _ecef2lla(pos: np.ndarray) -> Tuple[float, float, float]:
        """
        Convert ECEF [X, Y, Z] to LLA [latitude, longitude, altitude].
        
        Returns:
            (latitude_degrees, longitude_degrees, altitude_meters)
        """
        x, y, z = pos[0], pos[1], pos[2]
        
        # WGS84 constants
        a = 6378137.0
        e2 = 6.69437999014e-3
        
        b = a * math.sqrt(1 - e2)
        ep = math.sqrt((a**2 - b**2) / b**2)
        p = math.sqrt(x**2 + y**2)
        
        if p == 0:
            return 0.0, 0.0, z
        
        th = math.atan2(a*z, b*p)
        lon = math.atan2(y, x)
        lat = math.atan2(
            z + ep*ep*b*(math.sin(th)**3),
            p - e2*a*(math.cos(th)**3)
        )
        
        # Approximate altitude
        sin_lat = math.sin(lat)
        N = a / math.sqrt(1 - e2 * sin_lat**2)
        alt = p / math.cos(lat) - N
        
        return math.degrees(lat), math.degrees(lon), alt
