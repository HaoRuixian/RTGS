"""
Data models for storing GNSS observations and satellite states.
"""
from dataclasses import dataclass, field
from typing import Dict, Optional
from datetime import datetime

@dataclass
class SignalData:
    """
    Holds observation data for a specific frequency/signal.
    """
    signal_id: str        # e.g., "1C", "2W"
    snr: float            # dB-Hz
    phase: float          # cycles
    pseudorange: float    # meters
    lock_time: int   
    half_cycle: int
    doppler: Optional[float]

@dataclass
class SatelliteState:
    """
    Represents the state of a single satellite at a specific epoch.
    """
    sys_id: str           # 'G', 'E', 'C', 'R'
    prn: int              # Satellite ID
    
    # Geometric Data (Calculated from Ephemeris)
    azimuth: Optional[float] = None    # Degrees (0-360)
    elevation: Optional[float] = None  # Degrees (-90 to 90)
    sat_pos_ecef: Optional[list] = None # [x, y, z]
    
    # Signal Data: Key is signal_id (e.g., "1C")
    signals: Dict[str, SignalData] = field(default_factory=dict)

@dataclass
class IonosphericCorrection:
    """
    Ionospheric correction data (Slant Total Electron Content - STEC).
    """
    satellite_id: str     # e.g., "G01", "E02"
    stec: float           # Slant Total Electron Content (TECu)
    stec_rate: Optional[float] = None  # Rate of change of STEC (TECu/s)
    signal_id: Optional[str] = None    # e.g., "1C", "1X"
    quality_indicator: int = 0          # Quality indicator (0-15)

@dataclass
class TroposphericCorrection:
    """
    Tropospheric correction data (Hydrostatic + Wet delays).
    """
    ztd_hydro: Optional[float] = None   # Zenith Hydrostatic Delay (m)
    ztd_wet: Optional[float] = None     # Zenith Wet Delay (m)
    ztd_rate_hydro: Optional[float] = None  # Rate of change of hydrostatic delay (m/s)
    ztd_rate_wet: Optional[float] = None    # Rate of change of wet delay (m/s)
    quality_indicator: int = 0          # Quality indicator (0-15)

@dataclass
class SatelliteBiasCorrection:
    """
    Satellite code/phase bias corrections.
    """
    satellite_id: str     # e.g., "G01"
    code_biases: Dict[str, float] = field(default_factory=dict)  # signal_id -> bias (m)
    phase_biases: Dict[str, float] = field(default_factory=dict) # signal_id -> bias (cycles)
    yaw_angle: Optional[float] = None   # Yaw angle (radians)
    yaw_rate: Optional[float] = None    # Yaw rate (radians/s)

@dataclass
class SatelliteClockCorrection:
    """
    Satellite clock and orbit correction parameters.
    """
    satellite_id: str     # e.g., "G01"
    delta_clock: float = 0.0            # Clock correction (m)
    delta_clock_rate: float = 0.0       # Clock correction rate (m/s)
    delta_radial: float = 0.0           # Radial orbit correction (m)
    delta_radial_rate: float = 0.0      # Radial orbit correction rate (m/s)
    delta_along_track: float = 0.0      # Along-track orbit correction (m)
    delta_along_track_rate: float = 0.0 # Along-track orbit correction rate (m/s)
    delta_cross_track: float = 0.0      # Cross-track orbit correction (m)
    delta_cross_track_rate: float = 0.0 # Cross-track orbit correction rate (m/s)

@dataclass
class BroadcastEphemerisCorrections:
    """
    Physical corrections transmitted in broadcast ephemeris messages.
    These are intrinsic to the satellite signal and transmitted via RTCM.
    """
    satellite_id: str     # e.g., "G01"
    TGD: Optional[float] = None         # Total Group Delay (m) - GPS L1-L2/
    TGD1: Optional[float] = None        # BDS L2/B3 TGD (m)
    TGD2: Optional[float] = None        # BDS L1D/L5 TGD (m)
    ISC_L1CA: Optional[float] = None    # Galileo/GPS L1C/A Inter-Signal Correction (m)
    ISC_L1C: Optional[float] = None     # Galileo/GPS L1C Inter-Signal Correction (m)
    ISC_L5I: Optional[float] = None     # Galileo L5 I Inter-Signal Correction (m)
    ISC_L5Q: Optional[float] = None     # Galileo L5 Q Inter-Signal Correction (m)
    BGD_E1E5a: Optional[float] = None   # Galileo E1-E5a Bias Group Delay (m)
    BGD_E1E5b: Optional[float] = None   # Galileo E1-E5b Bias Group Delay (m)
    SISA: Optional[int] = None          # Signal In Space Accuracy (SISA) index - Galileo
    URAI: Optional[int] = None          # User Range Accuracy Index (URAI) - BDS
    SatHealth: Optional[int] = None     # Satellite health indicator
    FitInterval: Optional[int] = None   # Fit interval indicator
    AODE: Optional[int] = None          # Age of Data Ephemeris (BDS)
    AODC: Optional[int] = None          # Age of Data Clock (BDS)

@dataclass
class EpochObservation:
    """
    Container for all data in a single time epoch.
    """
    gps_time: float       # GPS Time of Week (seconds)
    satellites: Dict[str, SatelliteState] = field(default_factory=dict)
    utc_datetime: Optional[datetime] = None  # Absolute UTC time (year, month, day, hour, minute, second)
    
    # Correction parameters
    ionospheric_corrections: Dict[str, IonosphericCorrection] = field(default_factory=dict)  # satellite_id -> correction
    tropospheric_correction: Optional[TroposphericCorrection] = None  # Station-level tropospheric correction
    satellite_bias_corrections: Dict[str, SatelliteBiasCorrection] = field(default_factory=dict)  # satellite_id -> bias correction
    satellite_clock_corrections: Dict[str, SatelliteClockCorrection] = field(default_factory=dict)  # satellite_id -> clock/orbit correction
    broadcast_eph_corrections: Dict[str, BroadcastEphemerisCorrections] = field(default_factory=dict)  # satellite_id -> broadcast corrections
    
    # Time bias corrections
    gps_glonass_time_bias: Optional[float] = None  # GPS-GLONASS time bias (seconds)
    gps_galileo_time_bias: Optional[float] = None  # GPS-Galileo time bias (seconds)
    gps_bds_time_bias: Optional[float] = None      # GPS-BDS time bias (seconds)
