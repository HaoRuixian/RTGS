"""RTGS 全局运行配置。"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

LOGGER = logging.getLogger(__name__)


def _default_positioning_settings() -> dict[str, Any]:
    """
    构造定位解算默认参数。

    Returns:
        新的定位参数字典，调用方可以安全修改。
    """
    return {
        "cutoff_elevation_deg": 10.0,
        "min_satellites": 4,
        "max_pdop": 10.0,
        "ionosphere_option": "IFLC",
        "troposphere_model": "Sastamoinen",
        # 默认让启用的星座都参与 SPP；需要保守 GPS-only 时可在定位设置中开启。
        "gnss_systems": ["G", "R", "E", "C", "J", "I"],
        "prefer_gps_only": False,
        "weight_mode": "elevation",
        "use_smoothing": False,
        "smoothing_window": 10,
        "random_walk": 0.0,
        "uncertain_std_pos": 5.0,
        "fixed_std_pos": 2.5,
    }


@dataclass
class ConnectionSettings:
    """
    连接配置，支持 NTRIP、串口和文件回放数据源。
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
    全局配置容器，集中保存 OBS/EPH 数据流、接收机位置和定位参数。
    """
    # Observation stream settings
    obs_settings: ConnectionSettings = field(default_factory=ConnectionSettings)
    
    # Ephemeris stream settings
    eph_settings: ConnectionSettings = field(default_factory=lambda: ConnectionSettings(enabled=False))
    
    # Receiver approximate position (ECEF coordinates)
    approx_rec_pos: list[float] | None = field(default_factory=lambda: [0, 0, 0])
    
    # GNSS system filters
    target_systems: list[str] = field(default_factory=lambda: ['G', 'R', 'E', 'C', 'J', 'S', 'I'])
    # Positioning related settings (SPP/PPP/RTK parameters)
    positioning_settings: dict[str, Any] = field(default_factory=_default_positioning_settings)

    def get_connection_settings(self, stream_type: str) -> ConnectionSettings:
        """
        获取指定数据流的连接配置。

        Args:
            stream_type: ``OBS`` 表示观测流，``EPH`` 表示星历流。

        Returns:
            指定数据流的连接配置。

        Raises:
            ValueError: 当数据流类型不是 ``OBS`` 或 ``EPH`` 时抛出。
        """
        if stream_type.upper() == 'OBS':
            return self.obs_settings
        if stream_type.upper() == 'EPH':
            return self.eph_settings

        raise ValueError(f"Invalid stream type: {stream_type}. Use 'OBS' or 'EPH'")

    def update_settings(self, stream_type: str, settings: dict[str, Any]) -> None:
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
    
    def update_general_settings(self, settings: dict[str, Any]) -> None:
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
                    except (TypeError, ValueError) as exc:
                        LOGGER.debug("Ignore invalid approx_rec_pos value %r: %s", value, exc)
            else:
                setattr(self, key, value)

    def get_positioning_settings(self) -> dict[str, Any]:
        """Return the positioning settings dictionary."""
        return self.positioning_settings

    def update_positioning_settings(self, settings: dict[str, Any]) -> None:
        """Update positioning-related settings.

        Only keys present in the provided dict will be updated.
        """
        for key, value in settings.items():
            self.positioning_settings[key] = value

    def to_dict(self) -> dict[str, Any]:
        """Convert GlobalConfig to a dictionary suitable for YAML serialization."""
        return {
            'obs_settings': asdict(self.obs_settings),
            'eph_settings': asdict(self.eph_settings),
            'approx_rec_pos': self.approx_rec_pos,
            'target_systems': self.target_systems,
            'positioning_settings': self.positioning_settings,
        }

    def from_dict(self, config_dict: dict[str, Any]) -> None:
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
        except (OSError, yaml.YAMLError) as exc:
            raise IOError(f"Failed to save configuration to {filepath}: {exc}") from exc

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
        except (OSError, yaml.YAMLError, TypeError) as exc:
            raise IOError(f"Failed to load configuration from {filepath}: {exc}") from exc


# Create a singleton instance of GlobalConfig that can be imported and used globally
global_config = GlobalConfig()


def get_global_config() -> GlobalConfig:
    """
    Get the global configuration instance.
    
    Returns:
        GlobalConfig instance
    """
    return global_config


def update_connection_settings(stream_type: str, settings: dict[str, Any]) -> None:
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


def update_general_settings(settings: dict[str, Any]) -> None:
    """
    Convenience function to update general settings like approx_rec_pos and target_systems.
    
    Args:
        settings: Dictionary containing the general settings to update
    """
    global_config.update_general_settings(settings)


def get_positioning_settings() -> dict[str, Any]:
    """Convenience function to get positioning settings."""
    return global_config.get_positioning_settings()


def update_positioning_settings(settings: dict[str, Any]) -> None:
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
