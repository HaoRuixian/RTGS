"""
Data models for GNSS positioning results and state.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum


class PositioningMode(Enum):
    """Positioning mode types."""
    SPP = "Single Point Positioning (SPP)"
    PPP = "Precise Point Positioning (PPP)"
    RTK = "Real-Time Kinematic (RTK)"


class SolutionStatus(Enum):
    """Solution status indicators."""
    NO_FIX = "No Fix"
    UNCERTAIN = "Unfixed"
    FIXED = "Fixed"


@dataclass
class PositioningConfig:
    """Positioning module configuration."""
    mode: PositioningMode = PositioningMode.SPP
    enabled: bool = True
    
    # Basic positioning parameters
    min_satellites: int = 4
    min_elevation: float = 10.0  # degrees (cutoff angle)
    max_pdop: float = 10.0
    
    # Observation weighting
    weight_mode: str = 'elevation'  # 'equal', 'elevation', 'snr'
    
    # Ionosphere correction strategy
    ionosphere_option: str = 'IFLC'  # 'IFLC' (dual-freq IF-LC) or 'SINGLE' (single-freq with TGD)
    
    # Troposphere model
    troposphere_model: str = 'Sastamoinen'  # 'None', 'Sastamoinen', 'HMSL'
    
    # GNSS Systems to use
    gnss_systems: List[str] = field(default_factory=lambda: ['G', 'R', 'E', 'C', 'J', 'I'])  # GPS, GLONASS, Galileo, BeiDou, QZSS, IRNSS
    
    # Smoothing/filtering
    use_smoothing: bool = False
    smoothing_window: int = 10  # epochs
    
    # Random walk noise (m/sqrt(s))
    random_walk: float = 0.0
    
    # Solution status thresholds
    uncertain_std_pos: float = 5.0  # meters - threshold for "uncertain" status
    fixed_std_pos: float = 2.5  # meters - threshold for "fixed" status


@dataclass
class PositioningSolution:
    """A single positioning solution."""
    timestamp: float  # GPS time of week (seconds)
    gps_week: int  # GPS week number
    
    # Position in different formats
    latitude: float  # degrees
    longitude: float  # degrees
    height: float  # meters (WGS84 ellipsoidal height)
    
    ecef_x: float  # ECEF X coordinate (meters)
    ecef_y: float  # ECEF Y coordinate (meters)
    ecef_z: float  # ECEF Z coordinate (meters)
    
    # Velocity (if available)
    velocity_north: float = 0.0  # m/s
    velocity_east: float = 0.0  # m/s
    velocity_up: float = 0.0  # m/s
    
    # Clock parameters
    clock_bias: float = 0.0  # meters (dT * c)
    clock_drift: float = 0.0  # m/s (dT * c, drift)
    # time offsets for other systems (seconds relative to GPS)
    time_offsets: Dict[str, float] = field(default_factory=dict)
    
    # Accuracy metrics
    std_north: float = 0.0  # meters
    std_east: float = 0.0  # meters
    std_up: float = 0.0  # meters
    std_clock: float = 0.0  # meters
    
    # DOP values
    gdop: float = 0.0
    pdop: float = 0.0
    hdop: float = 0.0
    vdop: float = 0.0
    tdop: float = 0.0
    
    # Quality indicators
    num_satellites: int = 0
    num_signals: int = 0
    variance_unit_weight: float = 0.0
    convergence: bool = False
    status: SolutionStatus = SolutionStatus.NO_FIX
    
    # Residuals statistics
    residuals_mean: float = 0.0
    residuals_std: float = 0.0
    residuals_max: float = 0.0
    
    # Additional metadata
    mode: PositioningMode = PositioningMode.SPP
    num_iterations: int = 0
    processing_time_ms: float = 0.0  # milliseconds

    # ------------------------------------------------------------------
    # convenience properties
    # ------------------------------------------------------------------
    @property
    def position_ecef(self) -> List[float]:
        """Return ECEF coordinates as a list [X, Y, Z].
        
        This property provides compatibility with other parts of the
        codebase that expect a ``position_ecef`` attribute (for example
        when using a previous ``PositioningSolution`` instance as an
        initial guess).  The values are derived from the explicit
        ``ecef_x``, ``ecef_y`` and ``ecef_z`` fields.
        """
        return [self.ecef_x, self.ecef_y, self.ecef_z]


@dataclass
class PositionTrack:
    """Track of position history."""
    positions: List[PositioningSolution] = field(default_factory=list)
    max_history: int = 1000  # maximum number of positions to keep
    
    def add_solution(self, solution: PositioningSolution):
        """Add a new position to the track."""
        self.positions.append(solution)
        # Keep only the last max_history positions
        if len(self.positions) > self.max_history:
            self.positions = self.positions[-self.max_history:]
    
    def get_displacement_from_start(self) -> Optional[tuple]:
        """
        Calculate displacement from first sample.
        
        Returns:
            (delta_north, delta_east, delta_up) in meters, or None if < 2 samples
        """
        if len(self.positions) < 2:
            return None
        
        first = self.positions[0]
        last = self.positions[-1]
        
        # Simple approximation: 1 degree ~= 111 km
        lat_diff = (last.latitude - first.latitude) * 111000
        lon_diff = (last.longitude - first.longitude) * 111000 * float(
            __import__('math').cos(__import__('math').radians(first.latitude))
        )
        height_diff = last.height - first.height
        
        return (lat_diff, lon_diff, height_diff)
    
    def clear(self):
        """Clear the position history."""
        self.positions.clear()


@dataclass
class PositioningStats:
    """Statistics for positioning performance."""
    total_epochs: int = 0
    fixed_count: int = 0
    uncertain_count: int = 0
    no_fix_count: int = 0
    
    avg_num_satellites: float = 0.0
    avg_hdop: float = 0.0
    avg_vdop: float = 0.0
    
    # Position statistics
    position_history: List[tuple] = field(default_factory=list)  # (lat, lon, height)
    
    @property
    def fix_rate(self) -> float:
        """Fix rate (100 * fixed_count / total_epochs)."""
        if self.total_epochs == 0:
            return 0.0
        return 100.0 * self.fixed_count / self.total_epochs
    
    def update(self, solution: PositioningSolution):
        """Update statistics with a new solution."""
        self.total_epochs += 1
        
        if solution.status == SolutionStatus.FIXED:
            self.fixed_count += 1
        elif solution.status == SolutionStatus.UNCERTAIN:
            self.uncertain_count += 1
        else:
            self.no_fix_count += 1
        
        # Running average
        n = self.total_epochs
        self.avg_num_satellites = (
            (n - 1) * self.avg_num_satellites + solution.num_satellites
        ) / n
        self.avg_hdop = (n - 1) * self.avg_hdop / n + solution.hdop / n
        self.avg_vdop = (n - 1) * self.avg_vdop / n + solution.vdop / n
        
        self.position_history.append((solution.latitude, solution.longitude, solution.height))
    
    def reset(self):
        """Reset all statistics."""
        self.total_epochs = 0
        self.fixed_count = 0
        self.uncertain_count = 0
        self.no_fix_count = 0
        self.avg_num_satellites = 0.0
        self.avg_hdop = 0.0
        self.avg_vdop = 0.0
        self.position_history.clear()
