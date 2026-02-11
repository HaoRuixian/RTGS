"""
Global Configuration Module

This module provides a centralized configuration storage for NTRIP and serial connection settings
that can be accessed by all functions throughout the application.
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field


@dataclass
class ConnectionSettings:
    """
    Data class representing connection settings for either NTRIP or serial connection.
    """
    source_type: str = "NTRIP Server"  # "NTRIP Server" or "Serial Port"
    
    # NTRIP settings
    host: str = ""
    port: str = "2101"
    mountpoint: str = ""
    user: str = ""
    password: str = ""
    
    # Serial settings
    serial_port: str = "COM1"
    baudrate: int = 115200
    
    # Common settings
    enabled: bool = True


@dataclass
class GlobalConfig:
    """
    Global configuration container for the entire application.
    Contains both OBS and EPH stream settings.
    """
    # Observation stream settings
    obs_settings: ConnectionSettings = field(default_factory=ConnectionSettings)
    
    # Ephemeris stream settings
    eph_settings: ConnectionSettings = field(default_factory=lambda: ConnectionSettings(enabled=False))
    
    # Receiver approximate position (ECEF coordinates)
    approx_rec_pos: List[float] = field(default_factory=lambda: [0, 0, 0])
    
    # GNSS system filters (G=GPS, R=GLONASS, E=Galileo, C=Beidou)
    target_systems: List[str] = field(default_factory=lambda: ['G', 'R', 'E', 'C'])
    # Positioning related settings (SPP/PPP/RTK parameters)
    positioning_settings: dict = field(default_factory=lambda: {
        'cutoff_elevation_deg': 10.0,
        'weight_mode': 'elevation',  # or 'snr'
        'random_walk': 0.0,
        'smoothing_window': 0
    })
    
    def get_connection_settings(self, stream_type: str) -> ConnectionSettings:
        """
        Get connection settings for specified stream type.
        
        Args:
            stream_type: Either 'OBS' for observation stream or 'EPH' for ephemeris stream
            
        Returns:
            ConnectionSettings object for the specified stream
        """
        if stream_type.upper() == 'OBS':
            return self.obs_settings
        elif stream_type.upper() == 'EPH':
            return self.eph_settings
        else:
            raise ValueError(f"Invalid stream type: {stream_type}. Use 'OBS' or 'EPH'")
    
    def update_settings(self, stream_type: str, settings: Dict[str, Any]) -> None:
        """
        Update settings for specified stream type.
        
        Args:
            stream_type: Either 'OBS' for observation stream or 'EPH' for ephemeris stream
            settings: Dictionary containing the settings to update
        """
        conn_settings = self.get_connection_settings(stream_type.upper())
        
        for key, value in settings.items():
            if hasattr(conn_settings, key):
                setattr(conn_settings, key, value)
    
    def update_general_settings(self, settings: Dict[str, Any]) -> None:
        """
        Update general settings like approx_rec_pos and target_systems.
        
        Args:
            settings: Dictionary containing the general settings to update
        """
        for key, value in settings.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def get_positioning_settings(self) -> Dict[str, Any]:
        """Return the positioning settings dictionary."""
        return self.positioning_settings

    def update_positioning_settings(self, settings: Dict[str, Any]) -> None:
        """Update positioning-related settings.

        Only keys present in the provided dict will be updated.
        """
        for key, value in settings.items():
            self.positioning_settings[key] = value


# Create a singleton instance of GlobalConfig that can be imported and used globally
global_config = GlobalConfig()


def get_global_config() -> GlobalConfig:
    """
    Get the global configuration instance.
    
    Returns:
        GlobalConfig instance
    """
    return global_config


def update_connection_settings(stream_type: str, settings: Dict[str, Any]) -> None:
    """
    Convenience function to update connection settings.
    
    Args:
        stream_type: Either 'OBS' for observation stream or 'EPH' for ephemeris stream
        settings: Dictionary containing the settings to update
    """
    global_config.update_settings(stream_type, settings)


def get_connection_settings(stream_type: str) -> ConnectionSettings:
    """
    Convenience function to get connection settings.
    
    Args:
        stream_type: Either 'OBS' for observation stream or 'EPH' for ephemeris stream
        
    Returns:
        ConnectionSettings object for the specified stream
    """
    return global_config.get_connection_settings(stream_type)


def update_general_settings(settings: Dict[str, Any]) -> None:
    """
    Convenience function to update general settings like approx_rec_pos and target_systems.
    
    Args:
        settings: Dictionary containing the general settings to update
    """
    global_config.update_general_settings(settings)


def get_positioning_settings() -> Dict[str, Any]:
    """Convenience function to get positioning settings."""
    return global_config.get_positioning_settings()


def update_positioning_settings(settings: Dict[str, Any]) -> None:
    """Convenience function to update positioning settings."""
    global_config.update_positioning_settings(settings)