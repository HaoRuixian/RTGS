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
        "allow_gps_fallback": False,
        # Do not mix broadcast-only satellites into a solution once SSR
        # orbit/clock corrections are present.
        "require_ssr_corrections": True,
        "weight_mode": "elevation",
        "code_sigma_m": 1.0,
        "system_code_weight_factors": {"R": 5.0},
        # PPP defaults to an SPP bootstrap.  Set this to True only when the
        # receiver's RTCM 1005/1006 station coordinates should be used as the
        # tightly constrained initial position instead.
        "ppp_use_station_apriori": False,
        # Seed PPP from the configured approximate coordinate without applying
        # the tight RTCM-station position constraint.
        "ppp_use_config_initial_position": False,
        # Hard independent mode ignores all externally supplied coordinates in
        # PPP. Configured coordinates remain available only as solution truth.
        "ppp_independent_mode": False,
        "ppp_observation_model": "IFLC",
        "ppp_station_apriori_sigma_m": 0.05,
        "ppp_initial_position_sigma_m": 100.0,
        # Independent PPP uses this weak covariance for its SPP bootstrap;
        # it is intentionally separate from a configured-coordinate prior.
        "ppp_spp_bootstrap_sigma_m": 100.0,
        "ppp_initial_clock_sigma_m": 1000.0,
        "ppp_initial_ambiguity_sigma_m": 1000.0,
        "ppp_initial_ionosphere_sigma_m": 30.0,
        "ppp_ionosphere_process_noise_mps": 0.001,
        "ppp_position_process_noise_mps": 0.0,
        "ppp_trop_process_noise_mps": 5e-5,
        "ppp_estimate_trop_gradients": True,
        "ppp_initial_trop_gradient_sigma_m": 0.01,
        "ppp_trop_gradient_process_noise_mps": 1e-5,
        "ppp_zwd_correlation_time_s": 7 * 86400.0,
        # High-precision observation modelling.  File-backed antenna
        # and ocean-loading corrections remain inactive until their paths and
        # station metadata are configured.
        "ppp_precise_model_enabled": True,
        "ppp_apply_phase_windup": True,
        "ppp_use_ssr_yaw": True,
        "ppp_apply_shapiro_delay": True,
        "ppp_apply_solid_earth_tide": True,
        "ppp_apply_ocean_loading": True,
        "ppp_apply_receiver_antenna": True,
        "ppp_apply_satellite_antenna": True,
        "ppp_antex_file": "",
        "ppp_blq_file": "",
        "ppp_receiver_antenna": "",
        "ppp_station_id": "",
        "ppp_antenna_eccentricity_neu_m": [0.0, 0.0, 0.0],
        "ppp_auto_ssr_apc_reference": True,
        "ppp_ssr_apc_reference": False,
        # Repeat the epoch update from the same prior and remove the
        # largest post-fit outlier until all residuals pass these limits.
        "ppp_postfit_enabled": True,
        "ppp_max_code_postfit_residual_m": 3.0,
        "ppp_max_phase_postfit_residual_m": 0.03,
        # PPP ambiguity resolution requires integer-compatible SSR phase
        # biases (RTCM 1265-1270 or IGS SSR IM026/046/066/086/106/126).
        # It automatically falls back to float PPP when those data are absent.
        "ppp_ar_enabled": True,
        "ppp_ar_systems": ["G", "E", "C", "J"],
        "ppp_ar_min_epochs": 30,
        "ppp_ar_min_satellites": 5,
        "ppp_ar_min_elevation_deg": 10.0,
        "ppp_ar_max_wl_fraction": 0.15,
        "ppp_ar_max_nl_fraction": 0.12,
        "ppp_ar_max_wl_sigma_cycles": 0.20,
        "ppp_ar_max_nl_sigma_cycles": 0.20,
        "ppp_ar_ratio_threshold": 3.0,
        "ppp_ar_constraint_sigma_m": 0.0001,
        "ppp_ar_max_position_shift_m": 0.50,
        "ppp_ar_require_mw_consistency": True,
        # Partial fixes are deliberately disabled by default.  A single bad
        # satellite must not turn a valid float PPP solution into a false fix.
        "ppp_ar_require_full_group": True,
        # Native single-base and network RTK settings.
        "rtk_type": "single_base",
        "rtk_network_protocol": "VRS",
        "rtk_rover_mode": "kinematic",
        "rtk_rover_format": "rtcm3",
        "rtk_base_format": "rtcm3",
        "rtk_frequency": "l1+l2",
        "rtk_dynamics": True,
        "rtk_ar_mode": "fix-and-hold",
        "rtk_glonass_ar_mode": "autocal",
        "rtk_bds_ar": True,
        "rtk_ar_ratio_threshold": 3.0,
        "rtk_ar_lock_count": 5,
        "rtk_ar_min_fix": 10,
        "rtk_ar_outage_count": 5,
        "rtk_max_correction_age_s": 10.0,
        "rtk_cycle_slip_threshold_m": 0.05,
        "rtk_filter_iterations": 1,
        "rtk_base_position_source": "rtcm",
        "rtk_base_position": [0.0, 0.0, 0.0],
        # auto uses configured LLH/receiver ECEF when available, otherwise the
        # rover's single-point solution.  This covers VRS caster GGA requests.
        "rtk_gga_mode": "auto",
        "rtk_gga_position": [0.0, 0.0, 0.0],
        "rtk_gga_cycle_ms": 5000,
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

    # Raw receiver/RTCM format used by the native RTK adapter.
    data_format: str = "RTCM3"


@dataclass
class GlobalConfig:
    """
    全局配置容器，集中保存 OBS/EPH/SSR/BASE 数据流、接收机位置和定位参数。
    """
    # Observation stream settings
    obs_settings: ConnectionSettings = field(default_factory=ConnectionSettings)
    
    # Ephemeris stream settings
    eph_settings: ConnectionSettings = field(default_factory=lambda: ConnectionSettings(enabled=False))

    # SSR correction stream settings
    ssr_settings: ConnectionSettings = field(default_factory=lambda: ConnectionSettings(enabled=False))

    # RTK reference-station or network-correction stream settings
    base_settings: ConnectionSettings = field(default_factory=lambda: ConnectionSettings(enabled=False))
    
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
            stream_type: ``OBS`` 表示观测流，``EPH`` 表示星历流，``SSR`` 表示改正数流，
                ``BASE`` 表示 RTK 基站或网络改正流。

        Returns:
            指定数据流的连接配置。

        Raises:
            ValueError: 当数据流类型不是 ``OBS``、``EPH`` 或 ``SSR`` 时抛出。
        """
        if stream_type.upper() == 'OBS':
            return self.obs_settings
        if stream_type.upper() == 'EPH':
            return self.eph_settings
        if stream_type.upper() == 'SSR':
            return self.ssr_settings
        if stream_type.upper() == 'BASE':
            return self.base_settings

        raise ValueError(f"Invalid stream type: {stream_type}. Use 'OBS', 'EPH', 'SSR', or 'BASE'")

    def update_settings(self, stream_type: str, settings: dict[str, Any]) -> None:
        """
        Update settings for specified stream type.
        
        Args:
            stream_type: 'OBS' for observations, 'EPH' for broadcast ephemeris, or 'SSR' for corrections
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
            'ssr_settings': asdict(self.ssr_settings),
            'base_settings': asdict(self.base_settings),
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

        # Load SSR settings
        if 'ssr_settings' in config_dict:
            ssr_dict = config_dict['ssr_settings']
            for key, value in ssr_dict.items():
                if hasattr(self.ssr_settings, key):
                    setattr(self.ssr_settings, key, value)

        # Load RTK base/network correction settings
        if 'base_settings' in config_dict:
            base_dict = config_dict['base_settings']
            for key, value in base_dict.items():
                if hasattr(self.base_settings, key):
                    setattr(self.base_settings, key, value)
        
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
        stream_type: 'OBS' for observations, 'EPH' for broadcast ephemeris, or 'SSR' for corrections
        settings: Dictionary containing the settings to update
    """
    global_config.update_settings(stream_type, settings)


def get_connection_settings(stream_type: str) -> ConnectionSettings:
    """
    Convenience function to get connection settings.
    
    Args:
        stream_type: 'OBS' for observations, 'EPH' for broadcast ephemeris, or 'SSR' for corrections
        
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
