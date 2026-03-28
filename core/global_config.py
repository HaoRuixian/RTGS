"""
Global Configuration Module

This module provides a centralized configuration storage for NTRIP and serial connection settings
that can be accessed by all functions throughout the application.

It supports saving and loading configuration in YAML format.
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict
import yaml
from pathlib import Path


@dataclass
class ConnectionSettings:
    """
    Data class representing connection settings for either NTRIP or serial connection.
    """
    source_type: str = "NTRIP Server"  # "NTRIP Server", "Serial Port", or file mode
    
    # NTRIP settings
    host: str = ""
    port: str = "2101"
    mountpoint: str = ""
    user: str = ""
    password: str = ""
    
    # Serial settings
    serial_port: str = "COM1"
    baudrate: int = 115200
    databits: int = 8  # Data bits: 5, 6, 7, 8
    stopbits: float = 1  # Stop bits: 1, 1.5, 2
    parity: str = "None"  # Parity: None, Even, Odd, Mark, Space
    flowctrl: str = "None"  # Flow control: None, RTS/CTS, XOn/XOff
    
    # Common settings
    enabled: bool = True
    
    # File replay settings
    file_path: str = ""
    replay_speed: float = 1.0
    file_type: str = "Auto Detect"
    final_results_only: bool = False


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
    
    # GNSS system filters
    target_systems: List[str] = field(default_factory=lambda: ['G', 'R', 'E', 'C', 'J', 'S', 'I'])
    # Positioning related settings (SPP/PPP/RTK parameters)
    positioning_settings: dict = field(default_factory=lambda: {
        # Basic parameters
        'cutoff_elevation_deg': 10.0,  # Minimum elevation angle (degrees)
        'min_satellites': 4,
        'max_pdop': 10.0,
        
        # Ionosphere correction
        'ionosphere_option': 'IFLC',  # 'IFLC' (dual-freq IF-LC) or 'SINGLE' (single-freq)
        
        # Troposphere correction
        'troposphere_model': 'Sastamoinen',  # 'None', 'Sastamoinen', 'HMSL'
        
        # GNSS systems used by positioning
        'gnss_systems': ['G', 'R', 'E', 'C', 'J', 'I'],  # GPS, GLONASS, Galileo, BeiDou, QZSS, IRNSS
        
        # Observation weighting
        'weight_mode': 'elevation',  # 'equal', 'elevation', 'snr'
        
        # Smoothing
        'use_smoothing': False,
        'smoothing_window': 10,  # epochs
        'random_walk': 0.0,  # m/sqrt(s)
        
        # Solution status thresholds
        'uncertain_std_pos': 5.0,  # meters
        'fixed_std_pos': 2.5,  # meters
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
        Update general settings like ``approx_rec_pos`` and ``target_systems``.

        ``approx_rec_pos`` may be ``None`` to clear any previously stored
        value.  When providing a non-null value we attempt to coerce it to a
        list of floats for downstream users.

        Args:
            settings: Dictionary containing the general settings to update
        """
        for key, value in settings.items():
            if not hasattr(self, key):
                continue
            if key == 'approx_rec_pos':
                if value is None:
                    setattr(self, key, None)
                else:
                    # try to convert to list of floats
                    try:
                        coords = [float(v) for v in value]
                        setattr(self, key, coords)
                    except Exception:
                        # ignore invalid values and leave existing setting
                        pass
            else:
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

    def to_dict(self) -> Dict[str, Any]:
        """Convert GlobalConfig to a dictionary suitable for YAML serialization."""
        return {
            'obs_settings': {
                'source_type': self.obs_settings.source_type,
                'host': self.obs_settings.host,
                'port': self.obs_settings.port,
                'mountpoint': self.obs_settings.mountpoint,
                'user': self.obs_settings.user,
                'password': self.obs_settings.password,
                'serial_port': self.obs_settings.serial_port,
                'baudrate': self.obs_settings.baudrate,
                'databits': self.obs_settings.databits,
                'stopbits': self.obs_settings.stopbits,
                'parity': self.obs_settings.parity,
                'flowctrl': self.obs_settings.flowctrl,
                'enabled': self.obs_settings.enabled,
                'file_path': self.obs_settings.file_path,
                'replay_speed': self.obs_settings.replay_speed,
                'file_type': self.obs_settings.file_type,
                'final_results_only': self.obs_settings.final_results_only,
            },
            'eph_settings': {
                'source_type': self.eph_settings.source_type,
                'host': self.eph_settings.host,
                'port': self.eph_settings.port,
                'mountpoint': self.eph_settings.mountpoint,
                'user': self.eph_settings.user,
                'password': self.eph_settings.password,
                'serial_port': self.eph_settings.serial_port,
                'baudrate': self.eph_settings.baudrate,
                'databits': self.eph_settings.databits,
                'stopbits': self.eph_settings.stopbits,
                'parity': self.eph_settings.parity,
                'flowctrl': self.eph_settings.flowctrl,
                'enabled': self.eph_settings.enabled,
                'file_path': self.eph_settings.file_path,
                'replay_speed': self.eph_settings.replay_speed,
                'file_type': self.eph_settings.file_type,
                'final_results_only': self.eph_settings.final_results_only,
            },
            'approx_rec_pos': self.approx_rec_pos,
            'target_systems': self.target_systems,
            'positioning_settings': self.positioning_settings,
        }

    def from_dict(self, config_dict: Dict[str, Any]) -> None:
        """Load configuration from a dictionary (typically from YAML)."""
        # Load OBS settings
        if 'obs_settings' in config_dict:
            obs_dict = config_dict['obs_settings']
            for key, value in obs_dict.items():
                if hasattr(self.obs_settings, key):
                    setattr(self.obs_settings, key, value)
        
        # Load EPH settings
        if 'eph_settings' in config_dict:
            eph_dict = config_dict['eph_settings']
            for key, value in eph_dict.items():
                if hasattr(self.eph_settings, key):
                    setattr(self.eph_settings, key, value)
        
        # Load general settings
        if 'approx_rec_pos' in config_dict:
            self.approx_rec_pos = config_dict['approx_rec_pos']
        
        if 'target_systems' in config_dict:
            self.target_systems = config_dict['target_systems']
        
        # Load positioning settings
        if 'positioning_settings' in config_dict:
            self.positioning_settings.update(config_dict['positioning_settings'])

    def save_to_file(self, filepath: str) -> None:
        """Save the current configuration to a YAML file.
        
        Args:
            filepath: Path to save the configuration file
            
        Raises:
            IOError: If file cannot be written
        """
        try:
            config_dict = self.to_dict()
            Path(filepath).parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, 'w', encoding='utf-8') as f:
                yaml.dump(config_dict, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            raise IOError(f"Failed to save configuration to {filepath}: {str(e)}")

    def load_from_file(self, filepath: str) -> None:
        """Load configuration from a YAML file.
        
        Args:
            filepath: Path to the configuration file
            
        Raises:
            IOError: If file cannot be read or is invalid
        """
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                config_dict = yaml.safe_load(f)
            if config_dict:
                self.from_dict(config_dict)
        except Exception as e:
            raise IOError(f"Failed to load configuration from {filepath}: {str(e)}")


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


def save_config_to_file(filepath: str) -> None:
    """Convenience function to save the current configuration to a YAML file.
    
    Args:
        filepath: Path to save the configuration file
        
    Raises:
        IOError: If file cannot be written
    """
    global_config.save_to_file(filepath)


def load_config_from_file(filepath: str) -> None:
    """Convenience function to load configuration from a YAML file.
    
    Args:
        filepath: Path to the configuration file
        
    Raises:
        IOError: If file cannot be read or is invalid
    """
    global_config.load_from_file(filepath)
